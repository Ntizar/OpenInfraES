# -*- coding: utf-8 -*-
"""Redes de transporte del IGN (SignA) que no estaban en el visor.

Solo lo que **no se pisa** con lo que ya hay: las carreteras ya vienen de la RCE, los aeropuertos
estatales de Aena y las estaciones de Cercanías de Renfe/GTFS. Aquí entran los caminos de Santiago,
las vías verdes, el transporte por cable, las líneas de ferri y la aviación ligera (aeródromos y
helipuertos), que no estaban en ninguna capa.

Los puertos del IGN (588) y las estaciones de ferrocarril (3.603) se quedan fuera a propósito:
se solapan con las capas de Puertos del Estado y de Cercanías, y duplicar el mismo sitio es
justo lo que no queremos.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
BASE = "https://serviciosgis.ign.es/servicios/rest/services/Signa/02_redes_transporte/MapServer"
UA = {"User-Agent": "OpenInfraES/1.0 (visor de infraestructura)"}
HOY = "2026-11-24"


def pide(url, timeout=180):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                             timeout=timeout).read())


def capa(lid, tam=120):
    """El servicio NO pagina con `resultOffset` (500 a partir del segundo bloque): se piden los
    OBJECTID y se traen por tandas con `OBJECTID IN (...)`."""
    q = urllib.parse.urlencode({"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    d = pide("%s/%d/query?%s" % (BASE, lid, q))
    ids = d.get("objectIds") or []
    campo = d.get("objectIdFieldName") or "OBJECTID"
    salida = []
    for i in range(0, len(ids), tam):
        trozo = ids[i:i + tam]
        q = urllib.parse.urlencode({"where": "%s IN (%s)" % (campo, ",".join(str(x) for x in trozo)),
                                    "outFields": "*", "outSR": "4326", "f": "geojson"})
        for intento in range(3):
            try:
                salida.extend(pide("%s/%d/query?%s" % (BASE, lid, q)).get("features") or [])
                break
            except urllib.error.HTTPError:
                if intento == 2:
                    raise
    return salida


def limpia(v):
    if v is None:
        return None
    v = str(v).strip()
    return None if not v or v.lower() in ("desconocido", "no procede", "none") else v


def num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def redondea(g, dec=5):
    """Redondea anidando listas: vale para LineString, MultiPoint y Point por igual."""
    def rec(x):
        if isinstance(x, list):
            if x and isinstance(x[0], (int, float)):
                return [round(v, dec) for v in x]
            return [rec(v) for v in x]
        return x
    g["coordinates"] = rec(g["coordinates"])
    return g


def a_punto(g):
    """Point o MultiPoint del IGN -> lista de (lon, lat): el visor pinta puntos, no multipuntos."""
    if g.get("type") == "Point":
        return [g["coordinates"][:2]]
    c = g.get("coordinates") or []
    while c and isinstance(c[0], list) and isinstance(c[0][0], list):
        c = [p for bloque in c for p in bloque]
    return [p[:2] for p in c if isinstance(p, list) and len(p) >= 2]


def _rdp(pts, eps):
    """Douglas-Peucker iterativo: las líneas del IGN vienen con un vértice cada metro."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    pila = [(0, len(pts) - 1)]
    while pila:
        i, j = pila.pop()
        if j <= i + 1:
            continue
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        dx, dy = x2 - x1, y2 - y1
        norma = (dx * dx + dy * dy) ** 0.5
        peor, idx = -1.0, None
        for k in range(i + 1, j):
            x, y = pts[k]
            d = (abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norma) if norma else \
                ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            if d > peor:
                peor, idx = d, k
        if peor > eps:
            keep[idx] = True
            pila.append((i, idx))
            pila.append((idx, j))
    return [p for p, k in zip(pts, keep) if k]


def simplifica(g, eps=0.00012):
    """Redondea y simplifica (~13 m): vías verdes de 27 MB a menos de 2 MB sin perder el trazado."""
    t = g.get("type")
    if t == "LineString":
        g["coordinates"] = _rdp(g["coordinates"], eps)
    elif t == "MultiLineString":
        g["coordinates"] = [_rdp(anillo, eps) for anillo in g["coordinates"]]
    return redondea(g)


