# Tarjetas "Top Refugios" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una grilla de 6 tarjetas ("Top Refugios" por GMV) arriba de la tabla ordenable existente en el tab "Ranking Refugios" del tablero Patagonia Semestral, con GMV/Litros(hL)/SOT y su variación YoY por Refugio, más un texto opcional "Palancas".

**Architecture:** Extensión del pipeline batch existente (`generar_patagonia_semestral.py` → JSON en GCS → Flask sirve HTML con Chart.js/JS puro). Se agrega una clave nueva `top_refugios` al JSON de salida (sin tocar `refugios`, que sigue alimentando la tabla actual) y una sección nueva en el template que la renderiza con el mismo estilo `.kpi-card` ya usado en Resumen y Acciones.

**Tech Stack:** Python 3.14 (pytest), Flask, Chart.js 4.4.4, JS vanilla — sin frameworks nuevos.

## Global Constraints

- Repo del código: `C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\Proyecto_Patagonia_Semestral` (repo git propio, separado de `Claude_Cowork`).
- Litros en hectolitros (hL), recalculados por el pipeline — no los del slide de referencia (ver spec, discrepancia -8% a +86% sin factor consistente).
- Delta de SOT en puntos porcentuales (`(actual - anterior) * 100`), no en % relativo.
- Estilo visual: reutilizar `.kpi-card`/`.kpi-label`/`.kpi-value`/`.kpi-delta` ya existentes en `templates/patagonia_semestral.html` — no introducir paleta nueva.
- Top 6 por GMV (no los 36 Refugios).
- Spec completo: `docs/superpowers/specs/2026-08-03-top-refugios-cards-design.md` (en este mismo repo `Claude_Cowork`).

---

### Task 1: `calcular_delta_pp()` en `calculos.py`

**Files:**
- Modify: `calculos.py` (agregar al final del archivo, después de `combo_incluye_cerveza`, línea 59)
- Test: `tests/test_calculos.py` (agregar al final, después de `test_combo_incluye_cerveza_none_es_false`, línea 84)

**Interfaces:**
- Produces: `calcular_delta_pp(valor_actual: float, valor_anterior: float) -> float`

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_calculos.py`, actualizando el import de la línea 5-8 para incluir `calcular_delta_pp`:

```python
from calculos import (
    calcular_aov, calcular_litros_por_orden, calcular_sot,
    calcular_yoy, calcular_uplift, es_combo, combo_incluye_cerveza,
    calcular_delta_pp,
)
```

Y agregar al final del archivo:

```python
def test_calcular_delta_pp_positivo():
    # SOT pasa de 82% a 93% -> +11.0 pp
    assert round(calcular_delta_pp(valor_actual=0.93, valor_anterior=0.82), 4) == 11.0


def test_calcular_delta_pp_negativo():
    # SOT pasa de 96% a 95% -> -1.0 pp (no -1.04%)
    assert round(calcular_delta_pp(valor_actual=0.95, valor_anterior=0.96), 4) == -1.0


def test_calcular_delta_pp_sin_cambio():
    assert calcular_delta_pp(valor_actual=0.5, valor_anterior=0.5) == 0.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_calculos.py -v`
Expected: FAIL — `ImportError: cannot import name 'calcular_delta_pp'`

- [ ] **Step 3: Implementar `calcular_delta_pp`**

Agregar al final de `calculos.py`:

```python


