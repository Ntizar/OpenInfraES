#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_web.py — «Pregunta a los datos» de OpenInfraES con Qwen 3.6 (NaN).

Un chat que no inventa: el modelo NO calcula. Elige una de las 12 herramientas del
MCP federado (`mcp_openinfra.py`), la ejecuta aquí dentro, y redacta con lo que
devuelve. Las cifras, los porcentajes y los avisos de caducidad salen de las
herramientas; el modelo solo decide qué preguntar y cómo contarlo.

Modos:

    python scripts/chat_web.py                 # http://127.0.0.1:8080
    python scripts/chat_web.py --puerto 9000
    python scripts/chat_web.py --probar        # 3 preguntas end-to-end, sin navegador

La clave del modelo NUNCA sale al navegador: la pone este proceso, que hace de
proxy. El navegador solo habla con /chat.

Variables de entorno (todas opcionales, con valor por defecto):
    OPENINFRA_LLM_URL    http://127.0.0.1:4000/v1   (gateway LiteLLM de Hermes)
    OPENINFRA_LLM_KEY    se lee de .env: LITELLM_MASTER_KEY o NAN_API_KEY
    OPENINFRA_MODEL      qwen3.6
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_openinfra as mcp  # noqa: E402  (el MCP federado, en el mismo directorio)

VERSION = "1.0.0"
MODELO = os.environ.get("OPENINFRA_MODEL", "qwen3.6")
URL_LLM = os.environ.get("OPENINFRA_LLM_URL", "http://127.0.0.1:4000/v1").rstrip("/")
MAX_SALTOS = 4          # llamadas al modelo por pregunta como máximo
MAX_ENTRADA = 1200      # caracteres de la pregunta
MAX_TOOL_CHARS = 6000   # recorte del structuredData que se le devuelve al modelo
TIMEOUT_LLM = 50

SISTEMA = """Eres el asistente de OpenInfraES, una federación de datos abiertos de \
infraestructura de España (energía, agua, red eléctrica, gas, transporte, clima y territorio).

Reglas, sin excepciones:
1. NUNCA inventes una cifra. Si la respuesta exige un dato, llama a una herramienta.
2. Si la herramienta devuelve un AVISO de caducidad, dilo en la respuesta con su fecha.
3. Cita las entidades concretas (estación, planta, embalse, municipio, tramo) y sus unidades.
4. Distingue potencia INSTALADA de energía generada, y precio mayorista de precio final.
5. Si te preguntan algo que no está en las herramientas, dilo y ofrece la pregunta que sí puedes responder.
6. Responde en castellano, en 3-6 frases, con las cifras delante. Sin relleno y sin disculpas.
7. Si el dato está caducado o falta, un hueco declarado vale más que un número plausible.
8. No mezcles magnitudes: MW instantáneos no son porcentaje del día ni MWh. Si das un porcentaje,
   di de qué periodo sale; si das potencia, di que es potencia."""


# --------------------------------------------------------------------------
# Clave y llamada al modelo
# --------------------------------------------------------------------------


def leer_clave() -> str:
    if os.environ.get("OPENINFRA_LLM_KEY"):
        return os.environ["OPENINFRA_LLM_KEY"]
    orden = ("LITELLM_MASTER_KEY", "NAN_API_KEY", "OPENAI_API_KEY")
    for nombre in orden:
        if os.environ.get(nombre):
            return os.environ[nombre]
    # OJO: dentro de un .env puede haber varias claves y la primera que aparece no es
    # la que sirve (un OPENAI_API_KEY viejo gana al maestro y el gateway responde
    # «No connected db» en vez de 401). Se recogen todas y manda la prioridad.
    halladas: dict[str, str] = {}
    for ruta in (Path.home() / ".hermes" / ".env",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env",
                 RAIZ / ".env"):
        if not ruta.exists():
            continue
        for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in linea or linea.strip().startswith("#"):
                continue
            k, _, v = linea.partition("=")
            v = v.strip().strip('"').strip("'")
            if k.strip() in orden and v and k.strip() not in halladas:
                halladas[k.strip()] = v   # una línea vacía por encima de la buena no gana
    for nombre in orden:
        if nombre in halladas:
            return halladas[nombre]
    return ""


CLAVE = leer_clave()


