"""
permissions.py — Manejo de permisos basado en Firestore.

Reemplaza el sistema de whitelist.txt con permisos por usuario
almacenados en la colección "users_config" de Firestore.

Estructura de cada documento en users_config (doc ID = email en minúsculas):
    {
        "role": "superadmin" | "editor" | "viewer",
        "brands": ["bosque", "feriado"] | ["*"],
        "can_edit_objectives": True | False,
    }
"""
from __future__ import annotations
from typing import Optional
import logging
from datetime import datetime, timedelta, timezone
from google.cloud import firestore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

BRAND_FAMILIES = {
    "bosque":  ["bosque_"],
    "feriado": ["feriado_"],
    "cerveza": ["lata_"],
    "merch":   ["merch"],
}

VALID_ROLES = ("superadmin", "gerencia", "editor", "viewer")

COLLECTION = "users_config"


# ---------------------------------------------------------------------------
# Funciones de consulta
# ---------------------------------------------------------------------------

def get_available_brands() -> "list[str]":
    """Devuelve la lista ordenada de nombres de marcas disponibles."""
    return sorted(BRAND_FAMILIES.keys())


def get_user_permissions(db, email: str) -> Optional[dict]:
    """
    Busca los permisos del usuario en Firestore.

    Args:
        db:    Cliente de Firestore (google.cloud.firestore.Client).
        email: Email del usuario (se normaliza a minúsculas).

    Returns:
        Dict con {"role", "brands", "can_edit_objectives"} si existe,
        None si el usuario no está registrado.
    """
    normalized = email.lower()
    doc = db.collection(COLLECTION).document(normalized).get()
    if not doc.exists:
        return None
    return doc.to_dict()


def resolve_brand_families(brands: "list[str]") -> "list[str]":
    """
    Convierte nombres de marcas a sus prefijos de tabla/colección.

    Args:
        brands: Lista de marcas (p. ej. ["bosque", "cerveza"]) o ["*"] para todas.

    Returns:
        Lista de prefijos correspondientes (p. ej. ["bosque_", "lata_"]).
        Devuelve [] si brands está vacío.
    """
    if not brands:
        return []

    if brands == ["*"]:
        prefixes = []
        for ps in BRAND_FAMILIES.values():
            prefixes.extend(ps)
        return prefixes

    prefixes = []
    for brand in brands:
        if brand in BRAND_FAMILIES:
            prefixes.extend(BRAND_FAMILIES[brand])
    return prefixes


# ---------------------------------------------------------------------------
# Helpers de validación
# ---------------------------------------------------------------------------

def _validate_role(role: str) -> Optional[str]:
    """Devuelve un mensaje de error si el rol no es válido, o None si es correcto."""
    if role not in VALID_ROLES:
        return f"Rol inválido: '{role}'. Debe ser uno de: {', '.join(VALID_ROLES)}"
    return None


def _validate_brands(brands: "list[str]") -> Optional[str]:
    """Devuelve un mensaje de error si alguna marca no es válida, o None si todas son correctas."""
    valid = set(BRAND_FAMILIES.keys()) | {"*"}
    invalid = [b for b in brands if b not in valid]
    if invalid:
        return f"Marcas inválidas: {invalid}. Válidas: {sorted(BRAND_FAMILIES.keys())} o '*'"
    return None


# ---------------------------------------------------------------------------
# CRUD de usuarios
# ---------------------------------------------------------------------------

def list_users(db) -> "list[dict]":
    """Devuelve todos los usuarios en users_config con su email incluido."""
    docs = db.collection(COLLECTION).stream()
    users = []
    for doc in docs:
        data = doc.to_dict()
        data["email"] = doc.id
        users.append(data)
    return users


def create_user(db, email: str, role: str, brands: "list[str]") -> dict:
    """
    Crea un nuevo usuario en Firestore.

    Returns:
        {"ok": True} o {"ok": False, "error": "..."}
    """
    # No se puede crear otro superadmin
    if role == "superadmin":
        return {"ok": False, "error": "No se puede crear un usuario con rol superadmin"}

    # Validar rol
    err = _validate_role(role)
    if err:
        return {"ok": False, "error": err}

    # Validar marcas
    err = _validate_brands(brands)
    if err:
        return {"ok": False, "error": err}

    normalized = email.lower()
    doc_ref = db.collection(COLLECTION).document(normalized)
    snapshot = doc_ref.get()

    if snapshot.exists:
        return {"ok": False, "error": f"El usuario '{normalized}' ya existe"}

    now = datetime.now(timezone.utc)
    data = {
        "role": role,
        "brands": brands,
        "can_edit_objectives": role in ("editor", "gerencia"),
        "created_at": now,
        "updated_at": now,
    }
    doc_ref.set(data)
    logger.info("Usuario creado: %s con rol %s", normalized, role)
    return {"ok": True}


