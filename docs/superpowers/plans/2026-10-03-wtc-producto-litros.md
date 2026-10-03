# WTC fase 2 — litros en Producto · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sumar los litros de cerveza cargados a mano de WTC (Uruguay) a Patagonia y Todas en la pestaña Producto del tablero retail, con una nota que avise meses faltantes.

**Architecture:** `generar_preview_producto.py` lee la carga de WTC una vez (reusando `wtc.leer_carga`) y aplica una función pura `incorporar_wtc_producto` al resultado de cada período en `fetch_all`. El template `templates/producto_preview.html` muestra una nota (`wtcNotaProd`) armada por la función pura JS `wtcNotaProducto`. Solo litros: facturación, mix, dona, ranking y "vs período anterior" no se tocan.

**Tech Stack:** Python 3.12, google-cloud-bigquery, pytest; JS vanilla en el template, testeado con Node vía extracción de funciones.

**Spec:** `docs/superpowers/specs/2026-10-03-wtc-producto-litros-design.md`

## Global Constraints

- Solo litros: `total_fac`, `mix`, `ranking`, `vs_ant_pct`, `n_productos` quedan idénticos.
- Solo se tocan `PATAGONIA` y `TODAS`; `TEMPLE` y `FERIADO` nunca.
- Una marca con `sin_acceso` no recibe WTC (independiente entre PATAGONIA y TODAS).
- Fila de local: `{local:"WTC", marca:"Patagonia", lts_cerveza:L, lts_gin:0, lts_fernet:0, lts_feriado:0, lts_tragos:0, lts_total:L}`.
- Meses como `"YYYY-MM"` (igual que `wtc.leer_carga` y `_wtcMes` del tablero retail; la spec mostraba `"2026-07-01"`, se usa `"YYYY-MM"` por consistencia con fase 1).
- `meses_faltantes`: meses cerrados (`< mes de hoy`), desde `wtc.MES_MIN` (`"2025-01"`), sin fila. El mes en curso nunca es faltante.
- Falla de lectura → `WARN WTC` en el log, Producto sin WTC, `result["wtc"].error = true`. El paso Producto nunca se cae.
- Textos de la nota, exactos:
  - error: `⚠ No se pudo leer la carga de WTC: esta pestaña no lo incluye.`
  - con litros: `Incluye WTC (Uruguay): <fmtLts(lts)> de cerveza, carga manual. Solo litros; la facturación de WTC no está en esta pestaña.`
  - sin litros: `WTC (Uruguay): sin litros cargados en este período.`
  - sufijo si hay faltantes: ` ⚠ Falta cargar ago-26, sep-26.`
- Nota visible solo con marca `PATAGONIA` o `TODAS` y si la marca no es `sin_acceso`.
- Correr Python con `python -X utf8` (Windows).

## Review Focus

1. **Aliasing PATAGONIA/TODAS:** `fetch_all` arma `TODAS.locales` con los mismos dicts de `PATAGONIA.locales`; agregar WTC no debe duplicar ni compartir el dict de WTC entre listas → test `test_fila_wtc_no_compartida_entre_marcas` (Task 1).
2. **Meses cargados con 0 litros:** no debe aparecer una fila WTC con 0 en el top 10 ni cambiar totales → test `test_litros_cero_no_agrega_fila` (Task 1).
3. **Período que cruza año** (p. ej. últimos 6m desde nov a feb): los faltantes deben recorrer el cambio de año → test `test_faltantes_cruzan_cambio_de_anio` (Task 1).
4. **Patagonia sin acceso en el iframe:** la nota no debe mostrarse sobre una marca vacía → test `test_render_nota_oculta_si_sin_acceso` (Task 2).
5. **La lista leída se reusa en los 5 períodos:** la función no debe mutarla → test `test_no_muta_filas_wtc` (Task 1).

---

### Task 1: Lectura de WTC + `incorporar_wtc_producto` en el generador de Producto

**Files:**
- Modify: `generar_preview_producto.py` (agregar funciones después de `build_locales_data`, ~línea 321; cambiar `fetch_all` línea 425 y `main` líneas 583-597)
- Test: `tests/test_wtc_producto.py` (crear)

