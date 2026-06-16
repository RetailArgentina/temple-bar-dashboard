"""
app.py — Temple Bar Analytics Dashboard
Flask web application on GCP Cloud Run.

Routes:
  /health            — Cloud Run health probe (no auth)
  /login             — Start Google OAuth flow
  /auth/callback     — OAuth callback, validates whitelist
  /logout            — POST only, CSRF-protected, clears session
  /denied            — 403 page for non-whitelisted accounts
  /api/data          — Serves cached dashboard JSON (@login_required)
  /api/refresh       — Nightly BigQuery refresh (@require_scheduler)
  /dashboard         — Main dashboard HTML (@login_required)
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import wraps

import anthropic
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask, abort, jsonify, redirect, render_template,
    request, session, url_for,
)
from flask_wtf.csrf import CSRFProtect
from google.cloud import bigquery, firestore, storage
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import permissions
from whatsapp_agent import get_user, get_session, save_session, run_agent
from weekly_report import run_weekly_report

# In-memory cache for the dashboard HTML (avoids hitting GCS on every request)
_dash_cache: dict = {"html": None, "ts": 0.0}
_DASH_CACHE_TTL = 300  # seconds — refreshes at most every 5 min

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY
app.config["SESSION_COOKIE_SECURE"] = config.SESSION_COOKIE_SECURE
app.config["SESSION_COOKIE_HTTPONLY"] = config.SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = config.SESSION_COOKIE_SAMESITE
app.config["PERMANENT_SESSION_LIFETIME"] = config.PERMANENT_SESSION_LIFETIME
app.config["WTF_CSRF_TIME_LIMIT"] = None  # CSRF token lifetime = session lifetime

csrf = CSRFProtect(app)
bq_client = bigquery.Client(project=config.GCP_PROJECT_ID)

# Firestore client (lazy singleton for permissions)
_fs_client = None

def _get_firestore_client():
    global _fs_client
    if _fs_client is None:
        _fs_client = firestore.Client()
    return _fs_client

# ---------------------------------------------------------------------------
# OAuth (authlib)
# ---------------------------------------------------------------------------
oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=config.OAUTH_CLIENT_ID,
    client_secret=config.OAUTH_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Redirect HTML routes to /login; return 401 JSON for API routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def require_superadmin(f):
    """Only allow superadmin users."""
    @wraps(f)
    def decorated_sa(*args, **kwargs):
        user = session.get("user")
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        if user.get("role") != "superadmin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "forbidden"}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated_sa


def require_scheduler(f):
    """
    Verify that /api/refresh was called by Cloud Scheduler via OIDC token.

    Two-layer defence:
      1. Cloud Run IAM (roles/run.invoker on scheduler-invoker SA) — infra layer
      2. In-process OIDC token verification — defence-in-depth

    Returns 503 if CLOUD_RUN_URL is not configured (prevents audience-less
    token verification which would accept any valid Google OIDC token).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        if not config.CLOUD_RUN_URL:
            logger.error(
                "/api/refresh called but CLOUD_RUN_URL is not configured. "
                "Set CLOUD_RUN_URL env var after first deploy."
            )
            return jsonify({"error": "service not fully configured"}), 503

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing authorization header"}), 401

        token = auth_header.split(" ", 1)[1]
        try:
            claims = id_token.verify_token(
                token,
                google_requests.Request(),
                audience=config.CLOUD_RUN_URL,
            )
        except Exception as exc:
            logger.warning("OIDC token verification failed: %s", exc)
            return jsonify({"error": "invalid token"}), 401

        expected_email = config.SCHEDULER_SA_EMAIL
        if expected_email and claims.get("email") != expected_email:
            logger.warning(
                "Scheduler SA email mismatch: expected=%s got=%s",
                expected_email,
                claims.get("email"),
            )
            return jsonify({"error": "forbidden"}), 403

        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Health check (no auth — used by Cloud Run health probes)
# ---------------------------------------------------------------------------
@app.route("/health")
@csrf.exempt
def health():
    return {"status": "ok"}, 200


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login")
def login():
    prompt = request.args.get("prompt", "")
    reason = request.args.get("reason", "")
    callback_url = url_for("auth_callback", _external=True)
    extra_params = {}
    if prompt == "select_account":
        extra_params["prompt"] = "select_account"
    return oauth.google.authorize_redirect(callback_url, **extra_params)


