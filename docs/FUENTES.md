---
titulo: Fuentes oficiales — ficha por ficha
fecha: 2026-11-16
ambito: espana
estado: publicado
---

# Fuentes oficiales de OpenInfraES

Cada capa sale de un organismo público. Aquí está, para cada uno: **qué publica**, la **URL oficial**,
**cómo se obtiene** el dato, la **licencia**, la **frecuencia**, **qué capas alimenta** y sus
**limitaciones**.

Solo se cita al organismo que produce el dato.

---

## 1. IGN — Instituto Geográfico Nacional (SCNE)

**Qué publica.** La Base Topográfica Nacional (BTN) y la cartografía base de España. Es la fuente de
la red eléctrica, los recintos de subestación y las teselas del mapa.

- **URL oficial**: <https://www.ign.es> · <https://www.scne.es>
- **Cómo se obtiene**:
  - Teselas del mapa: `https://www.ign.es/wmts/ign-base?request=GetTile&service=WMTS&version=1.0.0&layer=IGNBase-gris&style=default&tilematrixset=GoogleMapsCompatible&tilematrix={z}&tilerow={y}&tilecol={x}&format=image/png`
  - Vectorial (BTN): capas en GeoJSON ya vectorizadas, en `datos/oficial/`.
- **Licencia**: CC BY 4.0 · atribución `© scne.es`.
- **Frecuencia**: continua (BTN Continua).
- **Alimenta**: fondo del mapa (4 bases) y **subestaciones (657)**, red de 220/400 kV.
- **Limitaciones**: el WMTS devuelve **200 con cuerpo vacío** sin `Accept: image/*` y `Referer`. No
  tiene teselas oscuras: el tema oscuro se hace con filtro CSS sobre la capa de solo líneas. Las capas
  vectoriales **mezclan geometrías**: la de red eléctrica son 657 polígonos de subestación **y** 2
  tendidos; hay que mirar la propiedad `categoria`, no el tipo de la primera feature.

## 2. MITECO — Ministerio para la Transición Ecológica

Tres conjuntos distintos, los tres oficiales:

### 2a. Boletín Hidrológico — el dato primario de los embalses
- **URL oficial**: <https://www.miteco.gob.es/es/agua.html>
- **Cómo se obtiene**: parte **semanal**; el volumen de cada embalse llega en el campo
  `agua_actual_hm3` con su propia fecha en `fecha_dato`.
- **Licencia**: reutilización con atribución (Ley 37/2007).
- **Alimenta**: **402 embalses** con capacidad y agua embalsada.
- **Limitaciones**: cubre embalses peninsulares de más de 5 hm³.

### 2b. Precios de carburantes — tiempo real
- **URL oficial**: `https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/`
- **Cómo se obtiene**: `GET` a esa URL → ~12 MB de JSON con **11.528 estaciones**. `scripts/carburantes.py`
  lo reduce a 11.433 con precio válido.
- **Licencia**: Ley 37/2007.
- **Frecuencia**: **cada 30 minutos**.
- **Alimenta**: carburantes con gasóleo A, gasolina 95/98, GNC, GNL y H₂.
- **Limitaciones**: el servidor **corta el handshake TLS con Python** (`SSLEOFError`) → descargar con
  `curl`. Números con **coma decimal** (`39,211417`) y claves con espacios y tildes.

### 2c. Desaladoras, presas e hidrógeno
- **Cómo se obtiene**: desaladoras (28) e instalaciones de hidrógeno en GeoJSON; el inventario de
  presas (≈3.200) **no publica geometría**, solo listados.

## 3. MITMA — Ministerio de Transportes (visor Hermes)

- **URL oficial**: <https://mapas.fomento.gob.es/VisorHermes/>
- **Cómo se obtiene** (ArcGIS REST abierto, sin clave):
  `https://mapas.fomento.gob.es/arcgis/rest/services/Hermes/<servicio>/MapServer/<capa>/query?where=1=1&outFields=*&returnGeometry=true&outSR=4326&f=geojson`
- **Licencia**: CC BY 4.0 (scne.es).
- **Alimenta**: carreteras (1.602), puertos (45), terminales portuarias (440), terminales de aeropuerto
  (102), terminales de mercancías (383), estaciones GNL/GNC/H₂ (165 de 11.485).
