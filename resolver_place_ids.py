#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resolver_place_ids.py
P3 del plan "tablero de reseñas Google".

Resuelve el place_id de Google Maps para cada local activo (Marca, Local)
que aparece en `vw_Ventas_Corporativo_Base` (últimos 365 días), usando
Google Places Text Search, y guarda los candidatos en Firestore
(colección `google_places_mapping`, vía permissions.set_places_mapping)
con status="pending" — SIEMPRE pending, la verificación humana es otra tarea.

Uso:
    python -X utf8 resolver_place_ids.py --dry-run   # no llama a la API ni a BQ/Firestore de escritura,
                                                       # solo imprime qué query mandaría por local
    python -X utf8 resolver_place_ids.py              # corrida real (requiere PLACES_API_KEY)
"""

import os
import sys
import argparse
from datetime import datetime

import httpx
from google.cloud import bigquery

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SA_KEY     = os.path.join(SCRIPT_DIR, "temple-bar-439715-da51b292ce5d.json")
BQ_PROJECT = "temple-bar-439715"

PLACES_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
MAX_CANDIDATES = 3

QUERY_LOCALES = """
SELECT DISTINCT Marca, Local
FROM `temple-bar-439715.Corporativo.vw_Ventas_Corporativo_Base`
WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY Marca, Local
"""

# Completar a mano: la clave es "MARCA__LOCAL" tal como aparece en BQ, el valor es
# la query de texto a mandar a Google Places Text Search. None = todavía sin curar.
# Los locales de abajo tienen nombre ambiguo (código interno, ciudad pura, o marca
# distinta a la esperada en Google Maps) y NO deben resolverse automáticamente.
CURATED_QUERIES = {
    # -- Ciudades/capitales de nombre puro: pueden matchear cualquier bar de
    #    esa ciudad en Google Maps, no solo el local propio --
    # Curadas 2026-07-22 probando cada query contra la Places API real y
    # verificando que el resultado tenga la marca + ciudad esperada. Todas
    # quedan como status=pending igual — requieren aprobación manual en el
    # admin antes de usarse.
    "Temple__SALTA": "Temple Craft Salta",
    "Patagonia__SALTA": "Cerveza Patagonia Refugio Salta",
    "Patagonia__JUJUY": "Cerveza Patagonia Refugio Jujuy",
    "Patagonia__NEUQUEN": "Cerveza Patagonia Refugio Neuquen",
    "Patagonia__COMODORO": "Cerveza Patagonia Refugio Comodoro Rivadavia",
    "Temple__COMODORO RIVADAVIA": "Temple Craft Comodoro Rivadavia",
    "Patagonia__BAHIA BLANCA": "Cerveza Patagonia Refugio Bahia Blanca",
    "Patagonia__PARANA": "Cerveza Patagonia Refugio Parana",
    "Patagonia__RESISTENCIA": "Cerveza Patagonia Refugio Resistencia",
    "Temple__CORRIENTES": "Temple Corrientes bar",
    "Temple__POSADAS": "Temple Craft Posadas",
    # SAN JUAN sin resolver: "Temple Craft San Juan" y "Temple San Juan bar"
    # matchean con locales de Buenos Aires (hay una Av. San Juan en CABA y un
    # "Temple Craft Hollywood" que gana por relevancia) — no la provincia. No
    # se encontró una query que devuelva un local en la provincia de San Juan.
    "Temple__SAN JUAN": None,
    "Temple__LA PLATA": "Temple Craft La Plata",
    "Temple__SANTIAGO DEL ESTERO": "Temple Craft Santiago del Estero",
    "Temple__RIO GALLEGOS": "Temple Rio Gallegos bar",
    "Patagonia__RIO GALLEGOS": "Cerveza Patagonia Refugio Rio Gallegos",
    "Patagonia__USHUAIA": "Cerveza Patagonia Refugio Ushuaia",
    # -- Códigos internos (sin significado geográfico obvio por sí solos) --
    "Patagonia__TCM - ABASTO": "Cerveza Patagonia Abasto Tucuman",
    "Patagonia__TCM - ACONQUIJA": "Cerveza Patagonia Aconquija Tucuman",
    "Patagonia__TCM - SHERATON": "Cerveza Patagonia Sheraton Tucuman",
    "Patagonia__BA - LANUS": "Cerveza Patagonia Refugio Lanus",
    # MERCADO CENTRAL (GUEMES) sin resolver: dos variantes de query devolvieron
    # dos locales YA MAPEADOS distintos de Córdoba ("Refugio Plaza de la
    # Música" y "Refugio Córdoba"), ninguno menciona "Mercado" ni "Guemes" en
    # el nombre — no hay forma de confirmar cuál es sin verificar a mano en
    # Google Maps qué local de Córdoba corresponde a este.
    "Patagonia__CBA - MERCADO CENTRAL (GUEMES)": None,
    "Patagonia__SFE - ALTO ROSARIO": "Cerveza Patagonia Alto Rosario Shopping",
    "Patagonia__SGO - SANTIAGO DEL ESTERO": "Cerveza Patagonia Refugio Santiago del Estero",
    "Patagonia__MIS - POSADAS": "Cerveza Patagonia Refugio Posadas Misiones",
    "Patagonia__CAT - CATAMARCA": "Cerveza Patagonia Refugio Catamarca",
    # Confianza moderada: el resultado es "Cerveza Patagonia - Jardín
    # Cervecero Corrientes" (no "Refugio Corrientes") — marca y ciudad
    # correctas, pero el sub-nombre distinto amerita doble check en el admin.
    "Patagonia__COR - CORRIENTES": "Cerveza Patagonia Refugio Corrientes",
    # Los 4 "DK*" de abajo sin resolver: todas las variantes probadas
    # devuelven otros locales de Temple YA MAPEADOS en Buenos Aires (Palermo,
    # Craft Hollywood, Craft Recoleta, Club Temple) en vez de un local propio
    # de este barrio — sugiere que en Google Maps no figuran con "Temple" ni
    # con el nombre del barrio solo. Revisar a mano qué nombre usan en Maps.
    "Temple__DK MONTE CASTRO": None,
    "Temple__DK MORENO": None,
    "Temple__DK OLIVOS": None,
    # A diferencia de los otros DK*, esta sí resolvió limpio: resultado único
    # "Temple San Martin" en Ayacucho 2668, San Martín (partido bonaerense).
    "Temple__DK SAN MARTIN": "Temple San Martin bar",
    "Temple__DK SAN MIGUEL": None,
    # DK TERRAZAS DE MAYO no aparece en los últimos 365 días de BQ (local
    # inactivo o cerrado en la ventana de la query). Se infiere marca Temple
    # por consistencia con el resto de locales "DK*" (todos son Temple según
    # el dry-run), pero no está confirmado contra una fila real de BQ.
    # Tampoco se encontró un match propio en Places (solo devolvió el
    # shopping "Terrazas de Mayo" en sí, no un local de Temple adentro).
    "Temple__DK TERRAZAS DE MAYO": None,
    # Tampoco aparecen en los últimos 365 días de BQ bajo ningún nombre
    # reconocible (ni "BA - ARCOS" ni "BA - MONTE GRANDE" en ninguna marca).
    # Se dejan con la clave original sin confirmar — revisar manualmente si
    # el local sigue activo y bajo qué nombre/marca aparece hoy en BQ.
    # Intentos de Places tampoco encontraron nada plausible (BA - MONTE
    # GRANDE matcheó "El templo bar", un negocio sin relación).
    "Temple__BA - ARCOS": None,
    "Temple__BA - MONTE GRANDE": None,
}

# Normalizamos las claves del dict una sola vez para que el match no falle
# por diferencias triviales de mayúsculas/espacios entre BQ y este archivo.
_CURATED_QUERIES_NORM = {
    key.upper().strip(): value for key, value in CURATED_QUERIES.items()
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_bq_client():
    import google.auth
    try:
        creds, _ = google.auth.default()
        return bigquery.Client(project=BQ_PROJECT, credentials=creds)
    except Exception as _adc_err:
        log(f"  ADC falló ({_adc_err!r}), usando service account key como fallback")
        return bigquery.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


def get_firestore_client():
    from google.cloud import firestore
    import google.auth
    try:
        creds, _ = google.auth.default()
        return firestore.Client(project=BQ_PROJECT, credentials=creds)
    except Exception as _adc_err:
        log(f"  ADC falló ({_adc_err!r}), usando service account key como fallback")
        return firestore.Client.from_service_account_json(SA_KEY, project=BQ_PROJECT)


def obtener_locales_activos():
    """Devuelve lista de dicts {marca, local} desde BQ."""
    client = get_bq_client()
    rows = client.query(QUERY_LOCALES).result()
    return [{"marca": row["Marca"], "local": row["Local"]} for row in rows]


def resolver_query(marca: str, local: str):
    """
    Determina qué query de texto usar para un local dado, o None si hay
    que omitirlo (está en CURATED_QUERIES pero todavía sin curar a mano).

    Devuelve una tupla (query, omitido: bool).
    """
    clave = f"{marca}__{local}".upper().strip()
    if clave in _CURATED_QUERIES_NORM:
        curada = _CURATED_QUERIES_NORM[clave]
        if curada is None:
            return None, True  # sin curar todavía -> omitir
        return curada, False
    # No está en el dict de ambiguos -> nombre no ambiguo, autogenerar
    return f"{marca} {local}", False


def buscar_candidatos_google(query: str) -> list:
    """Llama a Google Places Text Search y devuelve hasta MAX_CANDIDATES candidatos."""
    api_key = os.environ.get("PLACES_API_KEY")
    resp = httpx.get(PLACES_TEXTSEARCH_URL, params={
        "query": query,
        "key": api_key,
        "language": "es",
        "region": "ar",
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        raise RuntimeError(f"Places API status={data.get('status')} error={data.get('error_message')}")

    candidatos = []
    for r in data.get("results", [])[:MAX_CANDIDATES]:
        candidatos.append({
            "place_id": r.get("place_id"),
            "name": r.get("name"),
            "formatted_address": r.get("formatted_address"),
            "rating": r.get("rating"),
        })
    return candidatos


def main():
    parser = argparse.ArgumentParser(description="Resuelve place_ids de Google Maps para locales activos.")
    parser.add_argument("--dry-run", action="store_true",
                         help="No llama a la API de Google ni escribe en Firestore; solo imprime las queries que mandaría.")
    args = parser.parse_args()

    dry_run = args.dry_run
    api_key = os.environ.get("PLACES_API_KEY")

    if not api_key and not dry_run:
        log("ERROR: la variable de entorno PLACES_API_KEY no está seteada en este entorno.")
        log("Este proyecto (Claude_Cowork) todavía no tiene esa key configurada — solo existe en Proyecto_Locales_Propios.")
        log("Corré con --dry-run para verificar el script sin llamar a la API, o seteá PLACES_API_KEY y volvé a correr.")
        sys.exit(1)

    if not api_key and dry_run:
        log("Aviso: PLACES_API_KEY no está seteada. Como es --dry-run, se continúa igual sin llamar a la API real.")

    log("Obteniendo locales activos desde BigQuery (últimos 365 días)...")
    try:
        locales = obtener_locales_activos()
    except Exception as exc:
        log(f"ERROR al consultar BigQuery: {exc!r}")
        sys.exit(1)
    log(f"Locales activos encontrados: {len(locales)}")

    db = None
    if not dry_run:
        try:
            db = get_firestore_client()
        except Exception as exc:
            log(f"ERROR al conectar con Firestore: {exc!r}")
            sys.exit(1)

    from permissions import set_places_mapping, list_places_mapping

    # No volver a tocar locales que un humano ya aprobó o rechazó en el admin
    # — re-resolverlos pisaría esa decisión con status="pending" de nuevo.
    ya_decididos = set()
    if not dry_run:
        mapping_actual = list_places_mapping(db)
        ya_decididos = {
            doc_id for doc_id, datos in mapping_actual.items()
            if datos.get("status") in ("verified", "rejected")
        }

    resueltos = 0
    omitidos = 0
    fallidos = 0
    saltados_decididos = 0

    for loc in locales:
        marca = loc["marca"]
        local = loc["local"]

        if f"{marca}__{local}" in ya_decididos:
            saltados_decididos += 1
            continue

        query, omitido = resolver_query(marca, local)

        if omitido:
            log(f"⚠ Sin curar, omitido: {marca} {local}")
            omitidos += 1
            continue

        if dry_run:
            log(f"[dry-run] {marca} / {local} -> query: \"{query}\"")
            continue

        try:
            candidatos = buscar_candidatos_google(query)
        except Exception as exc:
            log(f"✗ Falló búsqueda para {marca} {local} (query=\"{query}\"): {exc!r}")
            fallidos += 1
            continue

        if not candidatos:
            log(f"✗ Sin resultados de Google para {marca} {local} (query=\"{query}\")")
            fallidos += 1
            continue

        primero = candidatos[0]
        resultado = set_places_mapping(
            db,
            marca=marca,
            local=local,
            place_id=primero["place_id"],
            display_name_google=primero.get("name"),
            formatted_address=primero.get("formatted_address"),
            status="pending",
            search_query_used=query,
            candidates=candidatos,
        )
        if resultado.get("ok"):
            log(f"✓ {marca} {local} -> {len(candidatos)} candidato(s), top: \"{primero.get('name')}\" ({primero.get('place_id')})")
            resueltos += 1
        else:
            log(f"✗ Falló guardado en Firestore para {marca} {local}: {resultado.get('error')}")
            fallidos += 1

    log("")
    log("=== Resumen ===")
    log(f"Total locales activos: {len(locales)}")
    if dry_run:
        log(f"Queries que se mandarían: {len(locales) - omitidos}")
        log(f"Omitidos (sin curar en CURATED_QUERIES): {omitidos}")
    else:
        log(f"Resueltos con candidatos guardados (status=pending): {resueltos}")
        log(f"Omitidos (sin curar en CURATED_QUERIES): {omitidos}")
        log(f"Fallidos (sin resultados o error de API/Firestore): {fallidos}")
        log(f"Saltados (ya verified/rejected por un humano, no se tocan): {saltados_decididos}")


if __name__ == "__main__":
    main()
