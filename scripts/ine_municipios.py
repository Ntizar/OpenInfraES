#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renta municipal del INE para la ficha del visor (atlas de distribución de renta).

Baja de la API pública del INE (wstempus, sin clave) la renta media y mediana de cada municipio,
cruzada por el código INE de 5 dígitos que ya llevan `datos/municipios.geojson` y las fichas.

Por qué congelado y no el MCP del INE en vivo: el visor es estático y no puede depender de cinco
llamadas encadenadas de ~1,5 s. El MCP sirve para que un agente pregunte; esto deja el dato fechado
y con recibo para el mapa.

    python3 scripts/ine_municipios.py              # usa la caché de resultados si existe
    python3 scripts/ine_municipios.py --todo       # vuelve a mirar todas las tablas
    python3 scripts/ine_municipios.py --limite 4   # sólo 4 tablas (prueba)
    python3 scripts/ine_municipios.py --si-caduca  # sale en segundos si el año ya está (cron)

Salida:
    datos/ine/municipios.json              {"municipios": {"02001": {...}}, "indicadores": {...}}
    datos/ine/_recibo_municipios.json

Dos trampas medidas:

1. Una tabla grande devuelve `{"status": "No puede mostrarse por restricciones de volumen"}` si no se
   le pasa `p=<año>`.
2. **La caché de los datos crudos no cabe.** Guardar las 540 respuestas de `DATOS_TABLA` son 2,7 GB:
   llenó los 20 GB del disco de la VM y el proceso murió con `OSError: [Errno 28] No space left on
   device`. Aquí sólo se cachea lo ya extraído (~20 KB por tabla) y el mapa nombre→código.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
SALIDA = os.path.join(DATOS, "ine")
CACHE = os.path.join(SALIDA, ".cache")
API = "https://servicios.ine.es/wstempus/js/ES"
UA = {"User-Agent": "Mozilla/5.0 (compatible; OpenInfraES/1.0)", "Accept": "application/json"}

OP_RENTA = 353          # Atlas de distribución de renta de los hogares
ANYO = int(sys.argv[sys.argv.index("--anyo") + 1]) if "--anyo" in sys.argv else time.gmtime().tm_year - 1
ESPACIO_MIN_MB = 400    # por debajo de esto, mejor parar que llenar el disco otra vez

# El orden importa: «mediana de la renta por unidad de consumo» contiene «renta … por unidad de
# consumo». Los nombres son los que publica el INE (sin «neta» en la unidad de consumo).
INDICADORES = [
    ("mediana de la renta por unidad de consumo", "renta_uc_mediana", "Mediana por unidad de consumo", "€/año"),
    ("media de la renta por unidad de consumo", "renta_uc_media", "Media por unidad de consumo", "€/año"),
    ("renta neta media por persona", "renta_persona", "Renta neta media por persona", "€/año"),
    ("renta neta media por hogar", "renta_hogar", "Renta neta media por hogar", "€/año"),
    ("renta bruta media por persona", "renta_bruta_persona", "Renta bruta media por persona", "€/año"),
    ("renta bruta media por hogar", "renta_bruta_hogar", "Renta bruta media por hogar", "€/año"),
]


def get(ruta, intentos=3):
    url = API + ruta
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as f:
                return json.loads(f.read().decode("utf-8"))
        except Exception:
            if i == intentos - 1:
                return None
            time.sleep(2 * (i + 1))


def libre_mb():
    st = os.statvfs(SALIDA)
    return st.f_bavail * st.f_frsize / 1e6


