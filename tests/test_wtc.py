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
