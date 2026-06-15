# Diseño: Orquestador unificado de actualización de tableros

**Fecha:** 2026-05-06
**Estado:** Aprobado

## Problema

Actualmente actualizar ambos tableros requiere correr dos comandos distintos manualmente. La tarea programada de Windows solo cubre el tablero de Ventas. No hay notificación si algo falla.

## Solución

Crear `actualizar_todo.py` como único punto de entrada que orquesta ambas actualizaciones, escribe log unificado y manda mail en caso de error.

## Arquitectura

```
actualizar_dashboard.bat
    └── python -X utf8 actualizar_todo.py
            ├── 1. actualizar_retail.py          (Ventas → super_dashboard_temple.html)
            └── 2. generar_preview_producto.py   (Producto → producto.html en GCS)
```

La tarea programada de Windows ya apunta al `.bat` — no se modifica.

## Componentes

### `actualizar_todo.py` (nuevo)
- Orquesta ambos scripts como subprocesos en secuencia
- Captura stdout/stderr de cada uno
- Escribe todo en `logs/dashboard_update.log` con timestamps
- Si cualquier script falla (returncode != 0): envía mail de error y termina con código 1
- Si ambos OK: registra éxito en log

### `email_config.json` (nuevo)
Archivo de configuración de credenciales SMTP. No se commitea a git.
```json
{
  "smtp_user": "darwin.salinas@temple.com.ar",
  "smtp_password": "<contraseña de aplicación Google>",
  "to": "darwin.salinas@temple.com.ar"
}
```

### `actualizar_dashboard.bat` (modificado)
Reemplazar el contenido actual por una sola llamada al orquestador:
```bat
@echo off
cd /d "C:\Users\Darwin Salinas\Claude_Cowork"
python -X utf8 actualizar_todo.py >> logs\dashboard_update.log 2>&1
```

## Email de error

- **Transport:** Gmail SMTP (`smtp.gmail.com:587`, STARTTLS)
- **Credenciales:** `email_config.json` (contraseña de aplicación Google de 16 caracteres)
- **Destinatario:** `darwin.salinas@temple.com.ar`
- **Asunto:** `⚠ Dashboard Temple — Error en actualización [YYYY-MM-DD HH:MM]`
- **Cuerpo:** script que falló, fecha/hora, código de salida, últimas 50 líneas del output

## Formato de log

```
[2026-05-06 08:30:01] ▶ Iniciando actualización completa
[2026-05-06 08:30:01] ── Ventas ──────────────────────────
[2026-05-06 08:30:35]   ✓ Ventas OK (34s)
[2026-05-06 08:30:35] ── Producto ────────────────────────
[2026-05-06 08:32:41]   ✓ Producto OK (2m 6s)
[2026-05-06 08:32:41] ✓ Actualización completa OK
```

En caso de error:
```
[2026-05-06 08:30:35]   ✗ Ventas FALLÓ (código 1)
[2026-05-06 08:30:35]   → Mail enviado a darwin.salinas@temple.com.ar
```

## Secuencia de implementación

1. Crear `actualizar_todo.py`
2. Crear `email_config.json` con placeholder
3. Agregar `email_config.json` a `.gitignore` (si existe)
4. Reemplazar contenido de `actualizar_dashboard.bat`
5. Probar ejecución manual
6. Guiar al usuario para generar contraseña de aplicación Google

## Archivos no modificados

- `actualizar_retail.py` — sin cambios
- `generar_preview_producto.py` — sin cambios
- Tarea programada de Windows — sin cambios
