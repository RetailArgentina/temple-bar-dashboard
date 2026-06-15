# Agente IA Retail — Diseño Técnico
**Fecha:** 2026-05-26
**Proyecto:** temple-bar-439715
**Estado:** Aprobado por Darwin

---

## Resumen

Agente de IA conversacional + informe automático semanal para análisis de ventas retail de Temple Bar Argentina. El agente responde preguntas en lenguaje natural vía WhatsApp y envía un informe automatizado cada lunes a las 8:00 hs.

---

## Casos de Uso

1. **Informe automático semanal:** Cada lunes 8:00 hs el agente envía por WhatsApp el cierre de la semana anterior con facturación, órdenes, ticket promedio, cumplimiento vs objetivo (real vs esperado al pace) y comparativa YoY. Resumen corto para todos; detalle completo solo para admins.

2. **Consulta conversacional ad hoc:** El usuario manda un mensaje de WhatsApp en lenguaje natural ("¿cómo viene Temple esta semana?") y el agente responde con datos en tiempo real desde BigQuery, formateado para WhatsApp.

---

## Arquitectura

```
WhatsApp (usuarios)
      ↓
   Twilio WhatsApp API
      ↓
Cloud Run — /whatsapp/webhook  (POST)
            /whatsapp/weekly-report  (POST, llamado por Cloud Scheduler)
      ↓
  Claude API — claude-sonnet-4-6 con tool use
      ↓  ↑
  Tools: query_retail / get_objectives / query_product
      ↓
  BigQuery (temple-bar-439715)
  Google Sheets (objetivos)

Cloud Scheduler → lunes 8:00 hs → /whatsapp/weekly-report
Cloud Firestore → historial de sesión por usuario
```

**Principio clave:** Se extiende `app.py` existente con 2 nuevos endpoints. No se crea un nuevo servicio Cloud Run.

---

## Componentes

### 1. Endpoints en app.py

**`POST /whatsapp/webhook`**
- Recibe mensajes de Twilio (campos: `From`, `Body`)
- Valida número en `agents_config.json`
- Carga historial de Firestore
- Llama a Claude API con tools
- Responde vía Twilio client
- Guarda historial actualizado en Firestore

**`POST /whatsapp/weekly-report`**
- Protegido con token secreto (Cloud Scheduler lo incluye en el header)
- Genera informe de la semana anterior (lunes a domingo)
- Claude produce resumen corto + detalle completo
- Envía resumen a todos los usuarios; detalle solo a admins

### 2. Claude API — Tool Use

**`query_retail(fecha_desde, fecha_hasta, agrupar_por)`**
- Consulta `temple-bar-439715.Corporativo.vw_Ventas_Corporativo_Base`
- `agrupar_por`: "marca" | "local" | "canal" | "dia"
- Retorna: facturación, órdenes, ticket promedio

**`get_objectives(marca, mes)`**
- Reutiliza `fetch_objetivos_data()` de `actualizar_retail.py`
- Retorna: obj_fac (millones), obj_ord, pace esperado al día actual

**`query_product(fecha_desde, fecha_hasta, marca)`**
- Reutiliza queries de `generar_preview_producto.py`
- Retorna: litros, mix de venta (%), top 10 productos

### 3. System Prompt del Agente

- Rol: analista de ventas senior, Temple Bar Argentina
- Idioma: español, tono directo y ejecutivo
- Formato: texto plano para WhatsApp, emojis para jerarquía visual (✅ ⚠️ 📊)
- Números en millones con M (ej: $600.5M)
- Sin tablas markdown (WhatsApp no las renderiza)
- Siempre incluir en respuestas de ventas:
  - Facturación + órdenes + ticket promedio
  - Cumplimiento real % vs objetivo mensual
  - Cumplimiento esperado % (pace = días transcurridos / días del mes)
  - Brecha en puntos porcentuales
- Si no puede responder con datos disponibles: lo dice explícitamente

### 4. Formato de Respuesta Estándar

```
📊 [Marca] — [período]
Real: $XM | X órdenes | ticket $X
──────────────────
Cumplimiento real: X% del objetivo mensual
Debería estar en: X% (día X de 31)
Brecha: +/-X puntos ✅/⚠️
──────────────────
Necesitás $XM más para estar en pace.
```

### 5. Control de Acceso — agents_config.json

