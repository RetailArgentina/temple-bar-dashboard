# Tablero Autogestionable — Sistema de Permisos y Panel Admin

**Fecha:** 2026-06-14
**Autor:** Darwin Salinas
**Estado:** Aprobado

## Objetivo

Convertir el tablero de destilería en un sistema autogestionable donde el superadmin (Darwin) pueda administrar accesos por email y asignar permisos granulares (rol + marcas visibles) desde un panel dentro de la propia app, sin intervención de desarrollo ni redeploys.

## Decisiones de diseño

| Decisión | Elección | Alternativas descartadas |
|----------|----------|--------------------------|
| Almacenamiento de permisos | Firestore (`users_config`) | BigQuery (overkill), Google Sheets (dependencia Drive API) |
| Interfaz de gestión | Panel admin integrado (`/admin`) | Google Sheet externa, app separada |
| Administración | Solo superadmin (Darwin) | Multi-admin, admin por área |
| Restricción de marcas | Tab no aparece (invisible) | Tab deshabilitado/gris |
| Detección de marcas | Dinámica por prefijo de familia | Lista manual hardcodeada |

---

## 1. Modelo de datos (Firestore)

Colección: `users_config`
Documento ID: email en lowercase.

```
users_config/darwin.salinas@temple.com.ar:
  role: "superadmin"
  brands: ["*"]
  can_edit_objectives: true
  created_at: timestamp
  updated_at: timestamp

users_config/usuario.ejemplo@temple.com.ar:
  role: "viewer"
  brands: ["bosque", "feriado"]
  can_edit_objectives: false
  created_at: timestamp
  updated_at: timestamp
```

**Campos:**

- `role` — `superadmin` | `editor` | `viewer`
- `brands` — array de strings. `["*"]` = todas las marcas (presentes y futuras)
- `can_edit_objectives` — booleano explícito (superadmin/editor = true, viewer = false)
- `created_at` / `updated_at` — timestamps de auditoría

**Roles:**

| Rol | Ve marcas | Edita objetivos | Panel admin |
|-----|-----------|-----------------|-------------|
| superadmin | Todas (`*`) | Sí | Sí |
| editor | Las asignadas | Sí | No |
| viewer | Las asignadas | No | No |

**Migración inicial:** Los 10 emails de `whitelist.txt` se crean como `viewer` con `brands: ["*"]`. `darwin.salinas@temple.com.ar` se crea como `superadmin`.

---

## 2. Flujo de autenticación y autorización

### Login

1. Usuario llega → Google OAuth (sin cambios)
2. Post-OAuth, se busca el email en Firestore `users_config`:
   - **Existe** → se cargan rol + marcas en la sesión Flask
   - **No existe** → pantalla de acceso denegado
3. Se elimina `whitelist.txt` como fuente de verdad
4. Se elimina la validación de dominio hardcodeada (`@temple.com.ar` / `@bosquegin.com`). Si el email está en Firestore, entra.

### Sesión Flask

```python
session["user"] = {
    "email": "usuario@temple.com.ar",
    "name": "Nombre Usuario",
    "picture": "...",
    "role": "viewer",
    "brands": ["bosque", "feriado"],
    "can_edit_objectives": False
}
```

### Autorización por ruta

| Ruta | Protección |
|------|-----------|
| `/destileria`, `/dashboard` | `@login_required` — marcas filtradas |
| `/admin`, `/api/admin/*` | `@require_superadmin` |
| `/api/data`, `/api/objectives` | `@login_required` + filtrado server-side por marcas |

---

## 3. Panel de administración (`/admin`)

**Acceso:** Solo `role == "superadmin"`. Ícono de engranaje visible en el header solo para ese rol.

### Vista principal — Lista de usuarios

Tabla con: email, nombre, rol, marcas asignadas, última actividad, acciones (editar/eliminar).

### Acciones

- **Agregar usuario** — email, rol (editor/viewer), marcas (checkboxes dinámicos)
- **Editar usuario** — mismos campos, precargados
- **Eliminar usuario** — con confirmación