def update_user(db, email: str, role: str = None, brands: "list[str]" = None) -> dict:
    """
    Actualiza un usuario existente.

    Returns:
        {"ok": True} o {"ok": False, "error": "..."}
    """
    normalized = email.lower()
    doc_ref = db.collection(COLLECTION).document(normalized)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        return {"ok": False, "error": f"El usuario '{normalized}' no existe"}

    current = snapshot.to_dict()

    # No se puede modificar un superadmin
    if current.get("role") == "superadmin":
        return {"ok": False, "error": "No se puede modificar un usuario superadmin"}

    # No se puede asignar rol superadmin
    if role == "superadmin":
        return {"ok": False, "error": "No se puede asignar el rol superadmin"}

    # Validar rol si se provee
    if role is not None:
        err = _validate_role(role)
        if err:
            return {"ok": False, "error": err}

    # Validar marcas si se proveen
    if brands is not None:
        err = _validate_brands(brands)
        if err:
            return {"ok": False, "error": err}

    updates = {"updated_at": datetime.now(timezone.utc)}
    if role is not None:
        updates["role"] = role
        updates["can_edit_objectives"] = role in ("editor", "gerencia")
    if brands is not None:
        updates["brands"] = brands

    doc_ref.update(updates)
    logger.info("Usuario actualizado: %s", normalized)
    return {"ok": True}


def delete_user(db, email: str, actor_email: str) -> dict:
    """
    Elimina un usuario de Firestore.

    Returns:
        {"ok": True} o {"ok": False, "error": "..."}
    """
    normalized = email.lower()
    actor_normalized = actor_email.lower()

    # No puede borrar a sí mismo
    if normalized == actor_normalized:
        return {"ok": False, "error": "No puedes eliminar tu propio usuario"}

    doc_ref = db.collection(COLLECTION).document(normalized)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        return {"ok": False, "error": f"El usuario '{normalized}' no existe"}

    current = snapshot.to_dict()

    # No puede borrar un superadmin
    if current.get("role") == "superadmin":
        return {"ok": False, "error": "No se puede eliminar un usuario superadmin"}

    doc_ref.delete()
    logger.info("Usuario eliminado: %s por %s", normalized, actor_normalized)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cluster overrides
# ---------------------------------------------------------------------------

CLUSTER_OVERRIDES_COLLECTION = "cluster_overrides"


def list_cluster_overrides(db) -> dict:
    """Devuelve {nombre_cliente: cluster} para todos los overrides guardados."""
    docs = db.collection(CLUSTER_OVERRIDES_COLLECTION).stream()
    return {doc.id: doc.to_dict().get("cluster", "") for doc in docs}


def set_cluster_override(db, client: str, cluster: str) -> dict:
    """Asigna un cluster a un cliente (override manual)."""
    if not client or not cluster:
        return {"ok": False, "error": "Cliente y cluster son requeridos"}
    doc_ref = db.collection(CLUSTER_OVERRIDES_COLLECTION).document(client)
    doc_ref.set({
        "cluster": cluster,
        "updated_at": datetime.now(timezone.utc),
    })
    logger.info("Cluster override: '%s' → '%s'", client, cluster)
    return {"ok": True}


def delete_cluster_override(db, client: str) -> dict:
    """Elimina el override de cluster para un cliente (vuelve al valor de BQ)."""
    doc_ref = db.collection(CLUSTER_OVERRIDES_COLLECTION).document(client)
    doc_ref.delete()
    logger.info("Cluster override eliminado: '%s'", client)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------

OBJECTIVES_COLLECTION = "objetivos_destileria"
_VALID_MARCAS = {"bosque", "feriado", "cerveza"}
_MONTH_NAMES = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]


