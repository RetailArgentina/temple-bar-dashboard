#!/usr/bin/env python3
"""
Temple Bar Dashboard Injection - Fresh data from BigQuery (fetched via MCP 2026-04-16)
Uses __PLACEHOLDER__ injection into the dashboard template.
"""
import json
import re
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Helper functions ──────────────────────────────────────────────────────────
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
    result, cur = [], end_mes
    for _ in range(count):
        result.insert(0, cur)
        cur = _prev_month(cur)
    return result

def compute_pd(mensual_rows):
    meses_set = sorted({r["mes"] for r in mensual_rows})
    if not meses_set: return {}
    latest = meses_set[-1]; prev = _prev_month(latest)
    last3 = _months_range(latest, 3); last6 = _months_range(latest, 6)
    ytd = [m for m in meses_set if m[:4] == latest[:4]]
    avail = set(meses_set)
    def fa(lst): return [m for m in lst if m in avail] if lst else None
    return {
        "todo":       {"label":"Todo el periodo","meses":None,"prevMeses":None,"prevLabel":"","yoyMeses":None,"yoyLabel":""},
        "mes_actual": {"label":f"Este mes ({_mes_label(latest)})","meses":[latest],"prevMeses":fa([prev]),
                       "prevLabel":_mes_label(prev),"yoyMeses":fa([_yoy_month(latest)]),"yoyLabel":_mes_label(_yoy_month(latest))},
        "mes_anterior":{"label":f"Mes pasado ({_mes_label(prev)})","meses":fa([prev]),"prevMeses":fa([_prev_month(prev)]),
                        "prevLabel":_mes_label(_prev_month(prev)),"yoyMeses":fa([_yoy_month(prev)]),"yoyLabel":_mes_label(_yoy_month(prev))},
        "ultimos_3m": {"label":"Últimos 3 meses","meses":fa(last3),
                       "prevMeses":fa(_months_range(_prev_month(last3[0]),3)),
                       "prevLabel":f"{_mes_label(_prev_month(last3[0]))}–{_mes_label(prev)}",
                       "yoyMeses":fa([_yoy_month(m) for m in last3]),
                       "yoyLabel":f"{_mes_label(_yoy_month(last3[0]))}–{_mes_label(_yoy_month(latest))}"},
        "ultimos_6m": {"label":"Últimos 6 meses","meses":fa(last6),
                       "prevMeses":fa(_months_range(_prev_month(last6[0]),6)),
                       "prevLabel":f"{_mes_label(_prev_month(last6[0]))}–{_mes_label(prev)}",
                       "yoyMeses":fa([_yoy_month(m) for m in last6]),
                       "yoyLabel":f"{_mes_label(_yoy_month(last6[0]))}–{_mes_label(_yoy_month(latest))}"},
        "ytd":        {"label":f"YTD {latest[:4]}","meses":fa(ytd),
                       "prevMeses":fa([_yoy_month(m) for m in ytd]),
                       "prevLabel":f"YTD {int(latest[:4])-1}",
                       "yoyMeses":fa([_yoy_month(m) for m in ytd]),
                       "yoyLabel":f"YTD {int(latest[:4])-1}"},
    }

def compute_preset_meses(mensual_rows):
    meses_set = sorted({r["mes"] for r in mensual_rows})
    if not meses_set: return {}
    latest = meses_set[-1]; prev = _prev_month(latest)
    last3 = _months_range(latest, 3); last6 = _months_range(latest, 6)
    ytd = [m for m in meses_set if m[:4] == latest[:4]]
    return {
        "todo":        [meses_set[0], latest],
        "mes_actual":  [latest, latest],
        "mes_anterior":[prev, prev],
        "ultimos_3m":  [last3[0], latest],
        "ultimos_6m":  [last6[0], latest],
        "ytd":         [ytd[0] if ytd else latest[:4]+"-01", latest],
    }

