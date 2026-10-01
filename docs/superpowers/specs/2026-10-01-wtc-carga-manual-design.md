# WTC (Uruguay) — carga manual mensual con conversión UYU→ARS

Fecha: 2026-10-01 · Estado: diseño aprobado en chat, spec pendiente de revisión

## Contexto

WTC es un local de Patagonia en **Uruguay** que usa otro sistema de ventas, por eso nunca
aparece en `Corporativo.vw_Ventas_Corporativo_Base`. Tiene objetivos cargados **en ARS**
(~$73-95M/mes) en `Objetivos_Temple_BQ`, así que hoy figura como "Objetivo sin venta" y le resta
~2 pp al cumplimiento de Patagonia.

Objetivo: que Darwin cargue a mano, por mes, facturación (UYU), órdenes y litros de cerveza de WTC,
y que los tableros lo muestren convertido a ARS al tipo de cambio oficial.

## Decisiones (tomadas con Darwin)

- Granularidad **mensual** (no diaria ni semanal).
- Tipo de cambio **automático, oficial**: API BCRA Estadísticas Cambiarias, `UYU.tipoCotizacion`
  (ARS por UYU). Verificado 01/10: `GET /estadisticascambiarias/v1.0/Cotizaciones/UYU?fechadesde=&fechahasta=`
  devuelve un valor por día hábil (ene-25 ≈ 23,6; 29/09/26 = 37,80). La API falla de forma intermitente.
- Conversión mensual = facturación UYU × **promedio de días hábiles del mes**.
- Objetivos de WTC ya están en ARS: se comparan contra la facturación convertida.
- Litros: **reales**, como los reporta WTC (no estimados por nombre de producto).
- Historia: **desde ene-25**.
- Almacenamiento en **BigQuery** (enfoque A). Descartados: fila mensual dentro de la vista diaria
  (rompe días de semana, mes en curso y el badge de calidad de datos) y Firestore (Patagonia
  Semestral no lo lee; antecedente del bug `_retry` con objetivos en cero).

## Alcance por fases

1. **Fase 1 (esta spec, en detalle):** tablas, formulario en `/admin`, tipo de cambio, tablero retail Ventas + Finanzas.
2. **Fase 2:** pestaña Producto del tablero retail (litros).
3. **Fase 3:** tablero Patagonia Semestral (Cloud Run aparte).

## Fase 1

### Datos

`temple-bar-439715.Corporativo.wtc_manual_mensual` — una fila por mes.

| columna | tipo | nota |
|---|---|---|
| mes | DATE | primer día del mes; clave |
| facturacion_uyu | NUMERIC | ≥ 0 |
| ordenes | INT64 | ≥ 0 |
| litros_cerveza | NUMERIC | ≥ 0, reales |
| cargado_por | STRING | email del admin |
| cargado_en | TIMESTAMP | |

Upsert por `mes` con `MERGE` con **lista de columnas explícita** en `INSERT (...) VALUES (...)`
(nunca `INSERT ROW`: empareja por posición).

`temple-bar-439715.Corporativo.tipo_cambio_uyu_ars` — una fila por mes.

| columna | tipo | nota |
|---|---|---|
| mes | DATE | clave |
| ars_por_uyu | NUMERIC | promedio de días hábiles del mes |
| dias | INT64 | días hábiles promediados |
| completo | BOOL | true si el mes ya cerró al calcularlo |
| actualizado_en | TIMESTAMP | |

### Tipo de cambio (`actualizar_tipo_cambio_uyu()` en el pipeline retail)

- Corre en `actualizar_retail.py` antes de armar los datos.
- Primera vez: trae ene-25 → hoy. Después: solo meses sin fila o con `completo = false`.
- Pide por rango a la API BCRA (timeout corto, 2 reintentos). Si falla: log `WARN`, sigue con lo que
  ya hay en la tabla. **Nunca lanza.**
- Un mes de WTC sin cotización **no se suma** y se avisa (nunca se inventa una cotización).

### Formulario `/admin` — "WTC Uruguay · carga mensual"

- Textarea para pegar 1..N filas (tab, `;` o espacios múltiples): `mes  facturacion_uyu  ordenes  litros`.
  - `mes`: `2025-01`, `01/2025` o `ene-25`.
  - Números en formato argentino (`12.345.678,50`) o plano (`12345678.50`).
