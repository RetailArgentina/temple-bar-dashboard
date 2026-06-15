#!/usr/bin/env python3
"""
Temple Bar Dashboard Refresh Script
Queries vw_Ventas_Corporativo_Base from BigQuery and regenerates the super dashboard HTML.
Usage: python3 actualizar_dashboard.py [--desde YYYY-MM-DD] [--hasta YYYY-MM-DD]
"""

import json
import argparse
import sys
import os
from datetime import datetime, timedelta

# Force UTF-8 output on Windows terminals (cp1252 can't encode ✓ ─ etc.)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from google.cloud import bigquery
from google.oauth2 import service_account

# Insights generator — genera análisis contextuales con IPC INDEC + datos BQ
from insights_generator import generate_insights, render_insights_html, load_economic_context

# Configuration
PROJECT_ID = "temple-bar-439715"
DATASET_ID = "Corporativo"
TABLE_VENTAS = "vw_Ventas_Corporativo_Base"
DATASET_CORP = "Corporativo"
TABLE_PROD   = "vw_productos_maestro_clean"

# Service Account key file (same folder as this script).
# Used only when running locally. In Cloud Run, ADC is used instead.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")


def get_bigquery_client():
    """Return a BigQuery client.

    - Local execution: loads credentials from the Service Account JSON key file.
    - Cloud Run / any GCP environment: uses Application Default Credentials
      injected automatically by the runtime (no key file needed).

    Drive scope incluido para poder leer tablas externas de BQ vinculadas a Google Sheets.
    """
    BQ_LOCATION = "US"
    SCOPES = [
        "https://www.googleapis.com/auth/bigquery",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/cloud-platform",
    ]

    if os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"  Using Service Account key: {os.path.basename(SERVICE_ACCOUNT_FILE)}")
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        return bigquery.Client(project=PROJECT_ID, credentials=credentials, location=BQ_LOCATION)
    else:
        print("  Using Application Default Credentials (Cloud Run mode)")
        import google.auth
        credentials, _ = google.auth.default(scopes=SCOPES)
        return bigquery.Client(project=PROJECT_ID, credentials=credentials, location=BQ_LOCATION)


def upload_to_gcs(local_path, bucket_name, blob_name="super_dashboard_temple.html"):
    """Upload the generated HTML to a GCS bucket and make it publicly readable."""
    from google.cloud import storage
    print(f"\nUploading to GCS: gs://{bucket_name}/{blob_name} ...")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path, content_type="text/html; charset=utf-8")
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    # No blob.make_public() — bucket uses uniform bucket-level access.
    # Public read is managed at the IAM level (allUsers: roles/storage.objectViewer),
    # so the object is already publicly readable after upload.
    public_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
    print(f"  OK Public URL: {public_url}")
    return public_url

TABLES = {
    'ventas': 'Ventas_Maestra',
    'mix': 'Mix_Maestro',
    'cerveza': 'Cerveza_Maestro',
    'gin': 'Gin_Maestro',
    'feriado': 'Feriado_Maestro'
}

def parse_args():
    parser = argparse.ArgumentParser(description='Update Temple Bar Dashboard')

    # Default to last 90 days
    today = datetime.now()
    default_hasta = today.strftime('%Y-%m-%d')
    default_desde = (today - timedelta(days=90)).strftime('%Y-%m-%d')

    parser.add_argument('--desde', default=default_desde, help=f'Start date (default: 90 days ago = {default_desde})')
    parser.add_argument('--hasta', default=default_hasta, help=f'End date (default: today = {default_hasta})')
    parser.add_argument('--output', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'super_dashboard_temple.html'),
                        help='Output HTML file path')
    parser.add_argument('--gcs-bucket', default='',
                        help='GCS bucket name to upload the dashboard after generation (e.g. temple-bar-dashboard-cache)')

    return parser.parse_args()

def fetch_data(client, desde, hasta):
    """Fetch data from vw_Ventas_Corporativo_Base and return in dashboard-compatible format."""
    print(f"Fetching data from {desde} to {hasta}...")

    query = f"""
        SELECT
            Fecha,
            Marca,
            Local                               AS Establecimiento,
            Canal,
            Turno,
            1                                                                AS ordenes,
            CAST(ROUND(SAFE_CAST(Facturacion AS FLOAT64)) AS INT64)          AS ventas,
            CAST(ROUND(SAFE_CAST(Total AS FLOAT64)) AS INT64)                AS total,
            CAST(ROUND(SAFE_CAST(Total AS FLOAT64)) AS INT64)                AS ticket,
            Origen
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha BETWEEN '{desde}' AND '{hasta}'
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        ORDER BY Fecha DESC
    """

    print(f"  Querying {TABLE_VENTAS}...", end='', flush=True)
    job = client.query(query)
    rows = job.result()

    ventas = []
    for row in rows:
        ventas.append({
            'd':     row.Fecha.strftime('%Y-%m-%d'),
            'e':     row.Establecimiento,
            'marca': row.Marca,
            'c':     row.Canal,
            't':     row.Turno,
            'o':     row.ordenes,
            'v':     row.ventas,
            'total': row.total,
            'tk':    row.ticket,
            'orig':  row.Origen,
        })

    print(f" {len(ventas)} rows OK")

    # Other table keys left as empty arrays for HTML backward-compatibility
    return {
        'ventas':   ventas,
        'mix':      [],
        'cerveza':  [],
        'gin':      [],
        'feriado':  [],
    }


def fetch_historical_for_insights(client):
    """
    Fetch lightweight monthly aggregation for the past 24 months.
    Used exclusively by the insights generator for YoY comparisons.
    Returns rows in the same format as ventas but aggregated by day+marca+canal.
    Only fetches: Fecha, Marca, Canal, Origen, sum(Orden), sum(Facturacion), avg_ticket.
    """
    print("  Querying 24-month history for YoY insights...", end='', flush=True)
    query = f"""
        SELECT
            Fecha,
            Marca,
            Canal,
            Origen,
            COUNT(DISTINCT Orden)                                                                         AS ordenes,
            CAST(ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64))) AS INT64)                               AS ventas,
            CAST(ROUND(SAFE_DIVIDE(SUM(SAFE_CAST(Total AS FLOAT64)), COUNT(DISTINCT Orden))) AS INT64) AS ticket
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 24 MONTH)
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        GROUP BY Fecha, Marca, Canal, Origen
        ORDER BY Fecha DESC
    """
    job = client.query(query)
    rows = job.result()

    hist = []
    for row in rows:
        hist.append({
            'd':     row.Fecha.strftime('%Y-%m-%d'),
            'e':     '',
            'marca': row.Marca,
            'c':     row.Canal,
            't':     '',
            'o':     row.ordenes,
            'v':     row.ventas,
            'total': row.ventas,
            'tk':    row.ticket,
            'orig':  row.Origen,
        })

    print(f" {len(hist)} rows OK")
    return hist

## ── Helpers de fecha ─────────────────────────────────────────────────────────

def _prev_month(mes):
    y, m = int(mes[:4]), int(mes[5:])
    return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"