def compute_top10(base_rows, latest_mes):
    prev = _prev_month(latest_mes)
    last3 = _months_range(latest_mes, 3); last6 = _months_range(latest_mes, 6)
    periods = {"mes_actual":[latest_mes],"mes_anterior":[prev],"ultimos_3m":last3,"ultimos_6m":last6}
    result = []
    for pk, months in periods.items():
        month_set = set(months); agg = {}
        for r in base_rows:
            if r["mes"] not in month_set: continue
            key = (r["m"], r["l"])
            if key not in agg: agg[key] = {"fac":0,"ord":0,"tot":0.0}
            agg[key]["fac"] += r["fac"]; agg[key]["ord"] += r["ord"]; agg[key]["tot"] += r["tot"]
        for (marca, local), v in sorted(agg.items(), key=lambda x: -x[1]["fac"])[:10]:
            tick = round(v["tot"] / v["ord"]) if v["ord"] > 0 else 0
            result.append({"p":pk,"m":marca,"l":local,"fac":v["fac"],"ord":int(v["ord"]),"tick":tick})
    return result

def parse_bq_rows(result, schema_fields, converters):
    """Parse BigQuery MCP result rows using converters dict {field: fn}."""
    rows = []
    for row in result.get("rows", []):
        vals = row.get("f", [])
        record = {}
        for i, field in enumerate(schema_fields):
            v = vals[i]["v"] if i < len(vals) else None
            if v is not None and field in converters:
                try: v = converters[field](v)
                except: v = None
            record[field] = v
        rows.append(record)
    return rows

def fetch_objetivos_from_sheet():
    """Read objectives from Google Sheet using service account key."""
    SHEET_ID   = "18gkS8YNGVpL0AlfQMemhtT3lOPeRRyORkkTvAoHi-YA"
    SHEET_NAME = "Objetivos_Temple_BQ"
    SA_FILE    = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
    SCOPES     = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                  "https://www.googleapis.com/auth/drive.readonly"]
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds   = service_account.Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result  = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"{SHEET_NAME}!A1:Z2000").execute()
        values  = result.get("values", [])
        if not values:
            print("  Sheet empty — using fallback"); return None
        headers = [h.strip() for h in values[0]]
        hl = {h.lower(): i for i, h in enumerate(headers)}
        idx_marca = next((hl[k] for k in hl if 'marca' in k), None)
        idx_mes   = next((hl[k] for k in hl if k in ('mes','month','periodo','period')), None)
        idx_fac   = hl.get('objetivo_facturacion_bq') or next((hl[k] for k in hl if 'fac' in k), None)
        idx_ord   = hl.get('objetivo_ordenes_bq')     or next((hl[k] for k in hl if 'ord' in k and 'order' not in k), None)
        if any(i is None for i in [idx_marca, idx_mes, idx_fac, idx_ord]):
            print(f"  Column mapping failed — using fallback"); return None
        result_dict = {}
        for row in values[1:]:
            def cell(i):
                try: return row[i].strip() if i < len(row) else ""
                except: return ""
            marca = cell(idx_marca); mes = cell(idx_mes)[:7]
            fac_s = cell(idx_fac).replace(".","").replace(",",".")
            ord_s = cell(idx_ord).replace(".","").replace(",",".")
            if not marca or not mes: continue
            try:
                obj_fac = round(float(fac_s) / 1e6) if fac_s else 0
                obj_ord = round(float(ord_s))         if ord_s else 0
            except ValueError: continue
            if mes not in result_dict.setdefault(marca, {}):
                result_dict[marca][mes] = {"obj_fac": 0, "obj_ord": 0}
            result_dict[marca][mes]["obj_fac"] += obj_fac
            result_dict[marca][mes]["obj_ord"] += obj_ord
        total = sum(len(v) for v in result_dict.values())
        print(f"  OK {total} objectives in {len(result_dict)} marcas")
        return result_dict
    except Exception as e:
        print(f"  WARN Objectives error: {e}"); return None

