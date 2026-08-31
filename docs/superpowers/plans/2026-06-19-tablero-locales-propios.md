# Tablero Locales Propios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un tablero dinámico FastAPI+HTMX en Cloud Run que muestre KPIs operativos y financieros de Barrio Chino y Monroe lado a lado, con login por usuario/contraseña y panel admin para reclamos y distribuciones.

**Architecture:** FastAPI sirve HTML server-side con Jinja2. El filtro de período usa HTMX para actualizar solo el bloque de KPIs sin recargar la página. Los datos vienen de BigQuery (ventas), Google Sheets (P&L), Google Places API (rating) y Firestore (alertas, usuarios).

**Tech Stack:** Python 3.11, FastAPI, Jinja2, HTMX, bcrypt, itsdangerous, google-cloud-bigquery, google-auth, gspread, firebase-admin, httpx, pytest

**Spec:** `docs/superpowers/specs/2026-06-19-tablero-locales-propios-design.md`

---

## Estructura de archivos

```
Proyecto_Locales_Propios/
├── main.py                  # FastAPI app, todas las rutas
├── auth.py                  # bcrypt, sesiones con itsdangerous
├── config.py                # Variables de entorno, umbrales semáforo
├── cache.py                 # Cache en memoria con TTL
├── setup_admin.py           # Script one-shot para crear superadmin
├── data/
│   ├── __init__.py
│   ├── bigquery.py          # Ventas, ordenes, ticket desde BQ
│   ├── sheets.py            # P&L desde Google Sheets
│   ├── places.py            # Rating desde Google Places API
│   └── firestore.py         # Usuarios, reclamos, distribuciones
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── tablero.html
│   ├── kpis_partial.html    # Fragmento HTMX
│   └── admin.html
├── static/style.css
├── requirements.txt
├── .env.example
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_cache.py
    ├── test_auth.py
    ├── test_bigquery.py
    ├── test_sheets.py
    ├── test_places.py
    └── test_firestore.py
```

---

## Pre-requisitos (verificar antes de empezar)

- [ ] Verificar nombre del campo de local en BigQuery:
  ```sql
  SELECT DISTINCT nombre_local FROM `temple-bar-439715.curated_database.curated_sales` LIMIT 10
  ```
  Identificar el valor exacto para "Barrio Chino" y "Monroe". Ajustar `BQ_LOCAL_FIELD`, `BQ_LOCAL_BC`, `BQ_LOCAL_MONROE` en `.env`.

- [ ] Verificar nombre del campo de fecha y de orden en `curated_sales`:
  ```sql
  SELECT * FROM `temple-bar-439715.curated_database.curated_sales` LIMIT 1
  ```
  Confirmar: `fecha`, `orden_id`, `ventas_netas`. Si difieren, ajustar `data/bigquery.py` Task 5.

- [ ] Obtener Place IDs de cada local desde `https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder`.

- [ ] Confirmar que el SA de Cloud Run tiene roles: `BigQuery Data Viewer`, `Cloud Datastore User`, y que Sheets API está habilitada.

---

## Task 1: Setup del proyecto y config

**Files:**
- Create: `Proyecto_Locales_Propios/requirements.txt`
- Create: `Proyecto_Locales_Propios/config.py`
- Create: `Proyecto_Locales_Propios/tests/__init__.py`
- Create: `Proyecto_Locales_Propios/tests/test_config.py`

- [ ] **Step 1: Crear estructura de directorios**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork"
mkdir -p Proyecto_Locales_Propios/data
mkdir -p Proyecto_Locales_Propios/templates
mkdir -p Proyecto_Locales_Propios/static
mkdir -p Proyecto_Locales_Propios/tests
touch Proyecto_Locales_Propios/tests/__init__.py
touch Proyecto_Locales_Propios/data/__init__.py
```

- [ ] **Step 2: Crear `requirements.txt`**

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
jinja2==3.1.4
python-multipart==0.0.9
itsdangerous==2.2.0
bcrypt==4.1.3
google-cloud-bigquery==3.20.1
google-auth==2.29.0
gspread==6.1.2
firebase-admin==6.5.0
httpx==0.27.0
pytest==8.2.0
pytest-asyncio==0.23.6
```

- [ ] **Step 3: Escribir `tests/test_config.py`**

```python
# tests/test_config.py
import importlib
import pytest

def test_config_loads_required_vars(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet123")
    monkeypatch.setenv("PLACES_API_KEY", "key123")
    monkeypatch.setenv("PLACES_ID_BARRIO_CHINO", "place_bc")
    monkeypatch.setenv("PLACES_ID_MONROE", "place_mo")
    monkeypatch.setenv("SESSION_SECRET", "secret123")
    monkeypatch.setenv("FIRESTORE_PROJECT", "temple-bar-439715")
    monkeypatch.setenv("BQ_PROJECT", "temple-bar-439715")
    monkeypatch.setenv("BQ_DATASET", "curated_database")
    monkeypatch.setenv("BQ_TABLE", "curated_sales")

    import config
    importlib.reload(config)

    assert config.GOOGLE_SHEETS_ID == "sheet123"
    assert config.SESSION_SECRET == "secret123"
    assert config.SEMAFORO_CMV_VERDE < config.SEMAFORO_CMV_AMARILLO
    assert config.SEMAFORO_LABORAL_VERDE < config.SEMAFORO_LABORAL_AMARILLO

def test_semaforo_defaults_son_razonables():
    import config
    assert 0 < config.SEMAFORO_CMV_VERDE < 1
    assert 0 < config.SEMAFORO_LABORAL_VERDE < 1
```

- [ ] **Step 4: Correr test — debe fallar**

```bash
cd Proyecto_Locales_Propios
pip install -r requirements.txt
pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Crear `config.py`**

```python
# config.py
import os

GOOGLE_SHEETS_ID = os.environ["GOOGLE_SHEETS_ID"]
PLACES_API_KEY = os.environ["PLACES_API_KEY"]
PLACES_ID_BARRIO_CHINO = os.environ["PLACES_ID_BARRIO_CHINO"]
PLACES_ID_MONROE = os.environ["PLACES_ID_MONROE"]
SESSION_SECRET = os.environ["SESSION_SECRET"]
FIRESTORE_PROJECT = os.environ["FIRESTORE_PROJECT"]
BQ_PROJECT = os.environ["BQ_PROJECT"]
BQ_DATASET = os.environ["BQ_DATASET"]
BQ_TABLE = os.environ["BQ_TABLE"]
BQ_LOCAL_FIELD = os.environ.get("BQ_LOCAL_FIELD", "nombre_local")
BQ_LOCAL_BC = os.environ.get("BQ_LOCAL_BC", "Barrio Chino")
BQ_LOCAL_MONROE = os.environ.get("BQ_LOCAL_MONROE", "Monroe")

# Semáforo CMV: verde < 30%, amarillo 30-35%, rojo > 35%
SEMAFORO_CMV_VERDE = float(os.environ.get("SEMAFORO_CMV_VERDE", "0.30"))
SEMAFORO_CMV_AMARILLO = float(os.environ.get("SEMAFORO_CMV_AMARILLO", "0.35"))

# Semáforo Costo Laboral: verde < 25%, amarillo 25-30%, rojo > 30%
SEMAFORO_LABORAL_VERDE = float(os.environ.get("SEMAFORO_LABORAL_VERDE", "0.25"))
SEMAFORO_LABORAL_AMARILLO = float(os.environ.get("SEMAFORO_LABORAL_AMARILLO", "0.30"))
```

- [ ] **Step 6: Correr tests — deben pasar**

```bash
pytest tests/test_config.py -v
```
Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git init
git add requirements.txt config.py tests/
git commit -m "feat: project setup y config con umbrales semáforo"
```

