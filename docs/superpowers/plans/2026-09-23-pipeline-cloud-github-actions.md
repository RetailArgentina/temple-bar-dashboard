# Pipeline Cloud (GitHub Actions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover el pipeline diario de actualización de tableros (`actualizar_todo.py`) de las tareas de Windows Task Scheduler a un workflow de GitHub Actions, para que corra sin depender de que la PC esté encendida y sin poder quedar con código desactualizado.

**Architecture:** Workflow de GitHub Actions con `schedule: cron` hace checkout del repo y corre `python actualizar_todo.py` directo en un runner `ubuntu-latest`. Autenticación a GCP vía Workload Identity Federation (sin key files). Secretos de APIs externas (Contabilium, Toteat, Places) vía GitHub Secrets.

**Tech Stack:** Python 3.11, GitHub Actions, `google-github-actions/auth@v2`, Workload Identity Federation (GCP), BigQuery, Cloud Storage.

**Spec:** `docs/superpowers/specs/2026-09-23-pipeline-cloud-github-actions-design.md`

## Global Constraints

- Alcance: TODO el pipeline (no solo Destilería) — Feriado Toteat, Feriado Catálogo, Ventas, Producto, Reseñas Google, Contabilium→BQ, Destilería.
- Sin archivos de key en el runner de GitHub — GCP se autentica solo vía Workload Identity Federation.
- Horarios: `30 11 * * *` y `0 15 * * *` UTC (= 08:30 y 12:00 ART, sin DST).
- Las tareas de Windows se deshabilitan (no se borran) recién al final, después de validar 2-3 corridas limpias.
- No tocar `dashboard-refresh-job` (Cloud Run Job inactivo, sin relación con este pipeline) ni el deploy del servicio web `temple-bar-dashboard`.
- **Ningún secreto real (API keys, tokens) va en texto plano dentro de este plan ni de ningún archivo commiteado** — siempre por variable de entorno o GitHub Secret, cargado a mano en el momento de ejecutar cada paso.

**Nota sobre verificación:** este plan no es TDD clásico (no hay suite de pytest para un pipeline de orquestación de subprocesos contra APIs externas reales). Cada tarea de código se verifica corriendo el script real con datos reales y comparando el resultado esperado, como ya se hace hoy para este pipeline.

---

### Task 1: Sacar las credenciales hardcodeadas de Contabilium

**Files:**
- Move: `C:\Users\Darwin Salinas\contabilium_sync_bq.py` → `C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\contabilium_sync_bq.py` (sobrescribe la copia idéntica sin trackear que ya está ahí)
- Modify: `Claude_Cowork\contabilium_sync_bq.py:11-13`

**Interfaces:**
- Produces: el script sigue exponiendo `get_token()` y `main()` sin cambios de firma — solo cambia de dónde salen `EMAIL`/`APIKEY`.

- [ ] **Step 1: Antes de tocar nada, guardar los valores actuales de EMAIL/APIKEY en un lugar seguro (no en el repo)**

Las líneas 12-13 del archivo original tienen los valores hardcodeados hoy. Copiarlos a un gestor de contraseñas o similar — hacen falta en el Step 3 de esta tarea y en el Task 4. No pegarlos en ningún archivo de este repo.

- [ ] **Step 2: Mover el archivo**

```bash
cd "C:\Users\Darwin Salinas"
mv contabilium_sync_bq.py "Mi unidad\Claude_Cowork\contabilium_sync_bq.py"
```

- [ ] **Step 3: Reemplazar las credenciales hardcodeadas por env vars**

En `Claude_Cowork\contabilium_sync_bq.py`, reemplazar:

```python
# ── Config ────────────────────────────────────────────────────────────────────
EMAIL   = "administracion@bosquegin.com.ar"
APIKEY  = "732bd0b8cfe54a03a648e93a08a46eaf"
```

por:

```python
# ── Config ────────────────────────────────────────────────────────────────────
import os
EMAIL   = os.environ["CONTABILIUM_EMAIL"]
APIKEY  = os.environ["CONTABILIUM_APIKEY"]
```

- [ ] **Step 4: Correr localmente con las env vars para confirmar que sigue funcionando igual que antes**

En PowerShell, usando los valores guardados en el Step 1 (no escribirlos en ningún script ni commit):

```powershell
$env:CONTABILIUM_EMAIL = Read-Host "EMAIL"
$env:CONTABILIUM_APIKEY = Read-Host "APIKEY" -AsSecureString | ConvertFrom-SecureString -AsPlainText
cd "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork"
python -X utf8 contabilium_sync_bq.py --modo incremental --desde (Get-Date).AddDays(-3).ToString('yyyy-MM-dd') --hasta (Get-Date).ToString('yyyy-MM-dd')
```

Expected: mismo output que las corridas anteriores del script (`SYNC ... | incremental`, `OK: N | Errores: 0`), sin errores de credenciales.

- [ ] **Step 5: Confirmar que el archivo viejo fuera del repo ya no existe y que la copia en Claude_Cowork queda trackeada por git**

```bash
ls "C:\Users\Darwin Salinas\contabilium_sync_bq.py" 2>&1   # debe dar "No such file or directory"
cd "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork"
git status --short contabilium_sync_bq.py   # debe mostrar "??" (untracked, todavía no agregado)
```

- [ ] **Step 6: Commit**

```bash
git add contabilium_sync_bq.py
git commit -m "security: mover contabilium_sync_bq.py al repo y sacar credenciales hardcodeadas a env vars

Requisito para poder correr el pipeline desde GitHub Actions sin
exponer las credenciales de Contabilium en el checkout del repo."
```

---

### Task 2: Arreglar la ruta rota de Contabilium en actualizar_todo.py y sacar código muerto

**Files:**
- Modify: `Claude_Cowork\actualizar_todo.py:67-82` (ruta del paso "Contabilium → BQ")
- Modify: `Claude_Cowork\actualizar_todo.py:101-107` (parche hardcodeado del 25/08/2026, vencido)

**Interfaces:**
- Consumes: `contabilium_sync_bq.py` ahora vive en `SCRIPT_DIR` (Task 1) — ya no dos niveles arriba.
- Produces: `SCRIPTS` list sin cambios de forma, solo de contenido.

- [ ] **Step 1: Arreglar la ruta del paso Contabilium**

Reemplazar:

```python
    # ── Sync Contabilium → BQ (antes de generar destilería) ──────────────────
    {
        "label":    "Contabilium → BQ",
        "cmd":      [
            sys.executable, "-X", "utf8",
            os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "contabilium_sync_bq.py"),
            "--modo", "incremental",
            # Sin --desde/--hasta, el script defaultea a 2020-01-01 → recorre
            # 7 años de comprobantes en la API de Contabilium todos los días.
            # Acotamos a los últimos 30 días, suficiente para un sync incremental diario.
            "--desde", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            "--hasta", datetime.now().strftime("%Y-%m-%d"),
        ],
        "critical": False,
        "timeout":  300,   # 5 min máx
    },
```

por:

```python
    # ── Sync Contabilium → BQ (antes de generar destilería) ──────────────────
    {
        "label":    "Contabilium → BQ",
        "cmd":      [
            sys.executable, "-X", "utf8",
            os.path.join(SCRIPT_DIR, "contabilium_sync_bq.py"),
            "--modo", "incremental",
            # Sin --desde/--hasta, el script defaultea a 2020-01-01 → recorre
            # 7 años de comprobantes en la API de Contabilium todos los días.
            # Acotamos a los últimos 30 días, suficiente para un sync incremental diario.
            "--desde", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            "--hasta", datetime.now().strftime("%Y-%m-%d"),
        ],
        "critical": False,
        "timeout":  300,   # 5 min máx
    },
```

