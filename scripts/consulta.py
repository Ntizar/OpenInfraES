#!/usr/bin/env python3
"""Consulta municipal de OpenInfraES: una tabla ancha y SQL, sin dependencias.

Uso:
    python3 scripts/consulta.py "select municipio, renta_persona from municipios where nuclear=1"
    python3 scripts/consulta.py --mart          # regenera datos/municipios_mart.csv
    python3 scripts/consulta.py --tablas        # esquema de la tabla

La tabla `municipios` junta en una fila por municipio (cod_ine, 5 dígitos) lo que hasta
ahora vivía en tres ficheros y se cruzaba a mano:
  - datos/ine/municipios.json      renta (INE ADRH: 6 indicadores)
  - datos/municipios.geojson       población, área, provincia, tramo
  - datos/plantas.geojson          centrales agregadas por tecnología (MW) + nº de plantas

SQL es SQLite en memoria (stdlib). 8.128 filas entran en 0,3 s: no hace falta DuckDB ni
pandas para preguntas municipales. DuckDB tiene sentido cuando entra el store de capas
completas (geometrías), no para agregados.
"""

import csv
import json
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MART = os.path.join(RAIZ, "datos", "municipios_mart.csv")

COLS = ["cod_ine", "municipio", "provincia", "poblacion", "area_km2", "tramo",
        "renta_persona", "renta_hogar", "renta_uc_media", "renta_uc_mediana",
        "renta_bruta_persona", "renta_bruta_hogar",
        "plantas_n", "mw_total"] + ["mw_" + t for t in
        ("nuclear", "solar_pv", "wind", "hydro", "pumped_hydro", "ccgt", "cogeneration", "otras")]


def construir_mart():
    renta = json.load(open(os.path.join(RAIZ, "datos/ine/municipios.json")))
    geo = json.load(open(os.path.join(RAIZ, "datos/municipios.geojson")))
    plantas = json.load(open(os.path.join(RAIZ, "datos/plantas.geojson")))

    filas = {}
    for f in geo["features"]:
        p = f["properties"]
        r = renta["municipios"].get(p["cod_ine"], {})
        filas[p["cod_ine"]] = {
            "cod_ine": p["cod_ine"], "municipio": p.get("nombre"),
            "provincia": p.get("provincia_nombre") or p.get("provincia"),
            "poblacion": p.get("poblacion"), "area_km2": p.get("area_km2"),
            "tramo": p.get("tramo_poblacion"),
            **{k: r.get(k) for k in ("renta_persona", "renta_hogar", "renta_uc_media",
                                     "renta_uc_mediana", "renta_bruta_persona", "renta_bruta_hogar")},
            "plantas_n": 0, "mw_total": 0.0,
        }
        for t in COLS[COLS.index("mw_nuclear"):]:
            filas[p["cod_ine"]][t] = 0.0

    conocidas = set(COLS[COLS.index("mw_nuclear"):-1])
    sueltas = 0
    for f in plantas["features"]:
        p = f["properties"]
        cod = p.get("cod_ine_municipio")
        if cod not in filas:
            sueltas += 1
            continue
        mw = p.get("installed_capacity_mw") or 0.0
        tech = p.get("technology_normalized") or ""
        fila = filas[cod]
        fila["plantas_n"] += 1
        fila["mw_total"] += mw
        col = "mw_" + tech
        fila[col if col in conocidas else "mw_otras"] += mw

    with open(MART, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for cod in sorted(filas):
            w.writerow({k: (round(v, 2) if isinstance(v, float) else v)
                        for k, v in filas[cod].items()})
    print(f"mart: {len(filas)} municipios, {len(plantas['features'])} plantas "
          f"({sueltas} sin municipio emparejado) -> {MART}")
    return len(filas)


def conectar():
    if not os.path.exists(MART):
        construir_mart()
    con = sqlite3.connect(":memory:")
    cur = con.cursor()
    tipos = []
    for c in COLS:
        tipos.append(c if c in ("cod_ine", "municipio", "provincia", "tramo") else "REAL")
    cur.execute(f"create table municipios ({', '.join(f'{c} {t}' for c, t in zip(COLS, tipos))})")
    with open(MART, encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        cur.executemany(
            f"insert into municipios values ({','.join('?' * len(COLS))})",
            [[row[c] if c in ("cod_ine", "municipio", "provincia", "tramo") or row[c] == ""
              else float(row[c]) for c in COLS] for row in r])
    con.commit()
    return con


def imprimir(cur):
    cols = [d[0] for d in cur.description]
    datos = cur.fetchall()
    anchos = [len(c) for c in cols]
    txt = []
    for fila in datos:
        celdas = []
        for i, v in enumerate(fila):
            if isinstance(v, float):
                v = f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
            celdas.append("" if v is None else str(v))
            anchos[i] = max(anchos[i], len(celdas[-1]))
        txt.append(celdas)
    print(" | ".join(c.ljust(anchos[i]) for i, c in enumerate(cols)))
    print("-+-".join("-" * a for a in anchos))
    for celdas in txt:
        print(" | ".join(c.ljust(anchos[i]) for i, c in enumerate(celdas)))
    print(f"\n{len(datos)} filas")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if args[0] == "--mart":
        construir_mart()
        return
    if args[0] == "--tablas":
        print("tabla municipios:", ", ".join(COLS))
        return
    con = conectar()
    imprimir(con.execute(" ".join(args)))


if __name__ == "__main__":
    main()
