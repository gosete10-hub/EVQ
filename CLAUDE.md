# Consulta de datos INE — guía del proyecto

Este fichero es la referencia de trabajo para Claude Code en este repositorio. Se actualiza a medida que el proyecto avanza, siempre a petición del usuario.

## 1. Qué es este proyecto

Web para hacer consultas en lenguaje natural sobre datos estadísticos de España, extrayendo los datos del INE (Instituto Nacional de Estadística) a través de su API pública. Un LLM (Claude, vía API) interpreta la pregunta, decide qué datos necesita, los obtiene mediante tools, hace los cálculos intermedios que hagan falta y devuelve una respuesta con visualización opcional.

No es un buscador de "¿cuál es el número de X?". Debe soportar preguntas que requieran:

- Varias extracciones de datos encadenadas (p. ej. población por provincia + defunciones por provincia).
- Cálculos intermedios: tasas, ratios, variaciones interanuales, probabilidades (p. ej. "probabilidad de que una persona de Lleida tenga más de 65 años"), medias ponderadas, proyecciones simples.
- Elección de la visualización adecuada (línea temporal, barras comparativas, mapa por CCAA/provincia, tabla).

Principio clave: **el LLM orquesta; los datos y los cálculos los hacen las tools de forma determinista.** El modelo nunca "inventa" cifras: toda cifra que aparece en la respuesta debe proceder de una llamada a tool trazable.

## 2. Estado actual

- 2026-11-12: proyecto inicializado. Sin código, sin git.
- 2026-11-12: creada la estructura de carpetas (sección 3), `.gitignore` y `.env.example`. Decidido que el LLM será de API gratuita; capa de proveedor agnóstica (sección 5).

(Actualizar esta sección en cada hito.)

## 3. Stack y decisiones de arquitectura

| Capa | Decisión | Motivo |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Cálculo numérico (pandas/numpy/scipy) en el mismo proceso que las tools. |
| LLM | Proveedor con API gratuita, accedido por endpoint compatible con OpenAI (SDK `openai` con `base_url`) | Restricción del proyecto: coste cero. Ver sección 5. |
| Datos | API JSON del INE (Tempus3) vía `httpx` | Sin scraping. Cache local de metadatos. |
| Frontend | HTML + JS ligero (sin framework por ahora) servido por FastAPI; gráficos con Plotly.js | Mínimo para iterar rápido. Se revisará si crece. |
| Persistencia | Ninguna al inicio; cache de metadatos INE en disco (`data/cache/`) | Los catálogos del INE cambian poco. |
| Config | Variables de entorno (`.env`, nunca commiteado) | `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`. |

Estructura prevista:

```
Consulta_de_datos/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── app/
│   ├── main.py            # FastAPI, endpoints /api/query (SSE) y estáticos
│   ├── llm/
│   │   └── proveedor.py   # cliente OpenAI-compatible por proveedor, reintentos 429, fallback
│   ├── agent/
│   │   ├── runner.py      # bucle agéntico manual (tool calls), system prompt, streaming
│   │   ├── prompts.py     # system prompt (estable, cacheable)
│   │   └── tools/
│   │       ├── ine.py     # tools de descubrimiento y extracción INE
│   │       ├── compute.py # tools de cálculo determinista
│   │       └── viz.py     # tool que emite spec de visualización
│   ├── ine/
│   │   ├── client.py      # cliente HTTP Tempus3 con cache y rate limit
│   │   └── models.py      # tipos: Operacion, Tabla, Serie, Valor
│   └── static/            # index.html, app.js, estilos
├── data/cache/            # catálogos INE cacheados (gitignored)
└── tests/
```

## 4. API del INE (Tempus3)

Base: `https://servicios.ine.es/wstempus/js/{idioma}/{funcion}/{input}?params`. Idioma `ES`. Respuestas JSON. Sin autenticación.

Funciones relevantes (la jerarquía es Operación → Tabla → Serie → Datos):

