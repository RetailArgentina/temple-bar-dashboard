"""
Contabilium -> BigQuery sync
Uso: PYTHONIOENCODING=utf-8 python contabilium_sync_bq.py [--desde 2020-01-01] [--hasta 2026-12-31] [--modo incremental|full]
"""
import requests, re, uuid, time, argparse
from datetime import datetime, timezone, date
from google.cloud import bigquery
import urllib3
urllib3.disable_warnings()

# ── Config ────────────────────────────────────────────────────────────────────
import os
EMAIL   = os.environ["CONTABILIUM_EMAIL"]
APIKEY  = os.environ["CONTABILIUM_APIKEY"]
BASE    = "https://rest.contabilium.com"
PROJECT = "temple-bar-439715"
DATASET = "Destileria_Contabilium"

BQ  = bigquery.Client(project=PROJECT)
NOW = datetime.now(timezone.utc).isoformat()

TIPOS_VALIDOS = {"FCA", "FCB", "FCC", "FCE", "FCM", "COT",
                 "NCA", "NCB", "NCC", "NCT"}

# ── Auth ──────────────────────────────────────────────────────────────────────
def get_token():
    r = requests.post(f"{BASE}/token", data={
        "grant_type": "client_credentials",
        "client_id": EMAIL, "client_secret": APIKEY
    }, verify=False, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

def api_get(token, path, params=None, timeout=60, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params, verify=False, timeout=timeout)
            return r.json() if r.ok else None
        except requests.exceptions.ConnectionError as e:
            if attempt < retries - 1:
                wait = 20 * (attempt + 1)
                print(f"  [WARN] Connection error (intento {attempt+1}/{retries}), reintentando en {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [ERROR] Connection error después de {retries} intentos: {e}")
                return None

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_ml(nombre):
    n = (nombre or "").upper()
    if re.match(r'^\s*(ECO)?VASO\b', n):
        # vasos/merchandising: el tamaño en el nombre es la capacidad del vaso,
        # no litros de producto vendido (rubro Contabilium 134001, no 133090)
        return None
    ml = None
    for pat, mult in [(r'(\d+)\s*ML\b', 1), (r'(\d+)\s*LTS?\b', 1000), (r'(\d+)\s*LITROS?\b', 1000)]:
        m = re.search(pat, n)
        if m:
            ml = int(m.group(1)) * mult
            break
    if ml is None:
        return None
    m_pack = re.search(r'PACK\s*X\s*(\d+)', n)  # ej. "473 ML (Pack x6)" -> 6 unidades por bulto
    if m_pack:
        ml *= int(m_pack.group(1))
    return ml

def parse_importe(s):
    if s is None: return None
    s = str(s)
    # Formato europeo: "1.500,50" → float 1500.50
    # Formato float nativo: "1500.50" → no tocar el punto decimal
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    return float(s)

def parse_date(s):
    if not s: return None
    return s[:10]

def parse_datetime(s):
    if not s: return None
    return s[:19].replace("T", " ")

# ── Paginado comprobantes ─────────────────────────────────────────────────────
def get_comprobantes_list(token, fecha_desde, fecha_hasta):
    items, page = [], 1
    while True:
        data = api_get(token, "/api/comprobantes/search", {
            "filtro": "", "fechaDesde": fecha_desde,
            "fechaHasta": fecha_hasta, "page": page
        })
        if not data or not data.get("Items"):
            break
        items.extend(data["Items"])
        if len(items) >= data.get("TotalItems", 0):
            break
        page += 1
    return items

# ── BQ insert ─────────────────────────────────────────────────────────────────
def bq_insert(tabla, rows):
    if not rows:
        return
    ref = f"{PROJECT}.{DATASET}.{tabla}"
    errors = BQ.insert_rows_json(ref, rows)
    if errors:
        print(f"  [BQ ERROR] {tabla}: {errors[0]}")

# ── BQ merge (carga por lotes + MERGE, evita duplicados) ───────────────────────
# A diferencia de bq_insert (streaming), esto usa un load job (batch) a una tabla
# temporal + MERGE por clave primaria. Necesario porque las filas de un streaming
# insert quedan en el "streaming buffer" de BQ hasta ~90 min, ventana en la que un
# DELETE/MERGE posterior no las puede tocar — si el sync corre dos veces en ese
# lapso (tarea programada + corrida manual, o solapamiento), el DELETE de COT
# fallaba en silencio y el re-insert duplicaba las filas (incidente 2026-08-25).
def bq_merge(tabla, rows, key_field):
    if not rows:
        return
    import io, json as _json
    tmp_id = f"{PROJECT}.{DATASET}._{tabla}_tmp"
    ndjson = '\n'.join(_json.dumps(r, ensure_ascii=False, default=str) for r in rows)
    existing_schema = BQ.get_table(f"{PROJECT}.{DATASET}.{tabla}").schema
    load_job = BQ.load_table_from_file(
        io.BytesIO(ndjson.encode("utf-8")),
        tmp_id,
        job_config=bigquery.LoadJobConfig(
            schema=existing_schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    load_job.result()  # sincrónico — datos disponibles inmediatamente para MERGE
    cols = [c for c in rows[0].keys() if c != key_field]
    set_clause = ",\n            ".join(f"{c} = S.{c}" for c in cols)
    BQ.query(f"""
        MERGE `{PROJECT}.{DATASET}.{tabla}` T
        USING `{tmp_id}` S ON T.{key_field} = S.{key_field}
        WHEN MATCHED THEN UPDATE SET
            {set_clause}
        WHEN NOT MATCHED THEN INSERT ROW
    """).result()
    BQ.query(f"DROP TABLE IF EXISTS `{tmp_id}`").result()

# ── Sync comprobantes ─────────────────────────────────────────────────────────
def sync(fecha_desde, fecha_hasta, modo="incremental"):
    sync_id = str(uuid.uuid4())[:8]
    t0 = time.time()
    print(f"\n{'='*55}")
    print(f"SYNC {sync_id} | {fecha_desde} a {fecha_hasta} | {modo}")
    print('='*55)

    token = get_token()

    lista = get_comprobantes_list(token, fecha_desde, fecha_hasta)
    lista = [c for c in lista if c.get("TipoFc") in TIPOS_VALIDOS]
    print(f"Comprobantes a procesar: {len(lista)}")

    # En modo incremental, saltar los ya cargados
    ids_existentes = set()
    if modo == "incremental" and lista:
        q = f"""
            SELECT DISTINCT id_comprobante
            FROM `{PROJECT}.{DATASET}.comprobantes`
            WHERE fecha_emision BETWEEN '{fecha_desde}' AND '{fecha_hasta}'
        """
        try:
            ids_existentes = {row.id_comprobante for row in BQ.query(q).result()}
            print(f"Ya en BQ: {len(ids_existentes)} — fetcheando solo los nuevos")
        except Exception as e:
            print(f"  No se pudo consultar BQ: {e}")

    # Los COT (cotizaciones) son mutables en Contabilium: a diferencia de las
    # facturas (con CAE, inmutables), se pueden seguir editando después de
    # creadas — hay que re-sincronizarlas siempre. El borrado de sus líneas
    # viejas en comprobantes_items ocurre más abajo, DESPUÉS de haber
    # re-obtenido cada una con éxito de la API (no antes): si se borrara por
    # adelantado y la API fallaba para alguna, esa cotización quedaba vacía en
    # BQ hasta el próximo sync exitoso — la facturación "retrocedía" y Cerveza
    # Lata (mayoría COT) quedaba en $0 (incidente 2026-08-25).
    ids_cot = {c["Id"] for c in lista if c.get("TipoFc") == "COT"}
    ids_existentes -= ids_cot  # forzar reprocesamiento aunque ya estuvieran en BQ

    rows_comp, rows_items = [], []
    pending_cot_ids = set()  # COT re-obtenidas con éxito en este lote, a borrar-y-reinsertar
    ok = err = 0

    def _flush_pending_cot_deletes():
        nonlocal pending_cot_ids
        if not pending_cot_ids:
            return
        ids_str = ",".join(str(x) for x in pending_cot_ids)
        try:
            BQ.query(f"DELETE FROM `{PROJECT}.{DATASET}.comprobantes_items` WHERE id_comprobante IN ({ids_str})").result()
        except Exception as e:
            print(f"  [WARN] No se pudieron borrar items COT antes de reinsertar: {e}")
        pending_cot_ids = set()

    for i, c in enumerate(lista):
        id_c = c["Id"]
        if id_c in ids_existentes:
            continue

        d = api_get(token, f"/api/comprobantes/{id_c}")
        if not d:
            err += 1
            continue

        tipo    = d.get("TipoFc", "")
        items   = d.get("Items") or []
        if tipo == "COT":
            pending_cot_ids.add(id_c)
        id_cli  = d.get("IdCliente")
        razon   = d.get("RazonSocial") or ""
        fecha_e = parse_date(d.get("FechaEmision"))

        rows_comp.append({
            "id_comprobante":          id_c,
            "numero":                  d.get("Numero"),
            "tipo_fc":                 tipo,
            "modo":                    d.get("Modo"),
            "fecha_emision":           fecha_e,
            "fecha_alta":              parse_datetime(d.get("FechaAlta")),
            "id_cliente":              id_cli,
            "razon_social":            razon,
            "punto_venta":             d.get("PuntoVenta"),
            "id_deposito":             d.get("Inventario"),
            "condicion_venta":         d.get("CondicionVenta"),
            "fecha_vencimiento":       parse_date(d.get("FechaVencimiento")),
            "importe_neto":            parse_importe(d.get("ImporteTotalNeto")),
            "importe_bruto":           parse_importe(d.get("ImporteTotalBruto")),
            "saldo":                   parse_importe(d.get("Saldo")),
            "cae":                     d.get("Cae"),
            "canal":                   d.get("Canal"),
            "observaciones":           (d.get("Observaciones") or "")[:500],
            "ref_externa":             d.get("RefExterna"),
            "id_comprobante_asociado": d.get("IdComprobanteAsociado"),
            "inserted_at":             NOW,
        })

        for it in items:
            nombre   = (it.get("Concepto") or "").strip()
            cantidad = float(it.get("Cantidad") or 0)
            bonif    = float(it.get("Bonificacion") or 0)
            precio   = float(it.get("PrecioUnitario") or 0)
            ml       = parse_ml(nombre)

            rows_items.append({
                "id_item":          it.get("Id"),
                "id_comprobante":   id_c,
                "fecha_emision":    fecha_e,
                "tipo_fc":          tipo,
                "id_cliente":       id_cli,
                "razon_social":     razon,
                "id_concepto":      it.get("IdConcepto"),
                "codigo":           (it.get("Codigo") or "").strip(),
                "concepto":         nombre,
                "tipo_item":        it.get("Tipo"),
                "id_rubro":         it.get("IdRubro"),
                "id_subrubro":      it.get("IdSubRubro"),
                "cantidad":         cantidad,
                "precio_unitario":  precio,
                "bonificacion_pct": bonif,
                "iva_pct":          float(it.get("Iva") or 0),
                "neto_linea":       round(precio * cantidad * (1 - bonif / 100), 2),
                "ml_botella":       ml,
                "litros":           round(cantidad * ml / 1000, 4) if ml else None,
                "inserted_at":      NOW,
            })

        ok += 1
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(lista)}...")
            _flush_pending_cot_deletes()
            bq_merge("comprobantes",       rows_comp,  "id_comprobante")
            bq_merge("comprobantes_items", rows_items, "id_item")
            rows_comp, rows_items = [], []

    _flush_pending_cot_deletes()
    bq_merge("comprobantes",       rows_comp,  "id_comprobante")
    bq_merge("comprobantes_items", rows_items, "id_item")

    dur = round(time.time() - t0, 1)
    print(f"OK: {ok} | Errores: {err} | Tiempo: {dur}s")

    bq_insert("sync_log", [{
        "sync_id":            sync_id,
        "fecha_desde":        fecha_desde,
        "fecha_hasta":        fecha_hasta,
        "comprobantes_total": len(lista),
        "items_insertados":   ok,
        "errores":            err,
        "duracion_seg":       dur,
        "estado":             "OK" if err == 0 else "PARTIAL",
        "created_at":         NOW,
    }])
    return ok

# ── Sync catálogo de productos ────────────────────────────────────────────────
def sync_conceptos():
    print("\nCatalogo de productos...")
    token = get_token()
    rows, page = [], 1
    while True:
        data = api_get(token, "/api/conceptos/search", {"filtro": "", "page": page})
        if not data or not data.get("Items"):
            break
        for c in data["Items"]:
            rows.append({
                "id_concepto":  c.get("Id"),
                "nombre":       c.get("Nombre"),
                "codigo":       c.get("Codigo"),
                "tipo":         c.get("Tipo"),
                "estado":       c.get("Estado"),
                "precio":       float(c.get("Precio") or 0),
                "precio_final": float(c.get("PrecioFinal") or 0),
                "iva_pct":      float(c.get("Iva") or 0),
                "stock":        float(c.get("Stock") or 0),
                "id_rubro":     int(c["IdRubro"]) if c.get("IdRubro") else None,
                "id_subrubro":  int(c["IdSubrubro"]) if c.get("IdSubrubro") else None,
                "ml_botella":   parse_ml(c.get("Nombre") or ""),
                "inserted_at":  NOW,
            })
        if len(rows) >= data.get("TotalItems", 0):
            break
        page += 1
    BQ.query(f"TRUNCATE TABLE `{PROJECT}.{DATASET}.conceptos`").result()
    bq_insert("conceptos", rows)
    print(f"  {len(rows)} productos cargados")

# ── Sync clientes ─────────────────────────────────────────────────────────────
def sync_clientes():
    print("\nClientes...")
    token = get_token()

    # Preservar clusters asignados manualmente antes del TRUNCATE
    clusters = {}
    try:
        res = BQ.query(f"""
            SELECT id_cliente, cluster
            FROM `{PROJECT}.{DATASET}.clientes`
            WHERE cluster IS NOT NULL
        """).result()
        clusters = {row.id_cliente: row.cluster for row in res}
        if clusters:
            print(f"  Preservando {len(clusters)} clusters manuales")
    except Exception as e:
        print(f"  (No se pudieron leer clusters: {e})")

    rows, page = [], 1
    while True:
        data = api_get(token, "/api/clientes/search", {"filtro": "", "page": page})
        if not data or not data.get("Items"):
            break
        for c in data["Items"]:
            rows.append({
                "id_cliente":      c.get("Id"),
                "razon_social":    (c.get("RazonSocial") or "").strip(),
                "nombre_fantasia": (c.get("NombreFantasia") or "").strip(),
                "condicion_iva":   c.get("CondicionIva") or "",
                "tipo_doc":        c.get("TipoDoc") or "",
                "nro_doc":         c.get("NroDoc") or "",
                "email":           c.get("Email") or "",
                "telefono":        c.get("Telefono") or "",
                "provincia":       c.get("Provincia") or "",
                "ciudad":          c.get("Ciudad") or "",
                "domicilio":       c.get("Domicilio") or "",
                "codigo":          str(c.get("Codigo") or ""),
                "cluster":         clusters.get(c.get("Id")),
                "inserted_at":     NOW,
            })
        if len(rows) >= data.get("TotalItems", 0):
            break
        page += 1
    # MERGE atómico: evita ventana donde la tabla queda vacía (vs TRUNCATE+INSERT)
    import io, json as _json
    tmp_id = f"{PROJECT}.{DATASET}._clientes_tmp"
    ndjson  = '\n'.join(_json.dumps(r, ensure_ascii=False, default=str) for r in rows)
    existing_schema = BQ.get_table(f"{PROJECT}.{DATASET}.clientes").schema
    load_job = BQ.load_table_from_file(
        io.BytesIO(ndjson.encode("utf-8")),
        tmp_id,
        job_config=bigquery.LoadJobConfig(
            schema=existing_schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    load_job.result()  # sincrónico — datos disponibles inmediatamente para MERGE
    BQ.query(f"""
        MERGE `{PROJECT}.{DATASET}.clientes` T
        USING `{tmp_id}` S ON T.id_cliente = S.id_cliente
        WHEN MATCHED THEN UPDATE SET
            razon_social    = S.razon_social,
            nombre_fantasia = S.nombre_fantasia,
            condicion_iva   = S.condicion_iva,
            tipo_doc        = S.tipo_doc,
            nro_doc         = S.nro_doc,
            email           = S.email,
            telefono        = S.telefono,
            provincia       = S.provincia,
            ciudad          = S.ciudad,
            domicilio       = S.domicilio,
            codigo          = S.codigo,
            cluster         = COALESCE(T.cluster, S.cluster),
            inserted_at     = S.inserted_at
        WHEN NOT MATCHED THEN INSERT ROW
    """).result()
    BQ.query(f"DROP TABLE IF EXISTS `{tmp_id}`").result()
    print(f"  {len(rows)} clientes sincronizados (MERGE)")

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Contabilium -> BigQuery sync")
    parser.add_argument("--desde", default="2020-01-01", help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--hasta", default=date.today().isoformat(), help="Fecha fin YYYY-MM-DD")
    parser.add_argument("--modo",  default="incremental", choices=["incremental", "full"])
    parser.add_argument("--solo-conceptos", action="store_true")
    args = parser.parse_args()

    if args.solo_conceptos:
        sync_conceptos()
    else:
        sync_conceptos()
        try:
            sync_clientes()
        except Exception as e:
            print(f"  [WARN] sync_clientes falló ({e}) — continuando con comprobantes")
        year_desde = int(args.desde[:4])
        year_hasta = int(args.hasta[:4])
        for y in range(year_desde, year_hasta + 1):
            fd = max(args.desde, f"{y}-01-01")
            fh = min(args.hasta, f"{y}-12-31")
            sync(fd, fh, args.modo)

    print("\nSync completo.")
