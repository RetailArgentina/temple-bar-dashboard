#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera informe semanal de ventas en PDF usando ReportLab.
Uso: python -X utf8 generar_informe_semanal_pdf.py
"""

import os
from datetime import date, timedelta
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.lib.colors import HexColor

# ── Paleta de colores ──────────────────────────────────────────────────────────
DARK        = HexColor("#0d1117")
DARK2       = HexColor("#161b22")
DARK3       = HexColor("#21262d")
BORDER      = HexColor("#30363d")
GOLD        = HexColor("#e6a817")
GOLD_LIGHT  = HexColor("#f5c842")
GREEN       = HexColor("#2ea043")
GREEN_LIGHT = HexColor("#56d364")
RED         = HexColor("#da3633")
RED_LIGHT   = HexColor("#f85149")
BLUE        = HexColor("#388bfd")
BLUE_LIGHT  = HexColor("#79c0ff")
PURPLE      = HexColor("#8957e5")
PURPLE_LIGHT= HexColor("#bc8cff")
MUTED       = HexColor("#8b949e")
WHITE       = HexColor("#f0f6fc")
OFF_WHITE   = HexColor("#c9d1d9")
ROW_ALT     = HexColor("#1c2128")
ROW_HEADER  = HexColor("#1f2937")

# Colores por marca
MARCA_COLOR = {
    "Patagonia": BLUE,
    "Temple":    GOLD,
    "Feriado":   GREEN,
}

W, H = A4  # 595 x 842 pts

# ── Datos (cargados una sola vez) ─────────────────────────────────────────────
DATA = {
    "desde": "2026-05-11",
    "hasta": "2026-05-17",
    "semana_label": "12 al 18 de Mayo 2026",
    "semana_label_short": "12–18 Mayo 2026",

    "resumen": [
        # marca, fac, fac_pct_wow, fac_pct_yoy, ordenes, ord_pct_wow, ord_pct_yoy, ticket, tick_pct_yoy
        ("Patagonia", 522_371_666, -2.2, +24.4, 13_580, +1.6, +2.7,  38_744, +22.0),
        ("Temple",    274_711_635, +6.3, +20.7,  7_420, +4.2, -13.5, 38_403, +32.6),
        ("Feriado",    11_965_100, +5.5,  +6.9,    243, -4.0, -23.8, 49_239, +40.0),
    ],
    "total": (809_048_401, +0.7, +22.7, 21_243, +1.9),

    "dias": [
        ("Lun 12/05", 35.0, 17.6, 1.2),
        ("Mar 13/05", 44.2, 20.6, 0.6),
        ("Mié 14/05", 49.2, 25.6, 0.7),
        ("Jue 15/05", 67.6, 34.7, 1.2),
        ("Vie 16/05", 121.7, 67.0, 3.3),
        ("Sáb 17/05", 138.2, 79.7, 2.6),
        ("Dom 18/05", 66.4, 29.4, 2.4),
    ],

    "patagonia": {
        "fac": 522_371_666,
        "fac_wow": -2.2, "fac_yoy": +24.4,
        "ordenes": 13_580, "ord_wow": +1.6, "ord_yoy": +2.7,
        "ticket": 38_744, "tick_wow": -3.6, "tick_yoy": +22.0,
        "canal": [
            ("App Propia (SALE_APP)", 509.5, 12_905, 39_484, 97.5),
            ("PedidosYa",             12.7,    670, 24_636,  2.4),
            ("Rappi",                  0.1,      5, 18_000,  0.0),
        ],
        "turnos": [("Tarde", 201.8, 4712), ("Noche", 184.5, 5701), ("Mañana", 111.7, 2425), ("Extra", 24.4, 742)],
        "top_locales": [
            ("Pto. Iguazú MIS",   65.1, 1712, 38_027),
            ("Ushuaia",           52.1, 1168, 44_634),
            ("Puerto Madero",     34.3,  643, 53_339),
            ("Río Gallegos",      33.8, 1075, 31_997),
            ("Resistencia",       28.4, 2013, 14_119),
            ("Neuquén",           26.7,  369, 72_442),
            ("Corrientes",        24.4,  742, 32_877),
            ("Paraná",            22.7,  763, 33_313),
            ("Chaltén",           21.2,  349, 60_670),
            ("Casa del Tango",    18.4,  171,107_399),
        ],
        "nota": "Casa del Tango tiene el ticket más alto de la red: $107.399. Resistencia lidera en órdenes (2.013) con el ticket más bajo ($14.119).",
        "canal_nota": "97.5% canal propio. Prácticamente sin dependencia de agregadores.",
    },

    "temple": {
        "fac": 274_711_635,
        "fac_wow": +6.3, "fac_yoy": +20.7,
        "ordenes": 7_420, "ord_wow": +4.2, "ord_yoy": -13.5,
        "ticket": 38_403, "tick_wow": +3.5, "tick_yoy": +32.6,
        "canal": [
            ("App Propia (SALE_APP)", 253.1, 6227, 40_650, 92.1),
            ("PedidosYa",             21.6, 1193, 26_676,  7.9),
        ],
        "turnos": [("Noche", 161.4, 4000), ("Tarde", 65.3, 1988), ("Mañana", 48.0, 1432)],
        "top_locales": [
            ("Club Temple",      53.5,  919, 58_189),
            ("Puerto Madero",    47.3,  953, 49_770),
            ("Soho",             30.7,  768, 40_288),
            ("Barrio Chino",     22.1,  665, 33_260),
            ("Hollywood",        19.8,  491, 40_919),
            ("Casa Temple",      17.4,  439, 39_572),
            ("Maschwitz",        14.7,  438, 35_345),
            ("Río Gallegos",     12.9,  595, 28_285),
            ("Monroe",           12.1,  471, 26_048),
            ("Recoleta",          8.8,  320, 27_490),
        ],
        "nota": "Club Temple + Puerto Madero concentran el 37% de la facturación de la marca.",
        "canal_nota": "7.9% en PedidosYa con ticket 34% menor al canal propio ($26.676 vs $40.650).",
    },

    "feriado": {
        "fac": 11_965_100,
        "fac_wow": +5.5, "fac_yoy": +6.9,
        "ordenes": 243, "ord_wow": -4.0, "ord_yoy": -23.8,
        "ticket": 49_239, "tick_wow": +9.8, "tick_yoy": +40.0,
        "canal": [
            ("Salón",    10.0, 177, 56_575, 83.4),
            ("Delivery",  2.0,  66, 29_567, 16.6),
        ],
        "turnos": [("Noche", 6.8, 129), ("Tarde", 5.1, 114)],
        "top_locales": [
            ("Coghlan", 12.0, 243, 49_239),
        ],
        "nota": "Único local. Tráfico -23.8% YoY compensado con ticket +40% YoY.",
        "canal_nota": "Delivery opera al 52% del ticket del salón. Evaluar si es incremental o canibaliza mesas.",
    },

    "agenda": [
        ("Patagonia — caída de ticket -3.6% WoW",
         "La facturación baja a pesar del crecimiento en tráfico (+1.6%). ¿Mix geográfico o de producto? ¿Qué locales lideraron la caída?"),
        ("Temple — volumen vs. ticket YoY",
         "Órdenes -13.5% YoY pero revenue +20.7%. ¿La base 2025 incluía locales hoy cerrados? ¿Es premiumización real o cambio de base?"),
        ("PedidosYa en Temple — $21.6 M a ticket -34%",
         "Canal genera volumen a descuento significativo vs App propia. Revisar política de comisiones y descuentos por canal."),
        ("Feriado — tráfico en caída sostenida -23.8% YoY",
         "Los ingresos se sostienen por ticket, pero el volumen declina. ¿Hay plan de segundo local, expansión de capacidad o revisión de precios?"),
        ("Resistencia (Patagonia) — 2.013 órdenes a $14.119 ticket",
         "Mayor volumen de la red al ticket más bajo. ¿Es formato diferente por diseño? ¿Hay oportunidad de revisión de mix?"),
    ],
}


# ── Estilos ───────────────────────────────────────────────────────────────────
def make_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=22,
        textColor=WHITE, leading=26, alignment=TA_CENTER,
        spaceAfter=4,
    )
    styles["subtitle"] = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=11,
        textColor=MUTED, leading=14, alignment=TA_CENTER,
        spaceAfter=2,
    )
    styles["section"] = ParagraphStyle(
        "section", fontName="Helvetica-Bold", fontSize=13,
        textColor=WHITE, leading=16, spaceAfter=6, spaceBefore=14,
        leftIndent=0,
    )
    styles["subsection"] = ParagraphStyle(
        "subsection", fontName="Helvetica-Bold", fontSize=10,
        textColor=OFF_WHITE, leading=13, spaceAfter=4, spaceBefore=8,
    )
    styles["body"] = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9,
        textColor=OFF_WHITE, leading=13, spaceAfter=4,
    )
    styles["body_bold"] = ParagraphStyle(
        "body_bold", fontName="Helvetica-Bold", fontSize=9,
        textColor=WHITE, leading=13, spaceAfter=4,
    )
    styles["caption"] = ParagraphStyle(
        "caption", fontName="Helvetica-Oblique", fontSize=8,
        textColor=MUTED, leading=11, spaceAfter=6,
    )
    styles["kpi_label"] = ParagraphStyle(
        "kpi_label", fontName="Helvetica", fontSize=8,
        textColor=MUTED, leading=10, alignment=TA_CENTER,
    )
    styles["kpi_value"] = ParagraphStyle(
        "kpi_value", fontName="Helvetica-Bold", fontSize=16,
        textColor=WHITE, leading=18, alignment=TA_CENTER,
    )
    styles["agenda_title"] = ParagraphStyle(
        "agenda_title", fontName="Helvetica-Bold", fontSize=9,
        textColor=GOLD_LIGHT, leading=12, spaceAfter=2,
    )
    styles["agenda_body"] = ParagraphStyle(
        "agenda_body", fontName="Helvetica", fontSize=8.5,
        textColor=OFF_WHITE, leading=12, spaceAfter=2, leftIndent=8,
    )
    styles["footer"] = ParagraphStyle(
        "footer", fontName="Helvetica", fontSize=7.5,
        textColor=MUTED, leading=10, alignment=TA_CENTER,
    )
    return styles


# ── Helpers de formato ────────────────────────────────────────────────────────
def fmt_pct(v, good_positive=True):
    """Retorna string con color para variación porcentual."""
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    color = GREEN_LIGHT if (v > 0) == good_positive else RED_LIGHT
    return f'<font color="#{color.hexval()[2:]}">{sign}{v:.1f}%</font>'

def fmt_m(v):
    """Formatea millones con 1 decimal."""
    return f"${v/1e6:.1f} M"

def fmt_money(v):
    """Formatea pesos con separador de miles."""
    return f"${v:,.0f}"


def pct_arrow(v, good_positive=True):
    sign = "▲" if v > 0 else "▼"
    color = GREEN_LIGHT if (v > 0) == good_positive else RED_LIGHT
    return f'<font color="#{color.hexval()[2:]}">{sign} {abs(v):.1f}%</font>'


# ── Tabla genérica estilizada ─────────────────────────────────────────────────
def dark_table(data, col_widths, header_bg=ROW_HEADER, alt_bg=ROW_ALT, base_bg=DARK2,
               align_cols=None):
    """Crea tabla con fondo oscuro, filas alternadas y header destacado."""
    n_rows = len(data)
    n_cols = len(data[0])

    # Alineaciones por columna
    if align_cols is None:
        align_cols = ["CENTER"] * n_cols
        align_cols[0] = "LEFT"

    style_cmds = [
        ("BACKGROUND",  (0, 0), (-1, 0),          header_bg),
        ("TEXTCOLOR",   (0, 0), (-1, 0),          WHITE),
        ("FONTNAME",    (0, 0), (-1, 0),          "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0),          8),
        ("BOTTOMPADDING", (0, 0), (-1, 0),        5),
        ("TOPPADDING",  (0, 0), (-1, 0),          5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),      [base_bg, alt_bg]),
        ("TEXTCOLOR",   (0, 1), (-1, -1),         OFF_WHITE),
        ("FONTNAME",    (0, 1), (-1, -1),         "Helvetica"),
        ("FONTSIZE",    (0, 1), (-1, -1),         8),
        ("BOTTOMPADDING", (0, 1), (-1, -1),       4),
        ("TOPPADDING",  (0, 1), (-1, -1),         4),
        ("LINEBELOW",   (0, 0), (-1, 0),          0.5, BORDER),
        ("BOX",         (0, 0), (-1, -1),         0.5, BORDER),
        ("INNERGRID",   (0, 0), (-1, -1),         0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1),         6),
        ("RIGHTPADDING",(0, 0), (-1, -1),         6),
    ]

    for ci, al in enumerate(align_cols):
        style_cmds.append(("ALIGN", (ci, 0), (ci, -1), al))

    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Header/Footer de página ───────────────────────────────────────────────────
def on_page(canvas, doc, styles):
    canvas.saveState()

    # Header banda oscura
    canvas.setFillColor(DARK)
    canvas.rect(0, H - 1.4*cm, W, 1.4*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(GOLD)
    canvas.drawString(1.5*cm, H - 0.9*cm, "TEMPLE BAR GROUP")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(W - 1.5*cm, H - 0.9*cm, f"Informe Semanal · {DATA['semana_label_short']} · Confidencial")

    # Footer
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, W, 1*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(1.5*cm, 0.35*cm, "Datos: BigQuery · Temple Bar BI · Uso interno exclusivo")
    canvas.drawRightString(W - 1.5*cm, 0.35*cm, f"Página {doc.page}")

    canvas.restoreState()


# ── Sección KPI de marca ───────────────────────────────────────────────────────
def marca_kpi_band(marca, d, styles):
    color = MARCA_COLOR[marca]

    fac_M = d["fac"] / 1e6
    wow_fac = d["fac_wow"]
    yoy_fac = d["fac_yoy"]
    wow_ord = d["ord_wow"]
    yoy_ord = d["ord_yoy"]
    wow_tick = d["tick_wow"]
    yoy_tick = d["tick_yoy"]

    def kpi_cell(label, value, wow, yoy, good_pos_wow=True, good_pos_yoy=True):
        v_str = value
        w_str = pct_arrow(wow, good_pos_wow)
        y_str = pct_arrow(yoy, good_pos_yoy)
        return [
            Paragraph(label,           styles["kpi_label"]),
            Paragraph(v_str,           styles["kpi_value"]),
            Paragraph(f"vs sem.ant: {w_str}", styles["kpi_label"]),
            Paragraph(f"vs may-25: {y_str}",  styles["kpi_label"]),
        ]

    kpi_data = [
        kpi_cell("FACTURACIÓN",    f"${fac_M:.1f} M", wow_fac, yoy_fac),
        kpi_cell("ÓRDENES",        f"{d['ordenes']:,}", wow_ord, yoy_ord),
        kpi_cell("TICKET PROM.",   f"${d['ticket']:,.0f}", wow_tick, yoy_tick),
    ]

    col_w = (W - 3*cm) / 3
    rows = []
    for row in range(4):
        rows.append([kpi_data[c][row] for c in range(3)])

    t = Table(rows, colWidths=[col_w]*3)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1),  DARK3),
        ("BOX",         (0,0),(-1,-1),  1.5, color),
        ("LINEAFTER",   (0,0),(1,-1),   0.5, BORDER),
        ("TOPPADDING",  (0,0),(-1,-1),  3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
        ("ALIGN",       (0,0),(-1,-1),  "CENTER"),
        ("VALIGN",      (0,0),(-1,-1),  "MIDDLE"),
    ]))
    return t


# ── Construcción del documento ────────────────────────────────────────────────
def build_pdf(output_path):
    styles = make_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2.0*cm,  bottomMargin=1.5*cm,
        title=f"Informe Semanal Ventas {DATA['semana_label']}",
        author="Temple Bar BI",
        subject="Informe Gerencial de Ventas",
    )

    story = []

    # ── PORTADA ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*cm))

    # Bloque título sobre fondo oscuro
    title_data = [[
        Paragraph("INFORME DE VENTAS SEMANAL", styles["title"]),
    ]]
    title_table = Table(title_data, colWidths=[W - 3*cm])
    title_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), DARK),
        ("BOX",        (0,0),(-1,-1), 2, GOLD),
        ("TOPPADDING", (0,0),(-1,-1), 16),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ]))
    story.append(title_table)

    subtitle_data = [[
        Paragraph(f"Semana {DATA['semana_label']}", styles["subtitle"]),
    ],[
        Paragraph("Reunión Gerencial · Confidencial", styles["subtitle"]),
    ]]
    sub_table = Table(subtitle_data, colWidths=[W - 3*cm])
    sub_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), DARK2),
        ("BOX",        (0,0),(-1,-1), 1, BORDER),
        ("TOPPADDING", (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
    ]))
    story.append(sub_table)
    story.append(Spacer(1, 0.6*cm))

    # ── RESUMEN EJECUTIVO ─────────────────────────────────────────────────────
    story.append(Paragraph("RESUMEN EJECUTIVO", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=6))

    exec_text = (
        "El retail consolidado facturó <b>$809 M</b> en la semana, con crecimiento interanual del "
        "<b>+22.7% nominal</b>. El desempeño fue heterogéneo entre marcas: "
        "<b>Temple aceleró</b> (+6.3% WoW), <b>Patagonia cedió levemente</b> (-2.2% WoW a pesar de "
        "más tráfico) y <b>Feriado mantiene ingresos con tráfico decreciente</b> (-23.8% órdenes YoY "
        "compensado con ticket +40% YoY). En contexto de inflación estimada ~35% anual, el crecimiento "
        "nominal implica una caída real para todas las marcas — el volumen de órdenes consolidado cae "
        "-5.3% YoY."
    )
    story.append(Paragraph(exec_text, styles["body"]))
    story.append(Spacer(1, 0.3*cm))

    # ── TABLA RESUMEN ─────────────────────────────────────────────────────────
    story.append(Paragraph("CUADRO COMPARATIVO — SEMANA 12–18 MAYO", styles["subsection"]))

    def p(txt, st="body", align=None):
        s = styles[st]
        if align:
            s = ParagraphStyle("_tmp", parent=s, alignment={"C": TA_CENTER, "R": TA_RIGHT, "L": TA_LEFT}[align])
        return Paragraph(txt, s)

    hdr = [
        p("MARCA","body_bold","L"), p("FACTURACIÓN","body_bold","C"), p("vs s.ant","body_bold","C"),
        p("vs may-25","body_bold","C"), p("ÓRDENES","body_bold","C"), p("vs s.ant","body_bold","C"),
        p("vs may-25","body_bold","C"), p("TICKET","body_bold","C"), p("vs may-25","body_bold","C"),
    ]

    cw = [2.8*cm, 2.5*cm, 1.7*cm, 1.7*cm, 2.0*cm, 1.7*cm, 1.7*cm, 2.2*cm, 1.7*cm]

    rows = [hdr]
    for (marca, fac, fac_wow, fac_yoy, ord_, ord_wow, ord_yoy, tick, tick_yoy) in DATA["resumen"]:
        color = MARCA_COLOR[marca]
        row = [
            Paragraph(f'<font color="#{color.hexval()[2:]}"><b>{marca}</b></font>', styles["body"]),
            p(fmt_m(fac),            "body", "C"),
            Paragraph(pct_arrow(fac_wow),  styles["body"]),
            Paragraph(pct_arrow(fac_yoy),  styles["body"]),
            p(f"{ord_:,}",           "body", "C"),
            Paragraph(pct_arrow(ord_wow),  styles["body"]),
            Paragraph(pct_arrow(ord_yoy),  styles["body"]),
            p(fmt_money(tick),       "body", "C"),
            Paragraph(pct_arrow(tick_yoy), styles["body"]),
        ]
        rows.append(row)

    # Fila total
    fac_t, fac_t_wow, fac_t_yoy, ord_t, ord_t_wow = DATA["total"]
    total_row = [
        p("<b>TOTAL RETAIL</b>", "body_bold", "L"),
        p(f"<b>{fmt_m(fac_t)}</b>", "body_bold", "C"),
        Paragraph(pct_arrow(fac_t_wow), styles["body_bold"]),
        Paragraph(pct_arrow(fac_t_yoy), styles["body_bold"]),
        p(f"<b>{ord_t:,}</b>", "body_bold", "C"),
        Paragraph(pct_arrow(ord_t_wow), styles["body_bold"]),
        p("—", "body", "C"),
        p("—", "body", "C"),
        p("—", "body", "C"),
    ]
    rows.append(total_row)

    t_res = dark_table(rows, cw, align_cols=["LEFT","CENTER","CENTER","CENTER","CENTER","CENTER","CENTER","CENTER","CENTER"])
    t_res.setStyle(TableStyle([
        ("BACKGROUND",  (0, len(rows)-1), (-1, len(rows)-1), HexColor("#1f2937")),
        ("LINEABOVE",   (0, len(rows)-1), (-1, len(rows)-1), 1, GOLD),
        ("BOX",         (0,0),(-1,-1), 0.5, BORDER),
        ("INNERGRID",   (0,0),(-1,-1), 0.3, BORDER),
        ("LEFTPADDING", (0,0),(-1,-1), 5),
        ("RIGHTPADDING",(0,0),(-1,-1), 5),
        ("TOPPADDING",  (0,0),(-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("ROWBACKGROUNDS",(0,1),(-1,len(rows)-2), [DARK2, ROW_ALT]),
        ("FONTSIZE",    (0,0),(-1,-1), 8),
        ("ALIGN",       (0,0),(-1,-1), "CENTER"),
        ("ALIGN",       (0,0),(0,-1),  "LEFT"),
        ("BACKGROUND",  (0,0),(-1,0),  ROW_HEADER),
        ("TEXTCOLOR",   (0,0),(-1,0),  WHITE),
        ("FONTNAME",    (0,0),(-1,0),  "Helvetica-Bold"),
    ]))
    story.append(t_res)
    story.append(Spacer(1, 0.3*cm))

    # ── FACTURACIÓN DIARIA ────────────────────────────────────────────────────
    story.append(Paragraph("FACTURACIÓN DIARIA (en millones $)", styles["subsection"]))

    dias_hdr = [p("DÍA","body_bold","L"), p("PATAGONIA","body_bold","C"),
                p("TEMPLE","body_bold","C"), p("FERIADO","body_bold","C"), p("TOTAL","body_bold","C")]
    dias_rows = [dias_hdr]
    for (dia, pat, tem, fer) in DATA["dias"]:
        total_dia = pat + tem + fer
        dias_rows.append([
            p(dia, "body", "L"),
            p(f"${pat:.1f} M", "body", "C"),
            p(f"${tem:.1f} M", "body", "C"),
            p(f"${fer:.1f} M", "body", "C"),
            p(f"<b>${total_dia:.1f} M</b>", "body_bold", "C"),
        ])

    t_dias = dark_table(dias_rows, [3.2*cm, 3.4*cm, 3.4*cm, 2.8*cm, 3.0*cm],
                        align_cols=["LEFT","CENTER","CENTER","CENTER","CENTER"])
    story.append(t_dias)
    story.append(Paragraph(
        "Vie+Sáb concentran ~50% de la facturación semanal en las tres marcas.",
        styles["caption"]
    ))

    # ── ANÁLISIS POR MARCA ────────────────────────────────────────────────────
    for marca in ["Patagonia", "Temple", "Feriado"]:
        story.append(PageBreak())
        d = DATA[marca.lower()]
        color = MARCA_COLOR[marca]

        # Banner de marca
        banner_data = [[Paragraph(
            f'<font color="#{color.hexval()[2:]}">■</font>  <b>{marca.upper()}</b>  —  '
            f'Facturación {fmt_m(d["fac"])}  ·  {d["ordenes"]:,} órdenes  ·  Ticket {fmt_money(d["ticket"])}',
            ParagraphStyle("banner", fontName="Helvetica-Bold", fontSize=11,
                           textColor=WHITE, leading=14)
        )]]
        banner = Table(banner_data, colWidths=[W - 3*cm])
        banner.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,-1), DARK),
            ("BOX",         (0,0),(-1,-1), 2, color),
            ("TOPPADDING",  (0,0),(-1,-1), 10),
            ("BOTTOMPADDING",(0,0),(-1,-1), 10),
            ("LEFTPADDING", (0,0),(-1,-1), 12),
        ]))
        story.append(banner)
        story.append(Spacer(1, 0.3*cm))

        # KPIs
        story.append(marca_kpi_band(marca, d, styles))
        story.append(Spacer(1, 0.4*cm))

        # Top Locales + Canal (lado a lado)
        story.append(Paragraph("TOP LOCALES", styles["subsection"]))
        loc_hdr = [p("LOCAL","body_bold","L"), p("FACTURACIÓN","body_bold","C"),
                   p("ÓRDENES","body_bold","C"), p("TICKET","body_bold","C")]
        loc_rows = [loc_hdr]
        for (local, fac_m, ords, tick) in d["top_locales"]:
            loc_rows.append([
                p(local, "body", "L"),
                p(f"${fac_m:.1f} M", "body", "C"),
                p(f"{ords:,}", "body", "C"),
                p(fmt_money(tick), "body", "C"),
            ])

        t_loc = dark_table(loc_rows, [5.5*cm, 3.0*cm, 2.5*cm, 3.0*cm],
                           align_cols=["LEFT","CENTER","CENTER","CENTER"])
        story.append(t_loc)
        story.append(Paragraph(d["nota"], styles["caption"]))
        story.append(Spacer(1, 0.3*cm))

        # Canal y Turno
        col_a = W - 3*cm

        story.append(Paragraph("CANAL", styles["subsection"]))
        can_hdr = [p("CANAL","body_bold","L"), p("FAC. (M$)","body_bold","C"),
                   p("ÓRDENES","body_bold","C"), p("TICKET","body_bold","C"), p("% FAC","body_bold","C")]
        can_rows = [can_hdr]
        for (canal, fac_m, ords, tick, pct) in d["canal"]:
            can_rows.append([
                p(canal, "body", "L"),
                p(f"${fac_m:.1f} M", "body", "C"),
                p(f"{ords:,}", "body", "C"),
                p(fmt_money(tick), "body", "C"),
                p(f"{pct:.1f}%", "body", "C"),
            ])
        t_can = dark_table(can_rows, [5.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 1.8*cm],
                           align_cols=["LEFT","CENTER","CENTER","CENTER","CENTER"])
        story.append(t_can)
        story.append(Paragraph(d["canal_nota"], styles["caption"]))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("TURNO", styles["subsection"]))
        tur_hdr = [p("TURNO","body_bold","L"), p("FAC. (M$)","body_bold","C"), p("ÓRDENES","body_bold","C"), p("% FAC","body_bold","C")]
        tur_rows = [tur_hdr]
        total_fac_tur = sum(f for _, f, _ in d["turnos"])
        for (turno, fac_m, ords) in d["turnos"]:
            pct_t = fac_m / total_fac_tur * 100 if total_fac_tur else 0
            tur_rows.append([
                p(turno, "body", "L"),
                p(f"${fac_m:.1f} M", "body", "C"),
                p(f"{ords:,}", "body", "C"),
                p(f"{pct_t:.1f}%", "body", "C"),
            ])
        t_tur = dark_table(tur_rows, [5.5*cm, 3.0*cm, 3.0*cm, 2.8*cm],
                           align_cols=["LEFT","CENTER","CENTER","CENTER"])
        story.append(t_tur)

    # ── AGENDA DE REUNIÓN ─────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("AGENDA — PUNTOS PARA DISCUSIÓN GERENCIAL", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=8))

    for i, (titulo, desc) in enumerate(DATA["agenda"], 1):
        item_data = [[
            Paragraph(f"{i}.", ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=12,
                                               textColor=GOLD, leading=14, alignment=TA_CENTER)),
            [
                Paragraph(titulo, styles["agenda_title"]),
                Paragraph(desc, styles["agenda_body"]),
            ]
        ]]
        item_t = Table(item_data, colWidths=[0.9*cm, W - 3*cm - 0.9*cm])
        item_t.setStyle(TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), DARK2),
            ("BOX",          (0,0),(-1,-1), 0.5, BORDER),
            ("LINEAFTER",    (0,0),(0,-1),  0.5, BORDER),
            ("VALIGN",       (0,0),(-1,-1), "TOP"),
            ("TOPPADDING",   (0,0),(-1,-1), 8),
            ("BOTTOMPADDING",(0,0),(-1,-1), 8),
            ("LEFTPADDING",  (0,0),(0,-1),  0),
            ("RIGHTPADDING", (0,0),(0,-1),  0),
            ("LEFTPADDING",  (1,0),(1,-1),  10),
        ]))
        story.append(KeepTogether(item_t))
        story.append(Spacer(1, 0.2*cm))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6))
    story.append(Paragraph(
        "Todos los valores son nominales en pesos argentinos. Para comparaciones reales contra inflación "
        "solicitar análisis IPC complementario. Fuente: BigQuery · Temple Bar BI · Generado automáticamente.",
        styles["caption"]
    ))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(
        story,
        onFirstPage=lambda c, d: on_page(c, d, styles),
        onLaterPages=lambda c, d: on_page(c, d, styles),
    )
    print(f"PDF generado: {output_path}")


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "Informe_Ventas_Semanal_12-18mayo2026.pdf")
    build_pdf(out)
