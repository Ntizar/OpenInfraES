# -*- coding: utf-8 -*-
"""catalogo_ia.py — el catálogo que lee el asistente.

`scripts/catalogo.py` responde «¿de quién es este dato y puedo publicarlo?» (licencia,
jerarquía, TTL). Este responde «¿con qué capa hablo y qué puedo hacer con ella?»: grupo,
etiqueta, geometría, campos de la primera feature y **clave territorial** (el campo por el
que se puede cruzar con otra capa).

Se parte de `datos/catalogo.json` —no de index.html— para no duplicar la política de
licencias: si una capa está vetada, el asistente lo sabe y no la ofrece.

    python3 scripts/catalogo_ia.py            # escribe datos/capas.json
    python3 scripts/catalogo_ia.py --probar   # solo cuenta y avisa de lo que falta
"""
from __future__ import annotations

import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(RAIZ, "index.html")
CATALOGO = os.path.join(RAIZ, "datos", "catalogo.json")
SALIDA = os.path.join(RAIZ, "datos", "capas.json")

# Campo que permite cruzar la capa con otra. Es la pieza que hace posible el «mix».
TERRITORIAL = {
    "cod_ine_municipio": "municipio",
    "municipio_ine": "municipio",
    "cod_ine": "municipio",
    "cod_municipio": "municipio",
    "provincia": "provincia",
    "carretera": "carretera",
    "demarcacion": "demarcacion",
}

# Verbo del asistente que tiene sentido por geometría y por contenido.
VERBOS = {
    "punto": ["volar", "capa", "filtrar", "ficha", "cerca"],
    "linea": ["volar", "capa", "filtrar"],
    "poligono": ["volar", "capa", "filtrar", "mezclar", "ficha"],
}


def _bloque_capas(html: str) -> list[str]:
    ini = html.index("const CAPAS = [")
    # el cierre es «];» al principio de una línea, no el primer «]» (hay arrays anidados)
    fin = html.index("\n];", ini)
    arr = html[ini + len("const CAPAS = ["):fin]
    objs, prof, comienzo = [], 0, None
    for i, c in enumerate(arr):
        if c == "{":
            if prof == 0:
                comienzo = i
            prof += 1
        elif c == "}":
            prof -= 1
            if prof == 0 and comienzo is not None:
                objs.append(arr[comienzo:i + 1])
    return objs


def _campo(bloque: str, nombre: str):
    m = re.search(r'\b' + nombre + r'\s*:\s*("(?:[^"\\]|\\.)*"|[\w.\-]+)', bloque)
    if not m:
        return None
    v = m.group(1)
    if v.startswith('"'):
        return v[1:-1]
    return v


def _parsea_visor() -> dict[str, dict]:
    html = open(INDEX, encoding="utf-8").read()
    out = {}
    for b in _bloque_capas(html):
        cid = _campo(b, "id")
        if not cid:
            continue
        out[cid] = {
            "grupo": _campo(b, "grupo"),
            "etiqueta": _campo(b, "label"),
            "tipo": _campo(b, "tipo"),
            "fichero": _campo(b, "fichero"),
            "color": _campo(b, "color"),
            "titulo": _campo(b, "popupTitulo"),
            "color_campo": _campo(b, "colorCampo"),
            "zoom_min": _campo(b, "zoomMin"),
            "on": _campo(b, "on") == "true",
        }
    return out


_CACHE: dict[str, list[str] | None] = {}


def _campos(fichero: str | None) -> list[str] | None:
    """Propiedades de la primera feature. Cachea por fichero: `plantas.geojson` sirve a 4 capas."""
    if not fichero:
        return None
    if fichero in _CACHE:
        return _CACHE[fichero]
    ruta = os.path.join(RAIZ, fichero)
    props = None
    try:
        if os.path.isfile(ruta):
            with open(ruta, encoding="utf-8") as f:
                fs = json.load(f).get("features") or []
            if fs:
                props = list((fs[0].get("properties") or {}).keys())
    except Exception:
        props = None
    _CACHE[fichero] = props
    return props


def _clave(campos: list[str] | None) -> str | None:
    for c in campos or []:
        if c in TERRITORIAL:
            return TERRITORIAL[c]
    return None


def construir() -> dict:
    cat = json.load(open(CATALOGO, encoding="utf-8"))["capas"]
    visor = _parsea_visor()

    capas = []
    for cid, v in visor.items():
        base = cat.get(cid) or {}
        campos = _campos(v.get("fichero"))
        clave = _clave(campos)
        capas.append({
            "id": cid,
            "etiqueta": v.get("etiqueta") or base.get("titulo") or cid,
            "grupo": v.get("grupo") or "otros",
            "tipo": v.get("tipo") or "punto",
            "color": v.get("color"),
            "fichero": v.get("fichero"),
            "titulo_campo": v.get("titulo"),
            "color_campo": v.get("color_campo"),
            "zoom_min": v.get("zoom_min"),
            "campos": campos,
            "clave_territorial": clave,
            "verbos": VERBOS.get(v.get("tipo") or "punto", VERBOS["punto"]),
            "organismo": base.get("organismo"),
            "oficial": base.get("oficial"),
            "jerarquia": base.get("jerarquia"),
            "licencia": (base.get("licencia") or {}).get("estado"),
            "features": base.get("features"),
            "kb": base.get("kb"),
            "caducado": base.get("caducado"),
            "en_catalogo": bool(base),
        })

    grupos = {}
    for c in capas:
        g = c["grupo"]
        d = grupos.setdefault(g, {"capas": 0, "kb": 0, "territoriales": 0})
        d["capas"] += 1
        d["kb"] = round(d["kb"] + (c.get("kb") or 0), 1)
        if c["clave_territorial"]:
            d["territoriales"] += 1

    return {
        "_meta": {
            "generado_por": "scripts/catalogo_ia.py",
            "base": "datos/catalogo.json + index.html (const CAPAS)",
            "capas": len(capas),
            "grupos": grupos,
            "con_clave_territorial": sum(1 for c in capas if c["clave_territorial"]),
            "sin_catalogo": [c["id"] for c in capas if not c["en_catalogo"]],
            "vetadas": [c["id"] for c in capas if c["licencia"] == "no"],
        },
        "capas": capas,
    }


def main() -> int:
    if not os.path.exists(CATALOGO):
        print("falta datos/catalogo.json: ejecuta antes scripts/catalogo.py")
        return 1
    d = construir()
    m = d["_meta"]
    if "--probar" not in sys.argv:
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    print(f"capas: {m['capas']} · con clave territorial: {m['con_clave_territorial']}")
    for g, v in sorted(m["grupos"].items(), key=lambda x: -x[1]["capas"]):
        print(f"  {g:18s} {v['capas']:3d} capas · {v['kb']:8.0f} KB · {v['territoriales']:2d} territoriales")
    if m["sin_catalogo"]:
        print("sin ficha en el catálogo:", ", ".join(m["sin_catalogo"][:8]))
    if m["vetadas"]:
        print("licencia restringida:", ", ".join(m["vetadas"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
