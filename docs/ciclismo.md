---
titulo: Accesibilidad ciclista en OSM — la regla de cyclingallowed, replicada y medida
fecha: 2026-11-23
ambito: espana
estado: publicado
fuentes: [osm, openfreemap, openmaptiles, cyclingallowed]
---

# Accesibilidad ciclista en OSM — qué vías admiten bicicleta

**<https://bertt.github.io/cyclingallowed/>** · dato de **© colaboradores de OpenStreetMap**,
licencia **ODbL 1.0** · teselas de **OpenFreeMap** (esquema **OpenMapTiles**) · código del visor:
<https://github.com/bertt/cyclingallowed>

OpenStreetMap no publica un «mapa de bici permitida»: publica etiquetas por vía (`highway`, `bicycle`,
`access`, `oneway`, `surface`, `foot`, `mtb:scale`) y cualquier clasificación es una lectura de esas
etiquetas. La más difundida es la de Bert Temme, que pinta 12 clases sobre la capa `transportation`
de OpenFreeMap. **Su regla no está en la documentación: está en el `CLASS_EXPR` de `index.html`**,
y es la que se replica aquí, literal, para poder medir España entera.

## 1. Cómo lo calcula (verificado en el código y en las teselas)

El visor no tiene datos propios: carga el estilo `https://tiles.openfreemap.org/styles/positron`
(fuente `openmaptiles` → `https://tiles.openfreemap.org/planet`) y añade una capa de línea
`source-layer: transportation` desde **z10**, que **solo existe hasta z14** (el `TileJSON` declara
`maxzoom: 14`). Filtro de la capa: `class` de carretera y `brunnel != tunnel`.

La clasificación es una expresión `case` (gana la primera que casa):

| # | Condición | Clase |
|---|---|---|
| 1 | `bicycle` ∈ {no, use_sidepath} **o** `access` ∈ {no, private} | **No (explícito)** |
| 2 | `bicycle` = dismount | **Desmonte** |
| 3 | `bicycle` ∈ {yes, designated, permissive} **o** `subclass` = cycleway | **Sí (explícito)** + sentido |
| 4 | `class` ∈ {motorway, trunk} **o** (`class`=path y `subclass` ∈ {footway, pedestrian, steps, platform, corridor}) | **No (implícito)** |
| 5 | `class` ∈ {primary, secondary, tertiary, minor} | **Sí (implícito)** + sentido |
| 6 | `class` ∈ {path, track} y (superficie sin pavimentar **o** `mtb_scale`) | **Probablemente no** |
| 7 | `class` = service y `service` ∈ {driveway, parking_aisle, drive-through, emergency_access} | **Probablemente no** |
| 8 | `class` ∈ {path, track} y (superficie pavimentada **o** `foot`=yes) | **Probablemente sí** |
| 9 | `class` = service | **Probablemente sí** |
| 10 | resto | **Dudoso** |

**Sentido** (solo en 3 y 5): `oneway`=1 → «solo un sentido»; `oneway`=-1 → «sentido contrario al
dibujo»; sin `oneway` → los dos.

`class` y `subclass` no son etiquetas de OSM: los deriva OpenMapTiles de `highway`
(`layers/transportation/{mapping.yaml, class.sql, transportation.yaml}`):

| `highway` | `class` | `subclass` |
|---|---|---|
| motorway, trunk, primary, secondary, tertiary (+ `_link`) | el mismo | — |
| unclassified, residential, living_street, **road** | `minor` | — |
| service | `service` | — |
| track | `track` | — |
| pedestrian, path, footway, cycleway, steps, bridleway, corridor | `path` | el valor de `highway` |
| `public_transport=platform` | `path` | `platform` |
| `construction` | `<tipo>_construction` | — (queda fuera del filtro) |
| railway, aerialway, `man_made=pier`, ferry | rail/transit/aerialway/pier/ferry | — (fuera) |

## 2. Lo que OpenMapTiles hace ANTES de que el estilo vea el dato

Esto es lo que no se ve leyendo el mapa, y cambia el resultado:

