"""tests/test_finanzas_js.py — cálculos de la pestaña Finanzas.

Extrae el bloque FINANZAS_CORE de templates/dashboard.html y lo corre con Node.
Se saltea si Node no está instalado.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="requiere Node")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


def run_js(expr, tmp_path):
    """Evalúa `expr` (JS) después del bloque FINANZAS_CORE y devuelve el resultado como Python."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"/\* FINANZAS_CORE:START.*?\*/(.*?)/\* FINANZAS_CORE:END \*/", html, re.S)
    assert m, "no se encontró el bloque FINANZAS_CORE en la plantilla"
    script = tmp_path / "fin.js"
    script.write_text(m.group(1) + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def run_dom_js(funciones, setup, expr, tmp_path):
    """Como run_js, pero agrega funciones de render de la plantilla (por nombre) y un
    `document` falso: getElementById devuelve siempre el mismo objeto por id."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    fuentes = []
    for nombre in funciones:
        m = re.search(r"^function " + nombre + r"\(.*?^\}\n", html, re.S | re.M)
        assert m, f"no se encontró {nombre} en la plantilla"
        fuentes.append(m.group(0))
    dom = ("const _els={};const document={getElementById:id=>_els[id]||(_els[id]="
           "{id,style:{},innerHTML:'',textContent:'',classList:{toggle(){}}})};\n")
    script = tmp_path / "dom.js"
    script.write_text(dom + "\n".join(fuentes) + "\n" + setup
                      + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_build_finanzas_sin_ipc_oculta_las_secciones_y_muestra_solo_el_aviso(tmp_path):
    r = run_dom_js(["buildFinanzas"], "const IPC=null; buildFinanzas();",
                   '[_els.finSinDatos.style.display,_els.finContenido.style.display]', tmp_path)
    assert r == ["flex", "none"]


def test_update_all_construye_finanzas_aunque_falle_otra_seccion(tmp_path):
    otras = ["updateBannerKPI", "buildTend", "buildRoyalties", "buildPlanAccion", "buildPotencialLocales",
             "buildDias", "buildTop10", "buildObjetivos", "buildObjetivosResumen", "buildObjetivosPorMarca",
             "buildLocalesTable"]
    setup = ("".join(f"function {n}(){{}}" for n in otras)
             + "buildTend=()=>{throw new Error('boom')};let fin=0;function buildFinanzas(){fin++;}"
             + "console.error=()=>{};document.getElementById('view-finanzas').style.display='block';updateAll();")
    assert run_dom_js(["updateAll"], setup, "fin", tmp_path) == 1


IPC = ('{base:"2026-09",estimados:[],'
       'general:{"2025-08":100,"2025-09":100,"2025-10":100,"2026-08":125,"2026-09":130,"2026-10":130},'
       'rubro:{"2025-09":100,"2026-09":140}}')


def test_fin_pace(tmp_path):
    r = run_js('[finPace("2026-08",new Date(2026,8,15)),finPace("2026-09",new Date(2026,8,15)),'
               'finPace("2026-10",new Date(2026,8,15))]', tmp_path)
    assert r == [1, 0.5, None]


def test_fin_inflacion_usa_indice_promedio_del_periodo(tmp_path):
    r = run_js(f'finInflacion(({IPC}).general,["2026-08","2026-09"],["2025-08","2025-09"])', tmp_path)
    assert r == pytest.approx(27.5)


def test_fin_inflacion_sin_meses_devuelve_null(tmp_path):
    assert run_js(f'finInflacion(({IPC}).general,["2026-09"],[])', tmp_path) is None


def test_fin_crecimiento_prorratea_el_mes_en_curso_y_deflacta(tmp_path):
    r = run_js(f'finCrecimiento([{{mes:"2025-09",fac:100}},{{mes:"2026-09",fac:65}}],'
               f'["2026-09"],["2025-09"],{IPC},m=>finPace(m,new Date(2026,8,15)))', tmp_path)
    assert r["nomCur"] == pytest.approx(130)      # 65 al día 15 de 30 → cierre estimado 130
    assert r["crecNom"] == pytest.approx(30)
    assert r["crecReal"] == pytest.approx(0)       # 30% nominal con 30% de inflación


def test_fin_crecimiento_sin_anio_anterior_es_null(tmp_path):
    r = run_js(f'finCrecimiento([{{mes:"2026-09",fac:65}}],["2026-09"],["2025-09"],{IPC},m=>1)', tmp_path)
    assert r is None


def test_fin_crecimiento_excluye_mes_con_menos_de_10pct_de_avance(tmp_path):
    # 2 de octubre: el mes en curso tiene 2/31 de avance → se saca de la comparación
    solo = run_js(f'finCrecimiento([{{mes:"2025-10",fac:100}},{{mes:"2026-10",fac:5}}],'
                  f'["2026-10"],["2025-10"],{IPC},m=>finPace(m,new Date(2026,9,2)))', tmp_path)
    assert solo is None
    dos = run_js(f'finCrecimiento([{{mes:"2025-09",fac:100}},{{mes:"2026-09",fac:130}},'
                 f'{{mes:"2025-10",fac:100}},{{mes:"2026-10",fac:5}}],'
                 f'["2026-09","2026-10"],["2025-09","2025-10"],{IPC},m=>finPace(m,new Date(2026,9,2)))', tmp_path)
    assert dos["nomCur"] == pytest.approx(130) and dos["crecReal"] == pytest.approx(0)
    # devuelve los meses efectivamente comparados, para calcular la inflación sobre los mismos
    assert dos["meses"] == ["2026-09"] and dos["yoyMeses"] == ["2025-09"]


def test_fin_inflacion_de_los_meses_comparados_reconcilia_nominal_y_real(tmp_path):
    # sep-26 cerrado vs sep-25 y oct-26 al 2 de octubre (se excluye): la inflación sale solo de septiembre
    ipc = ('{base:"2026-10",general:{"2025-09":100,"2025-10":100,"2026-09":130,"2026-10":160}}')
    r = run_js(f'(()=>{{const c=finCrecimiento([{{mes:"2025-09",fac:100}},{{mes:"2026-09",fac:143}},'
               f'{{mes:"2025-10",fac:100}},{{mes:"2026-10",fac:5}}],["2026-09","2026-10"],["2025-09","2025-10"],'
               f'{ipc},m=>finPace(m,new Date(2026,9,2)));'
               f'return [c.crecNom,c.crecReal,finInflacion(({ipc}).general,c.meses,c.yoyMeses)];}})()', tmp_path)
    nom, real, inf = r
    assert inf == pytest.approx(30)
    assert (1 + nom / 100) / (1 + inf / 100) - 1 == pytest.approx(real / 100)


def test_fin_same_store_solo_locales_en_ambos_periodos(tmp_path):
    rows = ('[{mes:"2025-09",m:"Temple",l:"A",fac:100},{mes:"2026-09",m:"Temple",l:"a ",fac:156},'
            '{mes:"2026-09",m:"Temple",l:"B",fac:50},{mes:"2026-09",m:"Feriado",l:"A",fac:999}]')
    r = run_js(f'finSameStore({rows},"Temple",["2026-09"],["2025-09"],{IPC},m=>1)', tmp_path)
    assert r["nomCur"] == pytest.approx(156)       # B no estaba el año anterior; Feriado es otra marca
    assert r["crecReal"] == pytest.approx(20)      # 156/130 − 1


def test_fin_clase_umbrales(tmp_path):
    assert run_js('[finClase(10.5),finClase(10),finClase(0),finClase(-0.1),finClase(null)]', tmp_path) == \
        ["Exigente", "Razonable", "Razonable", "Laxo", None]


def test_fin_obj_implicito(tmp_path):
    r = run_js('finObjImplicito(150,100,25)', tmp_path)
    assert r["nom"] == pytest.approx(50) and r["real"] == pytest.approx(20) and r["clase"] == "Exigente"


def test_fin_obj_implicito_sin_venta_anio_anterior_es_null(tmp_path):
    assert run_js('[finObjImplicito(150,0,25),finObjImplicito(0,100,25),finObjImplicito(150,100,null)]',
                  tmp_path) == [None, None, None]


def test_fin_resto_anio(tmp_path):
    ipc = '{base:"2026-08",general:{"2025-09":100,"2025-10":100,"2026-09":120,"2026-10":120}}'
    obj = '{"2026-01":{obj_fac:100},"2026-09":{obj_fac:100},"2026-10":{obj_fac:100},"2025-12":{obj_fac:999}}'
    rows = ('[{mes:"2026-01",fac:100},{mes:"2026-09",fac:50},'
            '{mes:"2025-09",fac:80},{mes:"2025-10",fac:80}]')
    r = run_js(f'finRestoAnio({obj},{rows},"2026",["2026-09","2026-10"],0.5,{ipc})', tmp_path)
    assert r["objAnual"] == 300 and r["ytd"] == 150 and r["faltante"] == 150
    assert r["ventaAA"] == pytest.approx(120)      # 80 × (1 − 0,5) + 80
    assert r["imp"]["nom"] == pytest.approx(25)
    assert r["imp"]["real"] == pytest.approx(125 / 120 * 100 - 100)
    assert r["imp"]["clase"] == "Razonable"


def test_fin_meses_grafico_saca_el_primer_mes_parcial_y_el_mes_en_curso(tmp_path):
    rows = '[{mes:"2025-10"},{mes:"2025-11"},{mes:"2025-11"},{mes:"2025-12"},{mes:"2026-01"},{mes:"2026-02"}]'
    r = run_js(f'[finMesesGrafico({rows},new Date(2026,1,10),24),finMesesGrafico({rows},new Date(2026,1,10),2)]',
               tmp_path)
    assert r[0] == ["2025-11", "2025-12", "2026-01"]   # oct-25 (arranque de la serie) y feb-26 (en curso) fuera
    assert r[1] == ["2025-12", "2026-01"]


def test_fin_meses_grafico_arranca_en_fin_serie_desde(tmp_path):
    # oct-24 → ene-25 los locales se fueron cargando de a poco: el gráfico empieza en feb-25
    rows = '[{mes:"2024-10"},{mes:"2024-11"},{mes:"2024-12"},{mes:"2025-01"},{mes:"2025-02"},{mes:"2025-03"},{mes:"2025-04"}]'
    r = run_js(f'finMesesGrafico({rows},new Date(2025,3,10),24)', tmp_path)
    assert r == ["2025-02", "2025-03"]


def test_fin_sumar_real_null_si_falta_ipc_de_algun_mes(tmp_path):
    # 2023-12 no está en la serie: la suma real sería parcial → null, el nominal sí se suma
    r = run_js(f'finSumar([{{mes:"2023-12",fac:50}},{{mes:"2026-09",fac:130}}],["2023-12","2026-09"],{IPC},()=>1)',
               tmp_path)
    assert r["nom"] == pytest.approx(180) and r["real"] is None and r["falta"] is True


def test_fin_sumar_real_con_ipc_completo(tmp_path):
    r = run_js(f'finSumar([{{mes:"2026-08",fac:125}},{{mes:"2026-09",fac:130}}],["2026-08","2026-09"],{IPC},()=>1)',
               tmp_path)
    assert r["real"] == pytest.approx(260)  # 125 × 130/125 + 130 (base 2026-09) and r["falta"] is False


def test_fin_crecimiento_sin_par_del_anio_anterior_en_algun_mes_es_null(tmp_path):
    # La marca no tiene venta en 2025-08 (no existía / hueco de sync): no se compara un período parcial
    r = run_js(f'finCrecimiento([{{mes:"2025-09",fac:100}},{{mes:"2026-08",fac:500}},{{mes:"2026-09",fac:130}}],'
               f'["2026-08","2026-09"],["2025-08","2025-09"],{IPC},m=>1)', tmp_path)
    assert r is None


def test_fin_sin_primer_mes_saca_todas_las_filas_del_mes_de_arranque(tmp_path):
    rows = ('[{mes:"2024-11",l:"A"},{mes:"2024-10",l:"A"},{mes:"2024-10",l:"B"},{mes:"2024-12",l:"A"}]')
    r = run_js(f'finSinPrimerMes({rows}).map(r=>r.mes)', tmp_path)
    assert r == ["2024-11", "2024-12"]


def test_fin_sin_primer_mes_por_marca_hace_null_el_crecimiento_contra_el_mes_parcial(tmp_path):
    # Feriado arranca en 2025-09 (parcial): 2026-09 no se compara contra ese mes
    rows = '[{mes:"2025-09",fac:10},{mes:"2025-10",fac:100},{mes:"2026-09",fac:130},{mes:"2026-10",fac:130}]'
    r = run_js(f'[finCrecimiento(finSinPrimerMes({rows}),["2026-09"],["2025-09"],{IPC},m=>1),'
               f'finCrecimiento(finSinPrimerMes({rows}),["2026-10"],["2025-10"],{IPC},m=>1)!==null]', tmp_path)
    assert r == [None, True]


def _periodo_custom(desde, hasta, tmp_path):
    meses = ["2024-10", "2024-11", "2024-12", "2025-01", "2025-02", "2025-09", "2025-10", "2025-11",
             "2025-12", "2026-01", "2026-02", "2026-09", "2026-10", "2026-11"]
    mensual = ",".join(f'{{mes:"{m}",m:"Temple",fac:1}}' for m in meses)
    setup = (f'const FIN_SERIE_DESDE="2025-02";const MENSUAL=[{mensual}];const STATE={{periodo:"custom",fromMes:"{desde}",toMes:"{hasta}"}};'
             'const PD={};')
    return run_dom_js(["finSinPrimerMes", "finSerieComparable", "getCustomMeses", "finYoyMes", "finPeriodoActual"], setup,
                      "finPeriodoActual()", tmp_path)


def test_fin_periodo_custom_con_oct25_no_compara_contra_oct24_parcial(tmp_path):
    r = _periodo_custom("2025-10", "2025-11", tmp_path)
    assert r["meses"] == ["2025-10", "2025-11"]
    assert r["yoyMeses"] == []   # oct-24 es el arranque de la serie (mes parcial)


def test_fin_periodo_custom_contra_meses_de_carga_incompleta_no_compara(tmp_path):
    # nov-24 a ene-25 tienen la red a medio cargar (antes de FIN_SERIE_DESDE)
    assert _periodo_custom("2025-11", "2025-11", tmp_path)["yoyMeses"] == []
    assert _periodo_custom("2026-01", "2026-02", tmp_path)["yoyMeses"] == []


def test_fin_periodo_custom_desde_fin_serie_desde_compara_normal(tmp_path):
    r = _periodo_custom("2026-02", "2026-02", tmp_path)
    assert r["yoyMeses"] == ["2025-02"]


def test_fin_serie_desde_es_feb25(tmp_path):
    assert run_js("FIN_SERIE_DESDE", tmp_path) == "2025-02"


def test_fin_serie_comparable_corta_antes_de_fin_serie_desde_y_el_arranque_de_la_marca(tmp_path):
    temple = '[{mes:"2024-10"},{mes:"2024-11"},{mes:"2025-01"},{mes:"2025-02"},{mes:"2025-03"}]'
    nueva = '[{mes:"2025-06",l:"A"},{mes:"2025-06",l:"B"},{mes:"2025-07",l:"A"}]'   # marca que arranca después
    r = run_js(f'[finSerieComparable({temple}).map(r=>r.mes),finSerieComparable({nueva}).map(r=>r.mes)]', tmp_path)
    assert r == [["2025-02", "2025-03"], ["2025-07"]]


def test_fin_venta_aa_usa_la_serie_comparable(tmp_path):
    # Objetivo de ene-26 no se mide contra ene-25 (carga incompleta, antes de FIN_SERIE_DESDE)
    rows = '[{mes:"2024-11",fac:1},{mes:"2025-01",fac:70},{mes:"2025-02",fac:100},{mes:"2025-03",fac:110}]'
    r = run_js(f'[finVentaAA({rows},"2026-01"),finVentaAA({rows},"2026-02"),finVentaAA({rows},"2026-04")]', tmp_path)
    assert r == [None, {"mes": "2025-02", "fac": 100}, None]


# ── Precio vs tráfico (same-store): órdenes vs ticket real ──

def test_fin_precio_trafico_abre_same_store_en_ordenes_y_ticket_real(tmp_path):
    rows = ('[{mes:"2025-09",m:"Temple",l:"A",fac:100,ord:10},{mes:"2026-09",m:"Temple",l:"a ",fac:90,ord:6},'
            '{mes:"2026-09",m:"Temple",l:"B",fac:500,ord:50},{mes:"2026-09",m:"Feriado",l:"A",fac:999,ord:99}]')
    r = run_js(f'finPrecioTrafico({rows},"Temple",["2026-09"],["2025-09"],{IPC},m=>finPace(m,new Date(2026,8,15)))',
               tmp_path)
    assert r["ordCur"] == pytest.approx(12)        # 6 al día 15 de 30 → cierre estimado 12 (B y Feriado afuera)
    assert r["crecOrd"] == pytest.approx(20)
    assert r["tickCur"] == pytest.approx(15) and r["tickYoy"] == pytest.approx(10)  # fac/ord agregado
    assert r["crecTickNom"] == pytest.approx(50)
    assert r["inflRubro"] == pytest.approx(40)
    assert r["crecTickReal"] == pytest.approx(150 / 140 * 100 - 100)
    assert r["lectura"] == "Más clientes y precio real ↑"
    # órdenes × ticket reconcilia con el crecimiento nominal same-store
    assert (1 + r["crecOrd"] / 100) * (1 + r["crecTickNom"] / 100) == pytest.approx(1.8)


def test_fin_precio_trafico_sin_ipc_rubro_deja_ticket_real_y_lectura_en_null(tmp_path):
    ipc = '{base:"2026-09",general:{"2025-09":100,"2026-09":130},rubro:{"2026-09":140}}'
    r = run_js(f'finPrecioTrafico([{{mes:"2025-09",m:"Temple",l:"A",fac:100,ord:10}},'
               f'{{mes:"2026-09",m:"Temple",l:"A",fac:130,ord:10}}],"todas",["2026-09"],["2025-09"],{ipc},m=>1)',
               tmp_path)
    assert r["crecOrd"] == pytest.approx(0) and r["crecTickNom"] == pytest.approx(30)
    assert r["crecTickReal"] is None and r["lectura"] is None


def test_fin_precio_trafico_sin_locales_comunes_o_sin_ordenes_es_null(tmp_path):
    sin_comunes = run_js(f'finPrecioTrafico([{{mes:"2026-09",m:"Temple",l:"A",fac:130,ord:10}}],'
                         f'"Temple",["2026-09"],["2025-09"],{IPC},m=>1)', tmp_path)
    sin_ord = run_js(f'finPrecioTrafico([{{mes:"2025-09",m:"Temple",l:"A",fac:100,ord:0}},'
                     f'{{mes:"2026-09",m:"Temple",l:"A",fac:130,ord:10}}],"Temple",["2026-09"],["2025-09"],{IPC},m=>1)',
                     tmp_path)
    assert sin_comunes is None and sin_ord is None


def test_fin_precio_trafico_excluye_mes_con_menos_de_10pct_de_avance(tmp_path):
    rows = ('[{mes:"2025-09",m:"T",l:"A",fac:100,ord:10},{mes:"2026-09",m:"T",l:"A",fac:130,ord:10},'
            '{mes:"2025-10",m:"T",l:"A",fac:100,ord:10},{mes:"2026-10",m:"T",l:"A",fac:5,ord:1}]')
    r = run_js(f'finPrecioTrafico({rows},"T",["2026-09","2026-10"],["2025-09","2025-10"],{IPC},'
               f'm=>finPace(m,new Date(2026,9,2)))', tmp_path)
    assert r["meses"] == ["2026-09"] and r["crecOrd"] == pytest.approx(0)
    assert r["inflRubro"] == pytest.approx(40)


def test_fin_lectura_precio_trafico_segun_signos(tmp_path):
    assert run_js('[finLecturaPT(5,3),finLecturaPT(-5,3),finLecturaPT(5,-3),finLecturaPT(-5,-3),'
                  'finLecturaPT(0,0),finLecturaPT(5,null)]', tmp_path) == [
        "Más clientes y precio real ↑",
        "Precio le gana a la inflación, pierde clientes",
        "Gana clientes, precio atrasado vs inflación",
        "Pierde clientes y precio real",
        "Más clientes y precio real ↑",
        None]


def test_build_fin_precio_trafico_pinta_una_fila_por_marca_con_lectura(tmp_path):
    core = re.search(r"/\* FINANZAS_CORE:START.*?\*/(.*?)/\* FINANZAS_CORE:END \*/",
                     open(TEMPLATE, encoding="utf-8").read(), re.S).group(1)
    setup = (core + 'const tPct=v=>(v>=0?"+":"")+v.toFixed(1)+"%";const tDot=m=>"";'
             'const fmtT=v=>"$ "+Math.round(v);const MN=["","ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];'
             f'const IPC={IPC};'
             'const LOCAL_MENSUAL=[{mes:"2025-08",m:"Temple",l:"A",fac:1,ord:100},{mes:"2025-09",m:"Temple",l:"A",fac:1,ord:100},{mes:"2026-09",m:"Temple",l:"A",fac:1.2,ord:80},'
             '{mes:"2025-09",m:"Feriado",l:"F",fac:1,ord:100}];'
             'buildFinPrecioTrafico(["Temple","Feriado"],{meses:["2026-09"],yoyMeses:["2025-09"],label:"Sep"},m=>1,ms=>"");')
    html = run_dom_js(["finPctHtml", "buildFinPrecioTrafico"], setup, "_els.finPTTable.innerHTML", tmp_path)
    assert "Precio le gana a la inflación, pierde clientes" in html      # ord −20%; ticket +50% vs rubro 40%
    assert "$ 15000" in html                                               # ticket actual: 1,2 M / 80
    assert html.count("<tr>") == 3                                         # header + Temple + Feriado (sin datos)
    assert "sin período comparable" in html.lower()
