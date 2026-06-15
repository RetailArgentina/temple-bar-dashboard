# Tablero Autogestionable — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el whitelist.txt estático por un sistema de permisos en Firestore con panel admin, migrando el tablero de destilería a Flask con filtrado de marcas por usuario.

**Architecture:** Firestore almacena usuarios con rol y marcas permitidas. Flask valida permisos en cada ruta y filtra datos server-side. Un panel `/admin` permite al superadmin gestionar usuarios. El tablero de destilería se sirve desde Flask con inyección de permisos al HTML.

**Tech Stack:** Python 3 / Flask / Firestore / Google OAuth (authlib) / BigQuery / GCS

**Spec:** `docs/superpowers/specs/2026-06-14-tablero-autogestionable-permisos-design.md`

---

## File Structure

| Archivo | Acción | Responsabilidad |
|---------|--------|-----------------|
| `permissions.py` | Crear | CRUD de Firestore `users_config`, lógica de permisos, `BRAND_FAMILIES` |
| `app.py` | Modificar | Nuevas rutas `/admin`, `/destileria`, `/api/admin/*`, refactor auth_callback |
| `config.py` | Modificar | Eliminar carga de whitelist.txt |
| `templates/admin.html` | Crear | Panel de gestión de usuarios |
| `templates/destileria.html` | Modificar | Leer `window.__USER_PERMISSIONS__` para filtrar tabs |
| `tests/test_permissions.py` | Crear | Tests del módulo permissions |
| `tests/test_admin_routes.py` | Crear | Tests de rutas admin |
| `tests/test_destileria_route.py` | Crear | Tests de ruta destilería con permisos |
| `scripts/migrate_whitelist.py` | Crear | Script one-time para migrar whitelist.txt a Firestore |

---

## Task 1: Módulo `permissions.py` — BRAND_FAMILIES y lectura de permisos

**Files:**
- Create: `permissions.py`
- Create: `tests/test_permissions.py`

- [ ] **Step 1: Escribir test de `get_available_brands()`**

```python
# tests/test_permissions.py
"""Tests for permissions module."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


def test_get_available_brands_returns_all_keys():
    from permissions import get_available_brands
    brands = get_available_brands()
    assert "bosque" in brands
    assert "feriado" in brands
    assert "cerveza" in brands
    assert "merch" in brands
    assert isinstance(brands, list)


def test_get_available_brands_is_sorted():
    from permissions import get_available_brands
    brands = get_available_brands()
    assert brands == sorted(brands)
```

