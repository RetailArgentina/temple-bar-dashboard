#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_feriado_toteat.py
ETL: Toteat API -> BigQuery (temple-bar-439715.Feriado.Ventas_Toteat)

La tabla resultante es compatible con Feriado_Maestro (mismas columnas clave)
y agrega campos extra de Toteat para análisis en Looker.

Uso:
  # Incremental (desde último registro en BQ hasta ayer):
  python -X utf8 sync_feriado_toteat.py

  # Backfill de un rango específico:
  python -X utf8 sync_feriado_toteat.py --desde 20260316 --hasta 20260511

  # Solo mostrar qué haría sin cargar nada:
  python -X utf8 sync_feriado_toteat.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests
from google.cloud import bigquery

# ── Configuración Toteat ──────────────────────────────────────────────────────
TOTEAT_BASE  = "https://api.toteat.com/mw/or/1.0"
TOTEAT_XIU   = os.environ.get("TOTEAT_XIU",   "1003")
TOTEAT_XIR   = os.environ.get("TOTEAT_XIR",   "5862845152100352")
TOTEAT_XIL   = os.environ.get("TOTEAT_XIL",   "1")
TOTEAT_TOKEN = os.environ.get("TOTEAT_TOKEN", "Cp7U3WnJGPrIR4urdU2u7pYxNkbJxiVT")
LOCAL_NOMBRE = os.environ.get("TOTEAT_LOCAL", "COGHLAN")  # nombre canónico del local en BQ
MARCA        = "FERIADO"
MAX_DIAS_POR_REQ = 14              # Toteat permite máx 15 días; usamos 14 por seguridad
REQ_PAUSE_SEG    = 22              # 3 req/min → 20 seg entre llamadas + margen

# ── Configuración BigQuery ────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SA_KEY      = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
BQ_PROJECT  = "temple-bar-439715"
BQ_DATASET  = "Feriado"
BQ_TABLE    = "Ventas_Toteat"
BQ_TABLE_ID = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

# ── Schema BQ ─────────────────────────────────────────────────────────────────
# Compatible con Feriado_Maestro + campos extra Toteat
BQ_SCHEMA = [
    # — Clave de dedup —
    bigquery.SchemaField("row_key",          "STRING",   description="orderId_paymentId_prodIdx — clave única"),
    # — Campos compatibles con Feriado_Maestro —
    bigquery.SchemaField("Establecimiento",  "STRING",   description="Nombre del local"),
    bigquery.SchemaField("Producto",         "STRING",   description="Nombre del producto"),
    bigquery.SchemaField("Fecha",            "DATE",     description="Fecha de apertura del turno"),
    bigquery.SchemaField("Turno",            "STRING",   description="Mediodía/Tarde/Noche (derivado)"),
    bigquery.SchemaField("Canal",            "STRING",   description="Salón/Delivery/App"),
    bigquery.SchemaField("Cantidad",         "INTEGER",  description="Unidades vendidas"),
    bigquery.SchemaField("Dinero",           "FLOAT64",  description="Monto cobrado por el producto"),
    bigquery.SchemaField("Mix",              "STRING",   description="Categoría del producto (hierarchyName)"),
    # — Campos extra Toteat —
    bigquery.SchemaField("orden_id",         "STRING",   description="ID único de la orden Toteat"),
    bigquery.SchemaField("producto_id",      "STRING",   description="ID del producto en Toteat"),
    bigquery.SchemaField("categoria_id",     "STRING",   description="ID de jerarquía (hierarchyId)"),
    bigquery.SchemaField("hora_apertura",    "DATETIME", description="Fecha+hora de apertura de la orden"),
    bigquery.SchemaField("hora_cierre",      "DATETIME", description="Fecha+hora de cierre de la orden"),
    bigquery.SchemaField("mesa",             "STRING",   description="Mesa / tableId"),
    bigquery.SchemaField("zona",             "STRING",   description="Zona del local"),
    bigquery.SchemaField("mozo",             "STRING",   description="Nombre del mozo"),
    bigquery.SchemaField("precio_unitario",  "FLOAT64",  description="Precio neto unitario"),
    bigquery.SchemaField("descuentos",       "FLOAT64",  description="Descuentos sobre el producto"),
    bigquery.SchemaField("impuestos",        "FLOAT64",  description="Impuestos del producto"),
    bigquery.SchemaField("total_orden",      "FLOAT64",  description="Total de la orden (todos los productos)"),
    bigquery.SchemaField("descuentos_orden", "FLOAT64",  description="Descuentos aplicados a nivel de orden"),
    bigquery.SchemaField("medio_pago",       "STRING",   description="Medio de pago principal de la orden"),
    bigquery.SchemaField("medios_pago_json", "STRING",   description="JSON de todos los medios de pago"),
    bigquery.SchemaField("n_clientes",       "INTEGER",  description="Cantidad de comensales"),
    bigquery.SchemaField("fuente",           "STRING",   description="Origen del dato (toteat_api)"),
    bigquery.SchemaField("cargado_at",       "DATETIME", description="Timestamp de carga en BQ"),
]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Derivar campos ────────────────────────────────────────────────────────────

