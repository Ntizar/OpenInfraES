---
titulo: APIs oficiales — estado verificado
fecha: 2026-11-16
ambito: espana
estado: publicado
---

# APIs oficiales: qué responde hoy y qué no

Cada línea de esta tabla se probó con una petición real el **16-11-2026**. Los errores están citados
literalmente: un `400` a secas no sirve para depurar.

Las fichas completas de cada organismo —qué publica, licencia, frecuencia y qué capa alimenta— están
en [`FUENTES.md`](FUENTES.md). Aquí, solo el estado técnico y las trampas.

## 1. Responde sin clave

| Organismo | Endpoint | Devuelve |
|---|---|---|
| **REE** | `apidatos.ree.es/es/datos/generacion/estructura-generacion?...&time_trunc=day` | 14 tecnologías |
| **REE** | `apidatos.ree.es/es/datos/balance/balance-electrico?...&time_trunc=day` | balance del día |
| **REE** | `apidatos.ree.es/es/datos/demanda/evolucion?...&time_trunc=day` | demanda |
| **MITECO** | `sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/` | 11.528 estaciones |
| **MITMA** | `mapas.fomento.gob.es/arcgis/rest/services/Hermes/<servicio>/MapServer/<capa>/query?...&f=geojson` | carreteras, puertos, terminales |
| **IGN** | `ign.es/wmts/ign-base?...` | teselas y capas BTN vectorizadas |
| **Renfe** | `gtfsrt.renfe.com/vehicle_positions.pb` | 418 trenes |
| **Renfe** | `data.renfe.com/api/3/action/package_show?id=estaciones-cercanias-<núcleo>` | estaciones por núcleo |
| **EMSC-CSEM** | `seismicportal.eu/fdsnws/event/1/query?format=json&...` | 80 sismos en 7 días |
| **OurAirports** | `davidmegginson.github.io/ourairports-data/airports.csv` | CSV global 12,7 MB → **553 aeródromos ES** |
| **GDACS** | `gdacs.org/xml/rss.xml` | RSS 654 KB, 213 alertas → **1 en España** (bbox 27-44,5 / -19,5-5) |

## 2. Responde con clave

| Organismo | Endpoint | Sin clave | Con clave |
|---|---|---|---|
| **ESIOS (REE)** | `api.esios.ree.es/indicators/<id>` | **403** | 1.982 indicadores; previsión en 460 y 541 |
| **AEMET** | `opendata.aemet.es/opendata/api/avisos_cap/...` | **404** | sin verificar (falta alta) |
| **ENTSO-E** | `web-api.tp.entsoe.eu/api?documentType=A75...` | **401** | sin verificar (falta alta) |
| **NAP (MITMA)** | `nap.transportes.gob.es/api/3/action/package_list` | **401** | **404** (ver [`nap.md`](nap.md)) |

## 3. Roto o limitado, con el error exacto

| Intento | Error | Consecuencia |
|---|---|---|
| REE `time_trunc=hour` en cualquier widget | `400` «Los datos solicitados no están disponibles» | la API pública **solo** sirve agregados diarios |
| REE `demanda/demanda-tiempo-real` | `400` | no hay tiempo real por API |
| REE `geo_limit=ccaa` | `500` | no hay generación por comunidad autónoma |
| REE `generacion/potencia-instalada` | `500` | sin potencia instalada por la API |
| MITMA `resultRecordCount=1000` | HTML de error | paginar de 500 en 500 |
| MITMA capa 0 de aeropuertos | `Failed to execute query` | usar las capas 1 y 2 |
| Overpass sin `User-Agent` | `406 Not Acceptable` | cabecera obligatoria |
| Overpass en hora punta | `502` / `504` | backoff y espejos |
| MITECO con `urllib` | `SSLEOFError` | descargar con `curl` |
| IGN WMTS sin `Accept: image/*` | `200` con **0 bytes** | cabecera y `Referer` obligatorios |
| GDACS con `Accept: application/rss+xml` | **`406 Not Acceptable`** | pedir `application/xml,text/xml` |
| Safecast sin `unit=cpm` | `200` con `unit:"status"` | **no es radiación**: son lecturas del estado del medidor |
| Overpass (`overpass-api.de`) desde esta red | **`000`** (sin conexión) | probar espejos o QLever antes de dar el dato por perdido |

