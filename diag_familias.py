"""
diag_familias.py
Muestra cuántos productos por familia en cada marca para detectar "Sin clasificar".
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
print(f"Período: {desde} → {hasta}\n")

# ── Temple ──────────────────────────────────────────────────────────
client_t = bigquery.Client(project='temple-bar-439715', credentials=creds)
q = f"""
SELECT
  COALESCE(familia_producto, '(NULL)') AS familia,
  COUNT(DISTINCT producto) AS n_productos,
  ROUND(SUM(dinero), 0) AS facturacion
FROM `temple-bar-439715.curated_database.vw_curated_compilado_ok`
WHERE fecha BETWEEN '{desde}' AND '{hasta}'
GROUP BY familia ORDER BY facturacion DESC
"""
print("=== TEMPLE — familia_producto ===")
for r in client_t.query(q).result():
    print(f"  {r.familia:<30} prods:{r.n_productos:>4}  fac:{r.facturacion:>12,.0f}")

# ── Patagonia ────────────────────────────────────────────────────────
client_p = bigquery.Client(project='patagonia-refugios', credentials=creds)
q = f"""
SELECT
  COALESCE(categoria, '(NULL)') AS categoria,
  COUNT(DISTINCT producto) AS n_productos,
  ROUND(SUM(dinero), 0) AS facturacion
FROM `patagonia-refugios.curated_database.curated_mix`
WHERE fecha BETWEEN '{desde}' AND '{hasta}'
GROUP BY categoria ORDER BY facturacion DESC
"""
print("\n=== PATAGONIA — categoria ===")
for r in client_p.query(q).result():
    print(f"  {r.categoria:<30} prods:{r.n_productos:>4}  fac:{r.facturacion:>12,.0f}")

# ── Feriado ──────────────────────────────────────────────────────────
client_f = bigquery.Client(project='feriado-cantina-431720', credentials=creds)
q = f"""
SELECT
  COALESCE(Categor__as_de_Productos_Platos, '(NULL)') AS categoria,
  COUNT(DISTINCT Nombre) AS n_productos,
  ROUND(SUM(Precio_a_Pagar), 0) AS facturacion
FROM `feriado-cantina-431720.Ventas.Compilado`
WHERE Fecha_de_creacion BETWEEN '{desde}' AND '{hasta}'
GROUP BY categoria ORDER BY facturacion DESC
"""
print("\n=== FERIADO — Categorías de Productos/Platos ===")
for r in client_f.query(q).result():
    print(f"  {r.categoria:<30} prods:{r.n_productos:>4}  fac:{r.facturacion:>12,.0f}")
