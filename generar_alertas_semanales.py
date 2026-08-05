#!/usr/bin/env python3
"""
generar_alertas_semanales.py
Genera un reporte HTML semanal de alertas de negocio (mix de producto,
performance/ritmo, ticket/órdenes) por local y por marca, para la reunión
gerencial de los lunes. Publica el resultado en GCS.

Uso: python -X utf8 generar_alertas_semanales.py [--semana YYYY-MM-DD]
     [--output alertas_semanales.html] [--gcs-bucket BUCKET] [--gcs-blob BLOB]
     [--no-upload]
     --semana: lunes de inicio de la semana a evaluar (default: semana pasada)
"""

import sys
import argparse
from datetime import date, timedelta, datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

CONFIG = {
    "ticket_caida_pct":         -8,
    "mix_desvio_self_pp":       15,
    "mix_desvio_peer_pp":       10,
    "mix_min_lts_semana":       50,
    "mix_min_semanas_historia": 4,
    "mix_min_locales_peer":     3,
}

MARCAS_ACTIVAS = ["Temple", "Patagonia", "Feriado"]


def compute_date_ranges(semana_inicio: date, hoy: date = None) -> dict:
    """Calcula todos los rangos de fecha y el pace mensual para una semana dada."""
    if hoy is None:
        hoy = date.today()
    semana_fin = semana_inicio + timedelta(days=6)
    sem_ant_ini = semana_inicio - timedelta(days=7)
    sem_ant_fin = semana_inicio - timedelta(days=1)
    mes_inicio = semana_inicio.replace(day=1)
    mes_key = semana_inicio.strftime('%Y-%m')

    siguiente_mes = mes_inicio.replace(month=mes_inicio.month % 12 + 1, day=1) if mes_inicio.month != 12 \
        else mes_inicio.replace(year=mes_inicio.year + 1, month=1, day=1)
    dias_mes_total = (siguiente_mes - timedelta(days=1)).day

    hasta_mes = min(hoy, semana_fin)
    dias_mes_trans = (hasta_mes - mes_inicio).days + 1
    pace = dias_mes_trans / dias_mes_total
    dias_rest = dias_mes_total - dias_mes_trans

    return {
        "semana_inicio": semana_inicio,
        "semana_fin": semana_fin,
        "sem_ant_ini": sem_ant_ini,
        "sem_ant_fin": sem_ant_fin,
        "mes_inicio": mes_inicio,
        "mes_key": mes_key,
        "dias_mes_total": dias_mes_total,
        "dias_mes_trans": dias_mes_trans,
        "pace": pace,
        "dias_rest": dias_rest,
    }


def build_mix_rows(raw_rows) -> list:
    """Normaliza filas de BQ (con atributos local/semana/lts_cerveza/lts_tragos)
    a dicts con pct_cerveza calculado. Descarta filas sin local."""
    out = []
    for r in raw_rows:
        local = str(getattr(r, 'local', '') or '').strip()
        if not local:
            continue
        lts_cerveza = float(getattr(r, 'lts_cerveza', 0) or 0)
        lts_tragos = float(getattr(r, 'lts_tragos', 0) or 0)
        denom = lts_cerveza + lts_tragos
        pct_cerveza = (lts_cerveza / denom) if denom > 0 else None
        out.append({
            "local": local,
            "semana": getattr(r, 'semana'),
            "lts_cerveza": lts_cerveza,
            "lts_tragos": lts_tragos,
            "pct_cerveza": pct_cerveza,
        })
    return out
