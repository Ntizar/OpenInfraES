# -*- coding: utf-8 -*-
"""Fallas activas del Cuaternario en la Península Ibérica (QAFI v4 · IGME-CSIC).

Lo que aporta: el visor enseñaba terremotos (lo que ya ha temblado) pero no las fallas (por dónde
puede temblar). Son cosas distintas y la segunda es la que sirve para leer un emplazamiento.

Fuente: servicio REST del IGME (`mapas.igme.es/gis/rest/.../IGME_QAFI_v4/MapServer/0`), capa
«QAFI v4 faults»: 201 trazas. Se pide `f=geojson` y `outSR=4326`, así que no hay que convertir
nada. **No hay WFS en el IGME** (el WFSServer devuelve 400): el REST /query es la única vía
vectorial, y es una sola petición de ~476 KB, sin clave y con CORS abierto.

Los nombres de campo vienen truncados a 10 caracteres (herencia del shapefile) y los tres últimos
son códigos numéricos que solo se entienden con la guía QAFI_v4_Guide.pdf. Aquí se traducen a
texto: un «3» no le dice nada a nadie, «especulativa» sí.

Licencia: **CC BY-SA 4.0** (Disclaimer del QAFI). Compartir igual: este GeoJSON derivado se publica
con la misma licencia, y así se declara. No es CC BY a secas y no se debe mezclar sin decirlo.

Capas hermanas que NO se descargan (se quedan fuera a propósito, para no mezclar certeza con duda):
  · MapServer/1 «debated faults» — 108 trazas en discusión
  · MapServer/2 «discarded faults» — 6 descartadas

    python scripts/fallas_qafi.py
"""
import datetime
import json
import os
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
BASE = ("https://mapas.igme.es/gis/rest/services/BasesDatos/IGME_QAFI_v4/MapServer/0/query"
        "?where=1%3D1&outFields=*&outSR=4326&f=geojson")
SALIDA = os.path.join(DATOS, "fallas_qafi.geojson")
RECIBO = os.path.join(DATOS, "fallas_qafi_recibo.json")

# Códigos de la guía QAFI v4 (QAFI_v4_Guide.pdf). Sin esto, la ficha enseña un dígito.
TRAZA = {1: "traza fiable (con afloramiento)", 2: "traza aproximada u oculta",
         3: "traza especulativa"}
ACTIVIDAD = {1: "actividad hasta el Holoceno", 2: "actividad al menos Pleistoceno superior (125 ka)",
             3: "cuaternaria, sin Pleistoceno superior demostrado"}
TASA = {1: "≥ 0,5 mm/año", 2: "0,2–0,5 mm/año", 3: "< 0,2 mm/año", 0: "sin dato"}


def pide(url):
    req = urllib.request.Request(url, headers={"User-Agent": "OpenInfraES/1.0 (+ntizar.github.io)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def texto(v, tabla):
    try:
        return tabla.get(int(v), None)
    except (TypeError, ValueError):
        return None


def main():
    print("QAFI v4 · fallas activas del IGME")
    d = pide(BASE)
    feats = d.get("features", [])
    if not feats:
        raise SystemExit("el IGME no devolvió objetos: no se toca el fichero anterior")

    salida, sin_nombre = [], 0
    for f in feats:
        p = f.get("properties") or {}
        nombre = (p.get("FaultName") or "").strip()
        if not nombre:
            sin_nombre += 1
        props = {
            "nombre": nombre or None,
            "seccion": (p.get("SectionNam") or "").strip() or None,
            "tasa": texto(p.get("Slip_Rate_"), TASA),
            "actividad": texto(p.get("Activity_D"), ACTIVIDAD),
            # Cuánto fiarse de la traza dibujada: una falla especulativa no es lo mismo que una
            # que aflora. Va como texto para que se lea en la ficha y en el CSV.
            "precision": texto(p.get("Fault_Trac"), TRAZA),
            "id_qafi": p.get("ID"),
        }
        f["properties"] = {k: v for k, v in props.items() if v not in (None, "")}
        salida.append(f)

    salida.sort(key=lambda f: (f["properties"].get("nombre") or "zzz"))
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": salida}, fh, ensure_ascii=False)

    por_tasa = {}
    for f in salida:
        t = f["properties"].get("tasa") or "sin dato"
        por_tasa[t] = por_tasa.get(t, 0) + 1

    recibo = {
        "capa": "fallas-qafi",
        "titulo": "Fallas activas del Cuaternario (QAFI v4)",
        "fuente": "IGME · QAFI",
        "editor": "IGME-CSIC · Quaternary Active Faults Database of Iberia (QAFI v4)",
        "producto": "Trazas de falla con actividad cuaternaria aceptada (201), ArcGIS REST /query",
        "url": BASE,
        "licencia": "CC BY-SA 4.0 · compartir igual (atribuir a IGME-CSIC / QAFI)",
        "url_terminos": "https://info.igme.es/qafi/Disclaimer.aspx",
        "crs": "EPSG:4326 (servicio en 4258 ETRS89, convertido por outSR)",
        "features": len(salida),
        "sin_nombre": sin_nombre,
        "por_tasa": por_tasa,
        "descargado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": "GeoJSON directo del MapServer (f=geojson). Sin WFS en el IGME: el WFSServer "
                  "devuelve 400. Códigos numéricos traducidos con QAFI_v4_Guide.pdf",
        "fuera": "MapServer/1 (108 en debate) y MapServer/2 (6 descartadas) no se incluyen",
        "fichero": os.path.basename(SALIDA),
    }
    with open(RECIBO, "w", encoding="utf-8") as fh:
        json.dump(recibo, fh, ensure_ascii=False, indent=1)

    kb = os.path.getsize(SALIDA) / 1024
    print(f"  → {len(salida)} fallas · {kb:,.0f} kB · sin nombre: {sin_nombre}")
    print(f"  tasas: {por_tasa}")


if __name__ == "__main__":
    main()
