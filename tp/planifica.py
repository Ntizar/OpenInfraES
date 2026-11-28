#!/usr/bin/env python3
"""Planificador de viaje sobre los indices estaticos del GTFS. Modelo de frecuencias.

    python3 planifica.py --de "40.4168,-3.7038" --a "40.4936,-3.5668" --hora 08:00

Algoritmo: RAPTOR de 3 rondas. Cada ronda anade un transbordo. Las aristas son:
  - a pie: entre paradas a menos de 200 m, aunque sean de redes distintas (EMT <-> Metro)
  - en linea: paradas consecutivas del recorrido de una linea, con su velocidad por modo
La espera al subir se estima como medio intervalo de esa linea en ese perfil de dia.
"""
import argparse
import collections
import json
import math
import os

AQUI = os.path.dirname(os.path.abspath(__file__))


def _indices():
    """Dónde están paradas/, lineas/ y horarios/.

    Si están al lado del módulo, se usan. Si no (producción sirve solo el repo), se
    descomprime indices.tar.gz en ~/.cache/openinfraes-gtfs una vez y se tira de ahí.
    """
    if os.path.isdir(os.path.join(AQUI, "paradas")):
        return AQUI
    import tarfile
    destino = os.environ.get("OPENINFRAES_GTFS",
                             os.path.join(os.path.expanduser("~"), ".cache", "openinfraes-gtfs"))
    listo = os.path.join(destino, ".listo")
    if not os.path.exists(listo):
        os.makedirs(destino, exist_ok=True)
        with tarfile.open(os.path.join(AQUI, "indices.tar.gz"), "r:gz") as t:
            t.extractall(destino)
        open(listo, "w").write("ok")
    return destino


AQUI = _indices()
VEL = {0: 20, 900: 20, 1: 32, 2: 55, 3: 14, 4: 26, 7: 18, 200: 60, 704: 20, 715: 18, -1: 700}
PARADA_S = 40
CAMINA = 1.35
ANTES_VUELO = 45  # facturacion y embarque
MAX_RONDAS = 5
RADIO = 900
PIE_M = 200
AEREO = "920"


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    x = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(x))


