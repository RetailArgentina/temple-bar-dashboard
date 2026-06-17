# Login Destilería Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar login por email y contraseña para `/destileria`, independiente del Google OAuth del dashboard retail.

**Architecture:** Nueva colección Firestore `destileria_users` con contraseñas hasheadas (bcrypt). Nuevo módulo `destileria_auth.py` con helpers de Firestore. Rutas nuevas `/destileria/login` y `/destileria/logout` en `app.py`. El decorator `@destileria_login_required` reemplaza `@login_required` solo en la ruta `/destileria`. El panel `/admin` recibe una nueva tab para CRUD de usuarios destilería.

**Tech Stack:** Flask, Firestore (google-cloud-firestore), werkzeug.security (bcrypt — ya en requirements), flask-wtf CSRF (ya configurado), Jinja2.

**Spec:** `docs/superpowers/specs/2026-06-17-login-destileria-design.md`

---

## File Map

| Archivo | Acción |
|---|---|
| `destileria_auth.py` | **Nuevo** — helpers Firestore para `destileria_users` |
| `tests/test_destileria_auth.py` | **Nuevo** — tests unitarios y de rutas |
| `app.py` | **Modificar** — decorator, rutas login/logout, admin API, fix redirect raíz |
| `templates/destileria_login.html` | **Nuevo** — formulario login estilo C |
| `templates/admin.html` | **Modificar** — nueva tab Destilería con CRUD |

---

## Task 1: Crear `destileria_auth.py` con tests

**Files:**
- Create: `destileria_auth.py`
- Create: `tests/test_destileria_auth.py`

- [ ] **Step 1: Escribir los tests unitarios**

Crear `tests/test_destileria_auth.py`:

```python
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
    user = get_destileria_user(db, "ANA@EMPRESA.COM")   # debe normalizar a minúsculas
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
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork"
python -m pytest tests/test_destileria_auth.py -v 2>&1 | head -30
```

Expected: `ImportError` o `ModuleNotFoundError: No module named 'destileria_auth'`

- [ ] **Step 3: Crear `destileria_auth.py`**

```python
"""
destileria_auth.py — Firestore helpers para la colección destileria_users.

Estructura de cada documento (doc_id = email en minúsculas):
    name: str
    password_hash: str          — bcrypt via werkzeug.security
    role: str                   — "gerencia" | "editor" | "viewer"
    brands: list[str]           — ["*"] o ["bosque", "feriado"]
    can_edit_objectives: bool
    active: bool
    created_at: str             — ISO 8601 UTC
    created_by: str             — email del admin que lo creó
"""
from __future__ import annotations
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

COLLECTION = "destileria_users"


def get_destileria_user(db, email: str) -> dict | None:
    """Retorna el usuario como dict (incluye password_hash), o None si no existe."""
    normalized = email.lower().strip()
    doc = db.collection(COLLECTION).document(normalized).get()
    if not doc.exists:
        return None
    return {"email": normalized, **doc.to_dict()}


def verify_destileria_password(db, email: str, password: str) -> dict | None:
    """
    Retorna el dict del usuario si el email existe, está activo y la contraseña es correcta.
    Retorna None en cualquier otro caso (sin indicar el motivo).
    """
    user = get_destileria_user(db, email)
    if user is None or not user.get("active", False):
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def create_destileria_user(
    db,
    email: str,
    name: str,
    password: str,
    role: str,
    brands: list[str],
    can_edit_objectives: bool,
    created_by: str,
) -> None:
    """Crea un nuevo usuario destilería. La contraseña se hashea antes de guardar."""
    data = {
        "name": name,
        "password_hash": generate_password_hash(password),
        "role": role,
        "brands": brands,
        "can_edit_objectives": can_edit_objectives,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }
    db.collection(COLLECTION).document(email.lower().strip()).set(data)


def update_destileria_user(
    db,
    email: str,
    name: str,
    role: str,
    brands: list[str],
    can_edit_objectives: bool,
) -> None:
    """Actualiza nombre, rol, marcas y permiso de objetivos. No toca la contraseña."""
    db.collection(COLLECTION).document(email.lower().strip()).update({
        "name": name,
        "role": role,
        "brands": brands,
        "can_edit_objectives": can_edit_objectives,
    })


def reset_destileria_password(db, email: str, new_password: str) -> None:
    """Reemplaza el hash de contraseña por uno nuevo."""
    db.collection(COLLECTION).document(email.lower().strip()).update({
        "password_hash": generate_password_hash(new_password),
    })


def toggle_destileria_user_active(db, email: str) -> bool:
    """Invierte el campo `active`. Retorna el nuevo valor."""
    ref = db.collection(COLLECTION).document(email.lower().strip())
    current = ref.get().to_dict().get("active", True)
    ref.update({"active": not current})
    return not current


def list_destileria_users(db) -> list[dict]:
    """Retorna todos los usuarios ordenados por nombre. Nunca incluye password_hash."""
    docs = db.collection(COLLECTION).stream()
    users = []
    for doc in docs:
        data = doc.to_dict()
        data.pop("password_hash", None)
        data["email"] = doc.id
        users.append(data)
    return sorted(users, key=lambda u: u.get("name", "").lower())
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

```bash
python -m pytest tests/test_destileria_auth.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add destileria_auth.py tests/test_destileria_auth.py
git -c user.email="darwin.salinas@temple.com.ar" -c user.name="Darwin Salinas" \
  commit -m "feat: add destileria_auth module with Firestore helpers"
