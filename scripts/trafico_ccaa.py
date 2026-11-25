#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IMD de tráfico de las redes autonómicas -> datos/trafico_ccaa.geojson.

Cada comunidad publica a su manera: la Comunitat Valenciana por WFS (GML, 2009-2025) y Aragón
por ArcGIS REST (DGA 2022 y MITMA 2021). Este script los funde en una sola capa con dos campos
que mandan: `ccaa` (para filtrar en el visor) y `anio` (para no disfrazar la fecha).

La DGT no publica intensidades y la IMD nacional del MITMA se quedó en 2021: lo fresco está en
las comunidades.
"""
import datetime
import json
import math
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
NS = {"ms": "http://mapserver.gis.umn.edu/mapserver", "gml": "http://www.opengis.net/gml/3.2",
      "wfs": "http://www.opengis.net/wfs/2.0"}

ESCALONES = ((2000, "#22c55e"), (5000, "#84cc16"), (10000, "#eab308"),
             (25000, "#f97316"), (50000, "#ef4444"))


def color(imd):
    for tope, col in ESCALONES:
        if (imd or 0) < tope:
            return col
    return "#7f1d1d"


def entero(v):
    try:
        return int(float(str(v).replace("%", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None


def largo_km(partes):
    """Longitud real del tramo a partir de sus vertices: `SHAPE_LENG` de la DGA viene a 0 y
    `LONGITUD` del MITMA ya esta en km, asi que se mide aqui y no se depende de ninguno."""
    total = 0.0
    for tramo in partes:
        for (x1, y1), (x2, y2) in zip(tramo, tramo[1:]):
            dx = (x2 - x1) * 111.32 * math.cos(math.radians((y1 + y2) / 2))
            dy = (y2 - y1) * 110.57
            total += math.hypot(dx, dy)
    return round(total, 2) or None


def limpia(coords, dec=4, paso=0.0005):
    """Redondea y adelgaza: un vertice cada ~50 m basta para leer una carretera a zoom de
    provincia, y el original traia uno cada 5 m (10 MB de GeoJSON por dos comunidades)."""
    out = []
    for c in coords:
        p = [round(c[0], dec), round(c[1], dec)]
        if not out:
            out.append(p)
            continue
        if abs(p[0] - out[-1][0]) < paso and abs(p[1] - out[-1][1]) < paso:
            continue
        out.append(p)
    if len(coords) > 1:
        fin = [round(coords[-1][0], dec), round(coords[-1][1], dec)]
        if len(out) > 1 and out[-1] != fin:
            out[-1] = fin
        if len(out) < 2:      # tramo mas corto que el paso: se queda con sus dos extremos
            ini = [round(coords[0][0], dec), round(coords[0][1], dec)]
            if ini != fin:
                out = [ini, fin]
    return out


# ---------------------------------------------------------------- Comunitat Valenciana (WFS)
CV = "https://terramapas.icv.gva.es/0902_Aforos"
CV_ANIO = 2025


def valencia():
    """WFS 2.0 de MapServer: solo devuelve GML, y con el orden lat/lon (EPSG:4326 OGC)."""
    salida, ini, lote = [], 0, 1000
    while True:
        p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
             "typeNames": "ms:Aforos%d" % CV_ANIO, "count": str(lote),
             "startIndex": str(ini), "srsName": "EPSG:4326"}
        url = CV + "?" + urllib.parse.urlencode(p)
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                     timeout=180).read()
        root = ET.fromstring(raw)
        n = 0
        for miembro in root.findall("wfs:member", NS):
            for feat in miembro:
                n += 1
                props = {c.tag.split("}")[1]: (c.text or "").strip() for c in feat
                         if not c.tag.endswith("boundedBy") and not c.tag.endswith("msGeometry")}
                geom = None
                for c in feat:
                    if not c.tag.endswith("msGeometry"):
                        continue
                    lineas = [e for e in c.iter() if e.tag.endswith("LineString")]
                    partes = []
                    for ln in lineas:
                        ps = [e for e in ln.iter() if e.tag.endswith("posList") or e.tag.endswith("pos")]
                        coords = []
                        for e in ps:
                            vals = (e.text or "").split()
                            if e.tag.endswith("posList"):
                                for i in range(0, len(vals) - 1, 2):
                                    coords.append([float(vals[i + 1]), float(vals[i])])
                            elif len(vals) >= 2:
                                coords.append([float(vals[1]), float(vals[0])])
                        coords = limpia(coords)
                        if len(coords) >= 2:
                            partes.append(coords)
                    if len(partes) == 1:
                        geom = {"type": "LineString", "coordinates": partes[0]}
                    elif partes:
                        geom = {"type": "MultiLineString", "coordinates": partes}
                if not geom:
                    continue
                imd = entero(props.get("imd"))
                salida.append({"type": "Feature", "geometry": geom, "properties": {
                    "ccaa": "Comunitat Valenciana", "anio": CV_ANIO,
                    "carretera": props.get("carretera") or None,
                    "tipo": props.get("tipo_calzada") or None,
                    "titular": props.get("titular") or None,
                    "pk_inicio": props.get("pk_inicio"), "pk_fin": props.get("pk_fin"),
                    "km": round(float(props.get("longitudm_real") or 0) / 1000, 2) or None,
                    "imd": imd, "pesados_pct": entero(props.get("vehiculo_pesados_zp")),
                    "color": color(imd)}})
        print("  CV: %d acumulados" % len(salida))
        if n < lote:
            break
        ini += lote
    return salida


# ---------------------------------------------------------------- Aragón (ArcGIS REST)
AR = ("https://idearagon.aragon.es/servicios/rest/services/CARRETERAS/"
      "AFOROS_ARAGON_GENERICO/MapServer")
AR_CAPAS = ((1, "DGA", 2022), (5, "MITMA", 2021))


def aragon():
    salida = []
    for capa, red, anio in AR_CAPAS:
        base = "%s/%d/query" % (AR, capa)
        ini = 0
        while True:
            # Esta capa NO soporta f=geojson (error 400): se pide Esri JSON en 4326 y se
            # convierte aqui. Es el mismo dato, con `paths` en vez de `coordinates`.
            p = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": 4326,
                 "f": "json", "resultOffset": ini, "resultRecordCount": 1000}
            d = json.load(urllib.request.urlopen(
                urllib.request.Request(base + "?" + urllib.parse.urlencode(p),
                                       headers={"User-Agent": UA}), timeout=180))
            lote = d.get("features") or []
            for f in lote:
                a = f.get("attributes") or {}
                paths = (f.get("geometry") or {}).get("paths") or []
                crudo = [[[c[0], c[1]] for c in tramo] for tramo in paths]
                crudo = [x for x in crudo if len(x) >= 2]
                if not crudo:
                    continue
                # La longitud se mide sobre el trazado original, no sobre el adelgazado:
                # quitar vertices recorta metros y el km dejaria de cuadrar con el del aforo.
                km = largo_km(crudo)
                partes = [x for x in (limpia(t) for t in crudo) if len(x) >= 2]
                if not partes:
                    continue
                geom = ({"type": "LineString", "coordinates": partes[0]} if len(partes) == 1
                        else {"type": "MultiLineString", "coordinates": partes})
                imd = entero(a.get("IMD") if red == "DGA" else a.get("IMD_TOTAL"))
                pct = entero(a.get("PORCEN_PES"))
                if pct is None and imd and entero(a.get("IMD_PESADO")) is not None:
                    pct = round(100.0 * entero(a.get("IMD_PESADO")) / imd)
                salida.append({"type": "Feature", "geometry": geom, "properties": {
                    "ccaa": "Aragón", "anio": anio,
                    "carretera": (a.get("CTRA") or a.get("CARRETERA") or "").strip() or None,
                    "tipo": (a.get("DESCRIPCIO") or a.get("TIPO") or None),
                    "titular": red,
                    "pk_inicio": a.get("PKI") if red == "DGA" else a.get("PK_INICIO"),
                    "pk_fin": a.get("PKF") if red == "DGA" else a.get("PK_FIN"),
                    "km": km,
                    "imd": imd,
                    "pesados_pct": pct,
                    "color": color(imd)}})
            print("  AR %s %d: %d" % (red, anio, len(salida)))
            if len(lote) < 1000:
                break
            ini += 1000
    return salida


def main():
    features = valencia() + aragon()
    if len(features) < 800:
        raise SystemExit("solo %d tramos autonómicos: no se publica" % len(features))
    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(DEST, "trafico_ccaa.geojson"), "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "generado": ahora,
                   "fuente": "Redes autonómicas de carreteras (GVA, DGA)", "features": features},
                  fh, ensure_ascii=False, separators=(",", ":"))
    por_ccaa = {}
    for f in features:
        c = f["properties"]["ccaa"]
        e = por_ccaa.setdefault(c, {"features": 0, "anios": set(), "km": 0.0})
        e["features"] += 1
        e["anios"].add(f["properties"]["anio"])
        e["km"] += f["properties"]["km"] or 0
    rec = {"fichero": "datos/trafico_ccaa.geojson", "features": len(features),
           "fuente": "Comunitat Valenciana (GVA · ICV) y Aragón (DGA)",
           "editor": "GVA · Institut Cartogràfic Valencià / Gobierno de Aragón · IDEARAGON",
           "url": "https://terramapas.icv.gva.es/0902_Aforos · "
                  "https://idearagon.aragon.es/servicios/rest/services/CARRETERAS/"
                  "AFOROS_ARAGON_GENERICO/MapServer",
           "licencia": "Reutilización con atribución (Ley 37/2007) · GVA y DGA",
           "descargado": ahora,
           "actualizado": "%d-12-31" % max(max(v["anios"]) for v in por_ccaa.values()),
           "fecha_dato": ", ".join("%s %s" % (c, "-".join(sorted(str(a) for a in v["anios"])))
                                   for c, v in por_ccaa.items()),
           "metodo": "CV: WFS 2.0 ms:Aforos2025 en GML (posList lat/lon). AR: query f=geojson "
                     "sobre AFOROS_ARAGON_GENERICO/1 (DGA 2022) y /5 (MITMA 2021). "
                     "Simplificado a 0,0015° y redondeado a 4 decimales.",
           "detalle": {c: {"features": v["features"], "anios": sorted(str(a) for a in v["anios"]),
                           "km": round(v["km"], 1)} for c, v in por_ccaa.items()},
           "nota": "Continuación de trafico-imd (MITMA 2021): aquí manda la comunidad, y el año "
                   "va por feature para no mezclar 2025 con 2022 sin avisar."}
    with open(os.path.join(DEST, "trafico_ccaa_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print("trafico_ccaa: %d tramos · %s" % (len(features), rec["fecha_dato"]))


if __name__ == "__main__":
    main()
