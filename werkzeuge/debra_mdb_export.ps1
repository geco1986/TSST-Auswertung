# Leser für die alte DEBRA-Software (Access 2.0 / Jet 2.0, *.mdb)
#
# Exportiert jede Datenbank vollständig in einen Ordner:
#   <Ziel>\<DB>\_struktur.txt        Tabellen, Spalten, Typen, Anzahl Zeilen
#   <Ziel>\<DB>\_abfragen.sql        gespeicherte Abfragen (Views/Prozeduren) mit SQL
#   <Ziel>\<DB>\<Tabelle>.csv        Inhalt (UTF-8, ;-getrennt), auch Systemtabellen
#   <Ziel>\<DB>\_binaer\<Tabelle>\…  Binärfelder (Formulare/Berichte/Module) je Zeile
#
# Jet 2.0 lässt sich nur noch mit dem 32-Bit-Treiber "Microsoft.Jet.OLEDB.4.0" lesen,
# der in Windows enthalten ist. Darum MUSS dieses Skript in der 32-Bit-PowerShell laufen –
# am einfachsten über debra_mdb_export.bat. Die Datenbanken sind über die Arbeitsgruppe
# SYSTEM.MDA geschützt; Anmeldung wie in DEBRA als "Chef" ohne Passwort.
#
# Aufruf: debra_mdb_export.bat [Quellordner] [Zielordner]
#   Standard: Inputs\Alte Software  ->  Inputs\Alte Software\Export
param(
    [string]$Quelle = (Join-Path $PSScriptRoot "..\Inputs\Alte Software"),
    [string]$Ziel = "",
    [string]$Benutzer = "Chef"
)
$ErrorActionPreference = "Stop"
if ([Environment]::Is64BitProcess) {
    throw "Bitte in der 32-Bit-PowerShell starten (debra_mdb_export.bat) – der Jet-2.0-Treiber ist nur 32-Bit."
}
$Quelle = (Resolve-Path $Quelle).Path
if (-not $Ziel) { $Ziel = Join-Path $Quelle "Export" }
New-Item -ItemType Directory -Force $Ziel | Out-Null
$inv = [Globalization.CultureInfo]::InvariantCulture
$utf8 = New-Object Text.UTF8Encoding $true

$system = Get-ChildItem -Path $Quelle -Recurse -Filter "SYSTEM.MDA" | Select-Object -First 1
if (-not $system) { throw "SYSTEM.MDA (Arbeitsgruppe) nicht gefunden unter $Quelle" }

# Jet sperrt Dateien (.ldb) – mit Kopien in einem Arbeitsordner arbeiten, Originale bleiben unberührt.
$arbeit = Join-Path ([IO.Path]::GetTempPath()) ("debra_mdb_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $arbeit | Out-Null
Copy-Item $system.FullName (Join-Path $arbeit "SYSTEM.MDA")

function Wert([object]$v) {
    if ($v -eq $null -or $v -is [DBNull]) { return "" }
    if ($v -is [DateTime]) { return $v.ToString("yyyy-MM-dd HH:mm:ss", $inv) }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) { return ([double]$v).ToString("R", $inv) }
    if ($v -is [bool]) { if ($v) { return "1" } else { return "0" } }
    return [string]$v
}
function Csv([string]$s) {
    if ($s -match '[;"\r\n]') { return '"' + $s.Replace('"', '""') + '"' }
    return $s
}
function Dateiname([string]$s) { return ($s -replace '[\\/:*?"<>|]', '_') }

$dbs = Get-ChildItem -Path $Quelle -Recurse -Include *.mdb |
    Where-Object { $_.FullName -notlike "$Ziel*" } |
    Sort-Object Name -Unique
