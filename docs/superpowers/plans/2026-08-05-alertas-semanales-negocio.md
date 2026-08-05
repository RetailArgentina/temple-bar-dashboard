# Alertas Semanales de Negocio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar automáticamente, cada lunes antes de la reunión gerencial, un reporte HTML standalone con hallazgos concretos de negocio (mix de producto, performance/ritmo, ticket/órdenes) por local y por marca (Temple, Patagonia, Feriado), publicado en GCS.

**Architecture:** Un solo script nuevo `generar_alertas_semanales.py` (mismo patrón de archivo único que el resto del repo). Reutiliza fetchers y fórmulas ya existentes en `generar_informe_semanal.py` (import directo) y el patrón de upload a GCS de `generar_preview_producto.py` (import directo). Todo el código nuevo (fetch de mix semanal, motor de reglas, render HTML) se escribe como funciones puras separadas de la obtención de datos de BigQuery, para que sean testeables sin credenciales ni red.

**Tech Stack:** Python 3, `google-cloud-bigquery`, `google-cloud-storage` (vía imports existentes), `pytest`.

## Global Constraints

- Categorías de regla en v1: **Performance**, **Mix producto**, **Ticket/Órdenes**. Fuera de alcance: canal, oportunidades de marketing, calidad de datos.
- Pace por marca: `cumpl_pace < 80` y `dias_rest > 3` → Alta; `< 92` → Media.
- Caída de local vs semana anterior: `dp < -30` → Alta; `< -20` → Media.
- Caída de ticket promedio por marca: `dp_tk < -8` → Media.
- Caída de órdenes por marca: `dp_o < -20` → Alta; `< -10` → Media.
- Mix de producto: `pct_cerveza = lts_cerveza / (lts_cerveza + lts_tragos)` — **no** usar `lts_total` (no es comparable entre marcas, ver spec).
- Mix — umbrales: desvío vs propia historia ≥ 15pp Y desvío vs pares ≥ 10pp → Alta; solo una señal → Media; ninguna → sin hallazgo.
- Mix — mínimos para evaluar: `(lts_cerveza + lts_tragos) >= 50` litros esa semana; ≥ 4 semanas de historia propia para self-history; ≥ 3 locales pares con datos esa semana para peer-comparison.
- Salida: HTML standalone, sin gráficos, sin cap de cantidad de hallazgos, agrupado Alta → Media → Baja, bloque explícito "Sin hallazgos relevantes esta semana" si la lista está vacía.
- GCS: bucket `temple-bar-dashboard-cache`, blob `alertas_semanales.html`, orden `upload_from_filename()` → `cache_control` → `patch()` → `reload()`.
- Spec completo: `docs/superpowers/specs/2026-08-05-alertas-semanales-negocio-design.md`.

---

## File Structure

- **Create:** `generar_alertas_semanales.py` — script único: `CONFIG`, `compute_date_ranges()`, `build_mix_rows()`, `fetch_mix_semanal_por_local()`, `evaluar_regla_mix()`, `evaluar_regla_performance()`, `evaluar_regla_ticket_ordenes()`, `render_alertas_html()`, `main()`.
- **Create:** `tests/test_generar_alertas_semanales.py` — todos los tests unitarios de las funciones puras de arriba.
- **Create:** `generar_alertas_semanales.bat` — entrypoint para la tarea programada.
- **Modify:** ninguno (todo lo reutilizado se importa, no se edita `generar_informe_semanal.py` ni `generar_preview_producto.py`).

---

### Task 1: Config y cálculo de rango de fechas

**Files:**
- Create: `generar_alertas_semanales.py` (arranca el archivo)
- Test: `tests/test_generar_alertas_semanales.py` (arranca el archivo)

**Interfaces:**
- Produces: `CONFIG: dict`, `compute_date_ranges(semana_inicio: date) -> dict` con claves `semana_inicio, semana_fin, sem_ant_ini, sem_ant_fin, mes_inicio, mes_key, dias_mes_total, dias_mes_trans, pace, dias_rest` (todas usadas por tasks posteriores).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generar_alertas_semanales.py
from datetime import date
from generar_alertas_semanales import compute_date_ranges, CONFIG


def test_compute_date_ranges_mid_month():
    # Lunes 10/08/2026, hoy = 12/08/2026 (miércoles de esa misma semana)
    r = compute_date_ranges(date(2026, 8, 10), hoy=date(2026, 8, 12))
    assert r["semana_inicio"] == date(2026, 8, 10)
    assert r["semana_fin"] == date(2026, 8, 16)
    assert r["sem_ant_ini"] == date(2026, 8, 3)
    assert r["sem_ant_fin"] == date(2026, 8, 9)
    assert r["mes_inicio"] == date(2026, 8, 1)
    assert r["mes_key"] == "2026-08"
    assert r["dias_mes_total"] == 31
    # hasta_mes = min(hoy, semana_fin) = 12/08 -> dias_mes_trans = 12
    assert r["dias_mes_trans"] == 12
    assert round(r["pace"], 4) == round(12 / 31, 4)
    assert r["dias_rest"] == 31 - 12


def test_compute_date_ranges_month_rollover_december():
    r = compute_date_ranges(date(2026, 12, 28), hoy=date(2026, 12, 30))
    assert r["mes_inicio"] == date(2026, 12, 1)
    assert r["dias_mes_total"] == 31


