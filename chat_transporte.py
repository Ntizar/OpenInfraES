"""Puerta de chat de OpenInfraES: convierte lenguaje natural en órdenes para el mapa.

La clave del modelo vive SOLO aquí (variable de entorno del contenedor). El navegador nunca la ve:
manda la pregunta a /api/chat y recibe una orden ya resuelta.

Regla de diseño: el modelo NO decide coordenadas. Devuelve una intención y un texto; el lugar se
busca en el índice real de paradas y ciudades (`busqueda.json`). Así una alucinación del modelo no
puede llevar el mapa a un punto inventado.
"""
import json
import os
import re
import urllib.request

API = os.environ.get("NAN_API_URL", "https://api.nan.builders/v1/chat/completions")
MODELO = os.environ.get("NAN_MODELO", "qwen3.6")

SISTEMA = """Eres el asistente de un visor del transporte público de España (GTFS del NAP).

Responde SIEMPRE con un único objeto JSON, sin texto alrededor y sin bloques de código:
{"accion":"ir|ruta|cerca|capas|responder","lugar":"","texto":"","capas":[]}

Reglas:
- "ir": el usuario quiere ir a un sitio o verlo en el mapa. Rellena "lugar" con el nombre tal cual
  (ciudad, estación, aeropuerto, calle). No inventes coordenadas.
- "ruta": quiere cómo llegar desde donde está. Rellena "lugar" con el destino.
- "cerca": pregunta qué hay alrededor o qué paradas tiene cerca. "lugar" vacío.
- "capas": pide ver u ocultar un modo. "capas" lleva los que hay que ACTIVAR, en minúsculas, de
  esta lista: autobus, tren, metro, tram, avion, maritimo. Si pide ocultar, "texto" lo dice.
- "responder": cualquier otra pregunta. "texto" con la respuesta, breve y en castellano.
- "texto" es siempre una frase corta para mostrar al usuario, en castellano y sin markdown."""


def _limpia_json(txt):
    """El modelo a veces envuelve el JSON en ```json ... ```."""
    txt = (txt or "").strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def interpreta(pregunta, ctx=""):
    """Devuelve el dict de intención. Lanza RuntimeError si falta la clave."""
    clave = os.environ.get("NAN_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not clave:
        raise RuntimeError("falta NAN_API_KEY en el entorno del contenedor")
    cuerpo = {
        "model": MODELO,
        "reasoning_effort": "minimal",
        "temperature": 0.1,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": SISTEMA + (("\n\nContexto: " + ctx) if ctx else "")},
            {"role": "user", "content": pregunta},
        ],
    }
    req = urllib.request.Request(
        API, data=json.dumps(cuerpo).encode(),
        headers={"Authorization": "Bearer " + clave, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        datos = json.load(r)
    contenido = datos["choices"][0]["message"].get("content", "")
    intencion = _limpia_json(contenido)
    if not intencion or "accion" not in intencion:
        return {"accion": "responder", "texto": "No te he entendido. Prueba con «llévame a Atocha»."}
    intencion.setdefault("texto", "")
    intencion.setdefault("lugar", "")
    intencion.setdefault("capas", [])
    return intencion


# --- búsqueda del lugar en el índice real ---
def _normaliza(s):
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def busca_lugar(indice, texto, limite=5):
    """Puntúa por coincidencia de palabras sobre [nombre, lat, lon, tipo]."""
    objetivo = _normaliza(texto)
    if not objetivo:
        return []
    palabras = [p for p in objetivo.split() if len(p) > 2]
    if not palabras:
        palabras = objetivo.split()
    mejores = []
    for it in indice:
        nombre = _normaliza(it[0])
        if not nombre:
            continue
        puntos = 0
        if nombre == objetivo:
            puntos += 100
        for p in palabras:
            if p in nombre:
                puntos += 10 if nombre.startswith(p) else 4
        if nombre.startswith(objetivo):
            puntos += 30
        if puntos:
            mejores.append((puntos, it))
    mejores.sort(key=lambda x: -x[0])
    return [{"nombre": m[1][0], "lat": m[1][1], "lon": m[1][2], "tipo": m[1][3]}
            for m in mejores[:limite]]
