# -*- coding: utf-8 -*-
"""ENTSO-E Transparency — el único que da generación y previsión POR UNIDAD.

La cuenta de la web NO es la clave de la API. Se pide un token «Restful API» a
transparency@entsoe.eu (asunto: "Restful API access"), indicando el email de la cuenta.
Con él, la API responde XML; aquí se convierte a estructuras simples.

    python scripts/entsoe.py --probar
    python scripts/entsoe.py --dia 2026-11-16
    python scripts/entsoe.py --unidades 2026-11-16

Endpoints usados (dominio España = 10YES-REE------0):
    A75  generación real agregada por tipo
    A73  generación real por unidad (registeredResource)
    A65  demanda total del sistema
    A44  precio del mercado diario
    A71  previsión de generación
    A69  previsión de demanda
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://web-api.tp.entsoe.eu/api"
ES = "10YES-REE------0"
DEST = os.path.join(RAIZ, "datos")


def token():
    t = os.environ.get("ENTSOE_TOKEN")
    if t:
        return t.strip()
    ruta = os.path.join(RAIZ, ".env")
    if not os.path.exists(ruta):        # sin fichero no hay clave: se avisa, no se revienta
        return None
    for linea in open(ruta, encoding="utf-8"):
        if linea.startswith("ENTSOE_TOKEN="):
            v = linea.split("=", 1)[1].strip()
            if v:            # una linea vacia arriba no debe tapar la buena
                return v
    return None


def pedir(params):
    tk = token()
    if not tk:
        print("  falta ENTSOE_TOKEN (ni en el entorno ni en .env): se mantiene el fichero anterior")
        raise SystemExit(3)             # 3 = sin clave; el workflow lo trata como salto, no como caida
    q = urllib.parse.urlencode({**params, "securityToken": tk})
    req = urllib.request.Request(API + "?" + q, headers={"User-Agent": "OpenInfraES/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit("ENTSO-E %s: %s" % (e.code, cuerpo))


NS = {"g": "urn:iec62325.351:tc57wg16:451-6:generationdocument:7:0",
      "g2": "urn:iec62325.351:tc57wg16:451-3:generationdocument:7:0",
      "g3": "urn:iec62325.351:tc57wg16:451-6:publicationdocument:7:3"}


def puntos(root):
    """Extrae (tipo, cantidad, inicio, resolucion) de cualquier documento de publicación."""
    salida = []
    for serie in root.iter():
        if not serie.tag.endswith("TimeSeries"):
            continue
        tipo = None
        for hijo in serie:
            if hijo.tag.endswith("MktPSRType"):
                for h2 in hijo:
                    if h2.tag.endswith("psrType"):
                        tipo = h2.text
        for periodo in serie:
            if not periodo.tag.endswith("Period"):
                continue
            ini = None
            res = None
            for h in periodo:
                if h.tag.endswith("timeInterval"):
                    for h2 in h:
                        if h2.tag.endswith("start"):
                            ini = h2.text
                if h.tag.endswith("resolution"):
                    res = h.text
            for p in periodo:
                if not p.tag.endswith("Point"):
                    continue
                pos = cant = None
                for h in p:
                    if h.tag.endswith("position"):
                        pos = int(h.text)
                    if h.tag.endswith("quantity"):
                        cant = float(h.text)
                salida.append({"tipo": tipo, "posicion": pos, "valor": cant,
                               "inicio": ini, "resolucion": res})
    return salida



def puntos_precio(root):
    """A44 usa <price.amount>, no <quantity>. Se agrupa por periodo para no mezclar dias."""
    salida = []
    for serie in root.iter():
        if not serie.tag.endswith("TimeSeries"):
            continue
        for n_per, periodo in enumerate([p for p in serie if p.tag.endswith("Period")]):
            ini = None
            start_tag = ""
            for h in periodo:
                if h.tag.endswith("timeInterval"):
                    for h2 in h:
                        if h2.tag.endswith("start"):
                            ini = h2.text
            for p in periodo:
                if not p.tag.endswith("Point"):
                    continue
                pos = val = None
                for h in p:
                    if h.tag.endswith("position"):
                        pos = int(h.text)
                    if h.tag.endswith("price.amount"):
                        val = float(h.text)
                if pos is not None and val is not None:
                    # LAS POSICIONES NO SE REINICIAN ENTRE PERIODOS: el segundo periodo
                    # empieza en 25. Sin separar por periodo se mezclan horas de dias distintos.
                    salida.append({"periodo": n_per, "inicio": ini, "posicion": pos, "precio": val})
    return salida


def precio(fecha):
    """A44 · precio del mercado diario. Sirve para CONTRASTAR el CSV de OMIE."""
    ini = fecha.replace("-", "") + "0000"
    fin = fecha.replace("-", "") + "2300"
    root = ET.fromstring(pedir({"documentType": "A44", "in_Domain": ES, "out_Domain": ES,
                                "contract_MarketAgreement.type": "A01",
                                "periodStart": ini, "periodEnd": fin}))
    filas = puntos_precio(root)
    # El dia pedido son 24 horas de UN periodo. Si se juntan periodos salen 48+ posiciones
    # con la numeracion corrida (25, 26...) y precios de otro dia.
    deldia = [f for f in filas if (f["inicio"] or "").startswith(fecha[:10])]
    if not deldia:
        deldia = filas
    primer = deldia[0]["periodo"]
    deldia = sorted([f for f in deldia if f["periodo"] == primer], key=lambda f: f["posicion"])
    # A44 llega en PT15M: 96 cuartos de hora, no 24 horas. Y puede venir incompleto
    # (2026-11-18 traia 78 de 96), asi que NO se reindexa: se conserva la posicion original.
    precios = [f["precio"] for f in deldia]
    salida = {"fecha": fecha, "fuente": "ENTSO-E Transparency (A44)",
              "cuartos": len(deldia), "resolucion": "PT15M",
              "horas": [{"cuarto": f["posicion"],
                         "hora": (f["posicion"] - 1) // 4 + 1,
                         "minuto": ((f["posicion"] - 1) % 4) * 15,
                         "precio": round(f["precio"], 2)} for f in deldia],
              "min": round(min(precios), 2), "max": round(max(precios), 2),
              "media": round(sum(precios) / len(precios), 2), "unidad": "EUR/MWh"}
    json.dump(salida, open(os.path.join(DEST, "entsoe_precio.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("  A44 %s · %d cuartos de hora · media %.2f EUR/MWh"
          % (fecha, len(deldia), salida["media"]))
    # contraste con OMIE, si esta
    ruta = os.path.join(DEST, "omie_precio.json")
    if os.path.exists(ruta):
        om = json.load(open(ruta, encoding="utf-8"))
        if om.get("fecha") == fecha:
            a = {h["cuarto"]: h["es"] for h in om["horas"]}
            b = {h["cuarto"]: h["precio"] for h in salida["horas"]}
            comunes = sorted(set(a) & set(b))
            iguales = [c for c in comunes if abs(a[c] - b[c]) < 0.02]
            print("   contraste con OMIE: %d de %d cuartos coinciden" % (len(iguales), len(comunes)))
            if len(iguales) < len(comunes):
                malos = [c for c in comunes if abs(a[c]-b[c]) >= 0.02][:5]
                print("   OJO: no coinciden los cuartos %s" % (malos,))
    return salida


def prevision(fecha):
    """A71 prevision de generacion y A69 prevision de demanda."""
    ini = fecha.replace("-", "") + "0000"
    fin = fecha.replace("-", "") + "2300"
    salida = {"fecha": fecha, "fuente": "ENTSO-E Transparency (A71/A69)"}
    for doc, clave, nombre in (("A71", "generacion", "prevision de generacion"),
                               ("A69", "demanda", "prevision de demanda")):
        try:
            root = ET.fromstring(pedir({"documentType": doc, "processType": "A01",
                                        "in_Domain": ES, "out_Domain": ES,
                                        "periodStart": ini, "periodEnd": fin}))
            filas = puntos(root)
            # NO se suma todo: hay una serie por tipo y varias pueden solaparse. Sumar da
            # 3,4 TWh para un dia, cinco veces la demanda real de Espana. Se publica el
            # numero de series y el rango por periodo, sin total inventado.
            series = len({(f["inicio"], f["tipo"]) for f in filas})
            vals = [f["valor"] for f in filas if f.get("valor")]
            salida[clave] = {"puntos": len(filas), "series": series,
                             "min": round(min(vals), 1) if vals else None,
                             "max": round(max(vals), 1) if vals else None}
            print("  %s %-24s %3d puntos · %2d series · rango %.0f-%.0f MWh"
                  % (doc, nombre, len(filas), series,
                     min(vals) if vals else 0, max(vals) if vals else 0))
        except Exception as e:
            salida[clave] = {"error": str(e)[:90]}
            print("  %s %-24s ERROR %s" % (doc, nombre, str(e)[:60]))
    json.dump(salida, open(os.path.join(DEST, "entsoe_prevision.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return salida


def probar():
    root = ET.fromstring(pedir({"documentType": "A75", "processType": "A16",
                                "in_Domain": ES, "out_Domain": ES,
                                "periodStart": "202611160000", "periodEnd": "202611162300"}))
    filas = puntos(root)
    print("  TOKEN OK · %d puntos de generación" % len(filas))
    tipos = {}
    for f in filas:
        if f["valor"]:
            tipos[f["tipo"]] = tipos.get(f["tipo"], 0) + f["valor"]
    for t, v in sorted(tipos.items(), key=lambda kv: -kv[1])[:8]:
        print("   psrType %-6s %10.1f MWh" % (t, v))


def dia(fecha):
    ini = fecha.replace("-", "") + "0000"
    fin = fecha.replace("-", "") + "2300"
    root = ET.fromstring(pedir({"documentType": "A75", "processType": "A16",
                                "in_Domain": ES, "out_Domain": ES,
                                "periodStart": ini, "periodEnd": fin}))
    filas = puntos(root)
    json.dump({"fecha": fecha, "puntos": filas, "fuente": "ENTSO-E Transparency (A75)"},
              open(os.path.join(DEST, "entsoe_generacion.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("  %d puntos -> datos/entsoe_generacion.json" % len(filas))


def unidades(fecha):
    """Generación por unidad: A73 con todos los recursos registrados."""
    ini = fecha.replace("-", "") + "0000"
    fin = fecha.replace("-", "") + "2300"
    root = ET.fromstring(pedir({"documentType": "A73", "processType": "A16",
                                "in_Domain": ES, "out_Domain": ES,
                                "periodStart": ini, "periodEnd": fin}))
    recursos = []
    for serie in root.iter():
        if not serie.tag.endswith("TimeSeries"):
            continue
        nombre = None
        for h in serie:
            if h.tag.endswith("registeredResource"):
                for h2 in h:
                    if h2.tag.endswith("name"):
                        nombre = h2.text
        if nombre:
            recursos.append(nombre)
    print("  unidades con producción: %d" % len(set(recursos)))
    for r in sorted(set(recursos))[:15]:
        print("   ", r)



# Codigos PSR de ENTSO-E (documentType A75)
# Códigos PSR de ENTSO-E (documentType A75). La tabla estaba DESPLAZADA a partir de B11:
# B11 es hidro fluyente, B12 embalse y B13 marina; B15 es otras renovables (no solar térmica).
PSR = {
    "B01": "Biomasa", "B02": "Lignito", "B03": "Gas de carbón", "B04": "Gas natural",
    "B05": "Carbón", "B06": "Fuel", "B07": "Pizarra bituminosa", "B08": "Turba",
    "B09": "Geotérmica", "B10": "Hidro bombeo", "B11": "Hidro fluyente",
    "B12": "Hidro embalse", "B13": "Marina", "B14": "Nuclear", "B15": "Otras renovables",
    "B16": "Solar fotovoltaica", "B17": "Residuos", "B18": "Otras", "B19": "Eólica terrestre",
    "B20": "Eólica marina", "B25": "Almacenamiento",
}


def mix(fecha=None):
    """A75 · generación real por tecnología cada 15 minutos.

    Es el dato mas fino que publica REE en abierto. A73 (por unidad/planta) NO existe para
    Espana: el endpoint responde «No matching data found» con cualquier processType.
    """
    if fecha is None:
        hoy = datetime.date.today()
    else:
        hoy = datetime.date.fromisoformat(fecha)
    ini = hoy.strftime("%Y%m%d") + "0000"
    fin = hoy.strftime("%Y%m%d") + "2300"
    root = ET.fromstring(pedir({"documentType": "A75", "processType": "A16",
                                "in_Domain": ES, "out_Domain": ES,
                                "periodStart": ini, "periodEnd": fin}))
    filas = puntos(root)
    # OJO: A75 da MW MEDIOS de cada cuarto, no energia. Sumar MW y llamarlo MWh multiplica por 4
    # la cifra (daba 1.468 GWh para un dia de ~700). La energia de un cuarto es MW x 0,25 h.
    # Cada punto necesita su FECHA: «ultimo» por orden de aparicion daba las 13:30 cuando el
    # fichero se descargo a esa hora, y el visor lo pintaba como «generando ahora».
    def _ts(pt):
        if not pt.get("inicio") or not pt.get("posicion"):
            return None
        try:
            t0 = datetime.datetime.fromisoformat(pt["inicio"].replace("Z", "+00:00"))
        except ValueError:
            return None
        m = re.match(r"PT(\d+)M", pt.get("resolucion") or "PT15M")
        paso = int(m.group(1)) if m else 15
        return t0 + datetime.timedelta(minutes=paso * (pt["posicion"] - 1))

    ultimo, ultimo_t, acumulado, cuartos = {}, {}, {}, {}
    for f in filas:
        t = f.get("tipo")
        if not t or f.get("valor") is None:
            continue
        v = float(f["valor"])
        acumulado[t] = acumulado.get(t, 0.0) + v * 0.25
        cuartos[t] = cuartos.get(t, 0) + 1
        ts = _ts(f)
        if ts is None or t not in ultimo_t or ultimo_t[t] is None or ts >= ultimo_t[t]:
            ultimo[t] = v
            ultimo_t[t] = ts

    # la hora del último cuarto REAL, en hora de Madrid, y cuántos minutos tiene encima
    hora_ultimo = None
    try:
        ts_max = max([x for x in ultimo_t.values() if x], default=None)
        if ts_max:
            try:
                import zoneinfo
                ts_max = ts_max.astimezone(zoneinfo.ZoneInfo("Europe/Madrid"))
            except Exception:
                pass
            hora_ultimo = ts_max
    except ValueError:
        hora_ultimo = None
    edad_min = None
    if hora_ultimo:
        try:
            ahora = datetime.datetime.now(hora_ultimo.tzinfo) if hora_ultimo.tzinfo \
                    else datetime.datetime.now()
            edad_min = int((ahora - hora_ultimo).total_seconds() // 60)
        except Exception:
            edad_min = None
    total_dia = sum(acumulado.values()) or 1.0

    # capacidad instalada por tecnologia, para el factor de carga y la estimacion por planta
    capacidad = {}
    ruta_p = os.path.join(DEST, "plantas.geojson")
    if os.path.exists(ruta_p):
        for f in json.load(open(ruta_p, encoding="utf-8"))["features"]:
            pr = f.get("properties") or {}
            tec = (pr.get("technology_normalized") or "").lower()
            n = pr.get("installed_capacity_mw")
            if not tec or n is None:
                continue
            try:
                capacidad[tec] = capacidad.get(tec, 0.0) + float(n)
            except (TypeError, ValueError):
                continue

    # un código desconocido no se publica como "B25": se agrupa por el nombre visible y los
    # sumandos de la misma tecnología (B03 y B05 son las dos «carbón») se suman en una fila
    def _nombre(cod):
        return PSR.get(cod, "Otras")
    nu, ne, nc = {}, {}, {}
    for c, v in ultimo.items():
        nu[_nombre(c)] = nu.get(_nombre(c), 0.0) + v
    for c, v in acumulado.items():
        ne[_nombre(c)] = ne.get(_nombre(c), 0.0) + v
    for c, v in cuartos.items():
        nc[_nombre(c)] = nc.get(_nombre(c), 0) + v
    acumulado, ultimo, cuartos = ne, nu, nc

    techs = [{"codigo": t, "nombre": t,
              "mwh": round(acumulado[t], 1),
              "pct": round(100 * acumulado[t] / total_dia, 2),
              "ultimo_mw": round(ultimo[t], 1),
              "cuartos": cuartos[t],
              "horas": round(cuartos[t] * 0.25, 2),
              # factor de carga: energia producida / (potencia instalada x horas transcurridas)
              "factor_carga": None}
             for t in sorted(acumulado, key=lambda x: -acumulado[x])]

    # emparejar tecnologia ENTSO-E con la de plantas.geojson y calcular factor de carga
    # nombres reales de technology_normalized en plantas.geojson
    EQUIV = {"eólica terrestre": "wind", "eólica marina": "wind", "eolica terrestre": "wind",
             "solar fotovoltaica": "solar_pv", "solar térmica": "solar_thermal",
             "hidro embalse": "hydro", "hidro fluyente": "hydro", "hidro bombeo": "pumped_hydro",
             "nuclear": "nuclear", "gas natural": "ccgt", "carbón": "coal",
             "biomasa": None, "residuos": None, "otras": "other"}
    for t in techs:
        clave = EQUIV.get(t["nombre"].lower())
        cap = capacidad.get(clave) if clave else None
        if cap and t["horas"]:
            mw_medio = t["mwh"] / t["horas"]
            t["capacidad_mw"] = round(cap, 1)
            t["factor_carga"] = round(100 * mw_medio / cap, 1)
            t["mw_medio"] = round(mw_medio, 1)

    salida = {
        "fuente": "ENTSO-E Transparency · A75",
        "url": "https://web-api.tp.entsoe.eu/api",
        "documento": "A75 · Actual generation per production type",
        "dominio": ES,
        "fecha": hoy.isoformat(),
        "resolucion": "PT15M",
        "puntos": len(filas),
        "hora_ultimo": hora_ultimo.strftime("%H:%M") if hora_ultimo else None,
        "edad_min": edad_min,
        "series": len(acumulado),
        "total_mwh": round(total_dia, 1),
        "tecnologias": techs,
        "descargado": datetime.datetime.now().isoformat(timespec="seconds"),
        "unidad": "MWh (MW del cuarto x 0,25 h)",
        "capacidad_tecnologia_mw": {k: round(v, 1) for k, v in capacidad.items()},
        "nota": ("No existe generacion por planta en abierto: ENTSO-E A73 responde «No matching "
                 "data found» para Espana. Lo mas fino que hay es esto, por tecnologia. Si el dia "
                 "esta en curso, faltan cuartos: mirar `cuartos` por tecnologia."),
    }
    json.dump(salida, open(os.path.join(DEST, "entsoe_mix.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("  A75 %s · %d puntos · %.1f GWh" % (hoy, len(filas), total_dia / 1000))
    for t in techs[:8]:
        print("   %-22s %8.1f GWh  %5.1f%%" % (t["nombre"], t["mwh"] / 1000, t["pct"]))
    return salida


def main():
    ap = argparse.ArgumentParser(description="ENTSO-E Transparency")
    ap.add_argument("--probar", action="store_true")
    ap.add_argument("--dia", metavar="YYYY-MM-DD")
    ap.add_argument("--unidades", metavar="YYYY-MM-DD")
    ap.add_argument("--precio", metavar="YYYY-MM-DD", help="A44, contraste con OMIE")
    ap.add_argument("--prevision", metavar="YYYY-MM-DD", help="A71 y A69")
    ap.add_argument("--mix", nargs="?", const="hoy", metavar="YYYY-MM-DD",
                    help="A75: generacion por tecnologia cada 15 min")
    a = ap.parse_args()
    if a.probar:
        probar()
    elif a.dia:
        dia(a.dia)
    elif a.unidades:
        unidades(a.unidades)
    elif a.precio:
        precio(a.precio)
    elif a.prevision:
        prevision(a.prevision)
    elif a.mix:
        mix(None if a.mix == "hoy" else a.mix)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
