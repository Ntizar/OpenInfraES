# Capas pendientes de meter

Lista de trabajo, no de deseos. Cada fila dice **de dónde saldría el dato** y **cuánto cuesta**.
Lo verificado está probado con `curl` desde la VM; lo demás se marca como tal.

Estado a 2026-11-25: **101 capas**, 17 grupos, 126 entradas de catálogo.

---

## Prioridad 1 — lo que cierra huecos conceptuales

### 1. Relieve legible (curvas de nivel y MDT)
- **Qué aporta**: hoy el grupo «Relieve» son cimas y alineaciones. Sin sombreado ni curvas no se
  entiende un embalse de bombeo (cota superior / inferior) ni por qué una línea cruza un collado.
- **Fuente verificada**: `https://servicios.idee.es/wms-inspire/mdt` — capas `curvasnivel`,
  `EL.ContourLine`, `EL.ElevationGridCoverage`, `puntosacotados` (GetCapabilities comprobado).
- **Formato**: WMS imagen (el visor ya sabe pintar `tipo:"wms"` con EPSG:4326).
- **Coste**: bajo. Una capa, sin descarga, sin licencia que evaluar (IGN, CC BY 4.0).
- **Ojo**: el WMS no soporta 3857; el visor ya pide 4326 para estos servicios.

### 2. Hidráulica de bombeo, separada de la de gravedad
- **Qué aporta**: `hidro` ya filtra `["hydro","pumped_hydro"]` pero los pinta **igual**. El bombeo
  es otra cosa: mueve agua entre dos embalses y es lo que explica los saltos de cota.
- **Fuente**: la misma `datos/plantas.geojson` (ya descargada). Cero descarga nueva.
- **Coste**: muy bajo. Dividir la capa, color propio, y cruzar cada bombeo con sus dos embalses
  más cercanos para enseñar «superior / inferior» en la ficha.
- **Pendiente de decidir**: el cruce por proximidad es una **estimación**, no un dato del editor.
  Si se hace, la ficha debe decirlo.

### 3. Avisos meteorológicos en vigor (AEMET, CAP)
- **Qué aporta**: el visor tiene clima interpolado (IDW) pero no la alerta oficial: nivel, fenómeno,
  ámbito y vigencia. Es el dato que la gente mira de verdad.
- **Fuente**: AEMET publica CAP por fenómeno (`/documentos_d/eltiempo/prediccion/avisos/...`).
  Ya hay `scripts/aemet.py` en el repo: comprobar si sirve y ampliarlo, no reescribirlo.
- **Formato**: XML CAP → GeoJSON de zonas (AEMET ya tiene `aemet_zonas`).
- **Coste**: medio. Requiere parsear CAP y casar zona con polígono.

### 4. Incendios activos (EFFIS *near real time*)
- **Qué aporta**: la capa actual es el **histórico** de superficie quemada. `ms:effis.nrt.ba.poly`
  da lo que está ardiendo ahora (verificado en el GetCapabilities).
- **Fuente**: mismo WFS de EFFIS, capa `ms:effis.nrt.ba.poly`.
- **Coste**: bajo (el parser GML ya existe en `scripts/incendios_effis.py`).
- **Ojo**: TTL corto (1 h), y es MODIS: manchas de 250 m, no el parte oficial.

---

## Prioridad 2 — infraestructura que falta

### 5. Emisiones industriales (PRTR)
- Complejos con emisiones al aire, agua y suelo, declaradas por el propio industrial.
- `prtr-es.es`: descarga por complejo (Excel/CSV), no hay API. Coste **medio-alto** (scrapeo).
- Licencia: reutilización del MITECO, con atribución.

### 6. Puntos de recarga de vehículo eléctrico
- Registro del MITECO / plataforma de recarga. Cambia a menudo; TTL corto.
- Coste medio: hay que ver qué administración publica el listado completo.

### 7. Zonas inundables (ARPSI), por demarcación
- **No** por el SNCZI completo: sus shapefiles son de 834 MB por periodo de retorno.
- Vía viable: ARPSI (áreas de riesgo potencial significativo) por cuenca, mucho más ligero.
- Coste medio; hay que resolver una descarga por demarcación.

### 8. Vertederos y suelos contaminados
- MITECO publica inventario de suelos contaminados y vertederos. Coste medio.

### 9. Peajes y concesiones de autopistas
- MITMA publica el catálogo de concesiones (titular, tramo, año de reversión).
- Coste bajo si viene como tabla; la geometría se puede tomar de la red de carreteras.

### 10. Peligrosidad sísmica (no sismos)
- `sismos` es lo que ha temblado; falta el mapa de peligrosidad del IGME (aceleración esperada).
- Coste medio: raster o polígonos por comarca.

---

## Prioridad 3 — enriquecer lo que ya hay

### 11. Calidad del aire: valores en vivo
- Existe `calidad-aire-estaciones`; falta el dato de la última hora por estación (ICA).
- Fuente: MITECO / EEA. Coste medio.

### 12. Aforos: caudal en vivo
- Existe `aforos`; el SAIH publica caudal por estación. Cruzar ambos da «este río lleva X».
- Coste medio-alto según cuenca (cada confederación publica distinto).

### 13. Embalses: cota y volumen
- Existe `embalses` con volumen. Añadir **cota** permitiría ordenar bombeo superior/inferior
  de verdad, no por proximidad.

---

## Descartado conscientemente

- **SNCZI completo como objetos**: 834 MB por periodo; solo tiene sentido como WMS.
- **Cartografía catastral completa**: enormes volúmenes y licencia con condiciones propias.
- **Runt del IGN por municipio entero**: ya hay `nucleos`; el callejero a nivel nacional no
  cabe en GitHub Pages ni se lee en un mapa.

---

## Regla para cualquier capa nueva

1. Fuente con URL y licencia **evaluada** antes de escribir el script (no después).
2. `origen` declarado en `ORIGEN` (`api`, `fichero`, `visor`, `pdf`, `osm`, `comunidad`,
   `elaborado`): si sale de un PDF o de otro mapa, se dice.
3. Fecha del dato, fecha de descarga y **TTL** en `catalogo.py`.
4. Cadena completa: `fuentes_visor.py` → `catalogo.py` → `cifras.py` → `snapshot.py` → `validar.py`.
5. Nunca cargar las 101 capas a la vez para probar: por grupos, en pestaña nueva.
