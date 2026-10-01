"""tests/test_wtc.py — WTC Uruguay: parser del pegado, tipo de cambio BCRA, BigQuery (falso),
incorporación al tablero retail."""
from datetime import date

import pytest

import wtc

HOY = date(2026, 10, 1)


# ── parse_mes / parse_numero ─────────────────────────────────────────────────

@pytest.mark.parametrize("s,esperado", [
    ("2025-01", "2025-01"), ("01/2025", "2025-01"), ("1/2025", "2025-01"),
    ("ene-25", "2025-01"), ("ENE-25", "2025-01"), ("ene-2025", "2025-01"),
    ("set-25", "2025-09"), ("sep-25", "2025-09"), ("dic-26", "2026-12"),
])
def test_parse_mes_formatos_validos(s, esperado):
    assert wtc.parse_mes(s) == esperado


@pytest.mark.parametrize("s", ["2025-13", "13/2025", "xyz-25", "", "2025", "enero"])
def test_parse_mes_invalidos(s):
    assert wtc.parse_mes(s) is None


@pytest.mark.parametrize("s,esperado", [
    ("12.345.678,50", 12345678.5), ("12345678.50", 12345678.5), ("12345678", 12345678.0),
    ("1.234", 1234.0), ("1234,5", 1234.5), ("$1.000", 1000.0), ("0", 0.0),
])
def test_parse_numero(s, esperado):
    assert wtc.parse_numero(s) == esperado


def test_parse_numero_punto_con_tres_digitos_es_miles():
    # Review Focus #2: "1.234" en Argentina es mil doscientos treinta y cuatro
    assert wtc.parse_numero("1.234") == 1234.0
    assert wtc.parse_numero("1234.5") == 1234.5


@pytest.mark.parametrize("s", ["abc", "1,2,3", "", "-", "-5", "$", "1.2.3,4,5"])
def test_parse_numero_invalidos(s):
    assert wtc.parse_numero(s) is None


# ── wtc_parse_filas ──────────────────────────────────────────────────────────

def test_parse_filas_tab_punto_y_coma_y_espacios():
    texto = "2025-01\t12.345.678,50\t1.200\t3.400,5\n03/2025;1;2;3\nfeb-25   100   2   3"
    filas, errores = wtc.wtc_parse_filas(texto, HOY)
    assert errores == []
    assert filas == [
        {"mes": "2025-01", "facturacion_uyu": 12345678.5, "ordenes": 1200, "litros_cerveza": 3400.5},
        {"mes": "2025-03", "facturacion_uyu": 1.0, "ordenes": 2, "litros_cerveza": 3.0},
        {"mes": "2025-02", "facturacion_uyu": 100.0, "ordenes": 2, "litros_cerveza": 3.0},
    ]


def test_parse_ignora_encabezado():
    # Review Focus #1
    filas, errores = wtc.wtc_parse_filas("Mes\tFacturacion UYU\tOrdenes\tLitros\n2025-01\t10\t1\t1", HOY)
    assert errores == [] and [f["mes"] for f in filas] == ["2025-01"]


def test_parse_ignora_lineas_vacias():
    filas, errores = wtc.wtc_parse_filas("\n\n2025-01 10 1 1\n   \n", HOY)
    assert errores == [] and len(filas) == 1


def test_parse_errores_por_linea():
    texto = "\n".join([
        "2025-01 10 1 1",        # ok (línea 1)
        "2024-12 10 1 1",        # antes de 2025-01
        "2026-11 10 1 1",        # después del mes actual (HOY = oct-26)
        "2025-02 -5 1 1",        # negativo
        "2025-03 10 1,5 1",      # órdenes no entera
        "2025-04 10 1",          # faltan columnas
        "2025-01 20 2 2",        # mes repetido
        "abc 10 1 1",            # mes inválido
        "2025-05 diez 1 1",      # número inválido
    ])
    filas, errores = wtc.wtc_parse_filas(texto, HOY)
    assert [e["linea"] for e in errores] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert "2025-01" in errores[0]["error"]
    assert "repetido" in errores[5]["error"]
    assert [f["mes"] for f in filas] == ["2025-01"]


