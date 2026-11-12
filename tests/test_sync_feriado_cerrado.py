"""Feriado cerrado: el chequeo de gap histórico no corre y borra el banner (12/11/2026)."""
import sys
import types
from datetime import date

import sync_feriado_toteat as s


class _Blob:
    def __init__(self, existe):
        self.existe, self.borrado = existe, False

    def exists(self):
        return self.existe

    def delete(self):
        self.borrado = True


def _fake_storage(monkeypatch, blob):
    cliente = types.SimpleNamespace(bucket=lambda _b: types.SimpleNamespace(blob=lambda _n: blob))
    mod = types.SimpleNamespace(Client=lambda: cliente)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", mod)
    monkeypatch.setattr(sys.modules["google.cloud"], "storage", mod, raising=False)


def _hoy(monkeypatch, d):
    class _D(date):
        @classmethod
        def today(cls):
            return d
    monkeypatch.setattr(s, "date", _D)


def _sin_bq_ni_toteat(monkeypatch):
    def _no(*a, **k):
        raise AssertionError("no debería consultar Toteat")
    monkeypatch.setattr(s, "fetch_ventas", _no)

    def _no_bq(*a, **k):
        raise AssertionError("no debería consultar BQ")
    return types.SimpleNamespace(query=_no_bq)


def test_feriado_cerrado_no_verifica_y_borra_el_alert(monkeypatch):
    blob = _Blob(existe=True)
    _fake_storage(monkeypatch, blob)
    _hoy(monkeypatch, date(2026, 11, 12))
    assert s.verificar_gap_historico(_sin_bq_ni_toteat(monkeypatch), dry_run=False) is True
    assert blob.borrado


def test_feriado_cerrado_dry_run_no_toca_gcs(monkeypatch):
    blob = _Blob(existe=True)
    _fake_storage(monkeypatch, blob)
    _hoy(monkeypatch, date(2026, 11, 12))
    assert s.verificar_gap_historico(_sin_bq_ni_toteat(monkeypatch), dry_run=True) is True
    assert not blob.borrado
