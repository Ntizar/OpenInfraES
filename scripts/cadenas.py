# -*- coding: utf-8 -*-
"""Cadenas de procedencia: quien produce el dato, quien lo publica y que fecha tiene cada cosa.

La pregunta que resuelve: si el visor toma un dato ya vectorizado que a su vez
Boletín Hidrológico, ¿de cuándo es el dato? Aquí se separan tres fechas distintas:

  fecha_dato        cuando se midio el dato (la que declara el productor)
  fecha_publicacion cuando el agregador lo publico (verificado_a / release)
  fecha_descarga    cuando lo bajamos nosotros

Solo se escribe lo que esta documentado en el repo o en el propio dato. Donde el
productor no lo declara, se dice.
"""
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
HOY = "2026-11-16"

# capa -> (productor primario, como llega, nota)
CADENAS = {
    # --- capas vectorizadas: los eslabones que el propio dato declara
    "embalses": ("MITECO — Boletín Hidrológico (parte semanal)", "Descarga directa del organismo",
                 "El parte trae fecha propia en el campo fecha_dato y se conserva tal cual."),
    "subestaciones": ("IGN — BTN Continua (Base Topográfica Nacional)", "Descarga directa del organismo",
                      "El campo atribucion del dato dice: «Obra derivada de BTN Continua CC-BY 4.0 ign.es»."),
    "desaladoras": ("MITECO / Acuamed (instalaciones declaradas)", "Descarga directa del organismo",
                    "El estado administrativo y la verificación se toman del registro del organismo."),
    "nuclear": ("Consejo de Seguridad Nuclear / propietarios", "Descarga directa del organismo",
                "Potencia y tecnología por reactor; el estado se verifica por registro."),
    "regas": ("Enagás / operadores de planta", "Descarga directa del organismo", ""),
    "gasalm": ("Enagás / operadores", "Descarga directa del organismo", ""),
    "refinerias": ("Corporación de Reservas / operadores", "Descarga directa del organismo", ""),
    "interelec": ("REE — operador del sistema", "Descarga directa del organismo", ""),
    "h2": ("MITECO — Proyectos de Interés Común (PCI)", "Descarga directa del organismo", ""),
    # --- capas propias de OpenInfraES
    "l400": ("Red Eléctrica de España (instalaciones) / mapeo OSM", "OpenInfraES ← OSM",
             "La tensión viene etiquetada en cada línea de OSM; no se cruza con REE."),
    "l220": ("Red Eléctrica de España (instalaciones) / mapeo OSM", "OpenInfraES ← OSM", ""),
    "gasoductos": ("Enagás / mapeo OSM", "OpenInfraES ← OSM", "Operador y presión según etiquetas de OSM."),
    "hidro": ("Propietarios de central / mapeo OSM + ELECTRA", "OpenInfraES ← OSM", ""),
    "gasgen": ("Propietarios / mapeo OSM", "OpenInfraES ← OSM", "Subconjunto de plantas.geojson."),
    "resto": ("Propietarios / mapeo OSM", "OpenInfraES ← OSM", "Subconjunto de plantas.geojson."),
    # --- MITMA
    "carreteras": ("MITMA — Inventario de la Red de Carreteras del Estado", "Visor Hermes (ArcGIS REST)",
                   "Fuente primaria: el propio ministerio. No hay intermediario."),
    "puertos": ("Puertos del Estado / autoridades portuarias", "Visor Hermes (ArcGIS REST)", ""),
    "terminales-puerto": ("Autoridades portuarias", "Visor Hermes (ArcGIS REST)", ""),
    "terminales-aero": ("Aena", "Visor Hermes (ArcGIS REST)", ""),
    "terminales-aero-pista": ("Aena", "Visor Hermes (ArcGIS REST)", ""),
    "intermodales": ("Adif / Puertos del Estado", "Visor Hermes (ArcGIS REST)", ""),
    "estaciones-gas": ("MITECO — registro de carburantes", "Visor Hermes (ArcGIS REST)",
                       "Los flags GNL/GNC/H2 son del registro; el visor filtra a 165 de 11.485."),
    # --- agua (OSM)
    "irewater-edar": ("I-ReWater HUB (Interreg) — EDAR de las demarcaciones",
                      "Descarga directa de la capa del proyecto",
                      "Capa de proyecto europeo, no inventario oficial del MITECO: se declara como tal."),
    "edar": ("Ayuntamientos / confederaciones (declarado en OSM)", "OpenInfraES ← OSM",
             "No es el inventario oficial del MITECO: es lo que está mapeado en OSM."),
    "etap": ("Confederaciones / ayuntamientos (declarado en OSM)", "OpenInfraES ← OSM", ""),
    "trasvases": ("Ministerio / confederaciones (trazado mapeado en OSM)", "OpenInfraES ← OSM",
                  "118 tramos unidos en 26 trazos. No existe capa oficial abierta."),
    "canales": ("Confederaciones hidráulicas / comunidades de regantes", "OpenInfraES ← OSM",
                "Acequias históricas: muchas con siglos de historia."),
    "agua-conducciones": ("Confederaciones y comunidades de regantes (mapeo OSM)",
                          "OpenInfraES ← OSM",
                          "Fichero crudo del que salen las capas Trasvases y Canales."),
    "rios": ("Confederaciones hidráulicas (geometría OSM)", "OpenInfraES ← OSM",
             "Caudal consultado en vivo a Open-Meteo Flood (GloFAS), que es MODELADO, no aforo."),
    "aeropuertos": ("OurAirports (base colaborativa de aeródromos)", "Descarga directa del CSV público",
                    "Dominio público. Es infraestructura física: no trae tráfico ni pasajeros, eso es MITMA."),
    "alertas-gdacs": ("GDACS — Comisión Europea (JRC)", "Descarga directa del RSS público",
                      "Acumulativa por (tipo, id) con ventana de 120 días; el nivel de alerta va en el dato."),
    # --- MITECO · OGC API Features (datos de alto valor, Reglamento UE 2023/138) ---
    "aforos": ("MITECO — Red Integrada de Estaciones de Aforo (SAIH-ROEA)",
               "OGC API Features del propio ministerio",
               "Colección agua:Estaciones_Aforos. Es la estación de aforo, no el caudal: el caudal "
               "en vivo es otro dato y no está abierto en la misma colección."),
    "canales-miteco": ("Confederaciones hidrográficas / MITECO — red de canales principales",
                       "OGC API Features del propio ministerio",
                       "Colección agua:canales (792 trazos). No confundir con la capa de OSM: "
                       "aquella son 10.800 acequias mapeadas, esta es la red principal declarada."),
    "calidad-aire-estaciones": ("MITECO y comunidades autónomas — red de evaluación de la calidad del aire",
                                "OGC API Features del propio ministerio",
                                "Colección evaluacionambiental:ca_red_estaciones. Son las estaciones, "
                                "no las medidas: el índice horario va por otra vía y no se publica aquí."),
    "masas-subterraneas": ("MITECO y confederaciones hidrográficas — masas de agua subterránea (PHC 2022-2027)",
                           "OGC API Features del propio ministerio",
                           "Colección agua:estado_masas_aguasub_2027_global. El estado es el que declara "
                           "el plan hidrológico vigente, no una medición de hoy."),
    "dpmt": ("Dirección General de la Costa y del Mar (MITECO) — deslinde del dominio público",
             "OGC API Features del propio ministerio",
             "Colección costas:dominio_publico_maritimo_terrestre. Cada tramo lleva su referencia de "
             "deslinde y la orden ministerial; es un límite administrativo, no una cota de marea."),
}


