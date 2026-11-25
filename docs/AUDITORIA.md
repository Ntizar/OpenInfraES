# Respuesta a la auditoría v2 (19-11-2026)

La auditoría encontró seis problemas. Aquí está cada uno con lo que se ha hecho y cómo se
comprueba. Lo que no se ha cerrado se dice, no se maquilla.

## P1 · La prosa no describía el proyecto — **cerrado**

Decía 29 capas en la cabecera, 48 en su propia tabla y 28 en la biblioteca, mientras el visor
tenía 52 y el catálogo 73. Tres universos mezclados y ninguna cifra escrita a mano coincidía.

**Arreglo:** `scripts/cifras.py` cuenta donde están las cosas y reescribe los documentos.

| Universo | Dónde se cuenta | Valor hoy |
|---|---|---|
| Capas del visor | ids del array `CAPAS` de `index.html` | **52** |
| Grupos | valores distintos de `grupo` | **9** |
| Entradas de catálogo | claves de `datos/fuentes.json` | **73** |
| Organismos | organismos canónicos de `catalogo.json` | **15** |

`python scripts/cifras.py --check` devuelve **rc=1 si algo se desfasa**, y `validar.py` lo llama:
una cifra a mano ya no puede llegar a `main` sin que el CI se ponga rojo.

Además, las **5 capas sin ficha** que señalaba (`ine-ccaa`, `ine-densidad`, `ine-paro`,
`ine-provincias`, `estaciones-cercanias`) ya están declaradas. El listado de sin fuente del panel
de salud está en **0**.

## P2 · Los paneles «en vivo» servían fotos de hace días — **cerrado, y era peor de lo que decía**

La auditoría midió 1-3 días. Medido hoy: **30 capas superan su TTL** de las 73.

**Arreglo en dos partes:**

1. **Se declara, no se esconde.** `scripts/catalogo.py` calcula la caducidad **sobre la fecha del
   dato, no sobre la de descarga** — un fichero bajado hoy con un dato de hace tres días está
   caducado, y eso es lo que ve el lector. El panel de cada elemento lo muestra:

   > `licencia pendiente de evaluar` · `dato de hace 9 días (TTL 168 h)`

2. **Se refresca.** `.github/workflows/refresco.yml` corre **cada hora** (a los :07 UTC): demanda, precio,
   mix, avisos y sismos. Los pasos con `continue-on-error` hacen que la falta de una clave no
   rompa el workflow: el fichero anterior se queda y su fecha lo delata.

## P3 · Licencias sin evaluar (REE, OMIE, Renfe GTFS-RT) — **declaradas**

La licencia deja de ser texto suelto y pasa a ser un objeto con **tres estados**: `si`, `no`,
`pendiente`. Las tres fuentes señaladas quedan en **pendiente**, con el texto citado y la URL de
términos:

| Fuente | Estado | Motivo |
|---|---|---|
| **REE** | pendiente | Aviso legal §5: uso informativo no comercial; el resto exige autorización escrita. Condiciones de `apidatos` no localizadas |
| **OMIE** | pendiente | Sin cláusula de reutilización identificada |
| **Renfe GTFS-RT** | pendiente | Sin condiciones localizadas (las estaciones de `data.renfe.com` sí son CC BY 4.0) |

El KPI `⚖ 5 / 2` de la cabecera lo lleva a la vista: **5 licencias pendientes · 2 datos caducados**
entre las capas del visor. La regla queda escrita en `catalogo.json`: nada con estado `pendiente`
entra en un MCP público hasta cerrar su evaluación, y consultar en vivo no sustituye a evaluarla.

## P4 · La mezcla ODbL + CC BY — **aclarada**

La auditoría tiene razón: la ODbL define *Collective Database* y dice expresamente que una
colección de bases independientes **no** es *Derivative Database*. No hay contaminación automática.

Lo que sí lo son: las capas construidas **extrayendo** contenido OSM (líneas 220/400 kV,
gasoductos, EDAR, ríos, canales). Quedan bajo ODbL **capa a capa**, y el catálogo lo registra así
(`licencia.nombre`: «ODbL 1.0 · comparte igual en bases derivadas»). Atribución por capa derivada,
no por el conjunto.

## P5 · El catálogo no era un contrato — **cerrado**

`scripts/catalogo.py` genera `datos/catalogo.json` con el esquema de la sección 08:

```
id · titulo · organismo · producto
licencia{ estado, nombre, url_terminos }
endpoint · modo(foto|vivo) · frecuencia_fuente · ttl_segundos · ultima_verificacion
crs · fecha_dato · fecha_descarga · edad_dias · caducado
```

Y arregla las dos inconsistencias que señalaba:

- **Organismos canónicos.** `«I-ReWater HUB (Interreg) + INE»` → `I-ReWater HUB`;
  `«Visor Hermes — MITMA»` → `MITMA`. Las variantes se pliegan en una tabla.
- **`fecha_dato` y `fecha_descarga` separadas.** No son lo mismo y hasta ahora era un solo campo.

`fuentes.json` se queda como está: es lo que lee el visor. `catalogo.json` es el contrato.

## P6 · Sin series temporales — **abierto desde hoy**

`scripts/snapshot.py` archiva una entrada **por día** de cada capa viva en `datos/series/<capa>.json`.
El cron lo ejecuta en cada pasada, así que el día en curso se actualiza y los anteriores quedan
fijos.

```
python scripts/snapshot.py --lista
  aemet_zonas          1 días · de 2026-11-19 a 2026-11-19
  entsoe_mix           1 días · de 2026-11-19 a 2026-11-19
  omie_precio          1 días · de 2026-11-19 a 2026-11-19
  ree_vivo             1 días · de 2026-11-19 a 2026-11-19
  sismos               1 días · de 2026-11-19 a 2026-11-19
```

Hoy es el **primer día**. Una serie de un punto no es una serie: lo será cuando pasen los días.
No se promete `evolucion_embalse(año)` hasta que haya año.

## Lo que no se ha hecho, y por qué

- **Las 14 fuentes candidatas** (Adif, SAIH, Portus, Catastro, ENTSO-G…) **no se han integrado**.
  La propia auditoría pone primero el contrato (P5) y las cifras (P1), y eso es lo que se ha
  cerrado. Cada una exige medir su descarga y **leer su condición de redistribución** antes de
  entrar; añadirlas ahora sería sumar deuda al catálogo recién ordenado.
- **El MCP** no se ha empezado. La fachada única con adaptadores es la propuesta correcta y
  `docs/PATRON-MCP.md` es la receta que la alimenta.
- **Las tasas de las fuentes** siguen sin medir. La auditoría dice que ninguna cifra de tasas está
  verificada, y sigue siendo verdad.

## Cómo se comprueba todo esto

```bash
python scripts/fuentes_visor.py    # 73 entradas
python scripts/catalogo.py         # 5 pendientes de licencia · 30 caducadas
python scripts/cifras.py --check   # rc=0 si la prosa cuadra
python scripts/snapshot.py --lista # series archivadas
python scripts/validar.py          # VERDE, y falla si las cifras se desfasan
```
## Auditoría v3 — 19-11-2026

Reproducido en producción **antes** de tocar nada: con la capa de Cercanías apagada, su leyenda seguía
visible (`{hidden:false, de:"nap-lineas-cercanias", checked:false}`). La causa no era la leyenda: las
vistas temáticas y el enlace permanente apagaban capas tocando `chk.checked` y `mapa` por su cuenta, sin
avisar a nada. Corregido con **un solo camino** (`ponerCapa`) y **una sola dueña de la leyenda**
(`actualizarLeyenda`), más guardas en `pintarLeyenda` y en la llegada tardía del GeoJSON.

| Qué | Antes | Después |
|---|---|---|
| Escala del mapa | abajo-izquierda, tapada por la barra de estado (`elementFromPoint` devolvía el contador) | abajo-derecha, por encima del pie y visible |
| Leyenda al cambiar de vista | se quedaba abierta sobre una capa apagada | se esconde o pasa a la capa encendida |
| Bloque pegado en «Ver todas» | `setInterval` nuevo en cada clic (fuga) | eliminado |
| Código muerto | `ficha`, `fichaTren`, `colorEscala`, bloque `_btnTrenes` | borrado |
| Rutas `C:/Users/...` en scripts | 14 scripts | 0 (derivadas de `__file__`) |
| `_capturas/` | 27 MB, 40 PNG, **ningún** documento los citaba | retirado del repo (el historial los guarda) |
| Cifras del README | 28 capas / 7 grupos / 18.292 objetos | 53 / 9 / 80.719, **generadas** por `cifras.py` entre marcas |
| Trasvases en el panel | «118 tramos en 26 trazos» | «106 tramos en 11 trazos de 8 trasvases» (del recibo) |
| Panel «Qué es esto» | 74 capas y 10 organismos escritos a mano | 53 del visor · 74 del catálogo · 16 organismos, contados |

Y el panel de dato pasa a ser **el índice del dato**: métricas destacadas en grande, todos los campos
humanizados, procedencia y licencia en el pie, y **qué hay a menos de 30 km** (líneas, centrales,
embalses) pinchable para saltar de un dato a otro. Nuclear, embalses y desaladoras codifican su magnitud
en **tamaño y color**, con la leyenda como rampa de dos extremos.