def derivar_turno(hora: int) -> str:
    if 10 <= hora <= 18:
        return "Tarde"
    else:
        return "Noche"


def derivar_canal(table_name: str, table_id, comment: str) -> str:
    tid = str(table_id or "").upper()
    tn  = str(table_name or "").upper()
    cmt = (comment or "").upper()
    if tid.startswith("V-") or tn in ("VIRTUAL", "DELIVERY") or "DELIVERY" in cmt:
        return "Delivery"
    if "RAPPI" in cmt or "PEDIDOSYA" in cmt or "PEDIDOS YA" in cmt:
        return "App"
    return "Salón"


def medio_pago_principal(payment_forms: list) -> str:
    if not payment_forms:
        return ""
    # El que tiene mayor monto
    return max(payment_forms, key=lambda p: p.get("amount", 0)).get("name", "")


# ── Toteat API ────────────────────────────────────────────────────────────────

def fetch_ventas(ini: date, end: date, intento: int = 1) -> list:
    """Llama a /sales para el rango ini–end. Devuelve lista de órdenes."""
    url = (
        f"{TOTEAT_BASE}/sales"
        f"?xir={TOTEAT_XIR}&xil={TOTEAT_XIL}&xiu={TOTEAT_XIU}"
        f"&xapitoken={TOTEAT_TOKEN}"
        f"&ini={ini.strftime('%Y%m%d')}&end={end.strftime('%Y%m%d')}"
    )
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            log(f"  API retornó ok=false para {ini}–{end}: {data}")
            return []
        return data.get("data", [])
    except requests.RequestException as e:
        if intento < 3:
            log(f"  Error en request ({e}), reintento {intento+1}...")
            time.sleep(10)
            return fetch_ventas(ini, end, intento + 1)
        log(f"  Error definitivo fetching {ini}–{end}: {e}")
        return []


def ordenes_a_filas(ordenes: list, cargado_at: datetime) -> list:
    """Convierte lista de órdenes Toteat en filas para BQ (1 fila por producto)."""
    filas = []
    for o in ordenes:
        orden_id   = str(o.get("orderId", ""))
        payment_id = str(o.get("paymentId", ""))
        date_open  = o.get("dateOpen", "")
        date_close = o.get("dateClosed", "")

        try:
            dt_open = datetime.fromisoformat(date_open)
        except Exception:
            dt_open = None

        try:
            dt_close = datetime.fromisoformat(date_close)
        except Exception:
            dt_close = None

        fecha  = dt_open.date() if dt_open else None
        turno  = derivar_turno(dt_open.hour) if dt_open else None
        canal  = derivar_canal(
            o.get("tableName", ""),
            o.get("tableId", ""),
            o.get("comment", ""),
        )
        medio  = medio_pago_principal(o.get("paymentForms", []))
        medios_json = json.dumps(o.get("paymentForms", []), ensure_ascii=False)

        for idx, p in enumerate(o.get("products", [])):
            row_key = f"{orden_id}_{payment_id}_{idx}"
            filas.append({
                "row_key":          row_key,
                # Feriado_Maestro compatible
                "Establecimiento":  LOCAL_NOMBRE,
                "Producto":         p.get("name", ""),
                "Fecha":            fecha.isoformat() if fecha else None,
                "Turno":            turno,
                "Canal":            canal,
                "Cantidad":         int(p.get("quantity", 1)),
                "Dinero":           float(p.get("payed", 0)),
                "Mix":              p.get("hierarchyName", ""),
                # Extra Toteat
                "orden_id":         orden_id,
                "producto_id":      p.get("id", ""),
                "categoria_id":     p.get("hierarchyId", ""),
                "hora_apertura":    dt_open.isoformat() if dt_open else None,
                "hora_cierre":      dt_close.isoformat() if dt_close else None,
                "mesa":             o.get("tableId", ""),
                "zona":             o.get("zoneName", ""),
                "mozo":             o.get("waiterName", ""),
                "precio_unitario":  float(p.get("netPrice", 0)),
                "descuentos":       float(p.get("discounts", 0)),
                "impuestos":        float(p.get("taxes", 0)),
                "total_orden":      float(o.get("total", 0)),
                "descuentos_orden": float(o.get("discounts", 0)),
                "medio_pago":       medio,
                "medios_pago_json": medios_json,
                "n_clientes":       int(o.get("numberClients", 1)),
                "fuente":           "toteat_api",
                "cargado_at":       cargado_at.isoformat(),
            })
    return filas


