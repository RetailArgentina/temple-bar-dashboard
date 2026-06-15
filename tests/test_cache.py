"""
tests/test_cache.py — Tests for GCS cache read/write operations.

All GCS calls are mocked — no real GCS calls are made.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


SAMPLE_DATA = {
    "ventas": [{"d": "2026-01-01", "e": "SOHO", "c": "sale_app", "t": "N", "o": 10, "v": 500000, "tk": 50000}],
    "mix": [{"d": "2026-01-01", "m": "Bebida", "e": "SOHO", "q": 5, "$": 100000}],
    "cerv": [{"d": "2026-01-01", "s": "Wolf IPA", "cat": "Lupulada", "e": "SOHO", "q": 3, "$": 60000}],
    "gin": [{"d": "2026-01-01", "p": "Gin Mare", "e": "SOHO", "q": 2, "$": 40000, "l": 0.5}],
    "ferid": [{"d": "2026-01-01", "p": "Empanada", "e": "SOHO", "q": 10, "$": 5000}],
    "last_updated": "2026-01-01T06:00:00Z",
}


@pytest.fixture(autouse=True)
def reset_cache_client():
    """Reset the module-level GCS client between tests."""
    import cache
    original = cache._gcs_client
    cache._gcs_client = None
    yield
    cache._gcs_client = original


@pytest.fixture
def mock_gcs(monkeypatch):
    """Patch google.cloud.storage.Client used in cache.py."""
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    with patch("cache.storage.Client", return_value=mock_client):
        yield mock_client, mock_bucket, mock_blob


# ---------------------------------------------------------------------------
# read_cache
# ---------------------------------------------------------------------------

def test_read_cache_returns_dict_on_hit(mock_gcs):
    """Happy path: blob exists → returns parsed dict."""
    _, _, mock_blob = mock_gcs
    mock_blob.exists.return_value = True
    mock_blob.download_as_text.return_value = json.dumps(SAMPLE_DATA)

    import cache
    result = cache.read_cache()

    assert result is not None
    assert "ventas" in result
    assert "cerv" in result
    assert "last_updated" in result
    assert result["ventas"][0]["e"] == "SOHO"


def test_read_cache_returns_none_when_blob_missing(mock_gcs):
    """Edge: blob does not exist → returns None (not an exception)."""
    _, _, mock_blob = mock_gcs
    mock_blob.exists.return_value = False

    import cache
    result = cache.read_cache()

    assert result is None


def test_read_cache_returns_none_on_gcs_error(mock_gcs):
    """Edge: GCS raises exception → returns None (caller handles 503)."""
    _, _, mock_blob = mock_gcs
    mock_blob.exists.side_effect = Exception("GCS connection error")

    import cache
    result = cache.read_cache()

    assert result is None


def test_read_cache_uses_correct_bucket_and_key(mock_gcs):
    """Cache reads from the configured bucket with key 'latest.json'."""
    mock_client, mock_bucket, mock_blob = mock_gcs
    mock_blob.exists.return_value = True
    mock_blob.download_as_text.return_value = json.dumps(SAMPLE_DATA)

    import cache, config
    cache.read_cache()

    mock_client.bucket.assert_called_once_with(config.CACHE_BUCKET)
    mock_bucket.blob.assert_called_once_with("latest.json")


# ---------------------------------------------------------------------------
# write_cache
# ---------------------------------------------------------------------------

def test_write_cache_uploads_json_to_gcs(mock_gcs):
    """Happy path: write_cache uploads data as JSON to the correct blob."""
    mock_client, mock_bucket, mock_blob = mock_gcs

    import cache, config
    cache.write_cache(SAMPLE_DATA)

    mock_client.bucket.assert_called_once_with(config.CACHE_BUCKET)
    mock_bucket.blob.assert_called_once_with("latest.json")
    mock_blob.upload_from_string.assert_called_once()

    call_args = mock_blob.upload_from_string.call_args
    uploaded_content = call_args[0][0]
    uploaded_data = json.loads(uploaded_content)
    assert uploaded_data["last_updated"] == "2026-01-01T06:00:00Z"
    assert "ventas" in uploaded_data


def test_write_cache_sets_content_type_json(mock_gcs):
    """write_cache must set content_type='application/json'."""
    _, _, mock_blob = mock_gcs

    import cache
    cache.write_cache(SAMPLE_DATA)

    call_kwargs = mock_blob.upload_from_string.call_args[1]
    assert call_kwargs.get("content_type") == "application/json"


def test_write_cache_raises_on_gcs_error(mock_gcs):
    """write_cache raises if GCS upload fails — caller handles the error."""
    _, _, mock_blob = mock_gcs
    mock_blob.upload_from_string.side_effect = Exception("Upload failed")

    import cache
    with pytest.raises(Exception, match="Upload failed"):
        cache.write_cache(SAMPLE_DATA)


def test_write_cache_does_not_silently_swallow_errors(mock_gcs):
    """Errors in write_cache must propagate (no silent except: pass)."""
    _, _, mock_blob = mock_gcs
    mock_blob.upload_from_string.side_effect = ConnectionError("Network error")

    import cache
    with pytest.raises(ConnectionError):
        cache.write_cache(SAMPLE_DATA)


# ---------------------------------------------------------------------------
# /api/data endpoint (integration with app.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client(tmp_path):
    """Flask test client with a session and mocked cache."""
    import sys
    for mod in list(sys.modules.keys()):
        if mod in ("config", "app", "cache"):
            del sys.modules[mod]

    whitelist = tmp_path / "whitelist.txt"
    whitelist.write_text("test@temple.com.ar\n")

    env_vars = {
        "FLASK_SECRET_KEY": "test-secret-key-for-testing-only-x",
        "OAUTH_CLIENT_ID": "test-client-id",
        "OAUTH_CLIENT_SECRET": "test-secret",
        "CACHE_BUCKET": "test-bucket",
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


def test_api_data_returns_200_with_cached_data(api_client):
    """Happy path: cache hit → /api/data returns 200 with expected keys."""
    with patch("cache.read_cache", return_value=SAMPLE_DATA):
        resp = api_client.get("/api/data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "ventas" in data
    assert "cerv" in data
    assert "ferid" in data
    assert "last_updated" in data


def test_api_data_returns_503_when_cache_empty(api_client):
    """Edge: cache returns None → /api/data returns 503."""
    with patch("cache.read_cache", return_value=None):
        resp = api_client.get("/api/data")
    assert resp.status_code == 503
    data = resp.get_json()
    assert "error" in data


def test_api_data_does_not_contain_canal_or_turno_keys(api_client):
    """API response must NOT include 'canal' or 'turno' — derived client-side."""
    with patch("cache.read_cache", return_value=SAMPLE_DATA):
        resp = api_client.get("/api/data")
    data = resp.get_json()
    assert "canal" not in data
    assert "turno" not in data
