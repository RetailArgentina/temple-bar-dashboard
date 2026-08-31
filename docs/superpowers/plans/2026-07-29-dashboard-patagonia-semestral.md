# Dashboard Patagonia Semestral — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir `Proyecto_Patagonia_Semestral`, un tablero web standalone (Flask, sin auth, patrón `Proyecto_Mundial`) que presente de forma interactiva los KPIs del primer semestre 2026 de Patagonia para la reunión de resultados con Patagonia.

**Architecture:** Un script generador (`generar_patagonia_semestral.py`) corre queries de BigQuery + lee 3 CSV manuales, construye un único JSON, lo sube a GCS. Una app Flask (`main.py`) sirve ese JSON cacheado y una plantilla HTML con 7 tabs (JS puro, Chart.js) que consume el JSON vía `fetch('/data')`.

**Tech Stack:** Python 3, Flask, `google-cloud-bigquery`, `google-cloud-storage`, Chart.js 4.4.4 (CDN), HTML/CSS/JS vanilla (sin build step, mismo patrón que `Proyecto_Mundial`).

## Global Constraints

- Proyecto BigQuery: `temple-bar-439715`. Bucket GCS: `temple-bar-dashboard-cache`. Ruta del JSON: `patagonia_semestral/patagonia_data.json`.
- Marca en `vw_Ventas_Corporativo_Base`: `'Patagonia'`. Marca en `vw_productos_maestro_clean`: `'PATAGONIA'` (mayúsculas).
- Rango de datos históricos a consultar: `2025-01-01` a `2026-06-30` (necesario para YoY). Semestre de reporte: `2026-01-01` a `2026-06-30`.
- **Verificado en BigQuery real (2026-07-29):** los 43 nombres de `Local` (`vw_Ventas_Corporativo_Base`, marca Patagonia) coinciden 1:1 con los 43 `establecimiento` (`vw_productos_maestro_clean`, marca PATAGONIA) — join directo por igualdad de string, sin mapeo.
- **Verificado en BigQuery real:** `google_reviews_snapshots` no tiene datos antes del 2026-07-22 — no se usa en este proyecto. Todo el bloque Reputology es CSV manual.
- SOT cerveza = unidades cerveza / unidades alcohólicas totales (`tipo IN ('CERVEZA','TRAGOS','VINO')` como denominador, `tipo='CERVEZA'` como numerador exacto de BQ — los litros/unidades de cerveza estimados por nombre de producto NO entran al numerador del SOT, solo al KPI de litros; ver Task 3).
- Litros de cerveza = `cerveza_total` de BQ cuando no es NULL, más una estimación por nombre de producto (520ml/pinta) cuando `cerveza_total` es NULL pero el producto es identificable como cerveza — ver Task 3, es la lógica más sensible del proyecto.
- Sin autenticación en ningún endpoint, incluyendo `/refresh`.
- No hay tests para HTML/JS en este repo (patrón ya establecido en `Proyecto_Mundial`, `dashboard.html`) — la verificación de las tabs es visual en navegador local (Task 11), no pytest. Sí hay tests reales (pytest) para toda la lógica de cálculo en Python (Tasks 2 y 3), porque son funciones puras con riesgo real de estar mal.
- Spec de referencia: `docs/superpowers/specs/2026-07-29-dashboard-patagonia-semestral-design.md`.

---

## OLA 1 (paralelo — 5 tareas sin archivos compartidos, se pueden ejecutar con agentes simultáneos)

### Task 1: Scaffold del proyecto + config + acciones + CSVs manuales

**Files:**
- Create: `Proyecto_Patagonia_Semestral/requirements.txt`
- Create: `Proyecto_Patagonia_Semestral/Procfile`
- Create: `Proyecto_Patagonia_Semestral/config.py`
- Create: `Proyecto_Patagonia_Semestral/acciones.py`
- Create: `Proyecto_Patagonia_Semestral/data/sellin_cerveza.csv`
- Create: `Proyecto_Patagonia_Semestral/data/reputology.csv`
- Create: `Proyecto_Patagonia_Semestral/.gitignore`

**Interfaces:**
- Produces: constantes `PROJECT`, `BUCKET`, `GCS_PATH`, `MARCA_VENTAS`, `MARCA_PRODUCTOS`, `FECHA_DESDE_HIST`, `SEMESTRE_DESDE`, `SEMESTRE_HASTA`, `COL_ORDEN`, `COL_FECHA`, `COL_MARCA`, `COL_LOCAL`, `COL_TOTAL`, `COL_PM_LOCAL`, `COL_PM_MARCA`, `COL_PM_PRODUCTO`, `COL_PM_FECHA`, `COL_PM_CANTIDAD`, `COL_PM_DINERO`, `COL_PM_TIPO`, `COL_PM_CERV`, `TIPO_CERVEZA`, `TIPOS_ALCOHOLICOS`, `ML_POR_PINTA` en `config.py`. Lista `ACCIONES` (lista de dicts) en `acciones.py`, usada por Task 6.

- [ ] **Step 1: Crear estructura de carpetas y `requirements.txt`**

```
Proyecto_Patagonia_Semestral/
  data/
  templates/
  static/
  tests/
```

`requirements.txt`:
```
Flask==3.0.3
google-cloud-bigquery==3.25.0
google-cloud-storage==2.18.0
pytest==8.3.2
```

- [ ] **Step 2: Crear `Procfile`**

```
web: gunicorn main:app
```

- [ ] **Step 3: Crear `config.py`**

```python
# config.py
# Constantes compartidas: proyecto BQ, bucket GCS, columnas de las vistas usadas.

PROJECT = "temple-bar-439715"
BUCKET = "temple-bar-dashboard-cache"
GCS_PATH = "patagonia_semestral/patagonia_data.json"

MARCA_VENTAS = "Patagonia"        # valor de Marca en vw_Ventas_Corporativo_Base
MARCA_PRODUCTOS = "PATAGONIA"     # valor de marca en vw_productos_maestro_clean (mayúsculas)

FECHA_DESDE_HIST = "2025-01-01"   # arranca en 2025 para poder calcular YoY del semestre 2026
SEMESTRE_DESDE = "2026-01-01"
SEMESTRE_HASTA = "2026-06-30"

# ── Columnas de vw_Ventas_Corporativo_Base ──────────────────────────────────
COL_ORDEN = "Orden"
COL_FECHA = "Fecha"
COL_MARCA = "Marca"
COL_LOCAL = "Local"
COL_TOTAL = "Total"

# ── Columnas de vw_productos_maestro_clean ──────────────────────────────────
COL_PM_LOCAL = "establecimiento"
COL_PM_MARCA = "marca"
COL_PM_PRODUCTO = "producto"
COL_PM_FECHA = "fecha"
COL_PM_CANTIDAD = "cantidad"
COL_PM_DINERO = "dinero"
COL_PM_TIPO = "tipo"
COL_PM_CERV = "cerveza_total"

TIPO_CERVEZA = "CERVEZA"
TIPOS_ALCOHOLICOS = ("CERVEZA", "TRAGOS", "VINO")

# Litros por pinta para estimar volumen de cerveza cuando cerveza_total es NULL
# pero el producto es identificable como cerveza por nombre (ver estimacion_pintas.py).
# Decisión de Darwin Salinas, 2026-07-29.
ML_POR_PINTA = 0.52
```

- [ ] **Step 4: Crear `acciones.py`**

```python
# acciones.py
# Config de las 6 acciones comerciales del semestre + Mundial (reutilizado de Proyecto_Mundial).
#
# Fechas marcadas con "TODO: fecha a confirmar con Darwin" son APROXIMACIONES
# PLACEHOLDER — no bloquean construir el resto del tablero, pero sí bloquean
# generar el dato final para la reunión. Ver spec, sección "Pendientes".
#
# tipo="uplift": se compara la ventana [desde,hasta] contra [ref_desde,ref_hasta]
#                (período de referencia sin la acción, mismo patrón que Proyecto_Mundial).
# tipo="evolucion": no hay período de referencia — se muestra la serie mensual
#                   interna del rango (Otoño y 8va Canilla/Isleña son rangos de
#                   3 meses, no hay una "semana sin otoño" con la que comparar).
# tipo="externo": el resultado ya está calculado en otro proyecto (Mundial) y se
#                 reutiliza tal cual, sin recalcular.

ACCIONES = [
    {
        "id": "carnaval",
        "nombre": "Carnaval",
        "tipo": "uplift",
        "desde": "2026-02-14",     # TODO: fecha a confirmar con Darwin
        "hasta": "2026-02-17",     # TODO: fecha a confirmar con Darwin
        "ref_desde": "2026-02-07",  # TODO: fecha a confirmar con Darwin
        "ref_hasta": "2026-02-10",  # TODO: fecha a confirmar con Darwin
    },
    {
        "id": "semana_hamburguesa",
        "nombre": "Semana de la hamburguesa",
        "tipo": "uplift",
        "desde": "2026-05-11",      # TODO: fecha a confirmar con Darwin
        "hasta": "2026-05-17",      # TODO: fecha a confirmar con Darwin
        "ref_desde": "2026-05-04",   # TODO: fecha a confirmar con Darwin
        "ref_hasta": "2026-05-10",   # TODO: fecha a confirmar con Darwin
    },
    {
        "id": "semana_cerveza",
        "nombre": "Semana de la cerveza",
        "tipo": "uplift",
        "desde": "2026-05-18",      # TODO: fecha a confirmar con Darwin
        "hasta": "2026-05-24",      # TODO: fecha a confirmar con Darwin
        "ref_desde": "2026-05-25",   # TODO: fecha a confirmar con Darwin
        "ref_hasta": "2026-05-31",   # TODO: fecha a confirmar con Darwin
    },
    {
        "id": "mundial",
        "nombre": "Mundial",
        "tipo": "externo",
        "desde": "2026-06-02",
        "hasta": "2026-07-19",
        "nota": "Datos reutilizados de Proyecto_Mundial (corte 2026-07-19, dato ya generado y cerrado). Ver ese tablero para el detalle completo por partido.",
    },
    {
        "id": "otono",
        "nombre": "Otoño",
        "tipo": "evolucion",
        "desde": "2026-03-01",
        "hasta": "2026-05-31",
    },
    {
        "id": "canilla_isla",
        "nombre": "8va Canilla / Isleña",
        "tipo": "evolucion",
        "desde": "2026-04-01",
        "hasta": "2026-06-30",
    },
]
```