# ── BigQuery ──────────────────────────────────────────────────────────────────

def get_bq_client():
    import google.auth
    try:
        creds, _ = google.auth.default()
        return bigquery.Client(project=BQ_PROJECT, credentials=creds)
    except Exception:
        # Fallback a service account si ADC no está disponible
        return bigquery.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


def crear_tabla(client: bigquery.Client, recrear: bool = False):
    """Crea (o recrea) la tabla Ventas_Toteat."""
    table_ref = bigquery.Table(BQ_TABLE_ID, schema=BQ_SCHEMA)
    table_ref.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="Fecha",
    )
    table_ref.clustering_fields = ["Canal", "Mix", "Establecimiento"]
    if recrear:
        client.delete_table(BQ_TABLE_ID, not_found_ok=True)
        client.create_table(table_ref)
        log(f"  Tabla {BQ_TABLE} recreada (vacía).")
        return
    try:
        client.get_table(BQ_TABLE_ID)
        log(f"  Tabla {BQ_TABLE} ya existe.")
    except Exception:
        client.create_table(table_ref)
        log(f"  Tabla {BQ_TABLE} creada (particionada por Fecha).")


def ultima_fecha_en_bq(client: bigquery.Client) -> date | None:
    """Devuelve la fecha más reciente cargada en Ventas_Toteat."""
    try:
        q = f"SELECT MAX(Fecha) as ultima FROM `{BQ_TABLE_ID}`"
        for r in client.query(q).result():
            return r.ultima
    except Exception:
        return None


def borrar_rango(client: bigquery.Client, desde: date, hasta: date, dry_run: bool):
    """Elimina filas del rango para permitir recarga limpia."""
    q = (
        f"DELETE FROM `{BQ_TABLE_ID}` "
        f"WHERE Fecha BETWEEN '{desde.isoformat()}' AND '{hasta.isoformat()}'"
    )
    if dry_run:
        log(f"  [DRY-RUN] DELETE {desde} → {hasta}")
        return
    client.query(q).result()
    log(f"  Borradas filas {desde} → {hasta}")


def insertar_filas(client: bigquery.Client, filas: list, dry_run: bool) -> int:
    """Inserta filas en BQ usando load job (no streaming buffer). Devuelve cantidad insertada."""
    if not filas:
        return 0
    if dry_run:
        log(f"  [DRY-RUN] insertaría {len(filas)} filas")
        return len(filas)
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    import json as _json
    ndjson = "\n".join(_json.dumps(f, ensure_ascii=False, default=str) for f in filas)
    job = client.load_table_from_json(
        [_json.loads(l) for l in ndjson.splitlines()],
        BQ_TABLE_ID,
        job_config=job_config,
    )
    job.result()  # espera a que termine el load job
    if job.errors:
        log(f"  ERRORES en load job: {job.errors[:3]}")
    return len(filas)


# ── Lógica principal ──────────────────────────────────────────────────────────

