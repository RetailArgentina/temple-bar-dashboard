"""Mes en curso parcial: comparaciones a mismos días, distribución por día promediada,
variación real deflactada en Insights y marcas/locales cerrados (11/11/2026)."""
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actualizar_retail as ar  # noqa: E402
from insights_generator import generate_insights  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates", "dashboard.html")


def _r(mes, m, l, fac, ord_, u):
    return SimpleNamespace(mes=mes, m=m, l=l, fac=fac, ord=ord_, u=u)


def test_build_mtd_mes_parcial_arma_prev_y_yoy():
    u = date(2026, 11, 10)
    mtd = ar.build_mtd([_r("2026-11", "Temple", "SOHO", 10.0, 200, u),
                        _r("2026-10", "Temple", "SOHO", 9.0, 190, u)])
    assert mtd["mes"] == "2026-11" and mtd["dia"] == 10
    assert mtd["prev"] == "2026-10" and mtd["yoy"] == "2025-11"
    assert {"mes": "2026-10", "m": "Temple", "l": "SOHO", "fac": 9.0, "ord": 190} in mtd["rows"]


def test_build_mtd_enero_prev_es_diciembre_del_anio_anterior():
    mtd = ar.build_mtd([_r("2027-01", "Temple", "SOHO", 1.0, 10, date(2027, 1, 5))])
    assert mtd["prev"] == "2026-12" and mtd["yoy"] == "2026-01"


def test_build_mtd_mes_completo_o_vacio_devuelve_none():
    assert ar.build_mtd([_r("2026-10", "Temple", "SOHO", 1.0, 10, date(2026, 10, 31))]) is None
    assert ar.build_mtd([]) is None


def test_dias_data_trae_cantidad_de_cada_dia_del_periodo():
    # 1–10/11/2026: domingo 1 y 8 (2 domingos), miércoles 4 (1 miércoles)
    ventas = [{"d": f"2026-11-{d:02d}", "marca": "Temple", "v": 1_000_000} for d in range(1, 11)]
    mensual = [{"mes": "2026-11", "m": "Temple", "fac": 10, "ord": 1, "tick": 1}]
    rows = {r["dia"]: r for r in ar.compute_dias_data(ventas, mensual)["mes_actual"]}
    assert rows["Dom"]["n"] == 2 and rows["Dom"]["fac"] == 2
    assert rows["Mie"]["n"] == 1 and rows["Mie"]["fac"] == 1


def _ventas(mes_ini, dias, v_dia, marca="Temple"):
    return [{"d": (mes_ini + timedelta(days=i)).isoformat(), "marca": marca, "o": 10,
             "v": v_dia, "c": "Salon"} for i in range(dias)]


def test_insights_comparan_mismos_dias_y_deflactan_bien():
    # Nov-25 completo a 100/día, Nov-26 solo 10 días a 150/día: antes daba −50% (10 vs 30 días);
    # a mismos días es +50% nominal. Con 20% de inflación, real = 1,5/1,2 − 1 = +25% (no 50 − 20 = 30).
    # El insight interanual pide ≥13 meses: 01/11/2025–31/10/2026 a 100/día + 1–10/11/2026 a 150/día
    ventas = _ventas(date(2025, 11, 1), 365, 100) + _ventas(date(2026, 11, 1), 10, 150)
    ipc = {f"{y}-{m:02d}": 0.0 for y in (2025, 2026) for m in range(1, 13)}
    ipc["2026-06"] = 20.0
    ins = generate_insights(ventas, {"ipc_mensual": ipc, "contexto": {}})
    yoy = [i for i in ins if "interanual" in i["title"]]
    assert yoy, [i["title"] for i in ins]
    assert "+50.0% interanual" in yoy[0]["title"] and "+25.0% real" in yoy[0]["title"]
    assert "días 1 a 10" in yoy[0]["body"]


def test_insight_macro_sin_referencias_fijas_a_trimestres_viejos():
    ventas = _ventas(date(2026, 11, 1), 10, 100)
    ins = generate_insights(ventas, {"ipc_mensual": {"2026-10": 2.0}, "contexto": {"nota_sector": "Q1 2026 viejo"}})
    macro = [i for i in ins if i["title"].startswith("Macro AR")][0]
    assert "Q1" not in macro["body"] and "Q2" not in macro["body"]
    assert "2.0%" in macro["body"]


def _bloque(html, nombre):
    m = re.search(r"/\* " + nombre + r":START.*?" + nombre + r":END \*/", html, re.S)
    assert m, nombre
    return m.group(0) + "\n"


def _run_js(expr, tmp_path):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    script = tmp_path / "cerr.js"
    script.write_text(_bloque(html, "FINANZAS_CORE") + _bloque(html, "EXCEPCIONES_CORE")
                      + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def test_es_cerrado_vale_solo_desde_el_dia_siguiente_al_cierre(tmp_path):
    r = _run_js("[esCerrado('Feriado',null,new Date(2026,9,29,12)),"
                "esCerrado('Feriado',null,new Date(2026,9,30)),"
                "esCerrado('Patagonia','SFE - ROSARIO LA FLORIDA ',new Date(2026,10,1)),"
                "esCerrado('Patagonia','USHUAIA',new Date(2026,10,1)),"
                "esCerrado('Temple','PINAMAR',new Date(2026,3,4,12)),"
                "esCerrado('Temple','PINAMAR',new Date(2026,10,12))]", tmp_path)
    assert r == [False, True, True, False, False, True]


def test_insights_numeros_en_formato_argentino():
    from insights_generator import _es_ar
    assert _es_ar("+14.3% · $43,421 · $247.5M · 2.3x · 04/11 · 2026-11 · $1,234.5") == \
        "+14,3% · $43.421 · $247,5M · 2,3x · 04/11 · 2026-11 · $1.234,5"


def test_plantilla_tiene_placeholder_mtd():
    with open(TEMPLATE, encoding="utf-8") as f:
        assert "const MTD = __MTD_JSON__;" in f.read()


def _fn(html, nombre):
    m = re.search(r"^function " + nombre + r"\(.*?^}", html, re.S | re.M)
    assert m, nombre
    return m.group(0) + "\n"


def _run_fns(nombres, expr, tmp_path):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    script = tmp_path / "fns.js"
    script.write_text("".join(_fn(html, n) for n in nombres)
                      + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def test_deflactar_filas_lleva_a_pesos_del_mes_base_y_no_muta(tmp_path):
    r = _run_fns(["deflactarFilas"],
                 "(()=>{const ipc={base:'2026-08',general:{'2025-08':100,'2026-08':130}};"
                 "const rows=[{mes:'2025-08',fac:100},{mes:'2026-08',fac:130},{mes:'2026-11',fac:50}];"
                 "const d=deflactarFilas(rows,ipc);return [d.map(x=>x.fac),rows[0].fac,deflactarFilas(rows,null)===rows];})()",
                 tmp_path)
    assert r == [[130, 130, 50], 100, True]


def test_nota_wtc_avisa_objetivo_descontado(tmp_path):
    r = _run_fns(["_wtcMes", "wtcNotaTexto"],
                 "[wtcNotaTexto({meses:[],sin_cotizacion:[],falta_mes_actual:true,mes_actual:'2026-11',"
                 "obj_descontado:{'2026-11':100.5}},false),"
                 "wtcNotaTexto({meses:[],sin_cotizacion:[]},false)]", tmp_path)
    assert "Objetivo de Patagonia sin WTC" in r[0] and "100,5" in r[0]
    assert "sin WTC" not in r[1]
