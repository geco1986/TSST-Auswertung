# Auswertung TSST

Webbasierte Auswertungs-Software für den **Turn-, Spiel- und Stafettentag (TSST)**
des ZTV-WTU – ein Nachbau der früheren MS-Access-Lösung „DEBRA" als
Flask-/SQLite-Webapp. Deckt **Turner und Turnerinnen** ab: Erfassung, Wertung
nach den Wettkampfbestimmungen, Stafetten mit Vor-/Finalläufen, Ranglisten,
Listen und Notenblätter – im Netzwerk von mehreren PCs gleichzeitig nutzbar.

> Sprache der Oberfläche: **Deutsch**. Beim Login wird nur eine **Rolle**
> (Eingeber/Chef) und eine **Kennung/Station** gewählt – kein Passwort.

## Funktionen (Überblick)
- **Erfassung**: Schnellerfassung über alle Startnummern, Raster je Disziplin,
  DNS/DNF je Mitglied, Plausibilitäts-Warnung (min/max je Disziplin).
- **Wertung**: Durchschnitt (5 Turner / 4 Turnerinnen), Auszeichnung nach Prozent
  oder „bis Rang X", Vermerke (Disq/a.K./…), automatische a.K. bei DNS/DNF.
- **Stafetten**: 4×100 m mit Vorlauf + A/B-Final (Männer) bzw. Final (Frauen),
  Übergabefehler-Zuschläge, Selektion, **Bahnen-/Serieneinteilung** nach der
  Vorjahresliste; Serienplan im Querformat (ein Plan pro A4-Seite).
- **Ranglisten**: sortierbar am Bildschirm, Export immer nach Rang; Status je
  Rangliste (Alles eingegeben / Eingabe kontrolliert / Gedruckt / Fertig WKL);
  **manuelle Korrektur** von Rang/Total/Status.
- **Vier-Augen-Kontrolle**: Kontrollblatt je Erfasser-Kennung + lokales Backup.
- **Listen/Statistik**: Startlisten (nach Verein/Disziplin/Startnummer),
  Anmeldestatistik (inkl. Auszeichnungen bei 30/33/40 %), Notenblätter,
  Kranzliste, Top-Leistungen, Änderungs-Log.
- **Einsatzplan (Vormittag)**: Generator mit Anlagen/Zeit je Turner – ohne
  Vereins-Parallelität.
- **Import**: DEBRA-Text-Backup, Anmeldungen aus Excel (mit Prüfschritt),
  Vorjahres-Rangliste.
- **Betrieb**: SQLite im WAL-Modus (Mehrplatz), Rollen, automatische DB-Migration.

## Schnellstart (lokal, ohne Docker)
```bash
pip install -r requirements.txt
python serve.py           # Produktionsserver (waitress) auf Port 5000
# oder für die Entwicklung:  python app.py
```
Dann im Browser: <http://localhost:5000> – Rolle wählen.

## Docker
```bash
docker compose up -d --build
```
- Erreichbar unter `http://<host>:5000`.
- Die Datenbank liegt im Volume **`debra-data`** unter `/data/debra.sqlite3` und
  bleibt über Neustarts/Updates erhalten.
- **Wichtig:** in `docker-compose.yml` `DEBRA_SECRET` auf einen eigenen
  Zufallswert setzen.

Nur mit Docker (ohne Compose):
```bash
docker build -t auswertung-tsst .
docker run -d --name auswertung-tsst -p 5000:5000 \
  -v auswertung-tsst-data:/data \
  -e DEBRA_SECRET=ein-langer-zufallswert \
  auswertung-tsst
```

## TrueNAS SCALE
Fertiges Image: **`ghcr.io/geco1986/tsst-auswertung:latest`** – ausführliche
Schritt-für-Schritt-Anleitung in **[TRUENAS.md](TRUENAS.md)**, passende Vorlage
in **`docker-compose.truenas.yml`**.

Kurz: Dataset (z. B. `pool/apps/tsst-auswertung`) anlegen → Apps → *Custom App* →
*Install via YAML* → Inhalt von `docker-compose.truenas.yml` einfügen (Volume-Pfad
und `DEBRA_SECRET` anpassen) → installieren → `http://<TrueNAS-IP>:5000`.
Das GHCR-Paket muss dafür **öffentlich** sein (siehe TRUENAS.md).

## Konfiguration (Umgebungsvariablen)
| Variable        | Default                | Bedeutung |
|-----------------|------------------------|-----------|
| `DEBRA_DB`      | `/data/debra.sqlite3`  | Pfad zur SQLite-Datenbank |
| `DEBRA_SECRET`  | `debra-…-dev-key`      | Session-Secret – **unbedingt setzen** |
| `DEBRA_SEED`    | `1`                    | `1` = bei leerer DB Demo-Daten laden, `0` = leer |
| `HOST` / `PORT` | `0.0.0.0` / `5000`     | Bind-Adresse/Port |

## Echte Daten laden
In der App unter **Einstellungen**:
- **Excel-Import** der Anmeldungen (Blätter TU/TI), mit Spaltenzuordnung + Prüfung.
- **DEBRA-Backup importieren** (Text-Export der Access-Software), anschliessend
  **WKB anwenden** und **Vorjahr importieren**.

Per Kommandozeile (im Container z. B. via `docker exec`):
```bash
python -m debra.import_backup /pfad/zum/Backup
python -m debra.wkb
python -m debra.vorjahr
```

## Rollen
- **Eingeber**: Teilnehmer/Resultate erfassen und mutieren, Kontrollblatt.
- **Chef**: zusätzlich Ranglisten, Korrektur, Stafetten-Selektion & Bahnen,
  Einsatzplan, Listen, Einstellungen, Stammdaten, Änderungs-Log.

## Projektstruktur
```
app.py            Flask-App (Routen)
serve.py          Produktions-Start (waitress) – Container-Entrypoint
debra/            Kernmodule: db, scoring, wkb, import_backup, excel_import, vorjahr, seed
templates/        Jinja2-Templates (inkl. Druckvorlagen)
static/style.css  Design
Dockerfile, docker-compose.yml, .github/workflows/docker-image.yml
```

## Lizenz
MIT – siehe [LICENSE](LICENSE).
