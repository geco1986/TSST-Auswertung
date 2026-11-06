# =====================================================================
# TSST-Auswertung - Installations-SD-Karte (oder USB-Stick) fuer den Intel NUC erstellen
#
#   1. laedt Ubuntu Server 24.04 LTS (amd64) herunter und prueft die Pruefsumme
#   2. formatiert die Karte (FAT32) und kopiert den Installer darauf (UEFI-bootfaehig)
#   3. legt die automatische Installation (autoinstall) + TSST-Einrichtung dazu
#
# Beim Booten des NUC von dieser Karte wird Ubuntu OHNE Rueckfrage auf die interne
# Disk installiert (SSD vor eMMC), danach schaltet der NUC aus. Karte entfernen, einschalten:
# die TSST-Einrichtung laeuft automatisch.
#
# Start:  powershell -ExecutionPolicy Bypass -File nuc\sd-karte-erstellen.ps1
# =====================================================================
param(
    [int]$Disk = -1,
    [string]$UbuntuRelease = '24.04'
)
$ErrorActionPreference = 'Stop'
$Hier = Split-Path -Parent $PSCommandPath

# --- Administratorrechte ----------------------------------------------
$istAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $istAdmin) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-File', "`"$PSCommandPath`"")
    if ($Disk -ge 0) { $argList += @('-Disk', $Disk) }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit
}