@app.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    user = token.get("userinfo")

    if not user:
        return redirect(url_for("login"))

    email = user.get("email", "").lower()

    # Look up permissions in Firestore
    db = _get_firestore_client()
    perms = permissions.get_user_permissions(db, email)

    if perms is None:
        logger.warning("Access denied for %s — not in users_config", email)
        return redirect(url_for("denied") + f"?email={email}")

    session["user"] = {
        "email": email,
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "role": perms.get("role", "viewer"),
        "brands": perms.get("brands", []),
        "can_edit_objectives": perms.get("can_edit_objectives", False),
    }
    session.permanent = True
    return redirect(url_for("dashboard"))

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/denied")
def denied():
    # Email passed as query param when linked from denied.html try-another-account
    email = request.args.get("email", "")
    return render_template("denied.html", email=email), 403


# ---------------------------------------------------------------------------
# API: data
# ---------------------------------------------------------------------------
@app.route("/api/data")
@login_required
def api_data():
    query = """
        SELECT
            Fecha AS fecha,
            Marca,
            SUM(Facturacion) AS facturacion,
            COUNT(DISTINCT Orden) AS ordenes
        FROM `temple-bar-439715.Corporativo.vw_Ventas_Corporativo_Base`
        WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """

    try:
        rows = bq_client.query(query).result()

        data = []
        for row in rows:
            data.append({
                "fecha": row.fecha.isoformat() if row.fecha else None,
                "marca": row.Marca,
                "facturacion": float(row.facturacion or 0),
                "ordenes": int(row.ordenes or 0),
            })

        return jsonify({
            "ok": True,
            "rows": data
        }), 200

    except Exception as e:
        logger.exception("Error consultando BigQuery en /api/data")
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ---------------------------------------------------------------------------
# API: refresh (triggered by Cloud Scheduler)
# ---------------------------------------------------------------------------

@app.route("/api/refresh", methods=["POST"])
@require_scheduler
@csrf.exempt
def api_refresh():
    import pipeline
    import cache
    from google.cloud import bigquery
    from datetime import date, timedelta

    desde = (date.today() - timedelta(days=90)).isoformat()
    hasta = date.today().isoformat()

    logger.info("Starting BigQuery refresh: %s → %s", desde, hasta)

    bq_client = bigquery.Client(project=config.GCP_PROJECT_ID)
    try:
        data = pipeline.fetch_data(bq_client, desde, hasta)
    except Exception as exc:
        logger.error("BigQuery fetch failed: %s", exc)
        return jsonify({"error": "bigquery fetch failed", "detail": str(exc)}), 500

    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    total_records = sum(len(v) for v in data.values() if isinstance(v, list))
    logger.info("Fetched %d records, writing to GCS cache", total_records)

    try:
        cache.write_cache(data)
    except Exception as exc:
        logger.error("GCS write failed: %s", exc)
        return jsonify({"error": "cache write failed", "detail": str(exc)}), 500

    logger.info("Refresh complete: %d records, last_updated=%s", total_records, data["last_updated"])
    return jsonify({"status": "ok", "records": total_records, "last_updated": data["last_updated"]})

# ---------------------------------------------------------------------------
# Dashboard — sirve el HTML pre-generado desde GCS (con caché en memoria)
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    global _dash_cache
    now = time.time()
    if _dash_cache["html"] is None or now - _dash_cache["ts"] > _DASH_CACHE_TTL:
        try:
            gcs = storage.Client()
            blob = gcs.bucket(config.CACHE_BUCKET).blob("super_dashboard_temple.html")
            _dash_cache["html"] = blob.download_as_text(encoding="utf-8")
            _dash_cache["ts"] = now
            logger.info("Dashboard HTML refreshed from GCS")
        except Exception as exc:
            logger.error("Error reading dashboard from GCS: %s", exc)
            if _dash_cache["html"] is None:
                return "Dashboard temporalmente no disponible. Intentá de nuevo en unos minutos.", 503
    return _dash_cache["html"], 200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }


# ---------------------------------------------------------------------------
# Destileria dashboard — sirve HTML desde GCS con inyeccion de permisos
# ---------------------------------------------------------------------------
_dest_cache: dict = {"html": None, "ts": 0.0}

