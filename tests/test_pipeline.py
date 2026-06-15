"""
tests/test_pipeline.py — Tests for BigQuery data pipeline.

All BigQuery calls are mocked — no real BQ calls are made.
Focuses on key renames, data shape, and that old keys ('cerveza', 'feriado')
do not appear in the output.
"""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(**kwargs):
    """Create a mock BigQuery Row with attribute access."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _make_date(s: str):
    """Parse YYYY-MM-DD to a date object (simulates BigQuery fecha field)."""
    d = date.fromisoformat(s)
    mock_date = MagicMock()
    mock_date.strftime.return_value = s
    return mock_date


def _make_bq_client(results_by_key: dict) -> MagicMock:
    """
    Create a mock BigQuery client that returns different rows per table query.
    Maps query key to list of mock rows (matched by SQL substring).
    """
    client = MagicMock()

    def query_side_effect(sql):
        job = MagicMock()
        for key, rows in results_by_key.items():
            if key in sql.lower() or _TABLES_LOWER.get(key, "") in sql.lower():
                job.result.return_value = iter(rows)
                return job
        job.result.return_value = iter([])
        return job

    client.query.side_effect = query_side_effect
    return client


# Map pipeline output keys to table name fragments for query matching
_TABLES_LOWER = {
    "ventas": "ventas_maestra",
    "mix": "mix_maestro",
    "cerv": "cerveza_maestro",
    "gin": "gin_maestro",
    "ferid": "feriado_maestro",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test")
    monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("BQ_DATASET_ID", "test_dataset")


def _ventas_row():
    r = MagicMock()
    r.fecha = _make_date("2026-01-15")
    r.Establecimiento = "SOHO"
    r.Canal = "sale_app"
    r.Turno = "N"
    r.ordenes = 10
    r.ventas = 500000
    r.ticket = 50000
    return r

def _mix_row():
    r = MagicMock()
    r.fecha = _make_date("2026-01-15")
    r.Mix = "Bebida"
    r.Establecimiento = "SOHO"
    r.cantidad = 5
    r.dinero = 100000
    return r

def _cerv_row():
    r = MagicMock()
    r.fecha = _make_date("2026-01-15")
    r.Estilos = "Wolf IPA"
    r.Categoria = "Lupulada"
    r.Establecimiento = "SOHO"
    r.cantidad = 3
    r.dinero = 60000
    return r

def _gin_row():
    r = MagicMock()
    r.fecha = _make_date("2026-01-15")
    r.Producto = "Gin Mare"
    r.Establecimiento = "SOHO"
    r.cantidad = 2
    r.dinero = 40000
    r.litros = 0.5
    return r

def _ferid_row():
    r = MagicMock()
    r.fecha = _make_date("2026-01-15")
    r.Producto = "Empanada"
    r.Establecimiento = "SOHO"
    r.cantidad = 10
    r.dinero = 5000
    return r


# ---------------------------------------------------------------------------
# Key rename correctness
# ---------------------------------------------------------------------------

def test_fetch_data_output_keys_are_correct():
    """Output must have exactly ventas, mix, cerv, gin, ferid — no old names."""
    import pipeline

    client = MagicMock()
    job = MagicMock()

    # Return one row per query
    call_count = [0]
    rows_by_call = [
        [_ventas_row()],
        [_mix_row()],
        [_cerv_row()],
        [_gin_row()],
        [_ferid_row()],
    ]

    def side_effect(sql):
        j = MagicMock()
        idx = call_count[0]
        j.result.return_value = iter(rows_by_call[idx] if idx < len(rows_by_call) else [])
        call_count[0] += 1
        return j

    client.query.side_effect = side_effect

    result = pipeline.fetch_data(client, "2026-01-01", "2026-01-31")

    assert set(result.keys()) == {"ventas", "mix", "cerv", "gin", "ferid"}


def test_fetch_data_does_not_contain_old_key_cerveza():
    """'cerveza' must NOT appear in output — renamed to 'cerv'."""
    import pipeline

    client = MagicMock()
    job = MagicMock()
    job.result.return_value = iter([])
    client.query.return_value = job

    result = pipeline.fetch_data(client, "2026-01-01", "2026-01-31")

    assert "cerveza" not in result
    assert "cerv" in result


def test_fetch_data_does_not_contain_old_key_feriado():
    """'feriado' must NOT appear in output — renamed to 'ferid'."""
    import pipeline

    client = MagicMock()
    job = MagicMock()
    job.result.return_value = iter([])
    client.query.return_value = job

    result = pipeline.fetch_data(client, "2026-01-01", "2026-01-31")

    assert "feriado" not in result
    assert "ferid" in result


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------

def test_ventas_row_shape():
    """ventas rows must have keys: d, e, c, t, o, v, tk."""
    import pipeline

    client = MagicMock()
    call_count = [0]

    def side_effect(sql):
        j = MagicMock()
        if call_count[0] == 0:
            j.result.return_value = iter([_ventas_row()])
        else:
            j.result.return_value = iter([])
        call_count[0] += 1
        return j

    client.query.side_effect = side_effect
    result = pipeline.fetch_data(client, "2026-01-01", "2026-01-31")

    row = result["ventas"][0]
    assert set(row.keys()) == {"d", "e", "c", "t", "o", "v", "tk"}
    assert row["e"] == "SOHO"
    assert row["c"] == "sale_app"


def test_gin_row_has_litros_field():
    """gin rows must include 'l' (litros) field."""
    import pipeline

    client = MagicMock()
    call_count = [0]

    def side_effect(sql):
        j = MagicMock()
        if call_count[0] == 3:  # gin is 4th query
            j.result.return_value = iter([_gin_row()])
        else:
            j.result.return_value = iter([])
        call_count[0] += 1
        return j

    client.query.side_effect = side_effect
    result = pipeline.fetch_data(client, "2026-01-01", "2026-01-31")

    row = result["gin"][0]
    assert "l" in row
    assert row["l"] == 0.5


def test_fetch_data_empty_result_returns_empty_lists():
    """If BQ returns no rows, all values are empty lists (not None)."""
    import pipeline

    client = MagicMock()
    job = MagicMock()
    job.result.return_value = iter([])
    client.query.return_value = job

    result = pipeline.fetch_data(client, "2026-01-01", "2026-01-31")

    for key in ("ventas", "mix", "cerv", "gin", "ferid"):
        assert isinstance(result[key], list)
        assert len(result[key]) == 0


# ---------------------------------------------------------------------------
# /api/refresh endpoint (integration)
# ---------------------------------------------------------------------------

@pytest.fixture
def refresh_client(tmp_path):
    """Flask test client configured for testing /api/refresh."""
    import sys
    for mod in list(sys.modules.keys()):
        if mod in ("config", "app", "cache", "pipeline"):
            del sys.modules[mod]

    whitelist = tmp_path / "whitelist.txt"
    whitelist.write_text("test@temple.com.ar\n")

    env_vars = {
        "FLASK_SECRET_KEY": "x" * 32,
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
                yield c


def test_refresh_missing_auth_header_returns_401(refresh_client):
    """No Authorization header → 401."""
    resp = refresh_client.post("/api/refresh")
    assert resp.status_code == 401


def test_refresh_invalid_token_returns_401(refresh_client):
    """Invalid OIDC token → 401."""
    with patch("google.oauth2.id_token.verify_token", side_effect=Exception("bad token")):
        resp = refresh_client.post(
            "/api/refresh",
            headers={"Authorization": "Bearer invalid-token"}
        )
    assert resp.status_code == 401


def test_refresh_wrong_sa_email_returns_403(refresh_client):
    """Valid token but wrong SA email → 403."""
    with patch("google.oauth2.id_token.verify_token", return_value={"email": "wrong@sa.com"}):
        resp = refresh_client.post(
            "/api/refresh",
            headers={"Authorization": "Bearer valid-token"}
        )
    assert resp.status_code == 403


def test_refresh_bigquery_failure_returns_500_and_preserves_cache(refresh_client):
    """BQ exception → 500; existing cache must not be touched."""
    import cache

    original_data = {"ventas": [], "last_updated": "2026-01-01T00:00:00Z"}

    with patch("google.oauth2.id_token.verify_token", return_value={
        "email": "scheduler@test.iam.gserviceaccount.com"
    }):
        with patch("google.cloud.bigquery.Client") as mock_bq:
            mock_bq.return_value.query.side_effect = Exception("BQ quota exceeded")
            with patch.object(cache, "write_cache") as mock_write:
                resp = refresh_client.post(
                    "/api/refresh",
                    headers={"Authorization": "Bearer valid-token"}
                )
                # Cache must NOT be written on BQ failure
                mock_write.assert_not_called()

    assert resp.status_code == 500


def test_refresh_missing_cloud_run_url_returns_503(tmp_path):
    """CLOUD_RUN_URL not set → 503 (prevents empty-audience token verification)."""
    import sys
    for mod in list(sys.modules.keys()):
        if mod in ("config", "app", "cache", "pipeline"):
            del sys.modules[mod]

    whitelist = tmp_path / "whitelist.txt"
    whitelist.write_text("test@temple.com.ar\n")

    env_vars = {
        "FLASK_SECRET_KEY": "x" * 32,
        "OAUTH_CLIENT_ID": "test",
        "OAUTH_CLIENT_SECRET": "test",
        "CACHE_BUCKET": "test-bucket",
        "CLOUD_RUN_URL": "",  # explicitly empty
    }
    with patch.dict("os.environ", env_vars):
        with patch("pathlib.Path.__truediv__", return_value=whitelist):
            import config as cfg
            cfg.WHITELIST = frozenset(["test@temple.com.ar"])
            cfg.CLOUD_RUN_URL = ""

            import app as flask_app
            flask_app.app.config["TESTING"] = True
            flask_app.app.config["WTF_CSRF_ENABLED"] = False
            flask_app.app.config["SESSION_COOKIE_SECURE"] = False
            with flask_app.app.test_client() as c:
                resp = c.post(
                    "/api/refresh",
                    headers={"Authorization": "Bearer some-token"}
                )
    assert resp.status_code == 503
