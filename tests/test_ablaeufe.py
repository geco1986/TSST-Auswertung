"""Prüft Rollen, Erfassung im Mehrplatzbetrieb, Vier-Augen-Kontrolle, Sperren, Sicherung und Anlässe."""
import re
import sqlite3

import pytest

from debra.db import get_db


def _kategorie(db):
    """Eine normale Kategorie (keine Stafette/kein Seilziehen) im aktiven Anlass mit 2 Gruppen."""
    from app import _kat_positionen
    k = db.execute(
        "SELECT k.* FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id WHERE w.aktiv=1 "
        "AND k.ist_stafette=0 AND COALESCE(k.einheit,'')<>'Rang' AND COALESCE(k.berechnung,'')<>'jet' "
        "AND (SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=k.id)>=2 ORDER BY k.id LIMIT 1").fetchone()
    tns = db.execute("SELECT * FROM teilnehmer WHERE kategorie_id=? ORDER BY startnr", (k["id"],)).fetchall()
    db.execute(f"DELETE FROM resultat WHERE teilnehmer_id IN ({tns[0]['id']},{tns[1]['id']})")
    db.commit()
    return k, _kat_positionen(db, k)[0], tns[0], tns[1]


def _werte(tid):
    c = get_db()
    try:
        return {r["position"]: r["note"] for r in c.execute(
            "SELECT position, note FROM resultat WHERE teilnehmer_id=?", (tid,))}
    finally:
        c.close()


def _felder(t, pos, wert, orig=""):
    d = {f"note_{t['id']}_{p}": wert for p in pos}
    d.update({f"orig_note_{t['id']}_{p}": orig for p in pos})
    return d


# --------------------------------------------------------------------------- Rollen
def test_alle_seiten_ohne_serverfehler(app, login, db):
    """Jede GET-Seite mit jeder Rolle in jedem Anlass: kein Absturz."""
    kids = [r["id"] for r in db.execute("SELECT id FROM kategorie")]
    for rolle in ("eingeber", "chef", "superuser"):
        c = login(rolle)
        for regel in app.url_map.iter_rules():
            if "GET" not in regel.methods or regel.endpoint in ("static", "logout"):
                continue
            urls = [regel.rule.replace("<int:kid>", str(k)) for k in kids] if "<int:kid>" in regel.rule \
                else ([] if "<" in regel.rule else [regel.rule])
            for u in urls:
                assert c.get(u).status_code < 500, f"{rolle} {u}"


def test_chef_braucht_passwort(app):
    c = app.test_client()
    r = c.post("/login", data={"rolle": "chef"})
    assert r.status_code == 200 and "Falsches Chef-Passwort" in r.get_data(as_text=True)
    assert c.get("/rangliste").status_code == 302


def test_chef_ohne_gesetztes_passwort_gesperrt(app, db):
    db.execute("DELETE FROM einstellung WHERE schluessel='chef_passwort'")
    db.commit()
    r = app.test_client().post("/login", data={"rolle": "chef", "chef_passwort": "x"})
    assert "noch kein Passwort" in r.get_data(as_text=True)


def test_eingeber_pin(app, login):
    s = login("superuser")
    s.post("/passwoerter", data={"was": "pin", "neu": "4711", "neu2": "4711"})
    c = app.test_client()
    assert "Falsche Eingeber-PIN" in c.post("/login", data={"rolle": "eingeber"}).get_data(as_text=True)
    assert c.post("/login", data={"rolle": "eingeber", "pin": "4711"}).status_code == 302


def test_eingeber_gesperrte_bereiche(login):
    c = login("eingeber")
    for url in ("/backup", "/kontrollblatt/backup", "/rangliste", "/einstellungen", "/kategorien"):
        r = c.get(url)
        assert r.status_code == 302 and r.headers["Location"].endswith("/"), url


def test_login_leitet_nicht_auf_fremde_seiten(app):
    c = app.test_client()
    for ziel in ("https://boese.example/", "//boese.example/", "/\\boese.example"):
        r = c.post("/login?next=" + ziel, data={"rolle": "eingeber"})
        assert "boese" not in r.headers["Location"]


def test_fremde_formulare_abgelehnt(login):
    c = login("superuser")
    r = c.post("/wettkaempfe/1/aktiv", headers={"Origin": "https://boese.example"})
    assert r.status_code == 403
    r = c.post("/wettkaempfe/1/aktiv", headers={"Origin": "http://localhost"})
    assert r.status_code == 302
    assert c.get("/wettkaempfe/1/aktiv").status_code == 405


