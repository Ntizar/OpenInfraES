# -*- coding: utf-8 -*-
"""Túneles y puentes de la Red de Carreteras del Estado -> GeoJSON geolocalizado.

Dos fuentes, dos métodos, un mismo criterio: **una fila por sitio físico**. Si una estructura
llega repetida (un túnel con tres tubos, un puente partido en dos calzadas), se funde en un solo
elemento y los datos de cada parte quedan dentro, en `tubos` o en `calzadas`. Nunca dos chinchetas
en el mismo punto.

Túneles  -> MITMA, servicio Hermes (ArcGIS REST), capa 929. Trae geometría real, carretera, PK de
            entrada y salida por tubo, longitud y titular. 383 túneles.
Puentes  -> OSM (`bridge` sobre A-/AP-/N-). Es la única fuente con geometría nacional: el inventario
            del MITMA se publica en PDF y el de Castilla y León en CSV sin coordenadas. Cada calzada
            es un `way`, así que se agrupan por proximidad (~45 m) y se funden.
"""
import json
import math
import os
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
UA = {"User-Agent": "OpenInfraES/1.0 (visor de infraestructura; contacto en el repo)"}
HERMES = ("https://mapas.fomento.gob.es/arcgis2/rest/services/Hermes/"
          "1_INFRAESTRUCTURA_B%C3%81SICA_/MapServer/929/query")
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]


