"""tests/test_wtc_admin.py — rutas /api/admin/wtc* (BigQuery simulado)."""
from contextlib import ExitStack
from unittest.mock import patch

from tests.test_auth import client, _set_session  # noqa: F401  (fixture reutilizado)

TEXTO_OK = "2025-01\t1.000.000\t500\t1.200"


def _patch_bq(stack, cargados=(), cotiz=None):
    """Simula BigQuery en wtc. Devuelve el mock de guardar_filas."""
    import wtc
    stack.enter_context(patch.object(wtc, "leer_carga", return_value=[{"mes": m} for m in cargados]))
    stack.enter_context(patch.object(wtc, "leer_cotizaciones", return_value=cotiz or {}))
    return stack.enter_context(patch.object(wtc, "guardar_filas", side_effect=lambda c, f, e: len(f)))


def test_wtc_preview_convierte_marca_reemplaza_y_no_escribe(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        guardar = _patch_bq(s, cargados=["2025-01"], cotiz={"2025-01": 23.6})
        r = c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK})
    d = r.get_json()
    assert r.status_code == 200 and d["ok"] is True and d["errores"] == []
    f = d["filas"][0]
    assert f["ars_por_uyu"] == 23.6 and f["ars"] == 23600000.0 and f["reemplaza"] is True
    guardar.assert_not_called()


def test_wtc_preview_mes_sin_cotizacion(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        _patch_bq(s)
        f = c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK}).get_json()["filas"][0]
    assert f["ars_por_uyu"] is None and f["ars"] is None and f["reemplaza"] is False


def test_wtc_post_guarda_con_email_de_sesion(client):
    c, app = client
    _set_session(c, app, role="superadmin")
    with ExitStack() as s:
        guardar = _patch_bq(s)
        r = c.post("/api/admin/wtc", json={"texto": TEXTO_OK})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "escritas": 1}
    assert guardar.call_args[0][2] == "superadmin@temple.com.ar"


def test_wtc_post_con_error_no_escribe(client):
    # Review Focus #5: una fila mala en el pegado → no se guarda nada
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        guardar = _patch_bq(s)
        r = c.post("/api/admin/wtc", json={"texto": TEXTO_OK + "\n2025-02 abc 1 1"})
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert r.get_json()["errores"][0]["linea"] == 2
    guardar.assert_not_called()


def test_wtc_post_revalida_desde_texto(client):
    # Review Focus #5: el servidor ignora "filas" mandadas por el navegador
    c, app = client
    _set_session(c, app, role="gerencia")
    with ExitStack() as s:
        guardar = _patch_bq(s)
        r = c.post("/api/admin/wtc", json={"texto": "", "filas": [{"mes": "2025-01", "facturacion_uyu": -1}]})
    assert r.status_code == 400
    guardar.assert_not_called()


def test_wtc_get_lista_con_ars(client):
    import wtc
    c, app = client
    _set_session(c, app, role="gerencia")
    fila = {"mes": "2025-01", "facturacion_uyu": 1000.0, "ordenes": 5, "litros_cerveza": 2.0,
            "cargado_por": "a@b", "cargado_en": "2026-10-01T12:00:00+00:00"}
    with patch.object(wtc, "leer_carga", return_value=[fila]), \
         patch.object(wtc, "leer_cotizaciones", return_value={"2025-01": 23.6}):
        d = c.get("/api/admin/wtc").get_json()
    assert d["ok"] is True and d["filas"][0]["ars"] == 23600.0 and d["filas"][0]["ars_por_uyu"] == 23.6


def test_wtc_preview_bq_caido_502(client):
    import wtc
    c, app = client
    _set_session(c, app, role="gerencia")
    with patch.object(wtc, "leer_carga", side_effect=RuntimeError("BQ 503")):
        r = c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK})
    assert r.status_code == 502 and r.get_json()["ok"] is False


def test_wtc_bloquea_viewer(client):
    c, app = client
    _set_session(c, app, role="viewer")
    assert c.get("/api/admin/wtc").status_code == 403
    assert c.post("/api/admin/wtc", json={"texto": TEXTO_OK}).status_code == 403
    assert c.post("/api/admin/wtc/preview", json={"texto": TEXTO_OK}).status_code == 403


def test_wtc_post_requiere_csrf(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        with ExitStack() as s:
            guardar = _patch_bq(s)
            r = c.post("/api/admin/wtc", json={"texto": TEXTO_OK})
        assert r.status_code == 400
        guardar.assert_not_called()
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_admin_muestra_pestana_wtc_con_csrf_jinja(client):
    c, app = client
    _set_session(c, app, role="gerencia")
    html = c.get("/admin").get_data(as_text=True)
    assert 'id="tab-wtc"' in html and "switchTab('wtc')" in html
    assert "/api/admin/wtc/preview" in html
    # CSRF desde la variable Jinja, nunca de cookie
    assert "'X-CSRFToken': CSRF_TOKEN" in html and "document.cookie" not in html