---

## Task 2: Cache en memoria con TTL

**Files:**
- Create: `Proyecto_Locales_Propios/cache.py`
- Create: `Proyecto_Locales_Propios/tests/test_cache.py`

- [ ] **Step 1: Escribir `tests/test_cache.py`**

```python
# tests/test_cache.py
import time
from cache import TTLCache

def test_almacena_valor():
    c = TTLCache(ttl_seconds=60)
    c.set("k", {"x": 1})
    assert c.get("k") == {"x": 1}

def test_retorna_none_si_no_existe():
    c = TTLCache(ttl_seconds=60)
    assert c.get("noexiste") is None

def test_expira_despues_del_ttl():
    c = TTLCache(ttl_seconds=1)
    c.set("k", "val")
    time.sleep(1.1)
    assert c.get("k") is None

def test_sobreescribe_valor():
    c = TTLCache(ttl_seconds=60)
    c.set("k", "primero")
    c.set("k", "segundo")
    assert c.get("k") == "segundo"

def test_invalida_clave():
    c = TTLCache(ttl_seconds=60)
    c.set("k", "val")
    c.invalidate("k")
    assert c.get("k") is None
```

- [ ] **Step 2: Correr tests — deben fallar**

```bash
pytest tests/test_cache.py -v
```
Expected: `ModuleNotFoundError: No module named 'cache'`

- [ ] **Step 3: Crear `cache.py`**

```python
# cache.py
import time
from typing import Any

class TTLCache:
    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.time() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


# Instancias globales usadas por main.py
bq_cache = TTLCache(ttl_seconds=1800)       # 30 min
sheets_cache = TTLCache(ttl_seconds=21600)  # 6 horas
places_cache = TTLCache(ttl_seconds=86400)  # 24 horas
```

- [ ] **Step 4: Correr tests — deben pasar**

```bash
pytest tests/test_cache.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add cache.py tests/test_cache.py
git commit -m "feat: cache en memoria con TTL"
```

---

## Task 3: Auth — bcrypt + sesiones con cookie firmada

**Files:**
- Create: `Proyecto_Locales_Propios/auth.py`
- Create: `Proyecto_Locales_Propios/tests/test_auth.py`

- [ ] **Step 1: Escribir `tests/test_auth.py`**

```python
# tests/test_auth.py
import os
os.environ.setdefault("SESSION_SECRET", "test-secret")

from auth import hash_password, verify_password, create_session_token, decode_session_token

def test_hash_es_diferente_al_original():
    h = hash_password("mi_password")
    assert h != "mi_password"
    assert h.startswith("$2b$")

def test_verify_password_correcta():
    h = hash_password("secreto123")
    assert verify_password("secreto123", h) is True

def test_verify_password_incorrecta():
    h = hash_password("secreto123")
    assert verify_password("otro", h) is False

def test_session_token_roundtrip():
    token = create_session_token("user@temple.com.ar", "superadmin")
    data = decode_session_token(token)
    assert data["email"] == "user@temple.com.ar"
    assert data["role"] == "superadmin"

def test_token_invalido_retorna_none():
    assert decode_session_token("basura") is None

def test_token_manipulado_retorna_none():
    token = create_session_token("u@t.com", "viewer")
    assert decode_session_token(token[:-5] + "XXXXX") is None
```

- [ ] **Step 2: Correr tests — deben fallar**

```bash
pytest tests/test_auth.py -v
```
Expected: `ModuleNotFoundError: No module named 'auth'`

- [ ] **Step 3: Crear `auth.py`**

```python
# auth.py
import os
import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from typing import Optional

_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-in-prod")
_serializer = URLSafeTimedSerializer(_SECRET)
SESSION_COOKIE = "lp_session"
SESSION_MAX_AGE = 60 * 60 * 8  # 8 horas


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_token(email: str, role: str) -> str:
    return _serializer.dumps({"email": email, "role": role})


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
```

- [ ] **Step 4: Correr tests — deben pasar**

```bash
pytest tests/test_auth.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add auth.py tests/test_auth.py
git commit -m "feat: auth con bcrypt y sesiones firmadas con itsdangerous"
```

---

## Task 4: Capa Firestore — usuarios, reclamos, distribuciones

**Files:**
- Create: `Proyecto_Locales_Propios/data/firestore.py`
- Create: `Proyecto_Locales_Propios/tests/test_firestore.py`

- [ ] **Step 1: Escribir `tests/test_firestore.py`**

```python
# tests/test_firestore.py
from unittest.mock import MagicMock, patch

@patch("data.firestore._db")
def test_get_user_existente(mock_db):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"role": "viewer", "password_hash": "$2b$12$abc"}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    from data.firestore import get_user
    user = get_user("user@temple.com.ar")
    assert user["role"] == "viewer"

@patch("data.firestore._db")
def test_get_user_inexistente(mock_db):
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    from data.firestore import get_user
    assert get_user("noexiste@temple.com.ar") is None

@patch("data.firestore._db")
def test_get_reclamos_activos_filtra_cerrados(mock_db):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "reclamos": [
            {"id": "r1", "texto": "Problema", "fecha": "2026-06-01", "estado": "activo", "cerrado_at": None},
            {"id": "r2", "texto": "Resuelto", "fecha": "2026-05-01", "estado": "cerrado", "cerrado_at": "2026-05-02"},
        ],
        "distribuciones": []
    }
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    from data.firestore import get_reclamos_activos
    activos = get_reclamos_activos("barrio_chino")
    assert len(activos) == 1
    assert activos[0]["id"] == "r1"

@patch("data.firestore._db")
def test_get_distribuciones_pendientes_filtra_pagados(mock_db):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "reclamos": [],
        "distribuciones": [
            {"id": "d1", "monto": 2500000, "descripcion": "Retiro socio", "fecha": "2026-06-01", "estado": "pendiente", "pagado_at": None},
            {"id": "d2", "monto": 1000000, "descripcion": "Pago anterior", "fecha": "2026-05-01", "estado": "pagado", "pagado_at": "2026-05-15"},
        ]
    }
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    from data.firestore import get_distribuciones_pendientes
    pendientes = get_distribuciones_pendientes("barrio_chino")
    assert len(pendientes) == 1
    assert pendientes[0]["id"] == "d1"
```

- [ ] **Step 2: Correr tests — deben fallar**

```bash
pytest tests/test_firestore.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.firestore'`

- [ ] **Step 3: Crear `data/firestore.py`**

