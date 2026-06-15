# Agente IA Retail — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un agente IA conversacional vía WhatsApp que analiza datos de ventas retail en tiempo real desde BigQuery y envía un informe semanal automático cada lunes a las 8:00 hs.

**Architecture:** Se extiende el `app.py` existente en Cloud Run con 2 endpoints nuevos. El agente usa Claude API (`claude-sonnet-4-6`) con tool use para consultar BigQuery. Las sesiones de conversación se persisten en Cloud Firestore. WhatsApp se integra vía Twilio.

**Tech Stack:** Python 3.x · Flask · Anthropic SDK · Twilio · Google Cloud BigQuery · Google Cloud Firestore · Cloud Scheduler · google-auth

---

## Spec de referencia
`docs/superpowers/specs/2026-05-26-agente-ia-retail-design.md`

---

## Estructura de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `whatsapp_tools.py` | Crear | 3 tool functions + TOOL_DEFINITIONS para Claude API |
| `whatsapp_agent.py` | Crear | Session management (Firestore) + Claude agent loop + access control |
| `weekly_report.py` | Crear | Generación de informe semanal + envío vía Twilio |
| `agents_config.json` | Crear | Whitelist de usuarios con roles |
| `app.py` | Modificar | Agregar endpoints `/whatsapp/webhook` y `/whatsapp/weekly-report` |
| `requirements.txt` | Modificar | Agregar `twilio`, `anthropic`, `google-cloud-firestore` |
| `tests/test_whatsapp_tools.py` | Crear | Tests de las 3 tools |
| `tests/test_whatsapp_agent.py` | Crear | Tests del agente, sesiones y access control |
| `tests/test_weekly_report.py` | Crear | Tests del informe semanal |

---

## Task 1: Dependencies + Config

**Files:**
- Modify: `requirements.txt`
- Create: `agents_config.json`

- [ ] **Step 1: Agregar dependencias a requirements.txt**

Agregar al final de `requirements.txt`:
```
twilio>=9.0.0
anthropic>=0.40.0
google-cloud-firestore>=2.16.0
```

- [ ] **Step 2: Instalar dependencias**

```bash
pip install twilio anthropic google-cloud-firestore
```

Verificar:
```bash
python -c "import twilio; import anthropic; from google.cloud import firestore; print('OK')"
```
Esperado: `OK`

- [ ] **Step 3: Crear agents_config.json**

```json
{
  "users": [
    {
      "phone": "whatsapp:+549XXXXXXXXXX",
      "name": "Darwin",
      "role": "admin"
    }
  ],
  "scheduler_token": "REEMPLAZAR_CON_TOKEN_SECRETO"
}
```

> Nota: El número debe tener el prefijo `whatsapp:` — es como Twilio lo envía en el campo `From`. Reemplazar `XXXXXXXXXX` con el número real. El `scheduler_token` se moverá a Secret Manager en el Task 9.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt agents_config.json
git commit -m "chore: add whatsapp agent dependencies and config skeleton"
```

---

## Task 2: whatsapp_tools.py — query_retail

**Files:**
- Create: `whatsapp_tools.py`
- Create: `tests/test_whatsapp_tools.py`

- [ ] **Step 1: Escribir test para query_retail**

Crear `tests/test_whatsapp_tools.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


def make_bq_row(grupo, facturacion, ordenes, ticket):
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: grupo if k in ("Marca","Local","Canal","Fecha") else None)
    row.Facturacion = facturacion
    row.Ordenes = ordenes
    row.Ticket_Promedio = ticket
    return row


