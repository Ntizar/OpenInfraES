# -*- coding: utf-8 -*-
"""Agregados ligeros para la barra de indicadores del visor.

**Por qué existe.** La barra de arriba enseña cuatro cifras que cambian cada pocos segundos.
Para pintar «embalses al 55 %» no se puede bajar `agua-embalsada.geojson` (1,1 MB) ni
`carburantes.geojson` (4,7 MB) en cada carga: el visitante paga 6 MB para leer un porcentaje.
Este script hace la suma una vez y publica un fichero de ~2 KB.

Las cifras NO se escriben a mano: se cuentan de los GeoJSON que ya están en `datos/`. Si una
capa no está, su bloque no aparece y el indicador no se pinta (no se inventa un cero).

    python scripts/agregados.py
"""
import datetime
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")


def lee(nombre):
    ruta = os.path.join(DATOS, nombre)
    if not os.path.exists(ruta):
        return None
    try:
        return json.load(open(ruta, encoding="utf-8"))
    except Exception:
        return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def bloque_agua():
    d = lee("oficial/agua-embalsada.geojson")
    if not d:
        return None
    cap = act = 0.0
    n = 0
    fechas = set()
    for f in d.get("features", []):
        p = f.get("properties") or {}
        c, a = num(p.get("capacidad_hm3")), num(p.get("agua_actual_hm3"))
        if not c or a is None:
            continue
        cap += c
        act += a
        n += 1
        if p.get("fecha_dato"):
            fechas.add(str(p["fecha_dato"])[:10])
    if not cap:
        return None
    return {"capacidad_hm3": round(cap), "embalsada_hm3": round(act),
            "pct": round(100.0 * act / cap, 1), "n": n,
            "fecha": max(fechas) if fechas else None,
            "fuente": "MITECO · Boletín Hidrológico"}


def bloque_sismos():
    d = lee("sismos.geojson")
    if not d:
        return None
    mags = [num((f.get("properties") or {}).get("magnitud")) for f in d.get("features", [])]
    mags = [m for m in mags if m is not None]
    if not mags:
        return None
    return {"n": len(mags), "max": max(mags), "dias": 7,
            "fuente": "EMSC-CSEM (seismicportal.eu)"}


def bloque_trafico():
    d = lee("dgt_incidencias.geojson")
    if not d:
        return None
    act = sum(1 for f in d.get("features", [])
              if str((f.get("properties") or {}).get("estado") or "") == "active")
    return {"incidencias": len(d.get("features", [])), "activas": act,
            "fuente": "DGT · NAP de Tráfico (DATEX II)"}


def bloque_trenes():
    d = lee("gtfsrt_vehiculos.geojson")
    if not d:
        return None
    fs = d.get("features", [])
    return {"vehiculos": len(fs),
            "operadores": sorted({(f.get("properties") or {}).get("operador")
                                  for f in fs if (f.get("properties") or {}).get("operador")}),
            "fuente": "GTFS-Realtime · Renfe"}


def bloque_carburantes():
    d = lee("carburantes.geojson")
    if not d:
        return None
    vals, g95, fechas = [], [], set()
    for f in d.get("features", []):
        p = f.get("properties") or {}
        v = num(p.get("gasoleo_a"))
        if v and v > 0:
            vals.append(v)
        g = num(p.get("gasolina95"))
        if g and g > 0:
            g95.append(g)
        if p.get("fecha_dato"):
            fechas.add(str(p["fecha_dato"])[:10])
    if not vals:
        return None
    vals.sort()
    g95.sort()
    # Las dos medias del surtidor: gasóleo A y gasolina 95, con la misma vara. Antes solo se
    # calculaba el gasóleo y el mapa nunca enseñaba gasolina.
    salida = {"gasoleo_medio": round(sum(vals) / len(vals), 3),
              "gasoleo_mediana": round(vals[len(vals) // 2], 3),
              "gasoleo_min": round(vals[0], 3), "gasoleo_max": round(vals[-1], 3),
              "n": len(vals), "fecha": sorted(fechas)[-1] if fechas else None,
              "fuente": "MITECO · precios de carburantes"}
    if g95:
        salida.update({"gasolina_medio": round(sum(g95) / len(g95), 3),
                       "gasolina_mediana": round(g95[len(g95) // 2], 3),
                       "gasolina_min": round(g95[0], 3), "gasolina_max": round(g95[-1], 3),
                       "n_gasolina": len(g95)})
    return salida


def main():
    salida = {
        "generado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nota": "Agregados calculados de los GeoJSON de datos/. No se edita a mano.",
        "agua": bloque_agua(),
        "sismos": bloque_sismos(),
        "trafico": bloque_trafico(),
        "trenes": bloque_trenes(),
        "carburantes": bloque_carburantes(),
    }
    clim = lee("clima_recibo.json")
    if clim:
        salida["clima"] = {k: clim.get(k) for k in
                           ("temperatura_media", "mas_caliente", "mas_frio", "actualizado",
                            "provincias", "fuente", "nota")}
    salida = {k: v for k, v in salida.items() if v is not None}
    ruta = os.path.join(DATOS, "agregados.json")
    json.dump(salida, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    agua = salida.get("agua") or {}
    print("agregados: %d bloques · embalses %s %% · sismos %s · carburante %s €/l"
          % (len(salida) - 2, agua.get("pct", "-"), (salida.get("sismos") or {}).get("n", "-"),
             (salida.get("carburantes") or {}).get("gasoleo_mediana", "-")))


if __name__ == "__main__":
    main()
