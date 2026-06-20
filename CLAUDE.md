# Configuración de trabajo - Darwin Salinas

## Carpeta de trabajo
Siempre guardar los archivos en: `C:\Users\Darwin Salinas\Claude_Cowork`

## Usuario
- Nombre: Darwin Salinas
- Email: darwin.salinas@temple.com.ar

## Gotchas <!-- /aprende 2026-06-15 -->

- **GateGuard hook (pre:edit-write):** Antes de cada Edit/Write hay que presentar 4 hechos en el mismo turno de respuesta: (1) quién llama al archivo, (2) funciones/clases afectadas, (3) estructura de datos si aplica, (4) instrucción textual del usuario. El hook bloquea si los hechos no están en el mensaje inmediatamente anterior a la tool call.

- **Cloud Run deploy — locales-propios:** `gcloud run deploy locales-propios --source . --region us-central1 --project temple-bar-439715 --quiet` — usar `--update-env-vars` (no `--set-env-vars`) para agregar/modificar variables sin borrar las existentes. <!-- /aprende 2026-06-19 -->
