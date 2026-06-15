# Tablero de Producto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una vista "Producto" al dashboard de ventas existente, accesible mediante un toggle Económico/Producto, con datos de litros vendidos por categoría de bebida obtenidos de `vw_curated_compilado_ok`.

**Architecture:** Opción A — extender el script y template existentes. Se agrega `fetch_producto_data()` a `actualizar_dashboard.py` para consultar `vw_curated_compilado_ok` e inyectar `__PRODUCTO_JSON__` en el template. El template `dashboard.html` recibe el toggle, el filtro de establecimiento, y la sección de producto completa con JS de renderizado.

**Tech Stack:** Python 3, google-cloud-bigquery, HTML/CSS/JS puro (sin Chart.js), SVG para donut chart, `actualizar_dashboard.py` (pipeline existente).

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `actualizar_dashboard.py` | Agregar `fetch_producto_data()`, extender `generate_html_from_file()` para aceptar e inyectar `producto_data`, llamar desde `main()` |
| `templates/dashboard.html` | Agregar toggle en header, filtro establecimiento en filterbar, wrappers de vista, sección producto completa (HTML + CSS + JS) |

---

## Task 1: Agregar `fetch_producto_data()` en `actualizar_dashboard.py`

**Files:**
- Modify: `actualizar_dashboard.py` (agregar función después de la última `fetch_*` existente, antes de `generate_html_from_file`)

- [ ] **Step 1: Agregar la función después de las funciones fetch existentes**

Insertar antes de `def generate_html_from_file(`:

```python
DATASET_CURATED = "curated_database"
TABLE_CURADO = "vw_curated_compilado_ok"

def fetch_producto_data(client, desde, hasta):
    """Consulta vw_curated_compilado_ok y retorna estructura JSON para la vista Producto."""
    from dateutil.relativedelta import relativedelta
    from datetime import date as _date

    d_desde   = _date.fromisoformat(desde)
    d_hasta   = _date.fromisoformat(hasta)
    dias      = (d_hasta - d_desde).days + 1

    # Mismo rango pero mes anterior y año anterior
    desde_m1  = (d_desde  - relativedelta(months=1)).isoformat()
    hasta_m1  = (d_hasta  - relativedelta(months=1)).isoformat()
    desde_y1  = (d_desde  - relativedelta(years=1)).isoformat()
    hasta_y1  = (d_hasta  - relativedelta(years=1)).isoformat()

    print(f"  [producto] Fetching {PROJECT_ID}.{DATASET_CURATED}.{TABLE_CURADO} ...")

    # ── Query 1: evolución diaria (período actual) ──────────────────────────
    q_evol = f"""
    SELECT
      CAST(fecha AS STRING) AS fecha,
      establecimiento,
      SUM(cerveza_total)  AS cerveza_lts,
      SUM(gin_total)      AS gin_lts,
      SUM(fernet_total)   AS fernet_lts,
      SUM(feriado_total)  AS feriado_lts,
      SUM(dinero)         AS pesos
    FROM `{PROJECT_ID}.{DATASET_CURADO}.{TABLE_CURADO}`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY fecha, establecimiento
    ORDER BY fecha, establecimiento
    """

    # ── Query 2: comparativos mes anterior y año anterior ───────────────────
    q_comp = f"""
    SELECT 'mes_ant' AS periodo,
      SUM(cerveza_total) AS c, SUM(gin_total) AS g,
      SUM(fernet_total)  AS f, SUM(feriado_total) AS fer
    FROM `{PROJECT_ID}.{DATASET_CURADO}.{TABLE_CURADO}`
    WHERE fecha BETWEEN '{desde_m1}' AND '{hasta_m1}'
    UNION ALL
    SELECT 'anio_ant' AS periodo,
      SUM(cerveza_total), SUM(gin_total),
      SUM(fernet_total),  SUM(feriado_total)
    FROM `{PROJECT_ID}.{DATASET_CURADO}.{TABLE_CURADO}`
    WHERE fecha BETWEEN '{desde_y1}' AND '{hasta_y1}'
    """

    # ── Query 3: ranking de productos + mix tipo ────────────────────────────
    q_rank = f"""
    SELECT
      producto, categoria, mix, familia_producto, establecimiento,
      SUM(cantidad)   AS cantidad,
      SUM(dinero)     AS facturacion
    FROM `{PROJECT_ID}.{DATASET_CURADO}.{TABLE_CURADO}`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY producto, categoria, mix, familia_producto, establecimiento
    ORDER BY facturacion DESC
    LIMIT 500
    """

    # ── Query 4: cross table por establecimiento ────────────────────────────
    q_cross = f"""
    SELECT
      establecimiento,
      SUM(cerveza_total)  AS cerveza_lts,
      SUM(gin_total)      AS gin_lts,
      SUM(fernet_total)   AS fernet_lts,
      SUM(feriado_total)  AS feriado_lts,
      SUM(dinero)         AS total_pesos
    FROM `{PROJECT_ID}.{DATASET_CURADO}.{TABLE_CURADO}`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY establecimiento
    ORDER BY total_pesos DESC
    """

    rows_evol  = list(client.query(q_evol).result())
    rows_comp  = list(client.query(q_comp).result())
    rows_rank  = list(client.query(q_rank).result())
    rows_cross = list(client.query(q_cross).result())

    # ── Evolución diaria (red completa = sum de todos los establecimientos) ─
    evol_dict = {}  # fecha → {cerveza, gin, fernet, feriado}
    for r in rows_evol:
        ev = evol_dict.setdefault(r.fecha, {'cerveza_lts': 0, 'gin_lts': 0, 'fernet_lts': 0, 'feriado_lts': 0})
        ev['cerveza_lts']  += r.cerveza_lts  or 0
        ev['gin_lts']      += r.gin_lts      or 0
        ev['fernet_lts']   += r.fernet_lts   or 0
        ev['feriado_lts']  += r.feriado_lts  or 0
    evolucion = [{'fecha': f, **v} for f, v in sorted(evol_dict.items())]
    # Redondear a 1 decimal
    for e in evolucion:
        for k in ('cerveza_lts', 'gin_lts', 'fernet_lts', 'feriado_lts'):
            e[k] = round(e[k], 1)

    # ── KPIs actuales (suma total) ──────────────────────────────────────────
    kpi_actual = {'cerveza': 0.0, 'gin': 0.0, 'fernet': 0.0, 'feriado': 0.0}
    for e in evolucion:
        kpi_actual['cerveza']  += e['cerveza_lts']
        kpi_actual['gin']      += e['gin_lts']
        kpi_actual['fernet']   += e['fernet_lts']
        kpi_actual['feriado']  += e['feriado_lts']

    # ── KPIs comparativos ──────────────────────────────────────────────────
    comp = {}
    for r in rows_comp:
        comp[r.periodo] = {
            'cerveza': round(r.c   or 0, 1),
            'gin':     round(r.g   or 0, 1),
            'fernet':  round(r.f   or 0, 1),
            'feriado': round(r.fer or 0, 1),
        }

    kpis = {}
    for cat in ('cerveza', 'gin', 'fernet', 'feriado'):
        kpis[cat] = {
            'lts_actual':   round(kpi_actual[cat], 1),
            'lts_mes_ant':  comp.get('mes_ant',  {}).get(cat, 0),
            'lts_anio_ant': comp.get('anio_ant', {}).get(cat, None),
        }

    # ── Mix por categoría de líquido ────────────────────────────────────────
    total_lts = sum(kpi_actual.values()) or 1
    mix_lts = [
        {'cat': label, 'color': color,
         'lts': round(kpi_actual[key], 1),
         'pct': round(kpi_actual[key] / total_lts * 100, 1)}
        for key, label, color in (
            ('cerveza', 'Cerveza', '#f59e0b'),
            ('gin',     'Gin',     '#818cf8'),
            ('fernet',  'Fernet',  '#34d399'),
            ('feriado', 'Feriado', '#f472b6'),
        )
    ]

    # ── Ranking de productos (red completa) ─────────────────────────────────
    # Agregar por producto+categoria+mix (sin establecimiento)
    rank_dict = {}
    for r in rows_rank:
        key = (r.producto or '', r.categoria or '', r.mix or '')
        entry = rank_dict.setdefault(key, {'producto': r.producto or '', 'categoria': r.categoria or '', 'mix': r.mix or '', 'cantidad': 0, 'facturacion': 0.0})
        entry['cantidad']    += int(r.cantidad    or 0)
        entry['facturacion'] += float(r.facturacion or 0)
    total_fac = sum(e['facturacion'] for e in rank_dict.values()) or 1
    ranking = sorted(rank_dict.values(), key=lambda x: -x['facturacion'])[:50]
    for item in ranking:
        item['facturacion'] = round(item['facturacion'], 0)
        item['pct_fac']     = round(item['facturacion'] / total_fac * 100, 1)

    # ── Mix de venta por tipo (Bebida/Comida/Promoción/Merch) ───────────────
    tipo_colors = {'Bebida': '#58a6ff', 'Comida': '#fb923c', 'Promocion': '#a78bfa', 'Promoción': '#a78bfa', 'Merch': '#6ee7b7'}
    tipo_dict = {}
    for r in rows_rank:
        tipo = r.mix or 'Otros'
        tipo_dict[tipo] = tipo_dict.get(tipo, 0.0) + float(r.facturacion or 0)
    total_tipo = sum(tipo_dict.values()) or 1
    mix_tipo = sorted([
        {'label': k, 'monto': round(v, 0),
         'pct':   round(v / total_tipo * 100, 1),
         'color': tipo_colors.get(k, '#8b949e')}
        for k, v in tipo_dict.items()
    ], key=lambda x: -x['monto'])

    # ── Top 5 productos por categoría de líquido ────────────────────────────
    top_por_cat = {}
    for key, label in (('cerveza', 'cerveza'), ('gin', 'gin'), ('fernet', 'fernet'), ('feriado', 'feriado')):
        cat_rows = sorted(
            [r for r in rows_rank if key in (r.familia_producto or '').lower() or key in (r.categoria or '').lower()],
            key=lambda r: -(r.facturacion or 0)
        )
        # Agregar por producto (sin establecimiento)
        agg = {}
        for r in cat_rows:
            p = r.producto or ''
            agg[p] = agg.get(p, 0.0) + float(r.facturacion or 0)
        top5 = sorted(agg.items(), key=lambda x: -x[1])[:5]
        max_fac = top5[0][1] if top5 else 1
        top_por_cat[key] = [{'nombre': n, 'pct': round(f / max_fac * 100, 0)} for n, f in top5]

    # ── Cross table por establecimiento ─────────────────────────────────────
    cross = []
    for r in rows_cross:
        c_l   = r.cerveza_lts  or 0
        g_l   = r.gin_lts      or 0
        f_l   = r.fernet_lts   or 0
        fer_l = r.feriado_lts  or 0
        total = r.total_pesos  or 0
        total_liq = c_l + g_l + f_l + fer_l or 1
        cross.append({
            'est':          r.establecimiento,
            'cerveza_lts':  round(c_l,   1),
            'gin_lts':      round(g_l,   1),
            'fernet_lts':   round(f_l,   1),
            'feriado_lts':  round(fer_l, 1),
            'total_lts':    round(total_liq, 1),
            'cerveza_$':    round(total * c_l   / total_liq, 0),
            'gin_$':        round(total * g_l   / total_liq, 0),
            'fernet_$':     round(total * f_l   / total_liq, 0),
            'feriado_$':    round(total * fer_l / total_liq, 0),
            'total_$':      round(total, 0),
        })

    establecimientos = [r['est'] for r in cross if r['est']]

    print(f"  [producto] ✓ evolucion={len(evolucion)} días, ranking={len(ranking)} productos, cross={len(cross)} establecimientos")

    return {
        'kpis':            kpis,
        'mix_lts':         mix_lts,
        'ranking':         ranking,
        'cross':           cross,
        'mix_tipo':        mix_tipo,
        'evolucion':       evolucion,
        'top_por_cat':     top_por_cat,
        'establecimientos': establecimientos,
    }
```

- [ ] **Step 2: Verificar que `python-dateutil` esté disponible**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
python -c "from dateutil.relativedelta import relativedelta; print('OK')"
```

Si falla: `pip install python-dateutil`

- [ ] **Step 3: Probar la función aislada**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
python -X utf8 -c "
from actualizar_dashboard import get_bigquery_client, fetch_producto_data
client = get_bigquery_client()
data = fetch_producto_data(client, '2026-04-01', '2026-04-21')
import json; print(json.dumps(data, indent=2, default=str)[:2000])
"
```

Esperado: JSON con keys `kpis`, `mix_lts`, `ranking`, `cross`, `mix_tipo`, `evolucion`, `top_por_cat`, `establecimientos`.

---

## Task 2: Extender `generate_html_from_file()` y `main()` para inyectar `__PRODUCTO_JSON__`

**Files:**
- Modify: `actualizar_dashboard.py` línea 733 (firma de `generate_html_from_file`) y línea 890 (bloque de inyecciones) y línea 970 (llamada en `main`)

- [ ] **Step 1: Agregar parámetro `producto_data=None` a la firma de `generate_html_from_file`**

