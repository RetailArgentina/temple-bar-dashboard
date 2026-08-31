# Mundial 2026 Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir una app Flask independiente que muestra analytics de ventas durante partidos del Mundial, con filtrado client-side en JS, deployada en Cloud Run sin auth.

**Architecture:** Flask sirve una sola página HTML con toda la data de partidos pre-embedida como objeto JS. Un script Python separado (`generar_mundial.py`) consulta BQ y sube el JSON a GCS. Flask carga desde GCS al arrancar y re-carga en `/refresh`. Todo el filtrado ocurre en el browser.

**Tech Stack:** Python 3.11, Flask 3.0, google-cloud-bigquery, google-cloud-storage, Chart.js 4.4, vanilla JS, Cloud Run (buildpacks)

---

## Mapa de archivos

```
Proyecto_Mundial/
├── main.py                    # Flask: carga JSON desde GCS, sirve template
├── generar_mundial.py         # Script: query BQ → JSON → sube a GCS
├── partidos.py                # Config hardcodeada: partidos, turnos, columnas BQ
├── requirements.txt
├── Procfile                   # Para Cloud Run buildpacks
├── templates/
│   └── tablero.html           # Single-page app, todo JS inline
└── static/
    ├── style.css              # Copiado de Locales Propios
    ├── logo-temple-white.png
    ├── fonts/
    └── textures/
        └── crinkle-magenta.jpg
```

---

### Task 1: Scaffold del proyecto

**Files:**
- Create: `Proyecto_Mundial/` (directorio con subdirectorios)
- Create: `Proyecto_Mundial/requirements.txt`
- Create: `Proyecto_Mundial/Procfile`
- Copy: static assets desde Locales Propios

- [ ] **Step 1: Verificar columnas de BQ antes de empezar**

Correr en BigQuery console:

```sql
SELECT table_name, column_name, data_type
FROM `temple-bar-439715.Corporativo.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('vw_Ventas_Corporativo_Base', 'vw_productos_maestro_clean')
ORDER BY table_name, ordinal_position
```

Anotar nombres exactos de: fecha, hora, marca, local, total orden, producto id, nombre producto, categoría, cantidad, precio. Verificar si `vw_productos_maestro_clean` tiene columna de litros y su nombre. Actualizar `COL_*` en `partidos.py` (Task 2) según lo encontrado.

- [ ] **Step 2: Crear estructura de directorios**

```bash
mkdir -p "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/templates"
mkdir -p "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/fonts"
mkdir -p "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/textures"
```

- [ ] **Step 3: Crear requirements.txt**

`Proyecto_Mundial/requirements.txt`:
```
flask==3.0.3
google-cloud-bigquery==3.25.0
google-cloud-storage==2.18.2
```

- [ ] **Step 4: Crear Procfile**

`Proyecto_Mundial/Procfile`:
```
web: python main.py
```

- [ ] **Step 5: Copiar assets estáticos desde Locales Propios**

```bash
cp "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Locales_Propios/static/style.css" \
   "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/"

cp "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Locales_Propios/static/logo-temple-white.png" \
   "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/"

cp "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Locales_Propios/static/fonts/"* \
   "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/fonts/"

cp "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Locales_Propios/static/textures/crinkle-magenta.jpg" \
   "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/textures/"
```

- [ ] **Step 6: Verificar estructura**

```bash
ls "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/"
ls "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial/static/"
```

Expected: `requirements.txt`, `Procfile`, `templates/`, `static/` con `style.css`, `logo-temple-white.png`, `fonts/`, `textures/`.

- [ ] **Step 7: Init git y primer commit**

```bash
cd "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial"
git init
git add requirements.txt Procfile
git commit -m "feat: scaffold mundial dashboard project"
```

---

### Task 2: partidos.py — config hardcodeada

**Files:**
- Create: `Proyecto_Mundial/partidos.py`

- [ ] **Step 1: Crear partidos.py**

Completar `PARTIDOS` con fechas y horarios reales del fixture de Argentina:

```python
# partidos.py
# Config hardcodeada: partidos del Mundial 2026 + turnos + mapeo de columnas BQ

# Completar con fecha y horario real de cada partido. Formato hora: "HH:MM" (hora local Argentina)
PARTIDOS = [
    {"id": 1, "nombre": "Partido 1", "fecha": "2026-XX-XX", "inicio": "HH:MM", "fin": "HH:MM"},
    {"id": 2, "nombre": "Partido 2", "fecha": "2026-XX-XX", "inicio": "HH:MM", "fin": "HH:MM"},
    {"id": 3, "nombre": "Partido 3", "fecha": "2026-XX-XX", "inicio": "HH:MM", "fin": "HH:MM"},
    # Agregar mas segun avance en el torneo
]

TURNOS = {
    "tarde": {"inicio": 9,  "fin": 18},   # 09:00 - 18:00
    "noche": {"inicio": 20, "fin": 29},   # 20:00 - 05:00 (fin=29 para calculos cross-midnight)
}

FECHA_MIN = min(p["fecha"] for p in PARTIDOS)
FECHA_MAX = max(p["fecha"] for p in PARTIDOS)

