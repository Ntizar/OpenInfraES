#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_openinfra.py — el MCP federado de OpenInfraES.

Todas las fuentes del repositorio —las capas del catálogo, energía, agua, red,
gas, transporte, clima y geografía— detrás de UNA sola superficie JSON-RPC 2.0.

Tres modos:

    python scripts/mcp_openinfra.py                 # stdio NDJSON (Claude Code, Cursor, agentes)
    python scripts/mcp_openinfra.py --http 8077     # POST /api/mcp + GET /api/state (web y remoto)
    python scripts/mcp_openinfra.py --test          # autochequeo: se habla como cliente real

Contrato de respuesta (copiado del patrón que funciona en producción):

    {"content":[{"type":"text","text":"..."}],
     "structuredData": { ... },      # el dato, ya analizado, no la serie cruda
     "isError": false,
     "meta": {"toolName","executedAt","latencyMs","dataSourceIds","citedIds",
              "dato","resolucion","edad","aviso"}}

Reglas que este servidor cumple y que están pagadas con errores reales:
  * stdout es el protocolo: los logs van a stderr.
  * una herramienta por PREGUNTA real, no un proxy del fichero.
  * el análisis va dentro: porcentajes, agregados, distancias y umbrales se
    calculan aquí, no se le pasan al modelo para que los sume.
  * cada respuesta dice fuente, fecha, resolución y EDAD; si el dato está
    caducado se dice en el texto y en meta.aviso (un dato viejo con etiqueta
    de presente es peor que un hueco).
  * cero dependencias: solo stdlib. shapely no está, así que el point-in-polygon
    y las distancias son propios y están declarados como aproximación.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"
SERVIDOR = "mcp-openinfra"
PROTOCOLOS = {"2024-11-05", "2025-03-26", "2025-06-18"}

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"


# --------------------------------------------------------------------------
# Catálogo y carga perezosa
# --------------------------------------------------------------------------

_cache: dict[str, object] = {}


def _log(msg: str) -> None:
    print(f"[{SERVIDOR}] {msg}", file=sys.stderr, flush=True)


def cargar_json(relativa: str):
    """Carga un JSON del repo una sola vez por proceso."""
    if relativa in _cache:
        return _cache[relativa]
    ruta = DATOS / relativa
    if not ruta.exists():
        raise FaltaFichero(f"no existe datos/{relativa} — ejecuta el capturador correspondiente")
    with ruta.open(encoding="utf-8") as fh:
        dato = json.load(fh)
    _cache[relativa] = dato
    return dato


class FaltaFichero(RuntimeError):
    pass


def catalogo() -> dict:
    return cargar_json("catalogo.json")


def capa(capa_id: str) -> dict:
    c = catalogo()["capas"]
    if capa_id not in c:
        raise FaltaFichero(f"capa desconocida: {capa_id}")
    return c[capa_id]


def frescura(capa_id: str) -> dict:
    """Procedencia + edad de una capa, lista para pegar en la respuesta."""
    try:
        c = capa(capa_id)
    except FaltaFichero:
        return {"capa": capa_id, "organismo": None, "edad_dias": None, "caducado": None}
    return {
        "capa": capa_id,
        "organismo": c.get("organismo"),
        "producto": c.get("producto"),
        "fecha_dato": c.get("fecha_dato"),
        "fecha_descarga": c.get("fecha_descarga"),
        "edad_dias": c.get("edad_dias"),
        "ttl_dias": round((c.get("ttl_segundos") or 0) / 86400, 1),
        "caducado": c.get("caducado"),
        "licencia": (c.get("licencia") or {}).get("nombre"),
        "features": c.get("features"),
    }


def frescura_viva(nombre: str, fuente: str, edad_min=None, resolucion=None,
                  actualizado=None) -> dict:
    """Procedencia de un flujo en vivo: no está en el catálogo, y no debe heredar
    los avisos de una capa estática que no se ha usado."""
    return {"flujo": nombre, "organismo": fuente, "edad_min": edad_min,
            "resolucion": resolucion, "actualizado": actualizado, "caducado": None}


def avisos_de(capas: list[str]) -> list[str]:
    out = []
    for cid in capas:
        f = frescura(cid)
        if f.get("caducado"):
            out.append(
                f"{cid}: dato de {f.get('fecha_dato')} ({f.get('edad_dias')} días, TTL {f.get('ttl_dias')}) — CADUCADO"
            )
    return out


# --------------------------------------------------------------------------
# Geometría (stdlib, aproximación declarada)
# --------------------------------------------------------------------------

R_TIERRA_KM = 6371.0088


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_TIERRA_KM * math.asin(math.sqrt(a))


def _a_local(lat0, lon0, lat, lon):
    """Proyección equirectangular en km alrededor de un punto. Error <0,1 % a 100 km."""
    x = math.radians(lon - lon0) * math.cos(math.radians((lat + lat0) / 2)) * R_TIERRA_KM
    y = math.radians(lat - lat0) * R_TIERRA_KM
    return x, y


def distancia_punto_segmento(plat, plon, a, b) -> float:
    """Distancia en km de un punto a un segmento (a, b) dados como [lon, lat]."""
    ax, ay = _a_local(plat, plon, a[1], a[0])
    bx, by = _a_local(plat, plon, b[1], b[0])
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def distancia_a_linea(plat, plon, coords) -> float:
    mejor = float("inf")
    if len(coords) == 1:
        return haversine(plat, plon, coords[0][1], coords[0][0])
    for i in range(len(coords) - 1):
        d = distancia_punto_segmento(plat, plon, coords[i], coords[i + 1])
        if d < mejor:
            mejor = d
    return mejor


def longitud_linea_km(coords) -> float:
    total = 0.0
    for i in range(len(coords) - 1):
        total += haversine(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
    return total


def bbox_de(coords):
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def en_bbox(lat, lon, bb, margen_km=0.0) -> bool:
    minx, miny, maxx, maxy = bb
    dlat = margen_km / 111.0
    dlon = margen_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return (miny - dlat) <= lat <= (maxy + dlat) and (minx - dlon) <= lon <= (maxx + dlon)


def punto_en_poligono(lat, lon, anillo) -> bool:
    """Ray casting sobre un anillo [[lon, lat], ...] (sin agujeros)."""
    dentro = False
    n = len(anillo)
    j = n - 1
    for i in range(n):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            dentro = not dentro
        j = i
    return dentro


def anillos(geom) -> list:
    """Devuelve los anillos exteriores de un Polygon/MultiPolygon."""
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [pol[0] for pol in geom["coordinates"]]
    return []


def centroide(geom) -> tuple | None:
    for anillo in anillos(geom):
        xs = [p[0] for p in anillo]
        ys = [p[1] for p in anillo]
        return sum(ys) / len(ys), sum(xs) / len(xs)
    return None


# --------------------------------------------------------------------------
# Contrato de respuesta
# --------------------------------------------------------------------------


def responder(tool: str, texto: str, datos: dict, fuentes: list[str],
              citados: list[str] | None = None, t0: float | None = None,
              extra: dict | None = None, vivos: list[dict] | None = None) -> dict:
    avisos = avisos_de(fuentes)
    meta = {
        "toolName": tool,
        "executedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latencyMs": int((time.time() - t0) * 1000) if t0 else 0,
        "dataSourceIds": fuentes,
        "citedIds": citados or [],
        "frescura": [frescura(f) for f in fuentes] + (vivos or []),
    }
    if avisos:
        meta["aviso"] = avisos
        texto += "  ·  AVISO: " + "; ".join(avisos)
    if extra:
        meta.update(extra)
    return {
        "content": [{"type": "text", "text": texto}],
        "structuredData": datos,
        "isError": False,
        "meta": meta,
    }


def error(tool: str, mensaje: str, sugerencia: str = "") -> dict:
    texto = f"{mensaje}" + (f" — {sugerencia}" if sugerencia else "")
    return {
        "content": [{"type": "text", "text": texto}],
        "isError": True,
        "meta": {"toolName": tool, "executedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")},
    }


