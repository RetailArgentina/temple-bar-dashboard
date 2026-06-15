#!/usr/bin/env python3
"""
Inject fresh data from BigQuery into the Temple Bar dashboard template.
Replaces JavaScript constants with new data.
"""

import json
import re
from datetime import datetime

# Helper functions for date manipulation (same as actualizar_dashboard.py)
def _prev_month(mes):
    y, m = int(mes[:4]), int(mes[5:])
    return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"

def _yoy_month(mes):
    y, m = int(mes[:4]), int(mes[5:])
    return f"{y-1}-{m:02d}"

def _mes_label(mes):
    MESES = {"01":"Ene","02":"Feb","03":"Mar","04":"Abr","05":"May","06":"Jun",
             "07":"Jul","08":"Ago","09":"Sep","10":"Oct","11":"Nov","12":"Dic"}
    y, m = mes[:4], mes[5:]
    return f"{MESES[m]} {y[2:]}"

def _months_range(end_mes, count):
    """Lista de `count` meses consecutivos terminando en end_mes."""
    result, cur = [], end_mes
    for _ in range(count):
        result.insert(0, cur)
        cur = _prev_month(cur)
    return result

def compute_pd(mensual_rows):
    """Construye el objeto PD con etiquetas y rangos de meses dinámicos."""
    meses_set = sorted({r["mes"] for r in mensual_rows})
    if not meses_set:
        return {}
    latest = meses_set[-1]
    prev   = _prev_month(latest)
    last3  = _months_range(latest, 3)
    last6  = _months_range(latest, 6)
    ytd    = [m for m in meses_set if m[:4] == latest[:4]]
    avail  = set(meses_set)

    def fa(lst): return [m for m in lst if m in avail] if lst else None

    return {
        "todo":         {"label": "Todo el periodo", "meses": None, "prevMeses": None,
                         "prevLabel": "", "yoyMeses": None, "yoyLabel": ""},
        "mes_actual":   {"label": f"Este mes ({_mes_label(latest)})",
                         "meses": [latest], "prevMeses": fa([prev]),
                         "prevLabel": _mes_label(prev),
                         "yoyMeses": fa([_yoy_month(latest)]),
                         "yoyLabel": _mes_label(_yoy_month(latest))},
        "mes_anterior": {"label": f"Mes pasado ({_mes_label(prev)})",
                         "meses": fa([prev]), "prevMeses": fa([_prev_month(prev)]),
                         "prevLabel": _mes_label(_prev_month(prev)),
                         "yoyMeses": fa([_yoy_month(prev)]),
                         "yoyLabel": _mes_label(_yoy_month(prev))},
        "ultimos_3m":   {"label": "Últimos 3 meses",
                         "meses": fa(last3),
                         "prevMeses": fa(_months_range(_prev_month(last3[0]), 3)),
                         "prevLabel": f"{_mes_label(_prev_month(last3[0]))}–{_mes_label(prev)}",
                         "yoyMeses": fa([_yoy_month(m) for m in last3]),
                         "yoyLabel": f"{_mes_label(_yoy_month(last3[0]))}–{_mes_label(_yoy_month(latest))}"},
        "ultimos_6m":   {"label": "Últimos 6 meses",
                         "meses": fa(last6),
                         "prevMeses": fa(_months_range(_prev_month(last6[0]), 6)),
                         "prevLabel": f"{_mes_label(_prev_month(last6[0]))}–{_mes_label(prev)}",
                         "yoyMeses": fa([_yoy_month(m) for m in last6]),
                         "yoyLabel": f"{_mes_label(_yoy_month(last6[0]))}–{_mes_label(_yoy_month(latest))}"},
        "ytd":          {"label": f"YTD {latest[:4]}",
                         "meses": fa(ytd),
                         "prevMeses": fa([_yoy_month(m) for m in ytd]),
                         "prevLabel": f"YTD {int(latest[:4])-1}",
                         "yoyMeses": fa([_yoy_month(m) for m in ytd]),
                         "yoyLabel": f"YTD {int(latest[:4])-1}"},
    }

