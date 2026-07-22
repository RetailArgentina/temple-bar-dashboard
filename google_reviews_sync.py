#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
google_reviews_sync.py
P5 del plan "tablero de reseñas Google".

Por cada local con mapeo verificado en Firestore (google_places_mapping,
status="verified"), consulta el rating/reseñas actual vía Google Places
Details API, guarda un snapshot numérico (rating, total_reviews) en BigQuery
(temple-bar-439715.Corporativo.google_reviews_snapshots) y genera
resenas.html a partir de templates/resenas_preview.html con el detalle
completo de reseñas (texto incluido) para consumo del día — el texto de las
reseñas NO se persiste en BigQuery (solo rating/total_reviews numéricos),
por los términos de servicio de Google sobre no archivar contenido de
reseñas a largo plazo.

Detección de alertas: mantiene un doc chico por local en Firestore
(colección google_reviews_last_seen) con las keys de reseñas ya vistas.
Reseñas nuevas con rating <= 2 marcan is_alert=True para ese local.

Uso:
    python -X utf8 google_reviews_sync.py --test-mode --no-upload
        # 2 locales hardcodeados (BARRIO_CHINO / MONROE), sin subir a GCS

    python -X utf8 google_reviews_sync.py
        # corrida real: lee mappings verificados de Firestore, sube a GCS
