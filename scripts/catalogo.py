# -*- coding: utf-8 -*-
"""Normaliza el catálogo de fuentes al contrato machine-readable de la auditoría (§08 de la
auditoría v2 de OpenInfraES).

Problemas que resuelve, todos señalados en la auditoría:

  P3  La licencia era un texto suelto («CC-BY-4.0», «ODbL 1.0»). Ahora es un objeto con
      `estado` (si / no / pendiente), que es lo que permite decidir si una capa puede entrar
      en un MCP público. REE, OMIE y Renfe GTFS-RT quedan en **pendiente**: su reutilización
      no está evaluada, y «consultar en vivo» no sustituye a esa evaluación.
  P5  `fuente` mezclaba organismo y producto, y había variantes del mismo organismo
      («I-ReWater HUB (Interreg)» / «… + INE»). Ahora hay `organismo` canónico y `producto`.
  P2  No se distinguía cuándo se midió el dato de cuándo se descargó. Ahora `fecha_dato` y
      `fecha_descarga` son campos separados, y `ttl_segundos` dice cuándo el dato ya no vale.

    python scripts/catalogo.py

Escribe `datos/catalogo.json` (el contrato) sin tocar `fuentes.json` (lo que lee el visor).
"""
import datetime
import json
import re
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")

# --- organismos canónicos (P5): las variantes se pliegan en un solo nombre ---
ORGANISMO = {
    "MITECO": "MITECO", "IGN": "IGN", "REE": "REE", "CSN": "CSN", "ENRESA": "ENRESA",
    "CORES": "CORES", "Enagás": "Enagás", "NAP · MITMA": "MITMA", "MITMA": "MITMA",
    "DGT": "DGT", "AEMET": "AEMET", "EMSC-CSEM": "EMSC-CSEM",
    "OpenStreetMap (red)": "OpenStreetMap", "OpenStreetMap": "OpenStreetMap",
    "I-ReWater HUB (Interreg)": "I-ReWater HUB", "I-ReWater HUB (Interreg) + INE": "I-ReWater HUB",
    "INE · Eurostat GISCO": "INE / Eurostat", "INE · Cifras Oficiales del Padrón": "INE",
    "Visor Hermes — MITMA": "MITMA",    "Renfe": "Renfe", "OMIE": "OMIE", "Adif": "Adif", "Adif · IDEADIF": "Adif", "IGME": "IGME", "EMODnet": "EMODnet",
    "Copernicus EMS · EFFIS": "Copernicus EMS", "Copernicus EMS": "Copernicus EMS",
    "EFFIS · Copernicus Emergency Management Service": "Copernicus EMS",
    "Ministerio de Transportes (ArcGIS REST)": "MITMA",
    # Open-Meteo no produce el dato: agrega los modelos ICON (DWD) y GFS (NOAA). Jerarquía 2.
    "Open-Meteo": "Open-Meteo",
}