- [ ] **Step 2: Sacar el parche hardcodeado del 25/08/2026**

Eliminar este bloque completo:

```python
# Pausa puntual pedida por Darwin: no republicar el tablero de Destilería en la
# corrida de las 12:00 del 2026-08-25 (está en reunión y no quiere que cambie
# la visual). Autolimitado a esta fecha/franja horaria — no requiere revertir
# manualmente, deja de aplicar solo después de hoy.
_now = datetime.now()
if _now.date() == datetime(2026, 8, 25).date() and 11 <= _now.hour <= 13:
    SCRIPTS = [s for s in SCRIPTS if s["label"] != "Destilería"]
```

- [ ] **Step 3: Correr el pipeline completo local para confirmar que el paso Contabilium sigue funcionando con la ruta nueva**

```bash
cd "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork"
python -X utf8 actualizar_todo.py
```

Expected: en `logs/dashboard_update.log`, la línea `── Contabilium → BQ` seguida de `✓ Contabilium → BQ OK` (no debe fallar por "No such file or directory" como haría con la ruta vieja fuera de un entorno con la estructura exacta de la PC de Darwin).

- [ ] **Step 4: Commit**

```bash
git add actualizar_todo.py
git commit -m "fix: ruta de contabilium_sync_bq.py rota fuera de la PC de Darwin, sacar parche vencido del 25/08

La ruta con dirname(dirname(...)) solo funcionaba por casualidad en
un directorio específico — rompía en el Cloud Run Job descontinuado
y rompería igual en GitHub Actions. Ahora que el script vive junto
a los demás (Task 1), referenciarlo directo."
```

---

### Task 3: Crear Workload Identity Federation en GCP

**Files:** ninguno (comandos de infraestructura, no hay archivo para versionar el estado de esto en el repo).

- [ ] **Step 1: Crear el Workload Identity Pool**

```bash
gcloud iam workload-identity-pools create "github-actions-pool" \
  --project="temple-bar-439715" \
  --location="global" \
  --display-name="GitHub Actions"
```

- [ ] **Step 2: Crear el Provider dentro del pool, restringido al repo**

```bash
gcloud iam workload-identity-pools providers create-oidc "github-actions-provider" \
  --project="temple-bar-439715" \
  --location="global" \
  --workload-identity-pool="github-actions-pool" \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='RetailArgentina/temple-bar-dashboard'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

- [ ] **Step 3: Obtener el nombre completo del pool (lo necesita el workflow)**

```bash
gcloud iam workload-identity-pools describe "github-actions-pool" \
  --project="temple-bar-439715" \
  --location="global" \
  --format="value(name)"
```

Expected: algo como `projects/763905018652/locations/global/workloadIdentityPools/github-actions-pool` — guardar este valor, se usa en Task 4 y Task 5.

- [ ] **Step 4: Dar permiso a la identidad del repo para impersonar la SA existente**

```bash
gcloud iam service-accounts add-iam-policy-binding \
  "dashboard-refresh@temple-bar-439715.iam.gserviceaccount.com" \
  --project="temple-bar-439715" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/763905018652/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/RetailArgentina/temple-bar-dashboard"
```

(Reemplazar el número de proyecto `763905018652` por el que devolvió el Step 3 si es distinto.)

- [ ] **Step 5: Verificar el binding**

```bash
gcloud iam service-accounts get-iam-policy \
  "dashboard-refresh@temple-bar-439715.iam.gserviceaccount.com" \
  --project="temple-bar-439715"
```

Expected: aparece el binding de `roles/iam.workloadIdentityUser` con el `principalSet://...github-actions-pool/attribute.repository/RetailArgentina/temple-bar-dashboard` del Step 4.

---

### Task 4: Cargar los secrets en GitHub

**Files:** ninguno (configuración del repo en GitHub, no hay archivo).

