"""tests/test_ipc_indec.py — IPC INDEC para la pestaña Finanzas (red y GCS simulados)."""
from datetime import date

import pytest
import requests

import ipc_indec

HOY = date(2026, 9, 28)


def _series(general=None, rubro=None):
    return {
        "general": general or {"2026-06": 100.0, "2026-07": 102.0, "2026-08": 104.04},
        "rubro": rubro or {"2026-06": 200.0, "2026-07": 202.0, "2026-08": 204.02},
    }


def test_parse_respuesta_arma_series_por_mes_e_ignora_nulos():
    payload = {"data": [["2026-07-01", 100.5, 200.5], ["2026-08-01", 101.0, None]]}
    s = ipc_indec.parse_respuesta(payload)
    assert s == {"general": {"2026-07": 100.5, "2026-08": 101.0}, "rubro": {"2026-07": 200.5}}


def test_validar_rechaza_serie_vacia():
    with pytest.raises(ValueError, match="vacía"):
        ipc_indec.validar({"general": {}, "rubro": {"2026-08": 1.0}}, HOY)


def test_validar_rechaza_indice_que_baja():
    s = _series(general={"2026-07": 102.0, "2026-08": 101.0})
    with pytest.raises(ValueError, match="baja"):
        ipc_indec.validar(s, HOY)


def test_validar_avisa_si_el_ultimo_dato_tiene_mas_de_3_meses():
    s = _series(general={"2026-04": 100.0, "2026-05": 101.0})
    avisos = ipc_indec.validar(s, HOY)
    assert len(avisos) == 1 and avisos[0].startswith("FALLÓ IPC desactualizado: general")


def test_validar_sin_avisos_con_datos_al_dia():
    assert ipc_indec.validar(_series(), HOY) == []


def test_completar_estimados_repite_la_ultima_variacion_mensual():
    completas, estimados = ipc_indec.completar_estimados(_series(), "2026-10")
    assert estimados == ["2026-09", "2026-10"]
    assert completas["general"]["2026-09"] == pytest.approx(104.04 * 1.02, rel=1e-6)
    assert completas["general"]["2026-10"] == pytest.approx(104.04 * 1.02 ** 2, rel=1e-6)
    assert completas["general"]["2026-08"] == 104.04  # lo publicado no cambia


def test_construir_payload_base_es_ultimo_mes_publicado_y_completa_hasta_diciembre():
    p = ipc_indec.construir_payload(_series(), HOY, "api")
    assert p["base"] == "2026-08"
    assert p["estimados"] == ["2026-09", "2026-10", "2026-11", "2026-12"]
    assert "2026-12" in p["general"] and "2026-12" in p["rubro"]
    assert p["fuente"] == "api"


def test_descargar_reintenta_y_devuelve_series(monkeypatch):
    llamadas = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [["2026-08-01", 104.0, 204.0]]}

    def fake_get(url, params, timeout):
        llamadas.append(params)
        if len(llamadas) < 3:
            raise requests.ConnectionError("caída")
        return Resp()

    monkeypatch.setattr(ipc_indec.requests, "get", fake_get)
    s = ipc_indec.descargar(espera=0)
    assert len(llamadas) == 3
    assert llamadas[0]["ids"] == "148.3_INIVELNAL_DICI_M_26,146.3_IRESTAUNAL_DICI_M_33"
    assert s == {"general": {"2026-08": 104.0}, "rubro": {"2026-08": 204.0}}


def test_descargar_falla_despues_de_3_intentos(monkeypatch):
    def fake_get(url, params, timeout):
        raise requests.ConnectionError("caída")

    monkeypatch.setattr(ipc_indec.requests, "get", fake_get)
    with pytest.raises(RuntimeError, match="API IPC sin respuesta"):
        ipc_indec.descargar(espera=0)


def test_obtener_ipc_api_ok_guarda_cache(monkeypatch):
    guardado = {}
    monkeypatch.setattr(ipc_indec, "descargar", lambda: _series())
    monkeypatch.setattr(ipc_indec, "_guardar_cache", lambda b, s: guardado.update(b=b, s=s))
    p = ipc_indec.obtener_ipc("bucket-x", HOY, log=lambda *_: None)
    assert p["fuente"] == "api" and p["base"] == "2026-08"
    assert guardado == {"b": "bucket-x", "s": _series()}


def test_obtener_ipc_sin_bucket_no_toca_gcs(monkeypatch):
    monkeypatch.setattr(ipc_indec, "descargar", lambda: _series())

    def no_llamar(*a):
        raise AssertionError("no debe tocar GCS")

    monkeypatch.setattr(ipc_indec, "_guardar_cache", no_llamar)
    monkeypatch.setattr(ipc_indec, "_leer_cache", no_llamar)
    assert ipc_indec.obtener_ipc("", HOY, log=lambda *_: None)["fuente"] == "api"


def test_obtener_ipc_api_caida_usa_cache(monkeypatch):
    logs = []

    def caida():
        raise RuntimeError("API IPC sin respuesta")

    monkeypatch.setattr(ipc_indec, "descargar", caida)
    monkeypatch.setattr(ipc_indec, "_leer_cache", lambda b: _series())
    p = ipc_indec.obtener_ipc("bucket-x", HOY, log=logs.append)
    assert p["fuente"] == "cache"
    assert any("FALLÓ IPC API" in l for l in logs)


def test_obtener_ipc_datos_invalidos_de_api_usan_cache_y_no_se_guardan(monkeypatch):
    monkeypatch.setattr(ipc_indec, "descargar",
                        lambda: _series(general={"2026-07": 102.0, "2026-08": 101.0}))

    def no_guardar(*a):
        raise AssertionError("no debe guardar datos inválidos")

    monkeypatch.setattr(ipc_indec, "_guardar_cache", no_guardar)
    monkeypatch.setattr(ipc_indec, "_leer_cache", lambda b: _series())
    assert ipc_indec.obtener_ipc("bucket-x", HOY, log=lambda *_: None)["fuente"] == "cache"


def test_obtener_ipc_sin_api_ni_cache_devuelve_none(monkeypatch):
    logs = []

    def caida():
        raise RuntimeError("API IPC sin respuesta")

    monkeypatch.setattr(ipc_indec, "descargar", caida)
    monkeypatch.setattr(ipc_indec, "_leer_cache", lambda b: None)
    assert ipc_indec.obtener_ipc("bucket-x", HOY, log=logs.append) is None
    assert any("sin cache" in l for l in logs)


def test_obtener_ipc_falla_al_guardar_cache_no_rompe(monkeypatch):
    monkeypatch.setattr(ipc_indec, "descargar", lambda: _series())

    def falla(*a):
        raise OSError("sin permisos")

    monkeypatch.setattr(ipc_indec, "_guardar_cache", falla)
    assert ipc_indec.obtener_ipc("bucket-x", HOY, log=lambda *_: None)["fuente"] == "api"


def test_variaciones_mensuales_en_porcentaje_desde_el_indice():
    p = {"general": {"2026-06": 100.0, "2026-07": 102.0, "2026-08": 104.04, "2026-09": 106.1208}}
    assert ipc_indec.variaciones_mensuales(p) == {"2026-07": 2.0, "2026-08": 2.0, "2026-09": 2.0}


def test_variaciones_mensuales_sin_payload_es_vacio():
    assert ipc_indec.variaciones_mensuales(None) == {}
