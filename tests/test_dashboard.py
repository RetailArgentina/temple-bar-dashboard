"""
tests/test_dashboard.py — Tests for /dashboard route rendering.

Checks that the dashboard template is served correctly when the user
is authenticated, includes expected DOM structure, and exposes the user
name from the session context.
"""
import pytest
from unittest.mock import patch


SAMPLE_DATA = {
    "ventas": [{"d": "2026-01-01", "e": "SOHO", "c": "sale_app", "t": "N", "o": 10, "v": 500000, "tk": 50000}],
    "mix": [],
    "cerv": [],
    "gin": [],
    "ferid": [],
    "last_updated": "2026-01-01T06:00:00Z",
}


@pytest.fixture
def logged_in_client(tmp_path):
    """Flask test client with an authenticated session."""
    import sys
    for mod in list(sys.modules.keys()):
        if mod in ("config", "app", "cache", "pipeline"):
            del sys.modules[mod]

    whitelist = tmp_path / "whitelist.txt"
    whitelist.write_text("test@temple.com.ar\n")

    env_vars = {
        "FLASK_SECRET_KEY": "test-secret-key-for-testing-only-x",
        "OAUTH_CLIENT_ID": "test",
        "OAUTH_CLIENT_SECRET": "test",
        "CACHE_BUCKET": "test-bucket",
        "GCP_PROJECT_ID": "test-project",
        "BQ_DATASET_ID": "test_dataset",
        "CLOUD_RUN_URL": "https://test.run.app",
        "SCHEDULER_SA_EMAIL": "scheduler@test.iam.gserviceaccount.com",
    }
    with patch.dict("os.environ", env_vars):
        with patch("pathlib.Path.__truediv__", return_value=whitelist):
            import config as cfg
            cfg.WHITELIST = frozenset(["test@temple.com.ar"])

            import app as flask_app
            flask_app.app.config["TESTING"] = True
            flask_app.app.config["WTF_CSRF_ENABLED"] = False
            flask_app.app.config["SESSION_COOKIE_SECURE"] = False
            with flask_app.app.test_client() as c:
                with c.session_transaction() as sess:
                    sess["user"] = {"email": "test@temple.com.ar", "name": "Test User"}
                yield c


# ---------------------------------------------------------------------------
# /dashboard route
# ---------------------------------------------------------------------------

def test_dashboard_returns_200_when_authenticated(logged_in_client):
    """Authenticated user → GET /dashboard returns 200."""
    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_renders_html(logged_in_client):
    """Dashboard response is HTML."""
    resp = logged_in_client.get("/dashboard")
    assert b"<!DOCTYPE html>" in resp.data or b"<!doctype html>" in resp.data.lower()


def test_dashboard_shows_user_name(logged_in_client):
    """User's name from session must appear in the rendered page."""
    resp = logged_in_client.get("/dashboard")
    assert b"Test User" in resp.data


def test_dashboard_has_loading_overlay(logged_in_client):
    """Loading overlay element must be present (JS hides it after data load)."""
    resp = logged_in_client.get("/dashboard")
    assert b"loadingOverlay" in resp.data


def test_dashboard_includes_dashboard_js(logged_in_client):
    """dashboard.js static asset must be referenced in the page."""
    resp = logged_in_client.get("/dashboard")
    assert b"dashboard.js" in resp.data


def test_dashboard_includes_dashboard_css(logged_in_client):
    """dashboard.css static asset must be referenced in the page."""
    resp = logged_in_client.get("/dashboard")
    assert b"dashboard.css" in resp.data


def test_dashboard_has_logout_form(logged_in_client):
    """Page must contain a POST logout form."""
    resp = logged_in_client.get("/dashboard")
    assert b"/logout" in resp.data
    # Logout must be a POST form, not a GET link
    assert b'method="post"' in resp.data or b"method='post'" in resp.data


def test_dashboard_has_tab_buttons(logged_in_client):
    """Five tab buttons must be present in the rendered page."""
    resp = logged_in_client.get("/dashboard")
    for tab in (b"tab-resumen", b"tab-cerv", b"tab-gin", b"tab-ferid", b"tab-mix"):
        assert tab in resp.data


def test_dashboard_has_estab_select(logged_in_client):
    """estabSelect must be present (options populated by JS)."""
    resp = logged_in_client.get("/dashboard")
    assert b"estabSelect" in resp.data


def test_dashboard_has_date_range_input(logged_in_client):
    """dateRange flatpickr input must be present."""
    resp = logged_in_client.get("/dashboard")
    assert b"dateRange" in resp.data


def test_dashboard_has_last_updated_element(logged_in_client):
    """lastUpdated element must be present (populated by JS after data load)."""
    resp = logged_in_client.get("/dashboard")
    assert b"lastUpdated" in resp.data


def test_dashboard_redirects_when_unauthenticated(tmp_path):
    """GET /dashboard without session → 302 redirect to /login."""
    import sys
    for mod in list(sys.modules.keys()):
        if mod in ("config", "app", "cache", "pipeline"):
            del sys.modules[mod]

    whitelist = tmp_path / "whitelist.txt"
    whitelist.write_text("test@temple.com.ar\n")

    env_vars = {
        "FLASK_SECRET_KEY": "test-secret-key-for-testing-only-x",
        "OAUTH_CLIENT_ID": "test",
        "OAUTH_CLIENT_SECRET": "test",
        "CACHE_BUCKET": "test-bucket",
        "CLOUD_RUN_URL": "https://test.run.app",
    }
    with patch.dict("os.environ", env_vars):
        with patch("pathlib.Path.__truediv__", return_value=whitelist):
            import config as cfg
            cfg.WHITELIST = frozenset(["test@temple.com.ar"])

            import app as flask_app
            flask_app.app.config["TESTING"] = True
            flask_app.app.config["SESSION_COOKIE_SECURE"] = False
            with flask_app.app.test_client() as c:
                resp = c.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
