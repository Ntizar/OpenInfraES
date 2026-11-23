---
titulo: AEMET — avisos meteorológicos, con y sin geometría
fecha: 2026-11-16
ambito: riesgo
estado: publicado
---

# AEMET — avisos meteorológicos

Hay **dos vías** para los mismos avisos, y dan cosas distintas. Conviene saber cuál usar.

## Vía 1 — Meteoalerta con geometría (la buena)

AEMET publica las **zonas de aviso como polígonos**, sin clave, en la propia página de avisos.

```
https://www.aemet.es/es/eltiempo/prediccion/avisos
  -> /es/geojson/download/avisos/geojson_<epoch>.tar.gz     (~0,8 MB)
      av_hh_<elaborado>_penbal_<AAAAMMDDHH>CET_<...>.geojson   península y Baleares, por hora
      av_hh_<elaborado>_can_<AAAAMMDDHH>WET_<...>.geojson      Canarias, por hora
      r_D+N_<elaborado>_<area>_<AAAAMMDD><CET|WET>_<...>.geojson   resumen diario (respaldo)
```

El tar se **regenera cada hora**. Desde el **2026-11-23** el dato vivo está en la **rejilla horaria**
`av_hh_*`: un fichero por área y hora local de validez. Los `r_D+0_*` siguen viniendo pero **vacíos**
(167 bytes) mientras AEMET hace la migración; el script acepta las dos familias y usa la diaria solo si no
hay horarios con datos. Los ficheros de **menos de 300 bytes van vacíos**: esa área no tiene avisos.

```bash
python scripts/aemet_geo.py
```

Salida: `datos/aemet_zonas.geojson` (zonas con aviso, como polígonos) y su recibo.

La capa publica los avisos **vigentes o previstos en las próximas 48 h** (`ventana_horas` en el recibo).
Cada zona sale una vez, con su nivel máximo y la lista de avisos dentro; el recibo separa `vigentes` de
`previstas` en `por_estado`.

**Medido el 2026-11-23 (elaborado 10:48):** **21 zonas previstas, todas amarillas** (nevadas y costeros);
ninguna vigente en ese momento — el aviso de costeros del Ampurdán había caducado a las 11:59. El máximo
histórico medido fue de **70 zonas (59 rojas, 11 naranjas)** el 2026-11-18.

Capa **«Avisos AEMET (zonas)»** en el grupo Riesgo, con el relleno coloreado por nivel: amarillo, naranja
y rojo. Es la única capa del visor que cambia de color por feature.

## Vía 2 — Meteoalarm sin geometría

`https://feeds.meteoalarm.org/api/v1/warnings/feeds-spain` (EUMETNET, AEMET es el nodo español) da los
avisos en JSON, en abierto y sin clave: **351 avisos, 177 vigentes** el 2026-11-16.

Pero **no trae coordenadas ni polígono**: las áreas son **comarcas** («Interior de Pontevedra»,
«Albarracín y Jiloca»), 233 distintas, sin geometría. Por eso este feed **no se pinta**: se muestra como
lista en el panel de Riesgo, junto a la capa de zonas.

```bash
python scripts/aemet.py     # -> datos/aemet_avisos.json
```

## Trampas

- **El CAP de Meteoalarm viene en español y en inglés.** Sin filtrar por `language`, cada aviso se cuenta
  **dos veces**: 702 en vez de 351. Y el «evento» sale duplicado («vientos de nivel amarillo» y «Moderate
  wind warning» en la misma lista).
- **El tar.gz hay que buscarlo en el HTML de la página de avisos**, con su nombre exacto:
  `geojson_\d+\.tar\.gz`. La URL lleva un epoch que cambia en cada regeneración, así que no se puede
  construir a mano.
- **El HTML de AEMET viene en `iso-8859-15`, no en UTF-8.** Decodificarlo como UTF-8 destroza los acentos
  y el regex del enlace sigue funcionando, así que el fallo no se nota hasta que lees los nombres.
- **Los ficheros vacíos pesan menos de 300 bytes**, no cero. Comprobar `> 300` y no `> 0`, o se intenta
  parsear un GeoJSON de 200 bytes y salta una excepción que tumba el bucle.
- **`Nivel_COCO` y `Nivel_NENV` son códigos, no niveles: 3 = amarillo.** Leerlos como número pinta de rojo
  media España. El nivel sale del texto: `Sev_*` («Amarillo»/«Naranja»/«Rojo») y, si falta, de
  `Resum_*`/`Des_*` («Aviso de nevadas de nivel amarillo»).
- **Hay dos familias de campos en el mismo tar**: `*_COCO` (catálogo antiguo: costeros, lluvias) y `*_NENV`
  (avisos nuevos de Meteoalerta: nevadas, viento). Un parser que solo mire `Avis_COCO` pierde la mitad.
- **Una capa viva puede estar vacía de verdad** (no hay avisos, no hay incidencias). El validador lo admite
  si el recibo lo declara con fecha reciente y cuenta 0; si el recibo falta o está viejo, el vacío es una
  descarga rota y sale en rojo.
- **El esquema cambia sin avisar.** El 2026-11-23 los `r_D+0_*` pasaron a venir vacíos y el dato se mudó a
  `av_hh_*`. Por eso el script **falla sin escribir** cuando no reconoce ningún fichero: mejor una capa con
  fecha vieja y un aviso en la ejecución que una capa vacía publicada.
- **AEMET OpenData (`opendata.aemet.es`) exige clave** para `avisos_cap`. Ese camino no hace falta: el
  `tar.gz` de la web es el mismo dato con geometría y sin registro.

## Lo que hay en el repo de kit72h

El mecanismo salió de `scripts/noticias.py` de **`Ntizar/kit72h`**, que ya lo tenía resuelto para su cron
de noticias. Es el segundo caso en este proyecto donde un repo propio tenía la respuesta antes que la
búsqueda desde cero (el primero fue la cabecera `ApiKey` del NAP en `nap-dashboard`).