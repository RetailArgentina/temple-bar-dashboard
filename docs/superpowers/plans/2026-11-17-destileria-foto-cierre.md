# Foto de cierre mensual — Tablero Destilería — Plan de implementación

> **Para agentes:** SUB-SKILL REQUERIDA: superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans. Los pasos usan checkbox (`- [ ]`).

**Objetivo:** Guardar el día 1 de cada mes una foto del mes que cerró y mostrar en el tablero qué cambió después (altas posteriores vs. bajas/modificaciones), sin congelar los datos vivos.

**Arquitectura:** El generador diario (`generar_destileria_dashboard.py`, corre en GitHub Actions vía `actualizar_todo.py`) ya trae las filas de Contabilium. Se agregan a esas filas `id_comprobante` y `numero`. Un módulo nuevo `destileria_cierres.py` (funciones puras + I/O GCS) arma la foto a nivel comprobante × familia, la guarda una sola vez por mes en GCS y calcula la diferencia contra los datos de hoy. El resultado se inyecta como `__CIERRES_JSON__` y una pestaña nueva "Cierres" lo muestra.

**Stack:** Python 3.11, google-cloud-bigquery, google-cloud-storage, pytest; HTML/JS vanilla en `templates/destileria.html`; tests JS con Node (patrón `run_dom_js` de `tests/test_finanzas_js.py`).

**Spec:** acordado en conversación con Darwin, 17/11/2026:
- Los datos vivos NO se congelan: ventas cargadas tarde con fecha del mes cerrado (ej. liquidación Travel Retail) se siguen sumando.
- La foto se toma el **día 1** del mes siguiente (es el número que se reporta en el cierre).
- La diferencia se muestra separada en **altas posteriores** (suman, legítimas) y **bajas/modificaciones** (comprobantes anulados, editados o convertidos — a revisar), con cliente y comprobante.

## Restricciones globales

- Bucket: `temple-bar-dashboard-cache`. Blob por mes: `destileria_cierres/AAAA-MM.json`.
- Una foto **nunca se sobrescribe**: subir con `if_generation_match=0`; si ya existe, no hacer nada.
- Primer mes con foto: `2026-10` (se toma tardía en el primer deploy, marcada `"tardia": true`). No hay fotos de meses anteriores.
- No tomar foto si los guardrails de integridad Contabilium fallaron o se corrió con `--force-publish` (nunca fotografiar un estado roto). Reintenta en la corrida siguiente.
- Marca de una familia = prefijo de `classify_familia`: `bosque_*` → `bosque`, `feriado_*` → `feriado`, `lata_*` y `cerveza_barril` → `cerveza`, `merch` → `merch`.
- Los litros/$/unidades de la foto deben ser **los mismos valores que entran a `data`** (después de `classify_familia`, `_MERCH_SIN_LITROS`, alias de cliente). La foto se arma desde la misma lista, no desde otra query.
- Textos de UI en español rioplatense. Números con formato `es-AR`.
- El array `data` que va al frontend (`__ROWS_JSON__`) **no cambia de forma** (no agregar campos: pesa en el HTML).
- Agregar `__CIERRES_JSON__` a `_CRITICAL_CHECKS`.

## Foco de revisión

1. COT convertida en factura dentro del mes cerrado (caso Paseo La Plaza): la COT aparece como baja y la factura como alta del mismo cliente → ambas filas deben llevar la etiqueta `"COT convertida"` para no leerse como venta nueva + anulación sin relación.
2. Corrida del día 1 que falla o no corre: el día 2 debe tomar la foto del mes anterior igual (`"tardia": true` con la fecha real).
3. Mes con foto pero sin cambios: la pestaña muestra "Sin cambios desde el cierre", no una tabla vacía.
4. Usuario con permiso solo para algunas marcas: la pestaña Cierres no muestra movimientos ni totales de marcas que no puede ver.
5. Diferencias de redondeo (litros con 3 decimales, $ redondeado a entero): no deben generar "modificaciones" falsas → umbrales `|Δli| > 0.01`, `|Δto| >= 1`, `Δce != 0`.

---

## Mapa de archivos

- Crear: `destileria_cierres.py` — lógica pura de foto/diferencia + carga/guardado en GCS.
- Crear: `tests/test_destileria_cierres.py` — tests Python del módulo.
- Crear: `tests/test_destileria_cierres_js.py` — test del render JS.
- Modificar: `generar_destileria_dashboard.py` — `fetch_rows_contabilium` (líneas 680-751) agrega `ic`/`nu`; `main()` (línea ~1122 en adelante) arma líneas, toma foto, inyecta JSON; `_CRITICAL_CHECKS` (línea ~1154).
- Modificar: `templates/destileria.html` — botón de pestaña (después de `data-tab="cerveza"`, línea ~357), vista `#view-cierres`, función `renderCierres`.

