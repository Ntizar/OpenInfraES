---
titulo: Los datos — organización del directorio datos/
fecha: 2026-11-25
---

# Los datos: qué hay en `datos/` y por qué

Esto es el mapa del almacén. El **procedimiento** (cómo se añade una capa, paso a paso) está en
[`GUIA.md`](../GUIA.md); el **porqué de cada fuente**, en [`FUENTES.md`](FUENTES.md). Aquí solo se
explica cómo está ordenado el directorio para que cualquiera —persona o agente— sepa qué puede
tocar, qué se regenera y dónde está el dato bueno.

## La regla que explica todo lo demás

**Ningún fichero de `datos/` se edita a mano.** Cada uno lo escribe un script de `scripts/`, se puede
volver a generar y lleva al lado su procedencia. Si un dato está mal, se corrige en la fuente o en el
script; editar el GeoJSON dura hasta la siguiente pasada y rompe la trazabilidad.

## El árbol

```
datos/
├── <base>.geojson            una capa = un fichero; el nombre da el id de la capa
├── <base>_recibo.json        su procedencia (obligatorio: sin recibo, validar.py en ROJO)
├── fuentes.json              ficha por id: organismo, licencia, jerarquía, publicaciones
├── catalogo.json             contrato machine-readable: TTL, frescura, avisos
├── _procedencia.json         qué se capturó, de qué fuente y con qué ficheros
├── agregados.json            cifras de cabecera del visor (no es capa)
├── agregado_*.csv            5 tablas planas para consultar sin abrir el mapa
├── municipios_mart.csv       tabla ancha municipal: renta + población + plantas (regenerable)
├── oficial/                  capas vectorizadas a mano desde un PDF/servicio sin GeoJSON
├── hermes/                   capas del visor de MITMA (Hermes), tal como las sirve
├── simplificado/             versión Douglas-Peucker de las capas gordas
├── series/                   series vivas en JSON (no son geografía: son tiempo)
└── <id-de-capa>/             capa partida en trozos por provincia o comunidad
    ├── index.json            índice: campo, total y caja de cada trozo
    └── <slug>.geojson        los trozos
```

Nombres: `x.geojson` ↔ `x_recibo.json` (misma base, sin sufijos). El id del visor sale del nombre con
guiones (`adif_tramos` → `adif-tramos`); las excepciones se declaran en `ALIAS_FICHERO`
(`scripts/fuentes_visor.py`) y no se adivinan.

## 1. Una capa: el GeoJSON y su recibo

El recibo es la ficha de identidad del fichero y lo escribe el mismo script que genera la capa:

```json
{
  "fichero": "datos/trafico_ccaa.geojson",
  "features": 7398,
  "fuente": "Red del Estado (MITMA, 2021) + redes autonómicas de Comunitat Valenciana (GVA · ICV, 2025) y Aragón (DGA, 2022)",
  "editor": "MITMA · DGC / GVA · Institut Cartogràfic Valencià / Gobierno de Aragón",
  "url": "https://…",
  "licencia": "Reutilización con atribución (Ley 37/2007) · MITMA, GVA y DGA",
  "descargado": "2026-11-25T11:44:46Z",
  "actualizado": "2021-12-31",
  "fecha_dato": "Estatal 2021 · Aragón 2022 · Comunitat Valenciana 2025 · Navarra 2025",
  "metodo": "Estatal: trafico_imd.geojson simplificado. CV: WFS 2.0 en GML (posList lat/lon)…",
  "detalle": { "Aragón": { "features": 1026, "anios": [2021, 2022], "km": 8290.2 } },
  "nota": "El año va por tramo porque no hay un dato nacional posterior a 2021…"
}
```

Obligatorios para `validar.py`: `fuente`, `features` y `url`. Los demás aparecen según la fuente, y
ninguno es decorativo:

- **`descargado`** es cuándo se bajó (lo que mide frescura); **`fecha_dato`** es de cuándo es el dato
  según la fuente, que casi nunca coincide; **`actualizado`** es la fecha que declara el organismo.