def pide(url, datos=None, timeout=300):
    cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
    req = urllib.request.Request(url, data=cuerpo, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def pide_overpass(consulta, timeout=900):
    """Los servidores públicos de Overpass devuelven 502 cuando están saturados; se prueban los
    tres espejos antes de darse por vencido."""
    import time
    ultimo = None
    for intento in range(3):
        for espejo in OVERPASS:
            try:
                return pide(espejo, {"data": consulta}, timeout=timeout)
            except Exception as e:  # 429/502/timeout: siguiente espejo
                ultimo = e
        time.sleep(8 * (intento + 1))
    raise RuntimeError("Overpass no responde: %s" % ultimo)


def redondea(geom, dec=5):
    """5 decimales son ~1 m: de sobra para dibujar y ahorra la mitad del fichero."""
    def r(c):
        if isinstance(c, (int, float)):
            return round(c, dec)
        return [r(x) for x in c]
    if not geom:
        return geom
    return {"type": geom["type"], "coordinates": r(geom["coordinates"])}


def num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Túneles (MITMA · Hermes)
# ─────────────────────────────────────────────────────────────────────────────
def tuneles():
    q = {"where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson",
         "resultRecordCount": "2000"}
    d = pide(HERMES + "?" + urllib.parse.urlencode(q))
    feats = []
    vistos = {}
    for f in d.get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry")
        if not g or not g.get("coordinates"):
            continue
        # Un túnel = una fila. Los tubos vienen como columnas (dcha/izq/ctr/ambas) y aquí pasan a
        # ser una lista dentro del mismo elemento.
        tubos = []
        for lado, etiqueta in (("dcha", "Calzada derecha"), ("izq", "Calzada izquierda"),
                               ("ctr", "Tubo central"), ("ambas", "Ambos sentidos")):
            nombre = p.get("Tubo_" + lado)
            if not nombre and not p.get("Longitud_" + lado):
                continue
            tubos.append({"lado": etiqueta, "nombre": nombre,
                          "pk_ini": num(p.get("PK_ini_" + lado)),
                          "pk_fin": num(p.get("PK_fin_" + lado)),
                          "longitud_m": num(p.get("Longitud_" + lado)),
                          "nota": (p.get("Obs_tubo_" + lado) or "").strip() or None})
        largo = max([t["longitud_m"] for t in tubos if t["longitud_m"]] or [0]) or None
        carretera = (p.get("Carretera") or "").strip()
        clave = "%s|%s" % (carretera, (p.get("Tunel") or "").strip().upper())
        props = {
            "nombre": (p.get("Tunel") or "").strip() or None,
            "carretera": carretera or None,
            "titular": (p.get("Titular") or "").strip() or None,
            "pk_ini": min([t["pk_ini"] for t in tubos if t["pk_ini"] is not None] or [None]) if any(t["pk_ini"] is not None for t in tubos) else None,
            "pk_fin": max([t["pk_fin"] for t in tubos if t["pk_fin"] is not None] or [None]) if any(t["pk_fin"] is not None for t in tubos) else None,
            "longitud_m": largo,
            "n_tubos": len(tubos),
            # La ficha no sabe pintar listas de objetos: el detalle de cada tubo viaja también como
            # texto para leerlo de un vistazo, sin perder el array para quien lo consuma.
            "tubos_txt": " · ".join(
                "%s %s m%s" % (t["lado"].lower(),
                               int(t["longitud_m"]) if t["longitud_m"] else "?",
                               (" (PK %s–%s)" % (t["pk_ini"], t["pk_fin"]))
                               if t["pk_ini"] is not None and t["pk_fin"] is not None else "")
                for t in tubos) or None,
            "tubos": tubos or None,
            "tent": bool(p.get("TENT")) or None,
            "fuente": "MITMA · túneles de la RCE",
        }
        if clave in vistos:            # misma carretera y mismo nombre: se funde
            prev = vistos[clave]
            prev["properties"]["tubos"] = (prev["properties"]["tubos"] or []) + props["tubos"]
            prev["properties"]["n_tubos"] = len(prev["properties"]["tubos"])
            prev["properties"]["tubos_txt"] = " · ".join(
                "%s %s m" % (t["lado"].lower(), int(t["longitud_m"]) if t["longitud_m"] else "?")
                for t in prev["properties"]["tubos"]) or None
            prev["properties"]["longitud_m"] = max(prev["properties"]["longitud_m"] or 0,
                                                   props["longitud_m"] or 0) or None
            continue
        vistos[clave] = {"type": "Feature", "geometry": redondea(g), "properties": props}
        feats.append(vistos[clave])
    return feats


# ─────────────────────────────────────────────────────────────────────────────
# Puentes (OSM, restringido a la RCE)
# ─────────────────────────────────────────────────────────────────────────────
CONSULTA_PUENTES = """
[out:json][timeout:600];
way["bridge"]["highway"]["ref"~"^(A|AP|N)-"](35.9,-9.4,43.9,4.6);
out tags center;
"""


def celdas(lat, lon, metros=45.0):
    """Clave de rejilla para fundir calzadas del mismo puente. 45 m cubre el ancho de una autovía
    con mediana; no tanto como para juntar dos estructuras distintas."""
    dlat = metros / 111320.0
    dlon = metros / (111320.0 * max(0.15, math.cos(math.radians(lat))))
    return (round(lat / dlat), round(lon / dlon))


def puentes():
    d = pide_overpass(CONSULTA_PUENTES)
    grupos = {}
    for el in d.get("elements", []):
        c = (el.get("center") or {})
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        t = el.get("tags") or {}
        calzada = {"ref": t.get("ref"), "nombre": t.get("name"),
                   "tipo": t.get("bridge"), "highway": t.get("highway"),
                   "capas": num(t.get("lanes")), "largo_m": num(t.get("length"))}
        # la celda sola fundiría un puente de la A-2 con la pasarela que lo cruza: se añade la
        # carretera a la clave para no mezclar obras distintas
        k = celdas(lat, lon) + ((t.get("ref") or "").split(";")[0].strip().upper(),)
        if k not in grupos:
            grupos[k] = {"lat": lat, "lon": lon, "calzadas": []}
        grupos[k]["calzadas"].append(calzada)
    feats = []
    for g in grupos.values():
        calzadas = g["calzadas"]
        refs = sorted({c["ref"] for c in calzadas if c["ref"]})
        nombres = sorted({c["nombre"] for c in calzadas if c["nombre"]})
        tipos = sorted({c["tipo"] for c in calzadas if c["tipo"]})
        largos = [c["largo_m"] for c in calzadas if c["largo_m"]]
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(g["lon"], 6), round(g["lat"], 6)]},
            "properties": {
                "nombre": nombres[0] if nombres else None,
                "carretera": " · ".join(refs) if refs else None,
                "tipo": "/".join(tipos) if tipos else "puente",
                "n_calzadas": len(calzadas),
                "largo_m": max(largos) if largos else None,
                "fuente": "OpenStreetMap",
            },
        })
    return feats