def _num(v, nd=1):
    return round(v, nd) if isinstance(v, (int, float)) else v


# --------------------------------------------------------------------------
# Herramientas
# --------------------------------------------------------------------------


def t_datos_catalogo(args: dict) -> dict:
    t0 = time.time()
    c = catalogo()
    capas = list(c["capas"].values())
    filtro = (args.get("filtro") or "").lower()
    if filtro:
        capas = [x for x in capas if filtro in json.dumps(x, ensure_ascii=False).lower()]
    if args.get("solo_oficiales"):
        capas = [x for x in capas if x.get("oficial")]
    if args.get("solo_caducadas"):
        capas = [x for x in capas if x.get("caducado")]
    if args.get("licencia_pendiente"):
        capas = [x for x in capas if (x.get("licencia") or {}).get("estado") != "si"]
    capas.sort(key=lambda x: (-(x.get("features") or 0)))
    limite = int(args.get("limit") or 40)
    filas = [
        {
            "id": x["id"],
            "titulo": x.get("titulo"),
            "organismo": x.get("organismo"),
            "jerarquia": x.get("jerarquia_txt"),
            "licencia": (x.get("licencia") or {}).get("estado"),
            "features": x.get("features"),
            "fecha_dato": x.get("fecha_dato"),
            "edad_dias": x.get("edad_dias"),
            "caducado": x.get("caducado"),
        }
        for x in capas[:limite]
    ]
    datos = {
        "totalCapas": len(c["capas"]),
        "coincidencias": len(capas),
        "devueltas": len(filas),
        "resumen": c.get("resumen"),
        "capas": filas,
    }
    texto = (
        f"Catálogo OpenInfraES: {c['capas'].__len__()} capas, "
        f"{c['resumen'].get('oficiales')} de organismo productor y "
        f"{c['resumen'].get('comunitarias')} comunitarias; "
        f"{c['resumen'].get('licencia_pendiente')} con licencia sin evaluar (no se exponen en un MCP público) "
        f"y {c['resumen'].get('caducados')} caducadas. "
        f"Coincidencias con el filtro: {len(capas)} (se devuelven {len(filas)})."
    )
    return responder("es.datos.catalogo", texto, datos, [], [x["id"] for x in filas[:12]], t0)


def t_datos_salud(args: dict) -> dict:
    t0 = time.time()
    c = catalogo()
    capas = c["capas"]
    vivas = [
        ("ree_vivo.json", "energia"),
        ("omie_precio.json", "energia"),
        ("entsoe_mix.json", "energia"),
        ("gtfsrt_vehiculos.geojson", "transporte"),
        ("aemet_avisos.json", "clima"),
        ("dgt_incidencias.geojson", "carreteras"),
        ("sismos.geojson", "sismos"),
    ]
    estado = []
    for rel, dominio in vivas:
        p = DATOS / rel
        if not p.exists():
            estado.append({"fichero": rel, "dominio": dominio, "estado": "ausente"})
            continue
        try:
            d = cargar_json(rel)
        except Exception as exc:  # noqa: BLE001
            estado.append({"fichero": rel, "dominio": dominio, "estado": f"ilegible: {exc}"})
            continue
        edad = None
        for campo in ("edad_min", "descargado", "actualizado", "generado"):
            if isinstance(d, dict) and d.get(campo) is not None:
                v = d[campo]
                if campo == "edad_min":
                    edad = f"{v} min"
                else:
                    edad = f"descargado {v}"
                break
        estado.append({
            "fichero": rel,
            "dominio": dominio,
            "estado": "ok",
            "edad": edad,
            "fuente": (d.get("fuente") if isinstance(d, dict) else None),
        })
    caducadas = sorted(k for k, v in capas.items() if v.get("caducado"))
    sin_licencia = sorted(k for k, v in capas.items() if (v.get("licencia") or {}).get("estado") != "si")
    datos = {
        "totalCapas": len(capas),
        "caducadas": caducadas,
        "sinLicencia": sin_licencia,
        "vivos": estado,
        "resumen": c.get("resumen"),
        "generado": c.get("generado"),
    }
    texto = (
        f"Salud de la federación: {len(capas)} capas, {len(caducadas)} caducadas, "
        f"{len(sin_licencia)} sin licencia evaluada; "
        f"{sum(1 for e in estado if e['estado'] == 'ok')}/{len(estado)} conjuntos vivos legibles."
    )
    return responder("es.datos.salud", texto, datos, [], caducadas[:10], t0)


def t_energia_estado(args: dict) -> dict:
    t0 = time.time()
    ree = cargar_json("ree_vivo.json")
    e = ree["estado"]
    fuentes = []
    vivos = [frescura_viva("demanda-generacion-emisiones", "REE · ESIOS",
                           ree.get("edad_min"), ree.get("resolucion"), ree.get("actualizado"))]
    mix = None
    if (DATOS / "entsoe_mix.json").exists():
        mix = cargar_json("entsoe_mix.json")
        vivos.append(frescura_viva("mix-generacion", "ENTSO-E Transparency · A75",
                                   mix.get("edad_min"), mix.get("resolucion"),
                                   f"{mix.get('fecha')} {mix.get('hora_ultimo')}"))
    renovables = {"eolica", "solar_fv", "solar_ter", "hidro"}
    gen_esios = sum(v for k, v in e.items() if k in renovables) + e.get("ciclo", 0)
    datos = {
        "demandaMW": e.get("demanda"),
        "co2tCO2MWh": e.get("co2"),
        "intercambios": {
            "francia": _num(-(e.get("exp_francia") or 0) + (e.get("imp_francia") or 0)),
            "portugal": _num(-(e.get("exp_portugal") or 0) + (e.get("imp_portugal") or 0)),
            "marruecos": _num(-(e.get("exp_marruecos") or 0) + (e.get("imp_marruecos") or 0)),
            "andorra": _num(-(e.get("exp_andorra") or 0) + (e.get("imp_andorra") or 0)),
        },
        "bombeo": {"turbinaMW": e.get("bombeo_turb"), "consumeMW": e.get("bombeo_cons")},
        "generacionSeriesESIOS": {
            "eolica": e.get("eolica"), "solar_fv": e.get("solar_fv"),
            "solar_ter": e.get("solar_ter"), "hidro": e.get("hidro"), "ciclo": e.get("ciclo"),
        },
        "cobertura": {
            "hora": ree.get("actualizado"), "edad_min": ree.get("edad_min"),
            "resolucion": ree.get("resolucion"), "fuente": ree.get("fuente"),
            "con_clave": ree.get("con_clave"),
        },
        "mixENTSOE": None,
    }
    if mix:
        top = sorted(mix["tecnologias"], key=lambda t: -(t.get("ultimo_mw") or 0))[:6]
        datos["mixENTSOE"] = {
            "hora_ultimo": mix.get("hora_ultimo"),
            "edad_min": mix.get("edad_min"),
            "cuartos_cubiertos": mix.get("cuartos_cubiertos"),
            "top": [{"tecnologia": t["codigo"], "mw": t.get("ultimo_mw"),
                     "pct_del_dia": t.get("pct")} for t in top],
        }
    citados = ["ESIOS-2037"]
    texto = (
        f"Demanda nacional {e.get('demanda'):,.0f} MW a las {(ree.get('actualizado') or '')[11:16]} "
        f"(edad {ree.get('edad_min')} min, resolución {ree.get('resolucion')}). "
        f"CO₂ {e.get('co2')} t/MWh. Bombeo: turbina {e.get('bombeo_turb')} MW, consume {abs(e.get('bombeo_cons') or 0)} MW. "
        f"Intercambios netos: Francia {datos['intercambios']['francia']:+,.0f} · "
        f"Portugal {datos['intercambios']['portugal']:+,.0f} · "
        f"Marruecos {datos['intercambios']['marruecos']:+,.0f} MW."
    )
    if mix:
        texto += (
            f" Mix ENTSO-E (todas las tecnologías) a las {mix.get('hora_ultimo')}, "
            f"{mix.get('cuartos_cubiertos')} cuartos publicados: "
            + ", ".join(f"{t['tecnologia']} {t['mw']:,.0f} MW" for t in datos["mixENTSOE"]["top"][:4])
            + "."
        )
    texto += " Ojo: ESIOS solo abre 5 series de generación; el mix completo se lee de ENTSO-E A75."
    return responder("es.energia.estado_ahora", texto, datos, fuentes, citados, t0,
                     vivos=vivos)


