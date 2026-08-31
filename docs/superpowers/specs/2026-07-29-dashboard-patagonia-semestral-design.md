# Tablero Semestral Patagonia — Diseño

**Fecha:** 2026-07-29
**Proyecto:** Nuevo servicio Flask independiente — `Proyecto_Patagonia_Semestral`
**Alcance:** Tablero interactivo temporal (sin autenticación) para la reunión semestral de resultados con Patagonia (semana del 2026-08-04). Cubre el primer semestre 2026 (enero–junio) de la marca Patagonia (Refugios), con la acción "Mundial" incluida aparte aunque su ventana se extienda a julio.

---

## Contexto

Temple Bar tiene reunión semestral de resultados con Patagonia y quiere presentar la información de forma interactiva en vivo (no PDF). El tablero debe mostrar: KPIs headline del semestre con evolución mensual, crecimiento YoY, sellin vs. sellout de cerveza, ranking de Refugios, resultados de 6 acciones comerciales del semestre, ranking de combos de toda la red, y evolución de Reputology (rating/NPS/reseñas) por trimestre.

Dos datos no están en BigQuery y se cargan a mano: **sellin de cerveza** (lo pasa Agus desde Patagonia — Thinkion no lo tiene) y **NPS** (lo consigue Darwin desde Reputology — no existe en ningún sistema integrado). *Sellout* de cerveza, en cambio, ya está en BigQuery: es la venta a consumidor final en los Refugios.

---

## Arquitectura

### Patrón elegido: Flask standalone + dataset precargado en GCS (mismo patrón que `Proyecto_Mundial`)

```
generar_patagonia_semestral.py
    └─► Query BQ: vw_Ventas_Corporativo_Base (Marca='Patagonia')
    └─► Query BQ: vw_productos_maestro_clean (marca='PATAGONIA')
    └─► Query BQ: google_reviews_snapshots (marca='Patagonia')
    └─► Lee data/sellin_cerveza.csv y data/nps.csv (manuales)
    └─► Lee acciones.py (fechas de las 6 acciones)
    └─► Combina todo en un único patagonia_data.json
    └─► Sube a GCS (bucket temple-bar-dashboard-cache / carpeta patagonia_semestral/)

Flask app — Cloud Run (nuevo servicio: "patagonia-semestral")
    GET /         → sirve dashboard.html con el JSON precargado
    GET /data     → sirve el JSON cacheado en memoria (evita re-leer GCS en cada request)
    GET /refresh  → recarga el JSON desde GCS (uso interno, sin auth)

dashboard.html
    └─► JSON embebido/cargado como variable JS global al iniciar
    └─► JS puro maneja las 7 tabs (sin roundtrips al servidor)
    └─► Chart.js para gráficos de evolución mensual
    └─► Un solo JSON (no fragmentado por tab): volumen modesto — 6 meses, ~35 Refugios, datos mensuales/trimestrales — no justifica la complejidad de servir múltiples archivos
```

**Sin autenticación:** el link se comparte directo, como en `Proyecto_Mundial`. No se distribuye fuera de la reunión. `/refresh` queda sin proteger (uso interno).

### Approaches descartados

| Approach | Por qué se descartó |
|---|---|
| Tab nuevo dentro de `dashboard.html` (tablero principal) | Reutiliza la infraestructura de auth existente, pero esa auth (OAuth whitelist `@temple.com.ar`) es exactamente lo que no se necesita acá — Patagonia no tiene esos emails y de todos modos se decidió sin auth. Además acopla el release de este tablero temporal al ciclo de deploy del dashboard de producción diario. |
| HTML estático sin backend (JSON fijo embebido, sin Flask) | Más simple de desplegar, pero sin `/refresh` — cada ajuste de las fechas de acciones (hoy son placeholders) o cada actualización de los CSV manuales de Agus/Darwin obligaría a re-generar y re-deployar el HTML completo en vez de solo correr el generador y pegar el link de nuevo. Dado que ya se sabe que ambas cosas van a cambiar antes de la reunión, se descartó. |

---

## Fuentes de datos por KPI

