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


def _fetch_mix_temple(client, desde, hasta):
    q = f"""
    SELECT
      establecimiento                          AS local,
      DATE_TRUNC(fecha, WEEK(MONDAY))           AS semana,
      ROUND(SUM(COALESCE(cerveza_total,0)), 2) AS lts_cerveza,
      ROUND(SUM(COALESCE(tragos_total, 0)), 2) AS lts_tragos
    FROM `temple-bar-439715.curated_database.vw_curated_compilado_ok`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local, semana
    ORDER BY local, semana
    """
    return list(client.query(q).result())


def _fetch_mix_patagonia(client, desde, hasta):
    q = f"""
    SELECT
      establecimiento                          AS local,
      DATE_TRUNC(fecha, WEEK(MONDAY))           AS semana,
      ROUND(SUM(COALESCE(cerveza_total,0)), 2) AS lts_cerveza,
      ROUND(SUM(COALESCE(tragos_total, 0)), 2) AS lts_tragos
    FROM `patagonia-refugios.curated_database.curated_mix`
    WHERE fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local, semana
    ORDER BY local, semana
    """
    return list(client.query(q).result())


def _fetch_mix_feriado(client, desde, hasta):
    # Feriado no tiene un campo "tragos_total" propio en Ventas_Toteat (a
    # diferencia de Temple/Patagonia). Se usa "todo lo que no es cerveza"
    # (gin, fernet, vermú, etc.) como el bucket comparable de "tragos",
    # mismo criterio de Categoria_Empresa que ya usa fetch_locales_feriado()
    # en generar_preview_producto.py.
    q = f"""
    SELECT
      Establecimiento                                          AS local,
      DATE_TRUNC(Fecha, WEEK(MONDAY))                          AS semana,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa))
                          IN ('cmq cerveza','temple cerveza')
                     THEN COALESCE(Litros,0) ELSE 0 END), 2)   AS lts_cerveza,
      ROUND(SUM(CASE WHEN LOWER(TRIM(Categoria_Empresa))
                          NOT IN ('cmq cerveza','temple cerveza')
                     THEN COALESCE(Litros,0) ELSE 0 END), 2)   AS lts_tragos
    FROM `temple-bar-439715.Feriado.vw_Ventas_Feriado`
    WHERE Fecha BETWEEN '{desde}' AND '{hasta}'
    GROUP BY local, semana
    ORDER BY local, semana
    """
    return list(client.query(q).result())


_MIX_FETCHERS = {
    "Temple": _fetch_mix_temple,
    "Patagonia": _fetch_mix_patagonia,
    "Feriado": _fetch_mix_feriado,
}


def fetch_mix_semanal_por_local(client, marca: str, desde: str, hasta: str) -> list:
    """Filas crudas de BQ con local/semana/lts_cerveza/lts_tragos para la marca dada."""
    fetcher = _MIX_FETCHERS.get(marca)
    if fetcher is None:
        raise ValueError(f"Marca desconocida para fetch de mix: {marca!r}")
    return fetcher(client, desde, hasta)


def evaluar_regla_mix(mix_rows: list, marca: str, semana_evaluada, config: dict) -> list:
    """Detecta locales cuyo mix cerveza/tragos se desvía de su propia historia
    y/o del promedio de sus pares (misma marca) en la semana evaluada."""
    por_local = {}
    for row in mix_rows:
        por_local.setdefault(row["local"], []).append(row)

    hallazgos = []
    for local, filas in por_local.items():
        actual = next((f for f in filas if f["semana"] == semana_evaluada), None)
        if actual is None or actual["pct_cerveza"] is None:
            continue
        volumen = actual["lts_cerveza"] + actual["lts_tragos"]
        if volumen < config["mix_min_lts_semana"]:
            continue

        historia = [f["pct_cerveza"] for f in filas
                    if f["semana"] != semana_evaluada and f["pct_cerveza"] is not None]
        desvio_self = None
        self_avg = None
        if len(historia) >= config["mix_min_semanas_historia"]:
            self_avg = sum(historia) / len(historia)
            desvio_self = (actual["pct_cerveza"] - self_avg) * 100

        peers = [f["pct_cerveza"] for otro_local, filas_otro in por_local.items()
                 if otro_local != local
                 for f in filas_otro
                 if f["semana"] == semana_evaluada and f["pct_cerveza"] is not None]
        desvio_peer = None
        peer_avg = None
        if len(peers) >= config["mix_min_locales_peer"]:
            peer_avg = sum(peers) / len(peers)
            desvio_peer = (actual["pct_cerveza"] - peer_avg) * 100

        self_flag = desvio_self is not None and abs(desvio_self) >= config["mix_desvio_self_pp"]
        peer_flag = desvio_peer is not None and abs(desvio_peer) >= config["mix_desvio_peer_pp"]

        if self_flag and peer_flag:
            severidad = "Alta"
        elif self_flag or peer_flag:
            severidad = "Media"
        else:
            continue

        pct_txt = f"{actual['pct_cerveza'] * 100:.0f}%"
        self_txt = f"{self_avg * 100:.0f}% (su propia historia)" if self_avg is not None else "sin historia suficiente"
        peer_txt = f"{peer_avg * 100:.0f}% (locales pares)" if peer_avg is not None else "sin pares comparables"
        hallazgos.append({
            "marca": marca,
            "local": local,
            "categoria": "Mix producto",
            "severidad": severidad,
            "mensaje": f"{local} ({marca}): cerveza es el {pct_txt} del volumen cerveza+tragos esta semana",
            "detalle": f"Esperado: {self_txt}; {peer_txt}.",
        })

    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos.sort(key=lambda h: orden.get(h["severidad"], 9))
    return hallazgos
