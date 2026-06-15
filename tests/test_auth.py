"""
tests/test_auth.py — Tests for Google OAuth login flow, @login_required decorator.

Uses Flask test client with mocked OAuth and Firestore permissions.
No real Google OAuth or Firestore calls are made.
"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    """Create Flask test client with Firestore-based auth."""
    import sys

    env_vars = {
        "FLASK_SECRET_KEY": "test-secret-key-for-testing-only-x",
        "OAUTH_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        "OAUTH_CLIENT_SECRET": "test-client-secret",
        "CACHE_BUCKET": "test-bucket",
        "CLOUD_RUN_URL": "https://test.run.app",
        "SCHEDULER_SA_EMAIL": "scheduler@test.iam.gserviceaccount.com",
    }

    with patch.dict("os.environ", env_vars):
        for mod in list(sys.modules.keys()):
            if mod in ("config", "app", "cache", "pipeline", "permissions"):
                del sys.modules[mod]

        with patch("google.cloud.bigquery.Client"), \
             patch("google.cloud.firestore.Client"), \
             patch("twilio.rest.Client"), \
             patch("twilio.request_validator.RequestValidator"):
            import app as flask_app
            flask_app.app.config["TESTING"] = True
            flask_app.app.config["WTF_CSRF_ENABLED"] = False
            flask_app.app.config["SESSION_COOKIE_SECURE"] = False
            with flask_app.app.test_client() as c:
                yield c, flask_app.app


def _mock_firestore_lookup(exists=True, role="viewer", brands=None):
    """Return a mock that makes _get_firestore_client() work."""
    if brands is None:
        brands = ["*"]
    db = MagicMock()
    doc = MagicMock()
    doc.exists = exists
    if exists:
        doc.to_dict.return_value = {
            "role": role,
            "brands": brands,
            "can_edit_objectives": role in ("superadmin", "editor"),
        }
    db.collection.return_value.document.return_value.get.return_value = doc
    return db


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_check(client):
    c, _ = client
    resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


# ---------------------------------------------------------------------------
# login_required decorator — HTML routes
# ---------------------------------------------------------------------------

def test_dashboard_redirects_to_login_when_unauthenticated(client):
    """GET /dashboard without session -> 302 to /login."""
    c, app = client
    resp = c.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_root_redirects_to_dashboard(client):
    """GET / -> redirects (to /dashboard, then /login if unauthenticated)."""
    c, _ = client
    resp = c.get("/")
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# login_required decorator — API routes return 401 JSON
# ---------------------------------------------------------------------------

def test_api_data_returns_401_json_when_unauthenticated(client):
    """GET /api/data without session -> 401 JSON, not HTML redirect."""
    c, _ = client
    resp = c.get("/api/data")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data is not None, "Response must be JSON, not HTML"
    assert "error" in data
    assert data["error"] == "unauthorized"


# ---------------------------------------------------------------------------
# Auth callback — Firestore permissions lookup
# ---------------------------------------------------------------------------

def test_auth_callback_user_in_firestore_creates_session(client):
    """User found in Firestore -> session created -> 302 to /dashboard."""
    c, app = client
    mock_token = {
        "userinfo": {
            "email": "allowed@temple.com.ar",
            "name": "Allowed User",
            "picture": "https://photo.example.com/pic.jpg",
        }
    }
    mock_db = _mock_firestore_lookup(exists=True, role="viewer", brands=["bosque"])

    with patch.object(app.extensions["authlib.integrations.flask_client"].google,
                      "authorize_access_token", return_value=mock_token), \
         patch("app._get_firestore_client", return_value=mock_db):
        resp = c.get("/auth/callback")
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    with c.session_transaction() as sess:
        assert sess.get("user") is not None
        assert sess["user"]["email"] == "allowed@temple.com.ar"
        assert sess["user"]["role"] == "viewer"
        assert sess["user"]["brands"] == ["bosque"]
        assert sess["user"]["can_edit_objectives"] is False


def test_auth_callback_user_not_in_firestore_denied(client):
    """User NOT in Firestore -> redirect to /denied."""
    c, app = client
    mock_token = {
        "userinfo": {
            "email": "stranger@external.com",
            "name": "Stranger",
        }
    }
    mock_db = _mock_firestore_lookup(exists=False)

    with patch.object(app.extensions["authlib.integrations.flask_client"].google,
                      "authorize_access_token", return_value=mock_token), \
         patch("app._get_firestore_client", return_value=mock_db):
        resp = c.get("/auth/callback")
    assert resp.status_code == 302
    assert "/denied" in resp.headers["Location"]

    with c.session_transaction() as sess:
        assert sess.get("user") is None


def test_auth_callback_superadmin_gets_full_permissions(client):
    """Superadmin user gets role=superadmin and all brands in session."""
    c, app = client
    mock_token = {
        "userinfo": {
            "email": "admin@temple.com.ar",
            "name": "Admin",
        }
    }
    mock_db = _mock_firestore_lookup(exists=True, role="superadmin", brands=["*"])

    with patch.object(app.extensions["authlib.integrations.flask_client"].google,
                      "authorize_access_token", return_value=mock_token), \
         patch("app._get_firestore_client", return_value=mock_db):
        resp = c.get("/auth/callback")
    assert resp.status_code == 302

    with c.session_transaction() as sess:
        assert sess["user"]["role"] == "superadmin"
        assert sess["user"]["brands"] == ["*"]
        assert sess["user"]["can_edit_objectives"] is True


def test_auth_callback_email_is_lowercased(client):
    """Email from OAuth is normalized to lowercase before Firestore lookup."""
    c, app = client
    mock_token = {
        "userinfo": {
            "email": "ALLOWED@TEMPLE.COM.AR",
            "name": "Allowed User",
        }
    }
    mock_db = _mock_firestore_lookup(exists=True, role="viewer", brands=["*"])

    with patch.object(app.extensions["authlib.integrations.flask_client"].google,
                      "authorize_access_token", return_value=mock_token), \
         patch("app._get_firestore_client", return_value=mock_db):
        resp = c.get("/auth/callback")
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    with c.session_transaction() as sess:
        assert sess["user"]["email"] == "allowed@temple.com.ar"


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout_clears_session(client):
    """POST /logout -> session cleared -> redirect to /login."""
    c, app = client
    with c.session_transaction() as sess:
        sess["user"] = {
            "email": "allowed@temple.com.ar",
            "name": "Test",
            "role": "viewer",
            "brands": ["*"],
            "can_edit_objectives": False,
        }

    resp = c.post("/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    with c.session_transaction() as sess:
        assert sess.get("user") is None


def test_logout_get_is_not_allowed(client):
    """GET /logout must return 405 (POST only)."""
    c, _ = client
    resp = c.get("/logout")
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Denied page
# ---------------------------------------------------------------------------

def test_denied_page_accessible_without_session(client):
    """GET /denied -> 403 page rendered (no login required for this page)."""
    c, _ = client
    resp = c.get("/denied?email=stranger@example.com")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# require_superadmin decorator
# ---------------------------------------------------------------------------

def test_admin_requires_superadmin(client):
    """GET /admin with viewer role -> 403."""
    c, _ = client
    with c.session_transaction() as sess:
        sess["user"] = {
            "email": "viewer@temple.com.ar",
            "name": "Viewer",
            "role": "viewer",
            "brands": ["bosque"],
            "can_edit_objectives": False,
        }
    resp = c.get("/admin")
    assert resp.status_code == 403


def test_admin_accessible_for_superadmin(client):
    """GET /admin with superadmin role -> 200."""
    c, _ = client
    with c.session_transaction() as sess:
        sess["user"] = {
            "email": "admin@temple.com.ar",
            "name": "Admin",
            "role": "superadmin",
            "brands": ["*"],
            "can_edit_objectives": True,
        }
    resp = c.get("/admin")
    assert resp.status_code == 200


def test_admin_api_requires_superadmin(client):
    """GET /api/admin/users with viewer role -> 403 JSON."""
    c, _ = client
    with c.session_transaction() as sess:
        sess["user"] = {
            "email": "viewer@temple.com.ar",
            "name": "Viewer",
            "role": "viewer",
            "brands": ["bosque"],
            "can_edit_objectives": False,
        }
    resp = c.get("/api/admin/users")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


# ---------------------------------------------------------------------------
# Destileria route
# ---------------------------------------------------------------------------

def test_destileria_requires_login(client):
    """GET /destileria without session -> 302 to /login."""
    c, _ = client
    resp = c.get("/destileria")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
