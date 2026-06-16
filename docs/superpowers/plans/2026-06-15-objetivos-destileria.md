# Gestión de Objetivos — Tablero Destilería Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar tab "Objetivos" al panel `/admin` donde el rol `gerencia` puede importar objetivos mensuales desde Excel/.xlsx o Google Sheets. Los objetivos se persisten en Firestore y el script de generación del dashboard los lee primero antes de intentar Drive.

**Architecture:** Se agrega `gerencia` a `VALID_ROLES` en `permissions.py` junto con funciones CRUD para la colección `objetivos_destileria`. El panel admin expone endpoints `GET/POST /api/admin/objectives` y `POST /api/admin/objectives/preview` protegidos por un nuevo decorator `require_admin` (superadmin OR gerencia). El script de generación inserta Firestore como paso 0 en su cadena de carga existente.

**Tech Stack:** Python 3.9+, Flask, Firestore (google-cloud-firestore), openpyxl>=3.1, google-api-python-client (Sheets API v4), Jinja2

**Spec:** `docs/superpowers/specs/2026-06-15-objetivos-destileria-design.md`

---

## File Map

| Archivo | Cambio |
|---------|--------|
| `permissions.py` | Agregar `gerencia` a `VALID_ROLES`; corregir `can_edit_objectives`; agregar `OBJECTIVES_COLLECTION`, `parse_flat_objectives`, `list_objectives`, `save_objectives` |
| `requirements.txt` | Agregar `openpyxl>=3.1` |
| `app.py` | Agregar `SA_KEY`, `require_admin` decorator, `_parse_xlsx_to_rows`, `_fetch_sheet_rows`; actualizar ruta `/admin` y admin link; agregar 3 endpoints de objectives |
| `templates/admin.html` | Tab "Objetivos" condicional por rol + panel con UI de importación |
| `generar_destileria_dashboard (1).py` | Agregar `load_objectives_from_firestore`; insertarlo como paso 0 en la cadena de carga |
| `tests/test_permissions.py` | Tests para rol gerencia, `parse_flat_objectives`, `list_objectives`, `save_objectives` |
| `tests/test_auth.py` | Tests para `require_admin`, endpoints de objectives |

---

## Task 1: Extender permissions.py — rol gerencia + CRUD de objetivos

**Files:**
- Modify: `permissions.py`
- Test: `tests/test_permissions.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_permissions.py`:

```python
# ---------------------------------------------------------------------------
# Rol gerencia
# ---------------------------------------------------------------------------

def test_gerencia_in_valid_roles():
    from permissions import VALID_ROLES
    assert "gerencia" in VALID_ROLES


def test_create_gerencia_user_sets_can_edit_objectives_true():
    from permissions import create_user
    doc_ref = MagicMock()
    doc_ref.get.return_value.exists = False
    db = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    result = create_user(db, "gerencia@temple.com.ar", "gerencia", ["*"])
    assert result["ok"] is True
    call_args = doc_ref.set.call_args[0][0]
    assert call_args["can_edit_objectives"] is True


# ---------------------------------------------------------------------------
# parse_flat_objectives
# ---------------------------------------------------------------------------

_HEADER = ["marca", "dimension", "nombre",
           "ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic"]

def _obj_row(marca="bosque", dim="product", nombre="bosque_nativo", vals=None):
    if vals is None:
        vals = ["100"] * 12
    return [marca, dim, nombre] + vals


def test_parse_flat_objectives_valid():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(vals=["100","110","120","130","140","150",
                                     "160","170","180","190","200","210"])]
    docs, errors = parse_flat_objectives(rows)
    assert errors == []
    assert len(docs) == 1
    assert docs[0]["marca"] == "bosque"
    assert docs[0]["nombre"] == "bosque_nativo"
    assert docs[0]["valores"] == [100,110,120,130,140,150,160,170,180,190,200,210]


def test_parse_flat_objectives_missing_column():
    from permissions import parse_flat_objectives
    rows = [["marca", "dimension", "nombre", "ene", "feb"], _obj_row(vals=["100","110"])]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("Faltan columnas" in e for e in errors)


def test_parse_flat_objectives_unknown_marca():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(marca="desconocida")]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("marca desconocida" in e for e in errors)


def test_parse_flat_objectives_duplicate_row():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(), _obj_row()]
    docs, errors = parse_flat_objectives(rows)
    assert len(docs) == 1
    assert any("duplicado" in e for e in errors)


def test_parse_flat_objectives_nonnumeric_value():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(vals=["ABC"] + ["100"] * 11)]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("no numérico" in e for e in errors)


def test_parse_flat_objectives_no_header():
    from permissions import parse_flat_objectives
    rows = [_obj_row()]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("encabezado" in e for e in errors)


def test_parse_flat_objectives_empty_values_become_zero():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(vals=["","110","120","130","140","150",
                                      "160","170","180","190","200","210"])]
    docs, errors = parse_flat_objectives(rows)
    assert errors == []
    assert docs[0]["valores"][0] == 0


def test_parse_flat_objectives_skips_empty_rows():
    from permissions import parse_flat_objectives
    rows = [_HEADER, ["","","","","","","","","","","","","","",""], _obj_row()]
    docs, errors = parse_flat_objectives(rows)
    assert len(docs) == 1
    assert errors == []


# ---------------------------------------------------------------------------
# list_objectives / save_objectives
# ---------------------------------------------------------------------------

def _make_stream_db(docs_data):
    mock_docs = []
    for doc_id, data in docs_data.items():
        d = MagicMock()
        d.id = doc_id
        d.to_dict.return_value = data
        d.reference = MagicMock()
        mock_docs.append(d)
    db = MagicMock()
    db.collection.return_value.stream.return_value = iter(mock_docs)
    return db


def test_list_objectives_returns_sorted_list():
    from permissions import list_objectives
    db = _make_stream_db({
        "feriado__product__feriado_rojo": {
            "marca": "feriado", "dimension": "product",
            "nombre": "feriado_rojo", "valores": [1]*12,
        },
        "bosque__product__bosque_nativo": {
            "marca": "bosque", "dimension": "product",
            "nombre": "bosque_nativo", "valores": [2]*12,
        },
    })
    result = list_objectives(db)
    assert len(result) == 2
    assert result[0]["marca"] == "bosque"
    assert result[1]["marca"] == "feriado"


def test_save_objectives_deletes_existing_and_writes_new():
    from permissions import save_objectives
    existing_doc = MagicMock()
    existing_doc.reference = MagicMock()
    db = MagicMock()
    db.collection.return_value.stream.return_value = iter([existing_doc])
    docs = [{"marca": "bosque", "dimension": "product",
             "nombre": "bosque_nativo", "valores": [100]*12}]
    result = save_objectives(db, docs, updated_by="test@temple.com.ar")
    assert result["ok"] is True
    assert result["count"] == 1
    existing_doc.reference.delete.assert_called_once()
    db.collection.return_value.document.return_value.set.assert_called_once()


def test_save_objectives_rejects_empty_docs():
    from permissions import save_objectives
    db = MagicMock()
    result = save_objectives(db, [], updated_by="test@temple.com.ar")
    assert result["ok"] is False
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py -k "gerencia or parse_flat or list_obj or save_obj" -v 2>&1 | tail -20
```

Expected: FAIL — "cannot import name 'parse_flat_objectives' from 'permissions'"

- [ ] **Step 3a: Cambiar VALID_ROLES en permissions.py (línea 32)**

```python
VALID_ROLES = ("superadmin", "gerencia", "editor", "viewer")
```

- [ ] **Step 3b: Corregir `can_edit_objectives` en `create_user` (~línea 159)**

Buscar `"can_edit_objectives": role == "editor"` y reemplazar con:

```python
"can_edit_objectives": role in ("editor", "gerencia"),
```

- [ ] **Step 3c: Corregir `can_edit_objectives` en `update_user` (~línea 207)**

Buscar `updates["can_edit_objectives"] = role == "editor"` y reemplazar con:

```python
updates["can_edit_objectives"] = role in ("editor", "gerencia")
```

- [ ] **Step 3d: Agregar al final de permissions.py (después de `delete_cluster_override`)**