- [ ] **Step 2: Correr test para verificar que falla**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py::test_get_available_brands_returns_all_keys -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'permissions'`

- [ ] **Step 3: Implementar `permissions.py` con BRAND_FAMILIES y `get_available_brands`**

```python
# permissions.py
"""
permissions.py — User permissions backed by Firestore.

Collection: users_config
Document ID: email (lowercase)
Fields: role, brands, can_edit_objectives, created_at, updated_at
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Maps brand name -> list of family prefixes from classify_familia()
BRAND_FAMILIES = {
    "bosque":  ["bosque_"],
    "feriado": ["feriado_"],
    "cerveza": ["lata_"],
    "merch":   ["merch"],
}

VALID_ROLES = ("superadmin", "editor", "viewer")


def get_available_brands():
    """Return sorted list of brand names from BRAND_FAMILIES."""
    return sorted(BRAND_FAMILIES.keys())
```

- [ ] **Step 4: Correr test para verificar que pasa**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py -v`
Expected: PASS

- [ ] **Step 5: Escribir test de `get_user_permissions()`**

Agregar a `tests/test_permissions.py`:

```python
def _mock_firestore_doc(data):
    """Helper: crea un mock de documento Firestore."""
    doc = MagicMock()
    doc.exists = data is not None
    doc.to_dict.return_value = data
    return doc


def _make_db_mock(doc_data):
    """Helper: crea un mock de Firestore client."""
    db = MagicMock()
    doc = _mock_firestore_doc(doc_data)
    db.collection.return_value.document.return_value.get.return_value = doc
    return db


def test_get_user_permissions_existing_user():
    from permissions import get_user_permissions
    db = _make_db_mock({
        "role": "viewer",
        "brands": ["bosque", "feriado"],
        "can_edit_objectives": False,
    })
    perms = get_user_permissions(db, "user@temple.com.ar")
    assert perms is not None
    assert perms["role"] == "viewer"
    assert perms["brands"] == ["bosque", "feriado"]
    assert perms["can_edit_objectives"] is False
    db.collection.assert_called_with("users_config")


def test_get_user_permissions_not_found():
    from permissions import get_user_permissions
    db = _make_db_mock(None)
    perms = get_user_permissions(db, "unknown@gmail.com")
    assert perms is None


def test_get_user_permissions_normalizes_email():
    from permissions import get_user_permissions
    db = _make_db_mock({
        "role": "viewer",
        "brands": ["bosque"],
        "can_edit_objectives": False,
    })
    get_user_permissions(db, "USER@Temple.com.ar")
    db.collection.return_value.document.assert_called_with("user@temple.com.ar")
```

- [ ] **Step 6: Implementar `get_user_permissions()`**

Agregar a `permissions.py`:

```python
COLLECTION = "users_config"


def get_user_permissions(db, email):
    """
    Fetch user permissions from Firestore.
    Returns dict with role, brands, can_edit_objectives or None if not found.
    """
    email = email.strip().lower()
    doc = db.collection(COLLECTION).document(email).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return {
        "role": data.get("role", "viewer"),
        "brands": data.get("brands", []),
        "can_edit_objectives": data.get("can_edit_objectives", False),
    }
```

- [ ] **Step 7: Correr todos los tests para verificar**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Escribir test de `resolve_brand_families()`**

Agregar a `tests/test_permissions.py`:

```python
def test_resolve_brand_families_wildcard():
    from permissions import resolve_brand_families
    prefixes = resolve_brand_families(["*"])
    assert "bosque_" in prefixes
    assert "feriado_" in prefixes
    assert "lata_" in prefixes
    assert "merch" in prefixes


def test_resolve_brand_families_specific():
    from permissions import resolve_brand_families
    prefixes = resolve_brand_families(["bosque", "feriado"])
    assert "bosque_" in prefixes
    assert "feriado_" in prefixes
    assert "lata_" not in prefixes
    assert "merch" not in prefixes


def test_resolve_brand_families_empty():
    from permissions import resolve_brand_families
    prefixes = resolve_brand_families([])
    assert prefixes == []
```

- [ ] **Step 9: Implementar `resolve_brand_families()`**

Agregar a `permissions.py`:

```python
def resolve_brand_families(brands):
    """
    Convert brand names to family prefixes for data filtering.
    ["*"] returns all prefixes. ["bosque"] returns ["bosque_"].
    """
    if not brands:
        return []
    if "*" in brands:
        prefixes = []
        for prefix_list in BRAND_FAMILIES.values():
            prefixes.extend(prefix_list)
        return prefixes
    prefixes = []
    for brand in brands:
        if brand in BRAND_FAMILIES:
            prefixes.extend(BRAND_FAMILIES[brand])
    return prefixes
```

- [ ] **Step 10: Correr tests**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py -v`
Expected: PASS (8 tests)

- [ ] **Step 11: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add permissions.py tests/test_permissions.py
git commit -m "feat: add permissions module with Firestore user lookup and brand families"
```

---

## Task 2: CRUD de usuarios en `permissions.py`

**Files:**
- Modify: `permissions.py`
- Modify: `tests/test_permissions.py`

- [ ] **Step 1: Escribir tests de `list_users()`**

Agregar a `tests/test_permissions.py`:

```python
def test_list_users():
    from permissions import list_users
    db = MagicMock()
    doc1 = MagicMock()
    doc1.id = "admin@temple.com.ar"
    doc1.to_dict.return_value = {
        "role": "superadmin",
        "brands": ["*"],
        "can_edit_objectives": True,
    }
    doc2 = MagicMock()
    doc2.id = "viewer@temple.com.ar"
    doc2.to_dict.return_value = {
        "role": "viewer",
        "brands": ["bosque"],
        "can_edit_objectives": False,
    }
    db.collection.return_value.stream.return_value = [doc1, doc2]

    users = list_users(db)
    assert len(users) == 2
    assert users[0]["email"] == "admin@temple.com.ar"
    assert users[1]["email"] == "viewer@temple.com.ar"
```

- [ ] **Step 2: Implementar `list_users()`**

Agregar a `permissions.py`:

```python
def list_users(db):
    """Return list of all users from Firestore."""
    docs = db.collection(COLLECTION).stream()
    users = []
    for doc in docs:
        data = doc.to_dict()
        data["email"] = doc.id
        users.append(data)
    return users
```

- [ ] **Step 3: Escribir tests de `create_user()` y `update_user()`**

Agregar a `tests/test_permissions.py`:

```python
def test_create_user_valid():
    from permissions import create_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = False
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = create_user(db, "new@temple.com.ar", "viewer", ["bosque"])
    assert result["ok"] is True
    doc_ref.set.assert_called_once()
    call_data = doc_ref.set.call_args[0][0]
    assert call_data["role"] == "viewer"
    assert call_data["brands"] == ["bosque"]
    assert call_data["can_edit_objectives"] is False


def test_create_user_already_exists():
    from permissions import create_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = True
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = create_user(db, "existing@temple.com.ar", "viewer", ["bosque"])
    assert result["ok"] is False
    assert "existe" in result["error"].lower()
    doc_ref.set.assert_not_called()


def test_create_user_rejects_superadmin():
    from permissions import create_user
    db = MagicMock()
    result = create_user(db, "hacker@temple.com.ar", "superadmin", ["*"])
    assert result["ok"] is False
    assert "superadmin" in result["error"].lower()


def test_create_user_rejects_invalid_role():
    from permissions import create_user
    db = MagicMock()
    result = create_user(db, "user@temple.com.ar", "admin", ["bosque"])
    assert result["ok"] is False


def test_create_user_rejects_invalid_brand():
    from permissions import create_user
    db = MagicMock()
    result = create_user(db, "user@temple.com.ar", "viewer", ["whisky"])
    assert result["ok"] is False
    assert "whisky" in result["error"]


def test_update_user():
    from permissions import update_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {"role": "viewer", "brands": ["bosque"]}
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = update_user(db, "user@temple.com.ar", role="editor", brands=["bosque", "feriado"])
    assert result["ok"] is True
    doc_ref.update.assert_called_once()
    call_data = doc_ref.update.call_args[0][0]
    assert call_data["role"] == "editor"
    assert call_data["brands"] == ["bosque", "feriado"]
    assert call_data["can_edit_objectives"] is True


def test_update_user_not_found():
    from permissions import update_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = False
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = update_user(db, "ghost@temple.com.ar", role="viewer")
    assert result["ok"] is False


def test_update_user_cannot_change_superadmin():
    from permissions import update_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {"role": "superadmin", "brands": ["*"]}
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = update_user(db, "admin@temple.com.ar", role="viewer")
    assert result["ok"] is False
    assert "superadmin" in result["error"].lower()
```

- [ ] **Step 4: Implementar `create_user()` y `update_user()`**

Agregar a `permissions.py`:

```python
def _validate_role(role):
    if role not in VALID_ROLES:
        return f"Rol invalido: '{role}'. Validos: {', '.join(VALID_ROLES)}"
    return None


def _validate_brands(brands):
    available = set(BRAND_FAMILIES.keys()) | {"*"}
    invalid = [b for b in brands if b not in available]
    if invalid:
        return f"Marcas invalidas: {', '.join(invalid)}. Validas: {', '.join(sorted(available))}"
    return None


def create_user(db, email, role, brands):
    """
    Create a new user in Firestore.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    email = email.strip().lower()

    if role == "superadmin":
        return {"ok": False, "error": "No se puede crear otro superadmin desde el panel"}

    err = _validate_role(role)
    if err:
        return {"ok": False, "error": err}

    err = _validate_brands(brands)
    if err:
        return {"ok": False, "error": err}

    doc_ref = db.collection(COLLECTION).document(email)
    if doc_ref.get().exists:
        return {"ok": False, "error": f"El usuario {email} ya existe"}

    now = datetime.now(timezone.utc)
    doc_ref.set({
        "role": role,
        "brands": brands,
        "can_edit_objectives": role in ("superadmin", "editor"),
        "created_at": now,
        "updated_at": now,
    })
    logger.info("User created: %s (role=%s, brands=%s)", email, role, brands)
    return {"ok": True}


