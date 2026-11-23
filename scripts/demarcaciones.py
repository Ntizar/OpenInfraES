# -*- coding: utf-8 -*-
"""Demarcaciones hidrográficas del MITECO.

Es el dato que cuelga de cada presa y embalse: la presa dice a qué demarcación pertenece, y la
demarcación es la unidad de gestión (confederación). Servicio ArcGIS REST abierto, sin clave.

    python scripts/demarcaciones.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http_oficial import pide, CertificadoInvalido

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
BASE = ("https://sig.miteco.gob.es/arcgis/rest/services/25830/"
        "aguaHidroDemarcaciones/MapServer/2/query")
RUTA = os.path.join(DEST, "demarcaciones.geojson")
RUTA_RECIBO = os.path.join(DEST, "demarcaciones_recibo.json")


def heredar(motivo):
    """Se queda el ultimo geojson bueno y deja constancia en el recibo.

    El certificado de sig.mapa.gob.es caduca de vez en cuando y no depende de nosotros.
    Mismo criterio que el 403 del WAF de ESIOS: el dato no se pierde, y el recibo pasa a
    `estado: heredado` con el motivo para que el visor pueda avisar en vez de mentir.
    Devuelve False si no hay dato anterior que heredar (entonces si es un fallo real).
    """
    if not os.path.exists(RUTA):
        return False
    try:
        recibo = json.load(open(RUTA_RECIBO, encoding="utf-8"))
    except (OSError, ValueError):
        recibo = {}
    recibo["estado"] = "heredado"
    recibo["motivo"] = motivo[:200]
    recibo["heredado_en"] = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    with open(RUTA_RECIBO, "w", encoding="utf-8") as f:
        json.dump(recibo, f, ensure_ascii=False, indent=1)
    print("  aviso: %s · se mantiene el dato anterior (%s demarcaciones)"
          % (motivo[:110], recibo.get("features", "?")))
    return True


def main():
    try:
        d = pide(BASE + "?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326"
                 "&f=geojson&maxAllowableOffset=0.0005",
                 vacio_si=("features",))
    except CertificadoInvalido as e:
        # El certificado lo renueva el ministerio, no nosotros: se mantiene el ultimo dato
        # bueno (mismo criterio que el 403 del WAF de ESIOS) y el recibo lo deja dicho.
        if heredar(str(e)):
            return
        raise

    feats = d.get("features", [])
    # limpia propiedades vacias y normaliza el nombre
    for f in feats:
        p = f.get("properties") or {}
        f["properties"] = {k: v for k, v in p.items() if v not in (None, "", " ")}

    ruta = os.path.join(DEST, "demarcaciones.geojson")
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False)

    nombres = []
    for f in feats:
        p = f["properties"]
        for k in p:
            if any(t in k.lower() for t in ("nom", "name", "demarc")):
                nombres.append(str(p[k]))
                break

    recibo = {
        "fuente": "MITECO",
        "servicio": "sig.miteco.gob.es · aguaHidroDemarcaciones · capa 2",
        "url": BASE,
        "licencia": "Reutilización con atribución (Ley 37/2007)",
        "features": len(feats),
        "tamano_kb": round(os.path.getsize(ruta) / 1024, 1),
        "nombres": sorted(set(nombres))[:25],
    }
    json.dump(recibo, open(os.path.join(DEST, "demarcaciones_recibo.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)

    print("  %d demarcaciones · %s KB" % (len(feats), recibo["tamano_kb"]))
    for n in recibo["nombres"]:
        print("   ", n)


if __name__ == "__main__":
    main()