def calcular_delta_pp(valor_actual: float, valor_anterior: float) -> float:
    """Diferencia en puntos porcentuales entre dos ratios que ya son un
    porcentaje (ej. SOT) — a diferencia de calcular_yoy, que es % relativo."""
    return (valor_actual - valor_anterior) * 100
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_calculos.py -v`
Expected: PASS (todos, incluidos los 3 nuevos)

- [ ] **Step 5: Commit**

```bash
git add calculos.py tests/test_calculos.py
git commit -m "feat: agregar calcular_delta_pp para deltas de SOT en pp"
```

---

### Task 2: `_construir_top_refugios()` en `generar_patagonia_semestral.py` + `palancas.py`

**Files:**
- Create: `palancas.py` (dict vacío por ahora — se completa con texto real en el Task 4)
- Modify: `generar_patagonia_semestral.py`:
  - Imports (líneas 15-20): agregar `calcular_delta_pp` y `from palancas import PALANCAS`
  - Después de `_totales_ventana` (línea 203): agregar `_sot_local_ventana` y `_construir_top_refugios`
  - `construir_json()` (líneas 267-297): extraer `refugios` a variable y agregar clave `"top_refugios"`
- Test: `tests/test_generar_patagonia_semestral.py` (nuevo test al final del archivo)

**Interfaces:**
- Consumes: `_totales_ventana(rows_ventas, rows_productos, desde, hasta, refugios=None) -> (gmv, ordenes, litros)` (ya existe, línea 195); `_anio_anterior(fecha_str) -> str` (ya existe, línea 176); `calcular_sot`, `calcular_yoy`, `calcular_delta_pp` (de `calculos.py`); `PALANCAS: dict[str, str]` (de `palancas.py`, nuevo).
- Produces: `_sot_local_ventana(rows_productos, local, desde, hasta) -> (unid_cerveza, unid_alcoholicas)`; `_construir_top_refugios(refugios, rows_ventas, rows_productos, n=6) -> list[dict]` con claves `local, gmv, yoy_gmv, litros_cerveza, yoy_litros_cerveza, sot_cerveza, delta_sot_pp, palancas`; clave nueva `"top_refugios"` en el dict que devuelve `construir_json()`.

- [ ] **Step 1: Crear `palancas.py` (vacío, documentado)**

```python
# palancas.py
# Comentario cualitativo de negocio por Refugio para la vista "Top Refugios"
# del tab Ranking Refugios. Curado a mano por Darwin — no se puede derivar de
# BigQuery. Si un Refugio del Top 6 no tiene entrada acá, su tarjeta
# simplemente no muestra el bloque "Palancas" (no bloquea, no rompe).
PALANCAS = {}
```

- [ ] **Step 2: Escribir el test que falla**

Agregar al final de `tests/test_generar_patagonia_semestral.py`:

```python
def test_top_refugios_calcula_sot_y_yoy_por_refugio():
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
    ]

    resultado = construir_json(rows_ventas, rows_productos, [], [])
    top = resultado["top_refugios"]

    assert len(top) == 1  # el fixture solo tiene 1 local, aunque n=6
    r = top[0]
    assert r["local"] == "CALAFATE"
    assert r["gmv"] == 3000.0
    assert round(r["yoy_gmv"], 4) == 2.75  # (3000-800)/800
    assert r["litros_cerveza"] == resultado["refugios"][0]["litros_cerveza"]
    assert r["sot_cerveza"] == 1.0  # 2 unid cerveza / 2 unid alcohólicas (solo la fila tipo=CERVEZA cuenta)
    assert r["delta_sot_pp"] == 100.0  # 1.0 - 0.0 (no hay filas de productos en 2025) = +100 pp
    assert r["palancas"] is None  # CALAFATE no está en palancas.py
```

- [ ] **Step 3: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_generar_patagonia_semestral.py -v`
Expected: FAIL — `KeyError: 'top_refugios'`

- [ ] **Step 4: Implementar**

Actualizar las líneas 15-20 de `generar_patagonia_semestral.py`:

```python
from config import PROJECT, BUCKET, GCS_PATH, SEMESTRE_DESDE, SEMESTRE_HASTA, TIPO_CERVEZA, TIPOS_ALCOHOLICOS
from acciones import ACCIONES
from palancas import PALANCAS
from calculos import (
    calcular_aov, calcular_litros_por_orden, calcular_sot,
    calcular_yoy, calcular_uplift, es_combo, combo_incluye_cerveza,
    calcular_delta_pp,
)
```