"""

import os
import sys
import json
import argparse
from datetime import datetime, date, timezone

import permissions

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SA_KEY_FILE = "temple-bar-439715-da51b292ce5d.json"
SA_KEY = os.path.join(SCRIPT_DIR, SA_KEY_FILE)
BQ_PROJECT = "temple-bar-439715"
BQ_DATASET = "Corporativo"
BQ_TABLE = "google_reviews_snapshots"
BQ_TABLE_ID = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

OUTPUT_FILE = "resenas.html"
TEMPLATE = os.path.join(SCRIPT_DIR, "templates", "resenas_preview.html")

PLACES_URL = "https://maps.googleapis.com/maps/api/place/details/json"

LAST_SEEN_COLLECTION = "google_reviews_last_seen"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Clientes GCP (mismo patrón que resolver_place_ids.py) ──────────────────
def get_bq_client():
    import google.auth
    from google.cloud import bigquery
    try:
        creds, _ = google.auth.default()
        return bigquery.Client(project=BQ_PROJECT, credentials=creds)
    except Exception as _adc_err:
        log(f"  ADC falló ({_adc_err!r}), usando service account key como fallback")
        return bigquery.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


def get_firestore_client():
    import google.auth
    from google.cloud import firestore
    try:
        creds, _ = google.auth.default()
        return firestore.Client(project=BQ_PROJECT, credentials=creds)
    except Exception as _adc_err:
        log(f"  ADC falló ({_adc_err!r}), usando service account key como fallback")
        return firestore.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


# ── get_rating — portado de Proyecto_Locales_Propios/data/places.py ────────
# (self-contained, no importar cross-proyecto)
def get_rating(place_id):
    """
    Llama a Google Places Details API para un place_id dado.
    Devuelve {"rating", "total_reviews", "reviews"} o None si status != OK.
    Cada reseña incluye "date_str" (dd/mm/YYYY) derivado del timestamp "time".
    """
    import httpx
    api_key = os.environ.get("PLACES_API_KEY")
    resp = httpx.get(PLACES_URL, params={
        "place_id": place_id,
        "fields": "rating,user_ratings_total,reviews",
        "reviews_sort": "newest",
        "language": "es",
        "key": api_key,
    }, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK":
        return None
    result = data.get("result", {})
    reviews = result.get("reviews", [])
    for r in reviews:
        if r.get("time"):
            r["date_str"] = datetime.fromtimestamp(r["time"]).strftime("%d/%m/%Y")
    return {
        "rating": result.get("rating"),
        "total_reviews": result.get("user_ratings_total"),
        "reviews": reviews,
    }


# ── Locales a procesar ──────────────────────────────────────────────────────
def get_test_locales():
    """2 entradas hardcodeadas de prueba (--test-mode), para probar el pipeline
    sin depender de mappings verificados en Firestore."""
    return [
        {
            "marca": "Temple",
            "local": "BARRIO CHINO",
            "place_id": os.environ.get("PLACES_ID_BARRIO_CHINO"),
        },
        {
            "marca": "Temple",
            "local": "MONROE",
            "place_id": os.environ.get("PLACES_ID_MONROE"),
        },
    ]


def get_verified_locales(db):
    """Lee permissions.list_places_mapping(db) y filtra status == 'verified'."""
    from permissions import list_places_mapping
    mapping = list_places_mapping(db)
    locales = []
    for doc_id, data in mapping.items():
        if (data or {}).get("status") != "verified":
            continue
        place_id = data.get("place_id")
        if not place_id:
            log(f"  ⚠ Mapping '{doc_id}' está verified pero sin place_id, se omite")
            continue
        locales.append({
            "marca": data.get("marca", ""),
            "local": data.get("local", ""),
            "place_id": place_id,
        })
    return locales


# ── BigQuery: idempotencia (DELETE + batch load) ────────────────────────────
def delete_existing_snapshots(client, hoy, locales):
    """Borra filas existentes de hoy para estos locales (rerun same-day no duplica)."""
    from google.cloud import bigquery
    if not locales:
        return
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hoy", "DATE", hoy),
            bigquery.ArrayQueryParameter("locales", "STRING", locales),
        ]
    )
    query = f"""
        DELETE FROM `{BQ_TABLE_ID}`
        WHERE fecha_snapshot = @hoy AND local IN UNNEST(@locales)
    """
    client.query(query, job_config=job_config).result()


def load_snapshots(client, rows):
    """Batch load (NO streaming) — write_disposition WRITE_APPEND."""
    from google.cloud import bigquery
    if not rows:
        return
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=[
            bigquery.SchemaField("fecha_snapshot", "DATE", mode="REQUIRED"),
            bigquery.SchemaField("marca", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("local", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("place_id", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("rating", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("total_reviews", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("fetched_at", "TIMESTAMP", mode="REQUIRED"),
        ],
    )
    job = client.load_table_from_json(rows, BQ_TABLE_ID, job_config=job_config)
    job.result()  # espera a que termine el load job


def get_rating_prev_snapshot(client, local, hoy):
    """Rating más reciente ANTERIOR a hoy para ese local, o None si no hay histórico."""
    from google.cloud import bigquery
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("local", "STRING", local),
            bigquery.ScalarQueryParameter("hoy", "DATE", hoy),
        ]
    )
    query = f"""
        SELECT rating FROM `{BQ_TABLE_ID}`
        WHERE local = @local AND fecha_snapshot < @hoy
        ORDER BY fecha_snapshot DESC
        LIMIT 1
    """
    result = list(client.query(query, job_config=job_config).result())
    if not result:
        return None
    return result[0]["rating"]


def get_rating_historial(client, local, dias=90):
    """Historial de rating de los últimos `dias` días para ese local, ordenado por fecha ascendente."""
    from google.cloud import bigquery
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("local", "STRING", local),
            bigquery.ScalarQueryParameter("dias", "INT64", dias),
        ]
    )
    query = f"""
        SELECT fecha_snapshot, rating FROM `{BQ_TABLE_ID}`
        WHERE local = @local AND fecha_snapshot >= DATE_SUB(CURRENT_DATE(), INTERVAL @dias DAY)
        ORDER BY fecha_snapshot ASC
    """
    result = client.query(query, job_config=job_config).result()
    return [
        {"fecha": row["fecha_snapshot"].isoformat(), "rating": row["rating"]}
        for row in result
    ]


# ── Detección de reseñas negativas nuevas (alerta) ──────────────────────────
def _normalize_local_key(local):
    return "".join(c if c.isalnum() else "_" for c in (local or "").strip().lower())


def _review_key(review):
    """Key estable por reseña: author_name|time si hay time, si no author_name|date_str|rating."""
    author = review.get("author_name", "")
    if review.get("time"):
        return f"{author}|{review['time']}"
    return f"{author}|{review.get('date_str', '')}|{review.get('rating', '')}"


def check_alert_and_update_seen(db, local, reviews):
    """
    Devuelve (is_alert, new_negative_reviews):
      - is_alert: True si hay al menos una reseña nueva con rating <= 2 no vista antes.
      - new_negative_reviews: lista de reviews (dicts originales) nuevas con rating <= 2,
        usada para crear docs de gestión en google_reviews_gestion (P2b).
    Actualiza (merge=True) el doc de seen_review_keys en Firestore.
    """
    doc_id = _normalize_local_key(local)
    doc_ref = db.collection(LAST_SEEN_COLLECTION).document(doc_id)
    snapshot = doc_ref.get()
    seen_keys = set(snapshot.to_dict().get("seen_review_keys", [])) if snapshot.exists else set()

    is_alert = False
    new_negative_reviews = []
    new_keys = set(seen_keys)
    for r in reviews:
        key = _review_key(r)
        rating = r.get("rating")
        if key not in seen_keys and rating is not None and rating <= 2:
            is_alert = True
            new_negative_reviews.append(r)
        new_keys.add(key)

    doc_ref.set({"seen_review_keys": sorted(new_keys)}, merge=True)
    return is_alert, new_negative_reviews


# ── Generación de HTML / upload GCS (clonado de generar_preview_producto.py) ─
def generate_preview(datos, output):
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()
    resenas_json = json.dumps(datos, ensure_ascii=False, default=str)
    html = html.replace("__RESENAS_JSON__", resenas_json)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"  ✓ Guardado: {output}")


def upload_to_gcs(local_path, bucket_name, blob_name, creds,
                   content_type="text/html; charset=utf-8", min_size=512):
    from google.cloud import storage
    file_size = os.path.getsize(local_path)
    if file_size < min_size:
        raise RuntimeError(
            f"Archivo demasiado pequeño ({file_size} bytes) — abortando upload para evitar publicar archivo corrupto"
        )
    log(f"  Subiendo a GCS: gs://{bucket_name}/{blob_name} ({file_size // 1024} KB) ...")
    client = storage.Client(credentials=creds)
    blob = client.bucket(bucket_name).blob(blob_name)
    # ORDEN CRÍTICO: upload primero, cache_control DESPUÉS — invertirlo rompe
    # el caché del browser (lección ya documentada en este proyecto).
    blob.upload_from_filename(local_path, content_type=content_type)
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    blob.reload()
    if blob.cache_control != "no-cache, no-store, must-revalidate":
        log(f"  ⚠ WARNING: cache_control no se aplicó correctamente (valor actual: {blob.cache_control!r})")
    log(f"  ✓ Publicado: https://storage.googleapis.com/{bucket_name}/{blob_name}")


def _get_storage_creds():
    if os.path.exists(SA_KEY):
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            SA_KEY,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    import google.auth as _gauth
    creds, _ = _gauth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds


# ── Pipeline principal ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Sync de ratings/reseñas de Google Places -> BQ + resenas.html")
    parser.add_argument("--test-mode", action="store_true",
                         help="Usa 2 locales hardcodeados (BARRIO_CHINO/MONROE) en vez de leer Firestore.")
    parser.add_argument("--output", default=OUTPUT_FILE)
    parser.add_argument("--gcs-bucket", default="temple-bar-dashboard-cache")
    parser.add_argument("--gcs-blob", default="resenas.html")
    parser.add_argument("--gcs-alertas-blob", default="resenas_alertas.json",
                         help="Blob del JSON chico de alertas (P9), leído por dashboard.html vía fetch liviano.")
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("PLACES_API_KEY")
    if not api_key:
        log("ERROR: la variable de entorno PLACES_API_KEY no está seteada en este entorno.")
        log("Este proyecto (Claude_Cowork) todavía no tiene esa key configurada — solo existe en Proyecto_Locales_Propios.")
        sys.exit(1)

    # ── Firestore (mapeos + last_seen) ──
    try:
        db = get_firestore_client()
    except Exception as exc:
        log(f"ERROR al conectar con Firestore: {exc!r}")
        sys.exit(1)

    # ── BigQuery ──
    try:
        bq_client = get_bq_client()
    except Exception as exc:
        log(f"ERROR al conectar con BigQuery: {exc!r}")
        sys.exit(1)

    # ── Locales a procesar ──
    if args.test_mode:
        log("Modo --test-mode: usando 2 locales hardcodeados (BARRIO_CHINO / MONROE)")
        locales = get_test_locales()
    else:
        log("Leyendo mappings verificados desde Firestore (google_places_mapping)...")
        try:
            locales = get_verified_locales(db)
        except Exception as exc:
            log(f"ERROR al leer mappings de Firestore: {exc!r}")
            sys.exit(1)
    log(f"Locales a procesar: {len(locales)}")

    hoy = date.today()
    ahora = datetime.now(timezone.utc)

    rows_bq = []          # filas para BQ (solo numéricas)
    por_marca = {}         # marca (mayúsculas) -> lista de dicts para el HTML
    procesados = 0
    fallidos = 0

    for loc in locales:
        marca = loc["marca"]
        local = loc["local"]
        place_id = loc["place_id"]

        if not place_id:
            log(f"  ⚠ {marca} / {local}: sin place_id, se omite")
            fallidos += 1
            continue

        try:
            data = get_rating(place_id)
        except Exception as exc:
            log(f"  ✗ {marca} / {local}: error consultando Places API: {exc!r}")
            fallidos += 1
            continue

        if data is None:
            log(f"  ✗ {marca} / {local}: Places API status != OK (place_id={place_id})")
            fallidos += 1
            continue

        rating = data.get("rating")
        total_reviews = data.get("total_reviews")
        reviews = data.get("reviews", [])

        rows_bq.append({
            "fecha_snapshot": hoy.isoformat(),
            "marca": marca,
            "local": local,
            "place_id": place_id,
            "rating": rating,
            "total_reviews": total_reviews,
            "fetched_at": ahora.isoformat(),
        })

        marca_key = (marca or "").strip().upper()
        por_marca.setdefault(marca_key, []).append({
            "marca": marca_key,
            "local": local,
            "place_id": place_id,
            "rating": rating,
            "total_reviews": total_reviews,
            "reviews": reviews,
            "_raw_reviews": reviews,  # usado luego para alertas, se limpia antes de emitir JSON
        })

        procesados += 1
        log(f"  ✓ {marca} / {local}: rating={rating} total_reviews={total_reviews} reviews_fetched={len(reviews)}")

    log(f"Procesados OK: {procesados} | Fallidos: {fallidos}")

    # ── Guardar snapshot en BQ (idempotente: DELETE + batch load) ──
    if rows_bq:
        locales_hoy = [r["local"] for r in rows_bq]
        try:
            log("Borrando snapshots existentes de hoy para estos locales (idempotencia)...")
            delete_existing_snapshots(bq_client, hoy.isoformat(), locales_hoy)
            log("Insertando snapshot de hoy (batch load, WRITE_APPEND)...")
            load_snapshots(bq_client, rows_bq)
            log(f"  ✓ {len(rows_bq)} fila(s) guardadas en {BQ_TABLE_ID}")
        except Exception as exc:
            log(f"ERROR al guardar snapshot en BigQuery: {exc!r}")
            # No abortamos el pipeline completo por esto: igual generamos el HTML del día.
    else:
        log("  ⚠ Sin filas para guardar en BQ (todos los locales fallaron)")

    # ── rating_prev_snapshot + alertas por local ──
    for marca_key, entries in por_marca.items():
        for entry in entries:
            local = entry["local"]
            try:
                entry["rating_prev_snapshot"] = get_rating_prev_snapshot(bq_client, local, hoy.isoformat())
            except Exception as exc:
                log(f"  ⚠ {marca_key} / {local}: error consultando rating_prev_snapshot: {exc!r}")
                entry["rating_prev_snapshot"] = None

            try:
                entry["historial"] = get_rating_historial(bq_client, local)
            except Exception as exc:
                log(f"  ⚠ {marca_key} / {local}: error consultando historial: {exc!r}")
                entry["historial"] = []

            try:
                entry["is_alert"], new_negative_reviews = check_alert_and_update_seen(db, local, entry["_raw_reviews"])
            except Exception as exc:
                log(f"  ⚠ {marca_key} / {local}: error chequeando alertas: {exc!r}")
                entry["is_alert"] = False
                new_negative_reviews = []

            for r in new_negative_reviews:
                try:
                    gestion_doc_id = _review_key(r)
                    permissions.create_gestion_if_not_exists(
                        db,
                        gestion_doc_id,
                        marca_key,
                        local,
                        r.get("rating"),
                        r.get("text", ""),
                        r.get("author_name", ""),
                        r.get("date_str", ""),
                    )
                except Exception as exc:
                    log(f"  ⚠ {marca_key} / {local}: error creando gestión de reseña: {exc!r}")

            del entry["_raw_reviews"]

    # ── Armar dict final y generar HTML ──
    historial = {}
    for marca_key, entries in por_marca.items():
        for entry in entries:
            historial[f"{marca_key}__{entry['local']}"] = entry.pop("historial", [])

    datos = {
        "fecha_snapshot": hoy.isoformat(),
        "historial": historial,
        "por_marca": {
            "TEMPLE": por_marca.get("TEMPLE", []),
            "PATAGONIA": por_marca.get("PATAGONIA", []),
            "FERIADO": por_marca.get("FERIADO", []),
        },
    }

    generate_preview(datos, args.output)

    # ── P9: JSON chico de alertas — fetch liviano desde dashboard.html sin ──
    # depender del iframe lazy-load de resenas.html.
    alertas_locales = []
    for marca_key, entries in datos["por_marca"].items():
        for entry in entries:
            if entry.get("is_alert"):
                alertas_locales.append(f"{marca_key} - {entry['local']}")
    alertas = {
        "count": len(alertas_locales),
        "locales": alertas_locales,
        "fecha_snapshot": hoy.isoformat(),
    }
    alertas_output = os.path.join(os.path.dirname(args.output), "resenas_alertas.json") \
        if os.path.dirname(args.output) else "resenas_alertas.json"
    with open(alertas_output, "w", encoding="utf-8") as f:
        json.dump(alertas, f, ensure_ascii=False)
    log(f"  ✓ Guardado: {alertas_output} (count={alertas['count']})")

    if not args.no_upload and args.gcs_bucket:
        try:
            creds = _get_storage_creds()
            upload_to_gcs(args.output, args.gcs_bucket, args.gcs_blob, creds)
            upload_to_gcs(
                alertas_output, args.gcs_bucket, args.gcs_alertas_blob, creds,
                content_type="application/json; charset=utf-8", min_size=2,
            )
        except Exception as exc:
            log(f"ERROR al subir a GCS: {exc!r}")
            sys.exit(1)

    try:
        cleanup_result = permissions.cleanup_gestion_retention(db)
        log(f"  ✓ Limpieza de gestión de reseñas (retención): {cleanup_result}")
    except Exception as exc:
        log(f"  ⚠ Error en cleanup_gestion_retention: {exc!r}")

    log(f"✓ Listo: {args.output}")


if __name__ == "__main__":
    main()
