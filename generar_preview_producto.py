"""
generar_preview_producto.py
Genera preview_producto.html con datos reales de BigQuery.
Fuentes por marca:
  Temple    → temple-bar-439715.curated_database.vw_curated_compilado_ok
  Patagonia → patagonia-refugios.curated_database.curated_mix
  Feriado   → feriado-cantina-431720.Ventas.Compilado
"""
import os, sys, json, argparse
from datetime import date, timedelta
from google.cloud import bigquery
from google.oauth2 import service_account

SA_KEY_FILE = "temple-bar-439715-da51b292ce5d.json"
OUTPUT_FILE = "preview_producto.html"
TEMPLATE    = "templates/producto_preview.html"

SOURCES = {
    'TEMPLE':    ('temple-bar-439715',  'temple-bar-439715.curated_database.vw_curated_compilado_ok'),
    'PATAGONIA': ('patagonia-refugios', 'patagonia-refugios.curated_database.curated_mix'),
    'FERIADO':   ('temple-bar-439715',  'temple-bar-439715.Feriado.vw_Ventas_Feriado'),
}

# ── Colores por familia / categoría ──────────────────────────────
COLORS = {
    # Temple / Patagonia — columna mix
    'Comida':         '#fb923c',
    'Bebida':         '#60a5fa',
    'Promoción':      '#a78bfa',
    'Merch':          '#fbbf24',
    'Sin clasificar': '#8b949e',
    # Feriado — Mix values de Ventas_Toteat (Toteat hierarchyName)
    'Entradas':              '#fb923c',
    'Minutas':               '#f59e0b',
    'Bebidas Sin Alcohol':   '#60a5fa',
    'Pizzas Enteras':        '#e879f9',
    'Pizzas Al Corte':       '#e879f9',
    'Promociones':           '#a78bfa',
    'Tragos Con Vermú':      '#818cf8',
    'Otros Tragos':          '#818cf8',
    'Menu Mediodía':         '#34d399',
    'Menu Evento':           '#34d399',
    'Sanguches':             '#fbbf24',
    'Cerveza':               '#f59e0b',
    'Empanadas':             '#f87171',
    'Ensaladas':             '#6ee7b7',
    'Cafetería':             '#a78bfa',
    'Pastas Individuales':   '#f59e0b',
    'Postres':               '#fbbf24',
    'Menú Infantil':         '#6ee7b7',
    'Para Llevar':           '#8b949e',
    'Utilidades':            '#6e7681',
    'Activacion':            '#3b82f6',
    'Combos para compartir': '#f59e0b',
}

def color(key): return COLORS.get(key or '', '#8b949e')
def fl(v):      return float(v) if v is not None else 0.0

def _prev_month_date(d):
    """Mismo día del mes anterior, ajustado al último día si es necesario."""
    if d.month == 1:
        return d.replace(year=d.year - 1, month=12)
    try:
        return d.replace(month=d.month - 1)
    except ValueError:
        import calendar
        last = calendar.monthrange(d.year, d.month - 1)[1]
        return d.replace(month=d.month - 1, day=last)

def _apply_deltas(brand_data, prev_rows):
    """Agrega delta_pct a cada producto del ranking y vs_ant_pct al total."""
    prev_map = {}
    for r in prev_rows:
        prod = str(getattr(r, 'producto', '') or '')
        fac  = fl(getattr(r, 'facturacion', 0))
        prev_map[prod] = prev_map.get(prod, 0) + fac

    for item in brand_data['ranking']:
        prod = item['producto']
        prev = prev_map.get(prod, 0)
        curr = item['facturacion']
        if prev > 0:
            item['delta_pct'] = round((curr - prev) / prev * 100, 1)
        elif curr > 0:
            item['delta_pct'] = 'nuevo'
        else:
            item['delta_pct'] = None

    total_prev = sum(prev_map.values())
    if total_prev > 0:
        brand_data['vs_ant_pct'] = round(
            (brand_data['total_fac'] - total_prev) / total_prev * 100, 1)


