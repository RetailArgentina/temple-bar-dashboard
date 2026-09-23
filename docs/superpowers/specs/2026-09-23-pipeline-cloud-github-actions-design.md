# Pipeline de actualización de tableros — migración a GitHub Actions

## Contexto

El pipeline diario (`actualizar_todo.py`: sync Feriado Toteat, sync Catálogo Feriado, Ventas, Producto, Reseñas Google, sync Contabilium→BQ, Destilería) corre hoy desde dos tareas del Programador de Tareas de Windows en la notebook de Darwin (08:30 y 12:00 ART). Si la PC está dormida o apagada en esos horarios, el pipeline no corre — y hasta el 22/09/2026 hubo además un Cloud Run Job (`actualizar-dashboard`) disparado por Cloud Scheduler en los mismos dos horarios, pensado como respaldo, pero con una imagen Docker sin reconstruir desde julio y un bug de ruta que rompía el paso de Contabilium en silencio. Ese Job y sus triggers de Cloud Scheduler ya fueron eliminados (ver `lesson_destileria-cot-guardrail.md`, update 22/09).

Objetivo: que el pipeline corra 100% en la nube, sin depender de que la PC esté encendida, y sin poder quedar "viejo" como pasó con la imagen Docker anterior.

## Decisión de arquitectura

**GitHub Actions como scheduler y runtime**, no Cloud Run Job. Un workflow con `schedule: cron` hace checkout del repo y corre `python actualizar_todo.py` directo en el runner. Como cada corrida parte del código recién bajado del repo, no hay paso de build/deploy que alguien se pueda olvidar de disparar — el problema de raíz del incidente anterior.

Alcance: todo el pipeline (no solo Destilería). Las tareas de Windows se dan de baja del todo una vez validado el workflow.

## 1. Workflow y disparador

Archivo nuevo: `.github/workflows/actualizar-pipeline.yml`

- `on.schedule`: dos entradas cron, `30 11 * * *` y `0 15 * * *` (UTC = 08:30 y 12:00 ART; sin ajuste automático de horario de verano, Argentina no lo usa).
- `on.workflow_dispatch`: permite correrlo a mano desde la pestaña Actions de GitHub, para pruebas y para forzar una corrida si hace falta.
- `concurrency: { group: actualizar-pipeline, cancel-in-progress: false }`: si una corrida anterior sigue en curso cuando dispara la siguiente, la nueva espera en cola en vez de correr en paralelo — reemplaza el lock de archivo local (`temple_pipeline.lock`), que solo protege corridas dentro de la misma máquina y no sirve entre runners distintos de GitHub.
- Runner: `ubuntu-latest`, Python 3.11 (mismo que usaba `Dockerfile.job`).
- Timeout del job: 30 min (el pipeline local corre en ~10-15 min normalmente; los timeouts internos de cada paso ya están en `actualizar_todo.py`).

## 2. Credenciales y secretos

**GCP (BigQuery, GCS, Firestore):** Workload Identity Federation. Se crea una vez un Workload Identity Pool + Provider en `temple-bar-439715` que confía en tokens OIDC emitidos por GitHub Actions para el repo `RetailArgentina/temple-bar-dashboard`, con permiso de impersonar `dashboard-refresh@temple-bar-439715.iam.gserviceaccount.com`. El workflow usa `google-github-actions/auth@v2` con ese pool/provider — no hay ningún archivo de key, ni siquiera temporal, en el runner.

**APIs externas (GitHub Secrets → env vars del runner):**
| Secret | Reemplaza |
|---|---|
| `TOTEAT_XIU`, `TOTEAT_XIR`, `TOTEAT_XIL` | ya eran env vars localmente |
| `PLACES_API_KEY`, `PLACES_ID_BARRIO_CHINO`, `PLACES_ID_MONROE` | ya eran env vars localmente |
| `CONTABILIUM_EMAIL`, `CONTABILIUM_APIKEY` | **nuevo** — hoy hardcodeado en `contabilium_sync_bq.py` líneas 12-13 |

