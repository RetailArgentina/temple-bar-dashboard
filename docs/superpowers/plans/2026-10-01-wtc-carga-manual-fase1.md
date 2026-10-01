# WTC (Uruguay) — Fase 1: carga manual + tipo de cambio + tablero retail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Darwin carga a mano, por mes, facturación UYU, órdenes y litros de WTC en `/admin`; el pipeline retail baja el tipo de cambio oficial BCRA, convierte a ARS y suma WTC a Patagonia en las pestañas Ventas y Finanzas del tablero retail.

**Architecture:** Un módulo nuevo `wtc.py` (parser puro, tipo de cambio BCRA, lectura/escritura BigQuery) que usan tanto `app.py` (formulario admin) como `actualizar_retail.py` (pipeline). `incorporar_wtc()` es una función pura en `actualizar_retail.py` que suma WTC a los datasets ya consultados (`MENSUAL`, `LOCAL_MENSUAL`, `LOCALES_OBJ`, `LOC_COUNT_BY_MES`) **antes** de `compute_pd`/`compute_preset_meses`. El tablero recibe además `WTC_INFO` para la nota/avisos. Todo lo de WTC falla en blando: sin datos de WTC el tablero sale como hoy.

**Tech Stack:** Python 3.11, Flask + Flask-WTF (CSRF), google-cloud-bigquery, requests, pytest, Node (tests JS de la plantilla), GitHub Actions (pipeline), Cloud Run `temple-bar-dashboard`.

**Spec:** `docs/superpowers/specs/2026-10-01-wtc-carga-manual-design.md` (rama `feat/wtc-carga-manual`). Leer la spec antes de cada tarea.

## Global Constraints

- Proyecto/dataset BQ: `temple-bar-439715.Corporativo`. Tablas: `wtc_manual_mensual`, `tipo_cambio_uyu_ars` (columnas exactas de la spec).
- Upsert con `MERGE` y **lista de columnas explícita** en `INSERT (...) VALUES (...)` — nunca `INSERT ROW`.
- API tipo de cambio: `GET https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/UYU?fechadesde=YYYY-MM-DD&fechahasta=YYYY-MM-DD`, campo `results[].detalle[].tipoCotizacion` (ARS por UYU). Timeout corto, **2 reintentos**. Nunca lanza.
- Conversión mensual = `facturacion_uyu × promedio de días hábiles del mes`. Mes sin cotización: **no se suma** y se avisa. Nunca se inventa una cotización.
- Historia desde `2025-01`. Validación de mes: entre `2025-01` y el mes actual.
- Nombre del local: `WTC` (match con la planilla de objetivos por `UPPER(TRIM())`). Marca `Patagonia` (`"P"` en `LOCALES_OBJ`/`LOC_COUNT_BY_MES`).
- `fac_M = facturacion_uyu × ars_por_uyu / 1e6`. Ticket mensual Patagonia: `tick = round((tick·ord_ar + fac_M·1e6) / (ord_ar + ordenes))`.
- CSRF en admin: header `X-CSRFToken` con la variable JS `CSRF_TOKEN` ya definida en `templates/admin.html` (`'{{ csrf_token() }}'`) — nunca leer de cookie. Decorador `@require_admin`.
- Texto de la nota: `"WTC (Uruguay): carga manual mensual, convertida al oficial BCRA"`.
- Log del pipeline: los avisos de WTC empiezan con `WARN WTC` (el deploy los busca con `grep FALLÓ|WARN WTC`).
- Tests: correr siempre con `python -X utf8 -m pytest ...` (sin `-X utf8` 3 tests de `test_finanzas_js.py` fallan por encoding en Windows; es preexistente). Baseline verificado 01/10: `tests/test_ipc_indec.py tests/test_actualizar_retail_helpers.py tests/test_finanzas_js.py tests/test_auth.py tests/test_excepciones_js.py` → 138 passed. No correr `pytest` sin rutas desde la raíz: recolecta subproyectos y falla en colección (preexistente).
- GateGuard (hook del repo): antes de cada Edit/Write presentar en el mismo mensaje los 4 hechos (quién llama, funciones afectadas, estructura de datos, instrucción del usuario).

## Review Focus

1. **Pegado desde una planilla con fila de encabezado** (`mes  facturacion  ordenes  litros`) → se ignora el encabezado, no da error en la línea 1. Test: `test_parse_ignora_encabezado` (Task 1).
2. **Número ambiguo `1.234` (sin coma)** → se lee como mil doscientos treinta y cuatro (formato argentino, separador de miles), y `1234.5` como decimal. Test: `test_parse_numero_punto_con_tres_digitos_es_miles` (Task 1).
3. **Carga del mes en curso antes de que BQ tenga ventas de ese mes** (p. ej. el día 1) → WTC no crea un mes nuevo en `MENSUAL` (eso correría el "mes actual" de todos los presets); se omite y no rompe nada. Test: `test_incorporar_no_crea_meses_fuera_de_mensual` (Task 6).
4. **API BCRA caída en el primer run** (tabla de cotizaciones vacía) → el pipeline publica igual, WTC queda fuera, la nota lo dice; nunca se usa una cotización inventada. Tests: `test_actualizar_tc_api_caida_no_lanza_ni_escribe` (Task 2) y `test_incorporar_mes_sin_cotizacion_se_excluye_y_avisa` (Task 6).
5. **Guardar con un error en una sola fila de un pegado de 20** → no se escribe ninguna fila (todo o nada), y el servidor vuelve a validar aunque el navegador mande filas "ya validadas". Tests: `test_wtc_post_con_error_no_escribe` y `test_wtc_post_revalida_desde_texto` (Task 4).

---

## File Structure

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `wtc.py` | Crear | Parser/validación del pegado, tipo de cambio BCRA (descarga, promedio, meses pendientes, actualización), I/O BigQuery de las 2 tablas. Sin Flask, sin HTML. |
| `sql/wtc_tablas.sql` | Crear | DDL versionado de las 2 tablas (se corre una vez). |
| `app.py` | Modificar | 3 rutas `/api/admin/wtc*` (delgadas, delegan en `wtc`). |
| `templates/admin.html` | Modificar | Pestaña "WTC Uruguay" (textarea, vista previa, guardar, tabla de control). |
| `actualizar_retail.py` | Modificar | `incorporar_wtc()` (pura), `fetch_wtc()`, `inject_wtc_info()`, cableado en `main()` y `generate_html_from_file()`. |
| `templates/dashboard.html` | Modificar | `const WTC_INFO`, `wtcNotaTexto()` (pura), `buildWtcNota()`, dos `<p class="note">` (Ventas y Finanzas), llamada en `updateAll()`. |
| `tests/test_wtc.py` | Crear | Parser, tipo de cambio, I/O BQ con cliente falso, `incorporar_wtc`, `inject_wtc_info`. |
| `tests/test_wtc_admin.py` | Crear | Rutas admin (permisos, preview no escribe, todo-o-nada, CSRF). |
| `tests/test_wtc_js.py` | Crear | `wtcNotaTexto`, `buildWtcNota`, same-store con WTC. |

---

### Task 1: Parser del pegado (`wtc_parse_filas`)

**Files:**
- Create: `wtc.py`
- Test: `tests/test_wtc.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `wtc.MES_MIN = "2025-01"`
  - `wtc.parse_mes(s: str) -> str | None` → `"YYYY-MM"` o `None`
  - `wtc.parse_numero(s: str) -> float | None`
  - `wtc.wtc_parse_filas(texto: str, hoy: date) -> tuple[list[dict], list[dict]]` → `(filas, errores)`; fila = `{"mes": "2025-01", "facturacion_uyu": float, "ordenes": int, "litros_cerveza": float}`; error = `{"linea": int (1-based, del texto pegado), "error": str}`. Si hay **cualquier** error, `filas` igual trae las válidas (para la vista previa); quien guarda debe exigir `errores == []`.

Reglas (decididas en este plan, coherentes con la spec):
- Separador de columnas: tab, `;` o cualquier espacio (ninguno de los formatos válidos de mes/número tiene espacios, así que aceptar un espacio simple es más permisivo sin ambigüedad).
- Mes: `2025-01`, `01/2025`, `1/2025`, `ene-25`, `ene-2025` (también `set` = septiembre; sin distinguir mayúsculas).
- Número: con coma → formato argentino (`12.345.678,50`); sin coma y con varios puntos, o con un único punto seguido de exactamente 3 dígitos (`1.234`) → separador de miles; si no, punto decimal (`12345678.50`). Se permite `$` pegado adelante (`$1.000`).
- `ordenes` debe ser entero.
- Primera línea no vacía cuyo primer campo empieza con `mes` (sin distinguir mayúsculas) = encabezado, se ignora.
- Líneas vacías se ignoran. Exactamente 4 columnas.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_wtc.py — WTC Uruguay: parser del pegado, tipo de cambio BCRA, BigQuery (falso),
incorporación al tablero retail."""
from datetime import date

import pytest

import wtc

HOY = date(2026, 10, 1)


# ── parse_mes / parse_numero ─────────────────────────────────────────────────

@pytest.mark.parametrize("s,esperado", [
    ("2025-01", "2025-01"), ("01/2025", "2025-01"), ("1/2025", "2025-01"),
    ("ene-25", "2025-01"), ("ENE-25", "2025-01"), ("ene-2025", "2025-01"),
    ("set-25", "2025-09"), ("sep-25", "2025-09"), ("dic-26", "2026-12"),
])
def test_parse_mes_formatos_validos(s, esperado):
    assert wtc.parse_mes(s) == esperado


@pytest.mark.parametrize("s", ["2025-13", "13/2025", "xyz-25", "", "2025", "enero"])
def test_parse_mes_invalidos(s):
    assert wtc.parse_mes(s) is None


@pytest.mark.parametrize("s,esperado", [
    ("12.345.678,50", 12345678.5), ("12345678.50", 12345678.5), ("12345678", 12345678.0),
    ("1.234", 1234.0), ("1234,5", 1234.5), ("$1.000", 1000.0), ("0", 0.0),
])
def test_parse_numero(s, esperado):
    assert wtc.parse_numero(s) == esperado


def test_parse_numero_punto_con_tres_digitos_es_miles():
    # Review Focus #2: "1.234" en Argentina es mil doscientos treinta y cuatro
    assert wtc.parse_numero("1.234") == 1234.0
    assert wtc.parse_numero("1234.5") == 1234.5


@pytest.mark.parametrize("s", ["abc", "1,2,3", "", "-", "-5", "$", "1.2.3,4,5"])
def test_parse_numero_invalidos(s):
    assert wtc.parse_numero(s) is None


# ── wtc_parse_filas ──────────────────────────────────────────────────────────

def test_parse_filas_tab_punto_y_coma_y_espacios():
    texto = "2025-01\t12.345.678,50\t1.200\t3.400,5\n03/2025;1;2;3\nfeb-25   100   2   3"
    filas, errores = wtc.wtc_parse_filas(texto, HOY)
    assert errores == []
    assert filas == [
        {"mes": "2025-01", "facturacion_uyu": 12345678.5, "ordenes": 1200, "litros_cerveza": 3400.5},
        {"mes": "2025-03", "facturacion_uyu": 1.0, "ordenes": 2, "litros_cerveza": 3.0},
        {"mes": "2025-02", "facturacion_uyu": 100.0, "ordenes": 2, "litros_cerveza": 3.0},
    ]


def test_parse_ignora_encabezado():
    # Review Focus #1
    filas, errores = wtc.wtc_parse_filas("Mes\tFacturacion UYU\tOrdenes\tLitros\n2025-01\t10\t1\t1", HOY)
    assert errores == [] and [f["mes"] for f in filas] == ["2025-01"]


def test_parse_ignora_lineas_vacias():
    filas, errores = wtc.wtc_parse_filas("\n\n2025-01 10 1 1\n   \n", HOY)
    assert errores == [] and len(filas) == 1


def test_parse_errores_por_linea():
    texto = "\n".join([
        "2025-01 10 1 1",        # ok (línea 1)
        "2024-12 10 1 1",        # antes de 2025-01
        "2026-11 10 1 1",        # después del mes actual (HOY = oct-26)
        "2025-02 -5 1 1",        # negativo
        "2025-03 10 1,5 1",      # órdenes no entera
        "2025-04 10 1",          # faltan columnas
        "2025-01 20 2 2",        # mes repetido
        "abc 10 1 1",            # mes inválido
        "2025-05 diez 1 1",      # número inválido
    ])
    filas, errores = wtc.wtc_parse_filas(texto, HOY)
    assert [e["linea"] for e in errores] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert "2025-01" in errores[0]["error"]
    assert "repetido" in errores[5]["error"]
    assert [f["mes"] for f in filas] == ["2025-01"]


def test_parse_mes_actual_es_valido():
    filas, errores = wtc.wtc_parse_filas("2026-10 10 1 1", HOY)
    assert errores == [] and filas[0]["mes"] == "2026-10"


def test_parse_texto_vacio_da_error():
    filas, errores = wtc.wtc_parse_filas("   \n ", HOY)
    assert filas == [] and errores == [{"linea": 0, "error": "No hay filas para cargar"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q`
