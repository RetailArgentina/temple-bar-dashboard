"""
config.py — Application configuration loaded from environment variables.

All required vars are validated at import time with clear RuntimeError messages.
CLOUD_RUN_URL is optional at startup (unknown until first deploy) but validated
per-request inside the require_scheduler decorator.
"""
import os
from datetime import timedelta


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(
            f"Required environment variable '{name}' is missing or empty. "
            f"Set it in your .env file or Cloud Run service configuration."
        )
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# ---------------------------------------------------------------------------
# Required at startup
# ---------------------------------------------------------------------------
FLASK_SECRET_KEY: str = _require("FLASK_SECRET_KEY")
OAUTH_CLIENT_ID: str = _require("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET: str = _require("OAUTH_CLIENT_SECRET")
CACHE_BUCKET: str = _require("CACHE_BUCKET")

# ---------------------------------------------------------------------------
# Optional with sensible defaults
# ---------------------------------------------------------------------------
GCP_PROJECT_ID = "temple-bar-439715"
BQ_DATASET = "Corporativo"
BQ_TABLE = "vw_Ventas_Corporativo_Base"

# Not required at startup — validated per-request in require_scheduler decorator.
# An empty string here causes the decorator to return 503 immediately (safer than
# calling verify_token with an empty audience, which would skip audience validation).
CLOUD_RUN_URL: str = _optional("CLOUD_RUN_URL", "")

# ---------------------------------------------------------------------------
# Whitelist — REMOVED
# User access is now managed via Firestore collection 'users_config'.
# See permissions.py for details.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Session / cookie settings
# ---------------------------------------------------------------------------
SESSION_COOKIE_SECURE: bool = True
SESSION_COOKIE_HTTPONLY: bool = True
SESSION_COOKIE_SAMESITE: str = "Lax"
PERMANENT_SESSION_LIFETIME: timedelta = timedelta(hours=8)