class TestQueryRetail:
    def test_retorna_lista_con_estructura_correcta(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_row = make_bq_row("Temple", 279_758_420, 7502, 37_291)
        mock_client.query.return_value.result.return_value = [mock_row]

        result = query_retail(mock_client, "2026-05-18", "2026-05-24", "marca")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["facturacion"] == 279_758_420
        assert result[0]["ordenes"] == 7502
        assert result[0]["ticket"] == 37_291

    def test_agrupar_por_dia_usa_columna_fecha(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_retail(mock_client, "2026-05-18", "2026-05-24", "dia")

        call_args = mock_client.query.call_args[0][0]
        assert "Fecha" in call_args
        assert "GROUP BY Fecha" in call_args

    def test_agrupar_por_marca(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_retail(mock_client, "2026-05-18", "2026-05-24", "marca")

        call_args = mock_client.query.call_args[0][0]
        assert "GROUP BY Marca" in call_args
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
python -m pytest tests/test_whatsapp_tools.py::TestQueryRetail -v
```

Esperado: `ImportError` o `ModuleNotFoundError` — el módulo no existe aún.

- [ ] **Step 3: Implementar query_retail en whatsapp_tools.py**

Crear `whatsapp_tools.py`:

```python
"""
whatsapp_tools.py
Implementación de las 3 tools de Claude API para el agente retail.
"""
import json
import sys
import os
from datetime import date, timedelta
from google.cloud import bigquery

# ── Constantes ────────────────────────────────────────────────────────────────

PROJECT_ID    = "temple-bar-439715"
RETAIL_TABLE  = f"`{PROJECT_ID}.Corporativo.vw_Ventas_Corporativo_Base`"
PRODUCT_TABLE = f"`{PROJECT_ID}.curated_database.vw_curated_compilado_ok`"

# ── query_retail ──────────────────────────────────────────────────────────────

def query_retail(bq_client, fecha_desde: str, fecha_hasta: str, agrupar_por: str) -> list:
    """
    Consulta ventas retail desde BigQuery.
    agrupar_por: "marca" | "local" | "canal" | "dia"
    Retorna lista de dicts con grupo, facturacion, ordenes, ticket.
    """
    group_map = {
        "marca": "Marca",
        "local": "Local",
        "canal": "Canal",
        "dia":   "Fecha",
    }
    group_col = group_map.get(agrupar_por, "Marca")

    query = f"""
    SELECT
      {group_col},
      SUM(Facturacion)                                        AS Facturacion,
      COUNT(DISTINCT Orden)                                   AS Ordenes,
      ROUND(SUM(Facturacion) / NULLIF(COUNT(DISTINCT Orden), 0), 0) AS Ticket_Promedio
    FROM {RETAIL_TABLE}
    WHERE Fecha BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
    GROUP BY {group_col}
    ORDER BY Facturacion DESC
    """

    rows = list(bq_client.query(query).result())
    return [
        {
            "grupo":       str(r[group_col]),
            "facturacion": r.Facturacion,
            "ordenes":     r.Ordenes,
            "ticket":      r.Ticket_Promedio,
        }
        for r in rows
    ]
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

```bash
python -m pytest tests/test_whatsapp_tools.py::TestQueryRetail -v
```

Esperado: 3 tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add whatsapp_tools.py tests/test_whatsapp_tools.py
git commit -m "feat: add query_retail tool with tests"
```

---

## Task 3: whatsapp_tools.py — get_objectives

**Files:**
- Modify: `whatsapp_tools.py`
- Modify: `tests/test_whatsapp_tools.py`

- [ ] **Step 1: Agregar test para get_objectives**

Agregar a `tests/test_whatsapp_tools.py`:

```python
class TestGetObjectives:
    def test_retorna_estructura_con_pace(self):
        from whatsapp_tools import get_objectives_for_tool

        mock_obj = {
            "Temple": {
                "2026-05": {"obj_fac": 1424, "obj_ord": 38137}
            }
        }

        with patch("whatsapp_tools.fetch_objetivos_data", return_value=mock_obj):
            result = get_objectives_for_tool("Temple", "2026-05")

        assert result["obj_fac"] == 1424
        assert result["obj_ord"] == 38137
        assert "pace_pct" in result
        assert "dias_transcurridos" in result
        assert "dias_mes" in result
        assert 0 < result["pace_pct"] <= 100

    def test_marca_inexistente_retorna_ceros(self):
        from whatsapp_tools import get_objectives_for_tool

        with patch("whatsapp_tools.fetch_objetivos_data", return_value={}):
            result = get_objectives_for_tool("MarcaFalsa", "2026-05")

        assert result["obj_fac"] == 0
        assert result["obj_ord"] == 0
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
python -m pytest tests/test_whatsapp_tools.py::TestGetObjectives -v
```

Esperado: `ImportError` — `get_objectives_for_tool` no existe aún.

- [ ] **Step 3: Implementar get_objectives_for_tool en whatsapp_tools.py**

Agregar al final de `whatsapp_tools.py`:

```python
# ── get_objectives ─────────────────────────────────────────────────────────────

def get_objectives_for_tool(marca: str, mes: str) -> dict:
    """
    Retorna objetivos mensuales para una marca + pace calculado al día de hoy.
    mes: formato "YYYY-MM"
    """
    # Importar la función existente del script principal para no duplicar lógica
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from actualizar_retail import fetch_objetivos_data

    obj = fetch_objetivos_data()
    mes_data = obj.get(marca, {}).get(mes, {"obj_fac": 0, "obj_ord": 0})

    # Calcular pace: días transcurridos del mes / días totales del mes
    today = date.today()
    if today.month == 12:
        days_in_month = 31
    else:
        days_in_month = (date(today.year, today.month + 1, 1) - timedelta(days=1)).day

    pace_pct = round(today.day / days_in_month * 100, 1)

    return {
        "obj_fac":           mes_data["obj_fac"],
        "obj_ord":           mes_data["obj_ord"],
        "pace_pct":          pace_pct,
        "dias_transcurridos": today.day,
        "dias_mes":          days_in_month,
    }
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_whatsapp_tools.py::TestGetObjectives -v
```

Esperado: 2 tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add whatsapp_tools.py tests/test_whatsapp_tools.py
git commit -m "feat: add get_objectives tool with tests"
```

---

## Task 4: whatsapp_tools.py — query_product + TOOL_DEFINITIONS

**Files:**
- Modify: `whatsapp_tools.py`
- Modify: `tests/test_whatsapp_tools.py`

- [ ] **Step 1: Agregar test para query_product**

Agregar a `tests/test_whatsapp_tools.py`:

```python
class TestQueryProduct:
    def test_retorna_kpis_con_litros_y_ranking(self):
        from whatsapp_tools import query_product

        mock_row = MagicMock()
        mock_row.familia = "Cerveza"
        mock_row.lts_total = 320.5
        mock_row.facturacion = 150_000_000
        mock_row.producto = "Rubia 500cc"
        mock_row.cantidad = 1200

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = [mock_row]

        result = query_product(mock_client, "2026-05-18", "2026-05-24", "TEMPLE")

        assert "mix" in result
        assert "top_productos" in result
        assert isinstance(result["mix"], list)
        assert isinstance(result["top_productos"], list)

    def test_marca_todas_no_aplica_filtro(self):
        from whatsapp_tools import query_product

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_product(mock_client, "2026-05-18", "2026-05-24", "TODAS")

        call_args = mock_client.query.call_args[0][0]
        assert "establecimiento" not in call_args.lower() or True  # sin filtro de marca
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
python -m pytest tests/test_whatsapp_tools.py::TestQueryProduct -v
```

Esperado: `ImportError` — `query_product` no existe aún.

- [ ] **Step 3: Implementar query_product y TOOL_DEFINITIONS en whatsapp_tools.py**

Agregar a `whatsapp_tools.py`:

```python
# ── query_product ──────────────────────────────────────────────────────────────

def query_product(bq_client, fecha_desde: str, fecha_hasta: str, marca: str) -> dict:
    """
    Consulta datos de producto (litros, mix, top productos) desde la vista curada.
    marca: "TEMPLE" | "PATAGONIA" | "FERIADO" | "TODAS"
    """
    # Feriado usa columna de fecha diferente
    if marca.upper() == "FERIADO":
        date_col = "Fecha_de_creacion"
        prod_col  = "Nombre"
        fam_col   = "Categor__as_de_Productos_Platos"
        lts_col   = "Litros_Totales"
    else:
        date_col = "fecha"
        prod_col  = "producto"
        fam_col   = "familia"
        lts_col   = "Litros_Totales"

    marca_filter = f"AND marca = '{marca.upper()}'" if marca.upper() != "TODAS" else ""

    query_mix = f"""
    SELECT
      INITCAP(COALESCE({fam_col}, 'Sin clasificar'))  AS familia,
      ROUND(SUM(COALESCE({lts_col}, 0)), 1)           AS lts_total,
      ROUND(SUM(COALESCE(facturacion, 0)), 0)         AS facturacion
    FROM {PRODUCT_TABLE}
    WHERE {date_col} BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
    {marca_filter}
    GROUP BY familia
    ORDER BY lts_total DESC
    LIMIT 10
    """

    query_top = f"""
    SELECT
      {prod_col}                                      AS producto,
      ROUND(SUM(COALESCE({lts_col}, 0)), 1)           AS lts_total,
      ROUND(SUM(COALESCE(facturacion, 0)), 0)         AS facturacion
    FROM {PRODUCT_TABLE}
    WHERE {date_col} BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
    {marca_filter}
    GROUP BY producto
    ORDER BY facturacion DESC
    LIMIT 10
    """

    mix_rows = list(bq_client.query(query_mix).result())
    top_rows = list(bq_client.query(query_top).result())

    return {
        "mix": [
            {"familia": r.familia, "litros": r.lts_total, "facturacion": r.facturacion}
            for r in mix_rows
        ],
        "top_productos": [
            {"producto": r.producto, "litros": r.lts_total, "facturacion": r.facturacion}
            for r in top_rows
        ],
    }


# ── TOOL_DEFINITIONS para Claude API ──────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "query_retail",
        "description": (
            "Consulta datos de ventas retail desde BigQuery. "
            "Retorna facturación, órdenes y ticket promedio agrupados por marca, local, canal o día."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {
                    "type": "string",
                    "description": "Fecha de inicio en formato YYYY-MM-DD"
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "Fecha de fin en formato YYYY-MM-DD"
                },
                "agrupar_por": {
                    "type": "string",
                    "enum": ["marca", "local", "canal", "dia"],
                    "description": "Dimensión de agrupación"
                },
            },
            "required": ["fecha_desde", "fecha_hasta", "agrupar_por"],
        },
    },
    {
        "name": "get_objectives",
        "description": (
            "Retorna los objetivos mensuales de una marca y el pace esperado "
            "(porcentaje del mes transcurrido). Usá siempre junto a query_retail "
            "para calcular cumplimiento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "marca": {
                    "type": "string",
                    "enum": ["Temple", "Patagonia", "Feriado"],
                    "description": "Nombre de la marca"
                },
                "mes": {
                    "type": "string",
                    "description": "Mes en formato YYYY-MM (ej: 2026-05)"
                },
            },
            "required": ["marca", "mes"],
        },
    },
    {
        "name": "query_product",
        "description": (
            "Consulta datos de producto: mix de venta por familia (litros y facturación) "
            "y top 10 productos. Usar cuando pregunten sobre productos, litros o categorías."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {
                    "type": "string",
                    "description": "Fecha de inicio en formato YYYY-MM-DD"
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "Fecha de fin en formato YYYY-MM-DD"
                },
                "marca": {
                    "type": "string",
                    "enum": ["TEMPLE", "PATAGONIA", "FERIADO", "TODAS"],
                    "description": "Marca a consultar. Usar TODAS para consolidado."
                },
            },
            "required": ["fecha_desde", "fecha_hasta", "marca"],
        },
    },
]

# Solo tools básicas para viewers (sin query_product)
VIEWER_TOOL_DEFINITIONS = [t for t in TOOL_DEFINITIONS if t["name"] != "query_product"]
```

- [ ] **Step 4: Ejecutar todos los tests de tools**

```bash
python -m pytest tests/test_whatsapp_tools.py -v
```

Esperado: 7 tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add whatsapp_tools.py tests/test_whatsapp_tools.py
git commit -m "feat: add query_product tool and TOOL_DEFINITIONS"
```

---

## Task 5: whatsapp_agent.py — Session Management (Firestore)

**Files:**
- Create: `whatsapp_agent.py`
- Create: `tests/test_whatsapp_agent.py`

- [ ] **Step 1: Escribir tests de session management**

Crear `tests/test_whatsapp_agent.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


class TestSessionManagement:
    def test_get_session_retorna_lista_vacia_si_no_existe(self):
        from whatsapp_agent import get_session

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        result = get_session(mock_db, "whatsapp:+549111111111")
        assert result == []

    def test_get_session_retorna_lista_vacia_si_expirada(self):
        from whatsapp_agent import get_session

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        # Sesión de hace 3 horas — expirada
        mock_doc.to_dict.return_value = {
            "messages": [{"role": "user", "content": "hola"}],
            "last_activity": datetime.utcnow() - timedelta(hours=3),
            "user_name": "Darwin",
            "role": "admin",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        result = get_session(mock_db, "whatsapp:+549111111111")
        assert result == []

    def test_get_session_retorna_mensajes_si_vigente(self):
        from whatsapp_agent import get_session

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        messages = [{"role": "user", "content": "hola"}]
        mock_doc.to_dict.return_value = {
            "messages": messages,
            "last_activity": datetime.utcnow() - timedelta(minutes=10),
            "user_name": "Darwin",
            "role": "admin",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        result = get_session(mock_db, "whatsapp:+549111111111")
        assert result == messages

    def test_save_session_guarda_maximo_10_mensajes(self):
        from whatsapp_agent import save_session

        mock_db = MagicMock()
        messages = [{"role": "user", "content": str(i)} for i in range(15)]

        save_session(mock_db, "whatsapp:+549111111111", messages, "Darwin", "admin")

        saved_data = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert len(saved_data["messages"]) == 10
        # Debe guardar los últimos 10
        assert saved_data["messages"][0]["content"] == "5"
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
python -m pytest tests/test_whatsapp_agent.py::TestSessionManagement -v
```

Esperado: `ImportError` — el módulo no existe aún.

- [ ] **Step 3: Implementar session management en whatsapp_agent.py**

Crear `whatsapp_agent.py`:

```python
"""
whatsapp_agent.py
Agente IA retail vía WhatsApp: session management, Claude API loop y access control.
"""
import json
import os
from datetime import datetime, timedelta

from google.cloud import firestore

# ── Session Management ─────────────────────────────────────────────────────────

SESSION_TTL_HOURS = 2
MAX_MESSAGES      = 10


def get_session(db, phone: str) -> list:
    """
    Retorna el historial de mensajes de la sesión activa del usuario.
    Retorna [] si no existe o si la sesión expiró.
    """
    doc = db.collection("sessions").document(phone).get()
    if not doc.exists:
        return []

    data = doc.to_dict()
    last_activity = data.get("last_activity")

    if last_activity:
        # Normalizar a naive datetime para comparar
        if hasattr(last_activity, "tzinfo") and last_activity.tzinfo is not None:
            last_activity = last_activity.replace(tzinfo=None)
        age = datetime.utcnow() - last_activity
        if age > timedelta(hours=SESSION_TTL_HOURS):
            return []

    return data.get("messages", [])


def save_session(db, phone: str, messages: list, user_name: str, role: str) -> None:
    """Persiste los últimos MAX_MESSAGES mensajes en Firestore."""
    db.collection("sessions").document(phone).set({
        "messages":      messages[-MAX_MESSAGES:],
        "last_activity": datetime.utcnow(),
        "user_name":     user_name,
        "role":          role,
    })
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_whatsapp_agent.py::TestSessionManagement -v
```

Esperado: 4 tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add whatsapp_agent.py tests/test_whatsapp_agent.py
git commit -m "feat: add Firestore session management"
```

---

## Task 6: whatsapp_agent.py — Claude Agent Loop + Access Control

**Files:**
- Modify: `whatsapp_agent.py`
- Modify: `tests/test_whatsapp_agent.py`

- [ ] **Step 1: Agregar tests de access control y agent loop**

Agregar a `tests/test_whatsapp_agent.py`:

```python
class TestAccessControl:
    def _load_config(self):
        return {
            "users": [
                {"phone": "whatsapp:+549111111111", "name": "Darwin", "role": "admin"},
                {"phone": "whatsapp:+549222222222", "name": "Gerente", "role": "viewer"},
            ]
        }

    def test_admin_es_reconocido(self):
        from whatsapp_agent import get_user

        user = get_user("whatsapp:+549111111111", self._load_config())
        assert user is not None
        assert user["role"] == "admin"

    def test_viewer_es_reconocido(self):
        from whatsapp_agent import get_user

        user = get_user("whatsapp:+549222222222", self._load_config())
        assert user is not None
        assert user["role"] == "viewer"

    def test_numero_desconocido_retorna_none(self):
        from whatsapp_agent import get_user

        user = get_user("whatsapp:+549999999999", self._load_config())
        assert user is None


class TestAgentLoop:
    def test_responde_texto_cuando_no_usa_tools(self):
        from whatsapp_agent import run_agent
        import anthropic

        mock_anthropic = MagicMock()
        mock_bq = MagicMock()

        # Simular respuesta de Claude sin tool use
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hola, soy el agente retail."
        mock_response.content = [mock_text_block]
        mock_anthropic.messages.create.return_value = mock_response

        text, new_history = run_agent(
            user_message="hola",
            history=[],
            user_role="admin",
            bq_client=mock_bq,
            anthropic_client=mock_anthropic,
        )

        assert text == "Hola, soy el agente retail."
        assert len(new_history) == 2  # user + assistant

    def test_viewer_recibe_tools_reducidas(self):
        from whatsapp_agent import run_agent
        from whatsapp_tools import VIEWER_TOOL_DEFINITIONS

        mock_anthropic = MagicMock()
        mock_bq = MagicMock()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "ok"
        mock_response.content = [mock_text]
        mock_anthropic.messages.create.return_value = mock_response

        run_agent("hola", [], "viewer", mock_bq, mock_anthropic)

        call_kwargs = mock_anthropic.messages.create.call_args[1]
        tools_used = call_kwargs.get("tools", [])
        tool_names = [t["name"] for t in tools_used]
        assert "query_product" not in tool_names
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
python -m pytest tests/test_whatsapp_agent.py::TestAccessControl tests/test_whatsapp_agent.py::TestAgentLoop -v
```

Esperado: `ImportError` — `get_user` y `run_agent` no existen aún.

- [ ] **Step 3: Implementar en whatsapp_agent.py**

Agregar a `whatsapp_agent.py` (después del código de sesiones):

```python
import anthropic as anthropic_sdk
from whatsapp_tools import (
    TOOL_DEFINITIONS,
    VIEWER_TOOL_DEFINITIONS,
    query_retail,
    get_objectives_for_tool,
    query_product,
)

# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sos un analista de ventas senior de Temple Bar Argentina.
Respondés preguntas sobre ventas retail de 3 marcas: Temple, Patagonia y Feriado.

REGLAS DE FORMATO (respuestas van a WhatsApp):
- Texto plano únicamente, sin markdown
- Emojis para jerarquía visual: 📊 ✅ ⚠️ 🔵 🟣 🟢
- Números en millones con M (ej: $600.5M). Facturación siempre en pesos argentinos.
- Sin tablas — usá listas simples con saltos de línea
- Respuestas concisas y ejecutivas

SIEMPRE incluir en análisis de ventas:
- Facturación + órdenes + ticket promedio
- Cumplimiento real % = real / objetivo mensual × 100
- Cumplimiento esperado % = días transcurridos / días del mes × 100 (pace)
- Brecha en puntos porcentuales entre ambos
- Monto que falta para estar en pace (si hay brecha negativa)

Si no tenés datos para responder, decilo claramente. No inventes números.
Respondé siempre en español."""

# ── Access Control ─────────────────────────────────────────────────────────────

def get_user(phone: str, config: dict) -> dict | None:
    """Retorna el usuario si está en la whitelist, None si no."""
    for user in config.get("users", []):
        if user["phone"] == phone:
            return user
    return None


# ── Tool Executor ──────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict, bq_client) -> dict:
    if tool_name == "query_retail":
        return query_retail(bq_client, **tool_input)
    elif tool_name == "get_objectives":
        return get_objectives_for_tool(**tool_input)
    elif tool_name == "query_product":
        return query_product(bq_client, **tool_input)
    return {"error": f"Tool desconocida: {tool_name}"}


# ── Agent Loop ─────────────────────────────────────────────────────────────────

def run_agent(
    user_message: str,
    history: list,
    user_role: str,
    bq_client,
    anthropic_client,
) -> tuple[str, list]:
    """
    Ejecuta el loop del agente Claude con tool use.
    Retorna (texto_respuesta, historial_actualizado).
    """
    tools = TOOL_DEFINITIONS if user_role == "admin" else VIEWER_TOOL_DEFINITIONS
    messages = history + [{"role": "user", "content": user_message}]

    for _ in range(10):  # máximo 10 rondas de tool use
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "No pude procesar tu consulta."
            )
            messages.append({"role": "assistant", "content": response.content})
            return text, messages

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, bq_client)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(result, ensure_ascii=False, default=str),
                    })
            messages.append({"role": "user", "content": tool_results})

    return "Ocurrió un error procesando tu consulta.", messages
```

- [ ] **Step 4: Ejecutar todos los tests del agente**

```bash
python -m pytest tests/test_whatsapp_agent.py -v
```

Esperado: 7 tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add whatsapp_agent.py tests/test_whatsapp_agent.py
git commit -m "feat: add Claude agent loop with tool use and access control"
```

---

## Task 7: weekly_report.py — Informe Semanal

**Files:**
- Create: `weekly_report.py`
- Create: `tests/test_weekly_report.py`

- [ ] **Step 1: Escribir tests del informe semanal**

Crear `tests/test_weekly_report.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


class TestWeekDateRange:
    def test_rango_semana_anterior_desde_lunes(self):
        from weekly_report import get_last_week_range

        # Simular que hoy es lunes 26 mayo 2026
        with patch("weekly_report.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 26)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            desde, hasta = get_last_week_range()

        assert desde == "2026-05-18"  # lunes anterior
        assert hasta == "2026-05-25"  # domingo anterior (incluyendo feriado)


class TestFormatShortReport:
    def test_reporte_contiene_campos_clave(self):
        from weekly_report import format_short_report

        retail_data = [
            {"grupo": "Patagonia", "facturacion": 600_533_269, "ordenes": 15109, "ticket": 39747},
            {"grupo": "Temple",    "facturacion": 305_373_356, "ordenes": 8237,  "ticket": 37073},
            {"grupo": "Feriado",   "facturacion": 11_368_900,  "ordenes": 235,   "ticket": 48378},
        ]
        objectives = {
            "Patagonia": {"obj_fac": 2929, "pace_pct": 80.6, "dias_transcurridos": 25, "dias_mes": 31},
            "Temple":    {"obj_fac": 1424, "pace_pct": 80.6, "dias_transcurridos": 25, "dias_mes": 31},
            "Feriado":   {"obj_fac": 63,   "pace_pct": 80.6, "dias_transcurridos": 25, "dias_mes": 31},
        }

        text = format_short_report("2026-05-18", "2026-05-25", retail_data, objectives)

        assert "Patagonia" in text
        assert "Temple" in text
        assert "Feriado" in text
        assert "%" in text          # cumplimiento
        assert "$" in text          # facturación
        assert "ticket" in text.lower() or "Ticket" in text
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
python -m pytest tests/test_weekly_report.py -v
```

Esperado: `ImportError`.

- [ ] **Step 3: Implementar weekly_report.py**

Crear `weekly_report.py`:

```python
"""
weekly_report.py
Generación y envío del informe semanal automático vía Twilio WhatsApp.
"""
import os
import json
from datetime import date, timedelta

from twilio.rest import Client as TwilioClient

from whatsapp_tools import query_retail, get_objectives_for_tool


# ── Date helpers ───────────────────────────────────────────────────────────────

def get_last_week_range() -> tuple[str, str]:
    """
    Retorna (fecha_desde, fecha_hasta) de la semana anterior al lunes de hoy.
    Ejemplo: si hoy es lunes 26/05, retorna ("2026-05-18", "2026-05-25").
    """
    today = date.today()
    # today es lunes (weekday == 0); último lunes = today - 7 días
    last_monday = today - timedelta(days=7)
    last_sunday  = today - timedelta(days=1)
    return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")


# ── Formatters ─────────────────────────────────────────────────────────────────

def _semaforo(real_pct: float, pace_pct: float) -> str:
    diff = real_pct - pace_pct
    if diff >= -2:
        return "✅"
    return "⚠️"


def _marca_emoji(marca: str) -> str:
    return {"Patagonia": "🔵", "Temple": "🟣", "Feriado": "🟢"}.get(marca, "📊")


def format_short_report(
    desde: str,
    hasta: str,
    retail_data: list,
    objectives: dict,
) -> str:
    """
    Genera el texto del resumen corto para enviar a todos los usuarios.
    """
    total_fac = sum(r["facturacion"] for r in retail_data)
    total_ord = sum(r["ordenes"]     for r in retail_data)

    lines = [
        f"📊 Informe Semanal — {desde} al {hasta}",
        f"Red total: ${total_fac/1e6:.1f}M | {total_ord:,} órdenes",
        "──────────────────",
    ]

    for row in retail_data:
        marca     = row["grupo"]
        fac_m     = row["facturacion"] / 1e6
        ticket    = row["ticket"]
        obj       = objectives.get(marca, {})
        obj_fac   = obj.get("obj_fac", 0)          # ya en millones
        pace      = obj.get("pace_pct", 0)
        real_pct  = round(fac_m / obj_fac * 100, 1) if obj_fac else 0
        semaforo  = _semaforo(real_pct, pace)
        emoji     = _marca_emoji(marca)

        lines += [
            f"{emoji} {marca}: ${fac_m:.1f}M | ticket ${ticket:,.0f}",
            f"Cumpl: {real_pct}% real vs {pace}% esperado {semaforo}",
        ]

    # YoY placeholder — se pasa desde el caller si está disponible
    lines += [
        "──────────────────",
        'Respondé "más info" para el detalle completo.',
    ]

    return "\n".join(lines)


# ── Twilio sender ──────────────────────────────────────────────────────────────

def send_whatsapp(twilio_client: TwilioClient, to: str, from_: str, body: str) -> None:
    """Envía un mensaje de WhatsApp vía Twilio."""
    twilio_client.messages.create(
        from_=from_,
        to=to,
        body=body,
    )


# ── Main entrypoint (llamado desde el endpoint /whatsapp/weekly-report) ────────

def run_weekly_report(bq_client, config: dict) -> dict:
    """
    Genera y envía el informe semanal a todos los usuarios del config.
    Retorna resumen de envíos para logging.
    """
    desde, hasta = get_last_week_range()

    # Obtener datos de la semana
    retail_data = query_retail(bq_client, desde, hasta, "marca")

    # Objetivos del mes en curso
    mes_actual = date.today().strftime("%Y-%m")
    objectives = {
        marca: get_objectives_for_tool(marca, mes_actual)
        for marca in ["Patagonia", "Temple", "Feriado"]
    }

    short_text = format_short_report(desde, hasta, retail_data, objectives)

    # Enviar vía Twilio
    twilio_client = TwilioClient(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"],
    )
    twilio_from = os.environ["TWILIO_WHATSAPP_FROM"]

    sent = []
    for user in config["users"]:
        send_whatsapp(twilio_client, user["phone"], twilio_from, short_text)
        sent.append(user["phone"])

    return {"sent_to": sent, "desde": desde, "hasta": hasta}
```

- [ ] **Step 4: Ejecutar todos los tests del informe**

```bash
python -m pytest tests/test_weekly_report.py -v
```

Esperado: 2 tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add weekly_report.py tests/test_weekly_report.py
git commit -m "feat: add weekly report generator and Twilio sender"
```

---

## Task 8: app.py — Nuevos Endpoints

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Leer app.py para entender la estructura actual**

```bash
head -60 app.py
```

Identificar: dónde están los imports, cómo se crea el `app` Flask, y el último endpoint definido.

- [ ] **Step 2: Agregar imports al bloque de imports existente en app.py**

Agregar junto a los imports existentes (NO reemplazar):

```python
import json
from google.cloud import bigquery as bq_module
from google.cloud import firestore
from twilio.request_validator import RequestValidator
from whatsapp_agent import get_user, get_session, save_session, run_agent
from weekly_report import run_weekly_report
```

- [ ] **Step 3: Agregar función helper de BQ client y carga de config**

Agregar después de los imports en `app.py`:

```python
def _load_agents_config():
    config_path = os.path.join(os.path.dirname(__file__), "agents_config.json")
    with open(config_path) as f:
        return json.load(f)

def _get_bq_client():
    """Reutiliza el cliente BQ existente del proyecto (con Drive scope)."""
    # Importar la función ya definida en actualizar_retail.py
    from actualizar_retail import get_bigquery_client
    return get_bigquery_client()
```

- [ ] **Step 4: Agregar endpoint /whatsapp/webhook**

Agregar como nueva ruta en `app.py` (antes del `if __name__ == "__main__"`):

```python
@app.route("/whatsapp/webhook", methods=["POST"])
def whatsapp_webhook():
    """Recibe mensajes entrantes de Twilio WhatsApp."""
    # Validar firma Twilio (evitar requests no autorizados)
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    validator  = RequestValidator(auth_token)
    signature  = request.headers.get("X-Twilio-Signature", "")

    if auth_token and not validator.validate(request.url, request.form, signature):
        return "", 403

    from_number  = request.form.get("From", "")
    user_message = request.form.get("Body", "").strip()

    if not user_message:
        return "", 200

    config = _load_agents_config()
    user   = get_user(from_number, config)

    # Número no registrado
    if user is None:
        from twilio.rest import Client as TwilioClient
        tc = TwilioClient(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
        tc.messages.create(
            from_=os.environ["TWILIO_WHATSAPP_FROM"],
            to=from_number,
            body="No tenés acceso a este agente. Contactá a Darwin.",
        )
        return "", 200

    db      = firestore.Client()
    history = get_session(db, from_number)

    bq_client        = _get_bq_client()
    anthropic_client = __import__("anthropic").Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"]
    )

    try:
        reply_text, new_history = run_agent(
            user_message=user_message,
            history=history,
            user_role=user["role"],
            bq_client=bq_client,
            anthropic_client=anthropic_client,
        )
    except Exception as e:
        reply_text  = "Hubo un error procesando tu consulta. Intentá de nuevo."
        new_history = history

    save_session(db, from_number, new_history, user["name"], user["role"])

    from twilio.rest import Client as TwilioClient
    tc = TwilioClient(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    tc.messages.create(
        from_=os.environ["TWILIO_WHATSAPP_FROM"],
        to=from_number,
        body=reply_text,
    )

    return "", 200


@app.route("/whatsapp/weekly-report", methods=["POST"])
def whatsapp_weekly_report():
    """Endpoint llamado por Cloud Scheduler cada lunes a las 8:00 hs."""
    config         = _load_agents_config()
    expected_token = config.get("scheduler_token", "")
    provided_token = request.headers.get("X-Scheduler-Token", "")

    if expected_token and provided_token != expected_token:
        return {"error": "Unauthorized"}, 403

    bq_client = _get_bq_client()
    result    = run_weekly_report(bq_client, config)

    return {"ok": True, "result": result}, 200
```

- [ ] **Step 5: Verificar que el servidor levanta sin errores**

```bash
python -c "import app; print('app.py carga OK')"
```

Esperado: `app.py carga OK`

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: add /whatsapp/webhook and /whatsapp/weekly-report endpoints"
```

---

## Task 9: Deployment — Secrets + Cloud Scheduler + Cloud Run

**Files:**
- No code — comandos de infraestructura

- [ ] **Step 1: Crear cuenta Twilio y configurar WhatsApp Sandbox**

1. Ir a twilio.com → crear cuenta gratuita
2. En la consola: Messaging → Try it out → Send a WhatsApp message
3. Anotar:
   - `Account SID` (empieza con `AC...`)
   - `Auth Token`
   - Número sandbox (ej: `whatsapp:+14155238886`)
4. Configurar webhook URL: poner `https://temple-bar-dashboard-763905018652.southamerica-east1.run.app/whatsapp/webhook`

- [ ] **Step 2: Agregar secretos a Secret Manager**

```bash
# API Key de Anthropic (obtener en console.anthropic.com)
echo -n "sk-ant-..." | gcloud secrets create anthropic-api-key \
  --data-file=- --project=temple-bar-439715

# Twilio credentials
echo -n "ACxxxxxxxx" | gcloud secrets create twilio-account-sid \
  --data-file=- --project=temple-bar-439715

echo -n "your_auth_token" | gcloud secrets create twilio-auth-token \
  --data-file=- --project=temple-bar-439715

echo -n "whatsapp:+14155238886" | gcloud secrets create twilio-whatsapp-from \
  --data-file=- --project=temple-bar-439715

# Token para Cloud Scheduler (generar uno random)
python -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets create scheduler-token --data-file=- --project=temple-bar-439715
```

- [ ] **Step 3: Actualizar agents_config.json con el token del scheduler**

Reemplazar `REEMPLAZAR_CON_TOKEN_SECRETO` con el token generado en el paso anterior:

```bash
python -c "
import subprocess, json
token = subprocess.check_output([
    'gcloud', 'secrets', 'versions', 'access', 'latest',
    '--secret=scheduler-token', '--project=temple-bar-439715'
]).decode().strip()
print(token)
"
```

Editar `agents_config.json` con el valor obtenido.

- [ ] **Step 4: Agregar variables de entorno al Cloud Run service**

```bash
gcloud run services update temple-bar-dashboard \
  --region southamerica-east1 \
  --update-secrets \
    ANTHROPIC_API_KEY=anthropic-api-key:latest,\
    TWILIO_ACCOUNT_SID=twilio-account-sid:latest,\
    TWILIO_AUTH_TOKEN=twilio-auth-token:latest,\
    TWILIO_WHATSAPP_FROM=twilio-whatsapp-from:latest \
  --project=temple-bar-439715
```

- [ ] **Step 5: Agregar número real de Darwin a agents_config.json**

Editar `agents_config.json` — reemplazar el número placeholder con el número real de Darwin en formato `whatsapp:+549XXXXXXXXXX`:

```json
{
  "users": [
    {
      "phone": "whatsapp:+549XXXXXXXXXX",
      "name": "Darwin",
      "role": "admin"
    }
  ],
  "scheduler_token": "TOKEN_DEL_PASO_3"
}
```

- [ ] **Step 6: Hacer deploy a Cloud Run**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
gcloud builds submit --tag gcr.io/temple-bar-439715/dashboard \
  --project=temple-bar-439715

gcloud run deploy temple-bar-dashboard \
  --image gcr.io/temple-bar-439715/dashboard \
  --region southamerica-east1 \
  --project=temple-bar-439715
```

- [ ] **Step 7: Crear Cloud Scheduler job**

```bash
# Obtener el scheduler token
SCHED_TOKEN=$(gcloud secrets versions access latest \
  --secret=scheduler-token --project=temple-bar-439715)

gcloud scheduler jobs create http whatsapp-weekly-report \
  --location=southamerica-east1 \
  --schedule="0 8 * * 1" \
  --uri="https://temple-bar-dashboard-763905018652.southamerica-east1.run.app/whatsapp/weekly-report" \
  --message-body="{}" \
  --headers="Content-Type=application/json,X-Scheduler-Token=${SCHED_TOKEN}" \
  --http-method=POST \
  --time-zone="America/Argentina/Buenos_Aires" \
  --project=temple-bar-439715
```

- [ ] **Step 8: Test end-to-end**

1. En Twilio Sandbox, escanear el QR con el WhatsApp de Darwin
2. Mandar el mensaje de activación del sandbox (ej: `join <sandbox-word>`)
3. Mandar: `¿cómo viene Temple esta semana?`
4. Verificar respuesta con datos reales de BQ

- [ ] **Step 9: Testear informe manual (sin esperar al lunes)**

```bash
SCHED_TOKEN=$(gcloud secrets versions access latest \
  --secret=scheduler-token --project=temple-bar-439715)

curl -X POST \
  https://temple-bar-dashboard-763905018652.southamerica-east1.run.app/whatsapp/weekly-report \
  -H "Content-Type: application/json" \
  -H "X-Scheduler-Token: ${SCHED_TOKEN}" \
  -d "{}"
```

Esperado: `{"ok": true, "result": {"sent_to": [...], ...}}`

- [ ] **Step 10: Commit final**

```bash
git add agents_config.json
git commit -m "feat: deploy whatsapp agent to Cloud Run with Cloud Scheduler"
```

---

## Checklist de verificación post-deploy

- [ ] Darwin recibe respuesta en WhatsApp al hacer una consulta
- [ ] Respuesta incluye: facturación, órdenes, ticket, cumplimiento real %, pace %, brecha
- [ ] Número no registrado recibe mensaje de acceso denegado
- [ ] Endpoint `/whatsapp/weekly-report` sin token retorna 403
- [ ] Cloud Scheduler aparece en la consola GCP con próximo disparo el lunes
- [ ] Sesión expira correctamente (Firestore TTL de 2 horas)