Expected: FAIL / ERROR con `ModuleNotFoundError: No module named 'wtc'`

- [ ] **Step 3: Write minimal implementation**

```python
"""WTC (Uruguay): carga manual mensual con conversión UYU→ARS.

Lo usan app.py (formulario /admin) y actualizar_retail.py (pipeline del tablero).
Spec: docs/superpowers/specs/2026-10-01-wtc-carga-manual-design.md
"""
import re
from datetime import date

MES_MIN = "2025-01"
_MESES_ES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
             "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


def _mes_str(y, m):
    return f"{y:04d}-{m:02d}" if 1 <= m <= 12 else None


def parse_mes(s):
    """'2025-01' | '01/2025' | 'ene-25' | 'ene-2025' → '2025-01'; None si no se entiende."""
    s = (s or "").strip().lower()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", s):
        return _mes_str(int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", s):
        return _mes_str(int(m[2]), int(m[1]))
    if m := re.fullmatch(r"([a-z]{3})-(\d{2}|\d{4})", s):
        if m[1] not in _MESES_ES:
            return None
        y = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
        return _mes_str(y, _MESES_ES[m[1]])
    return None


def parse_numero(s):
    """Formato argentino ('12.345.678,50', '1.234' = 1234) o plano ('12345678.50'). None si no es número ≥ 0."""
    s = (s or "").strip()
    if s.startswith("$"):
        s = s[1:]
    if not s:
        return None
    if "," in s:
        if s.count(",") > 1:
            return None
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    return float(s)


def wtc_parse_filas(texto, hoy):
    """Parsea el pegado del formulario. Devuelve (filas, errores).
    Fila: {"mes", "facturacion_uyu", "ordenes", "litros_cerveza"}; error: {"linea", "error"}.
    Con cualquier error no se debe guardar nada (lo decide quien llama)."""
    mes_max = f"{hoy.year:04d}-{hoy.month:02d}"
    filas, errores, vistos = [], [], set()
    primera = True
    for n, linea in enumerate((texto or "").splitlines(), start=1):
        if not linea.strip():
            continue
        campos = [c for c in re.split(r"[\t;]|\s+", linea.strip()) if c]
        if primera and campos[0].lower().startswith("mes"):
            primera = False
            continue
        primera = False
        if len(campos) != 4:
            errores.append({"linea": n, "error": f"se esperaban 4 columnas (mes, facturación UYU, órdenes, litros) y hay {len(campos)}"})
            continue
        mes = parse_mes(campos[0])
        if not mes:
            errores.append({"linea": n, "error": f"mes inválido: '{campos[0]}' (usar 2025-01, 01/2025 o ene-25)"})
            continue
        if not (MES_MIN <= mes <= mes_max):
            errores.append({"linea": n, "error": f"mes {mes} fuera de rango ({MES_MIN} a {mes_max})"})
            continue
        if mes in vistos:
            errores.append({"linea": n, "error": f"mes {mes} repetido en el pegado"})
            continue
        fac, ords, lts = (parse_numero(c) for c in campos[1:])
        if fac is None or ords is None or lts is None:
            errores.append({"linea": n, "error": "facturación, órdenes y litros deben ser números ≥ 0"})
            continue
        if ords != int(ords):
            errores.append({"linea": n, "error": f"órdenes debe ser entero: '{campos[2]}'"})
            continue
        vistos.add(mes)
        filas.append({"mes": mes, "facturacion_uyu": round(fac, 2), "ordenes": int(ords),
                      "litros_cerveza": round(lts, 2)})
    if not filas and not errores:
        errores.append({"linea": 0, "error": "No hay filas para cargar"})
    return filas, errores
```

(Los negativos quedan rechazados porque `parse_numero` no acepta `-`: el mensaje "números ≥ 0" cubre ambos casos. `1,5` en órdenes se parsea como 1.5 y cae en "debe ser entero".)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add wtc.py tests/test_wtc.py
git commit -m "feat(wtc): parser del pegado mensual (formatos de mes y número argentino)"
```

---

### Task 2: Tipo de cambio BCRA (`actualizar_tipo_cambio_uyu`)

**Files:**
- Modify: `wtc.py`
- Test: `tests/test_wtc.py`

**Interfaces:**
- Consumes: `wtc.MES_MIN` (Task 1).
- Produces:
  - `wtc.PROYECTO`, `wtc.TABLA_CARGA = "temple-bar-439715.Corporativo.wtc_manual_mensual"`, `wtc.TABLA_TC = "temple-bar-439715.Corporativo.tipo_cambio_uyu_ars"`
  - `wtc.BCRA_URL = "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/UYU"`
  - `wtc.promedio_mensual(payload: dict) -> dict[str, tuple[float, int]]` → `{"2026-09": (ars_por_uyu, dias)}`
  - `wtc.meses_pendientes(existentes: dict[str, bool], hoy: date) -> list[str]` (`existentes` = `{mes: completo}`)
  - `wtc.descargar_cotizaciones(desde: date, hasta: date, intentos=3, espera=2, timeout=10) -> dict` (payload BCRA; lanza `RuntimeError` si fallan los 3 intentos)
  - `wtc._param_filas(filas: list[dict], tipos: dict[str, str]) -> bigquery.QueryJobConfig` (parámetro `@filas` ARRAY<STRUCT>)
  - `wtc.MERGE_TC_SQL: str`
  - `wtc.actualizar_tipo_cambio_uyu(client, hoy: date | None = None, log=print) -> None` — **nunca lanza**

Comportamiento de `actualizar_tipo_cambio_uyu`:
1. `SELECT FORMAT_DATE('%Y-%m', mes) AS mes, completo FROM TABLA_TC` → `existentes`.
2. `pendientes = meses_pendientes(existentes, hoy)`; si vacío → log `"  ✓ WTC tipo de cambio al día"` y return.
3. `descargar_cotizaciones(date(primer_pendiente, día 1), hoy)` → `promedio_mensual`; quedarse con meses en `pendientes` y `dias > 0`.
4. `completo = mes < mes_actual`. MERGE con `MERGE_TC_SQL`.
5. Cualquier excepción → `log(f"  WARN WTC tipo de cambio: {exc}")` y return.

- [ ] **Step 1: Write the failing tests** (agregar a `tests/test_wtc.py`)

```python
from types import SimpleNamespace

import requests

# Forma real verificada 01/10/2026 contra la API BCRA (recortada; oct-26 sintético).
BCRA_PAYLOAD = {
    "status": 200,
    "metadata": {"resultset": {"count": 5, "offset": 0, "limit": 1000}},
    "results": [
        {"fecha": "2026-10-01", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.0248, "tipoCotizacion": 37.70}]},
        {"fecha": "2026-09-30", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024846, "tipoCotizacion": 37.691782}]},
        {"fecha": "2026-09-29", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024837, "tipoCotizacion": 37.801925}]},
        {"fecha": "2026-09-28", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024832, "tipoCotizacion": 37.856965}]},
        {"fecha": "2026-09-25", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024766, "tipoCotizacion": 37.780942}]},
    ],
}


class FakeBQ:
    """Cliente BigQuery falso: devuelve filas según un fragmento del SQL y registra las llamadas."""
    def __init__(self, respuestas=None, falla=None):
        self.respuestas = respuestas or {}   # {fragmento_sql: [dict, ...]}
        self.falla = falla
        self.llamadas = []

    def query(self, sql, job_config=None):
        self.llamadas.append((sql, job_config))
        if self.falla:
            raise self.falla
        filas = [] if sql.lstrip().upper().startswith("MERGE") else \
            next((v for k, v in self.respuestas.items() if k in sql), [])
        return SimpleNamespace(result=lambda: [SimpleNamespace(**f) for f in filas])


def _merges(fake):
    return [(sql, jc) for sql, jc in fake.llamadas if sql.lstrip().upper().startswith("MERGE")]


def _struct(p):
    """Valores de un StructQueryParameter como dict {campo: valor}."""
    return dict(p.struct_values)


def test_promedio_mensual_promedia_dias_habiles_por_mes():
    p = wtc.promedio_mensual(BCRA_PAYLOAD)
    sep = (37.691782 + 37.801925 + 37.856965 + 37.780942) / 4
    assert p["2026-09"][0] == pytest.approx(sep) and p["2026-09"][1] == 4
    assert p["2026-10"][0] == pytest.approx(37.70) and p["2026-10"][1] == 1


def test_promedio_mensual_ignora_otras_monedas_y_nulos():
    payload = {"results": [
        {"fecha": "2026-09-30", "detalle": [{"codigoMoneda": "USD", "tipoCotizacion": 1400}]},
        {"fecha": "2026-09-29", "detalle": [{"codigoMoneda": "UYU", "tipoCotizacion": None}]},
        {"fecha": "2026-09-28", "detalle": [{"codigoMoneda": "UYU", "tipoCotizacion": 37.0}]},
    ]}
    assert wtc.promedio_mensual(payload) == {"2026-09": (37.0, 1)}


def test_promedio_mensual_payload_vacio():
    assert wtc.promedio_mensual({}) == {}


def test_meses_pendientes_primera_vez_trae_desde_ene25():
    assert wtc.meses_pendientes({}, date(2025, 3, 10)) == ["2025-01", "2025-02", "2025-03"]


def test_meses_pendientes_solo_faltantes_o_incompletos():
    existentes = {"2025-01": True, "2025-02": False, "2025-03": True}
    assert wtc.meses_pendientes(existentes, date(2025, 4, 2)) == ["2025-02", "2025-04"]


