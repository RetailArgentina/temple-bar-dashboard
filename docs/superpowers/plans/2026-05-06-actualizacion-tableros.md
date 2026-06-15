# Orquestador unificado de actualización de tableros — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un solo comando (`python -X utf8 actualizar_todo.py`) actualiza Ventas y Producto, escribe log unificado y manda mail a `darwin.salinas@temple.com.ar` si algo falla.

**Architecture:** `actualizar_todo.py` corre `actualizar_retail.py` y `generar_preview_producto.py` como subprocesos en secuencia, capturando su output. En caso de error llama a `send_error_mail()` que usa Gmail SMTP. `actualizar_dashboard.bat` queda reducido a una sola línea que invoca este orquestador.

**Tech Stack:** Python 3.x · smtplib (stdlib) · subprocess (stdlib) · Gmail SMTP (smtp.gmail.com:587 / STARTTLS)

---

## Archivos

| Acción | Archivo |
|--------|---------|
| Crear  | `actualizar_todo.py` |
| Crear  | `email_config.json` |
| Modificar | `actualizar_dashboard.bat` |

`email_config.json` ya queda cubierto por la regla `*.json` del `.gitignore` existente — no hay que tocarlo.

---

### Task 1: Crear `email_config.json` con placeholder

**Files:**
- Create: `C:\Users\Darwin Salinas\Claude_Cowork\email_config.json`

- [ ] **Step 1: Crear el archivo de configuración**

Crear `email_config.json` en la raíz del proyecto con este contenido exacto:

```json
{
  "smtp_user": "darwin.salinas@temple.com.ar",
  "smtp_password": "COMPLETAR_CON_CONTRASEÑA_DE_APP",
  "to": "darwin.salinas@temple.com.ar"
}
```

- [ ] **Step 2: Verificar que .gitignore lo excluye**

Correr:
```bash
git check-ignore -v email_config.json
```
Resultado esperado: `.gitignore:22:*.json    email_config.json`

Si no aparece, agregar manualmente `email_config.json` al `.gitignore`.

---

### Task 2: Crear `actualizar_todo.py`

**Files:**
- Create: `C:\Users\Darwin Salinas\Claude_Cowork\actualizar_todo.py`

- [ ] **Step 1: Escribir el script orquestador completo**

