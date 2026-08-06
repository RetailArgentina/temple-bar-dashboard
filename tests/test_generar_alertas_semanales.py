from datetime import date, timedelta, datetime
from types import SimpleNamespace
import pytest
from generar_alertas_semanales import compute_date_ranges, CONFIG, build_mix_rows, fetch_mix_semanal_por_local, evaluar_regla_mix, evaluar_regla_performance, evaluar_regla_ticket_ordenes, render_alertas_html


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
    # MADERO: 5 semanas de historia propia a 0.80, pares estables en 0.60
    # esas mismas semanas -> desvio historico de MADERO vs pares = +20pp.
    historia = [_rows_semana("MADERO", semana - timedelta(weeks=i), 0.80) for i in range(1, 6)]
    peers_hist = [_rows_semana(loc, semana - timedelta(weeks=i), 0.60)
                  for i in range(1, 6) for loc in ("OTRO_A", "OTRO_B", "OTRO_C")]
    peers_actual = [_rows_semana("OTRO_A", semana, 0.58), _rows_semana("OTRO_B", semana, 0.60),
                     _rows_semana("OTRO_C", semana, 0.62)]
    actual = _rows_semana("MADERO", semana, 0.55)  # cae 25pp vs su historia propia
    # vs pares: excess_actual = 0.55-0.60=-0.05, excess historico = +0.20 -> desvio_peer=-25pp
    # Nota: con solo 4 locales en total, la caida de MADERO tambien corre un
    # poco el promedio de pares de OTRO_C -- efecto matematico esperado en un
    # universo tan chico (insignificante con las decenas de locales reales
    # por marca), por eso se verifica el hallazgo de MADERO puntualmente en
    # vez de asumir que es el unico de la lista.
    hallazgos = evaluar_regla_mix(historia + peers_hist + peers_actual + [actual], "Patagonia", semana, CONFIG)
    madero_h = [h for h in hallazgos if h["local"] == "MADERO"]
    assert len(madero_h) == 1
    h = madero_h[0]
    assert h["marca"] == "Patagonia"
    assert h["categoria"] == "Mix producto"
    assert h["severidad"] == "Alta"


def test_mix_diferencia_estructural_no_dispara_pares():
    """Un local que SIEMPRE esta ~20pp por debajo de sus pares (mix distinto
    por naturaleza del local) no debe generar hallazgo si esa relacion no
    cambia esta semana -- solo debe alertar cuando el desvio vs pares se
    aparta de lo habitual para ese local, no por existir de por si."""
    semana = date(2026, 8, 10)
    historia = [_rows_semana("MADERO2", semana - timedelta(weeks=i), 0.50) for i in range(1, 6)]
    peers_hist = [_rows_semana(loc, semana - timedelta(weeks=i), 0.70)
                  for i in range(1, 6) for loc in ("OTRO_A", "OTRO_B", "OTRO_C")]
    peers_actual = [_rows_semana("OTRO_A", semana, 0.68), _rows_semana("OTRO_B", semana, 0.70),
                    _rows_semana("OTRO_C", semana, 0.72)]
    actual = _rows_semana("MADERO2", semana, 0.48)  # -2pp vs su historia, y sigue ~20pp bajo pares (sin cambio)
    hallazgos = evaluar_regla_mix(historia + peers_hist + peers_actual + [actual], "Patagonia", semana, CONFIG)
    assert hallazgos == []


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
    locales_top = [{"Marca": "Temple", "local": "PALERMO", "fac_M": 6.5, "ordenes": 500}]
    locales_ant_dict = {("Temple", "PALERMO"): 10.0}  # -35% exacto -> Media
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


def test_render_sin_hallazgos_muestra_estado_explicito():
    html = render_alertas_html([], date(2026, 8, 10), date(2026, 8, 16), datetime(2026, 8, 17, 6, 30))
    assert "Sin hallazgos relevantes esta semana" in html


def test_render_agrupa_por_severidad_alta_primero():
    hallazgos = [
        {"marca": "Temple", "local": None, "categoria": "Performance", "severidad": "Media",
         "mensaje": "Mensaje media", "detalle": "Detalle media"},
        {"marca": "Patagonia", "local": "MADERO", "categoria": "Mix producto", "severidad": "Alta",
         "mensaje": "Mensaje alta", "detalle": "Detalle alta"},
    ]
    html = render_alertas_html(hallazgos, date(2026, 8, 10), date(2026, 8, 16), datetime(2026, 8, 17, 6, 30))
    pos_alta = html.index("Mensaje alta")
    pos_media = html.index("Mensaje media")
    assert pos_alta < pos_media
    assert "Mix producto" in html
    assert "10/08/2026" in html and "16/08/2026" in html


def test_main_no_upload_genera_archivo_local(tmp_path, monkeypatch):
    import os
    from unittest.mock import patch

    output_path = tmp_path / "alertas_test.html"
    monkeypatch.chdir(tmp_path)

    with patch("generar_alertas_semanales.get_client", return_value=object()), \
         patch("generar_alertas_semanales.fetch_semana", return_value=[]), \
         patch("generar_alertas_semanales.fetch_mes_actual", return_value={}), \
         patch("generar_alertas_semanales.fetch_objetivos", return_value={}), \
         patch("generar_alertas_semanales.fetch_mix_semanal_por_local", return_value=[]), \
         patch("sys.argv", ["generar_alertas_semanales.py",
                             "--semana", "2026-08-10",
                             "--output", str(output_path),
                             "--no-upload"]):
        import generar_alertas_semanales
        generar_alertas_semanales.main()

    assert output_path.exists()
    contenido = output_path.read_text(encoding="utf-8")
    assert "Alertas Semanales de Negocio" in contenido
    assert "Sin hallazgos relevantes esta semana" in contenido