| KPI | Fuente / fórmula |
|---|---|
| GMV | `SUM(Facturacion)` en `vw_Ventas_Corporativo_Base` WHERE `Marca='Patagonia'` |
| Órdenes | `COUNT(DISTINCT Orden)` misma vista/filtro |
| AOV (ticket promedio) | GMV / Órdenes |
| Litros de cerveza (sellout) | `SUM(cerveza_total)` en `vw_productos_maestro_clean` WHERE `marca='PATAGONIA'` |
| Litros por orden | Litros de cerveza / Órdenes del mismo período — ratio agregado. **No** es un join a nivel de orden individual: se verificó que el campo `id` de `vw_productos_maestro_clean` no coincide con `Orden` de `vw_Ventas_Corporativo_Base` (son SKUs de producto, no IDs de orden; un mismo `id` aparece repetido en fechas y locales distintos). Toda relación entre ambas vistas se hace agregando por fecha + marca + local, nunca por orden. |
| SOT cerveza sobre alcohólicas | **En unidades, no en litros:** `SUM(cantidad WHERE tipo='CERVEZA') / SUM(cantidad WHERE tipo IN ('CERVEZA','TRAGOS','VINO'))` sobre `vw_productos_maestro_clean`. Se eligió unidades porque BigQuery solo tiene litros calculados para cerveza, gin y fernet (no para vodka/ron/vino/vermuth/tragos/aperitivo) — litros no cubre el universo alcohólico completo, unidades sí. **Limitación conocida:** las líneas de combo/promo con `tipo` NULL (la mayoría de los `PROMOCIÓN` sin categoría de cerveza explícita) quedan fuera tanto del numerador como del denominador — el SOT puede subestimar o sobreestimar levemente según cómo se reparta esa cerveza dentro de combos sin tipo asignado. |
| Sellin de cerveza | `data/sellin_cerveza.csv` (manual, litros mensuales que pasa Agus) |
| Sellin vs. Sellout (cerveza) | Litros sellin (CSV) vs. litros sellout (BQ, fila arriba), comparados mes a mes y en total del semestre. Esta comparación es **exclusivamente de cerveza en litros** — no de GMV ni de otras categorías. |
| Evolución mensual | Todos los KPIs anteriores agrupados por `FORMAT_DATE('%Y-%m', Fecha)` |
| Crecimiento YoY (mes vs. mismo mes 2025) | GMV, Órdenes y Litros de cerveza, mes 2026 vs. mismo mes 2025. Verificado con query real: hay datos completos de Patagonia en BQ desde enero 2025 (GMV, órdenes y locales activos consistentes mes a mes), por lo que la comparación YoY es viable para los 6 meses del semestre. |
| Ranking de Refugios | `GROUP BY Local` sobre `vw_Ventas_Corporativo_Base` (GMV, Órdenes) y sobre `vw_productos_maestro_clean` agregado por local (litros de cerveza). **Una sola tabla ordenable** por cualquiera de las tres columnas (GMV, litros de cerveza, órdenes); al ordenar por una columna se resaltan las 5 filas superiores (Top 5) y las 5 inferiores (Bottom 5) de ese criterio. **Caveat técnico verificado y resuelto (2026-07-29):** para otras marcas del grupo (ej. Feriado) el nombre de local puede no coincidir textualmente entre vistas, pero **se verificó con query real que para Patagonia específicamente los 43 locales de `Local` (`vw_Ventas_Corporativo_Base`) coinciden 1:1 y carácter por carácter con los 43 de `establecimiento` (`vw_productos_maestro_clean`)** — diff exacto por `NOT IN` entre ambos conjuntos da cero filas. No se necesita mapeo de nombres para este dashboard: join directo por igualdad de string. |
| Combos (ranking de red completa) | Se identifican por nombre de producto en `vw_productos_maestro_clean`: `UPPER(producto) LIKE '%COMBO%' OR UPPER(producto) LIKE '%PROMO%'`. "Incluye cerveza" = `cerveza_total > 0` en esa línea (el pipeline de datos ya prorratea litros de cerveza dentro de las líneas de combo que la incluyen — confirmado con datos reales, ej. "COMBO CUMPLE 1" tiene litros de cerveza asociados, "COMBO CUMPLE 4 (SIN CERVEZA)" no). Ranking por unidades vendidas (`cantidad`), facturación (`dinero`) y locales que lo activan (`COUNT DISTINCT establecimiento`, es decir cantidad de Refugios distintos que vendieron ese combo/promo al menos una vez en el semestre). |
| Reputology — rating, NPS y cantidad de reseñas por Q | **Cambio de fuente (2026-07-29, verificado en BigQuery real):** `google_reviews_snapshots` solo tiene datos desde el 2026-07-22 (8 días, 0 filas en el rango enero-junio 2026) — la API de Google no expone rating histórico, así que ese vacío es irrecuperable sin importar cómo se reconfigure el sync. Por decisión del usuario, **todo el bloque Reputology (rating + NPS + cantidad de reseñas) sale de `data/reputology.csv`**, un export manual de la plataforma externa Reputology, por trimestre calendario (Q1 = ene-mar, Q2 = abr-jun) y por Refugio. `google_reviews_snapshots` **no se usa** en este dashboard. |
| Resultados de acciones (uplift) | Ventana de la acción vs. un período de referencia sin la acción, mismo patrón usado en `Proyecto_Mundial`. Excepción: Otoño y 8va canilla/isleña no usan uplift (ver sección "Detalle de acciones"). |

---

## Estructura de datos manuales (sellin de cerveza y NPS)

Dos archivos CSV en `Proyecto_Patagonia_Semestral/data/`, versionados junto al código del proyecto (no en BigQuery), pensados para que Agus o Darwin los editen directamente sin tocar código. El generador (`generar_patagonia_semestral.py`) los lee en cada corrida — actualizar el dato es: editar el CSV → volver a correr el generador → el link ya refleja el cambio (o llamar a `/refresh` si el Cloud Run ya está desplegado).

**`data/sellin_cerveza.csv`:**
```
mes,litros_sellin
2026-01,
2026-02,
2026-03,
2026-04,
2026-05,
2026-06,
```
*(placeholder vacío — ver sección "Pendientes antes de implementar")*