def _yoy_month(mes):
    y, m = int(mes[:4]), int(mes[5:])
    return f"{y-1}-{m:02d}"

def _mes_label(mes):
    MESES = {"01":"Ene","02":"Feb","03":"Mar","04":"Abr","05":"May","06":"Jun",
             "07":"Jul","08":"Ago","09":"Sep","10":"Oct","11":"Nov","12":"Dic"}
    y, m = mes[:4], mes[5:]
    return f"{MESES[m]} {y[2:]}"

def _months_range(end_mes, count):
    """Lista de `count` meses consecutivos terminando en end_mes."""
    result, cur = [], end_mes
    for _ in range(count):
        result.insert(0, cur)
        cur = _prev_month(cur)
    return result

## ── Objetivos desde BQ ───────────────────────────────────────────────────────

def fetch_objetivos_data(client=None):
    """
    Lee el Google Sheet de Objetivos directamente via Sheets API (bypass BQ external table).
    Devuelve dict con el formato que espera el JS:
      { "Patagonia": { "2026-04": {"obj_fac": 3500, "obj_ord": 90000}, ... }, ... }

    obj_fac en millones (igual que MENSUAL.fac). obj_ord es count de órdenes.
    El service account debe tener acceso Viewer al Sheet.
    """
    SHEET_ID   = "18gkS8YNGVpL0AlfQMemhtT3lOPeRRyORkkTvAoHi-YA"
    SHEET_NAME = "Objetivos_Temple_BQ"

    print("  Reading Objetivos from Google Sheet...", end='', flush=True)

    import google.auth
    from googleapiclient.discovery import build

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # Credenciales: SA key local o ADC en Cloud Run
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    else:
        creds, _ = google.auth.default(scopes=SCOPES)

    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    result  = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_NAME}!A1:Z2000"
    ).execute()

    values = result.get("values", [])
    if not values:
        print(" WARN Sheet vacío — usando fallback hardcodeado")
        return _objetivos_fallback()

    # Primera fila = encabezados
    headers = [h.strip() for h in values[0]]
    print(f"\n    Headers: {headers}")
    print(f"    Rows: {len(values)-1}")

    # Mapear columnas — prioridad a columnas _BQ, fallback a fuzzy match
    hl = {h.lower(): i for i, h in enumerate(headers)}
    idx_marca = next((hl[k] for k in hl if 'marca' in k), None)
    idx_mes   = next((hl[k] for k in hl if k in ('mes','month','periodo','period')), None)
    # Usar columnas _BQ si existen, sino fallback a las originales
    idx_fac   = hl.get('objetivo_facturacion_bq') or next((hl[k] for k in hl if 'fac' in k), None)
    idx_ord   = hl.get('objetivo_ordenes_bq')     or next((hl[k] for k in hl if 'ord' in k and 'order' not in k), None)

    print(f"    Mapped -> marca={headers[idx_marca] if idx_marca is not None else None}, "
          f"mes={headers[idx_mes] if idx_mes is not None else None}, "
          f"fac={headers[idx_fac] if idx_fac is not None else None}, "
          f"ord={headers[idx_ord] if idx_ord is not None else None}")

    if any(i is None for i in [idx_marca, idx_mes, idx_fac, idx_ord]):
        print(" WARN No se pudo mapear columnas — usando fallback hardcodeado")
        return _objetivos_fallback()

    result_dict = {}
    for row in values[1:]:
        def cell(i):
            try: return row[i].strip() if i < len(row) else ""
            except: return ""

        marca = cell(idx_marca)
        mes   = cell(idx_mes)[:7]   # normalizar a YYYY-MM
        fac_s = cell(idx_fac).replace(".", "").replace(",", ".")
        ord_s = cell(idx_ord).replace(".", "").replace(",", ".")

        if not marca or not mes:
            continue
        try:
            obj_fac = round(float(fac_s) / 1e6) if fac_s else 0
            obj_ord = round(float(ord_s))         if ord_s else 0
        except ValueError:
            continue

        # Acumular (SUM) — puede haber múltiples filas por marca+mes (una por local)
        if mes not in result_dict.setdefault(marca, {}):
            result_dict[marca][mes] = {"obj_fac": 0, "obj_ord": 0}
        result_dict[marca][mes]["obj_fac"] += obj_fac
        result_dict[marca][mes]["obj_ord"] += obj_ord

    total = sum(len(v) for v in result_dict.values())
    print(f" OK {total} entradas en {len(result_dict)} marcas")
    return result_dict


def _objetivos_fallback():
    return {
        "Patagonia": {
            "2026-01": {"obj_fac": 4424, "obj_ord": 117517},
            "2026-02": {"obj_fac": 3713, "obj_ord": 96928},
            "2026-03": {"obj_fac": 3548, "obj_ord": 93122},
        },
        "Temple": {
            "2026-01": {"obj_fac": 1390, "obj_ord": 41187},
            "2026-02": {"obj_fac": 1196, "obj_ord": 35518},
            "2026-03": {"obj_fac": 1620, "obj_ord": 49919},
        }
    }