```python
# data/firestore.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional
import firebase_admin
from firebase_admin import firestore

if not firebase_admin._apps:
    firebase_admin.initialize_app()

_db = firestore.client()

COLLECTION_USERS = "users_config"
COLLECTION_LOCALES = "locales_config"


def get_user(email: str) -> Optional[dict]:
    doc = _db.collection(COLLECTION_USERS).document(email.lower()).get()
    return doc.to_dict() if doc.exists else None


def create_user(email: str, password_hash: str, role: str) -> None:
    now = datetime.now(timezone.utc)
    _db.collection(COLLECTION_USERS).document(email.lower()).set({
        "role": role,
        "password_hash": password_hash,
        "created_at": now,
        "updated_at": now,
    })


def update_user(email: str, **fields) -> None:
    fields["updated_at"] = datetime.now(timezone.utc)
    _db.collection(COLLECTION_USERS).document(email.lower()).update(fields)


def delete_user(email: str) -> None:
    _db.collection(COLLECTION_USERS).document(email.lower()).delete()


def list_users() -> list[dict]:
    docs = _db.collection(COLLECTION_USERS).stream()
    return [{"email": d.id, **d.to_dict()} for d in docs]


def _get_local_doc(local_id: str) -> dict:
    doc = _db.collection(COLLECTION_LOCALES).document(local_id).get()
    return doc.to_dict() if doc.exists else {"reclamos": [], "distribuciones": []}


def _save_local_doc(local_id: str, data: dict) -> None:
    _db.collection(COLLECTION_LOCALES).document(local_id).set(data)


def get_reclamos_activos(local_id: str) -> list[dict]:
    return [r for r in _get_local_doc(local_id).get("reclamos", []) if r["estado"] == "activo"]


def get_reclamos_todos(local_id: str) -> list[dict]:
    return _get_local_doc(local_id).get("reclamos", [])


def add_reclamo(local_id: str, texto: str, fecha: str) -> None:
    data = _get_local_doc(local_id)
    data.setdefault("reclamos", []).append({
        "id": str(uuid.uuid4()), "texto": texto, "fecha": fecha,
        "estado": "activo", "cerrado_at": None,
    })
    _save_local_doc(local_id, data)


def cerrar_reclamo(local_id: str, reclamo_id: str) -> None:
    data = _get_local_doc(local_id)
    for r in data.get("reclamos", []):
        if r["id"] == reclamo_id:
            r["estado"] = "cerrado"
            r["cerrado_at"] = datetime.now(timezone.utc).isoformat()
    _save_local_doc(local_id, data)


def get_distribuciones_pendientes(local_id: str) -> list[dict]:
    return [d for d in _get_local_doc(local_id).get("distribuciones", []) if d["estado"] == "pendiente"]


def get_distribuciones_todas(local_id: str) -> list[dict]:
    return _get_local_doc(local_id).get("distribuciones", [])


def add_distribucion(local_id: str, monto: float, descripcion: str, fecha: str) -> None:
    data = _get_local_doc(local_id)
    data.setdefault("distribuciones", []).append({
        "id": str(uuid.uuid4()), "monto": monto, "descripcion": descripcion,
        "fecha": fecha, "estado": "pendiente", "pagado_at": None,
    })
    _save_local_doc(local_id, data)


def marcar_pagado(local_id: str, dist_id: str) -> None:
    data = _get_local_doc(local_id)
    for d in data.get("distribuciones", []):
        if d["id"] == dist_id:
            d["estado"] = "pagado"
            d["pagado_at"] = datetime.now(timezone.utc).isoformat()
    _save_local_doc(local_id, data)
```

- [ ] **Step 4: Correr tests — deben pasar**

```bash
pytest tests/test_firestore.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add data/firestore.py tests/test_firestore.py
git commit -m "feat: capa Firestore para usuarios, reclamos y distribuciones"
```

---

## Task 5: Capa BigQuery — ventas, ordenes, ticket promedio

**Files:**
- Create: `Proyecto_Locales_Propios/data/bigquery.py`
- Create: `Proyecto_Locales_Propios/tests/test_bigquery.py`

- [ ] **Step 1: Escribir `tests/test_bigquery.py`**

```python
# tests/test_bigquery.py
import os
os.environ.setdefault("GOOGLE_SHEETS_ID", "x")
os.environ.setdefault("PLACES_API_KEY", "x")
os.environ.setdefault("PLACES_ID_BARRIO_CHINO", "x")
os.environ.setdefault("PLACES_ID_MONROE", "x")
os.environ.setdefault("SESSION_SECRET", "x")
os.environ.setdefault("FIRESTORE_PROJECT", "x")
os.environ.setdefault("BQ_PROJECT", "temple-bar-439715")
os.environ.setdefault("BQ_DATASET", "curated_database")
os.environ.setdefault("BQ_TABLE", "curated_sales")

from unittest.mock import MagicMock, patch
from data.bigquery import get_ventas_local, PeriodoVentas

def _mock_row(ventas, ordenes, ticket):
    row = MagicMock()
    row.ventas_netas = ventas
    row.num_ordenes = ordenes
    row.ticket_promedio = ticket
    return row

@patch("data.bigquery._get_client")
def test_get_ventas_mes(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.query.return_value.result.return_value = [_mock_row(197_600_000, 23382, 8450)]

    r = get_ventas_local("barrio_chino", PeriodoVentas.MES, 2026, 5)
    assert r["ventas_netas"] == 197_600_000
    assert r["num_ordenes"] == 23382
    assert r["ticket_promedio"] == 8450

@patch("data.bigquery._get_client")
def test_get_ventas_ytd(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.query.return_value.result.return_value = [_mock_row(900_000_000, 100000, 9000)]

    r = get_ventas_local("barrio_chino", PeriodoVentas.YTD, 2026, 5)
    assert r["ventas_netas"] == 900_000_000

@patch("data.bigquery._get_client")
def test_sin_datos_retorna_ceros(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.query.return_value.result.return_value = []

    r = get_ventas_local("monroe", PeriodoVentas.MES, 2026, 6)
    assert r == {"ventas_netas": 0, "num_ordenes": 0, "ticket_promedio": 0}
```

- [ ] **Step 2: Correr tests — deben fallar**

```bash
pytest tests/test_bigquery.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.bigquery'`

- [ ] **Step 3: Crear `data/bigquery.py`**

```python
# data/bigquery.py
from __future__ import annotations
from enum import Enum
import config
from google.cloud import bigquery

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = bigquery.Client(project=config.BQ_PROJECT)
    return _client


class PeriodoVentas(Enum):
    MES = "mes"
    YTD = "ytd"


_LOCAL_MAP = {
    "barrio_chino": config.BQ_LOCAL_BC,
    "monroe": config.BQ_LOCAL_MONROE,
}


def get_ventas_local(local_id: str, periodo: PeriodoVentas, anio: int, mes: int) -> dict:
    local_nombre = _LOCAL_MAP[local_id]
    tabla = f"`{config.BQ_PROJECT}.{config.BQ_DATASET}.{config.BQ_TABLE}`"

    if periodo == PeriodoVentas.MES:
        filtro = f"EXTRACT(YEAR FROM fecha) = {anio} AND EXTRACT(MONTH FROM fecha) = {mes}"
    else:
        filtro = f"EXTRACT(YEAR FROM fecha) = {anio} AND EXTRACT(MONTH FROM fecha) <= {mes}"

    query = f"""
        SELECT
            SUM(ventas_netas)                           AS ventas_netas,
            COUNT(DISTINCT orden_id)                    AS num_ordenes,
            SAFE_DIVIDE(SUM(ventas_netas),
                        COUNT(DISTINCT orden_id))       AS ticket_promedio
        FROM {tabla}
        WHERE {config.BQ_LOCAL_FIELD} = @local_nombre
          AND {filtro}
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("local_nombre", "STRING", local_nombre)
    ])
    rows = list(_get_client().query(query, job_config=job_config).result())

    if not rows or rows[0].ventas_netas is None:
        return {"ventas_netas": 0, "num_ordenes": 0, "ticket_promedio": 0}

    row = rows[0]
    return {
        "ventas_netas": float(row.ventas_netas or 0),
        "num_ordenes": int(row.num_ordenes or 0),
        "ticket_promedio": float(row.ticket_promedio or 0),
    }
```

> **Nota:** si los campos en BQ se llaman diferente a `fecha`, `orden_id` o `ventas_netas`, ajustar la query acá según lo verificado en pre-requisitos.

- [ ] **Step 4: Correr tests — deben pasar**

