#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aforos por estación (puntos) -> datos/trafico_estaciones.geojson.

Las comunidades que publican IMD como estaciones y no como tramos no caben en la capa de
líneas. Aquí van aparte, con su fuente y su año en cada punto:
  - Tenerife 2025: CSV de IMD unido al GeoJSON de estaciones por `estacion_id` (mismo Cabildo).
  - Cataluña 2022: Socrata del Departament de Territori, con latitud/longitud en el propio dato.

Sin clave. Nada de inventar: si una isla o una comunidad no publica, no aparece.
"""
import csv
import datetime
import io
import json
import os
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

TENERIFE_CSV = ("https://datos.tenerife.es/ckan/dataset/1717bda1-6b7b-43e0-be4e-e3ed060b8b97/"
                "resource/c3fe76ac-d91c-46cf-a765-46c3a741c6a9/download/"
                "intensidad-media-diaria-de-trafico-2025.csv")
TENERIFE_GEO = ("https://datos.tenerife.es/ckan/dataset/a114f82b-bb62-47e0-94bb-bebb484514a7/"
                "resource/27845ca5-4d5d-4976-89dd-038e5207db76/download/"
                "estaciones-de-control-de-aforo.geojson")
CATALUNA = ("https://analisi.transparenciacatalunya.cat/resource/xsvx-ym46.geojson"
            "?$where=any='2022'&$limit=50000")


def pide(url, intentos=3):
    for i in range(intentos):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read()
        except Exception:
            if i == intentos - 1:
                raise
            import time
            time.sleep(2 + 3 * i)


def entero(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return None


def color(imd):
    """Mismo semáforo que la capa de tramos: el color es el dato, no decoración."""
    if imd is None:
        return "#64748b"
    if imd < 2000:
        return "#22c55e"
    if imd < 5000:
        return "#84cc16"
    if imd < 10000:
        return "#eab308"
    if imd < 25000:
        return "#f97316"
    if imd < 50000:
        return "#ef4444"
    return "#7f1d1d"


def tenerife():
    """El CSV trae la IMD y el GeoJSON el punto: se cruzan por `estacion_id`."""
    filas = list(csv.DictReader(io.StringIO(pide(TENERIFE_CSV).decode("utf-8-sig", "replace"))))
    geo = json.loads(pide(TENERIFE_GEO))
    puntos = {}
    for f in geo.get("features") or []:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        if g.get("type") == "Point" and p.get("estacion_id") is not None:
            puntos[int(p["estacion_id"])] = g["coordinates"]
    salida, sin_punto = [], 0
    for fila in filas:
        eid = entero(fila.get("estacion_id"))
        imd = entero(fila.get("imd_total"))
        if eid is None or eid not in puntos:
            sin_punto += 1
            continue
        pesados = entero(fila.get("imd_pesados"))
        salida.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": puntos[eid]},
                       "properties": {
                           "ccaa": "Canarias", "provincia": "Santa Cruz de Tenerife",
                           "anio": 2025, "red": "Insular", "fuente": "Cabildo de Tenerife",
                           "carretera": (fila.get("carretera_codigo") or "").strip() or None,
                           "tipo": (fila.get("tramo_nombre") or "").strip() or None,
                           "estacion": (fila.get("estacion_nombre") or "").strip() or None,
                           "km": None, "imd": imd,
                           "pesados_pct": round(100.0 * pesados / imd) if (pesados is not None and imd) else None,
                           "color": color(imd)}})
    print("  Tenerife 2025: %d estaciones (%d sin punto)" % (len(salida), sin_punto))
    return salida


def cataluna():
    """Socrata devuelve el punto en latitud/longitud, no como geometría."""
    d = json.loads(pide(CATALUNA))
    salida = []
    for f in d.get("features") or []:
        p = f.get("properties") or {}
        try:
            lng, lat = float(p["longitud"]), float(p["latitud"])
        except Exception:
            continue
        imd = entero(p.get("imd"))
        pesados = None
        try:
            pesados = round(float(str(p["pesants"]).replace(",", ".")) * 100)   # viene en fracción
        except Exception:
            pass
        salida.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]},
                       "properties": {
                           "ccaa": "Cataluña", "provincia": p.get("poblaci") or None,
                           "anio": entero(p.get("any")), "red": "Autonómica",
                           "fuente": "Generalitat · SCT",
                           "carretera": p.get("carretera") or None,
                           "tipo": p.get("tipus_estaci") or None,
                           "estacion": p.get("definici_tram_origen") or None,
                           "km": float(p["long_tram"]) if p.get("long_tram") else None,
                           "imd": imd, "pesados_pct": pesados, "color": color(imd)}})
    print("  Cataluña 2022: %d estaciones" % len(salida))
    return salida


def main():
    features = tenerife() + cataluna()
    if len(features) < 500:
        raise SystemExit("solo %d estaciones: no se publica" % len(features))
    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(DEST, "trafico_estaciones.geojson"), "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "generado": ahora,
                   "fuente": "Cabildo de Tenerife (2025) y Generalitat de Catalunya · SCT (2022)",
                   "features": features}, fh, ensure_ascii=False, separators=(",", ":"))
    por_ccaa = {}
    for f in features:
        x = f["properties"]
        e = por_ccaa.setdefault(x["ccaa"], {"features": 0, "anios": set(), "fuentes": set()})
        e["features"] += 1
        e["anios"].add(x["anio"])
        e["fuentes"].add(x["fuente"])
    anios = {a for v in por_ccaa.values() for a in v["anios"] if a}
    rec = {"fichero": "datos/trafico_estaciones.geojson", "features": len(features),
           "fuente": "Cabildo de Tenerife · Servicio Técnico de Carreteras y Movilidad (2025) y "
                     "Generalitat de Catalunya · Servei Català de Trànsit (2022)",
           "url": TENERIFE_CSV + " · " + CATALUNA.split("?")[0],
           "licencia": "CC BY 4.0 (Tenerife) · Reutilización con atribución (Cataluña)",
           "descargado": ahora,
           "actualizado": "%d-12-31" % min(anios),
           "fecha_dato": " · ".join("%s %d" % (c, max(v["anios"]))
                                    for c, v in sorted(por_ccaa.items()) if v["anios"]),
           "metodo": "Tenerife: CSV de IMD 2025 cruzado por estacion_id con el GeoJSON de "
                     "estaciones del mismo portal. Cataluña: Socrata xsvx-ym46 filtrado a 2022, "
                     "punto desde latitud/longitud.",
           "campos": "ccaa, provincia, anio, red, fuente, carretera, tipo, estacion, imd, pesados_pct",
           "detalle": {c: {"features": v["features"], "anios": sorted(v["anios"]),
                           "fuentes": sorted(v["fuentes"])}
                       for c, v in sorted(por_ccaa.items())},
           "nota": "Canarias solo tiene Tenerife: Gran Canaria y el Gobierno de Canarias no "
                   "publican aforos vectoriales. Baleares no publica nada vectorial (solo un PDF "
                   "con el mapa de Mallorca). En Cataluña el dato es de 2022 y por estación: la "
                   "Generalitat no da IMD por tramo en abierto."}
    with open(os.path.join(DEST, "trafico_estaciones_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print("trafico_estaciones: %d estaciones · %s" % (len(features), rec["fecha_dato"]))


if __name__ == "__main__":
    main()