### Restricciones

- No se puede crear otro superadmin desde el panel
- El superadmin no puede eliminarse a sí mismo
- No se puede cambiar el rol del superadmin

### API endpoints

```
GET    /api/admin/users          → lista todos los usuarios
POST   /api/admin/users          → crea usuario nuevo
PUT    /api/admin/users/<email>  → actualiza rol/marcas
DELETE /api/admin/users/<email>  → elimina usuario
```

Todos protegidos con `@require_superadmin` + CSRF.

### Estilo visual

Mismo look oscuro del tablero: fondo `#0d1117`, bordes `#21262d`, acentos dorados `#c9a227`.

---

## 4. Migración del tablero de destilería a Flask

### Flujo actual

Script Python → genera HTML → sube a GCS → URL pública sin autenticación.

### Flujo nuevo

1. El script sigue generando y subiendo el HTML a GCS (sin cambios)
2. Flask sirve el HTML desde `/destileria` con `@login_required`, leyéndolo de GCS con caché en memoria (mismo patrón que `/dashboard`)
3. Antes de servir, Flask inyecta los permisos del usuario en el HTML:

```javascript
window.__USER_PERMISSIONS__ = {
  role: "viewer",
  brands: ["bosque", "feriado"],
  canEditObjectives: false
};
```

4. El JS del tablero lee `window.__USER_PERMISSIONS__` y:
   - Solo renderiza tabs de marcas permitidas
   - Oculta controles de edición si `canEditObjectives` es false

### Lo que no cambia

- Script de generación, template, proceso de regeneración
- La URL pública de GCS puede mantenerse como backup temporal

---

## 5. Detección dinámica de marcas

Diccionario en la app que agrupa familias en marcas por prefijo:

```python
BRAND_FAMILIES = {
    "bosque":  ["bosque_"],
    "feriado": ["feriado_"],
    "cerveza": ["lata_"],
    "merch":   ["merch"],
}
```

**Comportamiento:**

- Familia nueva con prefijo existente (ej. `bosque_premium`) → cae automáticamente en su marca
- Marca completamente nueva (ej. `whisky`) → se agrega al diccionario + redeploy. Aparece como opción en el panel admin automáticamente.
- El panel admin lee las keys de `BRAND_FAMILIES` para mostrar las marcas asignables.

---

## 6. Seguridad

1. **Autenticación** — Google OAuth (sin cambios)
2. **Autorización server-side** — toda ruta verifica permisos. Las APIs filtran datos por marcas autorizadas antes de devolver JSON. Ocultar tabs es conveniencia visual, no seguridad.
3. **CSRF** — Flask-WTF en todos los endpoints admin
4. **Protección del superadmin** — no se puede crear otro, eliminar al existente, ni cambiar su rol desde el panel
5. **Auditoría** — cada cambio en `users_config` se loguea en Cloud Run con timestamp y quién lo hizo
6. **Sesión** — TTL de 8 horas. Cambios de permisos aplican en el próximo login del usuario afectado

---

## Archivos impactados

| Archivo | Cambio |
|---------|--------|
| `app.py` | Nueva ruta `/admin`, `/destileria`, refactor de auth_callback, decoradores de autorización |
| `config.py` | Eliminar carga de `whitelist.txt`, agregar `BRAND_FAMILIES` |
| `whitelist.txt` | Se elimina (reemplazado por Firestore) |
| `templates/admin.html` | Nuevo — panel de gestión de usuarios |
| `templates/destileria.html` | Agregar lectura de `window.__USER_PERMISSIONS__` para filtrar tabs |
| `templates/login.html` | Sin cambios |
| `templates/denied.html` | Sin cambios |

## Fuera de alcance

- Edición de objetivos desde el tablero (futuro)
- Invalidación de sesiones en tiempo real al cambiar permisos
- Historial de cambios de permisos en Firestore (por ahora solo logs de Cloud Run)
- Automatización de regeneración del tablero (Cloud Scheduler — proyecto separado)