def test_main_no_upload_con_hallazgos_reales(tmp_path, monkeypatch):
    """Test de integración completa: verifica que main() genera hallazgos reales
    de las 3 categorías (Performance, Ticket/Órdenes, Mix producto) cuando hay
    datos que los disparan."""
    import os
    from unittest.mock import patch
    from datetime import date, timedelta

    output_path = tmp_path / "alertas_test_hallazgos.html"
    monkeypatch.chdir(tmp_path)

    semana_eval = date(2026, 8, 3)

    # === PERFORMANCE: pace bajo (cumpl_pace < 80 → Alta) ===
    # Cálculo con semana 2026-08-03, hoy=2026-08-06:
    # pace = 6/31 ≈ 0.194, obj_M=165 → obj_pace=32.0, real_M=25 → cumpl_pace=78.1% (<80)
    marca_esta = {"Temple": {"fac_M": 25.0, "ordenes": 1000}}
    marca_ant = {"Temple": {"fac_M": 30.0, "ordenes": 1100}}
    locales_top = []  # Sin caída de locales para simplificar
    locales_ant_dict = {}
    objetivos = {"Temple": {"2026-08": 165.0}}
    mes_real = {"Temple": {"fac_M": 25.0}}

    # === TICKET/ÓRDENES: caída fuerte de órdenes (dp_o < -20 → Alta) ===
    # Cálculo: esta_semana=775, ant_semana=1000 → dp_o=-22.5%
    marca_esta["Temple"]["ordenes"] = 775
    marca_ant["Temple"]["ordenes"] = 1000

    # === MIX PRODUCTO: desvío de pct_cerveza (ambas señales → Alta) ===
    # Historia de MADERO: 80% en 4-5 semanas previas
    # Actual: 55% → desvio_self = -25pp (|desvio_self| >= 15 → flagea)
    # Peers: promedio ~79% → desvio_peer = -24pp (|desvio_peer| >= 10 → flagea)
    mix_rows_temple = [
        SimpleNamespace(local="MADERO", semana=semana_eval - timedelta(weeks=5), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=semana_eval - timedelta(weeks=4), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=semana_eval - timedelta(weeks=3), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=semana_eval - timedelta(weeks=2), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=semana_eval - timedelta(weeks=1), lts_cerveza=80.0, lts_tragos=20.0),
        SimpleNamespace(local="MADERO", semana=semana_eval, lts_cerveza=55.0, lts_tragos=45.0),  # cae a 55%
        # Pares para la semana evaluada (mix_min_locales_peer=3)
        SimpleNamespace(local="OTRO_A", semana=semana_eval, lts_cerveza=78.0, lts_tragos=22.0),
        SimpleNamespace(local="OTRO_B", semana=semana_eval, lts_cerveza=79.0, lts_tragos=21.0),
        SimpleNamespace(local="OTRO_C", semana=semana_eval, lts_cerveza=80.0, lts_tragos=20.0),
    ]

    # Mock de fetch_mix_semanal_por_local: devuelve datos de Mix para Temple, vacío para Patagonia/Feriado
    def fetch_mix_mock(client, marca, desde, hasta):
        if marca == "Temple":
            return mix_rows_temple
        return []

    # Mock de agg_por_marca y agg_por_local
    call_count = {"agg_marca": 0}
    def agg_marca_mock(rows):
        call_count["agg_marca"] += 1
        return marca_esta if call_count["agg_marca"] == 1 else marca_ant

    def agg_local_mock(rows):
        return locales_top

    with patch("generar_alertas_semanales.get_client", return_value=object()), \
         patch("generar_alertas_semanales.fetch_semana", return_value=[]), \
         patch("generar_alertas_semanales.agg_por_marca", side_effect=agg_marca_mock), \
         patch("generar_alertas_semanales.agg_por_local", side_effect=agg_local_mock), \
         patch("generar_alertas_semanales.fetch_mes_actual", return_value=mes_real), \
         patch("generar_alertas_semanales.fetch_objetivos", return_value=objetivos), \
         patch("generar_alertas_semanales.fetch_mix_semanal_por_local", side_effect=fetch_mix_mock), \
         patch("sys.argv", ["generar_alertas_semanales.py",
                             "--semana", "2026-08-03",
                             "--output", str(output_path),
                             "--no-upload"]):
        import generar_alertas_semanales
        generar_alertas_semanales.main()

    assert output_path.exists()
    contenido = output_path.read_text(encoding="utf-8")

    # Verificaciones: debe haber hallazgos de las 3 categorías
    assert "Performance" in contenido, "Falta categoría Performance"
    assert "Mix producto" in contenido, "Falta categoría Mix producto"
    assert "Ticket/Órdenes" in contenido, "Falta categoría Ticket/Órdenes"
    assert "Sin hallazgos relevantes esta semana" not in contenido, "No debería haber mensaje de sin hallazgos"
    # Verificar que hay al menos una severidad Alta
    assert "Alta" in contenido, "Debería haber al menos un hallazgo de severidad Alta"
