# -*- coding: utf-8 -*-
"""Genera datos/fuentes.json: la procedencia de cada capa del visor.

Todo sale de los recibos reales (no se escribe a mano): capas oficiales, visor Hermes, OSM agua,
Overpass y el recibo de simplificacion. El visor pinta esta tabla en el panel 'Fuentes'.
"""
import datetime
import json
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")


def etiquetas_del_visor():
    """id -> label de CAPAS en index.html. El título de la ficha sale del mismo sitio que la
    leyenda: si la capa no declara su título en el recibo, no se inventa otro."""
    html = open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read()
    ini = html.index("const CAPAS = [")
    fin = html.index("];", ini)
    bloque = html[ini:fin]
    salida = {}
    for m in re.finditer(r'id:"([a-z0-9\-_]+)"', bloque):
        et = re.search(r'label:"([^"]+)"', bloque[m.end():m.end() + 400])
        if et:
            salida[m.group(1)] = et.group(1)
    return salida


ETIQUETAS = etiquetas_del_visor()
HOY = datetime.date.today().isoformat()

# cada capa, a su organismo oficial. Sin agregadores.
OFICIAL = {
    "parques-eolicos": ("MITECO", "https://www.miteco.gob.es", "Registro de instalaciones de producción"),
    "plantas-solares": ("MITECO", "https://www.miteco.gob.es", "Registro de instalaciones de producción"),
    "gas-regasificacion": ("Enagás", "https://www.enagas.es", "Plantas de regasificación declaradas"),
    "gas-almacenamiento": ("Enagás", "https://www.enagas.es", "Almacenamientos subterráneos"),
    "gas-interconexiones": ("Enagás", "https://www.enagas.es", "Interconexiones internacionales"),
    "refinerias": ("CORES", "https://www.cores.es", "Refinerías del sistema petrolífero"),
    "almacenamiento-petrolifero": ("CORES", "https://www.cores.es", "Almacenamiento de productos petrolíferos"),
    "nuclear": ("CSN", "https://www.csn.es", "Centrales y reactores autorizados"),
    "residuos-radiactivos": ("ENRESA", "https://www.enresa.es", "Instalaciones de gestión de residuos"),
    "electricidad-interconexiones": ("REE", "https://www.ree.es", "Interconexiones del sistema eléctrico"),
    "red-electrica": ("IGN", "https://www.ign.es", "BTN Continua: subestaciones (recintos) y tendido 220/400 kV"),
    "conducciones-combustible": ("Enagás", "https://www.enagas.es", "Conducciones de gas"),
    "generacion-electrica-provincia": ("REE", "https://www.ree.es", "Reparto provincial de generación"),
    "hidrogeno-produccion": ("MITECO", "https://www.miteco.gob.es", "Proyectos de Interés Común (PCI)"),
    "agua-embalsada": ("MITECO", "https://www.miteco.gob.es", "Boletín Hidrológico, parte semanal"),
    "desaladoras": ("MITECO", "https://www.miteco.gob.es", "Instalaciones de desalación"),
    "hidrogeno-red": ("MITECO", "https://www.miteco.gob.es", "Red de hidrógeno (PCI)"),
    "irewater-edar": ("I-ReWater HUB (Interreg)", "https://i-rewater-hub.com",
                      "vector tiles MVT del catálogo abierto, deduplicado"),
    "estaciones-cercanias": ("NAP · MITMA", "https://nap.transportes.gob.es",
                             "GTFS de Renfe Cercanías, paradas"),
    "plantas": ("REE · Registro administrativo de instalaciones de producción",
                "https://www.ree.es", "registro RAIPEE cruzado con ELECTRA"),
}

HERMES = {
    "nombre": "Visor Hermes — MITMA",
    "editor": "Ministerio de Transportes (ArcGIS REST)",
    "licencia": "CC-BY-4.0 (scne.es)",
    "url": "https://mapas.fomento.gob.es/VisorHermes/",
    "metodo": "query ArcGIS REST, paginado de 500 en 500",
}

