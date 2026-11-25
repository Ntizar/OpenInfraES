#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intensidad media diaria (IMD) por tramo de la Red del Estado -> datos/trafico_imd.geojson.

Fuente: Mapa de Tráfico del MITMA (servicio ArcGIS del visor oficial). La DGT no publica
intensidades en abierto: su catálogo (NAP) tiene incidencias, cámaras, paneles, radares y ZBE,
pero ningún conjunto de aforos. El último año servido con datos en este servicio es 2019;
los servicios de 2020 y 2021 están publicados pero vacíos.
"""
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
BASE = ("https://mapas.fomento.gob.es/arcgis/rest/services/MapaTrafico/Mapa2019web"
        "/MapServer/2")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
ANIO = 2019
FUENTE = "MITMA · Mapa de Tráfico (IMD por tramo)"
LICENCIA = "Reutilización Ley 37/2007 con atribución (© MITMA)"
CAMPOS = "Nombre,Tipo_de_ca,Pk_inicio,Pk_fin,Longitud,IMD_total,IMD_ligero,IMD_pesado,Provincia"
PAGINA = 1000

# tramos de IMD (vehículos/día): el color es el dato, no decoración
ESCALONES = ((2000, "#22c55e"), (5000, "#84cc16"), (10000, "#eab308"),
             (25000, "#f97316"), (50000, "#ef4444"))


def color(imd):
    for tope, col in ESCALONES:
        if imd < tope:
            return col
    return "#7f1d1d"


def pide(offset, intentos=3):
    params = {"where": "1=1", "outFields": CAMPOS, "returnGeometry": "true", "outSR": "4326",
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
            imd = a.get("IMD_total")
            try:
                imd = int(imd) if imd is not None else None
            except (TypeError, ValueError):
                imd = None
            features.append({"type": "Feature", "geometry": geom, "properties": {
                "carretera": (a.get("Nombre") or "").strip(),
                "tipo": (a.get("Tipo_de_ca") or "").strip(),
                "pk_inicio": a.get("Pk_inicio"),
                "pk_fin": a.get("Pk_fin"),
                "km": round(float(a.get("Longitud") or 0), 2),
                "imd": imd,
                "imd_ligero": a.get("IMD_ligero"),
                "imd_pesado": a.get("IMD_pesado"),
                "provincia": (a.get("Provincia") or "").strip().title() or None,
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
        "editor": "Ministerio de Transportes y Movilidad Sostenible",
        "url": "https://mapas.fomento.gob.es/arcgis/rest/services/MapaTrafico/"
               "Mapa2019web/MapServer/2",
        "licencia": LICENCIA, "descargado": ahora, "fecha_dato": "%d (año del aforo)" % ANIO,
        "metodo": "query f=geojson sobre Mapa2019web/MapServer/2 (Tramos), paginado de 1000 en "
                  "1000, simplificado a 0,0015° y redondeado a 4 decimales",
        "km_aforados": round(km, 1),
        "imd_mediana": imds[len(imds) // 2] if imds else None,
        "imd_maxima": imds[-1] if imds else None,
        "nota": "La DGT no publica intensidades en abierto (su NAP tiene incidencias, cámaras, "
                "paneles, radares y ZBE). El Mapa de Tráfico del MITMA es el dato oficial de "
                "IMD; en este servicio el último año con datos es 2019: las capas de 2020 y 2021 "
                "están publicadas pero vacías.",
    }
    with open(os.path.join(DEST, "trafico_imd_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print("trafico_imd: %d tramos · %.0f km · IMD mediana %s · máx %s"
          % (len(features), km, rec["imd_mediana"], rec["imd_maxima"]))


if __name__ == "__main__":
    main()
