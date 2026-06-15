#!/usr/bin/env bash
# =============================================================================
# deploy/deploy.sh — Build and deploy Temple Bar Dashboard to Cloud Run
#
# Usage: bash deploy/deploy.sh
# Prerequisites: gcloud authenticated, Docker running, setup.sh completed
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------
PROJECT_ID="temple-bar-439715"
REGION="southamerica-east1"
SERVICE_NAME="temple-bar-dashboard"
BUCKET_NAME="temple-bar-dashboard-cache"
DASHBOARD_SA="dashboard-sa"
SCHEDULER_SA="scheduler-invoker"

# BigQuery dataset name (the one containing Ventas_Maestra, Mix_Maestro, etc.)
BQ_DATASET_ID="Corporativo"

# Cloud Run URL — known from previous deploy.
CLOUD_RUN_URL="https://temple-bar-dashboard-ossmmikgja-rj.a.run.app"

# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
DASHBOARD_SA_EMAIL="${DASHBOARD_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev"
IMAGE="${REGISTRY}/${PROJECT_ID}/dashboard/${SERVICE_NAME}:$(date +%Y%m%d-%H%M%S)"

# ---------------------------------------------------------------------------
# Resolve OAUTH_CLIENT_ID
# ---------------------------------------------------------------------------
OAUTH_CLIENT_ID="${OAUTH_CLIENT_ID:-}"
if [ -z "${OAUTH_CLIENT_ID}" ] && [ -f ".env.local" ]; then
    OAUTH_CLIENT_ID=$(grep -E '^OAUTH_CLIENT_ID=' .env.local 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)
fi
if [ -z "${OAUTH_CLIENT_ID}" ]; then
    echo "ERROR: OAUTH_CLIENT_ID not set."
    echo "  Add it to .env.local:  OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com"
    echo "  Or export it:          export OAUTH_CLIENT_ID=..."
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Build Docker image
# ---------------------------------------------------------------------------
echo ">>> Building Docker image (linux/amd64): ${IMAGE}"
docker build --platform linux/amd64 -t "${IMAGE}" "$(dirname "$0")/.."

# ---------------------------------------------------------------------------
# 2. Push to Artifact Registry
# ---------------------------------------------------------------------------
echo ">>> Authenticating with Artifact Registry..."
gcloud auth configure-docker "${REGISTRY}" --quiet

echo ">>> Pushing image..."
docker push "${IMAGE}"

# ---------------------------------------------------------------------------
# 3. Deploy to Cloud Run
# ---------------------------------------------------------------------------
echo ">>> Deploying to Cloud Run..."

gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${DASHBOARD_SA_EMAIL}" \
  --allow-unauthenticated \
  --platform=managed \
  --min-instances=0 \
  --max-instances=2 \
  --memory=512Mi \
  --concurrency=80 \
  --timeout=300 \
  --set-env-vars="\
GCP_PROJECT_ID=${PROJECT_ID},\
BQ_DATASET_ID=${BQ_DATASET_ID},\
CACHE_BUCKET=${BUCKET_NAME},\
OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID},\
SCHEDULER_SA_EMAIL=${SCHEDULER_SA_EMAIL},\
CLOUD_RUN_URL=${CLOUD_RUN_URL}" \
  --update-secrets="\
FLASK_SECRET_KEY=flask-secret-key:latest,\
OAUTH_CLIENT_SECRET=oauth-client-secret:latest"

# ---------------------------------------------------------------------------
# 4. Print result
# ---------------------------------------------------------------------------
DEPLOYED_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

echo ""
echo "======================================================================"
echo "  DEPLOYMENT COMPLETE"
echo "======================================================================"
echo ""
echo "  Service URL: ${DEPLOYED_URL}"
echo ""

if [ -z "${CLOUD_RUN_URL}" ]; then
    echo "  *** FIRST DEPLOY — two more steps required: ***"
    echo ""
    echo "  Step 5: Add redirect URI to your OAuth 2.0 credential:"
    echo "    ${DEPLOYED_URL}/auth/callback"
    echo ""
    echo "  Step 6: Update CLOUD_RUN_URL in this file, then redeploy:"
    echo "    CLOUD_RUN_URL=\"${DEPLOYED_URL}\""
    echo "    bash deploy/deploy.sh"
    echo ""
    echo "  Step 8: Create the nightly Cloud Scheduler job:"
    echo "    bash deploy/scheduler.sh"
else
    echo "  Open:  ${DEPLOYED_URL}"
fi
echo "======================================================================"
