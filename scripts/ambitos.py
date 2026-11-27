# -*- coding: utf-8 -*-
"""Calcula el ÁMBITO real de cada capa: España, una comunidad o una provincia.

Para qué: con 104 capas, una lista plana no dice si lo que enciendes cubre España o solo
Navarra. Y no se declara a mano: se MIDE sobre la geometría, comparando dónde caen sus
objetos con los municipios del visor (que ya traen provincia). Así una capa nueva entra
sola en el clasificador y no hay que acordarse de etiquetarla.

Cómo:
  1. Centroides de los 8.128 municipios (provincia incluida) → cuadrícula de 0,25°.
  2. De cada capa se muestrean hasta 400 vértices (o puntos) repartidos por todo el
     fichero, no los primeros: si no, una capa de incendios parecería gallega.
  3. Cada muestra se asigna al municipio más cercano → provincia → comunidad.
  4. Regla: 20 provincias o más (o bbox de medio país) = nacional; una comunidad = CCAA;
     una provincia = provincial. Lo demás se declara "parcial" con sus provincias.

Las capas troceadas (`carpeta`) se dan por nacionales: se trocean justamente porque
cubren el país entero. Se dice en el JSON, no se adivina.

Escribe datos/ambitos.json (lo lee el visor para los distintivos y el filtro).

    python scripts/ambitos.py
"""
import datetime
import json
import math
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
SALIDA = os.path.join(DATOS, "ambitos.json")
MUESTRAS = 400
UMBRAL_NACIONAL = 20          # provincias distintas
UMBRAL_BBOX = 0.45            # fracción de España (9,5° x 7,5°)

# provincia (código INE) -> comunidad
CCAA = {
    "01": "País Vasco", "02": "Castilla-La Mancha", "03": "Comunidad Valenciana",
    "04": "Andalucía", "05": "Castilla y León", "06": "Extremadura", "07": "Illes Balears",
    "08": "Cataluña", "09": "Castilla y León", "10": "Extremadura", "11": "Andalucía",
    "12": "Comunidad Valenciana", "13": "Castilla-La Mancha", "14": "Andalucía",
    "15": "Galicia", "16": "Castilla-La Mancha", "17": "Cataluña", "18": "Andalucía",
    "19": "Castilla-La Mancha", "20": "País Vasco", "21": "Andalucía", "22": "Aragón",
    "23": "Andalucía", "24": "Castilla y León", "25": "Cataluña", "26": "La Rioja",
    "27": "Galicia", "28": "Comunidad de Madrid", "29": "Andalucía", "30": "Región de Murcia",
    "31": "Navarra", "32": "Galicia", "33": "Principado de Asturias", "34": "Castilla y León",
    "35": "Canarias", "36": "Galicia", "37": "Castilla y León", "38": "Canarias",
    "39": "Cantabria", "40": "Castilla y León", "41": "Andalucía", "42": "Castilla y León",
    "43": "Cataluña", "44": "Aragón", "45": "Castilla-La Mancha", "46": "Comunidad Valenciana",
    "47": "Castilla y León", "48": "País Vasco", "49": "Castilla y León", "50": "Aragón",
    "51": "Ceuta", "52": "Melilla",
}


def capas_del_visor():
    """Saca id, grupo, fichero y carpeta del array CAPAS de index.html."""
    h = open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read()
    trozos = re.split(r"\n\s*\{\s*id:\"", h)
    salida = []
    for t in trozos[1:]:
        cid = t.split('"')[0]
        fichero = re.search(r'fichero:"([^"]+)"', t[:600])
        carpeta = re.search(r'carpeta:"([^"]+)"', t[:600])
        grupo = re.search(r'grupo:"([^"]+)"', t[:600])
        salida.append({"id": cid,
                       "grupo": grupo.group(1) if grupo else "",
                       "fichero": fichero.group(1) if fichero else None,
                       "carpeta": carpeta.group(1) if carpeta else None})
    return [c for c in salida if c["id"] not in ("todos",)]