Cambiar:
```python
def generate_html_from_file(data, output_path, gcs_bucket='',
                             mensual_rows=None, turnos_rows=None,
                             canal_rows=None, top10_data=None,
                             pd_data=None, preset_meses=None,
                             objetivos_data=None, royalty_data=None,
                             locales_obj_data=None,
                             loc_count_by_mes=None):
```
Por:
```python
def generate_html_from_file(data, output_path, gcs_bucket='',
                             mensual_rows=None, turnos_rows=None,
                             canal_rows=None, top10_data=None,
                             pd_data=None, preset_meses=None,
                             objetivos_data=None, royalty_data=None,
                             locales_obj_data=None,
                             loc_count_by_mes=None,
                             producto_data=None):
```

- [ ] **Step 2: Agregar inyección de `__PRODUCTO_JSON__` en el bloque de inyecciones**

Después de la línea `html = html.replace('__LOC_COUNT_BY_MES_JSON__', ...)`, agregar:

```python
    if '__PRODUCTO_JSON__' in html:
        pd_json = producto_data or {}
        html = html.replace('__PRODUCTO_JSON__', json.dumps(pd_json, separators=(',', ':'), default=str))
        print(f"  ✓ PRODUCTO_JSON inyectado ({len(pd_json.get('ranking', []))} productos, {len(pd_json.get('evolucion', []))} días)")
```

- [ ] **Step 3: Agregar la llamada a `fetch_producto_data` en `main()` y pasar el resultado**

En `main()`, después de la línea `loc_count_by_mes = fetch_loc_count_by_mes(client)`:

```python
        # Fetch datos de producto desde vw_curated_compilado_ok
        try:
            producto_data = fetch_producto_data(client, args.desde, args.hasta)
        except Exception as exc:
            print(f"  ⚠ fetch_producto_data falló: {exc} — vista Producto sin datos")
            producto_data = {}
```

Y en la llamada a `generate_html_from_file(...)`, agregar `producto_data=producto_data,`:

```python
        generate_html_from_file(
            data_for_insights, args.output, gcs_bucket=args.gcs_bucket,
            mensual_rows=mensual_rows, turnos_rows=turnos_rows,
            canal_rows=canal_rows,      top10_data=top10_data,
            pd_data=pd_data,            preset_meses=preset_meses,
            objetivos_data=objetivos_data, royalty_data=royalty_data,
            locales_obj_data=locales_obj_data,
            loc_count_by_mes=loc_count_by_mes,
            producto_data=producto_data,
        )
```

