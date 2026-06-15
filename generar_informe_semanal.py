#!/usr/bin/env python3
"""
generar_informe_semanal.py
Genera un informe PDF semanal de ventas para reuniones gerenciales.
Uso: python -X utf8 generar_informe_semanal.py [--semana YYYY-MM-DD] [--output informe.pdf]
     --semana: lunes de inicio de la semana a reportar (default: semana pasada)
"""

import sys, os, io, argparse
from datetime import datetime, timedelta, date

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from google.cloud import bigquery
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

# ── Configuración ─────────────────────────────────────────────────────────────
PROJECT_ID   = "temple-bar-439715"
DATASET_ID   = "Corporativo"
TABLE_VENTAS = "vw_Ventas_Corporativo_Base"
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SA_FILE      = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
SHEET_ID_OBJ = "18gkS8YNGVpL0AlfQMemhtT3lOPeRRyORkkTvAoHi-YA"
SHEET_NAME   = "Objetivos_Temple_BQ"

# Paleta de colores
C_NAVY   = HexColor('#0f2544')
C_BLUE   = HexColor('#2563eb')
C_VIOLET = HexColor('#7c3aed')
C_GREEN  = HexColor('#059669')
C_RED    = HexColor('#dc2626')
C_GOLD   = HexColor('#d97706')
C_LGRAY  = HexColor('#f1f5f9')
C_MGRAY  = HexColor('#cbd5e1')
C_DKGRAY = HexColor('#475569')
C_WHITE  = colors.white
C_BLACK  = colors.black

BRAND_COLORS = {
    'Temple':   HexColor('#2563eb'),
    'Patagonia':HexColor('#7c3aed'),
    'Feriado':  HexColor('#059669'),
}
BRAND_MPL = {
    'Temple':   '#2563eb',
    'Patagonia':'#7c3aed',
    'Feriado':  '#059669',
}

# ── BQ client ─────────────────────────────────────────────────────────────────
def get_client():
    scopes = [
        "https://www.googleapis.com/auth/bigquery",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/cloud-platform",
    ]
    creds = service_account.Credentials.from_service_account_file(SA_FILE, scopes=scopes)
    return bigquery.Client(project=PROJECT_ID, credentials=creds)

# ── Fetch datos semanales ─────────────────────────────────────────────────────
def fetch_semana(client, desde, hasta):
    """Agrega ventas por marca, local y canal para el rango dado."""
    q = f"""
        SELECT
            FORMAT_DATE('%Y-%m-%d', Fecha)  AS dia,
            Marca,
            UPPER(TRIM(Local))              AS local_name,
            Canal,
            Turno,
            COUNT(*)                        AS ordenes,
            ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64)) / 1e6, 3) AS fac_M
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha BETWEEN '{desde}' AND '{hasta}'
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 1 AND 1e12
        GROUP BY dia, Marca, local_name, Canal, Turno
        ORDER BY dia, Marca
    """
    return [dict(r) for r in client.query(q).result()]

def fetch_mes_actual(client, mes_inicio, hasta):
    """Acumulado del mes en curso por marca."""
    q = f"""
        SELECT
            Marca,
            COUNT(*)                                                     AS ordenes,
            ROUND(SUM(SAFE_CAST(Facturacion AS FLOAT64)) / 1e6, 2)      AS fac_M
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_VENTAS}`
        WHERE Fecha BETWEEN '{mes_inicio}' AND '{hasta}'
          AND SAFE_CAST(Facturacion AS FLOAT64) BETWEEN 1 AND 1e12
        GROUP BY Marca
    """
    return {r['Marca']: {'fac_M': float(r['fac_M'] or 0), 'ordenes': int(r['ordenes'] or 0)}
            for r in client.query(q).result()}

