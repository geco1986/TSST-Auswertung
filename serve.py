"""Produktions-Start für den Container.

Importiert die App (löst Schema-Init + Migration aus), legt bei leerer
Datenbank optional Demo-Daten an und startet den WSGI-Server *waitress*.

Konfiguration über Umgebungsvariablen:
  DEBRA_DB      Pfad zur SQLite-Datei (Default im Container: /data/debra.sqlite3)
  DEBRA_SECRET  Secret-Key für Sessions (unbedingt setzen)
  DEBRA_SEED    "1" = bei leerer DB Demo-Daten laden, "0" (Default) = nicht
  HOST / PORT   Bind-Adresse/Port (Default 0.0.0.0:5000)
  DEBRA_URL_PREFIX  Optionaler Unterpfad, z. B. /tsst (die App bleibt auch unter / erreichbar)
"""
import os

from app import app                      # Import löst init_db()/Migration aus
from debra.db import get_db
from debra.seed import seed


def _seed_wenn_leer():
    if os.environ.get("DEBRA_SEED", "0") != "1":
        return
    conn = get_db()
    leer = conn.execute("SELECT COUNT(*) c FROM wettkampf").fetchone()["c"] == 0
    conn.close()
    if leer:
        seed()


_seed_wenn_leer()


class Unterpfad:
    """Bedient die App zusätzlich unter einem Pfad-Präfix (z. B. hinter dem Tunnel)."""

    def __init__(self, wsgi_app, praefix):
        self.wsgi_app = wsgi_app
        self.praefix = praefix

    def __call__(self, environ, start_response):
        pfad = environ.get("PATH_INFO", "")
        if pfad == self.praefix or pfad.startswith(self.praefix + "/"):
            environ["SCRIPT_NAME"] = self.praefix
            environ["PATH_INFO"] = pfad[len(self.praefix):] or "/"
        return self.wsgi_app(environ, start_response)


if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Auswertung TSST läuft auf http://{host}:{port}  (Rolle beim Login wählen)")
    praefix = os.environ.get("DEBRA_URL_PREFIX", "").rstrip("/")
    serve(Unterpfad(app, praefix) if praefix else app, host=host, port=port, threads=8)
