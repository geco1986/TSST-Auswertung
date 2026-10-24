# Startet die laufende Auswertung TSST neu (Fenster von start.bat wird ersetzt).
#   -NurBeiAenderung  nur neu starten, wenn Programmdateien seit dem letzten Start
#                     geändert wurden (für den automatischen Aufruf nach jeder Änderung)
# Gibt eine Zeile JSON {"systemMessage": ...} aus (Claude-Code-Hook).
param([switch]$NurBeiAenderung)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$marke = Join-Path $root "data\.letzter-neustart"

function Melden($text) { @{ systemMessage = $text } | ConvertTo-Json -Compress; exit 0 }

# Programmdateien: Python-Code, Templates, CSS/JS
$dateien = @(Get-ChildItem $root -File -Filter *.py) +
           @(Get-ChildItem (Join-Path $root "debra") -Recurse -File -Include *.py) +
           @(Get-ChildItem (Join-Path $root "templates"), (Join-Path $root "static") -Recurse -File)
$neueste = ($dateien | Measure-Object LastWriteTime -Maximum).Maximum
if ($NurBeiAenderung -and (Test-Path $marke) -and $neueste -le (Get-Item $marke).LastWriteTime) {
    exit 0      # nichts geändert
}

# Laufende Instanz dieses Projekts beenden (cmd von start.bat, start.ps1, serve.py)
$pfad = [regex]::Escape($root)
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match $pfad -and $_.CommandLine -match "start\.bat|start\.ps1|serve\.py"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

# Neu starten in eigenem Fenster (wie Doppelklick auf start.bat)
Start-Process -FilePath (Join-Path $root "start.bat") -WorkingDirectory $root
New-Item -ItemType File -Force $marke | Out-Null

# Warten, bis die App antwortet
$port = if ($env:PORT) { $env:PORT } else { "5000" }
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-WebRequest "http://127.0.0.1:$port/login" -UseBasicParsing -TimeoutSec 2 | Out-Null
        Melden "Auswertung TSST neu gestartet (http://localhost:$port)."
    } catch { }
}
Melden "Auswertung TSST wurde neu gestartet, antwortet aber noch nicht auf Port $port - Fenster von start.bat prüfen."