def centroides():
    """Municipios: centroide aproximado (media del anillo mayor) y provincia."""
    d = json.load(open(os.path.join(DATOS, "municipios.geojson"), encoding="utf-8"))
    out = []
    for f in d["features"]:
        g = f["geometry"]
        anillo = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        # el anillo mayor es el que más pesa: en multipolígono, el de más vértices
        if g["type"] == "MultiPolygon":
            anillo = max((a[0] for a in g["coordinates"]), key=len)
        n = len(anillo) - 1 or 1
        lon = sum(p[0] for p in anillo[:-1]) / n
        lat = sum(p[1] for p in anillo[:-1]) / n
        p = f["properties"]
        out.append((lon, lat, p.get("provincia"), p.get("provincia_nombre")))
    return out


def rejilla(centros):
    r = {}
    for lon, lat, prov, nom in centros:
        r.setdefault((int(lon * 4), int(lat * 4)), []).append((lon, lat, prov, nom))
    return r


def provincia_de(lon, lat, rej):
    """Municipio más cercano por cuadrícula; si el entorno está vacío, barrido completo."""
    kx, ky = int(lon * 4), int(lat * 4)
    cands = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cands.extend(rej.get((kx + dx, ky + dy), ()))
    if not cands:
        for c in rej.values():
            cands.extend(c)
    mejor, dmin = None, 1e9
    for clon, clat, prov, nom in cands:
        d = (clon - lon) ** 2 + (clat - lat) ** 2
        if d < dmin:
            dmin, mejor = d, (prov, nom)
    return mejor


def muestras(geom, tope):
    """Vértices repartidos por todo el fichero, no los primeros."""
    if geom["type"] in ("Point",):
        return [geom["coordinates"][:2]]
    if geom["type"] in ("MultiPoint", "LineString"):
        pts = geom["coordinates"]
        return [p[:2] for p in pts[:tope]]
    if geom["type"] == "MultiLineString":
        pts = [p for linea in geom["coordinates"] for p in linea]
        return [p[:2] for p in pts[:tope]]
    if geom["type"] == "Polygon":
        pts = [p for anillo in geom["coordinates"] for p in anillo]
        return [p[:2] for p in pts[:tope]]
    if geom["type"] == "MultiPolygon":
        pts = [p for poli in geom["coordinates"] for anillo in poli for p in anillo]
        return [p[:2] for p in pts[:tope]]
    return []


def dinamicas():
    """Capas cuyo contenido cambia cada hora: su cobertura de hoy no es su ámbito.

    `aemet-zonas` son las zonas con aviso ACTIVO: si hoy solo hay cuatro avisos en
    Extremadura, medirlas dice «provincial» y es mentira — mañana pueden ser veinte
    provincias. Se marcan nacionales por diseño, no por lo que haya en el fichero.
    """
    try:
        cat = json.load(open(os.path.join(DATOS, "catalogo.json"), encoding="utf-8"))["capas"]
    except Exception:
        return set()
    return {k for k, v in cat.items() if v.get("modo") in ("vivo",)}


EVENTOS = {
    # Capas de sucesos: el objeto se mueve de sitio cada día. Donde caiga hoy no dice
    # nada de su ámbito. Se marcan nacionales y se explica en el motivo.
    "alertas-gdacs": "sucesos: el aviso de hoy está donde está, no define la cobertura",
}


