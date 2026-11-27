# -*- coding: utf-8 -*-
"""Zonas de servicio de los puertos de interés general (Puertos del Estado · INSPIRE).

Lo que aporta: el visor tiene los puertos como PUNTO, y además copiados del mapa de otro
organismo (Visor Hermes del MITMA, jerarquía 2). Esto trae el polígono OFICIAL de la zona de
servicio, tal como la delimita Puertos del Estado: zona terrestre, zona I de aguas y zona II
de aguas, con superficie, dársena y fecha de desafectación.

Fuente: WFS 2.0 de Puertos del Estado — `geoserver.puertos.es/geoserver/puertos/wfs`
(dos tipos: `TN.WaterTransportNetwork.PortArea` y `TN.WaterTransportNetwork.FairwayArea`).
Devuelve GeoJSON con `outputFormat=application/json`, así que no hay que convertir nada.
Sin clave. Catálogo: https://www.idee.es/csw-codsi-idee/srv/api/records/spa_puertos_estado

Licencia: **CC BY 4.0** (Puertos del Estado), verificada en el CSW de IDEE —
el GetCapabilities del WFS no la trae.

Tres decisiones que cuestan tamaño y hay que dejar escritas:
  · La respuesta en bruto son 18 MB entre los dos tipos (la costa va con todo el detalle).
    Se redondea a 5 decimales y se simplifica con Douglas-Peucker a ~11 m: queda por debajo
    del megabyte. Sin eso, la capa se come el presupuesto de memoria del móvil sola.
  · `act` trae `DEUP` (zona vigente) y `Desafectación` (desafectada): NO se filtra, porque una
    zona desafectada sigue siendo información del puerto, pero se publica como campo `estado`
    para que la ficha no haga pasar por vigente lo que ya no lo es.
  · Una capa por uso: terrestre, Zona I y Zona II van juntas con `tipo` como atributo.

    python scripts/puertos_zonas.py
"""
import datetime
import json
import math
import os
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
WFS = "https://geoserver.puertos.es/geoserver/puertos/wfs"
TIPOS = [("TN.WaterTransportNetwork.PortArea", "Zona de servicio terrestre"),
         ("TN.WaterTransportNetwork.FairwayArea", None)]  # el subtipo lo dice zona_servi
SALIDA = os.path.join(DATOS, "puertos_zonas.geojson")
RECIBO = os.path.join(DATOS, "puertos_zonas_recibo.json")
TOLERANCIA = 0.0001  # ~11 m
DECIMALES = 5
COLOR = {"Zona de servicio terrestre": "#f59e0b", "Zona I": "#38bdf8", "Zona II": "#818cf8"}