- **`metodo`** deja escrito cómo se obtuvo (endpoint, formato, redondeo, simplificación). Es lo que
  permite repetirlo sin volver a investigar.
- **`detalle`** desglosa por comunidad cuando la capa mezcla años o redes distintas.
- **`estado: "heredado"`** (con `heredado_en`) lo escriben `demarcaciones.py` y `recibo_agua.py`
  cuando **la fuente falla y se conserva el último dato bueno**: no es un fichero corrupto, es un aviso
  con su fecha y se limpia solo en cuanto llega dato nuevo. Hoy hay un caso:
  `demarcaciones_recibo.json`.
- `validar.py` comprueba que existe el recibo, que `features` cuadra con el fichero y que la capa está
  declarada en `fuentes.json`.

## 2. Los dos ficheros de contrato

| Fichero | Quién lo escribe | Para qué |
|---|---|---|
| `fuentes.json` | `scripts/fuentes_visor.py` | una ficha por id de capa: `titulo`, `fuente`, `editor`, `licencia` con estado (reutilizable / pendiente / no), `descargado`, `features`, `url` y `metodo` |
| `catalogo.json` | `scripts/catalogo.py` | el contrato por capa: jerarquía (1 organismo productor, 2 agregador, 3 comunitario), `ttl_segundos`, `ultima_verificacion`, `endpoint`, `frecuencia_fuente`, `crs`; más un `resumen` con caducadas y licencias. Es lo que leen el MCP y el chat para no afirmar una frescura que no tienen |

Los dos se regeneran **después** de generar los datos y **antes** de `cifras.py`.

## 3. Carpetas temáticas

- **`oficial/`** — lo que su organismo no publica como GeoJSON (PDF, WMS, servicios cerrados) y se ha
  vectorizado aquí. Lleva un recibo único, `_recibo_oficial.json`, con fecha de verificación y origen.
- **`hermes/`** — las capas del visor de MITMA (carreteras, puertos, terminales), tal cual las sirve.
- **`simplificado/`** — la versión ligera (Douglas-Peucker) de las capas que pesan: es lo que consume
  el visor cuando la geometría completa no hace falta.
- **`series/`** — series temporales vivas: `ree_vivo`, `omie_precio`, `entsoe_mix`, `sismos`,
  `dgt_incidencias`, `aemet_zonas`. Formato `{ "capa": …, "dias": [ {fecha, …valores} ] }`, lo archiva
  `scripts/snapshot.py`. **No son geografía**: son el histórico de un panel en vivo.

## 4. Capas partidas (las que pesan)

Un GeoJSON de 9 MB cuesta dos veces: la descarga y el parseo, que bloquea el navegador justo cuando
el usuario espera el mapa. Las siete capas gordas se parten por provincia o comunidad:

| Capa | Campo | Trozos | Objetos |
|---|---|---:|---:|
| `trafico-ccaa` | `ccaa` | 17 | 7.398 |
| `trafico-estaciones` | `ccaa` | 2 | 1.074 |
| `municipios` | `provincia` | 52 | 8.128 |
| `nucleos` | `provincia` | 52 | 37.469 |
| `ciudad-docencia` | `provincia` | 52 | 33.232 |
| `dpmt` | `provincia` | 27 | 12.684 |
| `dgt-electrolineras` | `provincia_municipio` | 52 | 12.144 |

**Cómo se generan.** `scripts/partir.py` (lista `PARTIR` en el propio script) lee el GeoJSON completo
y escribe `datos/<id>/` con un `index.json` y un fichero por valor:

```json
{ "capa": "trafico-ccaa", "campo": "ccaa", "total": 7398,
  "partes": [ { "slug": "aragon", "etiqueta": "Aragón", "fichero": "aragon.geojson",
                "n": 1026, "bbox": [-2.2, 39.8, 0.8, 42.9], "bytes": 214331 } ] }
```

**Cómo lo consume el visor.** La capa declara `carpeta:"datos/<id>"` en `CAPAS`. Al encenderla,
`cargarPartesAlEntrar()` lee el índice y descarga **solo los trozos que cortan la vista**, de cuatro en
cuatro, repintando como mucho cada 200 ms; al mover el mapa pide los que faltan. Con una comunidad
elegida en el selector, solo esa. Si la capa no se dibuja por debajo de su zoom (`ocultaHasta`), **no
se descarga nada** hasta llegar a él.