# --- licencia en tres estados (P3) ---
#   si        reutilización permitida con atribución
#   pendiente condiciones no evaluadas: NO entra en un MCP público
#   no        prohibida
LICENCIA = {
    "MITECO": ("si", "Reutilización Ley 37/2007 con atribución",
               "https://www.miteco.gob.es/es/aviso-legal"),
    "IGN": ("si", "CC BY 4.0 · © scne.es", "https://www.ign.es/espmap/notas_leyenda.htm"),
    "CSN": ("si", "CC BY 4.0", "https://www.csn.es"),
    "ENRESA": ("si", "Reutilización Ley 37/2007", "https://www.enresa.es"),
    "CORES": ("si", "Reutilización Ley 37/2007", "https://www.cores.es"),
    "Enagás": ("si", "Reutilización Ley 37/2007", "https://www.enagas.es"),
    "MITMA": ("si", "Ley 37/2007 · NAP", "https://nap.transportes.gob.es"),
    "DGT": ("si", "Reutilización Ley 37/2007", "https://www.dgt.es"),
    "AEMET": ("si", "Reutilización Ley 37/2007", "https://www.aemet.es/es/aviso_legal"),
    "EMSC-CSEM": ("si", "CC BY 4.0", "https://www.emsc-csem.org"),
    "OpenStreetMap": ("si", "ODbL 1.0 · comparte igual en bases derivadas",
                      "https://opendatacommons.org/licenses/odbl/1-0/"),
    "I-ReWater HUB": ("si", "CC BY 4.0", "https://i-rewater-hub.com"),
    "OurAirports": ("si", "Dominio público", "https://ourairports.com/faq/"),
    "GDACS — Comisión Europea (JRC)": ("si", "Servicio público de la Comisión Europea · atribución",
                                       "https://www.gdacs.org/About/legal.aspx"),
    "INE": ("si", "Datos abiertos INE con cita", "https://www.ine.es/aviso_legal"),
    "INE / Eurostat": ("si", "INE con cita · Eurostat CC BY 4.0",
                       "https://ec.europa.eu/eurostat/web/main/legal-notice"),
    # PENDIENTES: la auditoría cita el texto y no encuentra cláusula que permita redistribuir
    "REE": ("pendiente", "Aviso legal REE §5: uso informativo no comercial; el resto exige "
                         "autorización escrita. Condiciones de apidatos no localizadas",
            "https://www.ree.es/es/aviso-legal"),
    "OMIE": ("pendiente", "Sin cláusula de reutilización identificada para los datos publicados",
             "https://www.omie.es/es/aviso-legal"),
    "IGME": ("si", "Reutilización Ley 37/2007", "https://www.igme.es"),
    "Open-Meteo": ("si", "CC BY 4.0 · atribuir a Open-Meteo y al modelo (ICON/GFS)",
                   "https://open-meteo.com/en/license"),
    "EMODnet": ("si", "CC BY 4.0", "https://emodnet.ec.europa.eu/en/legal-notice"),
    "Adif": ("si", "CC BY 4.0 según ficha de datos.gob.es",
             "https://datos.gob.es/es/catalogo/e0dat0002-wfs-de-la-red-de-transporte-ferroviario-de-adif"),
    "Renfe": ("pendiente", "GTFS-RT sin condiciones localizadas (los conjuntos de data.renfe.com "
                           "de estaciones sí son CC BY 4.0)",
              "https://data.renfe.com"),
    # Copernicus: política de datos abiertos del programa (Reg. UE 2021/696), atribución obligatoria.
    "Copernicus EMS": ("si", "Copernicus: reutilización libre con atribución (© Unión Europea, "
                             "Copernicus EMS · EFFIS)",
                       "https://www.copernicus.eu/en/legal-notice"),
}