- [ ] **Step 1: Sacar los valores actuales de TOTEAT_*/PLACES_* de las env vars de usuario de la PC**

```powershell
[Environment]::GetEnvironmentVariable("TOTEAT_XIU", "User")
[Environment]::GetEnvironmentVariable("TOTEAT_XIR", "User")
[Environment]::GetEnvironmentVariable("TOTEAT_XIL", "User")
[Environment]::GetEnvironmentVariable("PLACES_API_KEY", "User")
[Environment]::GetEnvironmentVariable("PLACES_ID_BARRIO_CHINO", "User")
[Environment]::GetEnvironmentVariable("PLACES_ID_MONROE", "User")
```

- [ ] **Step 2: Cargar los secrets con `gh` CLI, pegando cada valor cuando lo pida (no como argumento en la línea de comando, para que no quede en el historial de la shell)**

```bash
cd "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork"
gh secret set CONTABILIUM_EMAIL      # pegar el valor guardado en Task 1 Step 1, Enter, Ctrl+D
gh secret set CONTABILIUM_APIKEY     # ídem
gh secret set TOTEAT_XIU             # pegar el valor del Step 1 de esta tarea
gh secret set TOTEAT_XIR
gh secret set TOTEAT_XIL
gh secret set PLACES_API_KEY
gh secret set PLACES_ID_BARRIO_CHINO
gh secret set PLACES_ID_MONROE
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body "projects/763905018652/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider"
gh secret set GCP_SERVICE_ACCOUNT --body "dashboard-refresh@temple-bar-439715.iam.gserviceaccount.com"
```

(`gh secret set NOMBRE` sin `--body` espera el valor por stdin/prompt interactivo — evita que un secreto real quede en el historial de comandos o en este plan.)

- [ ] **Step 3: Verificar que los 10 secrets quedaron cargados**

```bash
gh secret list
```

Expected: lista con los 10 nombres de secrets del Step 2 (sin mostrar valores, GitHub nunca los expone después de cargados).

---

### Task 5: Escribir el workflow de GitHub Actions

**Files:**
- Create: `.github/workflows/actualizar-pipeline.yml`

**Interfaces:**
- Consumes: los 10 secrets de Task 4, `requirements_job.txt` (ya existe, usado antes por `Dockerfile.job` para el mismo pipeline).
- Produces: ejecución de `python actualizar_todo.py` con las mismas env vars que usa localmente `actualizar_dashboard.bat`.

- [ ] **Step 1: Crear el workflow**

```yaml
name: Actualizar pipeline de tableros

on:
  workflow_dispatch: {}
  # El cron se activa recién en Task 7, una vez validado workflow_dispatch.

concurrency:
  group: actualizar-pipeline
  cancel-in-progress: false

jobs:
  actualizar:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    permissions:
      contents: read
      id-token: write   # requerido por google-github-actions/auth (WIF)

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Instalar dependencias
        run: pip install -r requirements_job.txt

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}

      - name: Correr el pipeline
        env:
          CONTABILIUM_EMAIL: ${{ secrets.CONTABILIUM_EMAIL }}
          CONTABILIUM_APIKEY: ${{ secrets.CONTABILIUM_APIKEY }}
          TOTEAT_XIU: ${{ secrets.TOTEAT_XIU }}
          TOTEAT_XIR: ${{ secrets.TOTEAT_XIR }}
          TOTEAT_XIL: ${{ secrets.TOTEAT_XIL }}
          PLACES_API_KEY: ${{ secrets.PLACES_API_KEY }}
          PLACES_ID_BARRIO_CHINO: ${{ secrets.PLACES_ID_BARRIO_CHINO }}
          PLACES_ID_MONROE: ${{ secrets.PLACES_ID_MONROE }}
          PYTHONIOENCODING: utf-8
        run: python -X utf8 actualizar_todo.py

      - name: Subir el log si falló
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: dashboard-update-log
          path: logs/dashboard_update.log
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/actualizar-pipeline.yml
git commit -m "ci: workflow de GitHub Actions para correr el pipeline diario (solo workflow_dispatch por ahora)"
```

