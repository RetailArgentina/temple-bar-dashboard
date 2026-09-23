@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

for /f %%i in ('powershell -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set HASTA=%%i
for /f %%i in ('powershell -Command "(Get-Date).AddDays(-60).ToString('yyyy-MM-dd')"') do set DESDE=%%i

py -X utf8 "%~dp0contabilium_sync_bq.py" --desde %DESDE% --hasta %HASTA% --modo incremental