# --- frescura (P2): el TTL lo define la fuente, no la comodidad del servidor ---
TTL = {
    "embalses": (604800, "semanal", "foto"),
    "omie_precio": (3600, "cada subasta (≈13:00)", "vivo"),
    "ree_vivo": (300, "5 minutos", "vivo"),
    "clima-temperatura": (900, "15 minutos (modelo)", "vivo"),
    "clima-viento": (900, "15 minutos (modelo)", "vivo"),
    "entsoe_mix": (900, "15 minutos", "vivo"),
    "esios_prevision": (21600, "6 horas", "vivo"),
    "aemet_avisos": (3600, "cada hora", "vivo"),
    "aemet-zonas": (3600, "cada hora", "vivo"),
    # acumulativa por VENTANA: el fichero trae los N últimos días, así que su TTL es la ventana.
    # Con 30 minutos salía «caducada» todos los días por llevar un sismo de anteayer, que es
    # justo lo que la capa quiere enseñar.
    "sismos": (604800, "acumulativa (ventana de 7 días)", "vivo"),
    "dgt-camaras": (600, "10 minutos", "foto"),
    "dgt-incidencias": (300, "5 minutos", "vivo"),
    "gtfsrt": (120, "2 minutos", "vivo"),
    "carburantes": (86400, "diario", "vivo"),
    # Estructuras de la RCE: el inventario del MITMA cambia con las obras, no cada día.
    "tuneles-rce": (2592000, "mensual", "foto"),
    "puentes-rce": (2592000, "mensual", "foto"),
    # Patrimonio y equipamientos del IGN: cambian con las declaraciones y las obras, no a diario.
    "patrimonio-ign": (2592000, "mensual", "foto"),
    "sanidad-ign": (2592000, "mensual", "foto"),
    "residencias-ign": (2592000, "mensual", "foto"),
    "depositos-ign": (2592000, "mensual", "foto"),
    # Ciudad y servicios: detalle urbano del mismo servicio SignA. Es foto mensual, no dato vivo.
    "ciudad-aparcamientos": (2592000, "mensual", "foto"),
    "ciudad-cementerios": (2592000, "mensual", "foto"),
    "ciudad-zonas-verdes": (2592000, "mensual", "foto"),
    "ciudad-deportivas": (2592000, "mensual", "foto"),
    "ciudad-comercio": (2592000, "mensual", "foto"),
    "ciudad-ferias": (2592000, "mensual", "foto"),
    "ciudad-recreo": (2592000, "mensual", "foto"),
    "ciudad-docencia": (2592000, "mensual", "foto"),
    "ciudad-antenas": (2592000, "mensual", "foto"),
    "ciudad-mineria": (2592000, "mensual", "foto"),
    "ciudad-singulares": (2592000, "mensual", "foto"),
    "ciudad-logistica": (2592000, "mensual", "foto"),
    "ciudad-ciencia": (2592000, "mensual", "foto"),
    "ciudad-acuicultura": (2592000, "mensual", "foto"),
    "alojamiento-ign": (31536000, "anual", "foto"),
    "ocio-ign": (31536000, "anual", "foto"),
    "cimas-ign": (31536000, "anual", "foto"),
    "sierras-ign": (31536000, "anual", "foto"),
    "vias-verdes": (31536000, "anual", "foto"),
    "caminos-santiago": (31536000, "anual", "foto"),
    "cable-ign": (31536000, "anual", "foto"),
    "ferris-ign": (31536000, "anual", "foto"),
    "aviacion-ligera": (31536000, "anual", "foto"),
    "plantas": (2592000, "mensual", "foto"),
    "ine-provincias": (31536000, "anual (padrón)", "foto"),
    "ine-ccaa": (31536000, "anual (padrón)", "foto"),
    "ine-densidad": (31536000, "anual (padrón)", "foto"),
    "ine-paro": (7776000, "trimestral (EPA)", "foto"),
    "aeropuertos": (604800, "semanal", "foto"),
    "alertas-gdacs": (10368000, "acumulativa (ventana de 120 días)", "foto"),
    # OGC API Features del MITECO: inventarios que se actualizan con cada planificación
    "aforos": (7776000, "trimestral", "foto"),
    "canales-miteco": (7776000, "trimestral", "foto"),
    "calidad-aire-estaciones": (7776000, "trimestral", "foto"),
    "masas-subterraneas": (31536000, "por ciclo de planificación (6 años)", "foto"),
    "dpmt": (31536000, "por deslinde aprobado", "foto"),
    # IGN · SignA: figuras de proteccion y red fluvial oficial. Cambian cuando se declara un
    # parque o se revisa el MTN, no cada dia; se refrescan con el cron semanal.
    "espacios-protegidos": (7776000, "trimestral", "foto"),
    "red-natura": (7776000, "trimestral", "foto"),
    # EFFIS revisa el histórico con retraso: lo que caduca no es la fecha del incendio (un incendio
    # de 2019 sigue siendo cierto), es el snapshot. A los 90 días sin volver a pedirlo, se declara.
    "incendios-effis": (7776000, "trimestral", "foto"),
    "rios-mtn": (7776000, "trimestral", "foto"),
    "presas": (7776000, "trimestral", "foto"),
}

TTL_DEFECTO = (2592000, "mensual o inferior", "foto")

# Capas que publican una VENTANA de los N últimos días, no una foto: la «fecha del dato» de esos
# ficheros es la del evento más viejo de la ventana, y tomarla como edad del fichero lo declara
# viejo el primer día. Para ellas la fecha del dato es la de descarga (la ventana entra hasta hoy).
VENTANA = {"sismos": 7}