```bash
pytest tests/test_bigquery.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add data/bigquery.py tests/test_bigquery.py
git commit -m "feat: capa BigQuery para ventas, ordenes y ticket promedio"
```

---

## Task 6: Capa Google Sheets — P&L (CMV, laboral, EBITDA, resultado, caja)

**Files:**
- Create: `Proyecto_Locales_Propios/data/sheets.py`
- Create: `Proyecto_Locales_Propios/tests/test_sheets.py`

- [ ] **Step 1: Escribir `tests/test_sheets.py`**

```python
# tests/test_sheets.py
import os
os.environ.setdefault("GOOGLE_SHEETS_ID", "x")
os.environ.setdefault("PLACES_API_KEY", "x")
os.environ.setdefault("PLACES_ID_BARRIO_CHINO", "x")
os.environ.setdefault("PLACES_ID_MONROE", "x")
os.environ.setdefault("SESSION_SECRET", "x")
os.environ.setdefault("FIRESTORE_PROJECT", "x")
os.environ.setdefault("BQ_PROJECT", "x")
os.environ.setdefault("BQ_DATASET", "x")
os.environ.setdefault("BQ_TABLE", "x")

import pytest
from unittest.mock import MagicMock, patch
from data.sheets import get_pl_local, PeriodoSheets

# Columnas: col0=label, col1=Ene_val, col2=Ene_pct, col3=Feb_val, ..., col15=Total2026_val
MOCK_ROWS = [
    ["Ingresos por Ventas", "197600000", "100%", "264000000", "100%", "0","0","0","0","0","0","0","0","0","0", "1208000000", ""],
    ["Costo Mercadería",    "58700000",  "29.7%","82000000",  "31%",  "0","0","0","0","0","0","0","0","0","0", "360000000",  ""],
    ["Total Costo Laboral", "45200000",  "22.9%","59000000",  "22.4%","0","0","0","0","0","0","0","0","0","0", "290000000",  ""],
    ["EBITDA",              "9400000",   "4.8%", "14600000",  "5.5%", "0","0","0","0","0","0","0","0","0","0", "63000000",   ""],
    ["Resultado Operativo", "9400000",   "4.8%", "14600000",  "5.5%", "0","0","0","0","0","0","0","0","0","0", "57000000",   ""],
    ["Caja Generada",       "8300000",   "4.2%", "8400000",   "3.2%", "0","0","0","0","0","0","0","0","0","0", "40000000",   ""],
    ["Total 2026",          "",          "",     "",           "",     "","","","","","","","","","",  "",       ""],
]

@patch("data.sheets._get_worksheet")
def test_get_pl_mes_enero(mock_ws_fn):
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = MOCK_ROWS
    mock_ws_fn.return_value = mock_ws

    pl = get_pl_local("barrio_chino", PeriodoSheets.MES, 2026, 1)
    assert pl["ventas_netas"] == 197_600_000
    assert pl["cmv_pct"] == pytest.approx(0.297, abs=0.001)
    assert pl["laboral_pct"] == pytest.approx(0.229, abs=0.001)
    assert pl["ebitda_pct"] == pytest.approx(0.048, abs=0.001)
    assert pl["resultado_operativo"] == 9_400_000
    assert pl["caja_generada"] == 8_300_000

@patch("data.sheets._get_worksheet")
def test_get_pl_ytd(mock_ws_fn):
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = MOCK_ROWS
    mock_ws_fn.return_value = mock_ws

    pl = get_pl_local("barrio_chino", PeriodoSheets.YTD, 2026, 5)
    assert pl["ventas_netas"] == 1_208_000_000
```

- [ ] **Step 2: Correr tests — deben fallar**

```bash
pytest tests/test_sheets.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.sheets'`

- [ ] **Step 3: Crear `data/sheets.py`**

```python
# data/sheets.py
from __future__ import annotations
from enum import Enum
import gspread
from google.auth import default
import config

_gc = None
_worksheets: dict[str, gspread.Worksheet] = {}

SHEET_NAME_MAP = {
    "barrio_chino": "P&L Barrio Chino",
    "monroe": "P&L Monroe",
}

ROW_LABELS = {
    "ventas_netas":       "ingresos por ventas",
    "cmv":                "costo mercadería",
    "laboral":            "total costo laboral",
    "ebitda":             "ebitda",
    "resultado_operativo":"resultado operativo",
    "caja_generada":      "caja generada",
}


class PeriodoSheets(Enum):
    MES = "mes"
    YTD = "ytd"


def _get_client():
    global _gc
    if _gc is None:
        creds, _ = default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        _gc = gspread.authorize(creds)
    return _gc


def _get_worksheet(local_id: str) -> gspread.Worksheet:
    if local_id not in _worksheets:
        sh = _get_client().open_by_key(config.GOOGLE_SHEETS_ID)
        _worksheets[local_id] = sh.worksheet(SHEET_NAME_MAP[local_id])
    return _worksheets[local_id]


def _parse_number(s: str) -> float:
    s = s.strip().rstrip("%").replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_row(rows: list[list[str]], label_key: str) -> list[str] | None:
    label = ROW_LABELS[label_key]
    for row in rows:
        if row and label in row[0].lower():
            return row
    return None


def _mes_col(mes: int) -> int:
    """Columna de valor para el mes N (1=Ene). col1=Ene, col3=Feb, col5=Mar..."""
    return 1 + (mes - 1) * 2


def _ytd_col(rows: list[list[str]]) -> int:
    """Busca columna 'Total 2026' en las primeras filas."""
    for row in rows[:5]:
        for i, cell in enumerate(row):
            if "total" in cell.lower() and "2026" in cell:
                return i
    return -2  # fallback: penúltima columna


def get_pl_local(local_id: str, periodo: PeriodoSheets, anio: int, mes: int) -> dict:
    ws = _get_worksheet(local_id)
    rows = ws.get_all_values()

    val_col = _mes_col(mes) if periodo == PeriodoSheets.MES else _ytd_col(rows)

    def val(label_key: str) -> float:
        row = _find_row(rows, label_key)
        return _parse_number(row[val_col]) if row and val_col < len(row) else 0.0

    ventas = val("ventas_netas")
    cmv_val = val("cmv")
    lab_val = val("laboral")

    return {
        "ventas_netas":       ventas,
        "cmv_pct":            cmv_val / ventas if ventas else 0.0,
        "laboral_pct":        lab_val / ventas if ventas else 0.0,
        "ebitda_pct":         val("ebitda") / ventas if ventas else 0.0,
        "resultado_operativo":val("resultado_operativo"),
        "caja_generada":      val("caja_generada"),
    }
```

- [ ] **Step 4: Correr tests — deben pasar**

```bash
pytest tests/test_sheets.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add data/sheets.py tests/test_sheets.py
git commit -m "feat: capa Google Sheets para P&L (CMV, laboral, EBITDA, resultado, caja)"
```

---

## Task 7: Capa Google Places — rating y reviews

**Files:**
- Create: `Proyecto_Locales_Propios/data/places.py`
- Create: `Proyecto_Locales_Propios/tests/test_places.py`

- [ ] **Step 1: Escribir `tests/test_places.py`**