**Interfaces:**
- Consumes: `wtc.leer_carga(client) -> list[dict]` con claves `mes` (`"YYYY-MM"`), `litros_cerveza` (float), etc.; `wtc.MES_MIN = "2025-01"`.
- Produces:
  - `fetch_wtc_litros(client) -> list[dict] | None` — dicts `{"mes": "YYYY-MM", "litros_cerveza": float}`; `None` si falla.
  - `incorporar_wtc_producto(result: dict, wtc_filas: list[dict] | None, desde: str, hasta: str, hoy: date) -> dict` — muta y devuelve `result`; siempre deja `result["wtc"] = {"lts": float, "meses_incluidos": [str], "meses_faltantes": [str], "error": bool}`.
  - `fetch_all(desde, hasta, clients, wtc_filas, hoy)` — firma nueva (Task 2 lee `DATASETS[periodo].wtc`).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_wtc_producto.py`:

```python
"""tests/test_wtc_producto.py — litros de WTC (Uruguay) en la pestaña Producto."""
import copy
from datetime import date

import generar_preview_producto as gp

HOY = date(2026, 10, 3)


def _marca(lts_c=100.0, total=150.0, **kw):
    d = {"total_fac": 1000, "total_lts": total, "lts_cerveza": lts_c, "lts_gin": 5.0,
         "mix": [{"mix": "Bebida", "fac": 1000}], "ranking": [{"producto": "IPA", "facturacion": 1000}],
         "vs_ant_pct": 5.0, "n_productos": 1,
         "locales": [{"local": "PALERMO", "marca": "Patagonia", "lts_cerveza": 80.0, "lts_total": 120.0}]}
    d.update(kw)
    return d


def _result():
    r = {"TEMPLE": _marca(), "PATAGONIA": _marca(), "FERIADO": _marca(), "TODAS": _marca(300.0, 450.0)}
    # Igual que fetch_all: TODAS comparte los dicts de locales de cada marca
    r["TODAS"]["locales"] = r["PATAGONIA"]["locales"] + r["TEMPLE"]["locales"]
    return r


def _w(*pares):
    return [{"mes": m, "litros_cerveza": l} for m, l in pares]


def test_suma_litros_a_patagonia_y_todas():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    assert r["PATAGONIA"]["lts_cerveza"] == 600.0 and r["PATAGONIA"]["total_lts"] == 650.0
    assert r["TODAS"]["lts_cerveza"] == 800.0 and r["TODAS"]["total_lts"] == 950.0
    assert r["TEMPLE"] == _marca() and r["FERIADO"] == _marca()
    assert r["wtc"] == {"lts": 500.0, "meses_incluidos": ["2026-09"], "meses_faltantes": [], "error": False}


def test_mes_fuera_de_rango_no_suma():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-08", 400.0), ("2026-09", 500.0)),
                                   "2026-09-01", "2026-09-30", HOY)
    assert r["wtc"]["lts"] == 500.0 and r["wtc"]["meses_incluidos"] == ["2026-09"]


def test_mes_en_curso_cargado_suma_y_sin_cargar_no_es_faltante():
    con = gp.incorporar_wtc_producto(_result(), _w(("2026-10", 70.0)), "2026-10-01", "2026-10-03", HOY)
    assert con["wtc"]["lts"] == 70.0 and con["PATAGONIA"]["lts_cerveza"] == 170.0
    sin = gp.incorporar_wtc_producto(_result(), [], "2026-10-01", "2026-10-03", HOY)
    assert sin["wtc"]["meses_faltantes"] == []


def test_faltantes_solo_meses_cerrados_desde_2025_01():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-07", 10.0)), "2024-11-01", "2026-10-03", HOY)
    falt = r["wtc"]["meses_faltantes"]
    assert falt[0] == "2025-01" and falt[-1] == "2026-09"
    assert "2026-07" not in falt and "2026-10" not in falt and "2024-12" not in falt