```json
{
  "users": [
    {"phone": "+549XXXXXXXXXX", "name": "Darwin", "role": "admin"},
    {"phone": "+549XXXXXXXXXX", "name": "Nombre", "role": "viewer"}
  ],
  "scheduler_token": "SECRET_TOKEN"
}
```

**Roles:**
- `admin`: conversación libre, recibe informe completo
- `viewer`: recibe informe semanal, solo puede preguntar "¿cómo viene [marca]?" y "¿cuál fue el mejor local?"
- Número no registrado: respuesta de acceso denegado + contactar a Darwin

### 6. Gestión de Sesiones — Cloud Firestore

**Colección:** `/sessions/{phone_number}`

```json
{
  "messages": [{"role": "user/assistant", "content": "...", "timestamp": "..."}],
  "last_activity": "timestamp",
  "user_name": "Darwin",
  "role": "admin"
}
```

- Máximo **10 mensajes** por sesión (balance contexto/tokens)
- Expiración por **inactividad de 2 horas** — próximo mensaje inicia sesión nueva
- Firestore serverless, sin infraestructura adicional

### 7. Informe Automático — Cloud Scheduler

- **Schedule:** `0 8 * * 1` (lunes 8:00 hs, zona horaria America/Argentina/Buenos_Aires)
- **Target:** `POST /whatsapp/weekly-report` con header `X-Scheduler-Token`
- **Período analizado:** lunes anterior a domingo anterior
- **Envío:** resumen corto a todos → detalle completo a admins (mensaje separado)

---

## Formato Informe Semanal

**Resumen corto (todos):**
```
📊 Informe Semanal — [fecha inicio] al [fecha fin]
Red total: $XM | X órdenes
──────────────────
🔵 Patagonia: $XM | ticket $X
Cumpl: X% real vs X% esperado ✅/⚠️
🟣 Temple: $XM | ticket $X
Cumpl: X% real vs X% esperado ✅/⚠️
🟢 Feriado: $XM | ticket $X
Cumpl: X% real vs X% esperado ✅/⚠️
──────────────────
YoY: Patagonia +X% | Temple +X%
Respondé con "más info" para el detalle.
```

**Detalle completo (solo admins):**
- Todo lo anterior
- Top 5 locales por marca
- Desglose de facturación por día (lun-dom)
- Proyección al cierre del mes (si es mes en curso)

---

## Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Canal mensajería | WhatsApp vía Twilio |
| Servidor | Cloud Run (app.py existente) |
| Agente IA | Claude API `claude-sonnet-4-6` con tool use |
| Datos retail | BigQuery `vw_Ventas_Corporativo_Base` |
| Datos objetivos | Google Sheets vía Sheets API (código existente) |
| Datos producto | BigQuery (queries de generar_preview_producto.py) |
| Sesiones | Cloud Firestore |
| Cron | Cloud Scheduler |
| Config usuarios | `agents_config.json` (nuevo archivo en proyecto) |
| Secretos | Secret Manager (ya configurado) — agregar `twilio-auth-token`, `scheduler-token` |

---

## Archivos Nuevos / Modificados

| Archivo | Acción |
|---|---|
| `app.py` | Modificar — agregar 2 endpoints |
| `whatsapp_agent.py` | Nuevo — lógica del agente (Claude API, tools, session) |
| `whatsapp_tools.py` | Nuevo — implementación de las 3 tools (query_retail, get_objectives, query_product) |
| `weekly_report.py` | Nuevo — generación y envío del informe semanal |
| `agents_config.json` | Nuevo — whitelist y roles de usuarios |
| `requirements.txt` | Modificar — agregar twilio, anthropic, google-cloud-firestore |

---

## Consideraciones de Seguridad

- Token secreto para el endpoint de Cloud Scheduler (evita llamadas no autorizadas)
- Twilio valida firma de cada request entrante (validación de webhook)
- Números de teléfono en `agents_config.json` — no hardcodear en código
- Secrets en Secret Manager, no en variables de entorno en texto plano
- Viewers no pueden ejecutar queries arbitrarias — solo consultas predefinidas

---

## Costos Estimados (uso interno, ~5 usuarios)

| Servicio | Estimado mensual |
|---|---|
| Twilio WhatsApp | ~$2-5 USD |
| Claude API (claude-sonnet-4-6) | ~$3-8 USD |
| Cloud Firestore | < $1 USD |
| Cloud Scheduler | Gratis (< 3 jobs) |
| **Total** | **~$5-15 USD/mes** |
