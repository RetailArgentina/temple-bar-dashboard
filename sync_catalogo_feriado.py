#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_catalogo_feriado.py
Lee las 3 hojas del Google Sheet de Feriado y las carga en BigQuery:
  - Feriado.Cat_Empresa  ← Categorizar_Bebidas  (producto → categoría por empresa)
  - Feriado.Cat_BD       ← BD       (producto → categorías + ml por unidad)
  - Feriado.Recetas_BQ   ← Recetas  (producto → ingredientes + uso)

Uso: python -X utf8 sync_catalogo_feriado.py
"""

import os
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.cloud import bigquery

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SA_KEY     = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
BQ_PROJECT = "temple-bar-439715"
SHEET_ID   = "1pNtwkL8H9pbU8fV58fjiXfZGa4tErst45ZVeCdCe024"

SCOPES_SHEETS = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_sheets_service():
    if os.path.exists(SA_KEY):
        creds = service_account.Credentials.from_service_account_file(SA_KEY, scopes=SCOPES_SHEETS)
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES_SHEETS)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def get_bq_client():
    import google.auth
    try:
        creds, _ = google.auth.default()
        return bigquery.Client(project=BQ_PROJECT, credentials=creds)
    except Exception as _adc_err:
        log(f"  ADC falló ({_adc_err!r}), usando service account key como fallback")
        return bigquery.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


def leer_hoja(service, rango: str) -> list[list]:
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=rango
        ).execute()
        return result.get("values", [])
    except Exception as exc:
        if "Unable to parse range" in str(exc) or "400" in str(exc):
            try:
                meta = service.spreadsheets().get(
                    spreadsheetId=SHEET_ID, fields="sheets.properties.title"
                ).execute()
                hojas = [s["properties"]["title"] for s in meta.get("sheets", [])]
                raise RuntimeError(
                    f"Rango inválido: '{rango}'. "
                    f"Hojas disponibles en el Sheet: {hojas}"
                ) from exc
            except RuntimeError:
                raise
            except Exception:
                pass
        raise


def cargar_tabla(client: bigquery.Client, table_id: str, schema: list, filas: list):
    """Reemplaza la tabla completa con los nuevos datos (WRITE_TRUNCATE)."""
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = client.load_table_from_json(filas, table_id, job_config=job_config)
    job.result()
    if job.errors:
        raise RuntimeError(f"Carga BQ fallida en {table_id}: {job.errors[:3]}")
    return job.output_rows or 0


# ── Hoja 18 → Cat_Empresa ────────────────────────────────────────────────────

SCHEMA_CAT_EMPRESA = [
    bigquery.SchemaField("producto_id",       "STRING",  description="Código FV del producto"),
    bigquery.SchemaField("nombre_producto",   "STRING",  description="Nombre del producto"),
    bigquery.SchemaField("categoria_empresa", "STRING",  description="Categoría por empresa (Feriado Vermu, Bosque Gin, etc.)"),
]

def sync_cat_empresa(service, client: bigquery.Client):
    log("Leyendo Categorizar_Bebidas (Cat_Empresa)...")
    rows = leer_hoja(service, "Categorizar_Bebidas!A:C")
    filas = []
    for r in rows[1:]:  # skip header
        if not r or not r[0].strip():
            continue
        filas.append({
            "producto_id":       r[0].strip(),
            "nombre_producto":   r[1].strip() if len(r) > 1 else "",
            "categoria_empresa": r[2].strip() if len(r) > 2 else "",
        })
    n = cargar_tabla(client, f"{BQ_PROJECT}.Feriado.Cat_Empresa", SCHEMA_CAT_EMPRESA, filas)
    log(f"  Cat_Empresa: {n} productos cargados")


# ── BD → Cat_BD ───────────────────────────────────────────────────────────────

SCHEMA_CAT_BD = [
    bigquery.SchemaField("producto_id",    "STRING",  description="Código FV del producto"),
    bigquery.SchemaField("nombre",         "STRING",  description="Nombre del producto"),
    bigquery.SchemaField("categoria_1",    "STRING",  description="Categoría nivel 1 (Comida/Bebida/Promocion)"),
    bigquery.SchemaField("categoria_2",    "STRING",  description="Categoría nivel 2 (Entradas, Tragos, etc.)"),
    bigquery.SchemaField("ml_por_unidad",  "FLOAT64", description="Mililitros por unidad vendida (NULL si no es líquido)"),
]

def sync_cat_bd(service, client: bigquery.Client):
    log("Leyendo BD (Cat_BD)...")
    rows = leer_hoja(service, "BD!A:E")
    filas = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        ml_raw = r[4].strip() if len(r) > 4 else ""
        try:
            ml = float(ml_raw) if ml_raw else None
        except ValueError:
            ml = None
        filas.append({
            "producto_id":   r[0].strip(),
            "nombre":        r[1].strip() if len(r) > 1 else "",
            "categoria_1":   r[2].strip() if len(r) > 2 else "",
            "categoria_2":   r[3].strip() if len(r) > 3 else "",
            "ml_por_unidad": ml,
        })
    n = cargar_tabla(client, f"{BQ_PROJECT}.Feriado.Cat_BD", SCHEMA_CAT_BD, filas)
    log(f"  Cat_BD: {n} productos cargados ({len([f for f in filas if f['ml_por_unidad']])} con ML)")


# ── Recetas → Recetas_BQ ──────────────────────────────────────────────────────

SCHEMA_RECETAS = [
    bigquery.SchemaField("producto_id",   "STRING",  description="Código FV del plato"),
    bigquery.SchemaField("plato",         "STRING",  description="Nombre del plato"),
    bigquery.SchemaField("costo_final",   "FLOAT64", description="Costo total del plato"),
    bigquery.SchemaField("insumo_id",     "STRING",  description="Código del insumo"),
    bigquery.SchemaField("ingrediente",   "STRING",  description="Nombre del ingrediente"),
    bigquery.SchemaField("uso",           "FLOAT64", description="Cantidad usada por plato"),
    bigquery.SchemaField("presentacion",  "FLOAT64", description="Tamaño del envase del insumo"),
    bigquery.SchemaField("costo_insumo",  "FLOAT64", description="Costo del insumo"),
    bigquery.SchemaField("tipo_unidad",   "STRING",  description="Unidad (G, ML, U)"),
]

def limpiar_numero(s: str) -> float | None:
    """Convierte '$1,234.56' o '1234.56' a float."""
    if not s:
        return None
    s = s.strip().replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(s) if s else None
    except ValueError:
        return None

def sync_recetas(service, client: bigquery.Client):
    log("Leyendo Recetas...")
    rows = leer_hoja(service, "Recetas!A:I")
    filas = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        filas.append({
            "producto_id":  r[0].strip(),
            "plato":        r[1].strip() if len(r) > 1 else "",
            "costo_final":  limpiar_numero(r[2]) if len(r) > 2 else None,
            "insumo_id":    r[3].strip() if len(r) > 3 else "",
            "ingrediente":  r[4].strip() if len(r) > 4 else "",
            "uso":          limpiar_numero(r[5]) if len(r) > 5 else None,
            "presentacion": limpiar_numero(r[6]) if len(r) > 6 else None,
            "costo_insumo": limpiar_numero(r[7]) if len(r) > 7 else None,
            "tipo_unidad":  r[8].strip() if len(r) > 8 else "",
        })
    n = cargar_tabla(client, f"{BQ_PROJECT}.Feriado.Recetas_BQ", SCHEMA_RECETAS, filas)
    log(f"  Recetas_BQ: {n} filas cargadas")


def main():
    log("Sincronizando catálogo Feriado (Sheet → BigQuery)")
    service = get_sheets_service()
    client  = get_bq_client()

    sync_cat_empresa(service, client)
    sync_cat_bd(service, client)
    sync_recetas(service, client)

    log("✓ Catálogo sincronizado")


if __name__ == "__main__":
    main()
