# Centro de Descargas del CNIG: qué hay, qué tenemos y qué falta

Sondeo completo del catálogo el **2026-11-25** (125 series, 9 categorías). Este documento existe
para no repetir el barrido: si vuelves a mirar el Centro de Descargas, empieza por aquí.

Fuente: <https://centrodedescargas.cnig.es/CentroDescargas/buscar-mapa>
Ficha de cada serie: `catalogo.do?Serie=<código>` (de ahí salen formato, unidad de descarga y
número de ficheros).

## 1. El Centro de Descargas no es una API, pero el IGN tiene siete puertas

La descarga del Centro es un `POST` a `descargaDir` con `nav_signature` y un campo trampa
(`secuencial_descarga_9f713b4d`). No se scrapea: no hay endpoint estable y forzarlo es pelear con
un anti-bot. Sirve como **inventario de lo que existe**, no como tubería.

Lo que sí es una API, medido el 2026-11-25:

| servicio | qué da | estado |
|---|---|---|
| ArcGIS REST `serviciosgis.ign.es/servicios/rest/services` | **168 servicios · 675 capas** (612 reales): SignA, Redes de Transporte, Hidrografía, Hosted, ADE | 200, **sin clave** — la mina |
| WMS `www.ign.es/wms-inspire/ign-base` | solo cartografía de fondo (4 capas) | 200 |
| WMTS `www.ign.es/wmts/ign-base` | teselas de fondo (150 KB de capabilities) | 200 |
| WFS `www.ign.es/wfs-inspire/...` | — | **404**, ahí no hay WFS |
| CSW IDEE `www.idee.es/csw-inspire` | metadatos, no datos | no responde desde la VM (000) |
| Geocodificador CartoCiudad `www.cartociudad.es/geocoder/api/geocoder` | direcciones → coordenada | **200, sin clave** |
| Centro de Descargas `descargaDir` | SHP / GPKG / GeoTIFF | protegido (honeypot) |

Barrido reproducible del árbol ArcGIS: `~/.hermes/cache/scratch/cnig/barrido_servicios_ign.py`
(168 servicios, ~2 min) → `servicios_ign.json`.

## 2. Lo que se ha añadido hoy

`espacios-protegidos` pasa de 246 a **873 features** (+627), con un servicio que el visor no
usaba: `Signa/06_espacios_protegidos`.

- Paisajes protegidos: 67 · Monumentos naturales: 302 · Reservas naturales: 243
- Áreas marinas protegidas: 2 · Geoparques: 18
- 5 paisajes que ya venían como «Otro espacio protegido» se **reclasifican**, no se duplican.
- Atributo nuevo en toda la capa: **`provincia`** (y `ccaa` en geoparques), que la ficha no tenía.
- Trampa medida: con `maxAllowableOffset=0.0015` el servicio devuelve **96 de 302 monumentos
  degenerados** y se perdían en silencio. Ahora se piden sin simplificar y se redondea en local,
  conservando el anillo fino cuando el polígono es de dos manzanas.

`nucleos` es capa nueva: **37.469 núcleos de población** con población, hombres y mujeres por
núcleo (`Signa/01_unidades_administrativas/12`). El padrón que teníamos estaba agregado a
municipio, así que una pedanía de 40 habitantes no existía en el visor. Suma 47,4 M de habitantes
frente a los 49,1 M del padrón: la diferencia es población que el BTN no asigna a ningún núcleo,
y se declara en el recibo.

Recibo: `datos/espacios_protegidos_recibo.json` (fuente, licencia, método, fecha de descarga,
recuento por figura). Servicio vivo: no hay fecha de referencia del IGN por elemento; la edad que
publica el catálogo es la de descarga.

## 3. Lo que ya teníamos y NO se duplica

| Serie CNIG | Dónde está ya en el visor |
|---|---|
| CartoCiudad (`02122`) | `cp` + `callejero.py`: CP → municipios con INE y padrón |
| BTN-POI (`BPOIS`) | 20 capas `ciudad-*` desde SignA (`03_construcciones_otros`) |
| Redes de transporte (`REDTR`) | `carreteras` (MITMA), `adif-tramos`, `nap-*`, `vias-verdes` |
| Hidrografía (`HIDRO`) | `rios-mtn`, `presas`, `canales`, `aguas estancadas` (SignA/HIDRO) |
| Poblaciones (`POBLA`) y Nomenclátor (`NGMEN`) | **`nucleos` añadido hoy** (37.469, con población por núcleo); `municipios` con padrón INE 2025 |
| Límites (`LILIM`) | `municipios`, `provincias`, `ccaa` (INE/Eurostat) |
| LIC y ZEPA (`10`, `11`, `12`) | `red-natura` (1.790 espacios) |
| Geoparques (`GEOPA`) | **añadido hoy** vía SignA, mismo dato y servicio abierto |

