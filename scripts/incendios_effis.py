# -*- coding: utf-8 -*-
"""Superficie quemada por incendio forestal en España (EFFIS · Copernicus).

Lo que aporta: el visor tiene alertas de desastre globales (GDACS) y terremotos, pero no tenía
ni un dato de incendios en España. Esto no es un aviso en vivo: es el **perímetro quemado**
que EFFIS (Emergency Management Service de Copernicus) deriva de MODIS, con la fecha del incendio
y las hectáreas. Sirve para responder «qué se ha quemado aquí y cuándo», que es otra pregunta.

Fuente: WFS público de EFFIS (`maps.effis.emergency.copernicus.eu`), capa `ms:modis.ba.poly`.
El WFS **no ofrece GeoJSON** (devuelve 502 si se pide `application/json`): hay que pedir GML y
convertirlo. Se pagina con `startIndex`/`maxFeatures` porque el servidor no siempre devuelve el
lote entero.

Licencia: datos Copernicus, reutilización libre con atribución (Reglamento (UE) 2021/696 y
política de datos de Copernicus). © European Union, Copernicus EMS — EFFIS.

Qué se deja fuera y por qué: los polígonos de menos de 1 ha son píxeles sueltos de MODIS (250 m)
que a esta escala no son incendios sino ruido. No se descargan las capas `nrt` (tiempo real) en
esta capa: cambian cada hora y romperían la caché del visor; el refresco diario basta.

    python scripts/incendios_effis.py
"""
import datetime
import json
import os
import re
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
BASE = "https://maps.effis.emergency.copernicus.eu/effis"
CAPA = "ms:modis.ba.poly"
# España peninsular + Baleares + Canarias en un solo bbox (incluye Portugal: se filtra por país)
BBOX = "-18.5,27.5,4.6,44.0"
AREA_MIN_HA = 1.0
LOTE = 2000
MAX_VERTICES = 250          # por anillo; por encima se decima
SALIDA = os.path.join(DATOS, "incendios_effis.geojson")
RECIBO = os.path.join(DATOS, "incendios_effis_recibo.json")


def pide(url):
    req = urllib.request.Request(url, headers={"User-Agent": "OpenInfraES/1.0 (+ntizar.github.io)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read().decode("utf-8", "replace")


def lotes():
    """Genera el GML por lotes. No se acumula: 23.000 polígonos son ~180 MB de XML.

    El servidor devuelve 1.897 objetos por petición aunque se pidan 2.000, así que se avanza con
    el número REAL recibido, no con `LOTE`. Si un lote no aporta ids nuevos (servidor que ignora
    `startIndex`), se corta: repetir el mismo lote sería publicar duplicados.
    """
    inicio, vistos = 0, set()
    while inicio < 60000:
        url = (f"{BASE}?service=WFS&version=1.1.0&request=GetFeature&typeName={CAPA}"
               f"&bbox={BBOX}&maxFeatures={LOTE}&startIndex={inicio}")
        xml = pide(url)
        ids = re.findall(r'gml:id="modis\.ba\.poly\.(\d+)"', xml)
        nuevos = [i for i in ids if i not in vistos]
        print(f"  lote startIndex={inicio}: {len(ids)} objetos · {len(nuevos)} nuevos")
        if not nuevos:
            break
        vistos.update(nuevos)
        yield xml
        inicio += len(ids)
    print(f"  total descargado: {len(vistos)} objetos únicos")


def valor(frag, etiqueta):
    m = re.search(rf"<ms:{etiqueta}>(.*?)</ms:{etiqueta}>", frag, re.S)
    return m.group(1).strip() if m else None


def anillo(frag):
    """Primer anillo exterior en [lon, lat] (GML trae posList lat lon sueltos)."""
    m = re.search(r"<gml:posList[^>]*>(.*?)</gml:posList>", frag, re.S)
    if not m:
        return None
    nums = [float(x) for x in m.group(1).split()]
    if len(nums) < 6:
        return None
    pts = [[round(nums[i + 1], 4), round(nums[i], 4)] for i in range(0, len(nums) - 1, 2)]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) > MAX_VERTICES:
        paso = max(1, len(pts) // MAX_VERTICES)
        recorte = pts[::paso]
        if recorte[-1] != pts[-1]:
            recorte.append(pts[-1])
        pts = recorte
    return pts


def main():
    print("EFFIS · superficie quemada por incendio")
    feats, descartados = [], {"fuera_de_espana": 0, "sin_geometria": 0, "menos_de_1ha": 0}
    for xml in lotes():
        for frag in re.findall(r"<gml:featureMember>(.*?)</gml:featureMember>", xml, re.S):
            pais = valor(frag, "COUNTRY")
            if pais != "ES":
                descartados["fuera_de_espana"] += 1
                continue
            try:
                ha = float(valor(frag, "AREA_HA") or 0)
            except ValueError:
                ha = 0.0
            if ha < AREA_MIN_HA:
                descartados["menos_de_1ha"] += 1
                continue
            pts = anillo(frag)
            if not pts:
                descartados["sin_geometria"] += 1
                continue
            fecha = (valor(frag, "FIREDATE") or "")[:10]
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [pts]},
                "properties": {
                    "id": valor(frag, "id"),
                    "fecha": fecha or None,
                    "hectareas": round(ha, 1),
                    "provincia": valor(frag, "PROVINCE"),
                    "municipio": valor(frag, "COMMUNE"),
                    "clase": valor(frag, "CLASS"),
                    "actualizado": (valor(frag, "LASTUPDATE") or "")[:10],
                },
            })

    feats.sort(key=lambda f: f["properties"]["fecha"] or "")
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
    escribir_recibo(feats, descartados)


