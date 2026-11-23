# -*- coding: utf-8 -*-
"""Accesibilidad ciclista en España — réplica medida de bertt/cyclingallowed.

Qué mide
--------
El mapa <https://bertt.github.io/cyclingallowed/> pinta cada vía de OSM con una de 12 clases
(sí / sí solo un sentido / no / desmonte / probable / dudoso) aplicando una expresión de estilo
de MapLibre sobre los atributos de la capa `transportation` de OpenMapTiles, servida por
OpenFreeMap. Este script **reproduce esas mismas reglas sobre el extracto oficial de OSM de
España** y da, para el país entero, kilómetros y número de vías por clase.

Por qué no se leen las teselas
------------------------------
Las teselas z14 de OpenFreeMap dan la foto exacta que ve el mapa, pero (a) España entera son
~145.000 teselas y (b) en ellas el campo `id` **no es el `osm_id`** (comprobado: el id 43080742
de una tesela de Madrid corresponde a un arroyo de Alabama), así que no se pueden cruzar con el
extracto. El reparto por clases de una zona sí se puede calcular desde las teselas: eso lo hace
`verificar_ciclismo_tiles.py`, que compara el reparto de las teselas con el de este script.

Reglas (idénticas al CLASS_EXPR de index.html del proyecto original)
--------------------------------------------------------------------
1. `bicycle=no|use_sidepath` o `access=no|private`             → no (explícito)
2. `bicycle=dismount`                                          → desmonte (explícito)
3. `bicycle=yes|designated|permissive` o `subclass=cycleway`   → sí (explícito), con sentido
4. `class=motorway|trunk`, o `class=path` con `subclass` footway/pedestrian/steps/platform/corridor
                                                               → no (implícito)
5. `class=primary|secondary|tertiary|minor`                    → sí (implícito), con sentido
6. `class=path|track` con superficie sin pavimentar o `mtb:scale` → probablemente no
7. `class=service` con `service=driveway|parking_aisle|drive-through|emergency_access`
                                                               → probablemente no
8. `class=path|track` con superficie pavimentada o `foot=yes`  → probablemente sí
9. `class=service`                                             → probablemente sí
10. resto                                                      → dudoso

Lo que OpenMapTiles hace ANTES de que el estilo vea el dato (y que cambia el resultado):
`layers/transportation/{mapping.yaml,class.sql,transportation.sql}`.

- `class` y `subclass` se derivan de `highway` con la tabla CLASE de abajo.
- `surface` se **colapsa a `paved` o `unpaved`** (`surface_value()`, y usa `tracktype` si no hay
  `surface`). Por eso las listas finas del estilo (asphalt, compacted, fine_gravel…) nunca casan:
  en la práctica solo se distinguen pavimentado y no pavimentado.
- `service` se limita a spur/yard/siding/crossover/driveway/alley/parking_aisle: `drive-through`
  y `emergency_access` **no llegan nunca** a la tesela.
- `access` se normaliza a `no` cuando es `private` o `no`; `destination`, `customers`, `delivery`
  y `permissive` **se pierden** (no hay clase «condicional» en este mapa).
- `bicycle`, `foot`, `horse`, `mtb:scale` pasan tal cual.
- `oneway` sale del tag `oneway` (1 / -1). No se deduce de `junction=roundabout`.
- La capa solo existe hasta **z14** y la geometría de `path`/`track` se filtra en z12 y z13:
  la foto completa es a z14.

Salidas
-------
datos/ciclismo_es.json                 totales, clases, por tipo de vía, conflictos declarados
datos/ciclismo_es_clases.csv           la tabla de clases en CSV
datos/ciclismo_verificacion_muestra.json  muestra por vía de tres zonas (para cruzar con teselas)
datos/ciclismo_madrid.geojson          muestra dibujable del centro de Madrid

Uso
---
    python scripts/ciclismo_osm.py                     # usa/descarga el extracto en la caché
    python scripts/ciclismo_osm.py --pbf C:/ruta/espana.osm.pbf
    python scripts/ciclismo_osm.py --limite 200000     # prueba rápida
"""
import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("OPENINFRAES_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "openinfraes")
URL_PBF = "https://download.openstreetmap.fr/extracts/europe/spain.osm.pbf"
FUENTE_PBF = "OpenStreetMap Foundation — extracto de España de openstreetmap.fr"
R = 6371.0088  # km

# --- derivación de `class`/`subclass` en OpenMapTiles (transportation.yaml + class.sql) --------
CLASE = {
    "motorway": "motorway", "motorway_link": "motorway",
    "trunk": "trunk", "trunk_link": "trunk",
    "primary": "primary", "primary_link": "primary",
    "secondary": "secondary", "secondary_link": "secondary",
    "tertiary": "tertiary", "tertiary_link": "tertiary",
    "unclassified": "minor", "residential": "minor", "living_street": "minor", "road": "minor",
    "service": "service", "track": "track",
    "pedestrian": "path", "path": "path", "footway": "path", "cycleway": "path",
    "steps": "path", "bridleway": "path", "corridor": "path",
}
ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "minor",
                "service", "track", "path"}
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones",
         "sett", "compacted", "fine_gravel"}
