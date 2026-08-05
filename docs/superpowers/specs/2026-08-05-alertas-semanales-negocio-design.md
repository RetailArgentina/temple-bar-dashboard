# Alertas Semanales de Negocio — Diseño

**Fecha:** 2026-08-05
**Proyecto:** Nuevo script en la raíz de `Claude_Cowork`, reutiliza fetchers de `generar_informe_semanal.py` y el patrón de mix de producto de `generar_preview_producto.py`.
**Alcance:** Generar automáticamente, cada lunes antes de la reunión semanal con el Country Manager, la gerente de Operaciones y la gerente de Marketing, un reporte HTML standalone con hallazgos concretos de negocio (no narrativa genérica) sobre las 3 marcas (Temple, Patagonia, Feriado).

---

## Contexto

A Darwin le están pidiendo en su trabajo que actúe más como analista de datos/negocio: revisar los datos semanales y levantar alertas concretas sobre situaciones que no correspondan o parezcan desvirtuadas (ej.: un local de Patagonia vendiendo más tragos que cerveza, siendo la cerveza el producto principal de la marca). El resultado de este análisis alimenta una reunión semanal fija los lunes.

**Lo que ya existe y se reutiliza:**
- `generar_informe_semanal.py` ya tiene un motor de reglas con severidad Alta/Media/Baja (`generate_plan_accion()`, líneas 399-593) sobre pace vs objetivo, caída de local, caída de ticket y caída de órdenes — pero es manual (`python generar_informe_semanal.py --semana ...`) y nunca se conectó a un pipeline automático.
- `generar_preview_producto.py` ya calcula litros por familia (cerveza/gin/fernet/feriado/tragos) **por local**, vía `fetch_locales_temple/patagonia/feriado()` (líneas 217-283), reutilizando la columna `establecimiento`/`Establecimiento` que sí existe en las 3 tablas base. Hoy solo se usa para un período fijo (no por semana), y no calcula ningún tipo de desvío.
- El patrón de upload a GCS (`upload_to_gcs()`, líneas 502-519 de `generar_preview_producto.py`) ya resuelve el bug conocido de orden `upload_from_filename()` → `cache_control` → `patch()` → `reload()`.

**Lo que no existe y hay que construir:** el cálculo de mix cerveza/tragos con ventana semanal, la comparación de un local contra sus propios pares (misma marca), y la automatización/reporte semanal en sí.

---

## Decisiones clave

- **Alcance de marcas:** las 3 (Temple, Patagonia, Feriado). Cada regla decide a qué marca(s) aplica según tenga sentido (ej. la regla de mix cerveza/tragos usa columnas distintas por marca, igual que `fetch_locales_*`).
- **3 categorías de reglas en esta v1:** Performance/ritmo, Mix de producto, Ticket/Órdenes. Explícitamente **fuera de alcance**: reglas de canal (delivery/salón), oportunidades de marketing (sprint de cierre, local con crecimiento fuerte) y calidad de datos (objetivos faltantes, local sin datos, ticket fuera de rango absoluto) — estas últimas ya existen en `generate_plan_accion()` pero no se reutilizan en v1 para no mezclar "alertas de negocio" con "alertas de calidad de datos". Se puede evaluar una v2 si Darwin lo pide después de la primera corrida real.
- **Método de detección del mix de producto: combinado.** Un local se marca solo si se desvía fuerte de (a) su propio promedio histórico (8 semanas previas) **y/o** (b) el promedio de sus pares (misma marca, misma semana). Ambas señales a la vez → Alta; solo una → Media. No hay un "target" oficial de mix por local (no existe hoy), así que no se usa un umbral absoluto fijo tipo "cerveza debe ser ≥70%".
- **Performance/ritmo y Ticket/Órdenes reutilizan los umbrales ya validados** de `generate_plan_accion()` (no se reinventan): pace <80%→Alta / <92%→Media; caída de local vs semana anterior <-20%→Media / <-30%→Alta; caída de ticket promedio >8%→Media; caída de órdenes <-10%→Media / <-20%→Alta.
- **Formato de salida: HTML standalone**, mismo estilo visual dark (paleta GitHub) que `informe_gerencial_abril2026.html`. Cada hallazgo es texto + números concretos — **sin gráficos ni tablas** (decisión explícita: rapidez de lectura sobre soporte visual).
- **Sin cap artificial de cantidad de hallazgos** — se muestran todos los que superen umbral, ordenados Alta → Media → Baja. Si una semana no genera ningún hallazgo, el reporte lo dice explícitamente en vez de mostrar una sección vacía.
- **Automatización: tarea programada nueva, no se mete en `actualizar_todo.py`** (ese pipeline corre 2 veces por día de lunes a domingo; este reporte solo tiene sentido una vez por semana). Nueva tarea "Alertas Semanales Lunes", lunes 06:30 ARG.
- **Publicación: GCS**, mismo bucket `temple-bar-dashboard-cache`, blob nuevo `alertas_semanales.html`, accesible sin auth vía URL directa (igual que `producto.html`) para poder compartir el link en el chat de la reunión.

