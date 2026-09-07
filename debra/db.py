"""Datenbankschicht für DEBRA-Web.

Nachbau des Datenmodells der Original-Software DEBRA (MS Access / Jet 2.0).
Die Original-Tabellen (tabTeilnehmer, tabResultate, tabVereinName,
tabKategorien, tabDisziplinen, tabAuszeichnung, tabZeitplan, tabPCSettings …)
werden hier als relationales SQLite-Schema abgebildet.
"""

import os
import sqlite3

# Ablageort der Datenbank: neben dem Projekt in einer Datei debra.sqlite3.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DEBRA_DB", os.path.join(BASE_DIR, "debra.sqlite3"))


def get_db():
    """Verbindung mit aktivierten Fremdschlüsseln und Zeilen als dict-artige Rows."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")      # Mehrplatzbetrieb: gleichzeitiges Lesen/Schreiben
    conn.execute("PRAGMA busy_timeout = 15000")    # bei „database is locked" warten statt Fehler
    return conn


SCHEMA = """
-- Wettkampf (ein Anlass, z. B. "Turnfest 2025")
CREATE TABLE IF NOT EXISTS wettkampf (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    ort       TEXT,
    datum     TEXT,
    aktiv     INTEGER NOT NULL DEFAULT 0
);

-- Verein / Sektion (tabVereinName)
CREATE TABLE IF NOT EXISTS verein (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nummer    TEXT,
    name      TEXT NOT NULL,
    zusatz    TEXT,
    ort       TEXT,
    verband   TEXT
);

-- Disziplin / Gerät (tabDisziplinen). Globaler Katalog.
-- einheit: Note (direkte Wertung) | Zeit | Weite | Hoehe | Anzahl
CREATE TABLE IF NOT EXISTS disziplin (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    abk          TEXT,
    bezeichnung  TEXT NOT NULL,
    diszgruppe   TEXT,
    einheit      TEXT NOT NULL DEFAULT 'Note'
);

-- Kategorie (tabKategorien) je Wettkampf.
-- typ:            einzel | sektion | gruppe
-- geschlecht:     m | w | alle
-- streich:        Anzahl gestrichener (schlechtester) Resultate
-- kranz_modus:    keiner | prozent | schwelle
-- kranz_wert:     Prozentanteil (0-100) bzw. Total-Schwelle
CREATE TABLE IF NOT EXISTS kategorie (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    wettkampf_id   INTEGER NOT NULL REFERENCES wettkampf(id) ON DELETE CASCADE,
    abk            TEXT,
    bezeichnung    TEXT NOT NULL,
    typ            TEXT NOT NULL DEFAULT 'einzel',
    geschlecht     TEXT NOT NULL DEFAULT 'alle',
    streich        INTEGER NOT NULL DEFAULT 0,
    kranz_modus    TEXT NOT NULL DEFAULT 'prozent',
    kranz_wert     REAL NOT NULL DEFAULT 33.0,
    sortierung     INTEGER NOT NULL DEFAULT 0,
    sparte         TEXT,          -- z. B. Knaben, Mädchen, Turner (aus DEBRA-Import)
    kat_nr         INTEGER,       -- originale KategorieNr aus DEBRA
    berechnung     TEXT NOT NULL DEFAULT 'summe',    -- summe | durchschnitt
    anzahl_werte   INTEGER NOT NULL DEFAULT 0,       -- Anzahl Wert-/Mitgliederspalten (0 = aus Disziplinen)
    richtung       TEXT NOT NULL DEFAULT 'hoch',     -- hoch = mehr ist besser | tief = weniger ist besser (Zeiten)
    einheit        TEXT,                             -- Anzeige-Einheit der Werte (m, s, …)
    ist_stafette   INTEGER NOT NULL DEFAULT 0,       -- 1 = Stafette (Zeit + Übergabefehler)
    hat_final      INTEGER NOT NULL DEFAULT 0,       -- 1 = Vorlauf + Final (4x100m)
    final_typ      TEXT,                             -- 'einzel' (1 Final) | 'ab' (A- und B-Final)
    zuschlag_a     REAL NOT NULL DEFAULT 0,          -- Sekunden je Übergabefehler Feld A
    zuschlag_b     REAL NOT NULL DEFAULT 0,          -- Sekunden je Übergabefehler Feld B
    zuschlag_a_label TEXT,
    zuschlag_b_label TEXT,
    bahnen         INTEGER NOT NULL DEFAULT 8,       -- Anzahl Bahnen je Serie
    anlagen        INTEGER NOT NULL DEFAULT 1,       -- Anzahl Anlagen (Zeitplan)
    zeit_pro_turner REAL NOT NULL DEFAULT 0,         -- Minuten je Sportler:in (Zeitplan)
    warn_min       REAL,                             -- Plausibilität: Warnung unter diesem Wert
    warn_max       REAL,                             -- Plausibilität: Warnung über diesem Wert
    abgeschlossen_von TEXT,                          -- Disziplin fertig: Kennung
    abgeschlossen_am  TEXT,                           -- Disziplin fertig: Zeitstempel
    rl_gedruckt    INTEGER NOT NULL DEFAULT 0,        -- Rangliste gedruckt
    rl_fertig      INTEGER NOT NULL DEFAULT 0,        -- Rangliste fertig/freigegeben (WKL)
    rl_fertig_von  TEXT
);