def main():
    print("Ámbito medido de cada capa")
    vivas = dinamicas()
    centros = centroides()
    rej = rejilla(centros)
    print(f"  {len(centros)} municipios de referencia")

    capas, sin_fichero = capas_del_visor(), []
    salida, resumen = {}, {}
    for c in capas:
        if c["carpeta"]:
            salida[c["id"]] = {"ambito": "nacional", "etiqueta": "España",
                               "motivo": "capa troceada por provincia: cubre el país",
                               "provincias": [], "ccaa": [], "features": None, "bbox": None}
            continue
        if not c["fichero"]:
            sin_fichero.append(c["id"])
            continue
        ruta = os.path.join(RAIZ, c["fichero"])
        if not os.path.exists(ruta):
            sin_fichero.append(c["id"])
            continue
        try:
            d = json.load(open(ruta, encoding="utf-8"))
        except Exception as e:
            print(f"  [X] {c['id']}: {type(e).__name__}")
            continue
        feats = d.get("features") or []
        if not feats:
            continue
        # muestreo repartido: paso fijo sobre el total
        paso = max(1, len(feats) // MUESTRAS)
        elegidos = feats[::paso][:MUESTRAS]
        provs, ccaas = set(), set()
        x0 = y0 = 1e9
        x1 = y1 = -1e9
        dentro = fuera = 0
        for f in elegidos:
            g = f.get("geometry")
            if not g:
                continue
            for lon, lat in muestras(g, max(8, MUESTRAS // max(1, len(elegidos)))):
                if -20 < lon < 6 and 27 < lat < 45:
                    dentro += 1
                    x0, y0, x1, y1 = min(x0, lon), min(y0, lat), max(x1, lon), max(y1, lat)
                    p = provincia_de(lon, lat, rej)
                    if p and p[0]:
                        provs.add(p[0])
                        ccaas.add(CCAA.get(p[0], "?"))
                else:
                    fuera += 1
        if not provs:
            salida[c["id"]] = {"ambito": "nacional", "etiqueta": "España",
                               "motivo": "sin geometría útil para clasificar",
                               "provincias": [], "ccaa": [], "features": len(feats), "bbox": None}
            continue
        if c["id"] in vivas or c["id"] in EVENTOS:
            salida[c["id"]] = {"ambito": "nacional", "etiqueta": "España",
                               "motivo": EVENTOS.get(c["id"],
                                                     "capa dinámica: su cobertura de hoy no es su ámbito"),
                               "provincias": sorted(provs), "ccaa": sorted(ccaas),
                               "features": len(feats),
                               "bbox": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]}
            resumen["nacional"] = resumen.get("nacional", 0) + 1
            continue
        if fuera > dentro:
            salida[c["id"]] = {"ambito": "mundo", "etiqueta": "Mundo",
                               "motivo": f"{fuera} muestras fuera de España de {dentro + fuera}",
                               "provincias": sorted(provs), "ccaa": sorted(ccaas),
                               "features": len(feats), "bbox": None}
            resumen["mundo"] = resumen.get("mundo", 0) + 1
            continue
        ancho, alto = (x1 - x0) / 9.5, (y1 - y0) / 7.5
        if len(provs) >= UMBRAL_NACIONAL or (ancho > UMBRAL_BBOX and alto > UMBRAL_BBOX):
            amb, et = "nacional", "España"
        elif len(ccaas) == 1:
            nombre = next(iter(ccaas))
            if len(provs) == 1:
                prov = next(iter(provs))
                amb = "provincia"
                et = next((n for _, _, p, n in centros if p == prov), nombre)
            else:
                amb, et = "ccaa", nombre
        else:
            amb, et = "parcial", " / ".join(sorted(ccaas))[:60]
        salida[c["id"]] = {"ambito": amb, "etiqueta": et,
                           "provincias": sorted(provs), "ccaa": sorted(ccaas),
                           "features": len(feats),
                           "bbox": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]}
        resumen[amb] = resumen.get(amb, 0) + 1

    for cid, v in salida.items():
        resumen.setdefault(v["ambito"], 0)
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"generado": datetime.datetime.now(datetime.timezone.utc)
                   .strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "regla": f"nacional si >= {UMBRAL_NACIONAL} provincias o bbox > "
                            f"{int(UMBRAL_BBOX * 100)}% de España; ccaa si una sola comunidad; "
                            "provincia si una sola; el resto, parcial",
                   "capas": salida}, fh, ensure_ascii=False, indent=0)
    print(f"  {len(salida)} capas · " + " · ".join(f"{k} {v}" for k, v in sorted(resumen.items())))
    for cid in sorted(salida):
        v = salida[cid]
        if v["ambito"] != "nacional":
            print(f"    {cid:26s} {v['ambito']:9s} {v['etiqueta']}")
    if sin_fichero:
        print(f"  sin fichero: {len(sin_fichero)} {sin_fichero[:6]}")


if __name__ == "__main__":
    main()