def fetch_locales_obj(client):
    """
    Lee objetivos por local desde Google Sheet + real desde BQ para 2026.
    Returns list: [{b:"P"|"T", l:"LOCAL_NAME", d:{"2026-01":[real_M,obj_M],...}}]
    Formato dict en d{} permite cualquier mes sin reindexar — forward compatible.
    """
    SHEET_ID   = "18gkS8YNGVpL0AlfQMemhtT3lOPeRRyORkkTvAoHi-YA"
    SHEET_NAME = "Objetivos_Temple_BQ"

    print("  Reading LOCALES_OBJ objetivos from Sheet...", end='', flush=True)

    import google.auth
    from googleapiclient.discovery import build

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    else:
        creds, _ = google.auth.default(scopes=SCOPES)

    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    result  = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_NAME}!A1:Z2000"
    ).execute()

    values = result.get("values", [])
    if not values:
        print(" WARN Sheet vacio -- LOCALES_OBJ sera []")
        return []

    headers = [h.strip() for h in values[0]]
    hl = {h.lower(): i for i, h in enumerate(headers)}

    idx_local = next((hl[k] for k in hl if k in ('local', 'establecimiento', 'sucursal')), None)
    idx_mes   = next((hl[k] for k in hl if k in ('mes', 'month', 'periodo', 'period')), None)
    idx_marca = next((hl[k] for k in hl if 'marca' in k), None)
    idx_fac   = hl.get('objetivo_facturacion_bq') or next((hl[k] for k in hl if 'fac' in k), None)

    if any(i is None for i in [idx_local, idx_mes, idx_marca, idx_fac]):
        print(f" WARN cols no mapeadas (local={idx_local}, mes={idx_mes}, marca={idx_marca}, fac={idx_fac}) -- LOCALES_OBJ sera []")
        return []

    # Objetivos por (b, local_upper) -> {mes: obj_M}
    obj_dict = {}
    for row in values[1:]:
        def cell(i):
            try: return row[i].strip() if i < len(row) else ""
            except: return ""

        local_raw = cell(idx_local)
        mes       = cell(idx_mes)[:7]
        marca_raw = cell(idx_marca)
        fac_s     = cell(idx_fac).replace(".", "").replace(",", ".")

        if not local_raw or not mes:
            continue

        if "Patagonia" in marca_raw:
            b = "P"
        elif "Temple" in marca_raw:
            b = "T"
        else:
            continue

        try:
            obj_M = round(float(fac_s) / 1e6, 1) if fac_s else 0.0
        except ValueError:
            continue

        key = (b, local_raw.upper().strip())
        obj_dict.setdefault(key, {})[mes] = obj_M

    print(f" {len(obj_dict)} locales con objetivo.", end='', flush=True)

    # Real por local desde BQ (2026)
    print("  Querying BQ real por local 2026...", end='', flush=True)
    q = f"""
        SELECT
            FORMAT_DATE('%Y-%m', Fecha) AS mes,
            Marca,
            UPPER(TRIM(Local)) AS local_name,
            ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64)) / 1e6, 1) AS real_M
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE EXTRACT(YEAR FROM Fecha) = 2026
          AND Marca IN ('Patagonia', 'Temple')
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        GROUP BY mes, Marca, local_name
        ORDER BY mes, Marca, local_name
    """
    bq_rows = list(client.query(q).result())
    print(f" {len(bq_rows)} rows OK")

    # Index BQ results: (b, local_upper) -> {mes: real_M}
    real_dict = {}
    for r in bq_rows:
        if r.Marca == "Patagonia":
            b = "P"
        elif r.Marca == "Temple":
            b = "T"
        else:
            continue
        key = (b, (r.local_name or "").upper().strip())
        real_dict.setdefault(key, {})[r.mes] = round(float(r.real_M or 0), 1)

    # Aliases: nombre en la planilla (upper) → nombre en BQ (upper)
    # Agregar aquí cuando el nombre del local difiere entre Sheet y BQ.
    LOCAL_ALIASES = {
        ("P", "PARQUE LELOIR"): "LELOIR",
    }

    # Merge: one entry per (b, local) from objectives, real from BQ (0 if no data yet)
    result_list = []
    for (b, local_upper), obj_months in obj_dict.items():
        bq_key = LOCAL_ALIASES.get((b, local_upper), local_upper)
        real_months = real_dict.get((b, bq_key), {})
        d = {}
        for mes, obj_M in obj_months.items():
            if obj_M > 0:
                real_M = real_months.get(mes, 0.0)
                d[mes] = [round(real_M, 1), round(obj_M, 1)]
        if d:
            result_list.append({"b": b, "l": local_upper, "d": d})

    result_list.sort(key=lambda x: (x["b"], x["l"]))

    total_entries = sum(len(r["d"]) for r in result_list)
    print(f"  OK LOCALES_OBJ: {len(result_list)} locales, {total_entries} entradas mes/local")
    return result_list


def fetch_loc_count_by_mes(client):
    """
    Cuenta locales activos (con ventas > 0) por marca y mes en el año en curso.
    Returns dict: {"YYYY-MM": {"P": N, "T": N, "F": N}, ...}
    """
    q = f"""
        SELECT
            FORMAT_DATE('%Y-%m', Fecha) AS mes,
            Marca,
            COUNT(DISTINCT Local) AS cnt
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE EXTRACT(YEAR FROM Fecha) = EXTRACT(YEAR FROM CURRENT_DATE())
          AND SAFE_CAST(Facturacion AS FLOAT64) > 0
        GROUP BY mes, Marca
        ORDER BY mes, Marca
    """
    brand_map = {"Patagonia": "P", "Temple": "T", "Feriado": "F"}
    result = {}
    for r in client.query(q).result():
        b = brand_map.get(r.Marca)
        if not b:
            continue
        result.setdefault(r.mes, {"P": 0, "T": 0, "F": 0})[b] = int(r.cnt)
    return result


## ── Queries para datos JS dinámicos ──────────────────────────────────────────

def fetch_mensual_data(client):
    print("  Querying MENSUAL (monthly agg)...", end='', flush=True)
    q = f"""
        SELECT FORMAT_DATE('%Y-%m', Fecha) AS mes, Marca AS m,
               SAFE_CAST(ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64))/1e6) AS INT64) AS fac,
               COUNT(DISTINCT Orden)                                                 AS ord,
               SAFE_CAST(ROUND(SAFE_DIVIDE(SUM(SAFE_CAST(Total AS FLOAT64)),
                                           COUNT(DISTINCT Orden))) AS INT64)         AS tick
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 MONTH)
          AND Marca IS NOT NULL
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        GROUP BY mes, m ORDER BY mes, m
    """
    rows = list(client.query(q).result())
    print(f" {len(rows)} rows OK")
    return [{"mes": r.mes, "m": r.m, "fac": r.fac or 0, "ord": r.ord or 0, "tick": r.tick or 0} for r in rows]

def fetch_turnos_data(client):
    COLORS = {"Tarde":"#34d399","Noche":"#818cf8","Mañana":"#fbbf24",
              "Extra":"#f87171","Almuerzo":"#60a5fa","Desayuno":"#a78bfa"}
    print("  Querying TURNOS...", end='', flush=True)
    q = f"""
        SELECT Marca AS m, Turno AS t,
               SAFE_CAST(ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64))/1e6) AS INT64) AS fac,
               COUNT(DISTINCT Orden)                                                 AS ord,
               SAFE_CAST(ROUND(SAFE_DIVIDE(SUM(SAFE_CAST(Total AS FLOAT64)),
                                           COUNT(DISTINCT Orden))) AS INT64)         AS tick
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Turno IS NOT NULL AND Marca IS NOT NULL
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        GROUP BY m, t ORDER BY m, fac DESC
    """
    rows = list(client.query(q).result())
    print(f" {len(rows)} rows OK")
    return [{"m": r.m, "t": r.t, "fac": r.fac or 0, "ord": r.ord or 0, "tick": r.tick or 0,
             "color": COLORS.get(r.t, "#94a3b8")} for r in rows]

def fetch_canal_data(client):
    print("  Querying CANAL (last 6m)...", end='', flush=True)
    q = f"""
        SELECT FORMAT_DATE('%Y-%m', Fecha) AS mes, Marca AS m, Canal AS c,
               SAFE_CAST(ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64))/1e6) AS INT64) AS fac,
               COUNT(DISTINCT Orden)                                                 AS ord
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
          AND Canal IS NOT NULL AND Marca IS NOT NULL
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        GROUP BY mes, m, c ORDER BY mes, m, fac DESC
    """
    rows = list(client.query(q).result())
    print(f" {len(rows)} rows OK")
    return [{"mes": r.mes, "m": r.m, "c": r.c, "fac": r.fac or 0, "ord": r.ord or 0} for r in rows]