def test_faltantes_cruzan_cambio_de_anio():
    r = gp.incorporar_wtc_producto(_result(), _w(("2025-12", 10.0)), "2025-11-01", "2026-02-28", HOY)
    assert r["wtc"]["meses_faltantes"] == ["2025-11", "2026-01", "2026-02"]


def test_sin_filas_deja_datos_intactos():
    r = gp.incorporar_wtc_producto(_result(), [], "2026-09-01", "2026-09-30", HOY)
    base = _result()
    for m in ("PATAGONIA", "TODAS"):
        assert r[m] == base[m]
    assert r["wtc"]["lts"] == 0 and r["wtc"]["error"] is False


def test_error_de_lectura_marca_error_y_no_suma():
    r = gp.incorporar_wtc_producto(_result(), None, "2026-09-01", "2026-09-30", HOY)
    assert r["PATAGONIA"] == _result()["PATAGONIA"]
    assert r["wtc"] == {"lts": 0, "meses_incluidos": [], "meses_faltantes": [], "error": True}


def test_patagonia_sin_acceso_no_se_toca_pero_todas_si():
    res = _result()
    res["PATAGONIA"] = {"total_lts": 0, "lts_cerveza": 0, "locales": [], "sin_acceso": True}
    r = gp.incorporar_wtc_producto(res, _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    assert r["PATAGONIA"]["lts_cerveza"] == 0 and r["PATAGONIA"]["locales"] == []
    assert r["TODAS"]["lts_cerveza"] == 800.0


def test_wtc_entra_en_locales_ordenado():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    pat = r["PATAGONIA"]["locales"]
    assert pat[0] == {"local": "WTC", "marca": "Patagonia", "lts_cerveza": 500.0, "lts_gin": 0,
                      "lts_fernet": 0, "lts_feriado": 0, "lts_tragos": 0, "lts_total": 500.0}
    assert [l["local"] for l in r["TODAS"]["locales"]].count("WTC") == 1
    assert r["TODAS"]["locales"][0]["local"] == "WTC"


def test_fila_wtc_no_compartida_entre_marcas():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    w_pat = next(l for l in r["PATAGONIA"]["locales"] if l["local"] == "WTC")
    w_tod = next(l for l in r["TODAS"]["locales"] if l["local"] == "WTC")
    assert w_pat is not w_tod
    assert [l["local"] for l in r["PATAGONIA"]["locales"]].count("WTC") == 1


def test_litros_cero_no_agrega_fila():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 0.0)), "2026-09-01", "2026-09-30", HOY)
    assert all(l["local"] != "WTC" for l in r["PATAGONIA"]["locales"])
    assert r["PATAGONIA"]["total_lts"] == 150.0 and r["wtc"]["meses_incluidos"] == ["2026-09"]


def test_no_toca_facturacion_mix_ranking_ni_delta():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    for m in ("PATAGONIA", "TODAS"):
        base = _result()[m]
        for k in ("total_fac", "mix", "ranking", "vs_ant_pct", "n_productos", "lts_gin"):
            assert r[m][k] == base[k]


def test_no_muta_filas_wtc():
    filas = _w(("2026-09", 500.0))
    antes = copy.deepcopy(filas)
    gp.incorporar_wtc_producto(_result(), filas, "2026-09-01", "2026-09-30", HOY)
    assert filas == antes


def test_fetch_wtc_litros_mapea_filas(monkeypatch):
    import wtc
    monkeypatch.setattr(wtc, "leer_carga", lambda c: [
        {"mes": "2026-09", "facturacion_uyu": 1.0, "ordenes": 1, "litros_cerveza": 500.0,
         "cargado_por": "x", "cargado_en": None}])
    assert gp.fetch_wtc_litros(object()) == [{"mes": "2026-09", "litros_cerveza": 500.0}]


def test_fetch_wtc_litros_devuelve_none_si_falla(monkeypatch, capsys):
    import wtc

    def boom(c):
        raise RuntimeError("sin permiso")
    monkeypatch.setattr(wtc, "leer_carga", boom)
    assert gp.fetch_wtc_litros(object()) is None
    assert "WARN WTC" in capsys.readouterr().out
