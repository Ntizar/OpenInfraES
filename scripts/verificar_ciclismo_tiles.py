# -*- coding: utf-8 -*-
"""Cotejo de la réplica en OSM con lo que enseñan las teselas de OpenFreeMap.

El mapa de `bertt/cyclingallowed` no tiene datos propios: pinta la capa `transportation` de
OpenFreeMap (esquema OpenMapTiles) aplicando una expresión de estilo. `ciclismo_osm.py` aplica
esas mismas reglas sobre las etiquetas crudas de OSM. Este script comprueba que **ambas vías dan
el mismo reparto por clases** en tres zonas, y qué campos se pierden por el camino.

- Desde las teselas: se descargan las z14 de la zona, se decodifica `transportation` y se aplica
  la expresión tal cual sobre los campos de la tesela (`class`, `subclass`, `bicycle`, `access`,
  `oneway`, `surface`, `service`, `foot`, `mtb_scale`).
- Desde OSM: se lee `datos/ciclismo_verificacion_muestra.json`, que escribe `ciclismo_osm.py`.

No se cruzan por `id`: en las teselas el `id` de la feature **no es el `osm_id`** (comprobado:
una vía del centro de Madrid con id 43080742 en la tesela es un arroyo de Alabama en OSM). El
cotejo es por reparto de kilómetros por clase, que es lo que finalmente se ve en el mapa.

Uso
---
    python scripts/verificar_ciclismo_tiles.py
Salida: datos/ciclismo_verificacion_tiles.json
"""
import json
import math
import os
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUESTRA = os.environ.get("CICLISMO_MUESTRA") or os.path.join(RAIZ, "datos", "ciclismo_verificacion_muestra.json")
DESTINO = os.environ.get("CICLISMO_SALIDA") or os.path.join(RAIZ, "datos", "ciclismo_verificacion_tiles.json")
TILEJSON = "https://tiles.openfreemap.org/planet"
UA = {"User-Agent": "OpenInfraES/1.0"}

ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "minor",
                "service", "track", "path"}
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones",
         "sett", "compacted", "fine_gravel"}
UNPAVED = {"unpaved", "ground", "dirt", "earth", "sand", "grass", "mud", "gravel", "pebblestone",
           "rock", "woodchips", "snow", "ice"}
NO_SERVICE = {"driveway", "parking_aisle", "drive-through", "emergency_access"}


def clasifica(p):
    bici, access = p.get("bicycle"), p.get("access")
    if bici in ("no", "use_sidepath") or access in ("no", "private"):
        return "no explicito"
    if bici == "dismount":
        return "desmonte"
    if bici in ("yes", "designated", "permissive") or p.get("subclass") == "cycleway":
        return {"1": "si ida explicito", "-1": "si vuelta explicito"}.get(str(p.get("oneway")), "si explicito")
    if p["class"] in ("motorway", "trunk") or (
            p["class"] == "path" and p.get("subclass") in
            ("footway", "pedestrian", "steps", "platform", "corridor")):
        return "no implicito"
    if p["class"] in ("primary", "secondary", "tertiary", "minor"):
        return {"1": "si ida implicito", "-1": "si vuelta implicito"}.get(str(p.get("oneway")), "si implicito")
    if p["class"] in ("path", "track") and (p.get("surface") in UNPAVED or p.get("mtb_scale")):
        return "prob no"
    if p["class"] == "service" and p.get("service") in NO_SERVICE:
        return "prob no"
    if p["class"] in ("path", "track") and (p.get("surface") in PAVED or p.get("foot") == "yes"):
        return "prob si"
    if p["class"] == "service":
        return "prob si"
    return "dudoso"


def baja(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def lonlat(x, y, extent, tx, ty, z):
    """mapbox_vector_tile devuelve la y ya volteada (origen abajo), así que se deshace el giro."""
    n = 2 ** z
    lon = (tx + x / extent) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + (extent - y) / extent) / n))))
    return lon, lat


def longitud(pts):
    km = 0.0
    for (lo1, la1), (lo2, la2) in zip(pts, pts[1:]):
        dx = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2.0))
        dy = math.radians(la2 - la1)
        km += 6371.0088 * math.hypot(dx, dy)
    return km