```python
# tests/test_places.py
import os
os.environ.setdefault("PLACES_API_KEY", "test_key")
os.environ.setdefault("GOOGLE_SHEETS_ID","x"); os.environ.setdefault("PLACES_ID_BARRIO_CHINO","x")
os.environ.setdefault("PLACES_ID_MONROE","x"); os.environ.setdefault("SESSION_SECRET","x")
os.environ.setdefault("FIRESTORE_PROJECT","x"); os.environ.setdefault("BQ_PROJECT","x")
os.environ.setdefault("BQ_DATASET","x"); os.environ.setdefault("BQ_TABLE","x")

from unittest.mock import patch, MagicMock
from data.places import get_rating

@patch("data.places.httpx.get")
def test_get_rating_ok(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"result": {"rating": 4.6, "user_ratings_total": 1243}, "status": "OK"}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    r = get_rating("ChIJabc123")
    assert r["rating"] == 4.6
    assert r["total_reviews"] == 1243

@patch("data.places.httpx.get")
def test_get_rating_not_found_retorna_none(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "NOT_FOUND"}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    assert get_rating("invalido") is None
```

- [ ] **Step 2: Correr tests — deben fallar**

```bash
pytest tests/test_places.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.places'`

- [ ] **Step 3: Crear `data/places.py`**

```python
# data/places.py
from __future__ import annotations
from typing import Optional
import httpx
import config

PLACES_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def get_rating(place_id: str) -> Optional[dict]:
    resp = httpx.get(PLACES_URL, params={
        "place_id": place_id,
        "fields": "rating,user_ratings_total",
        "key": config.PLACES_API_KEY,
    }, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK":
        return None
    result = data.get("result", {})
    return {"rating": result.get("rating"), "total_reviews": result.get("user_ratings_total")}
```

- [ ] **Step 4: Correr tests — deben pasar**

```bash
pytest tests/test_places.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add data/places.py tests/test_places.py
git commit -m "feat: capa Google Places para rating y reviews"
```

---

## Task 8: FastAPI app — rutas, sesiones, lógica de KPIs

**Files:**
- Create: `Proyecto_Locales_Propios/main.py`

- [ ] **Step 1: Crear `main.py`**

```python
# main.py
from __future__ import annotations
import calendar
from datetime import datetime
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import config, auth
from data import firestore as fs
from data import bigquery as bq
from data import sheets as sh
from data import places as pl
from cache import bq_cache, sheets_cache, places_cache

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _get_session(request: Request) -> dict | None:
    token = request.cookies.get(auth.SESSION_COOKIE)
    return auth.decode_session_token(token) if token else None


def _ultimo_mes_cerrado() -> tuple[int, int]:
    now = datetime.now()
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def _parse_periodo(p: str | None) -> tuple[str, int, int]:
    if not p:
        anio, mes = _ultimo_mes_cerrado()
        return "mes", anio, mes
    if p.endswith("-ytd"):
        a, m = p[:-4].split("-")
        return "ytd", int(a), int(m)
    a, m = p.split("-")
    return "mes", int(a), int(m)


def _semaforo(v: float, verde: float, amarillo: float) -> str:
    return "verde" if v < verde else ("amarillo" if v < amarillo else "rojo")


def _get_kpis(local_id: str, tipo: str, anio: int, mes: int) -> dict:
    periodo_bq = bq.PeriodoVentas.MES if tipo == "mes" else bq.PeriodoVentas.YTD
    periodo_sh = sh.PeriodoSheets.MES if tipo == "mes" else sh.PeriodoSheets.YTD

    bq_key = f"bq:{local_id}:{tipo}:{anio}:{mes}"
    ventas = bq_cache.get(bq_key) or bq.get_ventas_local(local_id, periodo_bq, anio, mes)
    bq_cache.set(bq_key, ventas)

    sh_key = f"sh:{local_id}:{tipo}:{anio}:{mes}"
    pl_data = sheets_cache.get(sh_key) or sh.get_pl_local(local_id, periodo_sh, anio, mes)
    sheets_cache.set(sh_key, pl_data)

    place_id = config.PLACES_ID_BARRIO_CHINO if local_id == "barrio_chino" else config.PLACES_ID_MONROE
    pl_key = f"places:{local_id}"
    rating = places_cache.get(pl_key)
    if rating is None:
        rating = pl.get_rating(place_id) or {"rating": None, "total_reviews": None}
        places_cache.set(pl_key, rating)

    return {
        **ventas, **pl_data,
        "rating": rating.get("rating"),
        "total_reviews": rating.get("total_reviews"),
        "reclamos": fs.get_reclamos_activos(local_id),
        "distribuciones": fs.get_distribuciones_pendientes(local_id),
    }


def _ctx_tablero(request, session, tipo, anio, mes, periodo):
    kpis_bc = _get_kpis("barrio_chino", tipo, anio, mes)
    kpis_mo = _get_kpis("monroe", tipo, anio, mes)
    return {
        "request": request, "session": session,
        "kpis_bc": kpis_bc, "kpis_mo": kpis_mo,
        "periodo": periodo or f"{anio}-{mes:02d}",
        "tipo": tipo, "anio": anio, "mes": mes,
        "nombre_mes": calendar.month_name[mes],
        "sem_cmv_bc": _semaforo(kpis_bc.get("cmv_pct", 0), config.SEMAFORO_CMV_VERDE, config.SEMAFORO_CMV_AMARILLO),
        "sem_cmv_mo": _semaforo(kpis_mo.get("cmv_pct", 0), config.SEMAFORO_CMV_VERDE, config.SEMAFORO_CMV_AMARILLO),
        "sem_lab_bc": _semaforo(kpis_bc.get("laboral_pct", 0), config.SEMAFORO_LABORAL_VERDE, config.SEMAFORO_LABORAL_AMARILLO),
        "sem_lab_mo": _semaforo(kpis_mo.get("laboral_pct", 0), config.SEMAFORO_LABORAL_VERDE, config.SEMAFORO_LABORAL_AMARILLO),
    }


# --- Auth ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _get_session(request):
        return RedirectResponse("/tablero")
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = fs.get_user(email)
    if not user or not auth.verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Email o contraseña incorrectos"})
    token = auth.create_session_token(email, user["role"])
    resp = RedirectResponse("/tablero", status_code=303)
    resp.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=auth.SESSION_MAX_AGE)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


# --- Tablero ---

@app.get("/tablero", response_class=HTMLResponse)
async def tablero(request: Request, periodo: str | None = None):
    session = _get_session(request)
    if not session:
        return RedirectResponse("/login")
    tipo, anio, mes = _parse_periodo(periodo)
    ctx = _ctx_tablero(request, session, tipo, anio, mes, periodo)
    return templates.TemplateResponse("tablero.html", ctx)


@app.get("/tablero/kpis", response_class=HTMLResponse)
async def tablero_kpis(request: Request, periodo: str | None = None):
    session = _get_session(request)
    if not session:
        return HTMLResponse("", status_code=401)
    tipo, anio, mes = _parse_periodo(periodo)
    ctx = _ctx_tablero(request, session, tipo, anio, mes, periodo)
    return templates.TemplateResponse("kpis_partial.html", ctx)


# --- Admin ---

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    session = _get_session(request)
    if not session or session["role"] != "superadmin":
        return RedirectResponse("/tablero")
    return templates.TemplateResponse("admin.html", {
        "request": request, "session": session,
        "usuarios": fs.list_users(),
        "reclamos_bc": fs.get_reclamos_todos("barrio_chino"),
        "reclamos_mo": fs.get_reclamos_todos("monroe"),
        "distribuciones_bc": fs.get_distribuciones_todas("barrio_chino"),
        "distribuciones_mo": fs.get_distribuciones_todas("monroe"),
    })


@app.post("/admin/usuarios")
async def admin_crear_usuario(request: Request, email: str = Form(...), password: str = Form(...), role: str = Form(...)):
    if not _get_session(request) or _get_session(request)["role"] != "superadmin":
        raise HTTPException(403)
    fs.create_user(email, auth.hash_password(password), role)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/usuarios/{email}/delete")
async def admin_eliminar_usuario(email: str, request: Request):
    if not _get_session(request) or _get_session(request)["role"] != "superadmin":
        raise HTTPException(403)
    fs.delete_user(email)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reclamos")
async def admin_add_reclamo(request: Request, local_id: str = Form(...), texto: str = Form(...), fecha: str = Form(...)):
    if not _get_session(request) or _get_session(request)["role"] != "superadmin":
        raise HTTPException(403)
    fs.add_reclamo(local_id, texto, fecha)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reclamos/{reclamo_id}/cerrar")
async def admin_cerrar_reclamo(reclamo_id: str, request: Request, local_id: str = Form(...)):
    if not _get_session(request) or _get_session(request)["role"] != "superadmin":
        raise HTTPException(403)
    fs.cerrar_reclamo(local_id, reclamo_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/distribuciones")
async def admin_add_distribucion(request: Request, local_id: str = Form(...), monto: float = Form(...), descripcion: str = Form(...), fecha: str = Form(...)):
    if not _get_session(request) or _get_session(request)["role"] != "superadmin":
        raise HTTPException(403)
    fs.add_distribucion(local_id, monto, descripcion, fecha)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/distribuciones/{dist_id}/pagar")
async def admin_marcar_pagado(dist_id: str, request: Request, local_id: str = Form(...)):
    if not _get_session(request) or _get_session(request)["role"] != "superadmin":
        raise HTTPException(403)
    fs.marcar_pagado(local_id, dist_id)
    return RedirectResponse("/admin", status_code=303)
```

