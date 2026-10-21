@echo off
REM Auswertung TSST starten (Windows) – ruft start.ps1 auf
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