# --------------------------------------------------------------------------- Erfassung
def test_raster_ueberschreibt_keine_fremden_werte(login, db):
    k, pos, t1, t2 = _kategorie(db)
    anna, beat = login("eingeber", "Anna"), login("eingeber", "Beat")
    anna.post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"], **_felder(t1, pos, "8.5")})
    assert set(_werte(t1["id"]).values()) == {8.5}
    # Beat hat das Raster geöffnet, als t1 noch leer war, und erfasst nur t2
    beat.post(f"/erfassung/{k['id']}", data={**_felder(t1, pos, ""), **_felder(t2, pos, "9")})
    assert set(_werte(t1["id"]).values()) == {8.5}, "Annas Werte dürfen nicht gelöscht werden"
    assert set(_werte(t2["id"]).values()) == {9.0}


def test_konflikt_wird_gemeldet(login, db):
    k, pos, t1, _ = _kategorie(db)
    anna, beat = login("eingeber", "Anna"), login("eingeber", "Beat")
    anna.post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"], **_felder(t1, pos, "8.5")})
    r = beat.post(f"/erfassung/{k['id']}", data=_felder(t1, pos, "7"), follow_redirects=True)
    assert "inzwischen von anderer Stelle" in r.get_data(as_text=True)
    assert set(_werte(t1["id"]).values()) == {8.5}


def test_ungueltige_und_unplausible_werte(login, db):
    k, pos, t1, _ = _kategorie(db)
    db.execute("UPDATE kategorie SET warn_min=0, warn_max=10 WHERE id=?", (k["id"],))
    db.commit()
    c = login("eingeber")
    r = c.post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"], **_felder(t1, pos, "9,x")},
               follow_redirects=True)
    assert "ist keine Zahl" in r.get_data(as_text=True)
    assert _werte(t1["id"]) == {}
    r = c.post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"], **_felder(t1, pos, "99")},
               follow_redirects=True)
    assert "ausserhalb der Plausibilität" in r.get_data(as_text=True)


def test_doppelte_startnummer_abgelehnt(login, db):
    _, _, t1, t2 = _kategorie(db)
    c = login("eingeber")
    r = c.post(f"/teilnehmer/{t1['id']}/bearbeiten",
               data={"startnr": t2["startnr"], "nachname": "X", "kategorie_id": t1["kategorie_id"]})
    assert "schon vergeben" in r.get_data(as_text=True)


def test_teilnehmer_aenderung_protokolliert(login, db):
    _, _, t1, _ = _kategorie(db)
    c = login("eingeber", "Anna")
    c.post(f"/teilnehmer/{t1['id']}/bearbeiten",
           data={"startnr": t1["startnr"], "nachname": "Neuer Name", "vorname": t1["vorname"] or "",
                 "kategorie_id": t1["kategorie_id"], "verein_id": t1["verein_id"] or ""})
    log = db.execute("SELECT * FROM aenderung WHERE teilnehmer_id=? AND feld='Nachname'", (t1["id"],)).fetchone()
    assert log and log["neu"] == "Neuer Name" and log["kennung"] == "Anna"


# --------------------------------------------------------------------------- Kontrolle und Sperre
def test_vier_augen(login, db):
    k, pos, t1, _ = _kategorie(db)
    anna, beat = login("eingeber", "Anna"), login("eingeber", "Beat")
    anna.post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"], **_felder(t1, pos, "8")})
    anna.post("/kontrollblatt", data={"aktion": "quittieren", "sel": [t1["id"]], "kennung": "Anna"})
    kontr = lambda: get_db().execute("SELECT kontrolliert_von FROM teilnehmer WHERE id=?",  # noqa: E731
                                     (t1["id"],)).fetchone()[0]
    assert kontr() is None, "eigene Eingaben dürfen nicht quittiert werden"
    beat.post("/kontrollblatt", data={"aktion": "quittieren", "sel": [t1["id"]], "kennung": "Anna"})
    assert kontr() == "Beat"
    anna.post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"],
                                         **_felder(t1, pos, "7", orig="8.00")})
    assert kontr() is None, "nach einer Änderung muss neu kontrolliert werden"