def funde_cercanos(feats, metros=45.0):
    """Última pasada: dos puentes en celdas vecinas pero a menos de 45 m siguen siendo el mismo.
    Solo se funden si comparten carretera: dos estructuras distintas en el mismo punto (una
    pasarela sobre la A-7 y el viaducto de la A-7) son dos puentes, no uno."""
    def clave(lat, lon):
        dlat = metros / 111320.0
        dlon = metros / (111320.0 * max(0.15, math.cos(math.radians(lat))))
        return (int(lat / dlat), int(lon / dlon))

    def refs(p):
        return {r.strip() for r in str(p.get("carretera") or "").split("·") if r.strip()}

    def dist(a, b):
        dx = (a[0] - b[0]) * 111320.0 * math.cos(math.radians((a[1] + b[1]) / 2))
        dy = (a[1] - b[1]) * 111320.0
        return math.hypot(dx, dy)

    rejilla = {}
    salida = []
    for f in feats:
        lon, lat = f["geometry"]["coordinates"]
        k = clave(lat, lon)
        hallado = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for otro in rejilla.get((k[0] + di, k[1] + dj), []):
                    if dist((lon, lat), otro["geometry"]["coordinates"]) > metros:
                        continue
                    r1, r2 = refs(otro["properties"]), refs(f["properties"])
                    if r1 and r2 and not (r1 & r2):
                        continue          # carreteras distintas: son dos obras
                    hallado = otro
                    break
                if hallado:
                    break
            if hallado:
                break
        if hallado:
            p = hallado["properties"]
            p["n_calzadas"] = (p.get("n_calzadas") or 1) + (f["properties"].get("n_calzadas") or 1)
            if not p.get("nombre") and f["properties"].get("nombre"):
                p["nombre"] = f["properties"]["nombre"]
            if not p.get("carretera") and f["properties"].get("carretera"):
                p["carretera"] = f["properties"]["carretera"]
            if (f["properties"].get("largo_m") or 0) > (p.get("largo_m") or 0):
                p["largo_m"] = f["properties"]["largo_m"]
            continue
        rejilla.setdefault(k, []).append(f)
        salida.append(f)
    return salida


def escribe(nombre, feats, meta):
    ruta = os.path.join(DATOS, nombre)
    json.dump({"type": "FeatureCollection", "features": feats}, open(ruta, "w"),
              ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(ruta) / 1024
    recibo = dict(meta)
    recibo.update({"features": len(feats), "kb": round(kb, 1), "fichero": nombre})
    json.dump(recibo, open(os.path.join(DATOS, nombre.replace(".geojson", "_recibo.json")), "w"),
              ensure_ascii=False, indent=1)
    print("%-26s %6d elementos  %7.1f KB" % (nombre, len(feats), kb))
    return kb


def main():
    import sys
    que = (sys.argv[1] if len(sys.argv) > 1 else "todo").lower()
    if que in ("todo", "tuneles", "túneles"):
        t = tuneles()
        escribe("tuneles_rce.geojson", t, {
            "titulo": "Túneles de la Red de Carreteras del Estado",
            "fuente": "MITMA", "editor": "Ministerio de Transportes y Movilidad Sostenible",
            "licencia": "Reutilización con atribución (Ley 37/2007)",
            "url": "https://mapas.fomento.gob.es/arcgis2/rest/services/Hermes/1_INFRAESTRUCTURA_B%C3%81SICA_/MapServer/929",
            "metodo": "ArcGIS REST, capa 929, un elemento por túnel con sus tubos anidados"})
    if que in ("todo", "puentes"):
        p = puentes()
        p = funde_cercanos(p)
        escribe("puentes_rce.geojson", p, {
            "titulo": "Puentes y viaductos de la RCE",
            "fuente": "OpenStreetMap", "editor": "Colaboradores de OpenStreetMap",
            "licencia": "ODbL 1.0 (atribución y compartir igual)",
            "url": "https://overpass-api.de/",
            "metodo": "Overpass `bridge` sobre vías A-/AP-/N-, calzadas fundidas por proximidad de 45 m"})


if __name__ == "__main__":
    main()
