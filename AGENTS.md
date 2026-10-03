# Configuración de trabajo - Darwin Salinas

## Carpeta de trabajo
Siempre guardar los archivos en: `C:\Users\Darwin Salinas\Claude_Cowork`

## Usuario
- Nombre: Darwin Salinas
- Email: darwin.salinas@temple.com.ar

## Gotchas

- **GateGuard hook (pre:edit-write):** Antes de cada Edit/Write hay que presentar 4 hechos en el mismo turno de respuesta: (1) quién llama al archivo, (2) funciones/clases afectadas, (3) estructura de datos si aplica, (4) instrucción textual del usuario. El hook bloquea si los hechos no están en el mensaje inmediatamente anterior a la tool call.

- **Cloud Run deploy — locales-propios:** `gcloud run deploy locales-propios --source . --region us-central1 --project temple-bar-439715 --quiet` — usar `--update-env-vars` (no `--set-env-vars`) para agregar/modificar variables sin borrar las existentes. <!-- /aprende 2026-06-19 -->

- **Tests de render del tablero sin navegador:** `run_dom_js` en `tests/test_finanzas_js.py` extrae funciones de render de `templates/dashboard.html` por nombre (`^function X(...^}`) y las corre en Node con un `document` falso (`getElementById` devuelve un objeto por id con `style`/`innerHTML`/`textContent`). Usarlo para testear lógica de DOM (mostrar/ocultar secciones, try/catch de `updateAll`) en vez de regex sobre el HTML. <!-- /aprende 2026-09-29 -->

- **Pestaña Producto del tablero retail:** es el iframe `gs://temple-bar-dashboard-cache/producto.html`, generado por `generar_preview_producto.py` (paso "Producto" de `actualizar_todo.py`, por períodos: mes actual/anterior/3m/6m/YTD). `fetch_producto_data` en `actualizar_retail.py` es código muerto — no diseñar sobre esa función. <!-- /aprende 2026-10-03 -->