def sync_rango(client: bigquery.Client, desde: date, hasta: date, dry_run: bool):
    """Sincroniza el rango desde–hasta en chunks de MAX_DIAS_POR_REQ días.
    Acumula todas las filas en memoria y deduplica por row_key antes de insertar,
    para evitar duplicados cuando la API devuelve la misma orden en dos chunks."""
    log(f"Sincronizando {desde} → {hasta} ({(hasta - desde).days + 1} días)")
    borrar_rango(client, desde, hasta, dry_run)

    all_filas     = {}   # row_key → fila  (dedup en memoria)
    total_ordenes = 0
    cargado_at    = datetime.now()

    chunk_ini = desde
    llamada   = 0
    while chunk_ini <= hasta:
        chunk_fin = min(chunk_ini + timedelta(days=MAX_DIAS_POR_REQ - 1), hasta)

        if llamada > 0:
            log(f"  Esperando {REQ_PAUSE_SEG}s (rate limit Toteat)...")
            time.sleep(REQ_PAUSE_SEG)

        log(f"  Fetching {chunk_ini} → {chunk_fin}...")
        ordenes = fetch_ventas(chunk_ini, chunk_fin)
        filas   = ordenes_a_filas(ordenes, cargado_at)

        nuevas = dups = 0
        for f in filas:
            if f["row_key"] not in all_filas:
                all_filas[f["row_key"]] = f
                nuevas += 1
            else:
                dups += 1

        log(f"    {len(ordenes)} órdenes → {nuevas} filas nuevas, {dups} dups descartados")
        total_ordenes += len(ordenes)
        llamada       += 1
        chunk_ini      = chunk_fin + timedelta(days=1)

    filas_unicas = list(all_filas.values())
    n = insertar_filas(client, filas_unicas, dry_run)
    log(f"  Total: {total_ordenes} órdenes, {n} filas únicas en BQ")
    return n


def main():
    parser = argparse.ArgumentParser(description="Sync Feriado Toteat → BigQuery")
    parser.add_argument("--desde",    help="Fecha inicio YYYYMMDD (default: último en BQ)")
    parser.add_argument("--hasta",    help="Fecha fin YYYYMMDD (default: ayer)")
    parser.add_argument("--recrear",  action="store_true", help="Borra y recrea la tabla antes de cargar (útil para backfill completo)")
    parser.add_argument("--dry-run",  action="store_true", help="No escribe en BQ")
    args = parser.parse_args()

    ayer = date.today() - timedelta(days=1)

    client = get_bq_client()

    # --recrear: vacía la tabla para evitar conflictos con el streaming buffer
    if args.recrear and not args.dry_run:
        log("--recrear: eliminando y recreando la tabla...")
        crear_tabla(client, recrear=True)
    else:
        crear_tabla(client, recrear=False)

    # Determinar rango
    if args.hasta:
        hasta = datetime.strptime(args.hasta, "%Y%m%d").date()
    else:
        hasta = ayer

    if args.desde:
        desde = datetime.strptime(args.desde, "%Y%m%d").date()
    else:
        ultima = ultima_fecha_en_bq(client)
        if ultima:
            # Re-sincronizamos desde el último día registrado para capturar
            # órdenes que cruzaron la medianoche y tienen Fecha del día siguiente
            desde = ultima
            log(f"Modo incremental: último en BQ = {ultima}, re-sync desde {desde}")
            # Verificar gaps: comparar fechas únicas vs rango esperado
            try:
                q_gap = f"""
                    SELECT MIN(Fecha) as primera, MAX(Fecha) as ultima,
                           COUNT(DISTINCT Fecha) as dias_con_datos
                    FROM `{BQ_TABLE_ID}`
                """
                for r in client.query(q_gap).result():
                    if r.primera and r.ultima:
                        rango_esperado = (r.ultima - r.primera).days + 1
                        if r.dias_con_datos < rango_esperado * 0.9:
                            log(f"  ADVERTENCIA: posibles gaps — {r.dias_con_datos} días con datos "
                                f"vs {rango_esperado} días en rango {r.primera}→{r.ultima}. "
                                f"Considerá correr --desde {r.primera.strftime('%Y%m%d')} --hasta {r.ultima.strftime('%Y%m%d')}")
            except Exception as e:
                log(f"  (No se pudo verificar gaps: {e})")
        else:
            log("Tabla vacía — sync completo desde 2024-01-01")
            desde = date(2024, 1, 1)

    if desde > hasta:
        log(f"Nada que sincronizar (desde={desde} > hasta={hasta})")
        return

    log(f"{'[DRY-RUN] ' if args.dry_run else ''}Iniciando sync Feriado Toteat")
    log(f"  Tabla destino: {BQ_TABLE_ID}")
    log(f"  Rango: {desde} → {hasta}")

    total = sync_rango(client, desde, hasta, args.dry_run)
    log(f"✓ Sync completo — {total} filas {'(DRY-RUN)' if args.dry_run else 'en BQ'}")


if __name__ == "__main__":
    main()