- **Limitaciones**: `resultRecordCount=1000` **falla** → paginar de 500 en 500. Carreteras sin
  simplificar son ~85 MB → `maxAllowableOffset=0.002` la deja en 0,63 MB. La capa 0 de aeropuertos no
  admite query.

## 4. REE — Red Eléctrica de España

- **URL oficial**: <https://www.ree.es/es/apidatos> (sin clave) · <https://api.esios.ree.es> (con clave)
- **Cómo se obtiene**:
  - `https://apidatos.ree.es/es/datos/generacion/estructura-generacion?start_date=...&end_date=...&time_trunc=day`
  - Con clave: `https://api.esios.ree.es/indicators/<id>` + cabecera `x-api-key`.
- **Licencia**: **condiciones propias del editor**.
- **Frecuencia**: apidatos, **diaria**; ESIOS, cuartos de hora.
- **Alimenta**: panel ⚡ (14 tecnologías) e interconexiones (5); previsión por ESIOS (460 demanda,
  541 eólica).
- **Limitaciones**: la API pública **solo sirve agregados diarios** (`time_trunc=hour` → 400). **No hay
  generación por planta** ni **tensión de red**: los «niveles de tensión» de ESIOS son tarifarios.
- **Trampa**: las series están en **`included[]`**, no en `data.attributes.values`.

## 5. CSN, CORES y Enagás