1. **`surface` se colapsa a `paved` o `unpaved`** (`surface_value()`, y usa `tracktype` si no hay
   `surface`; lista cerrada de valores). Las listas finas del estilo (asphalt, compacted, fine_gravel,
   sett…) **nunca casan**: en la práctica solo se distingue pavimentado de no pavimentado.
2. **`service` se limita** a spur/yard/siding/crossover/driveway/alley/parking_aisle:
   `drive-through` y `emergency_access` **no llegan nunca** a la tesela (regla 7 medio muerta).
3. **`access` se normaliza a `no`** cuando vale `private` o `no`. `destination`, `customers`,
   `delivery` y `permissive` **se pierden**: el mapa no tiene clase «condicional».
4. **`oneway` sale solo del tag `oneway`** (1 / −1). No se deduce de `junction=roundabout`, y
   `oneway:bicycle` no viaja en la tesela: el contraflujo ciclista es invisible.
5. **`bicycle`, `foot`, `horse`, `mtb:scale` pasan tal cual** (sin normalizar).
6. **A z12 y z13 la capa viene recortada**: `track`/`path` solo entran si tienen nombre, rango de ruta
   o `sac_scale`, y los `service` con driveway/parking_aisle se caen en z13. **La foto completa es z14.**
7. **La geometría se recorta a la tesela** (`ST_AsMVTGeom` + buffer) y a z14 las vías con las mismas
   propiedades vienen **fusionadas** en un `MultiLineString`: no se puede comparar vía a vía.
8. **El `id` de la feature no es el `osm_id`** (comprobado: una vía del centro de Madrid con id
   43080742 en la tesela es un arroyo de Alabama en OSM). Para cruzar con OSM hay que hacerlo por
   reparto de kilómetros o por geometría, nunca por identificador.

## 3. España, medido (`datos/ciclismo_es.json`)

Extracto oficial de OSM de España (1.716.243.185 bytes, 23-11-2026), **5.848.803 vías y 1.782.643 km**
clasificadas con la regla de arriba (`scripts/ciclismo_osm.py`, 688 s).

| Clase | Vías | km | % km |
|---|---:|---:|---:|
| Sí (implícito) | 1.470.775 | 403.867 | 22,7 |
| Dudoso | 1.557.143 | **850.288** | **47,7** |
| Probablemente no | 473.184 | 190.168 | 10,7 |
| No (implícito) | 1.124.669 | 112.860 | 6,3 |
| Probablemente sí | 357.794 | 80.371 | 4,5 |
| Sí, solo un sentido (implícito) | 562.100 | 56.922 | 3,2 |
| Sí (explícito) | 134.316 | 51.856 | 2,9 |
| No (explícito) | 141.502 | 32.730 | 1,8 |
| Sí, solo un sentido (explícito) | 24.089 | 3.315 | 0,2 |
| Desmonte | 2.890 | 234 | 0,0 |
| Sí, sentido contrario (implícito/explícito) | 341 | 31 | 0,0 |

Por grupos: **sí 25,6 % · sí en un solo sentido 3,4 % · no 8,2 % · probable 4,5 % · probable no 10,7 %
· dudoso 47,7 % · desmonte 0,01 %**.

Y el desglose por tipo de vía que lo explica:

| `highway` | Vías | km | Lectura |
|---|---:|---:|---|
| **track** | 1.479.119 | **910.163** | la mitad del país en pistas agrícolas; casi todas sin `surface` |
| path | 499.745 | 200.192 | senderos: dudosos o probables, nunca «sí» por defecto |
| residential | 1.182.045 | 158.524 | el grueso del «sí implícito» |
| unclassified | 246.459 | 130.216 | idem |
| tertiary | 275.079 | 106.706 | idem |
| service | 564.801 | 69.920 | accesos: «probablemente sí» salvo driveway/parking |
| footway | 844.109 | 53.525 | «no implícito» (acera: no se circula) |
| secondary | 135.549 | 39.957 | sí implícito |
| motorway | 44.622 | 31.351 | no implícito |
| **cycleway** | 52.583 | **11.737** | **carril bici mapeado en España** |

