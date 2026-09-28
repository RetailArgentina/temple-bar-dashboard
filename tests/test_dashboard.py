"""
tests/test_dashboard.py — Tests for /dashboard route.

/dashboard sirve el HTML pre-generado desde GCS (super_dashboard_temple.html),
con caché en memoria de 5 min y un banner opcional si existe
feriado_sync_alert.json. Todas las llamadas a GCS están mockeadas.
"""
import json

import pytest
from unittest.mock import MagicMock, patch


DASHBOARD_HTML = "<!DOCTYPE html><html><head></head><body><div id=\"app\">Tablero Temple</div></body></html>"


class FakeGCS:
    """Mock de storage.Client que resuelve blobs por nombre."""

    def __init__(self):
        self.dashboard_html = DASHBOARD_HTML
        self.dashboard_error = None
        self.alert = None  # dict → feriado_sync_alert.json existe
        self.dashboard_downloads = 0
        self.client = MagicMock()
        self.client.bucket.return_value.blob.side_effect = self._blob

    def _blob(self, name):
        blob = MagicMock()
        if name == "super_dashboard_temple.html":
            def download(encoding=None):
                self.dashboard_downloads += 1
                if self.dashboard_error:
                    raise self.dashboard_error
                return self.dashboard_html
            blob.download_as_text.side_effect = download
        elif name == "feriado_sync_alert.json":
            blob.exists.return_value = self.alert is not None
            blob.download_as_text.return_value = json.dumps(self.alert or {})
        else:
            raise AssertionError(f"blob inesperado: {name}")
        return blob


@pytest.fixture
def gcs():
    return FakeGCS()


@pytest.fixture
def logged_in_client(tmp_path, gcs):
    """Flask test client with an authenticated session and mocked GCS."""
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
            with patch.object(flask_app.storage, "Client", return_value=gcs.client):
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


def test_dashboard_serves_html_from_gcs(logged_in_client, gcs):
    """El body es exactamente el HTML del blob en GCS (sin banner)."""
    resp = logged_in_client.get("/dashboard")
    assert resp.data.decode("utf-8") == DASHBOARD_HTML
    gcs.client.bucket.assert_any_call("test-bucket")


def test_dashboard_headers_are_html_no_cache(logged_in_client):
    """Content-Type HTML y sin caché de navegador."""
    resp = logged_in_client.get("/dashboard")
    assert resp.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "no-store" in resp.headers["Cache-Control"]


def test_dashboard_returns_503_when_gcs_fails_and_no_cache(logged_in_client, gcs):
    """GCS caído y sin HTML en memoria → 503."""
    gcs.dashboard_error = ConnectionError("GCS down")
    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 503
    assert "temporalmente no disponible" in resp.data.decode("utf-8")


def test_dashboard_uses_memory_cache_within_ttl(logged_in_client, gcs):
    """Dos requests dentro del TTL → una sola descarga de GCS."""
    logged_in_client.get("/dashboard")
    logged_in_client.get("/dashboard")
    assert gcs.dashboard_downloads == 1


def test_dashboard_serves_stale_html_when_gcs_fails_after_ttl(logged_in_client, gcs):
    """TTL vencido + GCS caído → sigue sirviendo el HTML viejo en memoria."""
    import app as flask_app
    logged_in_client.get("/dashboard")
    flask_app._dash_cache["ts"] = 0.0  # fuerza refresh
    gcs.dashboard_error = ConnectionError("GCS down")

    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.data.decode("utf-8") == DASHBOARD_HTML


def test_dashboard_refreshes_html_after_ttl(logged_in_client, gcs):
    """TTL vencido → vuelve a leer GCS y sirve la versión nueva."""
    import app as flask_app
    logged_in_client.get("/dashboard")
    flask_app._dash_cache["ts"] = 0.0
    gcs.dashboard_html = DASHBOARD_HTML.replace("Tablero Temple", "Tablero v2")

    resp = logged_in_client.get("/dashboard")
    assert b"Tablero v2" in resp.data
    assert gcs.dashboard_downloads == 2


def test_dashboard_injects_feriado_alert_banner(logged_in_client, gcs):
    """feriado_sync_alert.json presente → banner insertado después de <body>."""
    gcs.alert = {"reason": "faltan 12 órdenes", "checked_at": "2026-09-01"}
    html = logged_in_client.get("/dashboard").data.decode("utf-8")
    assert "<body><div" in html
    assert "faltan 12 órdenes" in html
    assert "2026-09-01" in html


def test_dashboard_alert_banner_escapes_html(logged_in_client, gcs):
    """El reason del alert no puede inyectar tags."""
    gcs.alert = {"reason": "<script>alert(1)</script>", "checked_at": "x"}
    html = logged_in_client.get("/dashboard").data.decode("utf-8")
    assert "<script>alert(1)" not in html
    assert "&lt;script>" in html


def test_dashboard_alert_read_failure_does_not_break_page(logged_in_client, gcs):
    """Error leyendo el alert es best-effort: la página sale igual, sin banner."""
    gcs.alert = {"reason": "x"}
    original = gcs._blob

    def failing_blob(name):
        if name == "feriado_sync_alert.json":
            raise ConnectionError("GCS down")
        return original(name)

    gcs.client.bucket.return_value.blob.side_effect = failing_blob
    resp = logged_in_client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.data.decode("utf-8") == DASHBOARD_HTML


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
