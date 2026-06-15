#!/usr/bin/env bash
# =============================================================================
# deploy/scheduler.sh — Create/update Cloud Scheduler job for nightly refresh
#
# Creates a job that POSTs to /api/refresh at 03:00 ART (06:00 UTC) every day.
# Uses an OIDC token from the scheduler-invoker SA to authenticate.
#
# Run AFTER deploy.sh with CLOUD_RUN_URL set (Step 8 in README).
# Prerequisites: gcloud authenticated, Cloud Run service deployed
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — must match deploy.sh values
# ---------------------------------------------------------------------------
PROJECT_ID="temple-bar-439715"
REGION="southamerica-east1"
SERVICE_NAME="temple-bar-dashboard"
SCHEDULER_SA="scheduler-invoker"
JOB_NAME="nightly-refresh"

# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
SCHEDULER_SA_EMAIL="${SCHEDULER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# Resolve Cloud Run URL from the live service
CLOUD_RUN_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)" 2>/dev/null || true)

if [ -z "${CLOUD_RUN_URL}" ]; then
    echo "ERROR: Could not determine Cloud Run service URL."
    echo "  Make sure the service is deployed: bash deploy/deploy.sh"
    exit 1
fi

REFRESH_URL="${CLOUD_RUN_URL}/api/refresh"
echo "  Target URL: ${REFRESH_URL}"

# ---------------------------------------------------------------------------
# 1. Grant scheduler SA permission to invoke the Cloud Run service
# ---------------------------------------------------------------------------
echo ">>> Granting run.invoker to scheduler-invoker SA..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${SCHEDULER_SA_EMAIL}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 2. Create or update the scheduler job
# ---------------------------------------------------------------------------
echo ">>> Configuring Cloud Scheduler job '${JOB_NAME}'..."

# Try to create; if it already exists, update it instead
if gcloud scheduler jobs describe "${JOB_NAME}" \
     --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then

    echo "  Job exists — updating..."
    gcloud scheduler jobs update http "${JOB_NAME}" \
      --location="${REGION}" \
      --schedule="0 6 * * *" \
      --time-zone="UTC" \
      --uri="${REFRESH_URL}" \
      --http-method=POST \
      --oidc-service-account-email="${SCHEDULER_SA_EMAIL}" \
      --oidc-token-audience="${CLOUD_RUN_URL}" \
      --attempt-deadline=300s \
      --project="${PROJECT_ID}"
else
    echo "  Creating job..."
    gcloud scheduler jobs create http "${JOB_NAME}" \
      --location="${REGION}" \
      --schedule="0 6 * * *" \
      --time-zone="UTC" \
      --uri="${REFRESH_URL}" \
      --http-method=POST \
      --oidc-service-account-email="${SCHEDULER_SA_EMAIL}" \
      --oidc-token-audience="${CLOUD_RUN_URL}" \
      --attempt-deadline=300s \
      --project="${PROJECT_ID}"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "  SCHEDULER CONFIGURED"
echo "======================================================================"
echo ""
echo "  Job:          ${JOB_NAME}"
echo "  Schedule:     0 6 * * * UTC  (03:00 ART daily)"
echo "  Target:       ${REFRESH_URL}"
echo "  Invoker SA:   ${SCHEDULER_SA_EMAIL}"
echo ""
echo "  Test immediately:"
echo "  gcloud scheduler jobs run ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo ""
echo "  Check logs after test:"
echo "  gcloud logging read 'resource.type=\"cloud_run_revision\" AND httpRequest.requestUrl:\"/api/refresh\"' --limit=10 --project=${PROJECT_ID}"
echo "======================================================================"