UNPAVED = {"unpaved", "ground", "dirt", "earth", "sand", "grass", "mud", "gravel", "pebblestone",
           "rock", "woodchips", "snow", "ice"}
NO_SERVICE = {"driveway", "parking_aisle", "drive-through", "emergency_access"}
SUPERFICIE_PAV = {"paved", "asphalt", "cobblestone", "concrete", "concrete:lanes", "concrete:plates",
                  "metal", "paving_stones", "sett", "unhewn_cobblestone", "wood", "grade1"}
SUPERFICIE_NO_PAV = {"unpaved", "compacted", "dirt", "earth", "fine_gravel", "grass", "grass_paver",
                     "gravel", "gravel_turf", "ground", "ice", "mud", "pebblestone", "salt", "sand",
                     "snow", "woodchips", "rock", "clay", "laterite"}
SERVICIOS = {"spur", "yard", "siding", "crossover", "driveway", "alley", "parking_aisle"}

ETIQUETAS = {
    "si explicito": "Sí (explícito)",
    "si implicito": "Sí (implícito)",
    "si ida explicito": "Sí, solo un sentido (explícito)",
    "si ida implicito": "Sí, solo un sentido (implícito)",
    "si vuelta explicito": "Sí, sentido contrario al dibujo (explícito)",
    "si vuelta implicito": "Sí, sentido contrario al dibujo (implícito)",
    "desmonte": "Desmonte (explícito)",
    "no explicito": "No (explícito)",
    "no implicito": "No (implícito)",
    "prob si": "Probablemente sí",
    "prob no": "Probablemente no",
    "dudoso": "Dudoso",
}
GRUPOS = {
    "si explicito": "sí", "si implicito": "sí", "prob si": "probable",
    "si ida explicito": "sí, un solo sentido", "si ida implicito": "sí, un solo sentido",
    "si vuelta explicito": "sí, un solo sentido", "si vuelta implicito": "sí, un solo sentido",
    "desmonte": "desmonte", "no explicito": "no", "no implicito": "no",
    "prob no": "probable no", "dudoso": "dudoso",
}


def superficie(valor, tracktype):
    """surface_value() de OpenMapTiles: colapsa a paved/unpaved o deja NULL."""
    v = valor or tracktype
    if v in SUPERFICIE_PAV:
        return "paved"
    if v in SUPERFICIE_NO_PAV:
        return "unpaved"
    return None


def clasifica(p):
    """Traducción 1:1 del CLASS_EXPR de index.html (mismo orden de precedencia)."""
    bici, access = p["bicycle"], p["access"]
    if bici in ("no", "use_sidepath") or access in ("no", "private"):
        return "no explicito"
    if bici == "dismount":
        return "desmonte"
    if bici in ("yes", "designated", "permissive") or p["subclass"] == "cycleway":
        return {"1": "si ida explicito", "-1": "si vuelta explicito"}.get(p["oneway"], "si explicito")
    if p["class"] in ("motorway", "trunk") or (
            p["class"] == "path" and p["subclass"] in
            ("footway", "pedestrian", "steps", "platform", "corridor")):
        return "no implicito"
    if p["class"] in ("primary", "secondary", "tertiary", "minor"):
        return {"1": "si ida implicito", "-1": "si vuelta implicito"}.get(p["oneway"], "si implicito")
    if p["class"] in ("path", "track") and (p["surface"] in UNPAVED or p["mtb_scale"]):
        return "prob no"
    if p["class"] == "service" and p["service"] in NO_SERVICE:
        return "prob no"
    if p["class"] in ("path", "track") and (p["surface"] in PAVED or p["foot"] == "yes"):
        return "prob si"
    if p["class"] == "service":
        return "prob si"
    return "dudoso"