# ── Temple ────────────────────────────────────────────────────────
def fetch_temple(client, desde, hasta):
    tbl = '`temple-bar-439715.curated_database.vw_curated_compilado_ok`'
    q = f"""
    SELECT
      producto,
      INITCAP(COALESCE(mix, 'Sin clasificar'))      AS familia,
      COALESCE(estilo, '')                          AS estilo,
      COALESCE(mix, '')                             AS mix,
      SUM(cantidad)                                 AS cantidad,
      SUM(dinero)                                   AS facturacion,
      SUM(COALESCE(total_receta,  0))               AS lts_total,
      SUM(COALESCE(cerveza_total, 0))               AS lts_cerveza,
      SUM(COALESCE(gin_total,     0))               AS lts_gin,
      SUM(COALESCE(fernet_total,  0))               AS lts_fernet,
      SUM(COALESCE(feriado_total, 0))               AS lts_feriado,
      SUM(COALESCE(tragos_total,  0))               AS lts_tragos,
      SUM(COALESCE(burger_total,  0))               AS lts_burger
    FROM {tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY producto, familia, estilo, mix
    ORDER BY facturacion DESC
    LIMIT 1000
    """
    rows = list(client.query(q).result())
    print(f"  [Temple] {len(rows)} filas de curated_compilado_ok")
    return rows


# ── Patagonia ─────────────────────────────────────────────────────
def fetch_patagonia(client, desde, hasta):
    # ml por unidad según Cat_BD de Feriado (referencia cruzada):
    #   Bosque Gin = 50ml/copa  |  Vermu Feriado = 120ml/copa  |  Fernet = 75ml/copa
    tbl = '`patagonia-refugios.curated_database.curated_mix`'
    q = f"""
    SELECT
      producto,
      INITCAP(COALESCE(mix, 'Sin clasificar'))  AS familia,
      COALESCE(tipo, '')                        AS estilo,
      COALESCE(mix,  '')                        AS mix,
      SUM(cantidad)                             AS cantidad,
      SUM(dinero)                               AS facturacion,
      ROUND(
        SUM(COALESCE(cerveza_total, 0))
        + SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'BOSQUE GIN')
                   THEN cantidad * 50.0  / 1000 ELSE 0 END)
        + SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'VERMU FERIADO')
                   THEN cantidad * 120.0 / 1000 ELSE 0 END)
        + SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'FERNET')
                   THEN cantidad * 75.0  / 1000 ELSE 0 END),
      2)                                        AS lts_total,
      SUM(COALESCE(cerveza_total, 0))           AS lts_cerveza,
      ROUND(SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'BOSQUE GIN')
                     THEN cantidad * 50.0  / 1000 ELSE 0 END), 2) AS lts_gin,
      ROUND(SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'FERNET')
                     THEN cantidad * 75.0  / 1000 ELSE 0 END), 2) AS lts_fernet,
      ROUND(SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'VERMU FERIADO')
                     THEN cantidad * 120.0 / 1000 ELSE 0 END), 2) AS lts_feriado,
      SUM(COALESCE(tragos_total, 0))            AS lts_tragos,
      0.0                                       AS lts_burger
    FROM {tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY producto, familia, estilo, mix
    ORDER BY facturacion DESC
    LIMIT 1000
    """
    rows = list(client.query(q).result())
    print(f"  [Patagonia] {len(rows)} filas de curated_mix")
    return rows


# ── Feriado ───────────────────────────────────────────────────────
# Fuente Feriado: temple-bar-439715.Feriado.Ventas_Toteat
#   Campos: Producto, Fecha, Cantidad, Dinero, Mix (hierarchyName), Establecimiento
#   Nota: Litros_Totales no está disponible en Ventas_Toteat —
#         los campos lts_* se reportan como 0 hasta que se incorpore esa fuente.
#
# Categoria_Empresa (lowercase) → tipo de licor para feriado_lts_by_tipo:
FERIADO_LTS_MAP = {
    'feriado vermu':  'lts_feriado',
    'cmq cerveza':    'lts_cerveza',
    'temple cerveza': 'lts_cerveza',
    'fernet':         'lts_fernet',
    'bosque gin':     'lts_gin',
}

def fetch_feriado(client, desde, hasta):
    tbl = '`temple-bar-439715.Feriado.vw_Ventas_Feriado`'
    q = f"""
    SELECT
      Producto                                        AS producto,
      COALESCE(Categoria_Toteat, 'Sin categoría')     AS familia,
      LOWER(TRIM(COALESCE(Categoria_Empresa, '')))    AS cat_empresa,
      SUM(Cantidad)                                   AS cantidad,
      SUM(Facturacion)                                AS facturacion,
      SUM(COALESCE(Litros, 0))                        AS lts_total
    FROM {tbl}
    WHERE Fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY producto, familia, cat_empresa
    ORDER BY facturacion DESC
    LIMIT 1000
    """
    rows = list(client.query(q).result())
    print(f"  [Feriado] {len(rows)} filas de vw_Ventas_Feriado")
    return rows