# Fresh data from the task
MENSUAL_DATA = [{"mes":"2023-12","m":"Patagonia","fac":761,"ord":52433,"tick":14523},{"mes":"2024-01","m":"Patagonia","fac":1541,"ord":101378,"tick":15202},{"mes":"2024-02","m":"Patagonia","fac":1476,"ord":87442,"tick":16880},{"mes":"2024-03","m":"Patagonia","fac":1610,"ord":87253,"tick":18463},{"mes":"2024-04","m":"Patagonia","fac":1272,"ord":62000,"tick":20530},{"mes":"2024-05","m":"Feriado","fac":9,"ord":422,"tick":20535},{"mes":"2024-05","m":"Patagonia","fac":1113,"ord":50172,"tick":22202},{"mes":"2024-06","m":"Feriado","fac":59,"ord":2247,"tick":26345},{"mes":"2024-06","m":"Patagonia","fac":1522,"ord":67290,"tick":22624},{"mes":"2024-07","m":"Feriado","fac":62,"ord":2155,"tick":28891},{"mes":"2024-07","m":"Patagonia","fac":1750,"ord":63701,"tick":27486},{"mes":"2024-08","m":"Feriado","fac":63,"ord":2013,"tick":31321},{"mes":"2024-08","m":"Patagonia","fac":1776,"ord":66303,"tick":26794},{"mes":"2024-09","m":"Feriado","fac":61,"ord":1826,"tick":33600},{"mes":"2024-09","m":"Patagonia","fac":2003,"ord":73455,"tick":27288},{"mes":"2024-10","m":"Feriado","fac":56,"ord":1684,"tick":33290},{"mes":"2024-10","m":"Patagonia","fac":2294,"ord":79632,"tick":28829},{"mes":"2024-10","m":"Temple","fac":2,"ord":55,"tick":29473},{"mes":"2024-11","m":"Feriado","fac":46,"ord":1411,"tick":32763},{"mes":"2024-11","m":"Patagonia","fac":2717,"ord":88895,"tick":30574},{"mes":"2024-11","m":"Temple","fac":476,"ord":19164,"tick":25881},{"mes":"2024-12","m":"Feriado","fac":67,"ord":1924,"tick":34589},{"mes":"2024-12","m":"Patagonia","fac":3448,"ord":111787,"tick":30863},{"mes":"2024-12","m":"Temple","fac":831,"ord":27674,"tick":30865},{"mes":"2025-01","m":"Feriado","fac":57,"ord":1717,"tick":33366},{"mes":"2025-01","m":"Patagonia","fac":3536,"ord":120475,"tick":29356},{"mes":"2025-01","m":"Temple","fac":1037,"ord":34316,"tick":30843},{"mes":"2025-02","m":"Feriado","fac":48,"ord":1452,"tick":32792},{"mes":"2025-02","m":"Patagonia","fac":2730,"ord":94421,"tick":28924},{"mes":"2025-02","m":"Temple","fac":1289,"ord":44735,"tick":29625},{"mes":"2025-03","m":"Feriado","fac":85,"ord":2719,"tick":31249},{"mes":"2025-03","m":"Patagonia","fac":2811,"ord":71853,"tick":39134},{"mes":"2025-03","m":"Temple","fac":1504,"ord":52936,"tick":29315},{"mes":"2025-04","m":"Feriado","fac":68,"ord":2273,"tick":29954},{"mes":"2025-04","m":"Patagonia","fac":2018,"ord":54366,"tick":37120},{"mes":"2025-04","m":"Temple","fac":1290,"ord":47316,"tick":28390},{"mes":"2025-05","m":"Feriado","fac":68,"ord":2238,"tick":30581},{"mes":"2025-05","m":"Patagonia","fac":1989,"ord":52140,"tick":38156},{"mes":"2025-05","m":"Temple","fac":1289,"ord":44921,"tick":30362},{"mes":"2025-06","m":"Feriado","fac":59,"ord":1875,"tick":31238},{"mes":"2025-06","m":"Patagonia","fac":1675,"ord":44068,"tick":38025},{"mes":"2025-06","m":"Temple","fac":1102,"ord":37070,"tick":30907},{"mes":"2025-07","m":"Feriado","fac":56,"ord":1451,"tick":38355},{"mes":"2025-07","m":"Patagonia","fac":2694,"ord":66118,"tick":40758},{"mes":"2025-07","m":"Temple","fac":1380,"ord":44845,"tick":31764},{"mes":"2025-08","m":"Feriado","fac":49,"ord":1347,"tick":36124},{"mes":"2025-08","m":"Patagonia","fac":2750,"ord":71665,"tick":38395},{"mes":"2025-08","m":"Temple","fac":1333,"ord":44175,"tick":31405},{"mes":"2025-09","m":"Feriado","fac":47,"ord":1182,"tick":39924},{"mes":"2025-09","m":"Patagonia","fac":2657,"ord":70219,"tick":37916},{"mes":"2025-09","m":"Temple","fac":1191,"ord":38891,"tick":32035},{"mes":"2025-10","m":"Feriado","fac":57,"ord":1362,"tick":41780},{"mes":"2025-10","m":"Patagonia","fac":3076,"ord":75144,"tick":41063},{"mes":"2025-10","m":"Temple","fac":1408,"ord":45395,"tick":32212},{"mes":"2025-11","m":"Feriado","fac":55,"ord":1375,"tick":39674},{"mes":"2025-11","m":"Patagonia","fac":3527,"ord":81915,"tick":43201},{"mes":"2025-11","m":"Temple","fac":1617,"ord":50683,"tick":33114},{"mes":"2025-12","m":"Feriado","fac":44,"ord":1023,"tick":43200},{"mes":"2025-12","m":"Patagonia","fac":2967,"ord":63488,"tick":46877},{"mes":"2025-12","m":"Temple","fac":1583,"ord":43016,"tick":37821},{"mes":"2026-01","m":"Feriado","fac":73,"ord":1737,"tick":41833},{"mes":"2026-01","m":"Patagonia","fac":4567,"ord":102772,"tick":44572},{"mes":"2026-01","m":"Temple","fac":1513,"ord":43593,"tick":35668},{"mes":"2026-02","m":"Feriado","fac":59,"ord":1415,"tick":41764},{"mes":"2026-02","m":"Patagonia","fac":3701,"ord":83360,"tick":44455},{"mes":"2026-02","m":"Temple","fac":1442,"ord":44343,"tick":33491},{"mes":"2026-03","m":"Feriado","fac":58,"ord":1430,"tick":40744},{"mes":"2026-03","m":"Patagonia","fac":3436,"ord":77557,"tick":44454},{"mes":"2026-03","m":"Temple","fac":1460,"ord":44935,"tick":33425},{"mes":"2026-04","m":"Feriado","fac":23,"ord":533,"tick":43747},{"mes":"2026-04","m":"Patagonia","fac":1368,"ord":34319,"tick":39972},{"mes":"2026-04","m":"Temple","fac":671,"ord":19298,"tick":35683}]