OSM = {
    "nombre": "OpenStreetMap",
    "editor": "colaboradores de OSM",
    "licencia": "ODbL 1.0",
    "url": "https://www.openstreetmap.org",
    "metodo": "Overpass API (man_made=*)",
}
OSM_RED = {
    "nombre": "OpenStreetMap (red)",
    "editor": "colaboradores de OSM",
    "licencia": "ODbL 1.0",
    "url": "https://www.openstreetmap.org",
    "metodo": "Overpass API (power=line, pipeline, plant)",
}
def leer(rel, defecto=None):
    ruta = os.path.join(DATOS, rel)
    if not os.path.exists(ruta):
        return defecto
    try:
        return json.load(open(ruta, encoding="utf-8"))
    except Exception:
        return defecto


# el id del visor no siempre es el id del origen
ALIAS_HERMES = {
    "puertos": "puertos-interes-general",
    "terminales-puerto": "terminales-portuarias",
    "terminales-aero": "terminales-aeropuerto",
    "intermodales": "terminales-mercancias",
    "carreteras": "carreteras",
    "estaciones-gas": "estaciones-gas",
}

# capas del visor que son subconjuntos de un fichero de plantas
DERIVADAS = {
    "gasgen": ("Ciclos combinados", "plantas.geojson", "technology_normalized in (ccgt, fuel_gas)"),
    "resto": ("Resto del parque", "plantas.geojson", "resto de tecnologias"),
}

ALIAS = {
    "subestaciones": "red-electrica",
    "eolicos": "parques-eolicos",
    "solares": "plantas-solares",
    "residuos": "residuos-radiactivos",
    "petrolifero": "almacenamiento-petrolifero",
    "h2red": "hidrogeno-red",
    "interelec": "electricidad-interconexiones",
    "nuclear": "nuclear",
    "regas": "gas-regasificacion",
    "gasalm": "gas-almacenamiento",
    "refinerias": "refinerias",
    "embalses": "agua-embalsada",
    "desaladoras": "desaladoras",
    "h2": "hidrogeno-produccion",
}


