# Pestaña "Finanzas" del tablero retail — facturación vs inflación

**Fecha:** 2026-09-28 · **Rama:** `finanzas-ipc` · **Estado:** diseño aprobado en chat, pendiente revisión de este spec

## Objetivo

Separar crecimiento real de crecimiento nominal en el tablero retail (Temple, Patagonia, Feriado).
Hoy todo está en pesos corrientes, así que "creció +29%" puede ser casi todo inflación
(ej.: Temple jul-26 same-store +29% facturación vs +8% órdenes).

Usuarios: **gerencia/dirección**. Dos preguntas a responder:
1. ¿El negocio crece por encima de la inflación? (por marca, total y same-store)
2. ¿Los objetivos 2026 en pesos siguen siendo realistas en términos reales?

Fuera de alcance: análisis de precios/ticket vs IPC, márgenes, costos, dólar.

## Decisiones tomadas

- Ubicación: **4ª pestaña "Finanzas"** en `templates/dashboard.html` (misma página, comparte filtros
  marca/período y los datasets `MENSUAL` / `LOCAL_MENSUAL` / objetivos ya inyectados). No iframe.
- Deflactor: **IPC general nacional** (`148.3_INIVELNAL_DICI_M_26`). Referencia del rubro:
  **IPC Hoteles y restaurantes nacional** (`146.3_IRESTAUNAL_DICI_M_33`). Ambas base dic-2016,
  mensuales, API pública `https://apis.datos.gob.ar/series/api/series/`.
- Objetivos: no se sabe si incluían inflación supuesta → se usa **crecimiento implícito** del
  objetivo vs venta real del año anterior (no requiere supuesto; no se agrega campo manual).
- Sin deploy de Cloud Run: sale por el pipeline de datos (GitHub Actions).

## Parte 1 — Bloque "Crecimiento real"

- **Base:** pesos del último mes con IPC publicado. Etiqueta explícita "en $ de <mmm-aa>".
- **KPIs** (responden a marca + período):
  - Facturación nominal (mismo número que Ventas).
  - Facturación real (nominal deflactada a la base).
  - **Crecimiento real vs año ant.** = (1 + crec. nominal YoY) / (1 + IPC YoY del período) − 1.
    Verde ≥ 0, rosa < 0.
  - Inflación del período: general y rubro lado a lado.
- **Gráfico** (Chart.js, línea): últimos 24 meses, facturación nominal vs real de la marca filtrada.
- **Tabla por marca** (Temple · Patagonia · Feriado · Total): crec. nominal YoY · IPC YoY ·
  crec. real YoY · crec. real same-store YoY (same-store con la misma regla que Ventas:
  match marca + UPPER(TRIM(local)) en `LOCAL_MENSUAL`).
- **Meses sin IPC publicado:** se estiman repitiendo la última variación mensual conocida;
  marcados con "e" + nota al pie. Se corrigen solos en la corrida siguiente a la publicación.
- **Mes en curso:** misma lógica de cierre estimado prorrateado que Ventas, para que las dos
  pestañas no se contradigan.

## Parte 2 — Bloque "Objetivos en términos reales"

Nota de diseño: el % de cumplimiento mensual no cambia al deflactar (venta y objetivo del mismo
mes usan el mismo IPC), por eso no se repite acá.

- **Tabla marca × mes (2026):** objetivo (`obj_fac`, millones) · venta real mismo mes 2025 ·
  crec. nominal implícito (obj / venta_aa − 1) · IPC YoY de ese mes ·
  **crec. real implícito** = (1 + nominal implícito) / (1 + IPC YoY) − 1.
  Clasificación: **Exigente** > +10% real · **Razonable** 0% a +10% · **Laxo** < 0%.
  Umbrales como constantes en el JS, fáciles de cambiar.
- **Tarjeta "Resto del año"** por marca: objetivo anual − facturado YTD = faltante; crecimiento
  real implícito del faltante vs mismos meses de 2025, con IPC proyectado (marcado estimado).
- **Salvedad WTC:** objetivos vienen por marca (no por local) desde el Sheet
  `Objetivos_Temple_BQ`; el de Patagonia incluye WTC (objetivo cargado, venta $0 en 2026).
  Se muestra nota fija; no se puede excluir.

## Parte 3 — Datos, fallas y tests

**Módulo nuevo `ipc_indec.py`** (no engordar `actualizar_retail.py`):
- `fetch_ipc(desde="2024-01")` → pide las 2 series (timeout 20 s, 2 reintentos).
- `completar_estimados(series, hasta=<mes actual>)` → extiende con la última variación mensual;
  devuelve también la lista de meses estimados.
- `validar(series)` → no vacías, índice no decreciente mes a mes. Si el último dato publicado
  tiene > 3 meses de antigüedad, imprime `FALLÓ IPC desactualizado` (el grep del pipeline lo toma).
- Salida (JSON inyectado): `{"base": "2026-08", "general": {"2024-01": 1234.5, ...},
  "rubro": {...}, "estimados": ["2026-09"], "fuente": "api"|"cache"}`.

**Fallback:**
1. Corrida OK → guarda `ipc_cache.json` en `gs://temple-bar-dashboard-cache/`
   (cache_control después del upload, según lección de GCS).
2. API falla → usa `ipc_cache.json`, log `FALLÓ IPC API, usando cache`.
3. Sin API ni cache → inyecta `null`; la pestaña muestra "Datos de inflación no disponibles".
   **El resto del tablero no se ve afectado** (una falla de IPC nunca aborta el pipeline).

**Integración:** marcador `__IPC_JSON__` en `dashboard.html`, reemplazado en
`generate_html_from_file` igual que `__MENSUAL_JSON__`. Botón `navFinanzas` + `view-finanzas`,
agregados en `switchView`. Estilos de `static/temple-retail.css` (clases existentes; lo nuevo
se agrega ahí). El gráfico se crea/redimensiona la **primera vez que se abre la pestaña**
(Chart.js en contenedor `display:none` queda de tamaño 0).

**Tests:**
- `tests/test_ipc_indec.py` con la API simulada: descarga OK, fallback a cache,
  sin API ni cache → None, estimación de meses, validación (vacía / decreciente / desactualizada).
- Test de que `generate_html_from_file` reemplaza `__IPC_JSON__` (incluido el caso `null`).
- `pytest tests/` completo en verde.
- Preview local (`design_handoff_tablero_retail/preview/rebuild.py`, con un `ipc.json` en `cache/`):
  sin errores de JS recorriendo marcas × períodos, 0 desbordes en 375/768/1440.

**Rollout:** implementación en `finanzas-ipc` → preview local aprobado por el usuario →
un solo merge a `main` → disparar `actualizar-pipeline.yml` → verificar log (grep FALL/Traceback)
y la pestaña en producción.
