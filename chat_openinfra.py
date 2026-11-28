# -*- coding: utf-8 -*-
"""chat_openinfra.py — el asistente del visor completo de OpenInfraES.

Convierte una frase en castellano en **acciones que el mapa sabe ejecutar** y en una respuesta
con cifras sacadas de los ficheros, no del modelo.

Reparto de responsabilidades (la regla que evita las alucinaciones):

  1. **Reglas deterministas** (`intencion_local`). Las frases con forma fija —«km 10 de la A-2»,
     «llévame a Bilbao», «mezcla renta con hidráulica»— se resuelven aquí, sin modelo y sin red.
     Es el 80 % del uso real y cuesta 0 tokens.
  2. **Modelo** (`interpreta_llm`) solo cuando las reglas no reconocen la frase. Devuelve un verbo
     y una entidad; **nunca coordenadas ni cifras**.
  3. **Resolución** (`resolver`) busca la entidad en el índice real (8.128 municipios, 3.222
     estaciones del NAP, 5.797 plantas, 1.977 cámaras) y calcula con los datos. Si no la
     encuentra, lo dice: no se inventa un punto.

Acciones que entiende el visor:
  volar {centro:[lon,lat], zoom}
  capa {id, visible}
  filtrar {id, campo, op, valor}
  mezclar {coropleta:{id, campo, valor_de, dominio, paleta}, puntos:{id, tamano_por}}
  ficha {titulo, html}

    python3 chat_openinfra.py --probar              # 16 frases sin modelo
    python3 chat_openinfra.py "km 10 de la a2 foto" # una frase
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(RAIZ, "datos")

API = os.environ.get("NAN_API_URL", "https://api.nan.builders/v1/chat/completions")
MODELO = os.environ.get("NAN_MODELO", "qwen3.6")

SISTEMA = """Eres el asistente de OpenInfraES, un visor de infraestructura de España.

Responde SIEMPRE con un único objeto JSON, sin texto alrededor:
{"verbo":"volar|encender|filtrar|mezclar|foto|responder","entidad":"","campo":"","valor":"","texto":""}

