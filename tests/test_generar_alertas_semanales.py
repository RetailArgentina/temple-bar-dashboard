from datetime import date, timedelta
from types import SimpleNamespace
import pytest
from generar_alertas_semanales import compute_date_ranges, CONFIG, build_mix_rows, fetch_mix_semanal_por_local, evaluar_regla_mix, evaluar_regla_performance, evaluar_regla_ticket_ordenes


class _FakeJob:
    def __init__(self, sql):
        self.sql = sql

    def result(self):
        return []


class _FakeClient:
    def __init__(self):
        self.last_sql = None

    def query(self, sql):
        self.last_sql = sql
        return _FakeJob(sql)


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


def test_fetch_mix_temple_query_shape():
    client = _FakeClient()
    fetch_mix_semanal_por_local(client, "Temple", "2026-06-01", "2026-08-16")
    sql = client.last_sql
    assert "vw_curated_compilado_ok" in sql
    assert "establecimiento" in sql
    assert "cerveza_total" in sql
    assert "tragos_total" in sql
    assert "GROUP BY local, semana" in sql


def test_fetch_mix_patagonia_query_shape():
    client = _FakeClient()
    fetch_mix_semanal_por_local(client, "Patagonia", "2026-06-01", "2026-08-16")
    sql = client.last_sql
    assert "curated_mix" in sql
    assert "cerveza_total" in sql
    assert "tragos_total" in sql


def test_fetch_mix_feriado_query_shape():
    client = _FakeClient()
    fetch_mix_semanal_por_local(client, "Feriado", "2026-06-01", "2026-08-16")
    sql = client.last_sql
    assert "vw_Ventas_Feriado" in sql
    assert "Categoria_Empresa" in sql


def test_fetch_mix_unknown_marca_raises():
    client = _FakeClient()
    with pytest.raises(ValueError):
        fetch_mix_semanal_por_local(client, "Otra", "2026-06-01", "2026-08-16")


def _rows_semana(local, semana, pct, lts_total=100.0):
    """Helper de test: fila con pct_cerveza dado y volumen total fijo."""
    return {
        "local": local, "semana": semana,
        "lts_cerveza": lts_total * pct, "lts_tragos": lts_total * (1 - pct),
        "pct_cerveza": pct,
    }


def test_mix_ambas_senales_da_alta():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    peers = [_rows_semana("OTRO_A", semana, 0.78), _rows_semana("OTRO_B", semana, 0.79),
             _rows_semana("OTRO_C", semana, 0.80)]
    actual = _rows_semana("MADERO", semana, 0.55)  # cae 25pp vs su historia y vs pares
    hallazgos = evaluar_regla_mix(historia + peers + [actual], "Patagonia", semana, CONFIG)
    assert len(hallazgos) == 1
    h = hallazgos[0]
    assert h["local"] == "MADERO"
    assert h["marca"] == "Patagonia"
    assert h["categoria"] == "Mix producto"
    assert h["severidad"] == "Alta"


def test_mix_solo_senal_propia_da_media():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    # Sin pares (menos de mix_min_locales_peer) -> solo se evalúa self
    actual = _rows_semana("MADERO", semana, 0.60)
    hallazgos = evaluar_regla_mix(historia + [actual], "Patagonia", semana, CONFIG)
    assert len(hallazgos) == 1
    assert hallazgos[0]["severidad"] == "Media"


def test_mix_sin_desvio_no_genera_hallazgo():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    actual = _rows_semana("MADERO", semana, 0.79)
    hallazgos = evaluar_regla_mix(historia + [actual], "Patagonia", semana, CONFIG)
    assert hallazgos == []


def test_mix_bajo_volumen_minimo_se_ignora():
    semana = date(2026, 8, 10)
    actual = _rows_semana("LOCAL_CHICO", semana, 0.10, lts_total=10.0)  # < mix_min_lts_semana
    hallazgos = evaluar_regla_mix([actual], "Feriado", semana, CONFIG)
    assert hallazgos == []


def test_mix_sin_fila_de_la_semana_evaluada_se_ignora():
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=1), 0.80)]
    hallazgos = evaluar_regla_mix(historia, "Patagonia", semana, CONFIG)
    assert hallazgos == []


def test_performance_pace_bajo_da_alta():
    marca_esta = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}
    marca_ant = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}
    objetivos = {"Temple": {"2026-08": 100.0}}
    # pace=0.5 (mitad del mes) -> obj_pace=50, real acumulado 30 -> cumpl 60% (<80)
    hallazgos = evaluar_regla_performance(
        marca_esta, marca_ant, locales_top=[], locales_ant_dict={},
        objetivos=objetivos, mes_key="2026-08", pace=0.5, dias_rest=15,
        config=CONFIG, mes_real={"Temple": {"fac_M": 30.0}},
    )
    pace_h = [h for h in hallazgos if "ritmo" in h["mensaje"]]
    assert len(pace_h) == 1
    assert pace_h[0]["severidad"] == "Alta"
    assert pace_h[0]["categoria"] == "Performance"


def test_performance_caida_local_da_media():
    locales_top = [{"Marca": "Temple", "local": "PALERMO", "fac_M": 4.0, "ordenes": 500}]
    locales_ant_dict = {("Temple", "PALERMO"): 5.0}  # -20% exacto -> Media
    hallazgos = evaluar_regla_performance(
        marca_esta={}, marca_ant={}, locales_top=locales_top,
        locales_ant_dict=locales_ant_dict, objetivos={}, mes_key="2026-08",
        pace=0.5, dias_rest=15, config=CONFIG, mes_real={},
    )
    local_h = [h for h in hallazgos if h["local"] == "PALERMO"]
    assert len(local_h) == 1
    assert local_h[0]["severidad"] == "Media"
    assert local_h[0]["categoria"] == "Performance"


def test_ticket_caida_da_media():
    marca_esta = {"Temple": {"fac_M": 9.0, "ordenes": 1000}}   # ticket = 9000
    marca_ant = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}   # ticket = 10000, cae 10%
    hallazgos = evaluar_regla_ticket_ordenes(marca_esta, marca_ant, CONFIG)
    ticket_h = [h for h in hallazgos if "ticket" in h["mensaje"].lower()]
    assert len(ticket_h) == 1
    assert ticket_h[0]["severidad"] == "Media"
    assert ticket_h[0]["categoria"] == "Ticket/Órdenes"


def test_ordenes_caida_fuerte_da_alta():
    marca_esta = {"Temple": {"fac_M": 8.0, "ordenes": 780}}
    marca_ant = {"Temple": {"fac_M": 10.0, "ordenes": 1000}}  # -22% ordenes
    hallazgos = evaluar_regla_ticket_ordenes(marca_esta, marca_ant, CONFIG)
    ordenes_h = [h for h in hallazgos if "órdenes" in h["mensaje"].lower()]
    assert len(ordenes_h) == 1
    assert ordenes_h[0]["severidad"] == "Alta"


def test_sin_datos_previos_no_rompe():
    hallazgos = evaluar_regla_ticket_ordenes({"Temple": {"fac_M": 5.0, "ordenes": 400}}, {}, CONFIG)
    assert hallazgos == []