```python
# ---------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------

OBJECTIVES_COLLECTION = "objetivos_destileria"
_VALID_MARCAS = {"bosque", "feriado", "cerveza"}
_MONTH_NAMES = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]


def parse_flat_objectives(rows: "list[list]") -> "tuple[list[dict], list[str]]":
    """
    Parsea filas en formato plano:
      marca | dimension | nombre | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic

    Returns:
        (docs, errors) — docs son dicts listos para Firestore, errors son strings descriptivos.
    """
    header_idx: Optional[int] = None
    col_idx: dict = {}
    for i, row in enumerate(rows):
        row_lower = [str(c).strip().lower() for c in row]
        if "marca" in row_lower:
            header_idx = i
            for j, name in enumerate(row_lower):
                if name not in col_idx:
                    col_idx[name] = j
            break

    if header_idx is None:
        return [], ["No se encontró fila de encabezado (debe contener 'marca')"]

    required = ["marca", "dimension", "nombre"] + _MONTH_NAMES
    missing = [c for c in required if c not in col_idx]
    if missing:
        return [], [f"Faltan columnas: {', '.join(missing)}"]

    docs: list = []
    errors: list = []
    seen: set = set()

    def _cell(row, col_name):
        idx = col_idx.get(col_name, -1)
        return str(row[idx]).strip() if 0 <= idx < len(row) else ""

    for i, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(str(c).strip() for c in row):
            continue

        marca = _cell(row, "marca").lower()
        dimension = _cell(row, "dimension").lower()
        nombre = _cell(row, "nombre")

        if not marca and not dimension and not nombre:
            continue

        if marca not in _VALID_MARCAS:
            errors.append(f"Fila {i}: marca desconocida '{marca}'")
            continue

        valores: list = []
        row_err = False
        for m in _MONTH_NAMES:
            raw = _cell(row, m)
            if raw in ("", "-"):
                valores.append(0)
            else:
                try:
                    valores.append(round(float(raw.replace(",", "."))))
                except ValueError:
                    errors.append(f"Fila {i}: valor no numérico en '{m}': '{raw}'")
                    row_err = True
                    break

        if row_err:
            continue

        key = (marca, dimension, nombre)
        if key in seen:
            errors.append(f"Fila {i}: duplicado '{marca}/{dimension}/{nombre}'")
            continue
        seen.add(key)

        docs.append({
            "marca": marca,
            "dimension": dimension,
            "nombre": nombre,
            "valores": valores,
        })

    return docs, errors


def list_objectives(db) -> "list[dict]":
    """Devuelve todos los objetivos de Firestore, ordenados por marca/dimension/nombre."""
    docs = db.collection(OBJECTIVES_COLLECTION).stream()
    result = [doc.to_dict() for doc in docs]
    return sorted(
        result,
        key=lambda x: (x.get("marca", ""), x.get("dimension", ""), x.get("nombre", "")),
    )


def save_objectives(db, docs: "list[dict]", updated_by: str) -> dict:
    """
    Reemplaza todos los objetivos en Firestore (replace completo).
    Borra la colección entera y escribe los nuevos documentos.

    Returns:
        {"ok": True, "count": N} o {"ok": False, "error": "..."}
    """
    if not docs:
        return {"ok": False, "error": "No hay datos para guardar"}

    for existing in db.collection(OBJECTIVES_COLLECTION).stream():
        existing.reference.delete()

    now = datetime.now(timezone.utc)
    for row in docs:
        doc_id = f"{row['marca']}__{row['dimension']}__{row['nombre']}"
        db.collection(OBJECTIVES_COLLECTION).document(doc_id).set({
            **row,
            "updated_at": now,
            "updated_by": updated_by,
        })

    logger.info("Objetivos guardados: %d filas por %s", len(docs), updated_by)
    return {"ok": True, "count": len(docs)}
```

- [ ] **Step 4: Verificar que todos los tests pasan**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_permissions.py -v 2>&1 | tail -20
```

Expected: todos en verde (incluidos los tests previos).

- [ ] **Step 5: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && git add permissions.py tests/test_permissions.py && git commit -m "feat: add gerencia role and objectives CRUD to permissions"
```

---

## Task 2: Agregar openpyxl a requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Agregar al final de requirements.txt**

```
openpyxl>=3.1
```

- [ ] **Step 2: Verificar instalación**

```bash
pip install openpyxl --quiet && python -c "import openpyxl; print('openpyxl', openpyxl.__version__)"
```

Expected: `openpyxl 3.x.x`

- [ ] **Step 3: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && git add requirements.txt && git commit -m "chore: add openpyxl for Excel parsing"
```

---

## Task 3: Actualizar app.py — require_admin + endpoints de objetivos

**Files:**
- Modify: `app.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_auth.py`:

```python
# ---------------------------------------------------------------------------
# require_admin — gerencia y superadmin pueden acceder a /admin
# ---------------------------------------------------------------------------

def _set_session(c, app, role="viewer"):
    with c.session_transaction() as sess:
        sess["user"] = {
            "email": f"{role}@temple.com.ar",
            "name": "Test",
            "picture": "",
            "role": role,
            "brands": ["*"],
            "can_edit_objectives": role in ("superadmin", "editor", "gerencia"),
        }


def test_admin_panel_allows_superadmin(client):
    c, app = client
    _set_session(c, app, role="superadmin")
    resp = c.get("/admin")
    assert resp.status_code == 200