Agregar después de `_totales_ventana` (después de la línea 203):

```python
def _sot_local_ventana(rows_productos, local, desde, hasta):
    """Unidades de cerveza y unidades alcohólicas totales de un Refugio en
    [desde, hasta] — insumo del SOT por Refugio (hoy solo existe agregado)."""
    unid_cerv = unid_alc = 0.0
    for r in rows_productos:
        if r["local"] == local and desde <= r["fecha"][:10] <= hasta:
            if r["tipo"] == TIPO_CERVEZA:
                unid_cerv += float(r["cantidad"])
            if r["tipo"] in TIPOS_ALCOHOLICOS:
                unid_alc += float(r["cantidad"])
    return unid_cerv, unid_alc


def _construir_top_refugios(refugios, rows_ventas, rows_productos, n=6):
    """Top N Refugios por GMV con SOT y YoY (GMV/Litros/SOT) — a diferencia de
    `refugios` (_construir_refugios), que solo trae el semestre actual."""
    resultado = []
    for r in refugios[:n]:
        local = r["local"]
        gmv_ant, _, litros_ant = _totales_ventana(
            rows_ventas, rows_productos,
            _anio_anterior(SEMESTRE_DESDE), _anio_anterior(SEMESTRE_HASTA), {local},
        )
        unid_cerv, unid_alc = _sot_local_ventana(rows_productos, local, SEMESTRE_DESDE, SEMESTRE_HASTA)
        unid_cerv_ant, unid_alc_ant = _sot_local_ventana(
            rows_productos, local, _anio_anterior(SEMESTRE_DESDE), _anio_anterior(SEMESTRE_HASTA)
        )
        sot = calcular_sot(unid_cerv, unid_alc)
        sot_ant = calcular_sot(unid_cerv_ant, unid_alc_ant)

        resultado.append({
            "local": local,
            "gmv": r["gmv"],
            "yoy_gmv": calcular_yoy(r["gmv"], gmv_ant),
            "litros_cerveza": r["litros_cerveza"],
            "yoy_litros_cerveza": calcular_yoy(r["litros_cerveza"], litros_ant),
            "sot_cerveza": sot,
            "delta_sot_pp": calcular_delta_pp(sot, sot_ant),
            "palancas": PALANCAS.get(local),
        })
    return resultado
```

Modificar `construir_json()` (líneas 267-297) — reemplazar:

```python
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
```

por:

```python
    refugios = _construir_refugios(ventas_local, productos_local)

    return {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "periodo": {"desde": SEMESTRE_DESDE, "hasta": SEMESTRE_HASTA},
        "resumen": resumen,
        "mensual": mensual,
        "sellin_sellout": _construir_sellin_sellout(mensual, sellin_rows),
        "refugios": refugios,
        "top_refugios": _construir_top_refugios(refugios, rows_ventas, rows_productos),
        "acciones": _construir_acciones(rows_ventas, rows_productos),
        "combos": combos,
        "reputology": _construir_reputology(reputology_rows),
        "pendientes": pendientes,
    }
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/ -v`
Expected: PASS (todos, incluido el nuevo)

- [ ] **Step 6: Commit**

```bash
git add generar_patagonia_semestral.py palancas.py tests/test_generar_patagonia_semestral.py
git commit -m "feat: agregar top_refugios (SOT y YoY por refugio) al JSON de salida"
```

---

### Task 3: Tarjetas en el template (`templates/patagonia_semestral.html`)

**Files:**
- Modify: `templates/patagonia_semestral.html`:
  - CSS (después de línea 45, `.kpi-delta.neutro`)
  - HTML del tab Refugios (línea 96-97, antes de `.tabla-wrap`)
  - JS: nuevas funciones `fmtPp`, `flecha`, `_cardTopRefugio`, `renderTopRefugios` (cerca de `renderRefugios`, línea 258+)
  - Cadena `fetch('/data')` (línea 422-433): agregar la llamada a `renderTopRefugios()`

