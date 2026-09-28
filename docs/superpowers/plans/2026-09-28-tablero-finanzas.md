# Pestaña Finanzas (facturación vs inflación) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una 4ª pestaña "Finanzas" al tablero retail que muestre crecimiento real (deflactado por IPC INDEC) y cuánto crecimiento real piden los objetivos 2026.

**Architecture:** Un módulo Python nuevo (`ipc_indec.py`) trae el IPC de la API de datos.gob.ar en cada corrida del pipeline, con copia de respaldo en GCS, y `actualizar_retail.py` lo inyecta en `templates/dashboard.html` con el marcador `__IPC_JSON__`. En el HTML, un bloque de funciones JS puras (`FINANZAS_CORE`) hace los cálculos —testeado con Node desde pytest— y `buildFinanzas()` los pinta con los datasets ya inyectados (`MENSUAL`, `LOCAL_MENSUAL`, `OBJETIVOS`, `PD`). Sale por el pipeline de GitHub Actions; no hay deploy de Cloud Run.

**Tech Stack:** Python 3 (requests, google-cloud-storage, pytest), JS vanilla + Chart.js 4.4.1 (ya cargado por `loadChartJS`), Node ≥ 18 solo para tests.

**Spec:** `docs/superpowers/specs/2026-09-28-tablero-finanzas-design.md`

## Global Constraints

- Series: IPC general `148.3_INIVELNAL_DICI_M_26`; rubro `146.3_IRESTAUNAL_DICI_M_33`; API `https://apis.datos.gob.ar/series/api/series/`.
- Umbrales objetivos: **Exigente** > +10% real · **Razonable** 0% a +10% · **Laxo** < 0%.
- Una falla de IPC **nunca** aborta el pipeline ni rompe Ventas/Producto/Reseñas.
- Logs de falla contienen `FALLÓ` (el chequeo post-run hace grep de `FALL`).
- GCS: `cache_control` se setea **después** del upload (`blob.patch()`), nunca antes.
- `templates/dashboard.html` usa **CRLF** y mezcla `\uXXXX` con acentos literales: si un Edit no matchea, editar por anclas de línea preservando CRLF.
- GateGuard: antes de cada Edit/Write presentar los 4 hechos que pide el hook.
- Correr Python con `python -X utf8` en Windows.
- Todo en la rama `finanzas-ipc`; **un solo merge a `main` al final**, después de que el usuario apruebe el preview.
- Commits terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Primeros días del mes en curso** (ej. 2/10): prorratear 2 días × 31 da crecimientos absurdos → los meses abiertos con avance < 10% se excluyen de ambos lados de la comparación; si no queda ninguno, "sin datos". Test en Task 3.
2. **Marca o local sin venta el año anterior** (Feriado nuevo, rango custom que arranca antes de la historia): crecimiento `null` → "—", nunca `Infinity`/`NaN`. Test en Task 3.
3. **Objetivo con venta del año anterior en 0** (mes sin historia): crecimiento implícito `null` → "—". Test en Task 3.
4. **IPC `null`** (API caída y sin copia): la pestaña muestra "Datos de inflación no disponibles" y el resto del tablero funciona. Tests en Task 1/2 + verificación en preview (Task 5).
5. **Rango personalizado sin año anterior completo**: si algún mes del rango no tiene su par del año anterior, la comparación es "sin datos" (no se compara un período parcial). Implementado en `finPeriodoActual` (Task 4) + barrido en preview (Task 5).

---

## File Structure

- **Create `ipc_indec.py`** — descarga, parseo, validación, estimación de meses sin publicar, copia en GCS. Una responsabilidad: entregar el payload IPC o `None`.
- **Create `tests/test_ipc_indec.py`** — tests del módulo con red y GCS simulados.
- **Modify `actualizar_retail.py`** — `fetch_ipc_data()`, `inject_ipc()`, tarea `"ipc"` en `main()`, parámetro `ipc_data` en `generate_html_from_file`.
- **Create `tests/test_finanzas_js.py`** — extrae el bloque `FINANZAS_CORE` de la plantilla y lo corre con Node.
- **Modify `templates/dashboard.html`** — `const IPC`, bloque `FINANZAS_CORE` (funciones puras), botón + vista `view-finanzas`, `buildFinanzas()`/`buildFinChart()`, hooks en `switchView` y `updateAll`.
- `static/temple-retail.css` no se toca: alcanzan las clases existentes (`kpi-grid`, `kpi-card`, `t-chip*`, `pos`/`neg`, `table-scroll`, `t-alert`, `note`).

---

### Task 1: Módulo `ipc_indec.py`

**Files:**
- Create: `ipc_indec.py`
- Test: `tests/test_ipc_indec.py`

**Interfaces:**
- Produces: `obtener_ipc(bucket: str = "", hoy: date | None = None, log=print) -> dict | None`.
  Payload: `{"base": "2026-08", "general": {"2024-01": 1234.5, ...}, "rubro": {...}, "estimados": ["2026-09", ...], "fuente": "api" | "cache"}`.
  Las series se completan hasta diciembre del año de `hoy`; `base` = último mes publicado de la serie general.

- [ ] **Step 1: Write the failing tests** — `tests/test_ipc_indec.py`:

```python
"""tests/test_ipc_indec.py — IPC INDEC para la pestaña Finanzas (red y GCS simulados)."""
from datetime import date

import pytest
import requests

import ipc_indec

HOY = date(2026, 9, 28)


def _series(general=None, rubro=None):
    return {
        "general": general or {"2026-06": 100.0, "2026-07": 102.0, "2026-08": 104.04},
        "rubro": rubro or {"2026-06": 200.0, "2026-07": 202.0, "2026-08": 204.02},
    }


def test_parse_respuesta_arma_series_por_mes_e_ignora_nulos():
    payload = {"data": [["2026-07-01", 100.5, 200.5], ["2026-08-01", 101.0, None]]}
    s = ipc_indec.parse_respuesta(payload)
    assert s == {"general": {"2026-07": 100.5, "2026-08": 101.0}, "rubro": {"2026-07": 200.5}}


def test_validar_rechaza_serie_vacia():
    with pytest.raises(ValueError, match="vacía"):
        ipc_indec.validar({"general": {}, "rubro": {"2026-08": 1.0}}, HOY)


def test_validar_rechaza_indice_que_baja():
    s = _series(general={"2026-07": 102.0, "2026-08": 101.0})
    with pytest.raises(ValueError, match="baja"):
        ipc_indec.validar(s, HOY)


def test_validar_avisa_si_el_ultimo_dato_tiene_mas_de_3_meses():
    s = _series(general={"2026-04": 100.0, "2026-05": 101.0})
    avisos = ipc_indec.validar(s, HOY)
    assert len(avisos) == 1 and avisos[0].startswith("FALLÓ IPC desactualizado: general")


def test_validar_sin_avisos_con_datos_al_dia():
    assert ipc_indec.validar(_series(), HOY) == []


def test_completar_estimados_repite_la_ultima_variacion_mensual():
    completas, estimados = ipc_indec.completar_estimados(_series(), "2026-10")
    assert estimados == ["2026-09", "2026-10"]
    assert completas["general"]["2026-09"] == pytest.approx(104.04 * 1.02, rel=1e-6)
    assert completas["general"]["2026-10"] == pytest.approx(104.04 * 1.02 ** 2, rel=1e-6)
    assert completas["general"]["2026-08"] == 104.04  # lo publicado no cambia


def test_construir_payload_base_es_ultimo_mes_publicado_y_completa_hasta_diciembre():
    p = ipc_indec.construir_payload(_series(), HOY, "api")
    assert p["base"] == "2026-08"
    assert p["estimados"] == ["2026-09", "2026-10", "2026-11", "2026-12"]
    assert "2026-12" in p["general"] and "2026-12" in p["rubro"]
    assert p["fuente"] == "api"


def test_descargar_reintenta_y_devuelve_series(monkeypatch):
    llamadas = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [["2026-08-01", 104.0, 204.0]]}

    def fake_get(url, params, timeout):
        llamadas.append(params)
        if len(llamadas) < 3:
            raise requests.ConnectionError("caída")
        return Resp()

    monkeypatch.setattr(ipc_indec.requests, "get", fake_get)
    s = ipc_indec.descargar(espera=0)
    assert len(llamadas) == 3
    assert llamadas[0]["ids"] == "148.3_INIVELNAL_DICI_M_26,146.3_IRESTAUNAL_DICI_M_33"
    assert s == {"general": {"2026-08": 104.0}, "rubro": {"2026-08": 204.0}}


def test_descargar_falla_despues_de_3_intentos(monkeypatch):
    def fake_get(url, params, timeout):
        raise requests.ConnectionError("caída")

    monkeypatch.setattr(ipc_indec.requests, "get", fake_get)
    with pytest.raises(RuntimeError, match="API IPC sin respuesta"):
        ipc_indec.descargar(espera=0)


def test_obtener_ipc_api_ok_guarda_cache(monkeypatch):
    guardado = {}
    monkeypatch.setattr(ipc_indec, "descargar", lambda: _series())
    monkeypatch.setattr(ipc_indec, "_guardar_cache", lambda b, s: guardado.update(b=b, s=s))
    p = ipc_indec.obtener_ipc("bucket-x", HOY, log=lambda *_: None)
    assert p["fuente"] == "api" and p["base"] == "2026-08"
    assert guardado == {"b": "bucket-x", "s": _series()}


def test_obtener_ipc_sin_bucket_no_toca_gcs(monkeypatch):
    monkeypatch.setattr(ipc_indec, "descargar", lambda: _series())

    def no_llamar(*a):
        raise AssertionError("no debe tocar GCS")

    monkeypatch.setattr(ipc_indec, "_guardar_cache", no_llamar)
    monkeypatch.setattr(ipc_indec, "_leer_cache", no_llamar)
    assert ipc_indec.obtener_ipc("", HOY, log=lambda *_: None)["fuente"] == "api"


def test_obtener_ipc_api_caida_usa_cache(monkeypatch):
    logs = []

    def caida():
        raise RuntimeError("API IPC sin respuesta")

    monkeypatch.setattr(ipc_indec, "descargar", caida)
    monkeypatch.setattr(ipc_indec, "_leer_cache", lambda b: _series())
    p = ipc_indec.obtener_ipc("bucket-x", HOY, log=logs.append)
    assert p["fuente"] == "cache"
    assert any("FALLÓ IPC API" in l for l in logs)


def test_obtener_ipc_datos_invalidos_de_api_usan_cache_y_no_se_guardan(monkeypatch):
    monkeypatch.setattr(ipc_indec, "descargar",
                        lambda: _series(general={"2026-07": 102.0, "2026-08": 101.0}))

    def no_guardar(*a):
        raise AssertionError("no debe guardar datos inválidos")

    monkeypatch.setattr(ipc_indec, "_guardar_cache", no_guardar)
    monkeypatch.setattr(ipc_indec, "_leer_cache", lambda b: _series())
    assert ipc_indec.obtener_ipc("bucket-x", HOY, log=lambda *_: None)["fuente"] == "cache"


def test_obtener_ipc_sin_api_ni_cache_devuelve_none(monkeypatch):
    logs = []

    def caida():
        raise RuntimeError("API IPC sin respuesta")

    monkeypatch.setattr(ipc_indec, "descargar", caida)
    monkeypatch.setattr(ipc_indec, "_leer_cache", lambda b: None)
    assert ipc_indec.obtener_ipc("bucket-x", HOY, log=logs.append) is None
    assert any("sin cache" in l for l in logs)


def test_obtener_ipc_falla_al_guardar_cache_no_rompe(monkeypatch):
    monkeypatch.setattr(ipc_indec, "descargar", lambda: _series())

    def falla(*a):
        raise OSError("sin permisos")

    monkeypatch.setattr(ipc_indec, "_guardar_cache", falla)
    assert ipc_indec.obtener_ipc("bucket-x", HOY, log=lambda *_: None)["fuente"] == "api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_ipc_indec.py -v`
Expected: ERROR con `ModuleNotFoundError: No module named 'ipc_indec'`

- [ ] **Step 3: Write the implementation** — `ipc_indec.py`:

```python
"""IPC INDEC para la pestaña Finanzas del tablero retail.

Trae de la API de series de datos.gob.ar el IPC general nacional y el de
Hoteles y restaurantes, completa los meses todavía no publicados repitiendo la
última variación mensual, y guarda las series publicadas en GCS como respaldo
por si la API falla en una corrida futura.

obtener_ipc() nunca lanza: ante cualquier falla devuelve la copia de GCS o None
(la pestaña muestra "Datos de inflación no disponibles").
"""
import json
import time
from datetime import date

import requests

API_URL = "https://apis.datos.gob.ar/series/api/series/"
SERIES = {  # el orden importa: es el orden de las columnas en la respuesta
    "general": "148.3_INIVELNAL_DICI_M_26",  # IPC Nivel general nacional, base dic-2016
    "rubro": "146.3_IRESTAUNAL_DICI_M_33",   # IPC Hoteles y restaurantes nacional, base dic-2016
}
CACHE_BLOB = "ipc_cache.json"
MAX_ATRASO_MESES = 3


def _mes_siguiente(mes):
    y, m = int(mes[:4]), int(mes[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def _distancia_meses(desde, hasta):
    return (int(hasta[:4]) - int(desde[:4])) * 12 + int(hasta[5:7]) - int(desde[5:7])


def parse_respuesta(payload):
    """{"data": [["2026-08-01", g, r], ...]} → {"general": {"2026-08": g}, "rubro": {...}}."""
    series = {nombre: {} for nombre in SERIES}
    for fila in payload.get("data", []):
        mes = fila[0][:7]
        for nombre, valor in zip(SERIES, fila[1:]):
            if valor is not None:
                series[nombre][mes] = float(valor)
    return series


def validar(series, hoy=None):
    """ValueError si una serie está vacía o su índice baja de un mes a otro.
    Devuelve avisos (texto con FALLÓ) si el último dato tiene más de 3 meses."""
    hoy = hoy or date.today()
    mes_hoy = f"{hoy.year:04d}-{hoy.month:02d}"
    avisos = []
    for nombre, serie in series.items():
        if not serie:
            raise ValueError(f"serie {nombre} vacía")
        meses = sorted(serie)
        for a, b in zip(meses, meses[1:]):
            if serie[b] < serie[a]:
                raise ValueError(f"serie {nombre} baja de {a} a {b}")
        atraso = _distancia_meses(meses[-1], mes_hoy)
        if atraso > MAX_ATRASO_MESES:
            avisos.append(f"FALLÓ IPC desactualizado: {nombre} último dato {meses[-1]} ({atraso} meses)")
    return avisos


def completar_estimados(series, hasta):
    """Extiende cada serie hasta `hasta` repitiendo su última variación mensual.
    Devuelve (series_completas, meses_estimados ordenados)."""
    completas, estimados = {}, set()
    for nombre, serie in series.items():
        s = dict(serie)
        meses = sorted(s)
        variacion = s[meses[-1]] / s[meses[-2]] if len(meses) >= 2 else 1.0
        mes = meses[-1]
        while mes < hasta:
            siguiente = _mes_siguiente(mes)
            s[siguiente] = round(s[mes] * variacion, 4)
            estimados.add(siguiente)
            mes = siguiente
        completas[nombre] = s
    return completas, sorted(estimados)


def construir_payload(series, hoy=None, fuente="api"):
    hoy = hoy or date.today()
    completas, estimados = completar_estimados(series, f"{hoy.year:04d}-12")
    return {"base": max(series["general"]), "general": completas["general"],
            "rubro": completas["rubro"], "estimados": estimados, "fuente": fuente}


def descargar(desde="2024-01", intentos=3, espera=3, timeout=20):
    params = {"ids": ",".join(SERIES.values()), "start_date": f"{desde}-01",
              "format": "json", "limit": 1000}
    ultimo_error = None
    for i in range(intentos):
        try:
            r = requests.get(API_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return parse_respuesta(r.json())
        except (requests.RequestException, ValueError) as exc:
            ultimo_error = exc
            if i < intentos - 1:
                time.sleep(espera)
    raise RuntimeError(f"API IPC sin respuesta: {ultimo_error}")


def _leer_cache(bucket):
    from google.cloud import storage
    blob = storage.Client().bucket(bucket).blob(CACHE_BLOB)
    if not blob.exists():
        return None
    return json.loads(blob.download_as_text(encoding="utf-8"))


def _guardar_cache(bucket, series):
    from google.cloud import storage
    blob = storage.Client().bucket(bucket).blob(CACHE_BLOB)
    blob.upload_from_string(json.dumps(series), content_type="application/json")
    blob.cache_control = "no-cache, no-store, must-revalidate"  # después del upload
    blob.patch()


def obtener_ipc(bucket="", hoy=None, log=print):
    """Payload IPC para el tablero, o None si no hay datos. Nunca lanza.
    Con bucket vacío (corridas locales) no lee ni escribe GCS."""
    try:
        series = descargar()
        avisos = validar(series, hoy)
        fuente = "api"
        if bucket:
            try:
                _guardar_cache(bucket, series)
            except Exception as exc:
                log(f"  ⚠ IPC: no se pudo guardar {CACHE_BLOB}: {exc}")
    except Exception as exc:
        log(f"  FALLÓ IPC API ({exc}), usando cache")
        if not bucket:
            return None
        try:
            series = _leer_cache(bucket)
            if not series:
                log("  FALLÓ IPC: sin cache en GCS — pestaña Finanzas sin datos")
                return None
            avisos = validar(series, hoy)
            fuente = "cache"
        except Exception as exc2:
            log(f"  FALLÓ IPC cache ({exc2}) — pestaña Finanzas sin datos")
            return None
    for aviso in avisos:
        log("  " + aviso)
    payload = construir_payload(series, hoy, fuente)
    log(f"  ✓ IPC ({fuente}): base {payload['base']}, {len(payload['estimados'])} meses estimados")
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_ipc_indec.py -v`
Expected: 15 passed

- [ ] **Step 5: Smoke test contra la API real (sin GCS)**

Run: `python -X utf8 -c "import ipc_indec as i; p=i.obtener_ipc(''); print(p['base'], p['estimados'][:2], len(p['general']))"`
Expected: `2026-08 ['2026-09', '2026-10'] 36` (o el último mes que haya publicado el INDEC)

- [ ] **Step 6: Commit**

```bash
git add ipc_indec.py tests/test_ipc_indec.py
git commit -m "feat(finanzas): módulo ipc_indec con fallback a cache en GCS"
```

---

### Task 2: Integración en el pipeline (`actualizar_retail.py`)

**Files:**
- Modify: `actualizar_retail.py` (nueva función después de `fetch_local_mensual_data` ~línea 562; firma de `generate_html_from_file` ~1106; inyección después del bloque `# ── Inyección de Objetivos ──` ~1241; `main()`: `tasks` ~1328, resultados ~1350, llamada ~1373)
- Modify: `templates/dashboard.html` (`const IPC` después de `const LOCAL_MENSUAL = __LOCAL_MENSUAL_JSON__;` ~línea 428)
- Test: `tests/test_actualizar_retail_helpers.py` (agregar al final)

**Interfaces:**
- Consumes: `ipc_indec.obtener_ipc(bucket) -> dict | None` (Task 1)
- Produces: `fetch_ipc_data(gcs_bucket: str = "") -> dict | None`; `inject_ipc(html: str, ipc_data: dict | None) -> str`; en el HTML, `const IPC` = payload o `null`.

- [ ] **Step 1: Write the failing tests** (al final de `tests/test_actualizar_retail_helpers.py`)

```python
# ---------------------------------------------------------------------------
# inject_ipc / fetch_ipc_data — pestaña Finanzas
# ---------------------------------------------------------------------------

def test_inject_ipc_reemplaza_marcador_con_json():
    from actualizar_retail import inject_ipc
    html = inject_ipc("const IPC = __IPC_JSON__;", {"base": "2026-08", "general": {"2026-08": 1.5}})
    assert html == 'const IPC = {"base":"2026-08","general":{"2026-08":1.5}};'


def test_inject_ipc_sin_datos_inyecta_null():
    from actualizar_retail import inject_ipc
    assert inject_ipc("const IPC = __IPC_JSON__;", None) == "const IPC = null;"


def test_inject_ipc_sin_marcador_no_cambia_html():
    from actualizar_retail import inject_ipc
    assert inject_ipc("<p>sin marcador</p>", {"base": "2026-08"}) == "<p>sin marcador</p>"


def test_plantilla_dashboard_tiene_marcador_ipc():
    import os
    with open(os.path.join("templates", "dashboard.html"), encoding="utf-8") as f:
        assert "const IPC = __IPC_JSON__;" in f.read()


def test_fetch_ipc_data_pasa_el_bucket(monkeypatch):
    import actualizar_retail, ipc_indec
    monkeypatch.setattr(ipc_indec, "obtener_ipc", lambda bucket: {"bucket": bucket})
    assert actualizar_retail.fetch_ipc_data("b1") == {"bucket": "b1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_actualizar_retail_helpers.py -k "ipc" -v`
Expected: FAIL con `ImportError: cannot import name 'inject_ipc'` y el test de plantilla con `AssertionError`

- [ ] **Step 3: Implement**

En `actualizar_retail.py`, después de `fetch_local_mensual_data`:

```python
def fetch_ipc_data(gcs_bucket=""):
    # IPC INDEC para la pestaña Finanzas. Nunca lanza: si la API falla usa la
    # copia de GCS, y si tampoco hay copia devuelve None (la pestaña muestra
    # "sin datos" y el resto del tablero no se entera).
    import ipc_indec
    return ipc_indec.obtener_ipc(gcs_bucket)


def inject_ipc(html, ipc_data):
    """Reemplaza __IPC_JSON__ por el payload IPC (o null si no hay datos)."""
    if '__IPC_JSON__' not in html:
        return html
    html = html.replace('__IPC_JSON__', json.dumps(ipc_data, separators=(',', ':')))
    print(f"  ✓ IPC inyectado ({'base ' + ipc_data['base'] if ipc_data else 'sin datos'})")
    return html
```

