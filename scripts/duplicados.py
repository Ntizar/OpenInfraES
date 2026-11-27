#!/usr/bin/env python3
"""duplicados.py — auditor de datos duplicados de OpenInfraES.

Tres preguntas, una pasada:

  1. ¿Dos capas del visor pintan el mismo sitio?  (duplicado en pantalla)
  2. ¿Algún fichero de datos está contenido en otro?  (fuente ya fusionada)
  3. ¿El catálogo tiene dos fichas del mismo producto?  (duplicado administrativo)

El solape se mide por distancia (100 m por defecto), nunca por nombre: dos
«Torrevieja» pueden ser sitios distintos y «IDAM Torrevieja» y «Desalinizadora
de Torrevieja» son el mismo.

Salida humana por consola; `--json` escribe `datos/duplicados.json`.
Sale con 1 si hay duplicado **en pantalla** o **en el catálogo** (el punto 2 es
solo inventario: una fuente fusionada puede quedarse como procedencia).
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(BASE, "datos")
VISOR = os.path.join(BASE, "index.html")
CATALOGO = os.path.join(DATOS, "catalogo.json")
SALIDA = os.path.join(DATOS, "duplicados.json")
CELDA = 0.005          # ~550 m


# ------------------------------------------------------------------ lectura


def capas_del_visor() -> dict[str, str]:
    """id de capa → fichero, leído de `const CAPAS` del visor."""
    try:
        html = open(VISOR, encoding="utf-8").read()
    except OSError:
        return {}
    ini = html.find("const CAPAS = [")
    if ini < 0:
        return {}
    bloque = html[ini:html.find("];", ini)]
    pares = re.findall(r'id\s*:\s*"([^"]+)"(.{0,600}?)fichero\s*:\s*"([^"]+)"', bloque, re.S)
    return {cid: fichero for cid, _, fichero in pares}


def puntos(ruta: str) -> list[tuple[float, float]]:
    """Puntos o centroides de un GeoJSON. Lo que no tenga coordenadas se ignora."""
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    salida = []
    for ft in d.get("features", []):
        g = ft.get("geometry") or {}
        t = g.get("type")
        c = g.get("coordinates") or []
        if t == "Point" and len(c) >= 2:
            salida.append((float(c[0]), float(c[1])))
        elif t in ("Polygon", "MultiPolygon"):
            poli = c[0] if t == "MultiPolygon" and c else c
            anillo = poli[0] if poli else []
            if anillo:
                salida.append((sum(p[0] for p in anillo) / len(anillo),
                               sum(p[1] for p in anillo) / len(anillo)))
    return salida


def ficheros() -> list[str]:
    vistos = []
    for patron in ("datos/*.geojson", "datos/**/*.geojson"):
        for f in glob.glob(patron, recursive=True):
            if f not in vistos and os.path.getsize(f) > 0:
                vistos.append(f)
    return sorted(vistos)


# ------------------------------------------------------------------ solape


def solapes(limite_m: float):
    """Cuenta, para cada par de ficheros, cuántos puntos comparten sitio."""
    cache = {f: puntos(f) for f in ficheros()}
    cache = {f: p for f, p in cache.items() if p}
    rejilla: dict[tuple, list] = defaultdict(list)
    for f, pts in cache.items():
        for x, y in pts:
            rejilla[(int(x / CELDA), int(y / CELDA))].append((f, x, y))

    pares: dict[tuple, int] = defaultdict(int)
    limite = limite_m
    for (cx, cy), lista in rejilla.items():
        vecinos = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                vecinos.extend(rejilla.get((cx + dx, cy + dy), ()))
        for f1, x1, y1 in lista:
            tocados = set()
            for f2, x2, y2 in vecinos:
                if f2 == f1 or f2 in tocados:
                    continue
                d = math.hypot((x1 - x2) * 111320 * math.cos(math.radians(y1)),
                               (y1 - y2) * 110540)
                if d <= limite:
                    pares[(f1, f2)] += 1
                    tocados.add(f2)
    # simetriza (y se queda con el máximo de los dos sentidos)
    final: dict[tuple, int] = {}
    for (a, b), n in pares.items():
        clave = tuple(sorted((a, b)))
        final[clave] = max(final.get(clave, 0), n)
    return {f: len(p) for f, p in cache.items()}, final


# ------------------------------------------------------------------ catálogo


def duplicados_catalogo():
    """Fallo: dos fichas con el mismo organismo y el mismo título (es el mismo dato).
    Aviso: mismo texto de producto pero título distinto — el campo `producto` guarda el
    método, así que dos capas distintas pueden compartirlo sin ser duplicado."""
    try:
        cat = json.load(open(CATALOGO, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], [], []
    capas = cat.get("capas") or cat
    if isinstance(capas, dict):
        capas = list(capas.values())
    por_titulo: dict[tuple, list] = defaultdict(list)
    por_producto: dict[tuple, list] = defaultdict(list)
    alias = []
    for e in capas:
        if e.get("alias_de"):
            alias.append((e.get("id"), e["alias_de"]))
            continue          # declarada como otra vista del mismo dato: no es duplicado
        titulo = (e.get("titulo") or "").strip().lower()
        prod = (e.get("producto") or "").strip().lower()
        if titulo:
            por_titulo[(e.get("organismo"), titulo)].append(e.get("id"))
        if prod:
            por_producto[(e.get("organismo"), prod)].append(e.get("id"))
    fallos = [(o, t[:70], v) for (o, t), v in por_titulo.items() if len(v) > 1]
    repetidos = {t for _, t, _ in fallos}
    avisos = [(o, p[:70], v) for (o, p), v in por_producto.items()
              if len(v) > 1 and p not in repetidos]
    return fallos, avisos, alias


# ------------------------------------------------------------------ main


def main(argv):
    umbral = 0.80
    limite = 100.0
    for i, a in enumerate(argv):
        if a == "--umbral" and i + 1 < len(argv):
            umbral = float(argv[i + 1])
        if a == "--radio" and i + 1 < len(argv):
            limite = float(argv[i + 1])

    n_pts, pares = solapes(limite)
    visor = capas_del_visor()
    rel = {cid: os.path.normpath(os.path.join(BASE, f)) for cid, f in visor.items()}

    contenido = []
    for (a, b), n in sorted(pares.items(), key=lambda kv: -kv[1]):
        na, nb = n_pts.get(a, 0), n_pts.get(b, 0)
        if not na or not nb:
            continue
        frac_menor = n / min(na, nb)
        if frac_menor >= umbral:
            menor, mayor = (a, b) if na <= nb else (b, a)
            contenido.append({
                "dentro": os.path.relpath(menor, BASE),
                "de": os.path.relpath(mayor, BASE),
                "puntos_dentro": n_puntos(n, na, nb, menor == a),
                "coincidencias": n,
                "fraccion": round(frac_menor, 3),
            })

    # duplicado en pantalla: dos ficheros DISTINTOS, ambos pintados, que solapan
    # (que un mismo fichero sirva a varias capas no es duplicado: es el patrón bueno,
    # una descarga y varias vistas — plantas, hidro, gasgen y resto salen de plantas.geojson)
    pintadas = defaultdict(list)
    for cid, ruta in rel.items():
        pintadas[ruta].append(cid)
    compartidos = [{"fichero": os.path.relpath(f, BASE), "capas": ids}
                   for f, ids in pintadas.items() if len(ids) > 1]
    pantalla = []
    for c in contenido:
        if c["dentro"] in pintadas and c["de"] in pintadas:
            pantalla.append({"contenida": c["dentro"], "en": c["de"],
                             "capas": pintadas[c["dentro"]] + pintadas[c["de"]]})

    catalogo, avisos_cat, alias_cat = duplicados_catalogo()

    print("=" * 62)
    print(" OPENINFRAES · AUDITOR DE DUPLICADOS")
    print("=" * 62)
    print(f" ficheros con geometría ....... {len(n_pts)}")
    print(f" puntos indexados ............. {sum(n_pts.values())}")
    print(f" radio de solape .............. {limite:.0f} m · umbral {umbral:.0%}")
    print("-" * 62)
    print(f" EN PANTALLA (fallo) .......... {len(pantalla)}")
    for p in pantalla:
        if "fichero" in p:
            print(f"   x {p['fichero']} lo pintan {len(p['capas'])} capas: {', '.join(p['capas'])}")
        else:
            print(f"   x {p['contenida']} ⊂ {p['en']} · capas {', '.join(p['capas'])}")
    print(f" CATÁLOGO repetido (fallo) .... {len(catalogo)}")
    for org, prod, ids in catalogo:
        print(f"   x {org} · «{prod}» → {', '.join(str(i) for i in ids)}")
    print(f" Mismo fichero, varias capas .. {len(compartidos)} (patrón bueno, no fallo)")
    for c in compartidos:
        print(f"   · {c['fichero']} → {', '.join(c['capas'])}")
    print(f" Alias declarados en catálogo .. {len(alias_cat)} (no son duplicados)")
    if avisos_cat:
        print(f" Mismo método, título distinto  {len(avisos_cat)} (a revisar, no fallo)")
        for org, prod, ids in avisos_cat[:6]:
            print(f"   ? {org} · «{prod}» → {', '.join(str(i) for i in ids)}")
    print(f" FUENTES ya fusionadas ........ {len(contenido)} (inventario, no fallo)")
    for c in contenido[:12]:
        print(f"   · {c['dentro']} ⊂ {c['de']} · {c['fraccion']:.0%} ({c['coincidencias']} puntos)")

    if "--json" in argv:
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump({"radio_m": limite, "umbral": umbral, "pantalla": pantalla,
                       "catalogo": catalogo, "avisos_catalogo": avisos_cat,
                       "mismo_fichero": compartidos, "contenido": contenido}, f,
                      ensure_ascii=False, indent=1)
        print(f"\n escrito {os.path.relpath(SALIDA, BASE)}")

    fallos = len(pantalla) + len(catalogo)
    print("\n RESULTADO:", "VERDE" if not fallos else f"ROJO · {fallos} duplicado(s) a corregir")
    return 0 if not fallos else 1


def n_puntos(n, na, nb, menor_es_a):
    return n / (na if menor_es_a else nb)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