**Interfaces:**
- Consumes: `DATOS.top_refugios` (del Task 2); `fmtMonedaAbrev`, `fmtHectolitros`, `fmtPct`, `claseDelta` (ya existen en el archivo).
- Produces: `fmtPp(v)`, `flecha(v)`, `_cardTopRefugio(r)`, `renderTopRefugios()` — funciones JS nuevas, sin tests automatizados (este proyecto no tiene test runner de JS; se verifica visualmente en el browser en el Task 5, mismo criterio ya usado para los charts de Evolución mensual).

- [ ] **Step 1: Agregar el CSS de la grilla**

Después de la línea 45 (`.kpi-delta.neutro { color: #aaa; }`), agregar:

```css
    .top-refugios-grid { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
```

- [ ] **Step 2: Agregar el contenedor en el HTML**

En la sección `#tab-refugios` (línea 96-97), reemplazar:

```html
    <section class="tab-panel" id="tab-refugios">
      <div class="tabla-wrap">
```

por:

```html
    <section class="tab-panel" id="tab-refugios">
      <div class="top-refugios-grid" id="topRefugiosGrid"></div>
      <div class="tabla-wrap">
```

- [ ] **Step 3: Agregar `fmtPp` y `flecha`**

Después de `fmtHectolitros` (línea 157-159), agregar:

```javascript
    function fmtPp(v) {
      if (v === null || v === undefined) return 'sin dato';
      return (v >= 0 ? '+' : '') + v.toFixed(1) + ' pp';
    }
    function flecha(v) {
      if (v === null || v === undefined) return '';
      return v >= 0 ? '▲ ' : '▼ ';
    }
```

- [ ] **Step 4: Agregar `_cardTopRefugio` y `renderTopRefugios`**

Justo antes de `function renderRefugios() {` (línea 258), agregar:

```javascript
    function _cardTopRefugio(r) {
      const palancasHtml = r.palancas ? `
        <div class="kpi-delta neutro" style="font-size:.75rem; margin-top:10px; padding-top:10px; border-top:1px solid #2a3540; line-height:1.4">
          <strong>Palancas:</strong> ${r.palancas}
        </div>` : '';
      return `<div class="kpi-card" style="min-width:280px; flex:1 1 300px">
        <div class="kpi-label" style="font-size:.9rem; color:#fff; font-weight:700; margin-bottom:10px">${r.local}</div>
        <div style="display:flex; gap:20px; flex-wrap:wrap">
          <div>
            <div class="kpi-label">GMV</div>
            <div class="kpi-value" style="font-size:1.05rem">${fmtMonedaAbrev(r.gmv)}</div>
            <div class="kpi-delta ${claseDelta(r.yoy_gmv)}">${flecha(r.yoy_gmv)}${fmtPct(r.yoy_gmv)}</div>
          </div>
          <div>
            <div class="kpi-label">Litros</div>
            <div class="kpi-value" style="font-size:1.05rem">${fmtHectolitros(r.litros_cerveza)}</div>
            <div class="kpi-delta ${claseDelta(r.yoy_litros_cerveza)}">${flecha(r.yoy_litros_cerveza)}${fmtPct(r.yoy_litros_cerveza)}</div>
          </div>
          <div>
            <div class="kpi-label">SOT</div>
            <div class="kpi-value" style="font-size:1.05rem">${(r.sot_cerveza * 100).toFixed(1)}%</div>
            <div class="kpi-delta ${claseDelta(r.delta_sot_pp)}">${flecha(r.delta_sot_pp)}${fmtPp(r.delta_sot_pp)}</div>
          </div>
        </div>
        ${palancasHtml}
      </div>`;
    }

    function renderTopRefugios() {
      document.getElementById('topRefugiosGrid').innerHTML = DATOS.top_refugios.map(_cardTopRefugio).join('');
    }

```

- [ ] **Step 5: Llamar a `renderTopRefugios()` en la cadena de carga**

