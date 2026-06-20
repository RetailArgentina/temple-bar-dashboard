"""
destileria_auth.py — Firestore helpers para la colección destileria_users.

Estructura de cada documento (doc_id = email en minúsculas):
    name: str
    password_hash: str          — bcrypt via werkzeug.security
    role: str                   — "superadmin" | "gerencia" | "editor" | "viewer"
    brands: list[str]           — ["*"] o ["bosque", "feriado"]
    can_edit_objectives: bool
    active: bool
    created_at: str             — ISO 8601 UTC
    created_by: str             — email del admin que lo creó
"""
from __future__ import annotations
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

COLLECTION = "destileria_users"


def get_destileria_user(db, email: str) -> dict | None:
    """Retorna el usuario como dict (incluye password_hash), o None si no existe."""
    normalized = email.lower().strip()
    doc = db.collection(COLLECTION).document(normalized).get()
    if not doc.exists:
        return None
    return {"email": normalized, **doc.to_dict()}


def verify_destileria_password(db, email: str, password: str) -> dict | None:
    """
    Retorna el dict del usuario si el email existe, está activo y la contraseña es correcta.
    Retorna None en cualquier otro caso (sin indicar el motivo).
    """
    user = get_destileria_user(db, email)
    if user is None or not user.get("active", False):
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def create_destileria_user(
    db,
    email: str,
    name: str,
    password: str,
    role: str,
    brands: list[str],
    can_edit_objectives: bool,
    created_by: str,
) -> None:
    """Crea un nuevo usuario destilería. La contraseña se hashea antes de guardar."""
    data = {
        "name": name,
        "password_hash": generate_password_hash(password),
        "role": role,
        "brands": brands,
        "can_edit_objectives": can_edit_objectives,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }
    db.collection(COLLECTION).document(email.lower().strip()).set(data)


def update_destileria_user(
    db,
    email: str,
    name: str,
    role: str,
    brands: list[str],
    can_edit_objectives: bool,
) -> None:
    """Actualiza nombre, rol, marcas y permiso de objetivos. No toca la contraseña."""
    db.collection(COLLECTION).document(email.lower().strip()).update({
        "name": name,
        "role": role,
        "brands": brands,
        "can_edit_objectives": can_edit_objectives,
    })


def reset_destileria_password(db, email: str, new_password: str) -> None:
    """Reemplaza el hash de contraseña por uno nuevo."""
    db.collection(COLLECTION).document(email.lower().strip()).update({
        "password_hash": generate_password_hash(new_password),
    })


def toggle_destileria_user_active(db, email: str) -> bool:
    """Invierte el campo `active`. Retorna el nuevo valor."""
    ref = db.collection(COLLECTION).document(email.lower().strip())
    current = ref.get().to_dict().get("active", True)
    ref.update({"active": not current})
    return not current


def list_destileria_users(db) -> list[dict]:
    """Retorna todos los usuarios ordenados por nombre. Nunca incluye password_hash."""
    docs = db.collection(COLLECTION).stream()
    users = []
    for doc in docs:
        data = doc.to_dict()
        data.pop("password_hash", None)
        data["email"] = doc.id
        users.append(data)
    return sorted(users, key=lambda u: u.get("name", "").lower())