def test_parse_mes_actual_es_valido():
    filas, errores = wtc.wtc_parse_filas("2026-10 10 1 1", HOY)
    assert errores == [] and filas[0]["mes"] == "2026-10"


def test_parse_texto_vacio_da_error():
    filas, errores = wtc.wtc_parse_filas("   \n ", HOY)
    assert filas == [] and errores == [{"linea": 0, "error": "No hay filas para cargar"}]


# ── Tipo de cambio BCRA ──────────────────────────────────────────────────────

from types import SimpleNamespace

import requests

# Forma real verificada 01/10/2026 contra la API BCRA (recortada; oct-26 sintético).
BCRA_PAYLOAD = {
    "status": 200,
    "metadata": {"resultset": {"count": 5, "offset": 0, "limit": 1000}},
    "results": [
        {"fecha": "2026-10-01", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.0248, "tipoCotizacion": 37.70}]},
        {"fecha": "2026-09-30", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024846, "tipoCotizacion": 37.691782}]},
        {"fecha": "2026-09-29", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024837, "tipoCotizacion": 37.801925}]},
        {"fecha": "2026-09-28", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024832, "tipoCotizacion": 37.856965}]},
        {"fecha": "2026-09-25", "detalle": [{"codigoMoneda": "UYU", "descripcion": "PESO URUGUAYO",
                                             "tipoPase": 0.024766, "tipoCotizacion": 37.780942}]},
    ],
}


class FakeBQ:
    """Cliente BigQuery falso: devuelve filas según un fragmento del SQL y registra las llamadas."""
    def __init__(self, respuestas=None, falla=None):
        self.respuestas = respuestas or {}   # {fragmento_sql: [dict, ...]}
        self.falla = falla
        self.llamadas = []

    def query(self, sql, job_config=None):
        self.llamadas.append((sql, job_config))
        if self.falla:
            raise self.falla
        filas = [] if sql.lstrip().upper().startswith("MERGE") else \
            next((v for k, v in self.respuestas.items() if k in sql), [])
        return SimpleNamespace(result=lambda: [SimpleNamespace(**f) for f in filas])


def _merges(fake):
    return [(sql, jc) for sql, jc in fake.llamadas if sql.lstrip().upper().startswith("MERGE")]


def _struct(p):
    """Valores de un StructQueryParameter como dict {campo: valor}."""
    return dict(p.struct_values)


def test_promedio_mensual_promedia_dias_habiles_por_mes():
    p = wtc.promedio_mensual(BCRA_PAYLOAD)
    sep = (37.691782 + 37.801925 + 37.856965 + 37.780942) / 4
    assert p["2026-09"][0] == pytest.approx(sep) and p["2026-09"][1] == 4
    assert p["2026-10"][0] == pytest.approx(37.70) and p["2026-10"][1] == 1


def test_promedio_mensual_ignora_otras_monedas_y_nulos():
    payload = {"results": [
        {"fecha": "2026-09-30", "detalle": [{"codigoMoneda": "USD", "tipoCotizacion": 1400}]},
        {"fecha": "2026-09-29", "detalle": [{"codigoMoneda": "UYU", "tipoCotizacion": None}]},
        {"fecha": "2026-09-28", "detalle": [{"codigoMoneda": "UYU", "tipoCotizacion": 37.0}]},
    ]}
    assert wtc.promedio_mensual(payload) == {"2026-09": (37.0, 1)}


def test_promedio_mensual_payload_vacio():
    assert wtc.promedio_mensual({}) == {}


def test_meses_pendientes_primera_vez_trae_desde_ene25():
    assert wtc.meses_pendientes({}, date(2025, 3, 10)) == ["2025-01", "2025-02", "2025-03"]


def test_meses_pendientes_solo_faltantes_o_incompletos():
    existentes = {"2025-01": True, "2025-02": False, "2025-03": True}
    assert wtc.meses_pendientes(existentes, date(2025, 4, 2)) == ["2025-02", "2025-04"]


