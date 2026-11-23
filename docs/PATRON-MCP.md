---
titulo: Cómo convertir un recurso oficial en un servidor MCP
fecha: 2026-11-16
ambito: patron
estado: publicado
---

# Cómo convertir un recurso oficial en un servidor MCP

Estudio de [`ESJavadex/ree-mcp`](https://github.com/ESJavadex/ree-mcp) — **medido en el código, no leído
del README** — y destilado en una receta para repetirlo con cualquier recurso: presas, embalses, red de
transporte, calidad del aire, lo que sea.

## Anatomía medida

| Dato | Valor |
|---|---|
| Ficheros Python | 36 (33 de código, 14 de test) |
| Líneas | 3.838 |
| Capas | 4 (dominio, aplicación, infraestructura, interfaz) |
| Herramientas MCP | **20** |
| Indicadores mapeados | **29** |
| Tests | unitarios de dominio, integración del cliente HTTP, e2e del servidor |
| Stack | Python + FastMCP + httpx + pydantic-settings + pytest |
| Licencia | MIT |

No es un script: es una **arquitectura en capas donde la capa de arriba no sabe de HTTP y la de abajo no
sabe de MCP**. Eso es lo que lo hace reutilizable.

## Las cuatro capas, con sus ficheros

```
src/ree_mcp/
├── domain/                       ← el recurso, sin dependencias de nada
│   ├── entities/indicator.py            qué es un indicador
│   ├── entities/indicator_data.py       qué es una serie
│   ├── entities/indicator_value.py      qué es un punto
│   ├── value_objects/indicator_id.py    valida el ID antes de usarlo
│   ├── value_objects/datetime_range.py  un rango es un objeto, no dos strings
│   ├── value_objects/geographic_scope.py
│   ├── value_objects/measurement_unit.py
│   ├── value_objects/time_granularity.py
│   ├── repositories/indicator_repository.py   interfaz abstracta
│   └── exceptions.py
├── application/                  ← los casos de uso
│   ├── use_cases/get_indicator_data.py
│   ├── use_cases/list_indicators.py
│   ├── use_cases/search_indicators.py
│   └── dtos/                     lo que entra y sale de cada caso
├── infrastructure/               ← HTTP, credenciales, reintentos
│   ├── http/ree_api_client.py          httpx + backoff exponencial
│   ├── repositories/ree_indicator_repository.py   implementa la interfaz
│   └── config/settings.py              .env, nunca hardcode
└── interface/                    ← el MCP
    ├── mcp_server.py             20 herramientas
    ├── indicator_config.py       IDs + metadatos, fuente única
    └── tool_helpers.py           formateo común de respuestas
```

**La regla que hace que funcione:** `domain/` no importa `httpx`, `infrastructure/` no importa `fastmcp`.
Se puede cambiar la API por otra sin tocar el MCP, y cambiar de MCP (FastMCP → otro) sin tocar el dominio.

## Las 20 herramientas: el patrón que hay que copiar

El repo **no** expone una sola herramienta `get_indicator(id)`. Expone esa *y* diecinueve más:

| Genéricas | De dominio (el valor real) |
|---|---|
| `get_indicator_data` | `get_demand_summary(date)` |
| `list_indicators` | `get_generation_mix(date, hour)` |
| `search_indicators(keyword)` | `get_renewable_summary(date, hour)` |
| `get_indicator_info(id)` | `get_carbon_intensity(date)` |
| `list_all_indicators` | `compare_forecast_actual(date)` |
| | `get_international_exchanges(date, hour)` |
| | `get_grid_stability(date, hour)` |
| | `get_generation_mix_timeline(date, granularity)` |
| | `get_spain_hourly_prices(date)` |
| | `get_price_analysis(...)` |
| | `get_storage_operations(date)` |
| | `get_peak_analysis(start, end)` |
| | `get_pvpc_rate(date, hour)` |
| | `get_daily_demand_statistics(start, end)` |
| | `analyze_demand_volatility(start, end)` |

**Por qué esto es lo importante:** un agente no sabe que el mix de generación es el indicador 2038. Si la
herramienta se llama `get_generation_mix`, el agente la elige sola con la descripción. La herramienta
genérica existe como escape para lo que no está cubierto, pero **no es la interfaz principal**. Un MCP
con solo `get_indicator_data` no lo usa nadie.

Y hay una segunda lección en los nombres: `compare_forecast_actual`, `get_peak_analysis`,
`analyze_demand_volatility` **no son consultas, son análisis**. El servidor hace el cálculo (compara
previsión con real, busca la punta, mide volatilidad) en vez de devolver 288 puntos y dejar que el modelo
los sume mal.

## La fuente única de IDs

`interface/indicator_config.py` concentra los 29 indicadores en un `Enum` de dataclasses:

```python
class IndicatorIDs:
    REAL_DEMAND_NATIONAL = IndicatorMetadata(
        id=2037,
        name="Real Demand (National)",
        category=IndicatorCategory.DEMAND,
        description="Real-time electricity demand for all of Spain (MW, 5 min)",
    )
```

Ese fichero es el **contrato con el recurso**. Cuando el organismo cambia un ID, se cambia ahí y en ningún
otro sitio. Y la `description` no es decorativa: es la que se muestra al agente cuando busca.

## Lo que copiaría y lo que no

**Copiar:**

1. **Un fichero de configuración del recurso**, no IDs dispersos por el código.
2. **Herramientas por caso de uso, no por endpoint.** Una docena de preguntas reales, no un proxy.
3. **Análisis en el servidor**: si el agente tiene que sumar 288 puntos, se los vas a dar mal.
4. **Value objects que validan al entrar**: un `IndicatorId` que rechaza un ID que no es número evita
   errores que luego parecen «la API no tiene datos».
5. **Retry con backoff exponencial** en el cliente HTTP, y no reintentar los 4xx (excepto 404 puntual).
6. **Token desde `.env`**, con `.env.example` de plantilla y `.env` en `.gitignore`.
7. **Tests que hablan con el servidor como cliente real**, no que importan el módulo.

**No copiar tal cual:**

1. **Una capa de dominio con 8 ficheros para 29 indicadores** es DDD de manual aplicado a un problema
   pequeño. Para un recurso con 3 endpoints, esto es ceremonia. Yo empezaría con dos ficheros
   (`recurso.py` con el catálogo, `servidor.py` con las herramientas) y separaría solo cuando duela.
2. **`FastMCP` añade una dependencia** que la skill `mcp-servers` evita: el protocolo cabe en stdlib.
   Pero FastMCP da `inputSchema` automático desde las type hints, y eso ahorra mucho código. Con un
   recurso grande, compensa.
3. **El README promete «1.967 indicadores»** cuando mapea 29. El número es del catálogo de ESIOS, no de lo
   que el servidor expone. Prometer cobertura que no existe es el error clásico de estos repos.

## La receta, generalizada

Para cualquier recurso oficial (embalses del MITECO, red del IGN, calidad del aire, puertos):

### Paso 1 — Encontrar la forma del dato, no el dato
Antes de escribir código: ¿el organismo expone JSON, XML, CSV o solo un visor? Prueba 5 URLs y anota el
código real de cada una. Si solo hay visor, hay que buscar su endpoint interno (como el ArcGIS REST del
visor Hermes de MITMA: abierto y sin clave). **Esto se documenta en `docs/apis.md` con el error literal.**

### Paso 2 — Probar el catálogo entero, no un ejemplo
Los 29 indicadores de ESIOS se probaron uno a uno: **19 respondían sin token y 10 daban 403**. Nadie lo
sabía, ni el propio repo que los usa. Esa tabla es el activo.

> **Ojo, 2026-11-23: eso ya no es cierto.** ESIOS cerró el acceso sin clave: hoy los 19 dan **403** sin
> `x-api-key` y **200** con ella (medido en el 2037: 36 bytes sin clave, 37.979 con clave). El token
> pasó a ser obligatorio en `ree_vivo.py` y en los secrets del repo. Un catálogo «abierto» caduca: se
> vuelve a medir antes de fiarse.

```
ID    indicador                      ¿abierto?
2037  Demanda real nacional           200
2038  Eólica                          200
2041  Ciclo combinado                 200
10355 Emisiones asociadas              200
1293  Demanda peninsular 5 min        403  ← token
600   Precio SPOT                     403  ← token
```

### Paso 3 — El catálogo como fichero
Un diccionario `clave → (id, etiqueta, grupo, unidad)`. Es lo que se cambia cuando el organismo rompe algo.

### Paso 4 — Una herramienta por pregunta real
No «dame el indicador». Sí: «dame el mix de generación de ayer», «compara previsión con real», «dame la
punta del mes». Cada una con su schema y su descripción en el idioma del proyecto.

### Paso 5 — Análisis dentro, no fuera
Si la respuesta natural es un número (la punta, el saldo, la volatilidad), calcúlalo tú. Devolver 288
puntos para que el modelo los procese es delegar tu trabajo en el eslabón más frágil.

### Paso 6 — Decir siempre de dónde viene y de cuándo es
Cada respuesta lleva `fuente`, `fecha` y `resolución`. En un recurso oficial esto no es opcional: es la
diferencia entre un dato y un rumor.

### Paso 7 — Autochequeo que hable el protocolo
Un `--test` que arranca el servidor como subproceso, hace `initialize`, `tools/list` y una llamada por
herramienta, y **verifica el contenido**. Si solo comprueba que no truena, no vale.

### Paso 8 — Documentar las limitaciones que el organismo no dice
Que el `route_id` de Renfe viene vacío, que el WMTS del IGN devuelve 200 con 0 bytes sin `Referer`, que
Overpass da 502 cuando se satura. Eso es lo que convierte el servidor en algo que otro puede usar.

## Lo que este estudio cambió en OpenInfraES

Los 19 indicadores abiertos de ESIOS ya están conectados:

```bash
python scripts/ree_vivo.py
```

Da **demanda, generación por tecnología, emisiones, intercambios internacionales y bombeo cada 5
minutos**, sin clave, y alimenta el bloque «ahora mismo» del panel ⚡ del visor. Verificado a las 18:35
del 2026-11-16: demanda 35.028 MW, eólica 13.184, hidráulica 7.201, ciclo combinado 5.917, saldo
internacional −4.492 MW (importando), bombeo neto +2.133 MW.

Es el 65% de lo que enseña la visiona de REE, sin pedir permiso a nadie.

## Lo que el repo original no tiene (y aquí sí)

Al usarlo, `ree-mcp` falla en un aspecto que su código no contempla: **si la API bloquea, la herramienta
devuelve un error y no hay dato**. Nosotros añadimos dos cosas que él no tiene:

1. **Distingue `BloqueoWAF` de `SinPermiso`.** El 403 de ESIOS es idéntico en cuerpo para «falta clave» y
   para «el WAF te ha cortado»; solo cambian las cabeceras (`X-CDN: Imperva`, `X-Iinfo`, `incap_ses`).
   Confundirlos lleva a pedir una clave que no falta.
2. **Herencia del dato bueno.** Si la descarga falla y hay una versión anterior, se conserva marcada
   `heredado: true` con su hora, y la interfaz lo dice. El repo original devuelve `{"error": ...}` y el
   usuario se queda sin panel.

Está en `scripts/http_oficial.py` (cliente con las cinco distinciones) y `scripts/ree_vivo.py` (herencia).

## El siguiente paso lógico

El mismo patrón sobre **embalses**: `get_embalse(nombre)`, `compare_semana_actual(embalse)`,
`embalses_bajo_minimo(demarcacion)`. El recurso ya está (402 embalses con capacidad y volumen semanal);
lo que falta es la capa de preguntas.