TURNOS_DATA = [{"m":"Feriado","t":"Noche","fac":825,"ord":21623,"tick":38161,"color":"#818cf8"},{"m":"Feriado","t":"Tarde","fac":504,"ord":17667,"tick":28510,"color":"#34d399"},{"m":"Patagonia","t":"T","fac":27427,"ord":902963,"tick":30416,"color":"#34d399"},{"m":"Patagonia","t":"N","fac":26314,"ord":786539,"tick":33490,"color":"#818cf8"},{"m":"Patagonia","t":"M","fac":14813,"ord":383769,"tick":38656,"color":"#fbbf24"},{"m":"Patagonia","t":"X","fac":1611,"ord":56232,"tick":28649,"color":"#f87171"},{"m":"Patagonia","t":"3","fac":602,"ord":28278,"tick":21281,"color":"#94a3b8"},{"m":"Patagonia","t":"2","fac":345,"ord":10129,"tick":34080,"color":"#94a3b8"},{"m":"Patagonia","t":"1","fac":204,"ord":5811,"tick":35045,"color":"#94a3b8"},{"m":"Patagonia","t":"S","fac":0,"ord":5,"tick":57340,"color":"#94a3b8"},{"m":"Temple","t":"N","fac":10085,"ord":242589,"tick":43387,"color":"#818cf8"},{"m":"Temple","t":"T","fac":6698,"ord":173340,"tick":39645,"color":"#34d399"},{"m":"Temple","t":"M","fac":5007,"ord":174418,"tick":29571,"color":"#fbbf24"},{"m":"Temple","t":"2","fac":306,"ord":8485,"tick":36490,"color":"#94a3b8"},{"m":"Temple","t":"3","fac":196,"ord":7525,"tick":27043,"color":"#94a3b8"},{"m":"Temple","t":"1","fac":93,"ord":3579,"tick":26709,"color":"#94a3b8"},{"m":"Temple","t":"X","fac":32,"ord":911,"tick":35181,"color":"#f87171"}]

