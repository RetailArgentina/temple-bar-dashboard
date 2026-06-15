"""
whatsapp_tools.py
Implementación de las 3 tools de Claude API para el agente retail.
"""
import json
import sys
import os
from datetime import date, timedelta
from google.cloud import bigquery
from actualizar_retail import fetch_objetivos_data

# ── Constantes ────────────────────────────────────────────────────────────────

PROJECT_ID    = "temple-bar-439715"
RETAIL_TABLE  = f"`{PROJECT_ID}.Corporativo.vw_Ventas_Corporativo_Base`"
PRODUCT_TABLE = f"`{PROJECT_ID}.curated_database.vw_curated_compilado_ok`"

# ── query_retail ──────────────────────────────────────────────────────────────

def query_retail(bq_client, fecha_desde: str, fecha_hasta: str, agrupar_por: str) -> list:
    """
    Consulta ventas retail desde BigQuery.
    agrupar_por: "marca" | "local" | "canal" | "dia"
    Retorna lista de dicts con grupo, facturacion, ordenes, ticket.
    """
    group_map = {
        "marca": "Marca",
        "local": "Local",
        "canal": "Canal",
        "dia":   "Fecha",
    }
    if agrupar_por not in group_map:
        raise ValueError(f"agrupar_por debe ser uno de {list(group_map.keys())}, recibido: {agrupar_por!r}")
    group_col = group_map[agrupar_por]

    query = f"""
    SELECT
      {group_col},
      SUM(Facturacion)                                        AS Facturacion,
      COUNT(DISTINCT Orden)                                   AS Ordenes,
      ROUND(SUM(Facturacion) / NULLIF(COUNT(DISTINCT Orden), 0), 0) AS Ticket_Promedio
    FROM {RETAIL_TABLE}
    WHERE Fecha BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
    GROUP BY {group_col}
    ORDER BY Facturacion DESC
    """

    rows = list(bq_client.query(query).result())
    return [
        {
            "grupo":       str(r[group_col]),
            "facturacion": r.Facturacion,
            "ordenes":     r.Ordenes,
            "ticket":      r.Ticket_Promedio,
        }
        for r in rows
    ]

# ── get_objectives ─────────────────────────────────────────────────────────────

def get_objectives_for_tool(marca: str, mes: str) -> dict:
    """
    Retorna objetivos mensuales para una marca + pace calculado al día de hoy.
    mes: formato "YYYY-MM"
    Reutiliza fetch_objetivos_data de actualizar_retail.py (no duplicar lógica).
    """
    obj = fetch_objetivos_data()
    mes_data = obj.get(marca, {}).get(mes, {"obj_fac": 0, "obj_ord": 0})

    # Calcular pace: días transcurridos del mes / días totales del mes
    today = date.today()
    if today.month == 12:
        days_in_month = 31
    else:
        days_in_month = (date(today.year, today.month + 1, 1) - timedelta(days=1)).day

    pace_pct = round(today.day / days_in_month * 100, 1)

    return {
        "obj_fac":            mes_data["obj_fac"],
        "obj_ord":            mes_data["obj_ord"],
        "pace_pct":           pace_pct,
        "dias_transcurridos": today.day,
        "dias_mes":           days_in_month,
    }

# ── query_product ──────────────────────────────────────────────────────────────

def query_product(bq_client, fecha_desde: str, fecha_hasta: str, marca: str) -> dict:
    """
    Consulta datos de producto (litros, mix, top productos) desde la vista curada.
    marca: "TEMPLE" | "PATAGONIA" | "FERIADO" | "TODAS"
    """
    if marca.upper() == "FERIADO":
        date_col = "Fecha_de_creacion"
        prod_col  = "Nombre"
        fam_col   = "Categor__as_de_Productos_Platos"
        lts_col   = "Litros_Totales"
    else:
        date_col = "fecha"
        prod_col  = "producto"
        fam_col   = "familia"
        lts_col   = "Litros_Totales"

    marca_filter = f"AND marca = '{marca.upper()}'" if marca.upper() != "TODAS" else ""

    query_mix = f"""
    SELECT
      INITCAP(COALESCE({fam_col}, 'Sin clasificar'))  AS familia,
      ROUND(SUM(COALESCE({lts_col}, 0)), 1)           AS lts_total,
      ROUND(SUM(COALESCE(facturacion, 0)), 0)         AS facturacion
    FROM {PRODUCT_TABLE}
    WHERE {date_col} BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
    {marca_filter}
    GROUP BY familia
    ORDER BY lts_total DESC
    LIMIT 10
    """

    query_top = f"""
    SELECT
      {prod_col}                                      AS producto,
      ROUND(SUM(COALESCE({lts_col}, 0)), 1)           AS lts_total,
      ROUND(SUM(COALESCE(facturacion, 0)), 0)         AS facturacion
    FROM {PRODUCT_TABLE}
    WHERE {date_col} BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
    {marca_filter}
    GROUP BY producto
    ORDER BY facturacion DESC
    LIMIT 10
    """

    mix_rows = list(bq_client.query(query_mix).result())
    top_rows = list(bq_client.query(query_top).result())

    return {
        "mix": [
            {"familia": r.familia, "litros": r.lts_total, "facturacion": r.facturacion}
            for r in mix_rows
        ],
        "top_productos": [
            {"producto": r.producto, "litros": r.lts_total, "facturacion": r.facturacion}
            for r in top_rows
        ],
    }


# ── TOOL_DEFINITIONS para Claude API ──────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "query_retail",
        "description": (
            "Consulta datos de ventas retail desde BigQuery. "
            "Retorna facturación, órdenes y ticket promedio agrupados por marca, local, canal o día."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "Fecha de inicio YYYY-MM-DD"},
                "fecha_hasta": {"type": "string", "description": "Fecha de fin YYYY-MM-DD"},
                "agrupar_por": {
                    "type": "string",
                    "enum": ["marca", "local", "canal", "dia"],
                    "description": "Dimensión de agrupación",
                },
            },
            "required": ["fecha_desde", "fecha_hasta", "agrupar_por"],
        },
    },
    {
        "name": "get_objectives",
        "description": (
            "Retorna los objetivos mensuales de una marca y el pace esperado "
            "(porcentaje del mes transcurrido). Usá siempre junto a query_retail "
            "para calcular cumplimiento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "marca": {
                    "type": "string",
                    "enum": ["Temple", "Patagonia", "Feriado"],
                    "description": "Nombre de la marca",
                },
                "mes": {"type": "string", "description": "Mes en formato YYYY-MM"},
            },
            "required": ["marca", "mes"],
        },
    },
    {
        "name": "query_product",
        "description": (
            "Consulta datos de producto: mix de venta por familia (litros y facturación) "
            "y top 10 productos. Usar cuando pregunten sobre productos, litros o categorías."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "Fecha de inicio YYYY-MM-DD"},
                "fecha_hasta": {"type": "string", "description": "Fecha de fin YYYY-MM-DD"},
                "marca": {
                    "type": "string",
                    "enum": ["TEMPLE", "PATAGONIA", "FERIADO", "TODAS"],
                    "description": "Marca a consultar. Usar TODAS para consolidado.",
                },
            },
            "required": ["fecha_desde", "fecha_hasta", "marca"],
        },
    },
]

# Solo tools básicas para viewers (sin query_product)
VIEWER_TOOL_DEFINITIONS = [t for t in TOOL_DEFINITIONS if t["name"] != "query_product"]