def feriado_lts_by_tipo(rows):
    """Desglosa litros de Feriado por tipo usando Categoria_por_Empresa."""
    totals = {k: 0.0 for k in ('lts_cerveza','lts_gin','lts_fernet','lts_feriado','lts_tragos','lts_burger')}
    for r in rows:
        cat = (str(getattr(r, 'cat_empresa', '') or '')).lower().strip()
        lts = fl(getattr(r, 'lts_total', 0))
        dest = FERIADO_LTS_MAP.get(cat)
        if dest:
            totals[dest] += lts
    return totals



# ── Top locales por litros ───────────────────────────────────────
def fetch_locales_temple(client, desde, hasta):
    tbl = '`temple-bar-439715.curated_database.vw_curated_compilado_ok`'
    q = f"""
    SELECT
      establecimiento                         AS local,
      ROUND(SUM(COALESCE(cerveza_total,0)),2) AS lts_cerveza,
      ROUND(SUM(COALESCE(gin_total,    0)),2) AS lts_gin,
      ROUND(SUM(COALESCE(fernet_total, 0)),2) AS lts_fernet,
      ROUND(SUM(COALESCE(feriado_total,0)),2) AS lts_feriado,
      ROUND(SUM(COALESCE(tragos_total, 0)),2) AS lts_tragos,
      ROUND(SUM(COALESCE(total_receta, 0)),2) AS lts_total
    FROM {tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local ORDER BY lts_total DESC
    """
    return list(client.query(q).result())


def fetch_locales_patagonia(client, desde, hasta):
    tbl = '`patagonia-refugios.curated_database.curated_mix`'
    q = f"""
    SELECT
      establecimiento                                                                   AS local,
      ROUND(SUM(COALESCE(cerveza_total, 0)), 2)                                        AS lts_cerveza,
      ROUND(SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'BOSQUE GIN')
                     THEN cantidad * 50.0 / 1000 ELSE 0 END), 2)                      AS lts_gin,
      ROUND(SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'FERNET')
                     THEN cantidad * 75.0 / 1000 ELSE 0 END), 2)                      AS lts_fernet,
      ROUND(SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'VERMU FERIADO')
                     THEN cantidad * 120.0 / 1000 ELSE 0 END), 2)                     AS lts_feriado,
      ROUND(SUM(COALESCE(tragos_total, 0)), 2)                                         AS lts_tragos,
      ROUND(
        SUM(COALESCE(cerveza_total, 0))
        + SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'BOSQUE GIN')
                   THEN cantidad * 50.0  / 1000 ELSE 0 END)
        + SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'FERNET')
                   THEN cantidad * 75.0  / 1000 ELSE 0 END)
        + SUM(CASE WHEN REGEXP_CONTAINS(UPPER(TRIM(producto)), r'VERMU FERIADO')
                   THEN cantidad * 120.0 / 1000 ELSE 0 END),
      2)                                                                                AS lts_total
    FROM {tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local ORDER BY lts_total DESC
    """
    return list(client.query(q).result())


def fetch_locales_feriado(client, desde, hasta):
    tbl = '`temple-bar-439715.Feriado.vw_Ventas_Feriado`'
    q = f"""
    SELECT
      Establecimiento AS local,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa)) IN ('cmq cerveza','temple cerveza')
                     THEN COALESCE(Litros,0) ELSE 0 END),2) AS lts_cerveza,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa)) = 'bosque gin'
                     THEN COALESCE(Litros,0) ELSE 0 END),2) AS lts_gin,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa)) = 'fernet'
                     THEN COALESCE(Litros,0) ELSE 0 END),2) AS lts_fernet,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa)) = 'feriado vermu'
                     THEN COALESCE(Litros,0) ELSE 0 END),2) AS lts_feriado,
      0.0                                                    AS lts_tragos,
      ROUND(SUM(COALESCE(Litros,0)),2)                       AS lts_total
    FROM {tbl}
    WHERE Fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local ORDER BY lts_total DESC
    """
    return list(client.query(q).result())