```

- [ ] **Step 2: Correr los tests y ver que fallan**

Run: `python -X utf8 -m pytest tests/test_wtc_producto.py -v`
Expected: FAIL con `AttributeError: module 'generar_preview_producto' has no attribute 'incorporar_wtc_producto'` (y `fetch_wtc_litros`).

- [ ] **Step 3: Implementar las funciones**

En `generar_preview_producto.py`, después de `build_locales_data` (antes de `# ── Construir datos por marca`), agregar:

```python
# ── WTC (Uruguay): litros de cerveza cargados a mano (fase 2) ─────
def fetch_wtc_litros(client):
    """Carga manual mensual de WTC (solo mes y litros). None si la lectura falla:
    Producto sale sin WTC y la nota lo avisa; el paso nunca se cae por esto."""
    try:
        import wtc
        filas = [{"mes": f["mes"], "litros_cerveza": f["litros_cerveza"]} for f in wtc.leer_carga(client)]
        print(f"  ✓ WTC: {len(filas)} meses cargados")
        return filas
    except Exception as e:
        print(f"  WARN WTC: no se pudo leer la carga manual — Producto sin WTC ({e})")
        return None


def _meses_entre(desde_m, hasta_m):
    """Meses 'YYYY-MM' de desde_m a hasta_m inclusive."""
    y, m = int(desde_m[:4]), int(desde_m[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hasta_m:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def incorporar_wtc_producto(result, wtc_filas, desde, hasta, hoy):
    """Suma los litros de cerveza de WTC del período a PATAGONIA y TODAS (solo litros:
    facturación, mix y ranking no se tocan) y deja result['wtc'] para la nota."""
    if wtc_filas is None:
        result["wtc"] = {"lts": 0, "meses_incluidos": [], "meses_faltantes": [], "error": True}
        return result
    from wtc import MES_MIN
    d_m, h_m, mes_hoy = desde[:7], hasta[:7], hoy.isoformat()[:7]
    cargados = {f["mes"]: f["litros_cerveza"] for f in wtc_filas}
    incluidos = sorted(m for m in cargados if d_m <= m <= h_m)
    lts = round(sum(cargados[m] for m in incluidos), 1)
    faltantes = [m for m in _meses_entre(max(d_m, MES_MIN), h_m) if m < mes_hoy and m not in cargados]
    result["wtc"] = {"lts": lts, "meses_incluidos": incluidos, "meses_faltantes": faltantes, "error": False}
    if lts <= 0:
        return result
    for marca in ("PATAGONIA", "TODAS"):
        d = result.get(marca)
        if not d or d.get("sin_acceso"):
            continue
        d["lts_cerveza"] = round(d.get("lts_cerveza", 0) + lts, 1)
        d["total_lts"] = round(d.get("total_lts", 0) + lts, 1)
        fila = {"local": "WTC", "marca": "Patagonia", "lts_cerveza": lts, "lts_gin": 0,
                "lts_fernet": 0, "lts_feriado": 0, "lts_tragos": 0, "lts_total": lts}
        d["locales"] = sorted(d.get("locales", []) + [fila], key=lambda x: -x["lts_total"])
    return result
```

- [ ] **Step 4: Correr los tests y ver que pasan**

Run: `python -X utf8 -m pytest tests/test_wtc_producto.py -v`
Expected: 15 passed.

- [ ] **Step 5: Conectar en `fetch_all` y `main`**

En `fetch_all` (línea 425) cambiar la firma:

```python
def fetch_all(desde, hasta, clients, wtc_filas, hoy):
    """Fetches data for a single date range using pre-created BQ clients."""
```

y al final, reemplazar:

```python
    result['TODAS'] = todas

    return result
```

por:

```python
    result['TODAS'] = todas

    incorporar_wtc_producto(result, wtc_filas, desde, hasta, hoy)
    return result
```

En `main()`, después de crear `clients` y antes de `periods = compute_periods()`:

```python
    # WTC (Uruguay): una sola lectura, se reparte por período en fetch_all
    wtc_filas = fetch_wtc_litros(clients['TEMPLE'])
    hoy = date.today()
```

y en el loop reemplazar `data = fetch_all(desde, hasta, clients)` por:

```python
        data = fetch_all(desde, hasta, clients, wtc_filas, hoy)
```

(`fetch_all` solo se llama desde `main`; verificado con grep.)

- [ ] **Step 6: Correr toda la suite**

Run: `python -X utf8 -m pytest tests -q`
Expected: todo verde (los tests que requieren Node se saltean si no está).

- [ ] **Step 7: Commit**

```bash
git add generar_preview_producto.py tests/test_wtc_producto.py
git commit -m "feat(wtc): litros de WTC suman a Patagonia y Todas en Producto

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Nota de WTC en el iframe de Producto

**Files:**
- Modify: `templates/producto_preview.html:63-66` (HTML de la nota), después de `fmtLts` (~línea 193, funciones nuevas), `render()` (~línea 218-221, llamada)
- Test: `tests/test_wtc_producto_js.py` (crear)

**Interfaces:**
- Consumes: `DATASETS[periodo].wtc` = `{lts, meses_incluidos, meses_faltantes, error}` (Task 1); globals del template `_marca`, `_periodo`, `fmtLts`, `_n1`.
- Produces: `_wtcMes(m)`, `wtcNotaProducto(w) -> string`, `renderWtcNota()`; elemento `#wtcNotaProd`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_wtc_producto_js.py`:

```python
"""tests/test_wtc_producto_js.py — nota WTC en templates/producto_preview.html (Node)."""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="requiere Node")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "producto_preview.html")
FN = ["_n1", "fmtLts", "_wtcMes", "wtcNotaProducto"]


def run_dom_js(funciones, setup, expr, tmp_path):
    """Igual que tests/test_finanzas_js.run_dom_js pero sobre producto_preview.html."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    fuentes = []
    for nombre in funciones:
        m = re.search(r"^function " + nombre + r"\(.*?^\}\n", html, re.S | re.M)
        assert m, f"no se encontró {nombre} en la plantilla"
        fuentes.append(m.group(0))
    dom = ("const _els={};const document={getElementById:id=>_els[id]||(_els[id]="
           "{id,style:{},innerHTML:'',textContent:''})};\n")
    script = tmp_path / "dom.js"
    script.write_text(dom + "\n".join(fuentes) + "\n" + setup
                      + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def test_nota_con_litros(tmp_path):
    t = run_dom_js(FN, "", 'wtcNotaProducto({lts:850,meses_incluidos:["2026-09"],meses_faltantes:[],error:false})',
                   tmp_path)
    assert t.startswith("Incluye WTC (Uruguay): ") and "de cerveza, carga manual." in t
    assert t.endswith("Solo litros; la facturación de WTC no está en esta pestaña.")


def test_nota_sin_litros_con_faltantes(tmp_path):
    t = run_dom_js(FN, "", 'wtcNotaProducto({lts:0,meses_incluidos:[],meses_faltantes:["2026-08","2026-09"],error:false})',
                   tmp_path)
    assert t == "WTC (Uruguay): sin litros cargados en este período. ⚠ Falta cargar ago-26, sep-26."


def test_nota_error_y_null(tmp_path):
    r = run_dom_js(FN, "", '[wtcNotaProducto({lts:0,meses_incluidos:[],meses_faltantes:["2026-09"],error:true}),'
                           'wtcNotaProducto(null)]', tmp_path)
    assert r == ["⚠ No se pudo leer la carga de WTC: esta pestaña no lo incluye.", ""]


@pytest.mark.parametrize("marca,display", [("TODAS", "block"), ("PATAGONIA", "block"),
                                           ("TEMPLE", "none"), ("FERIADO", "none")])
def test_render_nota_segun_marca(tmp_path, marca, display):
    setup = ('var DATASETS={mes_actual:{wtc:{lts:850,meses_incluidos:["2026-09"],meses_faltantes:[],error:false},'
             'TODAS:{},PATAGONIA:{},TEMPLE:{},FERIADO:{}}};'
             f'var _periodo="mes_actual";var _marca="{marca}";renderWtcNota();')
    r = run_dom_js(FN + ["renderWtcNota"], setup,
                   "[_els.wtcNotaProd.style.display,_els.wtcNotaProd.textContent]", tmp_path)
    assert r[0] == display
    assert r[1].startswith("Incluye WTC") == (display == "block")


def test_render_nota_oculta_si_sin_acceso(tmp_path):
    setup = ('var DATASETS={mes_actual:{wtc:{lts:850,meses_incluidos:[],meses_faltantes:[],error:false},'
             'PATAGONIA:{sin_acceso:true}}};var _periodo="mes_actual";var _marca="PATAGONIA";renderWtcNota();')
    r = run_dom_js(FN + ["renderWtcNota"], setup, "_els.wtcNotaProd.style.display", tmp_path)
    assert r == "none"


def test_render_llama_a_la_nota_y_existe_el_elemento():
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert 'id="wtcNotaProd"' in html
    cuerpo = re.search(r"^function render\(\)\{(.*?)^\}\n", html, re.S | re.M).group(1)
    assert cuerpo.index("renderWtcNota()") < cuerpo.index("if(d.sin_acceso)")
```