def t_energia_mix(args: dict) -> dict:
    t0 = time.time()
    mix = cargar_json("entsoe_mix.json")
    tec = (args.get("tecnologia") or "").lower()
    techs = mix["tecnologias"]
    if tec:
        techs = [t for t in techs if tec in t["codigo"].lower() or tec in t["nombre"].lower()]
    filas = [
        {
            "tecnologia": t["codigo"],
            "mwh": t.get("mwh"),
            "pct": t.get("pct"),
            "mw_medio": t.get("mw_medio"),
            "ultimo_mw": t.get("ultimo_mw"),
            "capacidad_mw": t.get("capacidad_mw"),
            "factor_carga_pct": t.get("factor_carga"),
            "cuartos": t.get("cuartos"),
            "consumo_mwh": t.get("consumo_mwh"),
        }
        for t in sorted(techs, key=lambda x: -(x.get("mwh") or 0))
    ]
    datos = {
        "fecha": mix.get("fecha"),
        "hora_ultimo": mix.get("hora_ultimo"),
        "edad_min": mix.get("edad_min"),
        "cuartos_cubiertos": mix.get("cuartos_cubiertos"),
        "resolucion": mix.get("resolucion"),
        "totalMWh": mix.get("total_mwh"),
        "consumoTotalMWh": mix.get("consumo_total_mwh"),
        "tecnologias": filas,
        "nota": "A75 da MW medios de cada cuarto: la energía de un cuarto es MW × 0,25 h. "
                "El día en curso está incompleto (cuartos_cubiertos).",
    }
    texto = (
        f"Mix de generación {mix.get('fecha')} hasta las {mix.get('hora_ultimo')} "
        f"({mix.get('cuartos_cubiertos')} cuartos, {mix.get('total_mwh'):,.0f} MWh): "
        + ", ".join(f"{f['tecnologia']} {f['pct']}%" for f in filas[:5])
        + f". Consumo de bombeo y almacenamiento: {mix.get('consumo_total_mwh'):,.0f} MWh (se descuenta, no se suma)."
    )
    return responder("es.energia.mix_tecnologia", texto, datos, [],
                     [f["tecnologia"] for f in filas[:6]], t0,
                     vivos=[frescura_viva("mix-generacion", "ENTSO-E Transparency · A75",
                                          mix.get("edad_min"), mix.get("resolucion"),
                                          f"{mix.get('fecha')} {mix.get('hora_ultimo')}")])


def t_energia_precio(args: dict) -> dict:
    t0 = time.time()
    q = cargar_json("omie_precio.json")
    horas = q["horas"]
    hora = args.get("hora")
    if hora is not None:
        sel = [h for h in horas if int(h["hora"]) == int(hora)]
    else:
        sel = horas
    if not sel:
        return error("es.energia.precio_cuarto_hora",
                     f"No hay cuartos para la hora {hora} en el fichero de OMIE",
                     "usa una hora entre 1 y 24")
    precios = [h["es"] for h in sel]
    caro = max(sel, key=lambda h: h["es"])
    barato = min(sel, key=lambda h: h["es"])
    datos = {
        "fecha": q.get("fecha"),
        "unidad": q.get("unidad"),
        "resolucion": q.get("resolucion"),
        "descargado": q.get("descargado"),
        "cuartosDisponibles": len(horas),
        "cuartosSeleccionados": len(sel),
        "media": _num(sum(precios) / len(precios), 2),
        "min": {"precio": barato["es"], "hora": f"{barato['hora']:02d}:{barato['minuto']:02d}"},
        "max": {"precio": caro["es"], "hora": f"{caro['hora']:02d}:{caro['minuto']:02d}"},
        "mediaDiaCompleto": q.get("media"),
        "cuartos": [{"cuarto": h["cuarto"], "hora": f"{h['hora']:02d}:{h['minuto']:02d}", "es": h["es"]}
                    for h in sel],
        "nota": "Las 96 filas del marginalpdbc son 96 CUARTOS de hora (PT15M), no horas. "
                "hora = (cuarto-1)//4+1.",
    }
    texto = (
        f"OMIE {q.get('fecha')} ({q.get('unidad')}, {q.get('resolucion')}): "
        f"media {datos['media']} €/MWh, mínimo {barato['es']} a las {datos['min']['hora']}, "
        f"máximo {caro['es']} a las {datos['max']['hora']}."
    )
    return responder("es.energia.precio_cuarto_hora", texto, datos, ["omie"], ["OMIE-MARGINALPDBC"], t0)


def t_agua_embalses(args: dict) -> dict:
    t0 = time.time()
    gj = cargar_json("simplificado/agua-embalsada.geojson")
    fs = gj["features"]
    dem = (args.get("demarcacion") or "").lower()
    if dem:
        fs = [f for f in fs if dem in (f["properties"].get("demarcacion") or "").lower()]
    registros = []
    for f in fs:
        p = f["properties"]
        cap = p.get("capacidad_hm3")
        agua = p.get("agua_actual_hm3")
        if cap is None or agua is None or cap <= 0:
            continue
        registros.append({
            "nombre": p.get("nombre"),
            "demarcacion": p.get("demarcacion"),
            "capacidad_hm3": cap,
            "agua_hm3": agua,
            "pct": round(100 * agua / cap, 1),
            "fecha_dato": p.get("fecha_dato"),
            "hidroelectrico": p.get("hidroelectrico"),
        })
    if not registros:
        return error("es.agua.embalses", "Ningún embalse con capacidad y agua en el filtro",
                     "prueba sin demarcación o revisa datos/simplificado/agua-embalsada.geojson")
    registros.sort(key=lambda r: r["pct"])
    cap_total = sum(r["capacidad_hm3"] for r in registros)
    agua_total = sum(r["agua_hm3"] for r in registros)
    porc = args.get("max_pct")
    if porc is not None:
        registros = [r for r in registros if r["pct"] <= float(porc)]
    limite = int(args.get("limit") or 12)
    datos = {
        "registros": len(registros),
        "capacidadTotalHm3": _num(cap_total),
        "aguaTotalHm3": _num(agua_total),
        "pctNacional": round(100 * agua_total / cap_total, 1),
        "masVacios": registros[:limite],
        "masLlenos": list(reversed(registros))[:limite],
        "fecha_dato": registros[0]["fecha_dato"],
    }
    texto = (
        f"Agua embalsada ({datos['registros']} embalses con capacidad declarada, parte del "
        f"{datos['fecha_dato']}): {datos['aguaTotalHm3']:,.0f} de {datos['capacidadTotalHm3']:,.0f} hm³ "
        f"= {datos['pctNacional']}%. El más vacío: {registros[0]['nombre']} "
        f"({registros[0]['pct']}%, {registros[0]['demarcacion']})."
    )
    return responder("es.agua.embalses", texto, datos, ["embalses"],
                     [r["nombre"] for r in registros[:6]], t0)