- [ ] **Step 5: Crear `data/sellin_cerveza.csv` (vacío, con estructura)**

```
mes,litros_sellin
2026-01,
2026-02,
2026-03,
2026-04,
2026-05,
2026-06,
```

- [ ] **Step 6: Crear `data/reputology.csv` (vacío, con estructura)**

```
trimestre,refugio,rating,nps,cantidad_resenas,fuente
2026-Q1,TOTAL,,,,Reputology
2026-Q2,TOTAL,,,,Reputology
```

- [ ] **Step 7: Crear `.gitignore`**

```
__pycache__/
*.pyc
.env
temple-bar-*.json
```

- [ ] **Step 8: Verificar que los archivos importan sin error**

Run: `python -c "import config, acciones; print(len(acciones.ACCIONES))"` (desde `Proyecto_Patagonia_Semestral/`)
Expected: imprime `6` sin error.

- [ ] **Step 9: Commit**

```bash
git init
git add config.py acciones.py requirements.txt Procfile .gitignore data/
git commit -m "scaffold: config, acciones y CSVs manuales del tablero Patagonia semestral"
```

---

### Task 2: `calculos.py` — funciones puras de KPI (TDD)

**Files:**
- Create: `Proyecto_Patagonia_Semestral/calculos.py`
- Test: `Proyecto_Patagonia_Semestral/tests/test_calculos.py`

**Interfaces:**
- Produces: `calcular_aov(gmv, ordenes) -> float`, `calcular_litros_por_orden(litros_cerveza, ordenes) -> float`, `calcular_sot(unidades_cerveza, unidades_alcoholicas_total) -> float`, `calcular_yoy(valor_actual, valor_anterior) -> float | None`, `calcular_uplift(valor_accion, valor_referencia) -> float | None`, `es_combo(nombre_producto) -> bool`, `combo_incluye_cerveza(litros_cerveza_linea) -> bool`. Usadas por Task 6.

- [ ] **Step 1: Escribir los tests (fallando)**

```python
# tests/test_calculos.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculos import (
    calcular_aov, calcular_litros_por_orden, calcular_sot,
    calcular_yoy, calcular_uplift, es_combo, combo_incluye_cerveza,
)


def test_calcular_aov_normal():
    assert calcular_aov(gmv=100000.0, ordenes=200) == 500.0


def test_calcular_aov_cero_ordenes():
    assert calcular_aov(gmv=100000.0, ordenes=0) == 0.0


def test_calcular_litros_por_orden_normal():
    assert calcular_litros_por_orden(litros_cerveza=390.0, ordenes=200) == 1.95


def test_calcular_litros_por_orden_cero_ordenes():
    assert calcular_litros_por_orden(litros_cerveza=390.0, ordenes=0) == 0.0


def test_calcular_sot_normal():
    # 600 unidades cerveza sobre 1000 unidades alcohólicas totales = 60%
    assert calcular_sot(unidades_cerveza=600.0, unidades_alcoholicas_total=1000.0) == 0.6


def test_calcular_sot_sin_alcoholicas():
    assert calcular_sot(unidades_cerveza=0.0, unidades_alcoholicas_total=0.0) == 0.0


def test_calcular_yoy_crecimiento():
    # 120 vs 100 = +20%
    assert round(calcular_yoy(valor_actual=120.0, valor_anterior=100.0), 4) == 0.2


def test_calcular_yoy_caida():
    # 80 vs 100 = -20%
    assert round(calcular_yoy(valor_actual=80.0, valor_anterior=100.0), 4) == -0.2


def test_calcular_yoy_sin_dato_anterior():
    assert calcular_yoy(valor_actual=120.0, valor_anterior=0.0) is None


def test_calcular_uplift_positivo():
    assert round(calcular_uplift(valor_accion=150.0, valor_referencia=100.0), 4) == 0.5


def test_calcular_uplift_sin_referencia():
    assert calcular_uplift(valor_accion=150.0, valor_referencia=0.0) is None


def test_es_combo_detecta_combo():
    assert es_combo("COMBO CUMPLE 1") is True


def test_es_combo_detecta_promo():
    assert es_combo("PROMO FERNET") is True


def test_es_combo_case_insensitive():
    assert es_combo("combo cumple 4 (sin cerveza)") is True


def test_es_combo_producto_normal_no_es_combo():
    assert es_combo("PINTA REFILL") is False


def test_combo_incluye_cerveza_true():
    assert combo_incluye_cerveza(litros_cerveza_linea=0.473) is True


def test_combo_incluye_cerveza_false():
    assert combo_incluye_cerveza(litros_cerveza_linea=0.0) is False


def test_combo_incluye_cerveza_none_es_false():
    assert combo_incluye_cerveza(litros_cerveza_linea=None) is False
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `pytest tests/test_calculos.py -v` (desde `Proyecto_Patagonia_Semestral/`)
Expected: FAIL con `ModuleNotFoundError: No module named 'calculos'`.

- [ ] **Step 3: Implementar `calculos.py`**

```python
# calculos.py
# Funciones puras de cálculo de KPIs. Sin dependencias de BigQuery/Flask —
# reciben números ya agregados y devuelven el KPI calculado.


def calcular_aov(gmv: float, ordenes: int) -> float:
    """Ticket promedio (Average Order Value) = GMV / cantidad de órdenes."""
    if ordenes == 0:
        return 0.0
    return gmv / ordenes


def calcular_litros_por_orden(litros_cerveza: float, ordenes: int) -> float:
    """Litros de cerveza vendidos por orden, como ratio agregado del período
    (NO es un join a nivel de orden individual — ver spec: `id` de
    vw_productos_maestro_clean no coincide con `Orden`)."""
    if ordenes == 0:
        return 0.0
    return litros_cerveza / ordenes


def calcular_sot(unidades_cerveza: float, unidades_alcoholicas_total: float) -> float:
    """Share of Throat: proporción de unidades de cerveza sobre el total de
    unidades de bebidas alcohólicas (tipo IN ('CERVEZA','TRAGOS','VINO'))."""
    if unidades_alcoholicas_total == 0:
        return 0.0
    return unidades_cerveza / unidades_alcoholicas_total


def calcular_yoy(valor_actual: float, valor_anterior: float) -> float | None:
    """Crecimiento año contra año. None si no hay dato del año anterior
    (no confundir con 0% de crecimiento)."""
    if valor_anterior == 0:
        return None
    return (valor_actual - valor_anterior) / valor_anterior


def calcular_uplift(valor_accion: float, valor_referencia: float) -> float | None:
    """Uplift de una acción comercial vs. un período de referencia sin la acción.
    None si no hay dato de referencia."""
    if valor_referencia == 0:
        return None
    return (valor_accion - valor_referencia) / valor_referencia


def es_combo(nombre_producto: str) -> bool:
    """Un producto se considera combo/promo si su nombre contiene 'COMBO' o
    'PROMO' (case-insensitive) — decisión de Darwin, 2026-07-29."""
    n = nombre_producto.upper()
    return "COMBO" in n or "PROMO" in n


def combo_incluye_cerveza(litros_cerveza_linea: float | None) -> bool:
    """Un combo/promo 'incluye cerveza' si su línea tiene litros de cerveza > 0
    (el pipeline de BQ ya prorratea litros de cerveza dentro de líneas de combo)."""
    if litros_cerveza_linea is None:
        return False
    return litros_cerveza_linea > 0
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_calculos.py -v`
Expected: 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add calculos.py tests/test_calculos.py
git commit -m "feat: funciones puras de cálculo de KPIs (AOV, SOT, YoY, uplift, combos)"
```

---

### Task 3: `estimacion_pintas.py` — estimación de litros de cerveza por nombre de producto (TDD)

**Contexto (por qué existe este archivo):** se verificó con query real en BigQuery que ~110.000+ unidades de productos que son claramente cerveza por su nombre (`PINTA REFILL`, `PINTAN DOS PAGAS UNA`, `ECOVASO PINTA`, `DEGUSTACION CERVEZAS`, promos `NxM PINTAS`, y pintas incluidas dentro de combos de comida como `BURGER CLASICA PINTA` o `PIZZA 2 PINTAS`) tienen `cerveza_total` (litros) en NULL en BigQuery — quedarían afuera del KPI "litros de cerveza" si se usa la columna tal cual. Decisión de Darwin (2026-07-29): estimar esos litros por nombre de producto a razón de **520ml por pinta**, incluyendo las pintas que vienen dentro de combos de comida. Non-cerveza (gaseosas en lata, sidra "Isidra", tragos con gin/fernet/vermú/campari/vodka) deben excluirse aunque el nombre contenga coincidencias parciales.

**Files:**
- Create: `Proyecto_Patagonia_Semestral/estimacion_pintas.py`
- Test: `Proyecto_Patagonia_Semestral/tests/test_estimacion_pintas.py`

**Interfaces:**
- Consumes: `ML_POR_PINTA` de `config.py` (Task 1).
- Produces: `cantidad_pintas_por_unidad(nombre_producto: str) -> float`, `litros_cerveza_linea(producto: str, cantidad: float, cerveza_total_bq: float | None) -> float`. Usadas por Task 6.

- [ ] **Step 1: Escribir los tests (fallando)**

