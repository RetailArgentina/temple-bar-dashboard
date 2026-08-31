"""
tests/test_actualizar_retail_helpers.py — Tests para helpers puros de actualizar_retail.py

Cubre:
- _prev_month: mes anterior
- _yoy_month: mismo mes año anterior
- _months_range: lista de N meses consecutivos
- compute_top10: top-10 locales por período
- compute_pd: objeto PD con rangos dinámicos
- compute_preset_meses: períodos preestablecidos
"""
import pytest


# ---------------------------------------------------------------------------
# _prev_month
# ---------------------------------------------------------------------------

def test_prev_month_january_wraps_to_december():
    """_prev_month de enero del año actual devuelve diciembre del año anterior"""
    from actualizar_retail import _prev_month
    result = _prev_month("2026-01")
    assert result == "2025-12"


def test_prev_month_regular_months():
    """_prev_month de meses regulares devuelve el mes anterior"""
    from actualizar_retail import _prev_month
    assert _prev_month("2026-06") == "2026-05"
    assert _prev_month("2026-02") == "2026-01"
    assert _prev_month("2026-12") == "2026-11"


def test_prev_month_format_is_yyyy_mm():
    """_prev_month devuelve formato YYYY-MM"""
    from actualizar_retail import _prev_month
    result = _prev_month("2026-03")
    assert len(result) == 7
    assert result[4] == "-"
    assert result[:4] == "2026"


# ---------------------------------------------------------------------------
# _yoy_month
# ---------------------------------------------------------------------------

def test_yoy_month_same_month_previous_year():
    """_yoy_month devuelve el mismo mes del año anterior"""
    from actualizar_retail import _yoy_month
    result = _yoy_month("2026-06")
    assert result == "2025-06"


def test_yoy_month_january():
    """_yoy_month de enero devuelve enero del año anterior"""
    from actualizar_retail import _yoy_month
    result = _yoy_month("2026-01")
    assert result == "2025-01"


def test_yoy_month_december():
    """_yoy_month de diciembre devuelve diciembre del año anterior"""
    from actualizar_retail import _yoy_month
    result = _yoy_month("2026-12")
    assert result == "2025-12"


def test_yoy_month_preserves_zero_padding():
    """_yoy_month preserva el formato MM con zero-padding"""
    from actualizar_retail import _yoy_month
    result = _yoy_month("2026-03")
    assert result == "2025-03"
    result = _yoy_month("2026-09")
    assert result == "2025-09"


# ---------------------------------------------------------------------------
# _months_range
# ---------------------------------------------------------------------------

def test_months_range_single_month():
    """_months_range con count=1 devuelve solo el mes final"""
    from actualizar_retail import _months_range
    result = _months_range("2026-06", 1)
    assert result == ["2026-06"]


def test_months_range_three_months():
    """_months_range(end_mes, 3) devuelve 3 meses consecutivos acabando en end_mes"""
    from actualizar_retail import _months_range
    result = _months_range("2026-06", 3)
    assert result == ["2026-04", "2026-05", "2026-06"]


def test_months_range_six_months():
    """_months_range(end_mes, 6) devuelve 6 meses"""
    from actualizar_retail import _months_range
    result = _months_range("2026-06", 6)
    assert result == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


def test_months_range_wraps_year_boundary():
    """_months_range maneja correctamente el cambio de año"""
    from actualizar_retail import _months_range
    result = _months_range("2026-02", 3)
    assert result == ["2025-12", "2026-01", "2026-02"]


def test_months_range_is_ordered():
    """_months_range devuelve meses en orden cronológico ascendente"""
    from actualizar_retail import _months_range
    result = _months_range("2026-06", 4)
    assert result == sorted(result)


# ---------------------------------------------------------------------------
# compute_top10
# ---------------------------------------------------------------------------

