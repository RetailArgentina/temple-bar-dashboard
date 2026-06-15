"""
diag_familias2.py
Revisa campos alternativos para clasificar los "Sin clasificar".
"""
from datetime import date
from google.cloud import bigquery
from google.oauth2 import service_account

SA_KEY_FILE = "temple-bar-439715-da51b292ce5d.json"
creds = service_account.Credentials.from_service_account_file(
    SA_KEY_FILE,
    scopes=['https://www.googleapis.com/auth/bigquery',
            'https://www.googleapis.com/auth/cloud-platform']
)

desde = date.today().replace(day=1).isoformat()
hasta = date.today().isoformat()

# ── Patagonia: qué tiene `tipo` cuando categoria es NULL ──────────────
client_p = bigquery.Client(project='patagonia-refugios', credentials=creds)
q = f"""
SELECT
  COALESCE(tipo, '(NULL)') AS tipo,
  COUNT(DISTINCT producto) AS n_productos,
  ROUND(SUM(dinero), 0) AS facturacion
FROM `patagonia-refugios.curated_database.curated_mix`
WHERE fecha BETWEEN '{desde}' AND '{hasta}'
  AND categoria IS NULL
GROUP BY tipo ORDER BY facturacion DESC
LIMIT 30
"""
print("=== PATAGONIA — campo `tipo` cuando categoria es NULL ===")
for r in client_p.query(q).result():
    print(f"  {r.tipo:<30} prods:{r.n_productos:>4}  fac:{r.facturacion:>12,.0f}")

# ── Temple: campos disponibles para los Sin clasificar ────────────────
client_t = bigquery.Client(project='temple-bar-439715', credentials=creds)
q = f"""
SELECT
  COALESCE(mix, '(NULL)') AS mix,
  COALESCE(estilo, '(NULL)') AS estilo,
  COUNT(DISTINCT producto) AS n_productos,
  ROUND(SUM(dinero), 0) AS facturacion
FROM `temple-bar-439715.curated_database.vw_curated_compilado_ok`
WHERE fecha BETWEEN '{desde}' AND '{hasta}'
  AND (familia_producto IS NULL OR familia_producto = 'Sin clasificar')
GROUP BY mix, estilo ORDER BY facturacion DESC
LIMIT 30
"""
print("\n=== TEMPLE — mix/estilo cuando familia_producto es Sin clasificar ===")
for r in client_t.query(q).result():
    print(f"  mix:{r.mix:<20} estilo:{r.estilo:<20} prods:{r.n_productos:>4}  fac:{r.facturacion:>12,.0f}")