def parse_flat_objectives(rows: "list[list]") -> "tuple[list[dict], list[str]]":
    """
    Parsea filas en formato plano:
      marca | dimension | nombre | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic

    Returns:
        (docs, errors) — docs son dicts listos para Firestore, errors son strings descriptivos.
    """
    header_idx: Optional[int] = None
    col_idx: dict = {}
    for i, row in enumerate(rows):
        row_lower = [str(c).strip().lower() for c in row]
        if "marca" in row_lower:
            header_idx = i
            for j, name in enumerate(row_lower):
                if name not in col_idx:
                    col_idx[name] = j
            break

    if header_idx is None:
        return [], ["No se encontró fila de encabezado (debe contener 'marca')"]

    required = ["marca", "dimension", "nombre"] + _MONTH_NAMES
    missing = [c for c in required if c not in col_idx]
    if missing:
        return [], [f"Faltan columnas: {', '.join(missing)}"]

    docs: list = []
    errors: list = []
    seen: set = set()

    def _cell(row, col_name):
        idx = col_idx.get(col_name, -1)
        return str(row[idx]).strip() if 0 <= idx < len(row) else ""

    for i, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(str(c).strip() for c in row):
            continue

        marca = _cell(row, "marca").lower()
        dimension = _cell(row, "dimension").lower()
        nombre = _cell(row, "nombre")

        if not marca and not dimension and not nombre:
            continue

        if marca not in _VALID_MARCAS:
            errors.append(f"Fila {i}: marca desconocida '{marca}'")
            continue

        valores: list = []
        row_err = False
        for m in _MONTH_NAMES:
            raw = _cell(row, m)
            if raw in ("", "-"):
                valores.append(0)
            else:
                try:
                    valores.append(round(float(raw.replace(",", "."))))
                except ValueError:
                    errors.append(f"Fila {i}: valor no numérico en '{m}': '{raw}'")
                    row_err = True
                    break

        if row_err:
            continue

        key = (marca, dimension, nombre)
        if key in seen:
            errors.append(f"Fila {i}: duplicado '{marca}/{dimension}/{nombre}'")
            continue
        seen.add(key)

        docs.append({
            "marca": marca,
            "dimension": dimension,
            "nombre": nombre,
            "valores": valores,
        })

    return docs, errors


def list_objectives(db) -> "list[dict]":
    """Devuelve todos los objetivos de Firestore, ordenados por marca/dimension/nombre."""
    docs = db.collection(OBJECTIVES_COLLECTION).stream()
    result = [doc.to_dict() for doc in docs]
    return sorted(
        result,
        key=lambda x: (x.get("marca", ""), x.get("dimension", ""), x.get("nombre", "")),
    )


def save_objectives(db, docs: "list[dict]", updated_by: str) -> dict:
    """
    Reemplaza todos los objetivos en Firestore (replace completo).

    Returns:
        {"ok": True, "count": N} o {"ok": False, "error": "..."}
    """
    if not docs:
        return {"ok": False, "error": "No hay datos para guardar"}

    for existing in db.collection(OBJECTIVES_COLLECTION).stream():
        existing.reference.delete()

    now = datetime.now(timezone.utc)
    for row in docs:
        doc_id = f"{row['marca']}__{row['dimension']}__{row['nombre']}"
        db.collection(OBJECTIVES_COLLECTION).document(doc_id).set({
            **row,
            "updated_at": now,
            "updated_by": updated_by,
        })

    logger.info("Objetivos guardados: %d filas por %s", len(docs), updated_by)
    return {"ok": True, "count": len(docs)}


# ---------------------------------------------------------------------------
# Google Places mapping (local -> place_id)
# ---------------------------------------------------------------------------

PLACES_MAPPING_COLLECTION = "google_places_mapping"

_VALID_PLACES_STATUS = ("pending", "verified", "rejected")


def list_places_mapping(db) -> dict:
    """Devuelve {doc_id: doc.to_dict()} para todos los mapeos local -> place_id."""
    docs = db.collection(PLACES_MAPPING_COLLECTION).stream()
    return {doc.id: doc.to_dict() for doc in docs}


