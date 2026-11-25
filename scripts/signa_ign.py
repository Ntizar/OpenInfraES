#!/usr/bin/env python3
"""signa_ign.py — espacios protegidos, Red Natura 2000, ríos del MTN y presas (IGN · SignA).

**Qué es.** Cuatro conjuntos del visor SignA del IGN/SCNE, servidos como ArcGIS REST
públicos en `serviciosgis.ign.es/.../rest/services/Signa/`. Se piden por `query` con
`f=geojson`, sin clave y sin registro.

**Qué no es.** No es una capa de generación eléctrica: el servicio de "Centrales" del IGN
trae solo `desc_tipo_0703` (ni nombre ni potencia), y el parque de `plantas.geojson` que ya
publicamos es mejor. Tampoco sustituye a los embalses: las presas del IGN no llevan nombre ni
capacidad, son solo el muro.

**Cómo se pide** (lo que hubo que averiguar):
  · `f=geojson` sí funciona en un MapServer (no hace falta FeatureServer).
  · `outSR=4326` o llega en 25830 (ETRS89) y el visor pinta en otra parte del mundo.
  · vienen de 1.000 en 1.000: hay que paginar con `resultOffset` hasta que la página venga
    corta. Sin eso se queda uno con las primeras 1.000 LIC y no se entera.
  · los polígonos vienen sin simplificar (un parque nacional = 78 KB): `maxAllowableOffset`
    en grados + redondeo a 3 decimales (~110 m) deja la forma y quita el 80 % del peso.

Salidas (una por capa del visor):
  datos/espacios_protegidos.geojson   parques nacionales, naturales y otros ENP
  datos/red_natura.geojson            LIC y ZEPA
  datos/rios_mtn.geojson              ríos con nombre y más de 15 km
  datos/presas.geojson                presas (el muro, sin atributos)
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
BASE = "https://serviciosgis.ign.es/servicios/rest/services/Signa"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
PAGINA = 1000
FUENTE = "IGN · SignA (SCNE)"
LICENCIA = "CC BY 4.0 · © Instituto Geográfico Nacional de España"


def pide(servicio, capa, params, intentos=3):
    """Una consulta a un MapServer de SignA. Devuelve el JSON ya cargado."""
    url = "%s/%s/MapServer/%s/query?%s" % (BASE, servicio, capa,
                                           urllib.parse.urlencode(params))
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == intentos - 1:
                raise RuntimeError("falla %s/%s: %s" % (servicio, capa, e))
            time.sleep(2 + 3 * i)


def categoria(texto, por_defecto=""):
    """'02-PARQUE NATURAL' -> 'Parque natural'. El prefijo numérico es ruido en la leyenda."""
    if not texto:
        return por_defecto
    t = texto.split("-", 1)[-1].strip() if texto[:2].isdigit() else texto.strip()
    t = t.lower()
    t = t[:1].upper() + t[1:]
    # el servicio mete reservas de biosfera, paisajes protegidos y monumentos naturales en un
    # cajon con `00-OTROS`, sin decir cual es cual. Se dice lo que hay, no se inventa el tipo.
    return "Otro espacio protegido" if t == "Otros" else t


def redondea(geom, dec=3, conservar=False):
    """Redondea y quita puntos repetidos: a 3 decimales (~110 m) la forma no cambia."""
    tipo = geom.get("type")
    if tipo == "Point":
        return {"type": tipo, "coordinates": [round(c, dec) for c in geom["coordinates"]]}
    if tipo in ("LineString", "MultiLineString"):
        anillos = [geom["coordinates"]] if tipo == "LineString" else geom["coordinates"]
        limpios = []
        for anillo in anillos:
            pts = []
            for c in anillo:
                p = [round(c[0], dec), round(c[1], dec)]
                if not pts or pts[-1] != p:
                    pts.append(p)
            if len(pts) >= 2:
                limpios.append(pts)
        if not limpios:
            return None
        return {"type": "LineString" if tipo == "LineString" else "MultiLineString",
                "coordinates": limpios[0] if tipo == "LineString" else limpios}
    if tipo in ("Polygon", "MultiPolygon"):
        anillos = [geom["coordinates"]] if tipo == "Polygon" else geom["coordinates"]
        limpios = []
        for poli in anillos:
            nuevos = []
            for anillo in poli:
                pts = []
                for c in anillo:
                    p = [round(c[0], dec), round(c[1], dec)]
                    if not pts or pts[-1] != p:
                        pts.append(p)
                if len(pts) >= 4:
                    if pts[0] != pts[-1]:
                        pts.append(pts[0])
                    nuevos.append(pts)
                elif conservar:
                    # Un monumento natural de 200 m se colapsa al redondear y se perdían 96 de
                    # 302. Se conserva el anillo fino: mejor un polígono de 11 m que una ficha
                    # que no existe en el mapa.
                    fino = []
                    for c in anillo:
                        q = [round(c[0], 6), round(c[1], 6)]
                        if not fino or fino[-1] != q:
                            fino.append(q)
                    if len(fino) >= 3:
                        if fino[0] != fino[-1]:
                            fino.append(fino[0])
                        nuevos.append(fino)
            if nuevos:
                limpios.append(nuevos)
        if not limpios:
            return None
        return {"type": "Polygon" if tipo == "Polygon" else "MultiPolygon",
                "coordinates": limpios[0] if tipo == "Polygon" else limpios}
    return geom


def descarga(servicio, capa, campos, where="1=1", offset=0.002, cat_fija=None, dec=3,
             conservar=False):
    """Trae una capa completa, paginando, con las propiedades normalizadas."""
    total, desplazamiento, feats = None, 0, []
    while True:
        d = pide(servicio, capa, {
            "where": where, "outFields": ",".join(campos), "returnGeometry": "true",
            "outSR": 4326, "f": "geojson", "resultOffset": desplazamiento,
            "resultRecordCount": PAGINA, "maxAllowableOffset": offset,
        })
        if "error" in d:
            raise RuntimeError("%s/%s: %s" % (servicio, capa, d["error"].get("message")))
        lote = d.get("features") or []
        for f in lote:
            geom = f.get("geometry")
            if not geom:
                continue
            geom = redondea(geom, dec, conservar)
            if not geom:
                continue
            a = f.get("properties") or {}
            props = {
                "nombre": (a.get("nombre") or a.get("etiqueta") or "").strip(),
                "categoria": categoria(a.get("desc_tipo_0102"), cat_fija or ""),
            }
            if a.get("superficie_ha") is not None:
                props["superficie_ha"] = round(float(a["superficie_ha"]), 1)
            elif a.get("superficie") is not None:  # geoparques: el campo se llama `superficie`
                props["superficie_ha"] = round(float(a["superficie"]), 1)
            # Provincia / comunidad: el servicio antiguo no las daba y son media ficha del popup.
            for k in ("provincia", "ccaa"):
                # el IGN rellena «Entidad no asociada a ninguna provincia» en las áreas marinas:
                # eso no es un dato, es un hueco
                if a.get(k) and not str(a[k]).startswith("Entidad no asociada"):
                    props[k] = a[k]
            if a.get("longitud_km") is not None:
                props["longitud_km"] = round(float(a["longitud_km"]), 1)
            if a.get("cod_rio"):
                props["cod_rio"] = a["cod_rio"]
            if not props["nombre"] and a.get("id") is not None:
                props["id"] = a["id"]
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
        if total is None:
            total = d.get("properties", {}).get("count")
        desplazamiento += len(lote)
        if len(lote) < PAGINA:
            break
    return feats, total


def escribe(nombre, features, extra, metodo):
    """GeoJSON compacto + su recibo (el validador exige datos/<base>_recibo.json)."""
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = {"type": "FeatureCollection", "generado": ahora, "fuente": FUENTE,
         "licencia": LICENCIA, "features": features}
    json.dump(d, open(os.path.join(DEST, nombre + ".geojson"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    cats = {}
    for f in features:
        c = f["properties"].get("categoria")
        if c:
            cats[c] = cats.get(c, 0) + 1
    rec = {"fichero": "datos/%s.geojson" % nombre, "features": len(features),
           "fuente": FUENTE, "editor": "Instituto Geográfico Nacional (SCNE)",
           "url": "https://signa.ign.es/signa/", "licencia": LICENCIA,
           "descargado": ahora, "metodo": metodo}
    if cats:
        rec["categorias"] = dict(sorted(cats.items(), key=lambda x: -x[1]))
    rec.update({k: v for k, v in extra.items() if v is not None})
    json.dump(rec, open(os.path.join(DEST, nombre + "_recibo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return rec


def main():
    # 1 · Espacios naturales protegidos: tres capas del mismo servicio, una sola capa en el visor
    enp = []
    # cada capa tiene SUS campos: pedir uno que no existe hace que ArcGIS devuelva
    # "Failed to execute query" sin decir cual. El parque nacional usa `nombre`, el resto
    # `etiqueta` (asi los publica el IGN).
    for capa, fija, off, campos in (
            (1, "Parque nacional", 0.001, ["nombre", "superficie_ha"]),
            (2, None, 0.0015, ["etiqueta", "desc_tipo_0102"]),
            (3, None, 0.0015, ["etiqueta", "desc_tipo_0102"])):
        feats, _ = descarga("Espacios_Protegidos", capa, campos,
                            offset=off, cat_fija=fija)
        enp += feats
        print("  esp. protegidos capa %d: %d" % (capa, len(feats)))
    if not enp:
        raise SystemExit("sin espacios protegidos: el servicio no devolvio nada, no se publica")

    # 1b · Cinco figuras que `Espacios_Protegidos` NO publica y `06_espacios_protegidos` sí:
    #      paisajes protegidos, monumentos naturales, reservas naturales, áreas marinas y
    #      geoparques. Medido antes de meterlas (25/11/2026): 632 features y solape por nombre
    #      de solo 5 — paisajes que ya venían como «Otro espacio protegido». Esos NO se
    #      duplican: se reclasifican con su figura. Y todas traen `provincia`, que la ficha no
    #      tenía.
    ya = {(f["properties"].get("nombre") or "").strip().lower(): f for f in enp}
    anadidas, reclasificadas = 0, 0
    # `offset` alto + `dec` bajo = fichero pequeño. La excepción es Monumento natural: son
    # polígonos de dos manzanas y el servicio los devuelve degenerados al simplificar (96 de
    # 302 se perdían). Ahí se pide la geometría entera y se redondea en local conservando el
    # anillo fino.
    for capa, figura, campos, offset, dec, conservar in (
            (5, "Paisaje protegido", ["nombre", "provincia", "superficie_ha"], 0.0015, 3, True),
            (6, "Monumento natural", ["nombre", "provincia", "superficie_ha"], 0, 3, True),
            (7, "Reserva natural", ["nombre", "provincia", "superficie_ha"], 0.0015, 3, True),
            (8, "Área marina protegida", ["nombre", "provincia", "superficie_ha"], 0.0015, 3, True),
            (14, "Geoparque", ["nombre", "ccaa", "superficie"], 0.0015, 3, True)):
        feats, _ = descarga("06_espacios_protegidos", capa, campos, offset=offset, cat_fija=figura,
                            dec=dec, conservar=conservar)
        if figura == "Geoparque":
            # el IGN los nombra por la provincia («Granada»): sin el prefijo la ficha no se entiende
            for f in feats:
                if not f["properties"]["nombre"].lower().startswith("geoparque"):
                    f["properties"]["nombre"] = "Geoparque de " + f["properties"]["nombre"]
        for f in feats:
            clave = (f["properties"].get("nombre") or "").strip().lower()
            previo = ya.get(clave)
            if previo is not None:
                if previo["properties"].get("categoria") == "Otro espacio protegido":
                    previo["properties"]["categoria"] = figura
                    for k in ("provincia", "ccaa"):
                        if f["properties"].get(k):
                            previo["properties"][k] = f["properties"][k]
                    reclasificadas += 1
                continue
            ya[clave] = f
            enp.append(f)
            anadidas += 1
        print("  %-22s capa %2d: %d" % (figura, capa, len(feats)))
    print("  figuras nuevas: %d · reclasificadas: %d" % (anadidas, reclasificadas))

    escribe("espacios_protegidos", enp, {"superficie_ha": round(sum(
        f["properties"].get("superficie_ha") or 0 for f in enp), 0),
        "figuras_nuevas": anadidas, "figuras_reclasificadas": reclasificadas},
        "query f=geojson sobre Espacios_Protegidos/1,2,3 (parques y otros) y sobre "
        "06_espacios_protegidos/5,6,7,8,14 (paisajes, monumentos, reservas, áreas marinas y "
        "geoparques), con maxAllowableOffset y redondeo a 3 decimales")

    # 2 · Red Natura 2000: LIC + ZEPA
    natura = []
    for capa, fija, off in ((5, "LIC", 0.003), (6, "ZEPA", 0.003)):
        feats, _ = descarga("Espacios_Protegidos", capa, ["etiqueta", "desc_tipo_0102"],
                            offset=off, cat_fija=fija)
        # el servicio repite el tipo; manda el nombre de la capa (LIC/ZEPA), que es lo que se busca
        for f in feats:
            f["properties"]["categoria"] = fija
        natura += feats
        print("  red natura capa %d (%s): %d" % (capa, fija, len(feats)))
    if not natura:
        raise SystemExit("sin Red Natura: no se publica")
    escribe("red_natura", natura, {},
            "query f=geojson sobre Espacios_Protegidos/5,6 (LIC y ZEPA)")

    # 3 · Ríos del MTN con nombre y más de 15 km: por debajo son arroyos sin toponimia
    rios, _ = descarga("Hidrografia", 3, ["etiqueta", "cod_rio", "longitud_km"],
                       where="longitud_km>15", offset=0.003)
    rios = [f for f in rios if f["properties"]["nombre"]]
    if not rios:
        raise SystemExit("sin rios: no se publica")
    escribe("rios_mtn", rios, {"longitud_km": round(sum(
        f["properties"].get("longitud_km") or 0 for f in rios), 0)},
        "query f=geojson sobre Hidrografia/3 con where=longitud_km>15")

    # 4 · Presas: el muro, sin nombre ni capacidad (los embalses ya dan nombre y hm3)
    presas, total = descarga("Hidrografia", 0, ["id"], offset=0.002)
    for i, f in enumerate(presas):
        f["properties"]["id"] = i + 1
    if presas:
        escribe("presas", presas, {"total_servicio": total},
                "query f=geojson sobre Hidrografia/0 (solo geometria del muro)")

    print("signa: %d espacios · %d red natura · %d rios · %d presas"
          % (len(enp), len(natura), len(rios), len(presas)))


if __name__ == "__main__":
    main()
