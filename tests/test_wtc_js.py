"""tests/test_wtc_js.py — nota WTC del tablero retail y same-store con WTC (Node)."""
import pytest

from tests.test_finanzas_js import run_js, run_dom_js, pytestmark  # noqa: F401  (skip sin Node)

INFO_OK = ('{error:false,meses:["2026-09"],sin_cotizacion:[],ultimo_cerrado:"2026-09",'
           'mes_actual:"2026-10",falta_ultimo_cerrado:false,falta_mes_actual:true}')
FN = ["_wtcMes", "wtcNotaTexto"]


def test_wtc_nota_ventas_basica_y_mes_en_curso(tmp_path):
    t = run_dom_js(FN, "", f"wtcNotaTexto({INFO_OK},false)", tmp_path)
    assert t.startswith("WTC (Uruguay): carga manual mensual, convertida al oficial BCRA.")
    assert "Mes en curso (oct-26) sin cargar." in t and "deflacta" not in t


def test_wtc_nota_finanzas_aclara_ipc_y_same_store(tmp_path):
    t = run_dom_js(FN, "", f"wtcNotaTexto({INFO_OK},true)", tmp_path)
    assert "IPC argentino" in t and "same-store" in t


def test_wtc_nota_avisos(tmp_path):
    info = ('{error:false,meses:[],sin_cotizacion:["2026-08","2026-09"],ultimo_cerrado:"2026-09",'
            'mes_actual:"2026-10",falta_ultimo_cerrado:true,falta_mes_actual:false}')
    t = run_dom_js(FN, "", f"wtcNotaTexto({info},false)", tmp_path)
    assert "Falta cargar sep-26." in t and "Sin cotización BCRA (no sumados): ago-26, sep-26." in t


def test_wtc_nota_error_y_null(tmp_path):
    r = run_dom_js(FN, "", '[wtcNotaTexto({error:true,meses:[],sin_cotizacion:[]},false),wtcNotaTexto(null,false)]',
                   tmp_path)
    assert "No se pudo leer la carga de WTC" in r[0] and r[1] == ""


@pytest.mark.parametrize("marca,display", [("todas", "block"), ("Patagonia", "block"), ("Temple", "none")])
def test_build_wtc_nota_se_oculta_en_otras_marcas(tmp_path, marca, display):
    setup = f'const WTC_INFO={INFO_OK};const STATE={{marca:"{marca}"}};buildWtcNota();'
    r = run_dom_js(FN + ["buildWtcNota"], setup,
                   "[_els.wtcNotaVentas.style.display,_els.wtcNotaFin.style.display,_els.wtcNotaFin.textContent]",
                   tmp_path)
    assert r[0] == display and r[1] == display and r[2].startswith("WTC (Uruguay)")


def test_same_store_incluye_wtc_solo_con_mismo_mes_del_anio_anterior(tmp_path):
    base = ('{mes:"2026-09",m:"Patagonia",l:"PALERMO",fac:100,ord:10},'
            '{mes:"2025-09",m:"Patagonia",l:"PALERMO",fac:80,ord:10},'
            '{mes:"2026-09",m:"Patagonia",l:"WTC",fac:90,ord:20}')
    sin = run_js(f'finLocalesComunes([{base}],"Patagonia",["2026-09"],["2025-09"]).map(r=>r.l)', tmp_path)
    con = run_js(f'finLocalesComunes([{base},{{mes:"2025-09",m:"Patagonia",l:"WTC",fac:70,ord:20}}],'
                 f'"Patagonia",["2026-09"],["2025-09"]).map(r=>r.l)', tmp_path)
    assert "WTC" not in sin and "WTC" in con