---

## Datos: nuevo script `generar_alertas_semanales.py`

### Fetchers reutilizados por import directo desde `generar_informe_semanal.py`
```python
from generar_informe_semanal import (
    get_client, fetch_semana, fetch_mes_actual, fetch_objetivos,
    agg_por_marca, agg_por_local, ticket_prom, delta_pct,
)
```
Se llaman con la misma lógica de fechas que usa `build_informe()` (línea 708 en adelante): `semana_inicio`/`semana_fin` = lunes a domingo de la semana a evaluar (default: semana pasada), `sem_ant_ini`/`sem_ant_fin` = semana anterior, `mes_inicio` = primer día del mes de `semana_inicio`, `pace = dias_mes_trans / dias_mes_total`.

### Fetcher nuevo: mix de producto por semana y por local
```
fetch_mix_semanal_por_local(client, marca, desde, hasta) -> list[dict]
    Igual a fetch_locales_temple/patagonia/feriado() de generar_preview_producto.py
    (mismas 3 queries, mismas columnas lts_cerveza/lts_gin/lts_fernet/lts_feriado/
    lts_tragos/lts_total por marca), pero agrega DATE_TRUNC(fecha, WEEK(MONDAY))
    AS semana al SELECT y GROUP BY, para traer de una sola consulta las últimas
    N semanas en vez de un período agregado.
    Devuelve: {local, semana, lts_cerveza, lts_tragos, lts_total, pct_cerveza}
    (pct_cerveza = lts_cerveza / lts_total si lts_total > 0, si no None)
```
Se llama una vez por marca pidiendo `desde = semana_inicio - 8 semanas`, `hasta = semana_fin`, para tener la semana a evaluar + 8 semanas de historia propia en una sola pasada por marca (3 queries en total, no 3×9).

### Config de umbrales (dict al inicio del script, mismo patrón que `economic_context.json`/`config.py` de otros scripts)
```python
CONFIG = {
    "ticket_caida_pct":        -8,     # Media
    "ordenes_caida_pct":       {-10: "Media", -20: "Alta"},
    "local_caida_pct":         {-20: "Media", -30: "Alta"},
    "pace_cumpl_pct":          {80: "Alta", 92: "Media"},   # menor a
    "mix_desvio_self_pp":      15,      # puntos porcentuales vs propio promedio 8 sem
    "mix_desvio_peer_pp":      10,      # puntos porcentuales vs promedio de pares
    "mix_min_lts_semana":      50,      # litros mínimos esa semana para evaluar (evita ruido de locales chicos)
    "mix_min_semanas_historia": 4,      # semanas mínimas de historia propia para evaluar self-history
    "mix_min_locales_peer":    3,       # locales pares mínimos (con datos esa semana) para evaluar peer-comparison
}
```

---

## Motor de reglas

Cada regla devuelve hallazgos con la misma forma:
```python
{"marca": str, "local": str | None, "categoria": "Performance" | "Mix producto" | "Ticket/Órdenes",
 "severidad": "Alta" | "Media" | "Baja", "mensaje": str, "detalle": str}
```
(`local=None` para hallazgos a nivel marca, ej. pace mensual.)

### Categoría "Performance" (reutiliza fórmulas de `generate_plan_accion()` líneas 419-453)
- Pace por marca: `cumpl_pace = real_M / (obj_M * pace) * 100`. `<80` y `dias_rest>3` → Alta; `<92` → Media.
- Caída de local vs semana anterior (sobre `agg_por_local` de esta semana vs `locales_ant_dict` de la anterior): `dp = (fac_actual - fac_ant) / fac_ant * 100`. `<-30` → Alta; `<-20` → Media.

### Categoría "Ticket/Órdenes" (líneas 455-469 y 485-496)
- Ticket promedio por marca: `dp_tk < -8%` → Media.
- Órdenes por marca: `dp_o < -10%` → Media; `<-20%` → Alta.

### Categoría "Mix producto" (nueva)
Para cada `(marca, local)` con datos en la semana evaluada y `lts_total >= mix_min_lts_semana`:
1. `pct_cerveza_semana = lts_cerveza / lts_total`
2. **Self:** si hay ≥`mix_min_semanas_historia` semanas previas con datos, `self_avg = promedio(pct_cerveza)` de esas semanas. `desvio_self = pct_cerveza_semana - self_avg` (en pp).
3. **Peer:** locales de la misma marca con datos esa misma semana (excluyendo el propio). Si hay ≥`mix_min_locales_peer`, `peer_avg = promedio(pct_cerveza)` de esos locales esa semana. `desvio_peer = pct_cerveza_semana - peer_avg` (en pp).
4. Severidad:
   - `|desvio_self| >= 15pp` **y** `|desvio_peer| >= 10pp` (ambos calculables) → **Alta**
   - Solo una de las dos señales calculable y supera su umbral → **Media**
   - Ninguna supera umbral, o ninguna es calculable (local nuevo, sin pares) → sin hallazgo
