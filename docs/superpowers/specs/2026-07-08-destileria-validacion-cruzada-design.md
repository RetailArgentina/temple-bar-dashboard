# Spec: Capa de Validación Cruzada — Tablero Destilería (Fase 1)

**Fecha:** 2026-07-08  
**Estado:** Aprobado — listo para implementar  
**Archivo objetivo:** `generar_destileria_dashboard.py`

---

## Problema

El tablero destilería consume 5 fuentes de datos independientes. Diferentes vistas
pueden mostrar números inconsistentes sobre el mismo negocio (ej: litros generales
≠ suma por cluster, sell-in agregado ≠ suma por local). El usuario pierde confianza
en el dato y no puede tomar decisiones.

## Solución — Fase 1: Validación cruzada pre-publicación

Agregar una función `validate_cross_views()` que corre **después de generar el HTML
y antes de subir a GCS**. Si algún check falla, el upload se cancela y el tablero
anterior sigue publicado.

---

## Invariantes verificados (4 checks)

### Check 1 — Litros por marca == suma litros por cluster
**Fuente:** array `data` (ya en memoria, mismo origen)  
**Lógica:**
- Total litros por marca (Bosque, Feriado, Cerveza) calculado directo sobre `data`
- Suma litros por cluster para cada marca calculado sobre `data`
- Deben coincidir ±3%

**Detecta:** Que la vista general y la vista por cluster usen el mismo dataset.

### Check 2 — Sell-in agregado == suma sell-in por local
**Fuente:** `_sio` (semanal agregado) vs `_sio_lw` (por local × semana), ambos ya en memoria  
**Lógica:**
- Sumar `si` de todas las semanas en `_sio` → total agregado
- Sumar `si` de todos los locales × semanas en `_sio_lw` → total por local
- Deben coincidir ±3%
- Repetir para Patagonia: `_sio_pat` vs `_sio_pat_lw`
- Repetir para Feriado Temple: `_sio_fer` vs `_sio_fer_lw`
- Repetir para Feriado Patagonia: `_sio_fer_pat` vs `_sio_fer_pat_lw`

**Detecta:** Que el gráfico de línea semanal y el detalle por local cuenten lo mismo.

### Check 3 — Cobertura Contabilium: datos del mes actual presentes
**Fuente:** array `data`  
**Lógica:**
- Filtrar registros con `f >= '2026-07-01'` (fuente Contabilium)
- Si el mes actual es julio 2026 o posterior y no hay ningún registro → fallo
- Si hay menos de 10 registros de Contabilium en los últimos 30 días → warning (no fallo)

**Detecta:** Que el corte histórico/Contabilium no cree un hueco invisible donde
el mes actual aparece vacío.

### Check 4 — Ratio merch ≤ 15% de litros totales
**Fuente:** array `data`  
**Lógica:**
- `total_litros = sum(r["li"] for r in data)`
- `merch_litros = sum(r["li"] for r in data if r["fa"] == "merch")`
- `merch_litros / total_litros ≤ 0.15`

**Detecta:** Que `classify_familia()` no esté perdiendo productos reales en la
familia residual `merch` (que solo debería tener mercadería, no gin ni feriado).

---

## Tolerancias

| Situación | Comportamiento |
|-----------|----------------|
| Divergencia ≤ 3% | OK — ruido de redondeo aceptable |
| Divergencia > 3% | FALLO — abortar upload |
| Contabilium < 10 registros últimos 30 días | WARNING — loguear, no abortar |
| Merch > 15% litros | FALLO — abortar upload |

---

## Comportamiento en caso de fallo

```
Check falla
    ↓
1. Imprimir detalle en stderr: qué check, valores, diferencia %
2. NO llamar upload_to_gcs() → tablero anterior sigue publicado en GCS
3. Guardar HTML localmente igual → permite inspección manual
4. Retornar exit code 1 desde main()
5. actualizar_todo.py captura el fallo → escribe en dashboard_errors.log
```

El tablero viejo sigue visible. **Nunca se publica un tablero inconsistente.**

---

## Arquitectura

```python
def validate_cross_views(data, sio, sio_lw, sio_pat, sio_pat_lw,
                         sio_fer, sio_fer_lw, sio_fer_pat, sio_fer_pat_lw,
                         tolerance=0.03):
    """
    Valida consistencia cruzada entre vistas del tablero destilería.
    Retorna (ok: bool, report: list[str])
    No hace queries a BQ — solo usa datos ya en memoria.
    """
    errors = []
    warnings = []

    # Check 1: litros marca == suma clusters
    _check_cluster_totals(data, errors, tolerance)

    # Check 2: sell-in agregado == suma por local (x4 combinaciones)
    _check_sellinout_local_sum(sio, sio_lw, "Bosque Temple", errors, tolerance)
    _check_sellinout_local_sum(sio_pat, sio_pat_lw, "Bosque Patagonia", errors, tolerance)
    _check_sellinout_local_sum(sio_fer, sio_fer_lw, "Feriado Temple", errors, tolerance)
    _check_sellinout_local_sum(sio_fer_pat, sio_fer_pat_lw, "Feriado Patagonia", errors, tolerance)

    # Check 3: cobertura Contabilium
    _check_contabilium_coverage(data, warnings)

    # Check 4: ratio merch
    _check_merch_ratio(data, errors, max_ratio=0.15)

    ok = len(errors) == 0
    return ok, errors + warnings
```

### Integración en `main()`

```python
# Después de inyectar todos los placeholders, antes de upload_to_gcs():
ok, report = validate_cross_views(
    data,
    _sio, _sio_lw,
    _sio_pat, _sio_pat_lw,
    _sio_fer, _sio_fer_lw,
    _sio_fer_pat, _sio_fer_pat_lw,
)
if not ok:
    for line in report:
        print(f"  ✗ {line}", file=sys.stderr)
    print("ABORT: validación cruzada falló — tablero NO publicado.", file=sys.stderr)
    sys.exit(1)

# Solo llega acá si ok=True
if args.gcs_bucket:
    upload_to_gcs(...)
```

---

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `generar_destileria_dashboard.py` | Agregar `validate_cross_views()` y 4 helpers; integrar en `main()` antes de upload |

Sin cambios en template, pipeline, ni otros scripts.

---

## Fase 2 (futura — no en este spec)

Una vez que la Fase 1 esté corriendo y los logs muestren qué checks fallan con
qué frecuencia, evaluar consolidar las queries de sell-in/out en un único dataset
BQ pre-agregado para eliminar la divergencia de origen.