## 4. Trampas de formato que cuestan una hora cada una

**REE es JSON:API y los datos no están donde parecen.** `data.attributes.values` solo trae título y
`last-update`. Las series están en **`included[]`**:

```json
{"data": {"attributes": {"title": "...", "last-update": "..."}},
 "included": [{"attributes": {"title": "Eólica", "values": [{"value": 311168.0}]}}]}
```

**El MITECO usa coma decimal y claves con espacios**: `"Latitud": "39,211417"`,
`"Longitud (WGS84)": "-1,539167"`, `"Precio Gasoleo A": "1,752"`.

**Renfe no rellena `route_id`**: la ruta va en la etiqueta (`C1-23551` → `C1`).

**EMSC usa `-1` como profundidad** para «superficie o desconocida».

**Algunas capas mezclan geometrías**: la de red eléctrica son 657 polígonos de subestación **y** 2
tendidos; hay que mirar la propiedad `categoria`, no el tipo de la primera feature.

## 5. Un 200 no es una prueba

El INE y el MITECO sirven **páginas de error con código 200**. La verificación de este repositorio
compara el **título** de la página devuelta, no solo el código. Y para los GeoJSON cuenta features: un
fichero de 0 bytes con 200 es un fallo silencioso, no un éxito.

## 6. Qué pedir, por orden de valor

1. **ENTSO-E** (formulario, gratis) — único con generación y previsión **por unidad**.
2. **AEMET** (registro, gratis) — cierra el bloque de riesgo meteorológico.
3. **NAP** — aclarar el header; 179 conjuntos de transporte público esperando.

Ninguno cuesta dinero. Los dos primeros son un formulario.


### El 403 de ESIOS: primero fue el WAF, hoy es la clave (2026-11-23)

**Actualización 2026-11-23:** los 19 indicadores que se leían sin clave **ya no están abiertos**. Medido
el mismo día: `GET /indicators/2037` sin cabecera → **403 con 36 bytes de cuerpo**;
con `x-api-key: <token>` → **200 con 37.979 bytes**. La capa «en vivo» (demanda, emisiones,
intercambios, bombeo) estuvo congelada en el último dato bueno del 16-11 hasta que el token entró en
`ree_vivo.py` y en los secrets del repo. Moraleja doble: un 403 de ESIOS **puede** ser el WAF, pero
también puede ser que cerraron la puerta — se distingue probando **con** clave.

Lo que sigue es el caso del WAF, que también ocurrió y volverá a ocurrir con barridos:

Tras ~50 peticiones seguidas, **los 19 indicadores abiertos empezaron a devolver 403**. El cuerpo es
siempre el mismo genérico:

```json
{"Status":403,"message":"Forbidden"}
```

La diferencia está en las **cabeceras**, no en el código ni en el cuerpo:

```
X-Cache: Error from cloudfront
X-CDN: Imperva
X-Iinfo: 57-10069179-10069185 NNNN CT(6 7 0) ...
Set-Cookie: incap_ses_4558_1885724=...; visid_incap_1885724=...
X-Amzn-ErrorType: ForbiddenException
```

Es un **WAF (Imperva detrás de CloudFront) bloqueando por comportamiento**, no un problema de
credenciales. Consecuencias:

- Los indicadores «abiertos» lo son **hasta que abusas**: el mismo endpoint da 200 y luego 403 según tus
  últimas peticiones. Un barrido del catálogo entero dispara el bloqueo.
- **Espaciar** las peticiones (~1 s) y no repetir el barrido. El bloqueo se levanta solo en minutos.
- **No se pierde el dato bueno por un bloqueo**: `ree_vivo.py` lee el JSON anterior y, para lo que no
  puede descargar, hereda la serie marcándola `heredado: true` con su hora. El visor avisa «sin
  actualizar: último dato bueno de las HH:MM». Un panel con datos de hace 20 minutos declarados es
  mejor que uno vacío o, peor, con ceros. Verificado: 18 series conservadas, 17 heredadas.