function Titel($t) { Write-Host ''; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Frage($text, $default = '') {
    $p = if ($default) { "$text [$default]" } else { $text }
    $a = Read-Host $p
    if ([string]::IsNullOrWhiteSpace($a)) { return $default } else { return $a.Trim() }
}
function GeheimFrage($text, [int]$minLaenge = 0, [switch]$Bestaetigen) {
    while ($true) {
        $s1 = Read-Host $text -AsSecureString
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
        if ($p1.Length -lt $minLaenge) { Write-Host "  Mindestens $minLaenge Zeichen." -ForegroundColor Yellow; continue }
        if ($Bestaetigen) {
            $s2 = Read-Host '  nochmals eingeben' -AsSecureString
            $p2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
            if ($p1 -ne $p2) { Write-Host '  Nicht gleich - bitte wiederholen.' -ForegroundColor Yellow; continue }
        }
        return $p1
    }
}
function YamlStr($s) { "'" + $s.Replace("'", "''") + "'" }
function BashStr($s) { "'" + $s.Replace("'", "'\''") + "'" }
function SchreibeLF($pfad, $text) {
    $text = $text.Replace("`r`n", "`n")
    [IO.File]::WriteAllText($pfad, $text, (New-Object Text.UTF8Encoding($false)))
}

# --- Ziel waehlen -----------------------------------------------------
Titel 'SD-Karte / USB-Stick waehlen'
$kandidaten = @(Get-Disk | Where-Object {
        -not $_.IsSystem -and -not $_.IsBoot -and $_.Size -gt 7GB -and $_.Size -lt 520GB -and
        ($_.BusType -in 'USB', 'SD', 'MMC' -or $_.FriendlyName -match 'Card|Reader|SD')
    })
if ($kandidaten.Count -eq 0) { throw 'Keine SD-Karte / kein USB-Stick gefunden (mind. 8 GB).' }
$kandidaten | Format-Table Number, FriendlyName, BusType, PartitionStyle, @{n = 'GB'; e = { [math]::Round($_.Size / 1GB, 1) } } -AutoSize | Out-Host
if ($Disk -lt 0) {
    $Disk = if ($kandidaten.Count -eq 1) { [int](Frage 'Nummer der Karte' $kandidaten[0].Number) } else { [int](Frage 'Nummer der Karte') }
}
$ziel = $kandidaten | Where-Object Number -eq $Disk
if (-not $ziel) { throw "Disk $Disk ist keine erkannte SD-Karte / kein USB-Stick." }

# --- Angaben ----------------------------------------------------------
Titel 'Angaben fuer den NUC'
Write-Host 'Benutzer fuer SSH/Konsole:'
$nucUser = Frage '  Benutzername' 'tsst'
$nucPass = GeheimFrage '  Passwort' 8 -Bestaetigen
Write-Host ''
Write-Host 'WLAN fuer die Internetverbindung (z. B. Handy-Hotspot). Ein zweites WLAN ist optional (z. B. zu Hause fuer die Einrichtung).'
$wlan = @()
$ssid = Frage '  WLAN 1 - Name (SSID)'
if (-not $ssid) { throw 'Ein WLAN wird benoetigt.' }
$wlan += , @($ssid, (GeheimFrage '  WLAN 1 - Passwort' 8))
$ssid2 = Frage '  WLAN 2 - Name (leer = keines)'
if ($ssid2) { $wlan += , @($ssid2, (GeheimFrage '  WLAN 2 - Passwort' 8)) }
Write-Host ''
Write-Host 'Passwort fuer den Zugriff auf die App von ausserhalb des Kabelnetzes (WLAN, DuckDNS, Tailscale):'
$webUser = Frage '  Benutzername' 'tsst'
$webPass = GeheimFrage '  Passwort' 10 -Bestaetigen
Write-Host ''
Write-Host 'DuckDNS (optional, funktioniert nur mit Portweiterleitung 80/443 am WLAN-Router):'
$duckDomain = (Frage '  Subdomain (ohne .duckdns.org, leer = ohne)') -replace '\.duckdns\.org$', ''
$duckToken = if ($duckDomain) { Frage '  Token' } else { '' }
Write-Host ''
Write-Host 'Tailscale Funnel (optional, Zugriff von aussen auch ueber Handy-Hotspot - siehe NUC.md):'
$tsKey = Frage '  Auth-Key (tskey-auth-..., leer = ohne)'

# --- Ubuntu-ISO herunterladen + pruefen -------------------------------
Titel "Ubuntu Server $UbuntuRelease herunterladen"
$basis = "https://releases.ubuntu.com/$UbuntuRelease"
$cache = Join-Path $env:TEMP 'tsst-nuc'
New-Item -ItemType Directory -Force $cache | Out-Null
$sums = (& curl.exe -sL --fail "$basis/SHA256SUMS") -join "`n"
if ($LASTEXITCODE -ne 0 -or -not $sums) { throw "Kann $basis/SHA256SUMS nicht laden." }
$m = [regex]::Match($sums, '(?m)^([0-9a-f]{64}) \*?(ubuntu-[0-9.]+-live-server-amd64\.iso)$')
if (-not $m.Success) { throw 'Server-ISO nicht in SHA256SUMS gefunden.' }
$isoHash = $m.Groups[1].Value; $isoName = $m.Groups[2].Value
$iso = Join-Path $cache $isoName
if ((Test-Path $iso) -and ((Get-FileHash $iso -Algorithm SHA256).Hash -eq $isoHash)) {
    Write-Host "Verwende vorhandenen Download: $iso"
} else {
    Write-Host "Lade $isoName (ca. 3 GB) ..."
    & curl.exe -L --fail -o $iso "$basis/$isoName"
    if ($LASTEXITCODE -ne 0) { throw 'Download fehlgeschlagen.' }
    Write-Host 'Pruefe Pruefsumme ...'
    if ((Get-FileHash $iso -Algorithm SHA256).Hash -ne $isoHash) { throw 'Pruefsumme stimmt nicht - Download defekt.' }
}

# --- Karte formatieren ------------------------------------------------
Write-Host ''
Write-Host ("ACHTUNG: Alle Daten auf Disk {0} ({1}, {2} GB) werden geloescht!" -f $ziel.Number, $ziel.FriendlyName, [math]::Round($ziel.Size / 1GB, 1)) -ForegroundColor Red
if ((Read-Host 'Zum Fortfahren JA eingeben') -cne 'JA') { throw 'Abgebrochen.' }

Titel 'Karte formatieren (FAT32)'
if ($ziel.PartitionStyle -ne 'RAW') {
    Clear-Disk -Number $ziel.Number -RemoveData -RemoveOEM -Confirm:$false
}
Initialize-Disk -Number $ziel.Number -PartitionStyle MBR
$part = New-Partition -DiskNumber $ziel.Number -Size 8GB -IsActive -AssignDriveLetter
Start-Sleep -Seconds 2
$part | Format-Volume -FileSystem FAT32 -NewFileSystemLabel 'TSST-INST' -Confirm:$false | Out-Null
$part = Get-Partition -DiskNumber $ziel.Number -PartitionNumber $part.PartitionNumber
$B = "$($part.DriveLetter):\"
Write-Host "Karte: $B"

# --- Installer kopieren -----------------------------------------------
Titel 'Ubuntu-Installer auf die Karte kopieren'
$mount = Mount-DiskImage -ImagePath $iso -PassThru
try {
    $isoLw = ($mount | Get-Volume).DriveLetter
    & robocopy.exe "$($isoLw):\" $B /E /XJ /A-:R /R:1 /W:1 /NFL /NDL /NJH /NP | Out-Host
    if ($LASTEXITCODE -ge 8) { throw "Kopieren fehlgeschlagen (robocopy $LASTEXITCODE)." }
} finally {
    Dismount-DiskImage -ImagePath $iso | Out-Null
}
Get-ChildItem $B -Recurse -Force | ForEach-Object { if ($_.Attributes -band [IO.FileAttributes]::ReadOnly) { $_.Attributes = $_.Attributes -bxor [IO.FileAttributes]::ReadOnly } }

# --- GRUB: automatische Installation starten --------------------------
$grubCfg = Join-Path $B 'boot\grub\grub.cfg'
$g = [IO.File]::ReadAllText($grubCfg)
$g = [regex]::Replace($g, '(?m)^set timeout=\d+', 'set timeout=10')
$g = [regex]::Replace($g, '(?m)^(\s*linux\s+/casper/vmlinuz)(.*?)\s---', '$1$2 autoinstall ds=nocloud\;s=/cdrom/nocloud/ ---')
$g = $g.Replace('"Try or Install Ubuntu Server"', '"TSST: Ubuntu automatisch auf interne Disk installieren (LOESCHT sie!)"')
SchreibeLF $grubCfg $g

# --- autoinstall ------------------------------------------------------
Titel 'Automatische Installation einrichten'
$N = Join-Path $B 'nocloud'
New-Item -ItemType Directory -Force (Join-Path $N 'tsst') | Out-Null

$aps = ($wlan | ForEach-Object { "          $(YamlStr $_[0]):`n            password: $(YamlStr $_[1])" }) -join "`n"
$userData = @"
#cloud-config
# TSST-Auswertung - erzeugt von nuc/sd-karte-erstellen.ps1
autoinstall:
  version: 1
  interactive-sections: []
  locale: de_CH.UTF-8
  keyboard:
    layout: ch
  timezone: Europe/Zurich
  apt:
    geoip: false
    fallback: offline-install
  network:
    version: 2
    ethernets:
      lan:
        match:
          name: "en*"
        dhcp4: true
        optional: true
    wifis:
      wlan:
        match:
          name: "wl*"
        dhcp4: true
        optional: true
        regulatory-domain: CH
        access-points:
$aps
  storage:
    layout:
      name: direct
      match:
        path: __ZIELDISK__
  ssh:
    install-server: true
    allow-pw: true
  packages:
    - wpasupplicant
  updates: security
  early-commands:
    - bash /cdrom/nocloud/zieldisk.sh
  late-commands:
    - mkdir -p /target/opt/tsst-install /target/etc/tsst
    - cp /cdrom/nocloud/tsst/setup.sh /target/opt/tsst-install/setup.sh
    - install -m 600 /cdrom/nocloud/tsst/tsst.conf /target/etc/tsst/tsst.conf
    - chmod 700 /target/etc/tsst
    - cp /cdrom/nocloud/tsst/tsst-setup.service /target/etc/systemd/system/tsst-setup.service
    - curtin in-target --target=/target -- systemctl enable tsst-setup.service
  user-data:
    hostname: tsst
    ssh_pwauth: true
    users:
      - name: $(YamlStr $nucUser)
        groups: [adm, sudo]
        shell: /bin/bash
        lock_passwd: false
        plain_text_passwd: $(YamlStr $nucPass)
  shutdown: poweroff
"@
SchreibeLF (Join-Path $N 'user-data') $userData
SchreibeLF (Join-Path $N 'meta-data') "instance-id: tsst-installer-$(Get-Date -Format yyyyMMddHHmmss)`n"
SchreibeLF (Join-Path $N 'vendor-data') ''
SchreibeLF (Join-Path $N 'zieldisk.sh') ([IO.File]::ReadAllText((Join-Path $Hier 'zieldisk.sh')))
foreach ($f in 'setup.sh', 'tsst-setup.service') {
    SchreibeLF (Join-Path $N "tsst\$f") ([IO.File]::ReadAllText((Join-Path $Hier $f)))
}
$conf = @"
# TSST-Auswertung - Konfiguration (liegt nach der Installation unter /etc/tsst/tsst.conf)
WEB_BENUTZER=$(BashStr $webUser)
WEB_PASSWORT=$(BashStr $webPass)
LAN_IP='192.168.50.1'
DUCKDNS_DOMAIN=$(BashStr $duckDomain)
DUCKDNS_TOKEN=$(BashStr $duckToken)
TAILSCALE_AUTHKEY=$(BashStr $tsKey)
IMAGE='ghcr.io/geco1986/tsst-auswertung:latest'
"@
SchreibeLF (Join-Path $N 'tsst\tsst.conf') $conf

Titel 'Fertig'
Write-Host "Die Installationskarte ist bereit ($B). Laufwerk auswerfen."
Write-Host ''
Write-Host 'Am NUC:' -ForegroundColor Cyan
Write-Host '  1. Karte einstecken, einschalten, F10 druecken (Boot-Menue) und die SD-Karte waehlen.'
Write-Host '  2. Ubuntu installiert sich ohne Rueckfrage auf die interne Disk (ca. 15-30 Min.).'
Write-Host '     Danach schaltet der NUC AUS.'
Write-Host '  3. Karte ENTFERNEN (sonst wird beim naechsten Start neu installiert!) und einschalten.'
Write-Host '     Die TSST-Einrichtung laeuft automatisch (Internet ueber WLAN noetig, ca. 10 Min.).'
Write-Host '  4. Kabelnetz: http://192.168.50.1  bzw.  http://tsst.lan'
Write-Host ''
Write-Host 'ACHTUNG: Diese Karte loescht JEDEN Rechner, der von ihr bootet. Sie enthaelt Passwoerter - nach Gebrauch loeschen.' -ForegroundColor Yellow
