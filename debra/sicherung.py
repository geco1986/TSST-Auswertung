"""Datensicherung der SQLite-Datenbank.

Die Datenbank läuft im WAL-Modus: frisch gespeicherte Änderungen stehen zuerst in der Datei
``…sqlite3-wal`` neben der Datenbank. Eine einfache Dateikopie der Hauptdatei kann deshalb die
neuesten Eingaben verlieren. Hier wird immer über die SQLite-Sicherungsfunktion kopiert, die
den vollständigen, gültigen Stand liefert.

Automatische Sicherung (serve.py): alle ``DEBRA_SICHERUNG_MINUTEN`` Minuten (Vorgabe 15,
0 = aus) nach ``sicherungen/`` neben der Datenbank – nur wenn sich seit der letzten Sicherung
etwas geändert hat. Es bleiben die neuesten ``DEBRA_SICHERUNG_BEHALTEN`` (Vorgabe 200) Dateien.
"""

import glob
import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime

from .db import DB_PATH

PRAEFIX = "auto-"


def intervall_minuten():
    try:
        return max(0, int(os.environ.get("DEBRA_SICHERUNG_MINUTEN", "15")))
    except ValueError:
        return 15


def ordner():
    return os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "sicherungen")


def kopie_schreiben(ziel, quelle=None):
    """Konsistente Kopie der Datenbank nach `ziel` (inkl. noch nicht übertragener WAL-Inhalte)."""
    src = sqlite3.connect(quelle or DB_PATH, timeout=15)
    try:
        dst = sqlite3.connect(ziel)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")     # eigenständige Datei ohne -wal
        finally:
            dst.close()
    finally:
        src.close()
    return ziel


def als_bytes():
    """Vollständige Sicherung als Bytes (für den Download im Browser)."""
    fd, pfad = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        kopie_schreiben(pfad)
        with open(pfad, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(pfad)
        except OSError:
            pass


def _pruefsumme(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def automatisch_sichern(behalten=None):
    """Legt eine Sicherung an, wenn sich der Inhalt geändert hat. Liefert den Pfad oder None."""
    if not os.path.exists(DB_PATH):
        return None
    behalten = behalten or int(os.environ.get("DEBRA_SICHERUNG_BEHALTEN", "200") or 200)
    os.makedirs(ordner(), exist_ok=True)
    # schneller Vorab-Test: Datenbank- und WAL-Datei seit der letzten Sicherung unverändert?
    stempel = "|".join(f"{os.stat(p).st_mtime_ns}:{os.stat(p).st_size}" if os.path.exists(p) else "-"
                       for p in (DB_PATH, DB_PATH + "-wal"))
    merker = os.path.join(ordner(), ".letzter-stand")
    try:
        with open(merker, encoding="utf-8") as f:
            if f.read().strip() == stempel:
                return None
    except OSError:
        pass
    with open(merker, "w", encoding="utf-8") as f:
        f.write(stempel)
    vorhandene = sorted(glob.glob(os.path.join(ordner(), PRAEFIX + "*.sqlite3")))
    neu = os.path.join(ordner(), f"{PRAEFIX}{datetime.now():%Y%m%d-%H%M%S}.sqlite3")
    tmp = neu + ".tmp"
    kopie_schreiben(tmp)
    if vorhandene and _pruefsumme(vorhandene[-1]) == _pruefsumme(tmp):
        os.remove(tmp)                                   # nichts geändert
        return None
    os.replace(tmp, neu)
    for alt in vorhandene[:max(0, len(vorhandene) + 1 - behalten)]:
        try:
            os.remove(alt)
        except OSError:
            pass
    return neu


def starten():
    """Startet die automatische Sicherung im Hintergrund (einmal pro Prozess)."""
    minuten = intervall_minuten()
    if not minuten:
        return None

    def schleife():
        while True:
            try:
                automatisch_sichern()
            except Exception as e:                      # Sicherung darf den Betrieb nie stoppen
                print(f"Automatische Sicherung fehlgeschlagen: {e}", flush=True)
            time.sleep(minuten * 60)

    t = threading.Thread(target=schleife, name="sicherung", daemon=True)
    t.start()
    return t
