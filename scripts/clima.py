# -*- coding: utf-8 -*-
"""Clima · observación actual por provincia y campo de viento (Open-Meteo).

**Qué es y qué no es.** Son las condiciones *de ahora* en cada provincia (52 polígonos, el
shape de `nuts3_es.geojson`, consultado en su centroide), servidas por Open-Meteo a partir de
los modelos ICON (DWD) y GFS, con paso de 15 minutos. No es una estación oficial de AEMET ni un parte: es un modelo interpolado, y la
ficha lo dice. Los avisos oficiales están en la capa `aemet-zonas`.

**Por qué Open-Meteo.** AEMET OpenData exige clave para observación; Open-Meteo no pide clave,
permite 52 coordenadas en una sola llamada y publica con licencia CC BY 4.0. Se atribuye en la
capa y en el recibo.

Salida:
  datos/clima_provincias.geojson   52 polígonos · temperatura, sensación, humedad, lluvia, viento
  datos/clima_viento.geojson       rejilla interpolada (IDW) en flechas con punta
  datos/clima_recibo.json          procedencia, licencia y hora del modelo

    python scripts/clima.py
"""
import datetime
import json
import math
import os
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
URL = "https://api.open-meteo.com/v1/forecast"
VARIABLES = ["temperature_2m", "apparent_temperature", "relative_humidity_2m",
             "precipitation", "wind_speed_10m", "wind_direction_10m", "weather_code"]

# WMO 4677 → castellano. Los códigos que no aparezcan salen como "sin dato", no como un número.
TIEMPO = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Niebla", 48: "Niebla helada",
    51: "Llovizna débil", 53: "Llovizna", 55: "Llovizna fuerte",
    56: "Llovizna helada", 57: "Llovizna helada fuerte",
    61: "Lluvia débil", 63: "Lluvia", 65: "Lluvia fuerte",
    66: "Lluvia helada", 67: "Lluvia helada fuerte",
    71: "Nieve débil", 73: "Nieve", 75: "Nieve fuerte", 77: "Granos de nieve",
    80: "Chubascos débiles", 81: "Chubascos", 82: "Chubascos fuertes",
    85: "Chubascos de nieve", 86: "Chubascos de nieve fuertes",
    95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta con granizo fuerte",
}
# Los tramos son los de la leyenda del visor: el color no se inventa en el cliente.
# Tramos de 5 °C, no de 8: con los de 8 casi toda España caía en "frío" o "fresco" y el coropleta
# se veía de dos colores. El rango útil de un día español cabe entero entre helado y caluroso.
TRAMOS_T = [(-99, 0, "helado", "#818cf8"), (0, 5, "muy frío", "#6366f1"),
            (5, 10, "frío", "#3b82f6"), (10, 15, "fresco", "#22d3ee"),
            (15, 20, "suave", "#a3e635"), (20, 25, "templado", "#fbbf24"),
            (25, 30, "cálido", "#fb923c"), (30, 99, "caluroso", "#f97316")]
# Rampa de aviso (cian -> verde -> ambar -> naranja -> rojo), no cinco azules: con #7dd3fc,
# #38bdf8 y #22d3ee el campo entero se veia del mismo color y el tramo solo se sabia por la ficha.
TRAMOS_V = [(0, 10, "flojo", "#67e8f9"), (10, 20, "moderado", "#4ade80"),
            (20, 40, "fuerte", "#fbbf24"), (40, 60, "muy fuerte", "#fb923c"),
            (60, 999, "temporal", "#ef4444")]


def tramo(valor, tabla):
    for lo, hi, nombre, color in tabla:
        if lo <= valor < hi:
            return nombre
    return tabla[-1][2]


def color_tramo(valor, tabla):
    for lo, hi, _n, color in tabla:
        if lo <= valor < hi:
            return color
    return tabla[-1][3]