- `POST /api/admin/wtc/preview` → filas parseadas + cotización del mes (si existe) + ARS convertido +
  marca "reemplaza" si el mes ya está cargado + errores por fila. No escribe.
- `POST /api/admin/wtc` → valida de nuevo y hace el MERGE. Responde filas escritas.
- `GET /api/admin/wtc` → lo cargado (mes, UYU, cotización, ARS, órdenes, litros, quién, cuándo) para la tabla de control.
- Validaciones: mes entre 2025-01 y el mes actual; no negativos; sin meses repetidos en el pegado.
  Con cualquier error, no se guarda nada.
- CSRF con la variable Jinja `CSRF_TOKEN` (nunca leído de cookie), mismo decorador de admin que el resto.
- Parser y validación en funciones puras (`wtc_parse_filas`) testeadas con pytest.

### Tablero retail — `incorporar_wtc()` (pura, en `actualizar_retail.py`)

Entrada: filas de WTC, cotizaciones, y los datasets ya consultados. Convierte
`fac_M = facturacion_uyu × ars_por_uyu / 1e6` y suma:

| dataset | efecto |
|---|---|
| `MENSUAL` | Patagonia: `fac += fac_M`, `ord += ordenes`; `tick = round((tick·ord_ar + fac_M·1e6) / (ord_ar + ordenes))` (ponderado por órdenes; el aporte de WTC usa su facturación ARS como total) |
| `LOCAL_MENSUAL` | fila propia `{mes, m:"Patagonia", l:"WTC", fac, ord}` |
| `LOCALES_OBJ` | real de WTC (`d[mes][0]`, `d[mes][2]`) en los meses cargados del año en curso |
| `LOC_COUNT_BY_MES` | `P += 1` los meses cargados |
| diarios (`ventas`, `DIAS`, `ULTIMA_VENTA`, badge) | sin cambios: WTC no es diario |
| Top 10 / producto | sin cambios en fase 1 |

Se aplica **antes** de `compute_pd` / `compute_preset_meses` para que períodos y presets lo vean.
Nombre del local: `WTC` (igual que en la planilla de objetivos; match por `UPPER(TRIM())`).

Nota en el tablero (Ventas y Finanzas), inyectada como `WTC_INFO`:
"WTC (Uruguay): carga manual mensual, convertida al oficial BCRA" + avisos si el último mes cerrado
o el mes en curso no están cargados, o si algún mes cargado no tiene cotización.
Finanzas: WTC se deflacta con IPC argentino como el resto (lo aclara la nota); same-store lo incluye
solo cuando tiene el mismo mes del año anterior cargado.

### Errores

Si fallan la consulta de WTC o la de cotizaciones: el tablero sale sin WTC (como hoy), `WARN` en el
log del pipeline y aviso en la nota. El pipeline no se cae por esto.

### Tests

- `tests/test_wtc.py` (pytest, primero): parser (formatos de mes y número, errores), validación,
  promedio mensual de cotizaciones a partir de la respuesta BCRA (fixture con la forma real verificada),
  `incorporar_wtc` (suma a Patagonia, fila local, objetivos, conteo, mes sin cotización excluido,
  sin datos = datasets intactos).
- Ruta admin: preview no escribe; POST con error no escribe nada; CSRF requerido.
- Preview local con `rebuild.py ventas` + sonda Chrome headless (iframe para anchos de celular).

### Deploy

- `templates/dashboard.html` + `actualizar_retail.py`: push a main + `gh workflow run actualizar-pipeline.yml`;
  verificar log (`grep FALLÓ|WARN WTC`) y blob GCS.
- `app.py` + `templates/admin.html`: redeploy de Cloud Run `temple-bar-dashboard`.
- Las tablas se crean una vez con DDL versionado en el repo (`sql/wtc_tablas.sql`).
- El pipeline (GitHub Actions) necesita salida HTTPS a `api.bcra.gob.ar` (verificar en el primer run).

## Fases 2 y 3 (resumen)

- **Producto:** `fetch_producto_data` suma `litros_cerveza` de WTC a Patagonia por mes; WTC no
  aporta a rankings de productos (no hay detalle).
- **Patagonia Semestral:** su backend lee las mismas dos tablas y suma WTC a GMV (ARS convertido),
  órdenes y litros del rango; ubicación del código y criterios del semestre se confirman al empezar la fase.

## Fuera de alcance

Carga diaria/semanal, detalle por producto de WTC, conversión de objetivos (ya están en ARS),
deflactar WTC con IPC uruguayo.