def test_descargar_cotizaciones_reintenta_2_veces_y_lanza(monkeypatch):
    intentos = []
    def get(*a, **kw):
        intentos.append(kw.get("timeout"))
        raise requests.ConnectionError("caída")
    monkeypatch.setattr(wtc.requests, "get", get)
    with pytest.raises(RuntimeError, match="BCRA"):
        wtc.descargar_cotizaciones(date(2026, 9, 1), date(2026, 9, 30), espera=0)
    assert len(intentos) == 3 and all(t and t <= 15 for t in intentos)


def test_descargar_cotizaciones_pasa_rango_de_fechas(monkeypatch):
    visto = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return BCRA_PAYLOAD
    def get(url, params=None, timeout=None):
        visto.update(url=url, params=params)
        return R()
    monkeypatch.setattr(wtc.requests, "get", get)
    assert wtc.descargar_cotizaciones(date(2026, 9, 1), date(2026, 10, 1)) == BCRA_PAYLOAD
    assert visto["url"] == wtc.BCRA_URL
    assert visto["params"]["fechadesde"] == "2026-09-01" and visto["params"]["fechahasta"] == "2026-10-01"


def test_actualizar_tc_escribe_meses_pendientes_con_completo(monkeypatch):
    hechos = [f"2025-{i:02d}" for i in range(1, 13)] + [f"2026-{i:02d}" for i in range(1, 9)]
    fake = FakeBQ({"tipo_cambio_uyu_ars": [{"mes": m, "completo": True} for m in hechos]})
    monkeypatch.setattr(wtc, "descargar_cotizaciones", lambda d, h: BCRA_PAYLOAD)
    wtc.actualizar_tipo_cambio_uyu(fake, HOY, log=lambda *_: None)
    (sql, jc), = _merges(fake)
    assert "INSERT (mes, ars_por_uyu, dias, completo, actualizado_en)" in sql
    assert "INSERT ROW" not in sql
    filas = {_struct(p)["mes"]: _struct(p) for p in jc.query_parameters[0].values}
    assert set(filas) == {"2026-09", "2026-10"}
    assert filas["2026-09"]["completo"] is True and filas["2026-09"]["dias"] == 4
    assert filas["2026-10"]["completo"] is False


def test_actualizar_tc_al_dia_no_llama_a_la_api(monkeypatch):
    todos = [f"2025-{i:02d}" for i in range(1, 13)] + [f"2026-{i:02d}" for i in range(1, 11)]
    fake = FakeBQ({"tipo_cambio_uyu_ars": [{"mes": m, "completo": True} for m in todos]})
    monkeypatch.setattr(wtc, "descargar_cotizaciones", lambda d, h: pytest.fail("no debía llamar"))
    wtc.actualizar_tipo_cambio_uyu(fake, HOY, log=lambda *_: None)
    assert _merges(fake) == []


def test_actualizar_tc_api_caida_no_lanza_ni_escribe(monkeypatch):
    # Review Focus #4
    logs = []
    fake = FakeBQ({})
    def caida(d, h): raise RuntimeError("API BCRA sin respuesta")
    monkeypatch.setattr(wtc, "descargar_cotizaciones", caida)
    wtc.actualizar_tipo_cambio_uyu(fake, HOY, log=logs.append)
    assert _merges(fake) == []
    assert any(l.strip().startswith("WARN WTC") for l in logs)