def test_config_has_required_thresholds():
    assert CONFIG["mix_desvio_self_pp"] == 15
    assert CONFIG["mix_desvio_peer_pp"] == 10
    assert CONFIG["mix_min_lts_semana"] == 50
    assert CONFIG["mix_min_semanas_historia"] == 4
    assert CONFIG["mix_min_locales_peer"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'generar_alertas_semanales'`

- [ ] **Step 3: Write minimal implementation**

```python
# generar_alertas_semanales.py
#!/usr/bin/env python3
"""
generar_alertas_semanales.py
Genera un reporte HTML semanal de alertas de negocio (mix de producto,
performance/ritmo, ticket/órdenes) por local y por marca, para la reunión
gerencial de los lunes. Publica el resultado en GCS.

Uso: python -X utf8 generar_alertas_semanales.py [--semana YYYY-MM-DD]
     [--output alertas_semanales.html] [--gcs-bucket BUCKET] [--gcs-blob BLOB]
     [--no-upload]
     --semana: lunes de inicio de la semana a evaluar (default: semana pasada)
"""

import sys
import argparse
from datetime import date, timedelta, datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

CONFIG = {
    "ticket_caida_pct":         -8,
    "mix_desvio_self_pp":       15,
    "mix_desvio_peer_pp":       10,
    "mix_min_lts_semana":       50,
    "mix_min_semanas_historia": 4,
    "mix_min_locales_peer":     3,
}

MARCAS_ACTIVAS = ["Temple", "Patagonia", "Feriado"]


def compute_date_ranges(semana_inicio: date, hoy: date = None) -> dict:
    """Calcula todos los rangos de fecha y el pace mensual para una semana dada."""
    if hoy is None:
        hoy = date.today()
    semana_fin = semana_inicio + timedelta(days=6)
    sem_ant_ini = semana_inicio - timedelta(days=7)
    sem_ant_fin = semana_inicio - timedelta(days=1)
    mes_inicio = semana_inicio.replace(day=1)
    mes_key = semana_inicio.strftime('%Y-%m')

    siguiente_mes = mes_inicio.replace(month=mes_inicio.month % 12 + 1, day=1) if mes_inicio.month != 12 \
        else mes_inicio.replace(year=mes_inicio.year + 1, month=1, day=1)
    dias_mes_total = (siguiente_mes - timedelta(days=1)).day

    hasta_mes = min(hoy, semana_fin)
    dias_mes_trans = (hasta_mes - mes_inicio).days + 1
    pace = dias_mes_trans / dias_mes_total
    dias_rest = dias_mes_total - dias_mes_trans

    return {
        "semana_inicio": semana_inicio,
        "semana_fin": semana_fin,
        "sem_ant_ini": sem_ant_ini,
        "sem_ant_fin": sem_ant_fin,
        "mes_inicio": mes_inicio,
        "mes_key": mes_key,
        "dias_mes_total": dias_mes_total,
        "dias_mes_trans": dias_mes_trans,
        "pace": pace,
        "dias_rest": dias_rest,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: config y cálculo de rango de fechas para alertas semanales"
```

---

### Task 2: Transformar filas de mix a formato normalizado (`build_mix_rows`)

**Files:**
- Modify: `generar_alertas_semanales.py`
- Modify: `tests/test_generar_alertas_semanales.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `build_mix_rows(raw_rows) -> list[dict]`, cada dict `{local: str, semana: date, lts_cerveza: float, lts_tragos: float, pct_cerveza: float | None}`. Usado por Task 4.

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace
from generar_alertas_semanales import build_mix_rows


def test_build_mix_rows_computes_pct():
    raw = [
        SimpleNamespace(local="MADERO", semana=date(2026, 8, 10), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=date(2026, 8, 3), lts_cerveza=90.0, lts_tragos=10.0),
    ]
    rows = build_mix_rows(raw)
    assert len(rows) == 2
    assert rows[0]["local"] == "MADERO"
    assert rows[0]["semana"] == date(2026, 8, 10)
    assert rows[0]["pct_cerveza"] == 0.8
    assert rows[1]["pct_cerveza"] == 0.9


def test_build_mix_rows_skips_empty_local():
    raw = [SimpleNamespace(local="", semana=date(2026, 8, 10), lts_cerveza=10.0, lts_tragos=5.0)]
    assert build_mix_rows(raw) == []


def test_build_mix_rows_pct_none_when_no_volume():
    raw = [SimpleNamespace(local="X", semana=date(2026, 8, 10), lts_cerveza=0.0, lts_tragos=0.0)]
    rows = build_mix_rows(raw)
    assert rows[0]["pct_cerveza"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k build_mix_rows`
Expected: FAIL con `ImportError: cannot import name 'build_mix_rows'`

- [ ] **Step 3: Write minimal implementation**

```python
def build_mix_rows(raw_rows) -> list:
    """Normaliza filas de BQ (con atributos local/semana/lts_cerveza/lts_tragos)
    a dicts con pct_cerveza calculado. Descarta filas sin local."""
    out = []
    for r in raw_rows:
        local = str(getattr(r, 'local', '') or '').strip()
        if not local:
            continue
        lts_cerveza = float(getattr(r, 'lts_cerveza', 0) or 0)
        lts_tragos = float(getattr(r, 'lts_tragos', 0) or 0)
        denom = lts_cerveza + lts_tragos
        pct_cerveza = (lts_cerveza / denom) if denom > 0 else None
        out.append({
            "local": local,
            "semana": getattr(r, 'semana'),
            "lts_cerveza": lts_cerveza,
            "lts_tragos": lts_tragos,
            "pct_cerveza": pct_cerveza,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k build_mix_rows`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: normalizar filas de mix de producto con pct_cerveza"
```

---

### Task 3: Fetcher de mix semanal por local (BigQuery)

**Files:**
- Modify: `generar_alertas_semanales.py`
- Modify: `tests/test_generar_alertas_semanales.py`

**Interfaces:**
- Consumes: nada (función de fetch independiente; su salida se procesa después con `build_mix_rows` de Task 2, en Task 4/7).
- Produces: `fetch_mix_semanal_por_local(client, marca: str, desde: str, hasta: str) -> list` (filas crudas de BQ, mismo formato que consume `build_mix_rows`). Usado por Task 7 (`main`).

- [ ] **Step 1: Write the failing test**

```python
import pytest
from generar_alertas_semanales import fetch_mix_semanal_por_local


class _FakeJob:
    def __init__(self, sql):
        self.sql = sql

    def result(self):
        return []


class _FakeClient:
    def __init__(self):
        self.last_sql = None

    def query(self, sql):
        self.last_sql = sql
        return _FakeJob(sql)


def test_fetch_mix_temple_query_shape():
    client = _FakeClient()
    fetch_mix_semanal_por_local(client, "Temple", "2026-06-01", "2026-08-16")
    sql = client.last_sql
    assert "vw_curated_compilado_ok" in sql
    assert "establecimiento" in sql
    assert "cerveza_total" in sql
    assert "tragos_total" in sql
    assert "GROUP BY local, semana" in sql


def test_fetch_mix_patagonia_query_shape():
    client = _FakeClient()
    fetch_mix_semanal_por_local(client, "Patagonia", "2026-06-01", "2026-08-16")
    sql = client.last_sql
    assert "curated_mix" in sql
    assert "cerveza_total" in sql
    assert "tragos_total" in sql


def test_fetch_mix_feriado_query_shape():
    client = _FakeClient()
    fetch_mix_semanal_por_local(client, "Feriado", "2026-06-01", "2026-08-16")
    sql = client.last_sql
    assert "vw_Ventas_Feriado" in sql
    assert "Categoria_Empresa" in sql


def test_fetch_mix_unknown_marca_raises():
    client = _FakeClient()
    with pytest.raises(ValueError):
        fetch_mix_semanal_por_local(client, "Otra", "2026-06-01", "2026-08-16")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k fetch_mix`
Expected: FAIL con `ImportError: cannot import name 'fetch_mix_semanal_por_local'`

- [ ] **Step 3: Write minimal implementation**

```python
def _fetch_mix_temple(client, desde, hasta):
    q = f"""
    SELECT
      establecimiento                          AS local,
      DATE_TRUNC(fecha, WEEK(MONDAY))           AS semana,
      ROUND(SUM(COALESCE(cerveza_total,0)), 2) AS lts_cerveza,
      ROUND(SUM(COALESCE(tragos_total, 0)), 2) AS lts_tragos
    FROM `temple-bar-439715.curated_database.vw_curated_compilado_ok`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local, semana
    ORDER BY local, semana
    """
    return list(client.query(q).result())


def _fetch_mix_patagonia(client, desde, hasta):
    q = f"""
    SELECT
      establecimiento                          AS local,
      DATE_TRUNC(fecha, WEEK(MONDAY))           AS semana,
      ROUND(SUM(COALESCE(cerveza_total,0)), 2) AS lts_cerveza,
      ROUND(SUM(COALESCE(tragos_total, 0)), 2) AS lts_tragos
    FROM `patagonia-refugios.curated_database.curated_mix`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local, semana
    ORDER BY local, semana
    """
    return list(client.query(q).result())


def _fetch_mix_feriado(client, desde, hasta):
    # Feriado no tiene un campo "tragos_total" propio en Ventas_Toteat (a
    # diferencia de Temple/Patagonia). Se usa "todo lo que no es cerveza"
    # (gin, fernet, vermú, etc.) como el bucket comparable de "tragos",
    # mismo criterio de Categoria_Empresa que ya usa fetch_locales_feriado()
    # en generar_preview_producto.py.
    q = f"""
    SELECT
      Establecimiento                                          AS local,
      DATE_TRUNC(Fecha, WEEK(MONDAY))                          AS semana,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa))
                          IN ('cmq cerveza','temple cerveza')
                     THEN COALESCE(Litros,0) ELSE 0 END), 2)   AS lts_cerveza,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa))
                          NOT IN ('cmq cerveza','temple cerveza')
                     THEN COALESCE(Litros,0) ELSE 0 END), 2)   AS lts_tragos
    FROM `temple-bar-439715.Feriado.vw_Ventas_Feriado`
    WHERE Fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local, semana
    ORDER BY local, semana
    """
    return list(client.query(q).result())


_MIX_FETCHERS = {
    "Temple": _fetch_mix_temple,
    "Patagonia": _fetch_mix_patagonia,
    "Feriado": _fetch_mix_feriado,
}


def fetch_mix_semanal_por_local(client, marca: str, desde: str, hasta: str) -> list:
    """Filas crudas de BQ con local/semana/lts_cerveza/lts_tragos para la marca dada."""
    fetcher = _MIX_FETCHERS.get(marca)
    if fetcher is None:
        raise ValueError(f"Marca desconocida para fetch de mix: {marca!r}")
    return fetcher(client, desde, hasta)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k fetch_mix`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: fetcher de mix semanal cerveza/tragos por local y marca"
```

---

### Task 4: Regla de mix de producto (`evaluar_regla_mix`)

**Files:**
- Modify: `generar_alertas_semanales.py`
- Modify: `tests/test_generar_alertas_semanales.py`

**Interfaces:**
- Consumes: `CONFIG` (Task 1), filas normalizadas con la forma de `build_mix_rows()` (Task 2): `{local, semana, lts_cerveza, lts_tragos, pct_cerveza}`.
- Produces: `evaluar_regla_mix(mix_rows: list[dict], marca: str, semana_evaluada: date, config: dict) -> list[dict]`. Cada hallazgo: `{"marca": str, "local": str, "categoria": "Mix producto", "severidad": "Alta"|"Media", "mensaje": str, "detalle": str}`. Usado por Task 7 (`main`) y tiene la misma forma que producen Task 5.

- [ ] **Step 1: Write the failing test**

```python
from generar_alertas_semanales import evaluar_regla_mix, CONFIG


def _rows_semana(local, semana, pct, lts_total=100.0):
    """Helper de test: fila con pct_cerveza dado y volumen total fijo."""
    return {
        "local": local, "semana": semana,
        "lts_cerveza": lts_total * pct, "lts_tragos": lts_total * (1 - pct),
        "pct_cerveza": pct,
    }


def test_mix_ambas_senales_da_alta():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    peers = [_rows_semana("OTRO_A", semana, 0.78), _rows_semana("OTRO_B", semana, 0.82),
             _rows_semana("OTRO_C", semana, 0.80)]
    actual = _rows_semana("MADERO", semana, 0.55)  # cae 25pp vs su historia y vs pares
    hallazgos = evaluar_regla_mix(historia + peers + [actual], "Patagonia", semana, CONFIG)
    assert len(hallazgos) == 1
    h = hallazgos[0]
    assert h["local"] == "MADERO"
    assert h["marca"] == "Patagonia"
    assert h["categoria"] == "Mix producto"
    assert h["severidad"] == "Alta"


def test_mix_solo_senal_propia_da_media():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    # Sin pares (menos de mix_min_locales_peer) -> solo se evalúa self
    actual = _rows_semana("MADERO", semana, 0.60)
    hallazgos = evaluar_regla_mix(historia + [actual], "Patagonia", semana, CONFIG)
    assert len(hallazgos) == 1
    assert hallazgos[0]["severidad"] == "Media"


def test_mix_sin_desvio_no_genera_hallazgo():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    actual = _rows_semana("MADERO", semana, 0.79)
    hallazgos = evaluar_regla_mix(historia + [actual], "Patagonia", semana, CONFIG)
    assert hallazgos == []


def test_mix_bajo_volumen_minimo_se_ignora():
    semana = date(2026, 8, 10)
    actual = _rows_semana("LOCAL_CHICO", semana, 0.10, lts_total=10.0)  # < mix_min_lts_semana
    hallazgos = evaluar_regla_mix([actual], "Feriado", semana, CONFIG)
    assert hallazgos == []


def test_mix_sin_fila_de_la_semana_evaluada_se_ignora():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=1), 0.80)]
    hallazgos = evaluar_regla_mix(historia, "Patagonia", semana, CONFIG)
    assert hallazgos == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k mix`
Expected: FAIL con `ImportError: cannot import name 'evaluar_regla_mix'`

- [ ] **Step 3: Write minimal implementation**

```python
def evaluar_regla_mix(mix_rows: list, marca: str, semana_evaluada, config: dict) -> list:
    """Detecta locales cuyo mix cerveza/tragos se desvía de su propia historia
    y/o del promedio de sus pares (misma marca) en la semana evaluada."""
    por_local = {}
    for row in mix_rows:
        por_local.setdefault(row["local"], []).append(row)

    hallazgos = []
    for local, filas in por_local.items():
        actual = next((f for f in filas if f["semana"] == semana_evaluada), None)
        if actual is None or actual["pct_cerveza"] is None:
            continue
        volumen = actual["lts_cerveza"] + actual["lts_tragos"]
        if volumen < config["mix_min_lts_semana"]:
            continue

        historia = [f["pct_cerveza"] for f in filas
                    if f["semana"] != semana_evaluada and f["pct_cerveza"] is not None]
        desvio_self = None
        self_avg = None
        if len(historia) >= config["mix_min_semanas_historia"]:
            self_avg = sum(historia) / len(historia)
            desvio_self = (actual["pct_cerveza"] - self_avg) * 100

        peers = [f["pct_cerveza"] for otro_local, filas_otro in por_local.items()
                 if otro_local != local
                 for f in filas_otro
                 if f["semana"] == semana_evaluada and f["pct_cerveza"] is not None]
        desvio_peer = None
        peer_avg = None
        if len(peers) >= config["mix_min_locales_peer"]:
            peer_avg = sum(peers) / len(peers)
            desvio_peer = (actual["pct_cerveza"] - peer_avg) * 100

        self_flag = desvio_self is not None and abs(desvio_self) >= config["mix_desvio_self_pp"]
        peer_flag = desvio_peer is not None and abs(desvio_peer) >= config["mix_desvio_peer_pp"]

        if self_flag and peer_flag:
            severidad = "Alta"
        elif self_flag or peer_flag:
            severidad = "Media"
        else:
            continue

        pct_txt = f"{actual['pct_cerveza'] * 100:.0f}%"
        self_txt = f"{self_avg * 100:.0f}% (su propia historia)" if self_avg is not None else "sin historia suficiente"
        peer_txt = f"{peer_avg * 100:.0f}% (locales pares)" if peer_avg is not None else "sin pares comparables"
        hallazgos.append({
            "marca": marca,
            "local": local,
            "categoria": "Mix producto",
            "severidad": severidad,
            "mensaje": f"{local} ({marca}): cerveza es el {pct_txt} del volumen cerveza+tragos esta semana",
            "detalle": f"Esperado: {self_txt}; {peer_txt}.",
        })

    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos.sort(key=lambda h: orden.get(h["severidad"], 9))
    return hallazgos
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k mix`
Expected: PASS (todos los tests de mix, 9 en total incluyendo Task 2/3)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: regla de mix de producto (desvío self+peer combinado)"
```

---

### Task 5: Reglas de performance/ritmo y ticket/órdenes

**Files:**
- Modify: `generar_alertas_semanales.py`
- Modify: `tests/test_generar_alertas_semanales.py`

**Interfaces:**
- Consumes: `CONFIG` (Task 1). Inputs con la misma forma que produce `agg_por_marca`/`agg_por_local` de `generar_informe_semanal.py` (dict `{fac_M, ordenes}` por marca, y lista de dicts `{Marca, local, fac_M, ordenes}` para locales).
- Produces: `evaluar_regla_performance(marca_esta, marca_ant, locales_top, locales_ant_dict, objetivos, mes_key, pace, dias_rest, config, mes_real) -> list[dict]` y `evaluar_regla_ticket_ordenes(marca_esta, marca_ant, config) -> list[dict]`. Misma forma de hallazgo que Task 4 (`categoria` = `"Performance"` o `"Ticket/Órdenes"`). Usados por Task 7.

- [ ] **Step 1: Write the failing test**

```python
from generar_alertas_semanales import evaluar_regla_performance, evaluar_regla_ticket_ordenes


def test_performance_pace_bajo_da_alta():
    marca_esta = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}
    marca_ant = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}
    objetivos = {"Temple": {"2026-08": 100.0}}
    # pace=0.5 (mitad del mes) -> obj_pace=50, real acumulado 30 -> cumpl 60% (<80)
    hallazgos = evaluar_regla_performance(
        marca_esta, marca_ant, locales_top=[], locales_ant_dict={},
        objetivos=objetivos, mes_key="2026-08", pace=0.5, dias_rest=15,
        config=CONFIG, mes_real={"Temple": {"fac_M": 30.0}},
    )
    pace_h = [h for h in hallazgos if "ritmo" in h["mensaje"]]
    assert len(pace_h) == 1
    assert pace_h[0]["severidad"] == "Alta"
    assert pace_h[0]["categoria"] == "Performance"


def test_performance_caida_local_da_media():
    locales_top = [{"Marca": "Temple", "local": "PALERMO", "fac_M": 4.0, "ordenes": 500}]
    locales_ant_dict = {("Temple", "PALERMO"): 5.0}  # -20% exacto -> Media
    hallazgos = evaluar_regla_performance(
        marca_esta={}, marca_ant={}, locales_top=locales_top,
        locales_ant_dict=locales_ant_dict, objetivos={}, mes_key="2026-08",
        pace=0.5, dias_rest=15, config=CONFIG, mes_real={},
    )
    local_h = [h for h in hallazgos if h["local"] == "PALERMO"]
    assert len(local_h) == 1
    assert local_h[0]["severidad"] == "Media"
    assert local_h[0]["categoria"] == "Performance"


def test_ticket_caida_da_media():
    marca_esta = {"Temple": {"fac_M": 9.0, "ordenes": 1000}}   # ticket = 9000
    marca_ant = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}   # ticket = 10000, cae 10%
    hallazgos = evaluar_regla_ticket_ordenes(marca_esta, marca_ant, CONFIG)
    ticket_h = [h for h in hallazgos if "ticket" in h["mensaje"].lower()]
    assert len(ticket_h) == 1
    assert ticket_h[0]["severidad"] == "Media"
    assert ticket_h[0]["categoria"] == "Ticket/Órdenes"


def test_ordenes_caida_fuerte_da_alta():
    marca_esta = {"Temple": {"fac_M": 8.0, "ordenes": 780}}
    marca_ant = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}  # -22% ordenes
    hallazgos = evaluar_regla_ticket_ordenes(marca_esta, marca_ant, CONFIG)
    ordenes_h = [h for h in hallazgos if "órdenes" in h["mensaje"].lower()]
    assert len(ordenes_h) == 1
    assert ordenes_h[0]["severidad"] == "Alta"


def test_sin_datos_previos_no_rompe():
    hallazgos = evaluar_regla_ticket_ordenes({"Temple": {"fac_M": 5.0, "ordenes": 400}}, {}, CONFIG)
    assert hallazgos == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k "performance or ticket or ordenes"`
Expected: FAIL con `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
def ticket_prom(fac_M, ordenes):
    if ordenes == 0:
        return 0
    return round(fac_M * 1e6 / ordenes)


def evaluar_regla_performance(marca_esta, marca_ant, locales_top, locales_ant_dict,
                               objetivos, mes_key, pace, dias_rest, config, mes_real):
    """Pace por marca vs objetivo prorrateado + caída de local vs semana anterior."""
    hallazgos = []

    for m, obj_por_mes in objetivos.items():
        obj_M = obj_por_mes.get(mes_key, 0)
        real_M = mes_real.get(m, {}).get('fac_M', 0)
        if obj_M <= 0:
            continue
        obj_pace = obj_M * pace
        cumpl_pace = real_M / obj_pace * 100 if obj_pace > 0 else 100
        if cumpl_pace < 80 and dias_rest > 3:
            severidad = "Alta"
        elif cumpl_pace < 92 and dias_rest > 3:
            severidad = "Media"
        else:
            continue
        falta = obj_M - real_M
        por_dia = falta / dias_rest if dias_rest > 0 else 0
        hallazgos.append({
            "marca": m, "local": None, "categoria": "Performance", "severidad": severidad,
            "mensaje": f"{m}: ritmo de facturación {cumpl_pace:.0f}% del objetivo esperado",
            "detalle": f"Faltan ${falta:.1f}M para el objetivo. Necesita ${por_dia:.1f}M/día "
                       f"en los próximos {dias_rest} días.",
        })

    caidas = []
    for loc in locales_top:
        key = (loc['Marca'], loc['local'])
        fac0 = locales_ant_dict.get(key, 0)
        if fac0 > 0 and loc['fac_M'] > 0:
            dp = (loc['fac_M'] - fac0) / fac0 * 100
            if dp <= -20:
                caidas.append((loc, dp, fac0))
    for loc, dp, fac0 in caidas:
        severidad = "Alta" if dp < -30 else "Media"
        hallazgos.append({
            "marca": loc['Marca'], "local": loc['local'], "categoria": "Performance",
            "severidad": severidad,
            "mensaje": f"{loc['local']} ({loc['Marca']}): caída del {abs(dp):.0f}% vs semana anterior",
            "detalle": f"Pasó de ${fac0:.1f}M a ${loc['fac_M']:.1f}M.",
        })

    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos.sort(key=lambda h: orden.get(h["severidad"], 9))
    return hallazgos


def evaluar_regla_ticket_ordenes(marca_esta, marca_ant, config):
    """Caída de ticket promedio y de cantidad de órdenes por marca."""
    hallazgos = []
    for m, datos_esta in marca_esta.items():
        datos_ant = marca_ant.get(m)
        if not datos_ant:
            continue

        tk_e = ticket_prom(datos_esta.get('fac_M', 0), datos_esta.get('ordenes', 0))
        tk_a = ticket_prom(datos_ant.get('fac_M', 0), datos_ant.get('ordenes', 0))
        if tk_a > 0 and tk_e > 0:
            dp_tk = (tk_e - tk_a) / tk_a * 100
            if dp_tk <= config["ticket_caida_pct"]:
                hallazgos.append({
                    "marca": m, "local": None, "categoria": "Ticket/Órdenes", "severidad": "Media",
                    "mensaje": f"{m}: ticket promedio cayó {abs(dp_tk):.0f}% (${tk_e:,.0f} vs ${tk_a:,.0f} sem. ant.)",
                    "detalle": "Puede indicar mix de productos más económico o promociones activas.",
                })

        ord_e = datos_esta.get('ordenes', 0)
        ord_a = datos_ant.get('ordenes', 0)
        if ord_a > 0 and ord_e > 0:
            dp_o = (ord_e - ord_a) / ord_a * 100
            if dp_o < -10:
                severidad = "Alta" if dp_o < -20 else "Media"
                hallazgos.append({
                    "marca": m, "local": None, "categoria": "Ticket/Órdenes", "severidad": severidad,
                    "mensaje": f"{m}: caída del {abs(dp_o):.0f}% en cantidad de órdenes vs semana anterior",
                    "detalle": f"Pasó de {ord_a:,} a {ord_e:,} órdenes.",
                })

    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos.sort(key=lambda h: orden.get(h["severidad"], 9))
    return hallazgos
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k "performance or ticket or ordenes"`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: reglas de performance/ritmo y ticket/ordenes reutilizando umbrales validados"
```

---

### Task 6: Render HTML del reporte

**Files:**
- Modify: `generar_alertas_semanales.py`
- Modify: `tests/test_generar_alertas_semanales.py`

**Interfaces:**
- Consumes: lista de hallazgos con la forma producida por Task 4/5: `{marca, local, categoria, severidad, mensaje, detalle}`.
- Produces: `render_alertas_html(hallazgos: list[dict], semana_inicio: date, semana_fin: date, generado_en: datetime) -> str`. Usado por Task 7.

- [ ] **Step 1: Write the failing test**

```python
from generar_alertas_semanales import render_alertas_html


def test_render_sin_hallazgos_muestra_estado_explicito():
    html = render_alertas_html([], date(2026, 8, 10), date(2026, 8, 16), datetime(2026, 8, 17, 6, 30))
    assert "Sin hallazgos relevantes esta semana" in html


def test_render_agrupa_por_severidad_alta_primero():
    hallazgos = [
        {"marca": "Temple", "local": None, "categoria": "Performance", "severidad": "Media",
         "mensaje": "Mensaje media", "detalle": "Detalle media"},
        {"marca": "Patagonia", "local": "MADERO", "categoria": "Mix producto", "severidad": "Alta",
         "mensaje": "Mensaje alta", "detalle": "Detalle alta"},
    ]
    html = render_alertas_html(hallazgos, date(2026, 8, 10), date(2026, 8, 16), datetime(2026, 8, 17, 6, 30))
    pos_alta = html.index("Mensaje alta")
    pos_media = html.index("Mensaje media")
    assert pos_alta < pos_media
    assert "Mix producto" in html
    assert "10/08/2026" in html and "16/08/2026" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k render`
Expected: FAIL con `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
_SEVERIDAD_COLOR = {"Alta": "#dc2626", "Media": "#d97706", "Baja": "#475569"}


def render_alertas_html(hallazgos: list, semana_inicio, semana_fin, generado_en) -> str:
    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos_ordenados = sorted(hallazgos, key=lambda h: orden.get(h["severidad"], 9))

    if hallazgos_ordenados:
        bloques = []
        for h in hallazgos_ordenados:
            color = _SEVERIDAD_COLOR.get(h["severidad"], "#475569")
            bloques.append(f"""
            <div class="hallazgo" style="border-left: 4px solid {color};">
              <span class="badge" style="background:{color};">{h['severidad']}</span>
              <span class="categoria">{h['categoria']}</span>
              <p class="mensaje">{h['mensaje']}</p>
              <p class="detalle">{h['detalle']}</p>
            </div>""")
        cuerpo = "\n".join(bloques)
    else:
        cuerpo = '<div class="sin-hallazgos">✅ Sin hallazgos relevantes esta semana.</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Alertas Semanales de Negocio</title>
<style>
  body {{ background:#0f2544; color:#f1f5f9; font-family: Arial, sans-serif; padding: 24px; }}
  h1 {{ color:#f1f5f9; }}
  .subtitulo {{ color:#cbd5e1; margin-bottom: 24px; }}
  .hallazgo {{ background:#16324f; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; }}
  .badge {{ display:inline-block; padding: 2px 8px; border-radius: 4px; font-weight:bold; font-size: 12px; }}
  .categoria {{ margin-left: 8px; color:#94a3b8; font-size: 13px; }}
  .mensaje {{ font-weight:bold; margin: 6px 0 2px 0; }}
  .detalle {{ color:#cbd5e1; margin: 0; font-size: 14px; }}
  .sin-hallazgos {{ background:#16324f; border-radius: 6px; padding: 16px; }}
  footer {{ color:#475569; margin-top: 32px; font-size: 12px; }}
</style>
</head>
<body>
  <h1>🚨 Alertas Semanales de Negocio</h1>
  <p class="subtitulo">
    Semana {semana_inicio.strftime('%d/%m/%Y')} – {semana_fin.strftime('%d/%m/%Y')} ·
    Generado {generado_en.strftime('%d/%m/%Y %H:%M')}
  </p>
  {cuerpo}
  <footer>Temple · Patagonia · Feriado — reporte automático semanal</footer>
</body>
</html>"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k render`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: render HTML de alertas semanales"
```

---

### Task 7: Orquestación CLI (`main`) y publicación a GCS

**Files:**
- Modify: `generar_alertas_semanales.py`
- Modify: `tests/test_generar_alertas_semanales.py`

**Interfaces:**
- Consumes: TODO lo anterior — `compute_date_ranges`, `build_mix_rows`, `fetch_mix_semanal_por_local`, `evaluar_regla_mix`, `evaluar_regla_performance`, `evaluar_regla_ticket_ordenes`, `render_alertas_html`, `CONFIG`, `MARCAS_ACTIVAS`. Además importa de `generar_informe_semanal.py`: `get_client, fetch_semana, fetch_mes_actual, fetch_objetivos, agg_por_marca, agg_por_local`. Y de `generar_preview_producto.py`: `upload_to_gcs`.
- Produces: `main()` (entry point del script, sin retorno usado por otros módulos).

- [ ] **Step 1: Write the failing test**

```python
import os
from unittest.mock import patch


def test_main_no_upload_genera_archivo_local(tmp_path, monkeypatch):
    output_path = tmp_path / "alertas_test.html"
    monkeypatch.chdir(tmp_path)

    with patch("generar_alertas_semanales.get_client", return_value=object()), \
         patch("generar_alertas_semanales.fetch_semana", return_value=[]), \
         patch("generar_alertas_semanales.fetch_mes_actual", return_value={}), \
         patch("generar_alertas_semanales.fetch_objetivos", return_value={}), \
         patch("generar_alertas_semanales.fetch_mix_semanal_por_local", return_value=[]), \
         patch("sys.argv", ["generar_alertas_semanales.py",
                             "--semana", "2026-08-10",
                             "--output", str(output_path),
                             "--no-upload"]):
        import generar_alertas_semanales
        generar_alertas_semanales.main()

    assert output_path.exists()
    contenido = output_path.read_text(encoding="utf-8")
    assert "Alertas Semanales de Negocio" in contenido
    assert "Sin hallazgos relevantes esta semana" in contenido
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k main`
Expected: FAIL con `AttributeError: module 'generar_alertas_semanales' has no attribute 'main'`

- [ ] **Step 3: Write minimal implementation**

```python
from generar_informe_semanal import (
    get_client, fetch_semana, fetch_mes_actual, fetch_objetivos,
    agg_por_marca, agg_por_local,
)
from generar_preview_producto import upload_to_gcs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--semana', default=None,
                         help='Lunes de inicio de la semana a evaluar (YYYY-MM-DD, default: semana pasada)')
    parser.add_argument('--output', default='alertas_semanales.html')
    parser.add_argument('--gcs-bucket', default='temple-bar-dashboard-cache')
    parser.add_argument('--gcs-blob', default='alertas_semanales.html')
    parser.add_argument('--no-upload', action='store_true')
    args = parser.parse_args()

    if args.semana:
        semana_inicio = datetime.strptime(args.semana, '%Y-%m-%d').date()
    else:
        hoy = date.today()
        lunes_esta_semana = hoy - timedelta(days=hoy.weekday())
        semana_inicio = lunes_esta_semana - timedelta(days=7)

    rangos = compute_date_ranges(semana_inicio)
    client = get_client()

    rows_esta = fetch_semana(client, rangos["semana_inicio"].isoformat(), rangos["semana_fin"].isoformat())
    rows_ant = fetch_semana(client, rangos["sem_ant_ini"].isoformat(), rangos["sem_ant_fin"].isoformat())
    marca_esta = agg_por_marca(rows_esta)
    marca_ant = agg_por_marca(rows_ant)
    locales_top = agg_por_local(rows_esta)
    locales_ant_dict = {(l['Marca'], l['local']): l['fac_M'] for l in agg_por_local(rows_ant)}

    mes_real = fetch_mes_actual(client, rangos["mes_inicio"].isoformat(), rangos["semana_fin"].isoformat())
    objetivos = fetch_objetivos()

    hallazgos = []
    hallazgos += evaluar_regla_performance(
        marca_esta, marca_ant, locales_top, locales_ant_dict, objetivos,
        rangos["mes_key"], rangos["pace"], rangos["dias_rest"], CONFIG, mes_real,
    )
    hallazgos += evaluar_regla_ticket_ordenes(marca_esta, marca_ant, CONFIG)

    desde_mix = (rangos["semana_inicio"] - timedelta(weeks=8)).isoformat()
    hasta_mix = rangos["semana_fin"].isoformat()
    for marca in MARCAS_ACTIVAS:
        raw_mix = fetch_mix_semanal_por_local(client, marca, desde_mix, hasta_mix)
        mix_rows = build_mix_rows(raw_mix)
        hallazgos += evaluar_regla_mix(mix_rows, marca, rangos["semana_inicio"], CONFIG)

    html = render_alertas_html(hallazgos, rangos["semana_inicio"], rangos["semana_fin"], datetime.now())
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generado {args.output} con {len(hallazgos)} hallazgo(s)")

    if not args.no_upload:
        from google.oauth2 import service_account
        import os as _os
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        sa_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "temple-bar-439715-da51b292ce5d.json")
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)
        upload_to_gcs(args.output, args.gcs_bucket, args.gcs_blob, creds)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generar_alertas_semanales.py -v -k main`
Expected: PASS

Luego correr la suite completa para confirmar que nada se rompió:
Run: `python -m pytest tests/test_generar_alertas_semanales.py -v`
Expected: PASS (todos los tests de Tasks 1-7)

- [ ] **Step 5: Commit**

```bash
git add generar_alertas_semanales.py tests/test_generar_alertas_semanales.py
git commit -m "feat: orquestación CLI de alertas semanales con publicación a GCS"
```

---

### Task 8: Script `.bat` y tarea programada

**Files:**
- Create: `generar_alertas_semanales.bat`

**Interfaces:**
- Consumes: `generar_alertas_semanales.py` (Task 7) vía `python -X utf8`.
- Produces: nada consumido por otro código — es el entrypoint de la tarea programada de Windows.

- [ ] **Step 1: Ver el .bat existente para copiar el mismo patrón de activación de entorno**

Run: `type "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\actualizar_dashboard.bat"`

- [ ] **Step 2: Crear `generar_alertas_semanales.bat`**

```bat
@echo off
cd /d "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork"
python -X utf8 generar_alertas_semanales.py --gcs-bucket temple-bar-dashboard-cache --gcs-blob alertas_semanales.html >> logs\alertas_semanales.log 2>&1
```
(Si `actualizar_dashboard.bat` activa un venv específico con `call venv\Scripts\activate.bat` u otro mecanismo, copiar esa línea exacta antes del `python -X utf8 ...` — no asumir que el `python` del PATH del sistema es el correcto.)

- [ ] **Step 3: Probar el .bat manualmente**

Run: `"C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\generar_alertas_semanales.bat"`
Expected: crea/actualiza `alertas_semanales.html` en el directorio del proyecto y sube a GCS sin errores (revisar `logs\alertas_semanales.log`).

- [ ] **Step 4: Crear la tarea programada de Windows**

Run (PowerShell, como administrador si hace falta):
```powershell
$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\cmd.exe" `
  -Argument '/c "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\generar_alertas_semanales.bat"'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 06:30AM
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Alertas Semanales Lunes" -Action $action `
  -Trigger $trigger -Settings $settings -Description "Genera y publica el reporte de alertas semanales de negocio"
```

- [ ] **Step 5: Verificar la tarea con una corrida manual**

Run: `schtasks /run /tn "Alertas Semanales Lunes"`
Expected: la tarea corre, `alertas_semanales.html` se actualiza en GCS. Verificar con:
```
curl -I "https://storage.googleapis.com/temple-bar-dashboard-cache/alertas_semanales.html"
```
Expected: `Cache-Control: no-cache, no-store, must-revalidate` en la respuesta.

- [ ] **Step 6: Commit**

```bash
git add generar_alertas_semanales.bat
git commit -m "feat: bat y tarea programada semanal para alertas de negocio"
```

---

## Verificación final end-to-end (después de Task 8)

1. `python -m pytest tests/test_generar_alertas_semanales.py -v` — todos los tests pasan.
2. Correr manualmente contra 2-3 semanas históricas reales conocidas por Darwin:
   `python -X utf8 generar_alertas_semanales.py --semana 2026-07-13 --no-upload --output /tmp/alertas_test.html`
   y confirmar que los hallazgos son razonables (no hay ruido evidente, y el caso real de mix cerveza/tragos en Patagonia que motivó el proyecto aparece si corresponde a esa semana).
3. Ajustar `CONFIG` (umbrales de mix, principalmente) según ese contraste antes de dejar la tarea programada corriendo sola sin supervisión.
4. Confirmar el link público funciona: abrir `https://storage.googleapis.com/temple-bar-dashboard-cache/alertas_semanales.html?v=1` en el navegador.
