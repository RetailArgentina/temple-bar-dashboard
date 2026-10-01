"""WTC (Uruguay): carga manual mensual con conversión UYU→ARS.

Lo usan app.py (formulario /admin) y actualizar_retail.py (pipeline del tablero).
Spec: docs/superpowers/specs/2026-10-01-wtc-carga-manual-design.md
"""
import re
from datetime import date

MES_MIN = "2025-01"
_MESES_ES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
             "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


def _mes_str(y, m):
    return f"{y:04d}-{m:02d}" if 1 <= m <= 12 else None


def parse_mes(s):
    """'2025-01' | '01/2025' | 'ene-25' | 'ene-2025' → '2025-01'; None si no se entiende."""
    s = (s or "").strip().lower()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", s):
        return _mes_str(int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", s):
        return _mes_str(int(m[2]), int(m[1]))
    if m := re.fullmatch(r"([a-z]{3})-(\d{2}|\d{4})", s):
        if m[1] not in _MESES_ES:
            return None
        y = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
        return _mes_str(y, _MESES_ES[m[1]])
    return None


def parse_numero(s):
    """Formato argentino ('12.345.678,50', '1.234' = 1234) o plano ('12345678.50'). None si no es número ≥ 0."""
    s = (s or "").strip()
    if s.startswith("$"):
        s = s[1:]
    if not s:
        return None
    if "," in s:
        if s.count(",") > 1:
            return None
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    return float(s)


def wtc_parse_filas(texto, hoy):
    """Parsea el pegado del formulario. Devuelve (filas, errores).
    Fila: {"mes", "facturacion_uyu", "ordenes", "litros_cerveza"}; error: {"linea", "error"}.
    Con cualquier error no se debe guardar nada (lo decide quien llama)."""
    mes_max = f"{hoy.year:04d}-{hoy.month:02d}"
    filas, errores, vistos = [], [], set()
    primera = True
    for n, linea in enumerate((texto or "").splitlines(), start=1):
        if not linea.strip():
            continue
        campos = [c for c in re.split(r"[\t;]|\s+", linea.strip()) if c]
        if primera and campos[0].lower().startswith("mes"):
            primera = False
            continue
        primera = False
        if len(campos) != 4:
            errores.append({"linea": n, "error": f"se esperaban 4 columnas (mes, facturación UYU, órdenes, litros) y hay {len(campos)}"})
            continue
        mes = parse_mes(campos[0])
        if not mes:
            errores.append({"linea": n, "error": f"mes inválido: '{campos[0]}' (usar 2025-01, 01/2025 o ene-25)"})
            continue
        if not (MES_MIN <= mes <= mes_max):
            errores.append({"linea": n, "error": f"mes {mes} fuera de rango ({MES_MIN} a {mes_max})"})
            continue
        if mes in vistos:
            errores.append({"linea": n, "error": f"mes {mes} repetido en el pegado"})
            continue
        fac, ords, lts = (parse_numero(c) for c in campos[1:])
        if fac is None or ords is None or lts is None:
            errores.append({"linea": n, "error": "facturación, órdenes y litros deben ser números ≥ 0"})
            continue
        if ords != int(ords):
            errores.append({"linea": n, "error": f"órdenes debe ser entero: '{campos[2]}'"})
            continue
        vistos.add(mes)
        filas.append({"mes": mes, "facturacion_uyu": round(fac, 2), "ordenes": int(ords),
                      "litros_cerveza": round(lts, 2)})
    if not filas and not errores:
        errores.append({"linea": 0, "error": "No hay filas para cargar"})
    return filas, errores
