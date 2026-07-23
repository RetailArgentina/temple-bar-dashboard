"""
backfill_resenas_gestion.py — Carga inicial (one-off) de google_reviews_gestion.

google_reviews_sync.py solo crea docs de gestión para reseñas negativas
detectadas como NUEVAS a partir de su despliegue (compara contra
seen_review_keys, que ya venía acumulando historial de antes). Las reseñas
negativas que ya existían en ese momento no se cargan retroactivamente.

Este script lee el snapshot público ya generado (resenas.html en GCS) y
crea en Firestore un doc por cada reseña con rating <= 2, usando la misma
key estable que usa el sync (_review_key: author_name|time). Es idempotente
vía permissions.create_gestion_if_not_exists — nunca pisa un doc que ya
esté en_curso/resuelta, así que correrlo de nuevo no duplica ni resetea
nada. Pensado para correrse una sola vez después de habilitar la Fase 2
de gestión de reseñas; queda en el repo como referencia/reutilizable si
hiciera falta re-seedear en otro entorno.

Uso: python backfill_resenas_gestion.py
"""
import json
import re
import sys
import urllib.request

import permissions
from google.cloud import firestore

RESENAS_URL = "https://storage.googleapis.com/temple-bar-dashboard-cache/resenas.html"


def _review_key(review):
    """Idéntica a _review_key() en google_reviews_sync.py — debe mantenerse en sync."""
    author = review.get("author_name", "")
    if review.get("time"):
        return f"{author}|{review['time']}"
    return f"{author}|{review.get('date_str', '')}|{review.get('rating', '')}"


def main():
    print(f"Descargando {RESENAS_URL} ...")
    with urllib.request.urlopen(RESENAS_URL) as resp:
        html = resp.read().decode("utf-8")

    m = re.search(r"const RESENAS\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        print("ERROR: no se encontró 'const RESENAS = {...};' en resenas.html")
        sys.exit(1)
    resenas = json.loads(m.group(1))

    db = firestore.Client()

    created = 0
    already = 0
    total_negative = 0

    for marca_key, entries in resenas["por_marca"].items():
        for entry in entries:
            local = entry["local"]
            for r in entry.get("reviews", []):
                rating = r.get("rating")
                if rating is None or rating > 2:
                    continue
                total_negative += 1
                doc_id = _review_key(r)
                result = permissions.create_gestion_if_not_exists(
                    db,
                    doc_id,
                    marca_key,
                    local,
                    rating,
                    r.get("text", ""),
                    r.get("author_name", ""),
                    r.get("date_str", ""),
                )
                if result.get("created"):
                    created += 1
                    print(f"  + creado: {marca_key}/{local} rating={rating} author={r.get('author_name')!r}")
                else:
                    already += 1

    print()
    print(f"Total reseñas rating<=2 encontradas: {total_negative}")
    print(f"Docs creados nuevos: {created}")
    print(f"Ya existían (no pisados): {already}")


if __name__ == "__main__":
    main()