def fetch_royalties_from_sheet():
    """Read royalties from Google Sheet."""
    SHEET_ID   = "19NIUwq4t-IBiEOG40U3XIiLhgH5ni_6J7Ej3oJOQVEA"
    SHEET_NAME = "Resumen"
    SA_FILE    = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
    SCOPES     = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                  "https://www.googleapis.com/auth/drive.readonly"]
    def parse_ar(s):
        if not s: return 0.0
        s = s.strip().lstrip('$').strip().replace('.','').replace(',','.')
        try: return float(s)
        except: return 0.0
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds   = service_account.Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result  = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"{SHEET_NAME}!A1:J30").execute()
        rows    = result.get("values", [])
        COLS    = {"Temple":(1,2,3),"Patagonia":(4,5,6),"Feriado":(7,8,9)}
        MES_MAP = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
                   "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}
        avg_pct = {}
        if len(rows) > 1:
            ytd = rows[1]
            for marca, (_, _, ci_pct) in COLS.items():
                try: avg_pct[marca] = round(parse_ar(ytd[ci_pct].replace('%','')) if ci_pct < len(ytd) else 0, 2)
                except: avg_pct[marca] = 3.5
        monthly = {m: {} for m in COLS}
        current_year = datetime.now().year
        for row in rows[5:]:
            if not row: continue
            mes_num = MES_MAP.get(row[0].strip().lower() if row else "")
            if not mes_num: continue
            mes_key = f"{current_year}-{mes_num}"
            for marca, (ci_gmv, ci_roy, ci_pct) in COLS.items():
                try:
                    gmv = parse_ar(row[ci_gmv] if ci_gmv < len(row) else "")
                    roy = parse_ar(row[ci_roy] if ci_roy < len(row) else "")
                    pct = parse_ar(row[ci_pct].replace('%','') if ci_pct < len(row) else "")
                    if gmv > 0 or roy > 0:
                        monthly[marca][mes_key] = {"gmv":round(gmv),"roy":round(roy),"pct":round(pct,2)}
                except: continue
        total = sum(len(v) for v in monthly.values())
        print(f"  OK {total} royalty entries · avgPct={avg_pct}")
        return {"monthly": monthly, "avgPct": avg_pct}
    except Exception as e:
        print(f"  WARN Royalties error: {e}"); return None

# ── Fresh data from BigQuery (fetched 2026-04-16) ────────────────────────────
COLORS = {"Noche":"#818cf8","Tarde":"#34d399","N":"#818cf8","T":"#34d399","M":"#fbbf24","X":"#f87171"}