En la firma de `generate_html_from_file`, reemplazar la última línea de parámetros:

```python
                             local_mensual_rows=None,
                             ipc_data=None):
```

Después del bloque `# ── Inyección de Objetivos ──` (el que termina en `print(f"  ✓ OBJETIVOS inyectados ...")`):

```python
    # ── Inyección de IPC (pestaña Finanzas) ──────────────────────────────
    html = inject_ipc(html, ipc_data)
```

En `main()`, dentro de `tasks = {...}` agregar:

```python
            "ipc":        lambda: fetch_ipc_data(args.gcs_bucket),
```

Después de `local_mensual_rows = results["local_mensual"] or []`:

```python
        ipc_data         = results["ipc"]
```

Y en la llamada a `generate_html_from_file(...)`, después de `local_mensual_rows=local_mensual_rows,`:

```python
            ipc_data=ipc_data,
```

En `templates/dashboard.html`, después de la línea `const LOCAL_MENSUAL = __LOCAL_MENSUAL_JSON__;` (CRLF):

```js
// IPC INDEC (general + hoteles y restaurantes), completado hasta diciembre con meses estimados.
// null si la API falló y no había copia en GCS → la pestaña Finanzas muestra "sin datos".
const IPC = __IPC_JSON__;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_actualizar_retail_helpers.py tests/test_ipc_indec.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add actualizar_retail.py templates/dashboard.html tests/test_actualizar_retail_helpers.py
git commit -m "feat(finanzas): inyectar IPC en el tablero desde el pipeline"
```

---

### Task 3: Funciones de cálculo `FINANZAS_CORE` (JS puro) + tests con Node

**Files:**
- Modify: `templates/dashboard.html` (bloque nuevo inmediatamente después de `const IPC = __IPC_JSON__;`)
- Create: `tests/test_finanzas_js.py`

**Interfaces:**
- Consumes: forma del payload IPC (Task 1); filas `MENSUAL` `{mes, m, fac, ord, tick}`, `LOCAL_MENSUAL` `{mes, m, l, fac, ord}`, `OBJETIVOS[marca][mes] = {obj_fac, obj_ord}` (fac y obj_fac en millones).
- Produces (usadas por Task 4):
  - `finYoyMes(mes) -> string`
  - `finPace(mes, hoy: Date) -> number | null` (1 cerrado, fracción si es el mes en curso, null si futuro)
  - `finInflacion(serie, meses, yoyMeses) -> number | null` (%)
  - `finSumar(rows, meses, ipc, pace) -> {nom, real, falta}`
  - `finCrecimiento(rows, meses, yoyMeses, ipc, pace) -> {nomCur, realCur, nomYoy, realYoy, crecNom, crecReal} | null`
  - `finSameStore(localRows, marca, meses, yoyMeses, ipc, pace) -> (igual que finCrecimiento) | null` (marca `"todas"` = todas)
  - `finClase(realPct) -> "Exigente" | "Razonable" | "Laxo" | null`
  - `finObjImplicito(obj, ventaAA, ipcPct) -> {nom, real, clase} | null`
  - `finRestoAnio(objMarca, rowsMarca, anio, mesesResto, paceActual, ipc) -> {objAnual, ytd, faltante, ventaAA, imp}`
  - Constantes `FIN_UMBRAL_EXIGENTE = 10`, `FIN_UMBRAL_LAXO = 0`, `FIN_PACE_MIN = 0.1`
- `pace` es una función `mes -> number | null`.

Nota de diseño: el crecimiento real se calcula deflactando **mes a mes** a pesos del mes base y comparando sumas. Para un solo mes es idéntico a `(1+nom)/(1+IPC)−1` del spec; para períodos de varios meses es la versión exacta.

- [ ] **Step 1: Write the failing tests** — `tests/test_finanzas_js.py`:

```python
"""tests/test_finanzas_js.py — cálculos de la pestaña Finanzas.

Extrae el bloque FINANZAS_CORE de templates/dashboard.html y lo corre con Node.
Se saltea si Node no está instalado.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="requiere Node")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


def run_js(expr, tmp_path):
    """Evalúa `expr` (JS) después del bloque FINANZAS_CORE y devuelve el resultado como Python."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"/\* FINANZAS_CORE:START.*?\*/(.*?)/\* FINANZAS_CORE:END \*/", html, re.S)
    assert m, "no se encontró el bloque FINANZAS_CORE en la plantilla"
    script = tmp_path / "fin.js"
    script.write_text(m.group(1) + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


IPC = ('{base:"2026-09",estimados:[],'
       'general:{"2025-08":100,"2025-09":100,"2025-10":100,"2026-08":125,"2026-09":130,"2026-10":130},'
       'rubro:{"2025-09":100,"2026-09":140}}')


def test_fin_pace(tmp_path):
    r = run_js('[finPace("2026-08",new Date(2026,8,15)),finPace("2026-09",new Date(2026,8,15)),'
               'finPace("2026-10",new Date(2026,8,15))]', tmp_path)
    assert r == [1, 0.5, None]


def test_fin_inflacion_usa_indice_promedio_del_periodo(tmp_path):
    r = run_js(f'finInflacion(({IPC}).general,["2026-08","2026-09"],["2025-08","2025-09"])', tmp_path)
    assert r == pytest.approx(27.5)


def test_fin_inflacion_sin_meses_devuelve_null(tmp_path):
    assert run_js(f'finInflacion(({IPC}).general,["2026-09"],[])', tmp_path) is None


def test_fin_crecimiento_prorratea_el_mes_en_curso_y_deflacta(tmp_path):
    r = run_js(f'finCrecimiento([{{mes:"2025-09",fac:100}},{{mes:"2026-09",fac:65}}],'
               f'["2026-09"],["2025-09"],{IPC},m=>finPace(m,new Date(2026,8,15)))', tmp_path)
    assert r["nomCur"] == pytest.approx(130)      # 65 al día 15 de 30 → cierre estimado 130
    assert r["crecNom"] == pytest.approx(30)
    assert r["crecReal"] == pytest.approx(0)       # 30% nominal con 30% de inflación


def test_fin_crecimiento_sin_anio_anterior_es_null(tmp_path):
    r = run_js(f'finCrecimiento([{{mes:"2026-09",fac:65}}],["2026-09"],["2025-09"],{IPC},m=>1)', tmp_path)
    assert r is None


def test_fin_crecimiento_excluye_mes_con_menos_de_10pct_de_avance(tmp_path):
    # 2 de octubre: el mes en curso tiene 2/31 de avance → se saca de la comparación
    solo = run_js(f'finCrecimiento([{{mes:"2025-10",fac:100}},{{mes:"2026-10",fac:5}}],'
                  f'["2026-10"],["2025-10"],{IPC},m=>finPace(m,new Date(2026,9,2)))', tmp_path)
    assert solo is None
    dos = run_js(f'finCrecimiento([{{mes:"2025-09",fac:100}},{{mes:"2026-09",fac:130}},'
                 f'{{mes:"2025-10",fac:100}},{{mes:"2026-10",fac:5}}],'
                 f'["2026-09","2026-10"],["2025-09","2025-10"],{IPC},m=>finPace(m,new Date(2026,9,2)))', tmp_path)
    assert dos["nomCur"] == pytest.approx(130) and dos["crecReal"] == pytest.approx(0)


def test_fin_same_store_solo_locales_en_ambos_periodos(tmp_path):
    rows = ('[{mes:"2025-09",m:"Temple",l:"A",fac:100},{mes:"2026-09",m:"Temple",l:"a ",fac:156},'
            '{mes:"2026-09",m:"Temple",l:"B",fac:50},{mes:"2026-09",m:"Feriado",l:"A",fac:999}]')
    r = run_js(f'finSameStore({rows},"Temple",["2026-09"],["2025-09"],{IPC},m=>1)', tmp_path)
    assert r["nomCur"] == pytest.approx(156)       # B no estaba el año anterior; Feriado es otra marca
    assert r["crecReal"] == pytest.approx(20)      # 156/130 − 1


def test_fin_clase_umbrales(tmp_path):
    assert run_js('[finClase(10.5),finClase(10),finClase(0),finClase(-0.1),finClase(null)]', tmp_path) == \
        ["Exigente", "Razonable", "Razonable", "Laxo", None]


def test_fin_obj_implicito(tmp_path):
    r = run_js('finObjImplicito(150,100,25)', tmp_path)
    assert r["nom"] == pytest.approx(50) and r["real"] == pytest.approx(20) and r["clase"] == "Exigente"


def test_fin_obj_implicito_sin_venta_anio_anterior_es_null(tmp_path):
    assert run_js('[finObjImplicito(150,0,25),finObjImplicito(0,100,25),finObjImplicito(150,100,null)]',
                  tmp_path) == [None, None, None]


def test_fin_resto_anio(tmp_path):
    ipc = '{base:"2026-08",general:{"2025-09":100,"2025-10":100,"2026-09":120,"2026-10":120}}'
    obj = '{"2026-01":{obj_fac:100},"2026-09":{obj_fac:100},"2026-10":{obj_fac:100},"2025-12":{obj_fac:999}}'
    rows = ('[{mes:"2026-01",fac:100},{mes:"2026-09",fac:50},'
            '{mes:"2025-09",fac:80},{mes:"2025-10",fac:80}]')
    r = run_js(f'finRestoAnio({obj},{rows},"2026",["2026-09","2026-10"],0.5,{ipc})', tmp_path)
    assert r["objAnual"] == 300 and r["ytd"] == 150 and r["faltante"] == 150
    assert r["ventaAA"] == pytest.approx(120)      # 80 × (1 − 0,5) + 80
    assert r["imp"]["nom"] == pytest.approx(25)
    assert r["imp"]["real"] == pytest.approx(125 / 120 * 100 - 100)
    assert r["imp"]["clase"] == "Razonable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -X utf8 -m pytest tests/test_finanzas_js.py -v`