def test_admin_panel_allows_gerencia(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    resp = c.get("/admin")
    assert resp.status_code == 200


def test_admin_panel_blocks_viewer(client):
    c, app = client
    _set_session(c, app, role="viewer")
    resp = c.get("/admin")
    assert resp.status_code == 403


def test_objectives_list_allows_gerencia(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    import app as flask_app
    mock_db = MagicMock()
    mock_db.collection.return_value.stream.return_value = iter([])
    with patch.object(flask_app, "_get_firestore_client", return_value=mock_db):
        resp = c.get("/api/admin/objectives")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_objectives_list_blocks_viewer(client):
    c, app = client
    _set_session(c, app, role="viewer")
    resp = c.get("/api/admin/objectives")
    assert resp.status_code == 403


def test_objectives_save_allows_gerencia(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    import app as flask_app
    mock_db = MagicMock()
    mock_db.collection.return_value.stream.return_value = iter([])
    docs = [{"marca": "bosque", "dimension": "product",
             "nombre": "bosque_nativo", "valores": [100]*12}]
    with patch.object(flask_app, "_get_firestore_client", return_value=mock_db):
        resp = c.post("/api/admin/objectives",
                      json={"rows": docs},
                      headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_objectives_save_blocks_editor(client):
    c, app = client
    _set_session(c, app, role="editor")
    resp = c.post("/api/admin/objectives", json={"rows": []})
    assert resp.status_code == 403
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_auth.py -k "admin_panel or objectives" -v 2>&1 | tail -20
```

Expected: FAIL — `test_admin_panel_allows_gerencia` da 403, endpoints de objectives dan 404.

- [ ] **Step 3a: Agregar SA_KEY en app.py**

Agregar después del bloque de imports, antes de `app = Flask(__name__)` (~línea 49):

```python
SA_KEY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temple-bar-439715-da51b292ce5d.json")
```

- [ ] **Step 3b: Agregar `require_admin` en app.py**

Agregar después de `require_superadmin` (~línea 114):

```python
def require_admin(f):
    """Permite acceso a superadmin o gerencia."""
    @wraps(f)
    def decorated_adm(*args, **kwargs):
        user = session.get("user")
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        if user.get("role") not in ("superadmin", "gerencia"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "forbidden"}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated_adm
```

- [ ] **Step 3c: Actualizar ruta `/admin` — cambiar decorator y pasar user_role**

Reemplazar la función `admin_panel` completa (~línea 415):

```python
@app.route("/admin")
@require_admin
def admin_panel():
    user = session["user"]
    brands = permissions.get_available_brands()
    return render_template("admin.html", brands=brands, user_role=user["role"])
```

- [ ] **Step 3d: Actualizar admin link en `/destileria` para gerencia**

Buscar `if user["role"] == "superadmin":` dentro de la ruta `destileria` y reemplazar con:

```python
if user["role"] in ("superadmin", "gerencia"):
```

- [ ] **Step 3e: Agregar helpers de objectives en app.py**

Agregar antes de `# Helpers for WhatsApp agent endpoints`:

```python
# ---------------------------------------------------------------------------
# Objectives helpers
# ---------------------------------------------------------------------------

def _parse_xlsx_to_rows(file_bytes: bytes) -> "list[list]":
    """Parsea bytes de un .xlsx y devuelve lista de listas de strings."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    return [
        [str(c) if c is not None else "" for c in row]
        for row in ws.iter_rows(values_only=True)
    ]


def _fetch_sheet_rows(sheet_url: str) -> "list[list]":
    """
    Lee filas de un Google Sheet via Sheets API v4.
    Usa SA key si está disponible, sino ADC.
    """
    import re
    import googleapiclient.discovery as disc

    match = re.search(r"spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not match:
        raise ValueError("URL inválida — debe contener 'spreadsheets/d/<ID>'")
    sheet_id = match.group(1)

    creds = None
    if os.path.exists(SA_KEY):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            SA_KEY,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )

    svc = disc.build("sheets", "v4", credentials=creds, cache_discovery=False)
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range="A:P"
    ).execute()
    return result.get("values", [])
```

- [ ] **Step 3f: Agregar endpoints de objectives en app.py**

Agregar después de la sección "Admin: Cluster management" (antes de `# Helpers for WhatsApp`):

```python
# ---------------------------------------------------------------------------
# Admin: Objectives management
# ---------------------------------------------------------------------------

@app.route("/api/admin/objectives", methods=["GET"])
@require_admin
def api_admin_list_objectives():
    """Lista todos los objetivos guardados en Firestore."""
    db = _get_firestore_client()
    objectives = permissions.list_objectives(db)
    return jsonify({"ok": True, "objectives": objectives})


@app.route("/api/admin/objectives/preview", methods=["POST"])
@require_admin
def api_admin_preview_objectives():
    """
    Parsea Excel o Sheets URL y devuelve preview + errores sin guardar.

    multipart/form-data → campo 'file' con el .xlsx
    application/json   → {"sheet_url": "..."}
    """
    content_type = request.content_type or ""

    if "multipart/form-data" in content_type:
        f = request.files.get("file")
        if not f:
            return jsonify({"ok": False, "error": "No se recibió archivo"}), 400
        try:
            rows = _parse_xlsx_to_rows(f.read())
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Error al leer Excel: {exc}"}), 400
    else:
        data = request.get_json(silent=True) or {}
        sheet_url = data.get("sheet_url", "").strip()
        if not sheet_url:
            return jsonify({"ok": False, "error": "sheet_url es requerido"}), 400
        try:
            rows = _fetch_sheet_rows(sheet_url)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Error al leer Sheet: {exc}"}), 400

    docs, errors = permissions.parse_flat_objectives(rows)
    return jsonify({"ok": True, "rows": docs, "errors": errors})


@app.route("/api/admin/objectives", methods=["POST"])
@require_admin
def api_admin_save_objectives():
    """Guarda filas de objetivos en Firestore (replace completo)."""
    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    if not rows:
        return jsonify({"ok": False, "error": "No hay filas para guardar"}), 400
    user_email = session["user"]["email"]
    db = _get_firestore_client()
    result = permissions.save_objectives(db, rows, updated_by=user_email)
    status = 200 if result["ok"] else 400
    return jsonify(result), status
```

- [ ] **Step 4: Verificar que todos los tests pasan**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/test_auth.py tests/test_permissions.py -v 2>&1 | tail -30
```

Expected: todos en verde.

- [ ] **Step 5: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && git add app.py tests/test_auth.py && git commit -m "feat: add require_admin and objectives API endpoints to app"
```

---

## Task 4: Agregar tab "Objetivos" a admin.html

**Files:**
- Modify: `templates/admin.html`

- [ ] **Step 1: Agregar badge CSS para gerencia**

Buscar `.badge-viewer { ... }` y agregar después:

```css
    .badge-gerencia  { background: rgba(52,211,153,0.18); color: #34d399; border: 1px solid rgba(52,211,153,0.4); }
```

- [ ] **Step 2: Agregar estilos CSS para el tab de objetivos**

Agregar antes del cierre `</style>`:

```css
    /* Objectives tab */
    .obj-import-section { display: flex; gap: 24px; margin-bottom: 28px; flex-wrap: wrap; }
    .obj-import-box {
      flex: 1; min-width: 260px;
      background: #161b22; border: 1px solid #21262d;
      border-radius: 8px; padding: 20px;
    }
    .obj-import-box h3 { font-size: 14px; font-weight: 600; color: #e6edf3; margin-bottom: 14px; }
    .obj-input {
      width: 100%; background: #0d1117; border: 1px solid #21262d;
      border-radius: 6px; color: #e6edf3; padding: 8px 12px;
      font-size: 13px; margin-bottom: 10px; box-sizing: border-box;
    }
    .obj-input:focus { outline: none; border-color: #58a6ff; }
    .btn-preview {
      background: #21262d; border: 1px solid #30363d; border-radius: 6px;
      color: #58a6ff; padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
    }
    .btn-preview:hover { background: #30363d; }
    .btn-save-obj {
      display: none; background: #1a7f37; border: none; border-radius: 6px;
      color: #fff; padding: 8px 18px; font-size: 13px; font-weight: 600;
      cursor: pointer; margin-top: 10px;
    }
    .btn-save-obj:hover { background: #238636; }
    .obj-preview-area { margin-top: 16px; overflow-x: auto; }
    .obj-preview-errors {
      background: #450a0a; border: 1px solid #7f1d1d; border-radius: 6px;
      color: #f87171; padding: 10px 14px; font-size: 12px; margin-top: 10px; display: none;
    }
    .obj-msg {
      display: none; padding: 10px 14px; border-radius: 6px;
      font-size: 13px; border: 1px solid transparent; margin-bottom: 12px;
    }
    .obj-msg.ok  { background: #052e16; border-color: #166534; color: #4ade80; }
    .obj-msg.err { background: #450a0a; border-color: #7f1d1d; color: #f87171; }
```

- [ ] **Step 3: Hacer tabs condicionales por rol**

Reemplazar el bloque `<div class="tab-nav">...</div>` completo:

```html
  <div class="tab-nav">
    {% if user_role == 'superadmin' %}
    <button class="tab-btn active" onclick="switchTab('usuarios')">Usuarios</button>
    <button class="tab-btn" onclick="switchTab('clusters')">Clusterizacion</button>
    {% endif %}
    <button class="tab-btn {% if user_role == 'gerencia' %}active{% endif %}" onclick="switchTab('objetivos')">Objetivos</button>
  </div>
```

- [ ] **Step 4: Envolver tabs existentes en condicional Jinja2**

Buscar `<!-- TAB: Usuarios` y envolver ambos panels (`tab-usuarios` y `tab-clusters`) así:

```html
  {% if user_role == 'superadmin' %}
  <!-- TAB: Usuarios -->
  <div id="tab-usuarios" class="tab-panel active">
    ... (contenido existente sin ningún cambio) ...
  </div>

  <!-- TAB: Clusterizacion -->
  <div id="tab-clusters" class="tab-panel">
    ... (contenido existente sin ningún cambio) ...
  </div>
  {% endif %}
```

- [ ] **Step 5: Agregar el panel #tab-objetivos**

Agregar inmediatamente después del `{% endif %}` del step 4, antes del `<script>`:

```html
  <!-- TAB: Objetivos -->
  <!-- ════════════════════════════════════════════════════════════ -->
  <div id="tab-objetivos" class="tab-panel {% if user_role == 'gerencia' %}active{% endif %}">

    <div id="obj-msg" class="obj-msg"></div>

    <div class="obj-import-section">

      <!-- Sub-flujo 1: Excel -->
      <div class="obj-import-box">
        <h3>Importar desde Excel (.xlsx)</h3>
        <p style="color:#8b949e;font-size:12px;margin-bottom:12px;">
          Formato de columnas:<br>
          <code style="color:#c9a227">marca | dimension | nombre | ene | feb | ... | dic</code>
        </p>
        <input type="file" id="obj-file-input" accept=".xlsx" class="obj-input" style="padding:6px;">
        <button class="btn-preview" onclick="previewExcel()">Vista previa</button>
        <button class="btn-save-obj" id="btn-save-file" onclick="saveObjectives('file')">Guardar en Firestore</button>
        <div class="obj-preview-errors" id="obj-file-errors"></div>
        <div class="obj-preview-area" id="obj-file-preview"></div>
      </div>

      <!-- Sub-flujo 2: Google Sheets -->
      <div class="obj-import-box">
        <h3>Importar desde Google Sheets</h3>
        <p style="color:#8b949e;font-size:12px;margin-bottom:12px;">
          Pegá la URL del Sheet con el mismo formato de columnas.
        </p>
        <input type="text" id="obj-sheet-url" class="obj-input"
               placeholder="https://docs.google.com/spreadsheets/d/...">
        <button class="btn-preview" onclick="previewSheet()">Leer Sheet</button>
        <button class="btn-save-obj" id="btn-save-sheet" onclick="saveObjectives('sheet')">Guardar en Firestore</button>
        <div class="obj-preview-errors" id="obj-sheet-errors"></div>
        <div class="obj-preview-area" id="obj-sheet-preview"></div>
      </div>

    </div>

    <h3 style="font-size:14px;font-weight:600;color:#8b949e;margin-bottom:12px;">
      Objetivos actuales en Firestore
    </h3>
    <div class="table-wrap" style="overflow-x:auto">
      <table id="obj-current-table">
        <thead>
          <tr>
            <th>Marca</th><th>Dim.</th><th>Nombre</th>
            <th>Ene</th><th>Feb</th><th>Mar</th><th>Abr</th><th>May</th><th>Jun</th>
            <th>Jul</th><th>Ago</th><th>Sep</th><th>Oct</th><th>Nov</th><th>Dic</th>
            <th>Actualizado por</th>
          </tr>
        </thead>
        <tbody id="obj-current-body">
          <tr><td colspan="17" style="color:#8b949e;text-align:center">Cargando...</td></tr>
        </tbody>
      </table>
    </div>

  </div>
```

- [ ] **Step 6: Agregar JS para objectives al inicio del bloque `<script>`**

Agregar inmediatamente después de `var CSRF_TOKEN = '{{ csrf_token() }}';`:

```javascript
    // ── Objectives tab ──────────────────────────────────────────────────────
    var _pendingRows = { file: null, sheet: null };

    function showObjMsg(text, type) {
      var el = document.getElementById('obj-msg');
      el.textContent = text;
      el.className = 'obj-msg ' + type;
      el.style.display = 'block';
      setTimeout(function() { el.style.display = 'none'; }, 5000);
    }

    function _renderPreview(rows, errorsEl, previewEl, saveBtn) {
      errorsEl.style.display = 'none';
      previewEl.innerHTML = '';
      saveBtn.style.display = 'none';
      if (!rows || rows.length === 0) {
        previewEl.innerHTML = '<p style="color:#8b949e;font-size:13px;margin-top:8px">Sin filas válidas.</p>';
        return;
      }
      var html = '<table style="font-size:12px;border-collapse:collapse;min-width:100%">'
        + '<thead><tr style="background:#161b22">'
        + '<th style="padding:6px 10px;text-align:left;color:#8b949e">Marca</th>'
        + '<th style="padding:6px 10px;text-align:left;color:#8b949e">Dim.</th>'
        + '<th style="padding:6px 10px;text-align:left;color:#8b949e">Nombre</th>'
        + '<th style="padding:6px 10px;text-align:right;color:#8b949e">Total año</th>'
        + '</tr></thead><tbody>';
      rows.forEach(function(r) {
        var total = (r.valores || []).reduce(function(a, b) { return a + b; }, 0);
        html += '<tr style="border-bottom:1px solid #21262d">'
          + '<td style="padding:5px 10px;color:#c9a227">' + (r.marca || '') + '</td>'
          + '<td style="padding:5px 10px;color:#8b949e">' + (r.dimension || '') + '</td>'
          + '<td style="padding:5px 10px">' + (r.nombre || '') + '</td>'
          + '<td style="padding:5px 10px;text-align:right">' + total.toLocaleString() + '</td>'
          + '</tr>';
      });
      html += '</tbody></table>';
      previewEl.innerHTML = html;
      saveBtn.style.display = 'inline-block';
    }

    function _renderErrors(errors, errorsEl) {
      if (!errors || errors.length === 0) { errorsEl.style.display = 'none'; return; }
      errorsEl.innerHTML = errors.map(function(e) { return '&#9888; ' + e; }).join('<br>');
      errorsEl.style.display = 'block';
    }

    function previewExcel() {
      var fi = document.getElementById('obj-file-input');
      var errEl = document.getElementById('obj-file-errors');
      var preEl = document.getElementById('obj-file-preview');
      var btn = document.getElementById('btn-save-file');
      if (!fi.files || !fi.files[0]) {
        errEl.innerHTML = 'Seleccioná un archivo .xlsx primero.';
        errEl.style.display = 'block';
        return;
      }
      var fd = new FormData();
      fd.append('file', fi.files[0]);
      fetch('/api/admin/objectives/preview', {
        method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN }, body: fd
      })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok) { errEl.innerHTML = '&#9888; ' + d.error; errEl.style.display = 'block'; return; }
        _pendingRows.file = d.rows;
        _renderErrors(d.errors, errEl);
        _renderPreview(d.rows, errEl, preEl, btn);
      })
      .catch(function(e) { errEl.innerHTML = '&#9888; Error: ' + e; errEl.style.display = 'block'; });
    }

    function previewSheet() {
      var url = document.getElementById('obj-sheet-url').value.trim();
      var errEl = document.getElementById('obj-sheet-errors');
      var preEl = document.getElementById('obj-sheet-preview');
      var btn = document.getElementById('btn-save-sheet');
      if (!url) { errEl.innerHTML = '&#9888; Ingresá la URL del Sheet.'; errEl.style.display = 'block'; return; }
      fetch('/api/admin/objectives/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ sheet_url: url })
      })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok) { errEl.innerHTML = '&#9888; ' + d.error; errEl.style.display = 'block'; return; }
        _pendingRows.sheet = d.rows;
        _renderErrors(d.errors, errEl);
        _renderPreview(d.rows, errEl, preEl, btn);
      })
      .catch(function(e) { errEl.innerHTML = '&#9888; Error: ' + e; errEl.style.display = 'block'; });
    }

    function saveObjectives(source) {
      var rows = _pendingRows[source];
      if (!rows || rows.length === 0) { showObjMsg('No hay datos en el preview para guardar.', 'err'); return; }
      fetch('/api/admin/objectives', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ rows: rows })
      })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.ok) {
          showObjMsg('✓ ' + d.count + ' objetivos guardados en Firestore.', 'ok');
          _pendingRows[source] = null;
          loadCurrentObjectives();
        } else {
          showObjMsg('Error: ' + d.error, 'err');
        }
      })
      .catch(function(e) { showObjMsg('Error de red: ' + e, 'err'); });
    }

    function loadCurrentObjectives() {
      var tbody = document.getElementById('obj-current-body');
      if (!tbody) return;
      fetch('/api/admin/objectives', { headers: { 'X-CSRFToken': CSRF_TOKEN } })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok || !d.objectives || d.objectives.length === 0) {
          tbody.innerHTML = '<tr><td colspan="17" style="color:#8b949e;text-align:center">Sin objetivos cargados.</td></tr>';
          return;
        }
        var html = '';
        d.objectives.forEach(function(obj) {
          var vals = obj.valores || [];
          html += '<tr>'
            + '<td style="color:#c9a227">' + (obj.marca||'') + '</td>'
            + '<td style="color:#8b949e">' + (obj.dimension||'') + '</td>'
            + '<td>' + (obj.nombre||'') + '</td>'
            + vals.map(function(v) { return '<td style="text-align:right">' + (v||0).toLocaleString() + '</td>'; }).join('')
            + '<td style="color:#8b949e;font-size:11px">' + (obj.updated_by||'-') + '</td>'
            + '</tr>';
        });
        tbody.innerHTML = html;
      })
      .catch(function() {
        tbody.innerHTML = '<tr><td colspan="17" style="color:#f87171;text-align:center">Error al cargar objetivos.</td></tr>';
      });
    }

    document.addEventListener('DOMContentLoaded', function() {
      loadCurrentObjectives();
    });
    // ── fin Objectives tab ──────────────────────────────────────────────────
```

- [ ] **Step 7: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && git add templates/admin.html && git commit -m "feat: add Objetivos tab to admin panel (gerencia role)"
```

---

## Task 5: Actualizar script de generación — Firestore primero

**Files:**
- Modify: `generar_destileria_dashboard (1).py`

- [ ] **Step 1: Agregar `load_objectives_from_firestore` después de `load_objectives_from_gcs` (~línea 131)**

```python
def load_objectives_from_firestore():
    """
    Carga objetivos desde Firestore (colección objetivos_destileria).
    Devuelve dict {marca: {dimension: {nombre: [12 vals]}}} o None si vacío/fallo.
    """
    try:
        from google.cloud import firestore as _fs
        db = _fs.Client()
        docs = list(db.collection("objetivos_destileria").stream())
        if not docs:
            return None
        result = {}
        for doc in docs:
            data = doc.to_dict()
            marca  = data.get("marca", "")
            dim    = data.get("dimension", "")
            nombre = data.get("nombre", "")
            vals   = data.get("valores", [])
            if not (marca and dim and nombre and len(vals) == 12):
                continue
            if marca not in result:
                result[marca] = {"product": {}, "cluster": {}}
            if dim not in result[marca]:
                result[marca][dim] = {}
            result[marca][dim][nombre] = vals
        return result if result else None
    except Exception as exc:
        print(f"WARN: load_objectives_from_firestore falló: {exc}", file=sys.stderr)
        return None
```

- [ ] **Step 2: Insertar como paso 0 en la cadena de carga**

Buscar `obj = None` (~línea 628) y reemplazar ese bloque inicial + el bloque de Drive con:

```python
    obj = None
    _obj_source = "none"

    # ── 0. Intentar desde Firestore (fuente de verdad si hay datos cargados) ─
    _fs_obj = load_objectives_from_firestore()
    if _fs_obj is not None:
        obj = _fs_obj
        _obj_source = "firestore"
        print(f"[{ts()}] Objetivos OK (desde Firestore)")

    # ── 1. Intentar desde Drive (solo si Firestore no tiene datos) ────────────
    if obj is None:
        try:
            obj = fetch_objectives(creds)
            _obj_source = "drive"
            print(f"[{ts()}] Objetivos OK (desde Drive)")
            _to_save = {**obj, "_meta": {
                "source": "drive",
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "file_id": SHEET_OBJ_ID,
            }}
            with open(OBJ_JSON_FILE, "w", encoding="utf-8") as fh:
                json.dump(_to_save, fh, ensure_ascii=False, indent=2)
            print(f"[{ts()}] JSON local de objetivos actualizado")
            if args.gcs_bucket:
                try:
                    save_objectives_to_gcs(_to_save, args.gcs_bucket)
                except Exception as _gcs_save_err:
                    print(f"WARN: No se pudo guardar objetivos en GCS: {_gcs_save_err}", file=sys.stderr)
        except Exception as exc:
            import traceback
            print(f"WARN: Drive falló: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
```

- [ ] **Step 3: Verificar que el script no tiene errores de sintaxis**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python3 -m py_compile "generar_destileria_dashboard (1).py" && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && git add "generar_destileria_dashboard (1).py" && git commit -m "feat: read objectives from Firestore first in generation script"
```

---

## Task 6: Smoke test y deploy

- [ ] **Step 1: Correr toda la suite de tests**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: todos en verde.

- [ ] **Step 2: Deploy a Cloud Run**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && gcloud run deploy temple-bar-dashboard --source . --region southamerica-east1 --project temple-bar-439715
```

Expected: URL del servicio sin errores.

- [ ] **Step 3: Crear usuario gerencia y verificar panel**

1. Loguearse como superadmin en `/admin`
2. Crear usuario con rol `gerencia` y marcas `["*"]`
3. Loguearse con ese usuario
4. Verificar que `/admin` muestra solo el tab "Objetivos" (sin Usuarios ni Clusterización)
5. Subir el Excel con el formato plano → ver preview → "Guardar en Firestore"
6. Verificar que la tabla "estado actual" se actualiza

- [ ] **Step 4: Verificar que el script usa Firestore tras la carga**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork" && python3 "generar_destileria_dashboard (1).py" --gcs-bucket temple-bar-dashboard-cache 2>&1 | grep -i "objetivo"
```

Expected: línea `Objetivos OK (desde Firestore)` si hay datos en Firestore.