def test_descargar_cotizaciones_reintenta_2_veces_y_lanza(monkeypatch):
    intentos = []
    def get(*a, **kw):
        intentos.append(kw.get("timeout"))
        raise requests.ConnectionError("caída")
    monkeypatch.setattr(wtc.requests, "get", get)
    with pytest.raises(RuntimeError, match="BCRA"):
        wtc.descargar_cotizaciones(date(2026, 9, 1), date(2026, 9, 30), espera=0)
    assert len(intentos) == 3 and all(t and t <= 15 for t in intentos)


def test_descargar_cotizaciones_pasa_rango_de_fechas(monkeypatch):
    visto = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return BCRA_PAYLOAD
    def get(url, params=None, timeout=None):
        visto.update(url=url, params=params)
        return R()
    monkeypatch.setattr(wtc.requests, "get", get)
    assert wtc.descargar_cotizaciones(date(2026, 9, 1), date(2026, 10, 1)) == BCRA_PAYLOAD
    assert visto["url"] == wtc.BCRA_URL
    assert visto["params"]["fechadesde"] == "2026-09-01" and visto["params"]["fechahasta"] == "2026-10-01"


def test_actualizar_tc_escribe_meses_pendientes_con_completo(monkeypatch):
    hechos = [f"2025-{i:02d}" for i in range(1, 13)] + [f"2026-{i:02d}" for i in range(1, 9)]
    fake = FakeBQ({"tipo_cambio_uyu_ars": [{"mes": m, "completo": True} for m in hechos]})
    monkeypatch.setattr(wtc, "descargar_cotizaciones", lambda d, h: BCRA_PAYLOAD)
    wtc.actualizar_tipo_cambio_uyu(fake, HOY, log=lambda *_: None)
    (sql, jc), = _merges(fake)
    assert "INSERT (mes, ars_por_uyu, dias, completo, actualizado_en)" in sql
    assert "INSERT ROW" not in sql
    filas = {_struct(p)["mes"]: _struct(p) for p in jc.query_parameters[0].values}
    assert set(filas) == {"2026-09", "2026-10"}
    assert filas["2026-09"]["completo"] is True and filas["2026-09"]["dias"] == 4
    assert filas["2026-10"]["completo"] is False


def test_actualizar_tc_al_dia_no_llama_a_la_api(monkeypatch):
    todos = [f"2025-{i:02d}" for i in range(1, 13)] + [f"2026-{i:02d}" for i in range(1, 11)]
    fake = FakeBQ({"tipo_cambio_uyu_ars": [{"mes": m, "completo": True} for m in todos]})
    monkeypatch.setattr(wtc, "descargar_cotizaciones", lambda d, h: pytest.fail("no debía llamar"))
    wtc.actualizar_tipo_cambio_uyu(fake, HOY, log=lambda *_: None)
    assert _merges(fake) == []


def test_actualizar_tc_api_caida_no_lanza_ni_escribe(monkeypatch):
    # Review Focus #4
    logs = []
    fake = FakeBQ({})
    def caida(d, h): raise RuntimeError("API BCRA sin respuesta")
    monkeypatch.setattr(wtc, "descargar_cotizaciones", caida)
    wtc.actualizar_tipo_cambio_uyu(fake, HOY, log=logs.append)
    assert _merges(fake) == []
    assert any(l.strip().startswith("WARN WTC") for l in logs)


def test_actualizar_tc_bq_caido_no_lanza():
    logs = []
    wtc.actualizar_tipo_cambio_uyu(FakeBQ(falla=RuntimeError("BQ 503")), HOY, log=logs.append)
    assert any("WARN WTC" in l for l in logs)


# ── BigQuery: carga manual ───────────────────────────────────────────────────

def test_guardar_filas_merge_con_columnas_explicitas():
    fake = FakeBQ()
    filas = [{"mes": "2025-01", "facturacion_uyu": 12345678.5, "ordenes": 1200, "litros_cerveza": 3400.5}]
    assert wtc.guardar_filas(fake, filas, "admin@ejemplo.com") == 1
    (sql, jc), = _merges(fake)
    assert "INSERT (mes, facturacion_uyu, ordenes, litros_cerveza, cargado_por, cargado_en)" in sql
    assert "INSERT ROW" not in sql
    params = {p.name: p for p in jc.query_parameters}
    assert params["email"].value == "admin@ejemplo.com"
    assert _struct(params["filas"].values[0]) == {"mes": "2025-01", "facturacion_uyu": "12345678.50",
                                                  "ordenes": 1200, "litros_cerveza": "3400.50"}


