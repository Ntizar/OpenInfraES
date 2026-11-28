#!/usr/bin/env python3
"""Servidor de OpenInfraES para NaN CLOUD.

Sirve el sitio estático y una pequeña API de transporte. Sin dependencias: sólo la biblioteca
estándar, para que la imagen arranque siempre y no dependa de instalar nada en el build.

Claves:
- **Range/206 obligatorio**: los PMTiles piden trozos del fichero; sin esto el mapa se queda en
  blanco. `http.server` no lo hace, por eso este servidor.
- **/data es persistente** (5 GiB): ahí van los índices de transporte que se descargan solos la
  primera vez, para no meterlos en la imagen ni en el repo.
- Puerto 3000, que es el que espera NaN CLOUD.
"""
import json
import os
import re
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS = os.environ.get("DATOS", "/data")
PUERTO = int(os.environ.get("PORT", "3000"))
GTFS = "https://ntizar.github.io/gtfs-espana/"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".geojson": "application/geo+json",
    ".pmtiles": "application/octet-stream",
    ".mbtiles": "application/octet-stream",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}

_cache = {}
_lock = threading.Lock()


def ruta_segura(ruta):
    """Normaliza y evita salir de RAIZ con ../"""
    ruta = os.path.normpath("/" + ruta).lstrip("/")
    destino = os.path.join(RAIZ, ruta)
    if not os.path.abspath(destino).startswith(RAIZ):
        return None
    return destino