- [ ] **Step 2: Correr los tests y ver que fallan**

Run: `python -X utf8 -m pytest tests/test_wtc_producto_js.py -v`
Expected: FAIL con `AssertionError: no se encontró _wtcMes en la plantilla` (y `id="wtcNotaProd"` ausente).

- [ ] **Step 3: Agregar el elemento HTML**

En `templates/producto_preview.html`, reemplazar:

```html
<section class="sec">
  <div class="grid g-220" id="kpiRow"></div>
  <div class="lts-strip" id="ltsRow"></div>
</section>
```

por:

```html
<section class="sec">
  <div class="grid g-220" id="kpiRow"></div>
  <p class="note" id="wtcNotaProd" style="display:none"></p>
  <div class="lts-strip" id="ltsRow"></div>
</section>
```

(`.note` ya existe en `static/temple-retail.css:88`.)

- [ ] **Step 4: Agregar las funciones JS**

Después de la función `fmtLts` (termina en `return _n1(n)+u;\n}`), agregar:

```js
/* WTC (Uruguay): litros cargados a mano, sumados en Python a Patagonia y Todas */
function _wtcMes(m){
  var n=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  return n[+m.slice(5,7)-1]+'-'+m.slice(2,4);
}
/* Texto de la nota de WTC. Pura: recibe DATASETS[periodo].wtc */
function wtcNotaProducto(w){
  if(!w) return '';
  if(w.error) return '⚠ No se pudo leer la carga de WTC: esta pestaña no lo incluye.';
  var t = w.lts > 0
    ? 'Incluye WTC (Uruguay): '+fmtLts(w.lts)+' de cerveza, carga manual. Solo litros; la facturación de WTC no está en esta pestaña.'
    : 'WTC (Uruguay): sin litros cargados en este período.';
  if((w.meses_faltantes||[]).length) t += ' ⚠ Falta cargar '+w.meses_faltantes.map(_wtcMes).join(', ')+'.';
  return t;
}
function renderWtcNota(){
  var el = document.getElementById('wtcNotaProd');
  var ds = DATASETS[_periodo] || {};
  var d  = ds[_marca] || {};
  var ver = (_marca==='PATAGONIA' || _marca==='TODAS') && !!ds.wtc && !d.sin_acceso;
  el.style.display = ver ? 'block' : 'none';
  el.textContent   = ver ? wtcNotaProducto(ds.wtc) : '';
}
```

- [ ] **Step 5: Llamar la nota en `render()`**

En `render()`, reemplazar:

```js
  const d = (DATASETS[_periodo]||{})[_marca];
  if(!d) return;

  // Sin acceso BQ
```

por:

```js
  const d = (DATASETS[_periodo]||{})[_marca];
  if(!d) return;

  renderWtcNota();

  // Sin acceso BQ
```