- [ ] **Step 2: Verificar sintaxis**

```bash
python -c "import ast; ast.parse(open('main.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: FastAPI app con todas las rutas, sesiones y lógica KPIs"
```

---

## Task 9: Templates — login, tablero, kpis_partial, admin, CSS

**Files:**
- Create: `Proyecto_Locales_Propios/static/style.css`
- Create: `Proyecto_Locales_Propios/templates/base.html`
- Create: `Proyecto_Locales_Propios/templates/login.html`
- Create: `Proyecto_Locales_Propios/templates/kpis_partial.html`
- Create: `Proyecto_Locales_Propios/templates/tablero.html`
- Create: `Proyecto_Locales_Propios/templates/admin.html`

- [ ] **Step 1: Crear `static/style.css`**

```css
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#111827;color:#f9fafb;font-size:14px}
.nav{background:#1f2937;padding:10px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #374151}
.nav-title{font-weight:bold;font-size:15px}
.nav-actions{display:flex;gap:10px;align-items:center}
.periodo-btn{padding:5px 12px;border-radius:5px;border:none;cursor:pointer;background:#374151;color:#9ca3af;font-size:12px}
.periodo-btn.activo,.periodo-btn:hover{background:#2563eb;color:white}
.main{padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
.local-col{display:flex;flex-direction:column;gap:8px}
.local-header{padding:8px 12px;border-radius:6px;font-size:12px;font-weight:bold;display:flex;justify-content:space-between}
.local-header.bc{background:#1e3a5f;color:#60a5fa}
.local-header.mo{background:#3b1f5e;color:#c084fc}
.kpi-grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
.kpi-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.kpi{background:#1f2937;border-radius:6px;padding:10px}
.kpi.verde{border-left:3px solid #10b981}
.kpi.amarillo{border-left:3px solid #f59e0b}
.kpi.rojo{border-left:3px solid #ef4444}
.kpi-label{color:#6b7280;font-size:9px;text-transform:uppercase;margin-bottom:4px}
.kpi-val{font-size:13px;font-weight:bold}
.kpi-val.verde{color:#6ee7b7}
.kpi-val.amarillo{color:#fcd34d}
.kpi-val.rojo{color:#fca5a5}
.kpi-val.neutral{color:#f9fafb}
.alertas{padding:10px;border-radius:6px;border-left:3px solid #ef4444;background:#7f1d1d}
.alertas.ok{background:#052e16;border-color:#10b981}
.alerta-titulo{font-size:10px;font-weight:bold;margin-bottom:4px}
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-box{background:#1f2937;border-radius:10px;padding:32px;width:360px}
.login-box h1{margin-bottom:24px;font-size:18px;text-align:center}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:12px;color:#9ca3af;margin-bottom:6px}
.form-group input{width:100%;padding:8px 12px;background:#374151;border:1px solid #4b5563;border-radius:6px;color:white;font-size:14px}
.btn-primary{width:100%;padding:10px;background:#2563eb;color:white;border:none;border-radius:6px;cursor:pointer;font-size:14px}
.error-msg{color:#fca5a5;font-size:12px;margin-bottom:12px}
.admin-wrap{padding:20px;max-width:1100px}
.admin-section{margin-bottom:32px}
.admin-section h2{font-size:16px;margin-bottom:12px;border-bottom:1px solid #374151;padding-bottom:8px}
.admin-form{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px}
.admin-form input,.admin-form select{padding:6px 10px;background:#374151;border:1px solid #4b5563;border-radius:5px;color:white;font-size:12px}
.btn-sm{padding:6px 12px;border:none;border-radius:5px;cursor:pointer;font-size:12px}
.btn-sm.primary{background:#2563eb;color:white}
.btn-sm.danger{background:#dc2626;color:white}
.btn-sm.success{background:#059669;color:white}
table{width:100%;border-collapse:collapse;font-size:12px}
table th{text-align:left;padding:6px 10px;color:#9ca3af;border-bottom:1px solid #374151}
table td{padding:6px 10px;border-bottom:1px solid #1f2937}
a.nav-link{color:#9ca3af;font-size:12px;text-decoration:none}
```

- [ ] **Step 2: Crear `templates/base.html`**

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Temple — Locales Propios</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body>{% block content %}{% endblock %}</body>
</html>
```

- [ ] **Step 3: Crear `templates/login.html`**

```html
{% extends "base.html" %}
{% block content %}
<div class="login-wrap">
  <div class="login-box">
    <h1>Temple — Locales Propios</h1>
    {% if error %}<p class="error-msg">{{ error }}</p>{% endif %}
    <form method="post" action="/login">
      <div class="form-group">
        <label>Email</label>
        <input type="email" name="email" required autofocus>
      </div>
      <div class="form-group">
        <label>Contraseña</label>
        <input type="password" name="password" required>
      </div>
      <button type="submit" class="btn-primary">Ingresar</button>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Crear `templates/kpis_partial.html`**