**`data/reputology.csv`:**
```
trimestre,refugio,rating,nps,cantidad_resenas,fuente
2026-Q1,TOTAL,,,,Reputology
2026-Q2,TOTAL,,,,Reputology
```
`refugio='TOTAL'` es el agregado de la red. Si Darwin consigue el detalle por Refugio, se agregan filas adicionales con el nombre del Refugio en esa columna; si solo hay dato total, el desagregado por Refugio se muestra como "sin dato" en esa tab sin bloquear el resto del tablero. Las tres métricas (`rating`, `nps`, `cantidad_resenas`) salen del mismo export de la plataforma Reputology — no hace falta combinar con ninguna fuente de BigQuery.

---

## Estructura de secciones / tabs del dashboard

1. **Resumen semestral** — KPIs headline (GMV, Órdenes, AOV, Litros de cerveza, Litros por orden, SOT) en tarjetas, con comparación YoY visible en cada tarjeta.
2. **Evolución mensual** — gráficos de línea/barra mes a mes de los mismos KPIs, con la serie 2025 de referencia superpuesta para dar contexto al YoY.
3. **Sellin vs. Sellout (cerveza)** — comparación mensual y total del semestre, litros sellin (CSV) vs. litros sellout (BQ).
4. **Ranking de Refugios** — tabla ordenable por GMV / litros de cerveza / órdenes, con Top 5 y Bottom 5 resaltados.
5. **Acciones** — una card por acción (Carnaval, Semana de la hamburguesa, Semana de la cerveza, Mundial, Otoño, 8va canilla/isleña) mostrando el resultado de cada una (uplift o evolución interna según el caso — ver detalle abajo).
6. **Combos** — ranking de combos/promos de toda la red, con columna "incluye cerveza" (sí/no), unidades, facturación y locales que lo activan.
7. **Reputology** — evolución por trimestre (Q1/Q2 2026) de rating, NPS y cantidad de reseñas, total red y desagregado por Refugio. Fuente 100% manual (`data/reputology.csv`, export de la plataforma Reputology) — no depende de BigQuery.

---

## Detalle de acciones (fechas placeholder — TODAS a confirmar)

| Acción | Ventana propuesta (placeholder, a confirmar) | Tipo de resultado mostrado |
|---|---|---|
| Carnaval | 2026-02-14 a 2026-02-17 | Uplift vs. semana previa sin feriado |
| Semana de la hamburguesa | 2026-05-11 a 2026-05-17 | Uplift vs. semana previa de mayo |
| Semana de la cerveza | 2026-05-18 a 2026-05-24 | Uplift vs. semana previa |
| Mundial | 2026-06-02 a 2026-07-19 (rango ya definido y con datos generados en `Proyecto_Mundial`) | Se reutiliza el uplift ya calculado en `Proyecto_Mundial` — no se recalcula desde cero. Corte de datos: 19/07/2026 (dato ya generado y cerrado; no se regenera para este tablero aunque la reunión sea después). |
| Otoño | 2026-03-01 a 2026-05-31 | **Evolución interna del período, sin uplift.** Es un rango de 3 meses, no un evento puntual — no existe una "semana equivalente sin otoño" contra la cual comparar de forma significativa. Se muestra la serie de GMV/litros de cerveza dentro del rango. |
| 8va canilla / isleña | 2026-04-01 a 2026-06-30 | **Evolución interna del período, sin uplift**, mismo criterio que Otoño. |

Las fechas de las 6 acciones son **aproximaciones iniciales, marcadas explícitamente como placeholder** en `acciones.py` con un comentario visible (`# TODO: fecha a confirmar con Darwin antes de generar el dato final`), pensadas para no bloquear el desarrollo del resto del tablero mientras se confirman las fechas reales.

---

## Autenticación

Sin autenticación — link directo, mismo patrón que `Proyecto_Mundial`. El endpoint `/refresh` queda sin proteger porque es de uso interno y el link no se distribuye fuera de la reunión con Patagonia.

---

## Pendientes antes de poder implementar / generar el dato final

Estos tres puntos no bloquean escribir el código del generador ni del dashboard (se puede construir con placeholders), pero **sí bloquean generar el JSON final con datos reales** para la reunión:

1. **Fechas reales de las 6 acciones** (Carnaval, Semana de la hamburguesa, Semana de la cerveza, Otoño, 8va canilla/isleña). Hoy son aproximaciones placeholder en la tabla de arriba. El Mundial es la única que ya tiene fecha real y dato generado.
2. **`data/sellin_cerveza.csv` real** — Agus todavía no mandó los litros mensuales de sellin de cerveza para el semestre. El CSV está creado con la estructura correcta pero vacío.
3. **`data/reputology.csv` real** — Darwin todavía tiene que exportar rating + NPS + cantidad de reseñas por Q (Q1 y Q2 2026, total y por Refugio) desde la plataforma Reputology. El CSV está creado con la estructura correcta pero vacío. Sin este archivo la tab 7 no tiene nada para mostrar (a diferencia de las otras tabs, que sí tienen datos reales de BigQuery aunque falten los otros dos CSV).