def test_sperre_nach_freigabe(login, db):
    k, pos, t1, _ = _kategorie(db)
    db.execute("UPDATE kategorie SET rl_fertig=1, rl_gedruckt=1 WHERE id=?", (k["id"],))
    db.commit()
    login("eingeber").post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"],
                                                      **_felder(t1, pos, "5")})
    assert _werte(t1["id"]) == {}
    login("chef").post("/schnellerfassung", data={"aktion": "speichern", "tid": t1["id"], **_felder(t1, pos, "5")})
    assert set(_werte(t1["id"]).values()) == {5.0}
    assert get_db().execute("SELECT rl_gedruckt FROM kategorie WHERE id=?", (k["id"],)).fetchone()[0] == 0


# --------------------------------------------------------------------------- Sicherung
def test_backup_enthaelt_neueste_aenderungen(login, db):
    offen = get_db()                                       # hält die WAL-Datei offen
    offen.execute("SELECT 1").fetchall()
    db.execute("INSERT INTO verein(name) VALUES('WAL-Test')")
    db.commit()
    daten = login("chef").get("/backup").data
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
        f.write(daten)
        f.flush()
        n = sqlite3.connect(f.name).execute("SELECT COUNT(*) FROM verein WHERE name='WAL-Test'").fetchone()[0]
    offen.close()
    assert n == 1


def test_automatische_sicherung(app, db):
    from debra import sicherung
    erste = sicherung.automatisch_sichern()
    assert erste and sicherung.automatisch_sichern() is None, "ohne Änderung keine neue Sicherung"
    db.execute("INSERT INTO verein(name) VALUES('Neu')")
    db.commit()
    import time
    time.sleep(0.01)
    assert sicherung.automatisch_sichern()


# --------------------------------------------------------------------------- Stammdaten, Anlässe
def test_loeschschutz(login, db):
    _, _, t1, _ = _kategorie(db)
    c = login("chef")
    c.post(f"/kategorien/{t1['kategorie_id']}/loeschen")
    assert db.execute("SELECT 1 FROM kategorie WHERE id=?", (t1["kategorie_id"],)).fetchone()
    c.post(f"/vereine/{t1['verein_id']}/loeschen")
    assert db.execute("SELECT 1 FROM verein WHERE id=?", (t1["verein_id"],)).fetchone()


def test_kategorie_formular_mit_buchstaben(login, db):
    k = db.execute("SELECT id FROM kategorie LIMIT 1").fetchone()
    r = login("superuser").post(f"/kategorien/{k['id']}/bearbeiten",
                                data={"bezeichnung": "X", "streich": "zwei"}, follow_redirects=True)
    assert r.status_code == 200 and "Bitte eine Zahl" in r.get_data(as_text=True)


def test_anlass_jahr_aus_einstellungen(login, db):
    db.execute("DELETE FROM wettkampf WHERE name LIKE 'Jugendwettk%'")
    db.commit()
    c = login("superuser")
    c.post("/konfiguration/jtsst", data={"datum": "2027-09-04", "ort": "Winterthur"})
    w = get_db().execute("SELECT * FROM wettkampf WHERE name LIKE 'Jugendwettk%'").fetchone()
    assert w["name"].endswith(" 2027") and w["datum"] == "2027-09-04" and w["ort"] == "Winterthur"
    # Datum im Reiter „Anlass“ ändern: Jahr im Namen zieht mit
    c.post("/einstellungen/jtsst", data={"wk_name": w["name"], "wk_ort": "Winterthur", "wk_datum": "2028-09-02"})
    w = get_db().execute("SELECT * FROM wettkampf WHERE id=?", (w["id"],)).fetchone()
    assert w["name"].endswith(" 2028") and w["datum"] == "2028-09-02"
    # das Anlegen erkennt den bestehenden JTSST trotz anderem Jahr
    c.post("/konfiguration/jtsst", data={"datum": "2028-09-02"})
    assert get_db().execute("SELECT COUNT(*) FROM wettkampf WHERE name LIKE 'Jugendwettk%'").fetchone()[0] == 1


def test_abschluss_excel_kein_absturz(login):
    assert login("chef").get("/liste/abschluss/xlsx").status_code == 404


def test_html_ohne_jinja_reste(login):
    text = login("superuser").get("/einstellungen").get_data(as_text=True)
    assert not re.search(r"\{\{|\{%", text)
