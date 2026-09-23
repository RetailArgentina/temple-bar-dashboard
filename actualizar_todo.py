#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
actualizar_todo.py
Orquestador unificado: actualiza Ventas + Producto y muestra notificación
de escritorio Windows si algo falla.
Uso: python -X utf8 actualizar_todo.py
"""

import os
import re
import subprocess
import sys
import tempfile
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
        "timeout":  300,   # 5 min máx — re-sync de 28 días = 2 requests con pausa de 22s
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
            os.path.join(SCRIPT_DIR, "contabilium_sync_bq.py"),
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
    # Verificación de gap Feriado vs Toteat: paso aparte y al final porque es lento
    # (pausas de rate limit) y solo escribe/borra el banner de alerta en GCS.
    {
        "label":    "Feriado gap check",
        "cmd":      [sys.executable, "-X", "utf8", "sync_feriado_toteat.py", "--solo-verificar"],
        "critical": False,
        "timeout":  300,
    },
]


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_SECRET_RE = re.compile(r"((?:xapitoken|api_?key|token|key)=)[^&\s)\"']+", re.IGNORECASE)


def mask_secrets(text):
    """Enmascara tokens/keys que aparezcan en URLs dentro de mensajes de error
    (ej. el 429 de Toteat imprime la URL completa con xapitoken)."""
    return _SECRET_RE.sub(r"\1***", text)


# Lock de instancia única: si la PC despierta y el Programador de tareas dispara
# dos corridas a la vez, ambas pisaban la subida a GCS (404 PATCH el 21/09/2026).
# Se usa un lock del sistema operativo sobre un archivo en la carpeta temporal
# (no en Drive): si el proceso muere, el SO lo libera solo y nunca queda trabado.
_LOCK_PATH = os.path.join(tempfile.gettempdir(), "temple_pipeline.lock")


def acquire_pipeline_lock():
    """Devuelve el file handle con el lock tomado, o None si ya hay otra corrida."""
    f = open(_LOCK_PATH, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def keep_awake(enable=True):
    """Pide a Windows no entrar en suspensión/espera moderna por inactividad
    mientras corre el pipeline. La PC entraba en 'Idle Timeout' 10-20 veces por
    día y las tareas corrían con CPU/red limitadas (timeouts del sync de Feriado).
    No mantiene la pantalla encendida. El flag es del hilo y se libera solo si el
    proceso muere. No-op fuera de Windows (Cloud Run)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS      = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if enable else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass  # nunca debe romper el pipeline


def log(msg):
    line = f"[{ts()}] {mask_secrets(str(msg))}"
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
    lock = acquire_pipeline_lock()
    if lock is None:
        log("\u26a0 Ya hay otra corrida del pipeline en curso \u2014 esta instancia se cancela para no pisar la subida a GCS.")
        return
    keep_awake(True)
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

    keep_awake(False)
    log("\u2713 Actualizaci\u00f3n completa OK")


if __name__ == "__main__":
    main()