def update_user(db, email, role=None, brands=None):
    """
    Update an existing user's role and/or brands.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    email = email.strip().lower()
    doc_ref = db.collection(COLLECTION).document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return {"ok": False, "error": f"Usuario {email} no encontrado"}

    current = doc.to_dict()
    if current.get("role") == "superadmin":
        return {"ok": False, "error": "No se puede modificar al superadmin desde el panel"}

    updates = {"updated_at": datetime.now(timezone.utc)}

    if role is not None:
        if role == "superadmin":
            return {"ok": False, "error": "No se puede asignar rol superadmin"}
        err = _validate_role(role)
        if err:
            return {"ok": False, "error": err}
        updates["role"] = role
        updates["can_edit_objectives"] = role in ("superadmin", "editor")

    if brands is not None:
        err = _validate_brands(brands)
        if err:
            return {"ok": False, "error": err}
        updates["brands"] = brands

    doc_ref.update(updates)
    logger.info("User updated: %s (%s)", email, updates)
    return {"ok": True}
```

- [ ] **Step 5: Escribir test de `delete_user()`**

Agregar a `tests/test_permissions.py`:

```python
def test_delete_user():
    from permissions import delete_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {"role": "viewer", "brands": ["bosque"]}
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = delete_user(db, "user@temple.com.ar", actor_email="admin@temple.com.ar")
    assert result["ok"] is True
    doc_ref.delete.assert_called_once()


def test_delete_user_cannot_delete_self():
    from permissions import delete_user
    db = MagicMock()
    result = delete_user(db, "admin@temple.com.ar", actor_email="admin@temple.com.ar")
    assert result["ok"] is False
    assert "mismo" in result["error"].lower() or "propio" in result["error"].lower()


def test_delete_user_cannot_delete_superadmin():
    from permissions import delete_user
    db = MagicMock()
    doc_ref = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {"role": "superadmin", "brands": ["*"]}
    db.collection.return_value.document.return_value = doc_ref
    doc_ref.get.return_value = doc_snapshot

    result = delete_user(db, "admin@temple.com.ar", actor_email="other@temple.com.ar")
    assert result["ok"] is False
    assert "superadmin" in result["error"].lower()
```

- [ ] **Step 6: Implementar `delete_user()`**

Agregar a `permissions.py`:

```python
def delete_user(db, email, actor_email):
    """
    Delete a user from Firestore.
    Cannot delete self or superadmin.
    """
    email = email.strip().lower()
    actor_email = actor_email.strip().lower()

    if email == actor_email:
        return {"ok": False, "error": "No podes eliminarte a vos mismo"}

    doc_ref = db.collection(COLLECTION).document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return {"ok": False, "error": f"Usuario {email} no encontrado"}

    if doc.to_dict().get("role") == "superadmin":
        return {"ok": False, "error": "No se puede eliminar al superadmin"}

    doc_ref.delete()
    logger.info("User deleted: %s (by %s)", email, actor_email)
    return {"ok": True}
```

- [ ] **Step 7: Correr todos los tests**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py -v`
Expected: PASS (18 tests)

- [ ] **Step 8: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add permissions.py tests/test_permissions.py
git commit -m "feat: add user CRUD operations to permissions module"
```

---

## Task 3: Refactor `config.py` — eliminar whitelist.txt

**Files:**
- Modify: `config.py:49-66`

- [ ] **Step 1: Modificar `config.py` — eliminar bloque whitelist**

Reemplazar las lineas 49-66 de `config.py` (todo el bloque `# Whitelist`) por:

```python
# ---------------------------------------------------------------------------
# Whitelist — REMOVED
# User access is now managed via Firestore collection 'users_config'.
# See permissions.py for details.
# ---------------------------------------------------------------------------
```

- [ ] **Step 2: Verificar que config importa sin error**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && FLASK_SECRET_KEY=test OAUTH_CLIENT_ID=test OAUTH_CLIENT_SECRET=test CACHE_BUCKET=test python -c "import config; print('OK, no WHITELIST:', not hasattr(config, 'WHITELIST'))"`
Expected: `OK, no WHITELIST: True`

- [ ] **Step 3: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add config.py
git commit -m "refactor: remove whitelist.txt dependency from config, permissions now in Firestore"
```

---

## Task 4: Refactor `app.py` — auth_callback con Firestore

**Files:**
- Modify: `app.py:1-14` (imports)
- Modify: `app.py:59-61` (after bq_client)
- Modify: `app.py:172-190` (auth_callback)

- [ ] **Step 1: Agregar import de permissions al inicio de `app.py`**

Agregar despues de `import config`:

```python
import permissions
```

- [ ] **Step 2: Agregar helper de Firestore en `app.py`**

Agregar despues de `bq_client = bigquery.Client(...)`:

```python
# Firestore client (lazy singleton for permissions)
_fs_client = None

def _get_firestore_client():
    global _fs_client
    if _fs_client is None:
        _fs_client = firestore.Client()
    return _fs_client
```

- [ ] **Step 3: Refactorear `auth_callback` en `app.py`**

Reemplazar el `auth_callback` actual (lineas 173-190) por:

```python
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
        "role": perms["role"],
        "brands": perms["brands"],
        "can_edit_objectives": perms["can_edit_objectives"],
    }
    session.permanent = True
    return redirect(url_for("dashboard"))
```

- [ ] **Step 4: Verificar que la app importa sin error**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && FLASK_SECRET_KEY=test OAUTH_CLIENT_ID=test OAUTH_CLIENT_SECRET=test CACHE_BUCKET=test python -c "import permissions; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add app.py
git commit -m "refactor: auth_callback uses Firestore permissions instead of whitelist"
```

---

## Task 5: Decorador `@require_superadmin` y rutas admin API

**Files:**
- Modify: `app.py`
- Create: `tests/test_admin_routes.py`

- [ ] **Step 1: Escribir tests de acceso admin**

```python
# tests/test_admin_routes.py
"""Tests for admin routes and refactored auth flow."""
import pytest
import json
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """Create Flask test client with Firestore-based auth."""
    import sys

    env_vars = {
        "FLASK_SECRET_KEY": "test-secret-key-for-testing-only-x",
        "OAUTH_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        "OAUTH_CLIENT_SECRET": "test-client-secret",
        "CACHE_BUCKET": "test-bucket",
        "CLOUD_RUN_URL": "https://test.run.app",
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
            yield flask_app.app.test_client()


def _login_session(test_client, email, role, brands):
    """Helper: simulate logged-in user by setting session."""
    with test_client.session_transaction() as sess:
        sess["user"] = {
            "email": email,
            "name": "Test",
            "picture": "",
            "role": role,
            "brands": brands,
            "can_edit_objectives": role in ("superadmin", "editor"),
        }


def test_admin_page_superadmin_can_access(client):
    _login_session(client, "admin@temple.com.ar", "superadmin", ["*"])
    resp = client.get("/admin")
    assert resp.status_code == 200


def test_admin_page_viewer_denied(client):
    _login_session(client, "user@temple.com.ar", "viewer", ["bosque"])
    resp = client.get("/admin")
    assert resp.status_code == 403


def test_admin_page_not_logged_in(client):
    resp = client.get("/admin")
    assert resp.status_code == 302


def test_api_admin_list_users(client):
    _login_session(client, "admin@temple.com.ar", "superadmin", ["*"])

    with patch("app._get_firestore_client") as mock_get_fs:
        db = MagicMock()
        mock_get_fs.return_value = db
        doc1 = MagicMock()
        doc1.id = "admin@temple.com.ar"
        doc1.to_dict.return_value = {"role": "superadmin", "brands": ["*"], "can_edit_objectives": True}
        db.collection.return_value.stream.return_value = [doc1]

        resp = client.get("/api/admin/users")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True
        assert len(data["users"]) == 1


def test_api_admin_create_user(client):
    _login_session(client, "admin@temple.com.ar", "superadmin", ["*"])

    with patch("app._get_firestore_client") as mock_get_fs:
        db = MagicMock()
        mock_get_fs.return_value = db
        doc_ref = MagicMock()
        doc_snapshot = MagicMock()
        doc_snapshot.exists = False
        db.collection.return_value.document.return_value = doc_ref
        doc_ref.get.return_value = doc_snapshot

        resp = client.post("/api/admin/users",
            data=json.dumps({"email": "new@temple.com.ar", "role": "viewer", "brands": ["bosque"]}),
            content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True


def test_api_admin_viewer_cannot_create(client):
    _login_session(client, "user@temple.com.ar", "viewer", ["bosque"])

    resp = client.post("/api/admin/users",
        data=json.dumps({"email": "new@temple.com.ar", "role": "viewer", "brands": ["bosque"]}),
        content_type="application/json")
    assert resp.status_code == 403
```

- [ ] **Step 2: Implementar `@require_superadmin` en `app.py`**

Agregar despues de `login_required`:

```python
def require_superadmin(f):
    """Only allow superadmin users."""
    @wraps(f)
    def decorated(*args, **kwargs):
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
    return decorated
```

- [ ] **Step 3: Agregar rutas admin en `app.py`**

```python
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
```

- [ ] **Step 4: Correr tests**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_admin_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add app.py tests/test_admin_routes.py
git commit -m "feat: add admin API routes with superadmin protection"
```

---

## Task 6: Template `admin.html`

**Files:**
- Create: `templates/admin.html`

- [ ] **Step 1: Crear `templates/admin.html`**

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Admin — Temple Bar</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}
.wrap{max-width:960px;margin:0 auto;padding:24px}
h1{font-size:20px;font-weight:800;margin-bottom:6px}
.subtitle{font-size:12px;color:#8b949e;margin-bottom:24px}
.back-link{color:#c9a227;text-decoration:none;font-size:12px;display:inline-block;margin-bottom:16px}
.back-link:hover{text-decoration:underline}

/* Table */
.tbl-wrap{overflow-x:auto;margin-bottom:24px}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:10px;color:#8b949e;font-weight:700;letter-spacing:.5px;text-transform:uppercase;padding:8px 12px;border-bottom:2px solid #21262d}
td{padding:10px 12px;border-bottom:1px solid #1c2128;font-size:13px}
tr:hover td{background:#161b22}
.role-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:12px}
.role-superadmin{background:#2d2000;color:#c9a227;border:1px solid #c9a227}
.role-editor{background:#0c2d48;color:#58a6ff;border:1px solid #58a6ff}
.role-viewer{background:#21262d;color:#8b949e;border:1px solid #30363d}
.brand-tag{font-size:10px;padding:2px 6px;border-radius:4px;background:#21262d;color:#c9d1d9;margin-right:4px;display:inline-block;margin-bottom:2px}
.btn{padding:5px 12px;font-size:11px;border-radius:6px;cursor:pointer;border:1px solid #30363d;background:transparent;color:#8b949e;transition:all .15s}
.btn:hover{border-color:#8b949e;color:#e6edf3}
.btn-danger:hover{border-color:#f87171;color:#f87171}
.btn-primary{background:#2d2000;border-color:#c9a227;color:#c9a227}
.btn-primary:hover{background:#3d3000}

/* Modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;width:420px;max-width:90vw}
.modal h2{font-size:16px;margin-bottom:16px}
.field{margin-bottom:14px}
.field label{display:block;font-size:11px;color:#8b949e;font-weight:700;margin-bottom:4px;text-transform:uppercase;letter-spacing:.4px}
.field input,.field select{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 10px;font-size:13px}
.field input:focus,.field select:focus{outline:none;border-color:#c9a227}
.chk-group{display:flex;flex-wrap:wrap;gap:8px}
.chk-group label{display:flex;align-items:center;gap:4px;font-size:12px;color:#c9d1d9;cursor:pointer;text-transform:none;letter-spacing:0;font-weight:400}
.chk-group input[type=checkbox]{accent-color:#c9a227}
.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:18px}
.msg{padding:10px 14px;border-radius:8px;font-size:12px;margin-bottom:14px;display:none}
.msg-ok{background:#052e16;border:1px solid rgba(110,231,183,.3);color:#6ee7b7}
.msg-err{background:#450a0a;border:1px solid rgba(252,165,165,.3);color:#fca5a5}
</style>
</head>
<body>
<div class="wrap">
  <a href="/destileria" class="back-link">&larr; Volver al tablero</a>
  <h1>Gestion de Usuarios</h1>
  <p class="subtitle">Administra accesos y permisos del tablero</p>

  <div id="msg" class="msg"></div>

  <button class="btn btn-primary" onclick="openModal('create')" style="margin-bottom:16px">+ Agregar usuario</button>

  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Email</th>
          <th>Rol</th>
          <th>Marcas</th>
          <th>Acciones</th>
        </tr>
      </thead>
      <tbody id="users-tbody">
        <tr><td colspan="4" style="color:#8b949e;text-align:center;padding:24px">Cargando...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Modal -->
<div class="modal-overlay" id="modal">
  <div class="modal">
    <h2 id="modal-title">Agregar usuario</h2>
    <div class="field">
      <label>Email</label>
      <input type="email" id="m-email" placeholder="usuario@temple.com.ar"/>
    </div>
    <div class="field">
      <label>Rol</label>
      <select id="m-role">
        <option value="viewer">Viewer — solo lectura</option>
        <option value="editor">Editor — puede editar objetivos</option>
      </select>
    </div>
    <div class="field">
      <label>Marcas</label>
      <div class="chk-group" id="m-brands">
        <label><input type="checkbox" value="*" onchange="toggleAll(this)"/> Todas</label>
        {% for b in brands %}
        <label><input type="checkbox" value="{{ b }}"/> {{ b|capitalize }}</label>
        {% endfor %}
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancelar</button>
      <button class="btn btn-primary" id="modal-submit" onclick="submitModal()">Guardar</button>
    </div>
  </div>
</div>

<script>
const CSRF_TOKEN = '{{ csrf_token() }}';
let modalMode = 'create';
let editingEmail = '';

function showMsg(text, ok) {
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = 'msg ' + (ok ? 'msg-ok' : 'msg-err');
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
}

async function loadUsers() {
  const resp = await fetch('/api/admin/users');
  const data = await resp.json();
  if (!data.ok) { showMsg('Error cargando usuarios', false); return; }
  const tbody = document.getElementById('users-tbody');
  if (data.users.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="color:#8b949e;text-align:center">No hay usuarios</td></tr>';
    return;
  }
  tbody.innerHTML = data.users.map(u => {
    const roleCls = 'role-' + u.role;
    const brandsHtml = (u.brands || []).map(b =>
      '<span class="brand-tag">' + (b === '*' ? 'Todas' : b) + '</span>'
    ).join('');
    const actions = u.role === 'superadmin'
      ? '<span style="color:#6e7681;font-size:11px">&mdash;</span>'
      : '<button class="btn" onclick="openModal(\'edit\',\'' + u.email + '\',\'' + u.role + '\',' + JSON.stringify(JSON.stringify(u.brands)) + ')">Editar</button> '
        + '<button class="btn btn-danger" onclick="deleteUser(\'' + u.email + '\')">Eliminar</button>';
    return '<tr>'
      + '<td>' + u.email + '</td>'
      + '<td><span class="role-badge ' + roleCls + '">' + u.role + '</span></td>'
      + '<td>' + brandsHtml + '</td>'
      + '<td>' + actions + '</td>'
      + '</tr>';
  }).join('');
}

function openModal(mode, email, role, brandsJson) {
  modalMode = mode;
  const emailInput = document.getElementById('m-email');
  const roleSelect = document.getElementById('m-role');

  if (mode === 'edit') {
    document.getElementById('modal-title').textContent = 'Editar usuario';
    editingEmail = email;
    emailInput.value = email;
    emailInput.disabled = true;
    roleSelect.value = role || 'viewer';
    const brands = brandsJson ? JSON.parse(brandsJson) : [];
    document.querySelectorAll('#m-brands input[type=checkbox]').forEach(cb => {
      cb.checked = brands.includes(cb.value) || brands.includes('*');
    });
  } else {
    document.getElementById('modal-title').textContent = 'Agregar usuario';
    editingEmail = '';
    emailInput.value = '';
    emailInput.disabled = false;
    roleSelect.value = 'viewer';
    document.querySelectorAll('#m-brands input[type=checkbox]').forEach(cb => { cb.checked = false; });
  }
  document.getElementById('modal').classList.add('open');
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

function toggleAll(masterCb) {
  document.querySelectorAll('#m-brands input[type=checkbox]').forEach(cb => {
    if (cb.value !== '*') cb.checked = masterCb.checked;
  });
}

async function submitModal() {
  const email = document.getElementById('m-email').value.trim();
  const role = document.getElementById('m-role').value;
  const allChecked = document.querySelector('#m-brands input[value="*"]').checked;
  let brands;
  if (allChecked) {
    brands = ['*'];
  } else {
    brands = [...document.querySelectorAll('#m-brands input[type=checkbox]:checked')]
      .map(cb => cb.value).filter(v => v !== '*');
  }

  if (!email) { showMsg('Email es requerido', false); return; }
  if (brands.length === 0) { showMsg('Selecciona al menos una marca', false); return; }

  const url = modalMode === 'create'
    ? '/api/admin/users'
    : '/api/admin/users/' + encodeURIComponent(editingEmail);
  const method = modalMode === 'create' ? 'POST' : 'PUT';

  const resp = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': CSRF_TOKEN,
    },
    body: JSON.stringify({ email, role, brands }),
  });
  const data = await resp.json();
  if (data.ok) {
    showMsg(modalMode === 'create' ? 'Usuario creado' : 'Usuario actualizado', true);
    closeModal();
    loadUsers();
  } else {
    showMsg(data.error || 'Error', false);
  }
}

async function deleteUser(email) {
  if (!confirm('Eliminar a ' + email + '?')) return;
  const resp = await fetch('/api/admin/users/' + encodeURIComponent(email), {
    method: 'DELETE',
    headers: { 'X-CSRFToken': CSRF_TOKEN },
  });
  const data = await resp.json();
  if (data.ok) {
    showMsg('Usuario eliminado', true);
    loadUsers();
  } else {
    showMsg(data.error || 'Error', false);
  }
}

loadUsers();
</script>
</body>
</html>
```

- [ ] **Step 2: Verificar que el template se renderiza**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('templates')); t = env.get_template('admin.html'); print('OK:', len(t.render(brands=['bosque','feriado','cerveza','merch'], csrf_token=lambda:'test')), 'chars')"`
Expected: `OK: NNNN chars`

- [ ] **Step 3: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add templates/admin.html
git commit -m "feat: add admin panel template for user management"
```

---

## Task 7: Ruta `/destileria` en Flask con inyeccion de permisos

**Files:**
- Modify: `app.py`
- Modify: `templates/destileria.html:325` (agregar placeholder)
- Create: `tests/test_destileria_route.py`

- [ ] **Step 1: Agregar placeholder en template `destileria.html`**

En `templates/destileria.html`, reemplazar la linea `<body>` (linea 325) por:

```html
<body>
__PERMISSIONS_INJECT__
```

El placeholder sera reemplazado por Flask al servir.

- [ ] **Step 2: Escribir test de la ruta `/destileria`**

```python
# tests/test_destileria_route.py
"""Tests for /destileria route with permission injection."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    import sys

    env_vars = {
        "FLASK_SECRET_KEY": "test-secret-key-for-testing-only-x",
        "OAUTH_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        "OAUTH_CLIENT_SECRET": "test-client-secret",
        "CACHE_BUCKET": "test-bucket",
        "CLOUD_RUN_URL": "https://test.run.app",
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
            yield flask_app.app.test_client()


def _login(test_client, role="viewer", brands=None):
    if brands is None:
        brands = ["bosque"]
    with test_client.session_transaction() as sess:
        sess["user"] = {
            "email": "test@temple.com.ar",
            "name": "Test",
            "picture": "",
            "role": role,
            "brands": brands,
            "can_edit_objectives": role in ("superadmin", "editor"),
        }


def test_destileria_requires_login(client):
    resp = client.get("/destileria")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_destileria_injects_permissions(client):
    _login(client, role="viewer", brands=["bosque", "feriado"])

    sample_html = '<html><head></head><body>__PERMISSIONS_INJECT__<div>content</div></body></html>'

    with patch("app._dest_cache", {"html": sample_html, "ts": 9999999999.0}):
        resp = client.get("/destileria")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "window.__USER_PERMISSIONS__" in html
        assert '"bosque"' in html
        assert '"feriado"' in html
        assert '"viewer"' in html


def test_destileria_superadmin_sees_admin_link(client):
    _login(client, role="superadmin", brands=["*"])

    sample_html = '<html><head></head><body>__PERMISSIONS_INJECT__<div>content</div></body></html>'

    with patch("app._dest_cache", {"html": sample_html, "ts": 9999999999.0}):
        resp = client.get("/destileria")
        html = resp.data.decode("utf-8")
        assert "/admin" in html
```

- [ ] **Step 3: Agregar ruta `/destileria` en `app.py`**

Agregar despues de la ruta `/dashboard`:

```python
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
                return "Tablero temporalmente no disponible. Intenta de nuevo en unos minutos.", 503

    user = session["user"]
    perms_json = json.dumps({
        "role": user["role"],
        "brands": user["brands"],
        "canEditObjectives": user["can_edit_objectives"],
    }, ensure_ascii=False)

    perms_script = f'<script>window.__USER_PERMISSIONS__={perms_json};</script>'

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
        perms_script + admin_link,
    )

    return html, 200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    }