```python
# tests/test_estimacion_pintas.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estimacion_pintas import cantidad_pintas_por_unidad, litros_cerveza_linea


# ── Casos reales encontrados en BigQuery (vw_productos_maestro_clean, marca PATAGONIA) ──

def test_pinta_simple():
    assert cantidad_pintas_por_unidad("PINTA REFILL") == 1.0


def test_ecovaso_pinta():
    assert cantidad_pintas_por_unidad("ECOVASO   PINTA TRADICIONAL IGZ") == 1.0


def test_media_pinta():
    assert cantidad_pintas_por_unidad("SAND BONDIOLA   MEDIA PINTA") == 0.5


def test_dos_pintas():
    assert cantidad_pintas_por_unidad("PIZZA   2 PINTAS") == 2.0


def test_cuatro_pintas_en_tabla():
    assert cantidad_pintas_por_unidad("TABLA   4 PINTAS TRADICIONALES") == 4.0


def test_dos_medias_pintas():
    # "2 MEDIAS PINTAS" = 2 medias pintas = 1 pinta equivalente
    assert cantidad_pintas_por_unidad("PAPAS CON CHEDDAR PANCETA Y VERDEO   2 MEDIAS PINTAS") == 1.0


def test_promo_3x2_pintas():
    # "3X2 PINTAS": se sirven 3 pintas (paga 2)
    assert cantidad_pintas_por_unidad("3X2 PINTAS") == 3.0


def test_promo_2x1_pinta():
    # "2X1 PINTA TRADICIONAL": se sirven 2 pintas (paga 1)
    assert cantidad_pintas_por_unidad("2X1 PINTA TRADICIONAL") == 2.0


def test_promo_6x4_pintas():
    assert cantidad_pintas_por_unidad("6X4 PINTAS TRADICIONALES") == 6.0


def test_pintan_dos_pagas_una():
    assert cantidad_pintas_por_unidad("PINTAN DOS, PAGAS UNA (TRADICIONALES)") == 2.0


def test_degustacion_cervezas():
    assert cantidad_pintas_por_unidad("DEGUSTACION CERVEZAS") == 1.0


def test_recarga_ecovaso():
    assert cantidad_pintas_por_unidad("RECARGA ECOVASO TRADICIONAL") == 1.0


def test_chopp():
    assert cantidad_pintas_por_unidad("CHOPP") == 1.0


# ── Exclusiones: no es cerveza aunque contenga coincidencias parciales ──

def test_pepsi_lata_no_es_cerveza():
    assert cantidad_pintas_por_unidad("PEPSI LATA") == 0.0


def test_isidra_pinta_no_es_cerveza():
    # Isidra es sidra, no cerveza — aunque el nombre diga "PINTA"
    assert cantidad_pintas_por_unidad("ISIDRA PINTA") == 0.0


def test_gin_no_es_cerveza():
    assert cantidad_pintas_por_unidad("GIN GINKGO - GINKGO TONIC") == 0.0


def test_vodka_no_es_cerveza():
    assert cantidad_pintas_por_unidad("VODKA RED BULL") == 0.0


def test_producto_sin_relacion_a_cerveza():
    assert cantidad_pintas_por_unidad("CAFE EXPRESO") == 0.0


# ── litros_cerveza_linea: prioriza el dato de BQ si existe ──

def test_litros_usa_bq_si_no_es_none():
    assert litros_cerveza_linea("PINTA PATAGONIA LATA", cantidad=10, cerveza_total_bq=4.73) == 4.73


def test_litros_estima_si_bq_es_none():
    # 2 unidades de "PINTA REFILL", 1 pinta/unidad, 0.52L/pinta = 1.04L
    assert round(litros_cerveza_linea("PINTA REFILL", cantidad=2, cerveza_total_bq=None), 4) == 1.04


def test_litros_cero_si_no_es_cerveza_y_bq_none():
    assert litros_cerveza_linea("PEPSI LATA", cantidad=100, cerveza_total_bq=None) == 0.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `pytest tests/test_estimacion_pintas.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'estimacion_pintas'`.

- [ ] **Step 3: Implementar `estimacion_pintas.py`**

```python
# estimacion_pintas.py
# Estima litros de cerveza a partir del NOMBRE de producto, para líneas donde
# BigQuery no calculó `cerveza_total` (ver Task 3 del plan para el contexto
# completo del hallazgo). Solo se usa como fallback cuando cerveza_total es NULL.
#
# Alcance conocido (documentado, no resuelto en esta versión):
# - Growlers (recarga de birrera para llevar) se excluyen: su volumen real
#   (~1-2L) no es "una pinta" — no aparece en los patrones de abajo, así que
#   devuelven 0.0 y ese volumen queda fuera de la estimación.
# - "SAND BONDIOLA + BEBIDA O PINTA" (el cliente elige UNA de las dos opciones)
#   se asume que eligió la pinta — sobrestima levemente en el caso contrario.
# - "Degustación" (tasting) se asume 1 pinta completa aunque el pour real de
#   una degustación suele ser más chico — aproximación conservadora hacia arriba.

import re

MARCAS_NO_CERVEZA = (
    "PEPSI", "MIRINDA", "7 UP", "7UP", "PASO DE LOS TOROS", "ISIDRA",
    "GIN", "FERNET", "VERMU", "CAMPARI", "VODKA", "TRAGO", "JUGO",
    "CAFE", "AGUA", "H2O", "LIMONADA", "GASEOSA", "GROWLER",
)

_PATRON_NXM_PINTA = re.compile(r"(\d+)\s*X\s*\d+\s*(?:MEDIA[S]?\s+)?PINTA")
_PATRON_N_PINTAS = re.compile(r"(\d+)\s+(?:MEDIA[S]?\s+)?PINTAS?\b")
_PATRON_MEDIA_PINTA = re.compile(r"\bMEDIA\s+PINTAS?\b")
_PATRON_PINTA = re.compile(r"\bPINTAS?\b")
_PATRON_ECOVASO_RECARGA = re.compile(r"\bECOVASO\b|\bRECARGA\b")
_PATRON_DEGUSTACION = re.compile(r"\bDEGUSTACION\b")
_PATRON_PINTAN_DOS = re.compile(r"PINTAN\s+DOS.*PAGAS\s+UNA")
_PATRON_CHOPP = re.compile(r"\bCHOPP\b")


def cantidad_pintas_por_unidad(nombre_producto: str) -> float:
    """Cuántas 'pintas equivalentes' representa 1 unidad vendida de este
    producto, según patrones en su nombre. 0.0 si no es identificable como
    cerveza o pertenece a otra marca/bebida."""
    n = nombre_producto.upper()

    if any(marca in n for marca in MARCAS_NO_CERVEZA):
        return 0.0

    if _PATRON_PINTAN_DOS.search(n):
        return 2.0

    m = _PATRON_NXM_PINTA.search(n)
    if m:
        return float(m.group(1))  # "3X2 PINTAS" -> 3, "2X1 PINTA" -> 2, "6X4 PINTAS" -> 6

    m = _PATRON_N_PINTAS.search(n)
    if m:
        cantidad = float(m.group(1))
        if "MEDIA" in n:
            return cantidad * 0.5
        return cantidad

    if _PATRON_MEDIA_PINTA.search(n):
        return 0.5

    if _PATRON_PINTA.search(n):
        return 1.0

    if _PATRON_ECOVASO_RECARGA.search(n) or _PATRON_DEGUSTACION.search(n):
        return 1.0

    if _PATRON_CHOPP.search(n):
        return 1.0

    return 0.0


def litros_cerveza_linea(producto: str, cantidad: float, cerveza_total_bq: float | None) -> float:
    """Litros de cerveza de una línea de venta.
    Si BigQuery ya calculó cerveza_total (no None), se usa ese valor exacto.
    Si es None, se estima: cantidad_pintas_por_unidad(producto) * cantidad * ML_POR_PINTA."""
    from config import ML_POR_PINTA

    if cerveza_total_bq is not None:
        return float(cerveza_total_bq)

    pintas_por_unidad = cantidad_pintas_por_unidad(producto)
    if pintas_por_unidad == 0.0:
        return 0.0
    return pintas_por_unidad * cantidad * ML_POR_PINTA
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_estimacion_pintas.py -v`
Expected: 19 tests PASS.

- [ ] **Step 5: Verificar contra el listado real de productos (sanity check, no un test automatizado)**

Run (con acceso a BigQuery configurado):
```bash
python -c "
from google.cloud import bigquery
from estimacion_pintas import cantidad_pintas_por_unidad
bq = bigquery.Client(project='temple-bar-439715')
rows = bq.query('''
  SELECT producto, SUM(cantidad) AS unidades
  FROM \`temple-bar-439715.Corporativo.vw_productos_maestro_clean\`
  WHERE marca='PATAGONIA' AND fecha >= '2026-01-01' AND fecha <= '2026-06-30'
    AND cerveza_total IS NULL
  GROUP BY producto ORDER BY unidades DESC LIMIT 40
''').result()
for r in rows:
    print(f'{cantidad_pintas_por_unidad(r[\"producto\"]):.2f}  {r[\"unidades\"]:>10.0f}  {r[\"producto\"]}')
"
```
Expected: revisar visualmente que los primeros ~40 productos por volumen tengan un valor de pintas razonable (no 0.0 para cerveza real, no >0 para gaseosas/sidra/tragos). Si aparece algo mal clasificado, ajustar los patrones/exclusiones antes de continuar — este chequeo es más importante que los tests unitarios porque los datos reales son mucho más variados que los 19 casos de test.

- [ ] **Step 6: Commit**

```bash
git add estimacion_pintas.py tests/test_estimacion_pintas.py
git commit -m "feat: estimación de litros de cerveza por nombre de producto (fallback cuando BQ no calcula cerveza_total)"
```

---

### Task 4: `main.py` — Flask app

**Files:**
- Create: `Proyecto_Patagonia_Semestral/main.py`

**Interfaces:**
- Consumes: `config.BUCKET`, `config.GCS_PATH`, `config.PROJECT` (Task 1). Espera que `templates/patagonia_semestral.html` exista (Task 7-10) para que `/` no tire 500 — hasta entonces, correrlo solo prueba `/data` y `/refresh` contra un JSON de prueba.
- Produces: rutas `GET /`, `GET /data`, `GET /refresh`. Mismo patrón que `Proyecto_Mundial/main.py`.

- [ ] **Step 1: Implementar `main.py`**

```python
# main.py
# Flask app — sirve patagonia_semestral.html con patagonia_data.json cacheado.
# Carga el JSON desde GCS al arrancar y en GET /refresh. Mismo patrón que
# Proyecto_Mundial/main.py. Sin autenticación (decisión de Darwin, 2026-07-29).