@app.route("/destileria")
@login_required
def destileria():
    global _dest_cache
    now = time.time()
    if _dest_cache["html"] is None or now - _dest_cache["ts"] > _DASH_CACHE_TTL:
        try:
            gcs = storage.Client()
            blob = gcs.bucket(config.CACHE_BUCKET).blob("destileria_dashboard.html")
            _dest_cache["html"] = blob.download_as_text(encoding="utf-8")
            _dest_cache["ts"] = now
            logger.info("Destileria HTML refreshed from GCS")
        except Exception as exc:
            logger.error("Error reading destileria from GCS: %s", exc)
            if _dest_cache["html"] is None:
                return "Tablero temporalmente no disponible.", 503

    user = session["user"]
    perms_json = json.dumps({
        "role": user["role"],
        "brands": user["brands"],
        "canEditObjectives": user["can_edit_objectives"],
    }, ensure_ascii=False)

    perms_script = f'<script>window.__USER_PERMISSIONS__={perms_json};</script>'

    # Inject cluster overrides for all users
    db = _get_firestore_client()
    overrides = permissions.list_cluster_overrides(db)
    overrides_script = ''
    if overrides:
        overrides_json = json.dumps(overrides, ensure_ascii=False)
        overrides_script = f'<script>window.__CLUSTER_OVERRIDES__={overrides_json};</script>'

    admin_link = ''
    if user["role"] == "superadmin":
        admin_link = (
            '<a href="/admin" style="position:fixed;bottom:16px;right:16px;z-index:9999;'
            'background:#2d2000;border:1px solid #c9a227;color:#c9a227;padding:8px 14px;'
            'border-radius:8px;font-size:12px;font-weight:700;text-decoration:none;'
            'font-family:system-ui,sans-serif">&#9881; Admin</a>'
        )

    html = _dest_cache["html"].replace(
        "__PERMISSIONS_INJECT__",
        perms_script + overrides_script + admin_link,
    )

    return html, 200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    }


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

@app.route("/admin")
@require_superadmin
def admin_panel():
    brands = permissions.get_available_brands()
    return render_template("admin.html", brands=brands)


@app.route("/api/admin/users", methods=["GET"])
@require_superadmin
def api_admin_list_users():
    db = _get_firestore_client()
    users = permissions.list_users(db)
    return jsonify({"ok": True, "users": users})


@app.route("/api/admin/users", methods=["POST"])
@require_superadmin
def api_admin_create_user():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "")
    role = data.get("role", "")
    brands = data.get("brands", [])

    if not email or not role:
        return jsonify({"ok": False, "error": "Email y rol son requeridos"}), 400

    db = _get_firestore_client()
    result = permissions.create_user(db, email, role, brands)
    status = 200 if result["ok"] else 400
    return jsonify(result), status


@app.route("/api/admin/users/<path:email>", methods=["PUT"])
@require_superadmin
def api_admin_update_user(email):
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    brands = data.get("brands")

    db = _get_firestore_client()
    result = permissions.update_user(db, email, role=role, brands=brands)
    status = 200 if result["ok"] else 400
    return jsonify(result), status


@app.route("/api/admin/users/<path:email>", methods=["DELETE"])
@require_superadmin
def api_admin_delete_user(email):
    actor = session["user"]["email"]
    db = _get_firestore_client()
    result = permissions.delete_user(db, email, actor_email=actor)
    status = 200 if result["ok"] else 400
    return jsonify(result), status


# ---------------------------------------------------------------------------
# Admin: Cluster management
# ---------------------------------------------------------------------------
import re as _re

_clients_parsed: dict = {"data": None, "html_id": None}


def _extract_clients_from_dashboard():
    """Extrae clientes únicos y sus clusters del JSON embebido en el dashboard."""
    global _clients_parsed
    if _dest_cache["html"] is None:
        return None

    # Avoid re-parsing if HTML hasn't changed
    html_id = id(_dest_cache["html"])
    if _clients_parsed["html_id"] == html_id and _clients_parsed["data"] is not None:
        return _clients_parsed["data"]

    match = _re.search(r'const ROWS = (\[.*?\]);\n', _dest_cache["html"], _re.DOTALL)
    if not match:
        return None

    rows = json.loads(match.group(1))
    # Build unique client → cluster + last purchase date
    client_map = {}
    for r in rows:
        nd = r.get("nd", "")
        cl = r.get("cl", "Sin clasificar")
        f = r.get("f", "")
        if nd:
            prev = client_map.get(nd)
            if prev is None or f > prev["f"]:
                client_map[nd] = {"cl": cl, "f": f}
            elif prev["cl"] == "Sin clasificar" and cl != "Sin clasificar":
                client_map[nd]["cl"] = cl

    data = sorted(
        [{"cliente": k, "cluster_bq": v["cl"], "ultima_compra": v["f"]}
         for k, v in client_map.items()],
        key=lambda x: (x["cluster_bq"], x["cliente"]),
    )
    _clients_parsed["data"] = data
    _clients_parsed["html_id"] = html_id
    return data