```

- [ ] **Step 4: Correr tests**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_destileria_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add app.py templates/destileria.html tests/test_destileria_route.py
git commit -m "feat: add /destileria route with permission injection"
```

---

## Task 8: Filtrado de tabs en frontend por permisos

**Files:**
- Modify: `templates/destileria.html` (seccion JS, ~linea 1729)

- [ ] **Step 1: Agregar logica de filtrado de tabs al JS del template**

En `templates/destileria.html`, agregar justo antes de la funcion `switchTab` (linea ~1729, antes de `// ============================================================` / `// TAB SWITCHING`):

```javascript
// ============================================================
// PERMISSION-BASED TAB FILTERING
// ============================================================
(function filterTabsByPermissions() {
  var perms = window.__USER_PERMISSIONS__;
  if (!perms || !perms.brands) return;

  var allowed = perms.brands;
  if (allowed.indexOf('*') !== -1) return; // all brands allowed

  // Map brand -> tab-group/tab IDs
  var brandTabs = {
    'feriado': ['grp-feriado'],
    'bosque':  ['grp-bosque'],
    'cerveza': []
  };

  // Hide tab groups for disallowed brands
  Object.keys(brandTabs).forEach(function(brand) {
    if (allowed.indexOf(brand) !== -1) return;
    brandTabs[brand].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    // Hide standalone tab buttons
    document.querySelectorAll('.tab-btn[data-tab="' + brand + '"]').forEach(function(btn) {
      btn.style.display = 'none';
    });
  });
})();
```

