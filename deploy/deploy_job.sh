#!/usr/bin/env bash
# =============================================================================
# deploy/deploy_job.sh — Deploy the dashboard refresh Cloud Run Job
#
# This script:
#   1. Grants the dashboard-sa Service Account the necessary permissions
#   2. Builds the Docker image using Cloud Build (no Docker needed locally)
#   3. Creates/updates the Cloud Run Job
#   4. Creates/updates the Cloud Scheduler job (daily at 03:00 ART)
#
# Run from the project root:
#   cd "C:\Users\Darwin Salinas\Claude_Cowork"
#   bash deploy/deploy_job.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - setup.sh already run at least once (creates bucket, SAs, Artifact Registry)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ID="temple-bar-439715"
REGION="southamerica-east1"
JOB_NAME="dashboard-refresh-job"
DASHBOARD_SA="dashboard-sa"
SCHEDULER_SA="scheduler-invoker"
BUCKET_NAME="temple-bar-dashboard-cache"

# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
DASHBOARD_SA_EMAIL="${DASHBOARD_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev"
IMAGE="${REGISTRY}/${PROJECT_ID}/dashboard/${JOB_NAME}:latest"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Temple Bar — Cloud Run Job Setup                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# 1. Ensure required APIs are enabled
# ---------------------------------------------------------------------------
echo ">>> [1/5] Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 2. Grant dashboard-sa permission to make GCS objects public
# ---------------------------------------------------------------------------
echo ">>> [2/5] Granting Storage Object Admin to dashboard-sa on bucket..."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${DASHBOARD_SA_EMAIL}" \
  --role="roles/storage.objectAdmin" 2>/dev/null || echo "  (already set, skipping)"

# Also allow allUsers to read objects (so the public URL works)
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="allUsers" \
  --role="roles/storage.objectViewer" 2>/dev/null || echo "  (public read already set, skipping)"

# ---------------------------------------------------------------------------
# 3. Build Docker image with Cloud Build (no local Docker needed)
# ---------------------------------------------------------------------------
echo ">>> [3/5] Building image with Cloud Build: ${IMAGE}"
# Uses Dockerfile.job specifically (not the web app's Dockerfile)
gcloud builds submit . \
  --dockerfile=Dockerfile.job \
  --tag="${IMAGE}" \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 4. Create or update the Cloud Run Job
# ---------------------------------------------------------------------------
echo ">>> [4/5] Deploying Cloud Run Job '${JOB_NAME}'..."

if gcloud run jobs describe "${JOB_NAME}" \
     --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "  Job exists — updating..."
  gcloud run jobs update "${JOB_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --service-account="${DASHBOARD_SA_EMAIL}" \
    --task-timeout=600 \
    --memory=512Mi \
    --project="${PROJECT_ID}"
else
  echo "  Creating job..."
  gcloud run jobs create "${JOB_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --service-account="${DASHBOARD_SA_EMAIL}" \
    --task-timeout=600 \
    --memory=512Mi \
    --project="${PROJECT_ID}"
fi

# ---------------------------------------------------------------------------
# 5. Create or update Cloud Scheduler (daily at 03:00 ART = 06:00 UTC)
# ---------------------------------------------------------------------------
echo ">>> [5/5] Configuring Cloud Scheduler (daily 03:00 ART)..."

# Grant scheduler-invoker permission to run the Cloud Run Job
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SCHEDULER_SA_EMAIL}" \
  --role="roles/run.invoker" \
  --condition=None 2>/dev/null || true

JOB_EXECUTION_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "${JOB_NAME}-scheduler" \
     --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "  Scheduler exists — updating..."
  gcloud scheduler jobs update http "${JOB_NAME}-scheduler" \
    --location="${REGION}" \
    --schedule="30 11 * * *" \
    --time-zone="UTC" \
    --uri="${JOB_EXECUTION_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SCHEDULER_SA_EMAIL}" \
    --attempt-deadline=660s \
    --project="${PROJECT_ID}"
else
  echo "  Creating scheduler..."
  gcloud scheduler jobs create http "${JOB_NAME}-scheduler" \
    --location="${REGION}" \
    --schedule="30 11 * * *" \
    --time-zone="UTC" \
    --uri="${JOB_EXECUTION_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SCHEDULER_SA_EMAIL}" \
    --attempt-deadline=660s \
    --project="${PROJECT_ID}"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
DASHBOARD_URL="https://storage.googleapis.com/${BUCKET_NAME}/super_dashboard_temple.html"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✓ Cloud Run Job deployed successfully!                     ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Job:        ${JOB_NAME}"
echo "║  Schedule:   Todos los días a las 08:30 ART (11:30 UTC)"
echo "║  Dashboard:  ${DASHBOARD_URL}"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Para probar ahora mismo:"
echo "║  gcloud run jobs execute ${JOB_NAME} \\"
echo "║    --region=${REGION} --project=${PROJECT_ID} --wait"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  El dashboard actualizado estará disponible en:"
echo "  ${DASHBOARD_URL}"
echo ""
