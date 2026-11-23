# -*- coding: utf-8 -*-
"""AEMET · avisos meteorológicos CON geometría (zonas Meteoalerta).

Meteoalarm daba los avisos sin coordenadas. AEMET sí publica las **zonas de aviso como polígonos**,
sin clave: en la página de avisos hay un enlace a un `tar.gz` de GeoJSON que se regenera cada hora.

    https://www.aemet.es/es/eltiempo/prediccion/avisos
      -> /es/geojson/download/avisos/geojson_<epoch>.tar.gz

**Esquema vigente (2026-11-23):** el tar ya no trae `r_D+0_*` con datos; trae una rejilla de ficheros
horarios

    av_hh_<elaborado>_<penbal|can>_<AAAAMMDDHH><CET|WET>_<epoch>.geojson

donde `AAAAMMDDHH` es la hora local de validez. Los de menos de 300 bytes van vacíos (esa área no
tiene avisos a esa hora). Además, cada aviso viene en una de dos familias de campos:

    *_COCO   catálogo antiguo (costeros, lluvias...)   Sev_COCO / Onset_COCO / Expire_COCO
    *_NENV   avisos de Meteoalerta (nevadas, viento)   Sev_NENV / Onset_NENV / Expire_NENV

`Nivel_COCO` / `Nivel_NENV` son **códigos**, no el nivel: 3 = amarillo. El nivel se lee del texto
(`Sev_*`, `Resum_*`), nunca del número. Los `r_D+N_*` se siguen aceptando como respaldo por si AEMET
vuelve atrás.

La capa del visor son las zonas con aviso **vigente o previsto en las próximas 48 h**; cada zona sale
una vez, pintada por su nivel máximo, con la lista de avisos dentro.

Si el esquema cambia otra vez, el script **falla sin escribir**: el fichero anterior y su fecha se
quedan, y el fallo se ve en el paso, en vez de publicar una capa vacía que rompa el validador.

    python scripts/aemet_geo.py
"""
import datetime
import io
import json
import os
import re
import tarfile
import tempfile
import urllib.request

try:
    from zoneinfo import ZoneInfo
    _MADRID = ZoneInfo("Europe/Madrid")
except Exception:                                   # sin tzdata: se asume CET fijo
    _MADRID = datetime.timezone(datetime.timedelta(hours=1))

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos")
PAGINA = "https://www.aemet.es/es/eltiempo/prediccion/avisos"
UA = {"User-Agent": "Mozilla/5.0 (compatible; OpenInfraES/1.0)",
      "Accept-Language": "es-ES,es;q=0.9"}

VENTANA_H = 48          # horas de antelación que se publican como «previsto»

# niveles de Meteoalerta: el texto manda, el número de Nivel_* es un código (3 = amarillo)
NIVEL = {1: ("amarillo", "#facc15"), 2: ("naranja", "#fb923c"), 3: ("rojo", "#ef4444")}
POR_TEXTO = {"amarillo": 1, "naranja": 2, "rojo": 3}

FENOMENOS = {
    "1": "Viento", "2": "Lluvia", "3": "Nieve", "4": "Tormenta",
    "5": "Niebla", "6": "Rachas de viento", "7": "Polvo en suspensión",
    "8": "Aludes", "9": "Temperaturas máximas", "10": "Temperaturas mínimas",
    "11": "Riberas y desbordamientos", "12": "Incendios forestales",
    "13": "Fenómenos costeros", "14": "Tormenta tropical",
}


def baja(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def redondea(geo, dec=4):
    if isinstance(geo, list):
        return [redondea(x, dec) for x in geo]
    if isinstance(geo, float):
        return round(geo, dec)
    return geo


def iso(valor):
    """ISO 8601 -> datetime con zona. Las fechas sin zona se toman como hora de Madrid."""
    if not valor or not isinstance(valor, str):
        return None
    try:
        d = datetime.datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=_MADRID)


def familias(p):
    """Familias de campos de aviso presentes en un feature: COCO, NENV, ..."""
    return sorted({m.group(1) for k in p
                   for m in [re.match(r"^(?:Onset|Expire)_([A-Z]+)$", k)] if m})