def longitud_km(locs):
    km = 0.0
    for (lo1, la1), (lo2, la2) in zip(locs, locs[1:]):
        dx = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2.0))
        dy = math.radians(la2 - la1)
        km += R * math.hypot(dx, dy)
    return km


def valor_oneway(tags):
    v = tags.get("oneway")
    if v in ("yes", "true", "1"):
        return "1"
    if v in ("-1", "reverse"):
        return "-1"
    return "0"


# zonas de la muestra que después se cruza con las teselas z14
ZONAS = [("madrid-centro", 40.4257, -3.7094),
         ("barcelona-eixample", 41.3874, 2.1686),
         ("gredos-rural", 40.2800, -5.1300)]
Z_MUESTRA = 14


def tesela(lat, lon, z):
    n = 2 ** z
    return (int((lon + 180.0) / 360.0 * n),
            int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n))


def limites_teselas(x0, y0, x1, y1, z):
    """Bordes del bloque de teselas x0..x1, y0..y1 (incluidos): (lon_oeste, lat_sur, lon_este, lat_norte)."""
    n = 2 ** z
    lon0 = x0 / n * 360.0 - 180.0
    lon1 = (x1 + 1) / n * 360.0 - 180.0
    lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y1 + 1) / n))))
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y0 / n))))
    return lon0, lat0, lon1, lat1


def prepara_zonas():
    zonas = []
    for nombre, lat, lon in ZONAS:
        x, y = tesela(lat, lon, Z_MUESTRA)
        x0, y0 = x - 1, y - 1  # 2x2 teselas con el centro en la esquina inferior derecha
        lon0, lat0, lon1, lat1 = limites_teselas(x0, y0, x0 + 1, y0 + 1, Z_MUESTRA)
        zonas.append({"nombre": nombre, "centro": [lat, lon], "teselas": [[x0, y0], [x0 + 1, y0],
                     [x0, y0 + 1], [x0 + 1, y0 + 1]], "z": Z_MUESTRA,
                     "bbox": [lon0, lat0, lon1, lat1]})
    return zonas


