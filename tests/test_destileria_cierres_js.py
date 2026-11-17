"""tests/test_destileria_cierres_js.py — render de la pestaña Cierres del Tablero Destilería.

Extrae funciones de templates/destileria.html por nombre y las corre en Node con un
`document` falso (mismo patrón que run_dom_js en tests/test_finanzas_js.py).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="requiere Node")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "destileria.html")
FUNCS = ["cierresMarcasPermitidas", "renderCierres"]


def run_dom_js(setup, expr, tmp_path):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    fuentes = []
    for nombre in FUNCS:
        m = re.search(r"^function " + nombre + r"\(.*?^\}\n", html, re.S | re.M)
        assert m, f"no se encontró {nombre} en la plantilla"
        fuentes.append(m.group(0))
    dom = ("const window={};const _els={};const document={getElementById:id=>_els[id]||(_els[id]="
           "{id,style:{},innerHTML:'',textContent:'',value:''})};\n")
    script = tmp_path / "dom.js"
    script.write_text(dom + setup + "\n" + "\n".join(fuentes)
                      + "\nrenderCierres();\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


R0 = {"li": 0, "to": 0}


def foto(movs, resumen):
    return {"mes": "2026-10", "tomada": "2026-11-17T09:00", "tardia": True, "resumen": resumen, "movs": movs}


def mov(tipo, nd, marca, etiqueta="", dli=-28.0, dto=0):
    return {"tipo": tipo, "etiqueta": etiqueta, "f": "2026-10-12", "nd": nd, "nu": "0002-00001234",
            "ti": "COT" if tipo == "baja" else "FCB", "fa": marca + "_x", "marca": marca,
            "dce": -56, "dli": dli, "dto": dto}


def test_sin_fotos(tmp_path):
    html = run_dom_js("const CIERRES=[];", "_els['cierres-body'].innerHTML", tmp_path)
    assert "Todavía no hay fotos de cierre" in html


def test_sin_cambios(tmp_path):
    res = {"bosque": {"cierre": {"li": 1162.3, "to": 100}, "hoy": {"li": 1162.3, "to": 100}, "altas": R0, "bajas": R0}}
    html = run_dom_js("const CIERRES=" + json.dumps([foto([], res)]) + ";", "_els['cierres-body'].innerHTML", tmp_path)
    assert "Sin cambios desde el cierre" in html
    assert "foto tomada el 17/11" in run_dom_js("const CIERRES=" + json.dumps([foto([], res)]) + ";",
                                                "_els['cierres-mes'].innerHTML", tmp_path)


def test_cot_convertida_y_marca_oculta(tmp_path):
    res = {"bosque":  {"cierre": {"li": 40, "to": 0}, "hoy": {"li": 12, "to": 50000}, "altas": {"li": 12, "to": 50000}, "bajas": {"li": -40, "to": 0}},
           "feriado": {"cierre": R0, "hoy": {"li": 5, "to": 900}, "altas": {"li": 5, "to": 900}, "bajas": R0}}
    movs = [mov("baja", "PASEO LA PLAZA", "bosque", "COT convertida"),
            mov("alta", "CLIENTE FERIADO", "feriado", dli=5.0, dto=900)]
    setup = ("window.__USER_PERMISSIONS__={brands:['bosque']};const CIERRES=" + json.dumps([foto(movs, res)]) + ";")
    html = run_dom_js(setup, "_els['cierres-body'].innerHTML", tmp_path)
    assert "COT convertida" in html and "PASEO LA PLAZA" in html
    assert "CLIENTE FERIADO" not in html and "Feriado" not in html


def test_acceso_total_ve_todas_las_marcas(tmp_path):
    res = {"feriado": {"cierre": R0, "hoy": {"li": 5, "to": 900}, "altas": {"li": 5, "to": 900}, "bajas": R0}}
    setup = "const CIERRES=" + json.dumps([foto([mov("alta", "CLIENTE FERIADO", "feriado", dli=5.0)], res)]) + ";"
    html = run_dom_js(setup, "_els['cierres-body'].innerHTML", tmp_path)
    assert "CLIENTE FERIADO" in html and "Altas posteriores" in html
