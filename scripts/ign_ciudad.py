# -*- coding: utf-8 -*-
"""Equipamientos de ciudad y servicios del IGN (SignA 05) -> GeoJSON para el visor.

Estas capas son de detalle: a escala nacional son una alfombra de chinchetas, así que nacen con
`zoomMin` de ciudad y el visor las enseña como burbujas contadas hasta que te acercas.

Tres capas del servicio NO se publican porque repetirían algo mejor que ya está en el visor:
  - 17 «Estaciones de servicio»: `carburantes` ya trae 11.311 surtidores con precio.
  - 18 «Punto recarga vehículo eléctrico»: `dgt-electrolineras` tiene 12.144 con potencia.
  - 26 «Instalaciones de hidrocarburos»: son vértices de gasoducto, no instalaciones.

Dedupe por sitio a 30 m: el IGN publica una fila por edificio y un colegio con tres pabellones
llega como tres puntos. En polígonos no hace falta (no hay duplicados) pero sí simplificar: los
recintos vienen con el contorno completo y 11.476 zonas verdes sin tocar pesaban 13 MB.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ign_patrimonio import DATOS, capa, escribe, limpia, una_por_sitio   # noqa: E402
from simplificar import simplificar_anillo                              # noqa: E402

SERVICIO = "Signa/05_servicios_industria"
TOL = 0.00012          # ~13 m: el contorno de una parcela no necesita más a zoom de ciudad
COMUN = {"editor": "Instituto Geográfico Nacional", "licencia": "CC BY 4.0",
         "url": "https://signa.ign.es/", "descargado": "2026-11-25"}

# (id de capa, categoría, color, prioridad). Prioridad baja manda si dos filas caen en el mismo sitio.
GRUPOS = {
    "docencia": [(5, "Universidad", "#a78bfa", 1), (6, "No universitaria", "#60a5fa", 2),
                 (7, "Otros centros docentes", "#94a3b8", 3),
                 (8, "Residencia de estudiantes", "#34d399", 4)],
    "recreo": [(21, "Área recreativa", "#22c55e", 1), (20, "Área de descanso", "#94a3b8", 2)],
    "mineria": [(30, "Mina a cielo abierto", "#a16207", 1), (31, "Mina subterránea", "#57534e", 2)],
    "singulares": [(23, "Centro penitenciario", "#64748b", 1),
                   (24, "Observatorio espacial", "#38bdf8", 2)],
    "comercio": [(46, "Feria y congresos", "#f472b6", 1), (47, "Centro comercial", "#fb923c", 2)],
    "logistica": [(44, "Centro logístico", "#eab308", 1), (45, "Parque científico", "#8b5cf6", 2),
                  (41, "Acuicultura", "#06b6d4", 3)],
}

# Capas simples: (id de capa, tipo fijo, campos extra que trae el IGN)
SIMPLES = {
    "aparcamientos": (19, None, []),
    "cementerios": (22, None, ["bic"]),
    "antenas": (25, None, []),
}


def punto(f, categoria, color, prioridad, tipo_fijo=None, extras=()):
    p = f.get("properties") or {}
    props = {
        "nombre": limpia(p.get("nombre")), "categoria": categoria, "prioridad": prioridad,
        "tipo": tipo_fijo or categoria, "color": color,
        "municipio": limpia(p.get("municipio")), "provincia": limpia(p.get("provincia")),
        "fuente": "IGN · SignA",
    }
    for c in extras:
        props[c] = limpia(p.get(c))
    if "sustancia" in p:
        props["sustancia"] = limpia(p.get("sustancia"))
    f["properties"] = props
    f["geometry"]["coordinates"] = [round(f["geometry"]["coordinates"][0], 5),
                                    round(f["geometry"]["coordinates"][1], 5)]
    return f


def puntos_de(que, tipo_fijo=None, extras=(), radio=30.0):
    """Junta las capas del grupo `que` en una sola, con el tipo como atributo y dedupe por sitio."""
    crudos, vistos = [], set()
    for lid, categoria, color, prioridad in GRUPOS[que]:
        for f in capa(SERVICIO, lid):
            if (f.get("geometry") or {}).get("type") != "Point":
                continue
            p = f.get("properties") or {}
            k = (categoria, limpia(p.get("nombre")),
                 round(f["geometry"]["coordinates"][0], 4), round(f["geometry"]["coordinates"][1], 4))
            if k in vistos:                    # misma fila repetida en el volcado
                continue
            vistos.add(k)
            crudos.append(punto(f, categoria, color, prioridad, tipo_fijo, extras))
        print("  %-26s %6d" % (categoria, sum(1 for x in crudos
                                              if x["properties"]["categoria"] == categoria)), flush=True)
    return una_por_sitio(crudos, radio)


def simple_de(que, color, radio=30.0):
    lid, tipo_fijo, extras = SIMPLES[que]
    crudos, vistos = [], set()
    for f in capa(SERVICIO, lid):
        if (f.get("geometry") or {}).get("type") != "Point":
            continue
        p = f.get("properties") or {}
        k = (limpia(p.get("nombre")), round(f["geometry"]["coordinates"][0], 4),
             round(f["geometry"]["coordinates"][1], 4))
        if k in vistos:
            continue
        vistos.add(k)
        crudos.append(punto(f, que, color, 1, tipo_fijo, extras))
    return una_por_sitio(crudos, radio)


def poligonos_de(lid, tipo_fijo, tol=TOL):
    """Recintos (zonas verdes, deportivas, ferias…): contorno simplificado y superficie."""
    feats, vertices, simple_vertices = [], 0, 0
    for f in capa(SERVICIO, lid):
        g = f.get("geometry") or {}
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        p = f.get("properties") or {}
        # Un MultiPolygon son varios recintos y cada uno puede tener huecos: se simplifica anillo a
        # anillo y se reconstruye la MISMA estructura (aplanarla convertiría los huecos en recintos).
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        nuevos = []
        for poly in polys:
            anillos = []
            for anillo in poly:
                vertices += len(anillo)
                r = simplificar_anillo([(round(x, 5), round(y, 5)) for x, y in anillo], tol)
                simple_vertices += len(r)
                anillos.append(r)
            nuevos.append(anillos)
        g["coordinates"] = nuevos[0] if g["type"] == "Polygon" else nuevos
        f["properties"] = {"nombre": limpia(p.get("nombre")), "tipo": tipo_fijo,
                           "superficie_m2": p.get("superficie_m2"), "fuente": "IGN · SignA"}
        feats.append(f)
    print("  vértices %d -> %d (-%d%%)" % (vertices, simple_vertices,
                                          round(100 - 100.0 * simple_vertices / max(1, vertices))), flush=True)
    return feats


def main():
    if not os.path.isdir(DATOS):
        sys.exit("no encuentro datos/")
    # Con `python3 ign_ciudad.py ciudad_antenas.geojson` se regenera solo esa capa: útil cuando el
    # IGN corta a mitad y no quieres volver a bajar las otras trece.
    solo = set(sys.argv[1:])

    # (fichero, qué lo genera, metadatos). El orden es el de descarga: puntos grandes primero.
    TABLA = [
        ("ciudad_aparcamientos.geojson", lambda: simple_de("aparcamientos", "#60a5fa"), {
            "titulo": "Aparcamientos (IGN)",
            "metodo": "Capa 19 de 05_servicios_industria, una chincheta por recinto a 30 m"}),
        ("ciudad_cementerios.geojson", lambda: simple_de("cementerios", "#a3a3a3"), {
            "titulo": "Cementerios (IGN)",
            "metodo": "Capa 22 de 05_servicios_industria, dedupe a 30 m"}),
        ("ciudad_recreo.geojson", lambda: puntos_de("recreo"), {
            "titulo": "Áreas recreativas y de descanso (IGN)",
            "metodo": "Capas 20 y 21 de 05_servicios_industria, con el tipo como atributo"}),
        ("ciudad_docencia.geojson", lambda: puntos_de("docencia"), {
            "titulo": "Docencia · universidades y centros (IGN)",
            "metodo": "Capas 5-8 de 05_servicios_industria, con el tipo como atributo y dedupe a 30 m"}),
        ("ciudad_antenas.geojson", lambda: simple_de("antenas", "#94a3b8", radio=25.0), {
            "titulo": "Antenas de telecomunicaciones (IGN)",
            "metodo": "Capa 25 de 05_servicios_industria; el IGN no publica nombre ni operador, "
                      "varias filas por mástil fundidas a 25 m"}),
        ("ciudad_mineria.geojson", lambda: puntos_de("mineria"), {
            "titulo": "Explotaciones mineras (IGN)",
            "metodo": "Capas 30 y 31 de 05_servicios_industria, con tipo y sustancia"}),
        ("ciudad_singulares.geojson", lambda: puntos_de("singulares"), {
            "titulo": "Centros penitenciarios y observatorios (IGN)",
            "metodo": "Capas 23 y 24 de 05_servicios_industria"}),
        ("ciudad_logistica.geojson", lambda: poligonos_de(44, "Centro logístico"), {
            "titulo": "Centros logísticos (IGN)",
            "metodo": "Capa 44 de 05_servicios_industria, contorno simplificado a ~13 m"}),
        ("ciudad_ciencia.geojson", lambda: poligonos_de(45, "Parque científico"), {
            "titulo": "Parques científicos y tecnológicos (IGN)",
            "metodo": "Capa 45 de 05_servicios_industria, contorno simplificado a ~13 m"}),
        ("ciudad_acuicultura.geojson", lambda: poligonos_de(41, "Acuicultura"), {
            "titulo": "Instalaciones de acuicultura (IGN)",
            "metodo": "Capa 41 de 05_servicios_industria, contorno simplificado a ~13 m"}),
        ("ciudad_comercio.geojson", lambda: poligonos_de(47, "Centro comercial"), {
            "titulo": "Centros comerciales (IGN)",
            "metodo": "Capa 47 de 05_servicios_industria, contorno simplificado a ~13 m"}),
        ("ciudad_ferias.geojson", lambda: poligonos_de(46, "Feria y congresos"), {
            "titulo": "Recintos de ferias y congresos (IGN)",
            "metodo": "Capa 46 de 05_servicios_industria, contorno simplificado a ~13 m"}),
        ("ciudad_zonas-verdes.geojson", lambda: poligonos_de(48, "Zona verde"), {
            "titulo": "Zonas verdes (IGN)",
            "metodo": "Capa 48 de 05_servicios_industria, contorno simplificado a ~13 m"}),
        ("ciudad_deportivas.geojson", lambda: poligonos_de(50, "Instalación deportiva"), {
            "titulo": "Instalaciones deportivas (IGN)",
            "metodo": "Capa 50 de 05_servicios_industria, contorno simplificado a ~13 m"}),
    ]
    for nombre, genera, meta in TABLA:
        if solo and nombre not in solo:
            continue
        escribe(nombre, genera(), dict(COMUN, fuente="IGN · SignA", **meta))


if __name__ == "__main__":
    main()
