"""tests/test_excepciones_js.py — reglas del panel "Locales a mirar" (Ventas).

Extrae los bloques FINANZAS_CORE y EXCEPCIONES_CORE de templates/dashboard.html y los corre
con Node. Se saltea si Node no está instalado.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="requiere Node")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


def _bloque(html, nombre):
    m = re.search(r"/\* " + nombre + r":START.*?\*/(.*?)/\* " + nombre + r":END \*/", html, re.S)
    assert m, f"no se encontró el bloque {nombre} en la plantilla"
    return m.group(1)


def run_js(expr, tmp_path, extra=""):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    script = tmp_path / "exc.js"
    script.write_text(_bloque(html, "FINANZAS_CORE") + _bloque(html, "EXCEPCIONES_CORE") + extra
                      + "\nconsole.log(JSON.stringify(" + expr + "));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


# IPC general plano (sin inflación) para leer los gaps directo de la facturación
IPC_G = '{"2025-06":100,"2025-07":100,"2025-08":100,"2026-06":100,"2026-07":100,"2026-08":100}'


def _rows(locales):
    """locales: {(marca, local): {mes: fac}} → literal JS de LOCAL_MENSUAL."""
    out = []
    for (m, l), meses in locales.items():
        for mes, fac in meses.items():
            out.append({"mes": mes, "m": m, "l": l, "fac": fac, "ord": 1})
    return json.dumps(out)


def _serie(aa, actual):
    """fac del año anterior (jun-ago 25) y actual (jun-ago 26)."""
    return {"2025-06": aa[0], "2025-07": aa[1], "2025-08": aa[2],
            "2026-06": actual[0], "2026-07": actual[1], "2026-08": actual[2]}


def test_exc_meses_cerrados_toma_los_ultimos_n_antes_del_mes_en_curso(tmp_path):
    rows = _rows({("T", "A"): _serie([1, 1, 1], [1, 1, 1]) | {"2026-09": 1}})
    assert run_js(f'excMesesCerrados({rows},new Date(2026,8,15),3)', tmp_path) == \
        ["2026-06", "2026-07", "2026-08"]


def test_exc_caida_vs_marca_sostenida_es_alta_y_solo_ultimo_mes_es_media(tmp_path):
    rows = _rows({
        ("T", "SOSTENIDA"): _serie([10, 10, 10], [5, 5, 5]),     # −50% los 3 meses
        ("T", "ULTIMO"):    _serie([10, 10, 10], [10, 10, 5]),   # solo agosto
        ("T", "RECUPERADO"): _serie([10, 10, 10], [5, 5, 10]),   # cayó y volvió: no se marca
        ("T", "PAR1"):      _serie([10, 10, 10], [10, 10, 10]),
        ("T", "PAR2"):      _serie([10, 10, 10], [10, 10, 10]),
    })
    r = run_js(f'excCaidaVsMarca({rows},{IPC_G},["2026-06","2026-07","2026-08"])', tmp_path)
    por_local = {x["l"]: x for x in r}
    assert set(por_local) == {"SOSTENIDA", "ULTIMO"}
    assert por_local["SOSTENIDA"]["sev"] == "Alta" and por_local["ULTIMO"]["sev"] == "Media"
    assert por_local["SOSTENIDA"]["cat"] == "Caída vs su marca"


def test_exc_caida_vs_marca_compara_contra_la_marca_no_contra_cero(tmp_path):
    # toda la marca cae 40%: un local que cae 40% no es excepción
    rows = _rows({("T", k): _serie([10, 10, 10], [6, 6, 6]) for k in "ABCD"})
    assert run_js(f'excCaidaVsMarca({rows},{IPC_G},["2026-06","2026-07","2026-08"])', tmp_path) == []


def test_exc_caida_vs_marca_ignora_locales_con_base_chica(tmp_path):
    rows = _rows({("T", "CHICO"): _serie([0.2, 0.2, 0.2], [0.01, 0.01, 0.01]),
                  ("T", "P1"): _serie([10, 10, 10], [10, 10, 10]),
                  ("T", "P2"): _serie([10, 10, 10], [10, 10, 10])})
    assert run_js(f'excCaidaVsMarca({rows},{IPC_G},["2026-06","2026-07","2026-08"])', tmp_path) == []


def test_exc_obj_sin_venta_alta_si_sigue_y_media_si_fue_antes(tmp_path):
    lo = json.dumps([
        {"b": "P", "l": "WTC", "d": {"2026-07": [0, 5, 0, 10], "2026-08": [0, 5, 0, 10], "2026-10": [0, 5, 0, 10]}},
        {"b": "T", "l": "LELOIR", "d": {"2026-01": [0, 5, 0, 10], "2026-08": [3, 5, 9, 10]}},
        {"b": "T", "l": "OK", "d": {"2026-08": [3, 5, 9, 10]}},
        {"b": "T", "l": "VIEJO", "d": {"2025-12": [0, 5, 0, 10]}},
    ])
    r = run_js(f'excObjSinVenta({lo},"2026","2026-08")', tmp_path)
    assert [(x["m"], x["l"], x["sev"]) for x in r] == [("Patagonia", "WTC", "Alta"), ("Temple", "LELOIR", "Media")]


def test_exc_sin_datos_por_local_y_marca_entera(tmp_path):
    uv = json.dumps([
        {"m": "Temple", "l": "A", "u": "2026-09-28"},
        {"m": "Temple", "l": "CERRADO", "u": "2026-09-20"},   # 9 días
        {"m": "Temple", "l": "PAUSA", "u": "2026-09-25"},     # 4 días
        {"m": "Feriado", "l": "X", "u": "2026-09-24"},        # toda la marca sin datos
        {"m": "Feriado", "l": "Y", "u": "2026-09-23"},
    ])
    r = run_js(f'excSinDatos({uv},new Date(2026,8,29),3)', tmp_path)
    got = {(x["m"], x["l"]): x["sev"] for x in r}
    assert got == {("Temple", "CERRADO"): "Alta", ("Temple", "PAUSA"): "Media", ("Feriado", None): "Alta"}
    assert "24/09" in next(x for x in r if x["m"] == "Feriado")["msg"]


def test_exc_sin_datos_null_no_evalua(tmp_path):
    assert run_js('excSinDatos(null,new Date(2026,8,29),3)', tmp_path) == []


def test_exc_ordenar_alta_primero_y_filtrar_marca(tmp_path):
    lista = json.dumps([{"m": "Temple", "l": "B", "sev": "Media"}, {"m": "Feriado", "l": "C", "sev": "Alta"},
                        {"m": "Temple", "l": "A", "sev": "Alta"}])
    assert [x["l"] for x in run_js(f'excOrdenar({lista},"todas")', tmp_path)] == ["C", "A", "B"]
    assert [x["l"] for x in run_js(f'excOrdenar({lista},"Temple")', tmp_path)] == ["A", "B"]


def test_build_excepciones_pinta_filas_filtra_marca_y_avisa_sin_ultima_venta(tmp_path):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    fn = re.search(r"^function buildExcepciones\(.*?^\}\n", html, re.S | re.M)
    assert fn, "no se encontró buildExcepciones"
    dom = ("const _els={};const document={getElementById:id=>_els[id]||(_els[id]="
           "{id,style:{},innerHTML:'',textContent:''})};const tDot=m=>'';\n")
    datos = ('const LOCAL_MENSUAL=[];const IPC={general:{}};const ULTIMA_VENTA=null;'
             'const LOCALES_OBJ=[{b:"P",l:"WTC",d:{"2026-08":[0,5,0,1]}},{b:"T",l:"LELOIR",d:{"2026-08":[0,5,0,1]}}];')
    script = tmp_path / "dom.js"
    script.write_text(dom + _bloque(html, "FINANZAS_CORE") + _bloque(html, "EXCEPCIONES_CORE") + fn.group(0)
                      + datos + 'const STATE={marca:"Patagonia"};buildExcepciones(new Date(2026,8,29));'
                      + "console.log(JSON.stringify([_els.excTable.innerHTML,_els.excSub.textContent]));",
                      encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    tabla, sub = json.loads(out.stdout)
    assert "WTC" in tabla and "LELOIR" not in tabla
    assert "sin datos de última venta" in sub.lower()


# ── Badge de calidad de datos (encabezado): frescura por marca vs la fecha de quien mira ──

def _uv(**marcas):
    """marcas: {marca: [último día por local, ...]} → literal JS de ULTIMA_VENTA."""
    return json.dumps([{"m": m, "l": f"L{i}", "u": u} for m, us in marcas.items() for i, u in enumerate(us)])


HOY = "new Date(2026,8,29)"


def test_calidad_todas_las_marcas_hasta_ayer_esta_al_dia(tmp_path):
    uv = _uv(Temple=["2026-09-28"], Patagonia=["2026-09-28"], Feriado=["2026-09-28"])
    r = run_js(f"calidadDatos({uv},{HOY})", tmp_path)
    assert r["estado"] == "fresh"
    assert "al día" in r["texto"] and "28/09" in r["texto"]


def test_calidad_la_marca_toma_su_local_mas_reciente(tmp_path):
    # un local viejo no atrasa a la marca (eso lo cubre "Locales a mirar")
    uv = _uv(Temple=["2026-09-10", "2026-09-28"], Feriado=["2026-09-28"])
    assert run_js(f"calidadDatos({uv},{HOY})", tmp_path)["estado"] == "fresh"


def test_calidad_marca_atrasada_2_o_3_dias_es_warn_y_la_nombra(tmp_path):
    for u in ("2026-09-27", "2026-09-26"):
        uv = _uv(Temple=["2026-09-28"], Feriado=[u])
        r = run_js(f"calidadDatos({uv},{HOY})", tmp_path)
        assert r["estado"] == "warn"
        assert "Feriado" in r["texto"] and u[8:10] + "/09" in r["texto"] and "Temple" not in r["texto"]


def test_calidad_mas_de_3_dias_es_stale_y_ordena_peor_primero(tmp_path):
    uv = _uv(Temple=["2026-09-28"], Patagonia=["2026-09-27"], Feriado=["2026-09-23"])
    r = run_js(f"calidadDatos({uv},{HOY})", tmp_path)
    assert r["estado"] == "stale"
    assert r["texto"].index("Feriado") < r["texto"].index("Patagonia")
    assert "Temple" not in r["texto"]
    # el detalle (tooltip) lista todas las marcas
    assert all(m in r["detalle"] for m in ("Temple", "Patagonia", "Feriado"))


def test_calidad_pipeline_caido_se_pone_rojo_con_el_paso_de_los_dias(tmp_path):
    # mismo HTML (datos hasta 28/09) mirado una semana después
    uv = _uv(Temple=["2026-09-28"], Patagonia=["2026-09-28"], Feriado=["2026-09-28"])
    assert run_js(f"calidadDatos({uv},new Date(2026,9,5))", tmp_path)["estado"] == "stale"


def test_calidad_sin_ultima_venta_devuelve_null(tmp_path):
    assert run_js(f"calidadDatos(null,{HOY})", tmp_path) is None
    assert run_js(f"calidadDatos([],{HOY})", tmp_path) is None


def _run_build_calidad(tmp_path, ultima_venta_js):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    fn = re.search(r"^function buildCalidadDatos\(.*?^\}\n", html, re.S | re.M)
    assert fn, "no se encontró buildCalidadDatos"
    dom = ("const _els={dataBadge:{className:'data-badge data-badge-fresh',title:'py'},"
           "dataBadgeTxt:{textContent:'Datos al 28 Sep 2026 · actualizado hoy'}};"
           "const document={getElementById:id=>_els[id]||null};\n")
    script = tmp_path / "badge.js"
    script.write_text(dom + _bloque(html, "FINANZAS_CORE") + _bloque(html, "EXCEPCIONES_CORE") + fn.group(0)
                      + f"const ULTIMA_VENTA={ultima_venta_js};buildCalidadDatos(new Date(2026,8,29));"
                      + "console.log(JSON.stringify([_els.dataBadge.className,_els.dataBadge.title,"
                      + "_els.dataBadgeTxt.textContent]));", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_build_calidad_pinta_el_badge_por_marca(tmp_path):
    cls, title, txt = _run_build_calidad(tmp_path, _uv(Temple=["2026-09-28"], Feriado=["2026-09-23"]))
    assert cls == "data-badge data-badge-stale"
    assert txt.startswith("Atrasado: Feriado hasta 23/09")
    assert "Temple: 28/09" in title


def test_build_calidad_sin_ultima_venta_deja_el_badge_del_pipeline(tmp_path):
    cls, title, txt = _run_build_calidad(tmp_path, "null")
    assert cls == "data-badge data-badge-fresh" and title == "py" and txt.startswith("Datos al 28 Sep")


def test_plantilla_badge_tiene_ids_para_el_render():
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert 'id="dataBadge"' in html and 'id="dataBadgeTxt"' in html
    assert "buildCalidadDatos()" in html


def test_calidad_todas_atrasadas_misma_fecha_resume_en_una_frase(tmp_path):
    # caso típico de pipeline caído: no repetir la fecha por marca
    uv = _uv(Temple=["2026-09-28"], Patagonia=["2026-09-28"], Feriado=["2026-09-28"])
    r = run_js(f"calidadDatos({uv},new Date(2026,8,30))", tmp_path)
    assert r["estado"] == "warn" and r["texto"] == "Atrasado: todas las marcas hasta 28/09"


def test_calidad_todas_atrasadas_distinta_fecha_lista_por_marca(tmp_path):
    uv = _uv(Temple=["2026-09-28"], Feriado=["2026-09-26"])
    assert run_js(f"calidadDatos({uv},new Date(2026,8,30))", tmp_path)["texto"] == \
        "Atrasado: Feriado hasta 26/09 · Temple hasta 28/09"


def test_plantilla_oculta_separador_del_header_en_celular():
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert re.search(r"@media \(max-width:480px\)\{\s*\.t-hdr-right \.t-sep\{display:none\}", html)