def nivel_texto(texto):
    t = (texto or "").lower()
    for palabra, n in POR_TEXTO.items():
        if "nivel %s" % palabra in t:
            return n
    return POR_TEXTO.get((texto or "").strip().lower())


def nivel_de(p, fam):
    """Nivel 1-3 de un aviso. El texto (`Sev_*` o el resumen) manda; Nivel_* es un código."""
    n = nivel_texto(p.get("Sev_" + fam))
    if n:
        return n
    return nivel_texto(p.get("Resum_" + fam)) or nivel_texto(p.get("Des_" + fam))


def avisos_de(p):
    """Lista de avisos del feature, sea cual sea la familia de campos que use AEMET."""
    salida = []
    for fam in familias(p):
        nivel = nivel_de(p, fam)
        if not nivel:
            continue
        salida.append({
            "familia": fam,
            "fenomeno": (p.get(fam) or "").strip(),
            "nivel": nivel,
            "nivel_txt": NIVEL[nivel][0],
            "descripcion": (p.get("Des_" + fam) or p.get("Resum_" + fam) or "")[:260],
            "desde": p.get("Onset_" + fam) or "",
            "hasta": p.get("Expire_" + fam) or "",
            "probabilidad": p.get("Prb_" + fam) or "",
            "certeza": p.get("Cer_" + fam) or "",
        })
    # esquema antiguo: lista anidada Avis_COCO
    for a in p.get("Avis_COCO") or []:
        if not isinstance(a, dict):
            continue
        try:
            nivel = int(a.get("nivel_num") or 0)
        except (TypeError, ValueError):
            nivel = 0
        if nivel not in NIVEL:
            nivel = nivel_texto(a.get("nivel") or a.get("nivel_txt") or "")
        if not nivel:
            continue
        salida.append({
            "familia": "COCO",
            "fenomeno": FENOMENOS.get(str(a.get("fenomeno") or ""), a.get("parametro") or ""),
            "nivel": nivel,
            "nivel_txt": NIVEL[nivel][0],
            "descripcion": (a.get("descripcion") or "")[:260],
            "desde": a.get("onset_local") or "",
            "hasta": a.get("expires_local") or "",
            "probabilidad": a.get("probabilidad") or "",
            "certeza": a.get("certeza") or "",
        })
    return salida


def estado(a, ahora):
    """(¿dentro de ventana?, estado) de un aviso respecto a ahora."""
    ini = iso(a["desde"])
    fin = iso(a["hasta"])
    if fin and fin < ahora:
        return False, "caducado"
    if ini and ini > ahora + datetime.timedelta(hours=VENTANA_H):
        return False, "fuera de ventana"
    if ini and ini > ahora:
        return True, "previsto"
    return True, "vigente"                 # vigente, o sin fechas con las que discutir