def set_places_mapping(
    db,
    marca: str,
    local: str,
    place_id: str,
    display_name_google: str = None,
    formatted_address: str = None,
    status: str = "pending",
    search_query_used: str = None,
    candidates: "list" = None,
) -> dict:
    """Crea o actualiza (merge) el mapeo de un local a un place_id de Google."""
    if not marca or not local or not place_id:
        return {"ok": False, "error": "Marca, local y place_id son requeridos"}

    doc_id = f"{marca}__{local}"
    doc_ref = db.collection(PLACES_MAPPING_COLLECTION).document(doc_id)
    doc_ref.set({
        "marca": marca,
        "local": local,
        "place_id": place_id,
        "display_name_google": display_name_google,
        "formatted_address": formatted_address,
        "status": status,
        "search_query_used": search_query_used,
        "candidates": candidates if candidates is not None else [],
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)
    logger.info("Places mapping guardado: '%s' -> '%s'", doc_id, place_id)
    return {"ok": True}


def update_places_mapping_status(db, doc_id: str, status: str, verified_by: str = None) -> dict:
    """Actualiza el status (pending/verified/rejected) de un mapeo existente."""
    doc_ref = db.collection(PLACES_MAPPING_COLLECTION).document(doc_id)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        return {"ok": False, "error": "Mapping no encontrado"}

    if status not in _VALID_PLACES_STATUS:
        return {"ok": False, "error": f"Status inválido: '{status}'. Debe ser uno de: {', '.join(_VALID_PLACES_STATUS)}"}

    updates = {"status": status}
    if verified_by is not None:
        updates["verified_by"] = verified_by
        updates["verified_at"] = firestore.SERVER_TIMESTAMP

    doc_ref.update(updates)
    logger.info("Places mapping status actualizado: '%s' -> '%s'", doc_id, status)
    return {"ok": True}


def delete_places_mapping(db, doc_id: str) -> dict:
    """Elimina un mapeo local -> place_id de Google."""
    doc_ref = db.collection(PLACES_MAPPING_COLLECTION).document(doc_id)
    doc_ref.delete()
    logger.info("Places mapping eliminado: '%s'", doc_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Google reviews — gestión (seguimiento operativo de reseñas)
# ---------------------------------------------------------------------------

GESTION_COLLECTION = "google_reviews_gestion"

_VALID_GESTION_STATUS = {"nueva", "en_curso", "resuelta"}


def review_gestion_key(author_name: str, time=None, date_str: str = None, rating=None) -> str:
    """
    Genera la key estable de una reseña (usada como doc_id en GESTION_COLLECTION).

    IMPORTANTE: debe mantenerse idéntica carácter a carácter a `_review_key()`
    en google_reviews_sync.py (línea ~236), que es la fuente de verdad para
    las keys guardadas en seen_review_keys. Si esa función cambia, replicar
    el cambio acá.
    """
    author = author_name or ""
    if time:
        return f"{author}|{time}"
    return f"{author}|{date_str or ''}|{rating if rating is not None else ''}"


def list_gestion(db) -> dict:
    """Devuelve {doc_id: doc.to_dict()} para todos los docs de gestión de reseñas."""
    docs = db.collection(GESTION_COLLECTION).stream()
    return {doc.id: doc.to_dict() for doc in docs}


def create_gestion_if_not_exists(
    db,
    doc_id: str,
    marca: str,
    local: str,
    rating,
    text: str,
    author_name: str,
    date_str: str,
) -> dict:
    """
    Crea el doc de gestión de una reseña, solo si no existe todavía.

    Nunca pisa un doc que ya está en_curso o resuelta (guard por existencia,
    igual que update_places_mapping_status).
    """
    doc_ref = db.collection(GESTION_COLLECTION).document(doc_id)
    if doc_ref.get().exists:
        return {"ok": True, "created": False}

    doc_ref.set({
        "marca": marca,
        "local": local,
        "rating": rating,
        "text": text,
        "author_name": author_name,
        "date_str": date_str,
        "estado": "nueva",
        "nota": "",
        "creado_at": firestore.SERVER_TIMESTAMP,
    })
    logger.info("Gestión de reseña creada: '%s'", doc_id)
    return {"ok": True, "created": True}


def update_gestion_status(
    db,
    doc_id: str,
    estado: str = None,
    nota: str = None,
    actualizado_por: str = None,
) -> dict:
    """Actualiza estado y/o nota de un doc de gestión de reseñas existente."""
    doc_ref = db.collection(GESTION_COLLECTION).document(doc_id)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        return {"ok": False, "error": "Gestión no encontrada"}

    if estado is not None and estado not in _VALID_GESTION_STATUS:
        return {
            "ok": False,
            "error": f"Estado inválido: '{estado}'. Debe ser uno de: {', '.join(sorted(_VALID_GESTION_STATUS))}",
        }

    updates = {}
    if estado is not None:
        updates["estado"] = estado
    if nota is not None:
        updates["nota"] = nota
    if actualizado_por is not None:
        updates["actualizado_por"] = actualizado_por

    if not updates:
        return {"ok": False, "error": "No hay cambios para aplicar"}

    updates["actualizado_at"] = firestore.SERVER_TIMESTAMP

    doc_ref.update(updates)
    logger.info("Gestión de reseña actualizada: '%s' -> %s", doc_id, updates)
    return {"ok": True}


def cleanup_gestion_retention(db) -> dict:
    """
    Borra docs de gestión de reseñas fuera de la ventana de retención:
      (a) estado == "resuelta" con actualizado_at > 30 días de antigüedad.
      (b) cualquier doc (resuelto o no) con creado_at > 90 días de antigüedad.

    Filtra en Python sobre .stream() completo (colección chica, evita
    necesidad de índice compuesto en Firestore).
    """
    now = datetime.now(timezone.utc)
    resuelta_cutoff = now - timedelta(days=30)
    creado_cutoff = now - timedelta(days=90)

    deleted = 0
    for doc in db.collection(GESTION_COLLECTION).stream():
        data = doc.to_dict() or {}
        creado_at = data.get("creado_at")
        actualizado_at = data.get("actualizado_at")

        should_delete = False
        if creado_at is not None and creado_at < creado_cutoff:
            should_delete = True
        if (
            data.get("estado") == "resuelta"
            and actualizado_at is not None
            and actualizado_at < resuelta_cutoff
        ):
            should_delete = True

        if should_delete:
            doc.reference.delete()
            deleted += 1

    if deleted:
        logger.info("Cleanup gestión reseñas: %d docs eliminados", deleted)
    return {"ok": True, "deleted": deleted}
