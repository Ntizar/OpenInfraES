---
titulo: Guía de trabajo — OpenInfraES
fecha: 2026-11-16
---

# Guía de trabajo

Reglas del repositorio. Breves y obligatorias.

## Qué es esto

Un visor de la infraestructura **energética, de transporte y de riesgo** de España, con los datos
normalizados, verificados y con su fuente declarada. No es una copia de OpenInfraMap ni un mapa
decorativo: cada capa se puede rastrear hasta el organismo que publica el dato.

Documentación: [`docs/PROYECTO.md`](docs/PROYECTO.md) (visión general) · [`docs/DATOS.md`](docs/DATOS.md)
(cómo está organizado `datos/`: recibos, contratos y capas partidas) · [`docs/FUENTES.md`](docs/FUENTES.md)
(ficha por fuente oficial) · [`docs/apis.md`](docs/apis.md) (estado técnico) · [`docs/nap.md`](docs/nap.md).

## Las cinco reglas

1. **Los GeoJSON no se editan a mano.** Se regeneran con su script. Si un dato está mal, se corrige en
   la fuente o en el script, nunca en el fichero.
2. **Cada capa tiene su recibo.** `scripts/validar.py` falla si falta un `_recibo.json`, si un conteo no
   cuadra o si una capa se queda sin fuente en `datos/fuentes.json`.
3. **Nada inventado ni estimado sin marcar.** Si algo es calculado (km por haversine, caudal modelado,
   trazado incompleto), se declara en el propio dato y en la ficha.
4. **Atribución por capa.** OSM es **ODbL** (comparte igual); IGN/SCNE, MITMA y MITECO son **CC BY 4.0**;
   REE y OMIE tienen **condiciones propias**. Mezclar ODbL con CC BY en un mismo producto derivado
   obliga a ODbL para el conjunto.
5. **Toda cifra publicada lleva fecha de dato y de descarga.** No son lo mismo: el parte hidrológico es
   del 10 de noviembre aunque se descargue el 16.

Y una que se olvida porque no duele hasta que duele: **siete capas gordas se sirven troceadas** por
provincia o comunidad (`datos/<id>/`). Si regeneras una, corre `python3 scripts/partir.py` antes de
validar; `validar.py` da ROJO si los trozos no son los del fichero de hoy. Detalle en
[`docs/DATOS.md`](docs/DATOS.md).

## Cómo añadir una capa

El visor es un array y una carpeta de ficheros. Siete pasos; el validador comprueba cinco de ellos y
si sale ROJO no se publica.

1. **Script propio** en `scripts/<fuente>.py`: descarga, normaliza y escribe su `_recibo.json` (fuente,
   licencia, fecha, número de objetos). Si la fuente es una API OGC Features (MITECO, IDEE), no escribas
   otra descarga: añade una entrada al diccionario `CAPAS` de `scripts/miteco_ogc.py`.
2. **Fusionar antes que duplicar.** Si la entidad ya existe en otra capa, se funde por proximidad y se
   acumulan los campos; una chincheta por sitio físico. Patrimonio a 60 m (prioridad BIC > Castillo >
   Parador > Museo > Mirador > zona arqueológica > refugio > conjunto histórico > Humanidad > faro);
   EDAR a 150 m (OSM + I-ReWater + IGN). La fuente intermedia se marca en `INTERMEDIOS` de
   `fuentes_visor.py` o el catálogo cuenta el doble.
3. **Geometría lista para pintar.** Coordenadas a 5 decimales; líneas simplificadas a ~13 m
   (Douglas-Peucker); multipuntos desdoblados en puntos. Medido: 142 vías verdes pasaron de 27 MB a
   2,8 MB y 756 caminos de Santiago de 10 a 2,1 MB.
4. **Declarar la fuente** en `scripts/fuentes_visor.py` (hay `ALIAS_FICHERO` cuando el id del visor no
   sale del nombre del fichero) y en `scripts/cadenas.py` (productor → publica → descarga).
5. **Entrar en `CAPAS`** de `index.html` con `on:false` —el visor abre vacío, y es a propósito—,
   `zoomMin` si a escala nacional no aporta, color, `campos` y, si procede, `escala` o `colorCampo`.