def test_compute_top10_with_minimal_data():
    """compute_top10 funciona con datos mínimos"""
    from actualizar_retail import compute_top10
    base_rows = [
        {"mes": "2026-06", "m": "Temple", "l": "Local A", "fac": 100, "ord": 10, "tot": 500.0},
    ]
    result = compute_top10(base_rows, "2026-06")
    assert isinstance(result, list)
    assert len(result) > 0


def test_compute_top10_ticket_zero_when_no_orders():
    """compute_top10 devuelve ticket=0 cuando ord=0 (evita división por cero)"""
    from actualizar_retail import compute_top10
    base_rows = [
        {"mes": "2026-06", "m": "Temple", "l": "Local B", "fac": 50, "ord": 0, "tot": 0.0},
    ]
    result = compute_top10(base_rows, "2026-06")
    # Buscar el resultado para Local B
    for r in result:
        if r["l"] == "Local B":
            assert r["tick"] == 0


def test_compute_top10_aggregates_by_period():
    """compute_top10 devuelve múltiples períodos (mes_actual, mes_anterior, ultimos_3m, ultimos_6m)"""
    from actualizar_retail import compute_top10
    base_rows = [
        {"mes": "2026-06", "m": "Temple", "l": "Local A", "fac": 100, "ord": 10, "tot": 500.0},
        {"mes": "2026-05", "m": "Temple", "l": "Local A", "fac": 90, "ord": 9, "tot": 450.0},
    ]
    result = compute_top10(base_rows, "2026-06")
    periods = {r["p"] for r in result}
    assert "mes_actual" in periods
    assert "mes_anterior" in periods


def test_compute_top10_sorts_by_facturacion_descending():
    """compute_top10 ordena locales por facturación descendente dentro de cada marca"""
    from actualizar_retail import compute_top10
    base_rows = [
        {"mes": "2026-06", "m": "Temple", "l": "Local A", "fac": 100, "ord": 10, "tot": 500.0},
        {"mes": "2026-06", "m": "Temple", "l": "Local B", "fac": 200, "ord": 20, "tot": 1000.0},
        {"mes": "2026-06", "m": "Temple", "l": "Local C", "fac": 150, "ord": 15, "tot": 750.0},
    ]
    result = compute_top10(base_rows, "2026-06")
    # Filtrar solo mes_actual y marca Temple
    mes_actual_temple = [r for r in result if r["p"] == "mes_actual" and r["m"] == "Temple"]
    # Verificar que están ordenados por facturación descendente
    facs = [r["fac"] for r in mes_actual_temple]
    assert facs == sorted(facs, reverse=True)


# ---------------------------------------------------------------------------
# compute_pd
# ---------------------------------------------------------------------------

def test_compute_pd_with_empty_data():
    """compute_pd con datos vacíos devuelve dict vacío"""
    from actualizar_retail import compute_pd
    result = compute_pd([])
    assert result == {}