```html
{# Fragmento HTMX — no extiende base #}
{% macro pesos(v) %}${{ "{:,.0f}".format(v / 1000000) }}M{% endmacro %}
{% macro pct(v) %}{{ "{:.1f}".format(v * 100) }}%{% endmacro %}

<div class="main" id="kpis-block">
{% for local_id, kpis, sem_cmv, sem_lab, hdr, lbl in [
    ("barrio_chino", kpis_bc, sem_cmv_bc, sem_lab_bc, "bc", "🏪 BARRIO CHINO"),
    ("monroe",       kpis_mo, sem_cmv_mo, sem_lab_mo, "mo", "🏪 MONROE"),
] %}
  <div class="local-col">
    <div class="local-header {{ hdr }}"><span>{{ lbl }}</span></div>

    <div class="kpi-grid-3">
      <div class="kpi"><div class="kpi-label">Ventas Netas</div><div class="kpi-val neutral">{{ pesos(kpis.ventas_netas) }}</div></div>
      <div class="kpi"><div class="kpi-label">Ordenes</div><div class="kpi-val neutral">{{ "{:,}".format(kpis.num_ordenes) }}</div></div>
      <div class="kpi"><div class="kpi-label">Ticket Prom.</div><div class="kpi-val neutral">${{ "{:,.0f}".format(kpis.ticket_promedio) }}</div></div>
    </div>

    <div class="kpi-grid-2">
      <div class="kpi {{ sem_cmv }}"><div class="kpi-label">CMV</div><div class="kpi-val {{ sem_cmv }}">{{ pct(kpis.cmv_pct) }}</div></div>
      <div class="kpi {{ sem_lab }}"><div class="kpi-label">Costo Laboral</div><div class="kpi-val {{ sem_lab }}">{{ pct(kpis.laboral_pct) }}</div></div>
    </div>

    {% set ebitda_color = "verde" if kpis.ebitda_pct > 0 else "rojo" %}
    {% set res_color = "verde" if kpis.resultado_operativo > 0 else "rojo" %}
    <div class="kpi-grid-3">
      <div class="kpi {{ ebitda_color }}"><div class="kpi-label">EBITDA</div><div class="kpi-val {{ ebitda_color }}">{{ pct(kpis.ebitda_pct) }}</div></div>
      <div class="kpi {{ res_color }}"><div class="kpi-label">Resultado Op.</div><div class="kpi-val {{ res_color }}">{{ pesos(kpis.resultado_operativo) }}</div></div>
      <div class="kpi"><div class="kpi-label">Caja Gen.</div><div class="kpi-val neutral">{{ pesos(kpis.caja_generada) }}</div></div>
    </div>

    <div class="kpi-grid-2">
      <div class="kpi">
        <div class="kpi-label">Calificación Google</div>
        <div class="kpi-val" style="color:#fcd34d">
          {% if kpis.rating %}★ {{ kpis.rating }} <small style="color:#6b7280;font-size:10px">{{ "{:,}".format(kpis.total_reviews) }} reviews</small>{% else %}—{% endif %}
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Distribución Pend.</div>
        <div class="kpi-val" style="color:#93c5fd">
          {% if kpis.distribuciones %}{{ pesos(kpis.distribuciones[0].monto) }}{% else %}—{% endif %}
        </div>
      </div>
    </div>

    <div class="alertas {% if not kpis.reclamos %}ok{% endif %}">
      {% if kpis.reclamos %}
        <div class="alerta-titulo" style="color:#fca5a5">⚠ Reclamos / Alertas</div>
        {% for r in kpis.reclamos %}<div style="color:#fecaca;font-size:11px">• {{ r.texto }} — {{ r.fecha }}</div>{% endfor %}
      {% else %}
        <div class="alerta-titulo" style="color:#6ee7b7">✓ Sin reclamos activos</div>
      {% endif %}
    </div>
  </div>
{% endfor %}
</div>
```

- [ ] **Step 5: Crear `templates/tablero.html`**

```html
{% extends "base.html" %}
{% block content %}
<nav class="nav">
  <span class="nav-title">TEMPLE — Locales Propios</span>
  <div class="nav-actions">
    {% set mes_ant = mes - 1 if mes > 1 else 12 %}
    {% set anio_ant = anio if mes > 1 else anio - 1 %}
    <button class="periodo-btn {% if tipo == 'mes' %}activo{% endif %}"
      hx-get="/tablero/kpis?periodo={{ anio }}-{{ '%02d'|format(mes) }}"
      hx-target="#kpis-block" hx-swap="outerHTML">
      {{ nombre_mes }} {{ anio }}
    </button>
    <button class="periodo-btn"
      hx-get="/tablero/kpis?periodo={{ anio_ant }}-{{ '%02d'|format(mes_ant) }}"
      hx-target="#kpis-block" hx-swap="outerHTML">
      Mes anterior
    </button>
    <button class="periodo-btn {% if tipo == 'ytd' %}activo{% endif %}"
      hx-get="/tablero/kpis?periodo={{ anio }}-{{ '%02d'|format(mes) }}-ytd"
      hx-target="#kpis-block" hx-swap="outerHTML">
      YTD {{ anio }}
    </button>
    {% if session.role == 'superadmin' %}<a href="/admin" class="nav-link">⚙ Admin</a>{% endif %}
    <a href="/logout" class="nav-link">Salir</a>
  </div>
</nav>
{% include "kpis_partial.html" %}
{% endblock %}
```

- [ ] **Step 6: Crear `templates/admin.html`**

```html
{% extends "base.html" %}
{% block content %}
<nav class="nav">
  <span class="nav-title">TEMPLE — Admin</span>
  <div class="nav-actions">
    <a href="/tablero" class="nav-link">← Tablero</a>
    <a href="/logout" class="nav-link">Salir</a>
  </div>
</nav>
<div class="admin-wrap">

  <div class="admin-section">
    <h2>Usuarios</h2>
    <form class="admin-form" method="post" action="/admin/usuarios">
      <input type="email" name="email" placeholder="email@temple.com.ar" required>
      <input type="password" name="password" placeholder="Contraseña" required>
      <select name="role"><option value="viewer">Viewer</option><option value="superadmin">Superadmin</option></select>
      <button type="submit" class="btn-sm primary">Crear</button>
    </form>
    <table>
      <tr><th>Email</th><th>Rol</th><th></th></tr>
      {% for u in usuarios %}
      <tr>
        <td>{{ u.email }}</td><td>{{ u.role }}</td>
        <td>{% if u.email != session.email %}
          <form method="post" action="/admin/usuarios/{{ u.email }}/delete" style="display:inline">
            <button type="submit" class="btn-sm danger" onclick="return confirm('¿Eliminar?')">Eliminar</button>
          </form>{% endif %}
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>

  {% for local_id, lbl, reclamos, distribuciones in [
      ("barrio_chino","Barrio Chino", reclamos_bc, distribuciones_bc),
      ("monroe","Monroe", reclamos_mo, distribuciones_mo),
  ] %}
  <div class="admin-section">
    <h2>{{ lbl }} — Reclamos</h2>
    <form class="admin-form" method="post" action="/admin/reclamos">
      <input type="hidden" name="local_id" value="{{ local_id }}">
      <input type="text" name="texto" placeholder="Descripción" required style="min-width:260px">
      <input type="date" name="fecha" required>
      <button type="submit" class="btn-sm primary">Agregar</button>
    </form>
    <table>
      <tr><th>Texto</th><th>Fecha</th><th>Estado</th><th></th></tr>
      {% for r in reclamos %}<tr>
        <td>{{ r.texto }}</td><td>{{ r.fecha }}</td><td>{{ r.estado }}</td>
        <td>{% if r.estado == 'activo' %}
          <form method="post" action="/admin/reclamos/{{ r.id }}/cerrar" style="display:inline">
            <input type="hidden" name="local_id" value="{{ local_id }}">
            <button type="submit" class="btn-sm success">Cerrar</button>
          </form>{% endif %}
        </td>
      </tr>{% endfor %}
    </table>
  </div>

  <div class="admin-section">
    <h2>{{ lbl }} — Distribuciones</h2>
    <form class="admin-form" method="post" action="/admin/distribuciones">
      <input type="hidden" name="local_id" value="{{ local_id }}">
      <input type="number" name="monto" placeholder="Monto $" required step="1000">
      <input type="text" name="descripcion" placeholder="Descripción" required>
      <input type="date" name="fecha" required>
      <button type="submit" class="btn-sm primary">Agregar</button>
    </form>
    <table>
      <tr><th>Descripción</th><th>Monto</th><th>Fecha</th><th>Estado</th><th></th></tr>
      {% for d in distribuciones %}<tr>
        <td>{{ d.descripcion }}</td><td>${{ "{:,.0f}".format(d.monto) }}</td>
        <td>{{ d.fecha }}</td><td>{{ d.estado }}</td>
        <td>{% if d.estado == 'pendiente' %}
          <form method="post" action="/admin/distribuciones/{{ d.id }}/pagar" style="display:inline">
            <input type="hidden" name="local_id" value="{{ local_id }}">
            <button type="submit" class="btn-sm success">Pagar</button>
          </form>{% endif %}
        </td>
      </tr>{% endfor %}
    </table>
  </div>
  {% endfor %}

</div>
{% endblock %}
```