def test_actualizar_tc_bq_caido_no_lanza():
    logs = []
    wtc.actualizar_tipo_cambio_uyu(FakeBQ(falla=RuntimeError("BQ 503")), HOY, log=logs.append)
    assert any("WARN WTC" in l for l in logs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q -k "promedio or pendientes or descargar or actualizar_tc"`
Expected: FAIL con `AttributeError: module 'wtc' has no attribute 'promedio_mensual'`

- [ ] **Step 3: Write minimal implementation** (agregar a `wtc.py`; arriba sumar `import time`, `import requests` junto a los imports existentes)

```python
PROYECTO = "temple-bar-439715"
TABLA_CARGA = f"{PROYECTO}.Corporativo.wtc_manual_mensual"
TABLA_TC = f"{PROYECTO}.Corporativo.tipo_cambio_uyu_ars"
BCRA_URL = "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/UYU"


def _mes_de(d):
    return f"{d.year:04d}-{d.month:02d}"


def _meses_entre(desde, hasta):
    """'2025-01', '2025-03' → ['2025-01', '2025-02', '2025-03']."""
    y, m = int(desde[:4]), int(desde[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hasta:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def promedio_mensual(payload):
    """Respuesta BCRA → {"YYYY-MM": (promedio ARS por UYU de los días hábiles, cantidad de días)}."""
    por_mes = {}
    for dia in (payload or {}).get("results", []):
        for d in dia.get("detalle", []):
            v = d.get("tipoCotizacion")
            if d.get("codigoMoneda") == "UYU" and v:
                por_mes.setdefault(dia["fecha"][:7], []).append(float(v))
    return {mes: (sum(vs) / len(vs), len(vs)) for mes, vs in por_mes.items()}


def meses_pendientes(existentes, hoy):
    """Meses desde MES_MIN hasta el actual sin fila o con completo = false."""
    return [m for m in _meses_entre(MES_MIN, _mes_de(hoy)) if not existentes.get(m, False)]


def descargar_cotizaciones(desde, hasta, intentos=3, espera=2, timeout=10):
    """Payload BCRA del rango (1 intento + 2 reintentos). Lanza RuntimeError si no responde."""
    params = {"fechadesde": desde.isoformat(), "fechahasta": hasta.isoformat(), "limit": 1000}
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(BCRA_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            ultimo = exc
            if i < intentos - 1:
                time.sleep(espera)
    raise RuntimeError(f"API BCRA sin respuesta: {ultimo}")


def _param_filas(filas, tipos):
    """Lista de dicts → QueryJobConfig con @filas ARRAY<STRUCT>. tipos = {campo: tipo BQ}."""
    from google.cloud import bigquery
    structs = [bigquery.StructQueryParameter(
        None, *[bigquery.ScalarQueryParameter(k, t, f[k]) for k, t in tipos.items()]) for f in filas]
    return bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("filas", "STRUCT", structs)])


MERGE_TC_SQL = f"""
MERGE `{TABLA_TC}` T
USING (SELECT PARSE_DATE('%Y-%m', f.mes) AS mes, CAST(f.ars_por_uyu AS NUMERIC) AS ars_por_uyu,
              f.dias, f.completo
       FROM UNNEST(@filas) AS f) S
ON T.mes = S.mes
WHEN MATCHED THEN UPDATE SET ars_por_uyu = S.ars_por_uyu, dias = S.dias, completo = S.completo,
                             actualizado_en = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (mes, ars_por_uyu, dias, completo, actualizado_en)
                      VALUES (S.mes, S.ars_por_uyu, S.dias, S.completo, CURRENT_TIMESTAMP())
"""


def actualizar_tipo_cambio_uyu(client, hoy=None, log=print):
    """Completa tipo_cambio_uyu_ars con los meses faltantes o incompletos. Nunca lanza."""
    hoy = hoy or date.today()
    try:
        existentes = {r.mes: bool(r.completo) for r in client.query(
            f"SELECT FORMAT_DATE('%Y-%m', mes) AS mes, completo FROM `{TABLA_TC}`").result()}
        pendientes = meses_pendientes(existentes, hoy)
        if not pendientes:
            log("  ✓ WTC tipo de cambio al día")
            return
        desde = date(int(pendientes[0][:4]), int(pendientes[0][5:7]), 1)
        promedios = promedio_mensual(descargar_cotizaciones(desde, hoy))
        mes_actual = _mes_de(hoy)
        filas = [{"mes": m, "ars_por_uyu": f"{promedios[m][0]:.6f}", "dias": promedios[m][1],
                  "completo": m < mes_actual}
                 for m in pendientes if m in promedios and promedios[m][1] > 0]
        if not filas:
            log(f"  WARN WTC tipo de cambio: la API no trajo cotizaciones para {pendientes[0]}..{pendientes[-1]}")
            return
        client.query(MERGE_TC_SQL, job_config=_param_filas(
            filas, {"mes": "STRING", "ars_por_uyu": "STRING", "dias": "INT64", "completo": "BOOL"})).result()
        log(f"  ✓ WTC tipo de cambio: {len(filas)} meses actualizados ({filas[0]['mes']}..{filas[-1]['mes']})")
    except Exception as exc:
        log(f"  WARN WTC tipo de cambio: {exc}")
```

Nota: el helper de test `_struct` lee `StructQueryParameter.struct_values` (atributo de google-cloud-bigquery ≥3). Si la versión instalada lo expone distinto, ajustar **solo** `_struct` en el test (verificar con `python -c "from google.cloud import bigquery as b; p=b.StructQueryParameter(None, b.ScalarQueryParameter('x','STRING','1')); print(vars(p))"`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add wtc.py tests/test_wtc.py
git commit -m "feat(wtc): tipo de cambio UYU→ARS desde BCRA (promedio mensual, nunca lanza)"
```

---

### Task 3: Tablas BQ + lectura/escritura de la carga

**Files:**
- Create: `sql/wtc_tablas.sql`
- Modify: `wtc.py`
- Test: `tests/test_wtc.py`

**Interfaces:**
- Consumes: `wtc.TABLA_CARGA`, `wtc.TABLA_TC`, `wtc._param_filas` (Task 2); `FakeBQ`, `_merges`, `_struct` (helpers de test de Task 2).
- Produces:
  - `wtc.MERGE_CARGA_SQL: str`
  - `wtc.guardar_filas(client, filas: list[dict], email: str) -> int` (filas = salida de `wtc_parse_filas`; devuelve cantidad)
  - `wtc.leer_carga(client) -> list[dict]` → `[{"mes": "2025-01", "facturacion_uyu": float, "ordenes": int, "litros_cerveza": float, "cargado_por": str, "cargado_en": "ISO" | None}]` ordenado por mes
  - `wtc.leer_cotizaciones(client) -> dict[str, float]` → `{"2025-01": 23.6, ...}`

- [ ] **Step 1: Write the failing tests** (agregar a `tests/test_wtc.py`)

```python
def test_guardar_filas_merge_con_columnas_explicitas():
    fake = FakeBQ()
    filas = [{"mes": "2025-01", "facturacion_uyu": 12345678.5, "ordenes": 1200, "litros_cerveza": 3400.5}]
    assert wtc.guardar_filas(fake, filas, "admin@ejemplo.com") == 1
    (sql, jc), = _merges(fake)
    assert "INSERT (mes, facturacion_uyu, ordenes, litros_cerveza, cargado_por, cargado_en)" in sql
    assert "INSERT ROW" not in sql
    params = {p.name: p for p in jc.query_parameters}
    assert params["email"].value == "admin@ejemplo.com"
    assert _struct(params["filas"].values[0]) == {"mes": "2025-01", "facturacion_uyu": "12345678.50",
                                                  "ordenes": 1200, "litros_cerveza": "3400.50"}


def test_guardar_filas_vacio_no_consulta():
    fake = FakeBQ()
    assert wtc.guardar_filas(fake, [], "x@y") == 0 and fake.llamadas == []


def test_leer_carga_convierte_tipos():
    from datetime import datetime, timezone
    from decimal import Decimal
    fake = FakeBQ({"wtc_manual_mensual": [{
        "mes": "2025-01", "facturacion_uyu": Decimal("100.50"), "ordenes": 3,
        "litros_cerveza": Decimal("7.25"), "cargado_por": "a@b",
        "cargado_en": datetime(2026, 10, 1, 12, tzinfo=timezone.utc)}]})
    assert wtc.leer_carga(fake) == [{"mes": "2025-01", "facturacion_uyu": 100.5, "ordenes": 3,
                                     "litros_cerveza": 7.25, "cargado_por": "a@b",
                                     "cargado_en": "2026-10-01T12:00:00+00:00"}]


def test_leer_cotizaciones_devuelve_float_por_mes():
    from decimal import Decimal
    fake = FakeBQ({"tipo_cambio_uyu_ars": [{"mes": "2025-01", "ars_por_uyu": Decimal("23.6")}]})
    assert wtc.leer_cotizaciones(fake) == {"2025-01": 23.6}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q -k "guardar or leer_"`
Expected: FAIL con `AttributeError: module 'wtc' has no attribute 'guardar_filas'`

- [ ] **Step 3: Write minimal implementation**

`sql/wtc_tablas.sql`:

```sql
-- WTC (Uruguay): carga manual mensual + tipo de cambio UYU→ARS.
-- Spec: docs/superpowers/specs/2026-10-01-wtc-carga-manual-design.md. Se corre una sola vez.
CREATE TABLE IF NOT EXISTS `temple-bar-439715.Corporativo.wtc_manual_mensual` (
  mes             DATE      NOT NULL OPTIONS(description="primer día del mes; clave"),
  facturacion_uyu NUMERIC   NOT NULL OPTIONS(description="pesos uruguayos, >= 0"),
  ordenes         INT64     NOT NULL,
  litros_cerveza  NUMERIC   NOT NULL OPTIONS(description="litros reales reportados por WTC"),
  cargado_por     STRING,
  cargado_en      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `temple-bar-439715.Corporativo.tipo_cambio_uyu_ars` (
  mes            DATE      NOT NULL OPTIONS(description="primer día del mes; clave"),
  ars_por_uyu    NUMERIC   NOT NULL OPTIONS(description="promedio de días hábiles, BCRA tipoCotizacion"),
  dias           INT64     NOT NULL,
  completo       BOOL      NOT NULL OPTIONS(description="true si el mes ya había cerrado al calcularlo"),
  actualizado_en TIMESTAMP
);
```

Agregar a `wtc.py`:

```python
MERGE_CARGA_SQL = f"""
MERGE `{TABLA_CARGA}` T
USING (SELECT PARSE_DATE('%Y-%m', f.mes) AS mes, CAST(f.facturacion_uyu AS NUMERIC) AS facturacion_uyu,
              f.ordenes, CAST(f.litros_cerveza AS NUMERIC) AS litros_cerveza
       FROM UNNEST(@filas) AS f) S
ON T.mes = S.mes
WHEN MATCHED THEN UPDATE SET facturacion_uyu = S.facturacion_uyu, ordenes = S.ordenes,
                             litros_cerveza = S.litros_cerveza, cargado_por = @email,
                             cargado_en = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (mes, facturacion_uyu, ordenes, litros_cerveza, cargado_por, cargado_en)
                      VALUES (S.mes, S.facturacion_uyu, S.ordenes, S.litros_cerveza, @email, CURRENT_TIMESTAMP())
"""


def guardar_filas(client, filas, email):
    """Upsert por mes. filas = salida válida de wtc_parse_filas. Devuelve filas escritas."""
    if not filas:
        return 0
    from google.cloud import bigquery
    jc = _param_filas(
        [{"mes": f["mes"], "facturacion_uyu": f"{f['facturacion_uyu']:.2f}", "ordenes": f["ordenes"],
          "litros_cerveza": f"{f['litros_cerveza']:.2f}"} for f in filas],
        {"mes": "STRING", "facturacion_uyu": "STRING", "ordenes": "INT64", "litros_cerveza": "STRING"})
    jc.query_parameters = list(jc.query_parameters) + [bigquery.ScalarQueryParameter("email", "STRING", email)]
    client.query(MERGE_CARGA_SQL, job_config=jc).result()
    return len(filas)


def leer_carga(client):
    q = f"""SELECT FORMAT_DATE('%Y-%m', mes) AS mes, facturacion_uyu, ordenes, litros_cerveza,
                   cargado_por, cargado_en
            FROM `{TABLA_CARGA}` ORDER BY mes"""
    return [{"mes": r.mes, "facturacion_uyu": float(r.facturacion_uyu), "ordenes": int(r.ordenes),
             "litros_cerveza": float(r.litros_cerveza), "cargado_por": r.cargado_por,
             "cargado_en": r.cargado_en.isoformat() if r.cargado_en else None}
            for r in client.query(q).result()]


def leer_cotizaciones(client):
    q = f"SELECT FORMAT_DATE('%Y-%m', mes) AS mes, ars_por_uyu FROM `{TABLA_TC}`"
    return {r.mes: float(r.ars_por_uyu) for r in client.query(q).result()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q`
Expected: all PASS

- [ ] **Step 5: Crear las tablas en BigQuery (una vez)**

Run (desde la raíz del repo, usa la SA local):
```bash
python -X utf8 -c "from actualizar_retail import get_bigquery_client as g; c=g(); [c.query(s).result() for s in open('sql/wtc_tablas.sql',encoding='utf-8').read().split(';') if 'CREATE' in s]; print('OK')"
```
Expected: `OK`. Verificar: `python -X utf8 -c "from actualizar_retail import get_bigquery_client as g; c=g(); print([f.name for f in c.get_table('temple-bar-439715.Corporativo.wtc_manual_mensual').schema])"` → las 6 columnas.

- [ ] **Step 6: Smoke test real del tipo de cambio (escribe la tabla)**

Run: `python -X utf8 -c "import wtc; from actualizar_retail import get_bigquery_client as g; c=g(); wtc.actualizar_tipo_cambio_uyu(c); t=wtc.leer_cotizaciones(c); print(len(t), t.get('2025-01'), t.get('2026-09'))"`
Expected: `✓ WTC tipo de cambio: 22 meses actualizados (2025-01..2026-10)`, luego `22 ~23.6 ~37.8`. Si la API falla: `WARN WTC ...` y reintentar más tarde (intermitencia conocida).

- [ ] **Step 7: Commit**

```bash
git add sql/wtc_tablas.sql wtc.py tests/test_wtc.py
git commit -m "feat(wtc): tablas BQ y lectura/escritura de la carga mensual (MERGE con columnas explícitas)"
```

---

### Task 4: Rutas admin `/api/admin/wtc*`

**Files:**
- Modify: `app.py` (imports ~líneas 20 y 36; rutas nuevas después de `api_admin_save_objectives`, ~línea 1080)
- Test: `tests/test_wtc_admin.py`

**Interfaces:**
- Consumes: `wtc.wtc_parse_filas`, `wtc.guardar_filas`, `wtc.leer_carga`, `wtc.leer_cotizaciones` (Tasks 1–3); `bq_client` global de `app.py`; `require_admin`; `session["user"]["email"]`; fixture `client` y helper `_set_session` de `tests/test_auth.py`.
- Produces (los consume Task 5):
  - `POST /api/admin/wtc/preview` body `{"texto": str}` → `200 {"ok": bool, "filas": [fila + {"ars_por_uyu": float|null, "ars": float|null, "reemplaza": bool}], "errores": [...]}`; `ok = errores == []`. Nunca escribe. BQ falla → `502 {"ok": false, "error": "No se pudo leer BigQuery: ..."}`.
  - `POST /api/admin/wtc` body `{"texto": str}` → `200 {"ok": true, "escritas": n}`; con errores → `400 {"ok": false, "errores": [...]}` sin escribir; BQ falla → `500 {"ok": false, "error": ...}`.
  - `GET /api/admin/wtc` → `200 {"ok": true, "filas": [leer_carga + {"ars_por_uyu", "ars"}]}`; BQ falla → `502`.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_wtc_admin.py — rutas /api/admin/wtc* (BigQuery simulado)."""
from contextlib import ExitStack
from unittest.mock import patch

from tests.test_auth import client, _set_session  # noqa: F401  (fixture reutilizado)

TEXTO_OK = "2025-01\t1.000.000\t500\t1.200"


def _patch_bq(stack, cargados=(), cotiz=None):
    """Simula BigQuery en wtc. Devuelve el mock de guardar_filas."""
    import wtc
    stack.enter_context(patch.object(wtc, "leer_carga", return_value=[{"mes": m} for m in cargados]))
    stack.enter_context(patch.object(wtc, "leer_cotizaciones", return_value=cotiz or {}))
    return stack.enter_context(patch.object(wtc, "guardar_filas", side_effect=lambda c, f, e: len(f)))


def test_wtc_preview_convierte_marca_reemplaza_y_no_escribe(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        guardar = _patch_bq(s, cargados=["2025-01"], cotiz={"2025-01": 23.6})
        r = c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK})
    d = r.get_json()
    assert r.status_code == 200 and d["ok"] is True and d["errores"] == []
    f = d["filas"][0]
    assert f["ars_por_uyu"] == 23.6 and f["ars"] == 23600000.0 and f["reemplaza"] is True
    guardar.assert_not_called()


def test_wtc_preview_mes_sin_cotizacion(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        _patch_bq(s)
        f = c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK}).get_json()["filas"][0]
    assert f["ars_por_uyu"] is None and f["ars"] is None and f["reemplaza"] is False


def test_wtc_post_guarda_con_email_de_sesion(client):
    c, app = client
    _set_session(c, app, role="superadmin")
    with ExitStack() as s:
        guardar = _patch_bq(s)
        r = c.post("/api/admin/wtc", json={"texto": TEXTO_OK})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "escritas": 1}
    assert guardar.call_args[0][2] == "superadmin@temple.com.ar"


def test_wtc_post_con_error_no_escribe(client):
    # Review Focus #5: una fila mala en el pegado → no se guarda nada
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        guardar = _patch_bq(s)
        r = c.post("/api/admin/wtc", json={"texto": TEXTO_OK + "\n2025-02 abc 1 1"})
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert r.get_json()["errores"][0]["linea"] == 2
    guardar.assert_not_called()


def test_wtc_post_revalida_desde_texto(client):
    # Review Focus #5: el servidor ignora "filas" mandadas por el navegador
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        guardar = _patch_bq(s)
        r = c.post("/api/admin/wtc", json={"texto": "", "filas": [{"mes": "2025-01", "facturacion_uyu": -1}]})
    assert r.status_code == 400
    guardar.assert_not_called()


def test_wtc_get_lista_con_ars(client):
    import wtc
    c, app = client
    _set_session(c, app, role="gerencia")
    fila = {"mes": "2025-01", "facturacion_uyu": 1000.0, "ordenes": 5, "litros_cerveza": 2.0,
            "cargado_por": "a@b", "cargado_en": "2026-10-01T12:00:00+00:00"}
    with patch.object(wtc, "leer_carga", return_value=[fila]), \
         patch.object(wtc, "leer_cotizaciones", return_value={"2025-01": 23.6}):
        d = c.get("/api/admin/wtc").get_json()
    assert d["ok"] is True and d["filas"][0]["ars"] == 23600.0 and d["filas"][0]["ars_por_uyu"] == 23.6


def test_wtc_preview_bq_caido_502(client):
    import wtc
    c, app = client
    _set_session(c, app, role="gerencia")
    with patch.object(wtc, "leer_carga", side_effect=RuntimeError("BQ 503")):
        r = c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK})
    assert r.status_code == 502 and r.get_json()["ok"] is False


def test_wtc_bloquea_viewer(client):
    c, app = client
    _set_session(c, app, role="viewer")
    assert c.get("/api/admin/wtc").status_code == 403
    assert c.post("/api/admin/wtc", json={"texto": TEXTO_OK}).status_code == 403
    assert c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK}).status_code == 403


def test_wtc_post_requiere_csrf(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        with ExitStack() as s:
            guardar = _patch_bq(s)
            r = c.post("/api/admin/wtc", json={"texto": TEXTO_OK})
        assert r.status_code == 400
        guardar.assert_not_called()
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc_admin.py -q`
Expected: FAIL (`assert 404 == 200` y similares)

- [ ] **Step 3: Write minimal implementation** (en `app.py`)

Imports: cambiar `from datetime import datetime, timedelta, timezone` por `from datetime import date, datetime, timedelta, timezone`; agregar `import wtc` debajo de `import permissions`.

Rutas, después de `api_admin_save_objectives`:

```python
# ---------------------------------------------------------------------------
# Admin: WTC Uruguay — carga manual mensual (spec 2026-10-01-wtc-carga-manual)
# ---------------------------------------------------------------------------

def _wtc_con_ars(filas, cotiz):
    for f in filas:
        c = cotiz.get(f["mes"])
        f["ars_por_uyu"] = c
        f["ars"] = round(f["facturacion_uyu"] * c, 2) if c else None
    return filas


@app.route("/api/admin/wtc", methods=["GET"])
@require_admin
def api_admin_wtc_list():
    try:
        filas = _wtc_con_ars(wtc.leer_carga(bq_client), wtc.leer_cotizaciones(bq_client))
    except Exception as exc:
        logger.warning("WTC: no se pudo leer BigQuery: %s", exc)
        return jsonify({"ok": False, "error": f"No se pudo leer BigQuery: {exc}"}), 502
    return jsonify({"ok": True, "filas": filas})


@app.route("/api/admin/wtc/preview", methods=["POST"])
@require_admin
def api_admin_wtc_preview():
    """Parsea el pegado y muestra la conversión. No escribe."""
    texto = (request.get_json(silent=True) or {}).get("texto", "")
    filas, errores = wtc.wtc_parse_filas(texto, date.today())
    try:
        cargados = {r["mes"] for r in wtc.leer_carga(bq_client)}
        cotiz = wtc.leer_cotizaciones(bq_client)
    except Exception as exc:
        logger.warning("WTC preview: no se pudo leer BigQuery: %s", exc)
        return jsonify({"ok": False, "error": f"No se pudo leer BigQuery: {exc}"}), 502
    for f in _wtc_con_ars(filas, cotiz):
        f["reemplaza"] = f["mes"] in cargados
    return jsonify({"ok": not errores, "filas": filas, "errores": errores})


@app.route("/api/admin/wtc", methods=["POST"])
@require_admin
def api_admin_wtc_save():
    """Vuelve a validar el texto (no confía en el navegador) y hace el MERGE. Todo o nada."""
    texto = (request.get_json(silent=True) or {}).get("texto", "")
    filas, errores = wtc.wtc_parse_filas(texto, date.today())
    if errores:
        return jsonify({"ok": False, "errores": errores}), 400
    try:
        n = wtc.guardar_filas(bq_client, filas, session["user"]["email"])
    except Exception as exc:
        logger.error("WTC: falló el MERGE: %s", exc)
        return jsonify({"ok": False, "error": f"No se pudo guardar en BigQuery: {exc}"}), 500
    logger.info("WTC: %d meses cargados por %s", n, session["user"]["email"])
    return jsonify({"ok": True, "escritas": n})
```

(Verificar que el logger del módulo se llama `logger`: `grep -n "^logger" app.py`. Si se llama distinto, usar ese nombre.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc_admin.py tests/test_auth.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_wtc_admin.py
git commit -m "feat(wtc): rutas /api/admin/wtc (preview sin escribir, guardar todo-o-nada)"
```

---

### Task 5: Pestaña "WTC Uruguay" en `/admin`

**Files:**
- Modify: `templates/admin.html` (botón en `.tab-nav` ~línea 553; panel después del cierre de `#tab-objetivos`; rama en `switchTab` ~línea 1008; JS nuevo después del bloque `// ── Objectives tab`)
- Test: `tests/test_wtc_admin.py`

**Interfaces:**
- Consumes: las 3 rutas de Task 4; `CSRF_TOKEN` (variable JS existente, línea ~849); clases CSS existentes `obj-import-box`, `obj-input`, `btn-preview`, `btn-save-obj`, `obj-preview-errors`, `obj-preview-area`, `obj-msg`, `table-wrap`.
- Produces: `#tab-wtc`, funciones JS `wtcPreview()`, `wtcGuardar()`, `wtcCargar()`, variable `wtcCargado`.

- [ ] **Step 1: Write the failing test** (agregar a `tests/test_wtc_admin.py`)

```python
def test_admin_muestra_pestana_wtc_con_csrf_jinja(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    html = c.get("/admin").get_data(as_text=True)
    assert 'id="tab-wtc"' in html and "switchTab('wtc')" in html
    assert "/api/admin/wtc/preview" in html
    # CSRF desde la variable Jinja, nunca de cookie
    assert "'X-CSRFToken': CSRF_TOKEN" in html and "document.cookie" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -X utf8 -m pytest tests/test_wtc_admin.py::test_admin_muestra_pestana_wtc_con_csrf_jinja -q`
Expected: FAIL (`assert 'id="tab-wtc"' in html`)

- [ ] **Step 3: Write minimal implementation**

Antes de escribir: `grep -n "\.obj-msg\." templates/admin.html` para confirmar los nombres de clase de éxito/error que usa `showObjMsg` (abajo se asumen `success` y `error`; si son otros, usar esos).

Botón (después del de Objetivos; visible para gerencia y superadmin):

```html
    <button class="tab-btn" onclick="switchTab('wtc')">WTC Uruguay</button>
```

Panel (después del cierre de `#tab-objetivos`):

```html
  <!-- ════════════════════════════════════════════════════════════ -->
  <!-- TAB: WTC Uruguay — carga mensual (spec 2026-10-01)          -->
  <div id="tab-wtc" class="tab-panel">
    <div id="wtc-msg" class="obj-msg"></div>
    <div class="obj-import-box">
      <h3>WTC Uruguay · carga mensual</h3>
      <p style="color:#8b949e;font-size:12px;margin-bottom:12px;">
        Pegá una fila por mes (tab, <code>;</code> o espacios):<br>
        <code style="color:#c9a227">mes &nbsp; facturación UYU &nbsp; órdenes &nbsp; litros cerveza</code><br>
        Mes: <code>2025-01</code>, <code>01/2025</code> o <code>ene-25</code>. Números: <code>12.345.678,50</code> o <code>12345678.50</code>.
        Si el mes ya está cargado, se reemplaza.
      </p>
      <textarea id="wtc-texto" class="obj-input" rows="8" style="width:100%;font-family:monospace"
                placeholder="2026-09&#9;12.345.678,50&#9;4.210&#9;3.150"></textarea>
      <button class="btn-preview" onclick="wtcPreview()">Vista previa</button>
      <button class="btn-save-obj" id="btn-wtc-save" style="display:none" onclick="wtcGuardar()">Guardar</button>
      <div class="obj-preview-errors" id="wtc-errores"></div>
      <div class="obj-preview-area" id="wtc-preview"></div>
    </div>
    <h3 style="font-size:14px;font-weight:600;color:#8b949e;margin:16px 0 12px;">Cargado</h3>
    <div class="table-wrap" style="overflow-x:auto">
      <table>
        <thead><tr><th>Mes</th><th>Facturación UYU</th><th>ARS por UYU</th><th>Facturación ARS</th>
          <th>Órdenes</th><th>Litros</th><th>Cargado por</th><th>Cuándo</th></tr></thead>
        <tbody id="wtc-body"><tr><td colspan="8" style="color:#8b949e;text-align:center">Cargando...</td></tr></tbody>
      </table>
    </div>
  </div>
```

Rama en `switchTab` (antes del `else` final):

```javascript
      } else if (tab === 'wtc') {
        var wBtn = document.querySelector('.tab-btn[onclick*="wtc"]');
        if (wBtn) wBtn.classList.add('active');
        document.getElementById('tab-wtc').classList.add('active');
        if (!wtcCargado) wtcCargar();
```

JS (después del bloque `// ── Objectives tab`):

```javascript
    // ── WTC Uruguay ─────────────────────────────────────────────────────────
    var wtcCargado = false;
    function _wtcNum(v, dec) {
      return (v === null || v === undefined) ? '—'
        : Number(v).toLocaleString('es-AR', { minimumFractionDigits: dec || 0, maximumFractionDigits: dec || 0 });
    }
    function _wtcEsc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
    function _wtcMsg(text, type) {
      var el = document.getElementById('wtc-msg');
      el.textContent = text; el.className = 'obj-msg ' + type; el.style.display = 'block';
      setTimeout(function() { el.style.display = 'none'; }, 6000);
    }
    function wtcPreview() {
      var errEl = document.getElementById('wtc-errores'), prevEl = document.getElementById('wtc-preview');
      var btn = document.getElementById('btn-wtc-save');
      btn.style.display = 'none'; errEl.style.display = 'none'; prevEl.innerHTML = '';
      fetch('/api/admin/wtc/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ texto: document.getElementById('wtc-texto').value })
      }).then(function(r) { return r.json(); }).then(function(d) {
        if (d.error) { _wtcMsg(d.error, 'error'); return; }
        if (d.errores && d.errores.length) {
          errEl.innerHTML = d.errores.map(function(e) {
            return (e.linea ? 'Línea ' + e.linea + ': ' : '') + _wtcEsc(e.error);
          }).join('<br>') + '<br><b>No se guarda nada hasta corregir.</b>';
          errEl.style.display = 'block';
        }
        var h = '<table style="font-size:12px;border-collapse:collapse;min-width:100%"><tr><th>Mes</th><th>UYU</th>'
          + '<th>ARS por UYU</th><th>ARS</th><th>Órdenes</th><th>Litros</th><th></th></tr>';
        (d.filas || []).forEach(function(f) {
          h += '<tr><td>' + f.mes + '</td><td>' + _wtcNum(f.facturacion_uyu, 2) + '</td><td>'
            + (f.ars_por_uyu ? _wtcNum(f.ars_por_uyu, 4) : 'sin cotización (no se suma al tablero)')
            + '</td><td>' + _wtcNum(f.ars, 0) + '</td><td>' + _wtcNum(f.ordenes) + '</td><td>'
            + _wtcNum(f.litros_cerveza, 1) + '</td><td>' + (f.reemplaza ? 'reemplaza' : 'nuevo') + '</td></tr>';
        });
        prevEl.innerHTML = h + '</table>';
        if (d.ok) btn.style.display = 'inline-block';
      }).catch(function(e) { _wtcMsg('Error: ' + e, 'error'); });
    }
    function wtcGuardar() {
      fetch('/api/admin/wtc', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ texto: document.getElementById('wtc-texto').value })
      }).then(function(r) { return r.json(); }).then(function(d) {
        if (!d.ok) { _wtcMsg(d.error || 'Hay errores: revisá la vista previa', 'error'); return; }
        _wtcMsg(d.escritas + ' mes(es) guardados. Se ven en el tablero en la próxima actualización.', 'success');
        document.getElementById('btn-wtc-save').style.display = 'none';
        document.getElementById('wtc-preview').innerHTML = '';
        document.getElementById('wtc-texto').value = '';
        wtcCargar();
      }).catch(function(e) { _wtcMsg('Error: ' + e, 'error'); });
    }
    function wtcCargar() {
      var body = document.getElementById('wtc-body');
      fetch('/api/admin/wtc', { headers: { 'X-CSRFToken': CSRF_TOKEN } })
        .then(function(r) { return r.json(); }).then(function(d) {
          wtcCargado = true;
          if (!d.ok) { body.innerHTML = '<tr><td colspan="8">' + _wtcEsc(d.error) + '</td></tr>'; return; }
          if (!d.filas.length) { body.innerHTML = '<tr><td colspan="8" style="color:#8b949e;text-align:center">Sin meses cargados</td></tr>'; return; }
          body.innerHTML = d.filas.slice().reverse().map(function(f) {
            return '<tr><td>' + f.mes + '</td><td>' + _wtcNum(f.facturacion_uyu, 2) + '</td><td>'
              + (f.ars_por_uyu ? _wtcNum(f.ars_por_uyu, 4) : 'sin cotización') + '</td><td>' + _wtcNum(f.ars, 0)
              + '</td><td>' + _wtcNum(f.ordenes) + '</td><td>' + _wtcNum(f.litros_cerveza, 1) + '</td><td>'
              + _wtcEsc(f.cargado_por) + '</td><td>' + _wtcEsc((f.cargado_en || '').slice(0, 16).replace('T', ' ')) + '</td></tr>';
          }).join('');
        }).catch(function(e) { body.innerHTML = '<tr><td colspan="8">Error: ' + _wtcEsc(e) + '</td></tr>'; });
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc_admin.py tests/test_auth.py -q`
Expected: all PASS

- [ ] **Step 5: Verificación manual local**

Levantar la app local como se hace habitualmente para probar `/admin` (env vars de `config.py`), entrar como gerencia → pestaña WTC → pegar `ene-25 1.000 10 5` → Vista previa muestra ARS ≈ 23.600 y "nuevo"; pegar una línea mala → aparece el error con número de línea y no aparece "Guardar". **No** apretar Guardar salvo que Darwin quiera dejar ese mes cargado (es la tabla real). Ver también a 375px de ancho (la tabla de preview scrollea dentro de su caja).

- [ ] **Step 6: Commit**

```bash
git add templates/admin.html tests/test_wtc_admin.py
git commit -m "feat(wtc): pestaña WTC Uruguay en /admin (pegar filas, vista previa, tabla de control)"
```

---

### Task 6: `incorporar_wtc()` en el pipeline retail

**Files:**
- Modify: `actualizar_retail.py` (función nueva después de `compute_preset_meses`, ~línea 817)
- Test: `tests/test_wtc.py`

**Interfaces:**
- Consumes: `_prev_month` (existente en `actualizar_retail.py`); forma de los datasets existentes:
  - `mensual_rows`: `[{"mes", "m", "fac": int (M ARS), "ord": int, "tick": int}]`
  - `local_mensual_rows`: `[{"mes", "m", "l", "fac": float (M, 3 dec), "ord": int}]`
  - `locales_obj_data`: `[{"b": "P"|"T", "l": "LOCAL UPPER", "d": {"YYYY-MM": [real_M, obj_M, real_ord, obj_ord]}}]`
  - `loc_count_by_mes`: `{"YYYY-MM": {"P": n, "T": n, "F": n}}`
  - `wtc_data`: `{"filas": [salida de wtc.leer_carga], "cotizaciones": {mes: float}}` o `None` (falló la consulta)
- Produces:
  - `incorporar_wtc(wtc_data, mensual_rows, local_mensual_rows, locales_obj_data, loc_count_by_mes, hoy: date) -> tuple[list, list, list, dict, dict]` → `(mensual, local_mensual, locales_obj, loc_count, wtc_info)`. **No muta** las entradas.
  - `wtc_info`: `{"error": bool, "meses": [meses sumados], "sin_cotizacion": [meses], "ultimo_cerrado": "YYYY-MM", "mes_actual": "YYYY-MM", "falta_ultimo_cerrado": bool, "falta_mes_actual": bool}`

Reglas:
- Solo se suman meses que ya existen en `mensual_rows` (Review Focus #3). Si el mes existe pero no hay fila Patagonia, se agrega.
- `MENSUAL`: `fac = round(fac + fac_M)` (entero, como el resto), `ord += ordenes`, `tick` ponderado (Global Constraints; con denominador 0 queda el original).
- `LOCAL_MENSUAL`: fila nueva `{"mes", "m": "Patagonia", "l": "WTC", "fac": round(fac_M, 3), "ord": ordenes}`.
- `LOCALES_OBJ`: entrada con `b == "P"` y `l.strip().upper() == "WTC"`; por mes sumado presente en `d`: `d[mes][0] = round(fac_M, 1)`, `d[mes][2] = ordenes`.
- `LOC_COUNT_BY_MES`: `P += 1` en meses sumados presentes en el dict.
- `falta_ultimo_cerrado` / `falta_mes_actual`: el mes no está cargado (independiente de la cotización).

- [ ] **Step 1: Write the failing tests** (agregar a `tests/test_wtc.py`)

```python
import copy

from actualizar_retail import incorporar_wtc

MENSUAL = [
    {"mes": "2026-08", "m": "Patagonia", "fac": 1000, "ord": 10000, "tick": 100000},
    {"mes": "2026-08", "m": "Temple", "fac": 500, "ord": 5000, "tick": 100000},
    {"mes": "2026-09", "m": "Patagonia", "fac": 1100, "ord": 11000, "tick": 100000},
    {"mes": "2026-10", "m": "Temple", "fac": 50, "ord": 500, "tick": 100000},
]
LOCAL_MENSUAL = [{"mes": "2026-09", "m": "Patagonia", "l": "PALERMO", "fac": 100.0, "ord": 1000}]
LOCALES_OBJ = [
    {"b": "P", "l": "WTC", "d": {"2026-08": [0, 80.0, 0, 9000], "2026-09": [0, 85.0, 0, 9500]}},
    {"b": "P", "l": "PALERMO", "d": {"2026-09": [100.0, 90.0, 1000, 900]}},
]
LOC_COUNT = {"2026-08": {"P": 30, "T": 19, "F": 1}, "2026-09": {"P": 31, "T": 19, "F": 1}}
WTC_DATA = {
    "filas": [{"mes": "2026-08", "facturacion_uyu": 2_000_000.0, "ordenes": 2000, "litros_cerveza": 900.0},
              {"mes": "2026-09", "facturacion_uyu": 2_500_000.0, "ordenes": 2500, "litros_cerveza": 950.0}],
    "cotizaciones": {"2026-08": 36.0, "2026-09": 37.8},
}


def _inc(wtc_data=WTC_DATA, hoy=HOY, mensual=MENSUAL):
    return incorporar_wtc(wtc_data, mensual, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT, hoy)


def test_incorporar_suma_a_patagonia_mensual_con_ticket_ponderado():
    mensual, *_ = _inc()
    ago = next(r for r in mensual if r["mes"] == "2026-08" and r["m"] == "Patagonia")
    fac_M = 2_000_000 * 36.0 / 1e6                      # 72 M ARS
    assert ago["fac"] == round(1000 + fac_M)             # 1072
    assert ago["ord"] == 12000
    assert ago["tick"] == round((100000 * 10000 + fac_M * 1e6) / 12000)
    assert next(r for r in mensual if r["mes"] == "2026-08" and r["m"] == "Temple") == MENSUAL[1]


def test_incorporar_agrega_fila_local_wtc():
    _, local, *_ = _inc()
    assert [r for r in local if r["l"] == "WTC"] == [
        {"mes": "2026-08", "m": "Patagonia", "l": "WTC", "fac": 72.0, "ord": 2000},
        {"mes": "2026-09", "m": "Patagonia", "l": "WTC", "fac": 94.5, "ord": 2500},
    ]


def test_incorporar_completa_real_de_wtc_en_objetivos():
    _, _, obj, *_ = _inc()
    w = next(e for e in obj if e["l"] == "WTC")
    assert w["d"]["2026-08"] == [72.0, 80.0, 2000, 9000]
    assert w["d"]["2026-09"] == [94.5, 85.0, 2500, 9500]


def test_incorporar_cuenta_wtc_como_local_patagonia():
    *_, cnt, _ = _inc()
    assert cnt["2026-08"]["P"] == 31 and cnt["2026-09"]["P"] == 32 and cnt["2026-08"]["T"] == 19


def test_incorporar_mes_sin_cotizacion_se_excluye_y_avisa():
    # Review Focus #4
    data = {"filas": WTC_DATA["filas"], "cotizaciones": {"2026-08": 36.0}}
    mensual, local, obj, cnt, info = _inc(data)
    assert next(r for r in mensual if r["mes"] == "2026-09" and r["m"] == "Patagonia") == MENSUAL[2]
    assert [r["mes"] for r in local if r["l"] == "WTC"] == ["2026-08"]
    assert next(e for e in obj if e["l"] == "WTC")["d"]["2026-09"][0] == 0
    assert cnt["2026-09"]["P"] == 31
    assert info["sin_cotizacion"] == ["2026-09"] and info["meses"] == ["2026-08"]


def test_incorporar_no_crea_meses_fuera_de_mensual():
    # Review Focus #3: oct-26 cargado pero MENSUAL no tiene el mes → no se inventa
    mensual_sin_oct = [r for r in MENSUAL if r["mes"] != "2026-10"]
    data = {"filas": WTC_DATA["filas"] + [{"mes": "2026-10", "facturacion_uyu": 1.0, "ordenes": 1,
                                           "litros_cerveza": 1.0}],
            "cotizaciones": {**WTC_DATA["cotizaciones"], "2026-10": 37.7}}
    mensual, local, *_ = _inc(data, mensual=mensual_sin_oct)
    assert {r["mes"] for r in mensual} == {"2026-08", "2026-09"}
    assert "2026-10" not in {r["mes"] for r in local if r["l"] == "WTC"}


def test_incorporar_mes_existente_sin_fila_patagonia_la_agrega():
    data = {"filas": [{"mes": "2026-10", "facturacion_uyu": 1_000_000.0, "ordenes": 100,
                       "litros_cerveza": 1.0}], "cotizaciones": {"2026-10": 37.7}}
    mensual, *_ = _inc(data)
    pat = [r for r in mensual if r["mes"] == "2026-10" and r["m"] == "Patagonia"]
    assert pat == [{"mes": "2026-10", "m": "Patagonia", "fac": 38, "ord": 100, "tick": 377000}]


def test_incorporar_sin_datos_deja_datasets_intactos():
    for data in (None, {"filas": [], "cotizaciones": {}}):
        mensual, local, obj, cnt, info = _inc(data)
        assert (mensual, local, obj, cnt) == (MENSUAL, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT)
    assert _inc(None)[4]["error"] is True


def test_incorporar_no_muta_entradas():
    antes = copy.deepcopy((MENSUAL, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT))
    _inc()
    assert (MENSUAL, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT) == antes


def test_incorporar_info_avisa_meses_faltantes():
    info = _inc()[4]                                   # HOY = 2026-10-01: sep cargado, oct no
    assert info["ultimo_cerrado"] == "2026-09" and info["falta_ultimo_cerrado"] is False
    assert info["mes_actual"] == "2026-10" and info["falta_mes_actual"] is True
    assert _inc(hoy=date(2026, 11, 3))[4]["falta_ultimo_cerrado"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q -k incorporar`
Expected: FAIL con `ImportError: cannot import name 'incorporar_wtc'`

- [ ] **Step 3: Write minimal implementation** (en `actualizar_retail.py`, después de `compute_preset_meses`)

```python
def incorporar_wtc(wtc_data, mensual_rows, local_mensual_rows, locales_obj_data, loc_count_by_mes, hoy):
    """Suma WTC (Uruguay, carga manual mensual convertida a ARS) a Patagonia. Pura: no muta.
    wtc_data = {"filas": wtc.leer_carga(), "cotizaciones": wtc.leer_cotizaciones()} o None si falló.
    Solo suma meses que ya están en MENSUAL (no crea meses: correría el "mes actual").
    Devuelve (mensual, local_mensual, locales_obj, loc_count, wtc_info)."""
    import copy
    mensual = copy.deepcopy(mensual_rows)
    local_mensual = copy.deepcopy(local_mensual_rows)
    locales_obj = copy.deepcopy(locales_obj_data)
    loc_count = copy.deepcopy(loc_count_by_mes)
    mes_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    ultimo_cerrado = _prev_month(mes_actual)
    cargados = {f["mes"] for f in (wtc_data or {}).get("filas", [])}
    info = {"error": wtc_data is None, "meses": [], "sin_cotizacion": [],
            "ultimo_cerrado": ultimo_cerrado, "mes_actual": mes_actual,
            "falta_ultimo_cerrado": ultimo_cerrado not in cargados,
            "falta_mes_actual": mes_actual not in cargados}
    if not wtc_data:
        return mensual, local_mensual, locales_obj, loc_count, info

    meses_mensual = {r["mes"] for r in mensual}
    cotiz = wtc_data.get("cotizaciones", {})
    wtc_obj = next((e for e in locales_obj if e["b"] == "P" and e["l"].strip().upper() == "WTC"), None)
    for f in sorted(wtc_data.get("filas", []), key=lambda x: x["mes"]):
        mes = f["mes"]
        if mes not in meses_mensual:
            continue
        if not cotiz.get(mes):
            info["sin_cotizacion"].append(mes)
            continue
        fac_M = f["facturacion_uyu"] * cotiz[mes] / 1e6
        ordenes = int(f["ordenes"])
        pat = next((r for r in mensual if r["mes"] == mes and r["m"] == "Patagonia"), None)
        if pat is None:
            pat = {"mes": mes, "m": "Patagonia", "fac": 0, "ord": 0, "tick": 0}
            mensual.append(pat)
        ord_ar = pat["ord"]
        if ord_ar + ordenes > 0:
            pat["tick"] = round((pat["tick"] * ord_ar + fac_M * 1e6) / (ord_ar + ordenes))
        pat["fac"] = round(pat["fac"] + fac_M)
        pat["ord"] = ord_ar + ordenes
        local_mensual.append({"mes": mes, "m": "Patagonia", "l": "WTC", "fac": round(fac_M, 3), "ord": ordenes})
        if wtc_obj and mes in wtc_obj["d"]:
            wtc_obj["d"][mes][0] = round(fac_M, 1)
            wtc_obj["d"][mes][2] = ordenes
        if mes in loc_count:
            loc_count[mes]["P"] = loc_count[mes].get("P", 0) + 1
        info["meses"].append(mes)
    mensual.sort(key=lambda r: (r["mes"], r["m"]))
    return mensual, local_mensual, locales_obj, loc_count, info
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc.py tests/test_actualizar_retail_helpers.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add actualizar_retail.py tests/test_wtc.py
git commit -m "feat(wtc): incorporar_wtc suma WTC convertido a Patagonia (mensual, local, objetivos, conteo)"
```

---

### Task 7: Cableado en el pipeline (`fetch_wtc`, `inject_wtc_info`, `main`)

**Files:**
- Modify: `actualizar_retail.py` (`fetch_wtc` e `inject_wtc_info` después de `inject_ipc`; `generate_html_from_file` gana `wtc_info=None`; `main()`)
- Test: `tests/test_wtc.py`

**Interfaces:**
- Consumes: `wtc.actualizar_tipo_cambio_uyu`, `wtc.leer_carga`, `wtc.leer_cotizaciones` (Tasks 2–3); `incorporar_wtc` (Task 6).
- Produces:
  - `fetch_wtc(client, hoy=None) -> dict` → `{"filas": [...], "cotizaciones": {...}}` (lanza si falla la lectura; `_safe` de `main` lo convierte en `None`)
  - `inject_wtc_info(html: str, info: dict | None) -> str` reemplaza `__WTC_INFO_JSON__` (marcador que agrega Task 8).

- [ ] **Step 1: Write the failing tests** (agregar a `tests/test_wtc.py`)

```python
import json

import actualizar_retail


def test_inject_wtc_info_reemplaza_marcador():
    info = {"error": False, "meses": ["2026-09"]}
    html = actualizar_retail.inject_wtc_info("const WTC_INFO = __WTC_INFO_JSON__;", info)
    assert json.loads(html.split("= ", 1)[1].rstrip(";")) == info


def test_inject_wtc_info_sin_marcador_no_cambia():
    assert actualizar_retail.inject_wtc_info("<html>", {"x": 1}) == "<html>"


def test_fetch_wtc_actualiza_tc_y_lee_tablas(monkeypatch):
    orden = []
    monkeypatch.setattr(wtc, "actualizar_tipo_cambio_uyu", lambda c, hoy=None, log=print: orden.append("tc"))
    monkeypatch.setattr(wtc, "leer_carga", lambda c: orden.append("carga") or [{"mes": "2026-09"}])
    monkeypatch.setattr(wtc, "leer_cotizaciones", lambda c: orden.append("cotiz") or {"2026-09": 37.8})
    d = actualizar_retail.fetch_wtc(object(), HOY)
    assert orden == ["tc", "carga", "cotiz"]
    assert d == {"filas": [{"mes": "2026-09"}], "cotizaciones": {"2026-09": 37.8}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc.py -q -k "inject_wtc or fetch_wtc"`
Expected: FAIL con `AttributeError: module 'actualizar_retail' has no attribute 'inject_wtc_info'`

- [ ] **Step 3: Write minimal implementation**

Después de `inject_ipc`:

```python
def fetch_wtc(client, hoy=None):
    # WTC (Uruguay): primero completa el tipo de cambio BCRA (nunca lanza), después lee la carga
    # manual y las cotizaciones. Si la lectura falla, _safe devuelve None y el tablero sale sin WTC.
    import wtc
    print("  WTC: tipo de cambio + carga manual...", flush=True)
    wtc.actualizar_tipo_cambio_uyu(client, hoy)
    filas = wtc.leer_carga(client)
    cotizaciones = wtc.leer_cotizaciones(client)
    print(f"  ✓ WTC: {len(filas)} meses cargados, {len(cotizaciones)} cotizaciones")
    return {"filas": filas, "cotizaciones": cotizaciones}


def inject_wtc_info(html, info):
    """Reemplaza __WTC_INFO_JSON__ (nota y avisos de WTC en Ventas y Finanzas)."""
    if '__WTC_INFO_JSON__' not in html:
        return html
    return html.replace('__WTC_INFO_JSON__', json.dumps(info, separators=(',', ':')))
```

En `generate_html_from_file`: agregar `wtc_info=None` al final de la firma y, debajo de `html = inject_ultima_venta(html, ultima_venta_rows)`:

```python
    html = inject_wtc_info(html, wtc_info)
```

En `main()`:
1. En `tasks`, agregar `"wtc": lambda: fetch_wtc(client),`.
2. Después del bloque `if not mensual_rows: ... sys.exit(1)` y **antes** de `latest_mes = ...`:

```python
        # WTC (Uruguay, carga manual): se suma antes de compute_pd/compute_preset_meses
        from datetime import date as _date
        mensual_rows, local_mensual_rows, locales_obj_data, loc_count_by_mes, wtc_info = incorporar_wtc(
            results["wtc"], mensual_rows, local_mensual_rows, locales_obj_data, loc_count_by_mes, _date.today())
        if wtc_info["error"]:
            print("  WARN WTC: no se pudo leer la carga manual — tablero sin WTC")
        if wtc_info["sin_cotizacion"]:
            print(f"  WARN WTC: meses sin cotización (no sumados): {', '.join(wtc_info['sin_cotizacion'])}")
        if wtc_info["falta_ultimo_cerrado"]:
            print(f"  WARN WTC: falta cargar {wtc_info['ultimo_cerrado']}")
        print(f"  ✓ WTC sumado a Patagonia: {', '.join(wtc_info['meses']) or 'ningún mes'}")
```

3. En la llamada a `generate_html_from_file(...)` agregar `wtc_info=wtc_info,`.

(`compute_dias_data` usa `data['ventas']` diarias: WTC no entra ahí, como dice la spec.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc.py tests/test_actualizar_retail_helpers.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add actualizar_retail.py tests/test_wtc.py
git commit -m "feat(wtc): pipeline retail lee WTC, actualiza tipo de cambio e inyecta WTC_INFO"
```

---

### Task 8: Nota WTC en Ventas y Finanzas (`templates/dashboard.html`)

**Files:**
- Modify: `templates/dashboard.html` (const debajo de `const ULTIMA_VENTA = __ULTIMA_VENTA_JSON__;` ~línea 500; `<p>` en `#view-economico` después del `</section>` de Indicadores ~línea 190; `<p>` en `#view-finanzas` antes de `#finEstimadoNota` ~línea 402; funciones nuevas antes de `function updateAll`; llamada en `updateAll`)
- Modify: `tests/test_finanzas_js.py` (stub `buildWtcNota` en el test de `updateAll`)
- Test: `tests/test_wtc_js.py`, `tests/test_wtc.py`

**Interfaces:**
- Consumes: `__WTC_INFO_JSON__` (Task 7), `STATE.marca`, `finLocalesComunes` (existente), helpers `run_js`, `run_dom_js` de `tests/test_finanzas_js.py`.
- Produces:
  - `function _wtcMes(m)` → `"sep-26"`
  - `function wtcNotaTexto(info, finanzas)` pura → `string` (`""` si `info` es null)
  - `function buildWtcNota()` → escribe `#wtcNotaVentas` y `#wtcNotaFin`; los oculta si `STATE.marca` no es `todas` ni `Patagonia`.

Textos:
- Base: `"WTC (Uruguay): carga manual mensual, convertida al oficial BCRA."`
- Finanzas agrega: `" Se deflacta con IPC argentino como el resto; en same-store entra solo si tiene cargado el mismo mes del año anterior."`
- `error` → `" ⚠ No se pudo leer la carga de WTC: este tablero no lo incluye."` (y nada más)
- `falta_ultimo_cerrado` → `" ⚠ Falta cargar sep-26."`
- `falta_mes_actual` → `" Mes en curso (oct-26) sin cargar."`
- `sin_cotizacion` no vacío → `" ⚠ Sin cotización BCRA (no sumados): ago-26, sep-26."`

- [ ] **Step 1: Write the failing tests**

`tests/test_wtc_js.py`:

```python
"""tests/test_wtc_js.py — nota WTC del tablero retail y same-store con WTC (Node)."""
import pytest

from tests.test_finanzas_js import run_js, run_dom_js, pytestmark  # noqa: F401  (skip sin Node)

INFO_OK = ('{error:false,meses:["2026-09"],sin_cotizacion:[],ultimo_cerrado:"2026-09",'
           'mes_actual:"2026-10",falta_ultimo_cerrado:false,falta_mes_actual:true}')
FN = ["_wtcMes", "wtcNotaTexto"]


def test_wtc_nota_ventas_basica_y_mes_en_curso(tmp_path):
    t = run_dom_js(FN, "", f"wtcNotaTexto({INFO_OK},false)", tmp_path)
    assert t.startswith("WTC (Uruguay): carga manual mensual, convertida al oficial BCRA.")
    assert "Mes en curso (oct-26) sin cargar." in t and "deflacta" not in t


def test_wtc_nota_finanzas_aclara_ipc_y_same_store(tmp_path):
    t = run_dom_js(FN, "", f"wtcNotaTexto({INFO_OK},true)", tmp_path)
    assert "IPC argentino" in t and "same-store" in t


def test_wtc_nota_avisos(tmp_path):
    info = ('{error:false,meses:[],sin_cotizacion:["2026-08","2026-09"],ultimo_cerrado:"2026-09",'
            'mes_actual:"2026-10",falta_ultimo_cerrado:true,falta_mes_actual:false}')
    t = run_dom_js(FN, "", f"wtcNotaTexto({info},false)", tmp_path)
    assert "Falta cargar sep-26." in t and "Sin cotización BCRA (no sumados): ago-26, sep-26." in t


def test_wtc_nota_error_y_null(tmp_path):
    r = run_dom_js(FN, "", '[wtcNotaTexto({error:true,meses:[],sin_cotizacion:[]},false),wtcNotaTexto(null,false)]',
                   tmp_path)
    assert "No se pudo leer la carga de WTC" in r[0] and r[1] == ""


@pytest.mark.parametrize("marca,display", [("todas", "block"), ("Patagonia", "block"), ("Temple", "none")])
def test_build_wtc_nota_se_oculta_en_otras_marcas(tmp_path, marca, display):
    setup = f'const WTC_INFO={INFO_OK};const STATE={{marca:"{marca}"}};buildWtcNota();'
    r = run_dom_js(FN + ["buildWtcNota"], setup,
                   "[_els.wtcNotaVentas.style.display,_els.wtcNotaFin.style.display,_els.wtcNotaFin.textContent]",
                   tmp_path)
    assert r[0] == display and r[1] == display and r[2].startswith("WTC (Uruguay)")


def test_same_store_incluye_wtc_solo_con_mismo_mes_del_anio_anterior(tmp_path):
    base = ('{mes:"2026-09",m:"Patagonia",l:"PALERMO",fac:100,ord:10},'
            '{mes:"2025-09",m:"Patagonia",l:"PALERMO",fac:80,ord:10},'
            '{mes:"2026-09",m:"Patagonia",l:"WTC",fac:90,ord:20}')
    sin = run_js(f'finLocalesComunes([{base}],"Patagonia",["2026-09"],["2025-09"]).map(r=>r.l)', tmp_path)
    con = run_js(f'finLocalesComunes([{base},{{mes:"2025-09",m:"Patagonia",l:"WTC",fac:70,ord:20}}],'
                 f'"Patagonia",["2026-09"],["2025-09"]).map(r=>r.l)', tmp_path)
    assert "WTC" not in sin and "WTC" in con
```

Agregar a `tests/test_wtc.py`:

```python
def test_plantilla_tiene_marcador_wtc_info():
    with open("templates/dashboard.html", encoding="utf-8") as f:
        assert "const WTC_INFO = __WTC_INFO_JSON__;" in f.read()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_wtc_js.py tests/test_wtc.py::test_plantilla_tiene_marcador_wtc_info -q`
Expected: FAIL (`no se encontró _wtcMes en la plantilla`, marcador ausente). El test de same-store **pasa ya**: documenta que same-store no necesita JS nuevo (la fila WTC de `LOCAL_MENSUAL` alcanza).

- [ ] **Step 3: Write minimal implementation**

Const (debajo de `const ULTIMA_VENTA = __ULTIMA_VENTA_JSON__;`):

```javascript
// WTC (Uruguay): carga manual mensual convertida a ARS, ya sumada a MENSUAL/LOCAL_MENSUAL/LOCALES_OBJ
// en el pipeline. Acá solo viene la info para la nota y los avisos (null si la plantilla no se inyectó).
const WTC_INFO = __WTC_INFO_JSON__;
```

Markup en `#view-economico`, después del `</section>` de la primera sección (Indicadores):

```html
<p class="note" id="wtcNotaVentas" style="padding:0 0 12px;margin:0;display:none"></p>
```

Markup en `#view-finanzas`, justo antes de `<p class="note" id="finEstimadoNota"></p>`:

```html
<p class="note" id="wtcNotaFin" style="display:none"></p>
```

Funciones (antes de `function updateAll(){`; cada una cierra con `}` en columna 0 — `run_dom_js` las extrae así):

```javascript
function _wtcMes(m){
  const n=["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
  return n[+m.slice(5,7)-1]+"-"+m.slice(2,4);
}

/* Nota de WTC (Uruguay) para Ventas y Finanzas. Pura: recibe WTC_INFO por parámetro. */
function wtcNotaTexto(info, finanzas){
  if(!info) return "";
  let t="WTC (Uruguay): carga manual mensual, convertida al oficial BCRA.";
  if(finanzas) t+=" Se deflacta con IPC argentino como el resto; en same-store entra solo si tiene cargado el mismo mes del año anterior.";
  if(info.error) return t+" ⚠ No se pudo leer la carga de WTC: este tablero no lo incluye.";
  if(info.falta_ultimo_cerrado) t+=" ⚠ Falta cargar "+_wtcMes(info.ultimo_cerrado)+".";
  if(info.falta_mes_actual) t+=" Mes en curso ("+_wtcMes(info.mes_actual)+") sin cargar.";
  if((info.sin_cotizacion||[]).length) t+=" ⚠ Sin cotización BCRA (no sumados): "+info.sin_cotizacion.map(_wtcMes).join(", ")+".";
  return t;
}

function buildWtcNota(){
  const ver=!!WTC_INFO&&(STATE.marca==="todas"||STATE.marca==="Patagonia");
  [["wtcNotaVentas",false],["wtcNotaFin",true]].forEach(([id,fin])=>{
    const el=document.getElementById(id);
    if(!el) return;
    el.textContent=wtcNotaTexto(WTC_INFO,fin);
    el.style.display=ver?"block":"none";
  });
}
```

En `updateAll()`, después de la línea de `buildCalidadDatos`:

```javascript
  try { buildWtcNota(); } catch(e){ console.error('[updateAll wtc]',e); }
```

En `tests/test_finanzas_js.py::test_update_all_construye_finanzas_aunque_falle_otra_seccion`, agregar `"buildWtcNota"` a la lista `otras` y, si `buildExcepciones`/`buildCalidadDatos` no estuvieran ya stubeados, no tocarlos (el `try` propio los absorbe). Es un stub más; lo que verifica el test no cambia.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_wtc_js.py tests/test_wtc.py tests/test_finanzas_js.py tests/test_excepciones_js.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard.html tests/test_wtc_js.py tests/test_wtc.py tests/test_finanzas_js.py
git commit -m "feat(wtc): nota WTC en Ventas y Finanzas con avisos de meses faltantes y sin cotización"
```

---

### Task 9: Preview local, deploy y verificación

**Files:** ninguno nuevo. Usar el skill `deploy-tablero-gcp` para Cloud Run.

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: tablero retail y `/admin` en producción con WTC.

- [ ] **Step 1: Suite completa de lo tocado**

Run: `python -X utf8 -m pytest tests/test_wtc.py tests/test_wtc_admin.py tests/test_wtc_js.py tests/test_ipc_indec.py tests/test_actualizar_retail_helpers.py tests/test_finanzas_js.py tests/test_auth.py tests/test_excepciones_js.py -q`
Expected: all PASS (baseline 138 + los nuevos).

- [ ] **Step 2: Datos reales de WTC (Darwin)**

Preguntar a Darwin si ya tiene los números de WTC (ene-25 → sep-26). Si sí, cargarlos por `/admin` local (Task 5, Step 5) — es la tabla de producción. Si no, seguir con la tabla vacía: el tablero tiene que salir igual que hoy, con la nota "⚠ Falta cargar sep-26".

- [ ] **Step 3: Preview local del tablero**

Run: `rm -f design_handoff_tablero_retail/preview/cache/fetch_wtc_*.pkl && python -X utf8 design_handoff_tablero_retail/preview/rebuild.py ventas`. `rebuild.py` cachea en pickle **todos** los `fetch_*`, `fetch_wtc` incluido: después de cargar o cambiar datos de WTC hay que borrar su pickle, si no el preview muestra la carga vieja. Los demás pickles pueden ser de otra fecha; si `MENSUAL` cacheado no tiene el mes cargado de WTC, ese mes no se suma (Review Focus #3), no es un bug.
Verificar en el log: `✓ WTC sumado a Patagonia: ...` o `WARN WTC: falta cargar ...`; sin `Traceback`.
Abrir el HTML generado con la sonda Chrome headless (`lesson_chrome-headless-probe-fallback`): Ventas con marca Patagonia → nota WTC visible; con Temple → oculta; Finanzas → nota con la aclaración de IPC; "Locales a mirar" → WTC ya no figura como "Objetivo sin venta" en meses cargados; ancho 375px con iframe inyectado → sin scroll horizontal. Si hay meses cargados, comparar el total Patagonia del mes contra `BQ + facturacion_uyu × cotización`.

- [ ] **Step 4: Code review de la rama**

Usar `superpowers:requesting-code-review` sobre `feat/wtc-carga-manual` antes de mergear.

- [ ] **Step 5: Merge y deploy del pipeline (lo corre Darwin)**

El auto mode bloquea merge/push a main: darle a Darwin las líneas con `!`:
```
! git checkout main && git merge --no-ff feat/wtc-carga-manual && git push origin main
! gh workflow run actualizar-pipeline.yml
```
Verificar el run: `gh run list --workflow actualizar-pipeline.yml -L 1` → `gh run view <id> --log | grep -E "FALLÓ|WARN WTC|✓ WTC"`. Expected: `✓ WTC tipo de cambio ...` (confirma salida HTTPS a `api.bcra.gob.ar` desde GitHub Actions) y `✓ WTC sumado a Patagonia`. Verificar el blob GCS del tablero (fecha y que contenga `const WTC_INFO = {`), según `reference_deploy-plantilla-retail`.

Si el run muestra `WARN WTC tipo de cambio: ...` (SSL o timeout): no desactivar la verificación SSL; las cotizaciones ya quedaron cargadas desde la corrida local (Task 3, Step 6). Reportarlo a Darwin.

- [ ] **Step 6: Redeploy de Cloud Run (admin)**

Con el skill `deploy-tablero-gcp`: redeploy de `temple-bar-dashboard` (región `southamerica-east1`) desde la raíz del repo, sincrónico. Antes: confirmar que la cuenta de servicio de Cloud Run puede escribir en BQ `Corporativo` (si el MERGE de `/api/admin/wtc` da 403, pedir a Darwin `roles/bigquery.dataEditor` sobre el dataset). Verificar en producción: `/admin` → pestaña WTC → la tabla "Cargado" lista lo cargado en Step 2 y la vista previa convierte.

- [ ] **Step 7: Memoria**

Actualizar `project_patagonia-wtc-objetivo-sin-venta.md`: fase 1 en producción (commit y run id), meses cargados, siguiente paso fase 2 (Producto litros).
