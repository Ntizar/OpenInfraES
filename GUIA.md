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

Documentación: [`docs/PROYECTO.md`](docs/PROYECTO.md) (visión general) · [`docs/FUENTES.md`](docs/FUENTES.md)
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

## Cómo añadir una capa

1. **Script propio** en `scripts/<fuente>.py`: descarga, normaliza y escribe su `_recibo.json`.
   Si la fuente es una API OGC API Features (MITECO, IDEE), no escribas otra descarga: añade una
   entrada al diccionario `CAPAS` de `scripts/miteco_ogc.py`.
2. **Simplificar** si trae geometría: `scripts/simplificar.py` con su tolerancia, o en el propio
   capturador cuando la capa llega de una API (`simplificar: 0.0002` en `miteco_ogc.py`), dejando la
   tolerancia en el recibo (`simplificado_m`).
3. **Declarar la fuente** en `scripts/fuentes_visor.py` (el id del visor y el id del origen no siempre
   coinciden: hay un mapa de alias) y en `scripts/cadenas.py` (productor → publica → descarga).
4. **Añadir la capa** al array `CAPAS` de `index.html`, con `zoomMin` si a escala nacional no aporta.
5. **Pasar el validador**: `python scripts/validar.py` → `RESULTADO: VERDE`.
6. **Commit en castellano** describiendo la capa y su fuente.

## Reglas de rendimiento (medidas, no supuestas)

- **Carga bajo demanda**: ninguna capa se descarga hasta que se enciende. El visor no pide nada al abrir
  que no esté en las capas de por defecto.
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
