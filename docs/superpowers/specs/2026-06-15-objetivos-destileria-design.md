# Diseño: Gestión de Objetivos — Tablero Destilería

**Fecha:** 2026-06-15  
**Estado:** Aprobado

---

## Resumen

Agregar un tab "Objetivos" al panel `/admin` del tablero de destilería que permita al rol `gerencia` importar objetivos mensuales desde Excel (.xlsx) o Google Sheets. Los objetivos se persisten en Firestore y son leídos por el script de generación del dashboard en el próximo ciclo de regeneración.

---

## 1. Roles y permisos

Se agrega el rol `gerencia` al sistema de permisos en `permissions.py`.

**Permisos del rol `gerencia`:**
- Acceso al panel `/admin` (tab "Objetivos" únicamente)
- Leer, importar y sobreescribir objetivos en Firestore (`objetivos_destileria`)
- No puede gestionar usuarios ni cluster_overrides (exclusivo de `superadmin`)

**Permisos de lectura en Firestore:**
- El script de generación usa la SA de Cloud Run existente para leer `objetivos_destileria`
- `superadmin` también puede operar el tab de objetivos

---

## 2. Tab "Objetivos" en el panel admin

Nuevo tab dentro de `/admin`, visible únicamente para `gerencia` y `superadmin`.

### Sub-flujo 1 — Importar desde Excel (.xlsx)
1. Botón "Subir Excel" → file picker (`.xlsx`)
2. POST al servidor con el archivo
3. El servidor parsea y valida (ver sección 4)
4. Si válido: tabla de preview con datos + botón "Guardar en Firestore"
5. Si inválido: mensajes de error en rojo, botón deshabilitado

### Sub-flujo 2 — Importar desde Google Sheets
1. Input de texto para URL o ID del Sheet
2. Botón "Leer Sheet" → el servidor hace fetch usando credenciales SA existentes
3. Mismo flujo de preview y guardado que el sub-flujo 1

### Estado actual
Debajo de los sub-flujos: tabla de solo lectura con los objetivos actualmente almacenados en Firestore (columnas: marca, dimensión, nombre, valores ene–dic, última actualización, usuario).

---

## 3. Modelo de datos en Firestore

**Colección:** `objetivos_destileria`

**ID de documento:** `{marca}__{dimension}__{nombre}`  
Ejemplo: `bosque__product__bosque_nativo`

**Estructura de documento:**
```json
{
  "marca": "bosque",
  "dimension": "product",
  "nombre": "bosque_nativo",
  "valores": [1030, 1188, 1206, 1408, 1471, 1564, 1612, 1692, 1784, 1946, 2014, 2119],
  "updated_at": "2026-06-15T22:00:00",
  "updated_by": "darwin.salinas@temple.com.ar"
}
```

**Estrategia de escritura:** Replace completo — al importar un archivo nuevo se borran todos los documentos existentes de la colección y se escriben los nuevos. Esto evita objetivos huérfanos de importaciones anteriores.

---

## 4. Parsing y validación del Excel/Sheet

### Formato esperado

Columnas requeridas (case-insensitive, orden flexible):

```
marca | dimension | nombre | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic
```

### Validaciones

| Regla | Comportamiento al fallar |
|-------|--------------------------|
| Las 15 columnas deben estar presentes | Error: "Falta la columna: X" |
| `marca` debe ser `bosque`, `feriado` o `cerveza` | Error: "Marca desconocida: X en fila N" |
| Los 12 valores mensuales deben ser numéricos | Vacíos → 0, texto no numérico → error |
| Sin duplicados de `marca + dimension + nombre` | Error: "Fila duplicada: X" |

Si hay errores → se muestran en rojo, botón "Guardar" deshabilitado.  
Si todo válido → preview en verde, botón "Guardar en Firestore" habilitado.

---

## 5. Cambio al script de generación

**Archivo:** `generar_destileria_dashboard (1).py`

Se agrega `load_objectives_from_firestore()`:
1. Conecta a Firestore con SA key existente
2. Lee todos los documentos de `objetivos_destileria`
3. Reconstruye el dict: `{marca: {dimension: {nombre: [12 valores]}}}`

**Cadena de prioridad actualizada:**
```
Firestore → Drive (Sheets) → GCS cache → local JSON
```

- Si Firestore tiene datos → se usan, no se intenta Drive
- Si Firestore está vacío o falla → fallback al comportamiento actual sin romper nada

---

## 6. Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `permissions.py` | Agregar rol `gerencia`, CRUD Firestore para `objetivos_destileria` |
| `app.py` | Endpoints `/api/admin/objectives` (GET, POST), protección por rol `gerencia`/`superadmin` |
| `templates/admin.html` | Nuevo tab "Objetivos" con UI de importación |
| `generar_destileria_dashboard (1).py` | `load_objectives_from_firestore()`, nueva cadena de prioridad |
| `tests/test_permissions.py` | Tests para CRUD de objetivos y rol gerencia |
| `tests/test_auth.py` | Tests para protección de endpoints de objetivos |

---

## 7. Fuera de alcance

- Trigger automático de regeneración del dashboard (pendiente en `project_destileria-cloud-run-setup.md`)
- Edición inline celda por celda de objetivos (solo importación masiva)
- Historial de versiones de objetivos anteriores
