# Tarjetas "Top Refugios" — Diseño

**Fecha:** 2026-08-03
**Proyecto:** `Proyecto_Patagonia_Semestral` (extensión del tab Ranking Refugios)
**Alcance:** Agregar una vista de 6 tarjetas (Top Refugios por GMV) arriba de la tabla ordenable existente del tab "Ranking Refugios", inspirada en un slide de referencia que Darwin ya usó en una reunión con Patagonia.

---

## Contexto

Darwin compartió un screenshot de un slide "Top refugios - H1 2026" con 6 tarjetas (Ushuaia, Puerto Iguazú, Chaltén, Puerto Madero, Neuquén, Resistencia): cada una muestra GMV, Litros y SOT con variación YoY (▲/▼), más un texto "Palancas" con comentario de negocio. Quiere esa misma vista dentro del tab Ranking Refugios del tablero interactivo.

**Hallazgo clave durante el brainstorming:** el GMV de las 6 tarjetas del screenshot coincide casi exactamente con el Top 6 real que ya calcula el tablero — confirma que el slide se basa en datos reales de Patagonia, no es un mockup genérico. Sin embargo, los **litros no coinciden** (diferencias de -8% a +86% según el Refugio, sin un factor de conversión consistente) — el slide probablemente usa otra metodología o fecha de corte, sin la corrección de estimación de pintas que ya tiene el tablero ([[lesson_patagonia-sellin-total-vs-suma-refugios]] y `estimacion_pintas.py`). Darwin decidió (ver Decisiones) usar los litros recalculados por el tablero, no los del slide.

Dos gaps de datos que hoy no existen en el pipeline:
1. **SOT por Refugio** — hoy `sot_cerveza` solo se calcula agregado (todo el semestre, todos los Refugios juntos).
2. **YoY por Refugio** (GMV, Litros, SOT) — `ventas_local`/`productos_local` (que alimentan la tabla y el ranking existentes) vienen pre-filtrados solo a H1 2026; no hay equivalente H1 2025 por Refugio.

---

## Decisiones clave

- **Alcance: Top 6 por GMV**, no los 36 Refugios ni un Top 10 — igual que el slide de referencia.
- **Ubicación: arriba de la tabla ordenable existente** en el tab Ranking Refugios (no reemplaza nada, no es un tab nuevo).
- **Unidad de litros: hectolitros (hL)**, recalculados por el pipeline (con la corrección de pintas) — no los litros del slide. Consistente con las tarjetas del Resumen y el gráfico de Evolución mensual (ya migrados a hL en esta misma sesión).
- **Delta de SOT en puntos porcentuales** (`sot_actual - sot_anterior`, ×100), no en % relativo — así se lee el screenshot ("▼ -0,7 pp") y es la forma correcta de comparar una métrica que ya es un ratio.
- **Estilo visual: el del tablero** (tarjeta oscura `#1e272e`, borde/acento rosa Temple), no el verde/gris del slide — para que se integre con el resto del tab en vez de parecer un elemento pegado de otra fuente.
- **Texto "Palancas": Darwin ajusta los números a mano.** Se parte del texto del slide, pero como los litros (y por lo tanto los % YoY) van a ser distintos a los del slide original, los números que menciona cada texto (ej. "+9% litros", "SOT 93%") se van a recalcular durante la implementación para que coincidan con los valores reales que muestra la tarjeta al lado — no se dejan los números viejos del slide ni se sacan directamente.
- Si en el futuro un Refugio nuevo entra al Top 6 y no tiene texto en `palancas.py`, la tarjeta simplemente no muestra el bloque "Palancas" (no bloquea, no rompe).

---

## Datos: nuevas funciones en `generar_patagonia_semestral.py`