En la cadena `fetch('/data')` (línea 422-433), agregar la llamada junto a `renderRefugios()`:

```javascript
    fetch('/data').then(r => r.json()).then(datos => {
      DATOS = datos;
      renderPendientes();
      renderResumen();
      renderEvolucionMensual();
      renderSellin();
      renderTopRefugios();
      renderRefugios();
      renderAcciones();
      renderCombos();
      renderReputology();
      mostrarTab('resumen');
    });
```

- [ ] **Step 6: Verificar que los tests de Python siguen pasando**

Run: `python -m pytest tests/ -v`
Expected: PASS (este task no toca Python, es solo para confirmar que no se rompió nada)

- [ ] **Step 7: Commit**

```bash
git add templates/patagonia_semestral.html
git commit -m "feat: renderizar tarjetas Top Refugios en el tab Ranking Refugios"
```

---

### Task 4: Regenerar datos, obtener números reales y escribir el texto final de `palancas.py`

**Files:**
- Modify: `palancas.py` (reemplazar el dict vacío con el texto final, con los números reales)

**Interfaces:**
- Consumes: `top_refugios` real (generado por el Task 2) vía el JSON en GCS/`/data`.
- Produces: `palancas.py` con `PALANCAS` completo para los 6 Refugios del Top actual.

- [ ] **Step 1: Regenerar el dato con el código del Task 2 (palancas.py aún vacío)**

```bash
cd "/c/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Patagonia_Semestral"
export GOOGLE_APPLICATION_CREDENTIALS="/c/Users/Darwin Salinas/Mi unidad/Claude_Cowork/temple-bar-439715-da51b292ce5d.json"
python -X utf8 generar_patagonia_semestral.py
```

Expected: `Subido a gs://temple-bar-dashboard-cache/patagonia_semestral/patagonia_data.json (...)`

- [ ] **Step 2: Leer los valores reales de `top_refugios` desde el servicio ya desplegado**

El servicio productivo actual sirve `/data` desde el JSON de GCS sin depender del HTML (el Task 3 todavía no se redeployó) — forzar refresh y leer:

```bash
curl -s https://patagonia-semestral-763905018652.us-central1.run.app/refresh
curl -s https://patagonia-semestral-763905018652.us-central1.run.app/data | python -c "import json,sys; d=json.load(sys.stdin); [print(r['local'], round(r['gmv']/1e6,1), 'M', round(r['yoy_gmv']*100,1), '%GMV |', round(r['litros_cerveza']/100,1), 'hL', round(r['yoy_litros_cerveza']*100,1), '%Litros |', round(r['sot_cerveza']*100,1), '%SOT', round(r['delta_sot_pp'],1), 'pp') for r in d['top_refugios']]"
```

Anotar los 6 valores impresos (GMV, YoY GMV, Litros hL, YoY Litros, SOT, delta SOT pp) — se usan en el Step 3.

- [ ] **Step 3: Escribir `palancas.py` con el texto final**

Reemplazar el contenido de `palancas.py`. Usar como base el comentario cualitativo del slide original que compartió Darwin (rol del Refugio, desafío de negocio), reemplazando cada número mencionado por el valor real impreso en el Step 2 — por ejemplo, si Ushuaia da +53,1% de GMV y 93,2% de SOT, el texto dice exactamente esos valores, no los que traía el slide (+53%, 93%):

