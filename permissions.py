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
from datetime import datetime, timezone

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

VALID_ROLES = ("superadmin", "editor", "viewer")

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
        "can_edit_objectives": role == "editor",
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
        updates["can_edit_objectives"] = role == "editor"
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