# Los nombres MCP llevan puntos (es.agua.embalses) y la API de funciones solo admite
# [a-zA-Z0-9_-]: se traducen en los dos sentidos y el modelo ve nombres limpios.
def nombre_api(mcp_name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", mcp_name)


HERRAMIENTAS_API = []
MAPA_NOMBRES = {}
for h in mcp.HERRAMIENTAS:
    api = nombre_api(h["name"])
    MAPA_NOMBRES[api] = h["name"]
    HERRAMIENTAS_API.append({
        "type": "function",
        "function": {"name": api, "description": h["description"], "parameters": h["inputSchema"]},
    })


def llamar_modelo(mensajes: list, con_herramientas: bool = True,
                  forzar_herramienta: bool = False, max_tokens: int = 1600) -> dict:
    cuerpo = {
        "model": MODELO,
        "messages": mensajes,
        "temperature": 0.15,
        "max_tokens": max_tokens,
        # qwen3.6 es un modelo pensante: sin este interruptor gasta el presupuesto en el
        # razonamiento y devuelve content vacío con finish_reason="length" (medido: 1.552
        # tokens de razonamiento y cero respuesta). Medido sobre 3 preguntas difíciles:
        #   reasoning_effort=low .......... 2/3 aciertos (hasta 20 s)
        #   enable_thinking=false ......... 2/3 aciertos (~0,8 s)
        #   enable_thinking=false+required  3/3 (~0,7 s)  ← esta
        #   low + off + required .......... 1/3 (se estorban)
        "extra_body": {"enable_thinking": False},
    }
    if con_herramientas:
        cuerpo["tools"] = HERRAMIENTAS_API
        cuerpo["tool_choice"] = "required" if forzar_herramienta else "auto"
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    pet = urllib.request.Request(
        URL_LLM + "/chat/completions", data=datos,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {CLAVE}"},
    )
    with urllib.request.urlopen(pet, timeout=TIMEOUT_LLM) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ejecutar_herramienta(nombre_api: str, argumentos: dict) -> tuple[dict, int, str]:
    """Ejecuta una herramienta del MCP y devuelve (resultado, ms, resumen legible)."""
    real = MAPA_NOMBRES.get(nombre_api)
    if real is None:
        return {"content": [{"type": "text", "text": f"Herramienta desconocida: {nombre_api}"}],
                "isError": True}, 0, f"{nombre_api} (no existe)"
    t0 = time.time()
    try:
        res = mcp.POR_NOMBRE[real]["fn"](argumentos or {})
    except Exception as exc:  # noqa: BLE001
        res = mcp.error(real, f"Fallo al ejecutar: {exc}")
    return res, int((time.time() - t0) * 1000), real


def texto_para_el_modelo(res: dict) -> str:
    """Lo que se le devuelve al modelo: el texto y el dato, recortado y marcado."""
    partes = [(res.get("content") or [{}])[0].get("text", "")]
    sd = res.get("structuredData")
    if sd is not None:
        crudo = json.dumps(sd, ensure_ascii=False)
        if len(crudo) > MAX_TOOL_CHARS:
            crudo = crudo[:MAX_TOOL_CHARS] + f"… [recortado: {len(crudo)} caracteres en total]"
        partes.append("DATOS: " + crudo)
    meta = res.get("meta") or {}
    if meta.get("aviso"):
        partes.append("AVISO: " + "; ".join(meta["aviso"]))
    if res.get("isError"):
        partes.append("(la herramienta ha fallado: dilo en la respuesta)")
    return "\n".join(p for p in partes if p)


# --------------------------------------------------------------------------
# Un turno de conversación
# --------------------------------------------------------------------------


_SALUDOS = re.compile(r"^\s*(hola|buenas|hey|qué tal|que tal|gracias|adiós|adios|"
                      r"quién eres|quien eres|qué puedes hacer|que puedes hacer)\b", re.I)


def _es_saludo(texto: str) -> bool:
    """Para un «hola» no se fuerza ninguna herramienta: no hay dato que buscar."""
    return bool(_SALUDOS.match(texto or "")) and len(texto or "") < 90


def responder(mensajes_usuario: list) -> dict:
    t0 = time.time()
    mensajes = [{"role": "system", "content": SISTEMA}] + mensajes_usuario
    trazas: list[dict] = []
    citados: list[str] = []
    avisos: list[str] = []
    uso = {"prompt_tokens": 0, "completion_tokens": 0}
    respuesta_texto = ""

    for salto in range(MAX_SALTOS):
        llm = llamar_modelo(mensajes, con_herramientas=(salto < MAX_SALTOS - 1))
        # Caso medido: qwen3.6 a veces contesta de memoria sin abrir ninguna herramienta
        # (o se queda en blanco). Se le obliga a usar una y se reintenta una sola vez.
        primera = (llm.get("choices") or [{}])[0].get("message") or {}
        if salto == 0 and not primera.get("tool_calls") and not _es_saludo(mensajes[-1]["content"]):
            u0 = llm.get("usage") or {}
            uso["prompt_tokens"] += u0.get("prompt_tokens") or 0
            uso["completion_tokens"] += u0.get("completion_tokens") or 0
            llm = llamar_modelo(mensajes, forzar_herramienta=True, max_tokens=1600)
        u = llm.get("usage") or {}
        uso["prompt_tokens"] += u.get("prompt_tokens") or 0
        uso["completion_tokens"] += u.get("completion_tokens") or 0
        msg = (llm.get("choices") or [{}])[0].get("message") or {}
        llamadas = msg.get("tool_calls") or []
        fin = (llm.get("choices") or [{}])[0].get("finish_reason")
        if not llamadas:
            respuesta_texto = (msg.get("content") or "").strip()
            # qwen razona antes de contestar: con presupuesto corto gasta los tokens en el
            # razonamiento y devuelve contenido vacío con finish_reason = length.
            if not respuesta_texto and fin == "length":
                mensajes.append({"role": "user",
                                 "content": "Resume en tres frases, con las cifras, lo que "
                                            "devolvieron las herramientas. No vuelvas a llamarlas."})
                llm2 = llamar_modelo(mensajes, con_herramientas=False)
                u2 = llm2.get("usage") or {}
                uso["prompt_tokens"] += u2.get("prompt_tokens") or 0
                uso["completion_tokens"] += u2.get("completion_tokens") or 0
                respuesta_texto = ((llm2.get("choices") or [{}])[0]
                                   .get("message", {}).get("content") or "").strip()
            if not respuesta_texto and trazas:
                # último recurso honesto: la herramienta ya trae el dato en texto
                respuesta_texto = ("El modelo no ha redactado la respuesta, pero la herramienta "
                                   "devuelve esto:\n\n" + trazas[-1]["resumen"])
            break
        mensajes.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": llamadas})
        for llamada in llamadas:
            fn = llamada.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            res, ms, real = ejecutar_herramienta(fn.get("name"), args)
            citados += (res.get("meta") or {}).get("citedIds") or []
            avisos += (res.get("meta") or {}).get("aviso") or []
            trazas.append({
                "herramienta": real,
                "argumentos": args,
                "ms": ms,
                "resumen": (res.get("content") or [{}])[0].get("text", "")[:220],
                "error": bool(res.get("isError")),
            })
            mensajes.append({"role": "tool", "tool_call_id": llamada.get("id"),
                             "name": fn.get("name"), "content": texto_para_el_modelo(res)})
    else:
        respuesta_texto = ("No he podido cerrar la respuesta con las herramientas disponibles "
                           "en el número de pasos permitido. Reformula la pregunta concretando "
                           "el municipio, la demarcación o la tecnología.")

    return {
        "answer": respuesta_texto or "No he obtenido respuesta del modelo.",
        "traza": trazas,
        "citados": list(dict.fromkeys(citados))[:12],
        "avisos": list(dict.fromkeys(avisos))[:5],
        "uso": uso,
        "modelo": MODELO,
        "latenciaMs": int((time.time() - t0) * 1000),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

_CUENTA: dict[str, list[float]] = defaultdict(list)
LIMITE_POR_MINUTO = 20


def permitido(ip: str) -> bool:
    ahora = time.time()
    _CUENTA[ip] = [t for t in _CUENTA[ip] if ahora - t < 60]
    if len(_CUENTA[ip]) >= LIMITE_POR_MINUTO:
        return False
    _CUENTA[ip].append(ahora)
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, formato, *a):
        pass

    def _enviar(self, codigo: int, cuerpo: str, tipo: str = "application/json; charset=utf-8"):
        datos = cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _json(self, codigo: int, obj: dict):
        self._enviar(codigo, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        ruta = self.path.split("?")[0].rstrip("/") or "/"
        if ruta == "/":
            self._enviar(200, PAGINA, "text/html; charset=utf-8")
        elif ruta == "/salud":
            self._json(200, {"status": "ok", "modelo": MODELO, "herramientas": len(HERRAMIENTAS_API),
                             "clave": bool(CLAVE), "llm": URL_LLM})
        elif ruta == "/tools":
            self._json(200, {"herramientas": [h["name"] for h in mcp.HERRAMIENTAS]})
        else:
            self._json(404, {"error": "no existe"})

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/chat":
            self._json(404, {"error": "usa POST /chat"})
            return
        ip = self.client_address[0]
        if not permitido(ip):
            self._json(429, {"error": "demasiadas preguntas seguidas: espera un minuto"})
            return
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > 64_000:
            self._json(413, {"error": "pregunta demasiado larga"})
            return
        try:
            cuerpo = json.loads(self.rfile.read(largo).decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "JSON ilegible"})
            return
        mensajes = cuerpo.get("messages") or []
        if not isinstance(mensajes, list) or not mensajes:
            self._json(400, {"error": "falta messages"})
            return
        # solo roles válidos y sin system del cliente (lo pone el servidor)
        limpios = [{"role": m.get("role"), "content": str(m.get("content"))[:4000]}
                   for m in mensajes[-10:] if m.get("role") in ("user", "assistant")]
        if not limpios or limpios[-1]["role"] != "user":
            self._json(400, {"error": "el último mensaje debe ser del usuario"})
            return
        if len(limpios[-1]["content"]) > MAX_ENTRADA:
            self._json(400, {"error": f"la pregunta pasa de {MAX_ENTRADA} caracteres"})
            return
        if not CLAVE:
            self._json(500, {"error": "no hay clave del modelo: define LITELLM_MASTER_KEY o NAN_API_KEY"})
            return
        try:
            self._json(200, responder(limpios))
        except urllib.error.HTTPError as exc:
            detalle = exc.read().decode("utf-8", "replace")[:300]
            self._json(502, {"error": f"el modelo respondió {exc.code}", "detalle": detalle})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"fallo interno: {exc}"})


PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenInfraES · Pregunta a los datos</title>
<style>
  :root{
    --fondo:#05080d; --panel:rgba(8,13,21,.9); --panel-solido:#0a1119;
    --borde:rgba(125,155,180,.16); --borde-fuerte:rgba(34,211,238,.45);
    --tinta:#e8f2f9; --suave:#93a9bd; --tenue:#63788c;
    --cian:#22d3ee; --ambar:#fbbf24;
    --mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:
      radial-gradient(900px 500px at 15% -10%, rgba(34,211,238,.10), transparent 60%),
      radial-gradient(700px 400px at 100% 0%, rgba(251,191,36,.06), transparent 55%),
      var(--fondo);
    color:var(--tinta);font-family:"Segoe UI",Inter,system-ui,Arial,sans-serif;
    min-height:100vh;display:flex;flex-direction:column}
  header{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
    padding:14px 18px;border-bottom:1px solid var(--borde);background:var(--panel);backdrop-filter:blur(8px)}
  header h1{font-size:14.5px;margin:0;letter-spacing:.06em;font-family:var(--mono);text-transform:uppercase}
  header h1 b{color:var(--cian);font-weight:600}
  .chip{font-family:var(--mono);font-size:10.6px;color:var(--suave);border:1px solid var(--borde);
    border-radius:2px;padding:3px 7px;letter-spacing:.04em}
  .chip.on{color:var(--cian);border-color:var(--borde-fuerte)}
  main{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:14px;
    max-width:900px;width:100%;margin:0 auto}
  .turno{display:flex;gap:10px;align-items:flex-start}
  .turno.user{flex-direction:row-reverse}
  .globo{max-width:min(100%,640px);padding:11px 14px;border-radius:4px;font-size:14px;line-height:1.55;
    border:1px solid var(--borde);background:var(--panel-solido);white-space:pre-wrap}
  .turno.user .globo{background:rgba(34,211,238,.09);border-color:var(--borde-fuerte)}
  .quien{font-family:var(--mono);font-size:9.5px;color:var(--tenue);letter-spacing:.08em;
    text-transform:uppercase;padding-top:4px;min-width:52px}
  .traza{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
  .tool{font-family:var(--mono);font-size:10.4px;color:var(--suave);border:1px solid var(--borde);
    border-radius:2px;padding:2px 6px;background:rgba(34,211,238,.05)}
  .tool b{color:var(--cian);font-weight:500}
  .tool.mal{border-color:rgba(248,113,113,.5);color:#fca5a5}
  .pie{font-family:var(--mono);font-size:10.2px;color:var(--suave);margin-top:7px;letter-spacing:.03em}
  .aviso{font-family:var(--mono);font-size:10.4px;color:var(--ambar);margin-top:6px}
  footer{padding:12px 18px 16px;border-top:1px solid var(--borde);background:var(--panel)}
  .barra{max-width:900px;margin:0 auto;display:flex;gap:8px}
  input{flex:1;background:var(--panel-solido);border:1px solid var(--borde);color:var(--tinta);
    border-radius:3px;padding:11px 13px;font-size:14px;font-family:inherit;outline:none}
  input:focus{border-color:var(--borde-fuerte)}
  button{background:rgba(34,211,238,.12);border:1px solid var(--borde-fuerte);color:var(--cian);
    border-radius:3px;padding:11px 18px;font-family:var(--mono);font-size:11px;letter-spacing:.08em;
    text-transform:uppercase;cursor:pointer}
  button:disabled{opacity:.45;cursor:default}
  .sugerencias{max-width:900px;margin:10px auto 0;display:flex;gap:6px;flex-wrap:wrap}
  .sugerencias button{background:transparent;border-color:var(--borde);color:var(--suave);
    font-size:10.2px;padding:5px 9px;text-transform:none;letter-spacing:0}
  .nota{max-width:900px;margin:8px auto 0;font-family:var(--mono);font-size:10.2px;color:var(--suave);line-height:1.5}
  .pensando .globo::after{content:"▍";animation:parp 1s steps(2) infinite;color:var(--cian)}
  @keyframes parp{50%{opacity:0}}
  @media(max-width:560px){.quien{display:none}.globo{max-width:100%}}
</style></head><body>
<header>
  <h1>OpenInfra<b>ES</b> · pregunta a los datos</h1>
  <span class="chip on" id="modelo">…</span>
  <span class="chip" id="herramientas">…</span>
  <span class="chip">las cifras las calculan las herramientas</span>
</header>
<main id="hilo">
  <div class="turno"><div class="quien">Sistema</div><div class="globo">Pregunta por la demanda
eléctrica, el agua embalsada, los precios del mercado diario, la red de 220/400 kV, las plantas de
generación, los avisos de AEMET o cualquier municipio. Cada respuesta se construye con las 12
herramientas del MCP federado y dice de dónde sale el dato y qué edad tiene.</div></div>
</main>
<footer>
  <div class="barra">
    <input id="texto" placeholder="¿Cuánta agua hay embalsada en el Segura? ¿Y qué planta genera más en Zamora?" autocomplete="off">
    <button id="enviar">Preguntar</button>
  </div>
  <div class="sugerencias" id="sugerencias"></div>
  <div class="nota">El modelo no calcula: elige herramienta y redacta. Si un dato está caducado, lo dice.
Precio mayorista ≠ precio final; potencia instalada ≠ energía generada.</div>
</footer>
<script>
const hilo=document.getElementById('hilo'),texto=document.getElementById('texto'),
      enviar=document.getElementById('enviar'),sugerencias=document.getElementById('sugerencias');
const historia=[];
const SUGERENCIAS=[
  '¿Cuánta agua hay embalsada en la demarcación del Segura y cuáles están más vacíos?',
  '¿Cómo está la demanda eléctrica ahora y cuánto está aportando la solar?',
  '¿A cuánto está el precio de la luz hoy y cuál es la hora más cara?',
  '¿Qué plantas de generación y qué alta tensión hay en Zamora?',
];
SUGERENCIAS.forEach(t=>{const b=document.createElement('button');b.textContent=t;
  b.onclick=()=>{texto.value=t;texto.focus()};sugerencias.appendChild(b)});

function burbuja(quien,clase){const d=document.createElement('div');d.className='turno '+clase;
  const q=document.createElement('div');q.className='quien';q.textContent=quien;
  const g=document.createElement('div');g.className='globo';d.append(q,g);hilo.appendChild(d);
  hilo.scrollTop=hilo.scrollHeight;return g}

async function preguntar(){
  const t=texto.value.trim(); if(!t) return;
  texto.value=''; enviar.disabled=true;
  burbuja('Tú','user').textContent=t;
  historia.push({role:'user',content:t});
  const globo=burbuja('OpenInfraES','asistente pensando'); globo.textContent='consultando las herramientas…';
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({messages:historia})});
    const d=await r.json();
    globo.parentElement.classList.remove('pensando');
    if(!r.ok){ globo.textContent='No he podido responder: '+(d.error||r.status)+'.'; return; }
    globo.textContent=d.answer;
    if(d.traza&&d.traza.length){
      const tr=document.createElement('div');tr.className='traza';
      d.traza.forEach(x=>{const s=document.createElement('span');
        s.className='tool'+(x.error?' mal':'');
        s.innerHTML='<b>'+x.herramienta+'</b> · '+JSON.stringify(x.argumentos)+' · '+x.ms+' ms';
        s.title=x.resumen; tr.appendChild(s)});
      globo.appendChild(tr);
    }
    if(d.avisos&&d.avisos.length){const a=document.createElement('div');a.className='aviso';
      a.textContent='AVISO · '+d.avisos.join(' · ');globo.appendChild(a)}
    const pie=document.createElement('div');pie.className='pie';
    pie.textContent=(d.modelo||'')+' · '+(d.uso.prompt_tokens+d.uso.completion_tokens)+' tokens · '
      +(d.latenciaMs/1000).toFixed(1)+' s'+(d.citados.length?' · citados: '+d.citados.slice(0,6).join(', '):'');
    globo.appendChild(pie);
    historia.push({role:'assistant',content:d.answer});
  }catch(e){ globo.textContent='Fallo de red: '+e.message; }
  finally{ enviar.disabled=false; texto.focus(); hilo.scrollTop=hilo.scrollHeight; }
}
enviar.onclick=preguntar;
texto.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();preguntar()}});
fetch('/salud').then(r=>r.json()).then(d=>{
  document.getElementById('modelo').textContent=d.modelo;
  document.getElementById('herramientas').textContent=d.herramientas+' herramientas';
});
</script></body></html>
"""


# --------------------------------------------------------------------------
# Prueba end-to-end sin navegador
# --------------------------------------------------------------------------

PREGUNTAS = [
    "¿Cuánta agua hay embalsada en la demarcación del Segura? ¿Cuáles están más vacíos?",
    "¿Cómo va la demanda eléctrica ahora y cuánto aporta la solar?",
    "¿A cuánto está el precio de la luz hoy y cuál es la hora más cara?",
]


def probar() -> int:
    print(f"== chat_web {VERSION} · modelo {MODELO} · {len(HERRAMIENTAS_API)} herramientas ==")
    if not CLAVE:
        print("FALLO: sin clave del modelo")
        return 1
    fallos = 0
    for p in PREGUNTAS:
        print("\n—", p)
        try:
            d = responder([{"role": "user", "content": p}])
        except Exception as exc:  # noqa: BLE001
            print("  FALLO:", exc)
            fallos += 1
            continue
        if not d["traza"]:
            print("  AVISO: no llamó ninguna herramienta")
        for t in d["traza"]:
            print(f"  · {t['herramienta']}{json.dumps(t['argumentos'], ensure_ascii=False)} {t['ms']} ms")
        print("  →", d["answer"][:400])
        print(f"  [{d['uso']['prompt_tokens']}+{d['uso']['completion_tokens']} tokens · {d['latenciaMs']} ms]")
        if not d["answer"] or len(d["answer"]) < 25:
            print("  FALLO: respuesta vacía o de relleno")
            fallos += 1
    print(f"\n{'VERDE' if not fallos else 'FALLO'}: {len(PREGUNTAS) - fallos}/{len(PREGUNTAS)} preguntas")
    return 0 if not fallos else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Chat web de OpenInfraES sobre Qwen (NaN)")
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--probar", action="store_true", help="3 preguntas end-to-end sin navegador")
    args = ap.parse_args()
    if args.probar:
        return probar()
    if not CLAVE:
        print("AVISO: no he encontrado clave del modelo (LITELLM_MASTER_KEY / NAN_API_KEY).", file=sys.stderr)
    print(f"[chat] http://127.0.0.1:{args.puerto}  ·  modelo {MODELO}  ·  "
          f"{len(HERRAMIENTAS_API)} herramientas  ·  llm {URL_LLM}", file=sys.stderr, flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.puerto), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