# JERARQUIA de la fuente. David: «dar mas valor a los datos oficiales que a los no oficiales».
#   1  organismo que PRODUCE el dato (INE, MITECO, REE, Adif, DGT, AEMET, IGN, CSN...)
#   2  organismo oficial que AGREGA o publica el de otro (NAP, Eurostat, MITMA)
#   3  comunitario / no oficial (OpenStreetMap). Vale, pero no manda cuando hay oficial.
JERARQUIA = {
    "INE": 1, "INE / Eurostat": 1, "MITECO": 1, "REE": 1, "Adif": 1, "DGT": 1,
    "AEMET": 1, "IGN": 1, "CSN": 1, "ENRESA": 1, "CORES": 1, "Enagás": 1,
    "I-ReWater HUB": 1, "OMIE": 1, "Renfe": 1, "EMSC-CSEM": 2,
    "Copernicus EMS": 1,
    "MITMA": 2, "EMODnet": 2, "IGME": 1, "OpenStreetMap": 3, "Open-Meteo": 2,
}
ETIQUETA_JERARQUIA = {1: "organismo productor", 2: "organismo agregador", 3: "fuente comunitaria"}


# capa -> fichero en datos/ (para saber cuanto pesa lo que se descarga)
def rutas_del_visor():
    """id -> ruta del fichero, leida de index.html. El nombre no siempre coincide con el id
    (`embalses` vive en `embalses.geojson` pero `adif-tramos` en `adif_tramos.geojson`), asi que
    adivinar por el id falla; la ruta real esta declarada en la capa."""
    html = open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read()
    ini = html.index("const CAPAS = [")
    fin = html.index("];", ini)
    bloque = html[ini:fin]
    salida = {}
    for m in re.finditer(r'id:"([a-z0-9\-_]+)"', bloque):
        resto = bloque[m.end():m.end() + 700]
        f = re.search(r'fichero:"([^"]+)"', resto)
        if f:
            salida[m.group(1)] = f.group(1)
    return salida


RUTAS = rutas_del_visor()


def fichero_de(cid):
    f = RUTAS.get(cid)
    if f:
        ruta = os.path.join(RAIZ, f.replace("/", os.sep))
        if os.path.exists(ruta):
            return ruta
    for ext in (".geojson", ".json"):
        for nombre in (cid.replace("-", "_"), cid):
            ruta = os.path.join(DATOS, nombre + ext)
            if os.path.exists(ruta):
                return ruta
    return None


def tamano(cid):
    ruta = fichero_de(cid)
    if not ruta:
        return None, None
    b = os.path.getsize(ruta)
    return b, round(b / 1024.0, 1)


def hoy_iso():
    return datetime.date.today().isoformat()


def normaliza_organismo(bruto):
    if not bruto:
        return "sin declarar"
    if bruto in ORGANISMO:
        return ORGANISMO[bruto]
    # variantes con sufijo: «REE · Registro administrativo…», «INE (padrón)»
    for clave in ORGANISMO:
        if bruto.startswith(clave) or clave in bruto:
            return ORGANISMO[clave]
    if bruto.startswith("INE"):
        return "INE"
    if "REE" in bruto:
        return "REE"
    return bruto


