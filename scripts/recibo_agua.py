# -*- coding: utf-8 -*-
"""Escribe datos/osm_agua_recibo.json contando los GeoJSON de agua ya descargados.

No inventa cifras: cuenta features y nombres de los ficheros del repositorio. Sirve
porque la descarga de OSM se corta a veces por timeout y el recibo no llega a escribirse.
"""
import json
import os
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
CAPAS = {
    "edar": ("edar.geojson", "EDAR (depuradoras de aguas residuales)"),
    "etap": ("etap.geojson", "ETAP (plantas potabilizadoras)"),
    "agua-conducciones": ("agua-conducciones.geojson", "Conducciones y trasvases de agua"),
}

recibo = {}
for capa, (fich, titulo) in CAPAS.items():
    ruta = os.path.join(DATOS, fich)
    if not os.path.exists(ruta):
        print("  %-18s falta %s" % (capa, fich))
        continue
    d = json.load(open(ruta, encoding="utf-8"))
    feats = d.get("features", [])
    con_nombre = sum(1 for f in feats if (f.get("properties") or {}).get("name"))
    nombres = {f["properties"]["name"] for f in feats
               if (f.get("properties") or {}).get("name")}
    recibo[capa] = {"features": len(feats), "con_nombre": con_nombre,
                    "nombres": len(nombres), "titulo": titulo,
                    "fichero": fich, "kb": round(os.path.getsize(ruta) / 1024)}
    # Frescura medida por mtime: si el refresco semanal no pudo bajar la capa, el recibo lo
    # dice (`estado: heredado`) en vez de callarse, y se limpia solo cuando llega dato nuevo.
    mtime = os.path.getmtime(ruta)
    recibo[capa]["refrescado_en"] = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(mtime))
    if (time.time() - mtime) / 86400 > 8:
        recibo[capa]["estado"] = "heredado"
        recibo[capa]["heredado_en"] = recibo[capa]["refrescado_en"]
    print("  %-18s %5d features (%d con nombre) %5.0f KB" % (capa, len(feats), con_nombre,
          os.path.getsize(ruta) / 1024))

json.dump(recibo, open(os.path.join(DATOS, "osm_agua_recibo.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nrecibo -> datos/osm_agua_recibo.json")