MENSUAL_DATA = [
    {"mes":"2024-05","m":"Feriado","fac":9,"ord":422,"tick":20535},
    {"mes":"2024-06","m":"Feriado","fac":59,"ord":2247,"tick":26345},
    {"mes":"2024-07","m":"Feriado","fac":62,"ord":2155,"tick":28891},
    {"mes":"2024-08","m":"Feriado","fac":63,"ord":2013,"tick":31321},
    {"mes":"2024-09","m":"Feriado","fac":61,"ord":1826,"tick":33600},
    {"mes":"2024-10","m":"Feriado","fac":56,"ord":1684,"tick":33290},
    {"mes":"2024-10","m":"Patagonia","fac":0,"ord":6,"tick":8467},
    {"mes":"2024-10","m":"Temple","fac":2,"ord":55,"tick":29473},
    {"mes":"2024-11","m":"Feriado","fac":46,"ord":1411,"tick":32763},
    {"mes":"2024-11","m":"Patagonia","fac":658,"ord":22945,"tick":28700},
    {"mes":"2024-11","m":"Temple","fac":476,"ord":19164,"tick":25881},
    {"mes":"2024-12","m":"Feriado","fac":67,"ord":1924,"tick":34589},
    {"mes":"2024-12","m":"Patagonia","fac":1506,"ord":42807,"tick":35185},
    {"mes":"2024-12","m":"Temple","fac":831,"ord":27674,"tick":30865},
    {"mes":"2025-01","m":"Feriado","fac":57,"ord":1717,"tick":33366},
    {"mes":"2025-01","m":"Patagonia","fac":1349,"ord":46745,"tick":28869},
    {"mes":"2025-01","m":"Temple","fac":1037,"ord":34316,"tick":30843},
    {"mes":"2025-02","m":"Feriado","fac":48,"ord":1452,"tick":32792},
    {"mes":"2025-02","m":"Patagonia","fac":1435,"ord":43827,"tick":32750},
    {"mes":"2025-02","m":"Temple","fac":1289,"ord":44735,"tick":29625},
    {"mes":"2025-03","m":"Feriado","fac":85,"ord":2719,"tick":31249},
    {"mes":"2025-03","m":"Patagonia","fac":1603,"ord":47064,"tick":34055},
    {"mes":"2025-03","m":"Temple","fac":1504,"ord":52936,"tick":29315},
    {"mes":"2025-04","m":"Feriado","fac":68,"ord":2273,"tick":29954},
    {"mes":"2025-04","m":"Patagonia","fac":1553,"ord":43047,"tick":36082},
    {"mes":"2025-04","m":"Temple","fac":1290,"ord":47316,"tick":28390},
    {"mes":"2025-05","m":"Feriado","fac":68,"ord":2238,"tick":30581},
    {"mes":"2025-05","m":"Patagonia","fac":1983,"ord":51940,"tick":38188},
    {"mes":"2025-05","m":"Temple","fac":1289,"ord":44921,"tick":30362},
    {"mes":"2025-06","m":"Feriado","fac":59,"ord":1875,"tick":31238},
    {"mes":"2025-06","m":"Patagonia","fac":1486,"ord":39080,"tick":38041},
    {"mes":"2025-06","m":"Temple","fac":1102,"ord":37070,"tick":30907},
    {"mes":"2025-07","m":"Feriado","fac":56,"ord":1451,"tick":38355},
    {"mes":"2025-07","m":"Patagonia","fac":1721,"ord":45661,"tick":37691},
    {"mes":"2025-07","m":"Temple","fac":1380,"ord":44845,"tick":31764},
    {"mes":"2025-08","m":"Feriado","fac":49,"ord":1347,"tick":36124},
    {"mes":"2025-08","m":"Patagonia","fac":2079,"ord":55033,"tick":37804},
    {"mes":"2025-08","m":"Temple","fac":1333,"ord":44175,"tick":31405},
    {"mes":"2025-09","m":"Feriado","fac":47,"ord":1182,"tick":39924},
    {"mes":"2025-09","m":"Patagonia","fac":1701,"ord":47477,"tick":35891},
    {"mes":"2025-09","m":"Temple","fac":1191,"ord":38891,"tick":32035},
    {"mes":"2025-10","m":"Feriado","fac":57,"ord":1362,"tick":41780},
    {"mes":"2025-10","m":"Patagonia","fac":1798,"ord":46426,"tick":38845},
    {"mes":"2025-10","m":"Temple","fac":1408,"ord":45395,"tick":32212},
    {"mes":"2025-11","m":"Feriado","fac":55,"ord":1375,"tick":39674},
    {"mes":"2025-11","m":"Patagonia","fac":1783,"ord":44779,"tick":39958},
    {"mes":"2025-11","m":"Temple","fac":1617,"ord":50683,"tick":33114},
    {"mes":"2025-12","m":"Feriado","fac":44,"ord":1023,"tick":43200},
    {"mes":"2025-12","m":"Patagonia","fac":2014,"ord":45789,"tick":44123},
    {"mes":"2025-12","m":"Temple","fac":1583,"ord":43016,"tick":37821},
    {"mes":"2026-01","m":"Feriado","fac":73,"ord":1737,"tick":41833},
    {"mes":"2026-01","m":"Patagonia","fac":2696,"ord":64729,"tick":41788},
    {"mes":"2026-01","m":"Temple","fac":1513,"ord":43593,"tick":35668},
    {"mes":"2026-02","m":"Feriado","fac":59,"ord":1415,"tick":41764},
    {"mes":"2026-02","m":"Patagonia","fac":2328,"ord":53807,"tick":43328},
    {"mes":"2026-02","m":"Temple","fac":1442,"ord":44343,"tick":33491},
    {"mes":"2026-03","m":"Feriado","fac":58,"ord":1430,"tick":40744},
    {"mes":"2026-03","m":"Patagonia","fac":3440,"ord":77692,"tick":44434},
    {"mes":"2026-03","m":"Temple","fac":1460,"ord":44935,"tick":33425},
    {"mes":"2026-04","m":"Feriado","fac":23,"ord":533,"tick":43747},
    {"mes":"2026-04","m":"Patagonia","fac":1477,"ord":36738,"tick":40349},
    {"mes":"2026-04","m":"Temple","fac":671,"ord":19298,"tick":35683},
]