## 3. Cambios de código necesarios

Estos cambios son requisito para que el checkout del repo sea seguro y el script corra en un entorno limpio (no scope agregado):

1. **`contabilium_sync_bq.py`**: mover de `C:\Users\Darwin Salinas\` (fuera de cualquier repo, deliberadamente, por las credenciales hardcodeadas) a `Claude_Cowork/contabilium_sync_bq.py` (ya existe una copia idéntica ahí, sin trackear — confirmado con `diff` que son iguales). Reemplazar `EMAIL = "..."` / `APIKEY = "..."` por `os.environ["CONTABILIUM_EMAIL"]` / `os.environ["CONTABILIUM_APIKEY"]`.
2. **`actualizar_todo.py`**: el paso "Contabilium → BQ" arma la ruta con `os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "contabilium_sync_bq.py")` — funciona por casualidad en la PC de Darwin (2 niveles arriba de `Claude_Cowork`), pero no existe en ningún otro entorno (rompía silenciosamente en el Cloud Run Job viejo). Cambiar a `os.path.join(SCRIPT_DIR, "contabilium_sync_bq.py")` ahora que el script vive junto a los demás. Sacar también el bloque de la pausa hardcodeada del 25/08/2026 (código muerto, esa fecha ya pasó).
3. **`generar_destileria_dashboard.py`**: `SA_KEY = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")` se usa para credenciales de Drive/BQ. Agregar fallback: si el archivo no existe (caso GitHub Actions, que usa WIF), usar `google.auth.default()` en su lugar. No cambia el comportamiento local (el archivo sigue estando en la PC de Darwin si corre algo a mano ahí).
4. Cualquier otro script del pipeline (`sync_feriado_toteat.py`, `sync_catalogo_feriado.py`, `actualizar_retail.py`, `generar_preview_producto.py`, `google_reviews_sync.py`) que cargue la misma `SA_KEY` de forma similar recibe el mismo fallback — se audita cada uno durante la implementación.

## 4. Manejo de fallos

GitHub notifica por email al dueño del repo automáticamente cuando un workflow falla — sin configuración adicional. Es una mejora real: hoy un fallo silencioso del pipeline solo queda escrito en `dashboard_errors.log`, que nadie revisa activamente (así pasó desapercibido el gap de 6 corridas del 18/08/2026). No se agrega ningún canal adicional (Slack/WhatsApp) en este alcance — se puede sumar después si hace falta.

## 5. Baja de las tareas de Windows

Una vez que el workflow corrió limpio un par de días seguidos (vía `workflow_dispatch` primero, después con el cron activo), se deshabilitan (no se borran) en el Programador de Tareas: "Dashboard Temple Ventas" (08:30) y "Dashboard Temple Ventas Mediodia" (12:00). Quedan ahí por si alguna vez hace falta volver a correr algo local a mano, pero no se disparan solas.

## 6. Plan de rollout

1. Mover `contabilium_sync_bq.py` a `Claude_Cowork`, aplicar los 3-4 cambios de código de la sección 3.
2. Cargar los secrets en GitHub (repo settings → Secrets and variables → Actions).
3. Crear el Workload Identity Pool + Provider en GCP y dar permiso de impersonación a la SA.
4. Escribir el workflow con `workflow_dispatch` solamente (sin cron activo todavía).
5. Correrlo a mano desde GitHub, verificar que publica en GCS igual que la corrida local (mismos guardrails de `generar_destileria_dashboard.py` aplican sin cambios — siguen corriendo dentro del mismo script).
6. Si sale limpio 2-3 veces seguidas, activar el cron.
7. Deshabilitar las tareas de Windows.

## Fuera de alcance

- No se toca `dashboard-refresh-job` (el otro Cloud Run Job inactivo desde abril, sin relación con este pipeline).
- No se cambia cómo se deploya el servicio web `temple-bar-dashboard` (Cloud Run service) — eso sigue igual, es un proceso separado.
- No se agregan canales de notificación nuevos más allá del email default de GitHub.
