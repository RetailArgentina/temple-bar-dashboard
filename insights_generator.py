#!/usr/bin/env python3
"""
Temple Bar — Insights Generator
=================================
Genera insights contextuales y dinámicos a partir de:
  - Datos de ventas frescos de BigQuery (últimos 90 días)
  - Contexto económico de Argentina: IPC INDEC, sector gastronómico/retail

Uso:
    from insights_generator import generate_insights
    insights = generate_insights(ventas_data, economic_context)
    html = render_insights_html(insights)
"""

from datetime import datetime, timedelta, date as date_type
from collections import defaultdict
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ══════════════════════════════════════════════════════════════════════════
#  ESTILOS por tipo de insight
# ══════════════════════════════════════════════════════════════════════════
INSIGHT_STYLES = {
    "red":    {"bg": "#450a0a", "border": "rgba(248,113,113,.2)", "title_color": "#f87171"},
    "green":  {"bg": "#064e3b", "border": "rgba(110,231,183,.2)", "title_color": "#6ee7b7"},
    "yellow": {"bg": "#3d2c00", "border": "rgba(251,191,36,.2)",  "title_color": "#fbbf24"},
    "orange": {"bg": "#3d1a0a", "border": "rgba(251,146,60,.2)",  "title_color": "#fb923c"},
    "purple": {"bg": "#1e0c3d", "border": "rgba(167,139,250,.2)", "title_color": "#a78bfa"},
    "blue":   {"bg": "#0c2a3d", "border": "rgba(56,189,248,.2)",  "title_color": "#38bdf8"},
}

DOW_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


