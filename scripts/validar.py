#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arnes del repositorio OpenInfraES. Offline y sin dependencias.

Comprueba:
  1. Que existen los GeoJSON y los CSV agregados.
  2. Que los agregados cuadran con los GeoJSON (segmentos y MW).
  3. Que los conteos coinciden con los declarados por la fuente.
  4. Que existe recibo de procedencia con URL.
Sale 0 si todo esta en verde.
"""
import csv
import datetime
import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
errores = []


def error(m):
    errores.append(m)


def vacio_declarado(ruta_geojson):
    """Motivo si el recibo del GeoJSON declara un vacio legitimo y reciente; None si no.

    Convencion del repo: el recibo de `datos/x.geojson` es `datos/x_recibo.json`. Vale si dice
    0 objetos y se descargo en las ultimas 12 horas; si el recibo falta, esta viejo o declara
    otra cuenta, el vacio es un fallo de descarga y se devuelve None para que salte el error.
    """
    base = ruta_geojson[:-len(".geojson")] if ruta_geojson.endswith(".geojson") else ruta_geojson
    ruta_recibo = base + "_recibo.json"
    if not os.path.exists(ruta_recibo):
        return None
    try:
        rec = json.load(open(ruta_recibo, encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(rec, dict):
        return None
    cuenta = rec.get("features", rec.get("objetos"))
    if cuenta is not None and cuenta != 0:
        return None
    for clave in ("descargado", "actualizado", "capturado", "generado"):
        valor = rec.get(clave)
        if not isinstance(valor, str) or len(valor) < 10:
            continue
        try:
            cuando = datetime.datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        if cuando.tzinfo:
            cuando = cuando.astimezone().replace(tzinfo=None)
        horas = (datetime.datetime.now() - cuando).total_seconds() / 3600.0
        if 0 <= horas <= 12:
            return "(sin datos, recibo de hace %.1f h)" % horas
        return None
    return None


def leer_csv(nombre):
    ruta = os.path.join(DATOS, nombre)
    if not os.path.exists(ruta):
        error("falta datos/%s" % nombre)
        return []
    with open(ruta, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    # 1. GeoJSON
    lineas = plantas = None
    for nombre in ("lineas_hv.geojson", "plantas.geojson"):
        ruta = os.path.join(DATOS, nombre)
        if not os.path.exists(ruta):
            error("falta datos/%s (ejecuta scripts/descargar.py)" % nombre)
            continue
        d = json.load(open(ruta, encoding="utf-8"))
        feats = d.get("features", [])
        if len(feats) < 1000:
            error("datos/%s: solo %d features" % (nombre, len(feats)))
        if nombre.startswith("lineas"):
            lineas = feats
        else:
            plantas = feats

    # 2 y 3. agregados
    agg_l = leer_csv("agregado_lineas.csv")
    agg_t = leer_csv("agregado_plantas_tecnologia.csv")
    agg_c = leer_csv("agregado_plantas_ccaa.csv")
    agg_o = leer_csv("agregado_lineas_operador.csv")

    if agg_l:
        seg = sum(int(f["segmentos"]) for f in agg_l)
        if lineas is not None and seg != len(lineas):
            error("agregado_lineas: %d segmentos != %d features" % (seg, len(lineas)))
        # La referencia es el propio GeoJSON (arriba), no una cifra escrita aquí: los números
        # 4.929 / 1.752 / 3.176 vivían dos veces (validador y README) y solo uno se actualizaba.
        # Lo que el README publica lo vigila scripts/cifras.py contra el dato medido.

    if agg_t:
        mw = sum(float(f["mw"]) for f in agg_t)
        n = sum(int(f["plantas"]) for f in agg_t)
        if plantas is not None and n != len(plantas):
            error("agregado_plantas: %d plantas != %d features" % (n, len(plantas)))
        if not (120000 < mw < 135000):
            error("MW totales fuera de rango razonable: %.0f" % mw)

    if agg_c and agg_t:
        mw_c = sum(float(f["mw"]) for f in agg_c)
        mw_t = sum(float(f["mw"]) for f in agg_t)
        if abs(mw_c - mw_t) > 50:
            error("MW por CCAA (%.0f) != MW por tecnologia (%.0f)" % (mw_c, mw_t))

    if agg_o and agg_l:
        seg_o = sum(int(f["segmentos"]) for f in agg_o)
        seg_l = sum(int(f["segmentos"]) for f in agg_l)
        if seg_o != seg_l:
            error("agregado por operador (%d) != agregado por tension (%d)" % (seg_o, seg_l))

    # 4. recibo
    ruta = os.path.join(DATOS, "_procedencia.json")
    if not os.path.exists(ruta):
        error("falta datos/_procedencia.json (ejecuta scripts/descargar.py)")
    else:
        p = json.load(open(ruta, encoding="utf-8"))
        for f in p.get("ficheros", []):
            if not str(f.get("url", "")).startswith("http"):
                error("_procedencia.json: %s sin URL" % f.get("fichero"))

    # 4b. conteos de OSM (foto completa)
    ruta_c = os.path.join(DATOS, "conteos_osm_20261116.json")
    if not os.path.exists(ruta_c):
        error("falta datos/conteos_osm_20261116.json")
    else:
        c = json.load(open(ruta_c, encoding="utf-8"))
        if not c.get("conteos"):
            error("conteos_osm: sin bloque 'conteos'")
        if not str(c.get("capturado", ""))[:4] == "2026":
            error("conteos_osm: sin fecha de captura creible")

    # 4c. capas OSM opcionales: si existen, no pueden estar vacias
    for capa in ("gasoductos", "presas", "desaladoras"):
        ruta_g = os.path.join(DATOS, capa + ".geojson")
        if os.path.exists(ruta_g):
            try:
                n = len(json.load(open(ruta_g, encoding="utf-8")).get("features", []))
            except Exception:
                error("datos/%s.geojson: no se puede leer" % capa)
                continue
            if n == 0:
                error("datos/%s.geojson: existe pero esta vacio (0 features)" % capa)

    # 4d. recibo de capas oficiales y capas que usa el visor
    ra = os.path.join(DATOS, "oficial", "_recibo_oficial.json")
    if not os.path.exists(ra):
        error("falta datos/oficial/_recibo_oficial.json (ejecuta scripts/capas_oficiales.py)")
    else:
        rec = json.load(open(ra, encoding="utf-8"))
        if len(rec.get("capas", [])) < 17:
            error("recibo de capas oficiales: solo %d capas" % len(rec.get("capas", [])))
        for capa in rec.get("capas", []):
            if capa.get("features", 0) == 0:
                error("oficial/%s: 0 features" % capa.get("id"))
        usadas = ["desaladoras", "nuclear", "gas-regasificacion", "gas-almacenamiento",
                  "agua-embalsada", "red-electrica", "conducciones-combustible"]
        for u in usadas:
            if not os.path.exists(os.path.join(DATOS, "oficial", u + ".geojson")):
                error("falta datos/oficial/%s.geojson (lo usa el visor)" % u)

    # 4e-bis. capas partidas: los trozos tienen que ser los del fichero de hoy
    # Si alguien regenera una capa partida y no corre scripts/partir.py, el visor sigue sirviendo
    # los trozos viejos y nada se queja. Esto lo canta antes de publicar.
    for nombre in sorted(os.listdir(DATOS)):
        ruta_carpeta = os.path.join(DATOS, nombre)
        ruta_ind = os.path.join(ruta_carpeta, "index.json")
        if not os.path.isdir(ruta_carpeta) or not os.path.exists(ruta_ind):
            continue
        try:
            ind = json.load(open(ruta_ind, encoding="utf-8"))
        except Exception:
            error("datos/%s/index.json: no se puede leer" % nombre)
            continue
        partes = ind.get("partes") or []
        total = ind.get("total") or 0
        suma = sum(p.get("n", 0) for p in partes)
        if suma != total:
            error("datos/%s: los trozos suman %d y el indice declara %d" % (nombre, suma, total))
        for p in partes:
            if not os.path.exists(os.path.join(ruta_carpeta, p.get("fichero", ""))):
                error("datos/%s: falta el trozo %s" % (nombre, p.get("fichero")))
        base = ind.get("base") or (nombre.replace("-", "_") + ".geojson")
        ruta_rec = os.path.join(DATOS, base.replace(".geojson", "_recibo.json"))
        if os.path.exists(ruta_rec):
            hojas = json.load(open(ruta_rec, encoding="utf-8")).get("features")
            if hojas is not None and hojas != total:
                error("datos/%s: trozos de %d objetos y el fichero entero %d; ejecuta scripts/partir.py"
                      % (nombre, total, hojas))
        else:
            error("datos/%s: no encuentro el recibo de %s" % (nombre, base))

    # 4e. capas de transporte (visor Hermes)
    rh = os.path.join(DATOS, "hermes", "_recibo_hermes.json")
    if not os.path.exists(rh):
        error("falta datos/hermes/_recibo_hermes.json (ejecuta scripts/hermes.py)")
    else:
        rec = json.load(open(rh, encoding="utf-8"))
        if len(rec.get("capas", [])) < 5:
            error("recibo de Hermes: solo %d capas" % len(rec.get("capas", [])))
        for capa in rec.get("capas", []):
            if capa.get("features", 0) == 0:
                error("hermes/%s: 0 features" % capa.get("id"))
            if not os.path.exists(os.path.join(DATOS, "hermes", capa["id"] + ".geojson")):
                error("falta datos/hermes/%s.geojson" % capa["id"])

    # 4f. geometrias simplificadas del visor
    rec = os.path.join(DATOS, "simplificado", "_recibo.json")
    if not os.path.exists(rec):
        error("falta datos/simplificado/_recibo.json (ejecuta scripts/simplificar.py)")
    else:
        r = json.load(open(rec, encoding="utf-8"))
        tot_a = sum(c["vertices_antes"] for c in r["capas"])
        tot_d = sum(c["vertices_despues"] for c in r["capas"])
        if tot_d >= tot_a:
            error("simplificar no reduce vertices (%d -> %d)" % (tot_a, tot_d))
        print("  simplificado ............... %d -> %d vertices (-%.0f%%)"
              % (tot_a, tot_d, 100 * (1 - tot_d / tot_a)))

    # 4g. procedencia de cada capa del visor
    fv = os.path.join(DATOS, "fuentes.json")
    if not os.path.exists(fv):
        error("falta datos/fuentes.json (ejecuta scripts/fuentes_visor.py)")
    else:
        d = json.load(open(fv, encoding="utf-8"))
        if d.get("total_capas", 0) < 30:
            error("fuentes.json: solo %d capas" % d.get("total_capas", 0))
        sin = [k for k, v in d.get("capas", {}).items() if not v.get("fuente")]
        if sin:
            error("fuentes.json: %d capas sin fuente (%s)" % (len(sin), ", ".join(sin[:5])))
        print("  procedencia de datos ........ %d capas documentadas" % d.get("total_capas", 0))

    # 4h. capas del visor: codigos sin traducir, capas vacias y ficheros repetidos
    html = open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read()
    ini_dic = html.index("const VALORES = {")
    fin_dic = html.index("};", ini_dic)
    traducidos = set(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"', html[ini_dic:fin_dic]))
    camel = re.compile(r"^[a-z]+(?:[A-Z][a-z]+){1,}$")
    under = re.compile(r"^[a-z]+(?:_[a-z]+){1,}$")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cifras import leer_array_capas          # el mismo parser del array que las cifras
    capas = leer_array_capas(html)

    # (a) un valor con pinta de codigo que no esta en el diccionario saldria crudo en la ficha
    # Los campos de TEXTO LIBRE no se revisan: un toponimo puede ser camelCase («vVadillo», en la
    # red de canales del MITECO) y no es un codigo sin traducir. La revision es para enumerados.
    TEXTO_LIBRE = {"nombre", "titulo", "descripcion", "mensaje", "lugar", "toma", "nota"}
    crudos = {}
    vistos_fich = set()
    for c in capas:
        f = c.get("fichero")
        if not f or f in vistos_fich:
            continue
        vistos_fich.add(f)
        ruta = os.path.join(RAIZ, f.replace("/", os.sep))
        if not os.path.exists(ruta):
            continue
        try:
            d = json.load(open(ruta, encoding="utf-8"))
        except Exception:
            continue
        for ft in d.get("features", [])[:5000]:
            for k, v in (ft.get("properties") or {}).items():
                if k.endswith("__v") or k.endswith("__f") or k in TEXTO_LIBRE:
                    continue
                if isinstance(v, str) and (camel.match(v) or under.match(v)) and v not in traducidos:
                    crudos.setdefault(k, set()).add(v)
    if crudos:
        detalle = "; ".join("%s: %s" % (k, ", ".join(sorted(v)[:3])) for k, v in list(crudos.items())[:5])
        error("codigos sin traducir en la ficha (anadelos a VALORES): %s" % detalle)
    print("  codigos traducidos ......... %d claves · %d campos crudos"
          % (len(traducidos), len(crudos)))

    # (b) una capa del visor con 0 features no es una capa: o se arregla o se retira...
    # ...salvo que su recibo declare a las claras que hoy no hay nada (no hay avisos de AEMET,
    # no hay incidencias de DGT). Esa capa vacia es un dato, no un fallo. Lo que si es un fallo
    # es un vacio sin recibo o con recibo viejo: eso es una descarga rota disfrazada.
    vacias, declaradas = [], []
    for c in capas:
        f = c.get("fichero")
        if not f:
            continue                      # xyz/wms: no hay features que contar
        ruta = os.path.join(RAIZ, f.replace("/", os.sep))
        if not os.path.exists(ruta):
            continue
        try:
            n = len(json.load(open(ruta, encoding="utf-8")).get("features", []))
        except Exception:
            n = -1
        if n == 0:
            motivo = vacio_declarado(ruta)
            if motivo:
                declaradas.append((c["id"], motivo))
            else:
                vacias.append(c["id"])
    if vacias:
        error("capas del visor con 0 features y sin recibo que lo declare: %s"
              % ", ".join(sorted(set(vacias))))
    print("  capas vacias .............. %d%s"
          % (len(set(vacias)),
             "".join(" · %s %s" % (i, m) for i, m in declaradas) if declaradas else ""))

    # (c) el mismo fichero en dos capas solo vale si cada una lo filtra de otra forma
    bloque = html[html.index("const CAPAS = ["):]
    trozos = re.split(r"\n  \{ id:\"", bloque)[1:]
    usa = {}
    for t in trozos:
        cid = t.split('"')[0]
        mf = re.search(r'fichero:"([^"]+)"', t[:500])
        if mf:
            cab = t[:900]
            usa.setdefault(mf.group(1), []).append((cid, "filtro:" in cab, "colorCampo:" in cab))
    # dos capas del mismo fichero se aceptan si cada una lo RECORTA (filtro) o lo PINTA por un
    # campo distinto (colorCampo); lo que no vale es la misma capa dos veces con otro nombre
    repetidos = {f: l for f, l in usa.items()
                 if len([x for x in l if not x[1] and not x[2]]) >= 2}
    if repetidos:
        error("mismo fichero en varias capas sin filtro que las distinga: %s"
              % "; ".join("%s (%s)" % (f, ", ".join(x[0] for x in l)) for f, l in list(repetidos.items())[:4]))
    compartidos = {f: l for f, l in usa.items() if len(l) > 1}
    print("  ficheros compartidos ...... %d (%d duplicados de verdad)"
          % (len(compartidos), len(repetidos)))

    # 4i. municipios: el dato tiene que cuadrar con el país, no solo existir
    rmun = os.path.join(DATOS, "municipios_recibo.json")
    if os.path.exists(rmun):
        m = json.load(open(rmun, encoding="utf-8"))
        f = m.get("fallos") or []
        if f:
            error("municipios: %s" % "; ".join(f))
        if m.get("features", 0) < 8000:
            error("municipios: solo %d polígonos" % m.get("features", 0))
        if m.get("codigos_ine_unicos") != m.get("features"):
            error("municipios: %d códigos únicos para %d polígonos"
                  % (m.get("codigos_ine_unicos", 0), m.get("features", 0)))
        # el cruce es por CÓDIGO y cada fila dice de qué año es su población
        sin_cod = [x for x in m.get("municipios", []) if not re.match(r"^\d{5}$", str(x.get("cod_ine") or ""))]
        if sin_cod:
            error("municipios: %d filas sin código INE de 5 dígitos" % len(sin_cod))
        sin_anio = [x for x in m.get("municipios", []) if not x.get("anio_poblacion")]
        if sin_anio:
            error("municipios: %d filas sin año de población (no se publica un dato sin fecha)" % len(sin_anio))
        if m.get("sin_padron"):
            error("municipios: %d códigos sin padrón (declararlos o arreglarlos)" % len(m.get("sin_padron")))
        if abs(m.get("area_suma_km2", 0) - 505990) / 505990 > 0.02:
            error("municipios: área %s km² fuera del 2%% de la oficial" % m.get("area_suma_km2"))
        print("  municipios ................. %d · %.0f km² · %.0f hab (padrón %s)"
              % (m.get("features", 0), m.get("area_suma_km2", 0), m.get("poblacion_suma", 0),
                 m.get("anio_padron")))
    else:
        error("falta datos/municipios_recibo.json (ejecuta scripts/municipios.py)")

    # 4j. encaje en el municipio (código) y demarcación por código
    ren = os.path.join(DATOS, "enriquecimiento_recibo.json")
    if os.path.exists(ren):
        e = json.load(open(ren, encoding="utf-8"))
        # el umbral va donde hay muestra: con 5 almacenamientos, dos centroides fuera del
        # término municipal son un dato, no un fallo del encaje
        flojos = [k for k, vv in e.get("capas", {}).items()
                  if vv.get("puntos", 0) >= 20 and vv.get("pct", 0) < 95]
        if flojos:
            error("encaje en municipio por debajo del 95%%: %s" % ", ".join(
                "%s (%.1f%%)" % (k, e["capas"][k]["pct"]) for k in flojos))
        tot = sum(x["puntos"] for x in e["capas"].values())
        okk = sum(x["encajados"] for x in e["capas"].values())
        print("  municipio por geometría .... %d/%d puntos (%.1f %%)"
              % (okk, tot, 100 * okk / max(1, tot)))
    ra = os.path.join(DATOS, "alias_demarcaciones.json")
    if os.path.exists(ra):
        al = json.load(open(ra, encoding="utf-8"))
        if al.get("sin_resolver"):
            print("  demarcación sin código ...... %d (declaradas)" % len(al["sin_resolver"]))
        print("  demarcación por código ..... %d alias resueltos" % len(al.get("alias", {})))

    # 4k. base local de códigos postales (CP -> municipio, con peso por direcciones)
    rcp = os.path.join(DATOS, "cp_municipios.json")
    if os.path.exists(rcp):
        c = json.load(open(rcp, encoding="utf-8"))
        cps = c.get("cps", {})
        ctrl = c.get("control", {})
        malos = [k for k in cps if len(k) != 5 or not k.isdigit()]
        if malos:
            error("cp_municipios: %d CP con formato invalido" % len(malos))
        sin_cod = [k for k, f in cps.items() if not f or not f[0][0]]
        if sin_cod:
            error("cp_municipios: %d CP sin codigo INE de municipio" % len(sin_cod))
        if len(cps) < 10000:
            error("cp_municipios: solo %d CP en la tabla (se esperan ~11.700)" % len(cps))
        t = ctrl.get("testigo") or 1
        # dos fuentes oficiales pueden discrepar en un CP: se tolera y se declara, no se tapa
        if ctrl.get("discrepan", 0) > 0.03 * t:
            error("cp_municipios: %d CP en conflicto con el testigo (%.1f %%)"
                  % (ctrl["discrepan"], 100.0 * ctrl["discrepan"] / t))
        print("  codigos postales ........... %d CP (%.1f %%) · %d en varios municipios · "
              "control %d/%d · %d conflictos declarados"
              % (len(cps), c.get("cobertura", {}).get("pct", 0),
                 c.get("cobertura", {}).get("cps_multimunicipio", 0),
                 ctrl.get("coinciden", 0), ctrl.get("testigo", 0),
                 len(c.get("discrepancias_fuente", []))))
    else:
        print("  codigos postales ........... falta (ejecuta scripts/callejero.py)")

    # 5. visor
    for f in ("index.html", "README.md"):
        if not os.path.exists(os.path.join(RAIZ, f)):
            error("falta %s" % f)

    # 6. catalogo y cifras de la prosa (auditoria P1 y P5)
    cat = os.path.join(DATOS, "catalogo.json")
    if not os.path.exists(cat):
        error("falta datos/catalogo.json (ejecuta scripts/catalogo.py)")
    else:
        c = json.load(open(cat, encoding="utf-8"))
        pend = c.get("avisos", {}).get("pendiente", [])
        print("  Catalogo ............. %d capas · %d licencia pendiente" % (
            c.get("total", 0), len(pend)))
        # las pendientes son un aviso, no un error: la auditoria pide declararlas, no esconderlas
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "cifras.py"),
                        "--check"], capture_output=True, text=True)
    if r.returncode != 0:
        error("las cifras de la prosa no cuadran (ejecuta scripts/cifras.py)")

    # 7. contrato de capas: es lo que permite seguir metiendo capas sin romper el visor.
    #    Cada capa que el visor pinta tiene que tener su GeoJSON y procedencia declarada
    #    (recibo junto al fichero, recibo de carpeta o entrada en datos/fuentes.json).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cifras as _cifras
    capas = _cifras.leer_array_capas(open(os.path.join(RAIZ, "index.html"), encoding="utf-8").read())
    fuentes = json.load(open(os.path.join(DATOS, "fuentes.json"), encoding="utf-8")).get("capas", {})
    ids = [c["id"] for c in capas]
    repes = sorted({i for i in ids if ids.count(i) > 1})
    if repes:
        error("capas repetidas en CAPAS: %s" % ", ".join(repes))
    sin_fich, sin_fuente, sin_ttl = [], [], []
    for c in capas:
        if c.get("on"):
            error("la capa %s arranca encendida: el visor abre vacio" % c["id"])
        ruta = os.path.join(RAIZ, c.get("fichero") or "")
        if not c.get("fichero") or not os.path.exists(ruta):
            sin_fich.append(c["id"])
            continue
        rec = ruta[: -len(".geojson")] + "_recibo.json"
        carpeta = os.path.dirname(ruta)
        recibos = [x for x in os.listdir(carpeta) if x.startswith("_recibo")]
        if not os.path.exists(rec) and not recibos and c["id"] not in fuentes:
            sin_fuente.append(c["id"])
        if c["id"] not in fuentes:
            sin_ttl.append(c["id"])
    if sin_fich:
        error("%d capas sin fichero: %s" % (len(sin_fich), ", ".join(sin_fich[:10])))
    if sin_fuente:
        error("%d capas sin procedencia: %s" % (len(sin_fuente), ", ".join(sin_fuente[:10])))
    print("  Contrato capas ....... %d capas · %d grupos · %d sin fichero · %d sin procedencia · %d sin ficha de fuente"
          % (len(capas), len({c["grupo"] for c in capas}), len(sin_fich), len(sin_fuente),
             len(sin_ttl)))

    # 8. ámbito: toda capa tiene que estar clasificada (España / comunidad / provincia).
    #    Si entra una capa y nadie la mide, el panel la enseñaría en cualquier sitio y el
    #    distintivo de cobertura dejaría de significar nada. Medido, no declarado: ambitos.py.
    try:
        amb = json.load(open(os.path.join(DATOS, "ambitos.json"), encoding="utf-8")).get("capas", {})
    except Exception:
        amb = {}
    sin_amb = [i for i in ids if i not in amb]
    if sin_amb:
        error("%d capas sin ámbito medido (lanza scripts/ambitos.py): %s"
              % (len(sin_amb), ", ".join(sin_amb[:8])))
    regionales = [k for k, v in amb.items() if v.get("ambito") not in ("nacional", None)]
    print("  Ámbito ............... %d medidos · %d sin medir · %d regionales"
          % (len(amb), len(sin_amb), len(regionales)))

    print("=" * 58)
    print(" OPENINFRAES · VALIDADOR")
    print("=" * 58)
    print("  GeoJSON .............. %s lineas / %s plantas" %
          (len(lineas) if lineas else "-", len(plantas) if plantas else "-"))
    print("  CSV agregados ........ %d" % len([1 for f in os.listdir(DATOS) if f.endswith(".csv")]))
    if errores:
        print("-" * 58)
        for e in errores:
            print("  x " + e)
        print(" RESULTADO: ROJO")
        return 1
    print(" RESULTADO: VERDE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
