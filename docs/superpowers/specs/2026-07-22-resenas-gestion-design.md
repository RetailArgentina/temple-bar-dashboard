# Diseño: Tendencia real, gestión de reseñas y reporte semanal (Reseñas Google — Fase 2)

Extiende [[project_resenas_google]] para que marketing pueda hacer seguimiento día a día, no solo ver un snapshot.

## Alcance

1. **Gráfico de tendencia real** (7/30/90 días) en el tab "Reseñas" existente (iframe estático, sin cambios de arquitectura).
2. **Gestión de reseñas negativas** (marcar nueva/en curso/resuelta + nota) — página nueva, mismo dominio que el tablero.
3. **Reporte semanal imprimible** — misma página nueva, sección aparte.

## Decisión de arquitectura (aprobada por Darwin)

El tab actual (`resenas_preview.html`) es un HTML estático servido desde GCS y cargado en `<iframe>` — dominio distinto al del tablero (Cloud Run). Sirve bien para *mostrar* datos, pero escribir cambios de estado requiere sesión autenticada, y hacer eso desde un iframe cross-origin exige relajar CORS/cookies de sesión de forma riesgosa para todo el tablero.

**Se separa en dos superficies:**
- El iframe existente sigue siendo de **solo lectura** (ranking, tarjetas, tendencia) — se le agrega el gráfico de tendencia real, sin tocar su arquitectura.
- Una **página nueva del mismo dominio**, `/resenas/gestion` en `app.py` (Jinja-rendered por request, como `admin.html` — así tiene sesión + CSRF nativos), protegida solo con `@login_required` (cualquier usuario logueado, no requiere superadmin) — ahí vive la gestión de negativas y el reporte semanal.

## 1. Gráfico de tendencia real (7/30/90 días)

- **Datos:** `google_reviews_sync.py` agrega una query a `Corporativo.google_reviews_snapshots` (ya existe, se viene llenando desde 2026-07-21) que trae, por local, el historial de `rating` de los últimos 90 días. Como recién hay ~2 días de datos, el gráfico empieza disperso y se va completando solo con el tiempo — no requiere backfill.
- **Forma del JSON nuevo** (se agrega a `__RESENAS_JSON__`, no reemplaza nada existente):
  ```json
  "historial": {
    "TEMPLE__BARRIO CHINO": [{"fecha": "2026-07-21", "rating": 4.5}, {"fecha": "2026-07-22", "rating": 4.5}]
  }
  ```
- **UI:** en `resenas_preview.html`, selector de período (7d/30d/90d) sobre la sección de tendencia existente. Reemplaza la comparación simple "vs snapshot anterior" por un sparkline SVG inline por local (sin librerías externas, mismo criterio que el resto del tablero) + el delta del período seleccionado.

## 2. Gestión de reseñas negativas

- **Nueva colección Firestore** `google_reviews_gestion`, doc ID estable por reseña (mismo esquema de key que ya usa `google_reviews_last_seen`: `f"{author_name}|{time}"` normalizado). Campos: `marca, local, rating, text, author_name, date_str, estado` (`nueva`/`en_curso`/`resuelta`), `nota`, `actualizado_por`, `actualizado_at`, `creado_at`.
- **`google_reviews_sync.py`** ya detecta reseñas negativas nuevas (`is_alert`) — ahora además, para esas, crea el doc en `google_reviews_gestion` con `estado="nueva"` si no existe todavía (no pisa uno que ya está `en_curso`/`resuelta`).
- **Retención (aprobada):** un paso de limpieza (dentro del mismo sync diario) borra docs con `estado="resuelta"` y `actualizado_at` > 30 días, y cualquier doc (resuelto o no) con `creado_at` > 90 días — minimiza cuánto tiempo se cachea contenido de reseñas, alineado con los términos de servicio de Google.
- **Ruta nueva `/resenas/gestion`** en `app.py` (`@login_required`, sin requerir superadmin): lista los docs de `google_reviews_gestion` ordenados por `estado` (nuevas primero) con botones para cambiar estado + campo de nota. Template nuevo `templates/resenas_gestion.html` (Jinja, clona el patrón de tabla + CSRF de `admin.html`).
- **Endpoint** `POST /api/resenas/gestion/<doc_id>` (`@login_required`, CSRF estándar) actualiza `estado`/`nota`.
- Acceso: cualquier usuario logueado (incluye `viewer` como Natalia/marketing@) puede cambiar estado — es la excepción puntual ya acordada.

