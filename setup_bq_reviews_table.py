#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_bq_reviews_table.py
Crea (idempotente) la tabla de BigQuery temple-bar-439715.Corporativo.google_reviews_snapshots,
que guarda snapshots diarios de rating de Google por local.

Este script SOLO crea la estructura de la tabla (particionada por fecha_snapshot,
clusterizada por marca/local). No inserta datos ni modifica vistas existentes.
El cálculo de tendencia histórica lo hace otra tarea aparte.

Uso: python -X utf8 setup_bq_reviews_table.py
"""

import os
from datetime import datetime
from google.cloud import bigquery

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SA_KEY     = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
BQ_PROJECT = "temple-bar-439715"
BQ_DATASET = "Corporativo"
BQ_TABLE   = "google_reviews_snapshots"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_bq_client():
    import google.auth
    try:
        creds, _ = google.auth.default()
        return bigquery.Client(project=BQ_PROJECT, credentials=creds)
    except Exception as _adc_err:
        log(f"  ADC falló ({_adc_err!r}), usando service account key como fallback")
        return bigquery.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


def main():
    client = get_bq_client()
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

    schema = [
        bigquery.SchemaField("fecha_snapshot", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("marca", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("local", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("place_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("rating", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("total_reviews", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("fetched_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(field="fecha_snapshot")
    table.clustering_fields = ["marca", "local"]

    try:
        created_table = client.create_table(table, exists_ok=True)
        log(f"OK: tabla lista -> {created_table.full_table_id}")
        log(f"  Partición: {created_table.time_partitioning}")
        log(f"  Clustering: {created_table.clustering_fields}")
    except Exception as exc:
        log(f"ERROR: no se pudo crear la tabla {table_id}: {exc!r}")
        raise


if __name__ == "__main__":
    main()
