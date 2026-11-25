"""Gemeinsame Test-Umgebung: eigene Datenbank mit Demo-Daten (keine echten Personendaten).

Die Datenbank wird über DEBRA_DB gewählt, bevor die App importiert wird.
"""
import os
import sys
import tempfile

import pytest

_ORDNER = tempfile.mkdtemp(prefix="debra-test-")
os.environ["DEBRA_DB"] = os.path.join(_ORDNER, "test.sqlite3")
os.environ["DEBRA_SECRET"] = "test"
os.environ["DEBRA_SICHERUNG_MINUTEN"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_modul                      # noqa: E402
from debra.db import get_db, set_setting     # noqa: E402
from debra.seed import seed                  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

PASSWORT = {"chef": "chef123", "superuser": "super123"}


def _aufbauen():
    seed(reset=True)
    db = get_db()
    from debra import jet, jtsst
    jtsst.anlegen(db, aktivieren=False)
    jet.anlegen(db)
    db.execute("UPDATE wettkampf SET aktiv=(name LIKE 'Kantonaler%')")
    db.commit()
    db.close()
    set_setting("chef_passwort", generate_password_hash(PASSWORT["chef"]))
    set_setting("superuser_passwort", generate_password_hash(PASSWORT["superuser"]))


@pytest.fixture()
def app():
    _aufbauen()
    app_modul.app.config["TESTING"] = True
    return app_modul.app


@pytest.fixture()
def db():
    c = get_db()
    yield c
    c.close()


def anmelden(app, rolle, kennung="Test"):
    c = app.test_client()
    daten = {"rolle": rolle, "kennung": kennung}
    if rolle == "chef":
        daten["chef_passwort"] = PASSWORT["chef"]
    if rolle == "superuser":
        daten["passwort"] = PASSWORT["superuser"]
    r = c.post("/login", data=daten)
    assert r.status_code == 302 and "/login" not in r.headers["Location"], f"Login {rolle} fehlgeschlagen"
    return c


@pytest.fixture()
def login(app):
    return lambda rolle, kennung="Test": anmelden(app, rolle, kennung)
