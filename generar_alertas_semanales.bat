@echo off
cd /d "C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork"
set PYTHONIOENCODING=utf-8
python -X utf8 generar_alertas_semanales.py --gcs-bucket temple-bar-dashboard-cache --gcs-blob alertas_semanales.html >> logs\alertas_semanales.log 2>&1