def carga_json(relativo):
    """Índice de transporte en /data, descargado de la web si falta."""
    with _lock:
        if relativo in _cache:
            return _cache[relativo]
    destino = os.path.join(DATOS, relativo)
    if not os.path.exists(destino):
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        try:
            req = urllib.request.Request(GTFS + relativo, headers={"User-Agent": "OpenInfraES"})
            with urllib.request.urlopen(req, timeout=120) as r, open(destino + ".tmp", "wb") as f:
                while True:
                    trozo = r.read(1 << 20)
                    if not trozo:
                        break
                    f.write(trozo)
            os.replace(destino + ".tmp", destino)
        except Exception as e:
            print(f"no pude descargar {relativo}: {e}", flush=True)
            return None
    try:
        with open(destino, encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return None
    with _lock:
        _cache[relativo] = datos
    return datos


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, obj, codigo=200):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta.startswith("/api/"):
            return self.api(ruta)

        if ruta == "/":
            ruta = "/index.html"
        destino = ruta_segura(ruta)
        if not destino or not os.path.isfile(destino):
            return self._json({"error": "no encontrado", "ruta": ruta}, 404)
        self.sirve_fichero(destino)

    # --- estáticos con soporte de Range ---
    def sirve_fichero(self, destino):
        tam = os.path.getsize(destino)
        ext = os.path.splitext(destino)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        rango = self.headers.get("Range")

        inicio, fin = 0, tam - 1
        parcial = False
        if rango:
            m = re.match(r"bytes=(\d*)-(\d*)", rango)
            if m:
                a, b = m.group(1), m.group(2)
                if a:
                    inicio = int(a)
                    fin = int(b) if b else tam - 1
                elif b:
                    inicio = max(0, tam - int(b))
                fin = min(fin, tam - 1)
                if inicio > fin or inicio >= tam:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{tam}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                parcial = True

        longitud = fin - inicio + 1
        self.send_response(206 if parcial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(longitud))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300")
        if parcial:
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{tam}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(destino, "rb") as f:
            f.seek(inicio)
            restante = longitud
            while restante > 0:
                trozo = f.read(min(1 << 16, restante))
                if not trozo:
                    break
                self.wfile.write(trozo)
                restante -= len(trozo)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        ruta = self.path.split("?")[0]
        if ruta != "/api/chat":
            return self._json({"error": "endpoint desconocido", "ruta": ruta}, 404)
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > 8192:
                return self._json({"error": "petición demasiado grande"}, 413)
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except Exception as e:
            return self._json({"error": "json inválido: %s" % e}, 400)

        pregunta = (cuerpo.get("q") or "").strip()[:600]
        if not pregunta:
            return self._json({"error": "falta la pregunta"}, 400)

        lat = cuerpo.get("lat")
        lon = cuerpo.get("lon")
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None

        ctx = ""
        if lat is not None and lon is not None:
            ctx = "El usuario está en %.5f, %.5f." % (lat, lon)

        # 1) Asistente del visor completo: catálogo de 104 capas, 8.128 municipios, 1.977 cámaras y
        #    5.797 plantas. Devuelve ACCIONES ejecutables; el modelo solo entra si las reglas
        #    deterministas no reconocen la frase.
        try:
            import chat_openinfra as CI
        except Exception:
            CI = None
        if CI is not None:
            try:
                intencion = CI.resolver(pregunta, lat, lon)
            except Exception as e:
                return self._json({"error": "el asistente falló: %s" % e}, 500)
            intencion["pregunta"] = pregunta
            # Compatibilidad: transporte/chat.js sigue leyendo {accion, lugar, lugares}. El visor
            # nuevo lee {verbo, texto, acciones}. Se mandan los dos, no se rompe ninguno.
            mapa_accion = {"volar": "ir", "cerca": "cerca", "capa": "capas", "filtrar": "capas",
                           "mezclar": "capas", "foto": "ficha"}
            intencion.setdefault("accion", mapa_accion.get(intencion.get("verbo"), "responder"))
            if intencion.get("verbo") == "volar":
                for a in intencion.get("acciones") or []:
                    if a.get("tipo") == "volar":
                        intencion.setdefault("lugar", a.get("etiqueta") or "")
            intencion.setdefault("lugares", [])
            return self._json(intencion)

        # 2) Respaldo: el chat del visor de transporte (5 verbos sobre el índice de paradas).
        try:
            import chat_transporte as CT
        except Exception as e:
            return self._json({"error": "módulo de chat no disponible: %s" % e}, 503)

        try:
            intencion = CT.interpreta(pregunta, ctx)
        except RuntimeError as e:
            return self._json({"error": str(e)}, 503)
        except Exception as e:
            return self._json({"error": "el modelo no respondió: %s" % e}, 502)

        lugar = (intencion.get("lugar") or "").strip()
        if intencion.get("accion") in ("ir", "ruta") and lugar:
            indice = carga_json("busqueda.json")
            if indice:
                intencion["lugares"] = CT.busca_lugar(indice, lugar, 5)

        intencion["pregunta"] = pregunta
        return self._json(intencion)

    # --- API ---
    def api(self, ruta):
        if ruta == "/api/salud":
            ram, disco = {}, {}
            try:
                with open("/proc/meminfo") as f:
                    for linea in f:
                        k = linea.split(":")[0]
                        if k in ("MemTotal", "MemAvailable"):
                            ram[k] = int(linea.split()[1]) // 1024
            except Exception:
                pass
            try:
                st = os.statvfs(DATOS)
                disco = {"libre_mb": st.f_bavail * st.f_frsize // (1 << 20),
                         "total_mb": st.f_blocks * st.f_frsize // (1 << 20)}
            except Exception:
                pass
            return self._json({
                "estado": "ok",
                "sitio": "OpenInfraES",
                "datos": os.path.isdir(DATOS),
                "ram_mb": ram,
                "disco": disco,
                "indices": sorted(os.listdir(DATOS)) if os.path.isdir(DATOS) else [],
            })
        if ruta == "/api/horarios":
            return self.api_horarios()
        return self._json({"error": "endpoint desconocido", "ruta": ruta}, 404)

    def api_horarios(self):
        """Consulta los horarios de una red desde /data (se descargan la primera vez)."""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        cid = (q.get("cid") or [""])[0]
        if not re.fullmatch(r"\d{1,6}", cid or ""):
            return self._json({"error": "cid obligatorio y numérico"}, 400)
        d = carga_json(f"horarios/{cid}.json")
        if d is None:
            return self._json({"error": "sin horarios para esa red"}, 404)
        return self._json({"cid": cid, "paradas": len(d)})


def main():
    os.makedirs(DATOS, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PUERTO), Handler)
    print(f"OpenInfraES en 0.0.0.0:{PUERTO} · datos en {DATOS}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
