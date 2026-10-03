# WTC (Uruguay) — fase 2: litros en la pestaña Producto

Fecha: 2026-10-03 · Estado: diseño aprobado en chat, spec pendiente de revisión
Base: `2026-10-01-wtc-carga-manual-design.md` (fase 1, en producción desde main `667ce1f`).

## Contexto

La fase 1 creó `temple-bar-439715.Corporativo.wtc_manual_mensual` (una fila por mes, con
`litros_cerveza` reales) y suma WTC a Patagonia en Ventas y Finanzas. La pestaña Producto todavía
no lo ve: los litros de cerveza de Patagonia excluyen a WTC.

Corrección a la spec de fase 1: ahí se nombraba `fetch_producto_data` (`actualizar_retail.py`),
pero esa función no se llama desde ningún lado. La pestaña Producto es un iframe de
`gs://temple-bar-dashboard-cache/producto.html`, generado por `generar_preview_producto.py`
(paso "Producto" de `actualizar_todo.py`, que corre en GitHub Actions). La fase 2 se implementa ahí.

## Decisiones (tomadas con Darwin)

- **Solo litros.** La facturación de WTC no se suma en Producto: Facturación total, dona, mix,
  ranking y "vs período anterior" siguen siendo solo Argentina. Por eso la fase 2 no depende de
  la cotización BCRA.
- Los litros de WTC son de cerveza: suman a "Litros · Cerveza" y a "Total litros".
- WTC aparece como un local más en "Top 10 locales · litros despachados".
- WTC no aporta productos (no hay detalle por producto).
- Enfoque: función pura en Python aplicada sobre el resultado ya armado de cada período
  (mismo patrón que `incorporar_wtc` de fase 1). Descartados: UNION en el SQL de Patagonia
  (cruza proyectos `patagonia-refugios` / `temple-bar-439715`, difícil de testear) y suma en el
  JS del iframe (duplica en el navegador la lógica de períodos que vive en Python).

## Diseño

### Lectura (una vez por corrida)

En `main()` de `generar_preview_producto.py`, con el cliente de `temple-bar-439715`:

```sql
SELECT mes, litros_cerveza
FROM `temple-bar-439715.Corporativo.wtc_manual_mensual`
ORDER BY mes
```

Función `fetch_wtc_litros(client) -> list[tuple[date, float]] | None`. Si la consulta falla:
imprime `WARN WTC: <error>` y devuelve `None` (distinto de `[]` = tabla vacía). El paso Producto
nunca se cae por esto. `main()` pasa la lista a `fetch_all(desde, hasta, clients, wtc)`.

### `incorporar_wtc_producto(result, wtc, desde, hasta, hoy)` — pura

Se llama en `fetch_all` al final, sobre `result` (el dict por marca de un período), antes de
devolverlo. `wtc` es la lista leída (o `None`); `hoy` es un `date` (inyectado para testear).

Meses del período: los meses cargados con `desde <= mes <= hasta` (`mes` = primer día del mes;
todos los períodos de `compute_periods()` empiezan un día 1). El mes en curso suma solo si está
cargado, aunque sea parcial. `L` = suma de `litros_cerveza` de esos meses.

Efecto, si `wtc` no es `None` y `L > 0`, para `PATAGONIA` y para `TODAS`:

| campo | efecto |
|---|---|
| `lts_cerveza` | `+= L` (redondeo a 1 decimal) |
| `total_lts` | `+= L` (redondeo a 1 decimal) |
| `locales` | agrega `{local:"WTC", marca:"Patagonia", lts_cerveza:L, lts_total:L, lts_gin:0, lts_fernet:0, lts_feriado:0, lts_tragos:0}` y reordena por `lts_total` desc |
| `total_fac`, `mix`, `ranking`, `vs_ant_pct`, `n_productos` | sin cambios |

