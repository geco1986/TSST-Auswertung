@echo off
REM DEBRA-Web starten (Windows)
cd /d "%~dp0"
python -m venv .venv 2>nul
call .venv\Scripts\activate 2>nul
pip install -q -r requirements.txt
python app.py
pause