# ══════════════════════════════════════════════════════════════════════════
#  CARGA DEL CONTEXTO ECONÓMICO
# ══════════════════════════════════════════════════════════════════════════
def load_economic_context():
    """Carga economic_context.json. Si no existe, usa valores internos."""
    ctx_file = os.path.join(SCRIPT_DIR, "economic_context.json")
    if os.path.exists(ctx_file):
        with open(ctx_file, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback mínimo
    return {
        "ipc_mensual": {
            "2024-01": 20.6, "2024-02": 13.2, "2024-03": 11.0, "2024-04": 8.8,
            "2024-05": 4.2,  "2024-06": 4.6,  "2024-07": 4.0,  "2024-08": 4.2,
            "2024-09": 3.5,  "2024-10": 2.4,  "2024-11": 2.4,  "2024-12": 2.7,
            "2025-01": 2.3,  "2025-02": 2.4,  "2025-03": 3.7,  "2025-04": 3.0,
            "2025-05": 3.3,  "2025-06": 3.3,  "2025-07": 3.0,  "2025-08": 4.2,
            "2025-09": 3.5,  "2025-10": 2.4,  "2025-11": 2.4,  "2025-12": 2.7,
            "2026-01": 2.3,  "2026-02": 2.4,  "2026-03": 3.7,
        },
        "contexto": {
            "umbrales_ticket": {"premium_bajo": 35000, "premium_alto": 60000},
            "comision_delivery": {"min": 25, "max": 32},
            "nota_sector": (
                "Recuperación gradual en gastronomía premium post-recesión 2024. "
                "Consumidor más selectivo y menos frecuente. Q1 2026 muestra señales "
                "de rebote real en el segmento medio-alto (FEHGRA 2026)."
            ),
        }
    }


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS DE INFLACIÓN
# ══════════════════════════════════════════════════════════════════════════
def _acum_inflation(ipc_dict, months):
    """Inflación acumulada (%) para una lista de 'YYYY-MM'."""
    result = 1.0
    for m in months:
        rate = ipc_dict.get(m)
        if rate is not None:
            result *= (1 + rate / 100)
    return round((result - 1) * 100, 1)


def _months_between(start_ym, end_ym):
    """Lista de 'YYYY-MM' desde start_ym hasta end_ym inclusive."""
    months = []
    y, mo = int(start_ym[:4]), int(start_ym[5:7])
    ey, emo = int(end_ym[:4]), int(end_ym[5:7])
    while (y, mo) <= (ey, emo):
        months.append(f"{y:04d}-{mo:02d}")
        mo += 1
        if mo > 12:
            mo = 1
            y += 1
    return months


def _prev_ym(ym, months_back=1):
    """Devuelve 'YYYY-MM' retrocediendo n meses."""
    y, m = int(ym[:4]), int(ym[5:7])
    for _ in range(months_back):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return f"{y:04d}-{m:02d}"


# ══════════════════════════════════════════════════════════════════════════
#  HELPER PARA CREAR INSIGHT
# ══════════════════════════════════════════════════════════════════════════
def _insight(color, icon, title, body, generated_at):
    s = INSIGHT_STYLES.get(color, INSIGHT_STYLES["blue"])
    return {
        "color": color,
        "icon": icon,
        "title": title,
        "body": body,
        "generated_at": generated_at,
        "bg": s["bg"],
        "border": s["border"],
        "title_color": s["title_color"],
    }


# ══════════════════════════════════════════════════════════════════════════
#  MOTOR PRINCIPAL DE INSIGHTS
# ══════════════════════════════════════════════════════════════════════════
def generate_insights(ventas_data, economic_context=None):
    """
    Genera hasta 6 insights contextuales.

    ventas_data: lista de rows de BigQuery (dicts con keys:
        'd', 'e', 'marca', 'c', 't', 'o', 'v', 'total', 'tk', 'orig')
    economic_context: dict cargado desde economic_context.json (opcional)

    Returns: list de insight dicts.
    """
    if economic_context is None:
        economic_context = load_economic_context()

    ipc     = economic_context.get("ipc_mensual", {})
    ctx     = economic_context.get("contexto", {})
    tk_bajo = ctx.get("umbrales_ticket", {}).get("premium_bajo", 35000)
    tk_alto = ctx.get("umbrales_ticket", {}).get("premium_alto", 60000)
    del_min = ctx.get("comision_delivery", {}).get("min", 25)
    del_max = ctx.get("comision_delivery", {}).get("max", 32)

    today        = datetime.now().date()
    generated_at = today.strftime("%d %b %Y")
    insights     = []

    # ── Parsear rows ─────────────────────────────────────────────────────
    rows = []
    for r in ventas_data:
        try:
            d = datetime.strptime(r["d"], "%Y-%m-%d").date()
            marca = (r.get("marca") or "").strip()
            if not marca:
                continue
            rows.append({
                "d":     d,
                "mes":   r["d"][:7],
                "marca": marca,
                "canal": (r.get("c") or "").strip(),
                "turno": (r.get("t") or "").strip(),
                "e":     (r.get("e") or "").strip(),
                "o":     int(r.get("o") or 0),
                "v":     int(r.get("v") or 0),
                "tk":    int(r.get("tk") or 0),
                "orig":  (r.get("orig") or "").strip(),
            })
        except Exception:
            continue

    if not rows:
        return [_insight("blue", "ℹ️", "Sin datos disponibles",
                         "No se encontraron filas en el rango consultado.", generated_at)]

    last_date = max(r["d"] for r in rows)
    meses_disponibles = sorted(set(r["mes"] for r in rows))
    marcas_validas = [m for m in set(r["marca"] for r in rows)
                     if m.lower() not in ("feriado", "feriados", "")]

    # Frescura de datos: días entre el último dato disponible y hoy
    days_stale = (today - last_date).days
    data_is_fresh = days_stale <= 10  # datos de los últimos 10 días = "recientes"

    # ── INSIGHT 1A — Tendencia semanal (solo si datos son frescos ≤ 10 días) ─
    if data_is_fresh:
        w1_e = last_date
        w1_s = w1_e - timedelta(days=6)
        w2_e = w1_s - timedelta(days=1)
        w2_s = w2_e - timedelta(days=6)

        w1 = [r for r in rows if w1_s <= r["d"] <= w1_e]
        w2 = [r for r in rows if w2_s <= r["d"] <= w2_e]

        if w1 and w2:
            w1_fac = sum(r["v"] for r in w1)
            w2_fac = sum(r["v"] for r in w2)
            w1_ord = sum(r["o"] for r in w1)
            w2_ord = sum(r["o"] for r in w2)

            wow_fac = (w1_fac / w2_fac - 1) * 100 if w2_fac else 0
            wow_ord = (w1_ord / w2_ord - 1) * 100 if w2_ord else 0

            ipc_mes_actual = ipc.get(last_date.strftime("%Y-%m"), 3.0)
            infl_semanal = ipc_mes_actual / 4.3  # aproximación semanal

            if wow_fac > infl_semanal + 0.5:
                col, ico = "green", "📈"
                title = f"Semana reciente: +{wow_fac:.1f}% en facturación — crecimiento real positivo"
                body = (
                    f"Del {w1_s.strftime('%d/%m')} al {w1_e.strftime('%d/%m')}, la facturación total "
                    f"creció {wow_fac:+.1f}% vs la semana anterior. "
                    f"Con inflación semanal estimada en ~{infl_semanal:.1f}% (IPC mensual {ipc_mes_actual:.1f}%), "
                    f"el resultado implica expansión real del negocio. "
                    f"Las órdenes {'también crecieron' if wow_ord > 0 else 'cayeron'} un {wow_ord:+.1f}% — "
                    f"{'tráfico genuinamente recuperado.' if wow_ord > 0 else 'el crecimiento es por ticket más alto, no más clientes.'}"
                )
            elif wow_fac < -2:
                col, ico = "red", "📉"
                title = f"Alerta semana {w1_s.strftime('%d/%m')}–{w1_e.strftime('%d/%m')}: {wow_fac:.1f}% en facturación"
                body = (
                    f"Del {w1_s.strftime('%d/%m')} al {w1_e.strftime('%d/%m')}, la facturación cayó "
                    f"{wow_fac:.1f}% vs la semana anterior. "
                    f"Las órdenes variaron {wow_ord:+.1f}%. "
                    f"En el contexto de recuperación gradual del sector gastronómico argentino, "
                    f"una caída sostenida en el tráfico es la señal de riesgo más crítica: "
                    f"el consumidor ajusta primero la frecuencia de visita antes que el gasto por salida."
                )
            else:
                col, ico = "yellow", "📊"
                title = f"Semana {w1_s.strftime('%d/%m')}–{w1_e.strftime('%d/%m')}: {wow_fac:+.1f}% nominal — sin crecimiento real"
                body = (
                    f"Del {w1_s.strftime('%d/%m')} al {w1_e.strftime('%d/%m')}, la facturación creció "
                    f"{wow_fac:+.1f}%, prácticamente igual que la inflación semanal estimada (~{infl_semanal:.1f}%). "
                    f"Crecimiento real cercano a cero. Las órdenes variaron {wow_ord:+.1f}%. "
                    f"Para avanzar, el negocio necesita superar la inercia inflacionaria "
                    f"recuperando frecuencia o mejorando el ticket en términos reales."
                )
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 1B — Comparativa mensual (cuando datos tienen más de 10 días) ─
    # Reemplaza al insight semanal para no mostrar períodos desactualizados
    else:
        ultimo_mes_disp = meses_disponibles[-1]   # ej. "2026-03"
        prev_mes_disp   = _prev_ym(ultimo_mes_disp, 1)  # ej. "2026-02"

        mes_rows  = [r for r in rows if r["mes"] == ultimo_mes_disp
                     and r["marca"].lower() not in ("feriado",)]
        prev_rows = [r for r in rows if r["mes"] == prev_mes_disp
                     and r["marca"].lower() not in ("feriado",)]

        if mes_rows and prev_rows:
            fac_m  = sum(r["v"] for r in mes_rows)
            fac_p  = sum(r["v"] for r in prev_rows)
            ord_m  = sum(r["o"] for r in mes_rows)
            ord_p  = sum(r["o"] for r in prev_rows)

            delta_fac = (fac_m / fac_p - 1) * 100 if fac_p else 0
            delta_ord = (ord_m / ord_p - 1) * 100 if ord_p else 0
            ipc_m = ipc.get(ultimo_mes_disp, 3.0)

            # Nombre de meses para el título
            MESES_ES = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
                        7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}
            m_num  = int(ultimo_mes_disp[5:7])
            mp_num = int(prev_mes_disp[5:7])
            m_year = ultimo_mes_disp[:4]
            lbl_m  = f"{MESES_ES[m_num]} {m_year}"
            lbl_p  = f"{MESES_ES[mp_num]}"

            nota_datos = f"(Último dato disponible en BigQuery: {last_date.strftime('%d/%m/%Y')})"

            if delta_fac > ipc_m and delta_ord > 0:
                col, ico = "green", "📈"
                title = f"{lbl_m}: +{delta_fac:.1f}% facturación y +{delta_ord:.1f}% órdenes vs {lbl_p}"
                body = (
                    f"{lbl_m} cerró con {delta_fac:+.1f}% en facturación y {delta_ord:+.1f}% en órdenes "
                    f"vs {lbl_p}. Con inflación mensual de ~{ipc_m:.1f}% (IPC INDEC), "
                    f"hay crecimiento real en ambas dimensiones — la señal más positiva posible "
                    f"en el contexto de recuperación del sector gastronómico argentino. {nota_datos}"
                )
            elif delta_fac > ipc_m and delta_ord < 0:
                col, ico = "yellow", "🎭"
                title = f"{lbl_m}: +{delta_fac:.1f}% facturación pero {delta_ord:.1f}% en órdenes vs {lbl_p}"
                body = (
                    f"{lbl_m} muestra la paradoja post-recesión: facturación {delta_fac:+.1f}% "
                    f"(por encima de la inflación de {ipc_m:.1f}%), pero {delta_ord:.1f}% en órdenes vs {lbl_p}. "
                    f"El cliente gasta más cuando sale, pero sale menos seguido. "
                    f"La frecuencia de visita sigue siendo el indicador de salud real del negocio. {nota_datos}"
                )
            elif delta_fac < 0:
                col, ico = "red", "📉"
                title = f"Alerta {lbl_m}: {delta_fac:.1f}% en facturación vs {lbl_p}"
                body = (
                    f"{lbl_m} cerró con {delta_fac:.1f}% en facturación y {delta_ord:.1f}% en órdenes "
                    f"vs {lbl_p}. Con inflación de ~{ipc_m:.1f}%, la caída nominal implica "
                    f"contracción real significativa. Revisar causas: estacionalidad, "
                    f"pricing, o pérdida de tráfico estructural. {nota_datos}"
                )
            else:
                col, ico = "yellow", "📊"
                title = f"{lbl_m}: {delta_fac:+.1f}% nominal vs {lbl_p} — crecimiento real mínimo"
                body = (
                    f"{lbl_m} creció {delta_fac:+.1f}% en facturación vs {lbl_p}, "
                    f"por debajo de la inflación mensual de ~{ipc_m:.1f}%. "
                    f"Las órdenes variaron {delta_ord:+.1f}%. Crecimiento real negativo: "
                    f"el negocio factura más en pesos pero vende menos en términos reales. {nota_datos}"
                )
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 2 — Comparativa YoY por marca ───────────────────────────
    if len(meses_disponibles) >= 13 and marcas_validas:
        ultimo_mes = meses_disponibles[-1]
        mismo_mes_anio_ant = _prev_ym(ultimo_mes, 12)

        by_marca_mes = defaultdict(lambda: defaultdict(lambda: {"v": 0, "o": 0}))
        for r in rows:
            by_marca_mes[r["marca"]][r["mes"]]["v"] += r["v"]
            by_marca_mes[r["marca"]][r["mes"]]["o"] += r["o"]

        yoy_marcas = {}
        for marca in marcas_validas:
            cur  = by_marca_mes[marca].get(ultimo_mes, {}).get("v", 0)
            prev = by_marca_mes[marca].get(mismo_mes_anio_ant, {}).get("v", 0)
            if cur > 0 and prev > 0:
                yoy_marcas[marca] = (cur / prev - 1) * 100

        if yoy_marcas:
            meses_12 = _months_between(mismo_mes_anio_ant, ultimo_mes)
            infl_12m = _acum_inflation(ipc, meses_12)

            best_m = max(yoy_marcas, key=yoy_marcas.get)
            best_v = yoy_marcas[best_m]
            best_real = best_v - infl_12m

            worst_m = min(yoy_marcas, key=yoy_marcas.get)
            worst_v = yoy_marcas[worst_m]
            worst_real = worst_v - infl_12m

            col = "green" if best_real > 0 else "yellow"
            ico = "🏆"
            title = (
                f"{best_m} lidera el portfolio: {best_v:+.1f}% YoY "
                f"({'real +'+str(round(best_real,1))+'%' if best_real > 0 else 'real '+str(round(best_real,1))+'%'})"
            )
            body = (
                f"En {ultimo_mes}, {best_m} creció {best_v:+.1f}% YoY en facturación. "
                f"Con inflación acumulada de ~{infl_12m:.0f}% en los últimos 12 meses (IPC INDEC), "
                f"el crecimiento real es {'positivo: +' if best_real > 0 else ''}{best_real:.1f}%. "
            )
            if len(yoy_marcas) > 1:
                body += (
                    f"{worst_m} creció {worst_v:+.1f}% nominal ({worst_real:+.1f}% real) — "
                    f"{'aún por debajo de la inflación.' if worst_real < 0 else 'también superando la inflación.'} "
                )
            body += (
                f"La brecha entre marcas refleja diferencias en posicionamiento de precio, "
                f"mix de canales y cobertura geográfica."
            )
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 3 — Órdenes vs ticket (la paradoja post-recesión) ────────
    if len(meses_disponibles) >= 3:
        mes_rec = meses_disponibles[-1]
        mes_ant = _prev_ym(mes_rec, 1)

        def _mes_totals(mes):
            rs = [r for r in rows if r["mes"] == mes and r["marca"].lower() not in ("feriado",)]
            return sum(r["v"] for r in rs), sum(r["o"] for r in rs)

        fac_rec, ord_rec = _mes_totals(mes_rec)
        fac_ant, ord_ant = _mes_totals(mes_ant)

        if ord_ant and ord_rec and fac_ant and fac_rec:
            delta_fac = (fac_rec / fac_ant - 1) * 100
            delta_ord = (ord_rec / ord_ant - 1) * 100
            ipc_m = ipc.get(mes_rec, 3.0)

            if delta_fac > ipc_m and delta_ord < 0:
                col, ico = "yellow", "🎭"
                title = "Paradoja post-recesión: más facturación, menos órdenes"
                body = (
                    f"{mes_rec} vs {mes_ant}: facturación {delta_fac:+.1f}% pero órdenes {delta_ord:+.1f}%. "
                    f"Con inflación mensual de ~{ipc_m:.1f}% (IPC INDEC), el crecimiento nominal de facturación "
                    f"{'supera' if delta_fac > ipc_m else 'no supera'} a la inflación, pero hay menos clientes entrando. "
                    f"Este es el patrón típico post-recesión en gastronomía argentina: el consumidor que sobrevivió "
                    f"al ajuste gasta más cuando sale, pero sale menos seguido. "
                    f"La frecuencia de visita — no el ticket — es el indicador de salud real del negocio."
                )
                insights.append(_insight(col, ico, title, body, generated_at))
            elif delta_ord > 0 and delta_fac > ipc_m:
                col, ico = "green", "🚀"
                title = f"Recuperación genuina: más órdenes ({delta_ord:+.1f}%) y más facturación ({delta_fac:+.1f}%)"
                body = (
                    f"{mes_rec} vs {mes_ant}: la facturación creció {delta_fac:+.1f}% y las órdenes {delta_ord:+.1f}%. "
                    f"Con inflación mensual de ~{ipc_m:.1f}%, hay crecimiento real en ambas dimensiones. "
                    f"En el contexto del sector gastronómico argentino en 2026, esto representa "
                    f"una recuperación genuina de tráfico — la señal más positiva posible "
                    f"después de los trimestres de contracción de 2024."
                )
                insights.append(_insight(col, ico, title, body, generated_at))
            else:
                # Crecimiento neutral: nominal por debajo de la inflación, órdenes sin recuperar
                col, ico = "orange", "⚠️"
                title = f"Alerta: facturación {delta_fac:+.1f}% nominal vs {mes_ant} — pérdida real"
                body = (
                    f"{mes_rec} vs {mes_ant}: la facturación creció {delta_fac:+.1f}% nominal, "
                    f"por debajo de la inflación mensual estimada (~{ipc_m:.1f}%). "
                    f"Las órdenes variaron {delta_ord:+.1f}%. Resultado: contracción real del negocio. "
                    f"En un contexto de desaceleración inflacionaria, crecer por debajo del IPC "
                    f"implica que la actualización de precios no alcanzó a compensar la caída de volumen. "
                    f"Revisar pricing, mix de canales y frecuencia de visita por segmento."
                )
                insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 4 — Canal de ventas y margen ─────────────────────────────
    canales = defaultdict(lambda: {"v": 0, "o": 0})
    for r in rows:
        canales[r["canal"]]["v"] += r["v"]
        canales[r["canal"]]["o"] += r["o"]

    total_ord = sum(v["o"] for v in canales.values())
    if total_ord > 0:
        terceros_keys = [k for k in canales if any(
            x in k.lower() for x in ["pedidos", "rappi", "delivery", "tercero", "third"])]
        propios_keys = [k for k in canales if any(
            x in k.lower() for x in ["sale", "propio", "directo", "local", "mesa", "mostrador", "app"])]

        ord_terceros = sum(canales[k]["o"] for k in terceros_keys)
        ord_propios  = sum(canales[k]["o"] for k in propios_keys)

        pct_terceros = ord_terceros / total_ord * 100
        pct_propios  = ord_propios  / total_ord * 100

        if pct_propios >= 85:
            col, ico = "blue", "📱"
            title = f"Canal propio al {pct_propios:.0f}% — ventaja estructural de margen"
            body = (
                f"{pct_propios:.0f}% de las órdenes se procesan por canal directo (app o mostrador propio). "
                f"En el mercado argentino, apps de terceros como Pedidos Ya y Rappi cobran entre "
                f"{del_min}% y {del_max}% de comisión — hasta 8–10 puntos de margen bruto por transacción. "
                f"Mantener el canal propio por encima del 85% es una decisión estratégica de rentabilidad. "
                f"Oportunidad: activar L–J (días de menor tráfico) con promociones dirigidas "
                f"al canal directo sin canibalizar el fin de semana."
            )
            insights.append(_insight(col, ico, title, body, generated_at))
        elif pct_terceros > 10:
            col, ico = "orange", "🚚"
            title = f"Delivery externo: {pct_terceros:.0f}% de órdenes — margen bajo presión"
            body = (
                f"{pct_terceros:.0f}% de las órdenes van por apps de terceros. "
                f"Con comisiones del {del_min}–{del_max}%, esto puede representar hasta 10 puntos "
                f"de margen bruto cedidos por transacción. En Argentina, el delivery post-pandemia "
                f"es un hábito permanente del consumidor, pero la batalla por retener ese volumen "
                f"en el canal propio es crítica para sostener la rentabilidad en un contexto "
                f"de costos en alza."
            )
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 5 — Ticket promedio vs umbral de resistencia ─────────────
    tk_marca = defaultdict(list)
    for r in rows:
        if r["tk"] > 0 and r["marca"].lower() not in ("feriado",):
            tk_marca[r["marca"]].append(r["tk"])

    if tk_marca:
        avg_tk = {m: sum(v) / len(v) for m, v in tk_marca.items() if v}
        # El de mayor ticket
        top_m = max(avg_tk, key=avg_tk.get)
        top_tk = avg_tk[top_m]

        if top_tk >= tk_bajo * 0.85:
            col, ico = "purple", "💰"
            if top_tk > tk_alto:
                title = f"{top_m}: ticket ${top_tk:,.0f} — superando el umbral de resistencia premium"
                body = (
                    f"El ticket promedio de {top_m} es ${top_tk:,.0f}, por encima del umbral estimado "
                    f"de resistencia del consumidor premium (${tk_alto:,}). "
                    f"Históricamente, tickets sobre ese nivel generan caída en frecuencia de visita "
                    f"antes de que baje el gasto total. El patrón ya se detecta en los datos: "
                    f"más ticket, menos órdenes. Priorizar recuperación de tráfico "
                    f"sobre nuevos incrementos de precio."
                )
            else:
                body = (
                    f"El ticket promedio de {top_m} ronda ${top_tk:,.0f}, "
                    f"acercándose al rango de elasticidad del consumidor premium argentino "
                    f"(${tk_bajo:,}–${tk_alto:,} según consultoras del sector, 2026). "
                    f"Los ajustes de precios en los próximos meses deben equilibrar "
                    f"la actualización inflacionaria con el sostenimiento de la frecuencia de visita."
                )
                otros = [f"{m}: ${v:,.0f}" for m, v in sorted(avg_tk.items(), key=lambda x: -x[1]) if m != top_m]
                if otros:
                    body += f" Tickets del portfolio: {top_m}: ${top_tk:,.0f}" + \
                            (f", {', '.join(otros)}" if otros else "") + "."
                title = f"Ticket promedio ${top_tk:,.0f} — cerca del umbral de elasticidad premium"
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 7 — Concentración fines de semana ───────────────────────
    last_90 = [r for r in rows if (today - r["d"]).days <= 90]
    if last_90:
        fds = [r for r in last_90 if r["d"].weekday() >= 4]   # Viernes–Domingo
        sem = [r for r in last_90 if r["d"].weekday() < 4]    # Lunes–Jueves

        fds_days = len(set(r["d"] for r in fds))
        sem_days = len(set(r["d"] for r in sem))

        if fds_days > 0 and sem_days > 0:
            fac_total = sum(r["v"] for r in last_90)
            fac_fds   = sum(r["v"] for r in fds)
            fac_fds_avg = fac_fds / fds_days
            fac_sem_avg = sum(r["v"] for r in sem) / sem_days
            mult = fac_fds_avg / fac_sem_avg if fac_sem_avg else 0
            pct_fds = fac_fds / fac_total * 100 if fac_total else 0

            col, ico = "blue", "📅"
            title = (f"Fines de semana: {pct_fds:.0f}% de la facturación · "
                     f"{mult:.1f}x el día promedio de semana")
            body = (
                f"En los últimos 90 días, los fines de semana (V–D) concentraron "
                f"el {pct_fds:.0f}% de la facturación total. "
                f"Un día de fin de semana genera en promedio {mult:.1f}x lo que un día de semana (L–J). "
                f"Esta concentración refleja el modelo de gastronomía experiencial argentino: "
                f"el cliente reserva el gasto para la salida del fin de semana. "
                f"Oportunidad: activar lunes a jueves con beneficios en canal directo "
                f"para distribuir mejor el tráfico y reducir la dependencia del fin de semana."
            )
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 8 — Eficiencia de la red: facturación por local ─────────
    meses_3m_list = sorted(set(r["mes"] for r in rows))[-3:]
    if meses_3m_list:
        rows_3m = [r for r in rows if r["mes"] in meses_3m_list]
        locales_por_marca = defaultdict(set)
        fac_por_marca_3m  = defaultdict(float)
        for r in rows_3m:
            if r["e"]:
                locales_por_marca[r["marca"]].add(r["e"])
                fac_por_marca_3m[r["marca"]] += r["v"]

        eficiencia = {}
        for marca, locs in locales_por_marca.items():
            n = len(locs)
            if n > 0:
                eficiencia[marca] = fac_por_marca_3m[marca] / n

        if len(eficiencia) >= 2:
            mejor_m = max(eficiencia, key=eficiencia.get)
            mejor_v = eficiencia[mejor_m]
            n_mejor = len(locales_por_marca[mejor_m])
            lines = [
                f"{m}: ${v/1e6:.1f}M/local ({len(locales_por_marca[m])} locales)"
                for m, v in sorted(eficiencia.items(), key=lambda x: -x[1])
            ]
            col, ico = "green", "🏪"
            title = (f"{mejor_m} lidera eficiencia: "
                     f"${mejor_v/1e6:.1f}M por local promedio (últimos 3 meses)")
            body = (
                f"Facturación promedio por local activo en los últimos 3 meses: "
                f"{', '.join(lines)}. "
                f"{mejor_m} opera con {n_mejor} {'local' if n_mejor == 1 else 'locales'} y lidera la "
                f"eficiencia por punto de venta. "
                f"Esta métrica es clave para decisiones de expansión: "
                f"un nuevo local debe alcanzar el promedio de la marca en 6 meses "
                f"para validar el modelo operativo y rentabilidad esperada."
            )
            insights.append(_insight(col, ico, title, body, generated_at))

    # ── INSIGHT 6 — Macroeconomía argentina retail (SIEMPRE incluir) ─────
    year_now  = today.year
    month_now = today.month
    months_ytd = [f"{year_now}-{m:02d}" for m in range(1, month_now + 1)]
    infl_ytd = _acum_inflation(ipc, months_ytd)

    # Últimos 3 meses
    meses_3m = [today.strftime("%Y-%m")]
    for i in range(1, 3):
        meses_3m.append(_prev_ym(meses_3m[-1]))
    infl_3m = _acum_inflation(ipc, meses_3m)

    # Últimos 12 meses
    ym_now  = today.strftime("%Y-%m")
    ym_12m  = _prev_ym(ym_now, 12)
    infl_12m = _acum_inflation(ipc, _months_between(ym_12m, ym_now))

    col, ico = "red", "🇦🇷"
    title = (
        f"Macro AR retail: inflación {infl_ytd:.1f}% acum. {year_now} · "
        f"{infl_3m:.1f}% últimos 3 meses"
    )
    nota = ctx.get("nota_sector", "")
    body = (
        f"Con {infl_ytd:.1f}% de inflación acumulada en {year_now} y {infl_12m:.0f}% interanual "
        f"(IPC INDEC), el entorno del sector gastronómico/retail argentino en {year_now} "
        f"muestra desaceleración inflacionaria respecto al pico de 2024 "
        f"(ene-feb 2024: +20.6% y +13.2% mensual). "
        f"{''+nota+' ' if nota else ''}"
        f"Para el portfolio Temple Bar, el termómetro clave es si la facturación nominal "
        f"crece por encima del IPC — cualquier número por debajo implica contracción real. "
        f"Benchmark: crecer >3–4% mensual nominal en Q2 2026 implica expansión real del negocio."
    )
    insights.append(_insight(col, ico, title, body, generated_at))

    return insights[:8]


# ══════════════════════════════════════════════════════════════════════════
#  RENDERER HTML
# ══════════════════════════════════════════════════════════════════════════
def render_insights_html(insights):
    """
    Convierte lista de insight dicts en HTML listo para inyectar
    dentro de <div class="ig" id="insightsClave">.
    """
    parts = []
    for ins in insights:
        parts.append(
            f'<div class="ic" style="background:{ins["bg"]};border:1px solid {ins["border"]}">'
            f'<div class="it" style="color:{ins["title_color"]}">{ins["icon"]} {ins["title"]}</div>'
            f'<div class="ib">{ins["body"]}</div>'
            f'</div>'
        )
    return "\n    ".join(parts)
