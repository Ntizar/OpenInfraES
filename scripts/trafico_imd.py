#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intensidad media diaria (IMD) por tramo de la Red del Estado -> datos/trafico_imd.geojson.

Fuente: Mapa de Tráfico de la Dirección General de Carreteras (MITMA). La DGT no publica
intensidades: ni en su catálogo del NAP (incidencias, cámaras, paneles, radares, ZBE, INVIVE) ni
en la API de su propio visor (`etrafficWEB/api/cache/getCamaras|getFilteredData|getPMVs`), que
solo sirve cámaras, incidencias y paneles. El servicio propio del MITMA
(mapas.fomento.gob.es/MapaTrafico) se quedó en 2019: 2020 y 2021 están publicados pero vacíos.
El más nuevo con datos es el FeatureServer de la DGC de 2021.
"""
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
SERVICIO = ("https://services1.arcgis.com/nCKYwcSONQTkPA4K/arcgis/rest/services/"
            "Mapa_de_tr%C3%A1fico_de_la_DGC_2021/FeatureServer")
BASE = SERVICIO + "/2"  # Tramos2021
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
ANIO = 2021
FUENTE = "MITMA · DGC · Mapa de Tráfico %d (IMD por tramo)" % ANIO
LICENCIA = "Reutilización Ley 37/2007 con atribución (© MITMA)"
CAMPOS = ("carretera,tipo,provincia,pk_inicio,pk_fin,longitud,"
          "imd_total,imd_ligero,imd_pesado")
PAGINA = 1000

# tramos de IMD (vehículos/día): el color es el dato, no decoración
ESCALONES = ((2000, "#22c55e"), (5000, "#84cc16"), (10000, "#eab308"),
             (25000, "#f97316"), (50000, "#ef4444"))


def entero(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def color(imd):
    for tope, col in ESCALONES:
        if imd < tope:
            return col
    return "#7f1d1d"


def pide(offset, intentos=3):
    params = {"where": "1=1", "outFields": CAMPOS, "returnGeometry": "true", "outSR": 4326,
              "f": "geojson", "resultOffset": offset, "resultRecordCount": PAGINA,
              "maxAllowableOffset": 0.0015}
    url = "%s/query?%s" % (BASE, urllib.parse.urlencode(params))
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if i == intentos - 1:
                raise RuntimeError("falla IMD offset %s: %s" % (offset, e))
            time.sleep(2 + 3 * i)


def limpia_linea(coords, dec=4):
    """Redondea y quita vértices repetidos: la línea sigue siendo la misma, pesa la mitad."""
    out = []
    for c in coords:
        p = [round(c[0], dec), round(c[1], dec)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def main():
    features, offset = [], 0
    while True:
        d = pide(offset)
        lote = d.get("features") or []
        for f in lote:
            a, g = f.get("properties") or {}, f.get("geometry")
            if not g:
                continue
            if g["type"] == "LineString":
                coords = limpia_linea(g["coordinates"])
                if len(coords) < 2:
                    continue
                geom = {"type": "LineString", "coordinates": coords}
            elif g["type"] == "MultiLineString":
                partes = [limpia_linea(p) for p in g["coordinates"]]
                partes = [p for p in partes if len(p) >= 2]
                if not partes:
                    continue
                geom = {"type": "MultiLineString", "coordinates": partes}
            else:
                continue
            imd = entero(a.get("imd_total"))
            features.append({"type": "Feature", "geometry": geom, "properties": {
                "carretera": (a.get("carretera") or "").strip(),
                "tipo": (a.get("tipo") or "").strip(),
                "pk_inicio": a.get("pk_inicio"),
                "pk_fin": a.get("pk_fin"),
                "km": round(float(a.get("longitud") or 0), 2),
                "imd": imd,
                "imd_ligero": entero(a.get("imd_ligero")),
                "imd_pesado": entero(a.get("imd_pesado")),
                "provincia": (a.get("provincia") or "").strip().title() or None,
                "anio": ANIO,
                "color": color(imd or 0),
            }})
        print("  %d tramos" % len(features))
        if len(lote) < PAGINA:
            break
        offset += PAGINA
    if len(features) < 4000:
        raise SystemExit("solo %d tramos: el servicio no devolvió lo esperado, no se publica"
                         % len(features))

    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(DEST, "trafico_imd.geojson"), "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "generado": ahora, "fuente": FUENTE,
                   "licencia": LICENCIA, "features": features}, fh, ensure_ascii=False,
                  separators=(",", ":"))
    imds = [f["properties"]["imd"] for f in features if f["properties"]["imd"] is not None]
    imds.sort()
    km = sum(f["properties"]["km"] for f in features)
    rec = {
        "fichero": "datos/trafico_imd.geojson", "features": len(features), "fuente": FUENTE,
        "editor": "Ministerio de Transportes y Movilidad Sostenible · Dirección General "
                  "de Carreteras",
        "url": BASE, "licencia": LICENCIA, "descargado": ahora, "fecha_dato": "%d" % ANIO,
        "actualizado": "%d-12-31" % ANIO,
        "metodo": "query f=geojson sobre Tramos2021 del FeatureServer de la DGC, paginado de "
                  "1000 en 1000, simplificado a 0,0015° y redondeado a 4 decimales",
        "km_aforados": round(km, 1),
        "imd_mediana": imds[len(imds) // 2] if imds else None,
        "imd_maxima": imds[-1] if imds else None,
        "nota": "La IMD es una media anual: el MITMA la publica con años de retraso. La DGT no "
                "publica intensidades en abierto: su NAP trae incidencias, cámaras, paneles, "
                "radares y ZBE, y la API de su visor solo sirve getCamaras/getFilteredData/"
                "getPMVs. El servicio propio del MITMA (mapas.fomento.gob.es/MapaTrafico) se "
                "quedó en 2019; 2020 y 2021 están publicados y vacíos. Este FeatureServer de la "
                "DGC, de 2021, es el año más nuevo con datos nacionales.",
    }
    with open(os.path.join(DEST, "trafico_imd_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print("trafico_imd: %d tramos · %.0f km · IMD mediana %s · máx %s"
          % (len(features), km, rec["imd_mediana"], rec["imd_maxima"]))


if __name__ == "__main__":
    main()
