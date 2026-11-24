# -*- coding: utf-8 -*-
"""Patrimonio y servicios del IGN (SignA) -> GeoJSON para el visor.

El IGN publica cada figura por separado (castillos, BIC, museos, miradores…), así que el mismo
sitio aparece en varias capas: un castillo es BIC y a veces conjunto histórico. Aquí se descarga
todo y se deja **una chincheta por sitio**, con la categoría más concreta mandando y las demás
guardadas en `tambien`. Nada de tres puntos encima del mismo castillo.

Servicios: capas 1, 6, 7, 8, 9, 10, 11, 12, 13 y 26 de `Signa/03_construcciones_otros`.
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
BASE = "https://serviciosgis.ign.es/servicios/rest/services"
UA = {"User-Agent": "OpenInfraES/1.0 (visor de infraestructura)"}

# (id de capa, categoría, prioridad). Prioridad baja = manda cuando dos figuras caen en el mismo
# sitio: un castillo que además es BIC se publica como castillo.
PATRIMONIO = [
    (1, "Castillo", 1),
    (12, "Parador", 2),
    (26, "Museo", 3),
    (9, "Mirador", 4),
    (8, "Zona arqueológica", 5),
    (13, "Refugio de montaña", 6),
    (6, "Conjunto histórico", 7),
    (7, "Patrimonio de la Humanidad", 8),
    (11, "Faro", 9),
    (10, "BIC", 10),
]
SERVICIO_PATRIMONIO = "Signa/03_construcciones_otros"

# Un color por figura: el visor pinta con `colorCampo:"color"` y la leyenda agrupa por `categoria`.
COLORES = {
    "Castillo": "#f59e0b", "Parador": "#eab308", "Museo": "#a78bfa", "Mirador": "#34d399",
    "Zona arqueológica": "#f472b6", "Refugio de montaña": "#38bdf8",
    "Conjunto histórico": "#fb923c", "Patrimonio de la Humanidad": "#facc15",
    "Faro": "#22d3ee", "BIC": "#94a3b8",
}


def pide(url, timeout=180):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def capa(servicio, lid, tam=2000):
    """Descarga una capa entera paginando: el IGN corta en 2.000 y marca exceededTransferLimit."""
    salida, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "outSR": "4326",
                                    "f": "geojson", "resultOffset": offset,
                                    "resultRecordCount": tam})
        d = pide("%s/%s/MapServer/%d/query?%s" % (BASE, servicio, lid, q))
        fs = d.get("features") or []
        salida.extend(fs)
        if not d.get("exceededTransferLimit") or not fs:
            break
        offset += len(fs)
        if offset > 400000:
            break
    return salida


def limpia(s):
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def metros(a, b):
    dx = (a[0] - b[0]) * 111320.0 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 111320.0
    return math.hypot(dx, dy)


def clave(lat, lon, m=60.0):
    dlat = m / 111320.0
    dlon = m / (111320.0 * max(0.15, math.cos(math.radians(lat))))
    return (int(lat / dlat), int(lon / dlon))


def una_por_sitio(feats, radio=60.0):
    """Funde en el mismo punto las figuras que el IGN publica por duplicado."""
    rejilla, salida = {}, []
    for f in feats:
        lon, lat = f["geometry"]["coordinates"][:2]
        k = clave(lat, lon, radio)
        hallado = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for otro in rejilla.get((k[0] + di, k[1] + dj), []):
                    if metros((lon, lat), otro["geometry"]["coordinates"][:2]) <= radio:
                        hallado = otro
                        break
                if hallado:
                    break
            if hallado:
                break
        if hallado:
            p, q = hallado["properties"], f["properties"]
            otras = set((p.get("tambien") or "").split(" · ")) - {""}
            otras.add(q["categoria"])
            if q["prioridad"] < p["prioridad"]:
                otras.add(p["categoria"])
                p.update({"categoria": q["categoria"], "prioridad": q["prioridad"],
                          "color": q.get("color"),
                          "nombre": p.get("nombre") or q.get("nombre"),
                          "tipo_ign": q.get("tipo_ign")})
            if not p.get("nombre") and q.get("nombre"):
                p["nombre"] = q["nombre"]
            if not p.get("municipio") and q.get("municipio"):
                p["municipio"] = q["municipio"]
            otras.discard(p["categoria"])
            p["tambien"] = " · ".join(sorted(otras)) or None
            continue
        rejilla.setdefault(k, []).append(f)
        salida.append(f)
    for f in salida:
        f["properties"].pop("prioridad", None)
    return salida


def patrimonio():
    crudos, vistos = [], set()
    for lid, categoria, prioridad in PATRIMONIO:
        for f in capa(SERVICIO_PATRIMONIO, lid):
            if not f.get("geometry") or not f["geometry"].get("coordinates"):
                continue
            p = f.get("properties") or {}
            clave_unica = (categoria, limpia(p.get("nombre")), round(f["geometry"]["coordinates"][0], 4),
                           round(f["geometry"]["coordinates"][1], 4))
            if clave_unica in vistos:      # misma fila repetida en el volcado
                continue
            vistos.add(clave_unica)
            f["properties"] = {
                "nombre": limpia(p.get("nombre")), "categoria": categoria,
                "prioridad": prioridad, "tipo_ign": limpia(p.get("clase") or p.get("bic")),
                "municipio": limpia(p.get("municipio")), "provincia": limpia(p.get("provincia")),
                "color": COLORES.get(categoria, "#94a3b8"),
                "fuente": "IGN · SignA",
            }
            f["geometry"]["coordinates"] = [round(f["geometry"]["coordinates"][0], 5),
                                            round(f["geometry"]["coordinates"][1], 5)]
            crudos.append(f)
        print("  %-30s %6d" % (categoria, len(crudos)), flush=True)
    return una_por_sitio(crudos)


def simple(servicio, lid, titulo, categoria):
    feats = []
    for f in capa(servicio, lid):
        if not f.get("geometry") or not f["geometry"].get("coordinates"):
            continue
        p = f.get("properties") or {}
        f["properties"] = {
            "nombre": limpia(p.get("nombre")), "municipio": limpia(p.get("municipio")),
            "provincia": limpia(p.get("provincia")),
            "tipo": limpia(p.get("componente") or p.get("clase")),
            "fuente": "IGN · SignA",
        }
        f["geometry"]["coordinates"] = [round(f["geometry"]["coordinates"][0], 5),
                                        round(f["geometry"]["coordinates"][1], 5)]
        feats.append(f)
    return feats


def escribe(nombre, feats, meta):
    ruta = os.path.join(DATOS, nombre)
    json.dump({"type": "FeatureCollection", "features": feats}, open(ruta, "w"),
              ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(ruta) / 1024
    rec = dict(meta)
    rec.update({"features": len(feats), "kb": round(kb, 1), "fichero": nombre})
    json.dump(rec, open(os.path.join(DATOS, nombre.replace(".geojson", "_recibo.json")), "w"),
              ensure_ascii=False, indent=1)
    print("%-28s %6d  %7.1f KB" % (nombre, len(feats), kb), flush=True)


def relieve():
    """Cimas acotadas y alineaciones montañosas: la altitud es el dato que las hace útiles."""
    cimas = []
    for f in capa("Signa/07_orografia_paisaje", 1):
        if not f.get("geometry"):
            continue
        p = f.get("properties") or {}
        lon, lat = f["geometry"]["coordinates"][:2]
        cimas.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                      "properties": {"nombre": limpia(p.get("nombre")),
                                     "cota_m": p.get("cota_m") if isinstance(p.get("cota_m"), (int, float)) else None,
                                     "clase": limpia(p.get("clase")),
                                     "puerto": (limpia(p.get("puerto_carretera")) == "Sí"),
                                     "municipio": limpia(p.get("municipio")),
                                     "provincia": limpia(p.get("provincia")),
                                     "fuente": "IGN · SignA"}})
    sierras = []
    for f in capa("Signa/07_orografia_paisaje", 4):
        if not f.get("geometry"):
            continue
        p = f.get("properties") or {}
        g = f["geometry"]
        g["coordinates"] = [[[round(x, 5), round(y, 5)] for x, y in anillo] for anillo in g["coordinates"]] \
            if g.get("type") == "Polygon" else [[round(x, 5), round(y, 5)] for x, y in g["coordinates"]]
        sierras.append({"type": "Feature", "geometry": g,
                        "properties": {"nombre": limpia(p.get("nombre")),
                                       "jerarquia": limpia(p.get("jerarquia")),
                                       "fuente": "IGN · SignA"}})
    return cimas, sierras


def main():
    que = (sys.argv[1] if len(sys.argv) > 1 else "todo").lower()
    comun = {"editor": "Instituto Geográfico Nacional", "licencia": "CC BY 4.0",
             "url": "https://signa.ign.es/", "descargado": "2026-11-24"}
    if que in ("todo", "patrimonio"):
        escribe("patrimonio_ign.geojson", patrimonio(), dict(comun, **{
            "titulo": "Patrimonio cultural (IGN)",
            "fuente": "IGN · SignA",
            "metodo": "Capas 1, 6-13 y 26 de 03_construcciones_otros, fundidas por sitio a 60 m"}))
    if que in ("todo", "servicios"):
        # Las depuradoras del IGN no van al visor por su cuenta: son la base de ubicación de
        # `edar_unificar.py`, que las funde con I-ReWater y OSM en una sola capa.
        escribe("depuradoras_ign.geojson", simple("Signa/05_servicios_industria", 28,
                                                 "Depuradoras", "Depuradora"), dict(comun, **{
            "titulo": "Estaciones depuradoras de aguas residuales (IGN)",
            "fuente": "IGN · SignA", "metodo": "Capa 28 de 05_servicios_industria"}))
        escribe("hospitales_ign.geojson", simple("Signa/05_servicios_industria", 1,
                                                "Hospitales", "Hospital"), dict(comun, **{
            "titulo": "Hospitales (IGN)",
            "fuente": "IGN · SignA", "metodo": "Capa 1 de 05_servicios_industria"}))


    if que in ("todo", "relieve"):
        cimas, sierras = relieve()
        escribe("cimas_ign.geojson", cimas, dict(comun, **{
            "titulo": "Cimas y puntos acotados (IGN)", "fuente": "IGN · SignA",
            "metodo": "Capa 1 de 07_orografia_paisaje con cota, clase y municipio"}))
        escribe("sierras_ign.geojson", sierras, dict(comun, **{
            "titulo": "Alineaciones montañosas (IGN)", "fuente": "IGN · SignA",
            "metodo": "Capa 4 de 07_orografia_paisaje"}))


if __name__ == "__main__":
    main()