Expected: FAIL con `AssertionError: no se encontró el bloque FINANZAS_CORE en la plantilla`

- [ ] **Step 3: Implement** — en `templates/dashboard.html`, inmediatamente después de `const IPC = __IPC_JSON__;` (CRLF):

```js
/* FINANZAS_CORE:START — cálculos de la pestaña Finanzas. Funciones puras: no leen el DOM
   ni variables globales (reciben todo por parámetro). Las testea tests/test_finanzas_js.py. */
const FIN_UMBRAL_EXIGENTE = 10; // % real pedido por encima del cual un objetivo es "Exigente"
const FIN_UMBRAL_LAXO = 0;      // por debajo: "Laxo" (se cumple vendiendo menos en términos reales)
const FIN_PACE_MIN = 0.1;       // meses en curso con menos avance no se proyectan (ruido)

function finYoyMes(mes){ const [y,m]=mes.split("-"); return (+y-1)+"-"+m; }

/* Fracción transcurrida de `mes` a la fecha `hoy`: 1 si ya cerró, null si es futuro. */
function finPace(mes, hoy){
  const hm=hoy.getFullYear()+"-"+String(hoy.getMonth()+1).padStart(2,"0");
  if(mes<hm) return 1;
  if(mes>hm) return null;
  return hoy.getDate()/new Date(hoy.getFullYear(),hoy.getMonth()+1,0).getDate();
}

function finIdxProm(serie, meses){
  if(!meses||!meses.length) return null;
  let s=0;
  for(const m of meses){ if(!(m in serie)) return null; s+=serie[m]; }
  return s/meses.length;
}

/* Inflación (%) de yoyMeses a meses, comparando el índice promedio de cada período. */
function finInflacion(serie, meses, yoyMeses){
  const a=finIdxProm(serie,meses), b=finIdxProm(serie,yoyMeses);
  return a&&b ? (a/b-1)*100 : null;
}

/* Suma nominal y real (en $ del mes base) de rows {mes, fac} en `meses`.
   El mes en curso se lleva a cierre estimado (fac / avance). */
function finSumar(rows, meses, ipc, pace){
  const g=ipc.general, b=g[ipc.base];
  let nom=0, real=0, falta=false;
  rows.forEach(r=>{
    if(!meses.includes(r.mes)) return;
    const p=pace(r.mes), f=p&&p<1 ? r.fac/p : r.fac;
    nom+=f;
    if(g[r.mes]) real+=f*b/g[r.mes]; else falta=true;
  });
  return {nom, real, falta};
}

/* Crecimiento nominal y real (%) de `meses` contra `yoyMeses` (mismo largo, alineados).
   Saca de ambos lados los meses en curso con avance < FIN_PACE_MIN. null si no hay base. */
function finCrecimiento(rows, meses, yoyMeses, ipc, pace){
  if(!meses||!yoyMeses||!meses.length||meses.length!==yoyMeses.length) return null;
  const idx=meses.map((m,i)=>i).filter(i=>{const p=pace(meses[i]);return p===null||p>=FIN_PACE_MIN;});
  if(!idx.length) return null;
  const cm=idx.map(i=>meses[i]), ym=idx.map(i=>yoyMeses[i]);
  const c=finSumar(rows,cm,ipc,pace), y=finSumar(rows,ym,ipc,()=>1);
  if(!(y.nom>0)||!(y.real>0)||c.falta||y.falta) return null;
  return {nomCur:c.nom, realCur:c.real, nomYoy:y.nom, realYoy:y.real,
          crecNom:(c.nom/y.nom-1)*100, crecReal:(c.real/y.real-1)*100};
}

/* Igual que finCrecimiento, solo con los locales que vendieron en ambos períodos. */
function finSameStore(localRows, marca, meses, yoyMeses, ipc, pace){
  if(!meses||!yoyMeses) return null;
  const rows=localRows.filter(r=>marca==="todas"||r.m===marca);
  const key=r=>r.m+"|"+String(r.l).trim().toUpperCase();
  const cur=new Set(rows.filter(r=>meses.includes(r.mes)).map(key));
  const yoy=new Set(rows.filter(r=>yoyMeses.includes(r.mes)).map(key));
  const comunes=rows.filter(r=>cur.has(key(r))&&yoy.has(key(r)));
  return comunes.length ? finCrecimiento(comunes,meses,yoyMeses,ipc,pace) : null;
}

function finClase(realPct){
  if(realPct===null||realPct===undefined) return null;
  if(realPct>FIN_UMBRAL_EXIGENTE) return "Exigente";
  if(realPct<FIN_UMBRAL_LAXO) return "Laxo";
  return "Razonable";
}

/* Crecimiento que pide el objetivo `obj` sobre la venta del año anterior, nominal y real (%). */
function finObjImplicito(obj, ventaAA, ipcPct){
  if(!(obj>0)||!(ventaAA>0)||ipcPct===null||ipcPct===undefined) return null;
  const nom=(obj/ventaAA-1)*100;
  const real=((1+nom/100)/(1+ipcPct/100)-1)*100;
  return {nom, real, clase:finClase(real)};
}

/* Resto del año de una marca: faltante = objetivo anual − facturado en el año, contra lo que se
   vendió en los mismos meses del año anterior (del mes en curso solo la parte que falta). */
function finRestoAnio(objMarca, rowsMarca, anio, mesesResto, paceActual, ipc){
  const objAnual=Object.keys(objMarca).filter(m=>m.startsWith(anio))
    .reduce((s,m)=>s+(objMarca[m].obj_fac||0),0);
  const ytd=rowsMarca.filter(r=>r.mes.startsWith(anio)).reduce((s,r)=>s+r.fac,0);
  const faltante=objAnual-ytd;
  let ventaAA=0;
  mesesResto.forEach((m,i)=>{
    const r=rowsMarca.find(x=>x.mes===finYoyMes(m));
    if(r) ventaAA+=r.fac*(i===0?1-paceActual:1);
  });
  const inf=finInflacion(ipc.general,mesesResto,mesesResto.map(finYoyMes));
  return {objAnual, ytd, faltante, ventaAA, imp:finObjImplicito(faltante,ventaAA,inf)};
}
/* FINANZAS_CORE:END */
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -X utf8 -m pytest tests/test_finanzas_js.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard.html tests/test_finanzas_js.py
git commit -m "feat(finanzas): funciones de crecimiento real y objetivos implícitos"
```