## 3. Reporte semanal imprimible

- Misma página `/resenas/gestion`, sección separada arriba o un sub-tab "Reporte semanal": resumen de la semana (nuevas reseñas negativas, resueltas, rating promedio por marca, ranking de mejoras/caídas) armado con los datos ya disponibles en BQ (`google_reviews_snapshots`) y Firestore (`google_reviews_gestion`).
- Formato: HTML normal, con una regla `@media print` para que al usar "Imprimir/Guardar como PDF" del navegador salga prolijo — sin infraestructura de generación de PDF nueva.
- No hay período seleccionable más allá de "última semana" en esta fase — mantenerlo simple.

## Fuera de alcance (ya decidido antes, sigue igual)

- Link directo para responder la reseña en Google (no pedido esta vez).
- Tasa de respuesta a reseñas vía Google Business Profile API (fase futura, no planificada).

## Archivos que se tocan

- `google_reviews_sync.py` — agrega query de historial + creación/limpieza de `google_reviews_gestion`.
- `templates/resenas_preview.html` — selector de período + sparkline.
- `app.py` — rutas `/resenas/gestion` (GET) y `/api/resenas/gestion/<doc_id>` (POST).
- `templates/resenas_gestion.html` — nuevo.
- `permissions.py` (o un módulo nuevo `resenas_gestion.py`) — funciones CRUD para la colección, mismo patrón que `google_places_mapping`.

---

## Plan de ejecución (Fable, 2026-07-22) — LISTO PARA EJECUTAR, no implementado todavía

Investigación en modo económico (grep puntual, no lectura completa de archivos). 7 propuestas en 3 olas.

**Hallazgo previo:** `actualizar_todo.py` (líneas 55-63) ya invoca `google_reviews_sync.py` completo con `critical: False`. La creación de docs de gestión y la limpieza por retención (P2b) deben vivir DENTRO de `main()` de `google_reviews_sync.py` — no tocar `actualizar_todo.py`.

### OLA 1 (paralelo)

**P1a — Query de historial 7/30/90 días en `google_reviews_sync.py`**
Nueva función `get_rating_historial(bq_client, local, dias=90)` que consulta `Corporativo.google_reviews_snapshots` filtrando por `local` y `fecha_snapshot >= DATE_SUB(hoy, INTERVAL dias DAY)`, devuelve `[{"fecha":..., "rating":...}]` ordenado. Se llama en el loop de `main()` donde ya se llama `get_rating_prev_snapshot()` (línea ~417), agrega `entry["historial"]`. Patrón a calcar: `get_rating_prev_snapshot()` (línea ~191) — mismo `bigquery.QueryJobConfig` + `ScalarQueryParameter`. Reusar el `bq_client` ya obtenido en `main()` (línea 319), no crear uno nuevo por local. Output: clave `"historial"` en `__RESENAS_JSON__`, forma `{"TEMPLE__BARRIO CHINO": [{"fecha": "2026-07-21", "rating": 4.5}, ...]}`.

**P1b — Sparkline + selector de período en `templates/resenas_preview.html`**
Reemplazar la Sección 3 actual (`div#tendenciaBody`, línea ~109-112, poblada en JS línea ~266) por: selector 7d/30d/90d + sparkline SVG inline por local desde `datos.historial[key]` (sin librerías externas) + delta sobre el período elegido. Mantener el fallback "Sin datos de tendencia" para los primeros días con pocos snapshots. No tocar ranking ni tarjetas de reseñas — solo esta sección.

**P2 — CRUD Firestore `google_reviews_gestion` en `permissions.py`**
Agregar junto a las funciones de `google_places_mapping` (línea 420+):
- `list_gestion(db)` — mismo patrón que `list_places_mapping` (línea 420-423).
- `create_gestion_if_not_exists(db, doc_id, marca, local, rating, text, author_name, date_str)` — crea con `estado="nueva"`, `creado_at=SERVER_TIMESTAMP` SOLO si el doc no existe (guard `doc_ref.get().exists`, igual patrón que `update_places_mapping_status` línea 463) — nunca pisa `en_curso`/`resuelta`.
- `update_gestion_status(db, doc_id, estado=None, nota=None, actualizado_por=None)` — mismo patrón que `update_places_mapping_status` (línea 458-476), valida contra `_VALID_GESTION_STATUS = {"nueva","en_curso","resuelta"}`.
- `cleanup_gestion_retention(db)` — borra `estado="resuelta"` con `actualizado_at` > 30 días, y cualquier doc con `creado_at` > 90 días. Filtrar en Python sobre `.stream()` completo (colección chica, evita índice compuesto).
- Constante `GESTION_COLLECTION = "google_reviews_gestion"`. doc_id: reusar la misma lógica de `_review_key()` (ya existe en `google_reviews_sync.py` línea 215-220) para que la key coincida con la de `seen_review_keys` — decidir si mover esa función a `permissions.py` o duplicarla exacta.

