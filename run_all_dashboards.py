#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all_dashboards.py
Wrapper que actualiza todos los dashboards en secuencia:
  1. Retail (Temple + Patagonia + Feriado) → super_dashboard_temple.html
  2. Destilería                            → destileria_dashboard.html

Uso Cloud Run:
  python3 run_all_dashboards.py --gcs-bucket temple-bar-dashboard-cache
"""

import argparse
import subprocess
import sys


def run(script, extra_args):
    cmd = [sys.executable, script] + extra_args
    print(f"\n{'='*60}")
    print(f"  Ejecutando: {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nERROR: {script} terminó con código {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Actualizar todos los dashboards")
    parser.add_argument("--gcs-bucket", default="temple-bar-dashboard-cache",
                        help="Bucket GCS destino")
    args = parser.parse_args()

    # 1 — Retail
    run("actualizar_dashboard.py", [
        "--output",     "/tmp/super_dashboard_temple.html",
        "--gcs-bucket", args.gcs_bucket,
    ])

    # 2 — Destilería
    run("generar_destileria_dashboard.py", [
        "--output",     "/tmp/destileria_dashboard.html",
        "--gcs-bucket", args.gcs_bucket,
    ])

    print("\nTodos los dashboards actualizados correctamente.")


if __name__ == "__main__":
    main()
