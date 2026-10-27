"""Tabla de locales (buildLocalesTable): un local con venta y sin objetivo cargado
(obj=0 en LOCALES_OBJ, ej. Rosario 3 al abrir) se muestra como "sin objetivo"."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_finanzas_js import run_dom_js  # noqa: E402

SETUP = """
const MN=["","Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
const LATEST_MES_DATA="2026-09";
const LOCAL_MENSUAL=[];
const STATE={periodo:"mes_actual",marca:"Temple",locMetric:"fac",locSort:"real"};
const LOCALES_OBJ=[{b:"T",l:"SOHO",d:{"2026-09":[80,100,2000,2500]}},
                   {b:"T",l:"ROSARIO 3",d:{"2026-09":[44.4,0,889,0]}},
                   {b:"T",l:"CERRADO",d:{"2026-09":[0,0,0,0]}}];
function getCustomMeses(){return [];}
function fmtM1(v){return "$"+v;} function fmtN(v){return String(v);} function tNum1(v){return v.toFixed(1);}
function tProgressBar(){return "";} function tPctCls(){return "";} function cmpVal(){return null;}
function tDot(){return "";}
buildLocalesTable();
"""


def test_local_sin_objetivo_aparece_en_la_tabla_marcado_sin_objetivo(tmp_path):
    r = run_dom_js(["buildLocalesTable"], SETUP,
                   "[_els.localesTable.innerHTML,_els.localesSub.textContent,_els.localesNota.textContent]",
                   tmp_path)
    tabla, sub, nota = r
    assert "ROSARIO 3" in tabla
    assert "CERRADO" not in tabla  # sin venta ni objetivo no aparece
    fila = tabla.split("ROSARIO 3")[1].split("</tr>")[0]
    assert "sin objetivo" in fila
    assert sub.startswith("2 locales")
    assert "1 bajo objetivo" in nota and "1 sin objetivo cargado" in nota


def test_orden_por_cumplimiento_deja_sin_objetivo_al_final(tmp_path):
    setup = SETUP.replace('locSort:"real"', 'locSort:"pct"')
    tabla = run_dom_js(["buildLocalesTable"], setup, "_els.localesTable.innerHTML", tmp_path)
    assert tabla.index("SOHO") < tabla.index("ROSARIO 3")