---

### Task 4: Vista "Finanzas" (HTML + render + gráfico)

**Files:**
- Modify: `templates/dashboard.html`:
  - CSS ~línea 34: `#view-producto,#view-resenas{display:none}` → agregar `#view-finanzas`
  - Nav ~línea 125: botón `navFinanzas` después de `navResenas`
  - HTML: bloque `view-finanzas` inmediatamente después de `</div><!-- /view-economico -->`
  - JS `switchView` (~353): mostrar/ocultar la vista, activar botón, llamar `buildFinanzas()`
  - JS: funciones de render después de `/* FINANZAS_CORE:END */`
  - JS `updateAll` (~1644): repintar Finanzas si está visible

**Interfaces:**
- Consumes: todo lo de Task 3; globals existentes `MENSUAL`, `LOCAL_MENSUAL`, `OBJETIVOS`, `PD`, `STATE`, `CHARTS`, `IPC`, `MN`, `BCOLOR`, `TC`, `tPct`, `tDot`, `fmtM`, `getCustomMeses`, `tChartDefaults`.
- Produces: `buildFinanzas()`, `buildFinChart()`, `finPeriodoActual()`.

- [ ] **Step 1: CSS y botón de navegación**

Línea 34:
```css
#view-producto,#view-resenas,#view-finanzas{display:none}
```

Después de `<button class="nav-btn"        id="navResenas"  onclick="switchView('resenas')">Reseñas</button>`:
```html
      <button class="nav-btn"        id="navFinanzas" onclick="switchView('finanzas')">Finanzas</button>
```

- [ ] **Step 2: HTML de la vista** — después de `</div><!-- /view-economico -->`:

```html
<div id="view-finanzas">

<section class="sec">
  <div class="sec-hd">
    <div class="sec-title">Crecimiento real</div>
    <div class="sec-note" id="finBaseNote"></div>
  </div>
  <div id="finSinDatos" class="t-alert" style="display:none">Datos de inflación no disponibles: la API del INDEC no respondió y no hay copia guardada. El resto del tablero no se ve afectado.</div>
  <div class="kpi-grid" id="finKpis"></div>
</section>

<section class="sec card">
  <h2>Facturación nominal vs real</h2>
  <div class="csub" id="finChartSub">Últimos 24 meses cerrados</div>
  <div style="position:relative;height:280px;margin-top:12px"><canvas id="cFinReal"></canvas></div>
</section>

<section class="sec card" style="padding-bottom:0">
  <h2>Crecimiento real por marca</h2>
  <div class="csub" id="finMarcaSub"></div>
  <div class="table-scroll bleed" style="margin-top:16px"><table id="finMarcaTable" style="min-width:640px"></table></div>
</section>

<section class="sec card" style="padding-bottom:0">
  <h2>Objetivos en términos reales</h2>
  <div class="csub">Cuánto crecimiento real le pide cada objetivo mensual a la venta del mismo mes del año anterior</div>
  <div class="table-scroll bleed" style="margin-top:16px"><table id="finObjTable" style="min-width:760px"></table></div>
  <p class="note" id="finObjNota" style="padding:12px 0 16px;margin:0"></p>
</section>

<section class="sec">
  <div class="sec-hd">
    <div class="sec-title">Resto del año</div>
    <div class="sec-note">Crecimiento real necesario para cumplir el objetivo anual</div>
  </div>
  <div class="kpi-grid" id="finResto"></div>
</section>

<p class="note" id="finEstimadoNota"></p>

</div><!-- /view-finanzas -->
```

- [ ] **Step 3: `switchView`** — en el cuerpo, junto a las líneas equivalentes de las otras vistas:

```js
  document.getElementById('view-finanzas').style.display  = v==='finanzas'  ? 'block' : 'none';
```
```js
  document.getElementById('navFinanzas').classList.toggle('active', v==='finanzas');
```
Y al final de la función (antes del `}` de cierre):
```js
  // Se pinta recién al mostrarse: Chart.js en un contenedor display:none queda de tamaño 0
  if(v==='finanzas') buildFinanzas();
```

- [ ] **Step 4: Render** — después de `/* FINANZAS_CORE:END */`:

```js
/* ── Pestaña Finanzas: render (usa FINANZAS_CORE + datasets globales) ── */
function finMesLbl(mes){ const [y,m]=mes.split("-"); return MN[+m]+"-"+y.slice(2); }
function finPctHtml(v){
  return v===null||v===undefined ? '<span class="muted">—</span>' : `<span class="${v>=0?"pos":"neg"}">${tPct(v)}</span>`;
}
function finKpi(lbl, val, sub){
  return `<div class="kpi-card"><div class="kpi-top"><div class="kpi-lbl">${lbl}</div></div>`
    +`<div class="kpi-val">${val}</div><div class="kpi-sub">${sub||""}</div></div>`;
}
/* Meses del período filtrado y sus pares del año anterior. Si algún par no existe
   en MENSUAL, yoyMeses queda vacío (no se compara un período incompleto). */
function finPeriodoActual(){
  const all=new Set(MENSUAL.map(r=>r.mes));
  if(STATE.periodo==="custom"){
    const meses=getCustomMeses(), yoy=meses.map(finYoyMes);
    return {meses, yoyMeses:yoy.every(m=>all.has(m))?yoy:[], label:STATE.fromMes+" → "+STATE.toMes};
  }
  const pd=PD[STATE.periodo]||{};
  const meses=pd.meses||[], yoy=meses.map(finYoyMes);
  return {meses, yoyMeses:yoy.every(m=>all.has(m))?yoy:[], label:pd.label||""};
}

function buildFinanzas(){
  const sinDatos=document.getElementById("finSinDatos");
  if(!IPC){
    sinDatos.style.display="flex";
    ["finKpis","finMarcaTable","finObjTable","finResto"].forEach(id=>document.getElementById(id).innerHTML="");
    ["finBaseNote","finMarcaSub","finObjNota","finEstimadoNota"].forEach(id=>document.getElementById(id).textContent="");
    return;
  }
  sinDatos.style.display="none";
  const hoy=new Date(), pace=m=>finPace(m,hoy);
  const per=finPeriodoActual();
  const marcas=STATE.marca==="todas"?["Temple","Patagonia","Feriado"]:[STATE.marca];
  const rowsOf=m=>MENSUAL.filter(r=>m==="todas"||r.m===m);
  const est=new Set(IPC.estimados||[]);
  const eSup=ms=>ms.some(m=>est.has(m))?' <sup class="muted">e</sup>':"";
  const baseLbl=finMesLbl(IPC.base);

  document.getElementById("finBaseNote").textContent="En $ de "+baseLbl+" · "+per.label
    +(STATE.marca!=="todas"?" · "+STATE.marca:"");

  // KPIs: los montos son los mismos que Ventas (real al día); el crecimiento usa cierre estimado
  const rows=rowsOf(STATE.marca);
  const suma=finSumar(rows,per.meses,IPC,()=>1);
  const c=finCrecimiento(rows,per.meses,per.yoyMeses,IPC,pace);
  const ig=finInflacion(IPC.general,per.meses,per.yoyMeses);
  const ir=finInflacion(IPC.rubro,per.meses,per.yoyMeses);
  const abierto=per.meses.some(m=>{const p=pace(m);return p!==null&&p<1;});
  const todos=[...per.meses,...per.yoyMeses];
  document.getElementById("finKpis").innerHTML=
    finKpi("Facturación nominal",fmtM(suma.nom),abierto?"Real al día · el crecimiento usa cierre estimado":"Pesos corrientes")
    +finKpi("Facturación real",fmtM(suma.real)+eSup(per.meses),"En $ de "+baseLbl)
    +finKpi("Crecimiento real vs año ant.",c?finPctHtml(c.crecReal)+eSup(todos):'<span class="muted">sin datos</span>',
            c?"Nominal "+tPct(c.crecNom):"Sin período comparable del año anterior")
    +finKpi("Inflación del período",ig!==null?tPct(ig)+eSup(todos):"—",
            ir!==null?"Rubro (hoteles y restaurantes) "+tPct(ir):"");

  // Tabla por marca
  document.getElementById("finMarcaSub").textContent=per.label
    +" vs mismo período del año anterior · same-store = solo locales con venta en ambos períodos";
  const filas=STATE.marca==="todas"?["Temple","Patagonia","Feriado","todas"]:[STATE.marca];
  let h='<thead><tr><th>Marca</th><th class="r">Crec. nominal</th><th class="r">Inflación</th>'
    +'<th class="r">Crec. real</th><th class="r">Real same-store</th></tr></thead><tbody>';
  filas.forEach(m=>{
    const cc=finCrecimiento(rowsOf(m),per.meses,per.yoyMeses,IPC,pace);
    const ss=finSameStore(LOCAL_MENSUAL,m,per.meses,per.yoyMeses,IPC,pace);
    const name=m==="todas"?"<b>Total</b>":`<span class="t-brand-cell">${tDot(m)}${m}</span>`;
    h+=`<tr><td>${name}</td><td class="r">${cc?tPct(cc.crecNom):"—"}</td>`
      +`<td class="r">${ig!==null?tPct(ig):"—"}</td>`
      +`<td class="r strong">${finPctHtml(cc?cc.crecReal:null)}</td>`
      +`<td class="r">${finPctHtml(ss?ss.crecReal:null)}</td></tr>`;
  });
  document.getElementById("finMarcaTable").innerHTML=h+"</tbody>";

  // Objetivos en términos reales (año en curso)
  const anio=String(hoy.getFullYear());
  let ho='<thead><tr><th>Marca</th><th>Mes</th><th class="r">Objetivo</th><th class="r">Venta año ant.</th>'
    +'<th class="r">Crec. nominal pedido</th><th class="r">Inflación a/a</th><th class="r">Crec. real pedido</th><th></th></tr></thead><tbody>';
  let nObj=0;
  marcas.forEach(m=>{
    const om=OBJETIVOS[m]||{};
    Object.keys(om).filter(k=>k.startsWith(anio)).sort().forEach(mes=>{
      const aa=MENSUAL.find(r=>r.m===m&&r.mes===finYoyMes(mes));
      const inf=finInflacion(IPC.general,[mes],[finYoyMes(mes)]);
      const imp=finObjImplicito(om[mes].obj_fac,aa?aa.fac:0,inf);
      const chipCls=!imp?"":imp.clase==="Exigente"?"t-chip-neg":imp.clase==="Razonable"?"t-chip-pos":"";
      ho+=`<tr><td><span class="t-brand-cell">${tDot(m)}${m}</span></td><td>${finMesLbl(mes)}</td>`
        +`<td class="r">${fmtM(om[mes].obj_fac||0)}</td><td class="r">${aa?fmtM(aa.fac):"—"}</td>`
        +`<td class="r">${imp?tPct(imp.nom):"—"}</td>`
        +`<td class="r">${inf!==null?tPct(inf)+eSup([mes]):"—"}</td>`
        +`<td class="r strong">${finPctHtml(imp?imp.real:null)}</td>`
        +`<td>${imp?`<span class="t-chip ${chipCls}">${imp.clase}</span>`:""}</td></tr>`;
      nObj++;
    });
  });
  if(!nObj) ho+='<tr><td colspan="8" class="empty">Sin objetivos cargados para '+anio+'.</td></tr>';
  document.getElementById("finObjTable").innerHTML=ho+"</tbody>";
  document.getElementById("finObjNota").textContent=
    "Exigente: pide más de +"+FIN_UMBRAL_EXIGENTE+"% real · Razonable: entre "+FIN_UMBRAL_LAXO+"% y +"+FIN_UMBRAL_EXIGENTE
    +"% · Laxo: se cumple vendiendo menos que el año anterior en términos reales."
    +(marcas.includes("Patagonia")?" El objetivo de Patagonia incluye WTC, que no registra ventas en "+anio+".":"");

  // Resto del año
  const mesHoy=anio+"-"+String(hoy.getMonth()+1).padStart(2,"0");
  const mesesResto=[];
  for(let mm=hoy.getMonth()+1;mm<=12;mm++) mesesResto.push(anio+"-"+String(mm).padStart(2,"0"));
  document.getElementById("finResto").innerHTML=marcas.map(m=>{
    const r=finRestoAnio(OBJETIVOS[m]||{},MENSUAL.filter(x=>x.m===m),anio,mesesResto,pace(mesHoy)||0,IPC);
    const lbl=tDot(m)+m;
    if(!(r.objAnual>0)) return finKpi(lbl,"—","Sin objetivo "+anio+" cargado");
    if(r.faltante<=0) return finKpi(lbl,"Cumplido","Objetivo "+anio+" de "+fmtM(r.objAnual)+" ya alcanzado");
    return finKpi(lbl,(r.imp?finPctHtml(r.imp.real):"—")+eSup(mesesResto),
      "Real necesario "+MN[hoy.getMonth()+1]+"–Dic · faltan "+fmtM(r.faltante)+" de "+fmtM(r.objAnual)
      +(r.imp?" · "+r.imp.clase:""));
  }).join("");

  // Nota de estimados y fuente
  const usados=[...new Set([...todos,...mesesResto])].filter(m=>est.has(m)).sort();
  document.getElementById("finEstimadoNota").textContent=
    (usados.length?"e = incluye IPC estimado para "+usados.map(finMesLbl).join(", ")
      +" (repite la última variación mensual publicada; se corrige solo cuando publica el INDEC). ":"")
    +"Fuente: IPC INDEC vía datos.gob.ar · base "+baseLbl
    +(IPC.fuente==="cache"?" · copia guardada: la API no respondió en la última actualización.":".");

  buildFinChart();
}

function buildFinChart(){
  if(typeof Chart==="undefined"||!IPC) return;
  tChartDefaults();
  const hoy=new Date();
  const rows=MENSUAL.filter(r=>STATE.marca==="todas"||r.m===STATE.marca);
  const cerrados=[...new Set(rows.map(r=>r.mes))].filter(m=>finPace(m,hoy)===1).sort().slice(-24);
  const b=IPC.general[IPC.base];
  const nom=cerrados.map(m=>rows.filter(r=>r.mes===m).reduce((s,r)=>s+r.fac,0));
  const real=cerrados.map((m,i)=>IPC.general[m]?nom[i]*b/IPC.general[m]:null);
  const color=STATE.marca==="Feriado"?TC.ink:(BCOLOR[STATE.marca]||TC.slate); // amarillo Feriado no contrasta sobre blanco
  document.getElementById("finChartSub").textContent="Últimos "+cerrados.length+" meses cerrados · "
    +(STATE.marca==="todas"?"todas las marcas":STATE.marca)+" · real en $ de "+finMesLbl(IPC.base);
  const data={labels:cerrados.map(finMesLbl),datasets:[
    {label:"Nominal",data:nom,borderColor:TC.ash,backgroundColor:TC.ash,borderDash:[4,4],pointRadius:0,borderWidth:2,tension:.25},
    {label:"Real",data:real,borderColor:color,backgroundColor:color,pointRadius:0,borderWidth:2.5,tension:.25}]};
  if(CHARTS.finReal){ CHARTS.finReal.data=data; CHARTS.finReal.update(); return; }
  CHARTS.finReal=new Chart(document.getElementById("cFinReal").getContext("2d"),{type:"line",data,
    options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
      scales:{y:{ticks:{callback:v=>"$ "+Math.round(v).toLocaleString("es-AR")+" M"}}},
      plugins:{tooltip:{callbacks:{label:ctx=>ctx.dataset.label+": "+fmtM(ctx.parsed.y)}}}}});
}
```