def area_y_centroide(anillo):
    """Área y centroide de un anillo (fórmula del polígono). Fuera de rango = área 0."""
    a = cx = cy = 0.0
    n = len(anillo)
    for i in range(n - 1):
        x1, y1 = anillo[i][0], anillo[i][1]
        x2, y2 = anillo[i + 1][0], anillo[i + 1][1]
        cruz = x1 * y2 - x2 * y1
        a += cruz
        cx += (x1 + x2) * cruz
        cy += (y1 + y2) * cruz
    a *= 0.5
    if abs(a) < 1e-12:
        return 0.0, anillo[0][0], anillo[0][1]
    return abs(a), cx / (6 * a), cy / (6 * a)


def centroide_principal(geom):
    """Centroide del polígono de mayor área: una provincia con islas se ancla en la isla grande.

    Con la media de todos los vértices, Santa Cruz de Tenerife caería en el mar entre islas y
    Baleares en mitad del canal. El polígono mayor es el que representa a la provincia.
    """
    tipo = geom.get("type")
    poligonos = [geom["coordinates"]] if tipo == "Polygon" else geom.get("coordinates") or []
    mejor = None
    for poli in poligonos:
        if not poli:
            continue
        a, x, y = area_y_centroide(poli[0])
        if mejor is None or a > mejor[0]:
            mejor = (a, x, y)
    return (mejor[1], mejor[2]) if mejor else None