- Si una marca (`PATAGONIA` o `TODAS`) vino `sin_acceso`, no se le suma nada (no mostrar una
  marca con solo WTC). Son independientes: PATAGONIA `sin_acceso` no impide sumar en TODAS.
- `TEMPLE` y `FERIADO` nunca se tocan.
- La marca de la fila WTC va como `"Patagonia"`, igual que el resto de los locales
  (`marca.capitalize()` en `fetch_all`), tanto en `PATAGONIA.locales` como en `TODAS.locales`.

Además agrega, siempre, `result["wtc"]` a nivel período:

```json
{"lts": 1234.5, "meses_incluidos": ["2026-07-01"], "meses_faltantes": ["2026-08-01"], "error": false}
```

- `meses_faltantes`: meses **cerrados** del período (`mes < primer día del mes de hoy`), desde
  `2025-01` (inicio de la historia de WTC), sin fila. El mes en curso nunca cuenta como faltante.
- Con `wtc is None`: `{"lts": 0, "meses_incluidos": [], "meses_faltantes": [], "error": true}` y no
  se suma nada.

### Nota en el iframe (`templates/producto_preview.html`)

Un `<p class="note" id="wtcNotaProd">` arriba de la franja de litros, visible solo con marca
`PATAGONIA` o `TODAS`. Texto armado por una función pura `wtcNotaProducto(wtc)`:

- `error`: "⚠ No se pudo leer la carga de WTC: esta pestaña no lo incluye." (solo eso).
- `lts > 0`: "Incluye WTC (Uruguay): X lts de cerveza, carga manual. Solo litros; la facturación
  de WTC no está en esta pestaña."
- `lts == 0`: "WTC (Uruguay): sin litros cargados en este período."
- En los dos últimos casos, si `meses_faltantes` no está vacío, agrega "⚠ Falta cargar ago-26, sep-26."

Formato de mes `ago-26`, igual que `_wtcMes` del tablero retail. La nota se actualiza en `render()`
(cambio de período o marca vía `postMessage`).

### Errores

- Falla la lectura de WTC → Producto se publica sin WTC (como hoy), `WARN WTC` en el log del
  pipeline, nota con aviso.
- Falla una marca (excepción existente en `fetch_all`) → sin cambios respecto de hoy.

## Tests (primero, pytest)

`tests/test_wtc_producto.py`:

- suma `L` a `lts_cerveza` y `total_lts` de PATAGONIA y TODAS; TEMPLE/FERIADO intactos;
- mes fuera del rango no suma; mes en curso cargado suma; mes en curso no cargado no figura en
  faltantes;
- mes cerrado sin fila → en `meses_faltantes`; meses previos a 2025-01 nunca faltantes;
- `wtc=[]` → datos intactos y `wtc.lts == 0`; `wtc=None` → datos intactos y `error: true`;
- PATAGONIA `sin_acceso` → no se toca; TODAS sí;
- WTC entra en `locales` con marca "Patagonia" y queda ordenado por `lts_total`;
- `total_fac`, `mix`, `ranking`, `vs_ant_pct` iguales antes y después.

Nota del template con `run_dom_js` (patrón de `tests/test_finanzas_js.py`): texto de
`wtcNotaProducto` para cada caso y visibilidad según marca.

Verificación local: `python -X utf8 generar_preview_producto.py --no-upload` y revisar
`preview_producto.html` (sonda Chrome headless, incluido ancho de celular por iframe).

## Deploy

- Push a main + `gh workflow run actualizar-pipeline.yml`; verificar log (`grep "FALLÓ\|WARN WTC"`)
  y que el blob `producto.html` tenga fecha nueva y contenga `wtcNotaProd`.
- No toca Cloud Run ni `app.py`.

## Fuera de alcance

Facturación de WTC en Producto, detalle por producto de WTC, borrar `fetch_producto_data`
(código muerto en `actualizar_retail.py`), fase 3 (Patagonia Semestral).