def escribe(nombre, feats, meta):
    ruta = os.path.join(DATOS, nombre)
    json.dump({"type": "FeatureCollection", "features": feats}, open(ruta, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(ruta) / 1024
    rec = dict(meta)
    rec.update({"features": len(feats), "kb": round(kb, 1), "descargado": HOY})
    json.dump(rec, open(os.path.join(DATOS, nombre.replace(".geojson", "_recibo.json")), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%-26s %6d  %8.1f KB" % (nombre, len(feats), kb), flush=True)


COMUN = {"editor": "Instituto Geográfico Nacional", "licencia": "CC BY 4.0",
         "url": "https://signa.ign.es/"}


def main():
    que = (sys.argv[1] if len(sys.argv) > 1 else "todo").lower()

    if que in ("todo", "vias-verdes"):
        feats = []
        for f in capa(19):
            p = f.get("properties") or {}
            feats.append({"type": "Feature", "geometry": simplifica(f["geometry"]),
                          "properties": {"nombre": limpia(p.get("nombre")),
                                         "recorrido": limpia(p.get("recorrido")),
                                         "firme": limpia(p.get("firme")),
                                         "longitud_km": num(p.get("longitud_km")),
                                         "id": limpia(p.get("id_vv")),
                                         "url": limpia(p.get("url_info")),
                                         "fuente": "IGN · SignA"}})
        escribe("vias_verdes_ign.geojson", feats, dict(COMUN, **{
            "titulo": "Vías verdes", "fuente": "IGN · SignA",
            "metodo": "Capa 19 de 02_redes_transporte, con firme y longitud"}))

    if que in ("todo", "santiago"):
        feats = []
        for f in capa(18):
            p = f.get("properties") or {}
            feats.append({"type": "Feature", "geometry": simplifica(f["geometry"]),
                          "properties": {"nombre": limpia(p.get("nombre_camino")),
                                         "agrupacion": limpia(p.get("nombre_agrupacion")),
                                         "longitud_km": num(p.get("longitud_camino_km")),
                                         "id": limpia(p.get("id_camino")),
                                         "url": limpia(p.get("url_info_camino")),
                                         "fuente": "IGN · SignA"}})
        escribe("caminos_santiago_ign.geojson", feats, dict(COMUN, **{
            "titulo": "Caminos de Santiago", "fuente": "IGN · SignA",
            "metodo": "Capa 18 de 02_redes_transporte, con agrupación y longitud"}))

    if que in ("todo", "cable"):
        colores = {"Teleférico": "#f472b6", "Telesilla": "#38bdf8", "Telesquí": "#c084fc"}
        feats = []
        for lid, tipo in ((1, "Teleférico"), (2, "Telesilla"), (3, "Telesquí")):
            for f in capa(lid):
                p = f.get("properties") or {}
                feats.append({"type": "Feature", "geometry": simplifica(f["geometry"]),
                              "properties": {"nombre": limpia(p.get("nombre")), "tipo": tipo,
                                             "color": colores[tipo],
                                             "fuente": "IGN · SignA"}})
        escribe("cable_ign.geojson", feats, dict(COMUN, **{
            "titulo": "Transporte por cable", "fuente": "IGN · SignA",
            "metodo": "Capas 1-3 de 02_redes_transporte (teleférico, telesilla, telesquí)"}))

    if que in ("todo", "ferris"):
        feats = []
        for f in capa(23):
            p = f.get("properties") or {}
            feats.append({"type": "Feature", "geometry": simplifica(f["geometry"]),
                          "properties": {"nombre": "Línea de ferri",
                                         "origen": limpia(p.get("destino1")),
                                         "destino": limpia(p.get("destino2")),
                                         "id": limpia(p.get("FerryID")),
                                         "fuente": "IGN · SignA"}})
        escribe("ferris_ign.geojson", feats, dict(COMUN, **{
            "titulo": "Líneas de ferri", "fuente": "IGN · SignA",
            "metodo": "Capa 23 de 02_redes_transporte"}))

    if que in ("todo", "aviacion"):
        colores = {"Aeródromo": "#94a3b8", "Helipuerto": "#2dd4bf"}
        feats = []
        for lid, tipo in ((6, "Aeródromo"), (7, "Helipuerto")):
            for f in capa(lid):
                p = f.get("properties") or {}
                for lon, lat in a_punto(f["geometry"]):
                    feats.append({"type": "Feature",
                                  "geometry": {"type": "Point",
                                               "coordinates": [round(lon, 5), round(lat, 5)]},
                                  "properties": {"nombre": limpia(p.get("nombre")),
                                                 "tipo": tipo, "uso": limpia(p.get("uso")),
                                                 "iata": limpia(p.get("cod_iata")),
                                                 "icao": limpia(p.get("cod_icao")),
                                                 "gestion": limpia(p.get("gestion")),
                                                 "color": colores[tipo],
                                                 "fuente": "IGN · SignA"}})
        escribe("aviacion_ligera_ign.geojson", feats, dict(COMUN, **{
            "titulo": "Aviación ligera · aeródromos y helipuertos", "fuente": "IGN · SignA",
            "metodo": "Capas 6 y 7 de 02_redes_transporte, multiPoint desdoblado en puntos"}))


if __name__ == "__main__":
    main()
