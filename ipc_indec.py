"""IPC INDEC para la pestaña Finanzas del tablero retail.

Trae de la API de series de datos.gob.ar el IPC general nacional y el de
Hoteles y restaurantes, completa los meses todavía no publicados repitiendo la
última variación mensual no negativa, y guarda las series publicadas en GCS como respaldo
por si la API falla en una corrida futura.

obtener_ipc() nunca lanza: ante cualquier falla devuelve la copia de GCS o None
(la pestaña muestra "Datos de inflación no disponibles").
"""
import json
import time
from datetime import date

import requests

API_URL = "https://apis.datos.gob.ar/series/api/series/"
SERIES = {  # el orden importa: es el orden de las columnas en la respuesta
    "general": "148.3_INIVELNAL_DICI_M_26",  # IPC Nivel general nacional, base dic-2016
    "rubro": "146.3_IRESTAUNAL_DICI_M_33",   # IPC Hoteles y restaurantes nacional, base dic-2016
}
CACHE_BLOB = "ipc_cache.json"
MAX_ATRASO_MESES = 3
MAX_BAJA_MENSUAL = 0.05  # una baja mayor del índice en un mes es un dato roto, no deflación


def _mes_siguiente(mes):
    y, m = int(mes[:4]), int(mes[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def _distancia_meses(desde, hasta):
    return (int(hasta[:4]) - int(desde[:4])) * 12 + int(hasta[5:7]) - int(desde[5:7])


def parse_respuesta(payload):
    """{"data": [["2026-08-01", g, r], ...]} → {"general": {"2026-08": g}, "rubro": {...}}."""
    series = {nombre: {} for nombre in SERIES}
    for fila in payload.get("data", []):
        mes = fila[0][:7]
        for nombre, valor in zip(SERIES, fila[1:]):
            if valor is not None:
                series[nombre][mes] = float(valor)
    return series


def validar(series, hoy=None):
    """ValueError si una serie está vacía o su índice baja más de 5% de un mes a otro.
    Devuelve avisos: con FALLÓ si el último dato tiene más de 3 meses, con ⚠ si el
    índice baja menos de 5% en un mes (deflación posible, sobre todo en el rubro)."""
    hoy = hoy or date.today()
    mes_hoy = f"{hoy.year:04d}-{hoy.month:02d}"
    avisos = []
    for nombre, serie in series.items():
        if not serie:
            raise ValueError(f"serie {nombre} vacía")
        meses = sorted(serie)
        for a, b in zip(meses, meses[1:]):
            baja = 1 - serie[b] / serie[a]
            if baja > MAX_BAJA_MENSUAL:
                raise ValueError(f"serie {nombre} baja de {a} a {b} ({baja:.1%})")
            if baja > 0:
                avisos.append(f"⚠ IPC {nombre} baja {baja * 100:.1f}% en {b} (aceptado)")
        atraso = _distancia_meses(meses[-1], mes_hoy)
        if atraso > MAX_ATRASO_MESES:
            avisos.append(f"FALLÓ IPC desactualizado: {nombre} último dato {meses[-1]} ({atraso} meses)")
    return avisos


def _variacion_estimada(serie):
    """Última variación mensual no negativa de la serie (1.0 si no hay). Una baja del índice
    (validar acepta hasta 5%) se toma como puntual: repetirla proyectaría deflación hasta diciembre."""
    meses = sorted(serie)
    for a, b in zip(reversed(meses[:-1]), reversed(meses[1:])):
        if serie[b] >= serie[a]:
            return serie[b] / serie[a]
    return 1.0


def completar_estimados(series, hasta):
    """Extiende cada serie hasta `hasta` repitiendo su última variación mensual no negativa.
    Devuelve (series_completas, meses_estimados ordenados)."""
    completas, estimados = {}, set()
    for nombre, serie in series.items():
        s = dict(serie)
        meses = sorted(s)
        variacion = _variacion_estimada(serie)
        mes = meses[-1]
        while mes < hasta:
            siguiente = _mes_siguiente(mes)
            s[siguiente] = round(s[mes] * variacion, 4)
            estimados.add(siguiente)
            mes = siguiente
        completas[nombre] = s
    return completas, sorted(estimados)


def construir_payload(series, hoy=None, fuente="api"):
    hoy = hoy or date.today()
    completas, estimados = completar_estimados(series, f"{hoy.year:04d}-12")
    return {"base": max(series["general"]), "general": completas["general"],
            "rubro": completas["rubro"], "estimados": estimados, "fuente": fuente}


def variaciones_mensuales(payload):
    """Variación mensual (%) del IPC general, con 1 decimal: {"2026-08": 2.0, ...}.
    Es el formato de ipc_mensual en economic_context.json (Insights de Ventas).
    Incluye los meses estimados. {} si no hay payload."""
    if not payload:
        return {}
    serie = payload["general"]
    meses = sorted(serie)
    return {b: round((serie[b] / serie[a] - 1) * 100, 1) for a, b in zip(meses, meses[1:])}


def descargar(desde="2024-01", intentos=3, espera=3, timeout=20):
    params = {"ids": ",".join(SERIES.values()), "start_date": f"{desde}-01",
              "format": "json", "limit": 1000}
    ultimo_error = None
    for i in range(intentos):
        try:
            r = requests.get(API_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return parse_respuesta(r.json())
        except (requests.RequestException, ValueError) as exc:
            ultimo_error = exc
            if i < intentos - 1:
                time.sleep(espera)
    raise RuntimeError(f"API IPC sin respuesta: {ultimo_error}")


def _leer_cache(bucket):
    from google.cloud import storage
    blob = storage.Client().bucket(bucket).blob(CACHE_BLOB)
    if not blob.exists():
        return None
    return json.loads(blob.download_as_text(encoding="utf-8"))


def _guardar_cache(bucket, series):
    from google.cloud import storage
    blob = storage.Client().bucket(bucket).blob(CACHE_BLOB)
    blob.upload_from_string(json.dumps(series), content_type="application/json")
    blob.cache_control = "no-cache, no-store, must-revalidate"  # después del upload
    blob.patch()


def obtener_ipc(bucket="", hoy=None, log=print):
    """Payload IPC para el tablero, o None si no hay datos. Nunca lanza.
    Con bucket vacío (corridas locales) no lee ni escribe GCS."""
    try:
        series = descargar()
        avisos = validar(series, hoy)
        fuente = "api"
        if bucket:
            try:
                _guardar_cache(bucket, series)
            except Exception as exc:
                log(f"  ⚠ IPC: no se pudo guardar {CACHE_BLOB}: {exc}")
    except Exception as exc:
        log(f"  FALLÓ IPC API ({exc}), usando cache")
        if not bucket:
            return None
        try:
            series = _leer_cache(bucket)
            if not series:
                log("  FALLÓ IPC: sin cache en GCS — pestaña Finanzas sin datos")
                return None
            avisos = validar(series, hoy)
            fuente = "cache"
        except Exception as exc2:
            log(f"  FALLÓ IPC cache ({exc2}) — pestaña Finanzas sin datos")
            return None
    for aviso in avisos:
        log("  " + aviso)
    payload = construir_payload(series, hoy, fuente)
    log(f"  ✓ IPC ({fuente}): base {payload['base']}, {len(payload['estimados'])} meses estimados")
    return payload