```

---

## Task 2: Agregar rutas de login/logout en `app.py`

**Files:**
- Modify: `app.py` — decorator + rutas `/destileria/login` y `/destileria/logout`
- Modify: `app.py` — cambiar decorator en `/destileria`, sesión y redirect raíz
- Modify: `tests/test_destileria_auth.py` — agregar tests de rutas

- [ ] **Step 1: Agregar tests de rutas al archivo de tests**

Agregar al final de `tests/test_destileria_auth.py`:

```python
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
```

- [ ] **Step 2: Correr tests para verificar que fallan**

```bash
python -m pytest tests/test_destileria_auth.py::test_destileria_redirects_to_login_unauthenticated -v
```

Expected: FAIL — la ruta `/destileria` todavía usa `@login_required`

- [ ] **Step 3: Agregar import de `destileria_auth` en `app.py`**

En `app.py`, después de la línea `import permissions`, agregar:

```python
import destileria_auth
```

- [ ] **Step 4: Agregar decorator `destileria_login_required` en `app.py`**

Después del decorator `login_required` existente en `app.py`, agregar:

```python
def destileria_login_required(f):
    """Protege rutas que requieren sesión de destilería (email/password)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "dest_user" not in session:
            return redirect(url_for("destileria_login"))
        return f(*args, **kwargs)
    return decorated
```

- [ ] **Step 5: Agregar rutas `/destileria/login` y `/destileria/logout` en `app.py`**

Agregar ANTES de la sección `# Destileria dashboard` (línea ~372):

```python
# ---------------------------------------------------------------------------
# Destileria auth — login/logout por email y contraseña
# ---------------------------------------------------------------------------

@app.route("/destileria/login", methods=["GET", "POST"])
def destileria_login():
    if "dest_user" in session:
        return redirect(url_for("destileria"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        db = _get_firestore_client()
        user = destileria_auth.verify_destileria_password(db, email, password)
        if user:
            session["dest_user"] = {
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
                "brands": user["brands"],
                "can_edit_objectives": user["can_edit_objectives"],
            }
            return redirect(url_for("destileria"))
        error = "Email o contraseña incorrectos"

    reason = request.args.get("reason")
    return render_template("destileria_login.html", error=error, reason=reason)


@app.route("/destileria/logout", methods=["POST"])
def destileria_logout():
    session.pop("dest_user", None)
    return redirect(url_for("destileria_login"))
```

- [ ] **Step 6: Cambiar `@login_required` por `@destileria_login_required` en la ruta `/destileria`**

En `app.py` alrededor de la línea 376, cambiar:

```python
@app.route("/destileria")
@login_required
def destileria():
```

Por:

```python
@app.route("/destileria")
@destileria_login_required
def destileria():
```

- [ ] **Step 7: Cambiar `session["user"]` por `session["dest_user"]` dentro de `destileria()`**

Dentro de la función `destileria()` (alrededor de línea 394), cambiar:

```python
    user = session["user"]
```

Por:

```python
    user = session["dest_user"]
```

- [ ] **Step 8: Cambiar redirect raíz en `app.py` (línea 201)**

En la función `index()`, cambiar:

```python
    return redirect(url_for("destileria"))
```

Por:

```python
    return redirect(url_for("dashboard"))
```

- [ ] **Step 9: Correr todos los tests de rutas**

```bash
python -m pytest tests/test_destileria_auth.py -v -k "destileria"
```

Expected: 7 tests PASSED

- [ ] **Step 10: Verificar que los tests existentes no se rompieron**

```bash
python -m pytest tests/test_auth.py -v
```

Expected: todos PASSED

- [ ] **Step 11: Commit**

```bash
git add app.py tests/test_destileria_auth.py
git -c user.email="darwin.salinas@temple.com.ar" -c user.name="Darwin Salinas" \
  commit -m "feat: add destileria login/logout routes and decorator"
```

---

## Task 3: Agregar admin API endpoints en `app.py`

**Files:**
- Modify: `app.py` — 5 endpoints nuevos de admin
- Modify: `tests/test_destileria_auth.py` — tests de admin API

- [ ] **Step 1: Agregar tests de admin API**

Agregar al final de `tests/test_destileria_auth.py`:

```python
# ── Admin API tests ───────────────────────────────────────────────────────

def _admin_session(c, role="superadmin"):
    with c.session_transaction() as sess:
        sess["user"] = {
            "email": "darwin.salinas@temple.com.ar",
            "name": "Darwin Salinas",
            "role": role,
            "brands": ["*"],
            "can_edit_objectives": True,
        }


def test_admin_list_destileria_users(client):
    c, _ = client
    _admin_session(c)
    doc = MagicMock()
    doc.id = "ana@empresa.com"
    doc.to_dict.return_value = {"name": "Ana", "role": "viewer", "brands": ["*"],
                                "can_edit_objectives": False, "active": True,
                                "password_hash": "secreto"}
    db = MagicMock()
    db.collection.return_value.stream.return_value = [doc]
    with patch("app._get_firestore_client", return_value=db):
        resp = c.get("/admin/destileria/users")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert "password_hash" not in data[0]


def test_admin_create_destileria_user(client):
    c, _ = client
    _admin_session(c)
    db = MagicMock()
    with patch("app._get_firestore_client", return_value=db):
        resp = c.post("/admin/destileria/users", json={
            "email": "nuevo@empresa.com", "name": "Nuevo",
            "password": "Temp2026!", "role": "viewer",
            "brands": ["bosque"], "can_edit_objectives": False,
        })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    db.collection.return_value.document.return_value.set.assert_called_once()


def test_admin_create_user_forbidden_for_viewer(client):
    c, _ = client
    _admin_session(c, role="viewer")
    with patch("app._get_firestore_client", return_value=MagicMock()):
        resp = c.post("/admin/destileria/users", json={
            "email": "x@x.com", "name": "X",
            "password": "p", "role": "viewer",
            "brands": ["*"], "can_edit_objectives": False,
        })
    assert resp.status_code == 403


def test_admin_reset_password(client):
    c, _ = client
    _admin_session(c)
    db = MagicMock()
    with patch("app._get_firestore_client", return_value=db):
        resp = c.post(
            "/admin/destileria/users/ana@empresa.com/reset-password",
            json={"password": "NuevoPass2026!"}
        )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_admin_toggle_active(client):
    c, _ = client
    _admin_session(c)
    doc = MagicMock()
    doc.to_dict.return_value = {"active": True}
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = doc
    with patch("app._get_firestore_client", return_value=db):
        resp = c.post("/admin/destileria/users/ana@empresa.com/toggle-active")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["active"] is False
```

- [ ] **Step 2: Correr tests para verificar que fallan**

```bash
python -m pytest tests/test_destileria_auth.py -v -k "admin"
```

Expected: FAIL — 404 porque los endpoints no existen aún

- [ ] **Step 3: Agregar los 5 endpoints de admin en `app.py`**

Agregar en la sección de rutas de admin (buscar el último endpoint de `/admin` existente) e insertar después:

```python
# ---------------------------------------------------------------------------
# Admin API — gestión de usuarios destilería
# Requiere sesión Google OAuth con rol superadmin o gerencia
# ---------------------------------------------------------------------------

@app.route("/admin/destileria/users", methods=["GET"])
@login_required
def admin_list_destileria_users():
    if session["user"]["role"] not in ("superadmin", "gerencia"):
        abort(403)
    db = _get_firestore_client()
    return jsonify(destileria_auth.list_destileria_users(db))


@app.route("/admin/destileria/users", methods=["POST"])
@login_required
def admin_create_destileria_user():
    if session["user"]["role"] not in ("superadmin", "gerencia"):
        abort(403)
    data = request.get_json()
    db = _get_firestore_client()
    destileria_auth.create_destileria_user(
        db,
        email=data["email"],
        name=data["name"],
        password=data["password"],
        role=data["role"],
        brands=data["brands"],
        can_edit_objectives=data.get("can_edit_objectives", False),
        created_by=session["user"]["email"],
    )
    return jsonify({"ok": True})


@app.route("/admin/destileria/users/<path:email>", methods=["PUT"])
@login_required
def admin_update_destileria_user(email):
    if session["user"]["role"] not in ("superadmin", "gerencia"):
        abort(403)
    data = request.get_json()
    db = _get_firestore_client()
    destileria_auth.update_destileria_user(
        db, email,
        name=data["name"],
        role=data["role"],
        brands=data["brands"],
        can_edit_objectives=data.get("can_edit_objectives", False),
    )
    return jsonify({"ok": True})


@app.route("/admin/destileria/users/<path:email>/reset-password", methods=["POST"])
@login_required
def admin_reset_destileria_password(email):
    if session["user"]["role"] not in ("superadmin", "gerencia"):
        abort(403)
    data = request.get_json()
    db = _get_firestore_client()
    destileria_auth.reset_destileria_password(db, email, data["password"])
    return jsonify({"ok": True})


@app.route("/admin/destileria/users/<path:email>/toggle-active", methods=["POST"])
@login_required
def admin_toggle_destileria_user(email):
    if session["user"]["role"] not in ("superadmin", "gerencia"):
        abort(403)
    db = _get_firestore_client()
    new_active = destileria_auth.toggle_destileria_user_active(db, email)
    return jsonify({"ok": True, "active": new_active})
```

- [ ] **Step 4: Correr todos los tests**

```bash
python -m pytest tests/test_destileria_auth.py -v
```

Expected: todos PASSED (unitarios + rutas + admin)

- [ ] **Step 5: Correr suite completa para detectar regresiones**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: todos PASSED

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_destileria_auth.py
git -c user.email="darwin.salinas@temple.com.ar" -c user.name="Darwin Salinas" \
  commit -m "feat: add admin API endpoints for destileria user management"
```

---

## Task 4: Crear `templates/destileria_login.html`

**Files:**
- Create: `templates/destileria_login.html`

Nota GateGuard: presentar estos hechos antes de crear el archivo:
1. Lo llama Flask desde `app.py` con `render_template("destileria_login.html", error=error, reason=reason)` en la función `destileria_login()`
2. No existe ningún `destileria_login.html` en `templates/`
3. Variables Jinja2: `error` (str|None) y `reason` (str|None)
4. Instrucción: crear template de login estilo C

- [ ] **Step 1: Crear el template `templates/destileria_login.html`**

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta name="theme-color" content="#0d1117"/>
  <title>Destilería — Ingresar</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: #0d1117; color: #e6edf3;
      min-height: 100vh; display: flex;
    }
    .brand-panel {
      width: 40%; min-height: 100vh;
      background: linear-gradient(160deg, #0d1117 0%, #1a1200 100%);
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      padding: 48px;
      border-right: 1px solid rgba(201,162,39,0.15);
      position: relative; overflow: hidden;
    }
    .brand-panel::before {
      content: '';
      position: absolute; width: 320px; height: 320px;
      background: radial-gradient(circle, rgba(201,162,39,0.07) 0%, transparent 70%);
      top: 50%; left: 50%; transform: translate(-50%, -50%);
    }
    .brand-icon {
      width: 76px; height: 76px;
      background: linear-gradient(135deg, #c9a227, #a07800);
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 34px; margin-bottom: 22px;
      box-shadow: 0 0 36px rgba(201,162,39,0.2);
      position: relative;
    }
    .brand-name {
      font-size: 22px; font-weight: 800;
      letter-spacing: 3px; text-transform: uppercase;
      color: #fff; margin-bottom: 6px; position: relative;
    }
    .brand-sub {
      font-size: 11px; letter-spacing: 3px; color: #c9a227;
      text-transform: uppercase; margin-bottom: 28px; position: relative;
    }
    .brand-desc {
      font-size: 12px; color: #4a5568;
      text-align: center; line-height: 1.7;
      max-width: 210px; position: relative;
    }
    .form-panel {
      flex: 1; display: flex;
      align-items: center; justify-content: center;
      padding: 48px;
    }
    .form-box { width: 100%; max-width: 360px; }
    h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
    .form-sub { font-size: 13px; color: #8b949e; margin-bottom: 28px; }
    .notice {
      border-radius: 8px; padding: 11px 14px;
      font-size: 13px; margin-bottom: 20px;
      display: flex; align-items: center; gap: 8px;
    }
    .notice-err {
      background: rgba(239,68,68,0.1);
      border: 1px solid rgba(239,68,68,0.4);
      color: #f87171;
    }
    .notice-warn {
      background: rgba(234,179,8,0.1);
      border: 1px solid rgba(234,179,8,0.35);
      color: #facc15;
    }
    .field { margin-bottom: 18px; }
    .field label {
      display: block; font-size: 11px; font-weight: 600;
      color: #8b949e; text-transform: uppercase;
      letter-spacing: 1px; margin-bottom: 7px;
    }
    .field input {
      width: 100%; background: #161b22;
      border: 1px solid rgba(201,162,39,0.2);
      border-radius: 8px; padding: 12px 14px;
      font-size: 14px; color: #e6edf3; outline: none;
      transition: border-color .2s;
    }
    .field input:focus { border-color: #c9a227; }
    .field input.error { border-color: rgba(239,68,68,0.5); }
    .btn-login {
      width: 100%;
      background: linear-gradient(90deg, #c9a227, #a07800);
      color: #0d1117; border: none; border-radius: 8px;
      padding: 13px; font-size: 13px; font-weight: 800;
      letter-spacing: 1px; text-transform: uppercase;
      cursor: pointer; margin-top: 6px;
      transition: opacity .2s;
    }
    .btn-login:hover { opacity: .9; }
    @media (max-width: 640px) { .brand-panel { display: none; } }
  </style>
</head>
<body>
  <div class="brand-panel">
    <div class="brand-icon">🥃</div>
    <div class="brand-name">Destilería</div>
    <div class="brand-sub">Patagónica</div>
    <p class="brand-desc">Acceso restringido al equipo comercial de destilería</p>
  </div>
  <div class="form-panel">
    <div class="form-box">
      <h1>Bienvenido</h1>
      <p class="form-sub">Ingresá con tu email y contraseña</p>

      {% if reason == 'expired' %}
      <div class="notice notice-warn">⏱ Tu sesión expiró, volvé a ingresar</div>
      {% endif %}

      {% if error %}
      <div class="notice notice-err">⚠ {{ error }}</div>
      {% endif %}

      <form method="POST" action="/destileria/login" novalidate>
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
        <div class="field">
          <label for="email">Email</label>
          <input type="email" id="email" name="email"
            placeholder="usuario@empresa.com"
            autocomplete="email" required
            {% if error %}class="error"{% endif %}/>
        </div>
        <div class="field">
          <label for="password">Contraseña</label>
          <input type="password" id="password" name="password"
            placeholder="••••••••"
            autocomplete="current-password" required
            {% if error %}class="error"{% endif %}/>
        </div>
        <button type="submit" class="btn-login">Ingresar</button>
      </form>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 2: Verificar visualmente**

Navegar a `http://localhost:5000/destileria/login` (app corriendo localmente). Verificar:
- Panel izquierdo con ícono dorado y "DESTILERÍA / PATAGÓNICA"
- Formulario con email y contraseña
- Botón dorado "INGRESAR"
- En mobile (< 640px) el panel izquierdo se oculta

- [ ] **Step 3: Commit**

```bash
git add templates/destileria_login.html
git -c user.email="darwin.salinas@temple.com.ar" -c user.name="Darwin Salinas" \
  commit -m "feat: add destileria login template (dark brand style)"
```

---

## Task 5: Agregar tab Destilería en `templates/admin.html`

**Files:**
- Modify: `templates/admin.html` — nueva tab + panel + JavaScript

Nota GateGuard antes de cada Edit:
1. Modifica `templates/admin.html` (1372 líneas)
2. Agrega tab button al nav de tabs y panel con tabla + modales
3. No lee/escribe datos — HTML+JS de interfaz
4. Instrucción: agregar sección CRUD de usuarios destilería al panel admin

- [ ] **Step 1: Agregar botón de tab Destilería**

En `templates/admin.html`, buscar el bloque de botones de tab (alrededor de línea 517-522) y agregar un botón nuevo al final de la lista:

```html
    <button class="tab-btn" onclick="switchTab('destileria')">Destilería</button>
```

- [ ] **Step 2: Agregar panel `tab-destileria`**

Buscar la línea que cierra el último panel de tab (antes del `<script>` principal). Insertar el panel nuevo:

```html
  <div id="tab-destileria" class="tab-panel">

    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div style="display:flex;align-items:center;gap:10px">
        <div style="width:28px;height:28px;background:linear-gradient(135deg,#c9a227,#a07800);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:14px">🥃</div>
        <div>
          <strong style="font-size:14px">Usuarios Destilería</strong>
          <span id="dest-count" style="font-size:11px;color:#8b949e;margin-left:8px"></span>
        </div>
      </div>
      <button class="btn-primary" onclick="openDestModal()">+ Nuevo usuario</button>
    </div>

    <div id="dest-msg" style="display:none;padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:13px"></div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Nombre</th><th>Email</th><th>Rol</th>
            <th>Marcas</th><th>Estado</th><th>Acciones</th>
          </tr>
        </thead>
        <tbody id="dest-tbody">
          <tr><td colspan="6" style="text-align:center;color:#8b949e;padding:24px">Cargando...</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Modal crear/editar -->
    <div id="dest-modal-overlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center">
      <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:28px;width:440px;max-width:95vw">
        <h3 id="dest-modal-title" style="margin-bottom:20px;font-size:16px">Nuevo usuario destilería</h3>
        <input type="hidden" id="dest-edit-email"/>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
          <div>
            <label style="display:block;font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">Nombre</label>
            <input id="dest-name" type="text" placeholder="Nombre completo" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;font-size:13px;color:#e6edf3"/>
          </div>
          <div>
            <label style="display:block;font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">Email</label>
            <input id="dest-email" type="email" placeholder="usuario@empresa.com" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;font-size:13px;color:#e6edf3"/>
          </div>
          <div id="dest-pass-field">
            <label style="display:block;font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">Contraseña temporal</label>
            <input id="dest-password" type="text" placeholder="Ej: Dest2026!" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;font-size:13px;color:#e6edf3"/>
          </div>
          <div>
            <label style="display:block;font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">Rol</label>
            <select id="dest-role" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;font-size:13px;color:#e6edf3">
              <option value="gerencia">Gerencia</option>
              <option value="editor">Editor</option>
              <option value="viewer" selected>Viewer</option>
            </select>
          </div>
          <div style="grid-column:1/-1">
            <label style="display:block;font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">Marcas</label>
            <select id="dest-brands" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;font-size:13px;color:#e6edf3">
              <option value="*">Todas</option>
              <option value="bosque">Bosque</option>
              <option value="feriado">Feriado</option>
              <option value="bosque,feriado">Bosque + Feriado</option>
            </select>
          </div>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px">
          <button onclick="closeDestModal()" style="background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:6px;padding:8px 18px;font-size:13px;cursor:pointer">Cancelar</button>
          <button onclick="saveDestUser()" style="background:linear-gradient(90deg,#c9a227,#a07800);color:#0d1117;border:none;border-radius:6px;padding:8px 18px;font-size:13px;font-weight:700;cursor:pointer">Guardar</button>
        </div>
      </div>
    </div>

    <!-- Modal reset password -->
    <div id="dest-reset-overlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center">
      <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:28px;width:360px;max-width:95vw">
        <h3 style="margin-bottom:16px;font-size:15px">Resetear contraseña</h3>
        <input type="hidden" id="dest-reset-email"/>
        <label style="display:block;font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Nueva contraseña temporal</label>
        <input id="dest-reset-pass" type="text" placeholder="Ej: NuevoPass2026!" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;font-size:13px;color:#e6edf3;margin-bottom:18px"/>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button onclick="closeResetModal()" style="background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:6px;padding:8px 18px;font-size:13px;cursor:pointer">Cancelar</button>
          <button onclick="confirmReset()" style="background:linear-gradient(90deg,#c9a227,#a07800);color:#0d1117;border:none;border-radius:6px;padding:8px 18px;font-size:13px;font-weight:700;cursor:pointer">Resetear</button>
        </div>
      </div>
    </div>

  </div><!-- /tab-destileria -->
```

- [ ] **Step 3: Agregar JavaScript de destilería antes del cierre `</script>`**

```javascript
    // ═══════════════════════════════════════════════════════════════
    // TAB DESTILERÍA — CRUD de usuarios
    // ═══════════════════════════════════════════════════════════════

    var destUsers = [];

    function loadDestUsers() {
      fetch('/admin/destileria/users')
        .then(function(r) { return r.json(); })
        .then(function(users) {
          destUsers = users;
          renderDestTable(users);
          var el = document.getElementById('dest-count');
          if (el) el.textContent = users.length + ' usuario' + (users.length !== 1 ? 's' : '');
        })
        .catch(function() { showDestMsg('Error cargando usuarios', false); });
    }

    function renderDestTable(users) {
      var tbody = document.getElementById('dest-tbody');
      if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8b949e;padding:24px">Sin usuarios registrados</td></tr>';
        return;
      }
      var ROLE_STYLE = {
        gerencia: 'background:rgba(201,162,39,0.15);color:#c9a227;border:1px solid rgba(201,162,39,0.3)',
        editor:   'background:rgba(59,130,246,0.15);color:#60a5fa;border:1px solid rgba(59,130,246,0.3)',
        viewer:   'background:rgba(107,114,128,0.15);color:#9ca3af;border:1px solid rgba(107,114,128,0.3)'
      };
      tbody.innerHTML = users.map(function(u) {
        var rs = ROLE_STYLE[u.role] || '';
        var as = u.active
          ? 'background:rgba(34,197,94,0.12);color:#4ade80;border:1px solid rgba(34,197,94,0.25)'
          : 'background:rgba(239,68,68,0.12);color:#f87171;border:1px solid rgba(239,68,68,0.25)';
        var brands = Array.isArray(u.brands) && u.brands[0] === '*' ? 'Todas' : (u.brands||[]).join(', ');
        var toggleBtn = u.active
          ? '<button onclick="toggleDestActive(\''+u.email+'\')" style="font-size:10px;font-weight:600;padding:4px 10px;border-radius:5px;border:1px solid rgba(239,68,68,0.35);color:#f87171;background:transparent;cursor:pointer">Desactivar</button>'
          : '<button onclick="toggleDestActive(\''+u.email+'\')" style="font-size:10px;font-weight:600;padding:4px 10px;border-radius:5px;border:1px solid rgba(34,197,94,0.35);color:#4ade80;background:transparent;cursor:pointer">Activar</button>';
        return '<tr>'+
          '<td><strong>'+u.name+'</strong></td>'+
          '<td style="font-size:12px;color:#8b949e">'+u.email+'</td>'+
          '<td><span style="display:inline-flex;font-size:10px;font-weight:700;padding:3px 8px;border-radius:12px;'+rs+'">'+u.role+'</span></td>'+
          '<td style="font-size:11px;color:#8b949e">'+brands+'</td>'+
          '<td><span style="display:inline-flex;font-size:10px;font-weight:700;padding:3px 8px;border-radius:12px;'+as+'">'+(u.active?'Activo':'Inactivo')+'</span></td>'+
          '<td><div style="display:flex;gap:6px">'+
            '<button onclick="openEditDest(\''+u.email+'\')" style="font-size:10px;font-weight:600;padding:4px 10px;border-radius:5px;border:1px solid rgba(59,130,246,0.35);color:#60a5fa;background:transparent;cursor:pointer">Editar</button>'+
            '<button onclick="openResetModal(\''+u.email+'\')" style="font-size:10px;font-weight:600;padding:4px 10px;border-radius:5px;border:1px solid rgba(201,162,39,0.35);color:#c9a227;background:transparent;cursor:pointer">Reset pass</button>'+
            toggleBtn+
          '</div></td>'+
        '</tr>';
      }).join('');
    }

    function openDestModal() {
      document.getElementById('dest-modal-title').textContent = 'Nuevo usuario destilería';
      document.getElementById('dest-edit-email').value = '';
      document.getElementById('dest-name').value = '';
      document.getElementById('dest-email').value = '';
      document.getElementById('dest-email').disabled = false;
      document.getElementById('dest-password').value = '';
      document.getElementById('dest-pass-field').style.display = '';
      document.getElementById('dest-role').value = 'viewer';
      document.getElementById('dest-brands').value = '*';
      document.getElementById('dest-modal-overlay').style.display = 'flex';
    }

    function openEditDest(email) {
      var u = destUsers.find(function(x){ return x.email === email; });
      if (!u) return;
      document.getElementById('dest-modal-title').textContent = 'Editar usuario';
      document.getElementById('dest-edit-email').value = email;
      document.getElementById('dest-name').value = u.name;
      document.getElementById('dest-email').value = email;
      document.getElementById('dest-email').disabled = true;
      document.getElementById('dest-pass-field').style.display = 'none';
      document.getElementById('dest-role').value = u.role;
      var bv = Array.isArray(u.brands) && u.brands[0]==='*' ? '*' : (u.brands||[]).join(',');
      document.getElementById('dest-brands').value = bv;
      document.getElementById('dest-modal-overlay').style.display = 'flex';
    }

    function closeDestModal() {
      document.getElementById('dest-modal-overlay').style.display = 'none';
    }

    function saveDestUser() {
      var editEmail = document.getElementById('dest-edit-email').value;
      var isEdit = !!editEmail;
      var bv = document.getElementById('dest-brands').value;
      var brands = bv === '*' ? ['*'] : bv.split(',');
      var body = {
        name: document.getElementById('dest-name').value.trim(),
        role: document.getElementById('dest-role').value,
        brands: brands,
        can_edit_objectives: document.getElementById('dest-role').value === 'gerencia'
      };
      var url, method;
      if (isEdit) {
        url = '/admin/destileria/users/' + encodeURIComponent(editEmail);
        method = 'PUT';
      } else {
        url = '/admin/destileria/users';
        method = 'POST';
        body.email = document.getElementById('dest-email').value.trim();
        body.password = document.getElementById('dest-password').value;
      }
      fetch(url, {
        method: method,
        headers: {'Content-Type':'application/json','X-CSRFToken':getCsrfToken()},
        body: JSON.stringify(body)
      }).then(function(r){ return r.json(); })
        .then(function(d){
          if (d.ok) { closeDestModal(); loadDestUsers(); showDestMsg(isEdit?'Usuario actualizado':'Usuario creado', true); }
          else { showDestMsg(d.error||'Error', false); }
        }).catch(function(){ showDestMsg('Error de red', false); });
    }

    function openResetModal(email) {
      document.getElementById('dest-reset-email').value = email;
      document.getElementById('dest-reset-pass').value = '';
      document.getElementById('dest-reset-overlay').style.display = 'flex';
    }

    function closeResetModal() {
      document.getElementById('dest-reset-overlay').style.display = 'none';
    }

    function confirmReset() {
      var email = document.getElementById('dest-reset-email').value;
      var pass = document.getElementById('dest-reset-pass').value;
      fetch('/admin/destileria/users/'+encodeURIComponent(email)+'/reset-password', {
        method: 'POST',
        headers: {'Content-Type':'application/json','X-CSRFToken':getCsrfToken()},
        body: JSON.stringify({password: pass})
      }).then(function(r){ return r.json(); })
        .then(function(d){
          if (d.ok) { closeResetModal(); showDestMsg('Contraseña reseteada', true); }
          else { showDestMsg('Error', false); }
        });
    }

    function toggleDestActive(email) {
      fetch('/admin/destileria/users/'+encodeURIComponent(email)+'/toggle-active', {
        method: 'POST',
        headers: {'X-CSRFToken':getCsrfToken()}
      }).then(function(r){ return r.json(); })
        .then(function(d){
          if (d.ok) { loadDestUsers(); showDestMsg(d.active?'Usuario activado':'Usuario desactivado', true); }
        });
    }

    function showDestMsg(text, ok) {
      var el = document.getElementById('dest-msg');
      el.textContent = text;
      el.style.cssText = 'display:block;padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:13px;' +
        (ok ? 'background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#4ade80'
            : 'background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#f87171');
      setTimeout(function(){ el.style.display='none'; }, 4000);
    }

    function getCsrfToken() {
      var m = document.cookie.match(/csrf_token=([^;]+)/);
      return m ? decodeURIComponent(m[1]) : '';
    }

    // Cargar usuarios cuando se activa la tab destilería
    (function(){
      var orig = switchTab;
      switchTab = function(tab) {
        orig(tab);
        if (tab === 'destileria') loadDestUsers();
      };
    })();
```

- [ ] **Step 4: Verificar visualmente**

Navegar a `/admin` → click en tab "Destilería". Verificar:
- Tabla carga usuarios desde `/admin/destileria/users`
- Botón "+ Nuevo usuario" abre el modal
- Botón "Editar" precarga los datos del usuario
- Botón "Reset pass" abre el modal de contraseña
- Botón "Desactivar/Activar" cambia el estado correctamente

- [ ] **Step 5: Commit**

```bash
git add templates/admin.html
git -c user.email="darwin.salinas@temple.com.ar" -c user.name="Darwin Salinas" \
  commit -m "feat: add Destileria tab to admin panel with full CRUD UI"
```

---

## Task 6: Test de humo end-to-end

- [ ] **Step 1: Suite completa de tests**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: todos PASSED

- [ ] **Step 2: Prueba manual del flujo completo**

1. `GET /` → debe redirigir a `/dashboard` (no a `/destileria`)
2. `GET /destileria` sin sesión → redirige a `/destileria/login`
3. Login con credenciales incorrectas → mensaje "Email o contraseña incorrectos"
4. Login con credenciales correctas → entra al tablero
5. `GET /admin` → tab "Destilería" → crear usuario con contraseña temporal
6. Cerrar sesión con `POST /destileria/logout` → redirige a `/destileria/login`
7. Login retail Google OAuth → llega a `/dashboard`, NO a `/destileria`

- [ ] **Step 3: Commit final si hubo ajustes**

```bash
git add -p
git -c user.email="darwin.salinas@temple.com.ar" -c user.name="Darwin Salinas" \
  commit -m "fix: post-e2e adjustments for destileria login"
```