# ids de origen que comparten organismo con su alias del visor
ALIAS_INVERSO = {
    "gas-regasificacion": "regas",
    "gas-almacenamiento": "gasalm",
    "electricidad-interconexiones": "interelec",
    "hidrogeno-produccion": "h2",
    "red-electrica": "subestaciones",
    "agua-embalsada": "embalses",
    "parques-eolicos": "hidro",
    "plantas-solares": "resto",
    "gas-interconexiones": "gasoductos",
    "almacenamiento-petrolifero": "refinerias",
    "residuos-radiactivos": "nuclear",
    "puertos-interes-general": "puertos",
    "terminales-portuarias": "terminales-puerto",
    "terminales-aeropuerto": "terminales-aero",
    "pistas-aeropuerto": "terminales-aero",
    "terminales-mercancias": "intermodales",
    "conducciones-combustible": "gasoductos",
    "hidrogeno-red": "h2",
    "generacion-electrica-provincia": "hidro",
}


ORGANISMOS = {
    "embalses": "MITECO", "subestaciones": "IGN", "desaladoras": "MITECO",
    "nuclear": "CSN / propietarios", "regas": "Enagás", "gasalm": "Enagás",
    "refinerias": "CORES", "interelec": "REE", "h2": "MITECO",
    "l400": "REE / OSM", "l220": "REE / OSM", "gasoductos": "Enagás / OSM",
    "hidro": "OSM / ELECTRA", "gasgen": "OSM", "resto": "OSM",
    "carreteras": "MITMA", "puertos": "Puertos del Estado",
    "terminales-puerto": "Autoridades portuarias", "terminales-aero": "Aena",
    "intermodales": "Adif / Puertos", "estaciones-gas": "MITECO",
    "edar": "OSM", "etap": "OSM", "trasvases": "OSM / confederaciones",
    "canales": "OSM / confederaciones", "rios": "OSM + Open-Meteo (GloFAS)",
    "agua-conducciones": "OSM", "sismos": "EMSC-CSEM",
    "estaciones-cercanias": "Renfe", "carburantes": "MITECO", "demarcaciones": "MITECO",
    "eolicos": "MITECO", "solares": "MITECO", "residuos": "ENRESA",
    "petrolifero": "CORES", "h2red": "MITECO",
    "nap-metro": "NAP · MITMA", "nap-cercanias": "NAP · MITMA",
    "nap-ave": "NAP · MITMA",
    "nap-lineas-metro": "NAP · MITMA", "nap-lineas-cercanias": "NAP · MITMA",
    "dgt-camaras": "DGT", "dgt-incidencias": "DGT", "dgt-paneles": "DGT", "dgt-electrolineras": "DGT", "gtfsrt": "Renfe", "aemet-zonas": "AEMET",
    "aeropuertos": "OurAirports", "alertas-gdacs": "GDACS (JRC · Comisión Europea)",
    "aforos": "MITECO", "canales-miteco": "MITECO", "calidad-aire-estaciones": "MITECO",
    "masas-subterraneas": "MITECO", "dpmt": "MITECO",
}


