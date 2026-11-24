#!/usr/bin/env bash
# Auswertung TSST auf dem Raspberry Pi starten (wird vom Dienst tsst-auswertung aufgerufen).
# Pendant zu start.ps1: Daten liegen in data/, das Session-Secret in data/secret.txt.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -x .venv/bin/python ] || { python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt; }

mkdir -p data
[ -s data/secret.txt ] || { (umask 077; .venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))" > data/secret.txt); }

DEBRA_SECRET="$(tr -d '\r\n' < data/secret.txt)"
export DEBRA_SECRET
export DEBRA_DB="$PWD/data/debra.sqlite3"
export DEBRA_SEED=0
export DEBRA_URL_PREFIX="${DEBRA_URL_PREFIX:-/tsst}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-5000}"

exec .venv/bin/python serve.py
