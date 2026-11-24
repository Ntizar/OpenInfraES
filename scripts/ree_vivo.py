# -*- coding: utf-8 -*-
"""REE en vivo — demanda, generación, emisiones, intercambios y bombeo de ESIOS.

**ESIOS ya NO está abierto.** Hasta el 2026-11-16 los 19 indicadores de este script respondían
`200` sin clave; el 2026-11-23 dan **`403` sin `x-api-key` y `200` con ella** (medido: 36 bytes
de cuerpo sin clave, 37.979 con clave en el 2037). Sin token no hay dato en vivo: la capa se
queda con lo último bueno y su hora, que es honesto pero no es lo que se quiere.

Granularidad real: 5 minutos. Demanda nacional trae 224 valores al día.

    python scripts/ree_vivo.py                 # hoy
    python scripts/ree_vivo.py --fecha 2026-11-15

Salida: datos/ree_vivo.json (estado actual + series de 24 h) y datos/ree_vivo_recibo.json
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http_oficial import (SinDatos, SinPermiso, NoExiste, PeticionMala,
                          ServidorCaido, BloqueoWAF, pide)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
BASE = "https://api.esios.ree.es/indicators"


def token():
    """Clave de ESIOS: primero el entorno (CI), luego el .env de casa."""
    t = os.environ.get("ESIOS_TOKEN")
    if t and t.strip():
        return t.strip()
    ruta = os.path.join(RAIZ, ".env")
    if not os.path.exists(ruta):
        return None
    for linea in open(ruta, encoding="utf-8"):
        if linea.startswith("ESIOS_TOKEN="):
            v = linea.split("=", 1)[1].strip()
            if v:            # una linea vacia arriba no debe tapar la buena
                return v
    return None


CABECERAS = {}
_TK = token()
if _TK:
    CABECERAS["x-api-key"] = _TK

# unidad real de cada magnitud (ESIOS no la declara en `unit`)
UNIDADES = {10355: "tCO₂/MW", 1294: "MW", 10004: "MW"}

# id -> (clave, etiqueta, grupo)
# ESIOS abre las trece tecnologías «Generación T.Real» al mismo minuto (204 puntos al día): con
# todas ellas la suma cuadra con la demanda y con el saldo de intercambios, y no hace falta
# mezclar ENTSO-E (15 min y 30-40 de retraso) para tener el mix completo.
ABIERTOS = {
    2037: ("demanda", "Demanda real nacional", "demanda"),
    10004: ("demanda_gen", "Demanda real (suma de generación)", "demanda"),
    2038: ("eolica", "Eólica", "generacion"),
    2039: ("nuclear", "Nuclear", "generacion"),
    2040: ("carbon", "Carbón", "generacion"),
    2041: ("ciclo", "Ciclo combinado", "generacion"),
    2042: ("hidro", "Hidráulica", "generacion"),
    2044: ("solar_fv", "Solar fotovoltaica", "generacion"),
    2045: ("solar_ter", "Solar térmica", "generacion"),
    2046: ("termica_renovable", "Térmica renovable", "generacion"),
    2047: ("diesel", "Motor diésel", "generacion"),
    2048: ("turbina_gas", "Turbina de gas", "generacion"),
    2049: ("turbina_vapor", "Turbina de vapor", "generacion"),
    2050: ("auxiliar", "Generación auxiliar", "generacion"),
    2051: ("cogen_residuos", "Cogeneración y residuos", "generacion"),
    2043: ("intercambios", "Intercambios internacionales", "intercambios"),
    10355: ("co2", "CO₂ asociado a la generación", "emisiones"),
    2068: ("exp_andorra", "Exportación a Andorra", "intercambios"),
    2073: ("imp_andorra", "Importación de Andorra", "intercambios"),
    2069: ("exp_marruecos", "Exportación a Marruecos", "intercambios"),
    2074: ("imp_marruecos", "Importación de Marruecos", "intercambios"),
    2070: ("exp_portugal", "Exportación a Portugal", "intercambios"),
    2075: ("imp_portugal", "Importación de Portugal", "intercambios"),
    2071: ("exp_francia", "Exportación a Francia", "intercambios"),
    2076: ("imp_francia", "Importación de Francia", "intercambios"),
    2078: ("bombeo_cons", "Consumo de bombeo", "almacenamiento"),
    2079: ("bombeo_turb", "Turbinado de bombeo", "almacenamiento"),
}


def trae(ind):
    """Un 200 con `values: []` es SIN DATOS, no una averia. El cliente lo distingue."""
    return pide("%s/%s" % (BASE, ind), cabeceras=CABECERAS,
                vacio_si=("indicator", "values"))


def limpia(v):
    """(hora, valor) con la hora local de Madrid y sin nulos."""
    salida = []
    for p in v:
        if p.get("value") is None:
            continue
        salida.append([p["datetime"][11:16], round(float(p["value"]), 2)])
    return salida


def edad_min(fecha, hhmm):
    """Minutos transcurridos desde la marca de la serie (la fuente da fecha + HH:MM)."""
    try:
        d = datetime.datetime.fromisoformat("%sT%s" % (fecha, hhmm))
    except Exception:
        return None
    minutos = (datetime.datetime.now() - d).total_seconds() / 60.0
    if minutos > 12 * 60:          # la marca es de ayer (pasada la medianoche)
        minutos -= 24 * 60
    if minutos < -60 or minutos > 24 * 60:
        return None
    return int(max(minutos, 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha")
    a = ap.parse_args()
    fecha = a.fecha or datetime.date.today().isoformat()

    # Si el WAF bloquea, NO se pierde el dato bueno: se hereda el ultimo conocido
    ruta_json = os.path.join(DEST, "ree_vivo.json")
    previo = {}
    if os.path.exists(ruta_json):
        try:
            previo = json.load(open(ruta_json, encoding="utf-8"))
        except Exception:
            previo = {}

    series = {}
    estado = {}
    fallos = []
    heredados = []
    for ind, (clave, etiqueta, grupo) in ABIERTOS.items():
        try:
            d = trae(ind)["indicator"]
            vals = limpia(d.get("values", []))
            if not vals:
                fallos.append({"id": ind, "clave": clave, "motivo": "sin valores"})
                continue
            series[clave] = {"etiqueta": etiqueta, "grupo": grupo, "id": ind,
                             "unidad": UNIDADES.get(ind, "MW"),
                             "hora": vals[-1][0], "valor": vals[-1][1],
                             "edad_min": edad_min(fecha, vals[-1][0]),
                             "serie": vals[-72:]}   # últimas ~6 h a 5 min
            estado[clave] = vals[-1][1]
        except (SinPermiso, NoExiste, PeticionMala, ServidorCaido, SinDatos, BloqueoWAF) as e:
            fallos.append({"id": ind, "clave": clave, "tipo": e.tipo, "motivo": str(e)[:90]})
            # herencia: conservar la serie anterior marcandola como tal
            if clave in (previo.get("series") or {}):
                v = dict(previo["series"][clave])
                v["heredado"] = True
                v["heredado_de"] = previo.get("actualizado")
                series[clave] = v
                estado[clave] = v.get("valor")
                heredados.append(clave)
        except Exception as e:
            fallos.append({"id": ind, "clave": clave, "tipo": "otro", "motivo": str(e)[:90]})
        time.sleep(1.1)

    edades = [v.get("edad_min") for k, v in series.items()
              if k not in heredados and v.get("edad_min") is not None]

    # Los indicadores no cierran el mismo minuto entre sí: unos publican a las 20:20 y otros se
    # quedan en 20:15. Sumar 20:20 con 20:15 fabrica una foto que no existe. Se elige el último
    # minuto que comparten TODAS las series vivas y se publica ese, con su hora.
    comunes = None
    for k, v in series.items():
        if v.get("heredado") or not v.get("serie"):
            continue
        horas = {p[0] for p in v["serie"]}
        comunes = horas if comunes is None else (comunes & horas)
    hora_comun = max(comunes) if comunes else None
    if hora_comun:
        for k, v in series.items():
            mapa = {p[0]: p[1] for p in (v.get("serie") or [])}
            if hora_comun in mapa:
                v["hora"] = hora_comun
                v["valor"] = mapa[hora_comun]
                v["edad_min"] = edad_min(fecha, hora_comun)
                estado[k] = mapa[hora_comun]
        edades = [v.get("edad_min") for k, v in series.items()
                  if k not in heredados and v.get("edad_min") is not None]

    salida = {
        "fecha": fecha,
        "actualizado": datetime.datetime.now().isoformat(timespec="seconds"),
        "edad_min": min(edades) if edades else None,
        "hora_comun": hora_comun,
        "con_clave": bool(_TK),
        "fuente": "REE · ESIOS (token)" if _TK else "REE · ESIOS (sin clave: 403)",
        "resolucion": "5 minutos",
        "estado": estado,
        "series": series,
        "fallos": fallos,
        "heredados": heredados,
    }
    ruta = ruta_json
    json.dump(salida, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    recibo = {
        "fuente": "REE · ESIOS",
        "url": BASE,
        "fecha": fecha,
        "descargado": salida["actualizado"],
        "indicadores_ok": len(series),
        "indicadores_probados": len(ABIERTOS),
        "series": {k: {"id": v["id"], "puntos": len(v["serie"]),
                       "ultimo": v["valor"], "hora": v["hora"]} for k, v in series.items()},
        "fallos": fallos,
    }
    json.dump(recibo, open(os.path.join(DEST, "ree_vivo_recibo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    vivos = len([k for k in series if k not in heredados])
    print("  %d de %d con descarga fresca · %d heredados · %s"
          % (vivos, len(ABIERTOS), len(heredados), fecha))
    for k in ("demanda", "eolica", "solar_fv", "hidro", "ciclo", "co2"):
        if k in series:
            v = series[k]
            print("   %-12s %10.1f %-6s  %s" % (v["etiqueta"][:12], v["valor"], v["unidad"], v["hora"]))
    if fallos:
        print("   fallos: %s" % ", ".join(f["clave"] for f in fallos))


if __name__ == "__main__":
    main()
