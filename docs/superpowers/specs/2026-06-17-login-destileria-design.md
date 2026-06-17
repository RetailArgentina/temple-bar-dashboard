# Login Destilería — Diseño

**Fecha:** 2026-06-17  
**Scope:** Solo tablero destilería (`/destileria`). No afecta el flujo retail ni Google OAuth.  
**Stack:** Flask + Firestore + werkzeug bcrypt. Sin dependencias nuevas.

---

## 1. Arquitectura

Tres piezas nuevas que coexisten sin tocar el flujo retail/OAuth existente:

| Pieza | Descripción |
|---|---|
| Rutas nuevas en `app.py` | `GET/POST /destileria/login`, `POST /destileria/logout` |
| Decorator `@destileria_login_required` | Reemplaza `@login_required` solo en la ruta `/destileria` |
| Colección Firestore `destileria_users` | Usuarios con contraseña hasheada, independiente de `users_config` |
| Sección en `/admin` | CRUD de usuarios destilería: crear, editar, reset password, activar/desactivar |

La sesión usa `session["dest_user"]` (distinto de `session["user"]` del OAuth retail) — mismo mecanismo Flask session, cero conflicto.

---

## 2. Modelo de datos — Firestore `destileria_users`

Doc ID: email del usuario en minúsculas.

```json
{
  "name": "Nombre Apellido",
  "password_hash": "$2b$12$<hash_bcrypt>",
  "role": "gerencia | editor | viewer",
  "brands": ["*"],
  "can_edit_objectives": true,
  "active": true,
  "created_at": "2026-06-17T12:00:00Z",
  "created_by": "admin@empresa.com"
}
```

- `brands`: `["*"]` = acceso a todas; o lista explícita `["bosque", "feriado"]`
- Mismos roles y estructura de `brands` que `users_config` → `permissions.py` sin cambios
- `password_hash`: generado con `werkzeug.security.generate_password_hash` (bcrypt)

---

## 3. Rutas nuevas en `app.py`

### `GET /destileria/login`
- Si `"dest_user"` ya está en sesión → redirect a `/destileria`
- Si no → renderiza `templates/destileria_login.html`
- Acepta query param `?reason=expired` para mostrar mensaje de sesión expirada

### `POST /destileria/login`
1. Valida token CSRF (flask-wtf, ya configurado)
2. Lee `email` y `password` del form
3. Busca doc en `destileria_users` por email (lowercase)
4. Si no existe o `active == False` → error genérico (sin revelar cuál falló)
5. Verifica hash con `check_password_hash`
6. Si falla → error genérico
7. Si OK → `session["dest_user"] = {email, name, role, brands, can_edit_objectives}` → redirect `/destileria`

### `POST /destileria/logout`
- CSRF-protected
- `session.pop("dest_user", None)`
- Redirect a `/destileria/login`

### Decorator `@destileria_login_required`
```python
def destileria_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "dest_user" not in session:
            return redirect(url_for("destileria_login"))
        return f(*args, **kwargs)
    return decorated
```

La ruta `/destileria` cambia de `@login_required` a `@destileria_login_required`. Los permisos se inyectan desde `session["dest_user"]` en lugar de `session["user"]`.

---

## 4. Panel Admin — Gestión de usuarios destilería

Nueva sección en `/admin` (solo visible para roles `superadmin` y `gerencia`):

| Acción | Descripción |
|---|---|
| Listar | Tabla con nombre, email, rol, marcas, estado activo/inactivo |
| Crear | Modal con nombre, email, contraseña temporal (texto plano → se hashea al guardar), rol, marcas |
| Editar | Cambiar nombre, rol, marcas, `can_edit_objectives` |
| Reset password | El admin ingresa nueva contraseña temporal → se hashea y guarda |
| Desactivar / Activar | Toggle del campo `active` |

Endpoints de API necesarios (AJAX, CSRF-protected):
- `POST /admin/destileria/users` — crear usuario
- `PUT /admin/destileria/users/<path:email>` — editar (Flask `<path:>` para soportar `@` y `.` en el email)
- `POST /admin/destileria/users/<path:email>/reset-password` — reset
- `POST /admin/destileria/users/<path:email>/toggle-active` — activar/desactivar

---

## 5. Template de login — `templates/destileria_login.html`

**Estilo:** Dark con identidad de marca prominente (opción C aprobada en brainstorming).

Layout split: panel izquierdo (branding — ícono dorado, "DESTILERÍA / PATAGÓNICA", fondo con gradiente oscuro) + panel derecho (formulario de login).

Estados:
- **Normal:** campos vacíos, botón "INGRESAR" en gradiente dorado
- **Error:** banner rojo "Email o contraseña incorrectos", inputs con borde rojo
- **Sesión expirada:** banner amarillo "Tu sesión expiró, volvé a ingresar"

---

## 6. Seguridad

- **Hashing:** `werkzeug.security.generate_password_hash` / `check_password_hash` (bcrypt)
- **CSRF:** todos los POST usan token flask-wtf existente
- **Mensajes de error genéricos:** nunca revelar si el email existe o si la contraseña es incorrecta
- **Usuario inactivo:** mismo mensaje de error genérico
- **Sin rate limiting:** aceptable para 10-20 usuarios internos; agregar Flask-Limiter si se necesita
- **Expiración de sesión:** usa `PERMANENT_SESSION_LIFETIME` ya configurado en `config.py`
- **Contraseña temporal:** el admin la ve una sola vez al crearla; se hashea antes de persistir

---

## 7. Flujo completo

```
GET /destileria
  └─ @destileria_login_required
       ├─ "dest_user" en sesión → sirve dashboard
       └─ no → redirect /destileria/login

POST /destileria/login
  ├─ CSRF válido?           No → 400
  ├─ Email en destileria_users?  No → error genérico
  ├─ active == True?        No → error genérico
  ├─ check_password_hash OK? No → error genérico
  └─ OK → session["dest_user"] = {...} → redirect /destileria

POST /destileria/logout
  └─ session.pop("dest_user") → redirect /destileria/login
```

---

## 8. Archivos a crear / modificar

| Archivo | Acción |
|---|---|
| `app.py` | Agregar decorator, rutas login/logout, endpoints admin API. **Actualizar redirect post-OAuth** (línea ~201) que actualmente apunta a `destileria` — cambiarlo a `/dashboard` u otra ruta retail. |
| `templates/destileria_login.html` | Nuevo — formulario de login estilo C |
| `templates/admin.html` | Ampliar — sección usuarios destilería + modal |
| `permissions.py` | Sin cambios |
| `config.py` | Sin cambios |
| `requirements.txt` | Sin cambios (werkzeug ya incluido) |

---

## 9. Fuera de scope

- Recuperación de contraseña por email (el admin resetea manualmente)
- Auto-registro de usuarios
- Rate limiting (puede agregarse luego)
- Forzar cambio de contraseña temporal al primer login