import json
import os
from flask import Flask, render_template, jsonify
from google.cloud import storage

from config import PROJECT, BUCKET, GCS_PATH

app = Flask(__name__)

_cache = {"data": None}


def cargar_datos_gcs():
    gcs = storage.Client(project=PROJECT)
    bucket = gcs.bucket(BUCKET)
    blob = bucket.blob(GCS_PATH)
    raw = blob.download_as_text(encoding="utf-8")
    return json.loads(raw)


@app.before_request
def _init():
    if _cache["data"] is None:
        _cache["data"] = cargar_datos_gcs()


@app.route("/")
def index():
    return render_template("patagonia_semestral.html")


@app.route("/data")
def data():
    return jsonify(_cache["data"])


@app.route("/refresh")
def refresh():
    _cache["data"] = cargar_datos_gcs()
    return jsonify({"ok": True, "generado_en": _cache["data"].get("generado_en")})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
```

- [ ] **Step 2: Probar `/data` y `/refresh` contra un JSON de prueba (sin depender de GCS real todavía)**

```bash
python -c "
import main
main._cache['data'] = {'generado_en': 'test'}
client = main.app.test_client()
r = client.get('/data')
assert r.status_code == 200
assert r.get_json()['generado_en'] == 'test'
print('OK /data')
"
```
Expected: imprime `OK /data` sin error. (`/` fallará hasta que exista el template — es esperado en esta task, se corrige en Task 11).

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: Flask app standalone (patrón Proyecto_Mundial, sin auth)"
```

---

### Task 5: `bq_queries.py` — queries de BigQuery

**Files:**
- Create: `Proyecto_Patagonia_Semestral/bq_queries.py`

**Interfaces:**
- Consumes: constantes de `config.py` (Task 1) — `PROJECT`, `MARCA_VENTAS`, `MARCA_PRODUCTOS`, `FECHA_DESDE_HIST`, `SEMESTRE_HASTA`, `COL_*`.
- Produces: `QUERY_VENTAS` (str), `QUERY_PRODUCTOS` (str), `run_query(bq_client, sql, label) -> list[Row]`. Usadas por Task 6.

- [ ] **Step 1: Implementar `bq_queries.py`**

```python
# bq_queries.py
# Queries de BigQuery para el tablero Patagonia Semestral.
# Rango de fechas: desde FECHA_DESDE_HIST (2025-01-01, para poder calcular YoY)
# hasta SEMESTRE_HASTA (2026-06-30).

from config import (
    PROJECT, MARCA_VENTAS, MARCA_PRODUCTOS, FECHA_DESDE_HIST, SEMESTRE_HASTA,
    COL_ORDEN, COL_FECHA, COL_MARCA, COL_LOCAL, COL_TOTAL,
    COL_PM_LOCAL, COL_PM_MARCA, COL_PM_PRODUCTO, COL_PM_FECHA,
    COL_PM_CANTIDAD, COL_PM_DINERO, COL_PM_TIPO, COL_PM_CERV,
)

QUERY_VENTAS = f"""
SELECT
  v.{COL_ORDEN}  AS orden_id,
  CAST(v.{COL_FECHA} AS STRING) AS fecha,
  v.{COL_LOCAL}  AS local,
  COALESCE(v.{COL_TOTAL}, 0.0) AS total
FROM `{PROJECT}.Corporativo.vw_Ventas_Corporativo_Base` v
WHERE v.{COL_MARCA} = '{MARCA_VENTAS}'
  AND DATE(v.{COL_FECHA}) >= '{FECHA_DESDE_HIST}'
  AND DATE(v.{COL_FECHA}) <= '{SEMESTRE_HASTA}'
"""

QUERY_PRODUCTOS = f"""
SELECT
  CAST(p.{COL_PM_FECHA} AS STRING) AS fecha,
  p.{COL_PM_LOCAL}     AS local,
  p.{COL_PM_PRODUCTO}  AS producto,
  p.{COL_PM_TIPO}      AS tipo,
  COALESCE(p.{COL_PM_CANTIDAD}, 0) AS cantidad,
  COALESCE(p.{COL_PM_DINERO}, 0.0) AS dinero,
  p.{COL_PM_CERV}      AS cerveza_total_bq
FROM `{PROJECT}.Corporativo.vw_productos_maestro_clean` p
WHERE p.{COL_PM_MARCA} = '{MARCA_PRODUCTOS}'
  AND DATE(p.{COL_PM_FECHA}) >= '{FECHA_DESDE_HIST}'
  AND DATE(p.{COL_PM_FECHA}) <= '{SEMESTRE_HASTA}'
"""


def run_query(bq_client, sql, label):
    print(f"Query {label}...")
    rows = list(bq_client.query(sql).result())
    print(f"  -> {len(rows)} filas")
    return rows
```

- [ ] **Step 2: Probar contra BigQuery real**

```bash
python -c "
from google.cloud import bigquery
from bq_queries import QUERY_VENTAS, QUERY_PRODUCTOS, run_query
from config import PROJECT
bq = bigquery.Client(project=PROJECT)
ventas = run_query(bq, QUERY_VENTAS, 'ventas')
productos = run_query(bq, QUERY_PRODUCTOS, 'productos')
assert len(ventas) > 0, 'query de ventas devolvió 0 filas'
assert len(productos) > 0, 'query de productos devolvió 0 filas'
print('OK — ventas:', len(ventas), 'productos:', len(productos))
"
```
Expected: imprime `OK — ventas: <N> productos: <M>` con N y M en el orden de decenas/cientos de miles (18 meses de datos de Patagonia).

- [ ] **Step 3: Commit**

```bash
git add bq_queries.py
git commit -m "feat: queries BigQuery de ventas y productos para Patagonia (2025-01 a 2026-06)"
```

---

## OLA 2 (depende de toda la OLA 1 — una sola tarea)

### Task 6: `generar_patagonia_semestral.py` — orquestador y construcción del JSON

**Files:**
- Create: `Proyecto_Patagonia_Semestral/generar_patagonia_semestral.py`

**Interfaces:**
- Consumes: `config.*` (Task 1), `acciones.ACCIONES` (Task 1), `calculos.*` (Task 2), `estimacion_pintas.litros_cerveza_linea` (Task 3), `bq_queries.QUERY_VENTAS/QUERY_PRODUCTOS/run_query` (Task 5).
- Produces: función `construir_json(rows_ventas, rows_productos, sellin_rows, reputology_rows) -> dict` (testeable sin BigQuery/GCS reales) y `main()` que orquesta todo y sube a GCS. El dict que devuelve `construir_json` es el **contrato con el frontend** (Tasks 7-10): claves de primer nivel `generado_en`, `periodo`, `resumen`, `mensual`, `sellin_sellout`, `refugios`, `acciones`, `combos`, `reputology`, `pendientes`.

- [ ] **Step 1: Escribir un test de integración liviano para `construir_json` con filas sintéticas**

```python
# tests/test_generar_patagonia_semestral.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generar_patagonia_semestral import construir_json


def _row(**kwargs):
    """Simula un google.cloud.bigquery.table.Row como dict (soporta row['campo'])."""
    return kwargs


def test_construir_json_estructura_basica():
    rows_ventas = [
        _row(orden_id="1", fecha="2026-01-15", local="CALAFATE", total=1000.0),
        _row(orden_id="2", fecha="2026-01-16", local="CALAFATE", total=2000.0),
        _row(orden_id="3", fecha="2025-01-15", local="CALAFATE", total=800.0),
    ]
    rows_productos = [
        _row(fecha="2026-01-15", local="CALAFATE", producto="PINTA PATAGONIA", tipo="CERVEZA",
             cantidad=2, dinero=1000.0, cerveza_total_bq=0.946),
        _row(fecha="2026-01-16", local="CALAFATE", producto="PINTA REFILL", tipo=None,
             cantidad=1, dinero=500.0, cerveza_total_bq=None),
        _row(fecha="2026-01-16", local="CALAFATE", producto="COMBO CUMPLE 1", tipo=None,
             cantidad=1, dinero=1500.0, cerveza_total_bq=0.473),
    ]
    sellin_rows = [{"mes": "2026-01", "litros_sellin": "500"}]
    reputology_rows = [{"trimestre": "2026-Q1", "refugio": "TOTAL", "rating": "4.5", "nps": "60", "cantidad_resenas": "120", "fuente": "Reputology"}]

    resultado = construir_json(rows_ventas, rows_productos, sellin_rows, reputology_rows)

    assert set(resultado.keys()) >= {
        "generado_en", "periodo", "resumen", "mensual", "sellin_sellout",
        "refugios", "acciones", "combos", "reputology", "pendientes",
    }
    assert resultado["resumen"]["gmv"] == 3000.0  # solo órdenes 2026
    assert resultado["resumen"]["ordenes"] == 2
    assert len(resultado["mensual"]) >= 1
    assert resultado["refugios"][0]["local"] == "CALAFATE"
    assert len(resultado["combos"]) == 1
    assert resultado["combos"][0]["nombre"] == "COMBO CUMPLE 1"
    assert resultado["combos"][0]["incluye_cerveza"] is True
    assert resultado["reputology"]["total"][0]["rating"] == 4.5
    assert isinstance(resultado["pendientes"], list) and len(resultado["pendientes"]) > 0
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/test_generar_patagonia_semestral.py -v`
Expected: FAIL con `ModuleNotFoundError` (todavía no existe `generar_patagonia_semestral.py`).

- [ ] **Step 3: Implementar `generar_patagonia_semestral.py`**

