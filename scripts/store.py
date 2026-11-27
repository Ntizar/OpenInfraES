#!/usr/bin/env python3
"""store.py — almacén de entidades y atributos de OpenInfraES (DuckDB).

Regla del sistema: **un sitio = una fila en `entidades`**; todo lo que sabemos de
él son filas en `atributos`, cada una con su fuente, su fecha y su licencia. El
mapa NO lee la base de datos: `--export` genera los GeoJSON por tipo desde ella.

La base (`datos/store.duckdb`) no se versiona: se regenera en la VM.

Uso:
    store.py --init
    store.py --ingest municipios,plantas,desaladoras,edar
    store.py --export
    store.py --parquet
    store.py --check
    store.py --stats
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import unicodedata
from datetime import datetime, timezone

import duckdb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(BASE, "datos")
SALIDA = os.path.join(DATOS, "store")
DB = os.path.join(DATOS, "store.duckdb")

RADIOS = {           # m: margen de digitalización por familia
    "municipio": 400.0,
    "planta_generacion": 150.0,
    "desaladora": 250.0,
    "edar": 150.0,
}
CELDA = 0.005        # grados por celda de la rejilla (~550 m en España)

# ---------------------------------------------------------------- utilidades


def norm(s) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("-", " ").split())


def metros(lon1, lat1, lon2, lat2) -> float:
    dx = (lon2 - lon1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110540.0
    return math.hypot(dx, dy)


def celda(lon, lat):
    return (int(lon / CELDA), int(lat / CELDA))


def centroide(geom) -> tuple[float | None, float | None]:
    """Punto representativo de un polígono: media de los vértices del anillo exterior."""
    if not geom:
        return None, None
    t = geom.get("type")
    c = geom.get("coordinates") or []
    if t == "Point":
        return float(c[0]), float(c[1])
    if t == "MultiPolygon":
        poligono = c[0] if c else []
    elif t == "Polygon":
        poligono = c
    else:
        return None, None
    anillo = poligono[0] if poligono else []
    if not anillo:
        return None, None
    xs = [p[0] for p in anillo]
    ys = [p[1] for p in anillo]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conectar():
    con = duckdb.connect(DB)
    con.execute("install json; load json;")
    return con


# ---------------------------------------------------------------- esquema


ESQUEMA = """
create table if not exists entidades (
    id                 varchar,
    tipo               varchar not null,
    nombre             varchar,
    lon                double,
    lat                double,
    geom               varchar,
    cod_ine_municipio  varchar,
    fuentes            varchar,
    n_atributos        integer default 0,
    actualizado        varchar
);
create table if not exists atributos (
    entidad_id         varchar not null,
    indicador          varchar not null,
    valor_num          double,
    valor_txt          varchar,
    unidad             varchar,
    fecha_dato         varchar,
    fuente             varchar,
    licencia           varchar
);
create table if not exists alias (
    fuente             varchar not null,
    clave              varchar not null,
    entidad_id         varchar not null
);
"""
# Sin PRIMARY KEY a propósito: DuckDB comprueba la clave fila a fila y con 60.000
# inserts se vuelve cuadrático (se quedó colgado 4 min con 0 filas escritas). La
# unicidad se impone en bloque al final de la ingesta (`ingerir`), que es donde
# DuckDB va rápido.


def init(con):
    con.execute(ESQUEMA)
    # migraciones idempotentes: la BD se regenera, pero nunca se recrea a mano
    for ddl in (
        "alter table entidades add column if not exists geom varchar",
    ):
        con.execute(ddl)
    print(f"esquema listo en {DB}")


# ---------------------------------------------------------------- resolver


class Resolutor:
    """Asigna cada hecho a una entidad: clave oficial primero, rejilla después."""

    def __init__(self, con):
        self.con = con
        self.rejilla: dict[tuple, list] = {}
        self.alias: dict[tuple, str] = {}
        self.nuevas = 0
        self.reusadas = 0
        self.por_alias = 0
        self.buf_ent: list[list] = []
        self.buf_atr: list[list] = []
        self.buf_ali: list[list] = []
        for fuente, clave, eid in con.execute("select fuente, clave, entidad_id from alias").fetchall():
            self.alias[(fuente, clave)] = eid
        for eid, tipo, lon, lat in con.execute(
            "select id, tipo, lon, lat from entidades where lon is not null"
        ).fetchall():
            self.rejilla.setdefault((tipo, *celda(lon, lat)), []).append((eid, lon, lat))

    def buscar(self, eid):
        return self.con.execute(
            "select id, tipo, nombre, lon, lat from entidades where id = ?", [eid]
        ).fetchone()

    def resolver(self, tipo, nombre, lon, lat, claves: dict | None = None, geom=None):
        if (lon is None or lat is None) and geom:
            lon, lat = centroide(geom)
        # 1) clave oficial ya vista (osm_id, codigo, cod_ine, minetur…)
        for fuente, clave in (claves or {}).items():
            if clave in (None, "", 0, "0"):
                continue
            fila = self.alias.get((fuente, str(clave).strip()))
            if fila:
                self.por_alias += 1
                self.reusadas += 1
                return fila

        # 2) rejilla espacial: mismo tipo y dentro del radio de la familia
        radio = RADIOS.get(tipo, 150.0)
        if lon is not None and lat is not None:
            cx, cy = celda(lon, lat)
            mejor, mejor_d = None, radio
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for qid, qlon, qlat in self.rejilla.get((tipo, cx + dx, cy + dy), ()):
                        d = metros(lon, lat, qlon, qlat)
                        if d < mejor_d:
                            mejor, mejor_d = qid, d
            if mejor:
                self.reusadas += 1
                return mejor

        # 3) entidad nueva
        coords = f"{lon:.5f},{lat:.5f}" if lon is not None and lat is not None else ""
        semilla = f"{tipo}|{norm(nombre)}|{coords}"
        eid = f"{tipo}:{hashlib.sha1(semilla.encode()).hexdigest()[:12]}"
        self.buf_ent.append(
            [eid, tipo, nombre, lon, lat, json.dumps(geom, ensure_ascii=False) if geom else None, ahora()]
        )
        if lon is not None and lat is not None:
            self.rejilla.setdefault((tipo, *celda(lon, lat)), []).append((eid, lon, lat))
        self.nuevas += 1
        return eid

    def atribuir(self, eid, fuente, licencia, indicadores: list):
        """indicadores: [(indicador, valor, unidad, fecha)] — None se ignora."""
        n = 0
        for indicador, valor, unidad, fecha in indicadores:
            if valor is None or valor == "":
                continue
            num = valor if isinstance(valor, (int, float)) else None
            txt = None if num is not None else str(valor)
            self.buf_atr.append(
                [eid, indicador, num, txt, unidad, fecha, fuente, licencia]
            )
            n += 1
        return n

    def enlazar(self, fuente, clave, eid):
        if clave in (None, "", 0, "0"):
            return
        clave = str(clave).strip()
        if len(clave) < 3:      # claves basura ("-", "1", "0") no identifican nada
            return
        self.buf_ali.append([fuente, clave, eid])
        self.alias[(fuente, clave)] = eid

    def flush(self):
        """Vuelca los búferes con executemany: fila a fila DuckDB no va."""
        if self.buf_ent:
            self.con.executemany(
                "insert into entidades (id,tipo,nombre,lon,lat,geom,n_atributos,actualizado)"
                " values (?,?,?,?,?,?,0,?)", self.buf_ent)
            self.buf_ent.clear()
        if self.buf_atr:
            self.con.executemany(
                "insert into atributos (entidad_id,indicador,valor_num,valor_txt,unidad,fecha_dato,fuente,licencia)"
                " values (?,?,?,?,?,?,?,?)", self.buf_atr)
            self.buf_atr.clear()
        if self.buf_ali:
            self.con.executemany(
                "insert into alias (fuente, clave, entidad_id) values (?,?,?)", self.buf_ali)
            self.buf_ali.clear()


# ---------------------------------------------------------------- ingestas


def lee_geojson(nombre):
    with open(os.path.join(DATOS, nombre), encoding="utf-8") as f:
        return json.load(f)["features"]


def geom_punto(f):
    g = f.get("geometry") or {}
    if g.get("type") != "Point":
        return None, None
    return g["coordinates"][0], g["coordinates"][1]


def ing_municipios(res: Resolutor):
    feats = lee_geojson("municipios.geojson")
    ine = json.load(open(os.path.join(DATOS, "ine", "municipios.json"), encoding="utf-8"))
    municipios = ine.get("municipios", {})
    anyo = str(ine.get("anyo") or "")
    n = 0
    for f in feats:
        p = f["properties"]
        clave = p.get("cod_ine") or p.get("cod_ine_municipio")
        if not clave:
            continue
        lon, lat = geom_punto(f)
        eid = res.resolver("municipio", p.get("nombre"), lon, lat, {"ine:municipio": clave},
                           geom=f.get("geometry"))
        res.enlazar("ine:municipio", clave, eid)
        inds = []
        for k, v in (municipios.get(str(clave)) or {}).items():
            inds.append((f"ine.{k}", v, "EUR" if k.startswith("renta") else None, anyo))
        res.atribuir(eid, "INE (padrón/renta)", "CC-BY-4.0", [
            ("ine.poblacion", p.get("poblacion"), "hab", "2024"),
            ("ine.densidad", p.get("densidad"), "hab/km2", "2024"),
        ] + inds)
        n += 1
    print(f"  municipios: {n} leídos")


def ing_plantas(res: Resolutor):
    n = 0
    for f in lee_geojson("plantas.geojson"):
        p = f["properties"]
        lon, lat = geom_punto(f)
        eid = res.resolver("planta_generacion", p.get("name"), lon, lat,
                           {"minetur": p.get("minetur")},
                           geom=f.get("geometry"))
        # El nombre NO es clave: «Torrevieja» existe en dos sitios y un alias por
        # nombre fusiona instalaciones distintas. Nombres solo por rejilla. 
        if p.get("minetur"):
            res.enlazar("minetur", str(p["minetur"]).split(" y ")[0], eid)
        res.atribuir(eid, "REE/LISTADO", "CC-BY-4.0", [
            ("potencia_mw", p.get("installed_capacity_mw"), "MW", "2025"),
            ("tecnologia", p.get("technology_normalized") or p.get("technology_ree"), None, "2025"),
            ("estado", p.get("status"), None, "2025"),
            ("propietario", p.get("owner"), None, "2025"),
        ])
        res.atribuir(eid, "ELECTRA", "CC-BY-4.0", [
            ("potencia_mw", p.get("installed_capacity_mw_electra"), "MW", "2025"),
            ("nombre_electra", p.get("electra_name"), None, "2025"),
        ])
        n += 1
    print(f"  plantas: {n} leídas")


def ing_desaladoras(res: Resolutor):
    n = 0
    for f in lee_geojson("desaladoras.geojson"):
        p = f["properties"]
        lon, lat = geom_punto(f)
        eid = res.resolver("desaladora", p.get("nombre"), lon, lat,
                           {"osm:id": p.get("osm_id")}, geom=f.get("geometry"))
        res.enlazar("osm:id", p.get("osm_id"), eid)
        res.atribuir(eid, "OSM", "ODbL-1.0", [
            ("capacidad_m3_dia", p.get("capacidad_m3_dia"), "m3/d", "2026"),
            ("operador", p.get("operador"), None, "2026"),
        ])
        n += 1
    print(f"  desaladoras: {n} leídas")


def ing_edar(res: Resolutor):
    n = 0
    for f in lee_geojson("edar_unificado.geojson"):
        p = f["properties"]
        lon, lat = geom_punto(f)
        eid = res.resolver("edar", p.get("nombre"), lon, lat,
                           {"edar:codigo": p.get("codigo"), "osm:id": p.get("osm_id")},
                           geom=f.get("geometry"))
        res.enlazar("edar:codigo", p.get("codigo"), eid)
        res.enlazar("osm:id", p.get("osm_id"), eid)
        res.atribuir(eid, p.get("fuente") or "IGN/I-ReWater/OSM", "CC-BY-4.0", [
            ("capacidad_hab_eq", p.get("capacidad"), "hab-eq", "2024"),
            ("caudal_entrada_m3_d", p.get("caudal_entrada"), "m3/d", "2024"),
            ("impacto", p.get("impacto"), None, "2024"),
        ])
        n += 1
    print(f"  edar: {n} leídas")


INGESTAS = {
    "municipios": ing_municipios,
    "plantas": ing_plantas,
    "desaladoras": ing_desaladoras,
    "edar": ing_edar,
}


def ingerir(con, familias):
    # reconstrucción completa: el almacén se regenera, no se parchea
    for tabla in ("entidades", "atributos", "alias"):
        con.execute(f"delete from {tabla}")
    res = Resolutor(con)
    import time as _t
    for fam in familias:
        fn = INGESTAS.get(fam)
        if not fn:
            print(f"  !! familia desconocida: {fam}")
            continue
        t0 = _t.time()
        fn(res)
        res.flush()
        print(f"    ({_t.time() - t0:.1f}s)")
    # unicidad en bloque (ver nota del esquema)
    con.execute("create or replace table atributos as select distinct on (entidad_id, indicador, fuente) * from atributos")
    con.execute("create or replace table alias as select distinct on (fuente, clave) * from alias")
    # OJO: no se filtran entidades sin atributos. Un sitio sin datos sigue siendo
    # un sitio: es justo donde mañana se cuelga el primer atributo.
    # clave INE y contadores, en una pasada
    con.execute("""
        update entidades e set cod_ine_municipio = a.clave
        from alias a where a.entidad_id = e.id and a.fuente = 'ine:municipio'
    """)
    con.execute("""
        update entidades e set
            n_atributos = coalesce(s.n, 0),
            fuentes = coalesce(s.f, ''),
            actualizado = ?
        from (select entidad_id, count(*) n, string_agg(distinct fuente, ' · ') f
              from atributos group by 1) s
        where s.entidad_id = e.id
    """, [ahora()])
    print(f"  nuevas: {res.nuevas} · reutilizadas: {res.reusadas} (por clave oficial: {res.por_alias})")


# ---------------------------------------------------------------- exportación

UNIDADES = {}


def exportar(con):
    os.makedirs(SALIDA, exist_ok=True)
    tipos = [r[0] for r in con.execute(
        "select tipo, count(*) c from entidades group by 1 order by c desc").fetchall()]
    total = 0
    for tipo in tipos:
        filas = con.execute(
            "select id, nombre, lon, lat, geom, cod_ine_municipio, fuentes, n_atributos"
            " from entidades where tipo = ? and (geom is not null or lon is not null)", [tipo]).fetchall()
        attrs = con.execute(
            "select a.entidad_id, a.indicador, a.valor_num, a.valor_txt, a.fuente"
            " from atributos a join entidades e on e.id = a.entidad_id where e.tipo = ?",
            [tipo]).fetchall()
        por_entidad: dict[str, dict] = {}
        for eid, ind, num, txt, fuente in attrs:
            por_entidad.setdefault(eid, {})[ind] = num if num is not None else txt
        features = []
        for eid, nombre, lon, lat, geom, cod_ine, fuentes, n_atr in filas:
            props = {"id": eid, "nombre": nombre, "fuentes": fuentes, "n_atributos": n_atr}
            if cod_ine:
                props["cod_ine_municipio"] = cod_ine
            props.update(por_entidad.get(eid, {}))
            geometria = json.loads(geom) if geom else {"type": "Point", "coordinates": [lon, lat]}
            features.append({
                "type": "Feature",
                "geometry": geometria,
                "properties": props,
            })
        salida = os.path.join(SALIDA, f"{tipo}.geojson")
        cuerpo = json.dumps({"type": "FeatureCollection", "generado": ahora(),
                             "tipo": tipo, "features": features},
                            ensure_ascii=False, separators=(",", ":"))
        with open(salida, "w", encoding="utf-8") as f:
            f.write(cuerpo)
        sha = hashlib.sha256(cuerpo.encode()).hexdigest()[:16]
        recibo = {"capa": tipo, "entidades": len(features), "generado": ahora(),
                  "sha256_16": sha, "bytes": len(cuerpo.encode()),
                  "con_varias_fuentes": sum(1 for x in features if "·" in (x["properties"]["fuentes"] or ""))}
        with open(salida.replace(".geojson", "_recibo.json"), "w", encoding="utf-8") as f:
            json.dump(recibo, f, ensure_ascii=False, indent=1)
        total += len(features)
        print(f"  {tipo:18s} {len(features):6d} entidades · {recibo['bytes']/1e6:6.2f} MB"
              f" · multi-fuente {recibo['con_varias_fuentes']}")
    print(f"total exportado: {total}")


def parquet(con):
    os.makedirs(SALIDA, exist_ok=True)
    for tabla in ("entidades", "atributos"):
        salida = os.path.join(SALIDA, f"{tabla}.parquet")
        # SNAPPY, no ZSTD: el lector del navegador (hyparquet) no descomprime ZSTD
        con.execute(f"copy (select * from {tabla}) to '{salida}'"
                    " (format parquet, compression snappy)")
        print(f"  {tabla}.parquet {os.path.getsize(salida)/1e6:.2f} MB")


# ---------------------------------------------------------------- control


def check(con):
    """Invariantes: sin duplicados por tipo a menos de 30 m, sin atributos huérfanos."""
    fallos = 0
    filas = con.execute(
        "select tipo, lon, lat, id from entidades where lon is not null order by tipo, lon").fetchall()
    prev = {}
    for tipo, lon, lat, eid in filas:
        for otro_id, olon, olat in prev.get(tipo, [])[-40:]:
            if metros(lon, lat, olon, olat) < 30.0:
                print(f"  DUPLICADO {tipo}: {eid} ~ {otro_id} (<30 m)")
                fallos += 1
        prev.setdefault(tipo, []).append((eid, lon, lat))
    huerfanos = con.execute(
        "select count(*) from atributos a where not exists (select 1 from entidades e where e.id=a.entidad_id)"
    ).fetchone()[0]
    if huerfanos:
        print(f"  HUÉRFANOS: {huerfanos} atributos sin entidad")
        fallos += 1
    print("check:", "OK" if not fallos else f"{fallos} fallos")
    return 0 if not fallos else 1


def stats(con):
    print("entidades por tipo:")
    for tipo, c, multi in con.execute("""
        select tipo, count(*), count(*) filter (where fuentes like '%·%')
        from entidades group by 1 order by 2 desc""").fetchall():
        print(f"  {tipo:18s} {c:6d}  multi-fuente {multi}")
    print("atributos por indicador (top 12):")
    for ind, c, f in con.execute("""
        select indicador, count(*), count(distinct fuente)
        from atributos group by 1 order by 2 desc limit 12""").fetchall():
        print(f"  {ind:26s} {c:6d}  fuentes {f}")


def main(argv):
    if "--reset" in argv and os.path.exists(DB):
        os.unlink(DB)
        print(f"borrada {DB} (se regenera)")
    if "--init" in argv:
        init(conectar())
        return 0
    con = conectar()
    if "--ingest" in argv:
        i = argv.index("--ingest")
        familias = (argv[i + 1] if i + 1 < len(argv) else "municipios,plantas,desaladoras,edar").split(",")
        print("ingesta:", ", ".join(familias))
        ingerir(con, familias)
    if "--export" in argv:
        exportar(con)
    if "--parquet" in argv:
        parquet(con)
    if "--check" in argv:
        return check(con)
    if "--stats" in argv:
        stats(con)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
