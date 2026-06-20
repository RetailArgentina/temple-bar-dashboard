#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_destileria_dashboard.py
Genera destileria_dashboard.html con datos de:
  temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final

Uso local:
  python -X utf8 generar_destileria_dashboard.py

Uso Cloud Run (sube automáticamente a GCS):
  python3 generar_destileria_dashboard.py \
      --output /tmp/destileria_dashboard.html \
      --gcs-bucket temple-bar-dashboard-cache
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
import google.auth
from google.cloud import bigquery

PROJECT   = "temple-brewery"
TABLE     = "temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE  = os.path.join(SCRIPT_DIR, "templates", "destileria.html")
OUTPUT_DEFAULT  = os.path.join(SCRIPT_DIR, "destileria_dashboard.html")
OBJ_JSON_FILE   = os.path.join(SCRIPT_DIR, "objetivos_destileria.json")

SHEET_OBJ_ID = os.environ.get("DEST_OBJ_DRIVE_ID", "1curY4eZKp6WZ_r2p8W9sglsdY3UUzirx")
OBJ_GCS_BLOB = "objetivos_destileria.json"   # cache persistente en GCS

SA_KEY = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")

GCP_SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Mapa: nombre de producto en el Sheet (MAYÚSCULAS) → familia de classify_familia
PRODUCT_FAMILIA_MAP = {
    "GIN BOSQUE ALTA MONTAÑA BOTELLA 500 ML":          "bosque_alta_montana",
    "GIN BOSQUE ALTA MONTAÑA BOTELLA 750 ML":          "bosque_alta_montana",
    "GIN BOSQUE ALTA MONTAÑA MINIATURA BOTELLA 50 ML": "bosque_alta_montana_mini",
    "GIN BOSQUE ALTA MONTANA BOTELLA 500 ML":          "bosque_alta_montana",
    "GIN BOSQUE ALTA MONTANA BOTELLA 750 ML":          "bosque_alta_montana",
    "GIN BOSQUE ALTA MONTANA MINIATURA BOTELLA 50 ML": "bosque_alta_montana_mini",
    "GIN BOSQUE NATIVO BOTELLA 500 ML":                "bosque_nativo",
    "GIN BOSQUE NATIVO BOTELLA 750 ML":                "bosque_nativo",
    "GIN BOSQUE NATIVO MINIATURA BOTELLA 50 ML":       "bosque_nativo_mini",
    "GIN BOSQUE REFUGIOS BOTELLA 500 ML":              "bosque_refugios",
    "GIN BOSQUE REFUGIOS BOTELLA 750 ML":              "bosque_refugios",
    "VERMU FERIADO ROJO 750 ML":                       "feriado_rojo",
    "VERMÚ FERIADO ROJO 750 ML":                       "feriado_rojo",
    "VERMU FERIADO ROJO BARRIL 20 LTS":                "feriado_barril_20",
    "VERMU FERIADO ROJO BARRIL 20 LT":                 "feriado_barril_20",
    "VERMU FERIADO ROJO BARRIL 20 L":                  "feriado_barril_20",
    "VERMU FERIADO ROSADO 750 ML":                     "feriado_rosado",
    "VERMÚ FERIADO ROSADO 750 ML":                     "feriado_rosado",
    "WOLF IPA":                                        "lata_wolf",
    "WOLF IPA (LATA)":                                 "lata_wolf",
    "SCOTTISH":                                        "lata_scottish",
    "SCOTTISH (LATA)":                                 "lata_scottish",
    "WOLF IPA 0%":                                     "lata_wolf0",
    "WOLF IPA 0% ALC":                                 "lata_wolf0",
    "WOLF IPA 0% (LATA)":                              "lata_wolf0",
    "INDIE GOLDEN":                                    "lata_golden",
    "INDIE GOLDEN (LATA)":                             "lata_golden",
    "GOLDEN LAGER MUNDIAL":                            "lata_golden",
    "FLOW APA (LATA)":                                 "lata_otras",
    "BLACK SOUL STOUT (LATA)":                         "lata_otras",
    "COSMICA (LATA)":                                  "lata_otras",
}

SKIP_CLUSTER_PATTERNS = ["OBJ TOTAL", "BXQ", "SUPERMERCADOS"]


# ---------------------------------------------------------------------------
# GCS upload
# ---------------------------------------------------------------------------

def upload_to_gcs(local_path, bucket_name, blob_name="destileria_dashboard.html", html_content=None):
    """Sube el HTML generado a GCS con cache-control adecuado."""
    from google.cloud import storage
    print(f"\nUploading to GCS: gs://{bucket_name}/{blob_name} ...")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    if html_content is not None:
        # Upload directo desde memoria — evita race condition con Drive Sync
        content_bytes = html_content.encode("utf-8")
        file_size = len(content_bytes)
        if file_size < 1024:
            raise RuntimeError(f"HTML demasiado pequeño ({file_size} bytes) — posible archivo corrupto, abortando upload")
        blob.upload_from_string(content_bytes, content_type="text/html; charset=utf-8")
    else:
        file_size = os.path.getsize(local_path)
        if file_size < 1024:
            raise RuntimeError(f"HTML demasiado pequeño ({file_size} bytes) — posible archivo corrupto, abortando upload")
        blob.upload_from_filename(local_path, content_type="text/html; charset=utf-8")
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    blob.reload()
    if blob.cache_control != "no-cache, no-store, must-revalidate":
        print(f"  WARN: cache_control no aplicado correctamente (valor: {blob.cache_control})", file=__import__('sys').stderr)
    public_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
    print(f"  OK: {public_url} ({file_size // 1024} KB)")
    return public_url


# ---------------------------------------------------------------------------
# Firestore — objetivos (fuente primaria)
# ---------------------------------------------------------------------------

def load_objectives_from_firestore(db):
    """
    Carga objetivos desde la colección 'objetivos_destileria' en Firestore.
    Cada documento tiene la forma:
        {marca, dimension, nombre, valores: [12 ints], updated_at, updated_by}
    Devuelve dict {marca: {dimension: {nombre: [12 valores]}}} o {} si vacío/error.
    """
    try:
        result = {}
        docs = list(db.collection("objetivos_destileria").stream())
        if not docs:
            return {}
        for doc in docs:
            d = doc.to_dict()
            marca     = d.get("marca")
            dimension = d.get("dimension")
            nombre    = d.get("nombre")
            valores   = d.get("valores")
            if not (marca and dimension and nombre and isinstance(valores, list) and len(valores) == 12):
                print(
                    f"WARN: Firestore doc '{doc.id}' ignorado — campos incompletos o valores inválidos",
                    file=__import__('sys').stderr,
                )
                continue
            result.setdefault(marca, {}).setdefault(dimension, {})[nombre] = valores
        return result
    except Exception as _fs_err:
        print(f"WARN: Firestore objetivos falló: {_fs_err}", file=__import__('sys').stderr)
        return {}


# ---------------------------------------------------------------------------
# GCS cache de objetivos (persiste entre runs de Cloud Run)
# ---------------------------------------------------------------------------

