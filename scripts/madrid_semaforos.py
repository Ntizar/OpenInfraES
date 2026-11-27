# -*- coding: utf-8 -*-
"""Cabezas de semáforo de Madrid (Ayuntamiento · sigma.madrid.es).

Lo que aporta: no hay nada parecido en el visor. Es el mobiliario de control de tráfico
de la ciudad, punto a punto, desde el servicio REST oficial del Ayuntamiento.

Fuente oficial: `sigma.madrid.es/hosted/rest/services/MOVILIDAD/SEMAFOROS/MapServer/4`,
consulta `query?...&f=geojson`. Sin clave.

Trampa: el servicio devuelve como mucho 2.000 objetos por consulta
(`maxRecordCount`) y **no avisa**. Son 2.301: se pagina con `resultOffset` y se comprueba
que el total cuadra con el `returnCountOnly` de antes. Si no cuadra, no se escribe nada y
se queda el fichero anterior: media ciudad sin semáforos es peor que la capa de ayer.

Qué NO trae: el atributo `TIPO_ELEM` viene a `other` en todos los objetos, así que la capa
dice DÓNDE hay un semáforo, no de qué tipo ni en qué estado. No se inventa el campo.

    python scripts/madrid_semaforos.py
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
BASE = "https://sigma.madrid.es/hosted/rest/services/MOVILIDAD/SEMAFOROS/MapServer/4/query"
SALIDA = os.path.join(DATOS, "madrid_semaforos.geojson")
RECIBO = os.path.join(DATOS, "madrid_semaforos_recibo.json")
PAGINA = 2000
DECIMALES = 5
UA = {"User-Agent": "OpenInfraES/1.0 (+ntizar.github.io)"}


def consulta(**kw):
    q = urllib.parse.urlencode({"f": "geojson", "outSR": 4326, **kw})
    req = urllib.request.Request(BASE + "?" + q, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    print("Semáforos de Madrid · sigma.madrid.es")
    total = consulta(where="1=1", returnCountOnly="true").get("count")
    print(f"  el servicio declara {total} objetos")
    todas, offset = [], 0
    while offset < (total or 0):
        d = consulta(where="1=1", outFields="OBJECTID,TIPO_ELEM", returnGeometry="true",
                     resultOffset=offset, resultRecordCount=PAGINA)
        feats = d.get("features") or []
        todas.extend(feats)
        print(f"  offset {offset}: {len(feats)} (acumulado {len(todas)}/{total})")
        if not feats:
            break
        offset += PAGINA
    if total is not None and len(todas) != total:
        raise SystemExit(f"no cuadra: {len(todas)} de {total}. No se toca el fichero.")

    salida = []
    for f in todas:
        c = f["geometry"]["coordinates"]
        f["geometry"]["coordinates"] = [round(c[0], DECIMALES), round(c[1], DECIMALES)]
        tipo = (f.get("properties") or {}).get("TIPO_ELEM")
        # todos vienen como 'other': se descarta el campo en vez de publicar un dato falso
        f["properties"] = {k: v for k, v in {"id": (f.get("properties") or {}).get("OBJECTID"),
                                            "tipo": tipo if tipo not in (None, "", "other") else None}.items()
                           if v is not None}
        salida.append(f)

    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": salida}, fh,
                  ensure_ascii=False, separators=(",", ":"))

    recibo = {
        "capa": "madrid-semaforos",
        "titulo": "Semáforos de Madrid",
        "fuente": "Ayuntamiento de Madrid · sigma.madrid.es",
        "editor": "Ayuntamiento de Madrid · Servicio de Información Geográfica (sigma)",
        "producto": "MOVILIDAD/SEMAFOROS · capa 4 «Cabezas semáforos» (ArcGIS REST)",
        "url": BASE,
        "licencia": "Reutilización Ley 37/2007 con atribución",
        "url_terminos": "https://sigma.madrid.es/",
        "crs": "EPSG:4326 (pedido con outSR)",
        "features": len(salida),
        "descargado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": f"query ArcGIS REST paginada con resultOffset (el servicio corta en {PAGINA}); "
                  f"coordenadas a {DECIMALES} decimales",
        "ambito": "Madrid",
        "nota": "El campo TIPO_ELEM viene a 'other' en todos los objetos: se descarta antes que "
                "publicar un tipo inventado. La capa dice dónde hay semáforo, no de qué clase.",
        "fichero": os.path.basename(SALIDA),
    }
    with open(RECIBO, "w", encoding="utf-8") as fh:
        json.dump(recibo, fh, ensure_ascii=False, indent=1)
    print(f"  → {len(salida)} semáforos · {os.path.getsize(SALIDA) / 1024:.0f} kB")


if __name__ == "__main__":
    main()