---

### Task 6: Correr el workflow a mano y verificar que publica igual que local

**Files:** ninguno (verificación, no cambia código).

- [ ] **Step 1: Disparar el workflow manualmente**

```bash
git push
gh workflow run actualizar-pipeline.yml
```

- [ ] **Step 2: Seguir la corrida y confirmar que termina OK**

```bash
gh run watch
```

Expected: todos los pasos del job en verde. Si algún script de los que tienen fallback SA-key/ADC (`sync_catalogo_feriado.py`, `actualizar_retail.py`, `generar_preview_producto.py`, `google_reviews_sync.py`, `generar_destileria_dashboard.py`) falla autenticando, el log del step muestra cuál — ya tienen el fallback a ADC escrito (confirmado en el código actual), así que debería funcionar sin cambios; si no, es la primera señal a investigar.

- [ ] **Step 3: Verificar que los archivos en GCS se actualizaron con la corrida de GitHub Actions**

```bash
python "C:\Users\DARWIN~1\AppData\Local\Temp\claude\C--Users-Darwin-Salinas\74a04e21-5135-4646-a3ab-9bcdc83589ce\scratchpad\check_gcs_dest.py"
```

Expected: `destileria_dashboard.html` y `destileria_cbl_hwm.json` con `updated` correspondiente al horario de la corrida del workflow (no una corrida vieja).

- [ ] **Step 4: Repetir Steps 1-3 dos veces más en días distintos, confirmando cada vez que no hay banner de alerta en `/destileria`**

Sin esto no se pasa a Task 7 — el objetivo es 2-3 corridas limpias seguidas antes de activar el cron, como quedó acordado en el spec.

---

### Task 7: Activar el cron

**Files:**
- Modify: `.github/workflows/actualizar-pipeline.yml:5-7`

- [ ] **Step 1: Agregar las dos entradas de schedule**

Reemplazar:

```yaml
on:
  workflow_dispatch: {}
  # El cron se activa recién en Task 7, una vez validado workflow_dispatch.
```

por:

```yaml
on:
  workflow_dispatch: {}
  schedule:
    - cron: "30 11 * * *"   # 08:30 ART
    - cron: "0 15 * * *"    # 12:00 ART
```

- [ ] **Step 2: Commit y push**

```bash
git add .github/workflows/actualizar-pipeline.yml
git commit -m "ci: activar el cron del pipeline (08:30 y 12:00 ART) tras 3 corridas manuales limpias"
git push
```

- [ ] **Step 3: Confirmar que el próximo disparo automático corrió solo, sin intervención manual**

```bash
gh run list --workflow=actualizar-pipeline.yml --limit 3
```

Expected: una corrida con `event: schedule` (no `workflow_dispatch`) en el horario esperado.

---

### Task 8: Deshabilitar las tareas de Windows

**Files:** ninguno (configuración del Programador de Tareas de Windows).

- [ ] **Step 1: Deshabilitar (no borrar) ambas tareas**

```powershell
Disable-ScheduledTask -TaskName 'Dashboard Temple Ventas'
Disable-ScheduledTask -TaskName 'Dashboard Temple Ventas Mediodia'
```

- [ ] **Step 2: Verificar el estado**

```powershell
Get-ScheduledTask -TaskName 'Dashboard Temple Ventas','Dashboard Temple Ventas Mediodia' | Select-Object TaskName, State
```

Expected: `State: Disabled` en ambas.

- [ ] **Step 3: Confirmar al día siguiente que el tablero se actualizó igual (sin la PC corriendo el pipeline)**

Revisar `updated` de `destileria_dashboard.html` en GCS (mismo script del Task 6 Step 3) y confirmar que corresponde al horario del cron de GitHub Actions, no a una corrida local.