def save_objectives_to_gcs(obj_data, bucket_name, blob_name=OBJ_GCS_BLOB):
    """Guarda el JSON de objetivos en GCS como backup persistente entre runs."""
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    content = json.dumps(obj_data, ensure_ascii=False, indent=2)
    blob.upload_from_string(content.encode("utf-8"), content_type="application/json; charset=utf-8")
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    print(f"  OK: objetivos guardados en gs://{bucket_name}/{blob_name}")


def load_objectives_from_gcs(bucket_name, blob_name=OBJ_GCS_BLOB):
    """Carga el JSON de objetivos desde GCS. Lanza excepción si no existe."""
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    content = blob.download_as_text(encoding="utf-8")
    return json.loads(content)


# ---------------------------------------------------------------------------
# Clasificación de productos
# ---------------------------------------------------------------------------

def classify_familia(producto, envase):
    """Devuelve la familia del producto para agrupar en el dashboard."""
    p = str(producto or "").upper()
    e = str(envase  or "").upper()

    # Barriles (Feriado) — detectar por envase primero, distinguir tamaño
    if "BARRIL" in e:
        if "50" in e or "50" in p: return "feriado_barril_50"
        return "feriado_barril_20"

    # Bosque — miniaturas antes que los genéricos
    if "BOSQUE NATIVO"   in p and "MINI" in p: return "bosque_nativo_mini"
    if "BOSQUE" in p and "ALTA MONTA" in p and "MINI" in p: return "bosque_alta_montana_mini"

    # Bosque
    if "BOSQUE NATIVO"       in p: return "bosque_nativo"
    if "BOSQUE ALTA MONTA"   in p: return "bosque_alta_montana"
    if "BOSQUE REFUGIOS"     in p: return "bosque_refugios"
    if "GIN RIDER"           in p: return "bosque_otro"
    if re.search(r'\bGIN\b', p): return "bosque_otro"  # palabra completa — evita falso positivo con "GINEBRA"

    # Feriado
    if "FERIADO ROSADO"      in p: return "feriado_rosado"
    if "FERIADO ROJO"        in p: return "feriado_rojo"
    if "VERMU"               in p: return "feriado_rojo"
    if "VERM\u00da"          in p: return "feriado_rojo"

    # Cervezas en lata — detectar por envase
    if "LATA" in e:
        if "WOLF IPA" in p and "0%" in p:           return "lata_wolf0"
        if "WOLF IPA" in p:                          return "lata_wolf"
        if "SCOTTISH" in p:                          return "lata_scottish"
        if "GOLDEN" in p or "INDIE" in p:            return "lata_golden"
        if "APA" in p or "IPL" in p or "IPA" in p:  return "lata_otras"
        return "lata_otras"

    # Todo lo demás → Merch (botellas de terceros, complementarios, etc.)
    return "merch"


# ---------------------------------------------------------------------------
# Objetivos — parsing Google Sheets
# ---------------------------------------------------------------------------

def parse_obj_num(s):
    """Parsea número del Sheet.
    - '1,500' o '1.500' (miles europeo, exactamente 3 decimales) → 1500
    - '29,43' (decimal con coma) → 29
    - '1775.114372' o '1499.5' (float decimal) → redondeado al entero más cercano
    """
    s = str(s).strip().replace("\xa0", "").replace("$", "").replace(" ", "")
    if not s or s in ("-", "—"):
        return 0
    # Coma decimal: "29,43" (1-3 dígitos + coma + 1-2 decimales)
    if re.match(r"^\d{1,3},\d{1,2}$", s):
        return round(float(s.replace(",", ".")))
    # Miles europeo con punto: "3.274" o "1.500" (≤3 dígitos antes, exactamente 3 después)
    # Si el resultado supera 50.000 es un decimal mal interpretado (ej: "328.545" → 329 L)
    if re.match(r"^\d{1,3}\.\d{3}$", s):
        as_european = int(s.replace(".", ""))
        if as_european > 50_000:
            return round(float(s))
        return as_european
    # Float decimal o entero: "1775.114372", "1499.5", "2349.0", "1882"
    try:
        return round(float(s.replace(",", "")))
    except Exception:
        return 0


def _month_cols(header_row):
    """Lista de 12 índices de columna (0-based) para ene–dic."""
    mmap = {
        "enero": 0, "ene": 0, "feb": 1, "febrero": 1, "mar": 2, "marzo": 2,
        "abr": 3, "abril": 3, "may": 4, "mayo": 4, "jun": 5, "junio": 5,
        "jul": 6, "julio": 6, "ago": 7, "agosto": 7,
        "sep": 8, "sept": 8, "septiembre": 8,
        "oct": 9, "octubre": 9, "nov": 10, "noviembre": 10,
        "dic": 11, "diciembre": 11,
    }
    found = {}
    for i, c in enumerate(header_row):
        k = str(c).strip().lower()
        if k in mmap and mmap[k] not in found:
            found[mmap[k]] = i
    return [found.get(m, -1) for m in range(12)]


def _is_header(row):
    """True si la fila contiene ≥4 nombres de meses."""
    mkeys = {"enero","feb","febrero","mar","marzo","abr","abril","may","mayo",
             "jun","junio","jul","julio","ago","agosto","sep","sept","oct","nov","dic"}
    return sum(1 for c in row if str(c).strip().lower() in mkeys) >= 4


def _detect_brand(row):
    """Detecta marcador de sección. Devuelve 'feriado' | 'cerveza' | None.
    Solo activa si la primera celda es corta (≤20 chars), para no confundir
    nombres de productos (ej: 'VERMU FERIADO ROJO 750 ML') con encabezados."""
    if not row:
        return None
    first = str(row[0]).strip()
    if len(first) > 20:
        return None
    txt = " ".join(str(c) for c in row[:4]).upper()
    if "FERIADO" in txt and "GIN" not in txt and "BOSQUE" not in txt:
        return "feriado"
    if "CERVEZA" in txt:
        return "cerveza"
    return None


def _norm(s):
    """Normaliza string para comparar sin tildes."""
    return (s.upper()
              .replace("Á", "A").replace("É", "E").replace("Í", "I")
              .replace("Ó", "O").replace("Ú", "U").replace("Ñ", "N"))


def _merge(dest, key, vals):
    """Agrega vals a dest[key] (suma si ya existe)."""
    dest[key] = [dest[key][m] + vals[m] for m in range(12)] if key in dest else vals