### OLA 2

**P2b — Crear docs de gestión + limpieza retención en `google_reviews_sync.py`** (depende de P2 y P1a; mismo archivo que P1a, correr DESPUÉS)
En el bloque donde ya se calcula `entry["is_alert"]` (línea ~423) y se usa (línea ~447), llamar `create_gestion_if_not_exists(...)` para cada reseña negativa nueva. Al final de `main()`, llamar `cleanup_gestion_retention(db)` una vez por corrida. Reusar el cliente Firestore que ya se obtiene en `main()` para `check_alert_and_update_seen`.

**P3 — Ruta `/resenas/gestion` + endpoint POST + template nuevo** (depende de P2; sin conflicto de archivo con P2b, puede ir en paralelo)
- `app.py`: `@app.route("/resenas/gestion")` con `@login_required` (línea 91 — confirmado que NO exige rol, solo `session.get("user")`, a diferencia de `@require_superadmin`). Handler: `_get_firestore_client()` (línea 69) + `permissions.list_gestion(db)`, ordenar nueva→en_curso→resuelta, `render_template("resenas_gestion.html", items=..., csrf_token=...)`.
- `@app.route("/api/resenas/gestion/<path:doc_id>", methods=["POST"])`, `@login_required`, body JSON `estado`/`nota`, llama `update_gestion_status(db, doc_id, ..., actualizado_por=session["user"]["email"])`. Mismo patrón de respuesta que `/api/admin/places-mapping/<doc_id>/approve` (línea 674).
- `templates/resenas_gestion.html` nuevo: clonar de `admin.html` la tabla (líneas 570/627/668/730) + patrón CSRF (`CSRF_TOKEN` línea 849, header `X-CSRFToken` como líneas 1598-1647). Fila: marca/local/rating/texto/estado + botones en_curso/resuelta + nota.

### OLA 3

**P4 — Reporte semanal imprimible** (depende de P3, mismo archivo, correr DESPUÉS)
Sección aparte arriba de la tabla en `resenas_gestion.html`: nuevas negativas de la semana, resueltas de la semana, rating promedio por marca, ranking mejoras/caídas. Datos: query BQ nueva sobre `google_reviews_snapshots` últimos 7 días (en el handler de `app.py`, verificar si ya hay un helper de cliente BQ en `app.py` antes de duplicar) + filtro en memoria sobre lo que ya trae `list_gestion`. Agregar `@media print` en el `<style>` que oculte nav/botones y deje solo el resumen + tabla limpia.

**P5 — Link visible desde el tablero** (sin dependencia dura, pero lógicamente después de que P3 exista; sin conflicto de archivo con P4, puede ir en paralelo)
Dentro de `div#view-resenas` (línea 360 de `dashboard.html`, junto al iframe), agregar `<a href="/resenas/gestion" target="_blank">Gestionar reseñas negativas →</a>` (target=_blank porque es una página Jinja completa, no un fragmento para iframe). No agregarlo a `switchView()` — es un link estático simple, no un tab nuevo.

### Tabla de archivos (para no pisarse)

| Archivo | Propuestas | Orden |
|---|---|---|
| `google_reviews_sync.py` | P1a → P2b | secuencial |
| `templates/resenas_preview.html` | P1b | solo |
| `permissions.py` | P2 | solo, debe terminar antes de P2b y P3 |
| `app.py` | P3 → P4 | secuencial |
| `templates/resenas_gestion.html` | P3 → P4 | secuencial |
| `templates/dashboard.html` | P5 | solo |
| `actualizar_todo.py` | ninguna | sin cambios |

**Orden de olas:** Ola 1 (P1a, P1b, P2 en paralelo) → Ola 2 (P2b y P3 en paralelo, ambos después de P2; P2b también después de P1a) → Ola 3 (P4 después de P3; P5 en paralelo con P4, después de que P3 exista).
