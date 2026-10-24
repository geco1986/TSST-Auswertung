# TrueNAS SCALE – Installation

App-Image: **`ghcr.io/geco1986/tsst-auswertung:latest`**
(wird vom GitHub-Workflow bei jedem Push auf `main` automatisch gebaut und veröffentlicht).

Die App kennt drei Anlässe – **TSST**, **JTSST** und **JET** – und drei Rollen:
Eingeber, Chef (nur aktiver Anlass) und **Superuser** (aktiver Anlass, Importe,
JET-Wertungsformeln; Passwort wird beim ersten Superuser-Login festgelegt).

## 0. Einmalig: Image in GHCR veröffentlichen
1. Repo nach `https://github.com/geco1986/TSST-Auswertung` pushen.
2. Der Workflow **Docker Image** baut das Image und legt es unter
   `ghcr.io/geco1986/tsst-auswertung` ab (Reiter *Actions* abwarten).
3. Das Paket **öffentlich** schalten, damit TrueNAS es ohne Login ziehen kann:
   GitHub → Profil → **Packages** → `tsst-auswertung` → *Package settings* →
   *Change visibility* → **Public**.
   (Alternativ privat lassen und in TrueNAS Registry-Zugangsdaten hinterlegen.)

## 1. Dataset für die Daten anlegen
TrueNAS → *Datasets* → z. B. `pool/apps/tsst-auswertung` erstellen.
- Hier liegt die SQLite-Datenbank (`debra.sqlite3`) – bleibt bei Updates erhalten.
- Darin einen Ordner **`Inputs`** anlegen (z. B. per SMB-Freigabe). Alles, was
  importiert werden soll, kommt hierhin – gleiche Struktur wie auf dem PC:
  ```
  Inputs/
    Import/              Anmeldezahlen TSST + Gesamtübersicht JTSST (Excel)
    JTSST/               JTSST-Anmeldungen (Excel)
    TSST/Backup-Final TSST/   DEBRA-Backup TSST (WT_/WR_/WI_-Dateien)
    jet/Backup/          DEBRA-Backup JET
    jet/Anmeldedaten/    JR_JET.xls / MR_JET.xls (Alternative zum Backup)
  ```
  In der App werden die Pfade relativ angegeben, z. B. `Inputs\jet\Backup` oder
  `Inputs/jet/Backup` (beide Schreibweisen funktionieren).

## 2. App installieren (empfohlen: Install via YAML)
Apps → *Discover Apps* → oben rechts **Custom App** → **Install via YAML**.
Inhalt von `docker-compose.truenas.yml` einfügen und anpassen:
- `/mnt/POOL/apps/tsst-auswertung` → deinen Dataset-Pfad eintragen (beide Zeilen,
  z. B. `/mnt/tank/apps/tsst-auswertung` und `/mnt/tank/apps/tsst-auswertung/Inputs`).
- `DEBRA_SECRET` → einen langen Zufallswert setzen.
Dann **Install**.

## 2b. Alternative: „Custom App“-Formular (ohne YAML)
- **Image Repository:** `ghcr.io/geco1986/tsst-auswertung`  **Tag:** `latest`
- **Port Forwarding:** Container-Port `5000` → gewünschter Host-Port (z. B. `5000`)
- **Storage / Host Path:**
  - Host-Pfad `…/apps/tsst-auswertung` → Mount-Pfad `/data`
  - Host-Pfad `…/apps/tsst-auswertung/Inputs` → Mount-Pfad `/app/Inputs`
- **Environment Variables:**
  - `DEBRA_DB` = `/data/debra.sqlite3`
  - `DEBRA_SECRET` = *(eigener Zufallswert)*
  - `DEBRA_SEED` = `0`
  - `PORT` = `5000`
- **Restart Policy:** `unless-stopped`

## 3. Aufrufen
`http://<TrueNAS-IP>:5000`
- Zuerst **als Superuser anmelden** und dabei das Superuser-Passwort festlegen
  (mind. 6 Zeichen). Ändern: Einstellungen → Allgemein → Superuser.
- Eingeber und Chef melden sich ohne Passwort mit Rolle + Kennung an.

## 4. Daten laden (als Superuser)
**Einstellungen** – je Anlass ein Reiter:
- **TSST:** Import & WKB → DEBRA-Backup importieren bzw. Allgemein → Import Excel;
  danach WKB anwenden, Vorjahr importieren.
- **JTSST:** Anlegen & Import → Anmeldungen importieren.
- **JET:** Oben rechts auf **JET** umschalten (legt den Anlass an) → Anlegen & Import →
  Anmeldungen importieren (`Inputs\jet\Backup`). Wertungsformeln unter *Wertungsformeln*.

Den aktiven Anlass (oben rechts) setzt nur der Superuser; der Chef arbeitet im aktiven Anlass.

## Bestehende Datenbank vom PC übernehmen
App stoppen → `data\debra.sqlite3` vom PC in das Dataset kopieren (ersetzt die dortige
`debra.sqlite3`; vorhandene `-wal`/`-shm`-Dateien im Dataset vorher löschen) → App starten.
Fehlende Tabellen/Spalten (z. B. für JET und Superuser) werden beim Start automatisch ergänzt.

## Updates
Neues Image bauen lassen (Push ins Repo) → in TrueNAS die App **aktualisieren**
(zieht `:latest` neu). Die Daten im Dataset bleiben erhalten; fehlende
Datenbank-Spalten werden beim Start automatisch migriert.
