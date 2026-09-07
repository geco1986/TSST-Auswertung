"""Produktions-Start für den Container.

Importiert die App (löst Schema-Init + Migration aus), legt bei leerer
Datenbank optional Demo-Daten an und startet den WSGI-Server *waitress*.

Konfiguration über Umgebungsvariablen:
  DEBRA_DB      Pfad zur SQLite-Datei (Default im Container: /data/debra.sqlite3)
  DEBRA_SECRET  Secret-Key für Sessions (unbedingt setzen)
  DEBRA_SEED    "1" (Default) = bei leerer DB Demo-Daten laden, "0" = nicht
  HOST / PORT   Bind-Adresse/Port (Default 0.0.0.0:5000)
"""
import os

from app import app                      # Import löst init_db()/Migration aus
from debra.db import get_db
from debra.seed import seed


def _seed_wenn_leer():
    if os.environ.get("DEBRA_SEED", "1") != "1":
        return
    conn = get_db()
    leer = conn.execute("SELECT COUNT(*) c FROM wettkampf").fetchone()["c"] == 0
    conn.close()
    if leer:
        seed()


_seed_wenn_leer()

if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Auswertung TSST läuft auf http://{host}:{port}  (Rolle beim Login wählen)")
    serve(app, host=host, port=port, threads=8)
