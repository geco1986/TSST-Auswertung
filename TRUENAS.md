# TrueNAS SCALE – Installation

App-Image: **`ghcr.io/geco1986/tsst-auswertung:latest`**
(wird vom GitHub-Workflow automatisch gebaut und veröffentlicht.)

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
Hier liegt später die SQLite-Datenbank (`debra.sqlite3`) – bleibt bei Updates erhalten.

## 2. App installieren (empfohlen: Install via YAML)
Apps → *Discover Apps* → oben rechts **Custom App** → **Install via YAML**.
Inhalt von `docker-compose.truenas.yml` einfügen und anpassen:
- `--- /mnt/POOL/apps/tsst-auswertung` → deinen Dataset-Pfad eintragen
  (z. B. `/mnt/tank/apps/tsst-auswertung`).
- `DEBRA_SECRET` → einen langen Zufallswert setzen.
Dann **Install**.

## 2b. Alternative: „Custom App"-Formular (ohne YAML)
- **Image Repository:** `ghcr.io/geco1986/tsst-auswertung`  **Tag:** `latest`
- **Port Forwarding:** Container-Port `5000` → gewünschter Host-Port (z. B. `5000`)
- **Storage / Host Path:** Host-Pfad `…/apps/tsst-auswertung` → Mount-Pfad `/data`
- **Environment Variables:**
  - `DEBRA_DB` = `/data/debra.sqlite3`
  - `DEBRA_SECRET` = *(eigener Zufallswert)*
  - `DEBRA_SEED` = `1`
  - `PORT` = `5000`
- **Restart Policy:** `unless-stopped`

## 3. Aufrufen
`http://<TrueNAS-IP>:5000` – beim Login Rolle (Eingeber/Chef) + Kennung wählen.

## 4. Echte Daten laden
In der App unter **Einstellungen**: Excel-Import der Anmeldungen bzw.
DEBRA-Backup importieren → WKB anwenden → Vorjahr importieren.
`DEBRA_SEED=0` setzen, wenn du ohne Demo-Daten (leer) starten willst.

## Updates
Neues Image bauen lassen (Push ins Repo) → in TrueNAS die App **aktualisieren**
(zieht `:latest` neu). Die Daten im Dataset bleiben erhalten; fehlende
Datenbank-Spalten werden beim Start automatisch migriert.