def _parse_product_sheet(rows, result):
    """Parsea hoja 1 (objetivos por etiqueta/producto)."""
    brand, month_cols, seen = "bosque", None, set()
    for row in rows:
        if not row:
            continue
        nb = _detect_brand(row)
        if nb:
            brand, month_cols, seen = nb, None, set()
            continue
        if _is_header(row):
            month_cols = _month_cols(row)
            continue
        if month_cols is None:
            continue
        name = _norm(str(row[0]).strip())
        if not name:
            continue
        if "VENTAS TOTALES" in name:
            key = "_TOTAL"
        else:
            key = PRODUCT_FAMILIA_MAP.get(name)
            if key is None:
                for pn, pk in PRODUCT_FAMILIA_MAP.items():
                    if _norm(pn) == name:
                        key = pk
                        break
        if key is None:
            continue
        sk = (brand, key)
        if sk in seen:       # skip segundo bloque "sensibilizado"
            continue
        seen.add(sk)
        vals = [parse_obj_num(row[ci]) if ci >= 0 and ci < len(row) else 0
                for ci in month_cols]
        _merge(result[brand]["product"], key, vals)


def _parse_cluster_sheet(rows, result):
    """Parsea hoja 2 (objetivos por cluster)."""
    brand, month_cols, seen = "bosque", None, set()
    for row in rows:
        if not row:
            continue
        nb = _detect_brand(row)
        if nb:
            brand, month_cols, seen = nb, None, set()
            continue
        if _is_header(row):
            month_cols = _month_cols(row)
            continue
        if month_cols is None:
            continue
        name = str(row[0]).strip()
        if not name:
            continue
        nu = name.upper()
        if "VENTAS TOTALES" in nu:
            key = "_TOTAL"
        else:
            if any(p in nu for p in SKIP_CLUSTER_PATTERNS):
                continue
            first = str(row[1]).strip() if len(row) > 1 else ""
            if first == "-":
                continue
            key = name
        sk = (brand, key)
        if sk in seen:
            continue
        seen.add(sk)
        vals = [parse_obj_num(row[ci]) if ci >= 0 and ci < len(row) else 0
                for ci in month_cols]
        if key != "_TOTAL" and not any(v > 0 for v in vals):
            continue
        _merge(result[brand]["cluster"], key, vals)


def fetch_objectives(creds):
    """
    Descarga el archivo Excel de objetivos desde Google Drive y lo parsea.
    Funciona con archivos .xlsx (no nativos de Google Sheets).
    Devuelve dict: {brand: {"product": {...}, "cluster": {...}}}
    Cada valor es lista de 12 ints (ene–dic).
    """
    import io
    import openpyxl
    import googleapiclient.discovery as disc
    from googleapiclient.http import MediaIoBaseDownload

    # Intentar SA key primero (tiene scope drive), luego ADC como fallback
    _drive_creds_list = []
    if os.path.exists(SA_KEY):
        from google.oauth2 import service_account as _sa
        _drive_creds_list.append(("SA key", _sa.Credentials.from_service_account_file(
            SA_KEY, scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )))
    _drive_creds_list.append(("ADC", creds))
    drive_svc = None
    for _label, _dc in _drive_creds_list:
        try:
            _svc = disc.build("drive", "v3", credentials=_dc, cache_discovery=False)
            _svc.files().get(fileId=SHEET_OBJ_ID, fields="id").execute()
            drive_svc = _svc
            print(f"  Drive auth OK ({_label})")
            break
        except Exception as _auth_err:
            print(f"  Drive auth fallida con {_label}: {_auth_err!r}")
    if drive_svc is None:
        raise RuntimeError("No se pudo autenticar con Drive (ni SA key ni ADC)")

    print(f"  Descargando Excel (ID: {SHEET_OBJ_ID})...")
    for _attempt in range(1, 4):
        try:
            request = drive_svc.files().get_media(fileId=SHEET_OBJ_ID)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            break
        except Exception as _dl_err:
            if _attempt == 3:
                raise
            import time as _time
            print(f"  Intento {_attempt} fallido ({_dl_err!r}), reintentando...", file=__import__('sys').stderr)
            _time.sleep(5)

    wb = openpyxl.load_workbook(fh, data_only=True)
    names = wb.sheetnames
    PRODUCT_SHEET = "Rolling - Mensual x Etiqueta"
    CLUSTER_SHEET = "Rolling - Mensual x Cluster"
    if PRODUCT_SHEET not in names or CLUSTER_SHEET not in names:
        raise ValueError(f"Hojas esperadas no encontradas. Disponibles: {names}")
    t1 = PRODUCT_SHEET
    t2 = CLUSTER_SHEET
    print(f"  Hoja productos: {t1}")
    print(f"  Hoja clusters:  {t2}")

    def sheet_to_rows(sheet_name):
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([str(c) if c is not None else "" for c in row])
        return rows

    result = {b: {"product": {}, "cluster": {}} for b in ("bosque", "feriado", "cerveza")}
    _parse_product_sheet(sheet_to_rows(t1), result)
    if t2:
        _parse_cluster_sheet(sheet_to_rows(t2), result)

    # Cerveza: objetivos en latas (473 ml c/u) → convertir a litros para comparar con BQ
    L_POR_LATA = 0.473
    for section in ("product", "cluster"):
        for key, arr in result["cerveza"][section].items():
            result["cerveza"][section][key] = [round(v * L_POR_LATA, 1) for v in arr]

    return result


# ---------------------------------------------------------------------------
# Validación de objetivos
# ---------------------------------------------------------------------------

# Rangos razonables de litros mensuales por marca (mínimo, máximo)
_OBJ_RANGES = {
    "bosque":  (200,   6_000),
    "feriado": (200,   5_000),
    "cerveza": (500,  30_000),   # objetivos en litros (convertidos desde latas × 0.473)
}
# Clusters que deben estar sí o sí
_OBJ_MIN_CLUSTERS = {
    "bosque":  {"Cadena Grupo Temple", "Distribuidor"},
    "feriado": {"Cadena Grupo Temple", "Distribuidor"},
    "cerveza": {"Grupo Temple", "Distribuidores"},   # nombres actuales en el Excel
}
# Productos que deben estar sí o sí (cerveza no tiene breakdown obligatorio)
_OBJ_MIN_PRODUCTS = {
    "bosque":  {"bosque_nativo", "bosque_alta_montana"},
    "feriado": {"feriado_rojo",  "feriado_rosado"},
    "cerveza": set(),
}
_OBJ_CHANGE_THRESHOLD = 0.25   # >25% de cambio vs caché anterior = advertencia