- `scripts/http_oficial.py` lo distingue con la excepción `BloqueoWAF` (lee `X-CDN`, `X-Iinfo`,
  `incap_ses`), separada de `SinPermiso`. Sin esa distinción, uno cree que le falta la clave cuando lo
  que le falta es paciencia.

## ESIOS · qué indicadores están abiertos SIN token

Probados los 29 que usa el MCP `ree-mcp`. **19 responden `200`** y 10 dan `403`.
Se comprueba con `GET https://api.esios.ree.es/indicators/<id>` y cabecera `Accept: application/json`.

| ID | Indicador | Sin token |
|---|---|---|
| 2037 | Demanda real nacional | **200** |
| 10004 | Demanda real (suma de generación) | **200** |
| 2038 | Eólica nacional | **200** |
| 2041 | Ciclo combinado nacional | **200** |
| 2042 | Hidráulica nacional | **200** |
| 2044 | Solar fotovoltaica nacional | **200** |
| 2045 | Solar térmica nacional | **200** |
| 1294 | Solar térmica peninsular | **200** (sin valores hoy) |
| 10355 | CO₂ asociado a la generación | **200** · tCO₂/MW |
| 2068 / 2073 | Exportación / importación Andorra | **200** |
| 2069 / 2074 | Exportación / importación Marruecos | **200** |
| 2070 / 2075 | Exportación / importación Portugal | **200** |
| 2071 / 2076 | Exportación / importación Francia | **200** |
| 2078 / 2079 | Consumo / turbinado de bombeo | **200** |
| 1293 | Demanda real peninsular (5 min) | 403 |
| 1292 | Previsión de demanda | 403 |
| 624 / 625 | Demanda máxima / mínima diaria | 403 |
| 549 | Nuclear | 403 |
| 547 | Carbón | 403 |
| 548 | Fuel/gas | 403 |
| 1295 | Solar FV peninsular | 403 |
| 600 | Precio SPOT | 403 |
| 1013 | Tarifa PVPC | 403 |

- **Resolución real: 5 minutos.** La demanda nacional trae 224 valores al día.
- **La unidad no viene en `unit`** (siempre `null`): está en `magnitud[]`. El 10355 declara `tCO2/MW`.
- **La nuclear y el carbón abiertos en `apidatos` pero cerrados en ESIOS**: dos puertas distintas del
  mismo organismo, con reglas distintas. Probar ambas antes de rendirse.
- Conector: `scripts/ree_vivo.py` → `datos/ree_vivo.json` + recibo.


## 8. Datos de alto valor (HVD): el inventario medido el 23-11-2026

El Reglamento de Ejecución (UE) 2023/138 obliga desde el **9 de junio de 2024** a publicar los
conjuntos de alto valor «de forma gratuita, en formatos legibles por máquina y accesibles mediante
API» en seis categorías: geoespacial, observación de la Tierra, medio ambiente, estadística,
empresarial y movilidad. España reporta el cumplimiento a la Comisión cada dos años con enlaces
persistentes a esas API. Lo que sigue es lo que **responde de verdad** al sondearlo, no lo que
anuncia el catálogo.

| Organismo | API | Clave | Medido | Qué sirve |
|---|---|---|---|---|
| **MITECO** | `gis.miteco.gob.es/geoserver/ogc/features/v1` | no | **534 colecciones**, GeoJSON, CORS abierto | agua, costas, clima, medio ambiente, demografía |
| **IDEE / CNIG** | `api-features.idee.es/collections` | no | **38 colecciones**, GeoJSON | hidrografía, transporte, aeródromos, puertos, direcciones |
| **INE** | `servicios.ine.es/wstempus/js/{ES}/{función}/{input}` | no | 200 | series estadísticas (Tempus3) |
| **MITECO (catálogo)** | `catalogo.datosabiertos.miteco.gob.es/catalogo/api/3/action/package_search` | no | 200 | metadatos CKAN y URL de cada recurso |
| **AEMET** | `opendata.aemet.es/opendata/api/...` | **sí** (gratis) | doble llamada | observación y predicción |

