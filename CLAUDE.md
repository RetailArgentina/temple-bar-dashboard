# Configuración de trabajo - Darwin Salinas

## Carpeta de trabajo
Siempre guardar los archivos en: `C:\Users\Darwin Salinas\Claude_Cowork`

## Usuario
- Nombre: Darwin Salinas
- Email: darwin.salinas@temple.com.ar

## Gotchas <!-- /aprende 2026-06-15 -->

- **GateGuard hook (pre:edit-write):** Antes de cada Edit/Write hay que presentar 4 hechos en el mismo turno de respuesta: (1) quién llama al archivo, (2) funciones/clases afectadas, (3) estructura de datos si aplica, (4) instrucción textual del usuario. El hook bloquea si los hechos no están en el mensaje inmediatamente anterior a la tool call.

- **Cloud Run deploy — locales-propios:** `gcloud run deploy locales-propios --source . --region us-central1 --project temple-bar-439715 --quiet` — usar `--update-env-vars` (no `--set-env-vars`) para agregar/modificar variables sin borrar las existentes. <!-- /aprende 2026-06-19 -->

- **Places API — reviews timestamp:** El campo `time` de cada reseña es un Unix timestamp entero. Convertirlo en `data/places.py` con `datetime.fromtimestamp(r["time"]).strftime("%d/%m/%Y")` y guardarlo como `r["date_str"]` para exponerlo al template. <!-- /aprende 2026-06-20 -->

- **Admin clusterización — valor BQ para sin canal:** El string exacto en BigQuery para clientes sin canal asignado es `'Sin Cluster'` (no `'Sin clasificar'`). Cualquier comparación en Python o JS debe usar `'Sin Cluster'`. Verificar con el script sobre el HTML generado si hay dudas. <!-- /aprende 2026-06-20 -->

- **Admin clusterización — _dest_cache no refresca para admin:** El endpoint `/api/admin/clients` debe siempre hacer fetch fresco desde GCS (no usar `if _dest_cache["html"] is None`). De lo contrario clientes nuevos son invisibles hasta restart del Cloud Run instance. <!-- /aprende 2026-06-20 -->

- **Script retail renombrado:** El script de actualización del tablero retail es `actualizar_retail.py` (no `actualizar_dashboard.py`, que ya no existe). El bat y `actualizar_todo.py` ya lo llaman correctamente. Solo afecta comandos manuales directos. <!-- /aprende 2026-06-26 -->

- **Cloud Run cache bust retail:** Cuando GCS tiene el HTML actualizado pero Cloud Run sigue sirviendo la versión vieja (caché 5 min TTL), forzar nueva revisión: `gcloud run services update temple-bar-dashboard --region southamerica-east1 --update-env-vars CACHE_BUST=$(date +%s)` <!-- /aprende 2026-06-26 -->

- **Tareas programadas — ExecutionTimeLimit:** Ambas tareas ("Dashboard Temple Ventas" 08:30 y "Mediodia" 12:00) necesitan `ExecutionTimeLimit=PT2H`, `StopIfGoingOnBatteries=False`, `DisallowStartIfOnBatteries=False`. El default PT20M mata el pipeline antes de que termine. <!-- /aprende 2026-06-26 -->

- **Pipeline BQ Feriado — arquitectura de facturación:** La cadena es `Ventas_Toteat` → `vw_Ventas_Feriado` → `vw_Ventas_Corporativo_Base` → `vw_KPI_Facturacion_Actual`. La vista corporativa usa `Total_Orden WHERE cuenta_orden=1` (no la columna `Facturacion`/`Dinero`). Diferencia entre columnas: Facturacion = neto por item, Total_Orden = total por orden, Total_Orden_Bruto = antes de descuentos. <!-- /aprende 2026-06-30 -->

- **Backfill Toteat — discrepancia de sync:** Si hay discrepancia entre facturación en BQ y reporte del sistema, primero comparar `COUNT(DISTINCT orden_id)`. Si hay menos órdenes en BQ → problema de sync, no de cálculo. Backfill: `python -X utf8 sync_feriado_toteat.py --desde YYYYMMDD --hasta YYYYMMDD`. Nunca día por día — siempre rangos de al menos 14 días. <!-- /aprende 2026-06-30 -->
