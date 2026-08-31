# Tablero Mundial 2026 — Diseño

**Fecha:** 2026-07-08  
**Proyecto:** Nuevo servicio Flask independiente — "mundial"  
**Alcance:** Tablero temporal sin autenticación para análisis de ventas durante partidos del Mundial 2026

---

## Contexto

El equipo comercial necesita analizar el comportamiento de ventas en los locales durante los partidos del Mundial. El tablero debe comparar performance durante partidos vs. días normales (mismo turno, sin partido), y permitir filtrar por partido, marca, establecimiento y turno.

---

## Arquitectura

### Patrón: Flask + dataset precargado en GCS

```
generar_mundial.py
    └─► Query BQ: vw_Ventas_Corporativo_Base + vw_productos_maestro_clean
    └─► Genera mundial_data.json
    └─► Sube a GCS (bucket temple-bar-439715 / carpeta mundial/)

Flask app — Cloud Run (nuevo servicio: "mundial")
    GET /           → sirve tablero.html con JSON precargado
    GET /refresh    → regenera JSON desde BQ (uso interno, sin auth)

tablero.html
    └─► JSON embedido como variable JS global al cargar la página
    └─► JS puro maneja todos los filtros (sin roundtrips al servidor)
    └─► Chart.js 4.4 para gráficos
    └─► Mismo sistema visual que Locales Propios (style.css reutilizado)
```

**Ventaja clave:** cada cambio de filtro es instantáneo (operación en memoria JS). La única query a BQ ocurre cuando se corre `generar_mundial.py` manualmente post-partido.

---

## Fuentes de datos

| Fuente | Uso |
|--------|-----|
| `temple-bar-439715.Corporativo.vw_Ventas_Corporativo_Base` | Órdenes: GMV, órdenes, ticket, productos vendidos |
| `temple-bar-439715.Corporativo.vw_productos_maestro_clean` | Catálogo: categoría, litros de cerveza por SKU |

### Definición de partidos (hardcodeado en `generar_mundial.py`)

```python
PARTIDOS = [
    {"id": 1, "nombre": "Partido 1", "fecha": "2026-XX-XX", "inicio": "HH:MM", "fin": "HH:MM"},
    # ... completar con fechas reales del fixture
]
```

### Definición de turnos (hardcodeado)

| Turno | Rango horario |
|-------|---------------|
| Tarde | 09:00 – 18:00 |
| Noche | 20:00 – 05:00 |

### Marcas disponibles

Tomadas directamente de la columna `marca` en la vista BQ: `Temple`, `Patagonia`, `Feriado`.

---

## Estructura del JSON (`mundial_data.json`)

```json
{
  "partidos": [
    {
      "id": 1,
      "nombre": "Partido 1",
      "fecha": "2026-XX-XX",
      "inicio": "HH:MM",
      "fin": "HH:MM"
    }
  ],
  "ordenes": [
    {
      "partido_id": 1,
      "turno": "tarde",
      "marca": "Temple",
      "local": "Barrio Chino",
      "orden_id": "...",
      "gmv": 1500.0,
      "items": [
        {
          "sku": "...",
          "nombre": "...",
          "categoria": "bebidas",
          "cantidad": 2,
          "gmv": 600.0,
          "litros": 1.0
        }
      ]
    }
  ],
  "ordenes_normales": [
    // misma estructura que ordenes, de días sin partido (para comparativo)
    // criterio: mismo día de la semana, mismo turno, sin solapamiento con partido
  ],
  "promos": [
    {
      "nombre": "Promo XX",
      "partido_id": 1,
      "local": "Barrio Chino",
      "unidades": 10,
      "gmv": 3000.0
    }
  ]
}
```

---

## UI / Layout

### Header
- Fondo `--temple-slate` (#323E48), textura crinkle-magenta (igual que Locales Propios)
- Logo Temple blanco + texto "Mundial 2026"
- Sin login ni botón de salir (acceso abierto)

### Barra de filtros (sticky, fila horizontal)
```
[ Partido ▼ ]  [ Marca ▼ ]  [ Establecimiento ▼ ]  [ Turno ▼ ]
```
- Establecimiento filtra dinámicamente según el partido seleccionado
- Todos los filtros son acumulativos: la vista se recalcula en JS al cambiar cualquiera

---

### Sección 1 — Banderas KPI (cards horizontales)

| Card | Métrica | Comparativo |
|------|---------|-------------|
| GMV Total | Suma GMV período filtrado | ▲/▼ vs. día normal mismo turno |
| Órdenes | Cantidad de órdenes | ▲/▼ vs. día normal |
| Ticket Promedio | GMV / órdenes | ▲/▼ vs. día normal |
| Litros de birra | Suma litros de cerveza | ▲/▼ vs. día normal |

Semáforo visual: verde si supera día normal, rojo si no.

---

### Sección 2 — Gráficos (fila de 3, Chart.js)

1. **Litros de birra por tipo de cerveza** — bar horizontal, agrupado por SKU/categoría de cerveza
2. **Mix de categorías** — donut: comidas / bebidas / promos (% sobre GMV total)
3. **Comparativo entre partidos** — bar agrupado: eje X = partidos, series = GMV / órdenes / ticket

---

### Sección 3 — Promociones (tabla)

Columnas: Promo | Unidades vendidas | GMV generado | Locales activos | % del total  
Fila expandible por local donde se activó la promo.

---

### Sección 4 — Ranking de productos

Toggle: **Por unidades** / **Por GMV**  
Selector de categoría: Todas / Comidas / Bebidas / Promos  
Top 10 productos con barra de progreso visual.

---

### Sección 5 — Tabla comparativa entre partidos

Fila por partido, columnas: Partido | GMV | Órdenes | Ticket prom. | Litros birra | Top producto  
Permite ver evolución a lo largo del torneo de un vistazo.

---

## Sistema visual

Hereda íntegramente de Locales Propios:
- `style.css` copiado al nuevo proyecto
- Mismas fuentes: Gotham (body), Knockout 71 (headlines)
- Mismos tokens de color: `--temple-slate`, `--temple-pink`, `--temple-teal`, semáforo verde/amarillo/rojo
- Textura de fondo: `crinkle-magenta.jpg`
- Chart.js 4.4 con colores de marca

---

## Deploy

```bash
gcloud run deploy mundial \
  --source . \
  --region us-central1 \
  --project temple-bar-439715 \
  --allow-unauthenticated \
  --quiet
```

Sin variables de entorno sensibles. Solo necesita acceso a GCS para leer `mundial_data.json`.

---

## Flujo de actualización post-partido

1. Correr `python -X utf8 generar_mundial.py`
2. El script descarga la data de BQ, genera el JSON y lo sube a GCS
3. El próximo request al tablero descarga el JSON actualizado automáticamente

No se necesita redeploy.

---

## Fuera de alcance (MVP)

- Auth / login
- Actualización automática / webhook post-partido
- Exportación a CSV/Excel