TURNOS_DATA = [
    {"m":"Feriado","t":"Noche","fac":825,"ord":21623,"tick":38161,"color":"#818cf8"},
    {"m":"Feriado","t":"Tarde","fac":504,"ord":17667,"tick":28510,"color":"#34d399"},
    {"m":"Patagonia","t":"N","fac":11510,"ord":215752,"tick":53441,"color":"#818cf8"},
    {"m":"Patagonia","t":"T","fac":10861,"ord":198624,"tick":54779,"color":"#34d399"},
    {"m":"Patagonia","t":"M","fac":7407,"ord":131901,"tick":56253,"color":"#fbbf24"},
    {"m":"Patagonia","t":"X","fac":1348,"ord":51402,"tick":26219,"color":"#f87171"},
    {"m":"Patagonia","t":"3","fac":771,"ord":45410,"tick":16970,"color":"#94a3b8"},
    {"m":"Patagonia","t":"2","fac":492,"ord":15081,"tick":32621,"color":"#94a3b8"},
    {"m":"Patagonia","t":"1","fac":224,"ord":6537,"tick":34321,"color":"#94a3b8"},
    {"m":"Temple","t":"N","fac":10085,"ord":242589,"tick":43387,"color":"#818cf8"},
    {"m":"Temple","t":"T","fac":6698,"ord":173340,"tick":39645,"color":"#34d399"},
    {"m":"Temple","t":"M","fac":5007,"ord":174418,"tick":29571,"color":"#fbbf24"},
    {"m":"Temple","t":"2","fac":306,"ord":8485,"tick":36490,"color":"#94a3b8"},
    {"m":"Temple","t":"3","fac":196,"ord":7525,"tick":27043,"color":"#94a3b8"},
    {"m":"Temple","t":"1","fac":93,"ord":3579,"tick":26709,"color":"#94a3b8"},
    {"m":"Temple","t":"X","fac":32,"ord":911,"tick":35181,"color":"#f87171"},
]