def fetch_top10_base(client):
    """Agrega fac/ord/total por mes+marca+local para los últimos 6 meses."""
    print("  Querying TOP10 base (last 6m by local)...", end='', flush=True)
    q = f"""
        SELECT FORMAT_DATE('%Y-%m', Fecha) AS mes, Marca AS m, Local AS l,
               SAFE_CAST(ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64))/1e6) AS INT64) AS fac,
               COUNT(DISTINCT Orden)                                                 AS ord,
               SUM(SAFE_CAST(Total AS FLOAT64))                                      AS tot
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
          AND Marca IS NOT NULL AND Local IS NOT NULL
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 0 AND 1e12
        GROUP BY mes, m, l
    """
    rows = list(client.query(q).result())
    print(f" {len(rows)} rows OK")
    return [{"mes": r.mes, "m": r.m, "l": r.l, "fac": r.fac or 0, "ord": r.ord or 0, "tot": r.tot or 0}
            for r in rows]

def compute_top10(base_rows, latest_mes):
    """Calcula top-10 locales para cada período desde los datos base."""
    prev     = _prev_month(latest_mes)
    last3    = _months_range(latest_mes, 3)
    last6    = _months_range(latest_mes, 6)
    periods  = {"mes_actual": [latest_mes], "mes_anterior": [prev],
                "ultimos_3m": last3,        "ultimos_6m":   last6}
    result = []
    for pk, months in periods.items():
        month_set = set(months)
        agg = {}
        for r in base_rows:
            if r["mes"] not in month_set:
                continue
            key = (r["m"], r["l"])
            if key not in agg:
                agg[key] = {"fac": 0, "ord": 0, "tot": 0.0}
            agg[key]["fac"] += r["fac"]
            agg[key]["ord"] += r["ord"]
            agg[key]["tot"] += r["tot"]
        for (marca, local), v in sorted(agg.items(), key=lambda x: -x[1]["fac"])[:10]:
            tick = round(v["tot"] / v["ord"]) if v["ord"] > 0 else 0
            result.append({"p": pk, "m": marca, "l": local,
                           "fac": v["fac"], "ord": int(v["ord"]), "tick": tick})
    return result

def compute_pd(mensual_rows):
    """Construye el objeto PD con etiquetas y rangos de meses dinámicos."""
    meses_set = sorted({r["mes"] for r in mensual_rows})
    if not meses_set:
        return {}
    latest = meses_set[-1]
    prev   = _prev_month(latest)
    last3  = _months_range(latest, 3)
    last6  = _months_range(latest, 6)
    ytd    = [m for m in meses_set if m[:4] == latest[:4]]
    avail  = set(meses_set)

    def fa(lst): return [m for m in lst if m in avail] if lst else None

    return {
        "todo":         {"label": "Todo el periodo", "meses": None, "prevMeses": None,
                         "prevLabel": "", "yoyMeses": None, "yoyLabel": ""},
        "mes_actual":   {"label": f"Este mes ({_mes_label(latest)})",
                         "meses": [latest], "prevMeses": fa([prev]),
                         "prevLabel": _mes_label(prev),
                         "yoyMeses": fa([_yoy_month(latest)]),
                         "yoyLabel": _mes_label(_yoy_month(latest))},
        "mes_anterior": {"label": f"Mes pasado ({_mes_label(prev)})",
                         "meses": fa([prev]), "prevMeses": fa([_prev_month(prev)]),
                         "prevLabel": _mes_label(_prev_month(prev)),
                         "yoyMeses": fa([_yoy_month(prev)]),
                         "yoyLabel": _mes_label(_yoy_month(prev))},
        "ultimos_3m":   {"label": "Últimos 3 meses",
                         "meses": fa(last3),
                         "prevMeses": fa(_months_range(_prev_month(last3[0]), 3)),
                         "prevLabel": f"{_mes_label(_prev_month(last3[0]))}–{_mes_label(prev)}",
                         "yoyMeses": fa([_yoy_month(m) for m in last3]),
                         "yoyLabel": f"{_mes_label(_yoy_month(last3[0]))}–{_mes_label(_yoy_month(latest))}"},
        "ultimos_6m":   {"label": "Últimos 6 meses",
                         "meses": fa(last6),
                         "prevMeses": fa(_months_range(_prev_month(last6[0]), 6)),
                         "prevLabel": f"{_mes_label(_prev_month(last6[0]))}–{_mes_label(prev)}",
                         "yoyMeses": fa([_yoy_month(m) for m in last6]),
                         "yoyLabel": f"{_mes_label(_yoy_month(last6[0]))}–{_mes_label(_yoy_month(latest))}"},
        "ytd":          {"label": f"YTD {latest[:4]}",
                         "meses": fa(ytd),
                         "prevMeses": fa([_yoy_month(m) for m in ytd]),
                         "prevLabel": f"YTD {int(latest[:4])-1}",
                         "yoyMeses": fa([_yoy_month(m) for m in ytd]),
                         "yoyLabel": f"YTD {int(latest[:4])-1}"},
    }

def compute_dias_data(ventas_rows, mensual_rows):
    """Calcula distribución de facturación por día de la semana, por período y marca."""
    from datetime import datetime as _dt
    DOW_ES  = {0:"Lun", 1:"Mar", 2:"Mie", 3:"Jue", 4:"Vie", 5:"Sab", 6:"Dom"}
    DOW_NUM = {0:2, 1:3, 2:4, 3:5, 4:6, 5:7, 6:1}

    # Pre-calcular día de semana por fecha para no repetir strptime
    dow_cache = {}
    def get_dow(d):
        if d not in dow_cache:
            try: dow_cache[d] = _dt.strptime(d, "%Y-%m-%d").weekday()
            except: dow_cache[d] = None
        return dow_cache[d]

    pd_periods = compute_pd(mensual_rows)
    result = {}

    for periodo, pd_info in pd_periods.items():
        meses_filter = set(pd_info.get("meses") or [])
        filtered = [r for r in ventas_rows if r["d"][:7] in meses_filter] if meses_filter else ventas_rows

        agg = {}
        for r in filtered:
            weekday = get_dow(r["d"])
            if weekday is None: continue
            dia = DOW_ES[weekday]
            key = (r["marca"], dia)
            if key not in agg:
                agg[key] = {"m": r["marca"], "dia": dia, "dow": DOW_NUM[weekday], "fac": 0.0}
            agg[key]["fac"] += r["v"] / 1_000_000

        result[periodo] = [
            {"m": v["m"], "dia": v["dia"], "dow": v["dow"], "fac": round(v["fac"])}
            for v in agg.values()
        ]

    return result

def compute_preset_meses(mensual_rows):
    meses_set = sorted({r["mes"] for r in mensual_rows})
    if not meses_set:
        return {}
    latest = meses_set[-1]; prev = _prev_month(latest)
    last3  = _months_range(latest, 3); last6 = _months_range(latest, 6)
    ytd    = [m for m in meses_set if m[:4] == latest[:4]]
    return {
        "todo":         [meses_set[0], latest],
        "mes_actual":   [latest, latest],
        "mes_anterior": [prev, prev],
        "ultimos_3m":   [last3[0], latest],
        "ultimos_6m":   [last6[0], latest],
        "ytd":          [ytd[0] if ytd else latest[:4]+"-01", latest],
    }

## ─────────────────────────────────────────────────────────────────────────────