- [ ] **Step 6: Correr los tests y ver que pasan**

Run: `python -X utf8 -m pytest tests/test_wtc_producto_js.py tests/test_wtc_producto.py -v`
Expected: todos passed. Si los JS aparecen como `skipped`, verificar `node -v` antes de seguir (en esta PC hay Node; skipped = no se probó).

- [ ] **Step 7: Commit**

```bash
git add templates/producto_preview.html tests/test_wtc_producto_js.py
git commit -m "feat(wtc): nota de WTC en la pestaña Producto (litros, meses faltantes)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Verificación local, merge y publicación

**Files:**
- Ninguno nuevo. El HTML generado va a `$env:TEMP`, fuera del repo.

**Interfaces:**
- Consumes: Tasks 1 y 2 completas en `feat/wtc-producto-litros`.
- Produces: `gs://temple-bar-dashboard-cache/producto.html` con WTC.

- [ ] **Step 1: Generar local sin subir**

Run (PowerShell): `python -X utf8 generar_preview_producto.py --no-upload --output "$env:TEMP\preview_producto.html"`
Expected: línea `✓ WTC: N meses cargados` (N ≥ 19), sin `WARN WTC`, termina con `✓ Listo`.

- [ ] **Step 2: Verificar los datos embebidos**

Run (PowerShell):

```powershell
python -X utf8 -c "import re,json,os;h=open(os.path.join(os.environ['TEMP'],'preview_producto.html'),encoding='utf-8').read();d=json.loads(re.search(r'const DATASETS = (\{.*?\});\n',h,re.S).group(1));[print(p,d[p]['wtc'],d[p]['PATAGONIA']['lts_cerveza'],[l['local'] for l in d[p]['PATAGONIA']['locales'][:10]].count('WTC')) for p in ('mes_anterior','ultimos_3m','ytd')]"
```

Expected: `error: False` en todos; `ytd` con `meses_incluidos` desde `2026-01` y `lts` > 0; si ago-26/sep-26 siguen sin cargar, `mes_anterior` con `lts` 0 y `meses_faltantes: ['2026-09']`, y `ultimos_3m` lista `2026-08` y `2026-09` como faltantes.

- [ ] **Step 3: Sonda visual (Chrome headless)**

Abrir `$env:TEMP\preview_producto.html` con Chrome headless (`--screenshot`; ver memoria `lesson_chrome-headless-probe-fallback`) a 1280px y a 390px de ancho (iframe inyectado como viewport). Inyectar `postMessage({type:'setMarca',marca:'PATAGONIA'})` y `postMessage({type:'setPeriodo',periodo:'ytd'})`. Verificar: nota visible entre los KPIs y la franja de litros, sin scroll horizontal a 390px, WTC con punto de color Patagonia en el top 10 si corresponde; con `TEMPLE` la nota no aparece.

- [ ] **Step 4: Merge a main (lo corre Darwin)**

El modo auto bloquea merge/push a main: pasarle a Darwin estas líneas para que las corra con `!`:

```
! git switch main
! git merge --no-ff feat/wtc-producto-litros -m "Merge branch 'feat/wtc-producto-litros'"
! git push origin main
```

- [ ] **Step 5: Correr el pipeline y verificar**

Run: `gh workflow run actualizar-pipeline.yml`, luego `gh run list --workflow actualizar-pipeline.yml -L 1` para el id y `gh run watch <id>`.
Verificar: `gh run view <id> --log | Select-String "FALLÓ|WARN WTC|✓ WTC"` → aparece `✓ WTC: N meses cargados` y ningún `FALLÓ` del paso Producto (workflow verde ≠ pasos OK). Luego el blob:

```powershell
python -X utf8 -c "from google.cloud import storage;b=storage.Client(project='temple-bar-439715').bucket('temple-bar-dashboard-cache').get_blob('producto.html');print(b.updated);print('wtcNotaProd' in b.download_as_text())"
```

Expected: `updated` de hoy y `True`.

- [ ] **Step 6: Borrar la rama mergeada**

```bash
git branch -d feat/wtc-producto-litros
```