---

### Tarea 1: Módulo de foto y diferencia (lógica pura)

**Archivos:**
- Crear: `destileria_cierres.py`
- Test: `tests/test_destileria_cierres.py`

**Interfaces — produce:**
- `marca_de_familia(fa: str) -> str` — `"bosque" | "feriado" | "cerveza" | "merch"`.
- `armar_lineas(filas: list[dict]) -> list[dict]` — entrada: dicts con `f, nd, fa, ti, ce, li, to, ic, nu`. Agrupa por `(ic, fa)` sumando `ce, li, to`; conserva `f, nd, ti, nu` de la primera fila. Salida: dicts `{"k": f"{ic}|{fa}", "ic", "nu", "f", "nd", "ti", "fa", "ce", "li", "to"}` con `li` redondeado a 3 decimales y `to` a entero.
- `mes_a_fotografiar(hoy: date, existentes: set[str], primer_mes: str = "2026-10") -> str | None` — devuelve `"AAAA-MM"` del mes anterior a `hoy` si `>= primer_mes` y no está en `existentes`; si no, `None`.
- `filtrar_mes(lineas: list[dict], mes: str) -> list[dict]` — líneas con `f` que empieza con `mes`.
- `diferencia(foto: list[dict], hoy: list[dict]) -> list[dict]` — movimientos `{"tipo": "alta"|"baja"|"modificado", "etiqueta": "" | "COT convertida", "f", "nd", "nu", "ti", "fa", "marca", "dce", "dli", "dto"}`. Alta = clave solo en `hoy`; baja = solo en `foto` (deltas negativos); modificado = en ambas y supera algún umbral (Foco #5). Etiqueta `"COT convertida"` en una baja con `ti == "COT"` y en las altas con `ti != "COT"` del mismo `nd` (Foco #1). Orden: bajas y modificados primero, luego altas; dentro de cada grupo por `abs(dli)` descendente.
- `resumen(foto: list[dict], hoy: list[dict], movs: list[dict]) -> dict` — por marca: `{"cierre": {"li","to"}, "hoy": {"li","to"}, "altas": {"li","to"}, "bajas": {"li","to"}}`, donde `bajas` suma `baja` + `modificado`.

- [ ] **Paso 1: Escribir los tests que fallan**

```python
from datetime import date
from destileria_cierres import (marca_de_familia, armar_lineas, mes_a_fotografiar,
                                filtrar_mes, diferencia, resumen)

def L(ic, fa="bosque_nativo", nd="CLI", ti="FCB", f="2026-10-12", ce=1, li=0.5, to=1000, nu=None):
    return {"k": f"{ic}|{fa}", "ic": ic, "nu": nu or str(ic), "f": f, "nd": nd, "ti": ti, "fa": fa, "ce": ce, "li": li, "to": to}

def test_marca_de_familia():
    assert marca_de_familia("bosque_nativo_mini") == "bosque"
    assert marca_de_familia("feriado_barril_20") == "feriado"
    assert marca_de_familia("lata_wolf") == "cerveza"
    assert marca_de_familia("cerveza_barril") == "cerveza"
    assert marca_de_familia("merch") == "merch"

def test_armar_lineas_agrupa_por_comprobante_y_familia():
    filas = [dict(f="2026-10-12", nd="A", fa="bosque_nativo", ti="FCB", ce=2, li=1.0, to=500.4, ic=7, nu="1"),
             dict(f="2026-10-12", nd="A", fa="bosque_nativo", ti="FCB", ce=1, li=0.5, to=250.2, ic=7, nu="1"),
             dict(f="2026-10-12", nd="A", fa="feriado_rojo",  ti="FCB", ce=1, li=0.75, to=300, ic=7, nu="1")]
    out = {l["k"]: l for l in armar_lineas(filas)}
    assert out["7|bosque_nativo"]["ce"] == 3 and out["7|bosque_nativo"]["li"] == 1.5 and out["7|bosque_nativo"]["to"] == 751
    assert "7|feriado_rojo" in out

def test_mes_a_fotografiar():
    assert mes_a_fotografiar(date(2026, 12, 1), set()) == "2026-11"
    assert mes_a_fotografiar(date(2026, 12, 2), set()) == "2026-11"          # día 1 falló
    assert mes_a_fotografiar(date(2026, 12, 5), {"2026-11"}) is None
    assert mes_a_fotografiar(date(2026, 10, 3), set()) is None               # 2026-09 < primer_mes
    assert mes_a_fotografiar(date(2027, 1, 1), set()) == "2026-12"

def test_filtrar_mes():
    assert [l["ic"] for l in filtrar_mes([L(1, f="2026-10-31"), L(2, f="2026-11-01")], "2026-10")] == [1]

def test_diferencia_alta_baja_modificado_y_redondeo():
    foto = [L(1), L(2, li=1.0), L(3, li=2.0, to=4000)]
    hoy  = [L(1, li=0.505, to=1000.4), L(3, li=1.0, to=2000), L(4, nd="TRAVEL", li=10.0, to=9000)]
    movs = diferencia(foto, hoy)
    assert sorted(m["tipo"] for m in movs) == ["alta", "baja", "modificado"]   # ic=1 no cambia (redondeo)
    m = [x for x in movs if x["tipo"] == "modificado"][0]
    assert m["dli"] == -1.0 and m["dto"] == -2000
    b = [x for x in movs if x["tipo"] == "baja"][0]
    assert b["dli"] == -1.0 and b["marca"] == "bosque"
    assert movs[-1]["tipo"] == "alta"

def test_diferencia_cot_convertida():
    foto = [L(10, nd="PASEO LA PLAZA", ti="COT", ce=80, li=40.0, to=0)]
    hoy  = [L(11, nd="PASEO LA PLAZA", ti="FCB", ce=24, li=12.0, to=50000)]
    movs = diferencia(foto, hoy)
    assert {m["tipo"]: m["etiqueta"] for m in movs} == {"baja": "COT convertida", "alta": "COT convertida"}
    assert movs[0]["tipo"] == "baja"

def test_resumen_por_marca():
    foto = [L(1, li=2.0, to=100), L(2, fa="feriado_rojo", li=1.0, to=50)]
    hoy  = [L(1, li=2.0, to=100), L(3, li=5.0, to=300)]
    movs = diferencia(foto, hoy)
    r = resumen(foto, hoy, movs)
    assert r["bosque"]["cierre"] == {"li": 2.0, "to": 100} and r["bosque"]["hoy"] == {"li": 7.0, "to": 400}
    assert r["bosque"]["altas"]["li"] == 5.0
    assert r["feriado"]["bajas"] == {"li": -1.0, "to": -50}
```

- [ ] **Paso 2: Correr y verificar que fallan**

Correr: `python -m pytest tests/test_destileria_cierres.py -v`
Esperado: FAIL con `ModuleNotFoundError: destileria_cierres`.

- [ ] **Paso 3: Implementar las seis funciones en `destileria_cierres.py`** con las firmas de arriba. Sin dependencias externas en esta parte.

- [ ] **Paso 4: Correr y verificar que pasan**

Correr: `python -m pytest tests/test_destileria_cierres.py -v` → 7 passed.

- [ ] **Paso 5: Commit**

```bash
git add destileria_cierres.py tests/test_destileria_cierres.py
git commit -m "feat(destileria): lógica de foto de cierre y diferencia por comprobante"
```

---

### Tarea 2: Guardado/carga de fotos en GCS

**Archivos:**
- Modificar: `destileria_cierres.py`
- Test: `tests/test_destileria_cierres.py`

**Interfaces — produce:**
- `PREFIJO = "destileria_cierres/"`
- `listar_fotos(bucket) -> set[str]` — meses `"AAAA-MM"` con blob existente (`bucket.list_blobs(prefix=PREFIJO)`).
- `guardar_foto(bucket, mes: str, lineas: list[dict], tomada: datetime) -> bool` — JSON `{"mes", "tomada": tomada.isoformat(timespec="minutes"), "tardia": tomada.day != 1, "lineas": [...]}`; `upload_from_string(..., if_generation_match=0)`, `cache_control` después del upload (memoria: orden upload GCS). Devuelve `False` si ya existía (`google.api_core.exceptions.PreconditionFailed`), `True` si la creó.
- `cargar_fotos(bucket) -> list[dict]` — todas las fotos (dicts completos), ordenadas por `mes` descendente.
- `armar_cierres(fotos: list[dict], lineas_hoy: list[dict]) -> list[dict]` — por foto: `{"mes", "tomada", "tardia", "resumen": resumen(...), "movs": diferencia(...)}` usando `filtrar_mes(lineas_hoy, mes)`.

`bucket` es un `google.cloud.storage.Bucket`; en tests se pasa un falso.

- [ ] **Paso 1: Tests que fallan** — con un `FakeBucket`/`FakeBlob` en memoria (dict nombre→texto; `upload_from_string` con `if_generation_match=0` levanta `PreconditionFailed` si el nombre existe):
  - `test_guardar_foto_no_sobrescribe`: primera llamada `True`, segunda con otras líneas `False`, contenido sigue siendo el primero.
  - `test_guardar_foto_tardia`: `tomada=datetime(2026,11,17,9,0)` → `"tardia": True`; `datetime(2026,12,1,9,0)` → `False`.
  - `test_listar_y_cargar_fotos`: tras guardar `2026-10` y `2026-11`, `listar_fotos == {"2026-10","2026-11"}` y `cargar_fotos` devuelve `2026-11` primero.
  - `test_armar_cierres_solo_mira_el_mes_de_la_foto`: foto de `2026-10` con `L(1)`; `lineas_hoy = [L(1), L(9, f="2026-11-03")]` → `movs == []`.
- [ ] **Paso 2:** `python -m pytest tests/test_destileria_cierres.py -v` → los 4 nuevos FAIL.
- [ ] **Paso 3:** Implementar las cuatro funciones.
- [ ] **Paso 4:** `python -m pytest tests/test_destileria_cierres.py -v` → 11 passed.
- [ ] **Paso 5: Commit** — `git commit -m "feat(destileria): guardar y cargar fotos de cierre en GCS sin sobrescribir"`

---

### Tarea 3: Integración en el generador

**Archivos:**
- Modificar: `generar_destileria_dashboard.py`
- Modificar: `templates/destileria.html` (solo la línea `const CIERRES = __CIERRES_JSON__;` en el `<script>` de datos, junto a `__ROWS_JSON__`)

**Interfaces — consume:** Tareas 1 y 2. **Produce:** placeholder `__CIERRES_JSON__` reemplazado por `json.dumps(cierres, ensure_ascii=False, separators=(",", ":"))` (lista de `armar_cierres`), o `"[]"` si no hay bucket o falla.

- [ ] **Paso 1: `fetch_rows_contabilium`** — verificar con `bq show --schema temple-bar-439715:Destileria_Contabilium.comprobantes` que la columna se llama `numero` (el sync la escribe así en `contabilium_sync_bq.py:244`). En la query, `LEFT JOIN temple-bar-439715.Destileria_Contabilium.comprobantes co ON co.id_comprobante = ci.id_comprobante` y agregar `ci.id_comprobante AS ic`, `COALESCE(CAST(co.numero AS STRING), CAST(ci.id_comprobante AS STRING)) AS nu`. Pasar `ic`/`nu` al `SimpleNamespace`.
- [ ] **Paso 2: armar líneas** — en el loop que arma `data` (línea ~1123), para las filas que tienen atributo `ic` (vienen de `raw_cbl`), acumular en `filas_cbl` un dict con los mismos `f, nd (con alias), fa, ti, ce, li (ya con _MERCH_SIN_LITROS), to` más `ic, nu`. Luego `lineas = armar_lineas(filas_cbl)`. `data` queda igual.
- [ ] **Paso 3: tomar foto** — después del loop, solo si `args.gcs_bucket` y los guardrails pasaron sin `--force-publish` (guardar un booleano `integridad_ok` en el bloque de guardrails, líneas 1050-1091): `mes = mes_a_fotografiar(date.today(), listar_fotos(bucket))`; si hay mes, `guardar_foto(bucket, mes, filtrar_mes(lineas, mes), datetime.now())` y loguear `✓ Foto de cierre {mes} guardada (N líneas)`. Todo el bloque en `try/except Exception` que loguea WARN y sigue (la foto nunca debe tumbar la publicación).
- [ ] **Paso 4: inyectar** — `cierres = armar_cierres(cargar_fotos(bucket), lineas)` (mismo try/except → `[]`), reemplazar `__CIERRES_JSON__` junto a los demás `html.replace` (línea ~1405). Agregar `("__CIERRES_JSON__", "Placeholder fotos de cierre (__CIERRES_JSON__)")` a `_CRITICAL_CHECKS` y la línea `const CIERRES = __CIERRES_JSON__;` en la plantilla.
- [ ] **Paso 5: verificación local sin publicar** — `python -X utf8 generar_destileria_dashboard.py --output "$TEMP/dest_test.html"` termina OK y el HTML contiene `const CIERRES = []`. `python -m pytest tests/test_destileria_cierres.py -v` sigue verde.
- [ ] **Paso 6: Commit** — `git commit -m "feat(destileria): tomar foto de cierre el día 1 e inyectar diferencias"`

---

### Tarea 4: Pestaña "Cierres" en el tablero

**Archivos:**
- Modificar: `templates/destileria.html`
- Test: `tests/test_destileria_cierres_js.py`

**Interfaces — consume:** `CIERRES` (Tarea 3). **Produce:** `function renderCierres()` que escribe en `#cierres-body`.

Contenido de la vista `#view-cierres`:
- Selector de mes (`<select id="cierres-mes">`, una opción por foto, más reciente primero; texto `Octubre 2026` y, si `tardia`, ` · foto tomada el 17/11`).
- Tabla resumen por marca visible: columnas **Marca · Al cierre (L / $) · Altas posteriores · Bajas y modificaciones · Hoy**. Altas en verde, bajas en rojo.
- Tabla de movimientos: **Tipo · Etiqueta · Fecha · Cliente · Comprobante (ti + nu) · Marca · Δ Litros · Δ $**, con filtro por marca.
- Sin fotos: "Todavía no hay fotos de cierre. La primera se toma el día 1 del mes próximo." Con foto y sin movimientos: "Sin cambios desde el cierre."
- Nota fija arriba: "Los datos del tablero siguen vivos: las ventas cargadas después del cierre con fecha del mes (por ejemplo la liquidación de Travel Retail) se suman. Esta pestaña muestra qué cambió respecto de lo que se reportó el día 1."
- Permisos (Foco #4): mostrar solo marcas que el usuario puede ver, con el mismo mecanismo que oculta los `tab-group[data-brand]` (ver la función alrededor de `templates/destileria.html:1862` y `__PERMISSIONS_INJECT__`). `cerveza` y `merch` siguen la misma regla que la pestaña Cerveza / General en ese mecanismo.

- [ ] **Paso 1: Test que falla** — en `tests/test_destileria_cierres_js.py`, reutilizar el helper `run_dom_js` de `tests/test_finanzas_js.py` apuntándolo a `templates/destileria.html`, extrayendo `renderCierres` y los helpers que use. Casos:
  - `test_sin_fotos`: `CIERRES = []` → `#cierres-body.innerHTML` contiene `Todavía no hay fotos de cierre`.
  - `test_sin_cambios`: una foto con `movs: []` → contiene `Sin cambios desde el cierre`.
  - `test_cot_convertida_y_marca_oculta`: foto con una baja `COT convertida` de bosque y una alta de feriado (cliente `CLIENTE FERIADO`); marcas permitidas solo `bosque` → contiene `COT convertida` y no contiene `CLIENTE FERIADO`.
- [ ] **Paso 2:** `python -m pytest tests/test_destileria_cierres_js.py -v` → FAIL.
- [ ] **Paso 3:** Agregar botón `<button class="tab-btn" data-tab="cierres" onclick="switchTab('cierres')">Cierres</button>` después del de Cerveza, la vista y `renderCierres` (llamarla desde `switchTab` cuando `tab === 'cierres'`). Formato con `toLocaleString('es-AR')`.
- [ ] **Paso 4:** `python -m pytest tests/test_destileria_cierres_js.py tests/test_destileria_cierres.py -v` → todo verde. Regenerar local (Paso 5 de Tarea 3) y abrir el HTML: la pestaña muestra "Todavía no hay fotos de cierre".
- [ ] **Paso 5: Commit** — `git commit -m "feat(destileria): pestaña Cierres con altas y bajas posteriores al cierre"`

---

### Tarea 5: Puesta en producción y foto de octubre

- [ ] **Paso 1:** Darwin hace merge a `main` y push (memoria: merge/push lo corre Darwin con `!`).
- [ ] **Paso 2:** Disparar el pipeline (`gh workflow run actualizar-pipeline.yml`) y esperarlo en background (~20 min). En el log del paso Destilería buscar `✓ Foto de cierre 2026-10 guardada`.
- [ ] **Paso 3: Verificar el blob** — descargar `gs://temple-bar-dashboard-cache/destileria_cierres/2026-10.json` (Python + SA) y confirmar `"tardia": true` y que la suma de `li` de familias `bosque_*` da **1.162,3 L** (el valor de octubre que muestra hoy Bosque → General).
- [ ] **Paso 4:** Abrir el tablero con cache-bust → pestaña Cierres → Octubre 2026 → "Sin cambios desde el cierre".