- "volar": ir a un lugar. "entidad" = municipio, estación o instalación, tal cual suena.
- "encender": activar una capa. "entidad" = nombre de la capa como la diría un humano.
- "filtrar": subconjunto de una capa. "campo" y "valor".
- "mezclar": cruzar dos capas por municipio. "campo" = campo numérico de la coropleta.
- "foto": cámara de tráfico. "entidad" = «A-2 km 10».
- "responder": todo lo demás. "texto" breve, en castellano, sin markdown.
No inventes coordenadas ni cifras: si no lo sabes, usa "responder" y dilo."""

# Palabras que no son entidad. Sin esto, «llévame a Bilbao» busca el municipio «llévame a bilbao».
STOP = set("""llevame ir vamos ve ver ensename muestrame muestra abre dame pon activa enciende quiero
necesito dime dame saber dime donde esta estan hay las los la el de del en al a con que cual cuales
cuanto cuanta cuantos cuantas mas menos foto tiempo real por favor un una unos
unas y o el la los mapa visor capa capas""".split())

TECNOLOGIAS = {
    "nuclear": ("nuclear",), "nucleares": ("nuclear",),
    "eolica": ("wind",), "eolicas": ("wind",), "eolicos": ("wind",), "viento": ("wind",),
    "solar": ("solar_pv", "solar_thermal"), "solares": ("solar_pv", "solar_thermal"),
    "fotovoltaica": ("solar_pv",), "termosolar": ("solar_thermal",),
    "hidraulica": ("hydro", "pumped_hydro"), "hidraulicas": ("hydro", "pumped_hydro"),
    "hidroelectrica": ("hydro", "pumped_hydro"), "hidroelectricas": ("hydro", "pumped_hydro"),
    "hidro": ("hydro", "pumped_hydro"), "bombeo": ("pumped_hydro",),
    "gas": ("ccgt", "fuel_gas"), "ciclo": ("ccgt",), "carbon": ("coal",),
    "cogeneracion": ("cogeneration",), "biomasa": ("cogeneration",),
}

_CACHE: dict[str, object] = {}


# ------------------------------------------------------------------ carga
def _carga(nombre):
    if nombre in _CACHE:
        return _CACHE[nombre]
    d = None
    try:
        with open(os.path.join(DATOS, nombre), encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = None
    _CACHE[nombre] = d
    return d


def capas() -> dict[str, dict]:
    d = _carga("capas.json") or {"capas": []}
    return {c["id"]: c for c in d["capas"]}


def municipios() -> list[dict]:
    if "mun" in _CACHE:
        return _CACHE["mun"]
    d = _carga("municipios.geojson") or {"features": []}
    out = []
    for f in d["features"]:
        p = f["properties"]
        c = _centroide(f.get("geometry"))
        if not c:
            continue
        out.append({"nombre": p.get("nombre"), "norm": _norm(p.get("nombre")),
                    "cod_ine": str(p.get("cod_ine") or ""), "lat": c[1], "lon": c[0],
                    "poblacion": p.get("poblacion") or 0,
                    "provincia": p.get("provincia_nombre") or p.get("provincia")})
    _CACHE["mun"] = out
    return out


def estaciones() -> list[dict]:
    """Paradas del NAP con nombre (metro, cercanías, AVE): 3.222 puntos."""
    if "est" in _CACHE:
        return _CACHE["est"]
    out = []
    for nombre in ("nap_paradas_cercanias-renfe.geojson", "nap_paradas_metro-madrid.geojson",
                   "nap_paradas_renfe-ave.geojson", "estaciones-cercanias.geojson"):
        d = _carga(nombre) or {"features": []}
        for f in d["features"]:
            p = f.get("properties") or {}
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            n = p.get("nombre") or p.get("name") or p.get("n")
            if not n:
                continue
            out.append({"nombre": n, "norm": _norm(n), "tipo": "estación",
                        "lat": g["coordinates"][1], "lon": g["coordinates"][0]})
    _CACHE["est"] = out
    return out


def plantas() -> list[dict]:
    if "pl" in _CACHE:
        return _CACHE["pl"]
    d = _carga("plantas.geojson") or {"features": []}
    out = []
    for f in d["features"]:
        p = f["properties"]
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        out.append({"nombre": p.get("name"), "norm": _norm(p.get("name")),
                    "tech": p.get("technology_normalized"), "mw": p.get("installed_capacity_mw") or 0,
                    "municipio": p.get("municipality"), "cod_ine": str(p.get("cod_ine_municipio") or ""),
                    "ccaa": p.get("autonomous_region"), "provincia": p.get("province"),
                    "lat": g["coordinates"][1], "lon": g["coordinates"][0]})
    _CACHE["pl"] = out
    return out


def camaras() -> list[dict]:
    if "cam" in _CACHE:
        return _CACHE["cam"]
    d = _carga("dgt_camaras.geojson") or {"features": []}
    out = []
    for f in d["features"]:
        p = f["properties"]
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        try:
            km = float(str(p.get("km")).replace(",", "."))
        except (TypeError, ValueError):
            km = None
        out.append({"via": _via(p.get("carretera")), "km": km, "provincia": p.get("provincia"),
                    "destino": p.get("destino"), "imagen": p.get("imagen"),
                    "lat": g["coordinates"][1], "lon": g["coordinates"][0]})
    _CACHE["cam"] = out
    return out


def renta() -> dict[str, dict]:
    return (_carga("ine/municipios.json") or {}).get("municipios") or {}


# ------------------------------------------------------------------ utilidades
def _norm(s) -> str:
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def _consulta(texto) -> str:
    """Texto sin verbos ni artículos: lo que queda es la entidad que hay que buscar."""
    t = _norm(texto)
    return " ".join(p for p in t.split() if p not in STOP)


def _via(s) -> str:
    return re.sub(r"R$", "", (s or "").upper().replace("-", "").replace(" ", ""))


def _centroide(geom):
    if not geom:
        return None
    g = geom
    if g.get("type") == "Point":
        return g["coordinates"][:2]
    if g.get("type") == "Polygon":
        anillo = max(g["coordinates"], key=len)
    elif g.get("type") == "MultiPolygon":
        anillo = max((max(p, key=len) for p in g["coordinates"]), key=len)
    else:
        return None
    if not anillo:
        return None
    pts = anillo[:-1] if len(anillo) > 1 and anillo[0] == anillo[-1] else anillo
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def _dist_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def buscar_municipio(texto, limite=3):
    obj = _consulta(texto)
    if not obj:
        return []
    palabras = [p for p in obj.split() if len(p) > 2] or obj.split()
    res = []
    for m in municipios():
        n = m["norm"]
        if not n:
            continue
        if n == obj:
            puntos = 1000
        elif n.startswith(obj):
            puntos = 300
        elif all(p in n for p in palabras):
            puntos = 100 + 20 * len(palabras)
        else:
            continue
        res.append((puntos + min(m["poblacion"] / 50000.0, 20), m))
    res.sort(key=lambda x: -x[0])
    return [m for _, m in res[:limite]]


def buscar_estacion(texto, limite=3):
    obj = _consulta(texto)
    palabras = [p for p in obj.split() if len(p) > 2] or obj.split()
    if not palabras:
        return []
    res = []
    for e in estaciones():
        n = e["norm"]
        if all(p in n for p in palabras):
            res.append((100 + (300 if n.startswith(palabras[0]) else 0), e))
    res.sort(key=lambda x: -x[0])
    return [e for _, e in res[:limite]]


def buscar_capa(texto):
    obj = _consulta(texto)
    if not obj:
        return None
    palabras = [p for p in obj.split() if len(p) > 2] or obj.split()
    mejor, puntos_mejor = None, 0
    for cid, c in capas().items():
        alias = _norm(c.get("etiqueta") or "") + " " + _norm(cid.replace("-", " ")) + " " + _norm(c.get("grupo") or "")
        if _norm(c.get("etiqueta") or "") == obj:
            puntos = 200
        elif obj in alias:
            puntos = 100
        elif all(p in alias for p in palabras):
            puntos = 60 + 10 * len(palabras)
        else:
            continue
        if puntos > puntos_mejor:
            mejor, puntos_mejor = cid, puntos
    return mejor


def tecnologia(texto):
    for palabra, tech in TECNOLOGIAS.items():
        if re.search(r"\b" + palabra + r"\b", _norm(texto)):
            return tech
    return None


# ------------------------------------------------------------------ verbos
def accion_volar(texto):
    mun = buscar_municipio(texto)
    if mun:
        m = mun[0]
        return {"verbo": "volar",
                "texto": f"{m['nombre']} ({m.get('provincia') or '—'}), {int(m['poblacion'])} hab.",
                "acciones": [{"tipo": "volar", "centro": [m["lon"], m["lat"]], "zoom": 12,
                              "etiqueta": m["nombre"]}],
                "alternativas": [x["nombre"] for x in mun[1:]]}
    est = buscar_estacion(texto)
    if est:
        e = est[0]
        return {"verbo": "volar", "texto": f"{e['nombre']} (estación del NAP)",
                "acciones": [{"tipo": "capa", "id": "nap-cercanias", "visible": True},
                             {"tipo": "volar", "centro": [e["lon"], e["lat"]], "zoom": 15,
                              "etiqueta": e["nombre"]}]}
    obj = _consulta(texto)
    for p in plantas():
        if obj and (obj in p["norm"] or p["norm"] == obj):
            return {"verbo": "volar",
                    "texto": f"{p['nombre']} · {p['mw']:.1f} MW · {p['municipio'] or '—'}",
                    "acciones": [{"tipo": "capa", "id": "plantas", "visible": True},
                                 {"tipo": "volar", "centro": [p["lon"], p["lat"]], "zoom": 14,
                                  "etiqueta": p["nombre"]}]}
    return None


def accion_foto(texto):
    # quita «km 10» antes de buscar la vía: si no, «KM10» se lee como carretera KM-10
    limpio = re.sub(r"\bkm\.?\s*\d+(?:[.,]\d+)?", " ", texto, flags=re.I)
    m_via = re.search(r"\b([A-Z]{1,2})[- ]?(\d{1,4})\b", limpio.upper())
    m_km = re.search(r"\bkm\.?\s*(\d+(?:[.,]\d+)?)\b", texto, re.I)
    if not m_via:
        return None
    via = _via(m_via.group(1) + m_via.group(2))
    km = float(m_km.group(1).replace(",", ".")) if m_km else 0.0
    cands = [c for c in camaras() if c["via"] == via and c["km"] is not None]
    if not cands:
        return {"verbo": "foto", "texto": f"No tengo cámaras de la DGT en la {via[:1]}-{via[1:]}.", "acciones": []}
    cands.sort(key=lambda c: abs(c["km"] - km))
    c = cands[0]
    d = abs(c["km"] - km)
    if d > 20:
        return {"verbo": "foto",
                "texto": f"La cámara más cercana al km {km:g} de la {via[:1]}-{via[1:]} está en el "
                         f"km {c['km']:g} ({d:.0f} km de distancia).", "acciones": []}
    nombre_via = f"{via[:1]}-{via[1:]}"
    return {"verbo": "foto",
            "texto": f"{nombre_via} km {c['km']:g} · {c['provincia']} · sentido {c['destino'] or '—'} "
                     f"({d:.1f} km del punto pedido)",
            "acciones": [
                {"tipo": "capa", "id": "dgt-camaras", "visible": True},
                {"tipo": "volar", "centro": [c["lon"], c["lat"]], "zoom": 13.5},
                {"tipo": "ficha", "titulo": f"{nombre_via} km {c['km']:g} · {c['provincia']}",
                 "html": f"<b>{nombre_via} km {c['km']:g}</b><br>{c['destino'] or '—'} · {c['provincia']}<br>"
                         f'<img src="{c["imagen"]}" style="width:100%;border-radius:8px;margin-top:6px">'},
            ],
            "dato": {"carretera": nombre_via, "km": c["km"], "imagen": c["imagen"]}}


def accion_mezclar(texto):
    tech = tecnologia(texto)
    if not tech:
        return None
    campo = "renta_uc_mediana" if "mediana" in _norm(texto) else "renta_uc_media"
    r = renta()
    if not r:
        return {"verbo": "mezclar", "texto": "Falta datos/ine/municipios.json para cruzar la renta.", "acciones": []}
    agg: dict[str, dict] = {}
    for p in plantas():
        if p["tech"] not in tech or not p["cod_ine"] or p["cod_ine"] not in r:
            continue
        a = agg.setdefault(p["cod_ine"], {"mw": 0.0, "n": 0, "nombre": p["municipio"]})
        a["mw"] += p["mw"]
        a["n"] += 1
    filas = []
    por_cod = {m["cod_ine"]: m for m in municipios()}
    for cod, a in agg.items():
        v = r[cod].get(campo)
        if v:
            m = por_cod.get(cod) or {}
            filas.append({"cod_ine": cod, "municipio": a["nombre"], "mw": round(a["mw"], 1),
                          "n": a["n"], "renta": v, "lat": m.get("lat"), "lon": m.get("lon")})
    if not filas:
        return {"verbo": "mezclar", "texto": "No hay municipios con las dos cosas.", "acciones": []}
    filas.sort(key=lambda x: -x["mw"])
    valores = [f["renta"] for f in filas]
    etiqueta = {"hydro": "hidráulica", "pumped_hydro": "hidráulica de bombeo", "wind": "eólica",
                "solar_pv": "solar", "solar_thermal": "termosolar", "nuclear": "nuclear",
                "ccgt": "ciclo combinado", "coal": "carbón", "cogeneration": "cogeneración",
                "fuel_gas": "gas"}[tech[0]]
    return {"verbo": "mezclar",
            "texto": (f"{len(filas)} municipios tienen {etiqueta} y renta publicada. El que más concentra: "
                      f"{filas[0]['municipio']} ({filas[0]['mw']:.0f} MW, {filas[0]['renta']} €/año)."),
            "acciones": [
                {"tipo": "capa", "id": "plantas", "visible": True},
                {"tipo": "filtrar", "id": "plantas", "campo": "technology_normalized",
                 "op": "in", "valor": list(tech)},
                {"tipo": "capa", "id": "municipios", "visible": True},
                {"tipo": "mezclar",
                 "coropleta": {"id": "municipios", "campo": "cod_ine", "valor_de": campo,
                               "dominio": [min(valores), max(valores)], "paleta": "viridis"},
                 "puntos": {"id": "plantas", "tamano_por": "installed_capacity_mw"}},
            ],
            "top": filas[:10],
            "dato": {"campo_renta": campo, "tecnologia": list(tech), "municipios": len(filas)}}


def accion_filtrar(texto):
    """«enséñame las nucleares», «muéstrame la eólica»."""
    tech = tecnologia(texto)
    if not tech:
        return None
    planta_tech = [p for p in plantas() if p["tech"] in tech]
    return {"verbo": "filtrar",
            "texto": f"{len(planta_tech)} instalaciones ({sum(p['mw'] for p in planta_tech):,.0f} MW).".replace(",", "."),
            "acciones": [{"tipo": "capa", "id": "plantas", "visible": True},
                         {"tipo": "filtrar", "id": "plantas", "campo": "technology_normalized",
                          "op": "in", "valor": list(tech)}],
            "dato": {"instalaciones": len(planta_tech),
                     "mw": round(sum(p["mw"] for p in planta_tech), 1)}}


def accion_encender(texto):
    cid = buscar_capa(texto)
    if not cid:
        return None
    c = capas()[cid]
    if c.get("licencia") == "no":
        return {"verbo": "capa",
                "texto": f"«{c['etiqueta']}» tiene licencia restringida ({c.get('organismo')}): "
                         f"la puedo enseñar aquí, pero no redistribuir.",
                "acciones": [{"tipo": "capa", "id": cid, "visible": True}]}
    return {"verbo": "capa", "texto": f"Enciendo «{c['etiqueta']}» ({c.get('organismo') or 'sin organismo'}).",
            "acciones": [{"tipo": "capa", "id": cid, "visible": True}]}


def accion_cerca(lat, lon):
    if lat is None or lon is None:
        return {"verbo": "cerca", "texto": "Necesito tu posición para decirte qué tienes cerca.", "acciones": []}
    mun = min(municipios(), key=lambda m: _dist_km(lat, lon, m["lat"], m["lon"]))
    cams = sorted(camaras(), key=lambda c: _dist_km(lat, lon, c["lat"], c["lon"]))[:3]
    pls = sorted(plantas(), key=lambda p: _dist_km(lat, lon, p["lat"], p["lon"]))[:3]
    texto = f"Estás en {mun['nombre']} ({mun.get('provincia') or '—'})."
    if cams:
        texto += f" Cámara DGT más cercana: {cams[0]['via'][:1]}-{cams[0]['via'][1:]} km {cams[0]['km']:g}, a {_dist_km(lat, lon, cams[0]['lat'], cams[0]['lon']):.1f} km."
    if pls:
        texto += f" Planta más cercana: {pls[0]['nombre']} ({pls[0]['mw']:.0f} MW), a {_dist_km(lat, lon, pls[0]['lat'], pls[0]['lon']):.1f} km."
    return {"verbo": "cerca", "texto": texto,
            "acciones": [{"tipo": "volar", "centro": [lon, lat], "zoom": 12, "etiqueta": "aquí"}],
            "dato": {"municipio": mun["nombre"],
                     "dist_municipio_km": round(_dist_km(lat, lon, mun["lat"], mun["lon"]), 1)}}


def accion_resumen(texto):
    t = _norm(texto)
    tech = tecnologia(texto)
    if tech and ("potencia" in t or "cuanta" in t or "cuanto" in t or "mas" in t or "donde" in t
                 or "total" in t or "suma" in t):
        sel = [p for p in plantas() if p["tech"] in tech]
        total = sum(p["mw"] for p in sel)
        prov: dict[str, float] = {}
        for p in sel:
            prov[p["provincia"] or "—"] = prov.get(p["provincia"] or "—", 0) + p["mw"]
        top = sorted(prov.items(), key=lambda x: -x[1])[:5]
        return {"verbo": "responder",
                "texto": (f"{len(sel)} instalaciones, {total:,.0f} MW. Por provincia: ".replace(",", ".")
                          + ", ".join(f"{k} {v:,.0f}".replace(",", ".") for k, v in top) + "."),
                "acciones": [{"tipo": "capa", "id": "plantas", "visible": True},
                             {"tipo": "filtrar", "id": "plantas", "campo": "technology_normalized",
                              "op": "in", "valor": list(tech)}],
                "dato": {"instalaciones": len(sel), "mw": round(total, 1), "top_provincias": top}}
    if "capa" in t or "catalogo" in t or "que tienes" in t or "que hay" in t:
        c = capas()
        grupos: dict[str, int] = {}
        for v in c.values():
            grupos[v["grupo"]] = grupos.get(v["grupo"], 0) + 1
        return {"verbo": "responder",
                "texto": f"{len(c)} capas en {len(grupos)} grupos: "
                         + ", ".join(f"{g} ({n})" for g, n in sorted(grupos.items(), key=lambda x: -x[1])[:6]) + ".",
                "acciones": []}
    return None


# ------------------------------------------------------------------ enrutado
RE_IR = re.compile(r"^(?:lle[vw]ame|ir|vamos|ve|ver|ensen|muestr|abre|d[oó]nde est)", re.I)


def intencion_local(frase, lat=None, lon=None):
    f = frase.strip()
    t = _norm(f)

    if re.search(r"foto|camara|imagen", t):
        r = accion_foto(f)
        if r:
            return r

    if re.search(r"\bmix\b|mezcla|cruza|combina|correlacion", t):
        r = accion_mezclar(f)
        if r:
            return r

    if re.search(r"\bcerca\b|alrededor", t):
        return accion_cerca(lat, lon)

    r = accion_resumen(f)
    if r:
        return r

    if re.search(r"\bkm\b", t):
        r = accion_foto(f)
        if r:
            return r

    r = accion_filtrar(f)
    if r:
        return r

    r = accion_encender(f)
    if r:
        return r

    if RE_IR.search(f) or buscar_municipio(f) or buscar_estacion(f):
        r = accion_volar(f)
        if r:
            return r
    return None


def interpreta_llm(frase, ctx=""):
    clave = None
    for nombre in ("NAN_API_KEY", "api_nan", "API_NAN", "OPENAI_API_KEY"):
        if os.environ.get(nombre):
            clave = os.environ[nombre]
            break
    if not clave:
        for ruta in (os.path.join(os.environ.get("DATOS", "/data"), "nan.key"),
                     os.path.expanduser("~/.hermes/nan.key")):
            if os.path.exists(ruta):
                try:
                    clave = open(ruta).read().strip()
                    break
                except OSError:
                    pass
    if not clave:
        return None
    cuerpo = {"model": MODELO, "reasoning_effort": "minimal", "temperature": 0.1, "max_tokens": 300,
              "messages": [{"role": "system", "content": SISTEMA + (("\n\nContexto: " + ctx) if ctx else "")},
                           {"role": "user", "content": frase}]}
    req = urllib.request.Request(
        API, data=json.dumps(cuerpo).encode(),
        headers={"Authorization": "Bearer " + clave, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            datos = json.load(r)
        m = re.search(r"\{.*\}", datos["choices"][0]["message"].get("content", ""), re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def resolver(frase, lat=None, lon=None):
    r = intencion_local(frase, lat, lon)
    if r:
        r["pregunta"] = frase
        return r

    it = interpreta_llm(frase, f"El usuario está en {lat}, {lon}." if lat is not None else "")
    if it:
        verbo, entidad = (it.get("verbo") or "").lower(), it.get("entidad") or ""
        for fn, verbos in ((accion_volar, ("volar",)), (accion_encender, ("encender", "capa")),
                           (accion_foto, ("foto",)), (accion_mezclar, ("mezclar",)),
                           (accion_filtrar, ("filtrar",))):
            if verbo in verbos:
                r = fn(entidad or frase)
                if r:
                    r["pregunta"] = frase
                    r["via_llm"] = True
                    return r
        if it.get("texto"):
            return {"verbo": "responder", "texto": it["texto"], "acciones": [],
                    "pregunta": frase, "via_llm": True}

    return {"verbo": "responder",
            "texto": "No te he entendido. Prueba con «llévame a Bilbao», «km 10 de la A-2, foto», "
                     "«mezcla renta con hidráulicas» o «enséñame las cámaras».",
            "acciones": [], "pregunta": frase}


# ------------------------------------------------------------------ prueba
PRUEBAS = [
    ("llévame a Bilbao", "volar"),
    ("enséñame las cámaras", "capa"),
    ("km 10 de la A-2 enséñame la foto en tiempo real", "foto"),
    ("hazme un mix de renta con centrales hidráulicas", "mezclar"),
    ("cuánta potencia hidráulica hay en España", "responder"),
    ("qué capas tienes", "responder"),
    ("llévame a Aldeadávila de la Ribera", "volar"),
    ("mezcla renta mediana con eólica", "mezclar"),
    ("muéstrame las centrales nucleares", "filtrar"),
    ("km 200 de la A-4, foto", "foto"),
    ("vamos a Atocha", "volar"),
    ("enséñame los embalses", "capa"),
    ("dónde hay más hidráulica", "responder"),
    ("foto del km 5 de la A-6", "foto"),
    ("llévame a la central de Aldeadávila", "volar"),
    ("qué tienes de transporte", "responder"),
]


def probar():
    fallos = 0
    for frase, esperado in PRUEBAS:
        r = resolver(frase)
        ok = r["verbo"] == esperado and (r["acciones"] or r["verbo"] in ("responder", "cerca"))
        if not ok:
            fallos += 1
        print(f"{'OK ' if ok else 'FALLA'} {frase[:44]:44s} -> {r['verbo']:9s} "
              f"{len(r['acciones'])} acc · {r['texto'][:76]}")
    print(f"\n{len(PRUEBAS) - fallos}/{len(PRUEBAS)} correctas")
    return 1 if fallos else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--probar" in sys.argv or not args:
        sys.exit(probar())
    for frase in args:
        print(json.dumps(resolver(frase), ensure_ascii=False, indent=1))
