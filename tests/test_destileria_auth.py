"""
tests/test_destileria_auth.py — Tests para helpers de Firestore destileria_users.
"""
import pytest
from unittest.mock import MagicMock, patch
from werkzeug.security import generate_password_hash


def _mock_db(exists=True, active=True, role="viewer", password="testpass"):
    """Retorna un mock de Firestore con un usuario destilería."""
    db = MagicMock()
    doc = MagicMock()
    doc.id = "ana@empresa.com"
    doc.exists = exists
    if exists:
        doc.to_dict.return_value = {
            "name": "Ana Rodriguez",
            "password_hash": generate_password_hash(password),
            "role": role,
            "brands": ["*"],
            "can_edit_objectives": role in ("gerencia",),
            "active": active,
            "created_at": "2026-06-17T00:00:00+00:00",
            "created_by": "darwin.salinas@temple.com.ar",
        }
    db.collection.return_value.document.return_value.get.return_value = doc
    return db


def test_get_user_exists():
    from destileria_auth import get_destileria_user
    db = _mock_db()
    user = get_destileria_user(db, "ANA@EMPRESA.COM")
    assert user is not None
    assert user["email"] == "ana@empresa.com"
    assert "password_hash" in user


def test_get_user_not_found():
    from destileria_auth import get_destileria_user
    db = _mock_db(exists=False)
    assert get_destileria_user(db, "noexiste@empresa.com") is None


def test_verify_password_correct():
    from destileria_auth import verify_destileria_password
    db = _mock_db(password="secret123")
    user = verify_destileria_password(db, "ana@empresa.com", "secret123")
    assert user is not None
    assert user["email"] == "ana@empresa.com"


def test_verify_password_wrong():
    from destileria_auth import verify_destileria_password
    db = _mock_db(password="secret123")
    assert verify_destileria_password(db, "ana@empresa.com", "wrongpass") is None


def test_verify_password_inactive_user():
    from destileria_auth import verify_destileria_password
    db = _mock_db(active=False, password="testpass")
    assert verify_destileria_password(db, "ana@empresa.com", "testpass") is None


def test_verify_password_user_not_found():
    from destileria_auth import verify_destileria_password
    db = _mock_db(exists=False)
    assert verify_destileria_password(db, "nadie@empresa.com", "pass") is None


def test_create_user_hashes_password():
    from destileria_auth import create_destileria_user
    from werkzeug.security import check_password_hash
    db = MagicMock()
    create_destileria_user(
        db, "nuevo@empresa.com", "Nuevo User", "plainpass",
        "viewer", ["bosque"], False, "darwin.salinas@temple.com.ar"
    )
    call_args = db.collection.return_value.document.return_value.set.call_args
    saved = call_args[0][0]
    assert "password_hash" in saved
    assert check_password_hash(saved["password_hash"], "plainpass")
    assert "plainpass" not in str(saved)
    assert saved["active"] is True


def test_list_users_excludes_password_hash():
    from destileria_auth import list_destileria_users
    db = MagicMock()
    doc = MagicMock()
    doc.id = "ana@empresa.com"
    doc.to_dict.return_value = {
        "name": "Ana Rodriguez",
        "password_hash": "hash_secreto",
        "role": "viewer",
        "brands": ["*"],
        "can_edit_objectives": False,
        "active": True,
    }
    db.collection.return_value.stream.return_value = [doc]
    users = list_destileria_users(db)
    assert len(users) == 1
    assert "password_hash" not in users[0]
    assert users[0]["email"] == "ana@empresa.com"


# ── Fixtures para tests de rutas ──────────────────────────────────────────

import sys


@pytest.fixture
def client():
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
            if mod in ("config", "app", "cache", "pipeline", "permissions", "destileria_auth"):
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


def test_destileria_redirects_to_login_unauthenticated(client):
    c, _ = client
    resp = c.get("/destileria")
    assert resp.status_code == 302
    assert "/destileria/login" in resp.headers["Location"]


def test_destileria_login_get_shows_form(client):
    c, _ = client
    resp = c.get("/destileria/login")
    assert resp.status_code == 200
    assert b"Ingresar" in resp.data or b"INGRESAR" in resp.data


def test_destileria_login_already_authenticated_redirects(client):
    c, _ = client
    with c.session_transaction() as sess:
        sess["dest_user"] = {"email": "ana@empresa.com", "role": "viewer"}
    resp = c.get("/destileria/login")
    assert resp.status_code == 302
    assert "/destileria" in resp.headers["Location"]


def test_destileria_login_post_valid_credentials(client):
    c, _ = client
    db = _mock_db(password="mipass")
    with patch("app._get_firestore_client", return_value=db):
        resp = c.post("/destileria/login", data={
            "email": "ana@empresa.com",
            "password": "mipass",
        })
    assert resp.status_code == 302
    assert "/destileria" in resp.headers["Location"]
    with c.session_transaction() as sess:
        assert "dest_user" in sess
        assert sess["dest_user"]["email"] == "ana@empresa.com"


def test_destileria_login_post_invalid_credentials(client):
    c, _ = client
    db = _mock_db(password="realpass")
    with patch("app._get_firestore_client", return_value=db):
        resp = c.post("/destileria/login", data={
            "email": "ana@empresa.com",
            "password": "wrongpass",
        })
    assert resp.status_code == 200
    assert b"incorrectos" in resp.data


def test_destileria_login_post_inactive_user(client):
    c, _ = client
    db = _mock_db(active=False, password="testpass")
    with patch("app._get_firestore_client", return_value=db):
        resp = c.post("/destileria/login", data={
            "email": "ana@empresa.com",
            "password": "testpass",
        })
    assert resp.status_code == 200
    assert b"incorrectos" in resp.data


def test_destileria_logout_clears_session(client):
    c, _ = client
    with c.session_transaction() as sess:
        sess["dest_user"] = {"email": "ana@empresa.com", "role": "viewer"}
    resp = c.post("/destileria/logout")
    assert resp.status_code == 302
    assert "/destileria/login" in resp.headers["Location"]
    with c.session_transaction() as sess:
        assert "dest_user" not in sess