foreach ($db in $dbs) {
    $kopie = Join-Path $arbeit $db.Name
    Copy-Item $db.FullName $kopie -Force
    $aus = Join-Path $Ziel ([IO.Path]::GetFileNameWithoutExtension($db.Name))
    New-Item -ItemType Directory -Force $aus | Out-Null
    $cs = "Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$kopie;" +
          "Jet OLEDB:System database=$(Join-Path $arbeit 'SYSTEM.MDA');User ID=$Benutzer;Password=;"
    $con = New-Object System.Data.OleDb.OleDbConnection $cs
    $con.Open()
    Write-Host "== $($db.Name)"
    $struktur = New-Object Text.StringBuilder
    [void]$struktur.AppendLine("Datenbank: $($db.Name)  ($($db.Length) Bytes, $($db.LastWriteTime))")

    $tabellen = $con.GetSchema("Tables") | Where-Object { $_.TABLE_TYPE -in "TABLE", "SYSTEM TABLE", "ACCESS TABLE", "LINK" } |
        Sort-Object TABLE_TYPE, TABLE_NAME
    foreach ($t in $tabellen) {
        $name = $t.TABLE_NAME
        [void]$struktur.AppendLine("")
        [void]$struktur.AppendLine("[$($t.TABLE_TYPE)] $name")
        if ($t.TABLE_TYPE -eq "LINK") {
            # Verknüpfte Tabelle: Daten liegen in deb_data/deb_conf (dort exportiert)
            [void]$struktur.AppendLine("    -> verknüpft, Quelle: $($t.DESCRIPTION)")
            continue
        }
        try {
            $spalten = $con.GetOleDbSchemaTable([System.Data.OleDb.OleDbSchemaGuid]::Columns, @($null, $null, $name, $null))
            foreach ($s in ($spalten | Sort-Object ORDINAL_POSITION)) {
                $typ = [System.Data.OleDb.OleDbType]$s.DATA_TYPE
                $len = if ($s.CHARACTER_MAXIMUM_LENGTH -isnot [DBNull]) { "($($s.CHARACTER_MAXIMUM_LENGTH))" } else { "" }
                [void]$struktur.AppendLine("    $($s.COLUMN_NAME)  $typ$len")
            }
        } catch {
            [void]$struktur.AppendLine("    !! Spalten nicht lesbar: $($_.Exception.Message)")
        }
        try {
            $cmd = $con.CreateCommand()
            $cmd.CommandText = "SELECT * FROM [$name]"
            $r = $cmd.ExecuteReader()
        } catch {
            [void]$struktur.AppendLine("    !! nicht lesbar: $($_.Exception.Message)")
            continue
        }
        $sb = New-Object Text.StringBuilder
        $kopf = @(); for ($i = 0; $i -lt $r.FieldCount; $i++) { $kopf += (Csv $r.GetName($i)) }
        [void]$sb.AppendLine($kopf -join ";")
        $n = 0
        while ($r.Read()) {
            $n++
            $zeile = @()
            for ($i = 0; $i -lt $r.FieldCount; $i++) {
                $v = $r.GetValue($i)
                if ($v -is [byte[]]) {
                    $bin = Join-Path $aus ("_binaer\" + (Dateiname $name))
                    New-Item -ItemType Directory -Force $bin | Out-Null
                    $datei = "{0:D5}_{1}.bin" -f $n, (Dateiname $r.GetName($i))
                    [IO.File]::WriteAllBytes((Join-Path $bin $datei), $v)
                    $zeile += "<binär $($v.Length) B: $datei>"
                } else {
                    $zeile += (Csv (Wert $v))
                }
            }
            [void]$sb.AppendLine($zeile -join ";")
        }
        $r.Close()
        [IO.File]::WriteAllText((Join-Path $aus ((Dateiname $name) + ".csv")), $sb.ToString(), $utf8)
        [void]$struktur.AppendLine("    = $n Zeilen")
        Write-Host ("   {0,-30} {1,6} Zeilen" -f $name, $n)
    }

    # Gespeicherte Abfragen mit SQL
    $sql = New-Object Text.StringBuilder
    foreach ($v in $con.GetOleDbSchemaTable([System.Data.OleDb.OleDbSchemaGuid]::Views, $null)) {
        [void]$sql.AppendLine("-- Abfrage: $($v.TABLE_NAME)"); [void]$sql.AppendLine($v.VIEW_DEFINITION); [void]$sql.AppendLine("")
    }
    foreach ($p in $con.GetOleDbSchemaTable([System.Data.OleDb.OleDbSchemaGuid]::Procedures, $null)) {
        [void]$sql.AppendLine("-- Aktions-/Parameterabfrage: $($p.PROCEDURE_NAME)"); [void]$sql.AppendLine($p.PROCEDURE_DEFINITION); [void]$sql.AppendLine("")
    }
    [IO.File]::WriteAllText((Join-Path $aus "_abfragen.sql"), $sql.ToString(), $utf8)
    [IO.File]::WriteAllText((Join-Path $aus "_struktur.txt"), $struktur.ToString(), $utf8)
    $con.Close()
}
[System.Data.OleDb.OleDbConnection]::ReleaseObjectPool()
[GC]::Collect(); [GC]::WaitForPendingFinalizers()
Remove-Item -Recurse -Force $arbeit -ErrorAction SilentlyContinue
Write-Host "Export fertig: $Ziel"
