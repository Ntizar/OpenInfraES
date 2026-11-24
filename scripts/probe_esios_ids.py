#!/usr/bin/env python3
"""Sonda temporal: qué indicadores ESIOS existen en el rango de «Generación T.Real».

Existe porque la VM no tiene la clave de ESIOS y el API sin clave devuelve 403: la lista de
indicadores solo se puede leer desde el workflow, que sí tiene el secret. Escribe
datos/_probe_esios.json con id, nombre, unidad y último valor de cada id que conteste.
Se borra en cuanto sepamos los ids buenos.
"""
import json
import os
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://api.esios.ree.es/indicators"
UA = {"Accept": "application/json", "User-Agent": "OpenInfraES/1.0"}


def token():
    for ruta in (os.path.join(RAIZ, ".env"), os.path.join(os.path.dirname(RAIZ), ".env")):
        if not os.path.exists(ruta):
            continue
        for linea in open(ruta, encoding="utf-8"):
            if linea.startswith("ESIOS_TOKEN=") and linea.split("=", 1)[1].strip():
                return linea.split("=", 1)[1].strip()
    return None


TK = token()
CAB = dict(UA)
if TK:
    CAB["x-api-key"] = TK


def pide(ind):
    req = urllib.request.Request("%s/%s?locale=es" % (BASE, ind), headers=CAB)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    salida = {"token": bool(TK), "indicadores": []}
    for ind in range(2030, 2061):
        try:
            d = pide(ind).get("indicator", {})
        except urllib.error.HTTPError as e:
            salida["indicadores"].append({"id": ind, "http": e.code})
            continue
        except Exception as e:  # noqa: BLE001
            salida["indicadores"].append({"id": ind, "error": type(e).__name__})
            continue
        vals = [v for v in (d.get("values") or []) if v.get("value") is not None]
        mag = d.get("magnitud")
        tie = d.get("time")
        salida["indicadores"].append({
            "id": ind,
            "nombre": d.get("name"),
            "corto": d.get("short_name"),
            "unidad": d.get("unit"),
            # ESIOS no siempre devuelve dicts: `magnitud` y `time` llegan como lista en algunos
            "magnitud": mag.get("name") if isinstance(mag, dict) else None,
            "tipo": tie.get("type") if isinstance(tie, dict) else None,
            "ultima": vals[-1]["datetime"] if vals else None,
            "valor": vals[-1]["value"] if vals else None,
            "n": len(vals),
        })
    os.makedirs(os.path.join(RAIZ, "datos"), exist_ok=True)
    with open(os.path.join(RAIZ, "datos", "_probe_esios.json"), "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    for x in salida["indicadores"]:
        if x.get("nombre"):
            print("%5s %-46s %-8s %s" % (x["id"], x["nombre"][:46], x.get("unidad"), x.get("ultima")))


if __name__ == "__main__":
    main()