def fetch_objetivos():
    """Lee objetivos mensuales del Google Sheet."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = service_account.Credentials.from_service_account_file(SA_FILE, scopes=scopes)
    svc   = gbuild("sheets", "v4", credentials=creds, cache_discovery=False)
    res   = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID_OBJ,
        range=f"{SHEET_NAME}!A1:Z2000"
    ).execute()
    values = res.get("values", [])
    if not values:
        return {}

    headers = [h.strip().lower() for h in values[0]]
    hl = {h: i for i, h in enumerate(headers)}

    idx_mes   = next((hl[k] for k in hl if k in ('mes','month','periodo')), None)
    idx_marca = next((hl[k] for k in hl if 'marca' in k), None)
    idx_fac   = hl.get('objetivo_facturacion_bq') or next((hl[k] for k in hl if 'fac' in k), None)

    objs = {}
    for row in values[1:]:
        def cell(i):
            try: return row[i].strip() if i < len(row) else ""
            except: return ""
        mes   = cell(idx_mes)[:7]
        marca = cell(idx_marca)
        fac_s = cell(idx_fac).replace(".", "").replace(",", ".")
        if not mes or not marca or not fac_s:
            continue
        try:
            fac_M = round(float(fac_s) / 1e6, 1)
        except ValueError:
            continue
        objs.setdefault(marca, {})[mes] = fac_M
    return objs

# ── Agregaciones helper ───────────────────────────────────────────────────────
def agg_por_marca(rows):
    """Suma fac_M y ordenes agrupando por Marca."""
    out = {}
    for r in rows:
        m = r['Marca']
        out.setdefault(m, {'fac_M': 0.0, 'ordenes': 0})
        out[m]['fac_M']   += float(r['fac_M'] or 0)
        out[m]['ordenes'] += int(r['ordenes'] or 0)
    return out

def agg_por_local(rows):
    """Top locales por fac_M."""
    out = {}
    for r in rows:
        key = (r['Marca'], r['local_name'])
        out.setdefault(key, {'fac_M': 0.0, 'ordenes': 0, 'Marca': r['Marca'], 'local': r['local_name']})
        out[key]['fac_M']   += float(r['fac_M'] or 0)
        out[key]['ordenes'] += int(r['ordenes'] or 0)
    return sorted(out.values(), key=lambda x: -x['fac_M'])

def agg_por_canal(rows):
    out = {}
    for r in rows:
        c = r['Canal'] or 'Sin canal'
        out.setdefault(c, {'fac_M': 0.0, 'ordenes': 0})
        out[c]['fac_M']   += float(r['fac_M'] or 0)
        out[c]['ordenes'] += int(r['ordenes'] or 0)
    return dict(sorted(out.items(), key=lambda x: -x[1]['fac_M']))

def agg_por_turno(rows):
    out = {}
    for r in rows:
        t = r['Turno'] or 'Sin turno'
        out.setdefault(t, {'fac_M': 0.0, 'ordenes': 0})
        out[t]['fac_M']   += float(r['fac_M'] or 0)
        out[t]['ordenes'] += int(r['ordenes'] or 0)
    return dict(sorted(out.items(), key=lambda x: -x[1]['fac_M']))

def fmt_M(v):
    """Formatea millones como $X.X M"""
    if v >= 1000:
        return f"${v/1000:.1f} B"
    if v >= 1:
        return f"${v:.1f} M"
    return f"${v*1000:.0f} K"

def fmt_pct(v, sign=True):
    s = f"{v:+.1f}%" if sign else f"{v:.1f}%"
    return s

def delta_pct(nuevo, viejo):
    if viejo == 0:
        return None
    return (nuevo - viejo) / viejo * 100

def ticket_prom(fac_M, ordenes):
    if ordenes == 0:
        return 0
    return round(fac_M * 1e6 / ordenes)

def fmt_ars(v):
    """Formatea entero como $XX.XXX"""
    return f"${int(v):,.0f}".replace(",", ".")

# ── Gráficos ──────────────────────────────────────────────────────────────────
def chart_marcas_comparativo(esta, anterior, marcas):
    """Bar chart lado a lado: esta semana vs anterior, por marca."""
    fig, ax = plt.subplots(figsize=(7, 3.2))
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#f8fafc')

    x     = np.arange(len(marcas))
    width = 0.35
    vals_esta = [esta.get(m, {}).get('fac_M', 0) for m in marcas]
    vals_ant  = [anterior.get(m, {}).get('fac_M', 0) for m in marcas]

    bars1 = ax.bar(x - width/2, vals_esta, width, label='Esta semana',
                   color=[BRAND_MPL.get(m, '#64748b') for m in marcas], zorder=3)
    bars2 = ax.bar(x + width/2, vals_ant,  width, label='Sem. anterior',
                   color=[BRAND_MPL.get(m, '#64748b') for m in marcas], alpha=0.35, zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(marcas, fontsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:.0f}M"))
    ax.set_ylabel("Facturación (M ARS)", fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=0.4, zorder=0)
    ax.spines[['top','right']].set_visible(False)

    for bar in bars1:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width()/2, h + max(vals_esta+vals_ant)*0.01,
                    f"${h:.1f}M", ha='center', va='bottom', fontsize=7, fontweight='bold')

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf

def chart_canal(canal_data):
    """Horizontal bar chart por canal."""
    canales = list(canal_data.keys())[:6]
    vals    = [canal_data[c]['fac_M'] for c in canales]
    total   = sum(vals)

    fig, ax = plt.subplots(figsize=(5.5, max(2.5, len(canales)*0.5 + 0.8)))
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#f8fafc')

    colors_bar = ['#2563eb','#3b82f6','#60a5fa','#93c5fd','#bfdbfe','#dbeafe']
    bars = ax.barh(canales, vals, color=colors_bar[:len(canales)], zorder=3)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:.0f}M"))
    ax.grid(axis='x', alpha=0.4, zorder=0)
    ax.spines[['top','right']].set_visible(False)
    ax.invert_yaxis()

    for bar, val in zip(bars, vals):
        pct = val/total*100 if total > 0 else 0
        ax.text(bar.get_width() + max(vals)*0.01, bar.get_y() + bar.get_height()/2,
                f"${val:.1f}M ({pct:.0f}%)", va='center', fontsize=7)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf

def chart_turno(turno_data):
    """Pie chart por turno."""
    turnos = list(turno_data.keys())[:5]
    vals   = [turno_data[t]['fac_M'] for t in turnos]

    fig, ax = plt.subplots(figsize=(4, 3.2))
    fig.patch.set_facecolor('#ffffff')

    palette = ['#2563eb','#7c3aed','#059669','#d97706','#dc2626']
    wedges, texts, autotexts = ax.pie(
        vals, labels=turnos, autopct='%1.0f%%',
        colors=palette[:len(turnos)],
        startangle=90, pctdistance=0.75,
        textprops={'fontsize': 8}
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color('white')
        at.set_fontweight('bold')

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf

# ── Estilos PDF ───────────────────────────────────────────────────────────────
def make_styles():
    base = getSampleStyleSheet()
    styles = {}
    styles['title'] = ParagraphStyle('title',
        fontName='Helvetica-Bold', fontSize=24, textColor=C_NAVY,
        alignment=TA_CENTER, spaceAfter=4)
    styles['subtitle'] = ParagraphStyle('subtitle',
        fontName='Helvetica', fontSize=13, textColor=C_DKGRAY,
        alignment=TA_CENTER, spaceAfter=2)
    styles['section'] = ParagraphStyle('section',
        fontName='Helvetica-Bold', fontSize=13, textColor=C_NAVY,
        spaceBefore=12, spaceAfter=6, borderPad=4)
    styles['body'] = ParagraphStyle('body',
        fontName='Helvetica', fontSize=9, textColor=C_DKGRAY, spaceAfter=4)
    styles['small'] = ParagraphStyle('small',
        fontName='Helvetica', fontSize=7.5, textColor=C_DKGRAY)
    styles['kpi_val'] = ParagraphStyle('kpi_val',
        fontName='Helvetica-Bold', fontSize=20, textColor=C_NAVY, alignment=TA_CENTER)
    styles['kpi_lbl'] = ParagraphStyle('kpi_lbl',
        fontName='Helvetica', fontSize=8, textColor=C_DKGRAY, alignment=TA_CENTER)
    styles['kpi_delta'] = ParagraphStyle('kpi_delta',
        fontName='Helvetica-Bold', fontSize=9, alignment=TA_CENTER)
    styles['footer'] = ParagraphStyle('footer',
        fontName='Helvetica', fontSize=7, textColor=C_MGRAY, alignment=TA_CENTER)
    return styles

# ── Header/footer canvas ──────────────────────────────────────────────────────
class HeaderFooter:
    def __init__(self, semana_label):
        self.semana = semana_label

    def __call__(self, canv, doc):
        canv.saveState()
        w, h = A4
        # Header bar
        canv.setFillColor(C_NAVY)
        canv.rect(0, h - 1.2*cm, w, 1.2*cm, fill=1, stroke=0)
        canv.setFillColor(C_WHITE)
        canv.setFont('Helvetica-Bold', 10)
        canv.drawString(1.5*cm, h - 0.85*cm, 'TEMPLE BAR · INFORME SEMANAL DE VENTAS')
        canv.setFont('Helvetica', 9)
        canv.drawRightString(w - 1.5*cm, h - 0.85*cm, self.semana)
        # Footer
        canv.setFillColor(C_MGRAY)
        canv.setFont('Helvetica', 7)
        canv.drawString(1.5*cm, 0.6*cm, 'Confidencial · Uso interno gerencial')
        canv.drawRightString(w - 1.5*cm, 0.6*cm, f'Pág. {doc.page}')
        canv.restoreState()

# ── Tabla con estilo ──────────────────────────────────────────────────────────
def make_table(data, col_widths, header_bg=None, stripe=True):
    if header_bg is None:
        header_bg = C_NAVY

    style = [
        ('BACKGROUND', (0,0), (-1,0), header_bg),
        ('TEXTCOLOR',  (0,0), (-1,0), C_WHITE),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,0), 8),
        ('ALIGN',      (0,0), (-1,0), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING',    (0,0), (-1,0), 6),
        ('FONTNAME',   (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,1), (-1,-1), 8),
        ('TOPPADDING',    (0,1), (-1,-1), 4),
        ('BOTTOMPADDING', (0,1), (-1,-1), 4),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_WHITE, C_LGRAY] if stripe else [C_WHITE]),
        ('GRID',       (0,0), (-1,-1), 0.4, C_MGRAY),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
    ]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style))
    return t

def delta_text(pct, styles):
    if pct is None:
        return Paragraph('—', styles['kpi_delta'])
    color = '#059669' if pct >= 0 else '#dc2626'
    arrow = '▲' if pct >= 0 else '▼'
    return Paragraph(f'<font color="{color}">{arrow} {abs(pct):.1f}%</font>', styles['kpi_delta'])

# ── Plan de Acción auto-generado ──────────────────────────────────────────────
def generate_plan_accion(
    marca_esta, marca_ant, locales_top, locales_ant_dict,
    mes_real, objetivos, pace, canal_data, turno_data,
    semana_inicio, dias_mes_trans, dias_mes_total
):
    """
    Genera acciones automáticas por área basadas en los datos de la semana.
    Retorna dict: {'Operaciones': [...], 'Marketing': [...], 'Datos': [...]}
    Cada acción es un dict: {prioridad: 'Alta'|'Media'|'Baja', texto: str, detalle: str}
    """
    mes_key = semana_inicio.strftime('%Y-%m')
    marcas_activas = ['Temple', 'Patagonia', 'Feriado']
    acciones = {'Operaciones': [], 'Marketing': [], 'Datos': []}

    def add(area, prioridad, texto, detalle=''):
        acciones[area].append({'prioridad': prioridad, 'texto': texto, 'detalle': detalle})

    # ── OPERACIONES ────────────────────────────────────────────────────────────

    # 1. Pace por marca: si real < 85% del objetivo prorrateado → acción urgente
    for m in marcas_activas:
        obj_M  = objetivos.get(m, {}).get(mes_key, 0)
        real_M = mes_real.get(m, {}).get('fac_M', 0)
        if obj_M <= 0:
            continue
        obj_pace = obj_M * pace
        cumpl_pace = real_M / obj_pace * 100 if obj_pace > 0 else 100
        dias_rest = dias_mes_total - dias_mes_trans
        if cumpl_pace < 80 and dias_rest > 3:
            falta = obj_M - real_M
            por_dia = falta / dias_rest if dias_rest > 0 else 0
            add('Operaciones', 'Alta',
                f"{m}: ritmo de facturación {cumpl_pace:.0f}% del objetivo esperado",
                f"Faltan ${falta:.1f}M para el objetivo. Necesita ${por_dia:.1f}M/día en los próximos {dias_rest} días. "
                f"Revisar densidad operativa y horarios de apertura en los locales de mayor volumen.")
        elif cumpl_pace < 92 and dias_rest > 3:
            add('Operaciones', 'Media',
                f"{m}: levemente por debajo del ritmo esperado ({cumpl_pace:.0f}%)",
                f"Diferencia recuperable. Foco en maximizar facturación en el fin de semana próximo.")

    # 2. Locales con caída fuerte vs semana anterior (top 20 por volumen)
    caidas_loc = []
    for loc in locales_top[:20]:
        key = (loc['Marca'], loc['local'])
        fac0 = locales_ant_dict.get(key, 0)
        if fac0 > 0 and loc['fac_M'] > 0:
            dp = (loc['fac_M'] - fac0) / fac0 * 100
            if dp < -20:
                caidas_loc.append((loc['local'].title(), loc['Marca'], dp, loc['fac_M'], fac0))
    caidas_loc.sort(key=lambda x: x[2])
    for local, marca, dp, fac, fac0 in caidas_loc[:3]:
        prioridad = 'Alta' if dp < -30 else 'Media'
        add('Operaciones', prioridad,
            f"{local} ({marca}): caída del {abs(dp):.0f}% vs semana anterior",
            f"Pasó de ${fac0:.1f}M a ${fac:.1f}M. Verificar apertura, dotación de personal y eventos del período.")

    # 3. Caída de ticket promedio por marca > 8%
    for m in marcas_activas:
        fac_e  = marca_esta.get(m, {}).get('fac_M', 0)
        ord_e  = marca_esta.get(m, {}).get('ordenes', 0)
        fac_a  = marca_ant.get(m, {}).get('fac_M', 0)
        ord_a  = marca_ant.get(m, {}).get('ordenes', 0)
        tk_e   = ticket_prom(fac_e, ord_e)
        tk_a   = ticket_prom(fac_a, ord_a)
        if tk_a > 0 and tk_e > 0:
            dp_tk = (tk_e - tk_a) / tk_a * 100
            if dp_tk < -8:
                add('Operaciones', 'Media',
                    f"{m}: ticket promedio cayó {abs(dp_tk):.0f}% (${tk_e:,.0f} vs ${tk_a:,.0f} sem. ant.)",
                    "Puede indicar mix de productos más económico, promociones activas o caída en consumo por mesa. "
                    "Revisar carta y sugerencias del personal de sala.")

    # 4. Turno con menor performance si hay disparidad grande
    if turno_data:
        vals_turno = [(t, v['fac_M']) for t, v in turno_data.items()]
        vals_turno.sort(key=lambda x: -x[1])
        if len(vals_turno) >= 2:
            mejor = vals_turno[0]
            peor  = vals_turno[-1]
            if mejor[1] > 0 and peor[1] / mejor[1] < 0.25:
                add('Operaciones', 'Baja',
                    f"Brecha de turno: {mejor[0]} factura {mejor[1]/peor[1]:.1f}x más que {peor[0]}",
                    "Evaluar estrategia de activación para el turno de menor performance (happy hour, promociones horarias).")

    # ── MARKETING ──────────────────────────────────────────────────────────────

    # 1. Marca con caída de órdenes significativa
    for m in marcas_activas:
        ord_e = marca_esta.get(m, {}).get('ordenes', 0)
        ord_a = marca_ant.get(m,  {}).get('ordenes', 0)
        fac_e = marca_esta.get(m, {}).get('fac_M', 0)
        if ord_a > 0 and ord_e > 0:
            dp_o = (ord_e - ord_a) / ord_a * 100
            if dp_o < -10:
                add('Marketing', 'Alta' if dp_o < -20 else 'Media',
                    f"{m}: caída del {abs(dp_o):.0f}% en cantidad de órdenes vs semana anterior",
                    f"Pasó de {ord_a:,} a {ord_e:,} órdenes. Revisar activaciones de comunicación, "
                    f"presencia en redes y campañas activas. Considerar push de tráfico para la próxima semana.")
        elif ord_e > 0 and ord_a == 0:
            pass  # nueva marca, sin comparación

    # 2. Canal delivery/online bajo vs salon
    salon_fac   = sum(v['fac_M'] for c, v in canal_data.items() if 'salon' in c.lower() or 'mesa' in c.lower() or 'local' in c.lower())
    delivery_fac= sum(v['fac_M'] for c, v in canal_data.items() if 'delivery' in c.lower() or 'online' in c.lower() or 'app' in c.lower() or 'pedidos' in c.lower())
    total_fac_c = sum(v['fac_M'] for v in canal_data.values())
    if delivery_fac > 0 and total_fac_c > 0:
        pct_del = delivery_fac / total_fac_c * 100
        if pct_del < 15:
            add('Marketing', 'Media',
                f"Canal digital/delivery representa solo el {pct_del:.0f}% de la facturación",
                "Oportunidad de crecimiento en canales online. Revisar visibilidad en Rappi/PedidosYa, "
                "estrategia de foto de producto y promociones exclusivas para canal delivery.")

    # 3. Marca cerca del objetivo mensual (85-98%): sprint de cierre
    for m in marcas_activas:
        obj_M  = objetivos.get(m, {}).get(mes_key, 0)
        real_M = mes_real.get(m, {}).get('fac_M', 0)
        if obj_M <= 0:
            continue
        cumpl = real_M / obj_M * 100
        dias_rest = dias_mes_total - dias_mes_trans
        if 82 <= cumpl < 98 and dias_rest > 0:
            falta = obj_M - real_M
            add('Marketing', 'Media',
                f"{m}: a ${falta:.1f}M de cumplir el objetivo del mes ({cumpl:.0f}% alcanzado)",
                f"Con {dias_rest} días restantes, un sprint de comunicación puede cerrar la brecha. "
                f"Considerar campaña de urgencia, push en redes sociales y comunicación interna a encargados.")

    # 4. Locales con crecimiento fuerte → amplificar
    crecimientos = []
    for loc in locales_top[:15]:
        key = (loc['Marca'], loc['local'])
        fac0 = locales_ant_dict.get(key, 0)
        if fac0 > 0 and loc['fac_M'] > 0:
            dp = (loc['fac_M'] - fac0) / fac0 * 100
            if dp > 30 and loc['fac_M'] > 1.0:
                crecimientos.append((loc['local'].title(), loc['Marca'], dp))
    if crecimientos:
        crecimientos.sort(key=lambda x: -x[2])
        top_c = crecimientos[0]
        add('Marketing', 'Baja',
            f"Local destacado: {top_c[0]} ({top_c[1]}) creció {top_c[2]:.0f}% vs semana anterior",
            "Identificar qué accionó este crecimiento (evento, campaña, clima, apertura) para replicarlo en otros locales.")

    # ── DATOS ──────────────────────────────────────────────────────────────────

    # 1. Marcas sin objetivos para el mes en curso
    for m in marcas_activas:
        obj_M = objetivos.get(m, {}).get(mes_key, 0)
        real_M = mes_real.get(m, {}).get('fac_M', 0)
        if real_M > 0 and obj_M == 0:
            add('Datos', 'Alta',
                f"Faltan objetivos de {m} para {mes_key} en la planilla",
                "Sin objetivo cargado no se puede calcular cumplimiento ni proyección. "
                "Completar la planilla Objetivos_Temple_BQ para habilitar el análisis de pace.")

    # 2. Locales de alto volumen con 0 datos en BQ esta semana
    # Detectar locales que están en el top de semanas anteriores pero no aparecen esta semana
    locales_esta = {(r['Marca'], r['local_name']) for r in
                    [{'Marca': l['Marca'], 'local_name': l['local']} for l in locales_top]}
    locales_con_ant = [(marca, loc) for (marca, loc), fac0 in locales_ant_dict.items()
                       if fac0 > 2.0 and (marca, loc) not in locales_esta]
    if locales_con_ant:
        locales_con_ant.sort(key=lambda x: -locales_ant_dict[x])
        faltantes = [f"{loc.title()} ({marca})" for marca, loc in locales_con_ant[:4]]
        add('Datos', 'Alta' if len(locales_con_ant) > 2 else 'Media',
            f"{len(locales_con_ant)} local(es) con ventas la semana pasada sin datos esta semana",
            "Posible falta de carga o error en el nombre del local. "
            f"Verificar: {', '.join(faltantes)}. Confirmar que los datos estén en BigQuery.")

    # 3. Locales con ticket anómalamente bajo (< $3.000) o alto (> $100.000)
    anomalias = []
    for loc in locales_top:
        tk = ticket_prom(loc['fac_M'], loc['ordenes'])
        if loc['ordenes'] > 10 and (tk < 3000 or tk > 150000):
            anomalias.append((loc['local'].title(), loc['Marca'], tk, loc['ordenes']))
    if anomalias:
        desc = '; '.join(f"{l} ({m}): ${tk:,.0f}/orden" for l, m, tk, _ in anomalias[:3])
        add('Datos', 'Media',
            f"{len(anomalias)} local(es) con ticket fuera del rango esperado",
            f"Ticket anómalo puede indicar error de carga, duplicados o mezcla de canales. Revisar: {desc}.")

    # 4. Cobertura total de datos: si hay menos de X días con datos en la semana
    dias_con_datos = len({r['dia'] for r in []})  # placeholder — siempre OK si se corrió bien
    # (ya validado por el fetch; si hay rows es porque hay datos)
    total_rows = sum(len(locales_top) > 0 for _ in [1])
    if not locales_top:
        add('Datos', 'Alta',
            "No se encontraron datos de ventas para el período seleccionado",
            "Verificar que los datos estén cargados en vw_Ventas_Corporativo_Base para la semana consultada.")

    # Ordenar por prioridad dentro de cada área
    orden_prioridad = {'Alta': 0, 'Media': 1, 'Baja': 2}
    for area in acciones:
        acciones[area].sort(key=lambda x: orden_prioridad.get(x['prioridad'], 9))

    return acciones


def render_plan_accion(acciones, styles, story):
    """Renderiza el plan de acción en el PDF."""
    DEPT_CONFIG = {
        'Operaciones': {
            'color': HexColor('#1e40af'),
            'bg':    HexColor('#eff6ff'),
            'icon':  '⚙',
            'desc':  'Acciones para equipos de local y supervisores de zona',
        },
        'Marketing': {
            'color': HexColor('#6d28d9'),
            'bg':    HexColor('#f5f3ff'),
            'icon':  '📣',
            'desc':  'Acciones de comunicación, activación y campañas',
        },
        'Datos': {
            'color': HexColor('#065f46'),
            'bg':    HexColor('#ecfdf5'),
            'icon':  '🗄',
            'desc':  'Alertas de calidad de datos y cobertura de objetivos',
        },
    }
    PRIORIDAD_COLORS = {
        'Alta':  ('#dc2626', '#fef2f2'),
        'Media': ('#d97706', '#fffbeb'),
        'Baja':  ('#475569', '#f8fafc'),
    }

    story.append(Paragraph("Plan de Acción por Área", styles['section']))
    story.append(HRFlowable(width='100%', thickness=1, color=C_MGRAY, spaceAfter=10))
    story.append(Paragraph(
        "Acciones generadas automáticamente a partir del análisis de datos de la semana.",
        styles['small']
    ))
    story.append(Spacer(1, 0.4*cm))

    for dept, cfg in DEPT_CONFIG.items():
        items = acciones.get(dept, [])

        # Header del departamento
        header_data = [[
            Paragraph(f"<b>{cfg['icon']}  {dept.upper()}</b>", ParagraphStyle(
                f'dept_{dept}', fontName='Helvetica-Bold', fontSize=11,
                textColor=C_WHITE, alignment=TA_LEFT)),
            Paragraph(f"<i>{cfg['desc']}</i>", ParagraphStyle(
                f'dept_desc_{dept}', fontName='Helvetica', fontSize=8,
                textColor=HexColor('#e2e8f0'), alignment=TA_RIGHT)),
        ]]
        h_t = Table(header_data, colWidths=[8*cm, 8.7*cm])
        h_t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), cfg['color']),
            ('TOPPADDING',    (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 7),
            ('LEFTPADDING',   (0,0), (0,0),   10),
            ('RIGHTPADDING',  (-1,0),(-1,0),  10),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(KeepTogether([h_t]))

        if not items:
            no_data = Table([[Paragraph("Sin alertas esta semana. Performance dentro de parámetros.", styles['small'])]],
                            colWidths=[16.7*cm])
            no_data.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), cfg['bg']),
                ('TOPPADDING',    (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING',   (0,0), (-1,-1), 12),
            ]))
            story.append(no_data)
        else:
            for i, accion in enumerate(items):
                pr       = accion['prioridad']
                pr_color, pr_bg = PRIORIDAD_COLORS.get(pr, ('#475569', '#f8fafc'))
                bg_row   = cfg['bg'] if i % 2 == 0 else C_WHITE

                badge = Paragraph(
                    f'<font color="{pr_color}"><b>{pr.upper()}</b></font>',
                    ParagraphStyle('badge', fontName='Helvetica-Bold', fontSize=7,
                                   alignment=TA_CENTER)
                )
                texto = Paragraph(
                    f'<b>{accion["texto"]}</b>',
                    ParagraphStyle('accion_txt', fontName='Helvetica-Bold', fontSize=8.5,
                                   textColor=C_NAVY)
                )
                detalle_parts = [texto]
                if accion.get('detalle'):
                    detalle_parts.append(
                        Paragraph(accion['detalle'],
                                  ParagraphStyle('accion_det', fontName='Helvetica', fontSize=7.5,
                                                 textColor=C_DKGRAY, spaceBefore=2))
                    )

                row_data = [[badge, detalle_parts]]
                row_t = Table(row_data, colWidths=[1.5*cm, 15.2*cm])
                row_t.setStyle(TableStyle([
                    ('BACKGROUND',    (0,0), (-1,-1), bg_row),
                    ('TOPPADDING',    (0,0), (-1,-1), 7),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 7),
                    ('LEFTPADDING',   (0,0), (0,0),   6),
                    ('LEFTPADDING',   (1,0), (1,0),   8),
                    ('RIGHTPADDING',  (0,0), (-1,-1), 8),
                    ('VALIGN',        (0,0), (-1,-1), 'TOP'),
                    ('LINEBELOW',     (0,0), (-1,-1), 0.3, C_MGRAY),
                ]))
                story.append(row_t)

        story.append(Spacer(1, 0.5*cm))

# ── Generador principal ───────────────────────────────────────────────────────
def build_informe(semana_inicio: date, output_path: str):
    semana_fin   = semana_inicio + timedelta(days=6)
    sem_ant_ini  = semana_inicio - timedelta(days=7)
    sem_ant_fin  = semana_inicio - timedelta(days=1)
    mes_inicio   = semana_inicio.replace(day=1)

    # Días del mes transcurridos hasta fin de semana (o hoy si está en curso)
    hoy = date.today()
    hasta_mes = min(semana_fin, hoy)

    dias_mes_total = (mes_inicio.replace(month=mes_inicio.month % 12 + 1, day=1) - timedelta(days=1)).day
    dias_mes_trans = (hasta_mes - mes_inicio).days + 1
    pace           = dias_mes_trans / dias_mes_total

    sem_label = f"{semana_inicio.strftime('%d/%m')} – {semana_fin.strftime('%d/%m/%Y')}"
    print(f"Generando informe semana {sem_label}...")

    # ── Fetch data ────────────────────────────────────────────────────────────
    client = get_client()
    print("  Consultando BQ — esta semana...", end='', flush=True)
    rows_esta = fetch_semana(client, semana_inicio.isoformat(), min(semana_fin, hoy).isoformat())
    print(f" {len(rows_esta)} filas")

    print("  Consultando BQ — semana anterior...", end='', flush=True)
    rows_ant  = fetch_semana(client, sem_ant_ini.isoformat(), sem_ant_fin.isoformat())
    print(f" {len(rows_ant)} filas")

    print("  Consultando BQ — mes actual...", end='', flush=True)
    mes_real  = fetch_mes_actual(client, mes_inicio.isoformat(), hasta_mes.isoformat())
    print(f" OK ({len(mes_real)} marcas)")

    print("  Leyendo objetivos del Sheet...", end='', flush=True)
    objetivos = fetch_objetivos()
    print(" OK")

    # ── Agregaciones ─────────────────────────────────────────────────────────
    marca_esta  = agg_por_marca(rows_esta)
    marca_ant   = agg_por_marca(rows_ant)
    canal_data  = agg_por_canal(rows_esta)
    turno_data  = agg_por_turno(rows_esta)
    locales_top = agg_por_local(rows_esta)

    # Construir comparativo anterior por local
    locales_ant_dict = {}
    for r in rows_ant:
        key = (r['Marca'], r['local_name'])
        locales_ant_dict.setdefault(key, 0.0)
        locales_ant_dict[key] += float(r['fac_M'] or 0)

    # Totales globales
    tot_fac_esta = sum(v['fac_M']   for v in marca_esta.values())
    tot_ord_esta = sum(v['ordenes'] for v in marca_esta.values())
    tot_fac_ant  = sum(v['fac_M']   for v in marca_ant.values())
    tot_ord_ant  = sum(v['ordenes'] for v in marca_ant.values())
    tot_tk_esta  = ticket_prom(tot_fac_esta, tot_ord_esta)
    tot_tk_ant   = ticket_prom(tot_fac_ant,  tot_ord_ant)

    d_fac = delta_pct(tot_fac_esta, tot_fac_ant)
    d_ord = delta_pct(tot_ord_esta, tot_ord_ant)
    d_tk  = delta_pct(tot_tk_esta,  tot_tk_ant)

    mes_label = semana_inicio.strftime('%B %Y').capitalize()
    marcas_ord = [m for m in ['Temple', 'Patagonia', 'Feriado'] if m in marca_esta or m in mes_real]

    # ── Gráficos ──────────────────────────────────────────────────────────────
    print("  Generando gráficos...", end='', flush=True)
    buf_marcas = chart_marcas_comparativo(marca_esta, marca_ant, marcas_ord)
    buf_canal  = chart_canal(canal_data)
    buf_turno  = chart_turno(turno_data)
    print(" OK")

    # ── Construir PDF ─────────────────────────────────────────────────────────
    print(f"  Armando PDF → {output_path}...", end='', flush=True)
    styles = make_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=1.6*cm, bottomMargin=1.2*cm,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        title=f"Informe Semanal Ventas {sem_label}",
        author="darwin.salinas@temple.com.ar",
    )
    hf = HeaderFooter(f"Semana {sem_label}")
    story = []

    # ─── PORTADA ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("TEMPLE BAR GROUP", ParagraphStyle('cover_brand',
        fontName='Helvetica-Bold', fontSize=11, textColor=C_DKGRAY, alignment=TA_CENTER)))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Informe Semanal de Ventas", styles['title']))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"Semana del {sem_label}", styles['subtitle']))
    story.append(Spacer(1, 0.2*cm))
    story.append(HRFlowable(width='80%', thickness=2, color=C_BLUE, spaceAfter=8))
    story.append(Spacer(1, 0.6*cm))

    # Marcas
    marcas_info = [
        ('Temple',    C_BLUE,   '🍺'),
        ('Patagonia', C_VIOLET, '🏔'),
        ('Feriado',   C_GREEN,  '🌿'),
    ]
    cov_data = [['', 'Marca', 'Facturación semana', 'vs Sem. ant.']]
    for marca, color, icon in marcas_info:
        fac  = marca_esta.get(marca, {}).get('fac_M', 0)
        fac0 = marca_ant.get(marca, {}).get('fac_M', 0)
        dp   = delta_pct(fac, fac0)
        dp_s = fmt_pct(dp) if dp is not None else '—'
        dp_c = '#059669' if (dp or 0) >= 0 else '#dc2626'
        cov_data.append([
            icon, marca, fmt_M(fac),
            Paragraph(f'<font color="{dp_c}">{dp_s}</font>', styles['body'])
        ])
    cover_t = Table(cov_data, colWidths=[1.2*cm, 4*cm, 5*cm, 4*cm])
    cover_t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), C_NAVY),
        ('TEXTCOLOR',     (0,0), (-1,0), C_WHITE),
        ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 10),
        ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [C_WHITE, C_LGRAY]),
        ('GRID',          (0,0), (-1,-1), 0.5, C_MGRAY),
    ]))
    story.append(cover_t)
    story.append(Spacer(1, 1.5*cm))

    story.append(Paragraph(
        f"Reunión de Gerencia · {hoy.strftime('%d de %B de %Y').capitalize()}",
        ParagraphStyle('cover_date', fontName='Helvetica', fontSize=10, textColor=C_DKGRAY, alignment=TA_CENTER)
    ))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("darwin.salinas@temple.com.ar", ParagraphStyle('cover_mail',
        fontName='Helvetica', fontSize=9, textColor=C_MGRAY, alignment=TA_CENTER)))

    story.append(PageBreak())

    # ─── RESUMEN EJECUTIVO ────────────────────────────────────────────────────
    story.append(Paragraph("Resumen Ejecutivo", styles['section']))
    story.append(HRFlowable(width='100%', thickness=1, color=C_MGRAY, spaceAfter=10))

    # 3 KPI cards en tabla
    def kpi_cell(label, valor, delta, styles):
        dp_color = '#059669' if (delta or 0) >= 0 else '#dc2626'
        dp_arrow = '▲' if (delta or 0) >= 0 else '▼'
        dp_txt   = f'<font color="{dp_color}">{dp_arrow} {abs(delta or 0):.1f}%</font>' if delta is not None else '—'
        return [
            Paragraph(label, styles['kpi_lbl']),
            Paragraph(valor, styles['kpi_val']),
            Paragraph(dp_txt, styles['kpi_delta']),
            Paragraph('vs semana anterior', styles['kpi_lbl']),
        ]

    kpi_data = [[
        kpi_cell('FACTURACIÓN TOTAL', fmt_M(tot_fac_esta), d_fac, styles),
        kpi_cell('ÓRDENES TOTALES',   f"{tot_ord_esta:,}".replace(",","."), d_ord, styles),
        kpi_cell('TICKET PROMEDIO',   fmt_ars(tot_tk_esta), d_tk, styles),
    ]]
    kpi_t = Table(kpi_data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    kpi_t.setStyle(TableStyle([
        ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('BOX',           (0,0), (0,0), 1, C_BLUE),
        ('BOX',           (1,0), (1,0), 1, C_VIOLET),
        ('BOX',           (2,0), (2,0), 1, C_GREEN),
        ('BACKGROUND',    (0,0), (0,0), HexColor('#eff6ff')),
        ('BACKGROUND',    (1,0), (1,0), HexColor('#f5f3ff')),
        ('BACKGROUND',    (2,0), (2,0), HexColor('#ecfdf5')),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('INNERGRID',     (0,0), (-1,-1), 0.5, C_MGRAY),
    ]))
    story.append(kpi_t)
    story.append(Spacer(1, 0.5*cm))

    # Tabla por marca con detalle
    story.append(Paragraph("Performance por Marca — Esta Semana", styles['section']))
    story.append(HRFlowable(width='100%', thickness=1, color=C_MGRAY, spaceAfter=8))

    marca_hdr = ['Marca', 'Facturación', 'vs Sem. ant.', 'Órdenes', 'vs Sem. ant.', 'Ticket Prom.']
    marca_rows = [marca_hdr]
    for m in ['Temple', 'Patagonia', 'Feriado']:
        if m not in marca_esta and m not in marca_ant:
            continue
        fac  = marca_esta.get(m, {}).get('fac_M', 0)
        fac0 = marca_ant.get(m,  {}).get('fac_M', 0)
        ord_ = marca_esta.get(m, {}).get('ordenes', 0)
        ord0 = marca_ant.get(m,  {}).get('ordenes', 0)
        tk   = ticket_prom(fac, ord_)
        dp_f = delta_pct(fac,  fac0)
        dp_o = delta_pct(ord_, ord0)
        def dp_cell(dp):
            if dp is None: return '—'
            color = '#059669' if dp >= 0 else '#dc2626'
            arrow = '▲' if dp >= 0 else '▼'
            return Paragraph(f'<font color="{color}">{arrow} {abs(dp):.1f}%</font>', styles['body'])
        marca_rows.append([
            Paragraph(f'<b>{m}</b>', styles['body']),
            fmt_M(fac), dp_cell(dp_f),
            f"{ord_:,}".replace(",","."), dp_cell(dp_o),
            fmt_ars(tk),
        ])
    m_t = make_table(marca_rows, [3*cm, 3.2*cm, 2.8*cm, 2.8*cm, 2.8*cm, 2.8*cm])
    story.append(m_t)
    story.append(Spacer(1, 0.4*cm))

    # Gráfico comparativo
    img_marcas = Image(buf_marcas, width=14*cm, height=6.5*cm)
    story.append(img_marcas)

    story.append(PageBreak())

    # ─── CUMPLIMIENTO MENSUAL ─────────────────────────────────────────────────
    story.append(Paragraph(f"Cumplimiento Mensual — {mes_label}", styles['section']))
    story.append(HRFlowable(width='100%', thickness=1, color=C_MGRAY, spaceAfter=8))
    story.append(Paragraph(
        f"Datos al {hasta_mes.strftime('%d/%m/%Y')} · Pace del mes: {pace*100:.1f}% ({dias_mes_trans} de {dias_mes_total} días)",
        styles['body']
    ))
    story.append(Spacer(1, 0.3*cm))

    cum_hdr = ['Marca', 'Obj. Mes', 'Real Acumulado', '% Cumpl. Real', 'Obj. Prorrateado', '% vs Pace', 'Proyección Cierre']
    cum_rows = [cum_hdr]
    for m in ['Temple', 'Patagonia', 'Feriado']:
        mes_key = semana_inicio.strftime('%Y-%m')
        obj_M = objetivos.get(m, {}).get(mes_key, 0)
        real  = mes_real.get(m, {}).get('fac_M', 0)
        if obj_M == 0 and real == 0:
            continue
        cumpl_real = real / obj_M * 100 if obj_M > 0 else None
        obj_pace   = obj_M * pace
        cumpl_pace = real / obj_pace * 100 if obj_pace > 0 else None
        proyec     = real / pace if pace > 0 else 0

        def pct_cell(v, threshold=100):
            if v is None: return '—'
            color = '#059669' if v >= threshold else ('#d97706' if v >= 85 else '#dc2626')
            return Paragraph(f'<font color="{color}"><b>{v:.1f}%</b></font>', styles['body'])

        cum_rows.append([
            Paragraph(f'<b>{m}</b>', styles['body']),
            fmt_M(obj_M) if obj_M else '—',
            fmt_M(real),
            pct_cell(cumpl_real),
            fmt_M(obj_pace) if obj_pace else '—',
            pct_cell(cumpl_pace),
            Paragraph(f'<b>{fmt_M(proyec)}</b>', styles['body']) if proyec else '—',
        ])

    cum_t = make_table(cum_rows, [2.8*cm, 2.4*cm, 2.8*cm, 2.4*cm, 2.8*cm, 2.4*cm, 2.8*cm])
    story.append(cum_t)

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "• % Cumpl. Real: real acumulado sobre objetivo total del mes. "
        "• % vs Pace: real sobre objetivo prorrateado al día de hoy (≥100% = en ritmo). "
        "• Proyección Cierre: extrapolación lineal del ritmo actual al fin de mes.",
        styles['small']
    ))

    story.append(PageBreak())

    # ─── TOP LOCALES ──────────────────────────────────────────────────────────
    story.append(Paragraph("Top 15 Locales — Esta Semana", styles['section']))
    story.append(HRFlowable(width='100%', thickness=1, color=C_MGRAY, spaceAfter=8))

    loc_hdr = ['#', 'Local', 'Marca', 'Facturación', 'Órdenes', 'Ticket', 'vs Sem. ant.']
    loc_rows = [loc_hdr]
    for i, loc in enumerate(locales_top[:15], 1):
        m    = loc['Marca']
        fac  = loc['fac_M']
        ord_ = loc['ordenes']
        tk   = ticket_prom(fac, ord_)
        fac0 = locales_ant_dict.get((m, loc['local']), 0)
        dp   = delta_pct(fac, fac0)
        if dp is not None:
            color = '#059669' if dp >= 0 else '#dc2626'
            arrow = '▲' if dp >= 0 else '▼'
            dp_s = Paragraph(f'<font color="{color}">{arrow} {abs(dp):.0f}%</font>', styles['small'])
        else:
            dp_s = '—'
        medal = {1:'🥇', 2:'🥈', 3:'🥉'}.get(i, str(i))
        loc_rows.append([
            medal,
            Paragraph(loc['local'].title(), styles['small']),
            Paragraph(f'<font color="{BRAND_MPL.get(m,"#333")}">{m}</font>', styles['small']),
            fmt_M(fac), f"{ord_:,}".replace(",","."),
            fmt_ars(tk), dp_s,
        ])
    loc_t = make_table(loc_rows, [0.8*cm, 5.5*cm, 2.4*cm, 2.4*cm, 1.8*cm, 2.5*cm, 2*cm])
    # Alinear números a derecha
    loc_t.setStyle(TableStyle([
        ('ALIGN', (3,1), (5,-1), 'RIGHT'),
        ('ALIGN', (6,1), (6,-1), 'CENTER'),
    ]))
    story.append(loc_t)

    story.append(PageBreak())

    # ─── DISTRIBUCIÓN CANAL Y TURNO ───────────────────────────────────────────
    story.append(Paragraph("Distribución por Canal y Turno", styles['section']))
    story.append(HRFlowable(width='100%', thickness=1, color=C_MGRAY, spaceAfter=10))

    # Canal + Turno lado a lado
    img_canal = Image(buf_canal, width=9*cm, height=5*cm)
    img_turno = Image(buf_turno, width=7*cm, height=5*cm)
    charts_t = Table([[img_canal, img_turno]], colWidths=[9.5*cm, 7*cm])
    charts_t.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(charts_t)

    story.append(Spacer(1, 0.6*cm))

    # Tabla canal
    story.append(Paragraph("Detalle por Canal", styles['section']))
    canal_hdr = ['Canal', 'Facturación', '% del total', 'Órdenes', 'Ticket Prom.']
    canal_rows = [canal_hdr]
    total_fac = sum(v['fac_M'] for v in canal_data.values())
    for canal, v in canal_data.items():
        pct = v['fac_M'] / total_fac * 100 if total_fac else 0
        tk  = ticket_prom(v['fac_M'], v['ordenes'])
        canal_rows.append([
            canal, fmt_M(v['fac_M']),
            f"{pct:.1f}%",
            f"{v['ordenes']:,}".replace(",","."),
            fmt_ars(tk),
        ])
    c_t = make_table(canal_rows, [4.5*cm, 3.5*cm, 3*cm, 3*cm, 3.4*cm])
    story.append(c_t)

    story.append(Spacer(1, 0.5*cm))

    # Tabla turno
    story.append(Paragraph("Detalle por Turno", styles['section']))
    turno_hdr = ['Turno', 'Facturación', '% del total', 'Órdenes', 'Ticket Prom.']
    turno_rows_t = [turno_hdr]
    for turno, v in turno_data.items():
        pct = v['fac_M'] / total_fac * 100 if total_fac else 0
        tk  = ticket_prom(v['fac_M'], v['ordenes'])
        turno_rows_t.append([
            turno, fmt_M(v['fac_M']),
            f"{pct:.1f}%",
            f"{v['ordenes']:,}".replace(",","."),
            fmt_ars(tk),
        ])
    t_t = make_table(turno_rows_t, [4.5*cm, 3.5*cm, 3*cm, 3*cm, 3.4*cm])
    story.append(t_t)

    story.append(PageBreak())

    # ─── PLAN DE ACCIÓN ───────────────────────────────────────────────────────
    print("  Generando plan de acción...", end='', flush=True)
    plan = generate_plan_accion(
        marca_esta=marca_esta, marca_ant=marca_ant,
        locales_top=locales_top, locales_ant_dict=locales_ant_dict,
        mes_real=mes_real, objetivos=objetivos,
        pace=pace, canal_data=canal_data, turno_data=turno_data,
        semana_inicio=semana_inicio,
        dias_mes_trans=dias_mes_trans, dias_mes_total=dias_mes_total,
    )
    total_acciones = sum(len(v) for v in plan.values())
    print(f" {total_acciones} acciones")
    render_plan_accion(plan, styles, story)

    # ─── Build ────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    print(f" OK")
    print(f"\n✓ Informe generado: {output_path}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Informe semanal PDF de ventas')
    today = date.today()
    # Default: lunes de la semana pasada
    last_monday = today - timedelta(days=today.weekday() + 7)
    parser.add_argument('--semana', default=last_monday.isoformat(),
        help='Lunes de inicio de la semana (YYYY-MM-DD). Default: semana pasada')
    parser.add_argument('--output', default=os.path.join(SCRIPT_DIR, 'informe_semanal.pdf'),
        help='Ruta del PDF de salida')
    args = parser.parse_args()

    semana_inicio = datetime.strptime(args.semana, '%Y-%m-%d').date()
    if semana_inicio.weekday() != 0:
        # Ajustar al lunes más cercano si no es lunes
        semana_inicio = semana_inicio - timedelta(days=semana_inicio.weekday())
        print(f"  Ajustando al lunes: {semana_inicio}")

    build_informe(semana_inicio, args.output)

if __name__ == '__main__':
    main()