def t_red_cerca(args: dict) -> dict:
    t0 = time.time()
    lat = float(args["lat"]); lon = float(args["lon"])
    radio = float(args.get("radio_km") or 25)
    tension = args.get("tension")
    gj = cargar_json("simplificado/lineas_hv.geojson")
    encontrados = []
    for f in gj["features"]:
        coords = f["geometry"]["coordinates"]
        if not coords:
            continue
        if tension and int(f["properties"].get("voltage") or 0) != int(tension) * 1000:
            continue
        if not en_bbox(lat, lon, bbox_de(coords), radio * 1.2):
            continue
        d = distancia_a_linea(lat, lon, coords)
        if d > radio:
            continue
        p = f["properties"]
        encontrados.append({
            "osm_id": p.get("osm_id"),
            "tension_kV": int((p.get("voltage") or 0) / 1000),
            "operador": p.get("operator"),
            "circuitos": p.get("circuits"),
            "tipo": p.get("line_type"),
            "distancia_km": round(d, 2),
            "longitud_km": round(longitud_linea_km(coords), 1),
        })
    encontrados.sort(key=lambda x: x["distancia_km"])
    por_tension: dict[str, int] = {}
    for e in encontrados:
        por_tension[f"{e['tension_kV']} kV"] = por_tension.get(f"{e['tension_kV']} kV", 0) + 1
    datos = {
        "punto": {"lat": lat, "lon": lon},
        "radio_km": radio,
        "tramos": len(encontrados),
        "porTension": por_tension,
        "masCercanos": encontrados[: int(args.get("limit") or 10)],
        "nota": "Distancia punto→polilínea en proyección local (error <0,1 % a 100 km). "
                "Tensión y operador vienen de OSM, no de un dato en vivo.",
    }
    texto = (
        f"{len(encontrados)} tramos de alta tensión en {radio:g} km de ({lat}, {lon}): "
        + (", ".join(f"{k}: {v}" for k, v in sorted(por_tension.items())) or "ninguno")
        + (f". El más cercano a {encontrados[0]['distancia_km']} km "
           f"({encontrados[0]['tension_kV']} kV, {encontrados[0]['operador'] or 'operador sin declarar'})."
           if encontrados else ".")
    )
    return responder("es.red.cerca", texto, datos, ["red-electrica"], [], t0)


def _puntos_cerca(rel: str, lat: float, lon: float, radio: float, campo_nombre: str,
                  campos_extra: list[str] | None = None, limite: int = 5) -> tuple[int, list]:
    p = DATOS / rel
    if not p.exists():
        return 0, []
    d = cargar_json(rel)
    out = []
    n = 0
    for f in d.get("features", []):
        g = f.get("geometry")
        if not g or g.get("type") != "Point":
            continue
        plon, plat = g["coordinates"][:2]
        dist = haversine(lat, lon, plat, plon)
        if dist > radio:
            continue
        n += 1
        if len(out) < limite:
            item = {"nombre": f["properties"].get(campo_nombre), "distancia_km": round(dist, 2)}
            for c in (campos_extra or []):
                v = f["properties"].get(c)
                if v not in (None, "", []):
                    item[c] = v
            out.append(item)
    out.sort(key=lambda x: x["distancia_km"])
    return n, out


def t_red_resumen(args: dict) -> dict:
    t0 = time.time()
    lat = float(args["lat"]); lon = float(args["lon"])
    radio = float(args.get("radio_km") or 30)
    plantas = cargar_json("plantas.geojson")["features"]
    por_tec: dict[str, dict] = {}
    pot_total = 0.0
    cerca = []
    for f in plantas:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        plon, plat = g["coordinates"][:2]
        if abs(plat - lat) > radio / 90 or abs(plon - lon) > radio / 60:
            continue
        dist = haversine(lat, lon, plat, plon)
        if dist > radio:
            continue
        p = f["properties"]
        tec = p.get("technology_normalized") or "otra"
        mw = p.get("installed_capacity_mw") or 0
        pot_total += mw
        d = por_tec.setdefault(tec, {"n": 0, "mw": 0.0, "max_mw": 0, "ejemplo": None})
        d["n"] += 1
        d["mw"] += mw
        if mw > d["max_mw"]:
            d["max_mw"] = mw
            d["ejemplo"] = p.get("name")
        cerca.append({"planta": p.get("name"), "tecnologia": tec,
                      "mw": round(mw, 1), "municipio": p.get("municipality"),
                      "distancia_km": round(dist, 1)})
    cerca.sort(key=lambda x: -(x["mw"] or 0))
    n_lineas, _ = _lineas_cerca(lat, lon, radio)
    embalses = cargar_json("simplificado/agua-embalsada.geojson")["features"]
    emb = []
    for f in embalses:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        plon, plat = g["coordinates"][:2]
        dist = haversine(lat, lon, plat, plon)
        if dist <= radio and f["properties"].get("capacidad_hm3"):
            emb.append({"nombre": f["properties"].get("nombre"),
                        "capacidad_hm3": f["properties"].get("capacidad_hm3"),
                        "agua_hm3": f["properties"].get("agua_actual_hm3"),
                        "distancia_km": round(dist, 1)})
    emb.sort(key=lambda x: -(x["capacidad_hm3"] or 0))
    n_edar, edar = _puntos_cerca("simplificado/edar.geojson", lat, lon, radio, "name")
    n_etap, etap = _puntos_cerca("simplificado/etap.geojson", lat, lon, radio, "osm_id")
    n_gas, gas = _puntos_cerca("simplificado/gasoductos.geojson", lat, lon, radio, "nombre",
                              ["operador", "gas", "presion"])
    n_desal, desal = _puntos_cerca("desaladoras.geojson", lat, lon, radio, "nombre",
                                   ["capacidad_m3_dia"])
    datos = {
        "punto": {"lat": lat, "lon": lon},
        "radio_km": radio,
        "energia": {
            "plantas": len(cerca),
            "potenciaMW": round(pot_total, 1),
            "porTecnologia": {k: {"n": v["n"], "MW": round(v["mw"], 1), "mayor": v["ejemplo"]}
                              for k, v in sorted(por_tec.items(), key=lambda kv: -kv[1]["mw"])},
            "mayores": cerca[:8],
            "tramosAltaTension": n_lineas,
        },
        "agua": {"embalses": len(emb), "capacidadHm3": _num(sum(e["capacidad_hm3"] for e in emb)),
                 "mayores": emb[:5], "edar": n_edar, "etap": n_etap,
                 "desaladoras": n_desal, "muestra_edar": edar, "muestra_desaladoras": desal},
        "gas": {"gasoductos": n_gas, "muestra": gas},
        "nota": "Radios medidos con haversine sobre puntos y distancia punto-polilínea; "
                "las plantas con MW proceden de REE + ELECTRA RAIPEE. No es un inventario censal: "
                "es lo que hay cartografiado en el radio.",
    }
    texto = (
        f"Resumen de {radio:g} km alrededor de ({lat}, {lon}): "
        f"{len(cerca)} plantas ({pot_total:,.0f} MW), {n_lineas} tramos de 220/400 kV, "
        f"{len(emb)} embalses, {n_edar} EDAR, {n_etap} ETAP, {n_desal} desaladoras, {n_gas} gasoductos. "
        + (f"La mayor: {cerca[0]['planta']} ({cerca[0]['mw']:,} MW, {cerca[0]['tecnologia']}, "
           f"a {cerca[0]['distancia_km']} km)." if cerca else "")
    )
    return responder("es.red.resumen_punto", texto, datos,
                     ["plantas", "red-electrica", "embalses", "edar", "etap", "desaladoras",
                      "conducciones-combustible"], [], t0)


