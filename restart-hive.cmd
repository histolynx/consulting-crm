@echo off
rem Double-click to restart the HIVE background server (e.g. after updating HIVE's code).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-server.ps1" -Restart
echo.
echo Now press Ctrl+R in the HIVE window to reload it.
pause