# Columnas de vw_Ventas_Corporativo_Base — ACTUALIZAR segun INFORMATION_SCHEMA (Task 1, Step 1)
COL_ORDEN_ID    = "orden_id"
COL_FECHA       = "fecha_orden"
COL_HORA        = "hora_orden"
COL_MARCA       = "marca"
COL_LOCAL       = "local_nombre"
COL_GMV_LINEA   = "precio_linea"
COL_PRODUCTO_ID = "producto_id"
COL_NOMBRE_PROD = "nombre_producto"
COL_CATEGORIA   = "categoria_producto"
COL_CANTIDAD    = "cantidad"

# Columnas de vw_productos_maestro_clean — ACTUALIZAR segun INFORMATION_SCHEMA (Task 1, Step 1)
COL_PROD_ID   = "producto_id"
COL_LITROS    = "litros_cerveza"   # VERIFICAR nombre exacto
COL_TIPO_CERV = "tipo_cerveza"     # VERIFICAR si existe
```

- [ ] **Step 2: Commit**

```bash
cd "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial"
git add partidos.py
git commit -m "feat: add partidos config hardcodeada"
```

---

### Task 3: generar_mundial.py — BQ + JSON + GCS

**Files:**
- Create: `Proyecto_Mundial/generar_mundial.py`

- [ ] **Step 1: Crear generar_mundial.py**

```python
# generar_mundial.py
# Uso: python -X utf8 generar_mundial.py
# Requiere GOOGLE_APPLICATION_CREDENTIALS apuntando al SA de temple-bar-439715

import json
from datetime import datetime
from google.cloud import bigquery, storage

from partidos import (
    PARTIDOS, TURNOS, FECHA_MIN, FECHA_MAX,
    COL_ORDEN_ID, COL_FECHA, COL_HORA, COL_MARCA, COL_LOCAL,
    COL_GMV_LINEA, COL_PRODUCTO_ID, COL_NOMBRE_PROD, COL_CATEGORIA, COL_CANTIDAD,
    COL_PROD_ID, COL_LITROS, COL_TIPO_CERV,
)

PROJECT  = "temple-bar-439715"
BUCKET   = "temple-bar-439715"
GCS_PATH = "mundial/mundial_data.json"

bq = bigquery.Client(project=PROJECT)


def build_query():
    return f"""
SELECT
  v.{COL_ORDEN_ID}                              AS orden_id,
  CAST(v.{COL_FECHA} AS STRING)                 AS fecha,
  CAST(v.{COL_HORA}  AS STRING)                 AS hora,
  v.{COL_MARCA}                                 AS marca,
  v.{COL_LOCAL}                                 AS local,
  COALESCE(v.{COL_GMV_LINEA}, 0.0)              AS gmv_linea,
  CAST(v.{COL_PRODUCTO_ID} AS STRING)           AS producto_id,
  v.{COL_NOMBRE_PROD}                           AS nombre_producto,
  COALESCE(p.categoria, v.{COL_CATEGORIA})      AS categoria,
  COALESCE(v.{COL_CANTIDAD}, 0)                 AS cantidad,
  COALESCE(p.{COL_LITROS}, 0.0)                 AS litros,
  COALESCE(p.{COL_TIPO_CERV}, '')               AS tipo_cerveza
FROM `{PROJECT}.Corporativo.vw_Ventas_Corporativo_Base` v
LEFT JOIN `{PROJECT}.Corporativo.vw_productos_maestro_clean` p
  ON CAST(v.{COL_PRODUCTO_ID} AS STRING) = CAST(p.{COL_PROD_ID} AS STRING)
WHERE DATE(v.{COL_FECHA}) >= '{FECHA_MIN}'
  AND DATE(v.{COL_FECHA}) <= '{FECHA_MAX}'
"""

def run_query(sql):
    print("Corriendo query BQ...")
    rows = list(bq.query(sql).result())
    print(f"  -> {len(rows)} filas")
    return rows


def hora_a_minutos(hora_str):
    partes = str(hora_str).split(":")
    return int(partes[0]) * 60 + int(partes[1])

def turno_de_minutos(m):
    t = TURNOS["tarde"]
    n = TURNOS["noche"]
    if t["inicio"] * 60 <= m < t["fin"] * 60:
        return "tarde"
    if m >= n["inicio"] * 60 or m < (n["fin"] - 24) * 60:
        return "noche"
    return None

def partido_de_fecha_hora(fecha_str, m):
    for p in PARTIDOS:
        if p["fecha"] != fecha_str[:10]:
            continue
        if hora_a_minutos(p["inicio"]) <= m <= hora_a_minutos(p["fin"]):
            return p["id"]
    return None


