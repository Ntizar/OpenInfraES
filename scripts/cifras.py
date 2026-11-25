# -*- coding: utf-8 -*-
"""Regenera las cifras de la prosa de los documentos desde el estado real del proyecto.

Problema P1 de la auditoría: el README decía 29 capas, su propia tabla 48 y la biblioteca 28,
mientras el visor tenía 52 y el catálogo 68. Tres universos distintos y ninguna cifra escrita a
mano coincidía con lo medido.

Aquí no hay una cuarta cifra: se cuentan las cosas donde están y se reescriben los documentos.

    python scripts/cifras.py          # reescribe y muestra qué cambió
    python scripts/cifras.py --check  # solo comprueba; rc=1 si algo está desfasado (para el CI)

Universos que se miden, y no se mezclan (la auditoría los separa a propósito):

  capas del visor    objetos del array CAPAS de index.html
  grupos             valores distintos de `grupo` en ese array
  objetos por grupo  features de los ficheros que usa el grupo, sin contar dos veces el mismo
                     fichero (hay capas que son dos filtros del mismo GeoJSON: 400 y 220 kV)
  entradas catálogo  claves de datos/fuentes.json
  organismos         organismos canónicos de datos/catalogo.json
"""
import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")

INICIO_TABLA = "<!-- CIFRAS-GRUPOS:INICIO (lo reescribe scripts/cifras.py) -->"
FIN_TABLA = "<!-- CIFRAS-GRUPOS:FIN -->"


def leer_array_capas(html):
    """Capas del array `CAPAS`, aislando cada objeto de primer nivel por conteo de llaves.

    El cierre del array NO se busca con `html.index("];")`: ese es el cierre de la primera
    llamada multilínea que aparezca, el error que ya enterró un bloque de código dentro de
    otra función.
    """
    i = html.index("const CAPAS = [")
    j = html.index("[", i)
    capas, buf, ll = [], "", 0
    for k in range(j + 1, len(html)):
        ch = html[k]
        if ch == "{":
            ll += 1
            if ll == 1:
                buf = "{"
                continue
        elif ch == "}":
            ll -= 1
            if ll == 0:
                capas.append({
                    "id": (re.search(r'id:"([^"]+)"', buf) or [None, ""])[1],
                    "grupo": (re.search(r'grupo:"([^"]+)"', buf) or [None, ""])[1],
                    "fichero": (re.search(r'fichero:"([^"]+)"', buf) or [None, None])[1],
                    "on": bool(re.search(r"\bon:true", buf)),
                })
                buf = ""
                continue
        elif ch == "]" and ll == 0:
            break                      # cierre del array CAPAS, ya fuera de todo objeto
        if ll >= 1:
            buf += ch
    return [c for c in capas if c["id"]]


def _features_fichero(ruta_rel):
    """Cuenta features de un GeoJSON del repositorio (la ruta que la capa declara, no una inventada)."""
    ruta = os.path.join(RAIZ, ruta_rel.replace("/", os.sep))
    if not os.path.exists(ruta):
        return None
    try:
        return len(json.load(open(ruta, encoding="utf-8")).get("features", []))
    except Exception:
        return None


def objetos_por_grupo(capas, fuentes):
    """Objetos de cada grupo contando UNA vez cada fichero.

    `l400` y `l220` son dos capas del mismo `simplificado/lineas_hv.geojson`; sumarlas por capa
    duplica la red de transporte. Igual con las cuatro capas de `plantas.geojson`.
    """
    grupos = {}
    for c in capas:
        g = grupos.setdefault(c["grupo"], {"capas": 0, "ficheros": set()})
        g["capas"] += 1
        if c["fichero"]:
            g["ficheros"].add(c["fichero"])

    cache = {}
    salida = []
    for nombre, g in grupos.items():
        total = 0
        for f in g["ficheros"]:
            if f not in cache:
                n = None
                for cid in [c["id"] for c in capas if c["fichero"] == f]:
                    if cid in fuentes and fuentes[cid].get("features"):
                        n = fuentes[cid]["features"]
                        break
                if n is None:
                    n = _features_fichero(f)
                cache[f] = n or 0
            total += cache[f]
        salida.append((nombre, g["capas"], total))
    return salida


def medidas():
    html = open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read()
    capas = leer_array_capas(html)

    fuentes = json.load(open(os.path.join(DATOS, "fuentes.json"), encoding="utf-8"))
    cat = fuentes.get("capas", {})

    organismos = 0
    ruta_cat = os.path.join(DATOS, "catalogo.json")
    if os.path.exists(ruta_cat):
        c = json.load(open(ruta_cat, encoding="utf-8"))
        organismos = len({v["organismo"] for v in c.get("capas", {}).values()})

    return {
        "capas": len(capas),
        "grupos": len({c["grupo"] for c in capas}),
        "entradas": len(cat),
        "organismos": organismos,
        "detalle": objetos_por_grupo(capas, cat),
    }


