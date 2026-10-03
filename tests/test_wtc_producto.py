"""tests/test_wtc_producto.py — litros de WTC (Uruguay) en la pestaña Producto."""
import copy
from datetime import date

import generar_preview_producto as gp

HOY = date(2026, 10, 3)


def _marca(lts_c=100.0, total=150.0, **kw):
    d = {"total_fac": 1000, "total_lts": total, "lts_cerveza": lts_c, "lts_gin": 5.0,
         "mix": [{"mix": "Bebida", "fac": 1000}], "ranking": [{"producto": "IPA", "facturacion": 1000}],
         "vs_ant_pct": 5.0, "n_productos": 1,
         "locales": [{"local": "PALERMO", "marca": "Patagonia", "lts_cerveza": 80.0, "lts_total": 120.0}]}
    d.update(kw)
    return d


def _result():
    r = {"TEMPLE": _marca(), "PATAGONIA": _marca(), "FERIADO": _marca(), "TODAS": _marca(300.0, 450.0)}
    # Igual que fetch_all: TODAS comparte los dicts de locales de cada marca
    r["TODAS"]["locales"] = r["PATAGONIA"]["locales"] + r["TEMPLE"]["locales"]
    return r


def _w(*pares):
    return [{"mes": m, "litros_cerveza": l} for m, l in pares]


def test_suma_litros_a_patagonia_y_todas():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    assert r["PATAGONIA"]["lts_cerveza"] == 600.0 and r["PATAGONIA"]["total_lts"] == 650.0
    assert r["TODAS"]["lts_cerveza"] == 800.0 and r["TODAS"]["total_lts"] == 950.0
    assert r["TEMPLE"] == _marca() and r["FERIADO"] == _marca()
    assert r["wtc"] == {"lts": 500.0, "meses_incluidos": ["2026-09"], "meses_faltantes": [], "error": False}


def test_mes_fuera_de_rango_no_suma():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-08", 400.0), ("2026-09", 500.0)),
                                   "2026-09-01", "2026-09-30", HOY)
    assert r["wtc"]["lts"] == 500.0 and r["wtc"]["meses_incluidos"] == ["2026-09"]


def test_mes_en_curso_cargado_suma_y_sin_cargar_no_es_faltante():
    con = gp.incorporar_wtc_producto(_result(), _w(("2026-10", 70.0)), "2026-10-01", "2026-10-03", HOY)
    assert con["wtc"]["lts"] == 70.0 and con["PATAGONIA"]["lts_cerveza"] == 170.0
    sin = gp.incorporar_wtc_producto(_result(), [], "2026-10-01", "2026-10-03", HOY)
    assert sin["wtc"]["meses_faltantes"] == []


def test_faltantes_solo_meses_cerrados_desde_2025_01():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-07", 10.0)), "2024-11-01", "2026-10-03", HOY)
    falt = r["wtc"]["meses_faltantes"]
    assert falt[0] == "2025-01" and falt[-1] == "2026-09"
    assert "2026-07" not in falt and "2026-10" not in falt and "2024-12" not in falt


def test_faltantes_cruzan_cambio_de_anio():
    r = gp.incorporar_wtc_producto(_result(), _w(("2025-12", 10.0)), "2025-11-01", "2026-02-28", HOY)
    assert r["wtc"]["meses_faltantes"] == ["2025-11", "2026-01", "2026-02"]


def test_sin_filas_deja_datos_intactos():
    r = gp.incorporar_wtc_producto(_result(), [], "2026-09-01", "2026-09-30", HOY)
    base = _result()
    for m in ("PATAGONIA", "TODAS"):
        assert r[m] == base[m]
    assert r["wtc"]["lts"] == 0 and r["wtc"]["error"] is False


def test_error_de_lectura_marca_error_y_no_suma():
    r = gp.incorporar_wtc_producto(_result(), None, "2026-09-01", "2026-09-30", HOY)
    assert r["PATAGONIA"] == _result()["PATAGONIA"]
    assert r["wtc"] == {"lts": 0, "meses_incluidos": [], "meses_faltantes": [], "error": True}


def test_patagonia_sin_acceso_no_se_toca_pero_todas_si():
    res = _result()
    res["PATAGONIA"] = {"total_lts": 0, "lts_cerveza": 0, "locales": [], "sin_acceso": True}
    r = gp.incorporar_wtc_producto(res, _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    assert r["PATAGONIA"]["lts_cerveza"] == 0 and r["PATAGONIA"]["locales"] == []
    assert r["TODAS"]["lts_cerveza"] == 800.0


def test_wtc_entra_en_locales_ordenado():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    pat = r["PATAGONIA"]["locales"]
    assert pat[0] == {"local": "WTC", "marca": "Patagonia", "lts_cerveza": 500.0, "lts_gin": 0,
                      "lts_fernet": 0, "lts_feriado": 0, "lts_tragos": 0, "lts_total": 500.0}
    assert [l["local"] for l in r["TODAS"]["locales"]].count("WTC") == 1
    assert r["TODAS"]["locales"][0]["local"] == "WTC"


def test_fila_wtc_no_compartida_entre_marcas():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    w_pat = next(l for l in r["PATAGONIA"]["locales"] if l["local"] == "WTC")
    w_tod = next(l for l in r["TODAS"]["locales"] if l["local"] == "WTC")
    assert w_pat is not w_tod
    assert [l["local"] for l in r["PATAGONIA"]["locales"]].count("WTC") == 1


def test_litros_cero_no_agrega_fila():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 0.0)), "2026-09-01", "2026-09-30", HOY)
    assert all(l["local"] != "WTC" for l in r["PATAGONIA"]["locales"])
    assert r["PATAGONIA"]["total_lts"] == 150.0 and r["wtc"]["meses_incluidos"] == ["2026-09"]


def test_no_toca_facturacion_mix_ranking_ni_delta():
    r = gp.incorporar_wtc_producto(_result(), _w(("2026-09", 500.0)), "2026-09-01", "2026-09-30", HOY)
    for m in ("PATAGONIA", "TODAS"):
        base = _result()[m]
        for k in ("total_fac", "mix", "ranking", "vs_ant_pct", "n_productos", "lts_gin"):
            assert r[m][k] == base[k]


def test_no_muta_filas_wtc():
    filas = _w(("2026-09", 500.0))
    antes = copy.deepcopy(filas)
    gp.incorporar_wtc_producto(_result(), filas, "2026-09-01", "2026-09-30", HOY)
    assert filas == antes


def test_fetch_wtc_litros_mapea_filas(monkeypatch):
    import wtc
    monkeypatch.setattr(wtc, "leer_carga", lambda c: [
        {"mes": "2026-09", "facturacion_uyu": 1.0, "ordenes": 1, "litros_cerveza": 500.0,
         "cargado_por": "x", "cargado_en": None}])
    assert gp.fetch_wtc_litros(object()) == [{"mes": "2026-09", "litros_cerveza": 500.0}]


def test_fetch_wtc_litros_devuelve_none_si_falla(monkeypatch, capsys):
    import wtc

    def boom(c):
        raise RuntimeError("sin permiso")
    monkeypatch.setattr(wtc, "leer_carga", boom)
    assert gp.fetch_wtc_litros(object()) is None
    assert "WARN WTC" in capsys.readouterr().out