def construir_json(rows):
    ordenes = {}
    for r in rows:
        oid     = str(r["orden_id"])
        fecha   = str(r["fecha"])[:10]
        hora    = str(r["hora"])[:5]
        minutos = hora_a_minutos(str(r["hora"]))
        pid     = partido_de_fecha_hora(fecha, minutos)
        turno   = turno_de_minutos(minutos)

        if oid not in ordenes:
            ordenes[oid] = {
                "orden_id":   oid,
                "fecha":      fecha,
                "hora":       hora,
                "marca":      r["marca"],
                "local":      r["local"],
                "partido_id": pid,
                "turno":      turno,
                "gmv":        0.0,
                "items":      [],
            }
        ordenes[oid]["gmv"] += float(r["gmv_linea"] or 0)
        ordenes[oid]["items"].append({
            "producto_id":  str(r["producto_id"]),
            "nombre":       r["nombre_producto"],
            "categoria":    r["categoria"],
            "cantidad":     int(r["cantidad"] or 0),
            "gmv":          float(r["gmv_linea"] or 0),
            "litros":       float(r["litros"] or 0),
            "tipo_cerveza": r["tipo_cerveza"],
        })

    todas = list(ordenes.values())
    return {
        "generado_en":      datetime.now().isoformat(),
        "partidos":         PARTIDOS,
        "ordenes":          [o for o in todas if o["partido_id"] is not None],
        "ordenes_normales": [o for o in todas if o["partido_id"] is None],
    }


def subir_gcs(data):
    gcs    = storage.Client(project=PROJECT)
    bucket = gcs.bucket(BUCKET)
    blob   = bucket.blob(GCS_PATH)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json",
    )
    blob.cache_control = "no-cache"
    blob.patch()
    print(f"Subido a gs://{BUCKET}/{GCS_PATH}")


if __name__ == "__main__":
    rows = run_query(build_query())
    data = construir_json(rows)
    print(f"Ordenes en partidos:  {len(data['ordenes'])}")
    print(f"Ordenes normales:     {len(data['ordenes_normales'])}")
    subir_gcs(data)
    print("Listo.")
```

- [ ] **Step 2: Probar dry-run local**

```bash
cd "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial"
pip install -r requirements.txt
python -X utf8 -c "
from generar_mundial import build_query, run_query, construir_json
import json
rows = run_query(build_query())
data = construir_json(rows)
print('ordenes partido:', len(data['ordenes']))
print('ordenes normales:', len(data['ordenes_normales']))
with open('test_data.json','w',encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, default=str, indent=2)
print('Guardado en test_data.json')
"
```

Si falla por nombres de columna, corregir `COL_*` en `partidos.py` y reintentar.

- [ ] **Step 3: Revisar test_data.json**

Verificar que:
- Ordenes de partido tienen `partido_id` distinto de `null`
- Items de cerveza tienen `litros` > 0
- Items tienen `categoria` no vacia

- [ ] **Step 4: Commit**

```bash
git add generar_mundial.py
git commit -m "feat: add generar_mundial script (BQ query + JSON build + GCS upload)"
```

---

### Task 4: main.py — Flask app

**Files:**
- Create: `Proyecto_Mundial/main.py`

- [ ] **Step 1: Crear main.py**

```python
# main.py
import json
import os
from flask import Flask, render_template, jsonify
from google.cloud import storage

app = Flask(__name__)

PROJECT  = "temple-bar-439715"
BUCKET   = "temple-bar-439715"
GCS_PATH = "mundial/mundial_data.json"

_cache = {"data": None}
_DATA_VACIA = {"generado_en": None, "partidos": [], "ordenes": [], "ordenes_normales": []}


def cargar_desde_gcs():
    gcs  = storage.Client(project=PROJECT)
    blob = gcs.bucket(BUCKET).blob(GCS_PATH)
    raw  = blob.download_as_text(encoding="utf-8")
    _cache["data"] = json.loads(raw)
    print(f"JSON cargado: {len(_cache['data']['ordenes'])} ordenes en partidos")


@app.before_request
def init():
    if _cache["data"] is None:
        try:
            cargar_desde_gcs()
        except Exception as e:
            print(f"Warning: no se pudo cargar JSON de GCS: {e}")
            _cache["data"] = _DATA_VACIA


@app.route("/")
def index():
    return render_template(
        "tablero.html",
        data_json=json.dumps(_cache["data"], ensure_ascii=False),
    )


@app.route("/refresh")
def refresh():
    cargar_desde_gcs()
    return jsonify({"ok": True, "ordenes": len(_cache["data"]["ordenes"])})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
```

- [ ] **Step 2: Crear template minimo**

`Proyecto_Mundial/templates/tablero.html`:
```html
<!DOCTYPE html><html><body><h1>OK</h1></body></html>
```

- [ ] **Step 3: Verificar que Flask arranca**

```bash
python main.py
```

Expected: `Running on http://0.0.0.0:8080`. Abrir `http://localhost:8080` → muestra "OK". Warning de GCS en local es esperado.

- [ ] **Step 4: Commit**

```bash
git add main.py templates/tablero.html
git commit -m "feat: add flask app with GCS JSON loader"
```

---

### Task 5: tablero.html — shell HTML + barra de filtros

**Files:**
- Modify: `Proyecto_Mundial/templates/tablero.html`