@app.route("/api/admin/clients", methods=["GET"])
@require_superadmin
def api_admin_clients():
    """Lista clientes únicos con su cluster actual (dashboard + overrides Firestore)."""
    # Ensure dashboard is loaded
    global _dest_cache
    if _dest_cache["html"] is None:
        try:
            gcs = storage.Client()
            blob = gcs.bucket(config.CACHE_BUCKET).blob("destileria_dashboard.html")
            _dest_cache["html"] = blob.download_as_text(encoding="utf-8")
            _dest_cache["ts"] = time.time()
        except Exception as exc:
            logger.error("Error loading dashboard for client list: %s", exc)
            return jsonify({"ok": False, "error": "Dashboard no disponible"}), 503

    base_data = _extract_clients_from_dashboard()
    if base_data is None:
        return jsonify({"ok": False, "error": "No se pudieron extraer clientes del dashboard"}), 500

    # Merge with Firestore overrides
    db = _get_firestore_client()
    overrides = permissions.list_cluster_overrides(db)

    clients = []
    clusters_set = set()
    for c in base_data:
        name = c["cliente"]
        override = overrides.get(name)
        cluster = override if override else c["cluster_bq"]
        clients.append({
            "cliente": name,
            "cluster_bq": c["cluster_bq"],
            "cluster": cluster,
            "override": override is not None,
            "ultima_compra": c.get("ultima_compra", ""),
        })
        clusters_set.add(cluster)
        clusters_set.add(c["cluster_bq"])

    clusters_set.discard("Sin clasificar")
    clusters = sorted(clusters_set)

    return jsonify({"ok": True, "clients": clients, "clusters": clusters})


@app.route("/api/admin/cluster-overrides", methods=["GET"])
@require_superadmin
def api_admin_list_overrides():
    db = _get_firestore_client()
    overrides = permissions.list_cluster_overrides(db)
    return jsonify({"ok": True, "overrides": overrides})


@app.route("/api/admin/cluster-overrides", methods=["POST"])
@require_superadmin
def api_admin_set_override():
    data = request.get_json(silent=True) or {}
    client = data.get("client", "").strip()
    cluster = data.get("cluster", "").strip()
    db = _get_firestore_client()
    result = permissions.set_cluster_override(db, client, cluster)
    status = 200 if result["ok"] else 400
    return jsonify(result), status


@app.route("/api/admin/cluster-overrides/<path:client>", methods=["DELETE"])
@require_superadmin
def api_admin_delete_override(client):
    db = _get_firestore_client()
    result = permissions.delete_cluster_override(db, client)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Helpers for WhatsApp agent endpoints
# ---------------------------------------------------------------------------

def _load_agents_config():
    """Load agents config from AGENTS_CONFIG env var (Secret Manager) or local file fallback."""
    env_config = os.environ.get("AGENTS_CONFIG")
    if env_config:
        return json.loads(env_config)
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents_config.json")
    with open(config_path) as f:
        return json.load(f)


def _get_bq_client():
    from actualizar_retail import get_bigquery_client
    return get_bigquery_client()


# ---------------------------------------------------------------------------
# WhatsApp agent endpoints
# ---------------------------------------------------------------------------

@app.route("/whatsapp/webhook", methods=["POST"])
@csrf.exempt
def whatsapp_webhook():
    """Recibe mensajes entrantes de Twilio WhatsApp."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if auth_token:
        validator = RequestValidator(auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validator.validate(request.url, request.form, signature):
            return "", 403

    from_number  = request.form.get("From", "")
    user_message = request.form.get("Body", "").strip()

    if not user_message:
        return "", 200

    config_data = _load_agents_config()
    user        = get_user(from_number, config_data)

    twilio_client = TwilioClient(
        os.environ.get("TWILIO_ACCOUNT_SID", ""),
        os.environ.get("TWILIO_AUTH_TOKEN", ""),
    )
    twilio_from = os.environ.get("TWILIO_WHATSAPP_FROM", "")

    if user is None:
        twilio_client.messages.create(
            from_=twilio_from,
            to=from_number,
            body="No tenés acceso a este agente. Contactá a Darwin.",
        )
        return "", 200

    db      = firestore.Client()
    history = get_session(db, from_number)

    anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    bq               = _get_bq_client()

    try:
        reply_text, new_history = run_agent(
            user_message=user_message,
            history=history,
            user_role=user["role"],
            bq_client=bq,
            anthropic_client=anthropic_client,
        )
    except Exception:
        logger.exception("run_agent failed for %s", from_number)
        reply_text  = "Hubo un error procesando tu consulta. Intentá de nuevo."
        new_history = history

    save_session(db, from_number, new_history, user["name"], user["role"])
    twilio_client.messages.create(from_=twilio_from, to=from_number, body=reply_text)

    return "", 200


@app.route("/whatsapp/weekly-report", methods=["POST"])
@csrf.exempt
def whatsapp_weekly_report():
    """Endpoint llamado por Cloud Scheduler cada lunes a las 8:00 hs."""
    config_data    = _load_agents_config()
    expected_token = config_data.get("scheduler_token", "")
    provided_token = request.headers.get("X-Scheduler-Token", "")

    if expected_token and provided_token != expected_token:
        return {"error": "Unauthorized"}, 403

    bq     = _get_bq_client()
    result = run_weekly_report(bq, config_data)

    return {"ok": True, "result": result}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