def build_locales_data(rows):
    by_local = {}
    for r in rows:
        local = str(getattr(r, 'local', '') or '').strip()
        if not local:
            continue
        if local not in by_local:
            by_local[local] = {k: 0.0 for k in ('lts_cerveza','lts_gin','lts_fernet','lts_feriado','lts_tragos','lts_total')}
        for k in ('lts_cerveza','lts_gin','lts_fernet','lts_feriado','lts_tragos','lts_total'):
            by_local[local][k] += fl(getattr(r, k, 0))
    return sorted(
        [{'local': k,
          'lts_cerveza': round(v['lts_cerveza'], 1),
          'lts_gin':     round(v['lts_gin'],     1),
          'lts_fernet':  round(v['lts_fernet'],  1),
          'lts_feriado': round(v['lts_feriado'], 1),
          'lts_tragos':  round(v['lts_tragos'],  1),
          'lts_total':   round(v['lts_total'],   1)}
         for k, v in by_local.items()],
        key=lambda x: -x['lts_total']
    )


# ── Construir datos por marca ─────────────────────────────────────
def build_brand_data(rows):
    """Convierte rows de BigQuery en el dict que consume el HTML."""
    mix_agg  = {}   # {familia: {fac, lts_total, lts_cerveza, ...}}
    prod_agg = {}   # {(producto, familia): {...}}

    for r in rows:
        fam = str(getattr(r, 'familia', '') or 'Sin clasificar')
        prod = str(getattr(r, 'producto', '') or '')

        if fam not in mix_agg:
            mix_agg[fam] = {k: 0.0 for k in ('fac','lts_total','lts_cerveza','lts_gin','lts_fernet','lts_feriado','lts_tragos','lts_burger')}
        mix_agg[fam]['fac']        += fl(getattr(r, 'facturacion', 0))
        mix_agg[fam]['lts_total']  += fl(getattr(r, 'lts_total',   0))
        mix_agg[fam]['lts_cerveza']+= fl(getattr(r, 'lts_cerveza', 0))
        mix_agg[fam]['lts_gin']    += fl(getattr(r, 'lts_gin',     0))
        mix_agg[fam]['lts_fernet'] += fl(getattr(r, 'lts_fernet',  0))
        mix_agg[fam]['lts_feriado']+= fl(getattr(r, 'lts_feriado', 0))
        mix_agg[fam]['lts_tragos'] += fl(getattr(r, 'lts_tragos',  0))
        mix_agg[fam]['lts_burger'] += fl(getattr(r, 'lts_burger',  0))

        key = (prod, fam)
        if key not in prod_agg:
            prod_agg[key] = {'producto': prod, 'familia': fam, 'cantidad': 0, 'facturacion': 0.0, 'lts': 0.0}
        prod_agg[key]['cantidad']   += int(fl(getattr(r, 'cantidad',   0)))
        prod_agg[key]['facturacion']+= fl(getattr(r, 'facturacion', 0))
        prod_agg[key]['lts']        += fl(getattr(r, 'lts_total',   0))

    total_fac = sum(v['fac'] for v in mix_agg.values()) or 1
    total_lts = sum(v['lts_total'] for v in mix_agg.values())

    mix_list = sorted(
        [{'mix': k, 'fac': round(v['fac'], 0), 'lts': round(v['lts_total'], 1),
          'pct': round(v['fac'] / total_fac * 100, 1), 'color': color(k)}
         for k, v in mix_agg.items() if v['fac'] > 0],
        key=lambda x: -x['fac']
    )

    ranking = sorted(prod_agg.values(), key=lambda x: -x['facturacion'])[:30]
    for item in ranking:
        item['pct_fac']     = round(item['facturacion'] / total_fac * 100, 1)
        item['facturacion'] = round(item['facturacion'], 0)
        item['litros']      = round(item['lts'], 1)
        item['color']       = color(item['familia'])

    # Totales de litros por tipo (suma de todas las familias)
    lts_by_tipo = {k: round(sum(v.get(k, 0) for v in mix_agg.values()), 1)
                   for k in ('lts_cerveza','lts_gin','lts_fernet','lts_feriado','lts_tragos','lts_burger')}

    n_productos = len({r[0] for r in prod_agg.keys() if r[0]})
    top_mix     = mix_list[0]['mix'] if mix_list else '—'
    top_mix_pct = mix_list[0]['pct'] if mix_list else 0

    return {
        'total_fac':   round(total_fac, 0),
        'total_lts':   round(total_lts, 1),
        'lts_cerveza': lts_by_tipo['lts_cerveza'],
        'lts_gin':     lts_by_tipo['lts_gin'],
        'lts_fernet':  lts_by_tipo['lts_fernet'],
        'lts_feriado': lts_by_tipo['lts_feriado'],
        'lts_tragos':  lts_by_tipo['lts_tragos'],
        'n_productos': n_productos,
        'top_mix':     top_mix,
        'top_mix_pct': top_mix_pct,
        'vs_ant_pct':  None,
        'mix':         mix_list,
        'ranking':     ranking,
    }


