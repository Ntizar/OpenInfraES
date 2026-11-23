# -*- coding: utf-8 -*-
"""Cliente HTTP para APIs de organismos públicos.

La lección que este módulo implementa, y que casi nadie hace: **`200` con lista vacía no es
un fallo de red**. Es «no hay datos en ese periodo», y el usuario decide distinto según cuál sea.

Cinco situaciones, cinco respuestas:

    SinDatos       200 pero el recurso viene vacío -> no hay dato, no hay avería
    NoExiste       404                              -> el recurso no existe (no se reintenta)
    SinPermiso     401/403                          -> falta clave o no cubre ese recurso
    PeticionMala   400/422                          -> la construimos mal (no se reintenta)
    ServidorCaido  5xx o timeout                    -> se reintenta con backoff y se rinde

Uso:

    from http_oficial import pide, SinDatos, NoExiste, SinPermiso

    d = pide("https://api.esios.ree.es/indicators/2037", vacio_si=("indicator", "values"))
"""
import json
import ssl
import time
import urllib.error
import urllib.request

UA = "OpenInfraES/1.0 (+https://github.com/Ntizar/OpenInfraES)"
ESPERA = 0.5          # factor del backoff: 0.5, 1, 2 s
REINTENTOS = 3


class FalloFuente(Exception):
    """Cualquier problema con una fuente oficial."""
    tipo = "fallo"


class SinDatos(FalloFuente):
    tipo = "sin_datos"


class NoExiste(FalloFuente):
    tipo = "no_existe"


class SinPermiso(FalloFuente):
    tipo = "sin_permiso"


class BloqueoWAF(FalloFuente):
    """403 de un cortafuegos de aplicaciones por comportamiento, NO falta de clave.

    Se detecta por cabeceras: `X-CDN: Imperva`, `X-Iinfo`, `X-Amz-Cf-Id`, cookies
    `incap_ses_*`. El cuerpo suele ser un genérico `{"Status":403,"message":"Forbidden"}`,
    indistinguible de «falta clave» si solo se mira el código.
    """
    tipo = "bloqueo_waf"


class CertificadoInvalido(FalloFuente):
    """El TLS del servidor no valida: certificado caducado, cadena rota o nombre que no casa.

    No es un fallo de red ni nuestro: reintentar no arregla nada (el ministerio tiene que
    renovarlo). Se separa de `ServidorCaido` para que el script que lo recibe pueda decidir
    heredar el ultimo dato bueno en vez de entrar en backoff y rendirse con un error opaco.
    """
    tipo = "certificado"


class PeticionMala(FalloFuente):
    tipo = "peticion_mala"


class ServidorCaido(FalloFuente):
    tipo = "servidor_caido"


def _vacio(d, ruta):
    """True si la ruta anidada existe y está vacía (lista o dict vacío)."""
    if not ruta:
        return False
    actual = d
    for clave in ruta:
        if not isinstance(actual, dict) or clave not in actual:
            return False
        actual = actual[clave]
    return actual in ([], {}, None, "")


def pide(url, cabeceras=None, vacio_si=None, timeout=60, reintentos=REINTENTOS,
         espera=ESPERA, metodo="GET", cuerpo=None):
    """Descarga JSON de una fuente oficial, distinguiendo los cinco casos.

    vacio_si: tupla con la ruta al array de datos. Si existe y está vacía -> SinDatos.
              Ej.: ("indicator", "values") para ESIOS, ("features",) para un GeoJSON.
    """
    hdrs = {"Accept": "application/json", "User-Agent": UA}
    if cabeceras:
        hdrs.update(cabeceras)

    ultimo = None
    for intento in range(reintentos + 1):
        req = urllib.request.Request(url, headers=hdrs, method=metodo,
                                     data=cuerpo.encode() if cuerpo else None)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                crudo = r.read()
                if not crudo.strip():
                    raise SinDatos("la respuesta llegó vacía (0 bytes): %s" % url)
                d = json.loads(crudo)
                if _vacio(d, vacio_si):
                    raise SinDatos("sin datos en este periodo: %s" % url)
                return d

        except urllib.error.HTTPError as e:
            codigo = e.code
            if codigo == 404:
                raise NoExiste("404: el recurso no existe · %s" % url)
            if codigo in (401, 403):
                # 403 de WAF != 403 de clave. Las cabeceras lo delatan.
                cab = {k.lower(): v for k, v in (e.headers or {}).items()}
                waf = (cab.get("x-cdn", "").lower().find("imperva") >= 0
                       or "x-iinfo" in cab
                       or "incap_ses" in str(cab)
                       or cab.get("x-amzn-errortype", "").lower() == "forbiddenexception")
                if waf:
                    raise BloqueoWAF(
                        "403 del WAF (Imperva/CloudFront): bloqueo por comportamiento, "
                        "no falta de clave. Espaciar las peticiones y esperar · %s" % url)
                raise SinPermiso("%d: falta clave o no cubre este recurso · %s" % (codigo, url))
            if 400 <= codigo < 500:
                detalle = e.read().decode("utf-8", "replace")[:160]
                raise PeticionMala("%d: %s · %s" % (codigo, detalle, url))
            # 5xx: reintentar
            ultimo = ServidorCaido("%d en el servidor · %s" % (codigo, url))
            if intento < reintentos:
                time.sleep(espera * (2 ** intento))
                continue
            raise ultimo

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            motivo = str(getattr(e, "reason", e))
            if ("CERTIFICATE_VERIFY_FAILED" in motivo
                    or isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError)):
                # Sin reintentos ni backoff: el certificado lo renueva el servidor, no nosotros.
                raise CertificadoInvalido("certificado del servidor no valida: %s · %s"
                                          % (motivo[:90], url))
            ultimo = ServidorCaido("red: %s · %s" % (motivo[:90], url))
            if intento < reintentos:
                time.sleep(espera * (2 ** intento))
                continue
            raise ultimo

        except json.JSONDecodeError:
            raise PeticionMala("la respuesta no es JSON · %s" % url)

    raise ultimo or ServidorCaido("agotados los reintentos · %s" % url)


def resumen(fallos):
    """Agrupa fallos por tipo para el recibo."""
    por_tipo = {}
    for f in fallos:
        por_tipo[f["tipo"]] = por_tipo.get(f["tipo"], 0) + 1
    return por_tipo