def validate_objectives(obj, prev_obj=None):
    """
    Valida estructura y valores de objetivos.
    Retorna (errores: list[str], advertencias: list[str]).
    Errores = datos inválidos/faltantes.
    Advertencias = cambios grandes vs caché anterior (puede ser legítimo).
    """
    errors, warns = [], []
    for brand in ("bosque", "feriado", "cerveza"):
        b = obj.get(brand, {})
        lo, hi = _OBJ_RANGES[brand]

        total = (b.get("cluster", {}).get("_TOTAL")
                 or b.get("product", {}).get("_TOTAL"))
        if not total:
            errors.append(f"[{brand}] _TOTAL ausente — parsing probablemente falló")
            continue
        if len(total) != 12:
            errors.append(f"[{brand}] _TOTAL tiene {len(total)} valores (esperados 12)")

        # Ceros en los primeros 6 meses (período con datos completos)
        zeros = [i + 1 for i, v in enumerate(total[:6]) if v == 0]
        if zeros:
            errors.append(f"[{brand}] _TOTAL con ceros en meses {zeros}")

        # Valores fuera de rango razonable
        for i, v in enumerate(total):
            if v > 0 and not (lo <= v <= hi):
                errors.append(
                    f"[{brand}] mes {i+1} = {v:,.0f} L fuera del rango [{lo:,}–{hi:,}]"
                )

        # Clusters mínimos (comparación case-insensitive + strip)
        cl_keys = set(b.get("cluster", {}).keys()) - {"_TOTAL"}
        cl_keys_norm = {k.strip().lower() for k in cl_keys}
        for exp in _OBJ_MIN_CLUSTERS.get(brand, set()):
            if exp.strip().lower() not in cl_keys_norm:
                errors.append(f"[{brand}] cluster obligatorio faltante: '{exp}' (disponibles: {sorted(cl_keys)})")

        # Productos mínimos
        prod_keys = set(b.get("product", {}).keys()) - {"_TOTAL"}
        for exp in _OBJ_MIN_PRODUCTS.get(brand, set()):
            if exp not in prod_keys:
                errors.append(f"[{brand}] producto obligatorio faltante: '{exp}'")

        # Cambio grande vs caché anterior
        if prev_obj:
            prev_b = prev_obj.get(brand, {})
            prev_total = (prev_b.get("cluster", {}).get("_TOTAL")
                          or prev_b.get("product", {}).get("_TOTAL"))
            if prev_total:
                for i in range(min(len(total), len(prev_total))):
                    pv, nv = prev_total[i], total[i]
                    if pv > 0 and abs(nv - pv) / pv > _OBJ_CHANGE_THRESHOLD:
                        warns.append(
                            f"[{brand}] mes {i+1}: {pv:,.0f} → {nv:,.0f} L "
                            f"({(nv - pv) / pv * 100:+.1f}%) — verificar si es cambio intencional"
                        )
    return errors, warns


# ---------------------------------------------------------------------------
# Fetch BQ
# ---------------------------------------------------------------------------

