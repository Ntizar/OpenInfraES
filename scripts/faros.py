#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Faros y señales marítimas del IGN (SignA) -> datos/faros.geojson.

278 puntos con municipio, provincia y la marca de Bien de Interés Cultural cuando la hay.
Una sola página: el servicio devuelve menos de 1000.
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
BASE = "https://serviciosgis.ign.es/servicios/rest/services/Signa"
SERVICIO, CAPA = "03_construcciones_otros", 11
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
FUENTE = "IGN · SignA (SCNE)"
LICENCIA = "CC BY 4.0 · © Instituto Geográfico Nacional de España"

BASURA = ("no procede", "territorio no asociado", "entidad no asociada")


def limpio(v):
    """El IGN rellena huecos con 'No procede' / 'Territorio no asociado...': eso no es dato."""
    t = (v or "").strip()
    return None if any(b in t.lower() for b in BASURA) or not t else t


def main():
    params = {"where": "1=1", "outFields": "nombre,bic,municipio,provincia",
              "returnGeometry": "true", "outSR": "4326", "f": "geojson",
              "resultRecordCount": "1000"}
    url = "%s/%s/MapServer/%s/query?%s" % (BASE, SERVICIO, CAPA, urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        crudo = json.loads(r.read().decode("utf-8"))
    features = []
    for f in crudo.get("features") or []:
        a, g = f.get("properties") or {}, f.get("geometry")
        if not g or g.get("type") != "Point":
            continue
        c = g["coordinates"]
        features.append({"type": "Feature",
                         "geometry": {"type": "Point",
                                      "coordinates": [round(c[0], 5), round(c[1], 5)]},
                         "properties": {"nombre": limpio(a.get("nombre")),
                                        "bic": limpio(a.get("bic")),
                                        "municipio": limpio(a.get("municipio")),
                                        "provincia": limpio(a.get("provincia"))}})
    features = [f for f in features if f["properties"]["nombre"]]
    features.sort(key=lambda f: (f["properties"]["provincia"] or "zz", f["properties"]["nombre"]))
    if len(features) < 250:
        raise SystemExit("solo %d faros: el servicio no devolvió lo esperado, no se publica"
                         % len(features))

    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(DEST, "faros.geojson"), "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "generado": ahora, "fuente": FUENTE,
                   "licencia": LICENCIA, "features": features}, fh, ensure_ascii=False,
                  separators=(",", ":"))
    bic = sum(1 for f in features if f["properties"]["bic"])
    provincias = len({f["properties"]["provincia"] for f in features if f["properties"]["provincia"]})
    rec = {"fichero": "datos/faros.geojson", "features": len(features), "fuente": FUENTE,
           "editor": "Instituto Geográfico Nacional (SCNE)", "url": "https://signa.ign.es/signa/",
           "licencia": LICENCIA, "descargado": ahora,
           "metodo": "query f=geojson sobre Signa/03_construcciones_otros/11, redondeo a 5 "
                     "decimales",
           "con_bic": bic, "provincias": provincias, "fecha_dato": None,
           "nota": "SignA es servicio vivo: el IGN no publica fecha por elemento; la consulta "
                   "es la fecha del recibo"}
    with open(os.path.join(DEST, "faros_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print("faros: %d · %d con BIC · %d provincias" % (len(features), bic, provincias))


if __name__ == "__main__":
    main()
