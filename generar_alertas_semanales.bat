@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
py -X utf8 generar_alertas_semanales.py --gcs-bucket temple-bar-dashboard-cache --gcs-blob alertas_semanales.html >> logs\alertas_semanales.log 2>&1