-- Zuordnung Disziplin -> Kategorie mit Reihenfolge (tabZusammenfassung).
CREATE TABLE IF NOT EXISTS kategorie_disziplin (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kategorie_id  INTEGER NOT NULL REFERENCES kategorie(id) ON DELETE CASCADE,
    disziplin_id  INTEGER NOT NULL REFERENCES disziplin(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 1
);

-- Teilnehmer (tabTeilnehmer)
-- Teilnehmer bzw. Riegen-/Team-Anmeldung. Name kann leer sein: dann ist der
-- Start eine Vereinsanmeldung (bei DEBRA-Leichtathletik-Wettkämpfen üblich).
CREATE TABLE IF NOT EXISTS teilnehmer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wettkampf_id  INTEGER NOT NULL REFERENCES wettkampf(id) ON DELETE CASCADE,
    startnr       INTEGER,
    vorname       TEXT,
    nachname      TEXT,
    jahrgang      INTEGER,
    geschlecht    TEXT,
    verein_id     INTEGER REFERENCES verein(id) ON DELETE SET NULL,
    verein_zusatz TEXT,
    verband       TEXT,
    gruppennr     INTEGER,
    kategorie_id  INTEGER REFERENCES kategorie(id) ON DELETE SET NULL,
    stationsnr    TEXT,
    status        TEXT,    -- '' | disq | ak | unfall | nges | aufg (Vermerk)
    bemerkung     TEXT,    -- freier Vermerk
    final_gruppe  TEXT,    -- Stafette: NULL | A | B | F (Selektion Final)
    anlage        TEXT,    -- Einsatzplan Vormittag: Anlage
    serie         INTEGER, -- Einsatzplan: Serie
    bahn          INTEGER, -- Einsatzplan: Bahn/Position
    startzeit     TEXT,    -- Einsatzplan: Startzeit (HH:MM)
    kontrolliert_von TEXT, -- Vier-Augen-Kontrolle: Kennung
    kontrolliert_am  TEXT, -- Vier-Augen-Kontrolle: Zeitstempel
    rang_manuell  INTEGER, -- manuell gesetzter Rang (überschreibt berechneten)
    total_manuell REAL,    -- manuell gesetztes Total (überschreibt berechnetes)
    total_off     REAL,    -- offizielles Total aus dem Import (falls vorhanden)
    rang_off      INTEGER, -- offizieller Rang aus dem Import
    ausz_off      INTEGER  -- offizielle Auszeichnung aus dem Import (0/1)
);

-- Stafetten-Zeiten je Runde (vorlauf/final) inkl. Übergabefehler und Bahn/Serie.
CREATE TABLE IF NOT EXISTS stafette (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    teilnehmer_id INTEGER NOT NULL REFERENCES teilnehmer(id) ON DELETE CASCADE,
    runde         TEXT NOT NULL,          -- vorlauf | final
    rohzeit       REAL,                   -- gelaufene Zeit in Sekunden
    fehler_a      INTEGER NOT NULL DEFAULT 0,
    fehler_b      INTEGER NOT NULL DEFAULT 0,
    serie         INTEGER,
    bahn          INTEGER,
    erfasst_von   TEXT,
    erfasst_am    TEXT,
    UNIQUE(teilnehmer_id, runde)
);

-- Änderungs-/Audit-Log
CREATE TABLE IF NOT EXISTS aenderung (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit          TEXT,
    kennung       TEXT,
    aktion        TEXT,
    teilnehmer_id INTEGER,
    kategorie_id  INTEGER,
    feld          TEXT,
    alt           TEXT,
    neu           TEXT
);