| Función | Para qué | Ejemplo |
|---|---|---|
| `OPERACIONES_DISPONIBLES` | Listar operaciones estadísticas (IPC, EPA, Cifras de población...) | `/OPERACIONES_DISPONIBLES` |
| `TABLAS_OPERACION/{id_op}` | Tablas de una operación | `/TABLAS_OPERACION/IPC` |
| `GRUPOS_TABLA/{id_tabla}` y `VALORES_GRUPOSTABLA/{id_tabla}/{id_grupo}` | Variables y valores que filtran una tabla | |
| `SERIES_TABLA/{id_tabla}` | Series de una tabla (con filtros `tv=id_var:id_valor`) | |
| `DATOS_TABLA/{id_tabla}?nult=N` | Datos de toda la tabla, últimos N periodos | |
| `DATOS_SERIE/{cod_serie}?nult=N` o `?date=AAAAMMDD:AAAAMMDD` | Datos de una serie concreta | `/DATOS_SERIE/IPC251852?nult=12` |
| `DATOS_METADATAOPERACION/{id_op}?g1=...&p=...` | Datos filtrando por variables/valores y periodicidad | |
| `VARIABLES`, `VALORES_VARIABLE/{id_var}` | Catálogo de variables (provincia, sexo, edad...) y sus valores | |
| `PERIODICIDADES`, `PUBLICACIONES`, `CLASIFICACIONES` | Metadatos auxiliares | |

Notas de uso que ya conocemos:

- Los ids de operación aceptan código alfanumérico (`IPC`) o numérico (`25`).
- `DATOS_TABLA` sin `nult` puede devolver series enormes: limitar siempre.
- Los valores vienen en `Data[]` con `Fecha` (epoch ms), `Anyo`, `FK_Periodo`, `Valor`. Hay que normalizar a `(periodo, valor)`.
- Hay un límite informal de peticiones; el cliente debe cachear catálogos y reintentar con backoff.
- Parámetros útiles: `det=N` (nivel de detalle de metadatos), `tip=A` (amigable: nombres en vez de ids), `tip=M` (metadatos).

Pendiente de verificar contra la API real en cuanto exista el cliente (marcar aquí lo confirmado).

## 5. LLM: proveedor gratuito y capa agnóstica

Restricción: el LLM debe ser de API gratuita. Los tiers gratuitos cambian de límites sin aviso, así que el código **no se ata a un proveedor**.

Decisiones:

- Todos los candidatos exponen un endpoint compatible con OpenAI Chat Completions con `tools`. Se usa el SDK `openai` cambiando `base_url`, `api_key` y `model` desde `.env`. Nada de lógica específica de proveedor fuera de `app/llm/proveedor.py`.
- Bucle agéntico manual: llamar al modelo, ejecutar los `tool_calls`, devolver resultados como mensajes `role="tool"`, repetir hasta que no haya tool calls. Límite de iteraciones por consulta (p. ej. 15).
- Reintentos con backoff ante 429 y, si se agota la cuota diaria, fallback configurable a un segundo proveedor (`LLM_FALLBACK_*`).
- Las tools deben ser pocas, con esquemas simples y descripciones claras: los modelos gratuitos fallan más en tool calling que los de pago. Validar siempre los argumentos con pydantic antes de ejecutar y devolver el error de validación al modelo para que corrija.
- Parsear `arguments` como JSON con tolerancia a errores; nunca comparar strings.
- Contar llamadas al LLM por consulta: con 20-250 peticiones/día en algunos tiers, cada consulta compleja gasta varias. Minimizar vueltas (tools que devuelvan lo necesario de una vez).
- Privacidad: en Gemini free y Mistral Experiment los datos de las peticiones pueden usarse para entrenar. Los datos del INE son públicos, pero las preguntas del usuario también se envían. Avisarlo en la UI.

Candidatos (verificado por búsqueda el 2026-11-12; los límites reales se consultan en la consola de cada proveedor):

| Proveedor | Modelos gratuitos útiles | Límites aproximados | Notas |
|---|---|---|---|
| Google AI Studio (Gemini) | Gemini Flash / Flash-Lite, Gemma | Muy variables: de ~20 a ~250 peticiones/día en Flash; por proyecto, reset a medianoche hora del Pacífico | Mejor calidad del grupo y contexto largo. Pro ya no es gratis o casi. |
| Groq | gpt-oss-120b, Llama 3.3 70B, Qwen | ~30 peticiones/min, ~1.000/día, tokens/día limitados (100K-200K en modelos grandes) | Muy rápido. Tool calling soportado. El tope de tokens/día es el cuello de botella. |
| Mistral (plan Experiment) | Mistral Small/Medium/Large, Devstral | ~1 petición/s por modelo | Exige verificar teléfono. Datos usados para entrenar. |
| OpenRouter | Modelos `:free` y router `openrouter/free` | 20/min, 50/día (1.000/día tras comprar 10 $ de crédito una vez) | Útil como fallback; el router elige un modelo gratuito que soporte tools. |
| Cerebras, SambaNova, Cloudflare Workers AI, GitHub Models | Varios open-weights | Variables | Alternativas de reserva. |

