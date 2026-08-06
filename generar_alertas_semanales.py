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

from generar_informe_semanal import (
    get_client, fetch_semana, fetch_mes_actual, fetch_objetivos,
    agg_por_marca, agg_por_local,
)
from generar_preview_producto import upload_to_gcs

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
    # NOTA: Gap de datos conocido en patagonia-refugios.curated_database.curated_mix:
    # La columna cerveza_total es NULL para líneas de combos comida+cerveza (gap en la
    # ingesta de datos). El COALESCE(cerveza_total,0) aquí trata esos NULLs como 0 litros
    # de cerveza, lo que puede generar falsos positivos en evaluar_regla_mix cuando hay
    # muchos combos en una semana (pct_cerveza se ve artificialmente bajo porque se divide
    # un volumen menor entre un denomin. parcial). En locales/semanas con >30% de volumen
    # en combos, la regla de mix puede disparar sin que haya un verdadero cambio en estrategia.
    # Ver lesson_curated-mix-mismo-hueco-combos.md en memoria de proyecto.
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
    y/o de su relación histórica habitual con sus pares (misma marca) en la
    semana evaluada.

    La señal de pares compara el desvío ACTUAL de este local respecto al
    promedio de sus pares contra el desvío HISTÓRICO TÍPICO de ese mismo
    local respecto a sus pares -- no contra cero. Comparar contra el promedio
    plano de la marca (validado a mano el 06/08/2026 contra datos reales)
    marca casi todos los locales todas las semanas, porque hay variación
    estructural real entre locales (algunos venden más tragos que otros por
    naturaleza del local/clientela, sin que eso sea una novedad); lo que
    importa es si ESE desvío particular cambia, no si existe."""
    por_local = {}
    for row in mix_rows:
        por_local.setdefault(row["local"], []).append(row)

    # {semana: {local: pct_cerveza}} -- para calcular el promedio de pares de
    # cualquier semana (histórica o actual), excluyendo el local evaluado.
    pct_por_semana = {}
    for local, filas in por_local.items():
        for f in filas:
            if f["pct_cerveza"] is not None:
                pct_por_semana.setdefault(f["semana"], {})[local] = f["pct_cerveza"]

    def peer_avg(semana, excluir_local):
        valores = [pct for loc, pct in pct_por_semana.get(semana, {}).items() if loc != excluir_local]
        if len(valores) >= config["mix_min_locales_peer"]:
            return sum(valores) / len(valores)
        return None

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

        desvio_peer = None
        excess_hist_avg = None
        excess_actual = None
        peer_avg_actual = peer_avg(semana_evaluada, local)
        if peer_avg_actual is not None:
            excess_actual = actual["pct_cerveza"] - peer_avg_actual
            excesos_hist = []
            for f in filas:
                if f["semana"] == semana_evaluada or f["pct_cerveza"] is None:
                    continue
                pa = peer_avg(f["semana"], local)
                if pa is not None:
                    excesos_hist.append(f["pct_cerveza"] - pa)
            if len(excesos_hist) >= config["mix_min_semanas_historia"]:
                excess_hist_avg = sum(excesos_hist) / len(excesos_hist)
                desvio_peer = (excess_actual - excess_hist_avg) * 100

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
        if excess_hist_avg is not None:
            peer_txt = (f"vs. pares esta semana {excess_actual * 100:+.0f}pp "
                        f"(habitual para este local: {excess_hist_avg * 100:+.0f}pp)")
        else:
            peer_txt = "sin historia de pares suficiente"
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


def ticket_prom(fac_M, ordenes):
    if ordenes == 0:
        return 0
    return round(fac_M * 1e6 / ordenes)


def evaluar_regla_performance(marca_esta, marca_ant, locales_top, locales_ant_dict,
                               objetivos, mes_key, pace, dias_rest, config, mes_real):
    """Pace por marca vs objetivo prorrateado + caída de local vs semana anterior."""
    hallazgos = []

    for m, obj_por_mes in objetivos.items():
        obj_M = obj_por_mes.get(mes_key, 0)
        real_M = mes_real.get(m, {}).get('fac_M', 0)
        if obj_M <= 0:
            continue
        obj_pace = obj_M * pace
        cumpl_pace = real_M / obj_pace * 100 if obj_pace > 0 else 100
        if cumpl_pace < 80 and dias_rest > 3:
            severidad = "Alta"
        elif cumpl_pace < 92 and dias_rest > 3:
            severidad = "Media"
        else:
            continue
        falta = obj_M - real_M
        por_dia = falta / dias_rest if dias_rest > 0 else 0
        hallazgos.append({
            "marca": m, "local": None, "categoria": "Performance", "severidad": severidad,
            "mensaje": f"{m}: ritmo de facturación {cumpl_pace:.0f}% del objetivo esperado",
            "detalle": f"Faltan ${falta:.1f}M para el objetivo. Necesita ${por_dia:.1f}M/día "
                       f"en los próximos {dias_rest} días.",
        })

    # Umbral calibrado a mano el 06/08/2026 contra la semana 27/07-02/08 real:
    # con -20/-30 (umbral original heredado de generar_informe_semanal.py, que
    # ahí solo se mostraba top-3) esta regla sin cap generaba 14 hallazgos en
    # una sola semana — la mayoría reflejaba volatilidad normal semana a semana
    # a nivel local (la facturación total de la compañía solo cayó -7% esa
    # semana, pero 31 de 50 locales bajaron y 19 subieron, con swings de hasta
    # ±96%). Subido a -35/-45 para que solo alerte ante caídas bien por encima
    # de esa volatilidad habitual.
    caidas = []
    for loc in locales_top:
        key = (loc['Marca'], loc['local'])
        fac0 = locales_ant_dict.get(key, 0)
        if fac0 > 0 and loc['fac_M'] > 0:
            dp = (loc['fac_M'] - fac0) / fac0 * 100
            if dp <= -35:
                caidas.append((loc, dp, fac0))
    for loc, dp, fac0 in caidas:
        severidad = "Alta" if dp < -45 else "Media"
        hallazgos.append({
            "marca": loc['Marca'], "local": loc['local'], "categoria": "Performance",
            "severidad": severidad,
            "mensaje": f"{loc['local']} ({loc['Marca']}): caída del {abs(dp):.0f}% vs semana anterior",
            "detalle": f"Pasó de ${fac0:.1f}M a ${loc['fac_M']:.1f}M.",
        })

    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos.sort(key=lambda h: orden.get(h["severidad"], 9))
    return hallazgos


def evaluar_regla_ticket_ordenes(marca_esta, marca_ant, config):
    """Caída de ticket promedio y de cantidad de órdenes por marca."""
    hallazgos = []
    for m, datos_esta in marca_esta.items():
        datos_ant = marca_ant.get(m)
        if not datos_ant:
            continue

        tk_e = ticket_prom(datos_esta.get('fac_M', 0), datos_esta.get('ordenes', 0))
        tk_a = ticket_prom(datos_ant.get('fac_M', 0), datos_ant.get('ordenes', 0))
        if tk_a > 0 and tk_e > 0:
            dp_tk = (tk_e - tk_a) / tk_a * 100
            if dp_tk <= config["ticket_caida_pct"]:
                hallazgos.append({
                    "marca": m, "local": None, "categoria": "Ticket/Órdenes", "severidad": "Media",
                    "mensaje": f"{m}: ticket promedio cayó {abs(dp_tk):.0f}% (${tk_e:,.0f} vs ${tk_a:,.0f} sem. ant.)",
                    "detalle": "Puede indicar mix de productos más económico o promociones activas.",
                })

        ord_e = datos_esta.get('ordenes', 0)
        ord_a = datos_ant.get('ordenes', 0)
        if ord_a > 0 and ord_e > 0:
            dp_o = (ord_e - ord_a) / ord_a * 100
            if dp_o < -10:
                severidad = "Alta" if dp_o < -20 else "Media"
                hallazgos.append({
                    "marca": m, "local": None, "categoria": "Ticket/Órdenes", "severidad": severidad,
                    "mensaje": f"{m}: caída del {abs(dp_o):.0f}% en cantidad de órdenes vs semana anterior",
                    "detalle": f"Pasó de {ord_a:,} a {ord_e:,} órdenes.",
                })

    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos.sort(key=lambda h: orden.get(h["severidad"], 9))
    return hallazgos


_SEVERIDAD_COLOR = {"Alta": "#dc2626", "Media": "#d97706", "Baja": "#475569"}


def render_alertas_html(hallazgos: list, semana_inicio, semana_fin, generado_en) -> str:
    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    hallazgos_ordenados = sorted(hallazgos, key=lambda h: orden.get(h["severidad"], 9))

    if hallazgos_ordenados:
        bloques = []
        for h in hallazgos_ordenados:
            color = _SEVERIDAD_COLOR.get(h["severidad"], "#475569")
            bloques.append(f"""
            <div class="hallazgo" style="border-left: 4px solid {color};">
              <span class="badge" style="background:{color};">{h['severidad']}</span>
              <span class="categoria">{h['categoria']}</span>
              <p class="mensaje">{h['mensaje']}</p>
              <p class="detalle">{h['detalle']}</p>
            </div>""")
        cuerpo = "\n".join(bloques)
    else:
        cuerpo = '<div class="sin-hallazgos">✅ Sin hallazgos relevantes esta semana.</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Alertas Semanales de Negocio</title>
<style>
  body {{ background:#0f2544; color:#f1f5f9; font-family: Arial, sans-serif; padding: 24px; }}
  h1 {{ color:#f1f5f9; }}
  .subtitulo {{ color:#cbd5e1; margin-bottom: 24px; }}
  .hallazgo {{ background:#16324f; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; }}
  .badge {{ display:inline-block; padding: 2px 8px; border-radius: 4px; font-weight:bold; font-size: 12px; }}
  .categoria {{ margin-left: 8px; color:#94a3b8; font-size: 13px; }}
  .mensaje {{ font-weight:bold; margin: 6px 0 2px 0; }}
  .detalle {{ color:#cbd5e1; margin: 0; font-size: 14px; }}
  .sin-hallazgos {{ background:#16324f; border-radius: 6px; padding: 16px; }}
  footer {{ color:#475569; margin-top: 32px; font-size: 12px; }}
</style>
</head>
<body>
  <h1>🚨 Alertas Semanales de Negocio</h1>
  <p class="subtitulo">
    Semana {semana_inicio.strftime('%d/%m/%Y')} – {semana_fin.strftime('%d/%m/%Y')} ·
    Generado {generado_en.strftime('%d/%m/%Y %H:%M')}
  </p>
  {cuerpo}
  <footer>Temple · Patagonia · Feriado — reporte automático semanal</footer>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--semana', default=None,
                         help='Lunes de inicio de la semana a evaluar (YYYY-MM-DD, default: semana pasada)')
    parser.add_argument('--output', default='alertas_semanales.html')
    parser.add_argument('--gcs-bucket', default='temple-bar-dashboard-cache')
    parser.add_argument('--gcs-blob', default='alertas_semanales.html')
    parser.add_argument('--no-upload', action='store_true')
    args = parser.parse_args()

    if args.semana:
        semana_inicio = datetime.strptime(args.semana, '%Y-%m-%d').date()
    else:
        hoy = date.today()
        lunes_esta_semana = hoy - timedelta(days=hoy.weekday())
        semana_inicio = lunes_esta_semana - timedelta(days=7)

    rangos = compute_date_ranges(semana_inicio)
    client = get_client()

    rows_esta = fetch_semana(client, rangos["semana_inicio"].isoformat(), rangos["semana_fin"].isoformat())
    rows_ant = fetch_semana(client, rangos["sem_ant_ini"].isoformat(), rangos["sem_ant_fin"].isoformat())
    marca_esta = agg_por_marca(rows_esta)
    marca_ant = agg_por_marca(rows_ant)
    locales_top = agg_por_local(rows_esta)
    locales_ant_dict = {(l['Marca'], l['local']): l['fac_M'] for l in agg_por_local(rows_ant)}

    mes_real = fetch_mes_actual(client, rangos["mes_inicio"].isoformat(), rangos["semana_fin"].isoformat())
    objetivos = fetch_objetivos()

    hallazgos = []
    hallazgos += evaluar_regla_performance(
        marca_esta, marca_ant, locales_top, locales_ant_dict, objetivos,
        rangos["mes_key"], rangos["pace"], rangos["dias_rest"], CONFIG, mes_real,
    )
    hallazgos += evaluar_regla_ticket_ordenes(marca_esta, marca_ant, CONFIG)

    desde_mix = (rangos["semana_inicio"] - timedelta(weeks=8)).isoformat()
    hasta_mix = rangos["semana_fin"].isoformat()
    for marca in MARCAS_ACTIVAS:
        raw_mix = fetch_mix_semanal_por_local(client, marca, desde_mix, hasta_mix)
        mix_rows = build_mix_rows(raw_mix)
        hallazgos += evaluar_regla_mix(mix_rows, marca, rangos["semana_inicio"], CONFIG)

    html = render_alertas_html(hallazgos, rangos["semana_inicio"], rangos["semana_fin"], datetime.now())
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generado {args.output} con {len(hallazgos)} hallazgo(s)")

    if not args.no_upload:
        from google.oauth2 import service_account
        import os as _os
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        sa_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "temple-bar-439715-da51b292ce5d.json")
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)
        upload_to_gcs(args.output, args.gcs_bucket, args.gcs_blob, creds)


if __name__ == '__main__':
    main()