def hmm(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def fmt(x):
    x = int(round(x)) % 1440
    return "%02d:%02d" % (x // 60, x % 60)


class Red:
    def __init__(self, cid):
        self.cid = cid
        self.hor = json.load(open(os.path.join(AQUI, "horarios", cid + ".json"), encoding="utf-8"))
        self.lin = json.load(open(os.path.join(AQUI, "lineas", cid + ".json"), encoding="utf-8"))
        self.pm = json.load(open(os.path.join(AQUI, "paradas", cid + ".json"), encoding="utf-8"))
        # linea -> [(stop, idx)] y recorridos por nombre corto
        self.por_sh = {}
        self.pos = {}
        for _, v in self.lin.items():
            if v[0] not in self.por_sh:
                self.por_sh[v[0]] = v[2]
                self.pos[v[0]] = {st: i for i, st in enumerate(v[2])}
        self._cache_dist = {}
        self._largo = {}

    def lineas_de(self, sid, dia):
        out = {}
        for L in self.hor.get(sid, []):
            per = L[2][dia]
            if per:
                out[L[0]] = (L[1], per[0], hmm(per[1]), hmm(per[2]), per[3])
        return out

    def largo(self, sh):
        """Longitud total del recorrido, en km. Sirve para saber si una línea es urbana o
        interurbana: no es lo mismo un bus de barrio que un ALSA Madrid-Toledo."""
        if sh not in self._largo:
            rec = self.por_sh.get(sh) or []
            d = 0.0
            for a, b in zip(rec, rec[1:]):
                p1, p2 = self.pm.get(a), self.pm.get(b)
                if p1 and p2:
                    d += hav(p1[1], p1[2], p2[1], p2[2])
            self._largo[sh] = d / 1000.0
        return self._largo[sh]

    def vel_de(self, sh, modo):
        """Velocidad media estimada según el modo y el largo del recorrido.

        Las tablas por modo solas dan 14 km/h a un bus interurbano y convierten Madrid-Toledo
        en 4 horas. El bus urbano va a 14; el de carretera, a 70. Se interpola entre 15 y 40 km
        de recorrido y se deja el valor de la tabla para lo corto.
        """
        L = self.largo(sh)
        if modo in (2, -1):            # tren y avión no se tocan
            return VEL.get(modo, 55)
        urbano, interurbano = (VEL.get(modo, 18), 20)
        if modo in (0, 900):           # tranvía
            urbano, interurbano = 20, 22
        elif modo == 1:                # metro
            urbano, interurbano = 32, 40
        elif modo == 4:                # ferry
            urbano, interurbano = 26, 30
        elif modo in (3, 200, 704, 715):
            urbano, interurbano = VEL.get(modo, 18), 70
        if L <= 15:
            return urbano
        if L >= 40:
            return interurbano
        f = (L - 15) / 25.0
        return urbano + f * (interurbano - urbano)

    def tramo_min(self, sh, i, j, modo):
        """minutos entre dos indices del recorrido, sumando distancias reales"""
        key = (sh, min(i, j), max(i, j))
        if key in self._cache_dist:
            return self._cache_dist[key]
        rec = self.por_sh.get(sh) or []
        a, b = key[1], key[2]
        dist = 0.0
        for k in range(a, b):
            p1, p2 = self.pm.get(rec[k]), self.pm.get(rec[k + 1])
            if p1 and p2:
                dist += hav(p1[1], p1[2], p2[1], p2[2])
        v = self.vel_de(sh, modo)
        mins = (dist / 1000.0) / v * 60 + (b - a) * PARADA_S / 60.0
        self._cache_dist[key] = mins
        return mins


class Planificador:
    def __init__(self, radio=RADIO):
        self.radio = radio
        self.idx = []
        self.celda = collections.defaultdict(list)
        for f in os.listdir(os.path.join(AQUI, "paradas")):
            cid = f[:-5]
            for sid, (nom, lat, lon) in json.load(
                    open(os.path.join(AQUI, "paradas", f), encoding="utf-8")).items():
                nodo = (cid, sid)
                self.idx.append((nodo, nom, lat, lon))
                self.celda[(int(lat / 0.003), int(lon / 0.003))].append((nodo, nom, lat, lon))
        self.aeropuertos = [(la, lo) for nodo, _, la, lo in self.idx if nodo[0] == AEREO]
        self.cache = {}

    def red(self, cid):
        if cid not in self.cache:
            try:
                self.cache[cid] = Red(cid)
            except FileNotFoundError:
                self.cache[cid] = None
        return self.cache[cid]

    def cerca(self, lat, lon, radio=None):
        radio = radio or self.radio
        cy, cx = int(lat / 0.003), int(lon / 0.003)
        r = int(radio / 300.0) + 1
        out = []
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                for nodo, nom, la, lo in self.celda.get((cy + dy, cx + dx), ()):
                    d = hav(lat, lon, la, lo)
                    if d <= radio:
                        out.append((d, nodo, nom, la, lo))
        out.sort()
        return out

    def vecinos_pie(self, nodo, lat, lon):
        """Transbordo andando. Los aeropuertos del feed aereo quedan lejos de la parada de
        bus, asi que para ellos el radio es de 1,2 km; en ciudad sigue siendo 200 m."""
        aereo = nodo[0] == AEREO
        # si hay un aeropuerto a menos de 3 km, el radio crece para poder enlazar con el
        cerca_de_aeropuerto = aereo or any(
            hav(lat, lon, a, b) < 3000 for a, b in self.aeropuertos)
        out = []
        for d, n, nom, la, lo in self.cerca(lat, lon, 2500 if cerca_de_aeropuerto else PIE_M):
            if n == nodo:
                continue
            if aereo or n[0] == AEREO or d <= PIE_M:
                out.append((d, n, nom))
        return out

    def tramo_geom(self, cid, sh, i, j):
        """Coordenadas [lon, lat] del recorrido entre los índices i y j (los del plan)."""
        red = self.red(cid)
        if not red:
            return []
        rec = red.por_sh.get(sh) or []
        if i is None or j is None or i >= len(rec) or j >= len(rec):
            return []
        # El recorrido se guarda en un sentido; si la bajada tiene índice menor que la subida,
        # el viaje va al revés y hay que recorrer la lista invertida.
        tramo = list(reversed(rec[j:i + 1])) if j < i else rec[i:j + 1]
        out = []
        for st in tramo:
            info = red.pm.get(st)
            if info:
                out.append([info[2], info[1]])
        return out

    def plan(self, origen, destino, hora, dia=0):
        t0 = hmm(hora)
        O = self.cerca(origen[0], origen[1], 1200)
        D = {n: (nom, la, lo) for _, n, nom, la, lo in self.cerca(destino[0], destino[1], 3000)}
        if not O or not D:
            return []

        # llegada minima por nodo y padre
        mejor = {}
        padre = {}
        for d, nodo, nom, la, lo in O:
            t = t0 + d / CAMINA / 60
            if t < mejor.get(nodo, 9e9):
                mejor[nodo] = t
                padre[nodo] = ("origen", nom, None, d / CAMINA / 60, d)

        frontera = dict(mejor)
        for ronda in range(MAX_RONDAS):
            # una linea se procesa UNA vez por ronda, desde su parada mas temprana
            porlinea = collections.defaultdict(list)
            for nodo, t in frontera.items():
                cid, sid = nodo
                red = self.red(cid)
                if not red:
                    continue
                for sh, (modo, n, ini_h, fin_h, iv) in red.lineas_de(sid, dia).items():
                    i = red.pos.get(sh, {}).get(sid)
                    if i is None:
                        continue
                    porlinea[(cid, sh)].append((t, i, nodo, modo, iv, fin_h))

            siguiente = {}
            for (cid, sh), v in porlinea.items():
                v.sort()
                t_mejor, i_mejor, nodo_mejor, modo, iv, fin_h = v[0]
                red = self.red(cid)
                rec = red.por_sh.get(sh) or []
                salida = t_mejor + max(2, (iv or 15) / 2) + (ANTES_VUELO if modo == -1 else 0)
                if salida > fin_h:
                    continue
                for j, stop in enumerate(rec):
                    if j == i_mejor:
                        continue
                    q = (cid, stop)
                    llegada = salida + red.tramo_min(sh, i_mejor, j, modo)
                    if llegada < mejor.get(q, 9e9) - 0.01:
                        mejor[q] = llegada
                        padre[q] = ("linea", sh, (nodo_mejor, salida, modo, i_mejor),
                                    max(2, (iv or 15) / 2) + (ANTES_VUELO if modo == -1 else 0), None, j)
                        siguiente[q] = llegada

            # transbordo andando entre redes distintas
            for nodo, t in list(frontera.items()):
                cid, sid = nodo
                red = self.red(cid)
                if not red:
                    continue
                info = red.pm.get(sid)
                if not info:
                    continue
                for d, vecino, nom in self.vecinos_pie(nodo, info[1], info[2]):
                    t2 = t + d / CAMINA / 60
                    if t2 < mejor.get(vecino, 9e9) - 0.01:
                        mejor[vecino] = t2
                        padre[vecino] = ("pie", nom, (nodo, t, None), d / CAMINA / 60, d)
                        siguiente.setdefault(vecino, t2)

            if not siguiente:
                break
            frontera = dict(sorted(siguiente.items(), key=lambda kv: kv[1])[:200000])

        self.mejor = mejor
        # reconstruir las mejores llegadas al destino
        res = []
        for nodo, (nom_d, la, lo) in D.items():
            if nodo not in mejor:
                continue
            llegada = mejor[nodo]
            d_fin = hav(la, lo, destino[0], destino[1])
            llegada += d_fin / CAMINA / 60
            if llegada <= t0:
                continue
            # reconstruir cadena
            cadena = []
            cur = nodo
            guarda = 0
            while cur is not None and guarda < 12:
                guarda += 1
                p = padre.get(cur)
                if not p:
                    break
                if p[0] == "linea":
                    prev, salida, modo, i_sub = p[2]
                    cadena.append((p[1], prev, cur, salida, mejor[cur], modo, p[3],
                                   self.tramo_geom(cur[0], p[1], i_sub, p[5])))
                    cur = prev
                elif p[0] == "pie":
                    cur = p[2][0]
                else:
                    break
            cadena.reverse()
            res.append(dict(total=llegada - t0, llega=llegada, destino=nom_d, cadena=cadena,
                            caminata=d_fin / CAMINA / 60))
        # deduplicar por combinacion de lineas: quedarse con la llegada mas temprana
        vistos = {}
        for r in res:
            firma = ">".join(c[0] for c in r["cadena"]) or "pie"
            if firma not in vistos or r["total"] < vistos[firma]["total"]:
                vistos[firma] = r
        out = sorted(vistos.values(), key=lambda r: r["total"])
        return out[:4]


def resumen(p, r):
    lineas = [c[0] for c in r["cadena"]]
    return " → ".join(lineas) if lineas else "a pie"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--hora", default="08:00")
    ap.add_argument("--dia", type=int, default=0)
    a = ap.parse_args()
    p = Planificador()
    print("indice: %d paradas, %d celdas" % (len(p.idx), len(p.celda)))
    o = tuple(float(x) for x in a.de.split(","))
    d = tuple(float(x) for x in a.a.split(","))
    res = p.plan(o, d, a.hora, a.dia)
    if not res:
        print("sin ruta")
        return
    for i, r in enumerate(res, 1):
        print("\n%d) %.0f min — llegada %s" % (i, r["total"], fmt(r["llega"])))
        print("   " + resumen(p, r))
        for sh, prev, cur, salida, llegada, modo, espera, _g in r["cadena"]:
            pn = (p.red(prev[0]).pm.get(prev[1]) or ["?"])[0]
            cn = (p.red(cur[0]).pm.get(cur[1]) or ["?"])[0]
            print("   %-10s %-30s %s  (espera %.0f min)" % (sh[:10], pn[:30], fmt(salida), espera))
        print("   llegada a %s a las %s (andando %.0f min)" % (
            r["destino"][:30], fmt(r["llega"]), r["caminata"]))


if __name__ == "__main__":
    main()