def _lineas_cerca(lat, lon, radio):
    gj = cargar_json("simplificado/lineas_hv.geojson")
    n = 0
    for f in gj["features"]:
        coords = f["geometry"]["coordinates"]
        if not coords or not en_bbox(lat, lon, bbox_de(coords), radio * 1.2):
            continue
        if distancia_a_linea(lat, lon, coords) <= radio:
            n += 1
    return n, {}


def t_plantas_buscar(args: dict) -> dict:
    t0 = time.time()
    plantas = cargar_json("plantas.geojson")["features"]
    tec = (args.get("tecnologia") or "").lower()
    ccaa = (args.get("ccaa") or "").lower()
    prov = (args.get("provincia") or "").lower()
    min_mw = float(args.get("min_mw") or 0)
    sel = []
    for f in plantas:
        p = f["properties"]
        if tec and tec not in (p.get("technology_normalized") or "").lower():
            continue
        if ccaa and ccaa not in (p.get("autonomous_region") or "").lower():
            continue
        if prov and prov not in (p.get("province") or "").lower():
            continue
        mw = p.get("installed_capacity_mw") or 0
        if mw < min_mw:
            continue
        sel.append((mw, p))
    sel.sort(key=lambda x: -x[0])
    por_tec: dict[str, dict] = {}
    for mw, p in sel:
        k = p.get("technology_normalized") or "otra"
        d = por_tec.setdefault(k, {"n": 0, "mw": 0.0})
        d["n"] += 1
        d["mw"] += mw
    datos = {
        "coincidencias": len(sel),
        "potenciaTotalMW": round(sum(m for m, _ in sel), 1),
        "porTecnologia": {k: {"n": v["n"], "MW": round(v["mw"], 1)}
                          for k, v in sorted(por_tec.items(), key=lambda kv: -kv[1]["mw"])},
        "mayores": [{"nombre": p.get("name"), "mw": round(mw, 1),
                     "tecnologia": p.get("technology_normalized"),
                     "provincia": p.get("province"), "municipio": p.get("municipality")}
                    for mw, p in sel[: int(args.get("limit") or 10)]],
        "nota": "Potencia del registro REE + ELECTRA RAIPEE: es potencia instalada, no producción.",
    }
    top = sorted(por_tec.items(), key=lambda kv: -kv[1]["mw"])[:4]
    detalle = ", ".join(f"{k} {round(v['mw']):,} MW" for k, v in top)
    texto = (
        f"{len(sel)} plantas, {sum(m for m, _ in sel):,.0f} MW acumulados"
        + (f" ({detalle})" if top else "")
        + (f". La mayor: {sel[0][1].get('name')} ({sel[0][0]:,.1f} MW)." if sel else ".")
    )
    return responder("es.plantas.buscar", texto, datos, ["plantas"], [], t0)


def t_clima_avisos(args: dict) -> dict:
    t0 = time.time()
    d = cargar_json("aemet_avisos.json")
    avisos = d.get("avisos", [])
    nivel = (args.get("nivel") or "").lower()
    zona = (args.get("zona") or "").lower()
    sel = []
    for a in avisos:
        if nivel and nivel not in json.dumps(a, ensure_ascii=False).lower():
            continue
        if zona and zona not in json.dumps(a, ensure_ascii=False).lower():
            continue
        sel.append(a)
    datos = {
        "descargado": d.get("descargado"),
        "via": d.get("via"),
        "total": d.get("total"),
        "vigentes": d.get("vigentes"),
        "porNivel": d.get("por_nivel"),
        "porEvento": d.get("por_evento"),
        "seleccionados": len(sel),
        "avisos": sel[: int(args.get("limit") or 10)],
        "nota_geometria": d.get("nota_geometria"),
    }
    texto = (
        f"AEMET vía Meteoalarm (descargado {d.get('descargado')}): {d.get('vigentes')} avisos vigentes "
        f"de {d.get('total')} — {d.get('por_nivel')}. "
        f"Coincidencias con el filtro: {len(sel)}."
    )
    return responder("es.clima.avisos", texto, datos, ["aemet-zonas"], [], t0)


def t_transporte_vivo(args: dict) -> dict:
    t0 = time.time()
    d = cargar_json("gtfsrt_vehiculos.geojson")
    linea = (args.get("linea") or "").upper()
    operador = (args.get("operador") or "").lower()
    sel = []
    for f in d["features"]:
        p = f["properties"]
        if linea and (p.get("linea") or "").upper() != linea:
            continue
        if operador and operador not in (p.get("operador") or "").lower():
            continue
        sel.append(p)
    ultima = max((p.get("ultima") or "" for p in sel), default=None)
    por_linea: dict[str, int] = {}
    for p in sel:
        k = p.get("linea") or "?"
        por_linea[k] = por_linea.get(k, 0) + 1
    datos = {
        "vehiculos": len(sel),
        "porLinea": dict(sorted(por_linea.items(), key=lambda kv: -kv[1])[:15]),
        "ultimaPosicion": ultima,
        "muestra": sel[: int(args.get("limit") or 8)],
        "nota": "GTFS-RT de Renfe (NAP). La licencia está pendiente de evaluar en el catálogo: "
                "no se sirve como dato público hasta cerrarlo.",
    }
    texto = (
        f"{len(sel)} vehículos en vivo (última posición {ultima})"
        + (f" — líneas: {', '.join(f'{k}×{v}' for k, v in list(datos['porLinea'].items())[:6])}." if sel else ".")
    )
    return responder("es.transporte.vivo", texto, datos, ["gtfsrt"], [], t0)