- [ ] **Step 4: Verificar que el script corre sin errores**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
python -X utf8 actualizar_dashboard.py --output test_producto_output.html
```

Esperado: línea `✓ PRODUCTO_JSON inyectado` en la salida. El archivo `test_producto_output.html` debe contener `__PRODUCTO_JSON__` reemplazado (verificar con grep).

```bash
grep -c "__PRODUCTO_JSON__" test_producto_output.html
```
Esperado: `0` (placeholder reemplazado, no queda ninguno).

---

## Task 3: Agregar toggle y CSS de la vista Producto en `templates/dashboard.html`

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Agregar estilos CSS del toggle y la vista producto**

En el bloque `<style>`, antes de `</style>`, agregar:

```css
/* ══ TOGGLE ECONÓMICO / PRODUCTO ══════════════════════════════════ */
.view-toggle{display:flex;gap:0;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:4px;width:fit-content;flex-shrink:0}
.view-btn{padding:7px 22px;border-radius:7px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:all .18s ease;background:transparent;color:#8b949e}
.view-btn.vb-active{background:#58a6ff;color:#0d1117}
.view-btn:not(.vb-active):hover{color:#e6edf3;background:#21262d}

/* Wrappers de vista */
#view-economico{display:block}
#view-producto{display:none}

/* ══ VISTA PRODUCTO — layout ════════════════════════════════════════ */
.pd-kpi-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.pd-kpi-card{flex:1;min-width:200px;background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px 20px;border-top:3px solid;display:flex;flex-direction:column;gap:10px}
.pd-kpi-card.pd-cerveza{border-top-color:#f59e0b}
.pd-kpi-card.pd-gin    {border-top-color:#818cf8}
.pd-kpi-card.pd-fernet {border-top-color:#34d399}
.pd-kpi-card.pd-feriado{border-top-color:#f472b6}
.pd-kpi-icon-row{display:flex;align-items:center;gap:10px}
.pd-kpi-icon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.pd-kpi-icon.pd-cerveza{background:rgba(245,158,11,.15)}
.pd-kpi-icon.pd-gin    {background:rgba(129,140,248,.15)}
.pd-kpi-icon.pd-fernet {background:rgba(52,211,153,.15)}
.pd-kpi-icon.pd-feriado{background:rgba(244,114,182,.15)}
.pd-kpi-title{font-size:11px;color:#8b949e;font-weight:700;letter-spacing:.4px;text-transform:uppercase}
.pd-kpi-val{font-size:32px;font-weight:900;letter-spacing:-1px;line-height:1}
.pd-kpi-unit{font-size:13px;font-weight:600;color:#8b949e;margin-left:2px}
.pd-subcard{background:#0d1117;border-radius:8px;padding:8px 12px;display:flex;flex-direction:column;gap:4px}
.pd-subcard-lbl{font-size:10px;color:#8b949e;font-weight:600;letter-spacing:.3px;text-transform:uppercase}
.pd-subcard-val{font-size:15px;font-weight:800}
.pd-subcard-val.pd-green{color:#6ee7b7}
.pd-subcard-val.pd-red{color:#f87171}
.pd-subcard-val.pd-pending{color:#484f58;font-style:italic;font-size:11px;font-weight:400}
.pd-subcard-sub{font-size:10px;color:#8b949e}
.pd-comps{display:flex;gap:12px}
.pd-comp-lbl{font-size:9px;color:#6e7681;font-weight:600;letter-spacing:.3px;text-transform:uppercase;margin-bottom:2px}
.pd-comp-val{font-size:12px;font-weight:700}
.pd-comp-val.up{color:#6ee7b7}
.pd-comp-val.dn{color:#f87171}
.pd-comp-val.na{color:#484f58}

/* Section card (reutiliza .card de ventas pero sin margin conflicts) */
.pd-card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px 24px;margin-bottom:16px}
.pd-title{font-size:13px;font-weight:700;letter-spacing:.3px;text-transform:uppercase;color:#8b949e;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.pd-title span{color:#e6edf3}

/* Mix por categoría — barras horizontales */
.pd-mix-row{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.pd-mix-lbl{width:80px;font-size:12px;font-weight:600;color:#e6edf3;flex-shrink:0;text-align:right}
.pd-mix-track{flex:1;background:#21262d;border-radius:4px;height:22px;overflow:hidden}
.pd-mix-fill{height:100%;border-radius:4px;display:flex;align-items:center;padding-left:8px;font-size:11px;font-weight:700;color:#0d1117;white-space:nowrap}
.pd-mix-pct{width:46px;font-size:12px;font-weight:700;text-align:right;flex-shrink:0}
.pd-mix-lts{width:80px;font-size:11px;color:#8b949e;text-align:right;flex-shrink:0}

/* Ranking tabla */
.pd-rank-btn{background:#21262d;border:1px solid #30363d;border-radius:6px;color:#8b949e;font-size:11px;font-weight:600;padding:5px 12px;cursor:pointer;transition:all .15s}
.pd-rank-btn.pd-active{background:#58a6ff;color:#0d1117;border-color:#58a6ff}
.pd-rank-btn:not(.pd-active):hover{color:#e6edf3;border-color:#484f58}
.pd-table{width:100%;border-collapse:collapse;font-size:12px}
.pd-table th{font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#8b949e;padding:8px 12px;border-bottom:1px solid #30363d;text-align:right;white-space:nowrap}
.pd-table th:nth-child(-n+3){text-align:left}
.pd-table td{padding:9px 12px;border-bottom:1px solid #21262d;text-align:right;vertical-align:middle}
.pd-table td:first-child{text-align:left;color:#8b949e;font-weight:700;width:28px}
.pd-table td:nth-child(2){text-align:left;font-weight:600}
.pd-table td:nth-child(3){text-align:left}
.pd-table tbody tr:hover{background:#1c2128}
.pd-chip{display:inline-block;font-size:10px;font-weight:700;border-radius:4px;padding:2px 7px}

/* Comparativa cross-table */
.pd-cross-toggle{display:flex;gap:6px}

/* Donut SVG */
.pd-donut-wrap{position:relative;flex-shrink:0;width:200px;height:200px}
.pd-donut-center{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;pointer-events:none}

/* Evolución barras */
.pd-evol-wrap{display:flex;gap:0;align-items:stretch}
.pd-evol-yaxis{display:flex;flex-direction:column-reverse;justify-content:space-between;padding-right:8px;min-width:36px;text-align:right;padding-bottom:20px}
.pd-evol-area{flex:1;position:relative}
.pd-evol-grid{position:absolute;inset:0;bottom:20px;display:flex;flex-direction:column-reverse;justify-content:space-between;pointer-events:none}
.pd-evol-bars{display:flex;gap:4px;align-items:flex-end;height:150px;position:relative;z-index:1}
.pd-evol-xaxis{display:flex;gap:4px;margin-top:4px}

/* Top por categoría */
.pd-top-grid{display:flex;gap:12px;flex-wrap:wrap}
.pd-top-cat{background:#0d1117;border-radius:10px;padding:14px 16px;flex:1;min-width:180px}
.pd-top-cat-title{font-size:11px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;margin-bottom:10px}

/* VS mes anterior cards */
.pd-vsmes-grid{display:flex;gap:12px;flex-wrap:wrap}
.pd-vsmes-card{background:#0d1117;border-radius:10px;padding:16px 20px;flex:1;min-width:160px;display:flex;flex-direction:column;gap:8px}

/* Filtro establecimiento en filterbar */
.pd-est-filter{display:none}
select.pd-est-select{background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#e6edf3;font-size:12px;padding:5px 9px;cursor:pointer;min-width:180px}
select.pd-est-select:focus{outline:none;border-color:#58a6ff}
.pd-filter-badge{font-size:9px;font-weight:700;background:#1a3a1a;color:#6ee7b7;border:1px solid rgba(110,231,183,.3);border-radius:4px;padding:1px 5px;margin-left:6px;vertical-align:middle}
```

- [ ] **Step 2: Agregar el toggle al header (línea 257, después de `</div>` de cierre del `.hdr`)**

Cambiar:
```html
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <span class="data-badge __BADGE_CLASS__" title="Último registro en BigQuery: __LAST_DATA_DATE__">
      <span class="dot"></span>
      Datos al __LAST_DATA_DATE__ &middot; __DAYS_STALE_LABEL__
    </span>
  </div>
</div>
```

Por:
```html
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <span class="data-badge __BADGE_CLASS__" title="Último registro en BigQuery: __LAST_DATA_DATE__">
      <span class="dot"></span>
      Datos al __LAST_DATA_DATE__ &middot; __DAYS_STALE_LABEL__
    </span>
    <div class="view-toggle" id="mainViewToggle">
      <button class="view-btn vb-active" onclick="switchMainView('economico',this)">Económico</button>
      <button class="view-btn" onclick="switchMainView('producto',this)">Producto</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Agregar filtro de establecimiento al final de la filterbar (antes del `</div>` de cierre de `.filterbar`, línea 296)**

Cambiar:
```html
  <div style="margin-left:auto;font-size:11px;color:#8b949e" id="filterLabel">Mostrando: <strong style="color:#e6edf3">Todas las marcas &middot; Todo el período</strong></div>
</div>
```

Por:
```html
  <div style="margin-left:auto;font-size:11px;color:#8b949e" id="filterLabel">Mostrando: <strong style="color:#e6edf3">Todas las marcas &middot; Todo el período</strong></div>
  <div class="pd-est-filter" id="pdEstFilter">
    <div class="filter-group">
      <div class="filter-label">&#128205; ESTABLECIMIENTO <span class="pd-filter-badge">PROD</span></div>
      <select class="pd-est-select" id="pdEstSelect" onchange="renderProductoView()">
        <option value="">Todos los establecimientos</option>
      </select>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Envolver todo el contenido económico y agregar contenedor de producto**

Después del `</div>` de cierre de la filterbar (línea 296), agregar `<div id="view-economico">`.

Antes del `<div class="footer">` (línea 520), agregar `</div>` (cierre del `view-economico`) y el bloque de la vista producto:

```html
</div><!-- /view-economico -->

<!-- ═══════════════════════════════════════════════════════════════
     VISTA PRODUCTO
     ═══════════════════════════════════════════════════════════════ -->
<div id="view-producto">

  <!-- KPI Cards: litros por categoría -->
  <div class="pd-kpi-row" id="pd-kpis"></div>

  <!-- Mix por categoría (barras horizontales) -->
  <div class="pd-card">
    <div class="pd-title">&#127866; <span>Mix por Categoría</span> &nbsp;·&nbsp; Litros en el período</div>
    <div id="pd-mix-lts"></div>
  </div>

  <!-- Ranking de productos -->
  <div class="pd-card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px">
      <div class="pd-title" style="margin-bottom:0">&#127942; <span>Ranking de Productos</span> &nbsp;·&nbsp; Ordenado por facturación</div>
    </div>
    <div style="overflow-x:auto">
      <table class="pd-table">
        <thead>
          <tr>
            <th style="text-align:left">#</th>
            <th style="text-align:left">Producto</th>
            <th style="text-align:left">Categoría</th>
            <th>Cantidad</th>
            <th>Facturación</th>
            <th>% Fac.</th>
          </tr>
        </thead>
        <tbody id="pd-ranking-body"></tbody>
      </table>
    </div>
  </div>

  <!-- Comparativa por establecimiento (tabla cruzada) -->
  <div class="pd-card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px">
      <div class="pd-title" style="margin-bottom:0">&#128205; <span>Comparativa por Tipo &middot; Establecimientos</span></div>
      <div class="pd-cross-toggle">
        <button class="pd-rank-btn pd-active" id="pd-cross-btn-lts" onclick="switchCrossMode('lts',this)">Litros</button>
        <button class="pd-rank-btn" id="pd-cross-btn-pesos" onclick="switchCrossMode('pesos',this)">Facturación</button>
      </div>
    </div>
    <div style="overflow-x:auto">
      <table class="pd-table">
        <thead>
          <tr>
            <th style="text-align:left">Establecimiento</th>
            <th style="color:#f59e0b">&#127866; Cerveza</th>
            <th style="color:#818cf8">&#127864; Gin</th>
            <th style="color:#34d399">&#129347; Fernet</th>
            <th style="color:#f472b6">&#127865; Feriado</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody id="pd-cross-body"></tbody>
      </table>
    </div>
  </div>

  <!-- Mix de venta por tipo (donut SVG) -->
  <div class="pd-card">
    <div class="pd-title">&#129379; <span>Mix de Venta por Tipo</span> &nbsp;·&nbsp; % del total facturado</div>
    <div style="display:flex;align-items:center;gap:48px;flex-wrap:wrap;justify-content:center">
      <div class="pd-donut-wrap">
        <svg id="pd-donut-svg" viewBox="0 0 200 200" width="200" height="200" style="transform:rotate(-90deg)"></svg>
        <div class="pd-donut-center">
          <div style="font-size:10px;color:#8b949e;font-weight:700;letter-spacing:.5px;text-transform:uppercase">TOTAL</div>
          <div style="font-size:22px;font-weight:900;color:#e6edf3;line-height:1.1">100%</div>
        </div>
      </div>
      <div id="pd-torta-legend" style="flex:1;min-width:220px;max-width:380px"></div>
    </div>
  </div>

  <!-- Evolución en el tiempo -->
  <div class="pd-card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;flex-wrap:wrap;gap:8px">
      <div class="pd-title" style="margin-bottom:0">&#128200; <span>Evolución en el Tiempo</span> &nbsp;·&nbsp; Litros por día</div>
      <div style="display:flex;gap:14px;font-size:11px;font-weight:600;flex-wrap:wrap">
        <span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#f59e0b;border-radius:3px;display:inline-block"></span>Cerveza</span>
        <span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#818cf8;border-radius:3px;display:inline-block"></span>Gin</span>
        <span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#34d399;border-radius:3px;display:inline-block"></span>Fernet</span>
        <span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#f472b6;border-radius:3px;display:inline-block"></span>Feriado</span>
      </div>
    </div>
    <div class="pd-evol-wrap">
      <div class="pd-evol-yaxis" id="pd-evol-yaxis"></div>
      <div class="pd-evol-area">
        <div class="pd-evol-grid" id="pd-evol-grid"></div>
        <div class="pd-evol-bars" id="pd-evol-bars"></div>
        <div class="pd-evol-xaxis" id="pd-evol-xaxis"></div>
      </div>
    </div>
  </div>

  <!-- Top productos por categoría -->
  <div class="pd-card">
    <div class="pd-title">&#128285; <span>Top Productos por Categoría</span></div>
    <div class="pd-top-grid" id="pd-top-cat"></div>
  </div>

  <!-- Comparativa vs mes anterior -->
  <div class="pd-card">
    <div class="pd-title">&#128202; <span>Comparativa vs Mes Anterior</span> &nbsp;·&nbsp; Litros por categoría</div>
    <div class="pd-vsmes-grid" id="pd-vsmes"></div>
  </div>

</div><!-- /view-producto -->
```

---

## Task 4: Agregar JS de la vista Producto en `templates/dashboard.html`

**Files:**
- Modify: `templates/dashboard.html` (agregar al final del bloque `<script>`, antes del cierre `</script>`)

- [ ] **Step 1: Agregar datos y funciones de renderizado**

Al final del bloque `<script>` existente (buscar `</script>` que cierra el JS principal), agregar antes del cierre `</script>`:

```javascript
// ═══════════════════════════════════════════════════════════════
// VISTA PRODUCTO
// ═══════════════════════════════════════════════════════════════
const PROD = __PRODUCTO_JSON__;

var _pdCrossMode = 'lts';

// Formateadores
function pdFmtLts(n){ return n >= 1000 ? (n/1000).toFixed(1)+'K lts' : (n||0)+' lts'; }
function pdFmtPesos(n){ return '$' + (n >= 1000000 ? (n/1000000).toFixed(1)+'M' : (n >= 1000 ? (n/1000).toFixed(0)+'K' : (n||0))); }
function pdFmtCant(n){ return n >= 1000 ? (n/1000).toFixed(1)+'K' : (n||0); }
function pdPct(a, b){ if (!b) return '—'; var p = ((a-b)/b*100); return (p>=0?'+':'')+p.toFixed(1)+'%'; }
function pdPctClass(a, b){ if (!b) return 'na'; return a >= b ? 'up' : 'dn'; }

// Obtener establecimiento seleccionado
function pdGetEst(){ return (document.getElementById('pdEstSelect')||{}).value || ''; }

// Filtrar datos de evolución por establecimiento
function pdFilterEvol(est){
  if (!est) return PROD.evolucion;
  // Si hay datos desagregados por establecimiento en la evolución, filtrar
  // De lo contrario retornar red completa (fetch_producto_data agrega por red)
  return PROD.evolucion;
}

// Filtrar datos de ranking por establecimiento
function pdFilterRanking(est){
  if (!est) return PROD.ranking;
  return PROD.ranking; // En v1 el ranking es red; drill-down por establecimiento en v2
}

// ── Poblar selector de establecimientos ─────────────────────────────────
function pdPopulateEstSelect(){
  var sel = document.getElementById('pdEstSelect');
  if (!sel || !PROD.establecimientos) return;
  sel.innerHTML = '<option value="">Todos los establecimientos</option>';
  PROD.establecimientos.forEach(function(e){
    sel.innerHTML += '<option value="'+e+'">'+e+'</option>';
  });
}

// ── Render KPI Cards ─────────────────────────────────────────────────────
function pdRenderKPIs(){
  var el = document.getElementById('pd-kpis');
  if (!el || !PROD.kpis) return;
  var cats = [
    {key:'cerveza', label:'Cerveza', icon:'🍺', cls:'pd-cerveza'},
    {key:'gin',     label:'Gin',     icon:'🍸', cls:'pd-gin'},
    {key:'fernet',  label:'Fernet',  icon:'🥃', cls:'pd-fernet'},
    {key:'feriado', label:'Feriado', icon:'🍹', cls:'pd-feriado'},
  ];
  el.innerHTML = '';
  cats.forEach(function(c){
    var kpi = PROD.kpis[c.key] || {};
    var actual   = kpi.lts_actual   || 0;
    var mes_ant  = kpi.lts_mes_ant  || 0;
    var anio_ant = kpi.lts_anio_ant;

    var vsObjHtml = '<div class="pd-subcard-val pd-pending">— Pendiente definición</div>';

    var vsMesVal = pdPct(actual, mes_ant);
    var vsMesCls = 'pd-comp-val ' + pdPctClass(actual, mes_ant);

    var vsAnioVal, vsAnioCls;
    if (anio_ant === null || anio_ant === undefined) {
      vsAnioVal = '— Sin dato'; vsAnioCls = 'pd-comp-val na';
    } else {
      vsAnioVal = pdPct(actual, anio_ant);
      vsAnioCls = 'pd-comp-val ' + pdPctClass(actual, anio_ant);
    }

    el.innerHTML +=
      '<div class="pd-kpi-card '+c.cls+'">'
        +'<div class="pd-kpi-icon-row">'
          +'<div class="pd-kpi-icon '+c.cls+'">'+c.icon+'</div>'
          +'<span class="pd-kpi-title">'+c.label+'</span>'
        +'</div>'
        +'<div><span class="pd-kpi-val">'+(actual>=1000?(actual/1000).toFixed(1):''+actual)+'</span>'
          +'<span class="pd-kpi-unit">'+(actual>=1000?'K lts':'lts')+'</span></div>'
        +'<div class="pd-subcard">'
          +'<div class="pd-subcard-lbl">VS OBJETIVO</div>'
          +vsObjHtml
        +'</div>'
        +'<div class="pd-comps">'
          +'<div><div class="pd-comp-lbl">VS MES ANT.</div><div class="'+vsMesCls+'">'+vsMesVal+'</div></div>'
          +'<div><div class="pd-comp-lbl">VS AÑO ANT.</div><div class="'+vsAnioCls+'">'+vsAnioVal+'</div></div>'
        +'</div>'
      +'</div>';
  });
}

// ── Render Mix por Categoría ─────────────────────────────────────────────
function pdRenderMixLts(){
  var el = document.getElementById('pd-mix-lts');
  if (!el || !PROD.mix_lts) return;
  var maxPct = Math.max.apply(null, PROD.mix_lts.map(function(m){ return m.pct; })) || 1;
  el.innerHTML = '';
  PROD.mix_lts.forEach(function(m){
    var barW = Math.max((m.pct / maxPct) * 100, 2);
    var ltsLabel = m.lts >= 1000 ? (m.lts/1000).toFixed(1)+'K' : m.lts;
    el.innerHTML +=
      '<div class="pd-mix-row">'
        +'<div class="pd-mix-lbl">'+m.cat+'</div>'
        +'<div class="pd-mix-track">'
          +'<div class="pd-mix-fill" style="width:'+barW+'%;background:'+m.color+'">'+ltsLabel+' lts</div>'
        +'</div>'
        +'<div class="pd-mix-pct" style="color:'+m.color+'">'+m.pct+'%</div>'
        +'<div class="pd-mix-lts">'+(m.lts>=1000?(m.lts/1000).toFixed(1)+'K':m.lts)+' lts</div>'
      +'</div>';
  });
}

// ── Render Ranking ───────────────────────────────────────────────────────
function pdRenderRanking(){
  var tbody = document.getElementById('pd-ranking-body');
  if (!tbody) return;
  var data = pdFilterRanking(pdGetEst());
  var catColors = {'Bebida':'#58a6ff','Comida':'#fb923c','Promoción':'#a78bfa','Promocion':'#a78bfa','Merch':'#6ee7b7'};
  tbody.innerHTML = '';
  data.forEach(function(r, i){
    var cc = catColors[r.mix] || catColors[r.categoria] || '#8b949e';
    var barW = Math.max(r.pct_fac * 2, 3);
    tbody.innerHTML +=
      '<tr>'
        +'<td>'+(i+1)+'</td>'
        +'<td>'+r.producto+'</td>'
        +'<td><span class="pd-chip" style="background:'+cc+'22;color:'+cc+'">'+r.mix+'</span></td>'
        +'<td>'+pdFmtCant(r.cantidad)+'</td>'
        +'<td style="color:'+cc+';font-weight:700">'+pdFmtPesos(r.facturacion)+'</td>'
        +'<td><div style="display:flex;align-items:center;gap:6px;justify-content:flex-end">'
          +'<span style="color:#8b949e;min-width:36px;text-align:right">'+r.pct_fac+'%</span>'
          +'<div style="width:'+barW+'px;height:6px;border-radius:3px;background:'+cc+';flex-shrink:0"></div>'
        +'</div></td>'
      +'</tr>';
  });
}

// ── Render Cross Table ───────────────────────────────────────────────────
function switchCrossMode(mode, btn){
  _pdCrossMode = mode;
  document.querySelectorAll('.pd-cross-toggle .pd-rank-btn').forEach(function(b){ b.classList.remove('pd-active'); });
  btn.classList.add('pd-active');
  pdRenderCross();
}

function pdRenderCross(){
  var tbody = document.getElementById('pd-cross-body');
  if (!tbody || !PROD.cross) return;
  var mode = _pdCrossMode;
  var colors = ['#f59e0b','#818cf8','#34d399','#f472b6'];
  var maxTotal = Math.max.apply(null, PROD.cross.map(function(r){
    return mode === 'lts' ? r.total_lts : r['total_$'];
  })) || 1;

  tbody.innerHTML = '';
  PROD.cross.forEach(function(r){
    var vals = mode === 'lts'
      ? [r.cerveza_lts, r.gin_lts, r.fernet_lts, r.feriado_lts, r.total_lts]
      : [r['cerveza_$'], r['gin_$'], r['fernet_$'], r['feriado_$'], r['total_$']];
    var fmt = mode === 'lts' ? pdFmtLts : pdFmtPesos;
    var barW = Math.round((vals[4] / maxTotal) * 80);
    var row = '<tr><td style="text-align:left;font-weight:600">'+r.est+'</td>';
    for (var i=0; i<4; i++){
      row += '<td style="color:'+colors[i]+';font-weight:'+(vals[i]>0?'700':'400')+'">'+(vals[i]>0?fmt(vals[i]):'—')+'</td>';
    }
    row += '<td style="font-weight:800;color:#e6edf3">'
      +'<div style="display:flex;align-items:center;gap:8px;justify-content:flex-end">'
      +'<span>'+fmt(vals[4])+'</span>'
      +'<div style="width:'+barW+'px;height:6px;border-radius:3px;background:#484f58;flex-shrink:0"></div>'
      +'</div></td></tr>';
    tbody.innerHTML += row;
  });
}

// ── Render Donut SVG ─────────────────────────────────────────────────────
function pdRenderDonut(){
  var svg = document.getElementById('pd-donut-svg');
  var leg = document.getElementById('pd-torta-legend');
  if (!svg || !PROD.mix_tipo) return;
  svg.innerHTML = '';
  var R=80, r=52, cx=100, cy=100;
  var startAngle = 0;
  PROD.mix_tipo.forEach(function(m){
    if (!m.pct) return;
    var angle = (m.pct / 100) * 2 * Math.PI;
    var endAngle = startAngle + angle;
    var x1=cx+R*Math.cos(startAngle), y1=cy+R*Math.sin(startAngle);
    var x2=cx+R*Math.cos(endAngle),   y2=cy+R*Math.sin(endAngle);
    var ix1=cx+r*Math.cos(startAngle),iy1=cy+r*Math.sin(startAngle);
    var ix2=cx+r*Math.cos(endAngle),  iy2=cy+r*Math.sin(endAngle);
    var large = angle > Math.PI ? 1 : 0;
    var d = 'M '+ix1+' '+iy1+' L '+x1+' '+y1
      +' A '+R+' '+R+' 0 '+large+' 1 '+x2+' '+y2
      +' L '+ix2+' '+iy2
      +' A '+r+' '+r+' 0 '+large+' 0 '+ix1+' '+iy1+' Z';
    var p = document.createElementNS('http://www.w3.org/2000/svg','path');
    p.setAttribute('d', d);
    p.setAttribute('fill', m.color);
    p.setAttribute('opacity', '0.9');
    p.style.cursor = 'default';
    svg.appendChild(p);
    startAngle = endAngle + 0.02;
  });

  if (!leg) return;
  leg.innerHTML = '';
  PROD.mix_tipo.forEach(function(m){
    leg.innerHTML +=
      '<div style="margin-bottom:14px">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px">'
          +'<div style="display:flex;align-items:center;gap:8px">'
            +'<div style="width:14px;height:14px;border-radius:4px;background:'+m.color+'"></div>'
            +'<span style="font-size:13px;font-weight:600">'+m.label+'</span>'
          +'</div>'
          +'<div style="display:flex;align-items:center;gap:12px">'
            +'<span style="font-size:12px;color:#8b949e">'+pdFmtPesos(m.monto)+'</span>'
            +'<span style="font-size:16px;font-weight:900;color:'+m.color+';min-width:40px;text-align:right">'+m.pct+'%</span>'
          +'</div>'
        +'</div>'
        +'<div style="background:#21262d;border-radius:4px;height:8px;overflow:hidden">'
          +'<div style="width:'+m.pct+'%;height:100%;background:'+m.color+';border-radius:4px;opacity:.85"></div>'
        +'</div>'
      +'</div>';
  });
}

// ── Render Evolución ─────────────────────────────────────────────────────
function pdRenderEvolucion(){
  var evol  = pdFilterEvol(pdGetEst());
  var yAxis = document.getElementById('pd-evol-yaxis');
  var grid  = document.getElementById('pd-evol-grid');
  var bars  = document.getElementById('pd-evol-bars');
  var xAxis = document.getElementById('pd-evol-xaxis');
  if (!bars || !evol || !evol.length) return;

  var maxTotal = Math.max.apply(null, evol.map(function(d){
    return d.cerveza_lts + d.gin_lts + d.fernet_lts + d.feriado_lts;
  })) || 1;
  var CHART_H = 150;

  // Eje Y
  if (yAxis) {
    var ticks = [0, 0.25, 0.5, 0.75, 1].map(function(t){ return Math.round(maxTotal * t); });
    yAxis.innerHTML = '';
    ticks.slice().reverse().forEach(function(v){
      yAxis.innerHTML += '<div style="font-size:10px;color:#6e7681;line-height:1">'+(v>=1000?(v/1000).toFixed(1)+'K':v)+'</div>';
    });
  }

  // Grid lines
  if (grid) {
    grid.innerHTML = '';
    for (var t=0; t<5; t++) grid.innerHTML += '<div style="border-top:1px dashed #21262d;width:100%"></div>';
  }

  bars.innerHTML = '';
  if (xAxis) xAxis.innerHTML = '';

  evol.forEach(function(d, i){
    var dayNum = parseInt((d.fecha || '').split('-')[2]) || (i+1);
    var hC   = Math.round((d.cerveza_lts  / maxTotal) * CHART_H);
    var hG   = Math.round((d.gin_lts      / maxTotal) * CHART_H);
    var hF   = Math.round((d.fernet_lts   / maxTotal) * CHART_H);
    var hFer = Math.round((d.feriado_lts  / maxTotal) * CHART_H);
    var tip = 'Día '+dayNum+'\nCerveza: '+d.cerveza_lts+' lts\nGin: '+d.gin_lts+' lts\nFernet: '+d.fernet_lts+' lts\nFeriado: '+d.feriado_lts+' lts';
    bars.innerHTML +=
      '<div title="'+tip+'" style="flex:1;min-width:0;display:flex;flex-direction:column-reverse;height:'+CHART_H+'px;border-radius:3px 3px 0 0;overflow:hidden;cursor:default"'
        +' onmouseover="this.style.filter=\'brightness(1.2)\'" onmouseout="this.style.filter=\'\'">'
        +'<div style="width:100%;height:'+hC+'px;background:#f59e0b;flex-shrink:0"></div>'
        +'<div style="width:100%;height:'+hG+'px;background:#818cf8;flex-shrink:0"></div>'
        +'<div style="width:100%;height:'+hF+'px;background:#34d399;flex-shrink:0"></div>'
        +'<div style="width:100%;height:'+hFer+'px;background:#f472b6;flex-shrink:0"></div>'
      +'</div>';
    if (xAxis) {
      var showLabel = dayNum === 1 || dayNum % 5 === 0;
      xAxis.innerHTML += '<div style="flex:1;min-width:0;font-size:9px;color:'+(showLabel?'#8b949e':'transparent')+';text-align:center;margin-top:4px">'+dayNum+'</div>';
    }
  });
}

// ── Render Top por Categoría ─────────────────────────────────────────────
function pdRenderTopCat(){
  var el = document.getElementById('pd-top-cat');
  if (!el || !PROD.top_por_cat) return;
  var catDefs = [
    {key:'cerveza', label:'Cerveza', color:'#f59e0b'},
    {key:'gin',     label:'Gin',     color:'#818cf8'},
    {key:'fernet',  label:'Fernet',  color:'#34d399'},
    {key:'feriado', label:'Feriado', color:'#f472b6'},
  ];
  el.innerHTML = '';
  catDefs.forEach(function(c){
    var items = PROD.top_por_cat[c.key] || [];
    var html = '<div class="pd-top-cat">'
      +'<div class="pd-top-cat-title" style="color:'+c.color+'">'+c.label+'</div>';
    if (!items.length) {
      html += '<div style="color:#484f58;font-size:11px">Sin datos</div>';
    } else {
      items.forEach(function(item){
        html +=
          '<div style="margin-bottom:6px">'
            +'<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">'
              +'<span style="color:#e6edf3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:130px">'+item.nombre+'</span>'
              +'<span style="color:'+c.color+';font-weight:700;flex-shrink:0;margin-left:4px">'+item.pct+'%</span>'
            +'</div>'
            +'<div style="background:#21262d;border-radius:2px;height:4px">'
              +'<div style="width:'+item.pct+'%;height:100%;background:'+c.color+';border-radius:2px"></div>'
            +'</div>'
          +'</div>';
      });
    }
    html += '</div>';
    el.innerHTML += html;
  });
}

// ── Render VS Mes Anterior ───────────────────────────────────────────────
function pdRenderVsMesAnt(){
  var el = document.getElementById('pd-vsmes');
  if (!el || !PROD.kpis) return;
  var cats = [
    {key:'cerveza', label:'Cerveza', icon:'🍺', color:'#f59e0b'},
    {key:'gin',     label:'Gin',     icon:'🍸', color:'#818cf8'},
    {key:'fernet',  label:'Fernet',  icon:'🥃', color:'#34d399'},
    {key:'feriado', label:'Feriado', icon:'🍹', color:'#f472b6'},
  ];
  el.innerHTML = '';
  cats.forEach(function(c){
    var kpi     = PROD.kpis[c.key] || {};
    var actual  = kpi.lts_actual  || 0;
    var ant     = kpi.lts_mes_ant || 0;
    var diff    = actual - ant;
    var pct     = ant ? (diff / ant * 100).toFixed(1) : null;
    var isUp    = diff >= 0;
    var arrow   = isUp ? '▲' : '▼';
    var col     = isUp ? '#6ee7b7' : '#f87171';
    var pctStr  = pct !== null ? arrow+' '+Math.abs(pct)+'%' : '— Sin dato';

    el.innerHTML +=
      '<div class="pd-vsmes-card">'
        +'<div style="display:flex;align-items:center;gap:8px">'
          +'<span style="font-size:20px">'+c.icon+'</span>'
          +'<span style="font-size:11px;font-weight:700;color:'+c.color+';text-transform:uppercase;letter-spacing:.4px">'+c.label+'</span>'
        +'</div>'
        +'<div style="font-size:22px;font-weight:900">'+(actual>=1000?(actual/1000).toFixed(1):''+actual)+'<span style="font-size:12px;color:#8b949e;font-weight:400"> '+(actual>=1000?'K ':'')+'lts</span></div>'
        +'<div style="display:flex;align-items:center;gap:6px">'
          +'<span style="font-size:16px;font-weight:800;color:'+col+'">'+pctStr+'</span>'
          +'<span style="font-size:11px;color:#8b949e">vs mes ant.</span>'
        +'</div>'
        +'<div style="font-size:11px;color:#6e7681">Mes ant: '+(ant>=1000?(ant/1000).toFixed(1)+'K':ant)+' lts</div>'
      +'</div>';
  });
}

// ── Toggle de vista principal ────────────────────────────────────────────
function switchMainView(view, btn){
  document.querySelectorAll('#mainViewToggle .view-btn').forEach(function(b){ b.classList.remove('vb-active'); });
  btn.classList.add('vb-active');
  document.getElementById('view-economico').style.display = view === 'economico' ? 'block' : 'none';
  document.getElementById('view-producto').style.display  = view === 'producto'  ? 'block' : 'none';
  document.getElementById('pdEstFilter').style.display    = view === 'producto'  ? '' : 'none';
  if (view === 'producto') renderProductoView();
}

// ── Render completo de la vista Producto ────────────────────────────────
function renderProductoView(){
  pdRenderKPIs();
  pdRenderMixLts();
  pdRenderRanking();
  pdRenderCross();
  pdRenderDonut();
  pdRenderEvolucion();
  pdRenderTopCat();
  pdRenderVsMesAnt();
}

// ── Init ─────────────────────────────────────────────────────────────────
if (PROD && PROD.establecimientos) {
  pdPopulateEstSelect();
}
```

- [ ] **Step 2: Verificar que `__PRODUCTO_JSON__` aparece exactamente una vez en el template**

```bash
grep -c "__PRODUCTO_JSON__" "C:\Users\Darwin Salinas\Claude_Cowork\templates\dashboard.html"
```
Esperado: `1`

---

## Task 5: Test end-to-end y deploy

**Files:**
- Run: `actualizar_dashboard.py` con output de test
- Verify: `super_dashboard_temple.html` generado

- [ ] **Step 1: Generar el dashboard completo**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
python -X utf8 actualizar_dashboard.py --output super_dashboard_temple.html
```

Esperado en la salida:
```
[producto] ✓ evolucion=N días, ranking=N productos, cross=N establecimientos
✓ PRODUCTO_JSON inyectado (N productos, N días)
```

- [ ] **Step 2: Verificar que no quedaron placeholders sin reemplazar**

```bash
grep "__PRODUCTO_JSON__" "C:\Users\Darwin Salinas\Claude_Cowork\super_dashboard_temple.html"
```
Esperado: sin output (0 coincidencias).

- [ ] **Step 3: Abrir en el navegador y verificar toggle**

```bash
start "C:\Users\Darwin Salinas\Claude_Cowork\super_dashboard_temple.html"
```

Verificar:
- [ ] Toggle "Económico / Producto" visible en el header
- [ ] Click en "Producto" muestra la vista de producto y aparece filtro de establecimiento
- [ ] Click en "Económico" vuelve a la vista original sin romper nada
- [ ] Las 8 secciones de producto renderizan correctamente con datos reales
- [ ] KPI cards muestran litros reales de cerveza/gin/fernet/feriado
- [ ] Barras de mix se renderizan proporcionalmente
- [ ] Ranking muestra productos ordenados por facturación
- [ ] Donut SVG se renderiza con los sectores correctos
- [ ] Evolución muestra barras apiladas por día

- [ ] **Step 4: Deploy a GCS**

```bash
cd "C:\Users\Darwin Salinas\Claude_Cowork"
gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" cp super_dashboard_temple.html gs://temple-bar-dashboard-cache/super_dashboard_temple.html
```

Verificar en: `https://storage.googleapis.com/temple-bar-dashboard-cache/super_dashboard_temple.html`