**El fichero entero se queda** en `datos/<base>.geojson`: es lo que descarga quien usa la API y lo que
leen `cifras.py`, `catalogo.py` y `validar.py`. Las carpetas cuelgan de `datos/`, así que
`fuentes_visor.py` (que recorre `datos/*_recibo.json`) no las confunde con capas nuevas.

**Coste**: los trozos suman lo mismo que el original (46 MB en total). Si algún día se quiere
recortar el repo, lo que sobra es el fichero entero de estas siete capas, no los trozos.

**Si se regenera una capa partida hay que volver a trocearla** (`python3 scripts/partir.py`): si no,
el visor sigue sirviendo los trozos de antes y nada se queja a simple vista. Para que eso no pase en
silencio, `validar.py` compara el `total` de cada `index.json` con los `features` de su recibo y con la
suma de los trozos, y da **ROJO** con el nombre de la capa y del script que hay que correr. El cron
semanal ya lo hace tras `agregar.py`.

**Para añadir una capa partida**: entrada en `PARTIR` de `partir.py`, `carpeta:` en su objeto de
`CAPAS`, y comprobar en el navegador que el primer trozo pinta y que el selector (si lo tiene) lista
sus valores sin haber descargado el resto.

## 5. Lo que no es capa

- **`agregados.json`** y los cinco **`agregado_*.csv`** (líneas por operador, plantas por comunidad y
  por tecnología): cifras para consultar o pintar en la cabecera, no capas del mapa.
- **`municipios_mart.csv`** — una fila por municipio (`cod_ine`) con los seis indicadores de renta del
  INE, población, área, provincia y las centrales agregadas por tecnología (MW y número). Es la tabla
  para **cruzar fuentes por municipio**: renta ↔ plantas ↔ cualquier capa con `cod_ine`. No se
  commitea (se regenera), y se consulta con SQL sin dependencias:

  ```bash
  python3 scripts/consulta.py --mart                          # (re)genera el CSV: 0,6 s
  python3 scripts/consulta.py "select municipio, renta_persona from municipios
                               where mw_nuclear > 0 order by renta_persona desc"
  ```

  La media nacional se saca de la propia tabla, ponderando por población:
  `sum(renta_persona*poblacion)/sum(poblacion)` — da 15.952 €, frente a los 15.948 € que publica el
  INE para 2024 (0,03 %). Si esa comprobación se va de más de 1 %, la capa de renta está desfasada.
- **Intermedios de fusión**: ficheros de una fuente que se han cruzado con otra para producir la capa
  buena (`edar`, `depuradoras_ign`, `irewater_hib_edar`). Se declaran en `INTERMEDIOS`
  (`scripts/fuentes_visor.py`) para que el catálogo no los cuente dos veces.

## 6. El estado de hoy (medido)

| | |
|---|---:|
| Capas en el visor | 99 en 17 grupos |
| Entradas de catálogo en `fuentes.json` | 124 |
| Capas partidas | 7 (254 trozos) |
| Peso de `datos/` | ~224 MB |

## 7. Reglas duras

1. **Nada a mano.** Ni GeoJSON, ni `catalogo.json`, ni `fuentes.json`, ni las tablas del README.
2. **Un conflicto en un generado se regenera**, no se elige lado: se corre su script y se hace `git add`.
3. **Orden de la cadena**: generadores → `agregados.py` → `partir.py` → `fuentes_visor.py` →
   `catalogo.py` → `cifras.py` → `snapshot.py` → `validar.py`. `cifras.py` siempre el último antes del
   validador; si corre antes, cuenta el catálogo viejo. `partir.py` va detrás de cualquier script que
   reescriba una capa partida.
4. **Sin recibo no hay capa**, y sin `validar.py` en VERDE no se publica.
5. **La frescura se mide por la fecha del recibo**, nunca por la fecha del commit.