def main():
    ruta = os.path.join(DATOS, "fuentes.json")
    if not os.path.exists(ruta):
        raise SystemExit("falta datos/fuentes.json: ejecuta antes fuentes_visor.py")
    crudo = json.load(open(ruta, encoding="utf-8"))
    capas = crudo.get("capas", {})

    catalogo = {}
    avisos = {"pendiente": [], "sin_organismo": [], "caducado": []}
    hoy = datetime.date.today()

    for cid, f in sorted(capas.items()):
        organismo = normaliza_organismo(f.get("fuente"))
        estado_lic, nombre_lic, url_lic = LICENCIA.get(
            organismo, ("pendiente", "sin evaluar", ""))
        ttl, frecuencia, modo = TTL.get(cid, TTL_DEFECTO)

        # fecha del dato y fecha de descarga son cosas distintas (P2)
        fecha_dato = f.get("actualizado") or f.get("descargado")
        fecha_desc = f.get("descargado")
        if cid in VENTANA:
            # la capa es una ventana de los N últimos días: su dato es de hoy, no del evento
            # más viejo que contenga
            fecha_dato = fecha_desc or fecha_dato

        # ¿está caducado? se declara, no se oculta
        # La caducidad se mide sobre la FECHA DEL DATO, no sobre cuando se descargo: un fichero
        # bajado hoy puede contener un dato de hace tres dias, y eso es lo que ve el lector.
        caducado = False
        edad_dias = None
        if fecha_dato:
            try:
                d = datetime.date.fromisoformat(str(fecha_dato)[:10])
                edad_dias = (hoy - d).days
                caducado = edad_dias * 86400 > ttl
            except ValueError:
                pass

        nivel = JERARQUIA.get(organismo, 3)
        catalogo[cid] = {
            "id": cid,
            "titulo": f.get("titulo") or cid,
            "organismo": organismo,
            "oficial": nivel <= 2,
            "jerarquia": nivel,
            "jerarquia_txt": ETIQUETA_JERARQUIA[nivel],
            "producto": f.get("metodo") or "",
            "licencia": {
                "estado": estado_lic,
                "nombre": nombre_lic,
                "url_terminos": url_lic,
            },
            "endpoint": f.get("url") or "",
            "modo": modo,
            "frecuencia_fuente": frecuencia,
            "ttl_segundos": ttl,
            "ultima_verificacion": hoy_iso(),
            "crs": "EPSG:4326",
            "features": f.get("features"),
            "bytes": tamano(cid)[0],
            "kb": tamano(cid)[1],
            "fecha_dato": fecha_dato,
            "fecha_descarga": fecha_desc,
            "edad_dias": edad_dias,
            "caducado": caducado,
        }

        if estado_lic == "pendiente":
            avisos["pendiente"].append(cid)
        if organismo == "sin declarar":
            avisos["sin_organismo"].append(cid)
        if caducado:
            avisos["caducado"].append(cid)

    salida = {
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "esquema": 1,
        "nota": ("Contrato machine-readable del catálogo. La licencia va en tres estados: "
                 "«pendiente» NO se expone en un MCP público hasta evaluarla."),
        "total": len(catalogo),
        "resumen": {
            "licencia_si": sum(1 for c in catalogo.values() if c["licencia"]["estado"] == "si"),
            "licencia_pendiente": len(avisos["pendiente"]),
            "caducados": len(avisos["caducado"]),
            "oficiales": sum(1 for c in catalogo.values() if c["oficial"]),
            "comunitarias": sum(1 for c in catalogo.values() if not c["oficial"]),
            "por_jerarquia": {k: sum(1 for c in catalogo.values() if c["jerarquia"] == k)
                              for k in (1, 2, 3)},
            "descargables_ligeros": sum(1 for c in catalogo.values()
                                        if c.get("kb") and c["kb"] <= 1024),
            "kb_total": round(sum(c.get("kb") or 0 for c in catalogo.values()), 1),
        },
        "avisos": avisos,
        "capas": catalogo,
    }
    json.dump(salida, open(os.path.join(DATOS, "catalogo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("  catálogo: %d capas" % len(catalogo))
    print("   oficiales: %d · comunitarias: %d" % (
        salida["resumen"]["oficiales"], salida["resumen"]["comunitarias"]))
    print("   licencia evaluada: %d · pendiente: %d · caducadas: %d" % (
        salida["resumen"]["licencia_si"], len(avisos["pendiente"]), len(avisos["caducado"])))
    if avisos["pendiente"]:
        print("   PENDIENTE DE LICENCIA: %s" % ", ".join(avisos["pendiente"]))
    if avisos["caducado"]:
        print("   CADUCADAS (superan su TTL): %s" % ", ".join(avisos["caducado"][:12]))
    if avisos["sin_organismo"]:
        print("   SIN ORGANISMO: %s" % ", ".join(avisos["sin_organismo"][:6]))


if __name__ == "__main__":
    main()