def test_guardar_filas_vacio_no_consulta():
    fake = FakeBQ()
    assert wtc.guardar_filas(fake, [], "x@y") == 0 and fake.llamadas == []


def test_leer_carga_convierte_tipos():
    from datetime import datetime, timezone
    from decimal import Decimal
    fake = FakeBQ({"wtc_manual_mensual": [{
        "mes": "2025-01", "facturacion_uyu": Decimal("100.50"), "ordenes": 3,
        "litros_cerveza": Decimal("7.25"), "cargado_por": "a@b",
        "cargado_en": datetime(2026, 10, 1, 12, tzinfo=timezone.utc)}]})
    assert wtc.leer_carga(fake) == [{"mes": "2025-01", "facturacion_uyu": 100.5, "ordenes": 3,
                                     "litros_cerveza": 7.25, "cargado_por": "a@b",
                                     "cargado_en": "2026-10-01T12:00:00+00:00"}]


def test_leer_cotizaciones_devuelve_float_por_mes():
    from decimal import Decimal
    fake = FakeBQ({"tipo_cambio_uyu_ars": [{"mes": "2025-01", "ars_por_uyu": Decimal("23.6")}]})
    assert wtc.leer_cotizaciones(fake) == {"2025-01": 23.6}


# ── incorporar_wtc (tablero retail) ──────────────────────────────────────────

import copy

from actualizar_retail import incorporar_wtc

MENSUAL = [
    {"mes": "2026-08", "m": "Patagonia", "fac": 1000, "ord": 10000, "tick": 100000},
    {"mes": "2026-08", "m": "Temple", "fac": 500, "ord": 5000, "tick": 100000},
    {"mes": "2026-09", "m": "Patagonia", "fac": 1100, "ord": 11000, "tick": 100000},
    {"mes": "2026-10", "m": "Temple", "fac": 50, "ord": 500, "tick": 100000},
]
LOCAL_MENSUAL = [{"mes": "2026-09", "m": "Patagonia", "l": "PALERMO", "fac": 100.0, "ord": 1000}]
LOCALES_OBJ = [
    {"b": "P", "l": "WTC", "d": {"2026-08": [0, 80.0, 0, 9000], "2026-09": [0, 85.0, 0, 9500]}},
    {"b": "P", "l": "PALERMO", "d": {"2026-09": [100.0, 90.0, 1000, 900]}},
]
LOC_COUNT = {"2026-08": {"P": 30, "T": 19, "F": 1}, "2026-09": {"P": 31, "T": 19, "F": 1}}
WTC_DATA = {
    "filas": [{"mes": "2026-08", "facturacion_uyu": 2_000_000.0, "ordenes": 2000, "litros_cerveza": 900.0},
              {"mes": "2026-09", "facturacion_uyu": 2_500_000.0, "ordenes": 2500, "litros_cerveza": 950.0}],
    "cotizaciones": {"2026-08": 36.0, "2026-09": 37.8},
}


def _inc(wtc_data=WTC_DATA, hoy=HOY, mensual=MENSUAL):
    return incorporar_wtc(wtc_data, mensual, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT, hoy)


def test_incorporar_suma_a_patagonia_mensual_con_ticket_ponderado():
    mensual, *_ = _inc()
    ago = next(r for r in mensual if r["mes"] == "2026-08" and r["m"] == "Patagonia")
    fac_M = 2_000_000 * 36.0 / 1e6                      # 72 M ARS
    assert ago["fac"] == round(1000 + fac_M)             # 1072
    assert ago["ord"] == 12000
    assert ago["tick"] == round((100000 * 10000 + fac_M * 1e6) / 12000)
    assert next(r for r in mensual if r["mes"] == "2026-08" and r["m"] == "Temple") == MENSUAL[1]