CANAL_DATA = [
    {"mes":"2025-10","m":"Patagonia","c":"SALE_APP","fac":213,"ord":5886},
    {"mes":"2025-10","m":"Patagonia","c":"PEDIDOS_YA","fac":2,"ord":105},
    {"mes":"2025-10","m":"Patagonia","c":"RAPPI","fac":0,"ord":2},
    {"mes":"2025-10","m":"Temple","c":"SALE_APP","fac":634,"ord":18561},
    {"mes":"2025-10","m":"Temple","c":"PEDIDOS_YA","fac":61,"ord":3521},
    {"mes":"2025-10","m":"Temple","c":"DIGITAL","fac":0,"ord":2},
    {"mes":"2025-11","m":"Patagonia","c":"SALE_APP","fac":1762,"ord":43788},
    {"mes":"2025-11","m":"Patagonia","c":"PEDIDOS_YA","fac":21,"ord":1168},
    {"mes":"2025-11","m":"Patagonia","c":"RAPPI","fac":0,"ord":12},
    {"mes":"2025-11","m":"Temple","c":"SALE_APP","fac":1498,"ord":44452},
    {"mes":"2025-11","m":"Temple","c":"PEDIDOS_YA","fac":119,"ord":7092},
    {"mes":"2025-11","m":"Temple","c":"DIGITAL","fac":0,"ord":27},
    {"mes":"2025-12","m":"Patagonia","c":"SALE_APP","fac":1990,"ord":44627},
    {"mes":"2025-12","m":"Patagonia","c":"PEDIDOS_YA","fac":24,"ord":1233},
    {"mes":"2025-12","m":"Patagonia","c":"RAPPI","fac":0,"ord":14},
    {"mes":"2025-12","m":"Temple","c":"SALE_APP","fac":1481,"ord":38485},
    {"mes":"2025-12","m":"Temple","c":"PEDIDOS_YA","fac":102,"ord":5532},
    {"mes":"2025-12","m":"Temple","c":"DIGITAL","fac":0,"ord":15},
    {"mes":"2026-01","m":"Patagonia","c":"SALE_APP","fac":2667,"ord":63257},
    {"mes":"2026-01","m":"Patagonia","c":"PEDIDOS_YA","fac":29,"ord":1530},
    {"mes":"2026-01","m":"Patagonia","c":"RAPPI","fac":0,"ord":18},
    {"mes":"2026-01","m":"Temple","c":"SALE_APP","fac":1415,"ord":38772},
    {"mes":"2026-01","m":"Temple","c":"PEDIDOS_YA","fac":97,"ord":5583},
    {"mes":"2026-01","m":"Temple","c":"DIGITAL","fac":0,"ord":24},
    {"mes":"2026-01","m":"Temple","c":"BOOKING","fac":0,"ord":1},
    {"mes":"2026-02","m":"Patagonia","c":"SALE_APP","fac":2302,"ord":52972},
    {"mes":"2026-02","m":"Patagonia","c":"PEDIDOS_YA","fac":26,"ord":1301},
    {"mes":"2026-02","m":"Patagonia","c":"RAPPI","fac":0,"ord":18},
    {"mes":"2026-02","m":"Temple","c":"SALE_APP","fac":1337,"ord":39252},
    {"mes":"2026-02","m":"Temple","c":"PEDIDOS_YA","fac":104,"ord":5596},
    {"mes":"2026-02","m":"Temple","c":"DIGITAL","fac":0,"ord":39},
    {"mes":"2026-03","m":"Patagonia","c":"SALE_APP","fac":3390,"ord":75389},
    {"mes":"2026-03","m":"Patagonia","c":"PEDIDOS_YA","fac":50,"ord":2685},
    {"mes":"2026-03","m":"Patagonia","c":"RAPPI","fac":0,"ord":16},
    {"mes":"2026-03","m":"Temple","c":"SALE_APP","fac":1354,"ord":39256},
    {"mes":"2026-03","m":"Temple","c":"PEDIDOS_YA","fac":105,"ord":5675},
    {"mes":"2026-03","m":"Temple","c":"DIGITAL","fac":0,"ord":3},
    {"mes":"2026-03","m":"Temple","c":"MUNDO_LINGO","fac":0,"ord":1},
    {"mes":"2026-04","m":"Patagonia","c":"SALE_APP","fac":1455,"ord":35590},
    {"mes":"2026-04","m":"Patagonia","c":"PEDIDOS_YA","fac":22,"ord":1145},
    {"mes":"2026-04","m":"Patagonia","c":"RAPPI","fac":0,"ord":6},
    {"mes":"2026-04","m":"Temple","c":"SALE_APP","fac":624,"ord":16873},
    {"mes":"2026-04","m":"Temple","c":"PEDIDOS_YA","fac":47,"ord":2424},
    {"mes":"2026-04","m":"Temple","c":"MUNDO_LINGO","fac":0,"ord":1},
]

# TOP10_BASE: Load from JSON file saved from MCP result
TOP10_BASE_FILE = os.path.join(SCRIPT_DIR, "top10_base_mcp.json")