def _miles(n):
    return format(n, ",").replace(",", ".")


def tabla_grupos(v):
    filas = ["| Grupo | Capas | Objetos |", "|---|---:|---:|"]
    for nombre, n, obj in v["detalle"]:
        filas.append("| **%s** | %d | %s |" % (nombre, n, _miles(obj)))
    filas.append("| **Total** | **%d** | **%s** |" % (v["capas"], _miles(sum(o for _, _, o in v["detalle"]))))
    return "\n".join(filas)


# cada patrón tiene que casar con lo que hay escrito; el grupo 2 es la cifra vieja y el 3 lo que
# viene detrás (para no comerse la frase)
PATRONES = [
    # README, cabecera de capas
    (r"(\*\*)(\d+)( capas en \d+ grupos temáticos\*\*)",
     lambda m, v: f"{m.group(1)}{v['capas']} capas en {v['grupos']} grupos temáticos**"),
    (r"(Con )(\d+)( capas en \d+\n)", lambda m, v: f"{m.group(1)}{v['capas']} capas en {v['grupos']}\n"),
    # tablas de estado
    (r"(\| Capas en el visor \| \*\*)(\d+)(\*\* \|)",
     lambda m, v: f"{m.group(1)}{v['capas']}{m.group(3)}"),
    # README, el catálogo citado en prosa: «—N entradas, incluidas las que no son capa—»
    (r"(—)(\d+)( entradas, incluidas)", lambda m, v: f"{m.group(1)}{v['entradas']}{m.group(3)}"),
    (r"(\| Grupos temáticos \| \*\*)(\d+)(\*\*)",
     lambda m, v: f"{m.group(1)}{v['grupos']}{m.group(3)}"),
    (r"(\| Capas documentadas en `fuentes.json` \| \*\*)(\d+)(\*\* \|)",
     lambda m, v: f"{m.group(1)}{v['entradas']}{m.group(3)}"),
    (r"(\| Organismos citados \| \*\*)(\d+)(\*\*)",
     lambda m, v: f"{m.group(1)}{v['organismos']}{m.group(3)}"),
    # PROYECTO, titular: «**99 capas en 17 grupos.**»
    (r"(\*\*)(\d+)( capas en \d+ grupos\.\*\*)",
     lambda m, v: f"{m.group(1)}{v['capas']} capas en {v['grupos']} grupos.**"),
    # biblioteca
    (r"(\*\*)(\d+)( capas en el visor\*\* y \*\*)(\d+)( entradas documentadas\*\*)",
     lambda m, v: f"{m.group(1)}{v['capas']} capas en el visor** y **{v['entradas']} entradas documentadas**"),
]

DOCS = ["README.md", os.path.join("docs", "BIBLIOTECA.md"), os.path.join("docs", "PROYECTO.md")]


def main():
    solo_check = "--check" in sys.argv
    v = medidas()
    print("  medido: %d capas · %d grupos · %d entradas de catálogo · %d organismos" % (
        v["capas"], v["grupos"], v["entradas"], v["organismos"]))

    cambios = 0
    desfases = []
    for doc in DOCS:
        ruta = os.path.join(RAIZ, doc)
        if not os.path.exists(ruta):
            continue
        texto = open(ruta, encoding="utf-8").read()
        nuevo = texto

        # la tabla de grupos se regenera ENTERA entre sus marcas: sumar a mano los objetos de cada
        # grupo es lo que dejó el 18.292 del README frente a los 75.130 que salen de contar
        if INICIO_TABLA in nuevo and FIN_TABLA in nuevo:
            ini = nuevo.index(INICIO_TABLA) + len(INICIO_TABLA)
            fin = nuevo.index(FIN_TABLA)
            nueva_tabla = "\n" + tabla_grupos(v) + "\n"
            if nuevo[ini:fin] != nueva_tabla:
                if solo_check:
                    desfases.append("%s: tabla de grupos desfasada" % doc)
                nuevo = nuevo[:ini] + nueva_tabla + nuevo[fin:]
                cambios += 1

        for patron, construir in PATRONES:
            for m in list(re.finditer(patron, nuevo)):
                reemplazo = construir(m, v)
                if reemplazo != m.group(0):
                    if solo_check:
                        desfases.append("%s: %r -> %r" % (doc, m.group(0)[:60], reemplazo[:60]))
                    nuevo = nuevo.replace(m.group(0), reemplazo, 1)
                    cambios += 1

        if not solo_check and nuevo != texto:
            open(ruta, "w", encoding="utf-8").write(nuevo)
            print("  %-26s actualizado" % doc)

    if solo_check:
        if desfases:
            print("  DESFASADO (%d):" % len(desfases))
            for d in desfases[:10]:
                print("   ", d)
            return 1
        print("  cifras coherentes")
        return 0

    print("  %d cifras reescritas" % cambios)
    return 0


if __name__ == "__main__":
    sys.exit(main())
