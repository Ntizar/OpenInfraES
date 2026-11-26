# -*- coding: utf-8 -*-
"""Resumen previo de las capas de puntos: burbujas nacionales en un fichero pequeño.

Una capa de puntos pesa entre 1 y 10 MB y el navegador tarda segundos en tenerla (descarga +
parseo). Mientras llega, el mapa está vacío y parece que el visor no responde. Este script
precalcula la misma capa agregada en una rejilla de 0,05° (~5,5 km): 50–100 KB, ~2 % del
original, que el visor pinta al instante como burbujas con la cifra real de cada celda. Cuando
llega el GeoJSON completo, el visor repinta con los puntos de verdad.

Salida: datos/resumen/<id>.json  {"capa","paso","total","celdas":[[lat,lng,n],...]}
Recibo: datos/resumen/_recibo.json con celdas, bytes y puntos de cada capa.

Uso:
    python3 scripts/resumen_puntos.py            # solo las que faltan o están viejas
    python3 scripts/resumen_puntos.py --todo     # todas, aunque ya existan
"""
import json
import os
import re
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
DEST = os.path.join(DATOS, "resumen")
PASO = 0.05          # grados: 0,05° ~ 5,5 km en el paralelo 40


def capas_de_puntos():
    """[(id, fichero|carpeta)] de las capas `tipo:"punto"` del array CAPAS del visor."""
    html = open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read()
    i = html.index("const CAPAS = [")
    j = html.index("[", i)
    bloques, buf, ll = [], "", 0
    for k in range(j + 1, len(html)):
        ch = html[k]
        if ch == "{":
            ll += 1
            if ll == 1:
                buf = "{"
                continue
        elif ch == "}":
            ll -= 1
            if ll == 0:
                bloques.append(buf)
        if ll:
            buf += ch
    salida = []
    for b in bloques:
        if not re.search(r'tipo:"punto"', b):
            continue
        cid = (re.search(r'id:"([^"]+)"', b) or [None, ""])[1]
        fich = (re.search(r'fichero:"([^"]+)"', b) or [None, None])[1]
        carp = (re.search(r'carpeta:"([^"]+)"', b) or [None, None])[1]
        if cid and (fich or carp):
            salida.append((cid, fich, carp))
    return salida


def puntos_de_feature(g):
    """Un punto, venga como Point o como MultiPoint (los nucleos del IGN son MultiPoint)."""
    if not g:
        return None
    a = g.get("coordinates")
    while isinstance(a, list) and a and isinstance(a[0], list):
        a = a[0]
    if isinstance(a, list) and len(a) >= 2 and isinstance(a[0], (int, float)):
        return a[0], a[1]          # lng, lat
    return None


def features_de(cid, fichero, carpeta):
    """Features de la capa: del fichero suelto o de todos los trozos del índice.
    `fichero`/`carpeta` vienen del visor con la ruta completa desde la raíz del repo."""
    if fichero:
        ruta = os.path.join(RAIZ, fichero)
        if os.path.exists(ruta):
            return json.load(open(ruta, encoding="utf-8")).get("features", [])
    if carpeta:
        ruta = os.path.join(RAIZ, carpeta, "index.json")
        if not os.path.exists(ruta):
            return []
        idx = json.load(open(ruta, encoding="utf-8"))
        salida = []
        for p in idx.get("partes", []):
            f = os.path.join(RAIZ, carpeta, p["fichero"])
            if os.path.exists(f):
                try:
                    salida.extend(json.load(open(f, encoding="utf-8")).get("features", []))
                except Exception as e:                      # un trozo roto no tumba el resumen
                    print("  aviso:", cid, p["fichero"], e)
        return salida
    return []


def resumen(feats):
    celdas = {}
    total = 0
    for f in feats:
        p = puntos_de_feature(f.get("geometry"))
        if not p:
            continue
        lng, lat = p
        k = (round(lat / PASO), round(lng / PASO))
        celdas[k] = celdas.get(k, 0) + 1
        total += 1
    # lat y lng del centro de la celda, redondeados a 4 decimales (~11 m): el JSON se queda corto
    lista = [[round(k[0] * PASO, 4), round(k[1] * PASO, 4), n] for k, n in
             sorted(celdas.items(), key=lambda x: -x[1])]
    return total, lista


def main():
    todo = "--todo" in sys.argv
    os.makedirs(DEST, exist_ok=True)
    recibo = {"paso": PASO, "generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "capas": {}}
    for cid, fichero, carpeta in capas_de_puntos():
        salida = os.path.join(DEST, cid + ".json")
        fuente = os.path.join(RAIZ, carpeta, "index.json") if carpeta else (
            os.path.join(RAIZ, fichero) if fichero else None)
        if (not todo and os.path.exists(salida) and fuente and os.path.exists(fuente)
                and os.path.getmtime(salida) >= os.path.getmtime(fuente)):
            continue
        feats = features_de(cid, fichero, carpeta)
        if not feats:
            print(f"{cid:<26} sin datos")
            continue
        total, celdas = resumen(feats)
        if not celdas:
            continue
        json.dump({"capa": cid, "paso": PASO, "total": total, "celdas": celdas},
                  open(salida, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        recibo["capas"][cid] = {"total": total, "celdas": len(celdas), "bytes": os.path.getsize(salida)}
        print(f"{cid:<26} {total:>7} puntos → {len(celdas):>6} celdas "
              f"{os.path.getsize(salida) / 1024:>7.1f} KB")
    json.dump(recibo, open(os.path.join(DEST, "_recibo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
