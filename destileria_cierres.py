"""Foto de cierre mensual del Tablero Destilería.

El día 1 de cada mes se guarda en GCS una foto del mes que cerró (comprobante ×
familia). Los datos del tablero siguen vivos; esta foto solo sirve para mostrar
qué cambió después del cierre: altas posteriores (ventas cargadas tarde, ej.
liquidación Travel Retail) vs. bajas/modificaciones (comprobantes anulados,
editados o COT convertidas en factura).
"""
import calendar
import json
from collections import defaultdict
from datetime import date, datetime

from google.api_core.exceptions import PreconditionFailed

PREFIJO = "destileria_cierres/"
PRIMER_MES = "2026-10"

_UMBRAL_LI = 0.01
_UMBRAL_TO = 1


def marca_de_familia(fa: str) -> str:
    fa = fa or ""
    if fa.startswith("bosque"):
        return "bosque"
    if fa.startswith("feriado"):
        return "feriado"
    if fa.startswith("lata") or fa.startswith("cerveza"):
        return "cerveza"
    return "merch"


def armar_lineas(filas: list) -> list:
    """Agrupa filas de Contabilium por (comprobante, familia)."""
    acc = {}
    for r in filas:
        k = f"{r['ic']}|{r['fa']}"
        if k not in acc:
            acc[k] = {"k": k, "ic": r["ic"], "nu": r["nu"], "f": r["f"], "nd": r["nd"],
                      "ti": r["ti"], "fa": r["fa"], "ce": 0, "li": 0.0, "to": 0.0}
        a = acc[k]
        a["ce"] += r["ce"]
        a["li"] += r["li"]
        a["to"] += r["to"]
    for a in acc.values():
        a["ce"] = int(round(a["ce"]))
        a["li"] = round(a["li"], 3)
        a["to"] = int(round(a["to"]))
    return list(acc.values())


def mes_a_fotografiar(hoy: date, existentes: set, primer_mes: str = PRIMER_MES):
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    m = f"{anio:04d}-{mes:02d}"
    if m < primer_mes or m in existentes:
        return None
    return m


def sync_ok_para_foto(estado, fecha_hasta, horas, mes: str) -> bool:
    """La foto es permanente: solo con el último sync Contabilium completo (estado OK),
    reciente (<= 24 h) y que haya cubierto hasta el último día del mes a fotografiar."""
    if estado != "OK" or not fecha_hasta or horas is None or horas > 24:
        return False
    anio, m = (int(x) for x in mes.split("-"))
    ultimo = f"{mes}-{calendar.monthrange(anio, m)[1]:02d}"
    return str(fecha_hasta)[:10] >= ultimo


def filtrar_mes(lineas: list, mes: str) -> list:
    return [l for l in lineas if str(l.get("f", "")).startswith(mes)]


def _mov(tipo, l, dce, dli, dto):
    return {"tipo": tipo, "etiqueta": "", "f": l["f"], "nd": l["nd"], "nu": l["nu"],
            "ti": l["ti"], "fa": l["fa"], "marca": marca_de_familia(l["fa"]),
            "dce": int(round(dce)), "dli": round(dli, 3), "dto": int(round(dto))}


