# Tablero Locales Propios — Temple

**Fecha:** 2026-06-19
**Autor:** Darwin Salinas
**Estado:** Aprobado

## Objetivo

Construir un tablero dinámico para la gestión operativa y financiera de los locales propios de Temple: Barrio Chino y Monroe. El tablero consolida métricas de ventas (BigQuery), P&L financiero (Google Sheets), calificación de clientes (Google Places) y alertas operativas (Firestore), accesible mediante login con usuario y contraseña.

---

## Decisiones de diseño

| Decisión | Elección | Alternativas descartadas |
|----------|----------|--------------------------|
| Stack backend | FastAPI + Jinja2 + HTMX | React/Next.js (complejidad), Flask puro (sin HTMX) |
| Layout | Vista comparativa lado a lado | Tabs por local (no permite comparar de un vistazo) |
| Auth | Email + contraseña con cookie de sesión | Google OAuth (no aplica para este proyecto) |
| Contraseñas | Hash con bcrypt en Firestore | Plaintext (inseguro), Firebase Auth (overhead innecesario) |
| Filtros de período | HTMX para actualización parcial | Recarga de página completa (UX inferior) |
| Fuente ventas | BigQuery `curated_sales` | Toteat directo (sin capa curated) |
| Fuente financiero | Google Sheets API v4 | BigQuery (datos no disponibles ahí), manual (error-prone) |
| Fuente Google rating | Google Places API | Scraping (frágil), manual (no actualizable) |
| Alertas y distribuciones | Firestore + panel admin | Google Sheets, Notion (dependencias externas) |
| Deploy | Cloud Run con `gcloud run deploy --source` | Docker local (innecesario) |
| Presupuesto | **Fuera de scope** | — |

---

## 1. Métricas y fuentes de datos

### KPIs por local

| KPI | Fuente | Notas |
|-----|--------|-------|
| Ventas netas | BigQuery `temple-bar-439715.curated_database.curated_sales` | Filtrado por local y período |
| Ordenes | BigQuery `curated_sales` | COUNT de órdenes únicas |
| Ticket promedio | BigQuery `curated_sales` | Ventas netas / Ordenes |
| CMV (% sobre ventas) | Google Sheets — P&L Barrio Chino / P&L Monroe | Subtotal fila costo de mercadería |
| Costo laboral (% sobre ventas) | Google Sheets — P&L | Subtotal fila laboral |
| EBITDA (%) | Google Sheets — P&L | Fila EBITDA |
| Resultado operativo ($) | Google Sheets — P&L | Fila Resultado Operativo |
| Caja generada ($) | Google Sheets — P&L | Fila Caja Generada |
| Calificación Google | Google Places API | `rating` + `user_ratings_total` |
| Reclamos / Alertas operativas | Firestore `locales_config/{local}/reclamos` | Solo estado "activo" |
| Distribuciones o aportes requeridos | Firestore `locales_config/{local}/distribuciones` | Solo estado "pendiente" |

### Fuente Google Sheets

- **Spreadsheet ID:** `1Z2YFlCFLy7QUDm7GA09AQr8oCinJgvw3uP0CJNur2yo`
- **Hojas:** `P&L Barrio Chino` y `P&L Monroe`
- **Estructura:** columnas mensuales (Ene–Dic) + Total año. Filas: líneas del P&L con valor absoluto y porcentaje sobre ventas.
- **Lectura:** rangos fijos por hoja, parseados por nombre de fila.

---

## 2. Períodos de tiempo

- **Vista default:** último mes cerrado con datos completos
- **Filtros disponibles:** mes anterior, YTD (acumulado año en curso)
- **Comportamiento:** al cambiar período, HTMX actualiza solo el bloque de KPIs sin recargar la página. El período queda reflejado en la URL (`?periodo=2026-05`) para permitir bookmarking y compartir.

---

## 3. Layout del tablero

Vista comparativa lado a lado: columna izquierda Barrio Chino, columna derecha Monroe. Ambas con la misma estructura de KPIs.

```
┌─────────────────────────────────────────────────────────┐
│  TEMPLE — Locales Propios    [Mayo 2026][Abr 2026][YTD] │
├────────────────────────┬────────────────────────────────┤
│  🏪 BARRIO CHINO       │  🏪 MONROE                     │
│  ┌──────┬──────┬─────┐ │  ┌──────┬──────┬─────┐        │
│  │Ventas│Orden.│T.Pr.│ │  │Ventas│Orden.│T.Pr.│        │
│  ├──────┴──────┘     │ │  ├──────┴──────┘     │        │
│  │ CMV%  │ Laboral%  │ │  │ CMV%  │ Laboral%  │        │
│  ├───────┼───────────┤ │  ├───────┼───────────┤        │
│  │EBITDA │Resultado  │ │  │EBITDA │Resultado  │        │
│  │       │Caja Gen.  │ │  │       │Caja Gen.  │        │
│  ├───────┴───────────┤ │  ├───────┴───────────┤        │
│  │ Google ★   Distrib│ │  │ Google ★   Distrib│        │
│  ├───────────────────┤ │  ├───────────────────┤        │
│  │ ⚠ Reclamos activos│ │  │ ✓ Sin reclamos    │        │
└──┴───────────────────┴─┴──┴───────────────────┴────────┘
```

