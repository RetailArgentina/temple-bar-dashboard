"""tests/test_wtc_producto_js.py — nota WTC en templates/producto_preview.html (Node)."""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="requiere Node")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "producto_preview.html")
FN = ["_n1", "fmtLts", "_wtcMes", "wtcNotaProducto"]


def run_dom_js(funciones, setup, expr, tmp_path):
    """Igual que tests/test_finanzas_js.run_dom_js pero sobre producto_preview.html."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    fuentes = []
    for nombre in funciones:
        m = re.search(r"^function " + nombre + r"\(.*?^\}\n", html, re.S | re.M)
        assert m, f"no se encontró {nombre} en la plantilla"
        fuentes.append(m.group(0))
    dom = ("const _els={};const document={getElementById:id=>_els[id]||(_els[id]="
           "{id,style:{},innerHTML:'',textContent:''})};\n")
    script = tmp_path / "dom.js"
    script.write_text(dom + "\n".join(fuentes) + "\n" + setup
                      + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def test_nota_con_litros(tmp_path):
    t = run_dom_js(FN, "", 'wtcNotaProducto({lts:850,meses_incluidos:["2026-09"],meses_faltantes:[],error:false})',
                   tmp_path)
    assert t.startswith("Incluye WTC (Uruguay): ") and "de cerveza, carga manual." in t
    assert t.endswith("Solo litros; la facturación de WTC no está en esta pestaña.")


def test_nota_sin_litros_con_faltantes(tmp_path):
    t = run_dom_js(FN, "", 'wtcNotaProducto({lts:0,meses_incluidos:[],meses_faltantes:["2026-08","2026-09"],error:false})',
                   tmp_path)
    assert t == "WTC (Uruguay): sin litros cargados en este período. ⚠ Falta cargar ago-26, sep-26."


def test_nota_error_y_null(tmp_path):
    r = run_dom_js(FN, "", '[wtcNotaProducto({lts:0,meses_incluidos:[],meses_faltantes:["2026-09"],error:true}),'
                           'wtcNotaProducto(null)]', tmp_path)
    assert r == ["⚠ No se pudo leer la carga de WTC: esta pestaña no lo incluye.", ""]


@pytest.mark.parametrize("marca,display", [("TODAS", "block"), ("PATAGONIA", "block"),
                                           ("TEMPLE", "none"), ("FERIADO", "none")])
def test_render_nota_segun_marca(tmp_path, marca, display):
    setup = ('var DATASETS={mes_actual:{wtc:{lts:850,meses_incluidos:["2026-09"],meses_faltantes:[],error:false},'
             'TODAS:{},PATAGONIA:{},TEMPLE:{},FERIADO:{}}};'
             f'var _periodo="mes_actual";var _marca="{marca}";renderWtcNota();')
    r = run_dom_js(FN + ["renderWtcNota"], setup,
                   "[_els.wtcNotaProd.style.display,_els.wtcNotaProd.textContent]", tmp_path)
    assert r[0] == display
    assert r[1].startswith("Incluye WTC") == (display == "block")


def test_render_nota_oculta_si_sin_acceso(tmp_path):
    setup = ('var DATASETS={mes_actual:{wtc:{lts:850,meses_incluidos:[],meses_faltantes:[],error:false},'
             'PATAGONIA:{sin_acceso:true}}};var _periodo="mes_actual";var _marca="PATAGONIA";renderWtcNota();')
    r = run_dom_js(FN + ["renderWtcNota"], setup, "_els.wtcNotaProd.style.display", tmp_path)
    assert r == "none"


def test_render_llama_a_la_nota_y_existe_el_elemento():
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert 'id="wtcNotaProd"' in html
    cuerpo = re.search(r"^function render\(\)\{(.*?)^\}\n", html, re.S | re.M).group(1)
    assert cuerpo.index("renderWtcNota()") < cuerpo.index("if(d.sin_acceso)")
