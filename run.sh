#!/usr/bin/env bash
# DEBRA-Web starten (Linux/macOS)
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null || true
. .venv/bin/activate 2>/dev/null || true
pip install -q -r requirements.txt
python app.py
