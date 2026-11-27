# -*- coding: utf-8 -*-
"""Aerogeneradores de Navarra, uno a uno (IDENA · Gobierno de Navarra).

Lo que aporta: el visor ya tiene los parques eólicos nacionales por INSTALACIÓN (MW
declarados en el registro). Esto trae la máquina: 1.422 aerogeneradores con modelo,
potencia unitaria, diámetro de rotor, altura de buje y fecha de alta. Sirve para lo que
la capa nacional no puede: ver si un parque está repotenciado y con qué máquinas.

Fuente oficial: WFS 2.0 de IDENA (Infraestructura de Datos Espaciales de Navarra),
`https://idena.navarra.es/ogc/wfs`, tipo `IDENA:ENERGI_Sym_AeroGen`, salida GeoJSON
(`outputFormat=application/json`) y `srsName=EPSG:4326`.

Trampa del servicio: **devuelve 1.000 objetos y calla**. `numberMatched` dice 1.422, pero
sin paginar llegan 1.000. Se pide con `startIndex` hasta que una página venga corta; si no,
la capa sale con 1.000 y un tercio de Navarra sin molinos, que es peor que no tenerla.

Ámbito: Navarra. La capa se dibuja a partir de zoom 9 y se declara como tal en la ficha.

    python scripts/navarra_eolicos.py
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
WFS = "https://idena.navarra.es/ogc/wfs"
TIPO = "IDENA:ENERGI_Sym_AeroGen"
PAGINA = 1000
SALIDA = os.path.join(DATOS, "navarra_eolicos.geojson")
RECIBO = os.path.join(DATOS, "navarra_eolicos_recibo.json")
DECIMALES = 5
CAMPOS = {"NOMBRE": "nombre", "MODELO": "modelo", "POT_MW": "potencia_mw",
          "PARQUE": "parque", "DIAMET_M": "rotor_m", "ALTURA_M": "buje_m",
          "BEGINLIFE": "alta"}


def pide(inicio):
    q = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": TIPO, "outputFormat": "application/json",
        "srsName": "EPSG:4326", "count": PAGINA, "startIndex": inicio})
    req = urllib.request.Request(WFS + "?" + q,
                                 headers={"User-Agent": "OpenInfraES/1.0 (+ntizar.github.io)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    print("Aerogeneradores de Navarra · IDENA WFS")
    todas, inicio, total = [], 0, None
    while True:
        d = pide(inicio)
        total = d.get("numberMatched") or total
        feats = d.get("features") or []
        todas.extend(feats)
        print(f"  página startIndex={inicio}: {len(feats)} (acumulado {len(todas)}/{total})")
        if len(feats) < PAGINA or not feats:
            break
        inicio += PAGINA
        if inicio > 50000:
            break
    if total and len(todas) < total:
        raise SystemExit(f"faltan objetos: {len(todas)}/{total}. No se toca el fichero.")

    salida = []
    for f in todas:
        p = f.get("properties") or {}
        props = {v: p.get(k) for k, v in CAMPOS.items()}
        if isinstance(props.get("alta"), str) and "/" in props["alta"]:
            a, m, d = props["alta"].split("/")
            props["alta"] = f"{d}-{m}-{a}"
        props = {k: v for k, v in props.items() if v not in (None, "", "?")}
        f["properties"] = props
        c = f["geometry"]["coordinates"]
        f["geometry"]["coordinates"] = [round(c[0], DECIMALES), round(c[1], DECIMALES)]
        salida.append(f)

    salida.sort(key=lambda f: ((f["properties"].get("parque") or "zzz"),
                              f["properties"].get("nombre") or ""))
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": salida}, fh,
                  ensure_ascii=False, separators=(",", ":"))

    mw = sum(f["properties"].get("potencia_mw") or 0 for f in salida)
    parques = {f["properties"].get("parque") for f in salida if f["properties"].get("parque")}
    modelos = {f["properties"].get("modelo") for f in salida if f["properties"].get("modelo")}

    recibo = {
        "capa": "navarra-eolicos",
        "titulo": "Aerogeneradores de Navarra, uno a uno (IDENA)",
        "fuente": "Gobierno de Navarra · IDENA",
        "editor": "Gobierno de Navarra · IDENA (Infraestructura de Datos Espaciales de Navarra)",
        "producto": "WFS 2.0 · IDENA:ENERGI_Sym_AeroGen",
        "url": WFS,
        "licencia": "CC BY 4.0",
        "url_terminos": "https://idena.navarra.es/",
        "crs": "EPSG:4326 (pedido con srsName; nativo UTM 30N/25830)",
        "features": len(salida),
        "parques": len(parques),
        "modelos": len(modelos),
        "potencia_total_mw": round(mw, 1),
        "descargado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": f"WFS paginado con startIndex (el servicio corta en {PAGINA} y no lo dice); "
                  f"coordenadas a {DECIMALES} decimales",
        "ambito": "Navarra",
        "nota": "Capa regional: se dibuja a partir de zoom 9. Complementa `eolicos` "
                "(instalaciones nacionales) con la máquina: potencia unitaria, rotor, buje y alta.",
        "fichero": os.path.basename(SALIDA),
    }
    with open(RECIBO, "w", encoding="utf-8") as fh:
        json.dump(recibo, fh, ensure_ascii=False, indent=1)
    print(f"  → {len(salida)} aerogeneradores · {len(parques)} parques · {mw:.1f} MW · "
          f"{os.path.getsize(SALIDA) / 1024:.0f} kB")


if __name__ == "__main__":
    main()