-- Resultat je Teilnehmer und Disziplin-Position (tabResultate, Note1..Note20).
-- Normalisiert statt breit gespeichert: eine Zeile pro Note.
CREATE TABLE IF NOT EXISTS resultat (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    teilnehmer_id INTEGER NOT NULL REFERENCES teilnehmer(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    note          REAL,
    wert          REAL,   -- gemessener Rohwert (Zeit/Weite), optional
    status        TEXT,   -- NULL | dns | dnf (einzelnes Mitglied)
    erfasst_von   TEXT,   -- Erfasser-/Stationskennung
    erfasst_am    TEXT,   -- Zeitstempel
    UNIQUE(teilnehmer_id, position)
);

-- Vorjahres-Rangliste als Grundlage für die Bahnen-/Serieneinteilung
CREATE TABLE IF NOT EXISTS vorjahr (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sparte    TEXT,               -- Turner | Turnerinnen
    disziplin TEXT NOT NULL,      -- z.B. 4x100m, Schwedenstafette
    verein    TEXT NOT NULL,
    gruppennr INTEGER,
    rang      INTEGER,
    zeit      REAL                -- Sekunden (für Stafetten)
);

-- Zeitplan (tabZeitplan)
CREATE TABLE IF NOT EXISTS zeitplan (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wettkampf_id  INTEGER NOT NULL REFERENCES wettkampf(id) ON DELETE CASCADE,
    zeit          TEXT,
    programmpunkt TEXT NOT NULL,
    ort           TEXT,
    bemerkung     TEXT,
    sortierung    INTEGER NOT NULL DEFAULT 0
);

-- Einstellungen (tabPCSettings) – Schlüssel/Wert.
CREATE TABLE IF NOT EXISTS einstellung (
    schluessel  TEXT PRIMARY KEY,
    wert        TEXT
);

CREATE INDEX IF NOT EXISTS idx_teiln_wk  ON teilnehmer(wettkampf_id);
CREATE INDEX IF NOT EXISTS idx_teiln_startnr ON teilnehmer(wettkampf_id, startnr);
CREATE INDEX IF NOT EXISTS idx_teiln_kat ON teilnehmer(kategorie_id);
CREATE INDEX IF NOT EXISTS idx_res_teiln ON resultat(teilnehmer_id);
CREATE INDEX IF NOT EXISTS idx_kat_wk    ON kategorie(wettkampf_id);
"""


def _migrate(conn):
    """Fügt fehlende Spalten zu bestehenden Tabellen hinzu (ohne Datenverlust).

    Nötig, wenn eine ältere Datenbank mit neuerem Code geöffnet wird –
    CREATE TABLE IF NOT EXISTS ergänzt keine Spalten.
    """
    zusatz = {
        "kategorie": [
            ("berechnung", "TEXT NOT NULL DEFAULT 'summe'"),
            ("anzahl_werte", "INTEGER NOT NULL DEFAULT 0"),
            ("richtung", "TEXT NOT NULL DEFAULT 'hoch'"),
            ("einheit", "TEXT"),
            ("ist_stafette", "INTEGER NOT NULL DEFAULT 0"),
            ("hat_final", "INTEGER NOT NULL DEFAULT 0"),
            ("final_typ", "TEXT"),
            ("zuschlag_a", "REAL NOT NULL DEFAULT 0"),
            ("zuschlag_b", "REAL NOT NULL DEFAULT 0"),
            ("zuschlag_a_label", "TEXT"),
            ("zuschlag_b_label", "TEXT"),
            ("bahnen", "INTEGER NOT NULL DEFAULT 8"),
            ("anlagen", "INTEGER NOT NULL DEFAULT 1"),
            ("zeit_pro_turner", "REAL NOT NULL DEFAULT 0"),
            ("warn_min", "REAL"),
            ("warn_max", "REAL"),
            ("abgeschlossen_von", "TEXT"),
            ("abgeschlossen_am", "TEXT"),
            ("rl_gedruckt", "INTEGER NOT NULL DEFAULT 0"),
            ("rl_fertig", "INTEGER NOT NULL DEFAULT 0"),
            ("rl_fertig_von", "TEXT"),
            ("sparte", "TEXT"), ("kat_nr", "INTEGER"), ("geschlecht", "TEXT"),
        ],
        "teilnehmer": [
            ("status", "TEXT"), ("bemerkung", "TEXT"), ("final_gruppe", "TEXT"),
            ("anlage", "TEXT"), ("serie", "INTEGER"), ("bahn", "INTEGER"), ("startzeit", "TEXT"),
            ("kontrolliert_von", "TEXT"), ("kontrolliert_am", "TEXT"),
            ("rang_manuell", "INTEGER"), ("total_manuell", "REAL"),
            ("total_off", "REAL"), ("rang_off", "INTEGER"), ("ausz_off", "INTEGER"),
            ("verein_zusatz", "TEXT"), ("verband", "TEXT"), ("gruppennr", "INTEGER"),
            ("stationsnr", "TEXT"),
        ],
        "resultat": [
            ("wert", "REAL"), ("status", "TEXT"), ("erfasst_von", "TEXT"), ("erfasst_am", "TEXT"),
        ],
        "stafette": [
            ("serie", "INTEGER"), ("bahn", "INTEGER"),
            ("erfasst_von", "TEXT"), ("erfasst_am", "TEXT"),
        ],
    }
    for tabelle, spalten in zusatz.items():
        try:
            vorhanden = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabelle})")}
        except sqlite3.OperationalError:
            continue
        if not vorhanden:
            continue
        for name, ddl in spalten:
            if name not in vorhanden:
                try:
                    conn.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} {ddl}")
                except sqlite3.OperationalError:
                    pass
    conn.commit()


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    conn.close()


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT wert FROM einstellung WHERE schluessel=?", (key,)).fetchone()
    conn.close()
    return row["wert"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO einstellung(schluessel, wert) VALUES(?,?) "
        "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_active_wettkampf(conn):
    """Aktiver Wettkampf oder der zuletzt angelegte, falls keiner aktiv ist."""
    row = conn.execute(
        "SELECT * FROM wettkampf WHERE aktiv=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM wettkampf ORDER BY id DESC LIMIT 1").fetchone()
    return row