CANAL_DATA = [{"mes":"2025-10","m":"Patagonia","c":"sale_app","fac":1475,"ord":37386},{"mes":"2025-10","m":"Patagonia","c":"pedidos_ya","fac":17,"ord":904},{"mes":"2025-10","m":"Patagonia","c":"rappi","fac":0,"ord":8},{"mes":"2025-10","m":"Temple","c":"SALE_APP","fac":634,"ord":18561},{"mes":"2025-10","m":"Temple","c":"PEDIDOS_YA","fac":61,"ord":3521},{"mes":"2025-10","m":"Temple","c":"DIGITAL","fac":0,"ord":2},{"mes":"2025-11","m":"Patagonia","c":"sale_app","fac":3488,"ord":80334},{"mes":"2025-11","m":"Patagonia","c":"pedidos_ya","fac":39,"ord":2103},{"mes":"2025-11","m":"Patagonia","c":"rappi","fac":1,"ord":23},{"mes":"2025-11","m":"Temple","c":"SALE_APP","fac":1498,"ord":44452},{"mes":"2025-11","m":"Temple","c":"PEDIDOS_YA","fac":119,"ord":7092},{"mes":"2025-11","m":"Temple","c":"DIGITAL","fac":0,"ord":27},{"mes":"2025-12","m":"Patagonia","c":"sale_app","fac":2934,"ord":61982},{"mes":"2025-12","m":"Patagonia","c":"pedidos_ya","fac":33,"ord":1707},{"mes":"2025-12","m":"Patagonia","c":"rappi","fac":0,"ord":19},{"mes":"2025-12","m":"Temple","c":"SALE_APP","fac":1481,"ord":38485},{"mes":"2025-12","m":"Temple","c":"PEDIDOS_YA","fac":102,"ord":5532},{"mes":"2025-12","m":"Temple","c":"DIGITAL","fac":0,"ord":15},{"mes":"2026-01","m":"Patagonia","c":"sale_app","fac":4517,"ord":100827},{"mes":"2026-01","m":"Patagonia","c":"pedidos_ya","fac":49,"ord":2572},{"mes":"2026-01","m":"Patagonia","c":"rappi","fac":1,"ord":36},{"mes":"2026-01","m":"Temple","c":"SALE_APP","fac":1415,"ord":38772},{"mes":"2026-01","m":"Temple","c":"PEDIDOS_YA","fac":97,"ord":5583},{"mes":"2026-01","m":"Temple","c":"DIGITAL","fac":0,"ord":24},{"mes":"2026-01","m":"Temple","c":"BOOKING","fac":0,"ord":1},{"mes":"2026-02","m":"Patagonia","c":"sale_app","fac":3659,"ord":82016},{"mes":"2026-02","m":"Patagonia","c":"pedidos_ya","fac":42,"ord":2069},{"mes":"2026-02","m":"Patagonia","c":"rappi","fac":0,"ord":20},{"mes":"2026-02","m":"Temple","c":"SALE_APP","fac":1337,"ord":39252},{"mes":"2026-02","m":"Temple","c":"PEDIDOS_YA","fac":104,"ord":5596},{"mes":"2026-02","m":"Temple","c":"DIGITAL","fac":0,"ord":39},{"mes":"2026-03","m":"Patagonia","c":"sale_app","fac":3385,"ord":75254},{"mes":"2026-03","m":"Patagonia","c":"pedidos_ya","fac":50,"ord":2688},{"mes":"2026-03","m":"Patagonia","c":"rappi","fac":0,"ord":16},{"mes":"2026-03","m":"Temple","c":"SALE_APP","fac":1354,"ord":39256},{"mes":"2026-03","m":"Temple","c":"PEDIDOS_YA","fac":105,"ord":5675},{"mes":"2026-03","m":"Temple","c":"DIGITAL","fac":0,"ord":3},{"mes":"2026-03","m":"Temple","c":"MUNDO_LINGO","fac":0,"ord":1},{"mes":"2026-04","m":"Patagonia","c":"sale_app","fac":1349,"ord":33357},{"mes":"2026-04","m":"Patagonia","c":"pedidos_ya","fac":19,"ord":959},{"mes":"2026-04","m":"Patagonia","c":"rappi","fac":0,"ord":6},{"mes":"2026-04","m":"Temple","c":"SALE_APP","fac":624,"ord":16873},{"mes":"2026-04","m":"Temple","c":"PEDIDOS_YA","fac":47,"ord":2424},{"mes":"2026-04","m":"Temple","c":"MUNDO_LINGO","fac":0,"ord":1}]