Configuración inicial propuesta: **principal Groq (`gpt-oss-120b`)** por volumen diario y velocidad, **fallback Gemini Flash** por calidad. Pendiente de confirmar con pruebas reales de tool calling sobre consultas del INE.

## 6. Diseño de las tools del agente

Las tools son funciones Python puras, tipadas, con docstring en español que explica cuándo usarlas. Devuelven JSON compacto (nunca dataframes enteros al modelo: resumir, truncar con aviso explícito).

### Descubrimiento y extracción (ine.py)

- `buscar_operaciones(texto)` — búsqueda difusa sobre el catálogo cacheado de operaciones.
- `listar_tablas(id_operacion)` — tablas de una operación con sus ids y nombres.
- `describir_tabla(id_tabla)` — variables, valores disponibles y periodicidad.
- `obtener_datos(id_tabla, filtros, nult | rango_fechas)` — devuelve filas normalizadas `(periodo, dimensiones, valor)` y las guarda en el **almacén de datasets de la sesión** bajo un `dataset_id`.
- `obtener_serie(codigo_serie, ...)` — atajo para series conocidas.

### Cálculo (compute.py)

Operan sobre `dataset_id`s del almacén de sesión, nunca sobre números que el modelo copia a mano:

- `calcular(expresion, datasets)` — expresión sobre columnas con pandas (suma, ratio, variación %, media ponderada). Sin `eval` libre: gramática limitada.
- `probabilidad(numerador_dataset, denominador_dataset, ...)` — cociente con comprobación de unidades y periodo coincidente.
- `agregar(dataset_id, por, funcion)` — groupby.
- `unir(dataset_a, dataset_b, claves)` — join por dimensiones comunes (provincia, periodo).
- `describir_dataset(dataset_id)` — resumen estadístico sin volcar todo.

### Visualización (viz.py)

- `visualizar(dataset_id, tipo, x, y, serie, titulo)` — no dibuja: devuelve una **spec declarativa** (tipo + columnas + datos) que el frontend renderiza con Plotly. Tipos: `linea`, `barras`, `barras_apiladas`, `tabla`, `mapa_ccaa`, `mapa_provincia`.

### Trazabilidad

Cada respuesta final incluye la lista de fuentes usadas (operación, tabla, periodo, URL de la petición al INE). El frontend las muestra plegadas bajo la respuesta.

## 7. Flujo de una consulta

1. Usuario escribe la pregunta → `POST /api/query` (SSE).
2. Backend crea el tool runner con el historial de la sesión.
3. Por cada llamada a tool se emite un evento `tool_call` al navegador (nombre + argumentos resumidos) para que el usuario vea el razonamiento.
4. Las specs de `visualizar` se emiten como evento `viz` y el frontend las pinta.
5. Texto final en streaming + evento `sources`.

## 8. Convenciones

- Idioma del código: identificadores y docstrings en español, salvo nombres de librerías. Comentarios mínimos.
- Tipado estricto (`mypy --strict` como objetivo), `ruff` para lint/format.
- Tests con `pytest`; las llamadas al INE se graban con fixtures JSON en `tests/fixtures/ine/` para no depender de la red.
- Nunca commitear `.env` ni `data/cache/`.
- Claude no lee `.env` (bloqueado en `.claude/settings.json`). Para saber qué variables existen, usar `.env.example`.
- Commits en español, imperativo, una línea de resumen.

## 9. Riesgos y decisiones abiertas

- Cobertura del INE: no todo está en Tempus3 con el mismo nivel de detalle; hay que detectar cuándo una pregunta no es respondible y decirlo en vez de aproximar.
- Ambigüedad geográfica (municipio vs provincia vs CCAA) y temporal: el agente debe preguntar o declarar el supuesto.
- Cuota por consulta: una pregunta compleja puede implicar 5-15 llamadas al LLM, lo que con tiers gratuitos agota el día rápido. Medir y registrar llamadas y tokens por consulta.
- Fiabilidad del tool calling en modelos gratuitos: puede haber argumentos mal formados o tools inventadas. Mitigación en sección 5.
- Mapas: pendiente decidir fuente de GeoJSON de provincias/CCAA.

## 10. Registro de cambios de este fichero

- 2026-11-12: creación inicial con visión, stack, API INE, reglas del SDK y diseño de tools.
- 2026-11-12: sustituido Claude por un proveedor de API gratuita con capa OpenAI-compatible; tabla de candidatos; añadido `app/llm/`.
- 2026-11-12: añadida la regla de no leer `.env` (sección 8).
