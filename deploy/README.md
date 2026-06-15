# Temple Bar Dashboard — Deployment Guide

## Overview

Flask web app on GCP Cloud Run. Data refreshed nightly from BigQuery via Cloud Scheduler. Google OAuth login with email whitelist.

**Architecture:**
```
Browser → Cloud Run (Flask) → GCS cache (latest.json)
Cloud Scheduler → POST /api/refresh → BigQuery → GCS
```

---

## Prerequisites

- `gcloud` CLI authenticated: `gcloud auth login`
- Docker installed and running
- Python 3.12+ for local testing
- Access to GCP project `temple-bar-439715` (Editor or Owner)

---

## Step 1: One-Time GCP Setup

Run once per environment (or per new client):

```bash
cd /path/to/Claude_Cowork
bash deploy/setup.sh
```

This creates:
- Service accounts (`dashboard-sa`, `scheduler-invoker`)
- IAM bindings (BigQuery, GCS, Secret Manager)
- GCS bucket `temple-bar-dashboard-cache` in `southamerica-east1`
- `flask-secret-key` and `oauth-client-secret` in Secret Manager
- Artifact Registry repo for Docker images
- Seeds initial data cache from `processed_data.json`

---

## Step 2: Create OAuth 2.0 Credentials

1. Go to: https://console.cloud.google.com/apis/credentials?project=temple-bar-439715
2. Click **Create Credentials → OAuth 2.0 Client ID**
3. Application type: **Web application**
4. Name: `Temple Bar Dashboard`
5. Authorized redirect URIs: Add a placeholder `http://localhost:8080/auth/callback`  
   *(You'll add the real Cloud Run URL in Step 5)*
6. Copy the **Client ID** and **Client Secret**

Update the secret:
```bash
echo -n "YOUR_CLIENT_SECRET" | gcloud secrets versions add oauth-client-secret --data-file=-
```

---

## Step 3: Configure Environment

Copy `.env.example` to `.env.local` and fill in:
```bash
cp .env.example .env.local
# Edit .env.local with your OAUTH_CLIENT_ID
```

Add your email to the whitelist:
```bash
echo "your.email@example.com" >> whitelist.txt
```

---

## Step 4: First Deploy (Get the Cloud Run URL)

```bash
bash deploy/deploy.sh
```

This will:
1. Build the Docker image
2. Push to Artifact Registry
3. Deploy to Cloud Run (`--no-allow-unauthenticated`)
4. Print the Cloud Run service URL

**Note the URL printed at the end** — you need it for Steps 5 and 6.

---

## Step 5: Update OAuth Redirect URI

1. Go back to GCP Console → Credentials → your OAuth 2.0 Client
2. Add to Authorized redirect URIs: `https://YOUR_CLOUD_RUN_URL/auth/callback`
3. Save

---

## Step 6: Update CLOUD_RUN_URL and Redeploy

```bash
# Edit deploy/deploy.sh — update CLOUD_RUN_URL variable
# Then redeploy:
bash deploy/deploy.sh
```

---

## Step 7: Bootstrap Data Cache

Trigger the first data refresh manually:
```bash
# Option A: gcloud scheduler (after scheduler is created)
gcloud scheduler jobs run nightly-refresh --location=southamerica-east1

# Option B: direct curl (with a valid OIDC token — easier via gcloud)
# The app will serve a 503 with "data not yet available" until the cache is seeded
```

If `processed_data.json` was present when you ran `setup.sh`, the cache was already seeded automatically.

---

## Step 8: Create Cloud Scheduler Job

```bash
bash deploy/scheduler.sh
```

This creates a nightly job that POSTs to `/api/refresh` at 03:00 ART (06:00 UTC).

---

## Step 9: Verify End-to-End

1. Open the Cloud Run URL in an incognito browser
2. You should be redirected to Google login
3. Log in with a whitelisted email
4. Dashboard should load with charts
5. Test establishment filter and CSV export on each tab
6. Check Cloud Logging for any errors:
   ```bash
   gcloud logs read --service=temple-bar-dashboard --limit=50 --format=json
   ```

---

## Day-to-Day Operations

### Add a user to the whitelist
1. Edit `whitelist.txt` — add the email on a new line
2. Redeploy: `bash deploy/deploy.sh`

### Trigger a manual data refresh
```bash
gcloud scheduler jobs run nightly-refresh --location=southamerica-east1
```

### Check refresh logs
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="temple-bar-dashboard" AND httpRequest.requestUrl:"/api/refresh"' --limit=10 --format=json
```

### Rotate FLASK_SECRET_KEY (logs all users out)
```bash
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo -n "${NEW_KEY}" | gcloud secrets versions add flask-secret-key --data-file=-
bash deploy/deploy.sh  # redeploy to pick up new version
```

---

## Multi-Client Deployment

To deploy for a second client:
1. Create a new GCP project (or reuse the same one with a different dataset)
2. Run `setup.sh` with updated `PROJECT_ID`, `BUCKET_NAME`, `REGION` variables
3. Create a new Cloud Run service pointing to the new client's BigQuery dataset
4. Set env vars: `GCP_PROJECT_ID`, `BQ_DATASET_ID`, `CACHE_BUCKET`
5. Create a separate `whitelist.txt` with the new client's emails

**Important:** Each client deployment needs its own private repository. The `whitelist.txt` is committed to the repo — never put multiple clients' whitelists in a public or shared repo.

---

## Cost Estimate

| Resource | Usage | Estimated Cost |
|----------|-------|---------------|
| Cloud Run | ~50 req/day, scale-to-zero | < $1/month |
| Cloud Scheduler | 1 job/day | Free tier |
| BigQuery | 5 queries/night, ~90-day range | < $1/month |
| GCS | 1 JSON file, ~2 MB | < $0.01/month |
| Secret Manager | 2 secrets | < $0.01/month |
| **Total** | | **~$2-5/month** |