Crear `actualizar_todo.py` con este contenido:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
actualizar_todo.py
Orquestador unificado: actualiza Ventas + Producto y manda mail si algo falla.
Uso: python -X utf8 actualizar_todo.py
"""

import json
import os
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_FILE     = os.path.join(SCRIPT_DIR, "logs", "dashboard_update.log")
CONFIG_FILE  = os.path.join(SCRIPT_DIR, "email_config.json")

SCRIPTS = [
    {
        "label":  "Ventas",
        "cmd":    [sys.executable, "-X", "utf8", "actualizar_retail.py"],
    },
    {
        "label":  "Producto",
        "cmd":    [
            sys.executable, "generar_preview_producto.py",
            "--gcs-bucket", "temple-bar-dashboard-cache",
            "--gcs-blob",   "producto.html",
        ],
    },
]


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
        f.write(line + "\n")


def load_email_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    if "COMPLETAR" in cfg.get("smtp_password", ""):
        return None
    return cfg


def send_error_mail(cfg, label, returncode, output):
    tail = "\n".join(output.splitlines()[-50:])
    body = (
        f"Script:         {label}\n"
        f"Fecha/hora:     {ts()}\n"
        f"Código salida:  {returncode}\n\n"
        f"--- Últimas 50 líneas del output ---\n{tail}"
    )
    msg = MIMEMultipart()
    msg["Subject"] = f"\u26a0 Dashboard Temple \u2014 Error en actualizaci\u00f3n [{ts()[:16]}]"
    msg["From"]    = cfg["smtp_user"]
    msg["To"]      = cfg["to"]
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.send_message(msg)


def run_script(entry):
    """Corre un script como subproceso. Devuelve (ok, output_str)."""
    label = entry["label"]
    log(f"\u2500\u2500 {label} \u2500" + "\u2500" * 40)
    start = time.time()

    result = subprocess.run(
        entry["cmd"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    elapsed = int(time.time() - start)
    combined = result.stdout + result.stderr

    for line in combined.splitlines():
        log(f"  {line}")

    if result.returncode == 0:
        mins, secs = divmod(elapsed, 60)
        dur = f"{mins}m {secs}s" if mins else f"{secs}s"
        log(f"  \u2713 {label} OK ({dur})")
        return True, combined
    else:
        log(f"  \u2717 {label} FALL\u00d3 (c\u00f3digo {result.returncode})")
        return False, combined


def main():
    log("\u25b6 Iniciando actualizaci\u00f3n completa")
    email_cfg = load_email_config()
    if not email_cfg:
        log("  AVISO: email_config.json no configurado \u2014 notificaciones desactivadas")

    for entry in SCRIPTS:
        ok, output = run_script(entry)
        if not ok:
            if email_cfg:
                try:
                    send_error_mail(email_cfg, entry["label"], 1, output)
                    log(f"  \u2192 Mail enviado a {email_cfg['to']}")
                except Exception as e:
                    log(f"  \u26a0 No se pudo enviar mail: {e}")
            log("\u2717 Actualizaci\u00f3n interrumpida por error.")
            sys.exit(1)

    log("\u2713 Actualizaci\u00f3n completa OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificar que el archivo se creó**

```bash
python -c "import ast; ast.parse(open('actualizar_todo.py').read()); print('Sintaxis OK')"
```
Resultado esperado: `Sintaxis OK`

- [ ] **Step 3: Commit**

```bash
git add actualizar_todo.py
git commit -m "feat: orquestador unificado actualizar_todo.py con mail de error"
```

---

### Task 3: Actualizar `actualizar_dashboard.bat`

**Files:**
- Modify: `C:\Users\Darwin Salinas\Claude_Cowork\actualizar_dashboard.bat`

- [ ] **Step 1: Reemplazar contenido del bat**

Reemplazar el contenido completo de `actualizar_dashboard.bat` con:

```bat
@echo off
cd /d "C:\Users\Darwin Salinas\Claude_Cowork"
python -X utf8 actualizar_todo.py >> logs\dashboard_update.log 2>&1
```

- [ ] **Step 2: Commit**

```bash
git add actualizar_dashboard.bat
git commit -m "chore: bat actualiza ambos tableros via actualizar_todo.py"
```

---

### Task 4: Configurar contraseña de aplicación Google y probar mail

**Files:** solo `email_config.json` (no se commitea)

- [ ] **Step 1: Generar contraseña de aplicación en Google**

1. Ir a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Seleccionar app: **Otra (nombre personalizado)** → escribir `Dashboard Temple`
3. Copiar la clave de 16 caracteres generada (formato: `xxxx xxxx xxxx xxxx`)

- [ ] **Step 2: Completar `email_config.json`**

Editar `email_config.json` y reemplazar `COMPLETAR_CON_CONTRASEÑA_DE_APP` con la clave de 16 caracteres (con o sin espacios, ambos funcionan):

```json
{
  "smtp_user": "darwin.salinas@temple.com.ar",
  "smtp_password": "xxxx xxxx xxxx xxxx",
  "to": "darwin.salinas@temple.com.ar"
}
```

- [ ] **Step 3: Probar el envío de mail directamente**

```bash
python -c "
import json, smtplib
from email.mime.text import MIMEText
cfg = json.load(open('email_config.json'))
msg = MIMEText('Test de configuración OK', 'plain', 'utf-8')
msg['Subject'] = 'Dashboard Temple — Test mail'
msg['From'] = cfg['smtp_user']
msg['To'] = cfg['to']
with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as s:
    s.starttls()
    s.login(cfg['smtp_user'], cfg['smtp_password'])
    s.send_message(msg)
print('Mail enviado OK')
"
```
Resultado esperado: `Mail enviado OK` + mail recibido en `darwin.salinas@temple.com.ar`

---

### Task 5: Prueba de integración completa

- [ ] **Step 1: Correr el orquestador manualmente**

```bash
python -X utf8 actualizar_todo.py
```

Resultado esperado (aprox 3 min):
```
[2026-05-06 HH:MM:SS] ▶ Iniciando actualización completa
[2026-05-06 HH:MM:SS] ── Ventas ─────...
...
[2026-05-06 HH:MM:SS]   ✓ Ventas OK (34s)
[2026-05-06 HH:MM:SS] ── Producto ───...
...
[2026-05-06 HH:MM:SS]   ✓ Producto OK (2m 6s)
[2026-05-06 HH:MM:SS] ✓ Actualización completa OK
```

- [ ] **Step 2: Verificar log**

```bash
tail -20 logs/dashboard_update.log
```
Las últimas líneas deben mostrar `✓ Actualización completa OK`.

- [ ] **Step 3: Verificar tableros en producción**

Abrir en el navegador y confirmar que ambos tienen datos del día de hoy:
- Ventas: `https://storage.googleapis.com/temple-bar-dashboard-cache/super_dashboard_temple.html`
- Producto: `https://storage.googleapis.com/temple-bar-dashboard-cache/producto.html`
