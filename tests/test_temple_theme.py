"""El tema TEMPLE se inserta inline en los 3 HTML del tablero (se sirven estáticos desde GCS)."""
import os

import pytest

from temple_theme import LOGO_MARKER, THEME_MARKER, apply_theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_apply_theme_inserta_css_fuentes_y_logo():
    html = f'<head>{THEME_MARKER}</head><body><img src="{LOGO_MARKER}"></body>'
    out = apply_theme(html)
    assert THEME_MARKER not in out and LOGO_MARKER not in out
    assert '--t-slate:#323E48' in out
    assert 'fonts.googleapis.com' in out and 'Montserrat' in out and 'Oswald' in out
    assert 'src="data:image/png;base64,' in out


def test_apply_theme_sin_marcadores_no_cambia_nada():
    html = '<html><head></head><body>hola</body></html>'
    assert apply_theme(html) == html


@pytest.mark.parametrize('template', ['dashboard.html', 'producto_preview.html', 'resenas_preview.html'])
def test_plantillas_tienen_marcador_de_tema(template):
    with open(os.path.join(ROOT, 'templates', template), encoding='utf-8') as f:
        html = f.read()
    assert THEME_MARKER in html
    # Los HTML salen estáticos de GCS: nada de url_for ni rutas a /static
    assert 'url_for(' not in html and '/static/' not in html