def test_compute_pd_keys_match_expected():
    """compute_pd devuelve las keys esperadas: todo, mes_actual, mes_anterior, ultimos_3m, ultimos_6m, ytd"""
    from actualizar_retail import compute_pd
    mensual_rows = [
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_pd(mensual_rows)
    expected_keys = {"todo", "mes_actual", "mes_anterior", "ultimos_3m", "ultimos_6m", "ytd"}
    assert set(result.keys()) == expected_keys


def test_compute_pd_has_label_and_meses():
    """compute_pd devuelve dicts con 'label', 'meses', 'prevMeses', 'yoyMeses'"""
    from actualizar_retail import compute_pd
    mensual_rows = [
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_pd(mensual_rows)
    for periodo, data in result.items():
        assert "label" in data
        assert "meses" in data
        assert "prevMeses" in data
        assert "yoyMeses" in data


def test_compute_pd_mes_actual_references_latest():
    """compute_pd mes_actual contiene el mes más reciente"""
    from actualizar_retail import compute_pd
    mensual_rows = [
        {"mes": "2026-04", "m": "Temple", "fac": 50, "ord": 5, "tick": 400},
        {"mes": "2026-05", "m": "Temple", "fac": 75, "ord": 7, "tick": 450},
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_pd(mensual_rows)
    assert result["mes_actual"]["meses"] == ["2026-06"]


def test_compute_pd_ytd_filters_by_current_year():
    """compute_pd ytd contiene solo meses del año actual"""
    from actualizar_retail import compute_pd
    mensual_rows = [
        {"mes": "2025-12", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
        {"mes": "2026-01", "m": "Temple", "fac": 110, "ord": 11, "tick": 510},
        {"mes": "2026-02", "m": "Temple", "fac": 120, "ord": 12, "tick": 520},
        {"mes": "2026-06", "m": "Temple", "fac": 150, "ord": 15, "tick": 550},
    ]
    result = compute_pd(mensual_rows)
    ytd_meses = result["ytd"]["meses"]
    assert all(m.startswith("2026") for m in ytd_meses)
    assert "2025-12" not in ytd_meses


# ---------------------------------------------------------------------------
# compute_preset_meses
# ---------------------------------------------------------------------------

def test_compute_preset_meses_with_empty_data():
    """compute_preset_meses con datos vacíos devuelve dict vacío"""
    from actualizar_retail import compute_preset_meses
    result = compute_preset_meses([])
    assert result == {}


def test_compute_preset_meses_keys_match_expected():
    """compute_preset_meses devuelve las keys esperadas"""
    from actualizar_retail import compute_preset_meses
    mensual_rows = [
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_preset_meses(mensual_rows)
    expected_keys = {"todo", "mes_actual", "mes_anterior", "ultimos_3m", "ultimos_6m", "ytd"}
    assert set(result.keys()) == expected_keys


def test_compute_preset_meses_values_are_lists():
    """compute_preset_meses devuelve listas [from_mes, to_mes]"""
    from actualizar_retail import compute_preset_meses
    mensual_rows = [
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_preset_meses(mensual_rows)
    for periodo, value in result.items():
        assert isinstance(value, list)
        assert len(value) == 2


def test_compute_preset_meses_mes_actual_range():
    """compute_preset_meses mes_actual devuelve [latest, latest]"""
    from actualizar_retail import compute_preset_meses
    mensual_rows = [
        {"mes": "2026-04", "m": "Temple", "fac": 50, "ord": 5, "tick": 400},
        {"mes": "2026-05", "m": "Temple", "fac": 75, "ord": 7, "tick": 450},
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_preset_meses(mensual_rows)
    assert result["mes_actual"] == ["2026-06", "2026-06"]


def test_compute_preset_meses_ultimos_3m_correct_range():
    """compute_preset_meses ultimos_3m devuelve [first_of_3, latest]"""
    from actualizar_retail import compute_preset_meses
    mensual_rows = [
        {"mes": "2026-01", "m": "Temple", "fac": 10, "ord": 1, "tick": 400},
        {"mes": "2026-04", "m": "Temple", "fac": 50, "ord": 5, "tick": 400},
        {"mes": "2026-05", "m": "Temple", "fac": 75, "ord": 7, "tick": 450},
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_preset_meses(mensual_rows)
    assert result["ultimos_3m"] == ["2026-04", "2026-06"]


def test_compute_preset_meses_todo_spans_all():
    """compute_preset_meses todo devuelve [first_mes, latest_mes]"""
    from actualizar_retail import compute_preset_meses
    mensual_rows = [
        {"mes": "2026-01", "m": "Temple", "fac": 10, "ord": 1, "tick": 400},
        {"mes": "2026-03", "m": "Temple", "fac": 30, "ord": 3, "tick": 420},
        {"mes": "2026-06", "m": "Temple", "fac": 100, "ord": 10, "tick": 500},
    ]
    result = compute_preset_meses(mensual_rows)
    assert result["todo"] == ["2026-01", "2026-06"]