**Semáforo de colores:**
- CMV: verde < 30%, amarillo 30–35%, rojo > 35%
- Costo laboral: verde < 25%, amarillo 25–30%, rojo > 30%
- EBITDA y Resultado operativo: verde si positivo, rojo si negativo
- Reclamos: rojo si hay activos, verde si no hay

Los umbrales de CMV y costo laboral son los valores default; pueden ajustarse en una variable de config sin redespliegue.

---

## 4. Autenticación

- **Método:** email + contraseña
- **Almacenamiento:** Firestore colección `users_config`, contraseña hasheada con `bcrypt`
- **Sesión:** cookie firmada con `itsdangerous`
- **Pantalla:** `GET /login` con formulario email + contraseña. Sin Google OAuth.
- **Gestión de usuarios:** Darwin crea/edita/elimina usuarios desde el panel admin (`/admin`)

### Estructura usuario en Firestore

```
users_config/{email}:
  role: "superadmin" | "viewer"
  password_hash: "$2b$12$..."
  created_at: timestamp
  updated_at: timestamp
```

---

## 5. Panel admin (`/admin`)

Solo accesible para rol `superadmin`. Tres secciones:

### 5.1 Gestión de usuarios
- Listar usuarios existentes
- Crear usuario: email + contraseña + rol
- Editar contraseña o rol
- Eliminar usuario

### 5.2 Reclamos / Alertas operativas
- Seleccionar local (Barrio Chino / Monroe)
- Agregar alerta: texto + fecha
- Cerrar alerta (estado → "cerrado", deja de mostrarse en el tablero)
- Ver historial de alertas cerradas

### 5.3 Distribuciones y aportes
- Seleccionar local
- Agregar distribución/aporte: monto + descripción + fecha
- Marcar como pagado
- Ver historial

---

## 6. Modelo de datos en Firestore

```
users_config/
  {email}:
    role: "superadmin" | "viewer"
    password_hash: string
    created_at: timestamp
    updated_at: timestamp

locales_config/
  barrio_chino/
    reclamos: [
      { id, texto, fecha, estado: "activo" | "cerrado", cerrado_at }
    ]
    distribuciones: [
      { id, monto, descripcion, fecha, estado: "pendiente" | "pagado", pagado_at }
    ]
  monroe/
    reclamos: [...]
    distribuciones: [...]
```

---

## 7. Cache y performance

| Fuente | TTL | Estrategia |
|--------|-----|------------|
| BigQuery | 30 minutos | Cache en memoria por (local, período) |
| Google Sheets P&L | 6 horas | Cache en memoria, invalidable manualmente |
| Google Places API | 24 horas | Cache en memoria por local |
| Firestore (alertas, distribuciones) | Sin cache | Lectura directa en cada request |

---

## 8. Rutas de la aplicación

| Ruta | Descripción |
|------|-------------|
| `GET /login` | Pantalla de login |
| `POST /login` | Autenticación, crea sesión |
| `GET /logout` | Elimina sesión |
| `GET /tablero` | Tablero principal (último mes cerrado por default) |
| `GET /tablero/kpis` | Fragmento HTMX de KPIs según `?periodo=` |
| `GET /admin` | Panel admin (solo superadmin) |
| `POST /admin/usuarios` | Crear/editar usuario |
| `DELETE /admin/usuarios/{email}` | Eliminar usuario |
| `POST /admin/reclamos` | Crear reclamo por local |
| `PATCH /admin/reclamos/{id}` | Cerrar reclamo |
| `POST /admin/distribuciones` | Crear distribución |
| `PATCH /admin/distribuciones/{id}` | Marcar como pagado |

---

## 9. Variables de entorno

```
GOOGLE_SHEETS_ID=1Z2YFlCFLy7QUDm7GA09AQr8oCinJgvw3uP0CJNur2yo
PLACES_API_KEY=<Google Maps API Key>
PLACES_ID_BARRIO_CHINO=<Place ID de Barrio Chino en Google Maps>
PLACES_ID_MONROE=<Place ID de Monroe en Google Maps>
SESSION_SECRET=<string aleatorio largo>
FIRESTORE_PROJECT=temple-bar-439715
BQ_PROJECT=temple-bar-439715
BQ_DATASET=curated_database
BQ_TABLE=curated_sales
```

---

## 10. Despliegue

- **Plataforma:** Cloud Run, proyecto `temple-bar-439715`
- **Nombre del servicio:** `locales-propios`
- **Deploy:** `gcloud run deploy locales-propios --source . --region us-central1`
- **Service Account:** SA del proyecto con acceso a BigQuery, Firestore y Sheets API
- **No requiere Docker local**

---

## 11. Fuera de scope (v1)

- Evolución vs presupuesto
- Gráficos de tendencia temporal
- Notificaciones por email o WhatsApp
- Integración con sistema contable externo
- Responsive/mobile completo