5. Mensaje ejemplo: `"{local} ({marca}): cerveza cayó a {pct:.0f}% del volumen (esperado ~{self_avg:.0f}% según su propia historia, {peer_avg:.0f}% en locales pares)"`.

---

## Render: `render_alertas_html(hallazgos, semana_inicio, semana_fin)`

- Mismo esqueleto visual dark que `informe_gerencial_abril2026.html` (paleta `#0f2544`/`#2563eb`/etc. ya usada en `generar_informe_semanal.py`, adaptada a HTML/CSS en vez de ReportLab).
- Header: rango de semana evaluada + fecha/hora de generación.
- Hallazgos agrupados por severidad (Alta primero), cada uno como bloque: categoría (badge), mensaje, detalle. Sin gráficos.
- Si `hallazgos` está vacío: bloque único "Sin hallazgos relevantes esta semana" (no se oculta la sección, se muestra el estado explícitamente).
- Footer con el link a los otros tableros (Ventas/Producto), igual que en los informes gerenciales existentes.

## Deploy: reutiliza `upload_to_gcs()` (adaptado desde `generar_preview_producto.py:502-519`)

```
python -X utf8 generar_alertas_semanales.py \
    [--semana YYYY-MM-DD] \
    --gcs-bucket temple-bar-dashboard-cache \
    --gcs-blob alertas_semanales.html
```
Orden: generar HTML local → `upload_from_filename()` → `cache_control` → `patch()` → `reload()` (verificación), igual que los otros 4 scripts ya corregidos por el bug de orden.

URL resultante: `https://storage.googleapis.com/temple-bar-dashboard-cache/alertas_semanales.html?v=N` (agregar `?v=N` para forzar cache-bust en el navegador al abrir el link antes de la reunión).

---

## Automatización

Nueva tarea programada Windows **"Alertas Semanales Lunes"**:
- `Execute: C:\Windows\System32\cmd.exe` / `Arguments: /c "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\generar_alertas_semanales.bat"` (mismo patrón que la tarea "Dashboard Temple Ventas" para evitar el bug de ruta partida por el espacio en "Darwin Salinas").
- Trigger: semanal, lunes, 06:30 ARG (antes de la reunión, después de que los datos del domingo ya estén sincronizados vía Toteat/Contabilium).
- `ExecutionTimeLimit=PT2H`, `DisallowStartIfOnBatteries=false`, `StopIfGoingOnBatteries=false`, `StartWhenAvailable=true` (mismos flags ya corregidos en las otras tareas por los incidentes previos).
- `generar_alertas_semanales.bat` nuevo, mismo patrón que `actualizar_dashboard.bat`: activa el venv/entorno, corre `python -X utf8 generar_alertas_semanales.py --gcs-bucket temple-bar-dashboard-cache --gcs-blob alertas_semanales.html`.

---

## Testing

- `tests/test_generar_alertas_semanales.py`:
  - Casos unitarios de la regla de mix: self-only, peer-only, ambas señales (Alta), ninguna señal, local sin suficiente historia, marca con <3 locales pares (Feriado) → solo se evalúa self.
  - Casos de performance/ticket/órdenes: mismos casos límite que ya cubre (si existen) los tests de `generar_informe_semanal.py`, para confirmar que la reutilización de fetchers no cambió el comportamiento.
  - Caso "sin hallazgos": `render_alertas_html([], ...)` debe producir el bloque de estado explícito, no una sección vacía.

## Verificación end-to-end

1. `python -m pytest tests/test_generar_alertas_semanales.py -v`.
2. Correr manualmente contra 2-3 semanas históricas ya conocidas por Darwin (`--semana YYYY-MM-DD` retroactivo) y confirmar que el reporte no genera ruido excesivo ni pasa por alto un caso evidente (ej. el ejemplo real de mix cerveza/tragos en Patagonia que motivó este proyecto).
3. Ajustar los umbrales de `CONFIG` (especialmente los de mix, que son los únicos sin precedente validado) según ese primer contraste con la realidad, antes de dejar la tarea programada corriendo sola.
4. Confirmar la tarea programada con una corrida manual (`schtasks /run /tn "Alertas Semanales Lunes"`) y verificar que el HTML aparece en GCS con `cache_control` correcto (`blob.reload()` en `upload_to_gcs()` ya lo valida y loguea warning si falla).
