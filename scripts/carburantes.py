# -*- coding: utf-8 -*-
"""Precios de carburantes en tiempo real (MITECO) -> GeoJSON ligero.

Fuente: https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/
        PreciosCarburantes/EstacionesTerrestres/
Sin clave. Devuelve ~12 MB de JSON con 11.500 estaciones; aquí se recorta a lo que
el visor necesita (precios y situación) para dejarlo en un par de megas.

Ojo con el formato: los números vienen con COMA decimal («39,211417») y las claves
llevan espacios y tildes («Precio Gasoleo A», «Longitud (WGS84)»).
"""
import json
import os
import subprocess
import tempfile

UA = {"User-Agent": "OpenInfraES/1.0", "Accept": "application/json"}
URL = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
       "PreciosCarburantes/EstacionesTerrestres/")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(RAIZ, "datos", "carburantes.geojson")

# campo del origen -> nombre corto en el GeoJSON
PRECIOS = {
    "Precio Gasoleo A": "gasoleo_a",
    "Precio Gasoleo Premium": "gasoleo_premium",
    "Precio Gasolina 95 E5": "gasolina95",
    "Precio Gasolina 98 E5": "gasolina98",
    "Precio GLP": "glp",
    "Precio Gas Natural Comprimido": "gnc",
    "Precio Gas Natural Licuado": "gnl",
    "Precio Adblue": "adblue",
    "Precio Biodiesel": "biodiesel",
    "Precio Bioetanol": "bioetanol",
    "Precio Hidrogeno": "hidrogeno",
}


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(".", "").replace(",", ".")
    try:
        return round(float(s), 3)
    except ValueError:
        return None


def main():
    # el servidor del MITECO corta el handshake TLS con urllib (SSLEOFError);
    # curl negocia bien, asi que se descarga con curl y se parsea aqui
    tmp = os.path.join(tempfile.gettempdir(), "carburantes_miteco.json")
    subprocess.run(["curl", "-s", "-L", "--max-time", "300", "-A", UA["User-Agent"],
                    "-o", tmp, URL], check=True)
    with open(tmp, "rb") as fh:
        d = json.loads(fh.read().decode("utf-8-sig"))

    fecha = d.get("Fecha")
    ests = d.get("ListaEESSPrecio", [])
    print("  estaciones en origen: %d · fecha %s" % (len(ests), fecha))

    feats, sin_precio = [], 0
    for e in ests:
        lat, lon = num(e.get("Latitud")), num(e.get("Longitud (WGS84)"))
        if not lat or not lon or not (-90 < lat < 90 and -20 < lon < 10):
            continue
        precios = {k: num(e.get(origen)) for origen, k in PRECIOS.items()}
        precios = {k: v for k, v in precios.items() if v is not None}
        if not precios:
            sin_precio += 1
            continue
        props = {
            "rotulo": (e.get("Rótulo") or "").strip() or None,
            "direccion": (e.get("Dirección") or "").strip() or None,
            "municipio": (e.get("Municipio") or "").strip() or None,
            "provincia": (e.get("Provincia") or "").strip() or None,
            "horario": (e.get("Horario") or "").strip() or None,
            "tipo_venta": (e.get("Tipo Venta") or "").strip() or None,
            "fuente": "MITECO — precios de carburantes",
            "fecha_dato": fecha,
        }
        props.update(precios)
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point", "coordinates": [lon, lat]}})

    gj = {"type": "FeatureCollection", "features": feats}
    json.dump(gj, open(DEST, "w", encoding="utf-8"), ensure_ascii=False)

    # estadísticas para el recibo
    diesel = [f["properties"]["gasoleo_a"] for f in feats if "gasoleo_a" in f["properties"]]
    gas95 = [f["properties"]["gasolina95"] for f in feats if "gasolina95" in f["properties"]]

    def mediana(xs):
        """El precio que ve el conductor es la mediana: la media la mueven cuatro gasolineras de
        autopista. Se publican las dos para que el KPI y el mapa no digan cosas distintas."""
        if not xs:
            return None
        v = sorted(xs)
        n = len(v)
        m = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
        return round(m, 3)

    kb = os.path.getsize(DEST) / 1024
    recibo = {
        "features": len(feats), "sin_precio": sin_precio, "fecha_dato": fecha,
        "kb": round(kb), "fuente": "MITECO", "fichero": "carburantes.geojson",
        "gasoleo_a_medio": round(sum(diesel) / len(diesel), 3) if diesel else None,
        "gasoleo_a_mediana": mediana(diesel),
        "gasoleo_a_min": min(diesel) if diesel else None,
        "gasoleo_a_max": max(diesel) if diesel else None,
        "gasolina95_medio": round(sum(gas95) / len(gas95), 3) if gas95 else None,
        "gasolina95_mediana": mediana(gas95),
        "gasolina95_min": min(gas95) if gas95 else None,
        "gasolina95_max": max(gas95) if gas95 else None,
        "n_gasoleo_a": len(diesel),
        "n_gasolina95": len(gas95),
        "con_glp": sum(1 for f in feats if "glp" in f["properties"]),
        "con_gnc": sum(1 for f in feats if "gnc" in f["properties"]),
        "con_gnl": sum(1 for f in feats if "gnl" in f["properties"]),
        "con_hidrogeno": sum(1 for f in feats if "hidrogeno" in f["properties"]),
    }
    json.dump(recibo, open(DEST.replace(".geojson", "_recibo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("  con precio válido: %d (%d sin precio, descartadas)" % (len(feats), sin_precio))
    print("  gasóleo A: medio %.3f · min %.3f · max %.3f €/l" % (
        recibo["gasoleo_a_medio"] or 0, recibo["gasoleo_a_min"] or 0, recibo["gasoleo_a_max"] or 0))
    print("  gasolina 95: medio %.3f €/l" % (recibo["gasolina95_medio"] or 0))
    print("  GLP %d · GNC %d · GNL %d · H2 %d" % (
        recibo["con_glp"], recibo["con_gnc"], recibo["con_gnl"], recibo["con_hidrogeno"]))
    print("  -> datos/carburantes.geojson (%.0f KB)" % kb)


if __name__ == "__main__":
    main()
