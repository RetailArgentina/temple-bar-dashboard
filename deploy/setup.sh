#!/usr/bin/env bash
# =============================================================================
# deploy/setup.sh — One-time GCP resource creation for Temple Bar Dashboard
#
# Run ONCE before first deployment. Idempotent: safe to re-run.
# Prerequisites: gcloud authenticated with owner/editor on temple-bar-439715
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these if deploying for a different client
# ---------------------------------------------------------------------------
PROJECT_ID="temple-bar-439715"
REGION="southamerica-east1"
BUCKET_NAME="temple-bar-dashboard-cache"
DASHBOARD_SA="dashboard-sa"
SCHEDULER_SA="scheduler-invoker"

# ---------------------------------------------------------------------------
# 1. Enable required APIs
# ---------------------------------------------------------------------------
echo ">>> Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 2. Create service accounts
# ---------------------------------------------------------------------------
echo ">>> Creating service accounts..."

# Dashboard SA (used by Cloud Run container)
gcloud iam service-accounts create "${DASHBOARD_SA}" \
  --display-name="Temple Bar Dashboard (Cloud Run)" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  dashboard-sa already exists, skipping"

# Scheduler SA (used by Cloud Scheduler to invoke Cloud Run)
gcloud iam service-accounts create "${SCHEDULER_SA}" \
  --display-name="Temple Bar Scheduler Invoker" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  scheduler-invoker already exists, skipping"

DASHBOARD_SA_EMAIL="${DASHBOARD_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "  Dashboard SA:  ${DASHBOARD_SA_EMAIL}"
echo "  Scheduler SA:  ${SCHEDULER_SA_EMAIL}"

# ---------------------------------------------------------------------------
# 3. Grant BigQuery permissions to dashboard SA
# ---------------------------------------------------------------------------
echo ">>> Granting BigQuery permissions..."

# dataViewer: SELECT on all tables in the project
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DASHBOARD_SA_EMAIL}" \
  --role="roles/bigquery.dataViewer" \
  --condition=None

# jobUser: required to actually execute queries (even read-only)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DASHBOARD_SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None

# ---------------------------------------------------------------------------
# 4. Create GCS bucket for dashboard data cache
# ---------------------------------------------------------------------------
echo ">>> Creating GCS bucket ${BUCKET_NAME}..."
gcloud storage buckets create "gs://${BUCKET_NAME}" \
  --location="${REGION}" \
  --default-storage-class=STANDARD \
  --uniform-bucket-level-access \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  Bucket already exists, skipping"

# Grant dashboard SA full object access on this specific bucket
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${DASHBOARD_SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# ---------------------------------------------------------------------------
# 5. Create Secret Manager secrets
# ---------------------------------------------------------------------------
echo ">>> Creating secrets in Secret Manager..."

# FLASK_SECRET_KEY — generate a strong random key
PYTHON_CMD=$(which python3 2>/dev/null || which python 2>/dev/null)
FLASK_KEY=$("${PYTHON_CMD}" -c "import secrets; print(secrets.token_hex(32))")
echo -n "${FLASK_KEY}" | gcloud secrets create flask-secret-key \
  --data-file=- \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  flask-secret-key already exists, skipping"

# OAUTH_CLIENT_SECRET — placeholder; replace after creating OAuth 2.0 credentials in GCP Console
# See deploy/README.md for instructions
echo -n "REPLACE_WITH_OAUTH_CLIENT_SECRET" | gcloud secrets create oauth-client-secret \
  --data-file=- \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  oauth-client-secret already exists, skipping"

# Grant dashboard SA access to read these secrets
gcloud secrets add-iam-policy-binding flask-secret-key \
  --member="serviceAccount:${DASHBOARD_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}"

gcloud secrets add-iam-policy-binding oauth-client-secret \
  --member="serviceAccount:${DASHBOARD_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 6. Seed initial GCS cache from processed_data.json
# ---------------------------------------------------------------------------
echo ">>> Seeding initial data cache..."
SEED_SCRIPT=$(cat <<'PYTHON'
import json, sys, pathlib

src = pathlib.Path("processed_data.json")
if not src.exists():
    print("  processed_data.json not found — skipping seed. Run deploy/deploy.sh --bootstrap after first deploy.")
    sys.exit(0)

data = json.loads(src.read_text())

# Rename keys to match API response schema
if "cerveza" in data:
    data["cerv"] = data.pop("cerveza")
if "feriado" in data:
    data["ferid"] = data.pop("feriado")

# Add last_updated timestamp
data["last_updated"] = "2026-04-08T00:00:00Z"

# Write seed file
import tempfile
out = pathlib.Path(tempfile.gettempdir()) / "latest.json"
out.write_text(json.dumps(data))
print(f"  Seed file ready: {out} ({out.stat().st_size // 1024} KB)")
PYTHON
)

"${PYTHON_CMD}" -c "${SEED_SCRIPT}" && \
  gcloud storage cp /tmp/latest.json "gs://${BUCKET_NAME}/latest.json" && \
  echo "  Cache seeded: gs://${BUCKET_NAME}/latest.json" || \
  echo "  Cache seed skipped (see message above)"

# ---------------------------------------------------------------------------
# 7. Create Artifact Registry repo for Docker images
# ---------------------------------------------------------------------------
echo ">>> Creating Artifact Registry repository..."
gcloud artifacts repositories create dashboard \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Temple Bar Dashboard container images" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  Artifact Registry repo already exists, skipping"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "  GCP SETUP COMPLETE"
echo "======================================================================"
echo ""
echo "  Next steps:"
echo "  1. Create OAuth 2.0 credentials in GCP Console:"
echo "     https://console.cloud.google.com/apis/credentials?project=${PROJECT_ID}"
echo "     - Application type: Web application"
echo "     - Authorized redirect URIs: https://YOUR_CLOUD_RUN_URL/auth/callback"
echo "     (URL will be known after first deploy — add it afterwards)"
echo ""
echo "  2. Update the oauth-client-secret in Secret Manager:"
echo "     gcloud secrets versions add oauth-client-secret --data-file=<(echo -n 'YOUR_SECRET')"
echo ""
echo "  3. Update .env.example with your OAUTH_CLIENT_ID"
echo ""
echo "  4. Run: bash deploy/deploy.sh"
echo ""
echo "  Dashboard SA:  ${DASHBOARD_SA_EMAIL}"
echo "  Scheduler SA:  ${SCHEDULER_SA_EMAIL}"
echo "  GCS Bucket:    gs://${BUCKET_NAME}"
echo "======================================================================"