def compute_periods():
    """Períodos que coinciden con los filtros rápidos del dashboard."""
    import calendar
    today = date.today()
    first = today.replace(day=1)

    # mes_anterior
    if first.month == 1:
        pf = first.replace(year=first.year - 1, month=12)
    else:
        pf = first.replace(month=first.month - 1)
    pl = pf.replace(day=calendar.monthrange(pf.year, pf.month)[1])

    # ultimos_3m: primero del mes que está 2 meses atrás
    m3, y3 = today.month - 2, today.year
    while m3 <= 0: m3 += 12; y3 -= 1
    first_3m = date(y3, m3, 1)

    # ultimos_6m: primero del mes que está 5 meses atrás
    m6, y6 = today.month - 5, today.year
    while m6 <= 0: m6 += 12; y6 -= 1
    first_6m = date(y6, m6, 1)

    return {
        'mes_actual':   (first.isoformat(),       today.isoformat()),
        'mes_anterior': (pf.isoformat(),           pl.isoformat()),
        'ultimos_3m':   (first_3m.isoformat(),     today.isoformat()),
        'ultimos_6m':   (first_6m.isoformat(),     today.isoformat()),
        'ytd':          (date(today.year, 1, 1).isoformat(), today.isoformat()),
    }


def fetch_all(desde, hasta, clients):
    """Fetches data for a single date range using pre-created BQ clients."""
    # Período anterior: mismo rango de días, mes previo
    desde_ant = _prev_month_date(date.fromisoformat(desde)).isoformat()
    hasta_ant = _prev_month_date(date.fromisoformat(hasta)).isoformat()
    print(f"    → prev: {desde_ant} / {hasta_ant}")

    result = {}
    brand_rows       = {}
    brand_prev_rows  = {}
    brand_local_rows = {}

    for marca, (project, _) in SOURCES.items():
        client = clients[marca]
        try:
            if marca == 'TEMPLE':
                brand_rows[marca]       = fetch_temple(client, desde, hasta)
                brand_prev_rows[marca]  = fetch_temple(client, desde_ant, hasta_ant)
                brand_local_rows[marca] = fetch_locales_temple(client, desde, hasta)
            elif marca == 'PATAGONIA':
                brand_rows[marca]       = fetch_patagonia(client, desde, hasta)
                brand_prev_rows[marca]  = fetch_patagonia(client, desde_ant, hasta_ant)
                brand_local_rows[marca] = fetch_locales_patagonia(client, desde, hasta)
            else:  # FERIADO
                brand_rows[marca]       = fetch_feriado(client, desde, hasta)
                brand_prev_rows[marca]  = fetch_feriado(client, desde_ant, hasta_ant)
                brand_local_rows[marca] = fetch_locales_feriado(client, desde, hasta)
        except Exception as e:
            print(f"  ⚠ [{marca}] Sin acceso: {e}")
            brand_rows[marca]       = []
            brand_prev_rows[marca]  = []
            brand_local_rows[marca] = []

    # Construir datos por marca
    for marca, rows in brand_rows.items():
        if rows:
            data = build_brand_data(rows)
            if marca == 'FERIADO':
                feriado_lts = feriado_lts_by_tipo(rows)
                for k, v in feriado_lts.items():
                    data[k] = round(v, 1)
            _apply_deltas(data, brand_prev_rows.get(marca, []))
        else:
            data = _empty_brand(marca)
        locales = build_locales_data(brand_local_rows.get(marca, []))
        for l in locales:
            l['marca'] = marca.capitalize()
        data['locales'] = locales
        result[marca] = data

    # TODAS = combinar todas las rows
    all_rows      = [r for rows in brand_rows.values() for r in rows]
    all_prev_rows = [r for rows in brand_prev_rows.values() for r in rows]
    if all_rows:
        todas = build_brand_data(all_rows)
        if brand_rows.get('FERIADO'):
            feriado_lts = feriado_lts_by_tipo(brand_rows['FERIADO'])
            for k, v in feriado_lts.items():
                todas[k] = round(todas.get(k, 0) + v, 1)
        _apply_deltas(todas, all_prev_rows)
    else:
        todas = _empty_brand('TODAS')
    todas_locales = [l for m in SOURCES for l in result.get(m, {}).get('locales', [])]
    todas_locales.sort(key=lambda x: -x['lts_total'])
    todas['locales'] = todas_locales
    result['TODAS'] = todas

    return result


