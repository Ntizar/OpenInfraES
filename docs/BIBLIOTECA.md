---
titulo: La biblioteca del dato — para qué existe este proyecto
fecha: 2026-11-16
ambito: transversal
estado: publicado
---

# La biblioteca del dato

Esto no es un mapa. El mapa es la puerta.

Lo que hay detrás es una **base de datos de infraestructura española** pensada para alimentar otros
proyectos: artículos, informes, modelos, visores, análisis territorial. Cada dato que entra aquí se
guarda de forma que **se pueda volver a usar sin repetir el trabajo**.

## Para qué sirve

David escribe sobre energía y monta proyectos con mapas. Sin una base común, cada proyecto empieza de
cero: buscar la fuente, descargar, limpiar, descubrir que el campo se llama distinto, olvidar de cuándo
era el dato. Eso se hace una vez y se hace bien.

Esta biblioteca resuelve cuatro cosas de golpe:

1. **La fuente está resuelta.** No se busca: está en `docs/FUENTES.md` con la URL, el endpoint y la
   licencia.
2. **El dato está normalizado.** Todos los GeoJSON hablan el mismo idioma (WGS84, nombres de campo en
   castellano, sin geometrías raras).
3. **La fecha está separada.** Se distingue cuándo se midió, cuándo se publicó y cuándo se descargó.
   Sin eso, cualquier serie temporal miente.
4. **El límite está escrito.** Lo que falta se declara: el Tajo-Segura solo llega a Alarcón, el caudal
   de los ríos es modelado, la generación por planta no existe en abierto.

## Cómo crece: agentes que rellenan fichas

La idea no es que una persona meta 5.000 presas a mano. Es que **un agente por tema** investigue y
complete las fichas, con las mismas reglas que ya usa el repositorio.

El modelo es una **ficha enriquecida**. Hoy una presa tiene nombre, capacidad y demarcación. Mañana:

| Campo | De dónde sale | Ejemplo |
|---|---|---|
| `nombre` | ya está | Embalse de Buendía |
| `capacidad_hm3` | MITECO | 1.638 |
| `agua_actual_hm3` | Boletín Hidrológico, semanal | 1.201 |
| `fecha_dato` | la trae el parte | 2026-11-10 |
| **`ano_construccion`** | catálogo de presas, bibliografía | 1958 |
| **`promotor`** | confederación / archivo | Confederación del Tajo |
| **`demarcacion`** | ya está | Tajo |
| **`uso`** | catálogo de presas | abastecimiento + riego + hidroeléctrico |
| **`enlace_demarcacion`** | Confederación Hidrográfica | `chtajo.es/...` |
| **`expediente`** | archivo del organismo | — |
| **`fuente` por campo** | cada dato, con su origen | «capacidad: MITECO 2021» |

La clave es la última fila: **cada campo dice de dónde viene**. Un dato sin procedencia no entra.

## Las reglas que hacen que esto valga

1. **Nada se escribe a mano.** Un dato entra por un script o por una ficha con su fuente citada. Si se
   escribe a mano, no se puede regenerar y el repositorio se pudre.
2. **Cada valor, con su organismo.** No «fuente: una web»; «produce: MITECO, Boletín Hidrológico».
3. **Un hueco declarado vale más que un número inventado.** Si falta el año de una presa, se deja vacío
   con la nota de que falta. Rellenarlo con una estimación plausible es el error que arruina una base
   de datos.
4. **El dato y su fecha viajan juntos.** Una cifra sin periodo no es un dato, es un rumor.
5. **Se puede reutilizar legalmente.** Licencia por capa, y aviso cuando mezclar ODbL con CC BY obliga a
   compartir igual.

## Qué contiene hoy

**69 capas en el visor** y **92 entradas documentadas** en `datos/fuentes.json`. Lo que se puede
consultar ya:

- **Energía**: red de 400/220 kV, 657 subestaciones, 7 reactores nucleares, ciclos combinados,
  678 gasoductos, 7 regasificadoras, 5 almacenamientos, 10 refinerías.
- **Agua**: 402 embalses con capacidad y volumen del parte semanal, 28 desaladoras, 3.034 EDAR,
  1.551 ETAP, 11 trazos de trasvase, 10.777 canales, 260 ríos con caudal.
- **Transporte**: 1.602 carreteras, 45 puertos, 440 terminales portuarias, 383 nodos de mercancías,
  405 estaciones de Cercanías, 418 trenes en vivo.
- **Tiempo real**: 11.433 carburantes con precio, generación y previsión del sistema eléctrico.
- **Riesgo**: 80 sismos de la última semana.

## Cómo se usa desde otro proyecto

No hay que copiar el visor. Los datos son ficheros:

```python
import json
red = json.load(open("OpenInfraES/datos/simplificado/lineas_hv.geojson"))
sub = json.load(open("OpenInfraES/datos/oficial/red-electrica.geojson"))
```

Y si hace falta el estado de una fuente:

```python
import json
fuentes = json.load(open("OpenInfraES/datos/fuentes.json"))
fuentes["capas"]["embalses"]["organismo"]   # "MITECO"
fuentes["capas"]["embalses"]["fecha_dato"]  # de cuando es el parte
```

## Lo que falta, por orden

1. **Fichas enriquecidas** de presas, subestaciones y centrales (año, promotor, expediente).
2. **Vector tiles** para que el visor sirva solo lo visible: hoy son ~25 MB de GeoJSON.
3. **Las tres claves** que cierran huecos: ENTSO-E (por planta), AEMET (riesgo), NAP (transporte).
4. **Una capa de series temporales**: hoy son fotos; el valor está en la evolución.

## El nombre

La biblioteca de Alejandría no se recuerda por sus rollos, sino por haberlos **catalogado**. El valor
no está en tener 11.433 gasolineras: está en que cualquiera pueda preguntar de dónde salieron, de cuándo
son y si puede usarlas.
