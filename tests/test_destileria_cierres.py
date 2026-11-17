from datetime import date, datetime

import pytest
from google.api_core.exceptions import PreconditionFailed

from destileria_cierres import (marca_de_familia, armar_lineas, mes_a_fotografiar,
                                filtrar_mes, diferencia, resumen,
                                listar_fotos, guardar_foto, cargar_fotos, armar_cierres)


def L(ic, fa="bosque_nativo", nd="CLI", ti="FCB", f="2026-10-12", ce=1, li=0.5, to=1000, nu=None):
    return {"k": f"{ic}|{fa}", "ic": ic, "nu": nu or str(ic), "f": f, "nd": nd, "ti": ti,
            "fa": fa, "ce": ce, "li": li, "to": to}


def test_marca_de_familia():
    assert marca_de_familia("bosque_nativo_mini") == "bosque"
    assert marca_de_familia("feriado_barril_20") == "feriado"
    assert marca_de_familia("lata_wolf") == "cerveza"
    assert marca_de_familia("cerveza_barril") == "cerveza"
    assert marca_de_familia("merch") == "merch"


def test_armar_lineas_agrupa_por_comprobante_y_familia():
    filas = [dict(f="2026-10-12", nd="A", fa="bosque_nativo", ti="FCB", ce=2, li=1.0, to=500.4, ic=7, nu="1"),
             dict(f="2026-10-12", nd="A", fa="bosque_nativo", ti="FCB", ce=1, li=0.5, to=250.2, ic=7, nu="1"),
             dict(f="2026-10-12", nd="A", fa="feriado_rojo",  ti="FCB", ce=1, li=0.75, to=300, ic=7, nu="1")]
    out = {l["k"]: l for l in armar_lineas(filas)}
    assert out["7|bosque_nativo"]["ce"] == 3 and out["7|bosque_nativo"]["li"] == 1.5 and out["7|bosque_nativo"]["to"] == 751
    assert "7|feriado_rojo" in out


def test_mes_a_fotografiar():
    assert mes_a_fotografiar(date(2026, 12, 1), set()) == "2026-11"
    assert mes_a_fotografiar(date(2026, 12, 2), set()) == "2026-11"          # día 1 falló
    assert mes_a_fotografiar(date(2026, 12, 5), {"2026-11"}) is None
    assert mes_a_fotografiar(date(2026, 10, 3), set()) is None               # 2026-09 < primer_mes
    assert mes_a_fotografiar(date(2027, 1, 1), set()) == "2026-12"


def test_filtrar_mes():
    assert [l["ic"] for l in filtrar_mes([L(1, f="2026-10-31"), L(2, f="2026-11-01")], "2026-10")] == [1]


def test_diferencia_alta_baja_modificado_y_redondeo():
    foto = [L(1), L(2, li=1.0), L(3, li=2.0, to=4000)]
    hoy  = [L(1, li=0.505, to=1000.4), L(3, li=1.0, to=2000), L(4, nd="TRAVEL", li=10.0, to=9000)]
    movs = diferencia(foto, hoy)
    assert sorted(m["tipo"] for m in movs) == ["alta", "baja", "modificado"]   # ic=1 no cambia (redondeo)
    m = [x for x in movs if x["tipo"] == "modificado"][0]
    assert m["dli"] == -1.0 and m["dto"] == -2000
    b = [x for x in movs if x["tipo"] == "baja"][0]
    assert b["dli"] == -1.0 and b["marca"] == "bosque"
    assert movs[-1]["tipo"] == "alta"


def test_diferencia_cot_convertida():
    foto = [L(10, nd="PASEO LA PLAZA", ti="COT", ce=80, li=40.0, to=0)]
    hoy  = [L(11, nd="PASEO LA PLAZA", ti="FCB", ce=24, li=12.0, to=50000)]
    movs = diferencia(foto, hoy)
    assert {m["tipo"]: m["etiqueta"] for m in movs} == {"baja": "COT convertida", "alta": "COT convertida"}
    assert movs[0]["tipo"] == "baja"


def test_resumen_por_marca():
    foto = [L(1, li=2.0, to=100), L(2, fa="feriado_rojo", li=1.0, to=50)]
    hoy  = [L(1, li=2.0, to=100), L(3, li=5.0, to=300)]
    movs = diferencia(foto, hoy)
    r = resumen(foto, hoy, movs)
    assert r["bosque"]["cierre"] == {"li": 2.0, "to": 100} and r["bosque"]["hoy"] == {"li": 7.0, "to": 400}
    assert r["bosque"]["altas"]["li"] == 5.0
    assert r["feriado"]["bajas"] == {"li": -1.0, "to": -50}


# ── GCS (Tarea 2) ─────────────────────────────────────────────────────────────

class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name, self.cache_control = store, name, None

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self.name in self.store:
            raise PreconditionFailed("existe")
        self.store[self.name] = data if isinstance(data, str) else data.decode("utf-8")

    def download_as_text(self, encoding="utf-8"):
        return self.store[self.name]

    def patch(self):
        pass


class FakeBucket:
    def __init__(self):
        self.store = {}

    def blob(self, name):
        return FakeBlob(self.store, name)

    def list_blobs(self, prefix=""):
        return [FakeBlob(self.store, n) for n in sorted(self.store) if n.startswith(prefix)]


def test_guardar_foto_no_sobrescribe():
    b = FakeBucket()
    assert guardar_foto(b, "2026-10", [L(1)], datetime(2026, 11, 1, 9, 0)) is True
    assert guardar_foto(b, "2026-10", [L(2)], datetime(2026, 11, 2, 9, 0)) is False
    assert cargar_fotos(b)[0]["lineas"][0]["ic"] == 1


def test_guardar_foto_tardia():
    b = FakeBucket()
    guardar_foto(b, "2026-10", [], datetime(2026, 11, 17, 9, 0))
    guardar_foto(b, "2026-11", [], datetime(2026, 12, 1, 9, 0))
    fotos = {f["mes"]: f for f in cargar_fotos(b)}
    assert fotos["2026-10"]["tardia"] is True and fotos["2026-11"]["tardia"] is False
    assert fotos["2026-10"]["tomada"] == "2026-11-17T09:00"


def test_listar_y_cargar_fotos():
    b = FakeBucket()
    guardar_foto(b, "2026-10", [], datetime(2026, 11, 1))
    guardar_foto(b, "2026-11", [], datetime(2026, 12, 1))
    assert listar_fotos(b) == {"2026-10", "2026-11"}
    assert [f["mes"] for f in cargar_fotos(b)] == ["2026-11", "2026-10"]


def test_armar_cierres_solo_mira_el_mes_de_la_foto():
    b = FakeBucket()
    guardar_foto(b, "2026-10", [L(1)], datetime(2026, 11, 1))
    c = armar_cierres(cargar_fotos(b), [L(1), L(9, f="2026-11-03")])
    assert len(c) == 1 and c[0]["mes"] == "2026-10" and c[0]["movs"] == []
    assert c[0]["resumen"]["bosque"]["cierre"] == c[0]["resumen"]["bosque"]["hoy"]