def _empty_brand(marca):
    return {
        'total_fac': 0, 'total_lts': 0,
        'lts_cerveza': 0, 'lts_gin': 0, 'lts_fernet': 0,
        'lts_feriado': 0, 'lts_tragos': 0,
        'n_productos': 0, 'top_mix': '—', 'top_mix_pct': 0,
        'vs_ant_pct': None, 'mix': [], 'ranking': [], 'locales': [],
        'sin_acceso': True,
    }


def generate_preview(datasets, output):
    datasets_json = json.dumps(datasets, separators=(',', ':'), default=str, ensure_ascii=False)
    with open(TEMPLATE, 'r', encoding='utf-8') as f:
        html = f.read()
    html = html.replace('__DATASETS_JSON__', datasets_json)
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✓ Guardado: {output}")


def upload_to_gcs(local_path, bucket_name, blob_name, creds):
    import os
    from google.cloud import storage
    file_size = os.path.getsize(local_path)
    if file_size < 1024:
        raise RuntimeError(
            f"HTML demasiado pequeño ({file_size} bytes) — abortando upload para evitar publicar archivo corrupto"
        )
    print(f"  Subiendo a GCS: gs://{bucket_name}/{blob_name} ({file_size // 1024} KB) ...")
    client = storage.Client(credentials=creds)
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(local_path, content_type="text/html; charset=utf-8")
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    blob.reload()
    if blob.cache_control != "no-cache, no-store, must-revalidate":
        print(f"  ⚠ WARNING: cache_control no se aplicó correctamente (valor actual: {blob.cache_control!r})")
    print(f"  ✓ Publicado: https://storage.googleapis.com/{bucket_name}/{blob_name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',     default=OUTPUT_FILE)
    parser.add_argument('--gcs-bucket', default='temple-bar-dashboard-cache')
    parser.add_argument('--gcs-blob',   default='producto.html')
    parser.add_argument('--no-upload',  action='store_true')
    args = parser.parse_args()

    _sa_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SA_KEY_FILE)
    if os.path.exists(_sa_path):
        creds = service_account.Credentials.from_service_account_file(
            _sa_path,
            scopes=['https://www.googleapis.com/auth/bigquery',
                    'https://www.googleapis.com/auth/cloud-platform']
        )
    else:
        import google.auth as _gauth
        creds, _ = _gauth.default(scopes=['https://www.googleapis.com/auth/bigquery',
                                          'https://www.googleapis.com/auth/cloud-platform'])

    # Crear clientes una sola vez y reutilizarlos en todos los períodos
    clients = {
        'TEMPLE':    bigquery.Client(project='temple-bar-439715',      credentials=creds),
        'PATAGONIA': bigquery.Client(project='patagonia-refugios',     credentials=creds),
        'FERIADO':   bigquery.Client(project='temple-bar-439715',      credentials=creds),
    }

    periods = compute_periods()
    datasets = {}
    for periodo, (desde, hasta) in periods.items():
        print(f"\n=== [{periodo}] {desde} → {hasta} ===")
        data = fetch_all(desde, hasta, clients)
        # Agregar label legible para mostrar en el iframe
        data['label'] = f"{desde} al {hasta}"
        datasets[periodo] = data

    generate_preview(datasets, args.output)

    if not args.no_upload and args.gcs_bucket:
        upload_to_gcs(args.output, args.gcs_bucket, args.gcs_blob, creds)

    print(f"\n✓ Listo: {args.output}")


if __name__ == '__main__':
    main()