def escribe(ruta, datos, indent=1):
    """Escritura atómica: o queda el fichero nuevo entero, o queda el viejo."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=indent)
        os.replace(tmp, ruta)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    ahora = datetime.datetime.now(datetime.timezone.utc)

    html = baja(PAGINA).decode("iso-8859-15", "replace")
    m = re.search(r"(?:https://www\.aemet\.es)?/es/geojson/download/avisos/geojson_\d+\.tar\.gz", html)
    if not m:
        raise SystemExit("no encuentro el enlace del geojson de avisos en la pagina de AEMET "
                         "(el fichero anterior se queda como estaba)")
    url = m.group(0)
    if url.startswith("/"):
        url = "https://www.aemet.es" + url
    print("  %s" % url)

    tar = baja(url, timeout=180)
    print("  %.1f MB" % (len(tar) / 1e6))

    horarios, diarios = [], []
    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as tf:
        for mi in tf.getmembers():
            n = mi.name
            if not n.endswith(".geojson"):
                continue
            if n.startswith("av_hh_"):
                horarios.append(mi)
            elif n.startswith("r_D+"):
                diarios.append(mi)

    if not horarios and not diarios:
        raise SystemExit("el tar de AEMET no trae ni av_hh_* ni r_D+*: esquema desconocido "
                         "(el fichero anterior se queda como estaba)")

    # la rejilla horaria es la buena; el resumen diario queda como respaldo
    elegidos = [mi for mi in horarios if mi.size >= 300] or \
               [mi for mi in diarios if mi.size >= 300]
    esquema = "av_hh" if horarios else "r_D+"

    # una zona se repite en decenas de ficheros horarios: se agrupa por código de zona
    zonas, ficheros, elaborado = {}, [], ""
    vistos, caducados, fuera = set(), 0, 0

    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as tf:
        for mi in elegidos:
            try:
                fc = json.loads(tf.extractfile(mi).read().decode("utf-8", "replace"))
            except Exception:
                continue
            ficheros.append(mi.name)
            mm = re.search(r"(?:^|_)(?:av_hh|r_D\+\d)_(\d{14})_", mi.name)
            if mm and not elaborado:
                elaborado = mm.group(1)
            for ft in fc.get("features", []):
                p = ft.get("properties") or {}
                for a in avisos_de(p):
                    clave = (p.get("COD_Z") or p.get("Nombre_zona") or "",
                             a["familia"], a["desde"], a["hasta"], a["descripcion"][:80])
                    if clave in vistos:
                        continue
                    dentro, est = estado(a, ahora)
                    if not dentro:
                        if est == "caducado":
                            caducados += 1
                        else:
                            fuera += 1
                        continue
                    vistos.add(clave)
                    cod = p.get("COD_Z") or p.get("Nombre_zona") or "?"
                    z = zonas.get(cod)
                    if z is None:
                        z = zonas[cod] = {
                            "type": "Feature",
                            "geometry": redondea(ft.get("geometry")),
                            "properties": {
                                "zona": p.get("Nombre_zona") or "",
                                "provincia": p.get("Provincia") or "",
                                "codigo": cod,
                                "nivel": 0, "nivel_txt": "", "estado": "",
                                "fenomenos": "", "avisos": [],
                            },
                        }
                    z["properties"]["avisos"].append({k: a[k] for k in
                                                      ("fenomeno", "nivel", "nivel_txt", "descripcion",
                                                       "desde", "hasta", "probabilidad", "certeza")})
                    if a["nivel"] > z["properties"]["nivel"]:
                        z["properties"]["nivel"] = a["nivel"]
                        z["properties"]["nivel_txt"] = a["nivel_txt"]
                    if not z["properties"]["estado"] or est == "vigente":
                        z["properties"]["estado"] = est

    feats = list(zonas.values())
    for z in feats:
        pr = z["properties"]
        pr["fenomenos"] = ", ".join(sorted({a["fenomeno"] for a in pr["avisos"] if a["fenomeno"]}))

    escribe(os.path.join(DEST, "aemet_zonas.geojson"),
            {"type": "FeatureCollection", "features": feats}, indent=None)

    por_nivel, por_estado = {}, {}
    for f in feats:
        p = f["properties"]
        por_nivel[p["nivel_txt"]] = por_nivel.get(p["nivel_txt"], 0) + 1
        por_estado[p["estado"]] = por_estado.get(p["estado"], 0) + 1

    escribe(os.path.join(DEST, "aemet_zonas_recibo.json"), {
        "fuente": "AEMET", "dataset": "Meteoalerta — zonas de aviso",
        "url": PAGINA, "url_geojson": url,
        "licencia": "© AEMET. Reproducción autorizada citando a AEMET como autora.",
        "elaborado": elaborado,
        "descargado": datetime.datetime.now().isoformat(timespec="seconds"),
        "esquema": esquema,
        "ventana_horas": VENTANA_H,
        "ficheros": ficheros,
        "features": len(feats),
        "por_nivel": por_nivel,
        "por_estado": por_estado,
        "descartados": {"caducados": caducados, "fuera_de_ventana": fuera},
        "geometria": True,
        "nota": ("Zonas con aviso vigente o previsto en las próximas %d h, como polígonos. "
                 "El nivel sale del texto Sev_*/Resum_*: Nivel_COCO es un código (3 = amarillo). "
                 "Ficheros de menos de 300 bytes = sin avisos en esa área y hora." % VENTANA_H),
    })

    print("  %d zonas · esquema %s · elaborado %s · %d vigentes, %d previstas"
          % (len(feats), esquema, elaborado or "?",
             por_estado.get("vigente", 0), por_estado.get("previsto", 0)))
    for k, v in sorted(por_nivel.items()):
        print("   %-10s %d" % (k, v))


if __name__ == "__main__":
    main()