```
_construir_top_refugios(refugios, rows_ventas, rows_productos, n=6)
    Toma los primeros `n` de `refugios` (ya vienen ordenados por gmv desc, ver
    _construir_refugios existente). Para cada uno:
      - gmv, litros_cerveza: ya vienen en el dict de `refugios` (H1 2026).
      - yoy_gmv, yoy_litros_cerveza: reutiliza _totales_ventana(rows_ventas,
        rows_productos, _anio_anterior(SEMESTRE_DESDE), _anio_anterior(SEMESTRE_HASTA),
        {local}) — función que ya existe (se usa en _construir_acciones) — y
        calcular_yoy() sobre el resultado.
      - sot_cerveza, delta_sot_pp: nueva función _sot_local_ventana(rows_productos,
        local, desde, hasta) que suma unid_cerveza/unid_alcoholicas filtrando por
        local + ventana (mismo criterio TIPO_CERVEZA/TIPOS_ALCOHOLICOS de config.py).
        Se llama una vez para H1 2026 y otra para H1 2025 (_anio_anterior), y se
        calcula sot con calcular_sot() y el delta con calcular_delta_pp() (nueva,
        ver abajo).
      - palancas: PALANCAS.get(local) del nuevo módulo palancas.py — None si no
        hay entrada (la card no muestra el bloque).
    Devuelve lista de dicts:
      {local, gmv, yoy_gmv, litros_cerveza, yoy_litros_cerveza,
       sot_cerveza, delta_sot_pp, palancas}
```

`construir_json()` agrega la clave nueva `"top_refugios"` al JSON de salida, sin tocar `"refugios"` (la tabla ordenable existente sigue igual, misma data que hoy).

### `calculos.py` — nueva función

```python
def calcular_delta_pp(valor_actual: float, valor_anterior: float) -> float:
    """Diferencia en puntos porcentuales entre dos ratios (ej. SOT), no % relativo."""
    return (valor_actual - valor_anterior) * 100
```

### `palancas.py` (nuevo módulo, mismo patrón que `acciones.py`)

```python
# Comentario cualitativo de negocio por Refugio para la vista "Top Refugios".
# Curado a mano por Darwin a partir del slide que compartió — los números que
# menciona cada texto se ajustan durante la implementación para coincidir con
# los valores reales recalculados (litros con corrección de pintas, no los del
# slide original). No se puede derivar de BigQuery.
PALANCAS = {
    "USHUAIA": "...",
    "MIS - PUERTO IGUAZU": "...",
    "CHALTEN": "...",
    "PUERTO MADERO": "...",
    "NEUQUEN": "...",
    "RESISTENCIA": "...",
}
```
(Nombres de `local` exactos verificados contra el JSON productivo actual — `MIS - PUERTO IGUAZU`, no `PUERTO IGUAZU`.)

---

## UI: `templates/patagonia_semestral.html`

- Nueva sección `<div class="top-refugios-grid">` dentro de `#tab-refugios`, antes de `.tabla-wrap`.
- Nueva función `renderTopRefugios()`, llamada junto a `renderRefugios()` en la cadena de `fetch('/data')`.
- Cada tarjeta: nombre del Refugio + 3 métricas (GMV, Litros hL, SOT), cada una con flecha ▲/▼ coloreada (reutiliza `claseDelta()` ya existente) y el delta correspondiente (% para GMV/Litros vía `fmtPct()` existente, pp para SOT vía nueva función `fmtPp()`). Bloque "Palancas" debajo de un separador, solo si `r.palancas` existe.
- Estilo: mismo `.kpi-card` (fondo `#1e272e`, borde izquierdo rosa) ya usado en Resumen — no se introduce paleta nueva.

---

## Testing

- `tests/test_calculos.py`: casos para `calcular_delta_pp` (positivo, negativo, cero).
- `tests/test_generar_patagonia_semestral.py`: extender el fixture existente o agregar uno con 2+ locales para verificar que `top_refugios` tiene la estructura esperada (local, gmv, yoy_gmv, litros_cerveza, yoy_litros_cerveza, sot_cerveza, delta_sot_pp, palancas) y que respeta el límite `n=6` (o el tamaño del fixture si es menor).

## Verificación end-to-end

1. `python -m pytest tests/ -v` — deben seguir pasando todos los tests más los nuevos.
2. Regenerar dato (`python -X utf8 generar_patagonia_semestral.py`) y confirmar en el JSON de GCS que `top_refugios` tiene 6 entradas con los mismos Refugios/GMV que hoy calcula el tablero.
3. Redeploy (cambia HTML) y verificar visualmente en browser: las 6 tarjetas se ven arriba de la tabla, con flechas y colores correctos, y el texto de Palancas aparece donde corresponde.