- [ ] **Step 5: `updateAll`** — dentro del `try`, al final de la cadena de `build*()`:

```js
 if(document.getElementById('view-finanzas').style.display==='block') buildFinanzas();
```

- [ ] **Step 6: Tests completos**

Run: `python -X utf8 -m pytest tests/ -q`
Expected: todo en verde (199 previos + los nuevos de Tasks 1–3)

- [ ] **Step 7: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(finanzas): pestaña Finanzas con crecimiento real y objetivos reales"
```

---

### Task 5: Verificación en preview local (antes de pedir aprobación)

**Files:** ninguno del repo (usa `design_handoff_tablero_retail/preview/`, excluida de git).

**Interfaces:**
- Consumes: todo lo anterior. `rebuild.py` cachea automáticamente `fetch_ipc_data` (empieza con `fetch_`); con bucket vacío no toca GCS.

- [ ] **Step 1: Regenerar Ventas con datos reales**

Run (desde `design_handoff_tablero_retail/preview`): `python -X utf8 rebuild.py ventas`
Expected: en el log aparecen `✓ IPC (api): base 2026-08, …` y `✓ IPC inyectado (base 2026-08)`

- [ ] **Step 2: Servir y abrir** — `python -m http.server 8765` en background; abrir `http://localhost:8765/ventas.html`, pestaña Finanzas.

- [ ] **Step 3: Barrido sin errores de JS** — en la consola del navegador:

```js
const errs=[]; const orig=console.error; console.error=(...a)=>{errs.push(a.join(" "));orig(...a);};
window.onerror=(m)=>{errs.push(String(m));};
switchView('finanzas');
for(const m of ["todas","Temple","Patagonia","Feriado"]){
  STATE.marca=m;
  for(const p of ["mes_actual","mes_anterior","ultimos_3m","ultimos_6m","ytd","todo"]){ if(PD[p]){STATE.periodo=p; updateAll();} }
  const primero=[...new Set(MENSUAL.map(r=>r.mes))].sort()[0];
  STATE.periodo="custom"; STATE.fromMes=primero; STATE.toMes=primero; updateAll(); // primer mes de la historia: sin año anterior → "sin datos"
}
({errs, raros:document.getElementById("view-finanzas").innerText.match(/NaN|Infinity|undefined/g)})
```
Expected: `errs: []`, `raros: null`

- [ ] **Step 4: Desbordes** — `http://localhost:8765/check.html?p=ventas.html` con la pestaña Finanzas activa, en 375/768/1440.
Expected: 0 desbordes (las tablas scrollean dentro de `.table-scroll`).

- [ ] **Step 5: Caso IPC null** — generar una copia con IPC nulo:

Run: `python -X utf8 -c "import re;h=open('ventas.html',encoding='utf-8').read();h=re.sub(r'const IPC = \{.*?\};\r?\n','const IPC = null;\n',h,count=1,flags=re.S);open('ventas_sin_ipc.html','w',encoding='utf-8').write(h)"`
Abrir `ventas_sin_ipc.html` → Finanzas muestra "Datos de inflación no disponibles"; Ventas funciona igual (KPIs con números, sin errores en consola).

- [ ] **Step 6: Mostrar el preview al usuario y esperar aprobación.** No mergear sin su OK.

---

### Task 6: Merge, pipeline y verificación en producción (solo con aprobación del usuario)

- [ ] **Step 1: Merge y push**

```bash
git switch main && git merge --ff-only finanzas-ipc && git push origin main
```

- [ ] **Step 2: Disparar el pipeline** — `gh workflow run actualizar-pipeline.yml --ref main`; tomar el id con `gh run list --workflow actualizar-pipeline.yml -L 1` y esperar con `gh run watch <id> --exit-status` (en background).

- [ ] **Step 3: Revisar el log (verde ≠ pasos OK)**

Run: `gh run view <id> --log | grep -iE "FALL|Traceback|Error|IPC"`
Expected: `✓ IPC (api): base …` y `✓ IPC inyectado`; ninguna línea `FALLÓ`/`Traceback`.

- [ ] **Step 4: Copia en GCS** — `curl -sI https://storage.googleapis.com/temple-bar-dashboard-cache/ipc_cache.json | grep -iE "HTTP|cache-control"` → `200` y `no-cache, no-store, must-revalidate`.

- [ ] **Step 5: Producción** — abrir `/dashboard` en Cloud Run (TTL de 5 min en memoria; si pasados 5 min no aparece la pestaña, cache-bust con `gcloud run services update temple-bar-dashboard --region southamerica-east1 --update-env-vars CACHE_BUST=$(date +%s)`) y confirmar que Finanzas muestra KPIs, gráfico, tablas y resto del año.

- [ ] **Step 6: Actualizar memoria del proyecto** con el estado y el pendiente de Insights (usan `economic_context.json` manual, desactualizado desde 2026-03).