```python
# generar_patagonia_semestral.py
# Uso: python -X utf8 generar_patagonia_semestral.py
# Requiere GOOGLE_APPLICATION_CREDENTIALS apuntando al SA de temple-bar-439715.
#
# Orquesta: BQ (ventas + productos) + CSV manuales (sellin, reputology) +
# acciones.py -> construye patagonia_data.json -> sube a GCS.

import csv
import json
from collections import defaultdict
from datetime import datetime, date, timedelta

from google.cloud import bigquery, storage

from config import PROJECT, BUCKET, GCS_PATH, SEMESTRE_DESDE, SEMESTRE_HASTA, TIPO_CERVEZA, TIPOS_ALCOHOLICOS
from acciones import ACCIONES
from calculos import (
    calcular_aov, calcular_litros_por_orden, calcular_sot,
    calcular_yoy, calcular_uplift, es_combo, combo_incluye_cerveza,
)
from estimacion_pintas import litros_cerveza_linea
from bq_queries import QUERY_VENTAS, QUERY_PRODUCTOS, run_query


def _mes(fecha_str):
    return fecha_str[:7]  # "2026-01-15" -> "2026-01"


def _es_semestre_2026(fecha_str):
    return SEMESTRE_DESDE <= fecha_str[:10] <= SEMESTRE_HASTA


def _mes_anterior_1anio(mes_str):
    """'2026-03' -> '2025-03'"""
    anio, mes = mes_str.split("-")
    return f"{int(anio) - 1}-{mes}"


def leer_csv_manual(path):
    """Lee un CSV manual (sellin o reputology) devolviendo lista de dicts.
    Si el archivo no existe o está vacío de datos, devuelve lista vacía —
    no debe bloquear la generación del resto del tablero."""
    try:
        with open(path, encoding="utf-8") as f:
            return [row for row in csv.DictReader(f)]
    except FileNotFoundError:
        return []


def _agregar_ventas_por_mes_y_local(rows_ventas):
    """Devuelve (por_mes: {mes: {gmv, ordenes}}, por_local: {local: {gmv, ordenes}})."""
    por_mes = defaultdict(lambda: {"gmv": 0.0, "ordenes": 0})
    por_local = defaultdict(lambda: {"gmv": 0.0, "ordenes": 0})
    for r in rows_ventas:
        mes = _mes(r["fecha"])
        por_mes[mes]["gmv"] += float(r["total"])
        por_mes[mes]["ordenes"] += 1
        if _es_semestre_2026(r["fecha"]):
            por_local[r["local"]]["gmv"] += float(r["total"])
            por_local[r["local"]]["ordenes"] += 1
    return por_mes, por_local


def _agregar_productos(rows_productos):
    """Devuelve (por_mes, por_local, combos) agregando litros de cerveza (con
    estimación por nombre cuando BQ no la calculó), unidades de cerveza y
    unidades alcohólicas totales."""
    por_mes = defaultdict(lambda: {"litros_cerveza": 0.0, "unid_cerveza": 0.0, "unid_alcoholicas": 0.0})
    por_local = defaultdict(lambda: {"litros_cerveza": 0.0})
    combos_acc = defaultdict(lambda: {"unidades": 0.0, "facturacion": 0.0, "locales": set(), "incluye_cerveza": False})

    for r in rows_productos:
        litros = litros_cerveza_linea(r["producto"], r["cantidad"], r["cerveza_total_bq"])
        mes = _mes(r["fecha"])
        por_mes[mes]["litros_cerveza"] += litros

        tipo = r["tipo"]
        if tipo == TIPO_CERVEZA:
            por_mes[mes]["unid_cerveza"] += float(r["cantidad"])
        if tipo in TIPOS_ALCOHOLICOS:
            por_mes[mes]["unid_alcoholicas"] += float(r["cantidad"])

        if _es_semestre_2026(r["fecha"]):
            por_local[r["local"]]["litros_cerveza"] += litros

            if es_combo(r["producto"]):
                c = combos_acc[r["producto"]]
                c["unidades"] += float(r["cantidad"])
                c["facturacion"] += float(r["dinero"])
                c["locales"].add(r["local"])
                if combo_incluye_cerveza(litros):
                    c["incluye_cerveza"] = True

    combos = [
        {
            "nombre": nombre,
            "incluye_cerveza": datos["incluye_cerveza"],
            "unidades": datos["unidades"],
            "facturacion": datos["facturacion"],
            "locales": len(datos["locales"]),
        }
        for nombre, datos in combos_acc.items()
    ]
    combos.sort(key=lambda c: c["facturacion"], reverse=True)

    return por_mes, por_local, combos


def _construir_resumen_y_mensual(ventas_mes, productos_mes):
    meses_semestre = sorted(m for m in ventas_mes if _es_semestre_2026(m + "-01"))
    mensual = []
    tot_gmv = tot_ordenes = tot_litros = tot_unid_cerv = tot_unid_alc = 0.0

    for mes in meses_semestre:
        gmv = ventas_mes[mes]["gmv"]
        ordenes = ventas_mes[mes]["ordenes"]
        litros = productos_mes.get(mes, {}).get("litros_cerveza", 0.0)
        unid_cerv = productos_mes.get(mes, {}).get("unid_cerveza", 0.0)
        unid_alc = productos_mes.get(mes, {}).get("unid_alcoholicas", 0.0)

        mes_ant = _mes_anterior_1anio(mes)
        gmv_ant = ventas_mes.get(mes_ant, {}).get("gmv", 0.0)
        ordenes_ant = ventas_mes.get(mes_ant, {}).get("ordenes", 0)
        litros_ant = productos_mes.get(mes_ant, {}).get("litros_cerveza", 0.0)

        mensual.append({
            "mes": mes,
            "gmv": gmv, "ordenes": ordenes,
            "aov": calcular_aov(gmv, ordenes),
            "litros_cerveza": litros,
            "litros_por_orden": calcular_litros_por_orden(litros, ordenes),
            "sot_cerveza": calcular_sot(unid_cerv, unid_alc),
            "yoy_gmv": calcular_yoy(gmv, gmv_ant),
            "yoy_ordenes": calcular_yoy(ordenes, ordenes_ant),
            "yoy_litros_cerveza": calcular_yoy(litros, litros_ant),
        })

        tot_gmv += gmv; tot_ordenes += ordenes; tot_litros += litros
        tot_unid_cerv += unid_cerv; tot_unid_alc += unid_alc

    resumen = {
        "gmv": tot_gmv, "ordenes": tot_ordenes,
        "aov": calcular_aov(tot_gmv, tot_ordenes),
        "litros_cerveza": tot_litros,
        "litros_por_orden": calcular_litros_por_orden(tot_litros, tot_ordenes),
        "sot_cerveza": calcular_sot(tot_unid_cerv, tot_unid_alc),
    }
    return resumen, mensual


def _construir_sellin_sellout(mensual, sellin_rows):
    sellin_por_mes = {r["mes"]: r["litros_sellin"] for r in sellin_rows if r.get("litros_sellin")}
    salida = []
    for m in mensual:
        sellin_raw = sellin_por_mes.get(m["mes"])
        salida.append({
            "mes": m["mes"],
            "litros_sellin": float(sellin_raw) if sellin_raw else None,
            "litros_sellout": m["litros_cerveza"],
        })
    return salida


def _construir_refugios(ventas_local, productos_local):
    refugios = []
    for local, v in ventas_local.items():
        refugios.append({
            "local": local,
            "gmv": v["gmv"],
            "ordenes": v["ordenes"],
            "litros_cerveza": productos_local.get(local, {}).get("litros_cerveza", 0.0),
        })
    refugios.sort(key=lambda r: r["gmv"], reverse=True)
    return refugios


def _totales_ventana(rows_ventas, rows_productos, desde, hasta):
    gmv = ordenes = litros = 0.0
    for r in rows_ventas:
        if desde <= r["fecha"][:10] <= hasta:
            gmv += float(r["total"]); ordenes += 1
    for r in rows_productos:
        if desde <= r["fecha"][:10] <= hasta:
            litros += litros_cerveza_linea(r["producto"], r["cantidad"], r["cerveza_total_bq"])
    return gmv, ordenes, litros


def _construir_acciones(rows_ventas, rows_productos):
    resultado = []
    for accion in ACCIONES:
        if accion["tipo"] == "externo":
            resultado.append({**accion})
            continue

        gmv, ordenes, litros = _totales_ventana(rows_ventas, rows_productos, accion["desde"], accion["hasta"])

        if accion["tipo"] == "uplift":
            gmv_ref, ordenes_ref, litros_ref = _totales_ventana(
                rows_ventas, rows_productos, accion["ref_desde"], accion["ref_hasta"])
            resultado.append({
                **accion,
                "gmv": gmv, "ordenes": ordenes, "litros_cerveza": litros,
                "gmv_ref": gmv_ref, "ordenes_ref": ordenes_ref, "litros_cerveza_ref": litros_ref,
                "uplift_gmv": calcular_uplift(gmv, gmv_ref),
                "uplift_ordenes": calcular_uplift(ordenes, ordenes_ref),
                "uplift_litros_cerveza": calcular_uplift(litros, litros_ref),
            })
        else:  # evolucion
            desde = date.fromisoformat(accion["desde"])
            hasta = date.fromisoformat(accion["hasta"])
            serie = []
            cursor = desde.replace(day=1)
            while cursor <= hasta:
                sig_mes = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
                mes_desde = max(cursor, desde).isoformat()
                mes_hasta = min(sig_mes - timedelta(days=1), hasta).isoformat()
                g, o, l = _totales_ventana(rows_ventas, rows_productos, mes_desde, mes_hasta)
                serie.append({"mes": cursor.strftime("%Y-%m"), "gmv": g, "ordenes": o, "litros_cerveza": l})
                cursor = sig_mes
            resultado.append({**accion, "gmv": gmv, "ordenes": ordenes, "litros_cerveza": litros, "serie_mensual": serie})

    return resultado


def _construir_reputology(reputology_rows):
    trimestres = sorted({r["trimestre"] for r in reputology_rows}) or ["2026-Q1", "2026-Q2"]
    total = []
    por_refugio = defaultdict(list)
    for r in reputology_rows:
        fila = {
            "trimestre": r["trimestre"],
            "rating": float(r["rating"]) if r.get("rating") else None,
            "nps": float(r["nps"]) if r.get("nps") else None,
            "cantidad_resenas": int(r["cantidad_resenas"]) if r.get("cantidad_resenas") else None,
        }
        if r.get("refugio", "TOTAL") == "TOTAL":
            total.append(fila)
        else:
            por_refugio[r["refugio"]].append(fila)

    if not total:
        total = [{"trimestre": t, "rating": None, "nps": None, "cantidad_resenas": None} for t in trimestres]

    return {"trimestres": trimestres, "total": total, "por_refugio": dict(por_refugio)}


def construir_json(rows_ventas, rows_productos, sellin_rows, reputology_rows):
    ventas_mes, ventas_local = _agregar_ventas_por_mes_y_local(rows_ventas)
    productos_mes, productos_local, combos = _agregar_productos(rows_productos)

    resumen, mensual = _construir_resumen_y_mensual(ventas_mes, productos_mes)

    pendientes = []
    if not any(r.get("litros_sellin") for r in sellin_rows):
        pendientes.append("data/sellin_cerveza.csv está vacío — falta que Agus mande los litros mensuales.")
    if not any(r.get("rating") for r in reputology_rows):
        pendientes.append("data/reputology.csv está vacío — falta exportar rating/NPS/reseñas de la plataforma Reputology.")
    pendientes.append("Fechas de las 6 acciones son aproximaciones placeholder — confirmar con Darwin antes de la reunión.")

    return {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "periodo": {"desde": SEMESTRE_DESDE, "hasta": SEMESTRE_HASTA},
        "resumen": resumen,
        "mensual": mensual,
        "sellin_sellout": _construir_sellin_sellout(mensual, sellin_rows),
        "refugios": _construir_refugios(ventas_local, productos_local),
        "acciones": _construir_acciones(rows_ventas, rows_productos),
        "combos": combos,
        "reputology": _construir_reputology(reputology_rows),
        "pendientes": pendientes,
    }


def subir_a_gcs(data_dict):
    contenido = json.dumps(data_dict, ensure_ascii=False)
    if len(contenido) < 1024:
        raise RuntimeError("JSON generado sospechosamente chico (<1KB) — abortando upload.")

    gcs = storage.Client(project=PROJECT)
    bucket = gcs.bucket(BUCKET)
    blob = bucket.blob(GCS_PATH)
    blob.upload_from_string(contenido, content_type="application/json")
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    blob.reload()
    if blob.cache_control != "no-cache, no-store, must-revalidate":
        print("WARNING: cache_control no se aplicó correctamente en GCS.")
    print(f"Subido a gs://{BUCKET}/{GCS_PATH} ({len(contenido)} bytes)")


def main():
    bq = bigquery.Client(project=PROJECT)
    rows_ventas = run_query(bq, QUERY_VENTAS, "ventas")
    rows_productos = run_query(bq, QUERY_PRODUCTOS, "productos")

    if len(rows_ventas) < 100:
        raise RuntimeError(f"Solo {len(rows_ventas)} filas de ventas — abortando, parece un error de query.")

    sellin_rows = leer_csv_manual("data/sellin_cerveza.csv")
    reputology_rows = leer_csv_manual("data/reputology.csv")

    data_dict = construir_json(rows_ventas, rows_productos, sellin_rows, reputology_rows)
    subir_a_gcs(data_dict)

    if data_dict["pendientes"]:
        print("\nPendientes antes de la reunión:")
        for p in data_dict["pendientes"]:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/test_generar_patagonia_semestral.py -v`
