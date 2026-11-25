#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Núcleos de población del IGN (SignA, BTN) -> datos/nucleos.geojson.

37.469 núcleos con población, hombres y mujeres por núcleo: el padrón que ya tenemos
está agregado a municipio, así que una pedanía de 40 habitantes no existía en el visor.
Una sola consulta paginada, sin clave.
"""
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
BASE = "https://serviciosgis.ign.es/servicios/rest/services/Signa"
SERVICIO, CAPA = "01_unidades_administrativas", 12
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
FUENTE = "IGN · SignA (SCNE)"
LICENCIA = "CC BY 4.0 · © Instituto Geográfico Nacional de España"
CAMPOS = "codine,nombre,poblacion,hombres,mujeres,desc_cod_pro,desc_cod_muni"
PAGINA = 1000


def pide(offset, intentos=3):
    params = {"where": "1=1", "outFields": CAMPOS, "returnGeometry": "true", "outSR": "4326",
              "f": "geojson", "resultOffset": offset, "resultRecordCount": PAGINA,
              "maxAllowableOffset": 0.0005}
    url = "%s/%s/MapServer/%s/query?%s" % (BASE, SERVICIO, CAPA, urllib.parse.urlencode(params))
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if i == intentos - 1:
                raise RuntimeError("falla %s/%s offset %s: %s" % (SERVICIO, CAPA, offset, e))
            time.sleep(2 + 3 * i)


def redondea(geom, dec=5):
    if geom["type"] != "Point":
        return geom
    c = geom["coordinates"]
    return {"type": "Point", "coordinates": [round(c[0], dec), round(c[1], dec)]}


def main():
    features, offset = [], 0
    while True:
        d = pide(offset)
        lote = d.get("features") or []
        for f in lote:
            a, g = f.get("properties") or {}, f.get("geometry")
            if not g:
                continue
            features.append({"type": "Feature", "geometry": redondea(g), "properties": {
                "codine": a.get("codine"),
                "nombre": (a.get("nombre") or "").strip(),
                "municipio": (a.get("desc_cod_muni") or "").strip(),
                "provincia": (a.get("desc_cod_pro") or "").strip(),
                "poblacion": a.get("poblacion"),
                "hombres": a.get("hombres"),
                "mujeres": a.get("mujeres"),
            }})
        print("  %d núcleos" % len(features))
        if len(lote) < PAGINA:
            break
        offset += PAGINA
    if len(features) < 30000:
        raise SystemExit("solo %d núcleos: el servicio no devolvió lo esperado, no se publica"
                         % len(features))

    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = {"type": "FeatureCollection", "generado": ahora, "fuente": FUENTE, "licencia": LICENCIA,
         "features": features}
    with open(os.path.join(DEST, "nucleos.geojson"), "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    hab = sum(f["properties"]["poblacion"] or 0 for f in features)
    con = sum(1 for f in features if (f["properties"]["poblacion"] or 0) > 0)
    rec = {
        "fichero": "datos/nucleos.geojson", "features": len(features), "fuente": FUENTE,
        "editor": "Instituto Geográfico Nacional (SCNE)", "url": "https://signa.ign.es/signa/",
        "licencia": LICENCIA, "descargado": ahora,
        "metodo": "query f=geojson sobre Signa/01_unidades_administrativas/12, paginado de 1000 "
                  "en 1000, redondeo a 5 decimales",
        "poblacion_total": hab, "nucleos_con_poblacion": con,
        "fecha_dato": None,
        "nota": "SignA es servicio vivo: el IGN no publica fecha por núcleo; la población es la "
                "del BTN en el momento de la consulta",
    }
    with open(os.path.join(DEST, "nucleos_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print("nucleos: %d · %d con población · %.0f hab · %.1f MB"
          % (len(features), con, hab, os.path.getsize(os.path.join(DEST, "nucleos.geojson"))
             / 1024 / 1024))


if __name__ == "__main__":
    main()