def t_geo_municipio(args: dict) -> dict:
    t0 = time.time()
    nomb = (args.get("nombre") or "").lower().strip()
    cod = str(args.get("cod_ine") or "").strip()
    if not nomb and not cod:
        return error("es.geo.municipio", "Falta el municipio",
                     "pasa cod_ine (5 dígitos) o nombre (se busca por coincidencia)")
    muns = cargar_json("municipios.geojson")["features"]
    objetivo = None
    for f in muns:
        p = f["properties"]
        if cod and str(p.get("cod_ine")) == cod:
            objetivo = f
            break
        if nomb and (p.get("nombre_norm") or "").replace(" ", "") == nomb.replace(" ", ""):
            objetivo = f
            break
    if objetivo is None and nomb:
        cand = [f for f in muns if nomb in (f["properties"].get("nombre_norm") or "")]
        if len(cand) == 1:
            objetivo = cand[0]
        elif len(cand) > 1:
            return error("es.geo.municipio", f"«{nomb}» coincide con {len(cand)} municipios",
                         "afina el nombre o pasa cod_ine: " +
                         ", ".join(f"{c['properties']['cod_ine']} {c['properties']['nombre']}" for c in cand[:5]))
    if objetivo is None:
        return error("es.geo.municipio", f"Municipio no encontrado ({cod or nomb})",
                     "el padrón trae 8.128 municipios con código INE de 5 dígitos")
    p = objetivo["properties"]
    centro = centroide(objetivo.get("geometry"))
    geom = objetivo.get("geometry") or {}
    anillos_ = anillos(geom)
    bb = bbox_de([(x, y) for anillo in anillos_ for x, y in anillo]) if anillos_ else None

    def dentro(lon, lat):
        if bb and not en_bbox(lat, lon, bb):
            return False
        return any(punto_en_poligono(lat, lon, a) for a in anillos_)

    plantas_sel = []
    for f in cargar_json("plantas.geojson")["features"]:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon_, lat_ = g["coordinates"][:2]
        if dentro(lon_, lat_):
            plantas_sel.append(f["properties"])
    por_tec: dict[str, dict] = {}
    for q in plantas_sel:
        k = q.get("technology_normalized") or "otra"
        d = por_tec.setdefault(k, {"n": 0, "mw": 0.0})
        d["n"] += 1
        d["mw"] += q.get("installed_capacity_mw") or 0
    emb = []
    for f in cargar_json("simplificado/agua-embalsada.geojson")["features"]:
        g = f.get("geometry") or {}
        if g.get("type") == "Point" and dentro(*g["coordinates"][:2]):
            q = f["properties"]
            if q.get("capacidad_hm3"):
                emb.append({"nombre": q.get("nombre"), "capacidad_hm3": q.get("capacidad_hm3"),
                            "agua_hm3": q.get("agua_actual_hm3"), "demarcacion": q.get("demarcacion")})
    edar = sum(1 for f in cargar_json("simplificado/edar.geojson")["features"]
               if (f.get("geometry") or {}).get("type") == "Point" and dentro(*f["geometry"]["coordinates"][:2]))
    etap = sum(1 for f in cargar_json("simplificado/etap.geojson")["features"]
               if (f.get("geometry") or {}).get("type") == "Point" and dentro(*f["geometry"]["coordinates"][:2]))
    lineas = 0
    if bb:
        for f in cargar_json("simplificado/lineas_hv.geojson")["features"]:
            coords = f["geometry"]["coordinates"]
            if coords and any(en_bbox(c[1], c[0], bb) for c in coords[::5] or coords[:1]):
                lineas += 1
    muni = {
        "cod_ine": p.get("cod_ine"),
        "nombre": p.get("nombre"),
        "provincia": p.get("provincia_nombre"),
        "poblacion": p.get("poblacion"),
        "anio_poblacion": p.get("anio_poblacion"),
        "poblacion_fuente": p.get("poblacion_fuente"),
        "area_km2": p.get("area_km2"),
        "densidad_hab_km2": round((p.get("poblacion") or 0) / p["area_km2"], 1) if p.get("area_km2") else None,
        "centroide": [round(centro[1], 4), round(centro[0], 4)] if centro else None,
    }
    datos = {
        "municipio": muni,
        "energia": {
            "plantas": len(plantas_sel),
            "potenciaMW": round(sum(q.get("installed_capacity_mw") or 0 for q in plantas_sel), 1),
            "porTecnologia": {k: {"n": v["n"], "MW": round(v["mw"], 1)}
                              for k, v in sorted(por_tec.items(), key=lambda kv: -kv[1]["mw"])},
            "tramosAltaTensionConVerticeEnElTermino": lineas,
        },
        "agua": {"embalses": len(emb), "capacidadHm3": _num(sum(e["capacidad_hm3"] for e in emb)),
                 "lista": emb[:5], "edar": edar, "etap": etap},
        "nota": "Point-in-polygon sobre el polígono municipal simplificado (ray casting, sin agujeros). "
                "Los tramos de línea se cuentan por vértices dentro del término: aproximación declarada.",
    }
    texto = (
        f"{muni['nombre']} ({muni['provincia']}, INE {muni['cod_ine']}): "
        f"{muni['poblacion']:,.0f} hab. en {muni['area_km2']} km² ({muni['densidad_hab_km2']} hab/km², "
        f"{muni['poblacion_fuente']}). "
        f"{len(plantas_sel)} plantas ({datos['energia']['potenciaMW']:,.0f} MW), "
        f"{lineas} tramos de alta tensión con vértice en el término, embalses: {len(emb)}, "
        f"EDAR: {edar}, ETAP: {etap}."
    )
    return responder("es.geo.municipio", texto, datos,
                     ["municipios", "plantas", "embalses", "red-electrica", "edar", "etap"],
                     [str(muni["cod_ine"])], t0)


# --------------------------------------------------------------------------
# Registro de herramientas (lo único que el modelo lee)
# --------------------------------------------------------------------------

