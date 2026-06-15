"""
weekly_report.py
Generación y envío del informe semanal automático vía Twilio WhatsApp.
"""
import os
from datetime import date, timedelta

from twilio.rest import Client as TwilioClient

from whatsapp_tools import query_retail, get_objectives_for_tool


# ── Date helpers ───────────────────────────────────────────────────────────────

def get_last_week_range() -> tuple[str, str]:
    """
    Retorna (fecha_desde, fecha_hasta) de la semana anterior.
    Diseñado para correr el lunes: fecha_desde = lunes anterior (hoy-7),
    fecha_hasta = domingo anterior (hoy-1).
    Ej: si hoy es lunes 25/05 → ("2026-05-18", "2026-05-24")
    """
    today       = date.today()
    last_monday = today - timedelta(days=7)
    last_sunday = today - timedelta(days=1)
    return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")


# ── Helpers de formato ─────────────────────────────────────────────────────────

def _semaforo(real_pct: float, pace_pct: float) -> str:
    return "✅" if real_pct - pace_pct >= -2 else "⚠️"


def _marca_emoji(marca: str) -> str:
    return {"Patagonia": "🔵", "Temple": "🟣", "Feriado": "🟢"}.get(marca, "📊")


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_short_report(
    desde: str,
    hasta: str,
    retail_data: list,
    objectives: dict,
) -> str:
    """Genera el texto del resumen corto para enviar a todos los usuarios."""
    total_fac = sum(r["facturacion"] for r in retail_data)
    total_ord = sum(r["ordenes"]     for r in retail_data)

    lines = [
        f"📊 Informe Semanal — {desde} al {hasta}",
        f"Red total: ${total_fac/1e6:.1f}M | {total_ord:,} órdenes",
        "──────────────────",
    ]

    for row in retail_data:
        marca    = row["grupo"]
        fac_m    = row["facturacion"] / 1e6
        ticket   = row["ticket"]
        obj      = objectives.get(marca, {})
        obj_fac  = obj.get("obj_fac", 0)
        pace     = obj.get("pace_pct", 0)
        real_pct = round(fac_m / obj_fac * 100, 1) if obj_fac else 0
        semaforo = _semaforo(real_pct, pace)
        emoji    = _marca_emoji(marca)

        lines += [
            f"{emoji} {marca}: ${fac_m:.1f}M | ticket ${ticket:,.0f}",
            f"Cumpl: {real_pct}% real vs {pace}% esperado {semaforo}",
        ]

    lines += [
        "──────────────────",
        'Respondé "más info" para el detalle completo.',
    ]

    return "\n".join(lines)


# ── Twilio sender ──────────────────────────────────────────────────────────────

def send_whatsapp(twilio_client: TwilioClient, to: str, from_: str, body: str) -> None:
    """Envía un mensaje de WhatsApp vía Twilio."""
    twilio_client.messages.create(from_=from_, to=to, body=body)


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def run_weekly_report(bq_client, config: dict) -> dict:
    """
    Genera y envía el informe semanal a todos los usuarios del config.
    Retorna resumen de envíos para logging.
    """
    desde, hasta = get_last_week_range()
    retail_data  = query_retail(bq_client, desde, hasta, "marca")

    mes_actual = date.today().strftime("%Y-%m")
    objectives = {
        marca: get_objectives_for_tool(marca, mes_actual)
        for marca in ["Patagonia", "Temple", "Feriado"]
    }

    short_text    = format_short_report(desde, hasta, retail_data, objectives)
    twilio_client = TwilioClient(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"],
    )
    twilio_from = os.environ["TWILIO_WHATSAPP_FROM"]

    sent = []
    for user in config["users"]:
        send_whatsapp(twilio_client, user["phone"], twilio_from, short_text)
        sent.append(user["phone"])

    return {"sent_to": sent, "desde": desde, "hasta": hasta}