def descargar_pbf(destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = destino + ".parcial"
    print(f"descargando {URL_PBF} -> {destino}")
    with urllib.request.urlopen(urllib.request.Request(URL_PBF, headers={"User-Agent": "OpenInfraES/1.0"}),
                                timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        hecho = 0
        while True:
            trozo = r.read(1 << 20)
            if not trozo:
                break
            f.write(trozo)
            hecho += len(trozo)
            if total and hecho % (64 << 20) < (1 << 20):
                print(f"  {hecho/1048576:.0f}/{total/1048576:.0f} MB")
    os.replace(tmp, destino)
    return destino


def main():
    ap = argparse.ArgumentParser(description="Accesibilidad ciclista en España (réplica de cyclingallowed)")
    ap.add_argument("--pbf", help="extracto .osm.pbf de España (si no se pasa, se usa/descarga en la caché)")
    ap.add_argument("--limite", type=int, default=0, help="cortar tras N vías (pruebas)")
    ap.add_argument("--salida", default=os.path.join(RAIZ, "datos"))
    args = ap.parse_args()

    try:
        import osmium
    except ImportError:
        sys.exit("falta pyosmium: python -m pip install osmium")

    pbf = args.pbf or os.path.join(CACHE, "espana.osm.pbf")
    if not os.path.exists(pbf):
        pbf = descargar_pbf(pbf)
    print(f"extracto: {pbf} ({os.path.getsize(pbf)/1048576:.0f} MB)")

    zonas = prepara_zonas()
    clases = {k: {"vias": 0, "km": 0.0} for k in ETIQUETAS}
    por_highway = {}
    conflictos = {"bici_permitida_pero_privada": 0, "contraflujo_no_visible": 0,
                  "condicional_perdido": 0, "tunel_excluido_km": 0.0,
                  "area_excluida": 0, "sin_superficie_km": 0.0}
    muestra = {}
    geojson_madrid = []
    total_km = 0.0
    total_vias = 0
    t0 = time.time()

    fp = (osmium.FileProcessor(pbf).with_locations(storage="sparse_file_array")
          .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
          .with_filter(osmium.filter.KeyFilter("highway", "public_transport")))

    for w in fp:
        tags = w.tags
        hw = tags.get("highway")
        clase_omt = CLASE.get(hw) if hw else None
        sub = None
        if clase_omt == "path":
            sub = hw
        elif not hw and tags.get("public_transport") == "platform":
            clase_omt, sub = "path", "platform"
        if clase_omt not in ROAD_CLASSES:
            continue  # rail, pier, aerialway, construction, raceway, busway… quedan fuera

        locs = []
        for n in w.nodes:
            if n.location.valid():
                locs.append((n.location.lon, n.location.lat))
        if len(locs) < 2:
            continue
        km = longitud_km(locs)

        brunnel = ("tunnel" if (tags.get("tunnel") not in (None, "no") or
                                any(t.k.startswith("tunnel:") for t in tags))
                   else "bridge" if tags.get("bridge") not in (None, "no") else None)
        if brunnel == "tunnel":
            conflictos["tunel_excluido_km"] += km
            continue
        if tags.get("area") == "yes":
            conflictos["area_excluida"] += 1
            continue

        uno = valor_oneway(tags)
        access_raw = tags.get("access")
        p = {
            "class": clase_omt,
            "subclass": sub,
            "bicycle": tags.get("bicycle"),
            "access": "no" if access_raw in ("private", "no") else None,
            "oneway": uno,
            "surface": superficie(tags.get("surface"), tags.get("tracktype")),
            "service": tags.get("service") if tags.get("service") in SERVICIOS else None,
            "foot": tags.get("foot"),
            "mtb_scale": bool(tags.get("mtb:scale")),
        }
        clase = clasifica(p)
        clases[clase]["vias"] += 1
        clases[clase]["km"] += km
        total_vias += 1
        total_km += km
        h = por_highway.setdefault(hw or "platform", {"vias": 0, "km": 0.0, "clases": {}})
        h["vias"] += 1
        h["km"] += km
        h["clases"][clase] = h["clases"].get(clase, 0) + km

        if not p["surface"] and clase_omt in ("path", "track", "service"):
            conflictos["sin_superficie_km"] += km
        if p["bicycle"] in ("yes", "designated", "permissive") and access_raw in ("private", "no"):
            conflictos["bici_permitida_pero_privada"] += 1
        if uno != "0" and tags.get("oneway:bicycle") == "no":
            conflictos["contraflujo_no_visible"] += 1
        if access_raw in ("destination", "customers", "delivery"):
            conflictos["condicional_perdido"] += 1

        for z in zonas:
            lo0, la0, lo1, la1 = z["bbox"]
            if any(lo0 <= lo <= lo1 and la0 <= la <= la1 for lo, la in locs):
                muestra.setdefault(z["nombre"], {})[str(w.id)] = {
                    "highway": hw, "class": clase_omt, "subclass": sub,
                    "bicycle": p["bicycle"], "access": access_raw, "oneway": uno,
                    "surface": p["surface"], "surface_osm": tags.get("surface"),
                    "service": p["service"], "foot": p["foot"], "mtb_scale": p["mtb_scale"],
                    "clase": clase, "km": round(km, 4),
                }
                if z["nombre"] == "madrid-centro":
                    geojson_madrid.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[round(a, 7), round(b, 7)] for a, b in locs]},
                        "properties": {"osm_id": w.id, "highway": hw, "nombre": tags.get("name"),
                                       "clase": clase, "clase_etiqueta": ETIQUETAS[clase],
                                       "bicycle": p["bicycle"], "oneway": uno,
                                       "km": round(km, 4)},
                    })
        if args.limite and total_vias >= args.limite:
            print(f"corte de prueba en {args.limite} vías")
            break
        if total_vias % 500000 == 0:
            print(f"  {total_vias:,} vías · {total_km:,.0f} km · {time.time()-t0:.0f}s", flush=True)

    os.makedirs(args.salida, exist_ok=True)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    filas = []
    for clave, et in ETIQUETAS.items():
        d = clases[clave]
        filas.append({"clave": clave, "etiqueta": et, "grupo": GRUPOS[clave],
                      "vias": d["vias"], "km": round(d["km"], 1),
                      "pct_km": round(100 * d["km"] / total_km, 2) if total_km else 0.0})
    grupos = {}
    for f in filas:
        g = grupos.setdefault(f["grupo"], {"vias": 0, "km": 0.0})
        g["vias"] += f["vias"]
        g["km"] += f["km"]
    for g in grupos.values():
        g["km"] = round(g["km"], 1)
        g["pct_km"] = round(100 * g["km"] / total_km, 2) if total_km else 0.0

    resumen = {
        "titulo": "Accesibilidad ciclista en España — réplica de bertt/cyclingallowed sobre OSM",
        "generado": ahora,
        "extracto": {"fichero": os.path.basename(pbf), "bytes": os.path.getsize(pbf),
                     "url": URL_PBF, "fuente": FUENTE_PBF},
        "reglas": {"proyecto": "https://github.com/bertt/cyclingallowed",
                   "fichero": "index.html → CLASS_EXPR",
                   "base": "OpenFreeMap · capa transportation del esquema OpenMapTiles (máx. z14)",
                   "equivalencia": "misma precedencia; surface y service ya vienen normalizados por OpenMapTiles"},
        "licencia": "ODbL 1.0 — © colaboradores de OpenStreetMap",
        "totales": {"vias": total_vias, "km": round(total_km, 1)},
        "clases": filas,
        "grupos": grupos,
        "por_highway": {k: {"vias": v["vias"], "km": round(v["km"], 1)}
                        for k, v in sorted(por_highway.items(), key=lambda kv: -kv[1]["km"])},
        "carril_bici_km": round(por_highway.get("cycleway", {}).get("km", 0.0), 1),
        "conflictos": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in conflictos.items()},
        "zonas_muestra": [{"nombre": z["nombre"], "teselas": z["teselas"], "z": z["z"],
                           "bbox": [round(c, 6) for c in z["bbox"]],
                           "vias": len(muestra.get(z["nombre"], {}))} for z in zonas],
        "segundos": round(time.time() - t0, 1),
    }

    ruta = os.path.join(args.salida, "ciclismo_es.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)

    with open(os.path.join(args.salida, "ciclismo_es_clases.csv"), "w", newline="", encoding="utf-8") as f:
        wcsv = csv.writer(f, delimiter=";")
        wcsv.writerow(["clase", "etiqueta", "grupo", "vias", "km", "pct_km"])
        for fila in filas:
            wcsv.writerow([fila["clave"], fila["etiqueta"], fila["grupo"], fila["vias"],
                           f"{fila['km']:.1f}".replace(".", ","), f"{fila['pct_km']:.2f}".replace(".", ",")])

    with open(os.path.join(args.salida, "ciclismo_verificacion_muestra.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "fuente": URL_PBF, "zonas": zonas, "vias": muestra}, f,
                  ensure_ascii=False, indent=None)

    with open(os.path.join(args.salida, "ciclismo_madrid.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": geojson_madrid}, f, ensure_ascii=False)

    with open(os.path.join(args.salida, "ciclismo_es_recibo.json"), "w", encoding="utf-8") as f:
        json.dump({"fuente": FUENTE_PBF, "url": URL_PBF, "licencia": "ODbL 1.0",
                   "generado": ahora, "vias": total_vias, "km": round(total_km, 1),
                   "fichero": "ciclismo_es.json", "metodo": "scripts/ciclismo_osm.py"}, f,
                  ensure_ascii=False, indent=1)

    print(f"\nvías {total_vias:,} · {total_km:,.0f} km · {time.time()-t0:.0f}s")
    for fila in filas:
        print(f"  {fila['etiqueta']:42s} {fila['vias']:>9,}  {fila['km']:>10,.0f} km  {fila['pct_km']:>5.1f}%")
    print(f"\nescrito {ruta}")


if __name__ == "__main__":
    main()
