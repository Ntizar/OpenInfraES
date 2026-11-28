# Despliegue en NaN CLOUD

OpenInfraES corre también como app propia en **NaN CLOUD**, además de GitHub Pages.

| | |
|---|---|
| URL | https://openinfraes-ntizar-ntizar.apps.nan.builders |
| Repo / rama | `Ntizar/OpenInfraES` · `main` |
| Build | `Dockerfile` (python:3.12-slim, sin dependencias) |
| Puerto | `3000` (`CONTAINER PORT`) |
| Auto-deploy | al hacer push a `main` |
| Persistencia | `/data`, 5 GiB |
| Medido | 251 GB de RAM, ~560 GB libres (28-nov-2026) |

## Por qué existe

GitHub Pages es estático: no puede tener backend. Esta app sí, y además tiene una RAM que en la
VM (3,9 GB, sin swap) es impensable. Aquí caben los 169 feeds del NAP en memoria y el índice de
horas de salida reales, que en el repo de Pages serían 100-200 MB de basura.

## Cómo está montado

- `servidor_nan.py` — servidor con la biblioteca estándar: sirve el sitio y una pequeña API.
  **Sin dependencias a propósito**: el build no puede fallar por un `pip install` caído.
- `.dockerignore` — fuera `.git` y temporales (el repo son 614 MB sin `.git`).
- `Dockerfile` — copia el repo, arranca en el 3000 y trae healthcheck contra `/api/salud`.

## Lo que hay que respetar

- **Range/206 no es opcional.** Los PMTiles piden trozos del fichero; sin `206` el mapa sale en
  blanco. `python3 -m http.server` no sirve para probar esto. Está implementado en
  `sirve_fichero()`; se prueba con `curl -H "Range: bytes=0-1023" -D -`.
- **`/data` es el único sitio que sobrevive a un reinicio.** Lo que se descargue ahí se queda;
  lo demás se pierde en cada despliegue.
- **El puerto es 3000.** Si se cambia en el código hay que cambiarlo también en NaN CLOUD.

## API

| Endpoint | Qué hace |
|---|---|
| `/api/salud` | estado, RAM y disco disponibles, índices presentes en `/data` |
| `/api/horarios?cid=896` | descarga el índice de horarios desde `ntizar.github.io/gtfs-espana` si falta y lo cachea en `/data` y en memoria |

## Comprobar tras un push

```bash
curl -s https://openinfraes-ntizar-ntizar.apps.nan.builders/api/salud
curl -s -o /dev/null -D - -H "Range: bytes=0-2047" \
  https://openinfraes-ntizar-ntizar.apps.nan.builders/transporte/ruta.js | head -4
```

El build tarda 1-3 minutos; durante ese rato la URL devuelve `no available server` o `503`.