def load_top10_base():
    if not os.path.exists(TOP10_BASE_FILE):
        print(f"  WARN: {TOP10_BASE_FILE} not found — TOP10 will be empty")
        return []
    with open(TOP10_BASE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = []
    for row in raw.get("rows", []):
        vals = row.get("f", [])
        try:
            rows.append({
                "mes": vals[0]["v"],
                "m":   vals[1]["v"],
                "l":   vals[2]["v"],
                "fac": int(vals[3]["v"] or 0),
                "ord": int(vals[4]["v"] or 0),
                "tot": float(vals[5]["v"] or 0),
            })
        except Exception: continue
    print(f"  TOP10_BASE loaded: {len(rows)} rows")
    return rows

# ── Main ──────────────────────────────────────────────────────────────────────
print("=== Temple Bar Dashboard Injection 2026-04-16 ===")

top10_base   = load_top10_base()
meses_set    = sorted({r["mes"] for r in MENSUAL_DATA})
latest_mes   = meses_set[-1]
first_mes    = meses_set[0]
top10_data   = compute_top10(top10_base, latest_mes)
pd_data      = compute_pd(MENSUAL_DATA)
preset_meses = compute_preset_meses(MENSUAL_DATA)

print(f"  latest_mes={latest_mes}, first_mes={first_mes}")
print(f"  TOP10 entries={len(top10_data)}, PD periods={len(pd_data)}")

print("Reading objectives from Google Sheet...")
objetivos = fetch_objetivos_from_sheet()
if not objetivos:
    objetivos = {
        "Patagonia": {
            "2026-01": {"obj_fac": 4424, "obj_ord": 117517},
            "2026-02": {"obj_fac": 3713, "obj_ord": 96928},
            "2026-03": {"obj_fac": 3548, "obj_ord": 93122},
        },
        "Temple": {
            "2026-01": {"obj_fac": 1390, "obj_ord": 41187},
            "2026-02": {"obj_fac": 1196, "obj_ord": 35518},
            "2026-03": {"obj_fac": 1620, "obj_ord": 49919},
        }
    }
    print("  Using hardcoded fallback objectives (Jan–Mar 2026)")

print("Reading royalties from Google Sheet...")
royalty_data = fetch_royalties_from_sheet()

LOCALES_OBJ = []

# ── Load and inject template ──────────────────────────────────────────────────
template_path = os.path.join(SCRIPT_DIR, "templates", "dashboard.html")
output_path   = os.path.join(SCRIPT_DIR, "super_dashboard_temple.html")

with open(template_path, "r", encoding="utf-8") as f:
    html = f.read()

print(f"Template loaded: {len(html):,} bytes")

today_str = datetime.now().strftime("%Y-%m-%d")
MESES_ES = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
            7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}

# Try placeholder-based injection first (__MENSUAL_JSON__ etc.)
if '__MENSUAL_JSON__' in html:
    print("  Using placeholder injection...")
    html = html.replace('__MENSUAL_JSON__',      json.dumps(MENSUAL_DATA,  separators=(',',':')))
    html = html.replace('__TURNOS_JSON__',       json.dumps(TURNOS_DATA,   separators=(',',':')))
    html = html.replace('__CANAL_JSON__',        json.dumps(CANAL_DATA,    separators=(',',':')))
    html = html.replace('__TOP10_JSON__',        json.dumps(top10_data,    separators=(',',':')))
    html = html.replace('__PD_JSON__',           json.dumps(pd_data,       separators=(',',':')))
    html = html.replace('__STATE_FROM_MES__',    first_mes)
    html = html.replace('__STATE_TO_MES__',      latest_mes)
    html = html.replace('__PRESET_MESES_JSON__', json.dumps(preset_meses,  separators=(',',':')))
    html = html.replace('__LATEST_MES__',        latest_mes)
    html = html.replace('__SNAPSHOT_DATE__',     today_str)
    if '__OBJETIVOS_JSON__' in html:
        html = html.replace('__OBJETIVOS_JSON__', json.dumps(objetivos, separators=(',',':')))
    if '__ROYALTY_JSON__' in html and royalty_data:
        html = html.replace('__ROYALTY_JSON__', json.dumps(royalty_data, separators=(',',':')))
    if '__LOCALES_OBJ_JSON__' in html:
        html = html.replace('__LOCALES_OBJ_JSON__', json.dumps(LOCALES_OBJ, separators=(',',':')))
    print("  Placeholder injection complete")

