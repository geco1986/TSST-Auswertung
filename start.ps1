# Auswertung TSST starten (Windows, PowerShell) – venv + Umgebungsvariablen + waitress
# Optional: .\start.ps1 -Port 5001 -Seed 0
param(
    [string]$Port = "5000",
    [string]$Seed = "0"   # keine Demo-Daten: die Software kennt nur TSST und JTSST
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.13 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}
. .\.venv\Scripts\Activate.ps1

$dataDir = Join-Path $PSScriptRoot "data"
New-Item -ItemType Directory -Force $dataDir | Out-Null

# Session-Secret einmalig erzeugen und wiederverwenden (Logins bleiben über Neustarts gültig)
$secretFile = Join-Path $dataDir "secret.txt"
if (-not (Test-Path $secretFile)) {
    python -c "import secrets; print(secrets.token_urlsafe(48))" | Out-File -Encoding ascii $secretFile
}

$env:DEBRA_SECRET = (Get-Content $secretFile -Raw).Trim()
$env:DEBRA_DB     = Join-Path $dataDir "debra.sqlite3"
$env:DEBRA_SEED   = $Seed
$env:PORT         = $Port

python serve.py
