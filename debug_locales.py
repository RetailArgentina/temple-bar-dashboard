"""Diagnóstico: compara nombres de locales en BQ vs Google Sheet."""
import os, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from google.cloud import bigquery
from google.oauth2 import service_account
import google.auth
from googleapiclient.discovery import build

SA_FILE = "temple-bar-439715-da51b292ce5d.json"
PROJECT  = "temple-bar-439715"
DATASET  = "Corporativo"
TABLE    = "vw_Ventas_Corporativo_Base"
SHEET_ID = "18gkS8YNGVpL0AlfQMemhtT3lOPeRRyORkkTvAoHi-YA"
SHEET_NAME = "Objetivos_Temple_BQ"

# --- BQ ---
creds_bq = service_account.Credentials.from_service_account_file(SA_FILE)
client = bigquery.Client(project=PROJECT, credentials=creds_bq)

q = f"""
SELECT DISTINCT Marca, UPPER(TRIM(Local)) AS local_name
FROM `{PROJECT}.{DATASET}.{TABLE}`
WHERE EXTRACT(YEAR FROM Fecha) = 2026
  AND Marca IN ('Patagonia','Temple')
ORDER BY Marca, local_name
"""
bq_rows = list(client.query(q).result())
bq_names = {(r.Marca, r.local_name) for r in bq_rows}
print(f"BQ: {len(bq_names)} locales únicos en 2026")
for marca, name in sorted(bq_names):
    print(f"  [{marca[0]}] {name}")

# --- Sheet ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds_sh = service_account.Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
svc = build("sheets", "v4", credentials=creds_sh, cache_discovery=False)
res = svc.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=f"{SHEET_NAME}!A1:Z2000").execute()
values = res.get("values", [])
headers = [h.strip().lower() for h in values[0]]
idx_local = next((i for i,h in enumerate(headers) if h in ('local','establecimiento')), None)
idx_marca = next((i for i,h in enumerate(headers) if 'marca' in h), None)

sheet_names = set()
for row in values[1:]:
    def cell(i):
        try: return row[i].strip() if i < len(row) else ""
        except: return ""
    m = cell(idx_marca)
    l = cell(idx_local).upper().strip()
    if l and ("Patagonia" in m or "Temple" in m):
        b = "P" if "Patagonia" in m else "T"
        marca = "Patagonia" if b == "P" else "Temple"
        sheet_names.add((marca, l))

print(f"\nSheet: {len(sheet_names)} locales únicos")
for marca, name in sorted(sheet_names):
    print(f"  [{marca[0]}] {name}")

# --- Comparación ---
print("\n=== EN SHEET PERO NO EN BQ (sin match -> real=0) ===")
no_match = sheet_names - bq_names
for marca, name in sorted(no_match):
    print(f"  [{marca[0]}] {name}")

print("\n=== EN BQ PERO NO EN SHEET ===")
only_bq = bq_names - sheet_names
for marca, name in sorted(only_bq):
    print(f"  [{marca[0]}] {name}")