def escribir_recibo(feats, descartados, descargado=None):
    """El recibo se puede reconstruir desde el GeoJSON (`--rehacer`): si falla la red a mitad, el
    dato no se pierde y no hay que volver a bajar 180 MB para tener la procedencia."""
    fechas = [f["properties"]["fecha"] for f in feats if f["properties"].get("fecha")]
    total_ha = sum(f["properties"]["hectareas"] for f in feats)
    por_prov = {}
    for f in feats:
        p = f["properties"]["provincia"] or "sin provincia"
        por_prov[p] = round(por_prov.get(p, 0) + f["properties"]["hectareas"], 0)

    recibo = {
        "capa": "incendios-effis",
        "titulo": "Incendios forestales · superficie quemada (EFFIS)",
        "fuente": "Copernicus EMS",
        "editor": "European Commission JRC · WFS mapserver EFFIS (capa MODIS burned area)",
        "producto": "Perímetro quemado derivado de MODIS (250 m), histórico por incendio",
        "url": f"{BASE}?service=WFS&version=1.1.0&request=GetFeature&typeName={CAPA}&bbox={BBOX}",
        "licencia": "Copernicus: reutilización libre con atribución (© Unión Europea, Copernicus EMS · EFFIS)",
        "crs": "EPSG:4326",
        "features": len(feats),
        "descartados": descartados,
        "area_min_ha": AREA_MIN_HA,
        "hectareas_totales": round(total_ha, 0),
        "incendio_mas_reciente": fechas[-1] if fechas else None,
        "incendio_mas_antiguo": fechas[0] if fechas else None,
        "descargado": descargado or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": "WFS 1.1.0 GML paginado por startIndex (el servidor no admite GeoJSON) → "
                  "anillo exterior, redondeo a 4 decimales, decimado a 250 vértices",
        "provincias_top": dict(sorted(por_prov.items(), key=lambda x: -x[1])[:10]),
        "fichero": os.path.basename(SALIDA),
    }
    with open(RECIBO, "w", encoding="utf-8") as f:
        json.dump(recibo, f, ensure_ascii=False, indent=1)
    kb = os.path.getsize(SALIDA) / 1024
    print(f"  → {len(feats)} incendios · {total_ha:,.0f} ha · {kb:,.0f} kB")
    print(f"  fechas: {recibo['incendio_mas_antiguo']} → {recibo['incendio_mas_reciente']}")
    print(f"  descartados: {descartados}")


if __name__ == "__main__":
    if "--rehacer" in sys.argv:
        previo = {}
        if os.path.exists(RECIBO):
            previo = json.load(open(RECIBO, encoding="utf-8"))
        datos = json.load(open(SALIDA, encoding="utf-8"))["features"]
        escribir_recibo(datos, previo.get("descartados") or {}, previo.get("descargado"))
        print(f"recibo rehecho con {len(datos)} objetos")
    else:
        main()