Expected: PASS.

- [ ] **Step 5: Correr el generador completo contra BigQuery y GCS reales**

Run: `python -X utf8 generar_patagonia_semestral.py`
Expected: imprime conteo de filas de ventas/productos, sube el JSON a GCS, y lista los 3 pendientes conocidos (CSVs vacíos + fechas de acciones placeholder). Si tira `RuntimeError` de "menos de 100 filas", revisar credenciales/query antes de continuar.

- [ ] **Step 6: Commit**

```bash
git add generar_patagonia_semestral.py tests/test_generar_patagonia_semestral.py
git commit -m "feat: generador orquestador — BQ + CSVs manuales + acciones -> JSON en GCS"
```

---

## OLA 3 (secuencial — las 4 tareas modifican el MISMO archivo `templates/patagonia_semestral.html`; ejecutar los agentes uno detrás del otro, nunca en paralelo, para evitar condiciones de carrera Read-Edit sobre el mismo archivo)

### Task 7: Template — shell, CSS, nav de tabs, Tab 1 (Resumen) y Tab 2 (Evolución mensual)

**Files:**
- Create: `Proyecto_Patagonia_Semestral/templates/patagonia_semestral.html`
- Copy: `Proyecto_Mundial/static/style.css` → `Proyecto_Patagonia_Semestral/static/style.css` (reusar tal cual, mismo tema oscuro Temple Bar)
- Copy: `Proyecto_Mundial/static/fonts/` → `Proyecto_Patagonia_Semestral/static/fonts/`
- Copy: `Proyecto_Mundial/static/logo-temple-white.png` → `Proyecto_Patagonia_Semestral/static/logo-temple-white.png`

**Interfaces:**
- Consumes: JSON de `GET /data` con la forma producida por `construir_json` (Task 6): `resumen.{gmv,ordenes,aov,litros_cerveza,litros_por_orden,sot_cerveza}`, `mensual[]`.
- Produces: función JS global `mostrarTab(id)` (usada por las Tasks 8-10 para el nav), variable global `DATOS` (el JSON completo, cargado una vez al iniciar).

- [ ] **Step 1: Copiar assets estáticos**

```bash
cp ../Proyecto_Mundial/static/style.css static/style.css
cp -r ../Proyecto_Mundial/static/fonts static/fonts
cp ../Proyecto_Mundial/static/logo-temple-white.png static/logo-temple-white.png
```