- [ ] **Step 7: Correr app y verificar que levanta sin errores de template**

```bash
export GOOGLE_SHEETS_ID=x SESSION_SECRET=dev PLACES_API_KEY=x \
  PLACES_ID_BARRIO_CHINO=x PLACES_ID_MONROE=x \
  FIRESTORE_PROJECT=temple-bar-439715 BQ_PROJECT=temple-bar-439715 \
  BQ_DATASET=curated_database BQ_TABLE=curated_sales
uvicorn main:app --port 8080
```
Abrir `http://localhost:8080/login` — debe mostrar el formulario sin errores.

- [ ] **Step 8: Correr todos los tests**

```bash
pytest tests/ -v
```
Expected: todos los tests pasan (auth, cache, bigquery, sheets, places, firestore).

- [ ] **Step 9: Commit**

```bash
git add templates/ static/
git commit -m "feat: templates login, tablero HTMX, kpis_partial y admin"
```

---

## Task 10: Crear superadmin inicial en Firestore

**Files:**
- Create: `Proyecto_Locales_Propios/setup_admin.py`

- [ ] **Step 1: Crear `setup_admin.py`**

```python
# setup_admin.py — ejecutar una sola vez con ADC activo
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import firestore
import auth as auth_module

firebase_admin.initialize_app()
db = firestore.client()

EMAIL = "darwin.salinas@temple.com.ar"
PASSWORD = input(f"Contraseña para {EMAIL}: ")
pw_hash = auth_module.hash_password(PASSWORD)

db.collection("users_config").document(EMAIL).set({
    "role": "superadmin",
    "password_hash": pw_hash,
    "created_at": datetime.now(timezone.utc),
    "updated_at": datetime.now(timezone.utc),
})
print(f"✓ Usuario {EMAIL} creado como superadmin.")
```

- [ ] **Step 2: Ejecutar el script**

```bash
gcloud auth application-default login
python setup_admin.py
```
Ingresar la contraseña cuando la solicite. Verificar en Firestore Console → `users_config` → `darwin.salinas@temple.com.ar`.

- [ ] **Step 3: Commit**

```bash
git add setup_admin.py
git commit -m "feat: script setup_admin para crear superadmin inicial"
```

---

## Task 11: Deploy a Cloud Run

**Files:**
- Create: `Proyecto_Locales_Propios/.env.example`

- [ ] **Step 1: Crear `.env.example`**

```
GOOGLE_SHEETS_ID=1Z2YFlCFLy7QUDm7GA09AQr8oCinJgvw3uP0CJNur2yo
PLACES_API_KEY=<Google Cloud Console → APIs → Places API → Credentials>
PLACES_ID_BARRIO_CHINO=<Place ID Finder en developers.google.com/maps>
PLACES_ID_MONROE=<Place ID Finder en developers.google.com/maps>
SESSION_SECRET=<python -c "import secrets; print(secrets.token_hex(32))">
FIRESTORE_PROJECT=temple-bar-439715
BQ_PROJECT=temple-bar-439715
BQ_DATASET=curated_database
BQ_TABLE=curated_sales
BQ_LOCAL_FIELD=nombre_local
BQ_LOCAL_BC=Barrio Chino
BQ_LOCAL_MONROE=Monroe
```

- [ ] **Step 2: Habilitar APIs necesarias**

```bash
gcloud services enable places-backend.googleapis.com sheets.googleapis.com --project=temple-bar-439715
```

- [ ] **Step 3: Generar SESSION_SECRET**

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Guardar el resultado — se usa en el siguiente paso.

- [ ] **Step 4: Deploy**

```bash
cd "/Users/darwjoses/Mi unidad/Claude_Cowork/Proyecto_Locales_Propios"

gcloud run deploy locales-propios \
  --source . \
  --region us-central1 \
  --project temple-bar-439715 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_SHEETS_ID=1Z2YFlCFLy7QUDm7GA09AQr8oCinJgvw3uP0CJNur2yo,PLACES_API_KEY=<TU_KEY>,PLACES_ID_BARRIO_CHINO=<BC_PLACE_ID>,PLACES_ID_MONROE=<MO_PLACE_ID>,SESSION_SECRET=<TU_SECRET>,FIRESTORE_PROJECT=temple-bar-439715,BQ_PROJECT=temple-bar-439715,BQ_DATASET=curated_database,BQ_TABLE=curated_sales"
```
Expected output: `Service URL: https://locales-propios-XXXX-uc.a.run.app`

- [ ] **Step 5: Smoke test del deploy**

Abrir la URL del servicio → `/login` debe cargar. Ingresar con `darwin.salinas@temple.com.ar` y la contraseña del Task 10. El tablero debe cargar con datos reales (o errores de conexión visibles en los logs de Cloud Run si algo falta).

- [ ] **Step 6: Commit final**

```bash
git add .env.example
git commit -m "feat: .env.example y deploy a Cloud Run"
```

---

## Self-Review

### Cobertura del spec

| Requisito | Task |
|-----------|------|
| FastAPI + Jinja2 + HTMX | 8, 9 |
| Vista comparativa lado a lado | 9 (kpis_partial.html) |
| Ventas, Ordenes, Ticket desde BigQuery | 5 |
| CMV, Laboral, EBITDA, Resultado, Caja desde Sheets | 6 |
| Calificación Google desde Places API | 7 |
| Reclamos y distribuciones desde Firestore | 4 |
| Auth email+contraseña con bcrypt | 3 |
| Cookie de sesión firmada con itsdangerous | 3, 8 |
| Panel admin (usuarios, reclamos, distribuciones) | 8, 9 |
| Filtros de período con HTMX | 8, 9 |
| Cache BQ 30min / Sheets 6h / Places 24h | 2, 8 |
| Semáforo con umbrales configurables | 1, 8, 9 |
| Deploy Cloud Run con `gcloud run deploy --source` | 11 |
| Variables de entorno | 1, 11 |
| Superadmin inicial | 10 |

### Consistencia de tipos y nombres
- `local_id` es siempre `"barrio_chino"` o `"monroe"` en todas las capas ✅
- `get_ventas_local` → retorna `{ventas_netas, num_ordenes, ticket_promedio}` — usado así en `main.py` ✅
- `get_pl_local` → retorna `{ventas_netas, cmv_pct, laboral_pct, ebitda_pct, resultado_operativo, caja_generada}` — usado así en `main.py` y templates ✅
- `get_rating` → retorna `{rating, total_reviews}` o `None` — manejado en `_get_kpis` con fallback ✅
- `_semaforo` en `main.py` retorna `"verde"/"amarillo"/"rojo"` — usadas como clases CSS en templates ✅
- Variables de template `sem_cmv_bc/mo` y `sem_lab_bc/mo` — definidas en `_ctx_tablero` y usadas en `kpis_partial.html` ✅