def fetch_royalty_data():
    """
    Lee la hoja 'Resumen' del Google Sheet de royalties.
    Devuelve dict:
      { "monthly": {"Temple": {"2026-01": {"gmv": 1510608232, "roy": 35345451, "pct": 2.34}, ...}, ...},
        "avgPct":  {"Temple": 2.46, "Patagonia": 3.89, "Feriado": 2.68} }
    """
    SHEET_ID   = "19NIUwq4t-IBiEOG40U3XIiLhgH5ni_6J7Ej3oJOQVEA"
    SHEET_NAME = "Resumen"
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    print("  Reading Royalties from Google Sheet...", end='', flush=True)

    try:
        sa_file = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
        if os.path.exists(sa_file):
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        else:
            import google.auth
            creds, _ = google.auth.default(scopes=SCOPES)
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result  = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"{SHEET_NAME}!A1:J30"
        ).execute()
        rows = result.get("values", [])
    except Exception as e:
        print(f" WARN Error: {e}")
        return None

    def parse_ar(s):
        if not s: return 0.0
        s = s.strip().lstrip('$').strip().replace('.','').replace(',','.')
        try: return float(s)
        except: return 0.0

    # Columnas reales del sheet: col0=Mes, 1=Temple GMV, 2=Temple ROY, 3=Temple %,
    # 4=Temple %Obj, 5=Temple Var, 6=Patagonia GMV, 7=Patagonia ROY, 8=Patagonia %
    COLS = {"Temple":(1,2,3), "Patagonia":(6,7,8)}
    MES_MAP = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
               "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}

    # Buscar la fila YTD dinámicamente (puede estar en cualquier fila)
    avg_pct = {}
    for row in rows:
        if row and row[0].strip().upper() == "YTD":
            for marca, (_, _, ci_pct) in COLS.items():
                try:
                    avg_pct[marca] = round(parse_ar(row[ci_pct].replace('%','')) if ci_pct < len(row) else 0, 2)
                except: avg_pct[marca] = 3.5
            break

    # Filas de datos mensuales: solo las que tienen nombre de mes reconocible
    monthly = {m: {} for m in COLS}
    current_year = datetime.now().year
    for row in rows:
        if not row: continue
        mes_num = MES_MAP.get(row[0].strip().lower() if row else "")
        if not mes_num: continue
        mes_key = f"{current_year}-{mes_num}"
        for marca, (ci_gmv, ci_roy, ci_pct) in COLS.items():
            try:
                gmv = parse_ar(row[ci_gmv] if ci_gmv < len(row) else "")
                roy = parse_ar(row[ci_roy] if ci_roy < len(row) else "")
                pct = parse_ar(row[ci_pct].replace('%','') if ci_pct < len(row) else "")
                if gmv > 0 or roy > 0:
                    monthly[marca][mes_key] = {"gmv": round(gmv), "roy": round(roy), "pct": round(pct,2)}
            except: continue

    total = sum(len(v) for v in monthly.values())
    print(f" OK {total} entradas · avgPct={avg_pct}")
    return {"monthly": monthly, "avgPct": avg_pct}