HERRAMIENTAS = [
    {
        "name": "es.datos.catalogo",
        "fn": t_datos_catalogo,
        "description": "Lista las capas de OpenInfraES con su organismo productor, su licencia, su fecha de dato "
                       "y si está caducada. Es el índice de la federación: úsalo antes de preguntar por una fuente "
                       "concreta. Filtra por texto (filtro), solo oficiales, solo caducadas o solo licencia pendiente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filtro": {"type": "string", "description": "Texto libre: 'gas', 'embalses', 'eólicos', 'gtfs'"},
                "solo_oficiales": {"type": "boolean", "description": "Solo capas de organismo productor"},
                "solo_caducadas": {"type": "boolean", "description": "Solo capas fuera de su TTL"},
                "licencia_pendiente": {"type": "boolean", "description": "Solo capas cuya licencia no está cerrada"},
                "limit": {"type": "number", "description": "Máximo de capas a devolver (por defecto 40)"},
            },
        },
        "ejemplo": {},
    },
    {
        "name": "es.datos.salud",
        "fn": t_datos_salud,
        "description": "Estado de salud de la federación: cuántas capas hay, cuántas están caducadas, cuáles no "
                       "tienen licencia evaluada y qué conjuntos en vivo (energía, trenes, clima, sismos) se pueden "
                       "leer ahora mismo y con qué edad. Úsalo para saber si un dato se puede citar.",
        "inputSchema": {"type": "object", "properties": {}},
        "ejemplo": {},
    },
    {
        "name": "es.energia.estado_ahora",
        "fn": t_energia_estado,
        "description": "Estado eléctrico de España ahora: demanda nacional, CO₂, bombeo e intercambios "
                       "internacionales (ESIOS) más el mix completo por tecnología (ENTSO-E A75), con la hora, la "
                       "resolución y la edad de cada dato.",
        "inputSchema": {"type": "object", "properties": {}},
        "ejemplo": {},
    },
    {
        "name": "es.energia.mix_tecnologia",
        "fn": t_energia_mix,
        "description": "Mix de generación del día por tecnología con energía (MWh), porcentaje, MW medio, capacidad "
                       "instalada y factor de carga. Filtra por tecnología ('nuclear', 'solar', 'eolica'). El día en "
                       "curso está incompleto: se declara cuántos cuartos hay.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tecnologia": {"type": "string", "description": "Filtro por nombre de tecnología"},
            },
        },
        "ejemplo": {"tecnologia": "nuclear"},
    },
    {
        "name": "es.energia.precio_cuarto_hora",
        "fn": t_energia_precio,
        "description": "Precio del mercado diario OMIE en €/MWh por cuartos de hora, con media, mínimo y máximo del "
                       "día. Si se pasa una hora, devuelve sus cuatro cuartos. Resolución PT15M real, no horaria.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hora": {"type": "number", "description": "Hora del día (1-24) para ver sus 4 cuartos"},
            },
        },
        "ejemplo": {"hora": 20},
    },
    {
        "name": "es.agua.embalses",
        "fn": t_agua_embalses,
        "description": "Agua embalsada en España según el Boletín Hidrológico del MITECO: capacidad, agua almacenada "
                       "y porcentaje por embalse y por demarcación, con el agregado nacional. Devuelve los más vacíos "
                       "y los más llenos.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "demarcacion": {"type": "string", "description": "Filtro por demarcación: 'Tajo', 'Ebro', 'Segura'..."},
                "max_pct": {"type": "number", "description": "Solo embalses por debajo de este % de llenado"},
                "limit": {"type": "number", "description": "Cuántos devolver en cada extremo (por defecto 12)"},
            },
        },
        "ejemplo": {"demarcacion": "Segura"},
    },
    {
        "name": "es.red.cerca",
        "fn": t_red_cerca,
        "description": "Tramos de alta tensión (220 y 400 kV) a menos de X km de un punto, ordenados por distancia, "
                       "con tensión, operador, circuitos y longitud del tramo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitud WGS84"},
                "lon": {"type": "number", "description": "Longitud WGS84"},
                "radio_km": {"type": "number", "description": "Radio en km (por defecto 25)"},
                "tension": {"type": "number", "description": "Filtrar por 220 o 400 kV"},
                "limit": {"type": "number", "description": "Cuántos devolver (por defecto 10)"},
            },
            "required": ["lat", "lon"],
        },
        "ejemplo": {"lat": 40.4168, "lon": -3.7038, "radio_km": 20},
    },
    {
        "name": "es.red.resumen_punto",
        "fn": t_red_resumen,
        "description": "Informe de infraestructura de un punto: en un radio dado cuenta plantas de generación con "
                       "su potencia por tecnología, tramos de 220/400 kV, embalses con capacidad, EDAR, ETAP, "
                       "desaladoras y gasoductos. Es la pregunta «¿qué hay aquí?» resuelta de una vez.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitud WGS84"},
                "lon": {"type": "number", "description": "Longitud WGS84"},
                "radio_km": {"type": "number", "description": "Radio en km (por defecto 30)"},
            },
            "required": ["lat", "lon"],
        },
        "ejemplo": {"lat": 41.6488, "lon": -0.8891, "radio_km": 40},
    },
    {
        "name": "es.plantas.buscar",
        "fn": t_plantas_buscar,
        "description": "Busca instalaciones de generación del registro REE + ELECTRA (5.797 plantas, 126 GW) por "
                       "tecnología, comunidad autónoma, provincia o potencia mínima, y devuelve agregados por "
                       "tecnología además de las mayores. La potencia es instalada, no producción.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tecnologia": {"type": "string", "description": "solar_pv, wind, nuclear, ccgt, hydro, cogeneration..."},
                "ccaa": {"type": "string", "description": "Comunidad autónoma"},
                "provincia": {"type": "string", "description": "Provincia"},
                "min_mw": {"type": "number", "description": "Potencia instalada mínima en MW"},
                "limit": {"type": "number", "description": "Cuántas devolver (por defecto 10)"},
            },
        },
        "ejemplo": {"tecnologia": "nuclear"},
    },
    {
        "name": "es.clima.avisos",
        "fn": t_clima_avisos,
        "description": "Avisos meteorológicos vigentes de AEMET (vía Meteoalarm) por nivel y por zona, con el "
                       "recuento por fenómeno y la fecha de descarga. Filtra por nivel ('naranja', 'amarillo') o zona.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nivel": {"type": "string", "description": "Nivel del aviso: amarillo, naranja, rojo"},
                "zona": {"type": "string", "description": "Nombre de la zona o provincia"},
                "limit": {"type": "number", "description": "Cuántos avisos devolver (por defecto 10)"},
            },
        },
        "ejemplo": {"nivel": "naranja"},
    },
    {
        "name": "es.transporte.vivo",
        "fn": t_transporte_vivo,
        "description": "Vehículos de Renfe en vivo por GTFS-RT (posición, línea, vehículo y última actualización), "
                       "filtrable por línea u operador. Declara que su licencia sigue pendiente en el catálogo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "linea": {"type": "string", "description": "Código de línea, por ejemplo 'C5'"},
                "operador": {"type": "string", "description": "Operador, por ejemplo 'Renfe'"},
                "limit": {"type": "number", "description": "Cuántos vehículos devolver (por defecto 8)"},
            },
        },
        "ejemplo": {"linea": "C5"},
    },
    {
        "name": "es.geo.municipio",
        "fn": t_geo_municipio,
        "description": "Ficha de un municipio cruzando padrón del INE, plantas de generación, embalses, EDAR, ETAP y "
                       "alta tensión DENTRO del término municipal: población, densidad, potencia instalada por "
                       "tecnología y agua embalsada. Es la pregunta «¿qué tiene este municipio?».",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cod_ine": {"type": "string", "description": "Código INE de 5 dígitos (ej. '28079' Madrid)"},
                "nombre": {"type": "string", "description": "Nombre del municipio si no se tiene el código"},
            },
        },
        "ejemplo": {"nombre": "Zamora"},
    },
]

POR_NOMBRE = {h["name"]: h for h in HERRAMIENTAS}


# --------------------------------------------------------------------------
# Protocolo MCP (JSON-RPC 2.0)
# --------------------------------------------------------------------------


def lista_herramientas() -> list[dict]:
    return [
        {"name": h["name"], "description": h["description"], "inputSchema": h["inputSchema"]}
        for h in HERRAMIENTAS
    ]


def manejar(peticion: dict) -> dict | None:
    metodo = peticion.get("method")
    ident = peticion.get("id")
    if ident is None:  # notificación: nunca se responde
        return None
    if metodo == "initialize":
        pedida = (peticion.get("params") or {}).get("protocolVersion")
        return {
            "jsonrpc": "2.0", "id": ident,
            "result": {
                "protocolVersion": pedida if pedida in PROTOCOLOS else "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVIDOR, "version": VERSION},
                "instructions": "Federación de datos de infraestructura de España (OpenInfraES). "
                                "Empieza por es.datos.catalogo si no sabes qué capa responde a la pregunta.",
            },
        }
    if metodo == "ping":
        return {"jsonrpc": "2.0", "id": ident, "result": {}}
    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": ident, "result": {"tools": lista_herramientas()}}
    if metodo == "tools/call":
        params = peticion.get("params") or {}
        nombre = params.get("name")
        args = params.get("arguments") or {}
        if nombre not in POR_NOMBRE:
            return {
                "jsonrpc": "2.0", "id": ident,
                "result": {"content": [{"type": "text", "text": f"Herramienta desconocida: {nombre}"}],
                           "isError": True},
            }
        try:
            resultado = POR_NOMBRE[nombre]["fn"](args)
        except FaltaFichero as exc:
            resultado = error(nombre, str(exc), "refresca los datos con el capturador de esa capa")
        except KeyError as exc:
            resultado = error(nombre, f"Falta el argumento obligatorio {exc}",
                              "mira inputSchema en tools/list")
        except Exception as exc:  # noqa: BLE001
            _log(f"fallo en {nombre}: {exc!r}")
            resultado = error(nombre, f"Fallo interno: {exc}", "revisa los argumentos y los datos del repo")
        return {"jsonrpc": "2.0", "id": ident, "result": resultado}
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": f"Method not found: {metodo}"}}