- [ ] **Step 2: Crear el shell del template con nav de 7 tabs + CSS de tabs + Tab 1 y Tab 2**

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Patagonia — Resultados Semestre 1 2026</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <style>
    .pat-header {
      background: var(--temple-slate, #323E48);
      padding: 18px 32px; display: flex; align-items: center; gap: 18px;
    }
    .pat-header img { height: 40px; }
    .pat-header h1 {
      color: #fff; font-family: 'Knockout 71', sans-serif;
      font-size: 1.8rem; letter-spacing: 1px; margin: 0;
    }
    .tabs-nav {
      position: sticky; top: 0; z-index: 100;
      background: var(--temple-slate, #323E48);
      padding: 0 32px; display: flex; gap: 4px; flex-wrap: wrap;
      border-bottom: 2px solid var(--temple-pink, #E83E6C);
    }
    .tab-btn {
      background: transparent; color: #ccc; border: none;
      padding: 12px 16px; font-size: .85rem; cursor: pointer;
      border-bottom: 3px solid transparent;
    }
    .tab-btn.activo { color: #fff; border-bottom-color: var(--temple-pink, #E83E6C); font-weight: 600; }
    .contenido { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }
    .tab-panel { display: none; }
    .tab-panel.activo { display: block; }
    .kpi-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 28px; }
    .kpi-card {
      flex: 1; min-width: 180px; background: #1e272e; border-radius: 8px;
      padding: 18px 22px; border-left: 4px solid var(--temple-pink, #E83E6C);
    }
    .kpi-label { font-size: .72rem; text-transform: uppercase; color: #aaa; letter-spacing: 1px; }
    .kpi-value { font-size: 1.5rem; font-weight: 700; color: #fff; margin: 4px 0; overflow-wrap: anywhere; }
    .kpi-delta { font-size: .8rem; font-weight: 600; }
    .kpi-delta.verde { color: #2ecc71; }
    .kpi-delta.rojo { color: #e74c3c; }
    .kpi-delta.neutro { color: #aaa; }
    .grafico-card { background: #1e272e; border-radius: 8px; padding: 18px; margin-bottom: 24px; }
    .grafico-card h3 { font-size: .8rem; text-transform: uppercase; color: #aaa; letter-spacing: 1px; margin: 0 0 14px; }
    .grafico-card canvas { max-height: 320px; }
    .tabla-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    th { background: #252f38; color: #aaa; text-align: left; padding: 9px 12px; font-size: .72rem; text-transform: uppercase; }
    td { padding: 8px 12px; border-bottom: 1px solid #2a3540; color: #ddd; }
    .pendientes-banner {
      background: #3a2f1e; border-left: 4px solid #e6a23c; color: #f0d9a8;
      padding: 12px 16px; margin-bottom: 20px; font-size: .82rem; border-radius: 4px;
    }
  </style>
</head>
<body>
  <div class="pat-header">
    <img src="/static/logo-temple-white.png" alt="Temple Bar">
    <h1>Patagonia — Resultados Semestre 1 2026</h1>
  </div>

  <nav class="tabs-nav" id="tabsNav">
    <button class="tab-btn" data-tab="resumen">Resumen</button>
    <button class="tab-btn" data-tab="evolucion">Evolución mensual</button>
    <button class="tab-btn" data-tab="sellin">Sellin vs Sellout</button>
    <button class="tab-btn" data-tab="refugios">Ranking Refugios</button>
    <button class="tab-btn" data-tab="acciones">Acciones</button>
    <button class="tab-btn" data-tab="combos">Combos</button>
    <button class="tab-btn" data-tab="reputology">Reputology</button>
  </nav>

  <div class="contenido">
    <div id="pendientesBanner" class="pendientes-banner" style="display:none"></div>

    <section class="tab-panel" id="tab-resumen">
      <div class="kpi-row" id="kpiRowResumen"></div>
    </section>

    <section class="tab-panel" id="tab-evolucion">
      <div class="grafico-card"><h3>GMV mensual (2026 vs 2025)</h3><canvas id="chartGmvMensual"></canvas></div>
      <div class="grafico-card"><h3>Litros de cerveza mensual (2026 vs 2025)</h3><canvas id="chartLitrosMensual"></canvas></div>
      <div class="grafico-card"><h3>Órdenes mensuales (2026 vs 2025)</h3><canvas id="chartOrdenesMensual"></canvas></div>
    </section>

    <section class="tab-panel" id="tab-sellin"></section>
    <section class="tab-panel" id="tab-refugios"></section>
    <section class="tab-panel" id="tab-acciones"></section>
    <section class="tab-panel" id="tab-combos"></section>
    <section class="tab-panel" id="tab-reputology"></section>
  </div>

  <script>
    let DATOS = null;

    function fmtMoneda(v) {
      return '$' + Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits: 0});
    }
    function fmtLitros(v) {
      return Number(v || 0).toLocaleString('es-AR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + ' L';
    }
    function fmtPct(v) {
      if (v === null || v === undefined) return 'sin dato';
      return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
    }
    function claseDelta(v) {
      if (v === null || v === undefined) return 'neutro';
      return v >= 0 ? 'verde' : 'rojo';
    }

    function mostrarTab(id) {
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('activo'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('activo'));
      document.getElementById('tab-' + id).classList.add('activo');
      document.querySelector('.tab-btn[data-tab="' + id + '"]').classList.add('activo');
    }

    function renderPendientes() {
      const banner = document.getElementById('pendientesBanner');
      if (DATOS.pendientes && DATOS.pendientes.length) {
        banner.style.display = 'block';
        banner.innerHTML = '<strong>Pendientes:</strong> ' + DATOS.pendientes.join(' · ');
      }
    }

    function renderResumen() {
      const r = DATOS.resumen;
      const cards = [
        ['GMV', fmtMoneda(r.gmv)],
        ['Órdenes', r.ordenes.toLocaleString('es-AR')],
        ['AOV', fmtMoneda(r.aov)],
        ['Litros de cerveza', fmtLitros(r.litros_cerveza)],
        ['Litros por orden', r.litros_por_orden.toFixed(2) + ' L'],
        ['SOT cerveza', (r.sot_cerveza * 100).toFixed(1) + '%'],
      ];
      document.getElementById('kpiRowResumen').innerHTML = cards.map(([label, valor]) =>
        `<div class="kpi-card"><div class="kpi-label">${label}</div><div class="kpi-value">${valor}</div></div>`
      ).join('');
    }

    function renderEvolucionMensual() {
      const m = DATOS.mensual;
      const labels = m.map(x => x.mes);
      new Chart(document.getElementById('chartGmvMensual'), {
        type: 'bar',
        data: { labels, datasets: [{ label: 'GMV 2026', data: m.map(x => x.gmv), backgroundColor: '#E83E6C' }] },
      });
      new Chart(document.getElementById('chartLitrosMensual'), {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Litros cerveza 2026', data: m.map(x => x.litros_cerveza), backgroundColor: '#58a6ff' }] },
      });
      new Chart(document.getElementById('chartOrdenesMensual'), {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Órdenes 2026', data: m.map(x => x.ordenes), backgroundColor: '#6ee7b7' }] },
      });
    }

    fetch('/data').then(r => r.json()).then(datos => {
      DATOS = datos;
      renderPendientes();
      renderResumen();
      renderEvolucionMensual();
      // renderSellin/renderRefugios/renderAcciones/renderCombos/renderReputology
      // se agregan en las siguientes tareas del plan (Tasks 8-10) y se llaman
      // desde este mismo callback.
      mostrarTab('resumen');
    });

    document.getElementById('tabsNav').addEventListener('click', (e) => {
      if (e.target.matches('.tab-btn')) mostrarTab(e.target.dataset.tab);
    });
  </script>
</body>
</html>
```

- [ ] **Step 3: Verificar que el HTML es válido y las tabs cambian**

Con `main.py` corriendo localmente (`python main.py`, requiere el JSON ya en GCS de Task 6) y abriendo `http://localhost:8080/` en el navegador: confirmar que carga la tab "Resumen" con 6 tarjetas de KPI con valores reales (no vacíos ni `NaN`), y que hacer click en "Evolución mensual" muestra 3 gráficos de barras con datos.

- [ ] **Step 4: Commit**

```bash
git add templates/patagonia_semestral.html static/
git commit -m "feat: shell del tablero, nav de 7 tabs, Tab Resumen y Tab Evolución mensual"
```

---

### Task 8: Template — Tab 3 (Sellin vs Sellout) y Tab 4 (Ranking Refugios)

**Files:**
- Modify: `Proyecto_Patagonia_Semestral/templates/patagonia_semestral.html` (mismo archivo que Task 7 — ejecutar DESPUÉS de que Task 7 esté commiteada)

**Interfaces:**
- Consumes: `DATOS.sellin_sellout[]` (`{mes, litros_sellin, litros_sellout}`), `DATOS.refugios[]` (`{local, gmv, ordenes, litros_cerveza}`), funciones `fmtMoneda`/`fmtLitros`/`mostrarTab` ya definidas en Task 7.
- Produces: funciones `renderSellin()`, `renderRefugios()`, llamadas a `renderSellin()` y `renderRefugios()` agregadas al callback de `fetch('/data')`.

- [ ] **Step 1: Agregar el contenido de la Tab 3 dentro de `<section class="tab-panel" id="tab-sellin">`**

Reemplazar `<section class="tab-panel" id="tab-sellin"></section>` por:
```html
<section class="tab-panel" id="tab-sellin">
  <div class="grafico-card"><h3>Sellin vs. Sellout de cerveza (litros, mensual)</h3><canvas id="chartSellin"></canvas></div>
  <div class="tabla-wrap">
    <table id="tablaSellin"><thead><tr><th>Mes</th><th>Litros Sellin</th><th>Litros Sellout</th><th>Diferencia</th></tr></thead><tbody></tbody></table>
  </div>
</section>
```

- [ ] **Step 2: Agregar el contenido de la Tab 4 dentro de `<section class="tab-panel" id="tab-refugios">`**

Reemplazar `<section class="tab-panel" id="tab-refugios"></section>` por:
```html
<section class="tab-panel" id="tab-refugios">
  <div class="tabla-wrap">
    <table id="tablaRefugios">
      <thead><tr>
        <th>#</th><th>Refugio</th>
        <th style="cursor:pointer" onclick="ordenarRefugios('gmv')">GMV ▾</th>
        <th style="cursor:pointer" onclick="ordenarRefugios('litros_cerveza')">Litros cerveza</th>
        <th style="cursor:pointer" onclick="ordenarRefugios('ordenes')">Órdenes</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</section>
```

- [ ] **Step 3: Agregar las funciones JS antes del `fetch('/data')` (reemplazar el comentario placeholder de Task 7)**

```javascript
function renderSellin() {
  const s = DATOS.sellin_sellout;
  new Chart(document.getElementById('chartSellin'), {
    type: 'line',
    data: {
      labels: s.map(x => x.mes),
      datasets: [
        { label: 'Sellin', data: s.map(x => x.litros_sellin), borderColor: '#E83E6C', spanGaps: true },
        { label: 'Sellout', data: s.map(x => x.litros_sellout), borderColor: '#58a6ff' },
      ],
    },
  });
  const tbody = document.querySelector('#tablaSellin tbody');
  tbody.innerHTML = s.map(x => {
    const diff = (x.litros_sellin !== null) ? (x.litros_sellin - x.litros_sellout) : null;
    return `<tr><td>${x.mes}</td><td>${x.litros_sellin !== null ? fmtLitros(x.litros_sellin) : 'sin dato'}</td>` +
           `<td>${fmtLitros(x.litros_sellout)}</td><td>${diff !== null ? fmtLitros(diff) : 'sin dato'}</td></tr>`;
  }).join('');
}

let _refugiosOrdenColumna = 'gmv';
function ordenarRefugios(columna) {
  _refugiosOrdenColumna = columna;
  renderRefugios();
}

function renderRefugios() {
  const lista = [...DATOS.refugios].sort((a, b) => b[_refugiosOrdenColumna] - a[_refugiosOrdenColumna]);
  const N = lista.length;
  const tbody = document.querySelector('#tablaRefugios tbody');
  tbody.innerHTML = lista.map((r, i) => {
    const esTop = i < 5, esBottom = i >= N - 5;
    const estilo = esTop ? 'background:#1a3a2a' : (esBottom ? 'background:#3a1a1a' : '');
    return `<tr style="${estilo}"><td>${i + 1}</td><td>${r.local}</td><td>${fmtMoneda(r.gmv)}</td>` +
           `<td>${fmtLitros(r.litros_cerveza)}</td><td>${r.ordenes.toLocaleString('es-AR')}</td></tr>`;
  }).join('');
}
```

- [ ] **Step 4: Agregar las llamadas al callback de `fetch('/data')`**

Dentro del `.then(datos => { ... })`, agregar `renderSellin();` y `renderRefugios();` justo después de `renderEvolucionMensual();`.

- [ ] **Step 5: Verificar en navegador**

Con el server local corriendo: click en "Sellin vs Sellout" → gráfico de línea con 2 series (sellin puede aparecer vacío si el CSV real todavía no está cargado — es esperado). Click en "Ranking Refugios" → tabla con todos los locales, filas superiores resaltadas en verde (Top 5) e inferiores en rojo (Bottom 5), y los headers de GMV/Litros cerveza reordenan la tabla al hacer click.

- [ ] **Step 6: Commit**

```bash
git add templates/patagonia_semestral.html
git commit -m "feat: Tab Sellin vs Sellout y Tab Ranking Refugios (Top5/Bottom5 ordenable)"
```

---

### Task 9: Template — Tab 5 (Acciones) y Tab 6 (Combos)

**Files:**
- Modify: `Proyecto_Patagonia_Semestral/templates/patagonia_semestral.html` (mismo archivo — ejecutar DESPUÉS de Task 8)

**Interfaces:**
- Consumes: `DATOS.acciones[]` (con `tipo` = `"uplift"` / `"evolucion"` / `"externo"`, ver forma exacta en Task 6), `DATOS.combos[]` (`{nombre, incluye_cerveza, unidades, facturacion, locales}`).
- Produces: funciones `renderAcciones()`, `renderCombos()`.

- [ ] **Step 1: Reemplazar `<section class="tab-panel" id="tab-acciones"></section>`**

```html
<section class="tab-panel" id="tab-acciones">
  <div id="accionesGrid" style="display:flex; flex-wrap:wrap; gap:16px;"></div>
</section>
```

- [ ] **Step 2: Reemplazar `<section class="tab-panel" id="tab-combos"></section>`**

```html
<section class="tab-panel" id="tab-combos">
  <div class="tabla-wrap">
    <table id="tablaCombos">
      <thead><tr><th>Combo/Promo</th><th>Incluye cerveza</th><th>Unidades</th><th>Facturación</th><th>Locales</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</section>
```

- [ ] **Step 3: Agregar las funciones JS**

```javascript
function _cardAccion(a) {
  if (a.tipo === 'externo') {
    return `<div class="kpi-card" style="min-width:260px"><div class="kpi-label">${a.nombre}</div>
      <div class="kpi-value" style="font-size:1rem">${a.nota}</div></div>`;
  }
  if (a.tipo === 'uplift') {
    return `<div class="kpi-card" style="min-width:260px">
      <div class="kpi-label">${a.nombre} (${a.desde} a ${a.hasta})</div>
      <div class="kpi-value">${fmtMoneda(a.gmv)}</div>
      <div class="kpi-delta ${claseDelta(a.uplift_gmv)}">GMV vs. referencia: ${fmtPct(a.uplift_gmv)}</div>
      <div class="kpi-delta ${claseDelta(a.uplift_litros_cerveza)}">Litros cerveza vs. referencia: ${fmtPct(a.uplift_litros_cerveza)}</div>
      <div class="kpi-delta ${claseDelta(a.uplift_ordenes)}">Órdenes vs. referencia: ${fmtPct(a.uplift_ordenes)}</div>
    </div>`;
  }
  // evolucion
  return `<div class="kpi-card" style="min-width:260px">
    <div class="kpi-label">${a.nombre} (${a.desde} a ${a.hasta})</div>
    <div class="kpi-value">${fmtMoneda(a.gmv)}</div>
    <div class="kpi-delta neutro">Litros cerveza: ${fmtLitros(a.litros_cerveza)} · sin período de referencia (rango largo)</div>
  </div>`;
}

function renderAcciones() {
  document.getElementById('accionesGrid').innerHTML = DATOS.acciones.map(_cardAccion).join('');
}

function renderCombos() {
  const tbody = document.querySelector('#tablaCombos tbody');
  tbody.innerHTML = DATOS.combos.map(c =>
    `<tr><td>${c.nombre}</td><td>${c.incluye_cerveza ? 'Sí' : 'No'}</td>` +
    `<td>${c.unidades.toLocaleString('es-AR')}</td><td>${fmtMoneda(c.facturacion)}</td><td>${c.locales}</td></tr>`
  ).join('');
}
```

- [ ] **Step 4: Agregar las llamadas al callback de `fetch('/data')`**

Agregar `renderAcciones();` y `renderCombos();` después de `renderRefugios();`.

- [ ] **Step 5: Verificar en navegador**

Tab "Acciones": 6 tarjetas — Carnaval/Semana hamburguesa/Semana cerveza muestran % de uplift con color (verde/rojo), Mundial muestra la nota de texto, Otoño/8va Canilla muestran solo GMV + litros sin comparación. Tab "Combos": tabla ordenada por facturación descendente, con columna "Incluye cerveza" en Sí/No.

- [ ] **Step 6: Commit**

```bash
git add templates/patagonia_semestral.html
git commit -m "feat: Tab Acciones (uplift/evolución/externo) y Tab Combos"
```

---

### Task 10: Template — Tab 7 (Reputology) + wiring final

**Files:**
- Modify: `Proyecto_Patagonia_Semestral/templates/patagonia_semestral.html` (mismo archivo — ejecutar DESPUÉS de Task 9, última de la ola)

**Interfaces:**
- Consumes: `DATOS.reputology` (`{trimestres[], total[], por_refugio: {nombre: [...]}}`, forma exacta en Task 6).
- Produces: función `renderReputology()`. Cierra el wiring: todas las 7 funciones `render*` deben estar llamadas desde el callback de `fetch('/data')` al terminar esta task.

- [ ] **Step 1: Reemplazar `<section class="tab-panel" id="tab-reputology"></section>`**

```html
<section class="tab-panel" id="tab-reputology">
  <div class="grafico-card"><h3>Rating por trimestre (total red)</h3><canvas id="chartRatingQ"></canvas></div>
  <div class="tabla-wrap">
    <table id="tablaReputologyTotal">
      <thead><tr><th>Trimestre</th><th>Rating</th><th>NPS</th><th>Cantidad de reseñas</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <h3 style="margin-top:20px; color:#aaa; font-size:.8rem; text-transform:uppercase;">Por Refugio</h3>
  <div class="tabla-wrap">
    <table id="tablaReputologyRefugio">
      <thead><tr><th>Refugio</th><th>Trimestre</th><th>Rating</th><th>NPS</th><th>Cantidad de reseñas</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</section>
```

- [ ] **Step 2: Agregar la función JS**

```javascript
function _celda(v, sufijo) {
  return (v === null || v === undefined) ? 'sin dato' : (v + (sufijo || ''));
}

function renderReputology() {
  const rep = DATOS.reputology;

  new Chart(document.getElementById('chartRatingQ'), {
    type: 'line',
    data: {
      labels: rep.total.map(x => x.trimestre),
      datasets: [{ label: 'Rating', data: rep.total.map(x => x.rating), borderColor: '#E83E6C', spanGaps: true }],
    },
    options: { scales: { y: { min: 0, max: 5 } } },
  });

  document.querySelector('#tablaReputologyTotal tbody').innerHTML = rep.total.map(x =>
    `<tr><td>${x.trimestre}</td><td>${_celda(x.rating)}</td><td>${_celda(x.nps)}</td><td>${_celda(x.cantidad_resenas)}</td></tr>`
  ).join('');

  const filasRefugio = [];
  for (const [refugio, filas] of Object.entries(rep.por_refugio)) {
    for (const f of filas) {
      filasRefugio.push({ refugio, ...f });
    }
  }
  const tbodyRefugio = document.querySelector('#tablaReputologyRefugio tbody');
  tbodyRefugio.innerHTML = filasRefugio.length
    ? filasRefugio.map(f =>
        `<tr><td>${f.refugio}</td><td>${f.trimestre}</td><td>${_celda(f.rating)}</td><td>${_celda(f.nps)}</td><td>${_celda(f.cantidad_resenas)}</td></tr>`
      ).join('')
    : '<tr><td colspan="5" style="color:#888">Sin detalle por Refugio cargado — solo hay dato total de la red.</td></tr>';
}
```

- [ ] **Step 3: Agregar la llamada final al callback de `fetch('/data')` y confirmar el wiring completo**

Agregar `renderReputology();` después de `renderCombos();`. El bloque final del `fetch('/data').then(...)` debe llamar, en orden: `renderPendientes(); renderResumen(); renderEvolucionMensual(); renderSellin(); renderRefugios(); renderAcciones(); renderCombos(); renderReputology(); mostrarTab('resumen');`

- [ ] **Step 4: Verificar en navegador — las 7 tabs**

Recorrer las 7 tabs con el server local corriendo y confirmar que ninguna tira error en la consola del navegador (F12) ni queda en blanco. Tab Reputology mostrará "sin dato" en todas las celdas hasta que `data/reputology.csv` tenga el export real — es el comportamiento esperado, no un bug.

- [ ] **Step 5: Commit**

```bash
git add templates/patagonia_semestral.html
git commit -m "feat: Tab Reputology + wiring final de las 7 tabs"
```

---

## OLA 4 (secuencial, depende de toda la OLA 3)

### Task 11: Verificación local end-to-end

**Files:** ninguno (solo verificación, sin cambios de código salvo fixes puntuales que surjan)

- [ ] **Step 1: Regenerar el JSON con datos reales**

Run: `python -X utf8 generar_patagonia_semestral.py`
Expected: sube el JSON a GCS sin error, imprime los pendientes conocidos.

- [ ] **Step 2: Levantar el servidor Flask local**

Run: `python main.py`
Expected: sirve en `http://localhost:8080`.

- [ ] **Step 3: Recorrer las 7 tabs en el navegador (Chrome, con DevTools abierto en la pestaña Console)**

Verificar para cada tab: (a) no hay errores rojos en consola, (b) los números de KPI no son `NaN`/`undefined`/vacíos donde debería haber dato real de BigQuery, (c) las tablas ordenables (Ranking Refugios) reordenan al hacer click, (d) los gráficos Chart.js renderizan (no canvas vacío).

- [ ] **Step 4: Validar magnitud de los números contra intuición de negocio**

Comparar GMV total del semestre y litros de cerveza total contra algún reporte previo conocido de Patagonia (si existe) para detectar un orden de magnitud incorrecto (ej. factor 1000 de diferencia por mal manejo de unidades). Si algo no cierra, revisar `generar_patagonia_semestral.py` antes de seguir — no deployar con un número que no pasó este chequeo.

- [ ] **Step 5: Anotar los pendientes reales que quedan para la reunión**

Confirmar con Darwin: fechas reales de las 6 acciones, `data/sellin_cerveza.csv` (Agus), `data/reputology.csv` (export de la plataforma Reputology). Actualizar esos 3 archivos y volver a correr `generar_patagonia_semestral.py` en cuanto estén disponibles — no bloquea el deploy, se puede regenerar el JSON después con `/refresh` sin redeployar Cloud Run.

---

### Task 12: Deploy a Cloud Run

**Files:** ninguno nuevo (usa los archivos de las tasks anteriores)

- [ ] **Step 1: Deploy**

Run:
```bash
gcloud run deploy patagonia-semestral --source . --region us-central1 --project temple-bar-439715 --allow-unauthenticated --quiet
```
Expected: termina con una URL de Cloud Run.

- [ ] **Step 2: Verificar la URL en producción**

Abrir la URL de Cloud Run en el navegador y repetir el chequeo de las 7 tabs del Task 11 (Step 3) contra el servicio ya deployado, no solo local.

- [ ] **Step 3: Confirmar `/refresh` funciona en producción**

Run: `curl https://<url-de-cloud-run>/refresh`
Expected: `{"ok": true, "generado_en": "..."}`.

- [ ] **Step 4: Compartir el link con Darwin para la reunión**

No requiere ninguna acción de código — el link de Cloud Run (sin auth) es el que se usa en vivo durante la reunión con Patagonia.