def test_incorporar_agrega_fila_local_wtc():
    _, local, *_ = _inc()
    assert [r for r in local if r["l"] == "WTC"] == [
        {"mes": "2026-08", "m": "Patagonia", "l": "WTC", "fac": 72.0, "ord": 2000},
        {"mes": "2026-09", "m": "Patagonia", "l": "WTC", "fac": 94.5, "ord": 2500},
    ]


def test_incorporar_completa_real_de_wtc_en_objetivos():
    _, _, obj, *_ = _inc()
    w = next(e for e in obj if e["l"] == "WTC")
    assert w["d"]["2026-08"] == [72.0, 80.0, 2000, 9000]
    assert w["d"]["2026-09"] == [94.5, 85.0, 2500, 9500]


def test_incorporar_cuenta_wtc_como_local_patagonia():
    *_, cnt, _ = _inc()
    assert cnt["2026-08"]["P"] == 31 and cnt["2026-09"]["P"] == 32 and cnt["2026-08"]["T"] == 19


def test_incorporar_mes_sin_cotizacion_se_excluye_y_avisa():
    # Review Focus #4
    data = {"filas": WTC_DATA["filas"], "cotizaciones": {"2026-08": 36.0}}
    mensual, local, obj, cnt, info = _inc(data)
    assert next(r for r in mensual if r["mes"] == "2026-09" and r["m"] == "Patagonia") == MENSUAL[2]
    assert [r["mes"] for r in local if r["l"] == "WTC"] == ["2026-08"]
    assert next(e for e in obj if e["l"] == "WTC")["d"]["2026-09"][0] == 0
    assert cnt["2026-09"]["P"] == 31
    assert info["sin_cotizacion"] == ["2026-09"] and info["meses"] == ["2026-08"]


def test_incorporar_no_crea_meses_fuera_de_mensual():
    # Review Focus #3: oct-26 cargado pero MENSUAL no tiene el mes → no se inventa
    mensual_sin_oct = [r for r in MENSUAL if r["mes"] != "2026-10"]
    data = {"filas": WTC_DATA["filas"] + [{"mes": "2026-10", "facturacion_uyu": 1.0, "ordenes": 1,
                                           "litros_cerveza": 1.0}],
            "cotizaciones": {**WTC_DATA["cotizaciones"], "2026-10": 37.7}}
    mensual, local, *_ = _inc(data, mensual=mensual_sin_oct)
    assert {r["mes"] for r in mensual} == {"2026-08", "2026-09"}
    assert "2026-10" not in {r["mes"] for r in local if r["l"] == "WTC"}


def test_incorporar_mes_existente_sin_fila_patagonia_la_agrega():
    data = {"filas": [{"mes": "2026-10", "facturacion_uyu": 1_000_000.0, "ordenes": 100,
                       "litros_cerveza": 1.0}], "cotizaciones": {"2026-10": 37.7}}
    mensual, *_ = _inc(data)
    pat = [r for r in mensual if r["mes"] == "2026-10" and r["m"] == "Patagonia"]
    assert pat == [{"mes": "2026-10", "m": "Patagonia", "fac": 38, "ord": 100, "tick": 377000}]


def test_incorporar_sin_datos_deja_datasets_intactos():
    for data in (None, {"filas": [], "cotizaciones": {}}):
        mensual, local, obj, cnt, info = _inc(data)
        assert (mensual, local, obj, cnt) == (MENSUAL, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT)
    assert _inc(None)[4]["error"] is True


def test_incorporar_no_muta_entradas():
    antes = copy.deepcopy((MENSUAL, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT))
    _inc()
    assert (MENSUAL, LOCAL_MENSUAL, LOCALES_OBJ, LOC_COUNT) == antes


def test_incorporar_info_avisa_meses_faltantes():
    info = _inc()[4]                                   # HOY = 2026-10-01: sep cargado, oct no
    assert info["ultimo_cerrado"] == "2026-09" and info["falta_ultimo_cerrado"] is False
    assert info["mes_actual"] == "2026-10" and info["falta_mes_actual"] is True
    assert _inc(hoy=date(2026, 11, 3))[4]["falta_ultimo_cerrado"] is True