6. **TTL en `scripts/catalogo.py`** (vivo, horario, diario, mensual, anual) y **cron con intérprete
   absoluto**: `openinfra-vivo.sh` si cambia en minutos u horas, `openinfra-semanal.sh` (lunes 04:30) si
   es trimestral o anual.
7. **Pasar la puerta y verificar lo servido**:

   ```bash
   python scripts/fuentes_visor.py && python scripts/catalogo.py \
     && python scripts/cifras.py && python scripts/validar.py    # RESULTADO: VERDE
   git push origin HEAD:main && git ls-remote origin main | head -1
   curl -sI "https://ntizar.github.io/OpenInfraES/datos/<fichero>.geojson?cb=$(date +%s)" | head -1
   ```

   Pages tarda 3-5 minutos y la caché miente: sin `?cb=` no has comprobado nada.

`validar.py` comprueba ahora, capa a capa: que el GeoJSON existe, que tiene procedencia (recibo junto
al fichero, recibo de carpeta o entrada en `fuentes.json`), que no arranca encendida y que no hay ids
repetidos.

### Errores que ya han costado una tarde

| Síntoma | Causa | Arreglo |
|---|---|---|
| Fichero de 42 bytes | geometría `Point` tratada como `MultiPoint` | mirar `geometry.type` |
| HTTP 500 desde el segundo bloque | el REST del IGN no pagina con `resultOffset` | `returnIdsOnly` + `OBJECTID IN (...)` |
| GeoJSON de 27 MB | un vértice por metro | Douglas-Peucker |
| Capa «SIN DECLARAR» en Salud | id del array ≠ clave de `fuentes.json` | `ALIAS_FICHERO` |
| El catálogo cuenta el doble | fuente intermedia listada como capa | `INTERMEDIOS` |
| Push rechazado en el cron | cambios locales en el clon de producción | trabajar en otro clon |

## Reglas de rendimiento (medidas, no supuestas)

- **Carga bajo demanda**: el visor abre **vacío** y no descarga nada hasta que enciendes una capa.
  Es a propósito: con ocho capas de arranque el mapa salía saturado y no se entendía qué se estaba
  viendo.
- **Puntos densos, agrupados con cifra**: por debajo de `zoomDetalle` los puntos se agregan por celda
  y cada burbuja **lleva el número dentro** (y crece con el número). Sin cifra, 20.000 puntos son una
  alfombra naranja; en móvil la celda se agranda ×1,8 porque caben tres veces menos. Si la capa
  colorea por atributo (`colorCampo`), la burbuja toma **el color del tipo dominante** de la celda:
  una burbuja verde de 40 es «40 campings», no una mezcla.
- **Etiquetas de la ficha por capa**: `etiquetas:{municipio:"Municipio"}` corrige el diccionario
  cuando la fuente usa la misma clave para otra cosa (el IGN llama `municipio` al nombre; OSM, al
  código). Sin eso, la ficha de un camping decía «Núcleo municipal: Ribas de Sil».
- **LOD por zoom (`zoomMin`)**: por debajo de su zoom recomendado la capa **se atenúa**, no se retira
  (David: «todas las capas tienen que poder verse en cualquier zoom»; retirarlas parecía que estaban
  rotas). No se vuelve a descargar nunca: el fichero se pide una sola vez por sesión.
- **Puntos: solo lo que cae en la vista**, con margen, y se repintan al mover.
- **Un popup reutilizable**, no un `bindPopup` por feature.
- Antes de decir «va más fluido», **mide**: `OpenInfraES.bench()` para el arrastre y una secuencia de
  `setZoom` para el redibujado. El FPS del arrastre no mide el coste de los paths (Leaflet mueve el
  contenedor con `transform`).

## Credenciales

Van en `.env` (**ignorado por git**) y nunca en un commit, en la documentación ni en el chat. El
validador no las lee; los scripts sí. Verificado con `git grep` que no aparecen en el historial.

## Limitaciones conocidas (no son bugs)

- **Red de transporte** (220/400 kV), no distribución.
- **No hay generación por planta** en la API pública de REE; hace falta ENTSO-E.
- **No hay tensión de red por nudo** en ninguna API pública.
- **El Tajo-Segura solo está mapeado hasta Alarcón** en OSM; el resto no existe con nombre.
- **El caudal de los ríos es modelado** (GloFAS, rejilla ~5 km), no aforo oficial.
- **AEMET, ENTSO-E y NAP** requieren clave; dos están sin tramitar.