def limpia(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def cache_leer(nombre):
    p = os.path.join(CACHE, nombre)
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def cache_escribir(nombre, dato):
    try:
        os.makedirs(CACHE, exist_ok=True)
        p = os.path.join(CACHE, nombre)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(dato, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(p + ".tmp", p)
    except OSError as e:
        print(f"  aviso: no se pudo cachear {nombre} ({e})", flush=True)


def indicador_de(nombre):
    bajo = limpia(nombre).lower()
    for clave, campo, _etiqueta, _unidad in INDICADORES:
        if clave in bajo:
            return campo
    return None


def una_tabla(tid, todo):
    """Una tabla provincial: {codigo: {campo: valor}}. No retiene ni cachea la respuesta cruda."""
    if not todo:
        guardado = cache_leer(f"res-{tid}.json")
        if guardado is not None:
            return guardado

    mapa = None if todo else cache_leer(f"mapa-{tid}.json")
    if mapa is None:
        mapa = {}
        grupos = get(f"/GRUPOS_TABLA/{tid}")
        if isinstance(grupos, list):
            for g in grupos:
                if "territorial" not in limpia(g.get("Nombre", "")).lower():
                    continue
                for v in (get(f"/VALORES_GRUPOSTABLA/{tid}/{g['Id']}") or []):
                    cod = str(v.get("Codigo") or "")
                    # 5 dígitos = municipio: ni sección censal ni distrito ni provincia.
                    if len(cod) == 5 and cod.isdigit() and not re.search(r"distrito|secci", v.get("Nombre", ""), re.I):
                        mapa[limpia(v.get("Nombre"))] = cod
        if mapa:
            cache_escribir(f"mapa-{tid}.json", mapa)

    datos = get(f"/DATOS_TABLA/{tid}?nult=1&p={ANYO}")
    if not isinstance(datos, list) or not datos:
        return {}

    salida = {}
    for s in datos:
        nombre = s.get("Nombre") or ""
        cod = mapa.get(limpia(nombre.split(".")[0]))
        if not cod:
            continue
        campo = indicador_de(nombre)
        if not campo:
            continue
        d = (s.get("Data") or [{}])[-1]
        if d.get("Secreto") or d.get("Valor") is None:
            continue
        salida.setdefault(cod, {})[campo] = round(float(d["Valor"]))
        salida[cod]["_anyo"] = d.get("Anyo")
    del datos
    if salida:
        cache_escribir(f"res-{tid}.json", salida)
    return salida


def main():
    todo = "--todo" in sys.argv
    limite = int(sys.argv[sys.argv.index("--limite") + 1]) if "--limite" in sys.argv else None

    # `--si-caduca`: el cron lo llama cada mes y sólo hace trabajo si el dato del año está viejo.
    # La renta del INE es anual; volver a bajar 540 tablas porque sí es tiempo tirado.
    if "--si-caduca" in sys.argv:
        ruta_r = os.path.join(SALIDA, "_recibo_municipios.json")
        if os.path.exists(ruta_r):
            try:
                r = json.load(open(ruta_r, encoding="utf-8"))
                if (r.get("anyo") or 0) >= ANYO - 1 and (r.get("municipios") or 0) >= 7000:
                    print("al día: renta " + str(r["anyo"]) + " con " + str(r["municipios"]) + " municipios")
                    return 0
            except Exception:
                pass

    t0 = time.time()
    os.makedirs(SALIDA, exist_ok=True)
    if libre_mb() < ESPACIO_MIN_MB:
        print(f"ABORTA: quedan {libre_mb():.0f} MB libres (mínimo {ESPACIO_MIN_MB})", flush=True)
        return 2

    ids = [t["Id"] for t in (get(f"/TABLAS_OPERACION/{OP_RENTA}") or [])]
    if limite:
        ids = ids[:limite]
    print(f"tablas a mirar: {len(ids)} · año {ANYO} · {libre_mb():.0f} MB libres", flush=True)

    municipios, usadas, vacias = {}, 0, 0
    with ThreadPoolExecutor(max_workers=4) as ex:          # 4: la VM tiene 3,9 GB y sin swap
        for i, trozo in enumerate(ex.map(lambda t: una_tabla(t, todo), ids), 1):
            if trozo:
                usadas += 1
                for cod, campos in trozo.items():
                    municipios.setdefault(cod, {}).update(campos)
            else:
                vacias += 1
            if i % 50 == 0:
                print(f"  {i}/{len(ids)} tablas · {len(municipios)} municipios · "
                      f"{time.time()-t0:.0f} s · {libre_mb():.0f} MB libres", flush=True)

    if not municipios:
        print("SIN DATOS: ninguna tabla con municipios para ese año (mira --anyo)", flush=True)
        return 1

    anyo = max((m.get("_anyo") or 0) for m in municipios.values())
    for m in municipios.values():
        m.pop("_anyo", None)

    salida = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fuente": "INE · Atlas de distribución de renta de los hogares",
        "url": "https://www.ine.es/experimental/atlas/experimental_atlas.htm",
        "anyo": anyo,
        "indicadores": {c: {"etiqueta": e, "unidad": u} for _, c, e, u in INDICADORES},
        "municipios": municipios,
    }
    ruta = os.path.join(SALIDA, "municipios.json")
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(ruta + ".tmp", ruta)

    recibo = {
        "generado": salida["generado"],
        "anyo": anyo,
        "segundos": round(time.time() - t0, 1),
        "tablas_usadas": usadas,
        "tablas_sin_datos": vacias,
        "municipios": len(municipios),
        "con_renta_persona": sum(1 for m in municipios.values() if "renta_persona" in m),
        "bytes": os.path.getsize(ruta),
    }
    with open(os.path.join(SALIDA, "_recibo_municipios.json"), "w", encoding="utf-8") as f:
        json.dump(recibo, f, ensure_ascii=False, indent=1)
    print(json.dumps(recibo, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
