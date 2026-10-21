@echo off
rem Startet den DEBRA-Leser in der 32-Bit-PowerShell (Jet 2.0 braucht den 32-Bit-Treiber).
rem Aufruf: debra_mdb_export.bat [Quellordner] [Zielordner]
set PS32=%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe
if not exist "%PS32%" set PS32=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
set ARGS=
if not "%~1"=="" set ARGS=-Quelle "%~1"
if not "%~2"=="" set ARGS=%ARGS% -Ziel "%~2"
"%PS32%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0debra_mdb_export.ps1" %ARGS%