- [ ] **Step 1: Reemplazar con shell completo**

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Temple - Mundial 2026</title>
  <link rel="stylesheet" href="/static/style.css?v=1">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    .filtros {
      position: sticky; top: 0; z-index: 100;
      background: var(--temple-black); border-bottom: 1px solid var(--rule);
      padding: .75rem 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap; align-items: center;
    }
    .filtros select {
      background: var(--bg-elev); color: var(--fg);
      border: 1px solid var(--rule); border-radius: 6px;
      padding: .4rem .75rem; font-size: .85rem; cursor: pointer;
    }
    .kpi-row { display: flex; gap: 1rem; padding: 1.5rem; flex-wrap: wrap; }
    .kpi-card { flex: 1; min-width: 160px; background: var(--bg-elev); border-radius: 10px; padding: 1rem 1.25rem; }
    .kpi-label { font-size: .75rem; color: var(--fg-muted); text-transform: uppercase; letter-spacing: .06em; }
    .kpi-val   { font-family: var(--font-headline); font-size: 2rem; margin: .25rem 0; }
    .kpi-delta { font-size: .8rem; }
    .kpi-delta.pos { color: var(--st-verde); }
    .kpi-delta.neg { color: var(--st-rojo); }
    .seccion { padding: 0 1.5rem 2rem; }
    .seccion-title {
      font-family: var(--font-headline); font-size: 1.25rem; color: var(--fg-muted);
      margin: 0 0 1rem; border-bottom: 1px solid var(--rule); padding-bottom: .5rem;
    }
    .charts-row { display: flex; gap: 1rem; flex-wrap: wrap; padding: 0 1.5rem 2rem; }
    .chart-card { flex: 1; min-width: 280px; background: var(--bg-elev); border-radius: 10px; padding: 1rem; }
    .chart-title { font-size: .85rem; color: var(--fg-muted); margin: 0 0 .75rem; }
    .tabla { width: 100%; border-collapse: collapse; font-size: .875rem; }
    .tabla th { color: var(--fg-muted); font-weight: 500; padding: .5rem .75rem; text-align: left; border-bottom: 1px solid var(--rule); }
    .tabla td { padding: .5rem .75rem; border-bottom: 1px solid var(--rule2); }
    .tabla tr:hover td { background: rgba(255,255,255,.04); }
    .pbar-wrap { width: 100%; background: var(--rule2); border-radius: 4px; height: 6px; margin-top: 4px; }
    .pbar { background: var(--temple-pink); height: 6px; border-radius: 4px; }
    .toggle-row { display: flex; gap: .5rem; margin-bottom: 1rem; }
    .tbtn { background: var(--bg-elev); border: 1px solid var(--rule); color: var(--fg-muted); border-radius: 6px; padding: .35rem .75rem; font-size: .8rem; cursor: pointer; }
    .tbtn.is-active { background: var(--temple-pink); border-color: var(--temple-pink); color: #fff; }
    .promo-detail { display: none; }
    .promo-detail.open { display: table-row-group; }
    .promo-expand { cursor: pointer; color: var(--temple-teal); font-size: .8rem; user-select: none; }
  </style>
</head>
<body>
<div class="app">
  <header class="top">
    <div class="brand">
      <img src="/static/logo-temple-white.png" alt="TEMPLE">
      <span class="cat">Mundial 2026</span>
    </div>
    <div class="controls">
      <span id="lbl-actualizado" style="font-size:.8rem;color:var(--fg-faint)"></span>
    </div>
  </header>

  <div class="filtros">
    <select id="f-partido"><option value="">Todos los partidos</option></select>
    <select id="f-marca"><option value="">Todas las marcas</option></select>
    <select id="f-local"><option value="">Todos los locales</option></select>
    <select id="f-turno">
      <option value="">Todos los turnos</option>
      <option value="tarde">Tarde (09-18h)</option>
      <option value="noche">Noche (20-05h)</option>
    </select>
  </div>

  <main class="main">
    <div class="kpi-row" id="kpi-row"></div>

    <div class="charts-row">
      <div class="chart-card">
        <p class="chart-title">Litros de birra por tipo</p>
        <canvas id="chart-birra" height="200"></canvas>
      </div>
      <div class="chart-card">
        <p class="chart-title">Mix de categorias (% GMV)</p>
        <canvas id="chart-mix" height="200"></canvas>
      </div>
      <div class="chart-card">
        <p class="chart-title">GMV y ordenes por partido</p>
        <canvas id="chart-comp" height="200"></canvas>
      </div>
    </div>

    <div class="seccion">
      <p class="seccion-title">Promociones por partido</p>
      <table class="tabla">
        <thead><tr><th>Promo</th><th>Unidades</th><th>GMV</th><th>Locales activos</th><th></th></tr></thead>
        <tbody id="body-promos"></tbody>
      </table>
    </div>

    <div class="seccion">
      <p class="seccion-title">Ranking de productos</p>
      <div class="toggle-row">
        <button class="tbtn is-active" id="btn-unidades" onclick="setRankMode('unidades')">Por unidades</button>
        <button class="tbtn" id="btn-gmv" onclick="setRankMode('gmv')">Por GMV</button>
      </div>
      <select id="f-cat-rank" style="margin-bottom:1rem;background:var(--bg-elev);color:var(--fg);border:1px solid var(--rule);border-radius:6px;padding:.35rem .75rem;font-size:.85rem">
        <option value="">Todas las categorias</option>
      </select>
      <table class="tabla">
        <thead><tr><th>#</th><th>Producto</th><th>Categoria</th><th>Unidades</th><th>GMV</th><th></th></tr></thead>
        <tbody id="body-rank"></tbody>
      </table>
    </div>

    <div class="seccion">
      <p class="seccion-title">Resumen por partido</p>
      <table class="tabla">
        <thead><tr><th>Partido</th><th>Fecha</th><th>GMV</th><th>Ordenes</th><th>Ticket prom.</th><th>Litros birra</th><th>Top producto</th></tr></thead>
        <tbody id="body-comparativa"></tbody>
      </table>
    </div>
  </main>
</div>

<script>var DATA = {{ data_json | safe }};</script>
<!-- JS tasks 6-9 -->
</body>
</html>
```

- [ ] **Step 2: Verificar shell**

Recargar `http://localhost:8080`. Header "Mundial 2026" visible, filtros y secciones en blanco, sin errores JS en consola.

- [ ] **Step 3: Commit**

```bash
git add templates/tablero.html
git commit -m "feat: add tablero.html shell with header, filters, and sections"
```

---

### Task 6: JS engine, filtros y KPI cards

**Files:**
- Modify: `Proyecto_Mundial/templates/tablero.html` — reemplazar `<!-- JS tasks 6-9 -->`

- [ ] **Step 1: Reemplazar comentario con bloques JS**

```html
<script>
function renderCharts(o) {}
function renderPromos(o) {}
function renderRanking(o) {}
function renderComparativa() {}
</script>
<script>
function fmtPesos(v) {
  if (v >= 1e6) return '$' + (v/1e6).toFixed(1) + 'M';
  if (v >= 1e3) return '$' + (v/1e3).toFixed(0) + 'k';
  return '$' + Math.round(v);
}
function fmtDelta(pct) { return (pct >= 0 ? '+' : '') + (pct*100).toFixed(1) + '%'; }
function deltaClass(pct) { return pct >= 0 ? 'pos' : 'neg'; }

var rankMode = 'unidades';
function setRankMode(mode) {
  rankMode = mode;
  document.getElementById('btn-unidades').classList.toggle('is-active', mode === 'unidades');
  document.getElementById('btn-gmv').classList.toggle('is-active', mode === 'gmv');
  renderRanking(filtrar());
}

function filtrar() {
  var fP = document.getElementById('f-partido').value;
  var fM = document.getElementById('f-marca').value;
  var fL = document.getElementById('f-local').value;
  var fT = document.getElementById('f-turno').value;
  return DATA.ordenes.filter(function(o) {
    return (!fP || String(o.partido_id) === fP)
        && (!fM || o.marca === fM)
        && (!fL || o.local  === fL)
        && (!fT || o.turno  === fT);
  });
}
function filtrarNormales() {
  var fM = document.getElementById('f-marca').value;
  var fL = document.getElementById('f-local').value;
  var fT = document.getElementById('f-turno').value;
  return DATA.ordenes_normales.filter(function(o) {
    return (!fM || o.marca === fM) && (!fL || o.local === fL) && (!fT || o.turno === fT);
  });
}

function agregar(ordenes) {
  var gmv = 0, cant = 0, litros = 0, items = [];
  ordenes.forEach(function(o) {
    gmv += o.gmv; cant += 1;
    (o.items||[]).forEach(function(i) { litros += i.litros||0; items.push(i); });
  });
  return { gmv:gmv, cant:cant, ticket: cant>0 ? gmv/cant : 0, litros:litros, items:items };
}

function renderKPIs(ordenes, normales) {
  var kp = agregar(ordenes), kn = agregar(normales);
  function delta(a,b) { return b>0 ? (a-b)/b : 0; }
  var cards = [
    { label:'GMV Total',       val:fmtPesos(kp.gmv),            d:delta(kp.gmv,kn.gmv) },
    { label:'Ordenes',         val:kp.cant.toLocaleString(),    d:delta(kp.cant,kn.cant) },
    { label:'Ticket promedio', val:fmtPesos(kp.ticket),         d:delta(kp.ticket,kn.ticket) },
    { label:'Litros birra',    val:kp.litros.toFixed(1)+' L',   d:delta(kp.litros,kn.litros) },
  ];
  document.getElementById('kpi-row').innerHTML = cards.map(function(c) {
    return '<div class="kpi-card">'
      +'<div class="kpi-label">'+c.label+'</div>'
      +'<div class="kpi-val">'+c.val+'</div>'
      +'<div class="kpi-delta '+deltaClass(c.d)+'">'+fmtDelta(c.d)+' vs dia normal</div>'
      +'</div>';
  }).join('');
}

function actualizarLocales(ordenes) {
  var locales = [...new Set(ordenes.map(function(o){return o.local;}))].sort();
  var sel = document.getElementById('f-local'), cur = sel.value;
  sel.innerHTML = '<option value="">Todos los locales</option>';
  locales.forEach(function(l){ var o=document.createElement('option'); o.value=l; o.textContent=l; sel.appendChild(o); });
  if (locales.indexOf(cur)>=0) sel.value=cur;
}

function poblarFiltros() {
  var selP = document.getElementById('f-partido');
  DATA.partidos.forEach(function(p) {
    var o=document.createElement('option'); o.value=p.id; o.textContent=p.nombre+' ('+p.fecha+')'; selP.appendChild(o);
  });
  var marcas = [...new Set(DATA.ordenes.map(function(o){return o.marca;}))].sort();
  var selM = document.getElementById('f-marca');
  marcas.forEach(function(m){ var o=document.createElement('option'); o.value=m; o.textContent=m; selM.appendChild(o); });
  actualizarLocales(DATA.ordenes);
  var cats = [...new Set(DATA.ordenes.flatMap(function(o){
    return (o.items||[]).map(function(i){return i.categoria;}).filter(Boolean);
  }))].sort();
  var selCat = document.getElementById('f-cat-rank');
  cats.forEach(function(c){ var o=document.createElement('option'); o.value=c; o.textContent=c; selCat.appendChild(o); });
  if (DATA.generado_en)
    document.getElementById('lbl-actualizado').textContent='Actualizado: '+DATA.generado_en.slice(0,16).replace('T',' ');
}

function renderTodo() {
  var ord=filtrar(), nor=filtrarNormales();
  actualizarLocales(ord.length>0 ? ord : DATA.ordenes);
  renderKPIs(ord,nor); renderCharts(ord); renderPromos(ord); renderRanking(ord); renderComparativa();
}

['f-partido','f-marca','f-local','f-turno','f-cat-rank'].forEach(function(id){
  document.getElementById(id).addEventListener('change', renderTodo);
});
poblarFiltros(); renderTodo();
</script>
```

- [ ] **Step 2: Verificar KPI cards**

Recargar. 4 cards visibles. Con data vacia: `$0`, `0`, `$0`, `0.0 L`, todos `+0.0% vs dia normal`. Sin errores JS.

- [ ] **Step 3: Commit**

```bash
git add templates/tablero.html
git commit -m "feat: add JS filter engine and KPI cards"
```

---

### Task 7: Chart.js graficos

**Files:**
- Modify: `Proyecto_Mundial/templates/tablero.html` — reemplazar `function renderCharts(o) {}`

- [ ] **Step 1: Reemplazar stub renderCharts**

```html
<script>
var _charts={};
function destroyChart(id){ if(_charts[id]){_charts[id].destroy();delete _charts[id];} }
var FG='rgba(248,247,247,.65)', GRID='rgba(248,247,247,.08)';
var AX={ ticks:{color:FG,font:{size:11}}, grid:{color:GRID} };
var LEG={ labels:{color:FG,font:{size:11},boxWidth:12} };

function renderCharts(ordenes) {
  var items = ordenes.flatMap(function(o){return o.items||[];});

  destroyChart('chart-birra');
  var bMap={};
  items.filter(function(i){return i.litros>0;}).forEach(function(i){
    var t=i.tipo_cerveza||i.nombre||'Sin tipo'; bMap[t]=(bMap[t]||0)+i.litros;
  });
  var bL=Object.keys(bMap).sort(function(a,b){return bMap[b]-bMap[a];}).slice(0,8);
  _charts['chart-birra']=new Chart(document.getElementById('chart-birra'),{
    type:'bar',
    data:{labels:bL,datasets:[{label:'Litros',data:bL.map(function(k){return +bMap[k].toFixed(2);}),
      backgroundColor:'rgba(212,19,103,.5)',borderColor:'#D41367',borderWidth:1.5}]},
    options:{indexAxis:'y',responsive:true,plugins:{legend:{display:false}},
      scales:{x:AX,y:{ticks:{color:FG,font:{size:10}},grid:{color:GRID}}}}
  });

  destroyChart('chart-mix');
  var cMap={};
  items.forEach(function(i){var c=i.categoria||'Sin categoria'; cMap[c]=(cMap[c]||0)+(i.gmv||0);});
  var cL=Object.keys(cMap), cC=['#D41367','#18988B','#FFDD00','#3ad08f','#ff6b6b','#9b59b6'];
  _charts['chart-mix']=new Chart(document.getElementById('chart-mix'),{
    type:'doughnut',
    data:{labels:cL,datasets:[{data:cL.map(function(k){return +cMap[k].toFixed(0);}),
      backgroundColor:cC.slice(0,cL.length),borderWidth:0}]},
    options:{responsive:true,plugins:{legend:LEG,tooltip:{callbacks:{label:function(c){
      var tot=c.dataset.data.reduce(function(a,b){return a+b;},0);
      return c.label+': '+(tot>0?(c.parsed/tot*100).toFixed(1):0)+'%';
    }}}}}
  });

  destroyChart('chart-comp');
  var fM=document.getElementById('f-marca').value;
  var fL=document.getElementById('f-local').value;
  var fT=document.getElementById('f-turno').value;
  var cd=DATA.partidos.map(function(p){
    var ords=DATA.ordenes.filter(function(o){
      return o.partido_id===p.id&&(!fM||o.marca===fM)&&(!fL||o.local===fL)&&(!fT||o.turno===fT);
    });
    return {gmv:ords.reduce(function(s,o){return s+o.gmv;},0),cant:ords.length};
  });
  _charts['chart-comp']=new Chart(document.getElementById('chart-comp'),{
    type:'bar',
    data:{labels:DATA.partidos.map(function(p){return p.nombre;}),datasets:[
      {label:'GMV ($)',data:cd.map(function(d){return +d.gmv.toFixed(0);}),
        backgroundColor:'rgba(212,19,103,.5)',borderColor:'#D41367',borderWidth:1.5,yAxisID:'y'},
      {label:'Ordenes',data:cd.map(function(d){return d.cant;}),
        backgroundColor:'rgba(24,152,139,.5)',borderColor:'#18988B',borderWidth:1.5,yAxisID:'y1'}
    ]},
    options:{responsive:true,plugins:{legend:LEG},scales:{
      x:AX,
      y:{...AX,position:'left',ticks:{color:FG,font:{size:11},callback:function(v){return '$'+v;}}},
      y1:{...AX,position:'right',grid:{drawOnChartArea:false}}
    }}
  });
}
</script>
```

- [ ] **Step 2: Verificar graficos**

Recargar. 3 graficos renderizan. Cambiar filtros → graficos se actualizan. Sin errores JS.

- [ ] **Step 3: Commit**

```bash
git add templates/tablero.html
git commit -m "feat: add Chart.js graficos (birra, mix categorias, comparativo partidos)"
```

---

### Task 8: Tabla promociones + ranking de productos

**Files:**
- Modify: `Proyecto_Mundial/templates/tablero.html` — reemplazar stubs `renderPromos` y `renderRanking`

- [ ] **Step 1: Reemplazar stub renderPromos**

```html
<script>
function renderPromos(ordenes) {
  var pm={};
  ordenes.forEach(function(o){
    (o.items||[]).filter(function(i){return i.categoria&&i.categoria.toLowerCase().indexOf('promo')>=0;})
    .forEach(function(i){
      if(!pm[i.nombre]) pm[i.nombre]={nombre:i.nombre,unidades:0,gmv:0,locales:{}};
      pm[i.nombre].unidades+=i.cantidad||0; pm[i.nombre].gmv+=i.gmv||0; pm[i.nombre].locales[o.local]=true;
    });
  });
  var promos=Object.values(pm).sort(function(a,b){return b.gmv-a.gmv;});
  document.getElementById('body-promos').innerHTML = promos.length===0
    ? '<tr><td colspan="5" style="color:var(--fg-faint);text-align:center">Sin promociones en la seleccion actual</td></tr>'
    : promos.map(function(p,idx){
        var locs=Object.keys(p.locales).sort();
        return '<tr><td>'+p.nombre+'</td><td>'+p.unidades+'</td><td>'+fmtPesos(p.gmv)+'</td>'
          +'<td>'+locs.length+' local'+(locs.length!==1?'es':'')+'</td>'
          +'<td><span class="promo-expand" onclick="togglePromo('+idx+')">&#9658; Ver locales</span></td></tr>'
          +'<tbody class="promo-detail" id="promo-detail-'+idx+'">'
          +locs.map(function(l){return '<tr><td></td><td colspan="4" style="color:var(--fg-muted);padding-left:2rem">'+l+'</td></tr>';}).join('')
          +'</tbody>';
      }).join('');
}
function togglePromo(idx){
  var el=document.getElementById('promo-detail-'+idx); if(el) el.classList.toggle('open');
}
</script>
```

- [ ] **Step 2: Reemplazar stub renderRanking**

```html
<script>
function renderRanking(ordenes) {
  var fCat=document.getElementById('f-cat-rank').value, pm={};
  ordenes.forEach(function(o){
    (o.items||[]).filter(function(i){return !fCat||i.categoria===fCat;}).forEach(function(i){
      var k=i.producto_id||i.nombre;
      if(!pm[k]) pm[k]={nombre:i.nombre,categoria:i.categoria,unidades:0,gmv:0};
      pm[k].unidades+=i.cantidad||0; pm[k].gmv+=i.gmv||0;
    });
  });
  var top10=Object.values(pm).sort(function(a,b){
    return rankMode==='gmv'?b.gmv-a.gmv:b.unidades-a.unidades;
  }).slice(0,10);
  var maxVal=top10.length>0?(rankMode==='gmv'?top10[0].gmv:top10[0].unidades):1;
  document.getElementById('body-rank').innerHTML=top10.map(function(p,i){
    var val=rankMode==='gmv'?p.gmv:p.unidades, pct=Math.round(val/maxVal*100);
    return '<tr><td style="color:var(--fg-muted)">'+(i+1)+'</td><td>'+p.nombre+'</td>'
      +'<td style="color:var(--fg-muted)">'+(p.categoria||'&mdash;')+'</td>'
      +'<td>'+p.unidades+'</td><td>'+fmtPesos(p.gmv)+'</td>'
      +'<td style="width:100px"><div class="pbar-wrap"><div class="pbar" style="width:'+pct+'%"></div></div></td></tr>';
  }).join('');
}
</script>
```

- [ ] **Step 3: Verificar**

Toggle unidades/GMV reordena el ranking. Selector de categoria filtra. "Ver locales" en promos expande correctamente.

- [ ] **Step 4: Commit**

```bash
git add templates/tablero.html
git commit -m "feat: add tabla promociones con expand y ranking de productos"
```

---

### Task 9: Tabla comparativa entre partidos

**Files:**
- Modify: `Proyecto_Mundial/templates/tablero.html` — reemplazar stub `renderComparativa`

- [ ] **Step 1: Reemplazar stub renderComparativa**

```html
<script>
function renderComparativa() {
  var fM=document.getElementById('f-marca').value;
  var fL=document.getElementById('f-local').value;
  var fT=document.getElementById('f-turno').value;
  document.getElementById('body-comparativa').innerHTML=DATA.partidos.map(function(p){
    var ords=DATA.ordenes.filter(function(o){
      return o.partido_id===p.id&&(!fM||o.marca===fM)&&(!fL||o.local===fL)&&(!fT||o.turno===fT);
    });
    var gmv=ords.reduce(function(s,o){return s+o.gmv;},0);
    var cant=ords.length, ticket=cant>0?gmv/cant:0;
    var litros=ords.flatMap(function(o){return o.items||[];}).reduce(function(s,i){return s+(i.litros||0);},0);
    var pm={};
    ords.flatMap(function(o){return o.items||[];}).forEach(function(i){pm[i.nombre]=(pm[i.nombre]||0)+(i.cantidad||0);});
    var top=Object.entries(pm).sort(function(a,b){return b[1]-a[1];})[0];
    return '<tr><td><b>'+p.nombre+'</b></td>'
      +'<td style="color:var(--fg-faint);font-size:.8rem">'+p.fecha+'</td>'
      +'<td>'+fmtPesos(gmv)+'</td><td>'+cant.toLocaleString()+'</td><td>'+fmtPesos(ticket)+'</td>'
      +'<td>'+litros.toFixed(1)+' L</td>'
      +'<td style="font-size:.85rem">'+(top?top[0]+' ('+top[1]+' u.)':'&mdash;')+'</td></tr>';
  }).join('');
}
</script>
```

- [ ] **Step 2: Verificar**

Una fila por partido. Filtros de marca/local/turno actualizan los valores. Filtro de partido no aplica (siempre muestra todos).

- [ ] **Step 3: Commit**

```bash
git add templates/tablero.html
git commit -m "feat: add tabla comparativa entre partidos"
```

---

### Task 10: Deploy a Cloud Run

- [ ] **Step 1: Obtener Service Account de locales-propios**

```bash
gcloud run services describe locales-propios \
  --region us-central1 \
  --project temple-bar-439715 \
  --format="value(spec.template.spec.serviceAccountName)"
```

Anotar el SA (ej: `sa-locales@temple-bar-439715.iam.gserviceaccount.com`).

- [ ] **Step 2: Deploy**

```bash
cd "C:/Users/Darwin Salinas/Mi unidad/Claude_Cowork/Proyecto_Mundial"
gcloud run deploy mundial \
  --source . \
  --region us-central1 \
  --project temple-bar-439715 \
  --allow-unauthenticated \
  --service-account <SA_DEL_PASO_1> \
  --quiet
```

Expected: `Service URL: https://mundial-xxxx-uc.a.run.app`

- [ ] **Step 3: Subir primer JSON desde BQ**

Con `PARTIDOS` completados en `partidos.py`:

```bash
python -X utf8 generar_mundial.py
```

Expected:
```
Corriendo query BQ...
  -> XXXX filas
Ordenes en partidos:  XXX
Ordenes normales:     XXX
Subido a gs://temple-bar-439715/mundial/mundial_data.json
Listo.
```

- [ ] **Step 4: Verificar en produccion**

Abrir la URL de Cloud Run. Verificar:
- Header "Mundial 2026" con logo visible
- Filtros poblados con partidos y locales reales
- 4 KPI cards con valores numericos
- 3 graficos renderizan
- Tabla comparativa con una fila por partido

- [ ] **Step 5: Commit final**

```bash
git add -A
git commit -m "feat: mundial dashboard MVP completo"
```

---

## Mantenimiento post-partido

**Actualizar datos:**
```bash
python -X utf8 generar_mundial.py
```
No requiere redeploy. El proximo request carga el JSON actualizado.

**Forzar recarga sin restart:**
```
GET https://mundial-xxxx-uc.a.run.app/refresh
```

**Agregar partidos nuevos:** editar `PARTIDOS` en `partidos.py` y re-correr el script.
