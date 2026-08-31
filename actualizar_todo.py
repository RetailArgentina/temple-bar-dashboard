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
from datetime import datetime, timedelta

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
        "timeout":  120,   # 2 min máx — si cuelga, falla rápido y el pipeline sigue
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
    {
        "label": "Reseñas Google",
        "cmd":   [
            sys.executable, "-X", "utf8", "google_reviews_sync.py",
            "--gcs-bucket", "temple-bar-dashboard-cache",
            "--gcs-blob",   "resenas.html",
            "--output",     os.path.join(_OUT_DIR, "resenas.html"),
        ],
        "critical": False,
    },
    # ── Sync Contabilium → BQ (antes de generar destilería) ──────────────────
    {
        "label":    "Contabilium → BQ",
        "cmd":      [
            sys.executable, "-X", "utf8",
            os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "contabilium_sync_bq.py"),
            "--modo", "incremental",
            # Sin --desde/--hasta, el script defaultea a 2020-01-01 → recorre
            # 7 años de comprobantes en la API de Contabilium todos los días.
            # Acotamos a los últimos 30 días, suficiente para un sync incremental diario.
            "--desde", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            "--hasta", datetime.now().strftime("%Y-%m-%d"),
        ],
        "critical": False,
        "timeout":  300,   # 5 min máx
    },
    {
        "label": "Destilería",
        "cmd":   [
            sys.executable, "-X", "utf8", "generar_destileria_dashboard.py",
            "--gcs-bucket", "temple-bar-dashboard-cache",
            "--output", os.path.join(_OUT_DIR, "destileria_dashboard.html"),
        ],
    },
]

# Pausa puntual pedida por Darwin: no republicar el tablero de Destilería en la
# corrida de las 12:00 del 2026-08-25 (está en reunión y no quiere que cambie
# la visual). Autolimitado a esta fecha/franja horaria — no requiere revertir
# manualmente, deja de aplicar solo después de hoy.
_now = datetime.now()
if _now.date() == datetime(2026, 8, 25).date() and 11 <= _now.hour <= 13:
    SCRIPTS = [s for s in SCRIPTS if s["label"] != "Destilería"]


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
    """Escribe el error en un archivo separado para fácil detección.
    No usa Windows Forms (cuelga en Task Scheduler sin desktop)."""
    try:
        error_file = os.path.join(os.path.dirname(LOG_FILE), "dashboard_errors.log")
        with open(error_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts()}] ERROR: {label} (código {returncode})\n")
    except Exception:
        pass


def run_script(entry):
    """Corre un script como subproceso. Devuelve (ok, output_str)."""
    label = entry["label"]
    log("\u2500\u2500 " + label + " \u2500" + "\u2500" * 40)
    start = time.time()

    # CREATE_NEW_PROCESS_GROUP aísla al hijo del CTRL+C del padre en Windows
    # (evita que una señal externa mate el subprocess con código 3221225786)
    extra = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        extra["stdin"] = subprocess.DEVNULL

    timeout = entry.get("timeout", 600)
    try:
        result = subprocess.run(
            entry["cmd"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **extra,
        )
    except subprocess.TimeoutExpired:
        mins = timeout // 60
        log(f"  \u2717 {label} TIMEOUT (>{mins} min) \u2014 proceso terminado")
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