OBJETIVOS = {"Patagonia":{"2026-01":{"obj_fac":4424,"obj_ord":117517},"2026-02":{"obj_fac":3713,"obj_ord":96928},"2026-03":{"obj_fac":3548,"obj_ord":93122}},"Temple":{"2026-01":{"obj_fac":1390,"obj_ord":41187},"2026-02":{"obj_fac":1196,"obj_ord":35518},"2026-03":{"obj_fac":1620,"obj_ord":49919}}}

LOCALES_OBJ = []

# Compute PD from MENSUAL_DATA
pd_obj = compute_pd(MENSUAL_DATA)

# Extract first and last months
meses_set = sorted({r["mes"] for r in MENSUAL_DATA})
first_month = meses_set[0]
latest_month = meses_set[-1]

# Read the template
template_path = "/sessions/nice-magical-carson/mnt/Claude_Cowork/templates/dashboard.html"
with open(template_path, "r", encoding="utf-8") as f:
    html_content = f.read()

print(f"Template size before: {len(html_content):,} bytes")

# Function to safely replace const assignments
def replace_const(content, var_name, new_value, is_array=True):
    """Replace const VAR_NAME = [...] or {...} ; with new value."""
    if is_array:
        pattern = rf'const\s+{var_name}\s*=\s*\[.*?\];'
    else:
        pattern = rf'const\s+{var_name}\s*=\s*\{{.*?\}};'

    json_str = json.dumps(new_value, separators=(',', ':'), ensure_ascii=False)
    replacement = f"const {var_name} = {json_str};"

    return re.sub(pattern, replacement, content, flags=re.DOTALL)

# Replace each constant
print("Replacing constants:")

html_content = replace_const(html_content, "MENSUAL", MENSUAL_DATA, is_array=True)
print("  - MENSUAL")

html_content = replace_const(html_content, "TURNOS_DATA", TURNOS_DATA, is_array=True)
print("  - TURNOS_DATA")

html_content = replace_const(html_content, "CANAL_DATA", CANAL_DATA, is_array=True)
print("  - CANAL_DATA")

html_content = replace_const(html_content, "OBJETIVOS", OBJETIVOS, is_array=False)
print("  - OBJETIVOS")

# Handle LOCALES_OBJ - it might have a placeholder
html_content = re.sub(
    r'const\s+LOCALES_OBJ\s*=\s*(?:\[.*?\]|__LOCALES_OBJ_JSON__);',
    f'const LOCALES_OBJ = {json.dumps(LOCALES_OBJ, separators=(",", ":"), ensure_ascii=False)};',
    html_content,
    flags=re.DOTALL
)
print("  - LOCALES_OBJ")

html_content = replace_const(html_content, "PD", pd_obj, is_array=False)
print("  - PD")

# Replace month string constants
# const MN = "..."; -> "2023-12" (first month)
html_content = re.sub(
    r'const\s+MN\s*=\s*"[^"]*"',
    f'const MN = "{first_month}"',
    html_content
)
print(f"  - MN -> {first_month}")

# const MC = "..."; -> "2026-04" (latest month)
html_content = re.sub(
    r'const\s+MC\s*=\s*"[^"]*"',
    f'const MC = "{latest_month}"',
    html_content
)
print(f"  - MC -> {latest_month}")

# Update snapshot comment if present
today_str = datetime.now().strftime("%Y-%m-%d")
html_content = re.sub(
    r"BigQuery snapshot \d{4}-\d{2}-\d{2}",
    f"BigQuery snapshot {today_str}",
    html_content
)
print(f"  - Updated snapshot date to {today_str}")

# Write the result
output_path = "/sessions/nice-magical-carson/mnt/Claude_Cowork/super_dashboard_temple.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\nTemplate size after: {len(html_content):,} bytes")
print(f"\nOutput written to: {output_path}")
print(f"Latest date in data: {latest_month}")
print(f"First date in data: {first_month}")
print(f"Total rows in MENSUAL: {len(MENSUAL_DATA)}")
print(f"Total rows in CANAL_DATA: {len(CANAL_DATA)}")
print(f"\nUpdate complete!")
