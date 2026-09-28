"""Tema visual TEMPLE para los HTML del tablero retail (Ventas, Producto, Reseñas).

Los tres HTML se generan como archivos estáticos y se sirven desde GCS (Ventas vía
app.py /dashboard, Producto y Reseñas por iframe), así que no pueden linkear a /static.
apply_theme() inserta inline la hoja static/temple-retail.css y el logo en base64.

Marcadores en las plantillas:
  <!--TEMPLE_THEME-->  en el <head>  → fuentes de Google + <style> con temple-retail.css
  __TEMPLE_LOGO__      en un src     → data URI del logo TEMPLE
"""
import base64
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
CSS_PATH = os.path.join(_BASE, 'static', 'temple-retail.css')
LOGO_PATH = os.path.join(_BASE, 'static', 'img', 'logo-temple.png')

THEME_MARKER = '<!--TEMPLE_THEME-->'
LOGO_MARKER = '__TEMPLE_LOGO__'

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Montserrat:wght@400;500;700&family=Oswald:wght@700&display=swap">'
)


def apply_theme(html):
    """Devuelve html con el CSS y el logo TEMPLE insertados en sus marcadores."""
    if THEME_MARKER in html:
        with open(CSS_PATH, 'r', encoding='utf-8') as f:
            css = f.read()
        html = html.replace(THEME_MARKER, _FONTS + '<style>\n' + css + '</style>', 1)
    if LOGO_MARKER in html:
        with open(LOGO_PATH, 'rb') as f:
            logo = base64.b64encode(f.read()).decode('ascii')
        html = html.replace(LOGO_MARKER, 'data:image/png;base64,' + logo)
    return html