## 4. Lo que falta y es candidato

| Serie | Qué aporta | Formato · ficheros | Coste |
|---|---|---|---|
| `LICOS` Línea de costa | No hay nada de costa; `dpmt` es dominio público, no línea | SHP · 1 | bajo: 1 fichero, atributos escasos |
| `02113` CORINE Land Cover | Usos del suelo (44 clases) | GPKG · 10 | medio: hay que simplificar y decidir la clase |
| `MSIN` Suelo industrial (caso de uso SIOSE) | Polígonos industriales; hoy solo hay puntos `ciudad-*` | GPKG · 2 | medio: encaja con «infraestructura» |
| `SIOAR` / `SIOSE` | Ocupación del suelo 1:25.000 / alta resolución | GPKG · 184 / 144 | alto: pesado, por CCAA |
| `ECLIP` Trío de eclipses | Franjas de totalidad 2026-2027 | GPKG+KML · 9 | bajo, pero es novedad, no infraestructura |
| `MPIFL` Peligrosidad por inundación | Zonas inundables T=10/100/500 | GeoTIFF · 5.507 | alto: es ráster, pide teselas; el vectorial está en SNCZI (MITECO) |
| `08_redes_geodesicas/3` Mareógrafos | 10 puntos con enlace al PSMSL: nivel del mar medido | 1 consulta | bajo |
| `03_construcciones_otros/11` Faros | 278, con BIC, municipio y provincia | 1 consulta | bajo |
| `Hosted/intensidades_tratado/0` Intensidades de tráfico | **88.232 registros** con fecha, intensidad y municipio; sin geometría, hay que unirlos con los aforos | 1 tabla | medio |
| `04_hidrografia/9` Balsas y estanques | 343.380 puntos | — | alto: ruido, no capa |

Lo que aparece en el árbol y **ya tenemos** (no repetir): subestaciones, depuradoras, hospitales,
nucleares, puertos, aeropuertos, helipuertos, faros del patrimonio, cuencas, embalses, antenas,
gasolineras, depósitos.

## 5. Lo que se descarta y por qué

Imágenes (PNOA, vuelos históricos), MDT/LiDAR y cartografía en PDF: son GB y no se pintan como
capa vectorial en un visor de 3,9 GB de RAM. Bases topográficas BTN25/BTN100/BC200/BC500: duplican
SignA a otra escala con mucho más peso. Mapas provinciales/autonómicos y documentación antigua: no
son datos.

## 6. Cómo se vuelve a comprobar

```bash
python3 ~/.hermes/cache/scratch/cnig/barrido_cnig.py    # 125 fichas → series.json (1 min)
```

El barrido saca por serie: título, SRS, unidad de descarga, formatos y nº de ficheros. Lo que no
está aquí es que no existe en el catálogo a día de hoy.

## Anexo · Las 125 series medidas