def pide(puntos):
    """Una sola llamada con todas las coordenadas: Open-Meteo devuelve la lista en orden."""
    lat = ",".join("%.4f" % p[1] for p in puntos)
    lon = ",".join("%.4f" % p[0] for p in puntos)
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "current": ",".join(VARIABLES),
        "timezone": "Europe/Madrid", "wind_speed_unit": "kmh",
    }, safe=",")
    req = urllib.request.Request(URL + "?" + q, headers={
        "User-Agent": "OpenInfraES/1.0 (+https://github.com/Ntizar/OpenInfraES)",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read())
    return d if isinstance(d, list) else [d]


def rejilla_viento(provincias, islas=False):
    """Campo de viento interpolado sobre una rejilla regular, en barbas de 2 vértices.

    IDW sobre los puntos, pero promediando el VECTOR (u, v) y no el ángulo: 350° y 10° son
    vientos casi iguales y su media aritmética daría 180°, justo el contrario. La barba mide lo
    que sopla (0,10°–0,40°) y apunta hacia donde va, no de donde viene.

    Canarias va en su propia rejilla: sus 22 °C y su alisio no pueden interpolar el golfo de
    Cádiz, y a 1.300 km la IDW les daría el mismo peso que a Huelva.
    """
    fuente = []
    for p in provincias:
        v = p["viento_kmh"]
        if v is None or p["viento_dir"] is None:
            continue
        rad = math.radians(p["viento_dir"])
        # dirección meteorológica = de donde viene; el vector apunta hacia donde va
        fuente.append((p["lon"], p["lat"], v, -math.sin(rad), -math.cos(rad)))
    if len(fuente) < 2:
        return []

    fechas = []
    if islas:
        paso_lon, paso_lat = 0.55, 0.45
        lon0, lon1, lat0, lat1 = -18.30, -13.20, 27.50, 29.50
    else:
        paso_lon, paso_lat = 0.90, 0.70
        lon0, lon1, lat0, lat1 = -9.80, 3.80, 35.90, 43.95
    lon = lon0
    while lon <= lon1:
        lat = lat0
        while lat <= lat1:
            sw = sx = sy = sv = 0.0
            for flon, flat, v, ux, uy in fuente:
                d2 = (lon - flon) ** 2 + (lat - flat) ** 2
                w = 1e6 if d2 < 1e-6 else 1.0 / (d2 ** 1.6)
                sw += w
                sx += w * ux
                sy += w * uy
                sv += w * v
            if sw <= 0:
                lat += paso_lat
                continue
            ux, uy, v = sx / sw, sy / sw, sv / sw
            if abs(ux) < 1e-9 and abs(uy) < 1e-9:
                lat += paso_lat
                continue
            rumbo = math.degrees(math.atan2(ux, uy))       # 0 = norte, 90 = este
            largo = 0.10 + min(1.0, v / 60.0) * 0.30
            coslat = max(0.3, math.cos(math.radians(lat)))

            def desplaza(factor, rb):
                """Paso en grados a lo largo de `rb`, corrigiendo la longitud por el paralelo."""
                return (largo * factor * math.sin(math.radians(rb)) / coslat,
                        largo * factor * math.cos(math.radians(rb)))

            # FLECHA, no rayita: cuerpo hasta la punta y dos alas de 28° que la cierran. Antes
            # eran dos vértices y no se sabía hacia dónde soplaba; el dato estaba bien, faltaba
            # la punta. Las alas van a 152° y 208° del rumbo (es decir, 28° respecto al cuerpo).
            dx, dy = desplaza(1.0, rumbo)
            ax, ay = desplaza(0.42, rumbo + 152)
            bx, by = desplaza(0.42, rumbo - 152)
            px, py = lon + dx, lat + dy
            fechas.append({
                "type": "Feature",
                # 2 decimales ≈ 1 km: una flecha mide 20-40 km, redondear más no se ve y
                # engorda el fichero que se descarga el visitante
                "geometry": {"type": "MultiLineString", "coordinates": [
                    [[round(lon, 2), round(lat, 2)], [round(px, 2), round(py, 2)]],
                    [[round(lon + ax, 2), round(lat + ay, 2)], [round(px, 2), round(py, 2)],
                     [round(lon + bx, 2), round(lat + by, 2)]]]},
                "properties": {
                    "viento_kmh": round(v, 1),
                    "rumbo": int(round(rumbo)) % 360,
                    "tramo": tramo(v, TRAMOS_V),
                    "color": color_tramo(v, TRAMOS_V),
                },
            })
            lat += paso_lat
        lon += paso_lon
    return fechas


def main():
    nuts = json.load(open(os.path.join(DEST, "nuts3_es.geojson"), encoding="utf-8"))
    sitios = []
    for f in nuts.get("features", []):
        p = f.get("properties") or {}
        c = centroide_principal(f.get("geometry") or {})
        if not c:
            continue
        sitios.append({"provincia": p.get("nombre") or "?", "cod_ine": p.get("cod_ine"),
                       "lon": c[0], "lat": c[1], "geom": f.get("geometry")})
    sitios.sort(key=lambda s: s["provincia"])
    if len(sitios) < 40:
        raise SystemExit("solo %d provincias con centroide: revisa nuts3_es.geojson" % len(sitios))

    respuestas = pide([(s["lon"], s["lat"]) for s in sitios])
    if len(respuestas) != len(sitios):
        raise SystemExit("Open-Meteo devolvio %d respuestas para %d provincias"
                         % (len(respuestas), len(sitios)))

    provincias, feats = [], []
    for s, r in zip(sitios, respuestas):
        c = r.get("current") or {}
        t = c.get("temperature_2m")
        v = c.get("wind_speed_10m")
        props = {
            "nombre": s["provincia"],
            "cod_ine": s["cod_ine"],
            "temperatura": t,
            "sensacion": c.get("apparent_temperature"),
            "humedad": c.get("relative_humidity_2m"),
            "lluvia_mm": c.get("precipitation"),
            "viento_kmh": v,
            "viento_dir": c.get("wind_direction_10m"),
            "tiempo": TIEMPO.get(c.get("weather_code"), "Sin dato"),
            "tramo": tramo(t, TRAMOS_T) if isinstance(t, (int, float)) else "sin dato",
            "color": color_tramo(t, TRAMOS_T) if isinstance(t, (int, float)) else "#64748b",
            "tramo_viento": tramo(v, TRAMOS_V) if isinstance(v, (int, float)) else "sin dato",
            "hora": c.get("time"),
            "modelo": "Open-Meteo · ICON (DWD) / GFS",
        }
        provincias.append({"lon": s["lon"], "lat": s["lat"], "viento_kmh": v,
                           "viento_dir": c.get("wind_direction_10m"),
                           "cod_ine": s["cod_ine"]})
        # El polígono de la provincia, no un punto en su centroide: el dato es de la provincia
        # entera y el mapa ya trae la forma, así que se pinta el contorno relleno de color. Con
        # un punto en el centroide, dos provincias vecinas del mismo tono se leían como una sola.
        feats.append({"type": "Feature",
                      "geometry": s["geom"],
                      "properties": props})

    canarias = {"35", "38"}
    peninsula = [p for p in provincias if p["cod_ine"] not in canarias]
    islas = [p for p in provincias if p["cod_ine"] in canarias]
    barbas = rejilla_viento(peninsula) + rejilla_viento(islas, islas=True)
    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hora_modelo = (respuestas[0].get("current") or {}).get("time") or ""

    def escribe(nombre, features, extra):
        ruta = os.path.join(DEST, nombre + ".geojson")
        d = {"type": "FeatureCollection",
             "generado": ahora,
             "fuente": "Open-Meteo (ICON DWD / GFS)",
             "licencia": "CC BY 4.0 · Open-Meteo",
             "hora_modelo": hora_modelo,
             "features": features}
        json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False,
                  separators=(",", ":"))
        rec = {"fichero": "datos/%s.geojson" % nombre, "features": len(features),
               "descargado": ahora, "actualizado": hora_modelo,
               "fuente": "Open-Meteo", "url": "https://open-meteo.com/",
               "licencia": "CC BY 4.0", "metodo": extra}
        json.dump(rec, open(os.path.join(DEST, nombre + "_recibo.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    escribe("clima_provincias", feats,
            "modelo ICON/GFS por provincia sobre el shape de nuts3_es.geojson "
            "(consulta en el centroide, pintado en el polígono), paso 15 min")
    escribe("clima_viento", barbas,
            "interpolacion IDW vectorial sobre rejilla de 0,90° x 0,70°, barbas de 2 vertices")

    # recibo único de la capa, con el resumen que se cita en la ficha
    temps = [f["properties"]["temperatura"] for f in feats
             if isinstance(f["properties"]["temperatura"], (int, float))]
    caliente = max(feats, key=lambda f: f["properties"]["temperatura"]
                   if isinstance(f["properties"]["temperatura"], (int, float)) else -99)
    frio = min(feats, key=lambda f: f["properties"]["temperatura"]
               if isinstance(f["properties"]["temperatura"], (int, float)) else 99)
    rec = {
        "fuente": "Open-Meteo",
        "editor": "Open-Meteo (modelos ICON del DWD y GFS de la NOAA)",
        "url": "https://open-meteo.com/",
        "licencia": "CC BY 4.0",
        "descargado": ahora,
        "actualizado": hora_modelo,
        "features": len(feats),
        "barbas": len(barbas),
        "provincias": len(feats),
        "temperatura_media": round(sum(temps) / len(temps), 1) if temps else None,
        "mas_caliente": {"provincia": caliente["properties"]["nombre"],
                         "temperatura": caliente["properties"]["temperatura"]},
        "mas_frio": {"provincia": frio["properties"]["nombre"],
                     "temperatura": frio["properties"]["temperatura"]},
        "nota": "Modelo interpolado, no estación oficial. Los avisos oficiales son la capa aemet-zonas.",
        "metodo": "una llamada por lotes a /v1/forecast (current) y rejilla IDW vectorial propia",
    }
    json.dump(rec, open(os.path.join(DEST, "clima_recibo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("clima: %d provincias · %d flechas · %.1f °C de media · %s %.1f °C / %s %.1f °C"
          % (len(feats), len(barbas), rec["temperatura_media"] or 0,
             rec["mas_caliente"]["provincia"], rec["mas_caliente"]["temperatura"] or 0,
             rec["mas_frio"]["provincia"], rec["mas_frio"]["temperatura"] or 0))


if __name__ == "__main__":
    main()