- [ ] **Step 2: Verificar que el placeholder y el filtrado estan en el template**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && grep -c "PERMISSIONS_INJECT\|filterTabsByPermissions" templates/destileria.html`
Expected: `2` (una linea para cada patron)

- [ ] **Step 3: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add templates/destileria.html
git commit -m "feat: filter visible tabs based on user brand permissions"
```

---

## Task 9: Verificar que el script de generacion preserva el placeholder

**Files:**
- Verify: `generar_destileria_dashboard (1).py`

- [ ] **Step 1: Verificar que el script no toca `__PERMISSIONS_INJECT__`**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && grep "PERMISSIONS" "generar_destileria_dashboard (1).py"`
Expected: Sin resultados (el script no lo reemplaza)

- [ ] **Step 2: Regenerar el dashboard y verificar que el placeholder pasa**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && /usr/bin/python3 "generar_destileria_dashboard (1).py" && grep -c "PERMISSIONS_INJECT" destileria_dashboard.html`
Expected: `1` (el placeholder sobrevive a la generacion)

- [ ] **Step 3: Subir HTML actualizado a GCS**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
gsutil cp destileria_dashboard.html gs://temple-bar-dashboard-cache/destileria_dashboard.html
```

---

## Task 10: Script de migracion whitelist a Firestore

**Files:**
- Create: `scripts/migrate_whitelist.py`

- [ ] **Step 1: Crear directorio scripts**

```bash
mkdir -p "/Users/darwjoses/Mi unidad/Claude_Cowork/scripts"
```

- [ ] **Step 2: Crear script de migracion**

```python
#!/usr/bin/env python3
"""
migrate_whitelist.py — One-time migration: whitelist.txt -> Firestore users_config.

Usage:
  python scripts/migrate_whitelist.py

Reads whitelist.txt, creates Firestore documents for each email.
darwin.salinas@temple.com.ar gets role=superadmin, all others get role=viewer.
All users get brands=["*"] (access to all brands).

Safe to run multiple times — skips emails that already exist.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore

SUPERADMIN_EMAIL = "darwin.salinas@temple.com.ar"
COLLECTION = "users_config"
WHITELIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "whitelist.txt",
)


def main():
    if not os.path.exists(WHITELIST_PATH):
        print(f"ERROR: {WHITELIST_PATH} not found")
        sys.exit(1)

    with open(WHITELIST_PATH, encoding="utf-8") as f:
        emails = [
            line.strip().lower()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]

    print(f"Found {len(emails)} emails in whitelist.txt")

    db = firestore.Client()
    now = datetime.now(timezone.utc)
    created, skipped = 0, 0

    for email in emails:
        doc_ref = db.collection(COLLECTION).document(email)
        if doc_ref.get().exists:
            print(f"  SKIP (exists): {email}")
            skipped += 1
            continue

        is_superadmin = email == SUPERADMIN_EMAIL
        role = "superadmin" if is_superadmin else "viewer"

        doc_ref.set({
            "role": role,
            "brands": ["*"],
            "can_edit_objectives": is_superadmin,
            "created_at": now,
            "updated_at": now,
        })
        print(f"  CREATED: {email} (role={role})")
        created += 1

    print(f"\nDone: {created} created, {skipped} skipped")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add scripts/migrate_whitelist.py
git commit -m "feat: add one-time whitelist to Firestore migration script"
```

---

## Task 11: Actualizar tests existentes de auth

**Files:**
- Modify: `tests/test_auth.py`

- [ ] **Step 1: Actualizar fixture de `test_auth.py`**

Reemplazar el fixture `client` (lineas 33-60 aprox) para que use Firestore en vez de whitelist:

```python
@pytest.fixture
def client(tmp_path):
    """Create Flask test client with Firestore-based auth."""
    import importlib
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
            yield flask_app.app.test_client()
```

- [ ] **Step 2: Actualizar tests que referencian `WHITELIST` o `ALLOWED_DOMAINS`**

Buscar y reemplazar tests que validan whitelist por tests que mockean `permissions.get_user_permissions()`.

- [ ] **Step 3: Correr toda la suite de tests**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/ -v --ignore=tests/test_whatsapp_agent.py --ignore=tests/test_whatsapp_tools.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add tests/test_auth.py
git commit -m "refactor: update auth tests to use Firestore permissions"
```

---

## Task 12: Ejecucion de migracion y verificacion end-to-end

- [ ] **Step 1: Ejecutar script de migracion**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
python scripts/migrate_whitelist.py
```

Expected: 10 usuarios creados (1 superadmin + 9 viewers)

- [ ] **Step 2: Verificar datos en Firestore**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
python -c "
from google.cloud import firestore
db = firestore.Client()
for doc in db.collection('users_config').stream():
    d = doc.to_dict()
    print(f\"{doc.id}: role={d['role']}, brands={d['brands']}\")
"
```

Expected: 10 usuarios listados, darwin.salinas como superadmin, el resto como viewer.

- [ ] **Step 3: Correr todos los tests**

Run: `cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: Subir dashboard actualizado a GCS**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
gsutil cp destileria_dashboard.html gs://temple-bar-dashboard-cache/destileria_dashboard.html
```

- [ ] **Step 5: Commit final**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
git add -A
git commit -m "feat: complete permission system — Firestore, admin panel, brand filtering"
```