def diferencia(foto: list, hoy: list) -> list:
    antes = {l["k"]: l for l in foto}
    ahora = {l["k"]: l for l in hoy}
    movs = []
    for k, l in ahora.items():
        if k not in antes:
            # Nota de crédito cargada tarde = anulación (a revisar), no venta nueva
            if str(l["ti"]).startswith("NC") or l["to"] < 0:
                m = _mov("baja", l, l["ce"], l["li"], l["to"])
                m["etiqueta"] = "Nota de crédito"
                movs.append(m)
            else:
                movs.append(_mov("alta", l, l["ce"], l["li"], l["to"]))
    for k, l in antes.items():
        if k not in ahora:
            movs.append(_mov("baja", l, -l["ce"], -l["li"], -l["to"]))
        else:
            n = ahora[k]
            dce, dli, dto = n["ce"] - l["ce"], n["li"] - l["li"], n["to"] - l["to"]
            if abs(dli) > _UMBRAL_LI or abs(dto) >= _UMBRAL_TO or dce != 0:
                movs.append(_mov("modificado", n, dce, dli, dto))

    # COT que desapareció + factura nueva del mismo cliente = conversión, no venta nueva
    cot_bajas = {m["nd"] for m in movs if m["tipo"] == "baja" and m["ti"] == "COT"}
    fc_altas = {m["nd"] for m in movs if m["tipo"] == "alta" and m["ti"] != "COT"}
    convertidos = cot_bajas & fc_altas
    for m in movs:
        if m["etiqueta"]:
            continue
        sin_unidades = m["dce"] == 0 and abs(m["dli"]) <= _UMBRAL_LI
        if m["nd"] in convertidos and (
                (m["tipo"] == "baja" and m["ti"] == "COT") or (m["tipo"] == "alta" and m["ti"] != "COT")):
            m["etiqueta"] = "COT convertida"
        # El generador no borra la COT facturada: le pone $0 (o se lo devuelve si el par
        # COT↔factura se deshace) y su factura entra sin unidades ni litros.
        elif m["tipo"] == "modificado" and m["ti"] == "COT" and sin_unidades:
            m["etiqueta"] = "COT convertida"
        elif m["tipo"] == "alta" and m["ti"] != "COT" and sin_unidades and m["dto"] > 0:
            m["etiqueta"] = "COT convertida"

    movs.sort(key=lambda m: (m["tipo"] == "alta", -abs(m["dli"])))
    return movs


def _suma(lineas, campo_li="li", campo_to="to"):
    out = defaultdict(lambda: {"li": 0.0, "to": 0})
    for l in lineas:
        m = l.get("marca") or marca_de_familia(l["fa"])
        out[m]["li"] += l[campo_li]
        out[m]["to"] += l[campo_to]
    return out


def resumen(foto: list, hoy: list, movs: list) -> dict:
    partes = {
        "cierre": _suma(foto),
        "hoy": _suma(hoy),
        "altas": _suma([m for m in movs if m["tipo"] == "alta"], "dli", "dto"),
        "bajas": _suma([m for m in movs if m["tipo"] != "alta"], "dli", "dto"),
    }
    marcas = set().union(*(p.keys() for p in partes.values()))
    res = {}
    for marca in sorted(marcas):
        res[marca] = {}
        for nombre, p in partes.items():
            v = p.get(marca, {"li": 0.0, "to": 0})
            res[marca][nombre] = {"li": round(v["li"], 3), "to": int(round(v["to"]))}
    return res


# ── GCS ──────────────────────────────────────────────────────────────────────

def _nombre_blob(mes: str) -> str:
    return f"{PREFIJO}{mes}.json"


def listar_fotos(bucket) -> set:
    return {b.name[len(PREFIJO):-len(".json")]
            for b in bucket.list_blobs(prefix=PREFIJO) if b.name.endswith(".json")}


def guardar_foto(bucket, mes: str, lineas: list, tomada: datetime) -> bool:
    """Guarda la foto del mes. Nunca sobrescribe: devuelve False si ya existía."""
    contenido = json.dumps({
        "mes": mes,
        "tomada": tomada.isoformat(timespec="minutes"),
        "tardia": tomada.day != 1,
        "lineas": lineas,
    }, ensure_ascii=False, separators=(",", ":"))
    blob = bucket.blob(_nombre_blob(mes))
    try:
        blob.upload_from_string(contenido.encode("utf-8"),
                                content_type="application/json; charset=utf-8",
                                if_generation_match=0)
    except PreconditionFailed:
        return False
    blob.cache_control = "no-cache, no-store, must-revalidate"
    blob.patch()
    return True


def cargar_fotos(bucket) -> list:
    fotos = [json.loads(b.download_as_text(encoding="utf-8"))
             for b in bucket.list_blobs(prefix=PREFIJO) if b.name.endswith(".json")]
    return sorted(fotos, key=lambda f: f["mes"], reverse=True)


def armar_cierres(fotos: list, lineas_hoy: list) -> list:
    out = []
    for foto in fotos:
        hoy = filtrar_mes(lineas_hoy, foto["mes"])
        movs = diferencia(foto["lineas"], hoy)
        out.append({"mes": foto["mes"], "tomada": foto["tomada"], "tardia": foto["tardia"],
                    "resumen": resumen(foto["lineas"], hoy, movs), "movs": movs})
    return out