# Also try const-replacement approach (for templates with embedded data)
def replace_const(content, var_name, new_value, is_array=True):
    pattern = rf'const\s+{var_name}\s*=\s*' + (r'\[.*?\]' if is_array else r'\{.*?\}') + r'\s*;'
    json_str = json.dumps(new_value, separators=(',',':'), ensure_ascii=False)
    new_content = re.sub(pattern, f'const {var_name} = {json_str};', content, flags=re.DOTALL)
    if new_content != content:
        print(f"  const {var_name} replaced")
    return new_content

html = replace_const(html, "MENSUAL",    MENSUAL_DATA, True)
html = replace_const(html, "TURNOS_DATA",TURNOS_DATA,  True)
html = replace_const(html, "CANAL_DATA", CANAL_DATA,   True)
if top10_data:
    html = replace_const(html, "TOP10",  top10_data,   True)
html = replace_const(html, "OBJETIVOS",  objetivos,    False)
html = replace_const(html, "PD",         pd_data,      False)

# LOCALES_OBJ special pattern
lo_pattern = r'const\s+LOCALES_OBJ\s*=\s*(?:\[.*?\]|__LOCALES_OBJ_JSON__)\s*;'
if re.search(lo_pattern, html, flags=re.DOTALL):
    html = re.sub(lo_pattern, f'const LOCALES_OBJ = {json.dumps(LOCALES_OBJ, separators=(",",":"), ensure_ascii=False)};',
                  html, flags=re.DOTALL)
    print("  const LOCALES_OBJ replaced")

# Update MN / MC month markers
html = re.sub(r'const\s+MN\s*=\s*"[^"]*"', f'const MN = "{first_mes}"',   html)
html = re.sub(r'const\s+MC\s*=\s*"[^"]*"', f'const MC = "{latest_mes}"',  html)

# Update snapshot date comment
html = re.sub(r"BigQuery snapshot \d{4}-\d{2}-\d{2}", f"BigQuery snapshot {today_str}", html)

# Data freshness badge
if '__LAST_DATA_DATE__' in html:
    last_dt_str = f"{latest_mes}-16"  # approximate mid-month
    last_dt = datetime.strptime(last_dt_str, "%Y-%m-%d").date()
    days_stale = (datetime.now().date() - last_dt).days
    last_label = f"16 {MESES_ES[last_dt.month]} {last_dt.year}"
    badge_class = "data-badge-fresh" if days_stale <= 3 else ("data-badge-warn" if days_stale <= 7 else "data-badge-stale")
    stale_label = "actualizado hoy" if days_stale == 0 else (f"hace {days_stale} días")
    html = html.replace('__LAST_DATA_DATE__', last_label)
    html = html.replace('__DAYS_STALE_LABEL__', stale_label)
    html = html.replace('__BADGE_CLASS__', badge_class)
    print(f"  Freshness badge: {last_label} ({stale_label})")

# Insights placeholder (replace with a note)
if '__INSIGHTS_HTML__' in html:
    insights_html = '<div class="ic" style="background:#161b22;border:1px solid #30363d"><div class="it" style="color:#8b949e">ℹ️ Insights generados automáticamente</div><div class="ib">Dashboard actualizado el ' + today_str + ' con datos frescos de BigQuery (vw_Ventas_Corporativo_Base). Datos disponibles hasta ' + latest_mes + '.</div></div>'
    html = html.replace('__INSIGHTS_HTML__', insights_html)
    html = html.replace('__INSIGHTS_DATE__', datetime.now().strftime("%-d %b %Y"))

with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n✅ Dashboard written to: {output_path}")
print(f"   Size: {len(html):,} bytes")
print(f"   Data range: {first_mes} → {latest_mes}")
print(f"   MENSUAL rows: {len(MENSUAL_DATA)}")
print(f"   CANAL rows:   {len(CANAL_DATA)}")
print(f"   TOP10 entries: {len(top10_data)}")
print(f"   Objectives marcas: {len(objetivos)}")
print(f"   Royalties: {'OK' if royalty_data else 'fallback'}")