def fetch_producto_data(client, desde, hasta):
    """Consulta vw_productos_maestro_clean y retorna estructura JSON para la vista Producto, filtrable por marca."""
    from dateutil.relativedelta import relativedelta
    from datetime import date as _date

    d_desde   = _date.fromisoformat(desde)
    d_hasta   = _date.fromisoformat(hasta)

    desde_m1  = (d_desde - relativedelta(months=1)).isoformat()
    hasta_m1  = (d_hasta - relativedelta(months=1)).isoformat()
    desde_y1  = (d_desde - relativedelta(years=1)).isoformat()
    hasta_y1  = (d_hasta - relativedelta(years=1)).isoformat()

    _tbl = f"`{PROJECT_ID}.{DATASET_CORP}.{TABLE_PROD}`"
    print(f"  [producto] Fetching {PROJECT_ID}.{DATASET_CORP}.{TABLE_PROD} ...")

    q_evol = f"""
    SELECT
      CAST(fecha AS STRING) AS fecha,
      establecimiento,
      marca,
      SUM(cerveza_total)  AS cerveza_lts,
      SUM(gin_total)      AS gin_lts,
      SUM(fernet_total)   AS fernet_lts,
      SUM(feriado_total)  AS feriado_lts,
      SUM(dinero)         AS pesos
    FROM {_tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY fecha, establecimiento, marca
    ORDER BY fecha, establecimiento
    """

    q_comp = f"""
    SELECT 'mes_ant' AS periodo, marca,
      SUM(cerveza_total) AS c, SUM(gin_total) AS g,
      SUM(fernet_total)  AS f, SUM(feriado_total) AS fer
    FROM {_tbl}
    WHERE fecha BETWEEN '{desde_m1}' AND '{hasta_m1}'
    GROUP BY periodo, marca
    UNION ALL
    SELECT 'anio_ant' AS periodo, marca,
      SUM(cerveza_total), SUM(gin_total),
      SUM(fernet_total),  SUM(feriado_total)
    FROM {_tbl}
    WHERE fecha BETWEEN '{desde_y1}' AND '{hasta_y1}'
    GROUP BY periodo, marca
    """

    q_rank = f"""
    SELECT
      producto, categoria, mix, tipo,
      establecimiento, marca,
      SUM(cantidad)   AS cantidad,
      SUM(dinero)     AS facturacion
    FROM {_tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY producto, categoria, mix, tipo, establecimiento, marca
    ORDER BY facturacion DESC
    LIMIT 500
    """

    q_cross = f"""
    SELECT
      establecimiento,
      marca,
      SUM(cerveza_total)  AS cerveza_lts,
      SUM(gin_total)      AS gin_lts,
      SUM(fernet_total)   AS fernet_lts,
      SUM(feriado_total)  AS feriado_lts,
      SUM(dinero)         AS total_pesos
    FROM {_tbl}
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY establecimiento, marca
    ORDER BY total_pesos DESC
    """

    rows_evol  = list(client.query(q_evol).result())
    rows_comp  = list(client.query(q_comp).result())
    rows_rank  = list(client.query(q_rank).result())
    rows_cross = list(client.query(q_cross).result())

    # ── Helpers de agregación filtrados por marca ───────────────────────────
    def _build_evolucion(rows, fm=None):
        d = {}
        for r in rows:
            if fm and (r.marca or '').upper() != fm.upper():
                continue
            ev = d.setdefault(r.fecha, {'cerveza_lts': 0.0, 'gin_lts': 0.0, 'fernet_lts': 0.0, 'feriado_lts': 0.0})
            ev['cerveza_lts']  += r.cerveza_lts  or 0
            ev['gin_lts']      += r.gin_lts      or 0
            ev['fernet_lts']   += r.fernet_lts   or 0
            ev['feriado_lts']  += r.feriado_lts  or 0
        result = [{'fecha': f, **v} for f, v in sorted(d.items())]
        for e in result:
            for k in ('cerveza_lts', 'gin_lts', 'fernet_lts', 'feriado_lts'):
                e[k] = round(e[k], 1)
        return result

    def _build_comp(rows, fm=None):
        comp = {}
        for r in rows:
            if fm and (r.marca or '').upper() != fm.upper():
                continue
            d = comp.setdefault(r.periodo, {'cerveza': 0.0, 'gin': 0.0, 'fernet': 0.0, 'feriado': 0.0})
            d['cerveza'] += r.c   or 0
            d['gin']     += r.g   or 0
            d['fernet']  += r.f   or 0
            d['feriado'] += r.fer or 0
        for vals in comp.values():
            for k in vals:
                vals[k] = round(vals[k], 1)
        return comp

    def _kpi_from_evol_comp(evolucion, comp):
        kpi_actual = {'cerveza': 0.0, 'gin': 0.0, 'fernet': 0.0, 'feriado': 0.0}
        for e in evolucion:
            kpi_actual['cerveza']  += e['cerveza_lts']
            kpi_actual['gin']      += e['gin_lts']
            kpi_actual['fernet']   += e['fernet_lts']
            kpi_actual['feriado']  += e['feriado_lts']
        kpis = {}
        for cat in ('cerveza', 'gin', 'fernet', 'feriado'):
            kpis[cat] = {
                'lts_actual':   round(kpi_actual[cat], 1),
                'lts_mes_ant':  comp.get('mes_ant',  {}).get(cat, 0),
                'lts_anio_ant': comp.get('anio_ant', {}).get(cat, None),
            }
        return kpis

    def _mix_lts_from_kpis(kpis):
        total_lts = sum(kpis[c]['lts_actual'] for c in ('cerveza', 'gin', 'fernet', 'feriado')) or 1
        return [
            {'cat': label, 'color': color,
             'lts': kpis[key]['lts_actual'],
             'pct': round(kpis[key]['lts_actual'] / total_lts * 100, 1)}
            for key, label, color in (
                ('cerveza', 'Cerveza', '#f59e0b'),
                ('gin',     'Gin',     '#818cf8'),
                ('fernet',  'Fernet',  '#34d399'),
                ('feriado', 'Feriado', '#f472b6'),
            )
        ]

    def _build_ranking(rows, fm=None):
        rank_dict = {}
        for r in rows:
            if fm and (r.marca or '').upper() != fm.upper():
                continue
            key = (r.producto or '', r.categoria or '', r.mix or '')
            entry = rank_dict.setdefault(key, {
                'producto': r.producto or '', 'categoria': r.categoria or '',
                'mix': r.mix or '', 'cantidad': 0, 'facturacion': 0.0
            })
            entry['cantidad']    += int(r.cantidad    or 0)
            entry['facturacion'] += float(r.facturacion or 0)
        total_fac = sum(e['facturacion'] for e in rank_dict.values()) or 1
        ranking = sorted(rank_dict.values(), key=lambda x: -x['facturacion'])[:50]
        for item in ranking:
            item['pct_fac']     = round(item['facturacion'] / total_fac * 100, 1)
            item['facturacion'] = round(item['facturacion'], 0)
        return ranking

    def _build_mix_tipo(rows, fm=None):
        tipo_colors = {'Bebida': '#58a6ff', 'Comida': '#fb923c',
                       'Promocion': '#a78bfa', 'Promoción': '#a78bfa', 'Merch': '#6ee7b7'}
        d = {}
        for r in rows:
            if fm and (r.marca or '').upper() != fm.upper():
                continue
            tipo = r.mix or 'Otros'
            d[tipo] = d.get(tipo, 0.0) + float(r.facturacion or 0)
        total = sum(d.values()) or 1
        return sorted([
            {'label': k, 'monto': round(v, 0),
             'pct': round(v / total * 100, 1),
             'color': tipo_colors.get(k, '#8b949e')}
            for k, v in d.items()
        ], key=lambda x: -x['monto'])

    def _build_top_por_cat(rows, fm=None):
        top = {}
        for key in ('cerveza', 'gin', 'fernet', 'feriado'):
            agg = {}
            for r in rows:
                if fm and (r.marca or '').upper() != fm.upper():
                    continue
                if key in (r.tipo or '').lower() or key in (r.categoria or '').lower():
                    p = r.producto or ''
                    agg[p] = agg.get(p, 0.0) + float(r.facturacion or 0)
            top5 = sorted(agg.items(), key=lambda x: -x[1])[:5]
            max_fac = top5[0][1] if top5 else 1
            top[key] = [{'nombre': n, 'pct': round(f / max_fac * 100, 0)} for n, f in top5]
        return top

    def _build_cross(rows, fm=None):
        result = []
        for r in rows:
            if fm and (r.marca or '').upper() != fm.upper():
                continue
            c_l   = r.cerveza_lts  or 0
            g_l   = r.gin_lts      or 0
            f_l   = r.fernet_lts   or 0
            fer_l = r.feriado_lts  or 0
            total = r.total_pesos  or 0
            total_liq = c_l + g_l + f_l + fer_l or 1
            result.append({
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
        return result

    # ── Agregar: todas las marcas ──────────────────────────────────────────
    evolucion    = _build_evolucion(rows_evol)
    comp_todas   = _build_comp(rows_comp)
    kpis         = _kpi_from_evol_comp(evolucion, comp_todas)
    mix_lts      = _mix_lts_from_kpis(kpis)
    ranking      = _build_ranking(rows_rank)
    mix_tipo     = _build_mix_tipo(rows_rank)
    top_por_cat  = _build_top_por_cat(rows_rank)
    cross        = _build_cross(rows_cross)
    establecimientos = [r['est'] for r in cross if r['est']]

    # ── Agregar: por marca ─────────────────────────────────────────────────
    evolucion_m = {}; kpis_m = {}; mix_lts_m = {}
    ranking_m = {};   mix_tipo_m = {}; top_por_cat_m = {}; cross_m = {}

    for m in ('Temple', 'Patagonia', 'Feriado'):
        ev_m            = _build_evolucion(rows_evol, m)
        comp_m          = _build_comp(rows_comp, m)
        evolucion_m[m]  = ev_m
        kpis_m[m]       = _kpi_from_evol_comp(ev_m, comp_m)
        mix_lts_m[m]    = _mix_lts_from_kpis(kpis_m[m])
        ranking_m[m]    = _build_ranking(rows_rank, m)
        mix_tipo_m[m]   = _build_mix_tipo(rows_rank, m)
        top_por_cat_m[m]= _build_top_por_cat(rows_rank, m)
        cross_m[m]      = _build_cross(rows_cross, m)

    print(f"  [producto] ✓ evolucion={len(evolucion)} días, ranking={len(ranking)} productos, cross={len(cross)} establecimientos")

    return {
        'kpis':            kpis,         'kpis_m':          kpis_m,
        'mix_lts':         mix_lts,      'mix_lts_m':       mix_lts_m,
        'ranking':         ranking,      'ranking_m':       ranking_m,
        'cross':           cross,        'cross_m':         cross_m,
        'mix_tipo':        mix_tipo,     'mix_tipo_m':      mix_tipo_m,
        'evolucion':       evolucion,    'evolucion_m':     evolucion_m,
        'top_por_cat':     top_por_cat,  'top_por_cat_m':   top_por_cat_m,
        'establecimientos': establecimientos,
    }


def generate_html_from_file(data, output_path, gcs_bucket='',
                             mensual_rows=None, turnos_rows=None,
                             canal_rows=None, top10_data=None,
                             pd_data=None, preset_meses=None,
                             objetivos_data=None, royalty_data=None,
                             locales_obj_data=None,
                             loc_count_by_mes=None,
                             dias_data=None,
                             producto_data=None):
    """Generate the dashboard HTML by reading the template.

    Template resolution order:
    1. Local file next to the script (local execution)
    2. Download from GCS (Cloud Run execution, when local file not found)

    Injections performed:
      - __INSIGHTS_HTML__    → insights generados dinámicamente (insights_generator.py)
      - __INSIGHTS_DATE__    → fecha de generación
      - __MENSUAL_JSON__     → array mensual agregado (28 meses)
      - __TURNOS_JSON__      → array de turnos por marca
      - __CANAL_JSON__       → array canal últimos 6m
      - __TOP10_JSON__       → array top-10 locales por período
      - __PD_JSON__          → objeto PD con rangos de meses dinámicos
      - __STATE_FROM_MES__   → primer mes disponible en MENSUAL
      - __STATE_TO_MES__     → último mes disponible en MENSUAL
      - __PRESET_MESES_JSON__ → objeto presetMeses con rangos
      - __LATEST_MES__       → último mes (para relevantMonths)
      - __SNAPSHOT_DATE__    → fecha de generación del snapshot
    """
    import re

    # Correct template: templates/dashboard.html
    local_template = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'dashboard.html')

    if os.path.exists(local_template):
        print(f"  Using local template: {local_template}")
        with open(local_template, 'r', encoding='utf-8') as f:
            html_template = f.read()
    elif gcs_bucket:
        print(f"  Local template not found — downloading from gs://{gcs_bucket}/dashboard_template.html ...")
        from google.cloud import storage
        storage_client = storage.Client()
        bucket = storage_client.bucket(gcs_bucket)
        blob = bucket.blob('dashboard_template.html')
        html_template = blob.download_as_text(encoding='utf-8')
        print("  OK Template downloaded from GCS")
    else:
        print(f"Error: Template file not found at {local_template} and no --gcs-bucket specified.")
        return False

    html = html_template

    # ── Inyección de RAW_DATA (si existe el placeholder en el template) ──
    json_data = json.dumps(data, separators=(',', ':'))
    if 'const RAW_DATA =' in html:
        pattern = r'const RAW_DATA = .*?;'
        html = re.sub(pattern, f'const RAW_DATA = {json_data};', html, flags=re.DOTALL)
        print("  OK RAW_DATA injected")

    # ── Inyección de Insights dinámicos ──────────────────────────────────
    if '__INSIGHTS_HTML__' in html:
        print("  Generating contextual insights (BQ data + IPC INDEC)...")
        try:
            eco_ctx = load_economic_context()
            insights = generate_insights(data.get('ventas', []), eco_ctx)
            insights_html = render_insights_html(insights)
            insights_date = datetime.now().strftime("%d %b %Y").lstrip("0")  # e.g. "11 Apr 2026"
        except Exception as exc:
            print(f"  WARN Insights generation failed: {exc} — using placeholder.")
            insights_html = '<div class="ic" style="background:#161b22;border:1px solid #30363d"><div class="it" style="color:#8b949e">⚠️ Insights temporalmente no disponibles</div><div class="ib">Los insights contextuales no pudieron generarse en este ciclo. Se actualizarán en la próxima ejecución.</div></div>'
            insights_date = datetime.now().strftime("%-d %b %Y")

        html = html.replace('__INSIGHTS_HTML__', insights_html)
        html = html.replace('__INSIGHTS_DATE__', insights_date)
        print(f"  ✓ {len(insights)} insights injected ({insights_date})")
    else:
        print("  ℹ Template does not have __INSIGHTS_HTML__ placeholder — skipping insights injection.")

    # ── Inyección del badge de frescura de datos en el header ─────────────
    if '__LAST_DATA_DATE__' in html:
        ventas = data.get('ventas', [])
        if ventas:
            last_data_dt = max(datetime.strptime(r['d'], '%Y-%m-%d').date() for r in ventas)
        else:
            last_data_dt = datetime.now().date()

        days_stale = (datetime.now().date() - last_data_dt).days

        MESES_ES = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
                    7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}
        last_data_label = f"{last_data_dt.day} {MESES_ES[last_data_dt.month]} {last_data_dt.year}"

        if days_stale <= 1:
            stale_label = "actualizado hoy"
            badge_class = "data-badge-fresh"
        elif days_stale <= 3:
            stale_label = f"hace {days_stale} días"
            badge_class = "data-badge-fresh"
        elif days_stale <= 7:
            stale_label = f"hace {days_stale} días"
            badge_class = "data-badge-warn"
        else:
            stale_label = f"hace {days_stale} días"
            badge_class = "data-badge-stale"

        html = html.replace('__LAST_DATA_DATE__', last_data_label)
        html = html.replace('__DAYS_STALE_LABEL__', stale_label)
        html = html.replace('__BADGE_CLASS__', badge_class)
        print(f"  ✓ Data freshness badge: {last_data_label} ({stale_label}) [{badge_class}]")

    # ── Inyección de arrays JS dinámicos ─────────────────────────────────
    if '__MENSUAL_JSON__' in html and mensual_rows is not None:
        meses_sorted = sorted({r["mes"] for r in mensual_rows})
        from_mes  = meses_sorted[0]  if meses_sorted else ""
        latest_mes = meses_sorted[-1] if meses_sorted else ""

        html = html.replace('__MENSUAL_JSON__',      json.dumps(mensual_rows,  separators=(',', ':')))
        html = html.replace('__TURNOS_JSON__',       json.dumps(turnos_rows  or [], separators=(',', ':')))
        html = html.replace('__CANAL_JSON__',        json.dumps(canal_rows   or [], separators=(',', ':')))
        html = html.replace('__TOP10_JSON__',        json.dumps(top10_data   or [], separators=(',', ':')))
        html = html.replace('__PD_JSON__',           json.dumps(pd_data      or {}, separators=(',', ':')))
        html = html.replace('__STATE_FROM_MES__',    from_mes)
        html = html.replace('__STATE_TO_MES__',      latest_mes)
        html = html.replace('__PRESET_MESES_JSON__', json.dumps(preset_meses or {}, separators=(',', ':')))
        html = html.replace('__LATEST_MES__',        latest_mes)
        html = html.replace('__SNAPSHOT_DATE__',     datetime.now().strftime('%Y-%m-%d'))
        print(f"  ✓ JS arrays dinámicos inyectados (latest_mes={latest_mes}, "
              f"mensual={len(mensual_rows)} rows, turnos={len(turnos_rows or [])}, "
              f"canal={len(canal_rows or [])}, top10={len(top10_data or [])})")
    else:
        print("  ℹ Sin datos dinámicos JS o placeholders ausentes — se usan los valores del template.")

    # ── Inyección de Objetivos ────────────────────────────────────────────
    if '__OBJETIVOS_JSON__' in html:
        obj = objetivos_data or {}
        html = html.replace('__OBJETIVOS_JSON__', json.dumps(obj, separators=(',', ':')))
        total_entries = sum(len(v) for v in obj.values()) if obj else 0
        print(f"  ✓ OBJETIVOS inyectados ({len(obj)} marcas, {total_entries} entradas)")

    # ── Inyección de Royalties ────────────────────────────────────────────
    if '__ROYALTY_JSON__' in html:
        rd = royalty_data or {"monthly": {}, "avgPct": {}}
        html = html.replace('__ROYALTY_JSON__', json.dumps(rd, separators=(',', ':')))
        total_r = sum(len(v) for v in rd.get("monthly", {}).values())
        print(f"  ✓ ROYALTY_DATA inyectado ({total_r} entradas mensuales)")

    # ── Inyección de LOCALES_OBJ dinámico ────────────────────────────────
    if '__LOCALES_OBJ_JSON__' in html:
        lo = locales_obj_data or []
        html = html.replace('__LOCALES_OBJ_JSON__', json.dumps(lo, separators=(',', ':')))
        print(f"  ✓ LOCALES_OBJ inyectado ({len(lo)} locales)")

    # ── Inyección de DIAS_DATA dinámico ──────────────────────────────────
    if '__DIAS_JSON__' in html:
        dd = dias_data or {}
        html = html.replace('__DIAS_JSON__', json.dumps(dd, separators=(',', ':')))
        total_dias = sum(len(v) for v in dd.values())
        print(f"  ✓ DIAS_DATA inyectado ({len(dd)} períodos, {total_dias} filas)")

    # ── Inyección de LOC_COUNT_BY_MES dinámico ───────────────────────────
    if '__LOC_COUNT_BY_MES_JSON__' in html:
        lc = loc_count_by_mes or {}
        html = html.replace('__LOC_COUNT_BY_MES_JSON__', json.dumps(lc, separators=(',', ':')))
        print(f"  ✓ LOC_COUNT_BY_MES inyectado ({len(lc)} meses)")

    # ── Inyección de PRODUCTO_JSON ────────────────────────────────────────
    if '__PRODUCTO_JSON__' in html:
        pd_json = producto_data or {}
        html = html.replace('__PRODUCTO_JSON__', json.dumps(pd_json, separators=(',', ':'), default=str))
        print(f"  ✓ PRODUCTO_JSON inyectado ({len(pd_json.get('ranking', []))} productos, {len(pd_json.get('evolucion', []))} días)")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✓ HTML dashboard saved to {output_path}")
    return True