### La que más rinde: OGC API Features del MITECO

```bash
# inventario de todo lo publicado
curl 'https://gis.miteco.gob.es/geoserver/ogc/features/v1/collections?f=json' | jq '.collections | length'
# 534

# una colección, en GeoJSON, sin clave
curl 'https://gis.miteco.gob.es/geoserver/ogc/features/v1/collections/agua%3Acanales/items?limit=10&f=json'
```

- **La paginación es `startIndex`, NO `offset`.** Con `offset` el servidor devuelve la misma página
  y la descarga sale inflada sin dar error: el primer intento de aforos trajo **3.000 objetos donde
  la fuente declara 2.191**. Regla: se pregunta `numberMatched` con `limit=1`, se descarga con
  `limit=N&startIndex=…` y **si el total no cuadra, no se escribe el recibo**.
- **`numberMatched` es el contrato.** Es lo que permite decir «la fuente dice 2.191 y hemos guardado
  2.191» en lugar de «parece que están todos».
- **`limit` alto funciona** (3.000 objetos en una sola petición); con 10.000 y varias colecciones
  seguidas el tiempo se dispara. Lotes de 5.000 para arriba no aportan nada.
- **CRS84: `[lon, lat]`**, siempre, aunque el servicio tenga otra SRS de origen. El capturador lo
  comprueba (si `|x|>20` y `|y|<20`, endereza) en vez de suponerlo.
- **Las propiedades vienen con 45 columnas** (aforos): `nom_anuario`, `cod_saih`, `cota_z`… Se
  traducen ocho o diez a castellano legible y el resto se tira. Una ficha con 45 campos no se lee.

### Lo que ya está dentro del visor por esta vía

| Capa | Colección | Objetos | Tamaño |
|---|---|---|---|
| `aforos` | `agua:Estaciones_Aforos` | 2.191 | 661 KB |
| `canales-miteco` | `agua:canales` | 792 | 1,4 MB (10,3 MB sin simplificar) |
| `calidad-aire-estaciones` | `evaluacionambiental:ca_red_estaciones` | 783 | 153 KB |

- **Las líneas se simplifican a ~22 m** (Douglas-Peucker iterativo, con pila): 10,3 MB → 1,4 MB.
  El visor pinta a escala nacional y provincial; esos 22 m no se ven y el navegador lo agradece.
  La tolerancia va declarada en el recibo (`simplificado_m`).
- **No todo lo que hay es una capa**: `agua:Estaciones_Aforos` es el **inventario de estaciones**,
  no el caudal. El caudal en vivo es otro dato y no está en la misma colección. Prometer «caudal en
  vivo del MITECO» con esto sería vender una cosa por otra.
- La red de canales del MITECO (792 trazos declarados) **no es** la capa de OSM (10.800 acequias
  mapeadas): son dos cosas distintas y las dos están en el visor, con su nombre.

### Descartadas hoy, con el número medido

| Colección | Por qué no entra (aún) |
|---|---|
| `agua:Zi_laminas_q100` | Láminas de inundación T=100: polígonos enormes, la descarga completa no termina en 5 min. Pide recorte por CCAA o teselas vectoriales. |
| `costas:poem_*` (60 colecciones) | Zonas de alto potencial eólico del POEM: interesantes para energía, pero cada una es media capa suelta; entra cuando haya una capa «POEM» de verdad. |
| `aemet:*` del GeoServer | Duplica lo que ya se baja de AEMET por su API; añadir la vía sin retirar la otra sería dos verdades para el mismo aviso. |

**Conector:** `scripts/miteco_ogc.py` (`python scripts/miteco_ogc.py aforos canales-miteco`), que
escribe `datos/<capa>.geojson` + `datos/<capa>_recibo.json`. Para añadir otra colección basta con una
entrada en su diccionario `CAPAS`; el alta en el visor sigue siendo de seis sitios (ver `GUIA.md`).
