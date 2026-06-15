---
date: 2026-04-08
topic: web-app-temple-bar-deploy
---

# Temple Bar Dashboard — Web App Deploy

## Problem Frame

El dashboard se entrega actualmente como un archivo HTML estático de 1.1 MB con datos embebidos. Temple Bar recibe un archivo nuevo cada vez que los datos se actualizan, y no existe URL permanente ni control de acceso. Esto genera fricción para el cliente, impide la evolución del producto, y bloquea la reutilización del código para otros clientes.

## High-Level Architecture

```
Browser
  │
  ▼
Cloud Run (Flask app)
  ├── GET  /login          → Google OAuth redirect
  ├── GET  /dashboard      → sirve HTML (carga datos vía fetch)
  ├── GET  /api/data       → devuelve JSON cacheado (GCS / Firestore)
  └── POST /api/refresh    ← Cloud Scheduler (nightly, UTC-3)
                                └── consulta BigQuery → actualiza caché
```

## Requirements

**Hosting y Acceso**
- R1. El dashboard es accesible vía una URL permanente; no se requiere abrir ni compartir archivos HTML.
- R2. El acceso requiere autenticación con Google OAuth. Los visitantes no autenticados son redirigidos al login de Google.
- R3. Solo los emails en una whitelist administrada pueden acceder. Cuentas no autorizadas reciben una página "acceso denegado".
- R4. La whitelist de emails se gestiona via archivo de configuración (sin UI de administración en v1).

**Frescura de Datos**
- R5. Los datos se actualizan automáticamente una vez al día durante la madrugada (zona horaria Buenos Aires, UTC-3).
- R6. El dashboard muestra el dataset cacheado más reciente. Si el refresh falla, el último dataset exitoso permanece disponible junto a un timestamp visible de "última actualización".

**API de Datos**
- R7. Los datos del dashboard se sirven via un endpoint API; no están embebidos en el HTML.
- R8. Todo el comportamiento de filtrado client-side existente (rango de fechas, selección de establecimientos, tabs) continúa funcionando igual sobre los datos recibidos via API.

**Exportar Datos**
- R9. Los usuarios pueden descargar los datos actualmente filtrados como CSV.
- R10. La exportación respeta los filtros activos (rango de fechas + establecimientos). Cada tab del dashboard genera su propio CSV.

**Preparación Multi-Cliente**
- R11. El ID del proyecto BigQuery, el dataset ID, y la lista de establecimientos se externalizan en configuración para que el mismo código pueda desplegarse para un cliente diferente cambiando solo la config, sin tocar código.

## Success Criteria
- Un stakeholder de Temple Bar abre una URL, se loguea con su cuenta Google, y ve datos de la noche anterior — sin recibir ni abrir ningún archivo HTML.
- Deployar la misma app para un segundo cliente requiere solo cambios de configuración.
- El dashboard carga en menos de 3 segundos en una conexión estándar.
- Un fallo en el refresh nocturno no deja el dashboard fuera de servicio.

## Scope Boundaries
- Sin UI de gestión de usuarios en v1; la whitelist se administra via archivo de config.
- Sin actualizaciones en tiempo real; el refresh diario es suficiente para BI ejecutivo.
- Sin comparativa año a año en esta fase.
- Sin drill-down por establecimiento individual en esta fase.
- Los archivos HTML legacy (`dashboard_ventas_temple.html`, `tablero_ventas.html`, `tablero-ventas-corregido.html`, `index.html`) no se eliminan en esta fase.

## Key Decisions
- **Flask en Cloud Run (no GCS estático):** Habilita auth server-side real, separación de API, y config multi-cliente — el costo adicional justifica los beneficios sobre un approach estático.
- **Whitelist de emails (no restricción por dominio):** Los stakeholders de Temple Bar pueden usar cuentas Gmail externas; la whitelist brinda control preciso sin depender de un dominio corporativo.
- **Exportación CSV client-side:** Los datos filtrados ya están en el browser; no requiere intervención del servidor. Bajo costo, reutiliza el pipeline de datos existente.
- **Refresh diario nocturno:** Apropiado para BI ejecutivo; evita costos de queries BigQuery por demanda.
- **Adaptar `actualizar_dashboard.py` como handler del endpoint `/api/refresh`:** La lógica de extracción BigQuery ya está implementada y probada.

## Dependencies / Assumptions
- El proyecto GCP `temple-bar-439715` y el dataset BigQuery `temple_bar` permanecen accesibles.
- Los stakeholders de Temple Bar tienen cuentas Google (cualquier dominio).
- La lógica de refresh existente en `actualizar_dashboard.py` puede adaptarse como handler del Cloud Run job.

## Outstanding Questions

### Deferred to Planning
- [Affects R6][Technical] ¿Cache de datos procesados en GCS (archivo JSON) o Firestore (documento)? Evaluar costo y latencia de lectura.
- [Affects R5][Needs research] Ventana óptima del cron de Cloud Scheduler considerando el tiempo de ejecución estimado de las queries BigQuery (~30-90s).
- [Affects R11][Technical] ¿Config per-cliente via env vars del Cloud Run service o archivo YAML commiteado por deployment?

## Next Steps
→ `/ce:plan` para planificación detallada de implementación