def main():
    fuentes = {}
    oficial = leer("oficial/_recibo_oficial.json", {})
    for c in oficial.get("capas", []):
        org, url, metodo = OFICIAL.get(c["id"], ("sin declarar", "", ""))
        fuentes[c["id"]] = {
            "capa": c["id"], "titulo": c.get("titulo"),
            "fuente": org, "editor": org,
            "licencia": c.get("licencia"),
            "actualizado": c.get("verificado_a"),
            "descargado": HOY,
            "features": c.get("features"),
            "url": url,
            "metodo": metodo,
        }

    hermes = leer("hermes/_recibo_hermes.json", {})
    for c in hermes.get("capas", []):
        fuentes[c["id"]] = {
            "capa": c["id"], "titulo": c.get("descripcion"),
            "fuente": HERMES["nombre"], "editor": HERMES["editor"],
            "licencia": hermes.get("licencia", HERMES["licencia"]),
            "actualizado": None, "descargado": HOY,
            "features": c.get("features"),
            "url": HERMES["url"],
            "metodo": "%s/%d — %s" % (c.get("servicio"), c.get("layer", 0), HERMES["metodo"]),
        }

    # I-ReWater: un recibo por capa descargada
    TITULOS_IRW = {"hib_edar": "EDAR · agua regenerable",
                   "hib_uda": "Unidades de Demanda Agrícola",
                   "hib_regadio": "Perímetros de regadío",
                   "hib_regadio_particion": "Particiones de regadío (25 h)",
                   "hib_demarcacion": "Demarcaciones hidrográficas (I-ReWater)",
                   "hib_nuts2": "Población por comunidad + agua aprovechable (NUTS2)",
                   "hib_nuts3": "Población por provincia + agua aprovechable (NUTS3)"}
    for fich in sorted(os.listdir(DATOS)):
        if not (fich.startswith("irewater_") and fich.endswith("_recibo.json")):
            continue
        r = leer(fich, {})
        if not r.get("capa") or not r.get("features"):
            continue
        cid = "irewater-" + r["capa"].replace("hib_", "").replace("_", "-")
        fuentes[cid] = {
            "capa": cid,
            "titulo": TITULOS_IRW.get(r["capa"], r["capa"]),
            "fuente": ("I-ReWater HUB (Interreg) + INE"
                       if r["capa"].startswith("hib_nuts")
                       else "I-ReWater HUB (Interreg)"),
            "editor": "I-ReWater HUB (Interreg) + INE" if r["capa"].startswith("hib_nuts") else "I-ReWater HUB (Interreg)",
            "licencia": "CC BY 4.0",
            "actualizado": r.get("descargado", "")[:10],
            "descargado": HOY,
            "features": r.get("features"),
            "url": "https://i-rewater-hub.com",
            "metodo": ("vector tiles MVT z%d + padrón del INE (tabla 2852/2853)"
                       % r.get("zoom", 8) if r["capa"].startswith("hib_nuts")
                       else "vector tiles MVT z%d, deduplicado por id" % r.get("zoom", 8)),
        }

    osm_agua = leer("osm_agua_recibo.json", {})
    for capa, r in osm_agua.items():
        fuentes[capa] = {
            "capa": capa, "titulo": {"edar": "EDAR (depuradoras)",
                                     "etap": "ETAP (potabilizadoras)",
                                     "agua-conducciones": "Conducciones de agua"}.get(capa, capa),
            "fuente": OSM["nombre"], "editor": OSM["editor"],
            "licencia": OSM["licencia"],
            "actualizado": (r.get("refrescado_en") or HOY)[:10],
            "descargado": (r.get("refrescado_en") or HOY)[:10],
            "features": r.get("features"),
            "url": OSM["url"],
            "metodo": "%s · %d con nombre" % (OSM["metodo"], r.get("con_nombre", 0)),
        }
        if r.get("estado"):
            fuentes[capa]["estado"] = r["estado"]


    # el recibo de Hermes puede no tener una capa descargada aparte: se completa contando el fichero
    carpeta = os.path.join(DATOS, "hermes")
    if os.path.isdir(carpeta):
        for fich in os.listdir(carpeta):
            if not fich.endswith(".geojson"):
                continue
            cid = fich[:-8]
            if cid in fuentes:
                continue
            try:
                n = len(json.load(open(os.path.join(carpeta, fich), encoding="utf-8"))["features"])
            except Exception:
                n = None
            fuentes[cid] = {"capa": cid, "titulo": cid.replace("-", " ").capitalize(),
                            "fuente": HERMES["nombre"], "editor": HERMES["editor"],
                            "licencia": HERMES["licencia"], "actualizado": None,
                            "descargado": HOY, "features": n, "url": HERMES["url"],
                            "metodo": HERMES["metodo"]}

    for capa, origen in ALIAS_HERMES.items():
        base = fuentes.get(origen)
        if base:
            f = dict(base); f["capa"] = capa
            fuentes[capa] = f

    # capa de plantas: un solo fichero con todas, potencia y tecnologia
    ruta_pl = os.path.join(DATOS, "plantas.geojson")
    if os.path.exists(ruta_pl):
        try:
            n_pl = len(json.load(open(ruta_pl, encoding="utf-8"))["features"])
        except Exception:
            n_pl = None
        org, url, metodo = OFICIAL.get("plantas",
            ("REE · Registro administrativo de instalaciones de producción",
             "https://www.ree.es", "registro RAIPEE cruzado con ELECTRA"))
        fuentes["plantas"] = {
            "capa": "plantas", "titulo": "Todas las plantas (con potencia)",
            "fuente": org, "editor": org, "licencia": "condiciones del editor",
            "actualizado": None, "descargado": HOY, "features": n_pl,
            "url": url, "metodo": metodo,
        }

    # paradas de Cercanias del NAP
    ruta_ec = os.path.join(DATOS, "estaciones-cercanias.geojson")
    if os.path.exists(ruta_ec):
        try:
            n_ec = len(json.load(open(ruta_ec, encoding="utf-8"))["features"])
        except Exception:
            n_ec = None
        fuentes["estaciones-cercanias"] = {
            "capa": "estaciones-cercanias", "titulo": "Estaciones de Cercanías",
            "fuente": "NAP · MITMA", "editor": "Ministerio de Transportes (NAP)",
            "licencia": "Ley 37/2007 · reutilización", "actualizado": HOY, "descargado": HOY,
            "features": n_ec, "url": "https://nap.transportes.gob.es",
            "metodo": "GTFS de Renfe Cercanías, tabla stops.txt",
        }

    # capas demograficas: geometria de Eurostat GISCO + datos del INE
    DEMO = {
        "ine-provincias": ("Población por provincia", "poblacion"),
        "ine-ccaa": ("Población por comunidad", "poblacion"),
        "ine-densidad": ("Densidad de población", "densidad"),
        "ine-paro": ("Tasa de paro (EPA)", "paro_pct"),
    }
    for cid, (titulo, campo) in DEMO.items():
        base = "nuts3_es.geojson" if "provincia" in cid or "densidad" in cid else "nuts2_es.geojson"
        ruta = os.path.join(DATOS, base)
        n = None
        if os.path.exists(ruta):
            try:
                n = len(json.load(open(ruta, encoding="utf-8"))["features"])
            except Exception:
                pass
        fuentes[cid] = {
            "capa": cid, "titulo": titulo,
            "fuente": "INE · Eurostat GISCO",
            "editor": "INE (padrón y EPA) + Eurostat (geometrías NUTS 2021)",
            "licencia": "datos abiertos INE · Eurostat CC BY 4.0",
            "actualizado": HOY, "descargado": HOY, "features": n,
            "url": "https://www.ine.es/jaxiT3/Tabla.htm?t=2852" if campo == "poblacion"
                   else "https://www.ine.es/jaxiT3/Tabla.htm?t=14506",
            "metodo": ("padrón del INE cruzado por cod_ine con polígonos NUTS de Eurostat"
                       if campo != "densidad" else "población / superficie del polígono"),
        }

    # capas que salen de ficheros propios generados con Overpass/REE
    propios = {
        "l400": ("Líneas 400 kV", OSM_RED, None),
        "l220": ("Líneas 220 kV", OSM_RED, None),
        "gasoductos": ("Gasoductos", OSM_RED, None),
        "hidro": ("Centrales hidráulicas", OSM_RED, None),
    }
    for capa, (titulo, src, act) in propios.items():
        fuentes[capa] = {
            "capa": capa, "titulo": titulo, "fuente": src["nombre"], "editor": src["editor"],
            "licencia": src["licencia"], "actualizado": act, "descargado": HOY,
            "features": None, "url": src["url"], "metodo": src["metodo"],
        }
    for capa, origen in ALIAS.items():
        base = fuentes.get(origen)
        if base:
            f = dict(base)
            f["capa"] = capa
            fuentes[capa] = f
        else:
            org, url, metodo = OFICIAL.get(origen, ("sin declarar", "", ""))
            fuentes[capa] = {"capa": capa, "titulo": capa, "fuente": org,
                             "editor": org, "licencia": "CC BY 4.0",
                             "actualizado": None, "descargado": HOY,
                             "features": None, "url": url, "metodo": metodo}

    for capa, (titulo, fich, filtro) in DERIVADAS.items():
        fuentes[capa] = {
            "capa": capa, "titulo": titulo, "fuente": OSM_RED["nombre"],
            "editor": OSM_RED["editor"], "licencia": OSM_RED["licencia"],
            "actualizado": None, "descargado": HOY, "features": None,
            "url": OSM_RED["url"], "metodo": "%s · subconjunto: %s" % (OSM_RED["metodo"], filtro),
        }

    # trasvases y canales comparten fichero pero no significado: misma fuente, distinto filtro.
    # Las cifras del trasvase salen de su RECIBO y del fichero que pinta la capa, no de la memoria:
    # aqui decia "118 tramos unidos en 26 trazos" cuando el recibo mide 106 tramos y 11 trazos.
    r_agua = osm_agua.get("agua-conducciones")
    import re as _re
    n_tras, n_can = None, None
    ruta_agua = os.path.join(DATOS, "agua-conducciones.geojson")
    if os.path.exists(ruta_agua):
        _f = json.load(open(ruta_agua, encoding="utf-8"))["features"]
        n_tras = sum(1 for x in _f if _re.search(r"trasvase|postrasvase",
                                                 (x.get("properties") or {}).get("name") or "", _re.I))
        n_can = len(_f) - n_tras

    rec_tras = leer("trasvases_recibo.json", {})
    lista_tras = rec_tras.get("trasvases") or []
    tramos_tras = sum(t.get("tramos") or 0 for t in lista_tras)
    trazos_tras = sum(t.get("trazos") or 0 for t in lista_tras)
    ruta_union = os.path.join(DATOS, "simplificado", "trasvases-union.geojson")
    feat_tras = trazos_tras
    if os.path.exists(ruta_union):
        feat_tras = len(json.load(open(ruta_union, encoding="utf-8"))["features"])
    metodo_tras = ("%d tramos unidos en %d trazos de %d trasvases "
                   "(scripts/unir_trasvases_v2.py, tolerancia %s m)"
                   % (tramos_tras, trazos_tras, len(lista_tras), rec_tras.get("tolerancia_m", "?")))

    if r_agua:
        for capa, titulo, filtro, nfeat in (
            ("trasvases", "Trasvases", metodo_tras, feat_tras),
            ("canales", "Canales y acequias", "resto: canales de riego, acequias y aducciones", n_can),
        ):
            fuentes[capa] = {
                "capa": capa, "titulo": titulo, "fuente": OSM["nombre"], "editor": OSM["editor"],
                "licencia": OSM["licencia"], "actualizado": HOY, "descargado": HOY,
                "features": nfeat, "url": OSM["url"],
                "metodo": "%s · %s" % (OSM["metodo"], filtro),
            }

    # ríos: geometria OSM, caudal por API en vivo
    rr = leer("rios_recibo.json", {})
    if rr:
        fuentes["rios"] = {
            "capa": "rios", "titulo": "Ríos (caudal en vivo)",
            "fuente": OSM["nombre"], "editor": OSM["editor"], "licencia": OSM["licencia"],
            "actualizado": None, "descargado": HOY, "features": rr.get("features"),
            "url": OSM["url"],
            "metodo": "%s · %d tramos agrupados, mínimo %s km; caudal por Open-Meteo Flood (GloFAS)"
                      % (OSM["metodo"], rr.get("tramos_osm", 0), rr.get("min_km", "")),
        }

    # carburantes y sismos: recibo propio de cada script
    import os as _os
    for capa, fich, fuente, editor, lic, url, met in (
        ("carburantes", "carburantes_recibo.json", "MITECO", "Secretaría de Estado de Energía",
         "Reutilización con atribución (Ley 37/2007)",
         "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/",
         "GET al JSON de estaciones terrestres; coma decimal"),
        ("demarcaciones", "demarcaciones_recibo.json", "MITECO", "MITECO · SIG",
         "Reutilización con atribución (Ley 37/2007)",
         "https://sig.miteco.gob.es/arcgis/rest/services/25830/aguaHidroDemarcaciones",
         "query ArcGIS REST, maxAllowableOffset 0.0005"),
        ("sismos", "sismos_recibo.json", "EMSC-CSEM", "seismicportal.eu",
         "abierta con atribución", "https://www.seismicportal.eu/fdsnws/event/1/query",
         "FDSN query con bbox de Espana"),
    ):
        r = leer(fich, {})
        if r:
            fuentes[capa] = {"capa": capa, "titulo": capa.capitalize(), "fuente": fuente,
                             "editor": editor, "licencia": lic,
                             "actualizado": r.get("fecha_dato") or r.get("desde"),
                             "descargado": HOY, "features": r.get("features"),
                             "url": url, "metodo": met}


    # fuentes nuevas: aeródromos (OurAirports) y alertas de desastre (GDACS)
    for capa, fich, titulo, fuente, editor, lic, url, met in (
        ("aeropuertos", "aeropuertos_recibo.json", "Aeródromos y helipuertos",
         "OurAirports", "OurAirports (dominio público)", "Dominio público",
         "https://ourairports.com/data/",
         "CSV global de aeródromos, filtro iso_country=ES; los cerrados se descartan"),
        ("alertas-gdacs", "alertas-gdacs_recibo.json", "Alertas de desastre (120 días)",
         "GDACS — Comisión Europea (JRC)", "GDACS (JRC)", "abierta con atribución",
         "https://www.gdacs.org/xml/rss.xml",
         "RSS público acumulativo, bbox de España, ventana de 120 días"),
    ):
        r = leer(fich, {})
        if r:
            fuentes[capa] = {"capa": capa, "titulo": titulo, "fuente": fuente,
                             "editor": editor, "licencia": lic,
                             "actualizado": r.get("fecha_dato") or r.get("desde"),
                             "descargado": HOY, "features": r.get("features"),
                             "url": url, "metodo": met}

    # --- MITECO · OGC API Features: aforos, canales y calidad del aire ---
    # Una sola via para las tres colecciones; el recibo de cada una declara la coleccion exacta,
    # el numberMatched de la fuente y cuantos objetos se guardaron.
    for capa, fich, titulo, met in (
        ("aforos", "aforos_recibo.json", "Estaciones de aforo (SAIH-ROEA)",
         "OGC API Features, coleccion agua:Estaciones_Aforos"),
        ("canales-miteco", "canales-miteco_recibo.json", "Red de canales principales",
         "OGC API Features, coleccion agua:canales, simplificado a ~22 m"),
        ("calidad-aire-estaciones", "calidad-aire-estaciones_recibo.json",
         "Estaciones de calidad del aire",
         "OGC API Features, coleccion evaluacionambiental:ca_red_estaciones"),
        ("masas-subterraneas", "masas-subterraneas_recibo.json",
         "Masas de agua subterránea (estado)",
         "OGC API Features, coleccion agua:estado_masas_aguasub_2027_global, simplificado a ~220 m"),
        ("dpmt", "dpmt_recibo.json", "Dominio público marítimo-terrestre",
         "OGC API Features, coleccion costas:dominio_publico_maritimo_terrestre, simplificado a ~22 m"),
    ):
        r = leer(fich, {})
        if r:
            fuentes[capa] = {
                "capa": capa, "titulo": titulo,
                "fuente": "MITECO", "editor": "MITECO · OGC API Features (GeoServer)",
                "licencia": "Reutilización Ley 37/2007 con atribución",
                "actualizado": None, "descargado": (r.get("descargado") or HOY)[:10],
                "features": r.get("features"),
                "url": r.get("url"), "metodo": met,
            }

    # --- IGN · SignA (SCNE): espacios protegidos, Red Natura, rios del MTN y presas ---
    # Leen su propio recibo: la fuente, la licencia y la fecha vienen del fichero, no se escriben
    # aqui (si manana cambia la capa, el recibo manda).
    for capa, fich, titulo, met in (
        ("espacios-protegidos", "espacios_protegidos_recibo.json",
         "Espacios naturales protegidos (IGN)",
         "query ArcGIS REST f=geojson, parques nacionales/naturales/otros, simplificado a ~110 m"),
        ("red-natura", "red_natura_recibo.json", "Red Natura 2000 (LIC y ZEPA)",
         "query ArcGIS REST f=geojson sobre Espacios_Protegidos/5 y /6"),
        ("rios-mtn", "rios_mtn_recibo.json", "Ríos del MTN (IGN)",
         "query ArcGIS REST f=geojson sobre Hidrografia/3, tramos de más de 15 km"),
        ("presas", "presas_recibo.json", "Presas (IGN)",
         "query ArcGIS REST f=geojson sobre Hidrografia/0 (solo el muro)"),
    ):
        r = leer(fich, {})
        if r:
            fuentes[capa] = {
                "capa": capa, "titulo": titulo,
                "fuente": r.get("fuente") or "IGN",
                "editor": "IGN · SignA (SCNE), servicios GIS",
                "licencia": r.get("licencia"),
                "actualizado": r.get("descargado"),
                "descargado": (r.get("descargado") or HOY)[:10],
                "features": r.get("features"),
                "url": r.get("url"), "metodo": met,
            }

    # --- NAP: paradas de GTFS (Metro, Cercanías, AVE) ---
    for capa, etq, titulo in (
        ("nap-metro", "metro-madrid", "Metro de Madrid (NAP)"),
        ("nap-cercanias", "cercanias-renfe", "Cercanías Renfe (NAP)"),
        ("nap-ave", "renfe-ave", "Renfe AVE y largo recorrido (NAP)"),
        ("nap-lineas-metro", "lineas_metro-madrid", "Líneas de Metro Madrid"),
        ("nap-lineas-cercanias", "lineas_cercanias-renfe", "Líneas de Cercanías"),
    ):
        r = leer("nap_%s_recibo.json" % etq, {})
        if r:
            fuentes[capa] = {
                "capa": capa, "titulo": titulo,
                "fuente": "NAP · MITMA", "editor": "NAP · MITMA",
                "licencia": "Reutilización con atribución (Ley 37/2007)",
                "actualizado": r.get("descargado") or None,
                "descargado": HOY,
                "features": r.get("paradas") or r.get("features"),
                "url": "https://nap.transportes.gob.es/api",
                "metodo": "GTFS-ZIP del NAP; cabecera `ApiKey`",
            }


    # --- Adif: red ferroviaria fisica (no es NAP: es el gestor de infraestructura) ---
    r = leer("adif_tramos_recibo.json", {})
    if r:
        fuentes["adif-tramos"] = {
            "capa": "adif-tramos", "titulo": "Red ferroviaria (Adif)",
            "fuente": "Adif", "editor": "Adif · IDEADIF",
            "licencia": "CC BY 4.0",
            "actualizado": r.get("descargado"), "descargado": HOY,
            "features": r.get("features"),
            "url": "https://ideadif.adif.es",
            "metodo": ("Trazado oficial de tramos (1.178 tramos, 604.913 vertices). El WFS de "
                       "IDEADIF responde 403 (Akamai); se parte del GeoJSON ya descargado y se "
                       "simplifica con Douglas-Peucker a 40 m"),
        }

    # --- DGT: NAP de Trafico (DATEX II) ---
    for capa, fich, titulo, ds in (
        ("dgt-camaras", "dgt_camaras_recibo.json", "Cámaras de tráfico (DGT)", "Cámaras DGT DATEX2 v3.7"),
        ("dgt-paneles", "dgt_paneles_recibo.json", "Paneles de mensaje variable", "Paneles DGT DATEX2 v3.7"),
        ("dgt-incidencias", "dgt_incidencias_recibo.json", "Incidencias en tiempo real", "Incidencias DGT DATEX2 v3.7"),
        ("dgt-electrolineras", "dgt_electrolineras_recibo.json", "Puntos de recarga eléctrica", "Puntos de recarga eléctrica para vehículos"),
    ):
        r = leer(fich, {})
        if r:
            fuentes[capa] = {
                "capa": capa, "titulo": titulo,
                "fuente": "DGT", "editor": "DGT · NAP de Tráfico",
                "licencia": "reutilización con atribución",
                "actualizado": r.get("actualizado") or None,
                "descargado": HOY,
                "features": r.get("features"),
                "url": "https://nap.dgt.es",
                "metodo": "DATEX II v3 (XML) del NAP de Tráfico · " + ds,
            }


    # --- GTFS-Realtime: vehiculos en vivo ---
    r = leer("gtfsrt_recibo.json", {})
    if r and r.get("feeds"):
        renfe = r["feeds"].get("renfe", {})
        fuentes["gtfsrt"] = {
            "capa": "gtfsrt", "titulo": "Vehículos en vivo (GTFS-RT)",
            "fuente": "Operadores (Renfe)", "editor": "GTFS-Realtime",
            "licencia": "condiciones del editor",
            "actualizado": (renfe.get("timestamp_feed") or "")[:19] or None,
            "descargado": r.get("descargado"),
            "features": renfe.get("vehiculos"),
            "url": renfe.get("url") or "https://gtfsrt.renfe.com/",
            "metodo": "protobuf GTFS-RT, refresco continuo",
        }


    # --- AEMET: zonas de aviso con geometria ---
    r = leer("aemet_zonas_recibo.json", {})
    if r:
        fuentes["aemet-zonas"] = {
            "capa": "aemet-zonas", "titulo": "Avisos AEMET (zonas)",
            "fuente": "AEMET", "editor": "AEMET · Meteoalerta",
            "licencia": "© AEMET, citar como autora",
            "actualizado": (r.get("elaborado") or "")[:8] or None,
            "descargado": r.get("descargado"),
            "features": r.get("features"),
            "url": r.get("url") or "https://www.aemet.es/es/eltiempo/prediccion/avisos",
            "metodo": "tar.gz de GeoJSON de la pagina de avisos (sin clave)",
        }

    # municipios: geometría de Eurostat GISCO y población del padrón del INE
    rm = leer("municipios_recibo.json", {})
    if rm:
        fuentes["municipios"] = {
            "capa": "municipios", "titulo": "Municipios (polígono y población)",
            "fuente": "INE · Eurostat GISCO", "editor": "INE / Eurostat",
            "licencia": rm.get("licencia", "© EuroGeographics · INE datos abiertos"),
            "actualizado": str(rm.get("anio_padron") or ""),
            "descargado": (rm.get("descargado") or "")[:10],
            "features": rm.get("features"),
            "url": "https://www.ine.es",
            "metodo": ("polígonos LAU 1M de Eurostat GISCO cruzados POR CÓDIGO INE (LAU_ID) con las cifras "
                       "oficiales del padrón (INE, tabla 29005 en CSV, columna Municipios = código + nombre)"),
        }

    # --- Clima: Open-Meteo (ICON/GFS), sin clave y con licencia CC BY 4.0 ---
    r = leer("clima_recibo.json", {})
    if r:
        for capa, titulo, met in (
            ("clima-temperatura", "Temperatura ahora (provincia)",
             "modelo ICON/GFS por provincia sobre el shape de nuts3_es.geojson "
             "(consulta en el centroide, pintado en el poligono), paso 15 min"),
            ("clima-viento", "Viento ahora (campo interpolado)",
             "interpolacion IDW vectorial sobre rejilla propia, barbas de 2 vertices; "
             "rejilla aparte para Canarias"),
        ):
            fuentes[capa] = {
                "capa": capa, "titulo": titulo,
                "fuente": "Open-Meteo", "editor": r.get("editor") or "Open-Meteo",
                "licencia": r.get("licencia") or "CC BY 4.0",
                "actualizado": r.get("actualizado") or None,
                "descargado": r.get("descargado"),
                "features": r.get("features"),
                "url": r.get("url") or "https://open-meteo.com/",
                "metodo": met,
            }

    # Estructuras de la RCE: túneles del MITMA y puentes de OSM. Cada fichero trae su propio recibo
    # (`*_recibo.json`) para que la ficha no dependa de una lista escrita a mano.
    # `depuradoras_ign` es insumo de `edar_unificar.py`, no una capa: si se listara, el catálogo
    # contaría dos veces las mismas plantas.
    INTERMEDIOS = {"depuradoras_ign", "edar", "irewater_hib_edar"}
    # El nombre del fichero no siempre da el id de la capa (`vias_verdes_ign` -> `vias-verdes`).
    # Se declara aquí y no se adivina: si no, la capa sale como «SIN DECLARAR» en Salud.
    ALIAS_FICHERO = {"vias_verdes_ign": "vias-verdes",
             "caminos_santiago_ign": "caminos-santiago",
             "aviacion_ligera_ign": "aviacion-ligera"}
    for fich in sorted(os.listdir(DATOS)):
        if not fich.endswith("_recibo.json"):
            continue
        base = fich[: -len("_recibo.json")]
        if base in INTERMEDIOS:
            continue
        capa = ALIAS_FICHERO.get(base, base.replace("_", "-"))
        if capa in fuentes:
            continue
        r = leer(fich, {})
        if not (r.get("fuente") and r.get("licencia") and r.get("features") is not None):
            continue
        fuentes[capa] = {
            "capa": capa, "titulo": r.get("titulo") or ETIQUETAS.get(capa) or capa,
            "fuente": r.get("fuente"), "editor": r.get("editor") or r.get("fuente"),
            "licencia": r.get("licencia"),
            "actualizado": r.get("actualizado") or r.get("descargado"),
            "descargado": r.get("descargado"),
            "features": r.get("features"),
            "fecha_dato": r.get("fecha_dato"),   # el año del aforo, no la fecha de descarga
            "url": r.get("url"), "metodo": r.get("metodo"),
        }

    # EDAR: una sola capa con las tres fuentes fundidas; su ficha manda sobre la de OSM a secas.
    r = leer("edar_unificado_recibo.json", {})
    if r.get("features") is not None:
        fuentes["edar"] = {
            "capa": "edar", "titulo": r.get("titulo") or "EDAR · depuradoras unificadas",
            "fuente": r.get("fuente"), "editor": r.get("editor"),
            "licencia": r.get("licencia"), "actualizado": r.get("descargado"),
            "descargado": r.get("descargado"), "features": r.get("features"),
            "url": r.get("url"), "metodo": r.get("metodo"),
        }

    sim = leer("simplificado/_recibo.json", {})
    simpl = {os.path.basename(c["id"]): c for c in sim.get("capas", [])}

    salida = {
        "generado": HOY,
        "nota": "Generado por scripts/fuentes_visor.py desde los recibos reales. "
                "No se edita a mano.",
        "capas": fuentes,
        "simplificacion": simpl,
        "total_capas": len(fuentes),
    }
    ruta = os.path.join(DATOS, "fuentes.json")
    json.dump(salida, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for k, v in sorted(fuentes.items()):
        print("  %-22s %-34s %s  %s" % (k, v["fuente"][:34], v["licencia"][:12],
                                        v["actualizado"] or "—"))
    print("\n%d capas -> datos/fuentes.json" % len(fuentes))


if __name__ == "__main__":
    main()
