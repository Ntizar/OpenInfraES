# -*- coding: utf-8 -*-
"""Capas del OGC API Features del MITECO.

Por que esta via y no un WMS: el catalogo CKAN del ministerio anuncia estos conjuntos como
datos de alto valor (HVD, Reglamento UE 2023/138) y su GeoServer los sirve en GeoJSON, que es
lo que el visor sabe leer sin intermediarios. Medido el 2026-11-23:

  GET https://gis.miteco.gob.es/geoserver/ogc/features/v1/collections  -> 200, 534 colecciones
  sin clave, con CORS abierto y respuesta por debajo del segundo.

Regla de la casa: si la descarga se corta, NO se escribe el recibo. Un recibo con mas objetos
de los guardados es peor que no tener recibo.

Uso:
  python scripts/miteco_ogc.py            # todas las capas
  python scripts/miteco_ogc.py aforos     # una
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://gis.miteco.gob.es/geoserver/ogc/features/v1"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
UA = {"User-Agent": "OpenInfraES/1.0 (datos abiertos MITECO; contacto en el repo)"}
LOTE = 1000          # el servidor responde bien hasta 1.000; con 10.000 se cae por tiempo

# capa -> donde esta la coleccion, como se llama el fichero y como se traducen las propiedades
# (la ficha del visor pinta TODAS las propiedades del objeto: 45 columnas del original serian
# ilegibles, asi que se queda lo que se lee y se tira el resto)
CAPAS = {
    "aforos": {
        "coleccion": "agua:Estaciones_Aforos",
        "titulo": "Estaciones de aforo (SAIH-ROEA)",
        "campos": {"nom_anuario": "nombre", "rio": "rio", "organismo_cuenca_visor": "organismo",
                   "tipo_estacion": "tipo", "situacion_estacion": "situacion",
                   "termino_municipal": "municipio", "provincia": "provincia",
                   "cota_z": "cota_m", "ano_inicio_medidas": "inicio",
                   "cod_saih": "codigo_saih", "cod_dma": "demarcacion",
                   "sensor_1": "sensor", "transm_1": "transmision"},
    },
    "canales-miteco": {
        "coleccion": "agua:canales",
        "titulo": "Red de canales principales",
        # 10 MB de lineas sin tocar: Douglas-Peucker a ~22 m lo deja en algo que el navegador
        # carga sin pensarlo. Se declara en el recibo (campo simplificado_m).
        "simplificar": 0.0002,
        "campos": {"nom_canal": "nombre", "toma": "toma", "cod_demar": "demarcacion",
                   "cod_canal": "codigo_canal"},
    },
    "calidad-aire-estaciones": {
        "coleccion": "evaluacionambiental:ca_red_estaciones",
        "titulo": "Estaciones de calidad del aire",
        "campos": {"nombre": "nombre", "cod_nacional": "codigo", "cod_europeo": "codigo_europeo",
                   "municipio": "municipio"},
    },
}

VACIOS = ("", "None", "none", "null", "NULL", "-")


def pedir(url, intentos=3):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == intentos - 1:
                raise
            print("      reintento %d (%s)" % (i + 1, str(e)[:70]))
            time.sleep(2 * (i + 1))


def limpia(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = " ".join(str(v).split())
    return None if s in VACIOS else s


def _dp(puntos, tol):
    """Douglas-Peucker iterativo (pila, no recursion: con 10.000 vertices la recursion revienta).

    Se aplica solo a lineas y con tolerancia en grados (~22 m con 0,0002): el visor pinta a
    escala nacional y provincial, y una capa de 10 MB por 22 m de detalle no es un buen cambio.
    """
    if len(puntos) < 3:
        return puntos
    def d_seg(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        px, py = x1 + t * dx, y1 + t * dy
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5
    keep = [False] * len(puntos)
    keep[0] = keep[-1] = True
    pila = [(0, len(puntos) - 1)]
    while pila:
        i, j = pila.pop()
        if j <= i + 1:
            continue
        peor, idx = -1.0, None
        for k in range(i + 1, j):
            d = d_seg(puntos[k], puntos[i], puntos[j])
            if d > peor:
                peor, idx = d, k
        if peor > tol:
            keep[idx] = True
            pila.append((i, idx))
            pila.append((idx, j))
    return [p for p, k in zip(puntos, keep) if k]


def simplifica_geometria(g, tol):
    if g.get("type") == "LineString":
        return {"type": "LineString", "coordinates": _dp(g["coordinates"], tol)}
    if g.get("type") == "MultiLineString":
        return {"type": "MultiLineString",
                "coordinates": [_dp(c, tol) for c in g["coordinates"] if len(c) > 1]}
    return g


def descargar(clave, cfg):
    col = cfg["coleccion"]
    base_url = "%s/collections/%s/items?f=json" % (BASE, urllib.parse.quote(col))
    print("== %s  (%s)" % (clave, col))
    # GeoServer pagina con `startIndex`, no con `offset` (medido: con offset repetia la misma
    # pagina y la descarga cuadruplicaba los objetos). Primero se pregunta cuantos hay.
    sonda = pedir(base_url + "&limit=1")
    total = sonda.get("numberMatched")
    if not total:
        raise SystemExit("   la coleccion no declara numberMatched: no se descarga a ciegas")
    feats = []
    vistos = 0
    while vistos < total:
        pagina = pedir(base_url + "&limit=%d&startIndex=%d" % (min(5000, total - vistos), vistos))
        lote = pagina.get("features") or []
        if not lote:
            break
        feats.extend(lote)
        vistos += len(lote)
    print("   fuente dice %d · descargados %d" % (total, len(feats)))
    if len(feats) != total:
        raise SystemExit("   DESCUADRE: %d de %d (no se escribe el recibo)" % (len(feats), total))

    salida = []
    for f in feats:
        p = f.get("properties") or {}
        nuevo = {}
        for origen, destino in cfg["campos"].items():
            v = limpia(p.get(origen))
            if v is not None:
                nuevo[destino] = v
        g = f.get("geometry")
        if not g:
            continue
        # CRS84: [lon, lat]. Se comprueba en vez de suponerlo; si viene al reves, se endereza.
        if g.get("type") == "Point":
            x, y = g["coordinates"][0], g["coordinates"][1]
            if abs(x) > 20 and abs(y) < 20:
                g["coordinates"] = [y, x]
        if cfg.get("simplificar"):
            g = simplifica_geometria(g, cfg["simplificar"])
        salida.append({"type": "Feature", "geometry": g, "properties": nuevo})

    ruta = os.path.join(DATOS, clave + ".geojson")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": salida}, fh,
                  ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(ruta) / 1024
    recibo = {
        "capa": clave,
        "titulo": cfg["titulo"],
        "fuente": "MITECO",
        "editor": "MITECO · OGC API Features (GeoServer)",
        "producto": "Conjunto de datos de alto valor (HVD) publicado como coleccion OGC API Features",
        "coleccion": col,
        "url": "%s/collections/%s" % (BASE, urllib.parse.quote(col)),
        "licencia": "Reutilización Ley 37/2007 con atribución (© MITECO)",
        "crs": "EPSG:4326 (CRS84)",
        "features": len(salida),
        "descartados_sin_geometria": len(feats) - len(salida),
        "numberMatched": total,
        "bytes": os.path.getsize(ruta),
        "kb": round(kb, 1),
        "descargado": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metodo": ("OGC API Features: %s/collections/%s/items, lotes de %d"
                   % (BASE.replace("https://", ""), col, LOTE)),
    }
    if cfg.get("simplificar"):
        recibo["simplificado_m"] = int(cfg["simplificar"] * 111000)
    with open(os.path.join(DATOS, clave + "_recibo.json"), "w", encoding="utf-8") as fh:
        json.dump(recibo, fh, ensure_ascii=False, indent=1)
    print("   escrito %s.geojson · %d objetos · %.1f KB" % (clave, len(salida), kb))
    if salida and salida[0]["geometry"]["type"] == "Point":
        xs = [f["geometry"]["coordinates"][0] for f in salida]
        ys = [f["geometry"]["coordinates"][1] for f in salida]
        print("   bbox lon %.3f..%.3f · lat %.3f..%.3f" % (min(xs), max(xs), min(ys), max(ys)))
    return recibo


def main():
    pedidas = sys.argv[1:] or list(CAPAS)
    for clave in pedidas:
        if clave not in CAPAS:
            raise SystemExit("capa desconocida: %s (hay: %s)" % (clave, ", ".join(CAPAS)))
        descargar(clave, CAPAS[clave])


if __name__ == "__main__":
    main()
