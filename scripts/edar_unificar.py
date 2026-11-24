# -*- coding: utf-8 -*-
"""Una sola capa de EDAR: IGN + I-ReWater + OSM fundidos por planta.

El visor tenía tres capas de lo mismo (OSM `edar`, `irewater-edar` y las depuradoras del IGN) y
una misma planta salía hasta tres veces, cada una con media verdad: el IGN pone municipio y
provincia, I-ReWater pone capacidad, caudal de entrada e impacto hidrológico, OSM pone el nombre
local. Aquí se cruzan por proximidad y queda **una chincheta por planta con todos los datos
dentro**. Si una planta solo está en una fuente, se queda igual: no se inventa nada.
"""
import json
import math
import os
import unicodedata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
RADIO = 150.0          # m: una EDAR es una planta grande; 150 m cubre el margen de digitalización


def lee(nombre):
    ruta = os.path.join(DATOS, nombre)
    if not os.path.exists(ruta):
        return []
    try:
        return json.load(open(ruta, encoding="utf-8")).get("features") or []
    except Exception:
        return []


def punto(f):
    g = f.get("geometry") or {}
    c = g.get("coordinates")
    if g.get("type") != "Point" or not c:
        # alguna fuente trae multipunto o punto dentro de lista
        while isinstance(c, list) and c and isinstance(c[0], list):
            c = c[0]
        if not (isinstance(c, list) and len(c) >= 2):
            return None
    return (float(c[0]), float(c[1]))


def metros(a, b):
    dx = (a[0] - b[0]) * 111320.0 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 111320.0
    return math.hypot(dx, dy)


def clave(lon, lat, m=RADIO):
    dlat = m / 111320.0
    dlon = m / (111320.0 * max(0.15, math.cos(math.radians(lat))))
    return (int(lat / dlat), int(lon / dlon))


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def busca(rejilla, lon, lat, radio=RADIO):
    k = clave(lon, lat, radio)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for otro in rejilla.get((k[0] + di, k[1] + dj), []):
                if metros((lon, lat), otro["_p"]) <= radio:
                    return otro
    return None


def anade(rejilla, salida, feat, lon, lat):
    rejilla.setdefault(clave(lon, lat), []).append(feat)
    salida.append(feat)


def main():
    ign = lee("depuradoras_ign.geojson")
    rew = lee("irewater_hib_edar.geojson")
    osm = lee("edar.geojson")

    salida, rejilla = [], {}
    for f in ign:                      # el IGN manda en la ubicación: es el que trae municipio
        p = f.get("properties") or {}
        ll = punto(f)
        if not ll:
            continue
        anade(rejilla, salida, {
            "_p": ll,
            "nombre": p.get("nombre"), "municipio": p.get("municipio"),
            "provincia": p.get("provincia"), "fuentes": ["IGN"],
        }, *ll)

    for f in rew:
        p = f.get("properties") or {}
        ll = punto(f)
        if not ll:
            continue
        otro = busca(rejilla, *ll)
        datos = {
            "capacidad": p.get("capacidad"),
            "caudal_entrada": p.get("qentrada_he"),
            "impacto": p.get("indice_impacto_hidrologico"),
            "codigo": p.get("codigo"),
        }
        if otro:
            for k, v in datos.items():
                if v not in (None, "", 0) and not otro.get(k):
                    otro[k] = v
            otro["fuentes"].append("I-ReWater")
            if not otro.get("municipio") and p.get("municipio"):
                otro["municipio"] = str(p["municipio"]).title()
        else:
            nuevo = dict(datos, _p=ll, nombre=None,
                         municipio=str(p["municipio"]).title() if p.get("municipio") else None,
                         provincia=None, fuentes=["I-ReWater"])
            anade(rejilla, salida, nuevo, *ll)

    for f in osm:
        p = f.get("properties") or {}
        ll = punto(f)
        if not ll:
            continue
        otro = busca(rejilla, *ll)
        if otro:
            if not otro.get("nombre") and p.get("name"):
                otro["nombre"] = p.get("name")
            if p.get("osm_id"):
                otro["osm_id"] = p.get("osm_id")
            otro["fuentes"].append("OSM")
        else:
            anade(rejilla, salida, {
                "_p": ll, "nombre": p.get("name"), "municipio": None, "provincia": None,
                "osm_id": p.get("osm_id"), "fuentes": ["OSM"],
            }, *ll)

    feats = []
    for s in salida:
        ll = s.pop("_p")
        # dos filas del IGN con el mismo nombre y a menos de 150 m ya se han fundido; si aun así
        # queda sin nombre, se dice por el municipio en vez de dejar un punto mudo
        nombre = s.get("nombre")
        if not nombre:
            if s.get("municipio"):
                nombre = "EDAR de " + s["municipio"]
            elif s.get("codigo"):
                nombre = "EDAR " + str(s["codigo"])[-6:]
            else:
                nombre = "EDAR sin nombre"
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(ll[0], 5), round(ll[1], 5)]},
            "properties": {
                "nombre": nombre, "municipio": s.get("municipio"), "provincia": s.get("provincia"),
                "capacidad": s.get("capacidad"), "caudal_entrada": s.get("caudal_entrada"),
                "impacto": s.get("impacto"), "codigo": s.get("codigo"), "osm_id": s.get("osm_id"),
                "fuentes": " · ".join(sorted(set(s["fuentes"]))),
                "n_fuentes": len(set(s["fuentes"])),
                "fuente": "IGN · I-ReWater · OSM",
            },
        })

    con_cap = sum(1 for f in feats if f["properties"]["capacidad"])
    ruta = os.path.join(DATOS, "edar_unificado.geojson")
    json.dump({"type": "FeatureCollection", "features": feats}, open(ruta, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    rec = {
        "titulo": "EDAR · depuradoras unificadas",
        "fuente": "IGN · I-ReWater · OSM",
        "editor": "IGN, I-ReWater HUB (Interreg) y OpenStreetMap",
        "licencia": "CC BY 4.0 + ODbL 1.0 (ver ficha por fuente)",
        "url": "https://signa.ign.es/",
        "descargado": "2026-11-24",
        "metodo": ("IGN + I-ReWater + OSM cruzados por proximidad de %.0f m; una planta, una fila, "
                   "con capacidad, caudal e impacto dentro" % RADIO),
        "features": len(feats),
        "con_capacidad": con_cap,
        "kb": round(os.path.getsize(ruta) / 1024, 1),
    }
    json.dump(rec, open(os.path.join(DATOS, "edar_unificado_recibo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("EDAR unificadas: %d (%.1f KB) · %d con capacidad · fuentes IGN %d / I-ReWater %d / OSM %d"
          % (len(feats), rec["kb"], con_cap, len(ign), len(rew), len(osm)))
    repetidas = len(ign) + len(rew) + len(osm) - len(feats)
    print("filas que se han fundido: %d" % repetidas)


if __name__ == "__main__":
    main()