def pide(tipo):
    q = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "Puertos:" + tipo, "outputFormat": "application/json"})
    req = urllib.request.Request(WFS + "?" + q,
                                 headers={"User-Agent": "OpenInfraES/1.0 (+ntizar.github.io)"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _dp(puntos, tol):
    """Douglas-Peucker sobre una lista de [x, y]."""
    if len(puntos) < 3:
        return puntos
    x1, y1 = puntos[0]
    x2, y2 = puntos[-1]
    dx, dy = x2 - x1, y2 - y1
    norma = math.hypot(dx, dy)
    dmax, idx = -1.0, 0
    for i in range(1, len(puntos) - 1):
        x0, y0 = puntos[i]
        if norma == 0:
            d = math.hypot(x0 - x1, y0 - y1)
        else:
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norma
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        izq = _dp(puntos[:idx + 1], tol)
        der = _dp(puntos[idx:], tol)
        return izq[:-1] + der
    return [puntos[0], puntos[-1]]


def _anillo(anillo):
    simpl = _dp(anillo, TOLERANCIA)
    if simpl[0] != simpl[-1]:
        simpl.append(simpl[0])
    return [[round(x, DECIMALES), round(y, DECIMALES)] for x, y in simpl]


def simplifica(geom):
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        return {"type": "Polygon", "coordinates": [_anillo(a) for a in c]}
    if t == "MultiPolygon":
        return {"type": "MultiPolygon",
                "coordinates": [[_anillo(a) for a in poli] for poli in c]}
    if t == "LineString":
        return {"type": "LineString", "coordinates": _anillo(c)}
    if t == "MultiLineString":
        return {"type": "MultiLineString", "coordinates": [_anillo(a) for a in c]}
    return geom


def main():
    print("Puertos del Estado · zonas de servicio (INSPIRE)")
    salida, vistos = [], set()
    for tipo, forzado in TIPOS:
        d = pide(tipo)
        feats = d.get("features") or []
        if not feats:
            raise SystemExit(f"{tipo} no devolvió objetos: no se toca el fichero anterior")
        print(f"  {tipo}: {len(feats)}")
        for f in feats:
            p = f.get("properties") or {}
            zona = forzado or p.get("zona_servi") or "sin clasificar"
            clave = (p.get("id_zs"), zona)
            if clave in vistos:
                continue
            vistos.add(clave)
            act = (p.get("act") or "").strip()
            props = {
                "puerto": p.get("puerto"),
                "autoridad": p.get("ap"),
                "tipo": zona,
                "estado": "vigente (DEUP)" if act.upper() == "DEUP" else
                          ("desafectada" if act else None),
                "fecha": p.get("fecha_act"),
                "darsena": p.get("darsena"),
                "superficie_ha": round(p["superficie"] / 10000.0, 1) if p.get("superficie") else None,
                "id": p.get("id_zs"),
                "ccaa": p.get("id_ccaa"),
                "color": COLOR.get(zona),
            }
            f["properties"] = {k: v for k, v in props.items() if v not in (None, "")}
            f["geometry"] = simplifica(f["geometry"])
            salida.append(f)

    salida.sort(key=lambda f: (f["properties"].get("puerto") or "zzz",
                              f["properties"].get("tipo") or ""))
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": salida}, fh,
                  ensure_ascii=False, separators=(",", ":"))

    por_tipo, por_estado, puertos = {}, {}, set()
    for f in salida:
        p = f["properties"]
        por_tipo[p.get("tipo")] = por_tipo.get(p.get("tipo"), 0) + 1
        por_estado[p.get("estado")] = por_estado.get(p.get("estado"), 0) + 1
        if p.get("puerto"):
            puertos.add(p["puerto"])

    recibo = {
        "capa": "puertos-zonas",
        "titulo": "Zonas de servicio portuarias (Puertos del Estado)",
        "fuente": "Puertos del Estado",
        "editor": "Puertos del Estado · modelo INSPIRE de redes de transporte (TN)",
        "producto": "WFS 2.0: TN.WaterTransportNetwork.PortArea + FairwayArea (zona terrestre, "
                    "Zona I y Zona II de aguas)",
        "url": WFS,
        "url_catalogo": "https://www.idee.es/csw-codsi-idee/srv/api/records/spa_puertos_estado",
        "licencia": "CC BY 4.0",
        "url_terminos": "https://www.idee.es/csw-codsi-idee/srv/api/records/spa_puertos_estado",
        "crs": "EPSG:4326 (servicio en ETRS89/4258; WGS84 al mismo orden de error del dato)",
        "features": len(salida),
        "por_tipo": por_tipo,
        "por_estado": por_estado,
        "puertos": len(puertos),
        "descargado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": "GeoJSON del WFS (outputFormat=application/json) en bruto 18 MB; redondeo a "
                  f"{DECIMALES} decimales y Douglas-Peucker a ~{TOLERANCIA * 111000:.0f} m",
        "nota": "No se filtra por estado: las zonas desafectadas se publican marcadas como tales. "
                "Los puntos `puertos` del visor salen del Visor Hermes (jerarquía 2); esto es el "
                "polígono oficial del mismo sitio.",
        "fichero": os.path.basename(SALIDA),
    }
    with open(RECIBO, "w", encoding="utf-8") as fh:
        json.dump(recibo, fh, ensure_ascii=False, indent=1)

    kb = os.path.getsize(SALIDA) / 1024
    print(f"  → {len(salida)} polígonos · {len(puertos)} puertos · {kb:,.0f} kB")
    print(f"  tipos: {por_tipo}")
    print(f"  estado: {por_estado}")


if __name__ == "__main__":
    main()