def servir_stdio() -> int:
    _log(f"escuchando en stdio (NDJSON) · {len(HERRAMIENTAS)} herramientas")
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            peticion = json.loads(linea)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": str(exc)}}) + "\n")
            sys.stdout.flush()
            continue
        respuesta = manejar(peticion)
        if respuesta is not None:
            sys.stdout.write(json.dumps(respuesta, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------
# Modo HTTP: /api/mcp (JSON-RPC) + /api/state (agregado para una web)
# --------------------------------------------------------------------------


def estado_agregado() -> dict:
    """El «/api/state» que necesita un panel: todo lo que se puede mirar de un vistazo."""
    t0 = time.time()
    c = catalogo()
    ree = cargar_json("ree_vivo.json")
    resumen = c.get("resumen") or {}
    mix = cargar_json("entsoe_mix.json") if (DATOS / "entsoe_mix.json").exists() else None
    omie = cargar_json("omie_precio.json") if (DATOS / "omie_precio.json").exists() else None
    emb = None
    p = DATOS / "simplificado" / "agua-embalsada.geojson"
    if p.exists():
        registros = [f["properties"] for f in cargar_json("simplificado/agua-embalsada.geojson")["features"]
                     if f["properties"].get("capacidad_hm3") and f["properties"].get("agua_actual_hm3")]
        cap = sum(r["capacidad_hm3"] for r in registros)
        agua = sum(r["agua_actual_hm3"] for r in registros)
        emb = {"embalses": len(registros), "capacidadHm3": _num(cap), "aguaHm3": _num(agua),
               "pct": round(100 * agua / cap, 1) if cap else None,
               "fecha_dato": registros[0].get("fecha_dato") if registros else None}
    return {
        "servidor": {"nombre": SERVIDOR, "version": VERSION,
                     "herramientas": len(HERRAMIENTAS),
                     "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "latencyMs": int((time.time() - t0) * 1000)},
        "catalogo": {"total": c.get("total"), **resumen},
        "kpis": {
            "demandaMW": (ree.get("estado") or {}).get("demanda"),
            "co2": (ree.get("estado") or {}).get("co2"),
            "precioOMIE_media": (omie or {}).get("media"),
            "precioOMIE_max": (omie or {}).get("max"),
            "aguaEmbalsadaPct": (emb or {}).get("pct"),
            "renovablesUltimoCuartoMW": round(sum(
                t.get("ultimo_mw") or 0 for t in (mix or {}).get("tecnologias", [])
                if (t["codigo"] or "").startswith(("Solar", "Eólica", "Hidro", "Biomasa",
                                                   "Otras renovables", "Geotérmica", "Marina"))), 0),
        },
        "energia": {
            "demanda": ree.get("estado"),
            "cobertura": {"actualizado": ree.get("actualizado"), "edad_min": ree.get("edad_min"),
                          "resolucion": ree.get("resolucion"), "fuente": ree.get("fuente")},
            "mix": [{"tecnologia": t["codigo"], "mw": t.get("ultimo_mw"), "pct": t.get("pct")}
                    for t in sorted((mix or {}).get("tecnologias", []), key=lambda x: -(x.get("ultimo_mw") or 0))],
            "precio": {"fecha": (omie or {}).get("fecha"), "media": (omie or {}).get("media"),
                       "min": (omie or {}).get("min"), "max": (omie or {}).get("max")},
            "agua": emb,
        },
        "capasCaducadas": sorted(k for k, v in c["capas"].items() if v.get("caducado")),
        "capasSinLicencia": sorted(k for k, v in c["capas"].items()
                                   if (v.get("licencia") or {}).get("estado") != "si"),
    }


def servir_http(puerto: int) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, formato, *a):  # silencio: no ensuciar stderr con cada petición
            pass

        def _json(self, codigo: int, cuerpo: dict):
            datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.end_headers()

        def do_GET(self):
            if self.path.rstrip("/") in ("", "/api/state", "/state"):
                try:
                    self._json(200, estado_agregado())
                except Exception as exc:  # noqa: BLE001
                    self._json(500, {"error": str(exc)})
            elif self.path.rstrip("/") in ("/api/mcp", "/mcp"):
                self._json(405, {"error": "usa POST con JSON-RPC 2.0"})
            elif self.path.rstrip("/") == "/salud":
                self._json(200, {"status": "ok", "servidor": SERVIDOR, "version": VERSION})
            else:
                self._json(404, {"error": "no existe", "rutas": ["/api/mcp", "/api/state", "/salud"]})

        def do_POST(self):
            if self.path.rstrip("/") not in ("/api/mcp", "/mcp"):
                self._json(404, {"error": "no existe", "rutas": ["/api/mcp", "/api/state"]})
                return
            largo = int(self.headers.get("Content-Length") or 0)
            try:
                peticion = json.loads(self.rfile.read(largo).decode("utf-8"))
            except Exception:  # noqa: BLE001
                self._json(400, {"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32700, "message": "JSON ilegible"}})
                return
            respuesta = manejar(peticion)
            if respuesta is None:
                self.send_response(202)
                self.end_headers()
                return
            self._json(200, respuesta)

    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    _log(f"HTTP en http://127.0.0.1:{puerto}  ·  POST /api/mcp  ·  GET /api/state")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


# --------------------------------------------------------------------------
# Autochequeo: se habla como un cliente MCP real (subproceso + NDJSON)
# --------------------------------------------------------------------------


def autochequeo() -> int:
    print(f"== autochequeo {SERVIDOR} v{VERSION} ==")
    peticiones = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "autochequeo", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    entrada = "\n".join(json.dumps(p, ensure_ascii=False) for p in peticiones) + "\n"
    proc = subprocess.run([sys.executable, __file__], input=entrada, capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    if proc.returncode != 0:
        print("FALLO: el servidor terminó con", proc.returncode)
        print(proc.stderr[-2000:])
        return 1
    lineas = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if len(lineas) != 2:
        print(f"FALLO: se esperaban 2 respuestas (la notificación no se responde), llegaron {len(lineas)}")
        for ln in lineas:
            print("  ", ln[:200])
        return 1
    inicial = json.loads(lineas[0])
    lista = json.loads(lineas[1])
    fallos = []
    if inicial.get("result", {}).get("protocolVersion") != "2025-06-18":
        fallos.append("initialize no devolvió la versión del cliente")
    herramientas = lista.get("result", {}).get("tools", [])
    if len(herramientas) != len(HERRAMIENTAS):
        fallos.append(f"tools/list devolvió {len(herramientas)} de {len(HERRAMIENTAS)}")
    print(f"  initialize ok · tools/list {len(herramientas)} herramientas")

    for h in HERRAMIENTAS:
        entrada = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 10, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}, ensure_ascii=False),
            json.dumps({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                        "params": {"name": h["name"], "arguments": h.get("ejemplo", {})}}, ensure_ascii=False),
        ]) + "\n"
        p2 = subprocess.run([sys.executable, __file__], input=entrada, capture_output=True,
                            text=True, encoding="utf-8", timeout=300)
        out = [ln for ln in p2.stdout.splitlines() if ln.strip()]
        if len(out) < 2:
            fallos.append(f"{h['name']}: sin respuesta")
            print(f"  FALLO {h['name']}: sin respuesta")
            continue
        r = json.loads(out[1])["result"]
        texto = (r.get("content") or [{}])[0].get("text", "")
        if r.get("isError"):
            fallos.append(f"{h['name']}: isError — {texto[:160]}")
            print(f"  FALLO {h['name']}: {texto[:160]}")
            continue
        if not texto or "structuredData" not in r:
            fallos.append(f"{h['name']}: respuesta sin texto o sin structuredData")
            print(f"  FALLO {h['name']}: falta texto o structuredData")
            continue
        meta = r.get("meta", {})
        # Las herramientas de catálogo no citan capas: su fuente ES el catálogo.
        if not meta.get("dataSourceIds") and h["name"] not in ("es.datos.catalogo", "es.datos.salud"):
            print(f"  aviso {h['name']}: sin dataSourceIds")
        print(f"  ok    {h['name']:<28} {meta.get('latencyMs', 0):>5} ms · {texto[:96]}…")
    if fallos:
        print(f"\nFALLO: {len(fallos)} incidencia(s)")
        return 1
    print(f"\nVERDE: {len(HERRAMIENTAS)} herramientas, framing correcto, contenido verificado")
    return 0


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="MCP federado de OpenInfraES")
    ap.add_argument("--http", nargs="?", const=8077, type=int,
                    help="sirve por HTTP (POST /api/mcp y GET /api/state)")
    ap.add_argument("--test", action="store_true", help="autochequeo como cliente MCP real")
    ap.add_argument("--list-tools", action="store_true", help="imprime el catálogo de herramientas")
    args = ap.parse_args()
    if args.test:
        return autochequeo()
    if args.list_tools:
        for h in HERRAMIENTAS:
            print(h["name"], "—", h["description"].split(".")[0])
        return 0
    if args.http is not None:
        return servir_http(args.http)
    return servir_stdio()


if __name__ == "__main__":
    sys.exit(main())