```python
# palancas.py
# Comentario cualitativo de negocio por Refugio para la vista "Top Refugios"
# del tab Ranking Refugios. Curado a mano por Darwin a partir del slide que
# compartió en la reunión — los números que menciona cada texto se ajustaron
# para coincidir con los valores reales que calcula el pipeline (litros con
# corrección de estimación de pintas), no los del slide original. Si un
# Refugio del Top 6 no tiene entrada acá, su tarjeta simplemente no muestra
# el bloque "Palancas" (no bloquea, no rompe).
PALANCAS = {
    "USHUAIA": "Refugio insignia, #1 en facturación. Plaza turística premium: volumen sostenido y SOT alto. Mix premium y pinta como motor.",
    "MIS - PUERTO IGUAZU": "Destino turístico de alto tráfico, #2 en facturación. SOT muy alto. Foco en recuperar litros sosteniendo ticket.",
    "CHALTEN": "Apertura 2026 con arranque muy fuerte: ya entre los de mayor volumen del semestre. Plaza de montaña, alta estacionalidad.",
    "PUERTO MADERO": "Apertura nueva en zona premium de CABA. Máximo volumen de litros del semestre y SOT alto. Challenge + fijo.",
    "NEUQUEN": "Plaza patagónica clave. Challenge +5%. Desafío: revertir la caída de litros con combos y pinta.",
    "RESISTENCIA": "Gran volumen de litros. Challenge +5% + fijo; foco en sostener volumen y elevar SOT.",
}
```

Nota para quien ejecute este paso: el texto de arriba es el punto de partida (framing cualitativo del slide de Darwin); antes de guardarlo, insertar los números reales del Step 2 donde corresponda dentro de cada oración (ej. "volumen sostenido (+X% litros) y SOT alto (Y%)"), igual que el slide original los mencionaba pero con los valores recalculados.

- [ ] **Step 4: Regenerar el dato de nuevo (ahora con `palancas.py` completo)**

```bash
python -X utf8 generar_patagonia_semestral.py
```

- [ ] **Step 5: Correr los tests una vez más (por las dudas de haber tocado algo)**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add palancas.py
git commit -m "feat: completar texto de Palancas con los 6 Refugios del Top actual"
```

---

### Task 5: Redeploy y verificación visual

**Files:** ninguno (solo deploy y verificación)

- [ ] **Step 1: Redeploy a Cloud Run** (cambió el HTML en el Task 3)

```bash
cd "/c/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Patagonia_Semestral"
gcloud run deploy patagonia-semestral --source . --region us-central1 --project temple-bar-439715 --allow-unauthenticated --quiet
```

Expected: `Service [patagonia-semestral] revision [...] has been deployed and is serving 100 percent of traffic.`

- [ ] **Step 2: Verificar visualmente en el browser**

Abrir `https://patagonia-semestral-763905018652.us-central1.run.app/`, ir al tab "Ranking Refugios", y confirmar:
- Las 6 tarjetas aparecen arriba de la tabla, con el mismo estilo oscuro/rosa del resto del tablero.
- GMV, Litros (hL) y SOT muestran flecha ▲/▼ coloreada (verde/rojo) según corresponda.
- El bloque "Palancas" aparece con el texto correcto debajo de cada tarjeta.
- La tabla ordenable de abajo sigue funcionando igual que antes (no se rompió nada).

---

## Self-Review

**Cobertura del spec:** Alcance Top 6 (Task 2, `n=6`) ✓; ubicación arriba de la tabla (Task 3, Step 2) ✓; litros en hL (Task 3, `fmtHectolitros`) ✓; delta SOT en pp (Task 1 + Task 3, `fmtPp`) ✓; estilo `.kpi-card` (Task 3) ✓; texto Palancas con números ajustados a mano (Task 4) ✓; `palancas.py` con fallback a `None`/sin bloque (Task 2 Step 1, Task 3 `_cardTopRefugio`) ✓; tests (Task 1, Task 2) ✓; regenerar+redeploy+verificación visual (Task 4, Task 5) ✓.

**Placeholders:** el único "..." de la spec original (texto final de Palancas) se resolvió con un mecanismo concreto y accionable en el Task 4 (comando exacto para obtener los números reales + texto base a editar) — no queda ningún TBD sin instrucciones.

**Consistencia de tipos:** `_construir_top_refugios` devuelve las mismas claves (`local, gmv, yoy_gmv, litros_cerveza, yoy_litros_cerveza, sot_cerveza, delta_sot_pp, palancas`) que consume `_cardTopRefugio` en el JS — verificado línea por línea.
