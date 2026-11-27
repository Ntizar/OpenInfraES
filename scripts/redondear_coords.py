# -*- coding: utf-8 -*-
"""Redondea coordenadas de todos los GeoJSON del visor a 5 decimales (~1,1 m).

Por qué existe: los generadores escriben lo que les llega. Un vértice del IGN entra con
14 decimales de ruido de proyección (`-5.31520949999998`) cuando la fuente no tiene esa
precisión: a zoom 18, un píxel son ~0,6 m, así que más de 5 decimales no los ve nadie y
solo engordan el fichero y el JSON.parse del móvil.

Es un pase **posterior** a los generadores y **idempotente**: si un fichero ya está
redondeado no se toca (ni se reescribe, para no mover el mtime ni el hash en balde).

No simplifica ni mueve vértices: cambia dígitos, nada más. Donde hace falta quitar
vértices está `simplificar.py`, que es otra cosa.

    python scripts/redondear_coords.py            # todo datos/**, informa
    python scripts/redondear_coords.py --dry-run  # solo mide
"""
import argparse
import glob
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
RECIBO = os.path.join(DATOS, "redondeo_recibo.json")
DECIMALES = 5


def entero(x):
    """round() respeta el tipo; el ruido de proyección llega como float con cola."""
    return round(x, DECIMALES)


def redondea(c):
    if isinstance(c, (int, float)):
        return entero(c)
    if isinstance(c, list):
        return [redondea(v) for v in c]
    return c


def cambia(c):
    """¿hay algún número con más decimales de los permitidos?"""
    if isinstance(c, (int, float)):
        return abs(c * 10 ** DECIMALES) - int(abs(c) * 10 ** DECIMALES) > 0
    if isinstance(c, list):
        return any(cambia(v) for v in c)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ficheros = sorted(glob.glob(os.path.join(DATOS, "**", "*.geojson"), recursive=True))
    antes_total = despues_total = 0
    tocados, fallos = [], []
    for ruta in ficheros:
        rel = os.path.relpath(ruta, DATOS)
        kb0 = os.path.getsize(ruta)
        antes_total += kb0
        try:
            with open(ruta, encoding="utf-8") as fh:
                d = json.load(fh)
            feats = d.get("features") or []
            sucio = any(cambia(f["geometry"]["coordinates"]) for f in feats
                        if f.get("geometry") and f["geometry"].get("coordinates"))
            if sucio and not a.dry_run:
                for f in feats:
                    g = f.get("geometry")
                    if g and g.get("coordinates"):
                        g["coordinates"] = redondea(g["coordinates"])
                with open(ruta, "w", encoding="utf-8") as fh:
                    json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
            kb1 = os.path.getsize(ruta)
        except Exception as e:  # un fichero roto no puede tumbar el pase
            fallos.append(f"{rel}: {type(e).__name__}")
            kb1 = kb0
        despues_total += kb1
        if sucio:
            tocados.append({"fichero": rel, "kb_antes": round(kb0 / 1024),
                            "kb_despues": round(kb1 / 1024),
                            "ahorro_pct": round(100 * (1 - kb1 / kb0), 1) if kb0 else 0})

    tocados.sort(key=lambda x: x["kb_antes"] - x["kb_despues"], reverse=True)
    if not a.dry_run:
        with open(RECIBO, "w", encoding="utf-8") as fh:
            json.dump({"decimales": DECIMALES, "ficheros": len(ficheros),
                       "tocados": len(tocados), "ahorro_mb": round((antes_total - despues_total) / 1e6, 2),
                       "detalle": tocados[:60], "fallos": fallos}, fh, ensure_ascii=False, indent=1)

    print(f"{len(ficheros)} GeoJSON · {len(tocados)} con decimales de más · "
          f"{antes_total / 1e6:.1f} → {despues_total / 1e6:.1f} MB "
          f"({(1 - despues_total / antes_total) * 100:.0f}% menos)")
    for t in tocados[:10]:
        print(f"  {t['fichero']:44s} {t['kb_antes']:7d} → {t['kb_despues']:7d} kB "
              f"({t['ahorro_pct']:.0f}%)")
    if fallos:
        print(f"  {len(fallos)} ilegibles: {fallos[:5]}")


if __name__ == "__main__":
    main()
