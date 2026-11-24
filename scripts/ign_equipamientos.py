# -*- coding: utf-8 -*-
"""Equipamientos del IGN (SignA 03_construcciones_otros): dónde dormir y qué visitar.

Dos capas, no ocho. El visor ya tiene 77 capas y una más por tipo de equipamiento sería ruido:
se agrupan por uso —alojamiento y ocio— y el tipo va como atributo con su color.

Fuera a propósito: instalaciones deportivas (16.411 puntos de piscina y pista municipal, ruido a
escala nacional) y los edificios religiosos, que se quedan como atributo del patrimonio para no
poner dos chinchetas en la misma iglesia.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
BASE = "https://serviciosgis.ign.es/servicios/rest/services/Signa/03_construcciones_otros/MapServer"
UA = {"User-Agent": "OpenInfraES/1.0 (visor de infraestructura)"}
HOY = "2026-11-24"

# (id de capa del IGN, etiqueta, color) por bloque
ALOJAMIENTO = [(15, "Camping", "#22c55e"), (16, "Albergue", "#38bdf8"),
               (25, "Área de autocaravanas", "#a78bfa"), (24, "Acampada libre", "#84cc16"),
               (17, "Balneario", "#2dd4bf")]
OCIO = [(20, "Parque temático", "#f472b6"), (18, "Circuito de velocidad", "#fb923c"),
        (14, "Estación invernal", "#93c5fd")]

COMUN = {"editor": "Instituto Geográfico Nacional", "licencia": "CC BY 4.0",
         "url": "https://signa.ign.es/"}


def pide(url, timeout=180):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                             timeout=timeout).read())


def capa(lid, tam=120):
    """El REST del IGN no pagina con resultOffset (500 desde el segundo bloque): OBJECTID IN (...)."""
    q = urllib.parse.urlencode({"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    d = pide("%s/%d/query?%s" % (BASE, lid, q))
    ids = d.get("objectIds") or []
    campo = d.get("objectIdFieldName") or "OBJECTID"
    salida = []
    for i in range(0, len(ids), tam):
        trozo = ids[i:i + tam]
        q = urllib.parse.urlencode({"where": "%s IN (%s)" % (campo, ",".join(map(str, trozo))),
                                    "outFields": "*", "outSR": "4326", "f": "geojson"})
        for intento in range(3):
            try:
                salida.extend(pide("%s/%d/query?%s" % (BASE, lid, q)).get("features") or [])
                break
            except urllib.error.HTTPError:
                if intento == 2:
                    raise
    return salida


def limpia(v):
    if v is None:
        return None
    v = str(v).strip()
    return None if not v or v.lower() in ("desconocido", "no procede") else v


def junta(bloques):
    feats = []
    for lid, tipo, color in bloques:
        for f in capa(lid):
            p = f.get("properties") or {}
            lon, lat = f["geometry"]["coordinates"][:2]
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point",
                                       "coordinates": [round(lon, 5), round(lat, 5)]},
                          "properties": {"nombre": limpia(p.get("nombre")), "tipo": tipo,
                                         "municipio": limpia(p.get("municipio")),
                                         "provincia": limpia(p.get("provincia")),
                                         "color": color, "fuente": "IGN · SignA"}})
    return feats


def escribe(nombre, feats, meta):
    ruta = os.path.join(DATOS, nombre)
    json.dump({"type": "FeatureCollection", "features": feats}, open(ruta, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    rec = dict(meta)
    rec.update({"features": len(feats), "kb": round(os.path.getsize(ruta) / 1024, 1),
                "descargado": HOY})
    json.dump(rec, open(os.path.join(DATOS, nombre.replace(".geojson", "_recibo.json")), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%-28s %5d  %7.1f KB" % (nombre, len(feats), os.path.getsize(ruta) / 1024), flush=True)


def main():
    pedido = {a.lower() for a in sys.argv[1:]} or {"todo"}
    if pedido & {"todo", "alojamiento"}:
        escribe("alojamiento_ign.geojson", junta(ALOJAMIENTO), dict(COMUN, **{
            "titulo": "Alojamiento (campings, albergues, autocaravanas)",
            "fuente": "IGN · SignA",
            "metodo": "Capas 15, 16, 24, 25 y 17 de 03_construcciones_otros; "
                      "una capa con el tipo como atributo"}))
    if pedido & {"todo", "ocio"}:
        escribe("ocio_ign.geojson", junta(OCIO), dict(COMUN, **{
            "titulo": "Ocio y nieve (parques temáticos, circuitos, estaciones invernales)",
            "fuente": "IGN · SignA",
            "metodo": "Capas 20, 18 y 14 de 03_construcciones_otros"}))


if __name__ == "__main__":
    main()
