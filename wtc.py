"""WTC (Uruguay): carga manual mensual con conversión UYU→ARS.

Lo usan app.py (formulario /admin) y actualizar_retail.py (pipeline del tablero).
Spec: docs/superpowers/specs/2026-10-01-wtc-carga-manual-design.md
"""
import re
import time
from datetime import date

import requests

MES_MIN = "2025-01"
_MESES_ES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
             "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


def _mes_str(y, m):
    return f"{y:04d}-{m:02d}" if 1 <= m <= 12 else None


def parse_mes(s):
    """'2025-01' | '01/2025' | 'ene-25' | 'ene-2025' → '2025-01'; None si no se entiende."""
    s = (s or "").strip().lower()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", s):
        return _mes_str(int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", s):
        return _mes_str(int(m[2]), int(m[1]))
    if m := re.fullmatch(r"([a-z]{3})-(\d{2}|\d{4})", s):
        if m[1] not in _MESES_ES:
            return None
        y = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
        return _mes_str(y, _MESES_ES[m[1]])
    return None


def parse_numero(s):
    """Formato argentino ('12.345.678,50', '1.234' = 1234) o plano ('12345678.50'). None si no es número ≥ 0."""
    s = (s or "").strip()
    if s.startswith("$"):
        s = s[1:]
    if not s:
        return None
    if "," in s:
        if s.count(",") > 1:
            return None
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    return float(s)


def wtc_parse_filas(texto, hoy):
    """Parsea el pegado del formulario. Devuelve (filas, errores).
    Fila: {"mes", "facturacion_uyu", "ordenes", "litros_cerveza"}; error: {"linea", "error"}.
    Con cualquier error no se debe guardar nada (lo decide quien llama)."""
    mes_max = f"{hoy.year:04d}-{hoy.month:02d}"
    filas, errores, vistos = [], [], set()
    primera = True
    for n, linea in enumerate((texto or "").splitlines(), start=1):
        if not linea.strip():
            continue
        campos = [c for c in re.split(r"[\t;]|\s+", linea.strip()) if c]
        if primera and campos[0].lower().startswith("mes"):
            primera = False
            continue
        primera = False
        if len(campos) != 4:
            errores.append({"linea": n, "error": f"se esperaban 4 columnas (mes, facturación UYU, órdenes, litros) y hay {len(campos)}"})
            continue
        mes = parse_mes(campos[0])
        if not mes:
            errores.append({"linea": n, "error": f"mes inválido: '{campos[0]}' (usar 2025-01, 01/2025 o ene-25)"})
            continue
        if not (MES_MIN <= mes <= mes_max):
            errores.append({"linea": n, "error": f"mes {mes} fuera de rango ({MES_MIN} a {mes_max})"})
            continue
        if mes in vistos:
            errores.append({"linea": n, "error": f"mes {mes} repetido en el pegado"})
            continue
        fac, ords, lts = (parse_numero(c) for c in campos[1:])
        if fac is None or ords is None or lts is None:
            errores.append({"linea": n, "error": "facturación, órdenes y litros deben ser números ≥ 0"})
            continue
        if ords != int(ords):
            errores.append({"linea": n, "error": f"órdenes debe ser entero: '{campos[2]}'"})
            continue
        vistos.add(mes)
        filas.append({"mes": mes, "facturacion_uyu": round(fac, 2), "ordenes": int(ords),
                      "litros_cerveza": round(lts, 2)})
    if not filas and not errores:
        errores.append({"linea": 0, "error": "No hay filas para cargar"})
    return filas, errores


# ── Tipo de cambio BCRA (ARS por UYU, promedio de días hábiles del mes) ──────

PROYECTO = "temple-bar-439715"
TABLA_CARGA = f"{PROYECTO}.Corporativo.wtc_manual_mensual"
TABLA_TC = f"{PROYECTO}.Corporativo.tipo_cambio_uyu_ars"
BCRA_URL = "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/UYU"


def _mes_de(d):
    return f"{d.year:04d}-{d.month:02d}"


def _meses_entre(desde, hasta):
    """'2025-01', '2025-03' → ['2025-01', '2025-02', '2025-03']."""
    y, m = int(desde[:4]), int(desde[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hasta:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def promedio_mensual(payload):
    """Respuesta BCRA → {"YYYY-MM": (promedio ARS por UYU de los días hábiles, cantidad de días)}."""
    por_mes = {}
    for dia in (payload or {}).get("results", []):
        for d in dia.get("detalle", []):
            v = d.get("tipoCotizacion")
            if d.get("codigoMoneda") == "UYU" and v:
                por_mes.setdefault(dia["fecha"][:7], []).append(float(v))
    return {mes: (sum(vs) / len(vs), len(vs)) for mes, vs in por_mes.items()}


def meses_pendientes(existentes, hoy):
    """Meses desde MES_MIN hasta el actual sin fila o con completo = false."""
    return [m for m in _meses_entre(MES_MIN, _mes_de(hoy)) if not existentes.get(m, False)]


def descargar_cotizaciones(desde, hasta, intentos=3, espera=2, timeout=10):
    """Payload BCRA del rango (1 intento + 2 reintentos). Lanza RuntimeError si no responde."""
    params = {"fechadesde": desde.isoformat(), "fechahasta": hasta.isoformat(), "limit": 1000}
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(BCRA_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            ultimo = exc
            if i < intentos - 1:
                time.sleep(espera)
    raise RuntimeError(f"API BCRA sin respuesta: {ultimo}")


def _param_filas(filas, tipos):
    """Lista de dicts → QueryJobConfig con @filas ARRAY<STRUCT>. tipos = {campo: tipo BQ}."""
    from google.cloud import bigquery
    structs = [bigquery.StructQueryParameter(
        None, *[bigquery.ScalarQueryParameter(k, t, f[k]) for k, t in tipos.items()]) for f in filas]
    return bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("filas", "STRUCT", structs)])


MERGE_TC_SQL = f"""
MERGE `{TABLA_TC}` T
USING (SELECT PARSE_DATE('%Y-%m', f.mes) AS mes, CAST(f.ars_por_uyu AS NUMERIC) AS ars_por_uyu,
              f.dias, f.completo
       FROM UNNEST(@filas) AS f) S
ON T.mes = S.mes
WHEN MATCHED THEN UPDATE SET ars_por_uyu = S.ars_por_uyu, dias = S.dias, completo = S.completo,
                             actualizado_en = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (mes, ars_por_uyu, dias, completo, actualizado_en)
                      VALUES (S.mes, S.ars_por_uyu, S.dias, S.completo, CURRENT_TIMESTAMP())
"""


def actualizar_tipo_cambio_uyu(client, hoy=None, log=print):
    """Completa tipo_cambio_uyu_ars con los meses faltantes o incompletos. Nunca lanza."""
    hoy = hoy or date.today()
    try:
        existentes = {r.mes: bool(r.completo) for r in client.query(
            f"SELECT FORMAT_DATE('%Y-%m', mes) AS mes, completo FROM `{TABLA_TC}`").result()}
        pendientes = meses_pendientes(existentes, hoy)
        if not pendientes:
            log("  ✓ WTC tipo de cambio al día")
            return
        desde = date(int(pendientes[0][:4]), int(pendientes[0][5:7]), 1)
        promedios = promedio_mensual(descargar_cotizaciones(desde, hoy))
        mes_actual = _mes_de(hoy)
        filas = [{"mes": m, "ars_por_uyu": f"{promedios[m][0]:.6f}", "dias": promedios[m][1],
                  "completo": m < mes_actual}
                 for m in pendientes if m in promedios and promedios[m][1] > 0]
        if not filas:
            log(f"  WARN WTC tipo de cambio: la API no trajo cotizaciones para {pendientes[0]}..{pendientes[-1]}")
            return
        client.query(MERGE_TC_SQL, job_config=_param_filas(
            filas, {"mes": "STRING", "ars_por_uyu": "STRING", "dias": "INT64", "completo": "BOOL"})).result()
        log(f"  ✓ WTC tipo de cambio: {len(filas)} meses actualizados ({filas[0]['mes']}..{filas[-1]['mes']})")
    except Exception as exc:
        log(f"  WARN WTC tipo de cambio: {exc}")


# ── BigQuery: carga manual ───────────────────────────────────────────────────

MERGE_CARGA_SQL = f"""
MERGE `{TABLA_CARGA}` T
USING (SELECT PARSE_DATE('%Y-%m', f.mes) AS mes, CAST(f.facturacion_uyu AS NUMERIC) AS facturacion_uyu,
              f.ordenes, CAST(f.litros_cerveza AS NUMERIC) AS litros_cerveza
       FROM UNNEST(@filas) AS f) S
ON T.mes = S.mes
WHEN MATCHED THEN UPDATE SET facturacion_uyu = S.facturacion_uyu, ordenes = S.ordenes,
                             litros_cerveza = S.litros_cerveza, cargado_por = @email,
                             cargado_en = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (mes, facturacion_uyu, ordenes, litros_cerveza, cargado_por, cargado_en)
                      VALUES (S.mes, S.facturacion_uyu, S.ordenes, S.litros_cerveza, @email, CURRENT_TIMESTAMP())
"""


def guardar_filas(client, filas, email):
    """Upsert por mes. filas = salida válida de wtc_parse_filas. Devuelve filas escritas."""
    if not filas:
        return 0
    from google.cloud import bigquery
    jc = _param_filas(
        [{"mes": f["mes"], "facturacion_uyu": f"{f['facturacion_uyu']:.2f}", "ordenes": f["ordenes"],
          "litros_cerveza": f"{f['litros_cerveza']:.2f}"} for f in filas],
        {"mes": "STRING", "facturacion_uyu": "STRING", "ordenes": "INT64", "litros_cerveza": "STRING"})
    jc.query_parameters = list(jc.query_parameters) + [bigquery.ScalarQueryParameter("email", "STRING", email)]
    client.query(MERGE_CARGA_SQL, job_config=jc).result()
    return len(filas)


def leer_carga(client):
    q = f"""SELECT FORMAT_DATE('%Y-%m', mes) AS mes, facturacion_uyu, ordenes, litros_cerveza,
                   cargado_por, cargado_en
            FROM `{TABLA_CARGA}` ORDER BY mes"""
    return [{"mes": r.mes, "facturacion_uyu": float(r.facturacion_uyu), "ordenes": int(r.ordenes),
             "litros_cerveza": float(r.litros_cerveza), "cargado_por": r.cargado_por,
             "cargado_en": r.cargado_en.isoformat() if r.cargado_en else None}
            for r in client.query(q).result()]


def leer_cotizaciones(client):
    q = f"SELECT FORMAT_DATE('%Y-%m', mes) AS mes, ars_por_uyu FROM `{TABLA_TC}`"
    return {r.mes: float(r.ars_por_uyu) for r in client.query(q).result()}