**Las tres conclusiones que salen del dato, no de la impresión:**

1. **El 47,7 % del kilometraje es «dudoso», y no por culpa del clasificador**: 980.036 km de vías
   (55 %) no declaran `surface` ni `tracktype`, así que la regla 6/8 no puede decidir. El propio
   README del proyecto reconoce que «dudoso» es demasiado grueso (7.594 de 30.000 muestras en NL).
2. **Lo que sí está decidido es corto**: 25,6 % claramente permitido + 3,4 % en un solo sentido.
   El resto es pista, sendero o prohibición.
3. **Carril bici mapeado: 11.737 km.** Es la cifra utilizable hoy para cruzar con red viaria,
   estaciones o planes de movilidad; y es OSM, no el inventario oficial (que no publica geometría).

## 4. Verificación: la réplica coincide con lo que enseñan las teselas

`scripts/verificar_ciclismo_tiles.py` recalcula el reparto **desde las teselas z14 reales** (aplica
la expresión a los campos de la tesela, no a las etiquetas OSM) y lo compara con el del extracto:

| Zona | Teselas: vías / km | OSM: vías / km | Desvío en km | Desvío máximo por clase |
|---|---:|---:|---:|---:|
| Madrid centro (4 teselas z14) | 2.752 / 703 | 9.333 / 706 | **−0,46 %** | 1,3 pp |
| Barcelona Eixample (4) | 4.667 / 883 | 16.704 / 872 | **+1,29 %** | 0,6 pp |
| Gredos rural (4) | 9 / 17 | 18 / 36 | −53 % | 6,1 pp |

Las dos zonas urbanas cuadran al 1 % en kilómetros y las clases no se mueven más de 1,3 puntos. La
diferencia de Gredos **no es de clasificación**: en el campo las vías son pistas de kilómetros que
cruzan el borde de la tesela y OpenMapTiles **recorta la geometría**, mientras el extracto cuenta la
vía entera. Menos teselas y más largas = más recorte.

## 5. Conflictos medidos (los agujeros del clasificador, cuantificados)

| Situación en OSM | Vías | Qué hace el mapa |
|---|---:|---|
| `bicycle=yes/designated` + `access=private\|no` | 4.160 | **No (explícito)**: la regla 1 gana a la 3, aunque el `bicycle` sea explícito |
| `oneway` + `oneway:bicycle=no` (contraflujo) | 2.915 | «solo un sentido»: el contraflujo ciclista no existe en la tesela |
| `access=destination\|customers` (condicional) | 13.595 | sale como permitida o como dudosa; no hay clase condicional |
| Túneles | 2.276 km | excluidos a propósito (`brunnel=tunnel`): no se pintan |
| Áreas (`area=yes`: plazas, peatonales) | 29.831 | fuera del recuento (en el mapa salen como contorno) |

## 6. Licencia — leer antes de mezclar

El dato es **ODbL 1.0** (comparte igual). Mezclar esta capa con datos **CC BY** (BTN del IGN, MITMA)
en un mismo producto **hace que el conjunto herede ODbL**: es el mismo aviso que ya está en
`BIBLIOTECA.md`. La atribución obligatoria es «© colaboradores de OpenStreetMap»; el visor de Bert
Temme es el método, no el productor del dato.

## 7. Cómo se reproduce

```bash
python -m pip install osmium            # pyosmium: lee el .pbf sin base de datos
python scripts/ciclismo_osm.py          # usa/descarga el extracto en ~/.cache/openinfraes
python scripts/verificar_ciclismo_tiles.py
```

Salidas: `datos/ciclismo_es.json` (totales, clases, por tipo de vía, conflictos), `datos/ciclismo_es_clases.csv`,
`datos/ciclismo_es_recibo.json`, `datos/ciclismo_verificacion_muestra.json`,
`datos/ciclismo_madrid.geojson` (muestra dibujable de 9.333 vías) y
`datos/ciclismo_verificacion_tiles.json`.

El extracto **no entra al repo** (1,7 GB): vive en `~/.cache/openinfraes/` o donde diga
`OPENINFRAES_CACHE`.
