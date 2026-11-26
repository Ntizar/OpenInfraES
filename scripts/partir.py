#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parte los GeoJSON gordos por provincia o comunidad -> datos/<capa>/ + index.json.

Un fichero de 9 MB se nota: el navegador se pasa un tercio de segundo parseando antes de pintar
nada, y con varias capas encendidas son segundos. Partido por provincia, cada trozo pesa unos
cientos de KB y el visor descarga solo los que cortan la vista (ver `cargarPartes` en index.html).

El fichero entero se queda donde estaba: la API y quien lo descargue no notan nada.
"""
import json
import os
import re
import shutil
import unicodedata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")

# (capa, fichero, campo por el que se parte, campo que da el nombre legible)
PARTIR = [
    ("trafico-ccaa", "trafico_ccaa.geojson", "ccaa", "ccaa"),
    ("trafico-estaciones", "trafico_estaciones.geojson", "ccaa", "ccaa"),
    ("municipios", "municipios.geojson", "provincia", "provincia_nombre"),
    ("nucleos", "nucleos.geojson", "provincia", "provincia"),
    ("ciudad-docencia", "ciudad_docencia.geojson", "provincia", "provincia"),
    ("dpmt", "dpmt.geojson", "provincia", "provincia"),
    ("dgt-electrolineras", "dgt_electrolineras.geojson", "provincia_municipio",
     "provincia_municipio"),
    # Las gordas de nivel nacional: se ven a zoom 7-12 y no hace falta bajarlas enteras.
    # (Antenas y aparcamientos del IGN no traen provincia: se quedan en un fichero.)
    # Sin esto, mirar Madrid descargaba los 26 MB de incendios de toda España.
    ("incendios-effis", "incendios_effis.geojson", "provincia", "provincia"),
    ("patrimonio-ign", "patrimonio_ign.geojson", "provincia", "provincia"),
    ("carburantes", "carburantes.geojson", "provincia", "provincia"),
    ("ciudad-cementerios", "ciudad_cementerios.geojson", "provincia", "provincia"),
    ("cimas-ign", "cimas_ign.geojson", "provincia", "provincia"),
]


def slug(texto):
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "sin-nombre"


def caja(geom):
    x0 = y0 = 1e9
    x1 = y1 = -1e9
    pila = [geom.get("coordinates")] if geom else []
    while pila:
        a = pila.pop()
        if not a:
            continue
        if isinstance(a[0], (int, float)):
            x, y = float(a[0]), float(a[1])
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
        else:
            pila.extend(a)
    if x0 > x1:
        return None
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]


def partir(capa, fichero, campo, campo_etiqueta):
    origen = os.path.join(DEST, fichero)
    if not os.path.exists(origen):
        print("  %-20s sin fichero, se salta" % capa)
        return
    with open(origen, encoding="utf-8") as fh:
        gj = json.load(fh)
    feats = gj.get("features") or []
    grupos = {}
    for f in feats:
        p = f.get("properties") or {}
        v = p.get(campo)
        if v is None or v == "":
            v = "sin-dato"
        grupos.setdefault(str(v), []).append(f)

    carpeta = os.path.join(DEST, capa)
    if os.path.isdir(carpeta):
        shutil.rmtree(carpeta)
    os.makedirs(carpeta)

    partes = []
    for valor, fs in sorted(grupos.items()):
        etiqueta = str((fs[0].get("properties") or {}).get(campo_etiqueta) or valor)
        nombre = slug(valor) + ".geojson"
        cajas = [c for c in (caja(f.get("geometry")) for f in fs) if c]
        bbox = None
        if cajas:
            bbox = [min(c[0] for c in cajas), min(c[1] for c in cajas),
                    max(c[2] for c in cajas), max(c[3] for c in cajas)]
        with open(os.path.join(carpeta, nombre), "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": fs}, fh,
                      ensure_ascii=False, separators=(",", ":"))
        partes.append({"slug": slug(valor), "valor": valor, "etiqueta": etiqueta,
                       "fichero": nombre, "n": len(fs), "bbox": bbox,
                       "bytes": os.path.getsize(os.path.join(carpeta, nombre))})
    indice = {"capa": capa, "base": fichero, "campo": campo, "total": len(feats),
              "fuente": gj.get("fuente"), "generado": gj.get("generado"), "partes": partes}
    with open(os.path.join(carpeta, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(indice, fh, ensure_ascii=False, separators=(",", ":"))
    mayor = max(p["bytes"] for p in partes) if partes else 0
    print("  %-20s %6d objetos -> %2d partes (la mayor %.0f KB)"
          % (capa, len(feats), len(partes), mayor / 1024.0))


def main():
    print("partiendo capas gordas")
    for capa, fichero, campo, etiqueta in PARTIR:
        partir(capa, fichero, campo, etiqueta)


if __name__ == "__main__":
    main()
