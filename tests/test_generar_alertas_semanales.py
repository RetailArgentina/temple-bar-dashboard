from datetime import date
from types import SimpleNamespace
from generar_alertas_semanales import compute_date_ranges, CONFIG, build_mix_rows


def test_compute_date_ranges_mid_month():
    # Lunes 10/08/2026, hoy = 12/08/2026 (miércoles de esa misma semana)
    r = compute_date_ranges(date(2026, 8, 10), hoy=date(2026, 8, 12))
    assert r["semana_inicio"] == date(2026, 8, 10)
    assert r["semana_fin"] == date(2026, 8, 16)
    assert r["sem_ant_ini"] == date(2026, 8, 3)
    assert r["sem_ant_fin"] == date(2026, 8, 9)
    assert r["mes_inicio"] == date(2026, 8, 1)
    assert r["mes_key"] == "2026-08"
    assert r["dias_mes_total"] == 31
    # hasta_mes = min(hoy, semana_fin) = 12/08 -> dias_mes_trans = 12
    assert r["dias_mes_trans"] == 12
    assert round(r["pace"], 4) == round(12 / 31, 4)
    assert r["dias_rest"] == 31 - 12


def test_compute_date_ranges_month_rollover_december():
    r = compute_date_ranges(date(2026, 12, 28), hoy=date(2026, 12, 30))
    assert r["mes_inicio"] == date(2026, 12, 1)
    assert r["dias_mes_total"] == 31


def test_config_has_required_thresholds():
    assert CONFIG["mix_desvio_self_pp"] == 15
    assert CONFIG["mix_desvio_peer_pp"] == 10
    assert CONFIG["mix_min_lts_semana"] == 50
    assert CONFIG["mix_min_semanas_historia"] == 4
    assert CONFIG["mix_min_locales_peer"] == 3


def test_build_mix_rows_computes_pct():
    raw = [
        SimpleNamespace(local="MADERO", semana=date(2026, 8, 10), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=date(2026, 8, 3), lts_cerveza=90.0, lts_tragos=10.0),
    ]
    rows = build_mix_rows(raw)
    assert len(rows) == 2
    assert rows[0]["local"] == "MADERO"
    assert rows[0]["semana"] == date(2026, 8, 10)
    assert rows[0]["pct_cerveza"] == 0.8
    assert rows[1]["pct_cerveza"] == 0.9


def test_build_mix_rows_skips_empty_local():
    raw = [SimpleNamespace(local="", semana=date(2026, 8, 10), lts_cerveza=10.0, lts_tragos=5.0)]
    assert build_mix_rows(raw) == []


def test_build_mix_rows_pct_none_when_no_volume():
    raw = [SimpleNamespace(local="X", semana=date(2026, 8, 10), lts_cerveza=0.0, lts_tragos=0.0)]
    rows = build_mix_rows(raw)
    assert rows[0]["pct_cerveza"] is None