def main():
    args = parse_args()

    print(f"=== Temple Bar Dashboard Refresh | Project: {PROJECT_ID} ===")

    try:
        # Initialize BigQuery client (auto-detects local vs Cloud Run)
        client = get_bigquery_client()

        # Fetch data (últimos 90 días para los gráficos)
        data = fetch_data(client, args.desde, args.hasta)

        # Fetch 24-month history for YoY insights (lightweight aggregation)
        # Merge with the 90-day data so insights generator has full history
        try:
            hist = fetch_historical_for_insights(client)
            # Combine: histórico primero, luego datos 90d (más detallados)
            # Deduplicar por fecha+marca+canal usando los 90d como fuente más precisa
            recent_keys = {(r['d'], r['marca'], r['c']) for r in data['ventas']}
            hist_filtered = [r for r in hist if (r['d'], r['marca'], r['c']) not in recent_keys]
            combined_ventas = hist_filtered + data['ventas']
            data_for_insights = dict(data)
            data_for_insights['ventas'] = combined_ventas
            print(f"  Total rows for insights: {len(combined_ventas)} (hist: {len(hist_filtered)} + recent: {len(data['ventas'])})")
        except Exception as exc:
            print(f"  ⚠ Historical fetch failed: {exc} — insights will use 90-day window only.")
            data_for_insights = data

        # Fetch data para los arrays JS dinámicos — queries independientes en paralelo
        print("\n── Fetching JS dynamic arrays (paralelo) ───────────────────────────")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time as _time

        def _safe(fn, *args, fallback=None, retries=2, label=""):
            """Ejecuta fn con reintentos en caso de error transitorio (503)."""
            for attempt in range(retries + 1):
                try:
                    return fn(*args)
                except Exception as exc:
                    if attempt < retries and ("503" in str(exc) or "unavailable" in str(exc).lower()):
                        print(f"  ⚠ {label} retry {attempt+1}/{retries} (503)...")
                        _time.sleep(3)
                    else:
                        print(f"  ⚠ {label} falló: {exc}")
                        return fallback() if callable(fallback) else fallback

        tasks = {
            "mensual":    lambda: fetch_mensual_data(client),
            "turnos":     lambda: fetch_turnos_data(client),
            "canal":      lambda: fetch_canal_data(client),
            "top10":      lambda: fetch_top10_base(client),
            "loc_count":  lambda: fetch_loc_count_by_mes(client),
            "objetivos":  lambda: fetch_objetivos_data(client),
            "royalty":    lambda: fetch_royalty_data(),
            "locales_obj": lambda: fetch_locales_obj(client),
        }

        results = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_map = {executor.submit(_safe, fn, fallback=None, retries=2, label=k): k
                          for k, fn in tasks.items()}
            for future in as_completed(future_map):
                k = future_map[future]
                results[k] = future.result()

        mensual_rows     = results["mensual"]     or []
        turnos_rows      = results["turnos"]      or []
        canal_rows       = results["canal"]       or []
        top10_base       = results["top10"]       or []
        loc_count_by_mes = results["loc_count"]   or {}
        objetivos_data   = results["objetivos"]   or {}
        locales_obj_data = results["locales_obj"] or []
        royalty_data     = results["royalty"]

        # Calcular estructuras derivadas
        latest_mes   = sorted({r["mes"] for r in mensual_rows})[-1] if mensual_rows else ""
        top10_data   = compute_top10(top10_base, latest_mes)
        pd_data      = compute_pd(mensual_rows)
        preset_meses = compute_preset_meses(mensual_rows)
        dias_data    = compute_dias_data(data['ventas'], mensual_rows)
        print(f"  Computed: top10={len(top10_data)} entries, PD={len(pd_data)} periods, "
              f"presetMeses={len(preset_meses)} keys")

        # Generate HTML (downloads template from GCS if not found locally)
        generate_html_from_file(
            data_for_insights, args.output, gcs_bucket=args.gcs_bucket,
            mensual_rows=mensual_rows, turnos_rows=turnos_rows,
            canal_rows=canal_rows,      top10_data=top10_data,
            pd_data=pd_data,            preset_meses=preset_meses,
            objetivos_data=objetivos_data, royalty_data=royalty_data,
            locales_obj_data=locales_obj_data,
            loc_count_by_mes=loc_count_by_mes,
            dias_data=dias_data,
            producto_data=None,
        )

        # Upload to GCS if requested (Cloud Run mode)
        public_url = ""
        if args.gcs_bucket:
            public_url = upload_to_gcs(args.output, args.gcs_bucket)

        print(f"\n Dashboard actualizado: {args.output}")
        if public_url:
            print(f"  URL: {public_url}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