def main():
    ruta = os.path.join(DEST, "fuentes.json")
    d = json.load(open(ruta, encoding="utf-8"))
    puestos = 0
    for capa, v in d["capas"].items():
        clave = capa if capa in CADENAS else ALIAS_INVERSO.get(capa)
        prod, via, nota = CADENAS.get(clave, (None, None, None))
        v["organismo"] = ORGANISMOS.get(capa) or (prod.split("—")[0].strip() if prod else None)
        v["publica_via"] = v.get("editor")
        v["cadena"] = {
            "productor": prod or "no declarado por el editor",
            "publica": via or v.get("editor"),
            "consume": "OpenInfraES (descarga directa del fichero)",
            "nota": nota or "",
        }
        # tres fechas distintas, y ninguna se inventa
        v["fecha_dato"] = v.get("actualizado") if capa in ("embalses",) else None
        v["fecha_publicacion"] = v.get("actualizado")
        v["fecha_descarga"] = v.get("descargado")
        if prod:
            puestos += 1
    d["generado"] = HOY
    d["nota_cadena"] = ("Cada capa declara productor (quien genera el dato), publica (quien lo "
                        "sirve tal como lo consumimos) y consume (nosotros). Son tres fechas "
                        "distintas: la del dato, la de publicación y la de descarga.")
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("  %d capas, %d con cadena documentada" % (len(d["capas"]), puestos))
    for k in ("embalses", "subestaciones", "carreteras", "rios"):
        if k in d["capas"]:
            c = d["capas"][k]["cadena"]
            print("   %-14s %s -> %s" % (k, c["productor"][:44], c["publica"][:26]))
    sin = [k for k, v in d["capas"].items() if v["cadena"]["productor"].startswith("no declarado")]
    if sin:
        print("  sin productor declarado: %s" % ", ".join(sin[:8]))


if __name__ == "__main__":
    main()