def fetch_rows(client):
    query = f"""
    WITH base AS (
      -- Deduplica filas idénticas ignorando Clusterizacion (que puede ser NULL en algunas copias)
      SELECT DISTINCT
        FechaPedido, NombreDeFantasia, GrupoCliente,
        Producto, Envase, Tipo, CantEnvases, Litros, Total_
      FROM `{TABLE}`
      WHERE FechaPedido IS NOT NULL
    ),
    cl_latest AS (
      -- Cluster más reciente no-null por cliente
      SELECT DISTINCT NombreDeFantasia, Clusterizacion
      FROM `{TABLE}`
      WHERE Clusterizacion IS NOT NULL
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY NombreDeFantasia ORDER BY FechaPedido DESC
      ) = 1
    )
    SELECT
      FORMAT_DATE('%Y-%m-%d', b.FechaPedido)              AS f,
      COALESCE(c.Clusterizacion, 'Sin clasificar')         AS cl,
      COALESCE(b.NombreDeFantasia, 'Sin nombre')           AS nd,
      COALESCE(b.GrupoCliente, '')                         AS gc,
      COALESCE(b.Producto, '')                             AS pr,
      COALESCE(b.Envase, '')                               AS en,
      COALESCE(b.Tipo, '')                                 AS ti,
      COALESCE(b.CantEnvases, 0)                           AS ce,
      ROUND(COALESCE(b.Litros,  0.0), 3)                   AS li,
      ROUND(COALESCE(b.Total_,  0.0), 0)                   AS to_
    FROM base b
    LEFT JOIN cl_latest c ON b.NombreDeFantasia = c.NombreDeFantasia
    ORDER BY b.FechaPedido
    """
    return list(client.query(query).result(timeout=120))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generar Destilería Dashboard")
    parser.add_argument("--output",     default=OUTPUT_DEFAULT,
                        help="Ruta del HTML generado")
    parser.add_argument("--gcs-bucket", default="",
                        help="Bucket GCS destino (opcional)")
    args = parser.parse_args()

    ts = lambda: datetime.now().strftime("%H:%M:%S")

    print(f"[{ts()}] Autenticando con Google (BQ + Sheets)...")
    creds, _ = google.auth.default(scopes=GCP_SCOPES)

    print(f"[{ts()}] Conectando a BigQuery (proyecto: {PROJECT})...")
    client = bigquery.Client(project=PROJECT, credentials=creds)

    print(f"[{ts()}] Consultando datos...")
    raw = fetch_rows(client)
    print(f"[{ts()}] {len(raw):,} filas obtenidas")
    if len(raw) < 100:
        raise RuntimeError(f"BQ devolvió solo {len(raw)} filas — posible error de datos, abortando")

    # Construir array compacto para el frontend
    data = []
    for r in raw:
        data.append({
            "f":  r.f,
            "cl": r.cl,
            "nd": r.nd,
            "fa": classify_familia(r.pr, r.en),
            "ti": r.ti,
            "ce": int(r.ce),
            "li": float(r.li),
            "to": float(r.to_),
        })

    now_str   = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    # Leer plantilla e inyectar
    if not os.path.exists(TEMPLATE):
        print(f"ERROR: No se encontro la plantilla: {TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    with open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()

    # ── Validación estructural crítica ───────────────────────────────────────
    # Estas secciones NO deben modificarse. Si el template pierde alguna (ej:
    # Google Drive sync baja una versión vieja), el pipeline aborta antes de
    # publicar un dashboard roto.
    _CRITICAL_CHECKS = [
        (
            'data-tab="feriado-semanas"',
            "Tab Semanas de Feriado (botón de navegación)",
        ),
        (
            'id="view-feriado-semanas"',
            "Vista Feriado Semanas (#view-feriado-semanas)",
        ),
        (
            'id="bosque-obj-panel"',
            "Panel de objetivos Bosque (#bosque-obj-panel)",
        ),
        (
            'id="bosque-retention-panel"',
            "Panel retención Bosque (#bosque-retention-panel)",
        ),
        (
            'data-tab="bosque-sellinout"',
            "Tab Sell In/Out Bosque (botón de navegación)",
        ),
        (
            'id="view-bosque-sellinout"',
            "Vista Sell In/Out Bosque (#view-bosque-sellinout)",
        ),
        (
            '__SELLINOUT_LOCAL_JSON__',
            "Placeholder sell-in/out por local (__SELLINOUT_LOCAL_JSON__)",
        ),
        (
            '__SELLINOUT_LOCAL_WK_JSON__',
            "Placeholder sell-in/out local × semana (__SELLINOUT_LOCAL_WK_JSON__)",
        ),
        (
            '__SELLINOUT_PAT_JSON__',
            "Placeholder sell-in/out Patagonia semanal (__SELLINOUT_PAT_JSON__)",
        ),
        (
            '__SELLINOUT_PAT_LOCAL_WK_JSON__',
            "Placeholder sell-in/out Patagonia local × semana (__SELLINOUT_PAT_LOCAL_WK_JSON__)",
        ),
        (
            '__PERMISSIONS_INJECT__',
            "Placeholder inyección de permisos y link Admin (__PERMISSIONS_INJECT__)",
        ),
    ]
    _tpl_errors = []
    for pattern, label in _CRITICAL_CHECKS:
        if pattern not in template:
            _tpl_errors.append(f"  ✗ FALTA: {label}  →  buscar: {pattern!r}")
    # Verificar orden: objetivos ANTES que retención en Bosque General
    _idx_obj = template.find('id="bosque-obj-panel"')
    _idx_ret = template.find('id="bosque-retention-panel"')
    if _idx_obj != -1 and _idx_ret != -1 and _idx_obj > _idx_ret:
        _tpl_errors.append(
            "  ✗ ORDEN INCORRECTO: bosque-obj-panel debe aparecer ANTES de bosque-retention-panel"
        )
    if _tpl_errors:
        print(
            f"\n{'!' * 60}\n"
            f"ERROR CRÍTICO: El template tiene secciones faltantes o en orden incorrecto.\n"
            f"Posible causa: Google Drive sincronizó una versión vieja del template.\n"
            + "\n".join(_tpl_errors)
            + f"\n{'!' * 60}\n",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"[{ts()}] Template OK — validación estructural superada ({len(_CRITICAL_CHECKS)} checks)")
    # ── Fin validación ───────────────────────────────────────────────────────

    print(f"[{ts()}] Leyendo objetivos (Firestore → Drive → GCS cache → JSON local → vacío)...")

    # Cargar caché anterior para comparar después del fetch
    _prev_obj = None
    if os.path.exists(OBJ_JSON_FILE):
        try:
            with open(OBJ_JSON_FILE, encoding="utf-8") as fh:
                _cached = json.load(fh)
            _prev_obj = {k: v for k, v in _cached.items() if k != "_meta"}
        except Exception:
            pass

    def _stale_days(meta):
        try:
            return (datetime.now() - datetime.fromisoformat(meta["fetched_at"])).days
        except Exception:
            return "?"

    def _apply_cached(cached_dict, source_label):
        _meta = cached_dict.pop("_meta", {})
        print(
            f"[{ts()}] Objetivos desde {source_label} — FALLBACK "
            f"(antigüedad: {_stale_days(_meta)} día(s), "
            f"última sync: {_meta.get('fetched_at', 'desconocida')})",
            file=sys.stderr,
        )
        return cached_dict

    obj = None
    _obj_source = "none"

    # ── 0. Intentar desde Firestore ──────────────────────────────────────────
    try:
        from google.cloud import firestore as _firestore
        _fs_client = _firestore.Client(project="temple-bar-439715")
        _fs_obj = load_objectives_from_firestore(_fs_client)
        if _fs_obj:
            obj = _fs_obj
            _obj_source = "firestore"
            print(f"[{ts()}] Objetivos OK (desde Firestore)")
    except Exception as _fs_init_err:
        print(f"WARN: Firestore init falló: {_fs_init_err}", file=sys.stderr)

    # ── 1. Intentar desde Drive ──────────────────────────────────────────────
    if obj is None:
        try:
            obj = fetch_objectives(creds)
            _obj_source = "drive"
            print(f"[{ts()}] Objetivos OK (desde Drive)")
            _to_save = {**obj, "_meta": {
                "source": "drive",
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "file_id": SHEET_OBJ_ID,
            }}
            # Guardar en local
            with open(OBJ_JSON_FILE, "w", encoding="utf-8") as fh:
                json.dump(_to_save, fh, ensure_ascii=False, indent=2)
            print(f"[{ts()}] JSON local de objetivos actualizado")
            # Guardar en GCS (persiste entre runs de Cloud Run)
            if args.gcs_bucket:
                try:
                    save_objectives_to_gcs(_to_save, args.gcs_bucket)
                except Exception as _gcs_save_err:
                    print(f"WARN: No se pudo guardar objetivos en GCS: {_gcs_save_err}", file=sys.stderr)
        except Exception as exc:
            import traceback
            print(f"WARN: Drive falló: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    # ── 2. Fallback: GCS cache (sobrevive reinicios de Cloud Run) ───────────
    if obj is None and args.gcs_bucket:
        try:
            _cached = load_objectives_from_gcs(args.gcs_bucket)
            obj = _apply_cached(_cached, f"gs://{args.gcs_bucket}/{OBJ_GCS_BLOB}")
            _obj_source = "gcs_cache"
        except Exception as _gcs_err:
            print(f"WARN: GCS cache falló: {_gcs_err}", file=sys.stderr)

    # ── 3. Fallback: archivo local ───────────────────────────────────────────
    if obj is None and os.path.exists(OBJ_JSON_FILE):
        try:
            with open(OBJ_JSON_FILE, encoding="utf-8") as fh:
                _cached = json.load(fh)
            obj = _apply_cached(_cached, os.path.basename(OBJ_JSON_FILE))
            _obj_source = "local_cache"
        except Exception as _local_err:
            print(f"WARN: Caché local falló: {_local_err}", file=sys.stderr)

    # ── 4. Sin objetivos — dashboard se genera con aviso visible ────────────
    _obj_missing = obj is None
    if _obj_missing:
        obj = {b: {"product": {}, "cluster": {}} for b in ("bosque", "feriado", "cerveza")}
        _obj_source = "empty"
        print("WARN: Sin objetivos disponibles — dashboard sin sección de objetivos", file=sys.stderr)

    # Validar estructura y detectar anomalías (solo log, nunca abortar)
    _errs, _warns = validate_objectives(obj, _prev_obj)
    if _errs or _warns:
        _hdr = (
            f"\n{'!' * 60}\n"
            f"⚠  ALERTA OBJETIVOS DESTILERÍA — fuente: {_obj_source}"
            + (f" | {len(_errs)} ERROR(ES)" if _errs else "")
            + (f" | {len(_warns)} cambio(s) grandes" if _warns else "")
            + f"\n"
        )
        print(_hdr, file=sys.stderr)
        for e in _errs:
            print(f"  ❌ ERROR  : {e}", file=sys.stderr)
        for w in _warns:
            print(f"  ⚠  CAMBIO: {w}", file=sys.stderr)
        print(f"{'!' * 60}\n", file=sys.stderr)
        # Si Drive devolvió objetivos inválidos, intentar GCS cache como recuperación
        if _errs and _obj_source == "drive" and args.gcs_bucket:
            try:
                _cached = load_objectives_from_gcs(args.gcs_bucket)
                _cached_errs, _ = validate_objectives(_cached)
                if not _cached_errs:
                    obj = _apply_cached(_cached, f"gs://{args.gcs_bucket}/{OBJ_GCS_BLOB} [recuperación]")
                    _obj_source = "gcs_cache"
                    _obj_missing = False
                    print(f"[{ts()}] Recuperado: usando GCS cache en lugar de objetivos inválidos de Drive")
            except Exception:
                pass

    obj_json  = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    html = template.replace("__ROWS_JSON__",   rows_json)
    html = html.replace("__OBJ_JSON__",        obj_json)
    html = html.replace("__UPDATED_AT__",      now_str)
    html = html.replace("__RECORD_COUNT__",    f"{len(data):,}")

    # ── Sell-in / Sell-out Bosque Nativo ────────────────────────────────────
    try:
        _sio = fetch_sellinout_weekly(creds, weeks=12)
        html = html.replace("__SELLINOUT_JSON__", json.dumps(_sio, ensure_ascii=False, separators=(",", ":")))
        print(f"[{ts()}] ✓ SELLINOUT inyectado ({len(_sio)} semanas)")
    except Exception as _sio_err:
        print(f"WARN: SELLINOUT falló — {_sio_err}", file=sys.stderr)
        html = html.replace("__SELLINOUT_JSON__", "[]")

    # ── Sell-in / Sell-out por local ────────────────────────────────────────
    try:
        _sio_local = fetch_sellinout_by_local(creds, weeks=12)
        html = html.replace("__SELLINOUT_LOCAL_JSON__", json.dumps(_sio_local, ensure_ascii=False, separators=(",", ":")))
        print(f"[{ts()}] ✓ SELLINOUT_LOCAL inyectado ({len(_sio_local)} locales)")
    except Exception as _sio_local_err:
        print(f"WARN: SELLINOUT_LOCAL falló — {_sio_local_err}", file=sys.stderr)
        html = html.replace("__SELLINOUT_LOCAL_JSON__", "[]")

    # ── Sell-in / Sell-out por local × semana ───────────────────────────────
    try:
        _sio_lw = fetch_sellinout_local_weekly(creds, weeks=12)
        html = html.replace("__SELLINOUT_LOCAL_WK_JSON__", json.dumps(_sio_lw, ensure_ascii=False, separators=(",", ":")))
        print(f"[{ts()}] ✓ SELLINOUT_LOCAL_WK inyectado ({len(_sio_lw)} filas)")
    except Exception as _sio_lw_err:
        print(f"WARN: SELLINOUT_LOCAL_WK falló — {_sio_lw_err}", file=sys.stderr)
        html = html.replace("__SELLINOUT_LOCAL_WK_JSON__", "[]")

    try:
        _sio_pat = fetch_sellinout_pat_weekly(creds, weeks=12)
        html = html.replace("__SELLINOUT_PAT_JSON__", json.dumps(_sio_pat, ensure_ascii=False, separators=(",", ":")))
        print(f"[{ts()}] ✓ SELLINOUT_PAT inyectado ({len(_sio_pat)} semanas)")
    except Exception as _sio_pat_err:
        print(f"WARN: SELLINOUT_PAT falló — {_sio_pat_err}", file=sys.stderr)
        html = html.replace("__SELLINOUT_PAT_JSON__", "[]")

    try:
        _sio_pat_lw = fetch_sellinout_pat_local_weekly(creds, weeks=12)
        html = html.replace("__SELLINOUT_PAT_LOCAL_WK_JSON__", json.dumps(_sio_pat_lw, ensure_ascii=False, separators=(",", ":")))
        print(f"[{ts()}] ✓ SELLINOUT_PAT_LOCAL_WK inyectado ({len(_sio_pat_lw)} filas)")
    except Exception as _sio_pat_lw_err:
        print(f"WARN: SELLINOUT_PAT_LOCAL_WK falló — {_sio_pat_lw_err}", file=sys.stderr)
        html = html.replace("__SELLINOUT_PAT_LOCAL_WK_JSON__", "[]")

    # Garantía: __PERMISSIONS_INJECT__ siempre presente aunque Drive haya
    # sincronizado una versión vieja del template que no lo tenga.
    if "__PERMISSIONS_INJECT__" not in html:
        html = html.replace("<body>", "<body>\n__PERMISSIONS_INJECT__", 1)
        print(f"[{ts()}] WARN: __PERMISSIONS_INJECT__ no estaba en el template — insertado automáticamente")

    # Banner visible cuando los objetivos no están disponibles
    if _obj_missing:
        _banner = (
            '<div style="background:#b91c1c;color:#fff;text-align:center;padding:10px 16px;'
            'font-family:sans-serif;font-size:14px;font-weight:600;position:sticky;top:0;z-index:9999">'
            '⚠ Objetivos no disponibles — Drive no accesible al momento de generar este dashboard. '
            f'Generado: {now_str}'
            '</div>'
        )
        html = html.replace("<body", _banner + "<body", 1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(html)

    kb = len(html.encode("utf-8")) // 1024
    print(f"[{ts()}] Generado: {args.output} ({kb} KB · {len(data):,} registros)")

    if args.gcs_bucket:
        upload_to_gcs(args.output, args.gcs_bucket, html_content=html)
    else:
        print()
        print("Deploy:")
        print('  gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" '
              'cp destileria_dashboard.html '
              'gs://temple-bar-dashboard-cache/destileria_dashboard.html')


def fetch_sellinout_weekly(creds, weeks=12):
    """
    Retorna lista de semanas (más reciente primero) con sell-in y sell-out
    de Bosque Nativo para el cluster Cadena Grupo Temple.

    Sell-in : Ventas_Maestro_Con_Cluster_Final — cl='CADENA GRUPO TEMPLE',
              fa='bosque_nativo' (cubre 500ml y 750ml), campo li (litros).
    Sell-out: temple-bar-439715.curated_database.curated_gin — todos los
              registros, campo Gin_Total (litros por serve ya calculado).

    Alarma: sell-out[semana N] > sell-in[semana N-1]
    """
    from google.cloud import bigquery as _bq
    bq_dest   = _bq.Client(project="temple-brewery",    credentials=creds)
    bq_temple = _bq.Client(project="temple-bar-439715", credentials=creds)

    q_si = f"""
    SELECT
      DATE_TRUNC(FechaPedido, WEEK(MONDAY))  AS semana,
      ROUND(SUM(COALESCE(Litros, 0)), 2)     AS litros
    FROM `temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final`
    WHERE LOWER(TRIM(Clusterizacion)) = 'cadena grupo temple'
      AND REGEXP_CONTAINS(UPPER(TRIM(Producto)), r'GIN BOSQUE.*(500|750)')
      AND FechaPedido >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
    GROUP BY semana
    """
    q_so = f"""
    SELECT
      DATE_TRUNC(Fecha, WEEK(MONDAY)) AS semana,
      ROUND(SUM(Gin_Total), 2)        AS litros
    FROM `temple-bar-439715.curated_database.curated_gin`
    WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
    GROUP BY semana
    """
    si_map = {str(r.semana): float(r.litros) for r in bq_dest.query(q_si).result(timeout=60)}
    so_map = {str(r.semana): float(r.litros) for r in bq_temple.query(q_so).result(timeout=60)}

    all_weeks = sorted(set(list(si_map) + list(so_map)), reverse=True)[:weeks]

    result = []
    for i, wk in enumerate(all_weeks):
        si      = si_map.get(wk, 0.0)
        so      = so_map.get(wk, 0.0)
        prev_wk = all_weeks[i + 1] if i + 1 < len(all_weeks) else None
        si_prev = si_map.get(prev_wk) if prev_wk else None
        result.append({
            "w":       wk,
            "si":      si,
            "so":      so,
            "diff":    round(si - so, 2),
            "si_prev": si_prev,
            "alarm":   (si_prev is not None and so > si_prev),
        })
    return result


# ── Mapping sell-in NombreDeFantasia → nombre canónico ──────────────────────
# None = excluir del análisis cadena (no son locales de la cadena Grupo Temple)
_SI_ALIAS = {
    "Temple Craft Madero":              "Puerto Madero",
    "Temple Hollywood":                 "Hollywood",
    "MINIMARKET (Distri Rio Gallegos)": "Rio Gallegos",
    "Temple Barrio Chino":              "Barrio Chino",
    "Temple Paseo La Plaza":            "Club Temple",
    "Temple Craft Soho":                "Soho",
    "Temple Monroe":                    "Monroe",
    "Temple Recoleta":                  "Recoleta",
    "Temple Santiago del Estero":       "Santiago del Estero",
    "Temple Craft Pilar":               "Pilar",
    "Temple Craft Salta":               "Salta",
    "Temple Comodoro":                  "Comodoro Rivadavia",
    "Temple Maschwitz":                 "Maschwitz",
    "Temple Cordoba":                   "Córdoba",
    "Temple Caminito":                  "Caminito",
    "Temple Palermo":                   "Casa Temple",
    "Barra Patio de los Lecheros":      None,   # no es cadena Grupo Temple
    "Trenque Craft":                    None,   # no es cadena Grupo Temple
}

# ── Mapping sell-out Establecimiento → nombre canónico ──────────────────────
_SO_ALIAS = {
    "PUERTO MADERO":      "Puerto Madero",
    "HOLLYWOOD":          "Hollywood",
    "CLUB TEMPLE":        "Club Temple",
    "SOHO":               "Soho",
    "CASA TEMPLE":        "Casa Temple",
    "MASCHWITZ":          "Maschwitz",
    "RIO GALLEGOS":       "Rio Gallegos",
    "BARRIO CHINO":       "Barrio Chino",
    "SALTA":              "Salta",
    "PILAR":              "Pilar",
    "MONROE":             "Monroe",
    "CORRIENTES":         "Corrientes",
    "RECOLETA":           "Recoleta",
    "SANTIAGO DEL ESTERO": "Santiago del Estero",
    "ROSARIO 2":          "Rosario 2",
    "COMODORO RIVADAVIA": "Comodoro Rivadavia",
    "TUCUMAN 3":          "Tucumán 3",
    "CAMINITO":           "Caminito",
    "GUEMES":             "Güemes",
    "PINAMAR":            "Pinamar",
}


# ── Productos Patagonia que usan 50ml de Gin Bosque en receta ───────────────
_PAT_SO_PRODUCTS = [
    'GIN TONIC - BOSQUE GIN',
    'BOTELLA GIN TONIC - (BOSQUE GIN)',
    'GIN TONIC LIMON',
    'GIN TONIC LIMA',
    'GIN TONIC POMELO',
    'GIN TONIC NARANJA',
    'GIN PEPINO',
    'GIN FRUTOS',
    'GIN MARACUYA',
    'GIN PEPINO LIMON',
    'GIN BOTELLA MEDIDA',
    'DRAGON GIN',
]
# Alias NombreDeFantasia → nombre canónico (None = excluir).
_PAT_SI_ALIAS: dict[str, str | None] = {
    "Patagonia Casa Tango":      "Casa Del Tango",
    "Patagonia Lanus":           "Ba - Lanus",
    "Patagonia Leloir":          "Leloir",
    "Patagonia Mendoza":         "Mendoza",
    "Refugio Patagonia Parana":  "Parana",
}
# Alias Establecimiento → nombre canónico. Completar con las sucursales de Patagonia.
_PAT_SO_ALIAS: dict[str, str | None] = {}


def fetch_sellinout_by_local(creds, weeks=12):
    """Sell-in (NombreDeFantasia) vs sell-out (Establecimiento) totales por local, últimas N semanas."""
    from google.cloud import bigquery as _bq
    bq_dest   = _bq.Client(project="temple-brewery",    credentials=creds)
    bq_temple = _bq.Client(project="temple-bar-439715", credentials=creds)

    q_si = f"""
    SELECT
      TRIM(NombreDeFantasia)             AS local,
      ROUND(SUM(COALESCE(Litros, 0)), 2) AS litros
    FROM `temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final`
    WHERE LOWER(TRIM(Clusterizacion)) = 'cadena grupo temple'
      AND REGEXP_CONTAINS(UPPER(TRIM(Producto)), r'GIN BOSQUE.*(500|750)')
      AND FechaPedido >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
    GROUP BY local
    """

    q_so = f"""
    SELECT
      TRIM(Establecimiento)    AS local,
      ROUND(SUM(Gin_Total), 2) AS litros
    FROM `temple-bar-439715.curated_database.curated_gin`
    WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
    GROUP BY local
    """

    si_raw = {r.local: float(r.litros) for r in bq_dest.query(q_si).result(timeout=60)}
    so_raw = {r.local: float(r.litros) for r in bq_temple.query(q_so).result(timeout=60)}

    # Aplicar alias sell-in (None = excluir)
    si_map: dict[str, float] = {}
    for name, litros in si_raw.items():
        canon = _SI_ALIAS.get(name, name)
        if canon is None:
            continue
        si_map[canon] = si_map.get(canon, 0.0) + litros

    # Aplicar alias sell-out
    so_map: dict[str, float] = {}
    for name, litros in so_raw.items():
        canon = _SO_ALIAS.get(name, name.title())
        so_map[canon] = so_map.get(canon, 0.0) + litros

    all_locals = sorted(set(list(si_map) + list(so_map)))
    result = []
    for local in all_locals:
        si = si_map.get(local, 0.0)
        so = so_map.get(local, 0.0)
        result.append({"local": local, "si": si, "so": so, "diff": round(si - so, 2)})

    result.sort(key=lambda x: x["so"], reverse=True)
    return result


def fetch_sellinout_local_weekly(creds, weeks=12):
    """Sell-in vs sell-out por local y por semana — pivot para vista Sem × Local."""
    from google.cloud import bigquery as _bq
    bq_dest   = _bq.Client(project="temple-brewery",    credentials=creds)
    bq_temple = _bq.Client(project="temple-bar-439715", credentials=creds)

    q_si = f"""
    SELECT
      DATE_TRUNC(FechaPedido, WEEK(MONDAY)) AS semana,
      TRIM(NombreDeFantasia)                AS local,
      ROUND(SUM(COALESCE(Litros, 0)), 2)   AS litros
    FROM `temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final`
    WHERE LOWER(TRIM(Clusterizacion)) = 'cadena grupo temple'
      AND REGEXP_CONTAINS(UPPER(TRIM(Producto)), r'GIN BOSQUE.*(500|750)')
      AND FechaPedido >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
    GROUP BY semana, local
    """

    q_so = f"""
    SELECT
      DATE_TRUNC(Fecha, WEEK(MONDAY)) AS semana,
      TRIM(Establecimiento)           AS local,
      ROUND(SUM(Gin_Total), 2)        AS litros
    FROM `temple-bar-439715.curated_database.curated_gin`
    WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
    GROUP BY semana, local
    """

    # Build maps: (canon_local, week_str) -> litros
    si_map: dict[tuple, float] = {}
    for r in bq_dest.query(q_si).result(timeout=60):
        canon = _SI_ALIAS.get(r.local, r.local)
        if canon is None:
            continue
        key = (canon, str(r.semana))
        si_map[key] = si_map.get(key, 0.0) + float(r.litros)

    so_map: dict[tuple, float] = {}
    for r in bq_temple.query(q_so).result(timeout=60):
        canon = _SO_ALIAS.get(r.local, r.local.title())
        key = (canon, str(r.semana))
        so_map[key] = so_map.get(key, 0.0) + float(r.litros)

    all_weeks  = sorted({k[1] for k in list(si_map) + list(so_map)}, reverse=True)[:weeks]
    all_locals = sorted({k[0] for k in list(si_map) + list(so_map)})

    result = []
    for local in all_locals:
        for wk in all_weeks:
            si = si_map.get((local, wk), 0.0)
            so = so_map.get((local, wk), 0.0)
            if si > 0 or so > 0:
                result.append({"local": local, "w": wk, "si": si, "so": so})
    return result


def fetch_sellinout_pat_weekly(creds, weeks=12):
    """
    Sell-in/out semanal para Cadena Patagonia.
    Sell-in : Ventas_Maestro_Con_Cluster_Final — cl='cadena patagonia', GIN BOSQUE 500+750ml, campo Litros.
    Sell-out: patagonia-refugios.curated_database.curated_mix — 12 productos con receta 50ml gin Bosque,
              litros = SUM(Cantidad) * 0.05.
    Alarma: sell-out[semana N] > sell-in[semana N-1].
    """
    from google.cloud import bigquery as _bq
    bq_dest = _bq.Client(project="temple-brewery",     credentials=creds)
    bq_pat  = _bq.Client(project="patagonia-refugios", credentials=creds)

    q_si = f"""
    SELECT
      DATE_TRUNC(FechaPedido, WEEK(MONDAY)) AS semana,
      ROUND(SUM(COALESCE(Litros, 0)), 2)   AS litros
    FROM `temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final`
    WHERE LOWER(TRIM(Clusterizacion)) = 'cadena patagonia'
      AND REGEXP_CONTAINS(UPPER(TRIM(Producto)), r'GIN BOSQUE.*(500|750)')
      AND FechaPedido >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
    GROUP BY semana
    """

    _prods_sql = ', '.join(f"'{p}'" for p in _PAT_SO_PRODUCTS)
    q_so = f"""
    SELECT
      DATE_TRUNC(Fecha, WEEK(MONDAY))     AS semana,
      ROUND(SUM(Cantidad) * 0.05, 2)     AS litros
    FROM `patagonia-refugios.curated_database.curated_mix`
    WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
      AND UPPER(TRIM(Producto)) IN ({_prods_sql})
    GROUP BY semana
    """

    si_map = {str(r.semana): float(r.litros) for r in bq_dest.query(q_si).result(timeout=60)}
    so_map = {str(r.semana): float(r.litros) for r in bq_pat.query(q_so).result(timeout=60)}

    all_weeks = sorted(set(list(si_map) + list(so_map)), reverse=True)[:weeks]
    result = []
    for i, wk in enumerate(all_weeks):
        si      = si_map.get(wk, 0.0)
        so      = so_map.get(wk, 0.0)
        prev_wk = all_weeks[i + 1] if i + 1 < len(all_weeks) else None
        si_prev = si_map.get(prev_wk) if prev_wk else None
        result.append({
            "w":       wk,
            "si":      si,
            "so":      so,
            "diff":    round(si - so, 2),
            "si_prev": si_prev,
            "alarm":   (si_prev is not None and so > si_prev),
        })
    return result


def fetch_sellinout_pat_local_weekly(creds, weeks=12):
    """Sell-in vs sell-out Patagonia por local y por semana — pivot para vista Sem × Local."""
    from google.cloud import bigquery as _bq
    bq_dest = _bq.Client(project="temple-brewery",     credentials=creds)
    bq_pat  = _bq.Client(project="patagonia-refugios", credentials=creds)

    q_si = f"""
    SELECT
      DATE_TRUNC(FechaPedido, WEEK(MONDAY)) AS semana,
      TRIM(NombreDeFantasia)                AS local,
      ROUND(SUM(COALESCE(Litros, 0)), 2)   AS litros
    FROM `temple-brewery.Destileria.Ventas_Maestro_Con_Cluster_Final`
    WHERE LOWER(TRIM(Clusterizacion)) = 'cadena patagonia'
      AND REGEXP_CONTAINS(UPPER(TRIM(Producto)), r'GIN BOSQUE.*(500|750)')
      AND FechaPedido >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
    GROUP BY semana, local
    """

    _prods_sql = ', '.join(f"'{p}'" for p in _PAT_SO_PRODUCTS)
    q_so = f"""
    SELECT
      DATE_TRUNC(Fecha, WEEK(MONDAY))     AS semana,
      TRIM(Establecimiento)               AS local,
      ROUND(SUM(Cantidad) * 0.05, 2)     AS litros
    FROM `patagonia-refugios.curated_database.curated_mix`
    WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks + 2} WEEK)
      AND UPPER(TRIM(Producto)) IN ({_prods_sql})
    GROUP BY semana, local
    """

    si_map: dict[tuple, float] = {}
    for r in bq_dest.query(q_si).result(timeout=60):
        canon = _PAT_SI_ALIAS.get(r.local, r.local)
        if canon is None:
            continue
        key = (canon, str(r.semana))
        si_map[key] = si_map.get(key, 0.0) + float(r.litros)

    so_map: dict[tuple, float] = {}
    for r in bq_pat.query(q_so).result(timeout=60):
        canon = _PAT_SO_ALIAS.get(r.local, r.local.title() if r.local else r.local)
        key = (canon, str(r.semana))
        so_map[key] = so_map.get(key, 0.0) + float(r.litros)

    all_weeks  = sorted({k[1] for k in list(si_map) + list(so_map)}, reverse=True)[:weeks]
    all_locals = sorted({k[0] for k in list(si_map) + list(so_map)})

    result = []
    for local in all_locals:
        for wk in all_weeks:
            si = si_map.get((local, wk), 0.0)
            so = so_map.get((local, wk), 0.0)
            if si > 0 or so > 0:
                result.append({"local": local, "w": wk, "si": si, "so": so})
    return result


if __name__ == "__main__":
    main()