def main():
    import mapbox_vector_tile as mvt

    with open(MUESTRA, encoding="utf-8") as f:
        muestra = json.load(f)
    tj = json.loads(baja(TILEJSON))
    plantilla = tj["tiles"][0]
    print(f"teselas: {plantilla} (maxzoom {tj['maxzoom']})")

    informe = {"generado": json.load(open(MUESTRA, encoding="utf-8")).get("generado"),
               "plantilla_teselas": plantilla, "maxzoom": tj["maxzoom"],
               "nota": "el id de la feature en las teselas NO es el osm_id; el cotejo es por reparto de km",
               "zonas": {}}

    for zona in muestra["zonas"]:
        nombre, z = zona["nombre"], zona["z"]
        clases_tesela = {}
        km_tesela = 0.0
        campo_ausente = {"surface": 0, "bicycle": 0, "oneway": 0, "subclass": 0, "access": 0}
        vias_tesela = 0
        for tx, ty in zona["teselas"]:
            url = plantilla.replace("{z}", str(z)).replace("{x}", str(tx)).replace("{y}", str(ty))
            try:
                capa = mvt.decode(baja(url)).get("transportation", {})
            except Exception as e:
                print(f"  {nombre} {tx}/{ty}: fallo {type(e).__name__}")
                continue
            extent = capa.get("extent", 4096)
            for f in capa.get("features", []):
                pr = f["properties"]
                if pr.get("class") not in ROAD_CLASSES:
                    continue
                if pr.get("brunnel") == "tunnel":
                    continue
                geo = f["geometry"]
                if geo["type"] == "LineString":
                    lineas = [geo["coordinates"]]
                elif geo["type"] == "MultiLineString":
                    lineas = geo["coordinates"]
                else:
                    continue  # Polygon/MultiPolygon: el capturador descarta area=yes; aquí también
                km = 0.0
                for linea in lineas:
                    pts = [lonlat(p[0], p[1], extent, tx, ty, z) for p in linea]
                    km += longitud(pts)
                clase = clasifica(pr)
                clases_tesela[clase] = clases_tesela.get(clase, 0.0) + km
                km_tesela += km
                vias_tesela += 1
                for k in campo_ausente:
                    if pr.get(k) is None:
                        campo_ausente[k] += 1

        clases_osm = {}
        vias_osm = 0
        km_osm = 0.0
        for reg in muestra["vias"].get(nombre, {}).values():
            clases_osm[reg["clase"]] = clases_osm.get(reg["clase"], 0.0) + reg["km"]
            km_osm += reg["km"]
            vias_osm += 1

        claves = sorted(set(clases_tesela) | set(clases_osm))
        tabla = []
        for k in claves:
            a = clases_tesela.get(k, 0.0)
            b = clases_osm.get(k, 0.0)
            tabla.append({"clase": k,
                          "km_tesela": round(a, 2), "km_osm": round(b, 2),
                          "pct_tesela": round(100 * a / km_tesela, 2) if km_tesela else 0.0,
                          "pct_osm": round(100 * b / km_osm, 2) if km_osm else 0.0})
        informe["zonas"][nombre] = {
            "z": z, "teselas": zona["teselas"],
            "vias_tesela": vias_tesela, "km_tesela": round(km_tesela, 1),
            "vias_osm": vias_osm, "km_osm": round(km_osm, 1),
            "desvio_km_pct": round(100 * (km_tesela - km_osm) / km_osm, 2) if km_osm else None,
            "campos_ausentes_en_tesela": campo_ausente,
            "clases": tabla,
        }
        print(f"\n{nombre} (z{z}): teselas {vias_tesela:,} vías / {km_tesela:.0f} km · "
              f"OSM {vias_osm:,} vías / {km_osm:.0f} km · desvío {informe['zonas'][nombre]['desvio_km_pct']:+.2f}%")
        print(f"  {'clase':22s} {'% tesela':>9s} {'% osm':>9s} {'Δpp':>7s}")
        for fila in tabla:
            print(f"  {fila['clase']:22s} {fila['pct_tesela']:9.2f} {fila['pct_osm']:9.2f} "
                  f"{fila['pct_tesela']-fila['pct_osm']:+7.2f}")

    with open(DESTINO, "w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
    print(f"\nescrito {DESTINO}")


if __name__ == "__main__":
    main()