| código | formatos | ficheros | qué es (de la ficha) |
|---|---|---|---|
| `02101` | Shapefile (.shp), GeoPackage | 9500 | ETRS89 en la península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `02105` | GeoTIFF y ECW, acompañados d | 1089 | Ficheros ráster georreferenciados de la serie Mapas Provinciales a escala 1:200. |
| `02107` | COG (Cloud Optimized GeoTIFF | 1524 | Se ha obtenido por interpolación a partir de la clase terreno de vuelos LIDAR de |
| `02109` | COG (Cloud Optimized GeoTIFF | 77 | Se ha obtenido por interpolación a partir de la clase terreno de vuelos LIDAR de |
| `02113` | Geopackage (.gpkg) y Geodata | 10 | Mapa de ocupación del suelo en España escala 1:100.000 correspondiente al proyec |
| `02118` | DGN y GeoPDF | 113 | En esta serie se incluyen los ejemplares más antiguos obtenidos por generalizaci |
| `02122` | Geopackage (.gpkg) | 52 | de nivel nacional, regional y local. A estos elementos se les ha asignado los mu |
| `02211` | COG (Cloud Optimized GeoTIFF | 13077 | Cada mosaico se forma seleccionando, de entre toda la información de ortofotogra |
| `02309` | JPG (sin georreferenciar con | 369 | Los ficheros digitales proceden del escaneado de los mapas impresos en papel con |
| `02310` | JPG (sin georreferenciar con | 53 | Los ficheros digitales proceden del escaneado de los mapas impresos en papel con |
| `ACLLI` | PDF | 99039 |  |
| `ARCHI` | Geopackage (.gpkg) y KML | 2 | Este producto es una guía electrónica y un directorio de archivos de España e Ib |
| `AREAJ` | KML, GPX y shapefile (.shp) | 3 | tiene como fines promover la movilidad territorial a través de los albergues juv |
| `BC200` | Shapefile (.shp) | 53 | Es un conjunto continuo de datos geográficos diseñado para su explotación en Sis |
| `BC500` | Shapefile (.shp) | 1 | Es un conjunto continuo de datos geográficos, derivado de la BCN200, diseñado pa |
| `BPOIS` | Shapefile (.shp) y Geopackag | 20 | ETRS89 en la península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `BT100` | Shapefile (.shp) | 10 | ETRS89 en la Península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `CAANE` | Shapefile (.shp), GeoPackage | 8 | Bases cartográficas simplificadas de España, Europa, el mundo u otras áreas geog |
| `CAANT` | JPG (sin georreferenciar con | 1752 | Colección digital procedente de los fondos cartográficos del Instituto Geográfic |
| `CACID` | KML, GPX y shapefile (.shp) | 299 | se desenvuelven principalmente por los territorios geográficos y literarios que  |
| `CAGUA` | KML, GPX y geopackage (.gpkg | 249 | El objetivo de esta Red de Cooperación es recuperar y promocionar los caminos hi |
| `CCINT` | PDF | 12008 | Documentación asociada a la elaboración de las planimetrías, que describe los ca |
| `COSTA` | ECW | 12140 | Fotogramas en color obtenidos del vuelo encargado por el Instituto Geográfico Na |
| `CSANT` | KML, GPX y shapefile (.shp) | 2231 | Las rutas del Camino Francés, Caminos Andaluces, Caminos de Galicia, Caminos del |
| `CUACA` | Shapefile (.shp) | 1 | Las cuadrículas cartográficas oficiales han sido definidas en Real Decreto 1071/ |
| `CVMOV` | MBTiles | 2 |  |
| `ECLIP` | Geopackage (.gpkg) y GeoTIFF | 9 | Grupo de ficheros con las efemérides de los eclipses totales de Sol del 12 de ag |
| `EVELO` | KML, GPX y shapefile (.shp) | 191 | Son las etapas españolas de la red europea de rutas ciclistas de larga distancia |
| `FEDME` | KML, GPX y shapefile (.shp) | 6923 | Etapas de los Senderos de Gran Recorrido (GR), de los Senderos de Pequeños Recor |
| `FOA30` | COG | 2726 | Fotogramas en blanco y negro con escalas aproximadas entre la 1:600 y la 1:15300 |
| `FOA40` | COG | 13387 | Fotogramas en blanco y negro con escalas aproximadas entre la 1:6000 y la 1:1900 |
| `FOA50` | COG | 21498 | Fotogramas en blanco y negro con escalas aproximadas entre la 1:6000 y la 1:2130 |
| `FOT00` | ECW | 664194 | Fotogramas de los vuelos fotogramétricos de 2004, 2005, 2006, 2007, 2008, 2009 y |
| `FOT10` | ECW y COG (Cloud Optimized G | 550422 | Fotogramas de los vuelos fotogramétricos de 2011, 2012, 2013, 2014, 2015, 2016,  |
| `FOT20` | COG (Cloud Optimized GeoTIFF | 244611 | Fotogramas de los vuelos fotogramétricos de 2021, 2022, 2023, 2024 y 2025 del Pl |
| `FPLEB` | COG (Cloud Optimized GeoTIFF | 49 | Mosaicos de los fotoplanos originales a escala 1:10.000 del vuelo histórico de l |
| `FSGPC` | COG y JP2 | 15928 | Vuelo fotogramétrico en color y blanco y negro de todo el territorio nacional a  |
| `GEOPA` | KML y shapefile (.shp) | 20 | Recorre a lo largo y ancho de nuestro país los geoparques mundiales reconocidos  |
| `HIDRO` | Geopackage (.gpkg) y shapefi | 45 | Base de datos a escala 1:5000 que contiene los objetos geográficos relacionados  |
| `HKPUP` | JPG (sin georreferenciar con | 9589 |  |
| `HRLLJ` | PDF (con GML adjunto) | 24916 | Documentos emitidos por el Registro Central de Cartografía que recogen la inform |
| `IESS2` | COG (Cloud Optimized GeoTIFF | 1846 | Producto ráster que representa el índice de severidad dNBR de los grandes incend |
| `INTMI` | ECW y JP2 | 134970 | Vuelo fotogramétrico realizado por encargo de los Ministerios de Agricultura, Ob |
| `LANDS` | COG (Cloud Optimized GeoTIFF | 24 | Los mosaicos nacionales históricos Landsat son un producto encuadrado dentro del |
| `LIBAR` | Shapefile (.shp) | 1 | Definen el origen desde el que se calculan los límites de los espacios marítimos |
| `LICOS` | Shapefile (.shp) | 1 | La línea de costa está formada por la línea de pleamar y la de bajamar, delimita |
| `LIDA2` | Fichero LAZ (formato de comp | 322264 | Ficheros digitales de nubes de puntos 3D obtenidos con LiDAR y de ámbito naciona |
| `LIDA3` | Fichero LAZ (formato de comp | 621035 | Datos distribuidos en ficheros de 1 × 1 km, con una densidad de 5 puntos/m² o su |
| `LIDAR` | Fichero LAZ (formato de comp | 327609 | Ficheros digitales de nubes de puntos 3D obtenidos con LiDAR y de ámbito naciona |
| `LIDEX` | COG (Cloud Optimized GeoTIFF | 37471 | Ortofotos expeditas obtenidas de forma simultánea al vuelo LiDAR, georreferencia |
| `LILIM` | Shapefile (.shp), geopackage | 4 | Recintos municipales, provinciales y autonómicos y líneas límite municipales, pr |
| `M1250` | GeoTIFF y ECW, acompañados d | 72 | Ficheros ráster georreferenciados de la serie Mapa de España Escala 1:1.250.000  |
| `M125I` | JPG (sin georreferenciar) | 8 | Se incluye información de orografía, hidrografía, comunicaciones, poblaciones, l |
| `M500I` | JPG (sin georreferenciar res | 15 | Los ejemplares en papel conservados por la Cartoteca del IGN han sido escaneados |
| `MAMOV` | MBTiles | 165 | Ficheros que permiten visualizar cartografía ráster correspondiente al mapa de E |
| `MAPLI` | COG (Cloud Optimized GeoTIFF | 1111 | Modelo Digital de Superficies sombreado al que se le han superpuesto dos capas p |
| `MAPNC` | KML y GPX | 873 | Conjunto de rutas para los Parques Nacionales de Ordesa y Monte Perdido, Caldera |
| `MARIF` | ASCII matriz ESRI (.asc) y P | 20250 | Modelos Digitales del Terreno (MDT) elaborados a partir de datos LIDAR PNOA del  |
| `MAUT` | DGN y GeoPDF | 36 | En esta serie se incluyen los ejemplares más antiguos obtenidos por generalizaci |
| `MAUTR` | GeoTIFF y ECW, acompañados d | 180 | Ficheros ráster georreferenciados de la serie Mapas Autonómicos (MAUT) a diversa |
| `MCASA` | PDF y JPG | 35 | Se muestran mapas del Camino Francés en España a escala 1:50.000 y 1:500.000, ma |
| `MDP02` | COG (Cloud Optimized GeoTIFF | 4152 | Es generado a partir de los MDT de la 2ª cobertura. Cada celda de la malla almac |
| `MDP05` | COG (Cloud Optimized GeoTIFF | 1179 | Es generado a partir de los MDT de la 1ª cobertura. Cada celda de la malla almac |
| `MDS02` | COG (Cloud Optimized GeoTIFF | 8153 | Se obtiene mediante interpolación de los puntos LiDAR clasificados como terreno, |
| `MDS05` | COG (Cloud Optimized GeoTIFF | 1180 | Se ha obtenido por interpolación a partir de las clases terreno, vegetación (baj |
| `MDS50` | COG (Cloud Optimized GeoTIFF | 14280 | Representa la superficie visible del territorio, incluyendo el terreno, la veget |
| `MDSE2` | COG (Cloud Optimized GeoTIFF | 1138 | Modelo digital de superficies normalizado de la clase edificación correspondient |
| `MDSNE` | COG (Cloud Optimized GeoTIFF | 1180 | Modelo digital de superficies normalizado de la clase edificación correspondient |
| `MDSNV` | COG (Cloud Optimized GeoTIFF | 1180 | Modelo digital de superficies normalizado de la clase vegetación correspondiente |
| `MDSV2` | COG (Cloud Optimized GeoTIFF | 1138 | Modelo digital de superficies normalizado de la clase vegetación correspondiente |
| `MDT01` | COG (Cloud Optimized GeoTIFF | 34573 | Se ha obtenido por interpolación, a partir de la clase suelo, de los vuelos LiDA |
| `MDT02` | COG (Cloud Optimized GeoTIFF | 8308 | ETRS89 y WGS84. ETRS89 en la península, Illes Balears, Ceuta y Melilla, y REGCAN |
| `MDT05` | COG (Cloud Optimized GeoTIFF | 1525 | ETRS89 en la península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `ME200` | GeoTIFF y ECW, acompañados d | 27 | Ficheros ráster georreferenciados de la serie Mapa de España Escala 1:200.000 (M |
| `ME500` | ECW | 2 | Es una cartografía derivada continua que cubre el país, generada mediante la sim |
| `MIN50` | JPG (sin georreferenciar con | 1094 | Las minutas MTN50 (1910-1970), coloquialmente llamado catastrón, por el tipo de  |
| `MIPAC` | JPG (sin georreferenciar con | 33872 |  |
| `MLID2` | ECW | 1161 | Modelo Digital de Superficies sombreado al que se le han superpuesto dos capas p |
| `MPEIC` | ASCII matriz ESRI (.asc) y P | 160 | », contienen información que puede ser utilizada en parte o en su integridad, si |
| `MPGEO` | JPG (sin georreferenciar) y  | 43 | El producto contiene tres tipos diferentes de documentos: mapas constitutivos de |
| `MPIFL` | GeoTIFF | 5507 | Mapas de Peligrosidad por inundación fluvial elaborados por el Ministerio para l |
| `MPPNN` | PDF | 47 | Mapas con sombreado de relieve y simbología especial a escala 1:25.000 con las r |
| `MSIN` | Geopackage (.gpkg) | 2 | Los archivos han sido generados mediante una revisión visual y la edición de la  |
| `MUNFP` | Con georreferenciación (Geot | 134 | Contienen información general sobre la ubicación y las características físicas o |
| `MUSEO` | Geopackage (.gpkg) y KML | 2 | Datos procedentes del Ministerio de Cultura en la que se puede consultar la temá |
| `MV125` | DGN y GeoPDF | 20 | La serie reúne distintas ediciones desde el año 2000 hasta la actualidad e inclu |
| `NAC84` | COG y ECW | 49157 | Fotogramas en blanco y negro procedentes del vuelo encargado por el Instituto Ge |
| `NGBES` | Base de datos de Access (.ac | 2 | Base de datos con la relación de topónimos con sus correspondientes coordenadas  |
| `NGMEN` | Base de datos de Access (.md | 1 | Base de datos con la información (denominaciones, coordenadas, población, etc.)  |
| `OFINT` | ECW | 586 | Vuelo realizado entre los años 1976 y 1986, por encargo de los Ministerios de Ag |
| `OFNAC` | ECW | 381 | Vuelo fotogramétrico realizado entre los años 1981 y 1986 por encargo del Instit |
| `ORVER` | COG (Cloud Optimized GeoTIFF | 14 | Ortoimágenes verdaderas generadas a partir de la orientación del vuelo fotogramé |
| `PLEDI` | JPG (sin georreferenciar con | 433 | Ficheros digitales procedentes del escaneado de planos de edificios singulares.  |
| `PLPOB` | JPG (sin georreferenciar con | 9677 | Ficheros digitales procedentes del escaneado de planos manuscritos de cascos urb |
| `PNOAH` | COG (Cloud Optimized GeoTIFF | 35128 | Cada mosaico se forma seleccionando, de entre toda la información de ortofotogra |
| `PNOAP` | COG (Cloud Optimized GeoTIFF | 6680 | Se hallan disponibles hasta que se dispongan de las ortofotos definitivas. Este  |
| `PNOIR` | COG (Cloud Optimized GeoTIFF | 8622 | Mosaicos de ortofotos más recientes disponibles en Falso Color Infrarrojo, del P |
| `POA10` | COG (Cloud Optimized GeoTIFF | 3840 | Mosaicos de ortofotos históricos de diferentes años de vuelos realizados por div |
| `POBLA` | Geopackage (.gpkg) | 52 | Base de datos georreferenciada que representa la localización y la geometría de  |
| `QUINQ` | COG | 27417 | Vuelo fotogramétrico realizado por encargo del Instituto Geográfico Nacional. Fo |
| `R2000` | GeoTIFF y ECW, acompañados d | 8 | ETRS89 en la Península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `RCARV` | KML, GPX y shapefile (.shp) | 11 | permiten conocer el legado artístico, histórico cultural y gastronómico del mona |
| `REDGE` | KMZ y hoja Excel (.xls) | 2 | Información de la red de estaciones permanentes GNSS (ERGNSS), redes geodésicas  |
| `REDTR` | Geopackage (.gpkg), shapefil | 119 | Conjunto de datos vectoriales de cobertura nacional que representa las redes de  |
| `RIMBA` | KML, GPX y shapefile (.shp) | 1155 | IMBA España está evitando el cierre y rescatando de su olvido y desaparición más |
| `RTANE` | Los mapas están disponibles  | 5422 | Los mapas temáticos del Atlas Nacional de España (ANE) son representaciones gráf |
| `RTCAR` | KML, GPX y shapefile (.shp) | 3 | permiten disfrutar del arte desarrollado a lo largo del Paleolítico Superior, el |
| `RTCNT` | KML, GPX y shapefile (.shp) | 1483 | Este programa pone en servicio más de 10.600 km de caminos naturales de los cual |
| `RTPAS` | KML, GPX y shapefile (.shp) | 29 | aúna historia, patrimonio artístico, tradiciones, gastronomía y naturaleza de di |
| `RTVPL` | KML, GPX y shapefile (.shp) | 120 | es una ruta histórica que desde el siglo VII a. de C. permitía el comercio convi |
| `RUIZA` | ECW | 5468 |  |
| `RUSTJ` | KML, GPX y shapefile (.shp) | 5 | Rutas norte y sur desde Ávila hasta Alba de Tormes, que unen la cuna y el sepulc |
| `SENT2` | COG (Cloud Optimized GeoTIFF | 102 | Mosaicos de ortoimágenes Sentinel 2 del programa europeo Copernicus a 10 metros  |
| `SIOAR` | Geopackage (.gpkg) y Geodata | 184 | El SIOSE AR (Sistema de Información de Ocupación del Suelo en España de Alta Res |
| `SIOSE` | Geopackage (.gpkg) y Geodata | 144 | El SIOSE (Sistema de Información de Ocupación del Suelo en España) es la base de |
| `T2002` | COG (Cloud Optimized GeoTIFF | 4445 | ETRS89 en la Península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `T25C2` | COG (Cloud Optimized GeoTIFF | 4287 | ETRS89 en la Península, Illes Balears, Ceuta y Melilla, y REGCAN95 en Canarias ( |
| `TESAN` | XML, RDF y CSV | 1 | El tesauro del Atlas Nacional de España (ANE) es una herramienta para la búsqued |
| `V2000` | GeoPDF | 2 | Ficheros generados a partir de la generalización del mapa físico de España a esc |
| `VAMSB` | ECW | 1154 | Vuelo realizado por el Army Map Service de EEUU entre enero de 1956 y noviembre  |
| `VIAVE` | KML, GPX y geopackage (.gpkg | 293 | , desarrollado actualmente por el Ministerio de Transportes y Movilidad Sostenib |
| `VOLIS` | ECW | 913 | Estas ortofotos realizadas por el Ministerio de Agricultura se usaron para la cr |
| `VREFE` | JP2 | 2488 | Fotogramas del vuelo fotogramétrico de la Comunidad de Madrid y alrededores enca |
| `VSIGP` | ECW y COG | 1180 | Estas ortofotos fueron desarrolladas por el Ministerio de Agricultura para la id |
| `ZEEZM` | Shapefile (.shp) | 1 | Límites del Mar Territorial y la Zona Contigua en el Golfo de Vizcaya; límites d |
