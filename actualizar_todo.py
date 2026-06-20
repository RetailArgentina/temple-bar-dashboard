#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
actualizar_todo.py
Orquestador unificado: actualiza Ventas + Producto y muestra notificación
de escritorio Windows si algo falla.
Uso: python -X utf8 actualizar_todo.py
"""

import os
import subprocess
import sys
import time
from datetime import datetime

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LOG_FILE    = os.path.join(SCRIPT_DIR, "logs", "dashboard_update.log")

# En Cloud Run (Linux) escribimos el HTML temporal en /tmp para evitar
# problemas de permisos en el directorio de la app.
_OUT_DIR = "/tmp" if sys.platform != "win32" else SCRIPT_DIR

SCRIPTS = [
    # ── Syncs de datos (primero, para que los dashboards lean datos frescos) ──
    # critical=False: si el sync falla, los dashboards igual se actualizan con datos anteriores
    {
        "label":    "Feriado Toteat → BQ",
        "cmd":      [sys.executable, "-X", "utf8", "sync_feriado_toteat.py"],
        "critical": False,
    },
    {
        "label":    "Feriado Catálogo → BQ",
        "cmd":      [sys.executable, "-X", "utf8", "sync_catalogo_feriado.py"],
        "critical": False,
    },
    # ── Dashboards (después del sync) ────────────────────────────────────────
    {
        "label": "Ventas",
        "cmd":   [
            sys.executable, "-X", "utf8", "actualizar_retail.py",
            "--gcs-bucket", "temple-bar-dashboard-cache",
            "--output", os.path.join(_OUT_DIR, "super_dashboard_temple.html"),
        ],
    },
    {
        "label": "Producto",
        "cmd":   [
            sys.executable, "-X", "utf8", "generar_preview_producto.py",
            "--gcs-bucket", "temple-bar-dashboard-cache",
            "--gcs-blob",   "producto.html",
            "--output",     os.path.join(_OUT_DIR, "preview_producto.html"),
        ],
    },
    # Destilería: actualización MANUAL únicamente — no corre en el pipeline automático.
    # Para actualizar: correr generar_destileria_dashboard.py directamente.
]


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except PermissionError:
        pass  # El log está bloqueado por otro proceso; continúa igual


def notify_error(label, returncode):
    """Muestra una notificación de escritorio Windows via PowerShell.
    En Linux/Cloud Run no hace nada (no hay escritorio)."""
    if sys.platform != "win32":
        return
    title   = "Dashboard Temple \u2014 Error"
    message = f"Fall\u00f3: {label} (c\u00f3digo {returncode}). Revis\u00e1 logs\\dashboard_update.log"
    script = (
        "$ErrorActionPreference = 'SilentlyContinue';"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$b = New-Object System.Windows.Forms.NotifyIcon;"
        "$b.Icon = [System.Drawing.SystemIcons]::Warning;"
        "$b.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Warning;"
        f"$b.BalloonTipTitle = '{title}';"
        f"$b.BalloonTipText = '{message}';"
        "$b.Visible = $true;"
        "$b.ShowBalloonTip(15000);"
        "Start-Sleep -Seconds 5;"
        "$b.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=20,
        )
    except Exception as e:
        log(f"  \u26a0 No se pudo mostrar notificaci\u00f3n: {e}")


def run_script(entry):
    """Corre un script como subproceso. Devuelve (ok, output_str)."""
    label = entry["label"]
    log("\u2500\u2500 " + label + " \u2500" + "\u2500" * 40)
    start = time.time()

    try:
        result = subprocess.run(
            entry["cmd"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        log(f"  \u2717 {label} TIMEOUT (>10 min) \u2014 proceso terminado")
        return False

    elapsed = int(time.time() - start)
    combined = result.stdout + result.stderr
    for line in combined.splitlines():
        log(f"  {line}")

    if result.returncode == 0:
        mins, secs = divmod(elapsed, 60)
        dur = f"{mins}m {secs}s" if mins else f"{secs}s"
        log(f"  \u2713 {label} OK ({dur})")
        return True
    else:
        log(f"  \u2717 {label} FALL\u00d3 (c\u00f3digo {result.returncode})")
        return False


def main():
    log("\u25b6 Iniciando actualizaci\u00f3n completa")

    for entry in SCRIPTS:
        ok = run_script(entry)
        if not ok:
            notify_error(entry["label"], 1)
            log(f"  \u2192 Notificaci\u00f3n de escritorio enviada")
            if entry.get("critical", True):
                log("\u2717 Actualizaci\u00f3n interrumpida por error cr\u00edtico.")
                sys.exit(1)
            else:
                log(f"  \u26a0 Script no cr\u00edtico fall\u00f3 — continuando pipeline.")

    log("\u2713 Actualizaci\u00f3n completa OK")


if __name__ == "__main__":
    main()