- **CSN** (<https://www.csn.es>): **7 reactores** con potencia y tecnología.
- **CORES** (<https://www.cores.es>): refinerías (10) y almacenamiento de productos petrolíferos.
- **Enagás** (<https://www.enagas.es>): regasificadoras (7), almacenamiento subterráneo (5) e
  interconexiones de gas.
- **Licencia**: CC BY 4.0 en las capas vectorizadas.

## 6. Renfe

### 6a. Posiciones de trenes (GTFS-Realtime)
- **URL oficial**: `https://gtfsrt.renfe.com/vehicle_positions.pb` (y `trip_updates.pb`, `alerts.pb`)
- **Cómo se obtiene**: descarga directa, sin clave. Protocol Buffers con `gtfs-realtime-bindings`.
- **Alimenta**: **418 trenes** y 98 alertas.
- **Limitaciones**: **`route_id` viene vacío** (la ruta va en la etiqueta, `C1-23551` → `C1`); las
  alertas traen `header_text` vacío aunque la descripción sí.

### 6b. Estaciones de Cercanías
- **URL oficial**: <https://data.renfe.com> (CKAN abierto)
- **Cómo se obtiene**: `api/3/action/package_show?id=estaciones-cercanias-<núcleo>` + su CSV.
- **Alimenta**: **405 estaciones** en 11 núcleos.
- **Limitaciones**: separador `;` o `,` según fichero; llevan **BOM** (`utf-8-sig`).

## 7. EMSC-CSEM — sismología europea

- **URL oficial**: <https://www.seismicportal.eu/fdsnws/event/1/query>
- **Cómo se obtiene**: `?format=json&minlatitude=27&maxlatitude=44.5&minlongitude=-19.5&maxlongitude=5&starttime=<fecha>`
- **Alimenta**: **80 sismos** en 7 días.
- **Limitaciones**: `profundidad = -1` significa **superficie o desconocida**.


## 7bis. NAP — Punto de Acceso Nacional de transportes (MITMA)

**Qué publica.** Los horarios completos (GTFS) de **169 conjuntos** de transporte de **550 operadores**:
148 de autobús, 27 ferroviarios, 3 marítimos y 1 aéreo. También GTFS en tiempo real (86), SIRI (67) y
NeTEx (30).

- **URL oficial**: `https://nap.transportes.gob.es/api`
- **Cómo se obtiene**: cabecera **`ApiKey`** (ni `X-Api-Key` ni `Authorization`).
  - Catálogo: `GET /Fichero/GetList` (10,5 MB)
  - Descarga: `GET /Fichero/downloadLink/{id}` → URL firmada de S3 que **caduca en 900 s**
- **Licencia**: reutilización con atribución (Ley 37/2007).
- **Frecuencia**: los conjuntos se actualizan a diario; el catálogo declara `fechaActualizacion`.
- **Alimenta**: paradas de **Metro de Madrid (1.050)**, **Cercanías Renfe (1.167)** y
  **Renfe AVE y largo recorrido (1.006)**, con sus líneas y frecuencias.
- **Limitaciones**:
  - El NAP devuelve **`200` con 0 bytes** en ráfaga: hay que reintentar.
  - **No todos los GTFS traen `frequencies.txt`**: Metro de Madrid sí; Cercanías y AVE no, y su frecuencia
    se calcula contando salidas reales.
  - **`stop_sequence` no siempre empieza en `1`**: los GTFS de Renfe numeran `01`, `02`. Comparar como
    entero o la frecuencia sale a cero sin error.
  - En largo recorrido un «headway» no significa nada: se publican **salidas al día**, no minutos entre
    trenes.

## 8. OpenStreetMap

- **URL oficial**: <https://www.openstreetmap.org> · consultas por <https://overpass-api.de>
- **Cómo se obtiene**: Overpass API con `[out:json]` y `out geom`.
- **Licencia**: **ODbL 1.0 — comparte igual**.
- **Alimenta**: líneas 400/220 kV, gasoductos, hidráulicas, EDAR (3.034), ETAP (1.551), trasvases,
  canales (10.777), ríos (260).
- **Limitaciones**: Overpass da **502/504** a menudo y exige `User-Agent` (si no, **406**). El mapeo es
  desigual: el **Tajo-Segura solo llega a Alarcón**; los trasvases son fragmentos con nombre.

## 9. Pendientes de clave

| Organismo | Qué falta | Estado |
|---|---|---|
| **AEMET** | avisos meteorológicos CAP | 404 sin token; alta gratuita |
| **ENTSO-E** | generación y previsión **por unidad** | 401 sin token; **cuenta ya creada** |
| **NAP (MITMA)** | 179 conjuntos de transporte | su gateway no acepta la clave por header |

## 10. Disponibles y no usados todavía

| Organismo | Qué ofrece | Por qué interesa |
|---|---|---|
| **DGT** | aforos de tráfico (IMD), incidencias, obras | explica la demanda de combustible |
| **Puertos del Estado** | estadística mensual de tráfico portuario | cruce con bunkering |
| **GIE AGSI+** | almacenamiento de gas europeo por instalación | nivel de gas y precio |
| **OMIE** | mercado diario e intradiario | el precio como variable |
| **NASA FIRMS** | focos de calor por satélite | riesgo de incendio junto a líneas |
| **Eurostat** | balance energético completo | la base de Prometeo |
| **INE** | población, renta y hogares por sección censal | la demanda, al detalle |

## 11. OurAirports — aeródromos y helipuertos

- **URL oficial**: <https://ourairports.com/data/> · descarga directa del CSV
  `https://davidmegginson.github.io/ourairports-data/airports.csv` (~12 MB global).
- **Cómo se obtiene**: `scripts/aeropuertos.py` baja el CSV, filtra `iso_country=ES`, descarta los
  `type=closed` y escribe `datos/aeropuertos.geojson` + su recibo.
- **Licencia**: **dominio público** (no hay restricción de reutilización).
- **Alimenta**: capa **Aeródromos y helipuertos (553)**: 310 aeródromos, 186 helipuertos, 34 aeropuertos
  regionales, 21 internacionales, 1 base de hidroaviones y 1 campo de globos. 52 con código IATA y 46 con
  vuelo regular.
- **Limitaciones**: es la **infraestructura física**, no el tráfico. Pasajeros y terminales son del MITMA
  (capa `terminales-aero`): las dos capas no se cruzan ni se suman. 36 aeródromos cerrados quedaron fuera
  a propósito (siguen en el CSV).

## 12. GDACS — alertas de desastre (Comisión Europea · JRC)

- **URL oficial**: <https://www.gdacs.org> · feed `https://www.gdacs.org/xml/rss.xml`.
- **Cómo se obtiene**: `scripts/gdacs.py` lee el RSS, filtra por bbox de España y **acumula** por
  `(tipo, id)` con ventana de 120 días.
- **Licencia**: abierta con atribución (servicio público de la Comisión Europea).
- **Alimenta**: capa **Alertas de desastre (120 días)**: inundación, terremoto, ciclón, volcán, sequía e
  incendio, con su nivel (verde/amarillo/naranja/rojo) **en el dato**, no en el estilo del visor.
- **Limitaciones**: el RSS solo publica lo vigente, así que sin acumular la capa estaría vacía casi
  siempre (una capa vacía no es una capa). El feed **no es constante en el formato**: unas alertas traen
  `geo:lat`/`geo:long` y otras `georss:point` («lat lon»); el capturador soporta las dos. Y devuelve
  **406** si se le pide `Accept: application/rss+xml`: hay que pedir `application/xml,text/xml`.

## 13. Evaluadas y descartadas (con el número medido)

Esta tabla es parte de la biblioteca: una fuente descartada con su motivo ahorra volver a sondearla.

| Fuente | Qué se probó | Resultado medido (2026-11-21) | Veredicto |
|---|---|---|---|
| **Safecast** (radiación, CC0) | `api.safecast.org/measurements.json?unit=cpm` con bbox de España | 2 años → **97 medidas en 1 celda de 5 km**, última **2024-11-21** | fuera: red inactiva en España. Ojo: sin `unit=cpm` devuelve `unit:"status"`, que no es radiación |
| **TeleGeography** (cables submarinos) | `submarinecablemap.com/api/v3/cable/cable-geo.json` | 756 KB, FeatureCollection válida | fuera: **licencia no libre** (© TeleGeography). Nada «pendiente» entra en el visor |
| **adsb.lol** (vuelos en vivo, ODbL) | `/api/planes` de un agregador que lo usa | 10.376 aeronaves, 5,3 MB | fuera de este repo: es vigilancia aérea, no infraestructura española. Mejor proyecto propio |
| **QLever** (`qlever.dev/api/osm-planet`, SPARQL) | consulta de `power=cable` + `location=underwater` con geometría | responde en 4 ms a patrones simples, pero **corta** la consulta con `OPTIONAL` de geometría | queda como vía alternativa a Overpass para consultas **simples**; no para volcados con geometría |
| **Global Energy Monitor** (plantas) | catálogo de plantas >50 MW | — | no entra: REE y el registro MITECO ya están, y son el productor oficial |
| **ENTSO-E** (carga de red) | — | — | ya cubierto por `scripts/entsoe.py` |

## 14. OpenStreetMap — accesibilidad ciclista por vía (cyclingallowed)

**Qué publica.** No publica un mapa de «bici permitida»: publica las etiquetas de cada vía
(`highway`, `bicycle`, `access`, `oneway`, `surface`, `foot`, `mtb:scale`). La clasificación en 12
clases es una **lectura** de esas etiquetas, y la más difundida es la del visor
<https://bertt.github.io/cyclingallowed/> (Bert Temme), que la aplica sobre la capa `transportation`
de OpenFreeMap.

- **Productor del dato**: © colaboradores de **OpenStreetMap** · <https://www.openstreetmap.org/copyright>
- **Cómo se obtiene**: extracto oficial de España en `.osm.pbf` (1,7 GB, sin clave) y las reglas
  replicadas sobre las etiquetas crudas → `scripts/ciclismo_osm.py`. Endpoint de las teselas para el
  cotejo: `https://tiles.openfreemap.org/planet` (TileJSON; plantilla versionada, **maxzoom 14**),
  capa `transportation` del esquema OpenMapTiles.
- **Licencia**: **ODbL 1.0** (comparte igual) → mezclarla con capas CC BY en un mismo producto hace
  que el conjunto herede ODbL. Atribución: «© colaboradores de OpenStreetMap».
- **Frecuencia**: continua (OSM se edita a diario); el extracto se regenera a diario.
- **Alimenta**: `datos/ciclismo_es.json` (5.848.803 vías, 1.782.643 km por clase),
  `datos/ciclismo_es_clases.csv`, `datos/ciclismo_madrid.geojson` (muestra de 9.333 vías) y
  `datos/ciclismo_verificacion_tiles.json`. **Método completo y límites: [`docs/ciclismo.md`](ciclismo.md).**
- **Limitaciones**: las teselas **no traen `osm_id`** (el `id` de la feature no es el de OSM) y a z14
  fusionan vías en `MultiLineString`; `surface` llega colapsada a paved/unpaved; `service` pierde
  `drive-through`/`emergency_access`; `access=destination|customers` se pierde (no hay clase
  condicional); `oneway:bicycle` no viaja (contraflujo invisible); la geometría se recorta al borde de
  la tesela. Medido en España: **47,7 % del kilometraje sale «dudoso»** porque 980.036 km no declaran
  `surface`. Cotejo teselas↔extracto: −0,46 % (Madrid) y +1,29 % (Barcelona) en kilómetros.
