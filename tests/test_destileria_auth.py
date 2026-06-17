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
