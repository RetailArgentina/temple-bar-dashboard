"""
pipeline.py — BigQuery data pipeline for Temple Bar Dashboard.

Adapted from actualizar_dashboard.py:
  - fetch_data() signature and SQL are preserved verbatim
  - Key renames applied: 'cerveza' → 'cerv', 'feriado' → 'ferid'
    (to match the /api/data response contract)
  - CLI-specific code removed (parse_args, generate_html_from_file, main)
  - bq_client is injected (not created inside the function) for testability
  - print() statements replaced with logging

The 5 BigQuery tables:
  Ventas_Maestra  → ventas  → compact keys: d,e,c,t,o,v,tk
  Mix_Maestro     → mix     → compact keys: d,m,e,q,$
  Cerveza_Maestro → cerv    → compact keys: d,s,cat,e,q,$
  Gin_Maestro     → gin     → compact keys: d,p,e,q,$,l
  Feriado_Maestro → ferid   → compact keys: d,p,e,q,$
"""
import logging

import config

logger = logging.getLogger(__name__)

_TABLES = {
    "ventas": "Ventas_Maestra",
    "mix": "Mix_Maestro",
    "cerv": "Cerveza_Maestro",   # note: key is 'cerv', table is 'Cerveza_Maestro'
    "gin": "Gin_Maestro",
    "ferid": "Feriado_Maestro",  # note: key is 'ferid', table is 'Feriado_Maestro'
}


def fetch_data(client, desde: str, hasta: str) -> dict:
    """
    Query all 5 BigQuery tables and return compact JSON-ready data.

    Args:
        client: google.cloud.bigquery.Client (injected for testability)
        desde:  start date in YYYY-MM-DD format (inclusive)
        hasta:  end date in YYYY-MM-DD format (inclusive)

    Returns:
        dict with keys: ventas, mix, cerv, gin, ferid
        (no 'canal' or 'turno' — derived client-side from ventas)
    """
    dataset = config.BQ_DATASET
    project = config.GCP_PROJECT_ID

    logger.info("Fetching BigQuery data: %s → %s", desde, hasta)

    queries = {
        "ventas": f"""
            SELECT fecha, Establecimiento, Canal, Turno,
                   CAST(ordenes AS INT64) AS ordenes,
                   CAST(ventas AS INT64) AS ventas,
                   CAST(ticket AS INT64) AS ticket
            FROM `{project}.{dataset}.{_TABLES['ventas']}`
            WHERE fecha BETWEEN '{desde}' AND '{hasta}'
            ORDER BY fecha DESC
        """,
        "mix": f"""
            SELECT fecha, Mix, Establecimiento,
                   CAST(cantidad AS INT64) AS cantidad,
                   CAST(dinero AS INT64) AS dinero
            FROM `{project}.{dataset}.{_TABLES['mix']}`
            WHERE fecha BETWEEN '{desde}' AND '{hasta}'
            ORDER BY fecha DESC
        """,
        "cerv": f"""
            SELECT fecha, Estilos, Categoria, Establecimiento,
                   CAST(cantidad AS INT64) AS cantidad,
                   CAST(dinero AS INT64) AS dinero
            FROM `{project}.{dataset}.{_TABLES['cerv']}`
            WHERE fecha BETWEEN '{desde}' AND '{hasta}'
            ORDER BY fecha DESC
        """,
        "gin": f"""
            SELECT fecha, Producto, Establecimiento,
                   CAST(cantidad AS INT64) AS cantidad,
                   CAST(dinero AS INT64) AS dinero,
                   CAST(litros AS FLOAT64) AS litros
            FROM `{project}.{dataset}.{_TABLES['gin']}`
            WHERE fecha BETWEEN '{desde}' AND '{hasta}'
            ORDER BY fecha DESC
        """,
        "ferid": f"""
            SELECT fecha, Producto, Establecimiento,
                   CAST(cantidad AS INT64) AS cantidad,
                   CAST(dinero AS INT64) AS dinero
            FROM `{project}.{dataset}.{_TABLES['ferid']}`
            WHERE fecha BETWEEN '{desde}' AND '{hasta}'
            ORDER BY fecha DESC
        """,
    }

    data = {}

    for key, query in queries.items():
        logger.info("  Querying %s...", key)
        job = client.query(query)
        rows = list(job.result())

        if key == "ventas":
            processed = [
                {
                    "d": row.fecha.strftime("%Y-%m-%d"),
                    "e": row.Establecimiento,
                    "c": row.Canal,
                    "t": row.Turno,
                    "o": row.ordenes,
                    "v": row.ventas,
                    "tk": row.ticket,
                }
                for row in rows
            ]
        elif key == "mix":
            processed = [
                {
                    "d": row.fecha.strftime("%Y-%m-%d"),
                    "m": row.Mix,
                    "e": row.Establecimiento,
                    "q": row.cantidad,
                    "$": row.dinero,
                }
                for row in rows
            ]
        elif key == "cerv":
            processed = [
                {
                    "d": row.fecha.strftime("%Y-%m-%d"),
                    "s": row.Estilos,
                    "cat": row.Categoria,
                    "e": row.Establecimiento,
                    "q": row.cantidad,
                    "$": row.dinero,
                }
                for row in rows
            ]
        elif key == "gin":
            processed = [
                {
                    "d": row.fecha.strftime("%Y-%m-%d"),
                    "p": row.Producto,
                    "e": row.Establecimiento,
                    "q": row.cantidad,
                    "$": row.dinero,
                    "l": row.litros,
                }
                for row in rows
            ]
        elif key == "ferid":
            processed = [
                {
                    "d": row.fecha.strftime("%Y-%m-%d"),
                    "p": row.Producto,
                    "e": row.Establecimiento,
                    "q": row.cantidad,
                    "$": row.dinero,
                }
                for row in rows
            ]
        else:
            processed = []

        data[key] = processed
        logger.info("  %s: %d rows", key, len(processed))

    return data
