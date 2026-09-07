"""DEBRA-Web – Turnwettkampf-Auswertung als Web-Applikation.

Nachbau der Access-Software DEBRA. Start:  python app.py
Dann im Browser: http://127.0.0.1:5000  (Login: Chef, kein Passwort)
"""

import csv
import io
import os
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, send_file, session, url_for)

from debra.db import (DB_PATH, get_active_wettkampf, get_db, get_setting,
                      init_db, set_setting)
from debra import scoring
from debra.seed import seed

app = Flask(__name__)
app.secret_key = os.environ.get("DEBRA_SECRET", "debra-turnverein-dev-key")

GERAETE_EINHEITEN = ["Note", "Zeit", "Weite", "Hoehe", "Anzahl"]
KATEGORIE_TYPEN = {"einzel": "Einzel", "sektion": "Sektion", "gruppe": "Gruppe"}
KRANZ_MODI = {"keiner": "Keine Auszeichnung", "prozent": "Beste X %",
              "rang": "Bis Rang X", "schwelle": "Ab Total-Schwelle"}


# --------------------------------------------------------------------------- #
# Auth (wie im Original: Login als "Chef", kein Passwort)
# --------------------------------------------------------------------------- #
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def load_context():
    g.db = get_db()
    g.wettkampf = get_active_wettkampf(g.db) if session.get("user") else None
    g.rolle = session.get("rolle", "eingeber")


@app.teardown_request
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def chef_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        if session.get("rolle") != "chef":
            flash("Dieser Bereich ist nur für die Rolle „Chef“.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def _anlass_titel(db):
    try:
        w = db.execute("SELECT name, datum FROM wettkampf ORDER BY id LIMIT 1").fetchone()
    except Exception:
        return ""
    if not w:
        return ""
    name = (w["name"] or "").split("–")[0].strip()
    datum = (w["datum"] or "")[:10]
    try:
        from datetime import datetime
        d = datetime.strptime(datum, "%Y-%m-%d")
        monate = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                  "August", "September", "Oktober", "November", "Dezember"]
        datum = f"{d.day}. {monate[d.month - 1]} {d.year}"
    except Exception:
        pass
    return (name + (" · " + datum if datum else "")).strip(" ·")


@app.context_processor
def inject_globals():
    return {"aktueller_user": session.get("user"),
            "aktuelle_rolle": session.get("rolle", "eingeber"),
            "ist_chef": session.get("rolle") == "chef",
            "kennung": session.get("kennung", ""),
            "aktueller_wettkampf": g.get("wettkampf"),
            "anlass_titel": _anlass_titel(g.db) if g.get("db") is not None else "",
            "fmt_zeit": scoring.fmt_zeit,
            "KATEGORIE_TYPEN": KATEGORIE_TYPEN}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        rolle = request.form.get("rolle", "eingeber")
        if rolle not in ("chef", "eingeber"):
            rolle = "eingeber"
        session["user"] = "Chef" if rolle == "chef" else "Eingeber"
        session["rolle"] = rolle
        kennung = (request.form.get("kennung") or "").strip()
        session["kennung"] = kennung or ("Chef" if rolle == "chef" else "Eingabe")
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@app.route("/")
@login_required
def dashboard():
    db = g.db
    wk = g.wettkampf
    stats = {"teilnehmer": 0, "kategorien": 0, "vereine": 0, "erfasst": 0}
    kategorien = []
    if wk:
        stats["teilnehmer"] = db.execute(
            "SELECT COUNT(*) c FROM teilnehmer WHERE wettkampf_id=?", (wk["id"],)
        ).fetchone()["c"]
        stats["kategorien"] = db.execute(
            "SELECT COUNT(*) c FROM kategorie WHERE wettkampf_id=?", (wk["id"],)
        ).fetchone()["c"]
        stats["vereine"] = db.execute("SELECT COUNT(*) c FROM verein").fetchone()["c"]
        kategorien = db.execute(
            "SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
            (wk["id"],),
        ).fetchall()
        # Erfassungsfortschritt je Kategorie
        kategorien = [dict(k) for k in kategorien]
        for k in kategorien:
            tn = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=?",
                            (k["id"],)).fetchone()["c"]
            if k.get("ist_stafette"):
                mit = db.execute(
                    "SELECT COUNT(DISTINCT t.id) c FROM teilnehmer t JOIN stafette s "
                    "ON s.teilnehmer_id=t.id WHERE t.kategorie_id=? AND s.rohzeit IS NOT NULL",
                    (k["id"],)).fetchone()["c"]
            else:
                mit = db.execute(
                    "SELECT COUNT(DISTINCT teilnehmer_id) c FROM resultat r "
                    "JOIN teilnehmer t ON t.id=r.teilnehmer_id WHERE t.kategorie_id=?",
                    (k["id"],)).fetchone()["c"]
            k["tn"] = tn
            k["mit_resultat"] = mit
            k["fortschritt"] = int(mit / tn * 100) if tn else 0
    return render_template("dashboard.html", stats=stats, kategorien=kategorien)


# --------------------------------------------------------------------------- #
# Wettkämpfe
# --------------------------------------------------------------------------- #
@app.route("/wettkaempfe", methods=["GET", "POST"])
@chef_required
def wettkaempfe():
    db = g.db
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            db.execute("INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,0)",
                       (name, request.form.get("ort", ""), request.form.get("datum", "")))
            db.commit()
            flash("Wettkampf angelegt.", "ok")
        return redirect(url_for("wettkaempfe"))
    liste = db.execute("SELECT * FROM wettkampf ORDER BY id DESC").fetchall()
    return render_template("wettkaempfe.html", liste=liste)


@app.route("/wettkaempfe/<int:wid>/aktiv")
@chef_required
def wettkampf_aktiv(wid):
    db = g.db
    db.execute("UPDATE wettkampf SET aktiv=0")
    db.execute("UPDATE wettkampf SET aktiv=1 WHERE id=?", (wid,))
    db.commit()
    flash("Aktiver Wettkampf gewechselt.", "ok")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/wettkaempfe/<int:wid>/loeschen", methods=["POST"])
@chef_required
def wettkampf_loeschen(wid):
    g.db.execute("DELETE FROM wettkampf WHERE id=?", (wid,))
    g.db.commit()
    flash("Wettkampf gelöscht.", "ok")
    return redirect(url_for("wettkaempfe"))


# --------------------------------------------------------------------------- #
# Vereine
# --------------------------------------------------------------------------- #
@app.route("/vereine", methods=["GET", "POST"])
@chef_required
def vereine():
    db = g.db
    if request.method == "POST":
        vid = request.form.get("id")
        daten = (request.form.get("nummer", ""), request.form.get("name", "").strip(),
                 request.form.get("zusatz", ""), request.form.get("ort", ""))
        if not daten[1]:
            flash("Vereinsname fehlt.", "error")
        elif vid:
            db.execute("UPDATE verein SET nummer=?, name=?, zusatz=?, ort=? WHERE id=?",
                       daten + (vid,))
            db.commit()
            flash("Verein gespeichert.", "ok")
        else:
            db.execute("INSERT INTO verein(nummer, name, zusatz, ort) VALUES(?,?,?,?)", daten)
            db.commit()
            flash("Verein hinzugefügt.", "ok")
        return redirect(url_for("vereine"))
    liste = db.execute("SELECT * FROM verein ORDER BY name").fetchall()
    return render_template("vereine.html", liste=liste)


@app.route("/vereine/<int:vid>/loeschen", methods=["POST"])
@chef_required
def verein_loeschen(vid):
    g.db.execute("DELETE FROM verein WHERE id=?", (vid,))
    g.db.commit()
    flash("Verein gelöscht.", "ok")
    return redirect(url_for("vereine"))


# --------------------------------------------------------------------------- #
# Disziplinen
# --------------------------------------------------------------------------- #
@app.route("/disziplinen", methods=["GET", "POST"])
@chef_required
def disziplinen():
    db = g.db
    if request.method == "POST":
        did = request.form.get("id")
        daten = (request.form.get("abk", ""), request.form.get("bezeichnung", "").strip(),
                 request.form.get("diszgruppe", ""), request.form.get("einheit", "Note"))
        if not daten[1]:
            flash("Bezeichnung fehlt.", "error")
        elif did:
            db.execute("UPDATE disziplin SET abk=?, bezeichnung=?, diszgruppe=?, einheit=? WHERE id=?",
                       daten + (did,))
            db.commit(); flash("Disziplin gespeichert.", "ok")
        else:
            db.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)", daten)
            db.commit(); flash("Disziplin hinzugefügt.", "ok")
        return redirect(url_for("disziplinen"))
    liste = db.execute("SELECT * FROM disziplin ORDER BY diszgruppe, bezeichnung").fetchall()
    return render_template("disziplinen.html", liste=liste, einheiten=GERAETE_EINHEITEN)


@app.route("/disziplinen/<int:did>/loeschen", methods=["POST"])
@chef_required
def disziplin_loeschen(did):
    g.db.execute("DELETE FROM disziplin WHERE id=?", (did,))
    g.db.commit()
    flash("Disziplin gelöscht.", "ok")
    return redirect(url_for("disziplinen"))


# --------------------------------------------------------------------------- #
# Kategorien (inkl. Disziplin-Zuordnung)
# --------------------------------------------------------------------------- #
def _require_wettkampf():
    if not g.wettkampf:
        flash("Bitte zuerst einen Wettkampf anlegen und aktivieren.", "error")
        return False
    return True


@app.route("/kategorien")
@chef_required
def kategorien():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    liste = db.execute(
        "SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
        (g.wettkampf["id"],)).fetchall()
    liste = [dict(k) for k in liste]
    for k in liste:
        k["diszs"] = db.execute(
            "SELECT d.abk, d.bezeichnung FROM kategorie_disziplin kd "
            "JOIN disziplin d ON d.id=kd.disziplin_id WHERE kd.kategorie_id=? ORDER BY kd.position",
            (k["id"],)).fetchall()
    return render_template("kategorien.html", liste=liste, typen=KATEGORIE_TYPEN, modi=KRANZ_MODI)


@app.route("/kategorien/neu", methods=["GET", "POST"])
@app.route("/kategorien/<int:kid>/bearbeiten", methods=["GET", "POST"])
@chef_required
def kategorie_form(kid=None):
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    kat = None
    if kid:
        kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
        if not kat:
            abort(404)
    if request.method == "POST":
        felder = dict(
            abk=request.form.get("abk", ""),
            bezeichnung=request.form.get("bezeichnung", "").strip(),
            typ=request.form.get("typ", "einzel"),
            geschlecht=request.form.get("geschlecht", "alle"),
            streich=int(request.form.get("streich") or 0),
            kranz_modus=request.form.get("kranz_modus", "prozent"),
            kranz_wert=float(request.form.get("kranz_wert") or 0),
            berechnung=request.form.get("berechnung", "summe"),
            anzahl_werte=int(request.form.get("anzahl_werte") or 0),
            richtung=request.form.get("richtung", "hoch"),
            einheit=request.form.get("einheit", "").strip(),
        )
        gewaehlt = request.form.getlist("disziplinen")
        if not felder["bezeichnung"]:
            flash("Bezeichnung fehlt.", "error")
        else:
            if kid:
                db.execute(
                    "UPDATE kategorie SET abk=?, bezeichnung=?, typ=?, geschlecht=?, "
                    "streich=?, kranz_modus=?, kranz_wert=?, berechnung=?, anzahl_werte=?, "
                    "richtung=?, einheit=? WHERE id=?",
                    (*felder.values(), kid))
            else:
                cur = db.execute(
                    "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, typ, geschlecht, "
                    "streich, kranz_modus, kranz_wert, berechnung, anzahl_werte, richtung, einheit) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (g.wettkampf["id"], *felder.values()))
                kid = cur.lastrowid
            db.execute("DELETE FROM kategorie_disziplin WHERE kategorie_id=?", (kid,))
            for pos, did in enumerate(gewaehlt, start=1):
                db.execute(
                    "INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) VALUES(?,?,?)",
                    (kid, int(did), pos))
            db.commit()
            flash("Kategorie gespeichert.", "ok")
            return redirect(url_for("kategorien"))
    disziplinen = db.execute("SELECT * FROM disziplin ORDER BY diszgruppe, bezeichnung").fetchall()
    zugeordnet = []
    if kid:
        zugeordnet = [r["disziplin_id"] for r in db.execute(
            "SELECT disziplin_id FROM kategorie_disziplin WHERE kategorie_id=? ORDER BY position",
            (kid,)).fetchall()]
    return render_template("kategorie_form.html", kat=kat, disziplinen=disziplinen,
                           zugeordnet=zugeordnet, typen=KATEGORIE_TYPEN, modi=KRANZ_MODI)


@app.route("/kategorien/<int:kid>/loeschen", methods=["POST"])
@chef_required
def kategorie_loeschen(kid):
    g.db.execute("DELETE FROM kategorie WHERE id=?", (kid,))
    g.db.commit()
    flash("Kategorie gelöscht.", "ok")
    return redirect(url_for("kategorien"))


# --------------------------------------------------------------------------- #
# Teilnehmer (Vorerfassung)
# --------------------------------------------------------------------------- #
@app.route("/teilnehmer")
@login_required
def teilnehmer():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    kat_filter = request.args.get("kategorie", type=int)
    gesamt = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE wettkampf_id=?",
                        (g.wettkampf["id"],)).fetchone()["c"]
    kategorien = db.execute(
        "SELECT k.*, (SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=k.id) n "
        "FROM kategorie k WHERE k.wettkampf_id=? ORDER BY k.sortierung, k.bezeichnung",
        (g.wettkampf["id"],)).fetchall()
    # Bei vielen Anmeldungen ohne Filter nur die Kategorie-Auswahl zeigen.
    liste = []
    zu_gross = gesamt > 300 and not kat_filter
    if not zu_gross:
        sql = ("SELECT t.*, v.name AS verein_name, k.bezeichnung AS kat_name "
               "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
               "LEFT JOIN kategorie k ON k.id=t.kategorie_id WHERE t.wettkampf_id=?")
        params = [g.wettkampf["id"]]
        if kat_filter:
            sql += " AND t.kategorie_id=?"
            params.append(kat_filter)
        sql += " ORDER BY t.startnr"
        liste = db.execute(sql, params).fetchall()
    return render_template("teilnehmer.html", liste=liste, kategorien=kategorien,
                           kat_filter=kat_filter, gesamt=gesamt, zu_gross=zu_gross,
                           status_labels=scoring.STATUS_LABELS)


@app.route("/teilnehmer/neu", methods=["GET", "POST"])
@app.route("/teilnehmer/<int:tid>/bearbeiten", methods=["GET", "POST"])
@login_required
def teilnehmer_form(tid=None):
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    tn = db.execute("SELECT * FROM teilnehmer WHERE id=?", (tid,)).fetchone() if tid else None
    if request.method == "POST":
        startnr = request.form.get("startnr", type=int)
        if not startnr:
            row = db.execute("SELECT COALESCE(MAX(startnr),0)+1 n FROM teilnehmer WHERE wettkampf_id=?",
                             (g.wettkampf["id"],)).fetchone()
            startnr = row["n"]
        felder = (startnr, request.form.get("vorname", ""), request.form.get("nachname", "").strip(),
                  request.form.get("jahrgang", type=int), request.form.get("geschlecht", ""),
                  request.form.get("verein_id", type=int), request.form.get("kategorie_id", type=int),
                  request.form.get("stationsnr", ""),
                  request.form.get("status", "").strip() or None,
                  request.form.get("bemerkung", "").strip() or None)
        if not felder[2] and not felder[5]:
            flash("Bitte einen Namen oder einen Verein angeben.", "error")
        elif tid:
            db.execute("UPDATE teilnehmer SET startnr=?, vorname=?, nachname=?, jahrgang=?, "
                       "geschlecht=?, verein_id=?, kategorie_id=?, stationsnr=?, status=?, "
                       "bemerkung=? WHERE id=?", felder + (tid,))
            db.commit(); flash("Teilnehmer gespeichert.", "ok")
            return redirect(url_for("teilnehmer"))
        else:
            db.execute("INSERT INTO teilnehmer(wettkampf_id, startnr, vorname, nachname, jahrgang, "
                       "geschlecht, verein_id, kategorie_id, stationsnr, status, bemerkung) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (g.wettkampf["id"], *felder))
            db.commit(); flash("Teilnehmer hinzugefügt.", "ok")
            return redirect(url_for("teilnehmer_form"))  # gleich nächsten erfassen
    vereine = db.execute("SELECT * FROM verein ORDER BY name").fetchall()
    kategorien = db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY bezeichnung",
                            (g.wettkampf["id"],)).fetchall()
    naechste_nr = db.execute("SELECT COALESCE(MAX(startnr),0)+1 n FROM teilnehmer WHERE wettkampf_id=?",
                             (g.wettkampf["id"],)).fetchone()["n"]
    return render_template("teilnehmer_form.html", tn=tn, vereine=vereine,
                           kategorien=kategorien, naechste_nr=naechste_nr,
                           status_labels=scoring.STATUS_LABELS)


@app.route("/teilnehmer/<int:tid>/loeschen", methods=["POST"])
@login_required
def teilnehmer_loeschen(tid):
    g.db.execute("DELETE FROM teilnehmer WHERE id=?", (tid,))
    g.db.commit()
    flash("Teilnehmer gelöscht.", "ok")
    return redirect(request.form.get("next") or url_for("teilnehmer"))


@app.route("/teilnehmer/sammelaktion", methods=["POST"])
@login_required
def teilnehmer_sammelaktion():
    """Sammelaktion für mehrere ausgewählte Teilnehmer (Mehrfachauswahl)."""
    db = g.db
    ids = request.form.getlist("sel", type=int)
    aktion = request.form.get("sammel_aktion", "")
    ziel = request.form.get("next") or url_for("teilnehmer")
    if not ids:
        flash("Keine Zeilen ausgewählt.", "error")
        return redirect(ziel)
    marks = ",".join("?" * len(ids))
    if aktion == "loeschen":
        db.execute(f"DELETE FROM teilnehmer WHERE id IN ({marks})", ids)
        flash(f"{len(ids)} Anmeldung(en) abgemeldet.", "ok")
    elif aktion == "status":
        st = request.form.get("status", "").strip() or None
        db.execute(f"UPDATE teilnehmer SET status=? WHERE id IN ({marks})", [st, *ids])
        flash(f"Status für {len(ids)} Zeile(n) gesetzt.", "ok")
    db.commit()
    return redirect(ziel)


@app.route("/mutation")
@login_required
def mutation():
    """Ab- und Nachmeldungen: Suche nach Verein oder Startnummer."""
    db = g.db
    q = (request.args.get("q") or "").strip()
    treffer = []
    if q:
        if q.isdigit():
            treffer = db.execute(
                "SELECT t.*, v.name AS verein_name, k.bezeichnung AS kat_name, w.name AS wk_name "
                "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
                "LEFT JOIN kategorie k ON k.id=t.kategorie_id "
                "LEFT JOIN wettkampf w ON w.id=t.wettkampf_id "
                "WHERE t.startnr=? ORDER BY t.startnr", (int(q),)).fetchall()
        else:
            treffer = db.execute(
                "SELECT t.*, v.name AS verein_name, k.bezeichnung AS kat_name, w.name AS wk_name "
                "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
                "LEFT JOIN kategorie k ON k.id=t.kategorie_id "
                "LEFT JOIN wettkampf w ON w.id=t.wettkampf_id "
                "WHERE v.name LIKE ? ORDER BY v.name, k.sortierung, t.startnr",
                (f"%{q}%",)).fetchall()
    return render_template("mutation.html", q=q, treffer=treffer,
                           status_labels=scoring.STATUS_LABELS)


# --------------------------------------------------------------------------- #
# Erfassung (Resultate-Raster je Kategorie)
# --------------------------------------------------------------------------- #
@app.route("/erfassung")
@login_required
def erfassung_index():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    kategorien = g.db.execute(
        "SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
        (g.wettkampf["id"],)).fetchall()
    return render_template("erfassung_index.html", kategorien=kategorien)


def _kat_positionen(db, kat):
    """Liefert (positionen, diszs, disz_bez, einheit, berechnung, richtung, anzahl_werte)
    für die Erfassung einer Kategorie – gemeinsam von Raster- und Schnellerfassung genutzt."""
    diszs = db.execute(
        "SELECT kd.position, d.abk, d.bezeichnung, d.einheit FROM kategorie_disziplin kd "
        "JOIN disziplin d ON d.id=kd.disziplin_id WHERE kd.kategorie_id=? ORDER BY kd.position",
        (kat["id"],)).fetchall()
    disz_bez = diszs[0]["bezeichnung"] if diszs else kat["bezeichnung"]
    anzahl_werte = kat["anzahl_werte"] if "anzahl_werte" in kat.keys() else 0
    einheit = (kat["einheit"] if "einheit" in kat.keys() else None) or ""
    berechnung = kat["berechnung"] if "berechnung" in kat.keys() else "summe"
    richtung = kat["richtung"] if "richtung" in kat.keys() else "hoch"
    if anzahl_werte and anzahl_werte > 0:
        positionen = list(range(1, anzahl_werte + 1))
        diszs = [{"position": p, "abk": (disz_bez if anzahl_werte == 1 else f"{p}"),
                  "bezeichnung": disz_bez, "einheit": einheit} for p in positionen]
    else:
        positionen = [d["position"] for d in diszs]
        if not positionen:
            positionen = list(range(1, 7))
            diszs = [{"position": p, "abk": f"N{p}", "bezeichnung": f"Note {p}",
                      "einheit": "Note"} for p in positionen]
    return positionen, diszs, disz_bez, einheit, berechnung, richtung, anzahl_werte


def _jetzt():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(db, aktion, teilnehmer_id, kategorie_id, feld, alt, neu):
    """Schreibt einen Eintrag ins Änderungs-/Audit-Log."""
    if str(alt or "") == str(neu or ""):
        return
    db.execute(
        "INSERT INTO aenderung(zeit, kennung, aktion, teilnehmer_id, kategorie_id, feld, alt, neu) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (_jetzt(), session.get("kennung", ""), aktion, teilnehmer_id, kategorie_id,
         feld, None if alt is None else str(alt), None if neu is None else str(neu)))


def _speichere_resultate(db, teilnehmer_id, positionen, form):
    """Speichert die Werte eines Teilnehmers aus dem Formular in die DB.

    Ein Wert kann auch „DNS" oder „DNF" sein – dann wird kein Zahlenwert
    gewertet, sondern der Mitglieder-Status gespeichert (zählt nicht im
    Durchschnitt; die Gruppe wird in der Rangliste als a.K. geführt).
    Schreibt erfasst_von/erfasst_am und protokolliert Änderungen.
    """
    kennung, jetzt = session.get("kennung", ""), _jetzt()
    alt_map = {r["position"]: (r["status"].upper() if r["status"] else
                               (f"{r['note']:.2f}" if r["note"] is not None else ""))
               for r in db.execute(
                   "SELECT position, note, status FROM resultat WHERE teilnehmer_id=?",
                   (teilnehmer_id,)).fetchall()}
    kid = db.execute("SELECT kategorie_id FROM teilnehmer WHERE id=?", (teilnehmer_id,)).fetchone()
    kid = kid["kategorie_id"] if kid else None
    for p in positionen:
        raw = (form.get(f"note_{teilnehmer_id}_{p}", "") or "").strip()
        alt = alt_map.get(p, "")
        if raw == "":
            db.execute("DELETE FROM resultat WHERE teilnehmer_id=? AND position=?",
                       (teilnehmer_id, p))
            _log(db, "resultat", teilnehmer_id, kid, f"Wert {p}", alt, "")
            continue
        low = raw.lower()
        if low in ("dns", "dnf"):
            db.execute(
                "INSERT INTO resultat(teilnehmer_id, position, note, status, erfasst_von, erfasst_am) "
                "VALUES(?,?,NULL,?,?,?) ON CONFLICT(teilnehmer_id, position) DO UPDATE SET "
                "note=NULL, status=excluded.status, erfasst_von=excluded.erfasst_von, erfasst_am=excluded.erfasst_am",
                (teilnehmer_id, p, low, kennung, jetzt))
            _log(db, "resultat", teilnehmer_id, kid, f"Wert {p}", alt, low.upper())
            continue
        try:
            wert = round(float(raw.replace(",", ".")), 2)
        except ValueError:
            continue
        db.execute(
            "INSERT INTO resultat(teilnehmer_id, position, note, status, erfasst_von, erfasst_am) "
            "VALUES(?,?,?,NULL,?,?) ON CONFLICT(teilnehmer_id, position) DO UPDATE SET "
            "note=excluded.note, status=NULL, erfasst_von=excluded.erfasst_von, erfasst_am=excluded.erfasst_am",
            (teilnehmer_id, p, wert, kennung, jetzt))
        _log(db, "resultat", teilnehmer_id, kid, f"Wert {p}", alt, f"{wert:.2f}")


def _speichere_stafette(db, tid, runde, form, prefix):
    """Speichert eine Stafetten-Runde (Rohzeit + 2 Übergabefehler-Felder)."""
    kennung, jetzt = session.get("kennung", ""), _jetzt()
    roh = scoring.parse_zeit(form.get(f"{prefix}_zeit", ""))
    fa = form.get(f"{prefix}_fa", type=int) or 0
    fb = form.get(f"{prefix}_fb", type=int) or 0
    kid = db.execute("SELECT kategorie_id FROM teilnehmer WHERE id=?", (tid,)).fetchone()
    kid = kid["kategorie_id"] if kid else None
    if roh is None and not fa and not fb:
        db.execute("DELETE FROM stafette WHERE teilnehmer_id=? AND runde=?", (tid, runde))
        return
    db.execute(
        "INSERT INTO stafette(teilnehmer_id, runde, rohzeit, fehler_a, fehler_b, erfasst_von, erfasst_am) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(teilnehmer_id, runde) DO UPDATE SET "
        "rohzeit=excluded.rohzeit, fehler_a=excluded.fehler_a, fehler_b=excluded.fehler_b, "
        "erfasst_von=excluded.erfasst_von, erfasst_am=excluded.erfasst_am",
        (tid, runde, roh, fa, fb, kennung, jetzt))
    _log(db, "stafette", tid, kid, f"{runde} Zeit", "", scoring.fmt_zeit(roh) if roh else "")


@app.route("/schnellerfassung", methods=["GET", "POST"])
@login_required
def schnellerfassung():
    """Erfassung per Startnummer: Nummer eingeben, Gruppe wird aus der DB geladen."""
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    wk_id = g.wettkampf["id"]

    if request.method == "POST" and request.form.get("aktion") == "speichern":
        tid = request.form.get("tid", type=int)
        t = db.execute("SELECT * FROM teilnehmer WHERE id=?", (tid,)).fetchone()
        if t:
            kat = db.execute("SELECT * FROM kategorie WHERE id=?", (t["kategorie_id"],)).fetchone()
            if kat and ("ist_stafette" in kat.keys() and kat["ist_stafette"]):
                if kat["hat_final"]:
                    _speichere_stafette(db, tid, "vorlauf", request.form, "vorlauf")
                _speichere_stafette(db, tid, "final", request.form, "final")
            else:
                positionen = _kat_positionen(db, kat)[0] if kat else []
                _speichere_resultate(db, tid, positionen, request.form)
            status = request.form.get("status", "").strip()
            db.execute("UPDATE teilnehmer SET status=?, bemerkung=? WHERE id=?",
                       (status or None, request.form.get("bemerkung", "").strip() or None, tid))
            db.commit()
            # Score für Rückmeldung berechnen
            noten = [r["note"] for r in db.execute(
                "SELECT note FROM resultat WHERE teilnehmer_id=? ORDER BY position", (tid,)).fetchall()]
            if kat and noten:
                score, *_ = scoring.gruppen_score(
                    [None] * 0 + noten, kat["berechnung"] if "berechnung" in kat.keys() else "summe",
                    kat["streich"], kat["richtung"] if "richtung" in kat.keys() else "hoch")
                flash(f"Startnummer {t['startnr']} gespeichert – Wertung {score:.2f}.", "ok")
            else:
                flash(f"Startnummer {t['startnr']} gespeichert.", "ok")
        else:
            flash("Startnummer nicht gefunden.", "error")
        return redirect(url_for("schnellerfassung"))

    nr = request.values.get("nr", type=int)
    eintrag = None
    nicht_gefunden = False
    if nr is not None:
        # alle Startnummern möglich: über alle Wettkämpfe suchen (Startnummern sind eindeutig)
        t = db.execute(
            "SELECT t.*, v.name AS verein_name, w.name AS wk_name FROM teilnehmer t "
            "LEFT JOIN verein v ON v.id=t.verein_id "
            "LEFT JOIN wettkampf w ON w.id=t.wettkampf_id "
            "WHERE t.startnr=? ORDER BY t.wettkampf_id LIMIT 1", (nr,)).fetchone()
        if t:
            kat = db.execute("SELECT * FROM kategorie WHERE id=?", (t["kategorie_id"],)).fetchone()
            ist_staf = bool(kat and "ist_stafette" in kat.keys() and kat["ist_stafette"])
            if ist_staf:
                runden = {r["runde"]: r for r in db.execute(
                    "SELECT * FROM stafette WHERE teilnehmer_id=?", (t["id"],)).fetchall()}
                eintrag = {"t": t, "kat": kat, "ist_stafette": True,
                           "hat_final": kat["hat_final"],
                           "zuschlag_a_label": kat["zuschlag_a_label"] or "Fehler A",
                           "zuschlag_b_label": kat["zuschlag_b_label"] or "Fehler B",
                           "vorlauf": runden.get("vorlauf"), "final": runden.get("final"),
                           "wk_name": t["wk_name"] if "wk_name" in t.keys() else "",
                           "positionen": [], "einheit": "s"}
            else:
                positionen, diszs, disz_bez, einheit, berechnung, richtung, anzahl_werte = \
                    _kat_positionen(db, kat)
                werte = {}
                for r in db.execute(
                        "SELECT position, note, status FROM resultat WHERE teilnehmer_id=?",
                        (t["id"],)).fetchall():
                    if r["status"] in ("dns", "dnf"):
                        werte[r["position"]] = r["status"].upper()
                    elif r["note"] is not None:
                        werte[r["position"]] = f"{r['note']:.2f}"
                eintrag = {"t": t, "kat": kat, "ist_stafette": False,
                           "positionen": positionen, "diszs": diszs,
                           "disz_bez": disz_bez, "einheit": einheit, "berechnung": berechnung,
                           "richtung": richtung, "anzahl_werte": anzahl_werte, "werte": werte,
                           "wk_name": t["wk_name"] if "wk_name" in t.keys() else ""}
        else:
            nicht_gefunden = True
    return render_template("schnellerfassung.html", nr=nr, eintrag=eintrag,
                           nicht_gefunden=nicht_gefunden, status_labels=scoring.STATUS_LABELS)


@app.route("/erfassung/<int:kid>", methods=["GET", "POST"])
@login_required
def erfassung(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    if "ist_stafette" in kat.keys() and kat["ist_stafette"]:
        # Stafetten werden im Stafetten-Modul bzw. per Schnellerfassung erfasst
        if session.get("rolle") == "chef":
            return redirect(url_for("stafette_verwalten", kid=kid))
        flash("Stafetten bitte über die Schnellerfassung erfassen.", "ok")
        return redirect(url_for("schnellerfassung"))
    positionen, diszs, disz_bez, einheit, berechnung, richtung, anzahl_werte = \
        _kat_positionen(db, kat)

    teilnehmende = db.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t "
        "LEFT JOIN verein v ON v.id=t.verein_id WHERE t.kategorie_id=? ORDER BY t.startnr",
        (kid,)).fetchall()

    if request.method == "POST":
        for t in teilnehmende:
            _speichere_resultate(db, t["id"], positionen, request.form)
        db.commit()
        flash("Resultate gespeichert.", "ok")
        return redirect(url_for("erfassung", kid=kid))

    werte = {}
    for t in teilnehmende:
        for r in db.execute("SELECT position, note, status FROM resultat WHERE teilnehmer_id=?",
                            (t["id"],)).fetchall():
            if r["status"] in ("dns", "dnf"):
                werte[(t["id"], r["position"])] = r["status"].upper()
            elif r["note"] is not None:
                werte[(t["id"], r["position"])] = f"{r['note']:.2f}"
    return render_template("erfassung.html", kat=kat, diszs=diszs, positionen=positionen,
                           teilnehmende=teilnehmende, werte=werte, streich=kat["streich"],
                           berechnung=berechnung, richtung=richtung, einheit=einheit,
                           disz_bez=disz_bez, anzahl_werte=anzahl_werte)


# --------------------------------------------------------------------------- #
# Auswertung / Ranglisten
# --------------------------------------------------------------------------- #
@app.route("/rangliste")
@chef_required
def rangliste_index():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    kategorien = g.db.execute(
        "SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
        (g.wettkampf["id"],)).fetchall()
    return render_template("rangliste_index.html", kategorien=kategorien)


def _rl_status(db, kat):
    """Workflow-Status einer Disziplin-Rangliste."""
    kid = kat["id"]
    tn = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=?", (kid,)).fetchone()["c"]
    if kat["ist_stafette"]:
        erf = db.execute("SELECT COUNT(DISTINCT t.id) c FROM teilnehmer t JOIN stafette s "
                         "ON s.teilnehmer_id=t.id WHERE t.kategorie_id=? AND s.rohzeit IS NOT NULL",
                         (kid,)).fetchone()["c"]
    else:
        erf = db.execute("SELECT COUNT(DISTINCT teilnehmer_id) c FROM resultat r JOIN teilnehmer t "
                         "ON t.id=r.teilnehmer_id WHERE t.kategorie_id=?", (kid,)).fetchone()["c"]
    kon = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=? AND kontrolliert_am IS NOT NULL",
                     (kid,)).fetchone()["c"]
    return {
        "eingegeben": tn > 0 and erf >= tn,
        "kontrolliert": tn > 0 and kon >= tn,
        "gedruckt": bool(kat["rl_gedruckt"] if "rl_gedruckt" in kat.keys() else 0),
        "fertig": bool(kat["rl_fertig"] if "rl_fertig" in kat.keys() else 0),
        "fertig_von": (kat["rl_fertig_von"] if "rl_fertig_von" in kat.keys() else "") or "",
    }


@app.route("/rangliste/<int:kid>/status", methods=["POST"])
@chef_required
def rangliste_status(kid):
    db = g.db
    feld = request.form.get("feld")
    if feld == "gedruckt":
        db.execute("UPDATE kategorie SET rl_gedruckt=1 WHERE id=?", (kid,))
    elif feld == "fertig":
        aktuell = db.execute("SELECT rl_fertig FROM kategorie WHERE id=?", (kid,)).fetchone()["rl_fertig"]
        neu = 0 if aktuell else 1
        db.execute("UPDATE kategorie SET rl_fertig=?, rl_fertig_von=? WHERE id=?",
                   (neu, session.get("kennung", "WKL") if neu else None, kid))
    db.commit()
    return redirect(url_for("rangliste", kid=kid))


@app.route("/rangliste/<int:kid>/korrigieren", methods=["GET", "POST"])
@chef_required
def rangliste_korrigieren(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    if request.method == "POST":
        for t in db.execute("SELECT id FROM teilnehmer WHERE kategorie_id=?", (kid,)).fetchall():
            tid = t["id"]
            rang = request.form.get(f"rang_{tid}", "").strip()
            total = request.form.get(f"total_{tid}", "").strip().replace(",", ".")
            status = request.form.get(f"status_{tid}", "").strip() or None
            rang_v = int(rang) if rang.isdigit() else None
            try:
                total_v = round(float(total), 2) if total else None
            except ValueError:
                total_v = None
            db.execute("UPDATE teilnehmer SET rang_manuell=?, total_manuell=?, status=? WHERE id=?",
                       (rang_v, total_v, status, tid))
            _log(db, "korrektur", tid, kid, "rang/total/status",
                 "", f"rang={rang_v} total={total_v} status={status or '-'}")
        db.commit()
        flash("Korrekturen gespeichert.", "ok")
        return redirect(url_for("rangliste", kid=kid))

    daten = scoring.rangliste(db, kat)
    berechnet = {e["teilnehmer_id"]: e for e in daten["eintraege"] + daten.get("sonder", [])}
    teil = db.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
        "WHERE t.kategorie_id=? ORDER BY t.startnr", (kid,)).fetchall()
    return render_template("korrektur.html", kat=kat, teil=teil, berechnet=berechnet,
                           fmt_zeit=scoring.fmt_zeit, ist_zeit=(daten.get("einheit") == "s"),
                           status_labels=scoring.STATUS_LABELS)


@app.route("/rangliste/<int:kid>")
@chef_required
def rangliste(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    daten = scoring.rangliste(db, kat)
    return render_template("rangliste.html", kat=kat, daten=daten,
                           rl_status=_rl_status(db, kat))


@app.route("/rangliste/<int:kid>/druck")
@chef_required
def rangliste_druck(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    daten = scoring.rangliste(db, kat)
    status = _rl_status(db, kat)
    db.execute("UPDATE kategorie SET rl_gedruckt=1 WHERE id=?", (kid,))  # Druck markiert „gedruckt"
    db.commit()
    return render_template("rangliste_druck.html", wettkampf=g.wettkampf,
                           bloecke=[{"kat": kat, "daten": daten, "status": status}])


@app.route("/rangliste/druck")
@chef_required
def rangliste_druck_alle():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    kategorien = db.execute(
        "SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
        (g.wettkampf["id"],)).fetchall()
    bloecke = [{"kat": kat, "daten": scoring.rangliste(db, kat), "status": _rl_status(db, kat)}
               for kat in kategorien]
    return render_template("rangliste_druck.html", wettkampf=g.wettkampf, bloecke=bloecke)


@app.route("/vereinsblatt")
@chef_required
def vereinsblatt():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    daten = scoring.vereinsblatt(g.db, g.wettkampf["id"])
    return render_template("vereinsblatt.html", daten=daten)


# --------------------------------------------------------------------------- #
# Zeitplan
# --------------------------------------------------------------------------- #
@app.route("/zeitplan", methods=["GET", "POST"])
@chef_required
def zeitplan():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    if request.method == "POST":
        zid = request.form.get("id")
        daten = (request.form.get("zeit", ""), request.form.get("programmpunkt", "").strip(),
                 request.form.get("ort", ""), request.form.get("bemerkung", ""))
        if not daten[1]:
            flash("Programmpunkt fehlt.", "error")
        elif zid:
            db.execute("UPDATE zeitplan SET zeit=?, programmpunkt=?, ort=?, bemerkung=? WHERE id=?",
                       daten + (zid,)); db.commit(); flash("Eintrag gespeichert.", "ok")
        else:
            db.execute("INSERT INTO zeitplan(wettkampf_id, zeit, programmpunkt, ort, bemerkung) "
                       "VALUES(?,?,?,?,?)", (g.wettkampf["id"], *daten))
            db.commit(); flash("Eintrag hinzugefügt.", "ok")
        return redirect(url_for("zeitplan"))
    liste = db.execute("SELECT * FROM zeitplan WHERE wettkampf_id=? ORDER BY sortierung, zeit",
                       (g.wettkampf["id"],)).fetchall()
    return render_template("zeitplan.html", liste=liste)


@app.route("/zeitplan/<int:zid>/loeschen", methods=["POST"])
@chef_required
def zeitplan_loeschen(zid):
    g.db.execute("DELETE FROM zeitplan WHERE id=?", (zid,))
    g.db.commit()
    flash("Eintrag gelöscht.", "ok")
    return redirect(url_for("zeitplan"))


# --------------------------------------------------------------------------- #
# Export / Backup (mirrors DEBRA Export/Import via USB)
# --------------------------------------------------------------------------- #
@app.route("/export/rangliste/<int:kid>.csv")
@chef_required
def export_rangliste_csv(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    daten = scoring.rangliste(db, kat)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    if daten["modus"] == "stafette":
        kopf = ["Rang", "StartNr", "Gruppe", "Verein"]
        if daten.get("hat_final"):
            kopf.append("Runde")
        kopf += ["Zeit", "Auszeichnung"]
        w.writerow(kopf)
        for e in daten["eintraege"]:
            row = [e["rang"] or "", e["startnr"], e["anzeige"], e["verein"]]
            if daten.get("hat_final"):
                row.append(e.get("runde", ""))
            row += ["" if e["total"] is None else scoring.fmt_zeit(e["total"]),
                    "Kranz" if e.get("auszeichnung") else ""]
            w.writerow(row)
    elif daten["modus"] == "einzel":
        score_kopf = ("Schnitt" if daten.get("berechnung") == "durchschnitt"
                      else ("Zeit" if daten.get("anzahl_werte") == 1 else "Total"))
        einzelwerte = daten.get("anzahl_werte", 0) and daten["anzahl_werte"] > 1
        kopf = ["Rang", "StartNr", "Gruppe", "Verein"]
        if einzelwerte:
            kopf += [str(p) for p in daten["positionen"]]
        kopf += [score_kopf, "Auszeichnung"]
        w.writerow(kopf)
        for e in daten["eintraege"]:
            row = [e["rang"] or "", e["startnr"], e["anzeige"], e["verein"]]
            if einzelwerte:
                row += [("" if n is None else f"{n:.2f}") for n in e["noten"]]
            row += ["" if e["total"] is None else f"{e['total']:.2f}",
                    "Kranz" if e["auszeichnung"] else ""]
            w.writerow(row)
    else:
        w.writerow(["Rang", "Verein", "Mitglieder", "Total", "Auszeichnung"])
        for e in daten["eintraege"]:
            w.writerow([e["rang"] or "", e["verein"], e["mitglieder"],
                        "" if e["total"] is None else f"{e['total']:.2f}",
                        "Kranz" if e.get("auszeichnung") else ""])
    data = out.getvalue().encode("utf-8-sig")
    fname = f"rangliste_{(kat['abk'] or kat['bezeichnung']).replace(' ', '_')}.csv"
    return Response(data, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.route("/backup")
@chef_required
def backup():
    """Ganze Datenbank herunterladen (entspricht Export auf USB im Original)."""
    return send_file(DB_PATH, as_attachment=True, download_name="debra_backup.sqlite3")


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #
@app.route("/konfiguration", methods=["GET", "POST"])
@chef_required
def konfiguration():
    if request.method == "POST":
        for key in ("pc_id", "client_typ", "backup_pfad", "verein_eigen"):
            set_setting(key, request.form.get(key, ""))
        flash("Einstellungen gespeichert.", "ok")
        return redirect(url_for("konfiguration"))
    settings = {k: get_setting(k, "") for k in ("pc_id", "client_typ", "backup_pfad", "verein_eigen")}
    return render_template("konfiguration.html", settings=settings, db_pfad=DB_PATH)


@app.route("/konfiguration/demo", methods=["POST"])
@chef_required
def demo_laden():
    seed(reset=True)
    flash("Demo-Daten neu geladen.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/konfiguration/wkb", methods=["POST"])
@chef_required
def wkb_anwenden():
    """Wendet die Wettkampfbestimmungen auf Turner/Turnerinnen an."""
    from debra.wkb import anwenden
    try:
        b = anwenden(g.db)
        try:
            from debra import vorjahr as vj
            vj.importieren(conn=g.db)
        except Exception:  # noqa: BLE001
            pass
        flash("WKB angewendet auf {wettkaempfe} Wettkämpfe (Turner/Turnerinnen), "
              "{kategorien} Disziplinen konfiguriert.".format(**b), "ok")
    except Exception as e:  # noqa: BLE001
        flash(f"WKB konnte nicht angewendet werden: {e}", "error")
    return redirect(url_for("dashboard"))


@app.route("/konfiguration/import", methods=["POST"])
@chef_required
def backup_import():
    """Importiert ein DEBRA-Backup (Ordner mit WT_/WR_/WI_-Textdateien)."""
    from debra.import_backup import importieren
    pfad = (request.form.get("import_pfad") or "").strip()
    if not pfad:
        flash("Bitte den Pfad zum Backup-Ordner angeben.", "error")
        return redirect(url_for("konfiguration"))
    try:
        b = importieren(pfad, reset=True)
        flash("Backup importiert: {wettkaempfe} Wettkämpfe, {kategorien} Kategorien, "
              "{teilnehmer} Anmeldungen, {vereine} Vereine, {resultate} Resultate."
              .format(**b), "ok")
    except FileNotFoundError as e:
        flash(str(e), "error")
    except Exception as e:  # noqa: BLE001
        flash(f"Import fehlgeschlagen: {e}", "error")
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Einstellungsseite (Chef) – konsolidierte Wettkampf-Konfiguration
# --------------------------------------------------------------------------- #
@app.route("/einstellungen", methods=["GET", "POST"])
@chef_required
def einstellungen():
    db = g.db
    if request.method == "POST":
        # Anlass-Daten je Wettkampf
        for w in db.execute("SELECT id FROM wettkampf").fetchall():
            name = request.form.get(f"wk_name_{w['id']}")
            if name is not None:
                db.execute("UPDATE wettkampf SET name=?, ort=?, datum=? WHERE id=?",
                           (name.strip(), request.form.get(f"wk_ort_{w['id']}", "").strip(),
                            request.form.get(f"wk_datum_{w['id']}", "").strip(), w["id"]))
        # Auszeichnung pro Kategorie (Modus + Wert)
        for kat in db.execute("SELECT id FROM kategorie").fetchall():
            modus = request.form.get(f"km_{kat['id']}")
            if modus:
                wert = request.form.get(f"kw_{kat['id']}", type=float)
                db.execute("UPDATE kategorie SET kranz_modus=?, kranz_wert=? WHERE id=?",
                           (modus, wert or 0, kat["id"]))
        # Auszeichnungs-Prozentsatz auf alle Kategorien anwenden (optional)
        proz = request.form.get("kranz_prozent", type=float)
        if proz is not None and request.form.get("kranz_auf_alle"):
            db.execute("UPDATE kategorie SET kranz_modus='prozent', kranz_wert=?", (proz,))
        # Stafetten-Zuschläge je Stafetten-Kategorie
        for kat in db.execute("SELECT id FROM kategorie WHERE ist_stafette=1").fetchall():
            za = request.form.get(f"za_{kat['id']}", type=float)
            zb = request.form.get(f"zb_{kat['id']}", type=float)
            bahnen = request.form.get(f"bahnen_{kat['id']}", type=int)
            if za is not None:
                db.execute("UPDATE kategorie SET zuschlag_a=?, zuschlag_b=?, bahnen=? WHERE id=?",
                           (za, zb or 0, bahnen or 8, kat["id"]))
        # Zeitplan & Plausibilität pro Disziplin
        for kat in db.execute("SELECT id FROM kategorie").fetchall():
            if request.form.get(f"anl_{kat['id']}") is not None:
                anl = request.form.get(f"anl_{kat['id']}", type=int)
                zpt = request.form.get(f"zpt_{kat['id']}", type=float)
                wmin = request.form.get(f"wmin_{kat['id']}", type=float)
                wmax = request.form.get(f"wmax_{kat['id']}", type=float)
                db.execute("UPDATE kategorie SET anlagen=?, zeit_pro_turner=?, warn_min=?, warn_max=? WHERE id=?",
                           (anl or 1, zpt or 0, wmin, wmax, kat["id"]))
        db.commit()
        flash("Einstellungen gespeichert.", "ok")
        return redirect(url_for("einstellungen"))

    wettkaempfe = db.execute("SELECT * FROM wettkampf ORDER BY id").fetchall()
    stafetten = db.execute(
        "SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=1 ORDER BY w.id, k.sortierung").fetchall()
    kategorien = db.execute(
        "SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "ORDER BY w.id, k.sortierung").fetchall()
    vorjahr_n = db.execute("SELECT COUNT(*) c FROM vorjahr").fetchone()["c"]
    settings = {k: get_setting(k, "") for k in ("pc_id", "client_typ")}
    return render_template("einstellungen.html", wettkaempfe=wettkaempfe,
                           stafetten=stafetten, kategorien=kategorien, modi=KRANZ_MODI,
                           vorjahr_n=vorjahr_n, settings=settings, db_pfad=DB_PATH)


# --------------------------------------------------------------------------- #
# Erfassungskontrolle – fehlende Resultate
# --------------------------------------------------------------------------- #
@app.route("/erfassungskontrolle")
@login_required
def erfassungskontrolle():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe") if g.rolle == "chef" else url_for("dashboard"))
    db = g.db
    bloecke = []
    for w in db.execute("SELECT * FROM wettkampf ORDER BY id").fetchall():
        zeilen = []
        for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                            (w["id"],)).fetchall():
            tn = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=?", (k["id"],)).fetchone()["c"]
            if k["ist_stafette"]:
                mit = db.execute(
                    "SELECT COUNT(DISTINCT t.id) c FROM teilnehmer t JOIN stafette s ON s.teilnehmer_id=t.id "
                    "WHERE t.kategorie_id=? AND s.rohzeit IS NOT NULL", (k["id"],)).fetchone()["c"]
            else:
                mit = db.execute(
                    "SELECT COUNT(DISTINCT teilnehmer_id) c FROM resultat r JOIN teilnehmer t "
                    "ON t.id=r.teilnehmer_id WHERE t.kategorie_id=?", (k["id"],)).fetchone()["c"]
            zeilen.append({"kat": k, "tn": tn, "mit": mit, "fehlt": tn - mit,
                           "kontrolliert": db.execute(
                               "SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=? "
                               "AND kontrolliert_am IS NOT NULL", (k["id"],)).fetchone()["c"],
                           "vollstaendig": tn > 0 and mit >= tn,
                           "abgeschlossen": bool(k["abgeschlossen_am"] if "abgeschlossen_am" in k.keys() else None)})
        bloecke.append({"wk": w, "zeilen": zeilen})
    return render_template("erfassungskontrolle.html", bloecke=bloecke)


# --------------------------------------------------------------------------- #
# Vier-Augen-Kontrolle: Kontrollblatt (nach Kennung) + Quittieren + Backup
# --------------------------------------------------------------------------- #
@app.route("/einsatzplan", methods=["GET"])
@chef_required
def einsatzplan():
    db = g.db
    kats = db.execute(
        "SELECT k.*, w.name AS wk_name, "
        "(SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=k.id) AS anz "
        "FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=0 ORDER BY w.id, k.sortierung").fetchall()
    startzeit = get_setting("einsatz_start", "08:00")
    return render_template("einsatzplan.html", kats=kats, startzeit=startzeit)


@app.route("/einsatzplan/generieren", methods=["POST"])
@chef_required
def einsatzplan_generieren():
    import math
    db = g.db
    start = (request.form.get("startzeit") or "08:00").strip()
    set_setting("einsatz_start", start)
    try:
        h, m = start.split(":"); base = int(h) * 60 + int(m)
    except ValueError:
        base = 8 * 60

    def frei(intervalle, t, dur):
        for s, e in intervalle:
            if t < e and s < t + dur:
                return False
        return True

    def frueheste(anlage_iv, verein_iv, dur):
        # kleinste Startzeit >= base, in der Anlage UND Verein frei sind
        kandidaten = {base}
        for s, e in anlage_iv + verein_iv:
            if e >= base:
                kandidaten.add(e)
        for t in sorted(kandidaten):
            if frei(anlage_iv, t, dur) and frei(verein_iv, t, dur):
                return t
        return max(kandidaten)

    # Aufgaben je Disziplin sammeln (Reihenfolge: Disziplin, Verein)
    aufgaben = []
    for k in db.execute("SELECT * FROM kategorie WHERE ist_stafette=0 ORDER BY sortierung, bezeichnung").fetchall():
        mitglieder = k["anzahl_werte"] or (5 if (k["geschlecht"] or "m") == "m" else 4)
        dauer = max(1, math.ceil((k["zeit_pro_turner"] or 0) * mitglieder)) if k["zeit_pro_turner"] else 10
        anlagen = k["anlagen"] or 1
        labels = [(f"{k['bezeichnung']} {n + 1}" if anlagen > 1 else k["bezeichnung"])
                  for n in range(anlagen)]
        for t in db.execute(
                "SELECT t.id, t.verein_id FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
                "WHERE t.kategorie_id=? ORDER BY v.name, t.gruppennr, t.startnr", (k["id"],)).fetchall():
            aufgaben.append((t["id"], t["verein_id"], dauer, labels))

    anlage_busy, verein_busy, zaehler = {}, {}, {}
    for tid, vid, dur, labels in aufgaben:
        viv = verein_busy.setdefault(vid, [])
        best = None
        for lab in labels:
            aiv = anlage_busy.setdefault(lab, [])
            t0 = frueheste(aiv, viv, dur)
            if best is None or t0 < best[0]:
                best = (t0, lab, aiv)
        t0, lab, aiv = best
        aiv.append((t0, t0 + dur)); aiv.sort()
        viv.append((t0, t0 + dur)); viv.sort()
        zaehler[lab] = zaehler.get(lab, 0) + 1
        hh, mm = divmod(t0, 60)
        db.execute("UPDATE teilnehmer SET anlage=?, bahn=?, startzeit=? WHERE id=?",
                   (lab, zaehler[lab], f"{hh:02d}:{mm:02d}", tid))
    db.commit()
    flash("Einsatzplan (Vormittag) erzeugt – kein Verein zeitgleich an zwei Anlagen. Manuell anpassbar.", "ok")
    return redirect(url_for("einsatzplan"))


@app.route("/einsatzplan/druck")
@chef_required
def einsatzplan_druck():
    db = g.db
    nach = request.args.get("nach", "anlage")   # anlage | verein
    rows = db.execute(
        "SELECT t.startnr, t.gruppennr, t.anlage, t.startzeit, v.name AS verein_name, "
        "t.verein_zusatz, k.bezeichnung AS kat_name FROM teilnehmer t "
        "LEFT JOIN verein v ON v.id=t.verein_id JOIN kategorie k ON k.id=t.kategorie_id "
        "WHERE k.ist_stafette=0 AND t.startzeit IS NOT NULL").fetchall()
    from itertools import groupby
    if nach == "verein":
        rows = sorted(rows, key=lambda r: ((r["verein_name"] or ""), r["startzeit"] or ""))
        gruppen = [{"kopf": key, "zeilen": list(grp)}
                   for key, grp in groupby(rows, key=lambda r: r["verein_name"] or "")]
    else:
        rows = sorted(rows, key=lambda r: ((r["anlage"] or ""), r["startzeit"] or ""))
        gruppen = [{"kopf": key, "zeilen": list(grp)}
                   for key, grp in groupby(rows, key=lambda r: r["anlage"] or "")]
    return render_template("einsatzplan_druck.html", gruppen=gruppen, nach=nach)


@app.route("/kontrollblatt", methods=["GET", "POST"])
@login_required
def kontrollblatt():
    db = g.db
    if request.method == "POST" and request.form.get("aktion") == "quittieren":
        ids = request.form.getlist("sel", type=int)
        if ids:
            marks = ",".join("?" * len(ids))
            db.execute(f"UPDATE teilnehmer SET kontrolliert_von=?, kontrolliert_am=? "
                       f"WHERE id IN ({marks})", [session.get("kennung", ""), _jetzt(), *ids])
            for tid in ids:
                _log(db, "kontrolle", tid, None, "kontrolliert", "", session.get("kennung", ""))
            db.commit()
            flash(f"{len(ids)} Gruppe(n) als kontrolliert markiert.", "ok")
        return redirect(url_for("kontrollblatt", kennung=request.form.get("kennung", ""),
                                kat=request.form.get("kat", ""), offen=request.form.get("offen", "")))

    kennungen = [r["erfasst_von"] for r in db.execute(
        "SELECT DISTINCT erfasst_von FROM resultat WHERE erfasst_von IS NOT NULL AND erfasst_von<>'' "
        "ORDER BY erfasst_von").fetchall()]
    gewaehlt = request.args.get("kennung", "") or (kennungen[0] if kennungen else "")
    nur_offen = request.args.get("offen", "1") == "1"
    kat_filter = request.args.get("kat", type=int)

    bloecke = []
    kat_rows = db.execute(
        "SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=0 ORDER BY w.id, k.sortierung").fetchall()
    for k in kat_rows:
        if kat_filter and k["id"] != kat_filter:
            continue
        positionen = _kat_positionen(db, k)[0]
        rows = db.execute(
            "SELECT DISTINCT t.id, t.startnr, t.gruppennr, t.kontrolliert_am, t.kontrolliert_von, "
            "v.name AS verein_name, t.verein_zusatz FROM teilnehmer t "
            "LEFT JOIN verein v ON v.id=t.verein_id JOIN resultat r ON r.teilnehmer_id=t.id "
            "WHERE t.kategorie_id=? AND r.erfasst_von=? ORDER BY t.startnr", (k["id"], gewaehlt)).fetchall()
        eintraege = []
        for t in rows:
            if nur_offen and t["kontrolliert_am"]:
                continue
            werte = {r["position"]: (r["status"].upper() if r["status"] else
                                     (f"{r['note']:.2f}" if r["note"] is not None else ""))
                     for r in db.execute("SELECT position, note, status FROM resultat WHERE teilnehmer_id=?",
                                         (t["id"],)).fetchall()}
            eintraege.append({"t": t, "werte": [werte.get(p, "") for p in positionen]})
        if eintraege:
            bloecke.append({"kat": k, "positionen": positionen, "eintraege": eintraege})
    return render_template("kontrollblatt.html", bloecke=bloecke, kennungen=kennungen,
                           gewaehlt=gewaehlt, nur_offen=nur_offen, kat_filter=kat_filter,
                           alle_kats=kat_rows)


@app.route("/kontrollblatt/backup")
@login_required
def kontrollblatt_backup():
    """Lokale Sicherung der Datenbank (wird beim Kontrollblatt-Druck ausgelöst)."""
    from datetime import datetime
    name = "debra_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".sqlite3"
    return send_file(DB_PATH, as_attachment=True, download_name=name)


# --------------------------------------------------------------------------- #
# Disziplin abschliessen + „Disziplin fertig"-Blatt
# --------------------------------------------------------------------------- #
@app.route("/disziplin/<int:kid>/abschliessen", methods=["POST"])
@chef_required
def disziplin_abschliessen(kid):
    db = g.db
    db.execute("UPDATE kategorie SET abgeschlossen_von=?, abgeschlossen_am=? WHERE id=?",
               (session.get("kennung", "Chef"), _jetzt(), kid))
    _log(db, "abschluss", None, kid, "abgeschlossen", "", session.get("kennung", "Chef"))
    db.commit()
    return redirect(url_for("disziplin_fertig", kid=kid))


@app.route("/disziplin/<int:kid>/fertig")
@chef_required
def disziplin_fertig(kid):
    db = g.db
    kat = db.execute("SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
                     "WHERE k.id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    anz = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=?", (kid,)).fetchone()["c"]
    return render_template("disziplin_fertig.html", kat=kat, anz=anz)


@app.route("/aenderungen")
@chef_required
def aenderungen():
    db = g.db
    kennung = request.args.get("kennung", "")
    sql = ("SELECT a.*, k.bezeichnung AS kat_name, v.name AS verein_name, t.startnr "
           "FROM aenderung a LEFT JOIN kategorie k ON k.id=a.kategorie_id "
           "LEFT JOIN teilnehmer t ON t.id=a.teilnehmer_id LEFT JOIN verein v ON v.id=t.verein_id ")
    params = []
    if kennung:
        sql += "WHERE a.kennung=? "
        params.append(kennung)
    sql += "ORDER BY a.id DESC LIMIT 500"
    eintraege = db.execute(sql, params).fetchall()
    kennungen = [r["kennung"] for r in db.execute(
        "SELECT DISTINCT kennung FROM aenderung WHERE kennung IS NOT NULL AND kennung<>'' ORDER BY kennung").fetchall()]
    return render_template("aenderungen.html", eintraege=eintraege, kennungen=kennungen, kennung=kennung)


# --------------------------------------------------------------------------- #
# Kranzliste (Chef) – ausgezeichnete Gruppen für die Rangverkündigung
# --------------------------------------------------------------------------- #
@app.route("/kranzliste")
@chef_required
def kranzliste():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    druck = request.args.get("druck")
    bloecke = []
    for w in db.execute("SELECT * FROM wettkampf ORDER BY id").fetchall():
        kats = []
        for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                            (w["id"],)).fetchall():
            d = scoring.rangliste(db, k)
            ausgez = [e for e in d["eintraege"] if e.get("auszeichnung")]
            if ausgez:
                kats.append({"kat": k, "eintraege": ausgez, "einheit": d.get("einheit", "")})
        if kats:
            bloecke.append({"wk": w, "kats": kats})
    return render_template("kranzliste.html", bloecke=bloecke, druck=druck)


# --------------------------------------------------------------------------- #
# Top-Leistungen (Chef) – beste Leistung je Disziplin für den Speaker
# --------------------------------------------------------------------------- #
@app.route("/top-leistungen")
@chef_required
def top_leistungen():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    bloecke = []
    for w in db.execute("SELECT * FROM wettkampf ORDER BY id").fetchall():
        zeilen = []
        for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                            (w["id"],)).fetchall():
            d = scoring.rangliste(db, k)
            beste = next((e for e in d["eintraege"] if e.get("rang") == 1 and e.get("total") is not None), None)
            zeilen.append({"kat": k, "beste": beste, "einheit": d.get("einheit", ""),
                           "ist_zeit": d.get("richtung") == "tief"})
        bloecke.append({"wk": w, "zeilen": zeilen})
    return render_template("top_leistungen.html", bloecke=bloecke)


# --------------------------------------------------------------------------- #
# Notenblätter / Startlisten (Chef) – druckbare Listen je Disziplin
# --------------------------------------------------------------------------- #
@app.route("/notenblaetter")
@chef_required
def notenblaetter():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    kategorien = db.execute(
        "SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "ORDER BY w.id, k.sortierung").fetchall()
    return render_template("notenblaetter.html", kategorien=kategorien)


@app.route("/notenblaetter/<int:kid>/druck")
@chef_required
def notenblatt_druck(kid):
    db = g.db
    kat = db.execute("SELECT k.*, w.name AS wk_name FROM kategorie k "
                     "JOIN wettkampf w ON w.id=k.wettkampf_id WHERE k.id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    if kat["ist_stafette"]:
        # Läufe: Bahnen-/Serienliste wie das offizielle Lauf-Notenblatt
        runde = request.args.get("runde", "vorlauf" if kat["hat_final"] else "final")
        serien = _serien_lanes(db, kat, runde)
        return render_template("notenblatt_lauf_druck.html", kat=kat, runde=runde, serien=serien)
    # Technische Disziplinen: Gruppen-Notenblatt (ein Blatt je Riege)
    mitglieder = kat["anzahl_werte"] or (5 if (kat["geschlecht"] or "m") == "m" else 4)
    sparte_tag = "TU" if (kat["geschlecht"] or "m") == "m" else "TI"
    gruppen = db.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
        "WHERE t.kategorie_id=? ORDER BY t.startnr", (kid,)).fetchall()
    return render_template("notenblatt_druck.html", kat=kat, gruppen=gruppen,
                           mitglieder=mitglieder, sparte_tag=sparte_tag)


# --------------------------------------------------------------------------- #
# Stafetten-Modul (Chef): Selektion, Zeiten, Bahnen-/Serieneinteilung
# --------------------------------------------------------------------------- #
LANE_ORDER = [4, 5, 3, 6, 2, 7, 1, 8]   # Standard-Bahnenverteilung (schnellste Mitte)


def _serien_lanes(db, kat, runde):
    """Serien -> alle Bahnen (1..bahnen) mit Team oder leer, für Lauf-Notenblatt."""
    bahnen = kat["bahnen"] or 8
    teams = _stafette_teams(db, kat["id"])
    belegt = {}   # (serie,bahn) -> team
    serien_ids = set()
    for t in teams:
        r = db.execute("SELECT serie, bahn FROM stafette WHERE teilnehmer_id=? AND runde=?",
                       (t["id"], runde)).fetchone()
        if r and r["serie"]:
            serien_ids.add(r["serie"])
            if r["bahn"]:
                belegt[(r["serie"], r["bahn"])] = t
    out = {}
    for s in sorted(serien_ids):
        reihen = []
        for b in range(1, bahnen + 1):
            t = belegt.get((s, b))
            if t:
                verein = (t["verein_name"] or "") + (" " + t["verein_zusatz"] if t["verein_zusatz"] else "") \
                    + (f" {t['gruppennr']}" if t["gruppennr"] else "")
                reihen.append({"bahn": b, "startnr": t["startnr"], "verein": verein.strip()})
            else:
                reihen.append({"bahn": b, "startnr": 0, "verein": ""})
        out[s] = reihen
    return out


@app.route("/stafetten")
@chef_required
def stafetten_index():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    kategorien = g.db.execute(
        "SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=1 ORDER BY w.id, k.sortierung").fetchall()
    return render_template("stafetten_index.html", kategorien=kategorien)


def _stafette_teams(db, kid):
    return db.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
        "WHERE t.kategorie_id=? ORDER BY t.startnr", (kid,)).fetchall()


@app.route("/stafetten/<int:kid>", methods=["GET", "POST"])
@chef_required
def stafette_verwalten(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat or not kat["ist_stafette"]:
        abort(404)
    teams = _stafette_teams(db, kid)

    if request.method == "POST":
        for t in teams:
            if kat["hat_final"]:
                _speichere_stafette(db, t["id"], "vorlauf", request.form, f"v_{t['id']}")
                _speichere_stafette(db, t["id"], "final", request.form, f"f_{t['id']}")
                gr = request.form.get(f"sel_{t['id']}", "").strip() or None
                db.execute("UPDATE teilnehmer SET final_gruppe=? WHERE id=?", (gr, t["id"]))
            else:
                _speichere_stafette(db, t["id"], "final", request.form, f"f_{t['id']}")
            st = request.form.get(f"status_{t['id']}", "").strip() or None
            db.execute("UPDATE teilnehmer SET status=? WHERE id=?", (st, t["id"]))
        db.commit()
        flash("Stafetten-Daten gespeichert.", "ok")
        return redirect(url_for("stafette_verwalten", kid=kid))

    # Einträge mit berechneten Endzeiten aufbereiten
    rows = []
    for t in teams:
        runden = {r["runde"]: r for r in db.execute(
            "SELECT * FROM stafette WHERE teilnehmer_id=?", (t["id"],)).fetchall()}
        rows.append({
            "t": t,
            "vorlauf": runden.get("vorlauf"), "final": runden.get("final"),
            "vz": scoring.stafette_endzeit(runden.get("vorlauf"), kat),
            "fz": scoring.stafette_endzeit(runden.get("final"), kat),
        })
    return render_template("stafette_verwalten.html", kat=kat, rows=rows,
                           status_labels=scoring.STATUS_LABELS)


@app.route("/stafetten/<int:kid>/selektion", methods=["POST"])
@chef_required
def stafette_selektion(kid):
    """Automatische Selektion A/B/F aus den Vorlaufzeiten (übersteuerbar)."""
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat or not kat["hat_final"]:
        abort(404)
    teams = _stafette_teams(db, kid)
    rang = []
    for t in teams:
        if (t["status"] or ""):
            continue
        row = db.execute("SELECT * FROM stafette WHERE teilnehmer_id=? AND runde='vorlauf'",
                         (t["id"],)).fetchone()
        ez = scoring.stafette_endzeit(row, kat)
        if ez is not None:
            rang.append((ez, t["id"]))
    rang.sort()
    db.execute("UPDATE teilnehmer SET final_gruppe=NULL WHERE kategorie_id=?", (kid,))
    if kat["final_typ"] == "ab":
        for i, (_, tid) in enumerate(rang):
            gr = "A" if i < 8 else ("B" if i < 16 else None)
            if gr:
                db.execute("UPDATE teilnehmer SET final_gruppe=? WHERE id=?", (gr, tid))
    else:
        for i, (_, tid) in enumerate(rang[:8]):
            db.execute("UPDATE teilnehmer SET final_gruppe='F' WHERE id=?", (tid,))
    db.commit()
    flash("Selektion aus den Vorlaufzeiten übernommen.", "ok")
    return redirect(url_for("stafette_verwalten", kid=kid))


@app.route("/stafetten/<int:kid>/bahnen", methods=["GET", "POST"])
@chef_required
def stafette_bahnen(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat or not kat["ist_stafette"]:
        abort(404)
    runde = request.args.get("runde", "vorlauf" if kat["hat_final"] else "final")
    bahnen = kat["bahnen"] or 8

    if request.method == "POST":
        for key, val in request.form.items():
            if key.startswith("serie_"):
                tid = int(key.split("_", 1)[1])
                serie = request.form.get(f"serie_{tid}", type=int)
                bahn = request.form.get(f"bahn_{tid}", type=int)
                db.execute(
                    "INSERT INTO stafette(teilnehmer_id, runde, serie, bahn) VALUES(?,?,?,?) "
                    "ON CONFLICT(teilnehmer_id, runde) DO UPDATE SET serie=excluded.serie, bahn=excluded.bahn",
                    (tid, runde, serie, bahn))
        db.commit()
        flash("Bahneneinteilung gespeichert.", "ok")
        return redirect(url_for("stafette_bahnen", kid=kid, runde=runde))

    teams = _stafette_teams(db, kid)
    rows = []
    for t in teams:
        r = db.execute("SELECT * FROM stafette WHERE teilnehmer_id=? AND runde=?",
                       (t["id"], runde)).fetchone()
        vz = None
        vr = db.execute("SELECT * FROM stafette WHERE teilnehmer_id=? AND runde='vorlauf'",
                        (t["id"],)).fetchone()
        vz = scoring.stafette_endzeit(vr, kat)
        rows.append({"t": t, "serie": r["serie"] if r else None,
                     "bahn": r["bahn"] if r else None, "vz": vz,
                     "final_gruppe": t["final_gruppe"]})
    return render_template("stafette_bahnen.html", kat=kat, rows=rows, runde=runde, bahnen=bahnen)


@app.route("/stafetten/<int:kid>/bahnen/auto", methods=["POST"])
@chef_required
def stafette_bahnen_auto(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat or not kat["ist_stafette"]:
        abort(404)
    runde = request.form.get("runde", "vorlauf" if kat["hat_final"] else "final")
    bahnen = kat["bahnen"] or 8
    teams = _stafette_teams(db, kid)

    def set_bahn(tid, serie, bahn):
        db.execute(
            "INSERT INTO stafette(teilnehmer_id, runde, serie, bahn) VALUES(?,?,?,?) "
            "ON CONFLICT(teilnehmer_id, runde) DO UPDATE SET serie=excluded.serie, bahn=excluded.bahn",
            (tid, runde, serie, bahn))

    if runde == "final" and kat["hat_final"]:
        # Finals nach Vorlaufzeit gesetzt (schnellste in die Mitte)
        for gruppe, serie in ((["A", "F"], 1), (["B"], 2)):
            teilnehmer = [t for t in teams if t["final_gruppe"] in gruppe and not (t["status"] or "")]
            zeiten = []
            for t in teilnehmer:
                vr = db.execute("SELECT * FROM stafette WHERE teilnehmer_id=? AND runde='vorlauf'",
                                (t["id"],)).fetchone()
                zeiten.append((scoring.stafette_endzeit(vr, kat) or 9e9, t["id"]))
            zeiten.sort()
            for i, (_, tid) in enumerate(zeiten):
                set_bahn(tid, serie, LANE_ORDER[i] if i < len(LANE_ORDER) else i + 1)
    else:
        # Grundlage Vorjahr NUR für Gruppe 1 je Verein; übrige Gruppen auf andere Serien.
        sparte = "Turner" if (kat["geschlecht"] or "m") == "m" else "Turnerinnen"
        aktive = [t for t in teams if not (t["status"] or "")]

        def vjz(t):
            vj = db.execute(
                "SELECT zeit FROM vorjahr WHERE disziplin=? AND verein=? "
                "AND (sparte=? OR sparte IS NULL) ORDER BY zeit LIMIT 1",
                (kat["bezeichnung"], t["verein_name"], sparte)).fetchone()
            return vj["zeit"] if vj and vj["zeit"] is not None else 9e9

        g1 = sorted([t for t in aktive if (t["gruppennr"] or 1) == 1], key=vjz)
        rest = sorted([t for t in aktive if (t["gruppennr"] or 1) != 1],
                      key=lambda t: ((t["verein_name"] or ""), t["gruppennr"] or 0))
        n = len(aktive)
        anz_serien = max(1, (n + bahnen - 1) // bahnen)
        serien = {s: [] for s in range(1, anz_serien + 1)}
        v_in_serie = {s: set() for s in range(1, anz_serien + 1)}

        if kat["hat_final"]:
            # 4x100m-Vorläufe: Gruppe-1-Teams serpentinenartig über alle Serien
            for idx, t in enumerate(g1):
                r = idx // anz_serien
                pos = idx % anz_serien
                s = (pos if r % 2 == 0 else anz_serien - 1 - pos) + 1
                serien[s].append(t["id"]); v_in_serie[s].add(t["verein_name"])
        else:
            # Endläufe: Gruppe-1-Teams (schnellste nach Vorjahr) in die letzte Serie
            for idx, t in enumerate(g1):
                s = max(1, anz_serien - (idx // bahnen))
                serien[s].append(t["id"]); v_in_serie[s].add(t["verein_name"])

        # übrige Gruppen auf andere Serien verteilen (möglichst nicht zum eigenen Verein)
        for t in rest:
            kandidaten = [s for s in serien if len(serien[s]) < bahnen]
            if not kandidaten:
                anz_serien += 1
                serien[anz_serien] = []; v_in_serie[anz_serien] = set()
                kandidaten = [anz_serien]
            ohne = [s for s in kandidaten if t["verein_name"] not in v_in_serie[s]]
            wahl = min(ohne or kandidaten, key=lambda s: len(serien[s]))
            serien[wahl].append(t["id"]); v_in_serie[wahl].add(t["verein_name"])

        for s, ids in serien.items():
            for i, tid in enumerate(ids):
                set_bahn(tid, s, LANE_ORDER[i] if i < len(LANE_ORDER) else i + 1)
    db.commit()
    flash("Bahnen automatisch zugeteilt (manuell anpassbar).", "ok")
    return redirect(url_for("stafette_bahnen", kid=kid, runde=runde))


@app.route("/stafetten/<int:kid>/bahnen/druck")
@chef_required
def stafette_bahnen_druck(kid):
    db = g.db
    kat = db.execute("SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
                     "WHERE k.id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    runde = request.args.get("runde", "vorlauf" if kat["hat_final"] else "final")
    serien = _serien_lanes(db, kat, runde)
    return render_template("notenblatt_lauf_druck.html", kat=kat, runde=runde, serien=serien)


@app.route("/import/excel", methods=["GET", "POST"])
@chef_required
def excel_import():
    """Schritt 1: Excel hochladen -> Spalten automatisch zuordnen -> prüfen."""
    from debra import excel_import as X
    if request.method == "POST":
        datei = request.files.get("datei")
        if not datei or not datei.filename:
            flash("Bitte eine Excel-Datei (.xlsx) auswählen.", "error")
            return redirect(url_for("excel_import"))
        import tempfile
        fd, pfad = tempfile.mkstemp(suffix=".xlsx", prefix="debra_up_")
        os.close(fd)
        datei.save(pfad)
        try:
            sheets = X.parse(pfad)
        except Exception as exc:  # noqa: BLE001
            flash(f"Excel konnte nicht gelesen werden: {exc}", "error")
            return redirect(url_for("excel_import"))
        if not sheets:
            flash("Keine Anmeldedaten gefunden (Blätter mit Kopfzeile „Verein“).", "error")
            return redirect(url_for("excel_import"))
        vorschlag = X.auto_map(g.db, sheets)
        kats = X.kategorien_je_sparte(g.db)
        summen = {sh["sparte"]: sum(sum(z["counts"].values()) for z in sh["zeilen"]) for sh in sheets}
        return render_template("excel_pruefen.html", sheets=sheets, vorschlag=vorschlag,
                               kats=kats, pfad=pfad, summen=summen)
    return render_template("excel_upload.html")


@app.route("/import/excel/uebernehmen", methods=["POST"])
@chef_required
def excel_uebernehmen():
    """Schritt 2: geprüfte Zuordnung übernehmen und Anmeldungen anlegen."""
    from debra import excel_import as X
    pfad = request.form.get("pfad", "")
    if not pfad or not os.path.exists(pfad):
        flash("Die hochgeladene Datei ist nicht mehr verfügbar. Bitte erneut hochladen.", "error")
        return redirect(url_for("excel_import"))
    mapping = {}
    for key, val in request.form.items():
        if key.startswith("map|"):
            mapping[key[4:]] = int(val) if val else None
    reset = bool(request.form.get("reset"))
    try:
        n = X.importieren(g.db, pfad, mapping, reset=reset)
        flash(f"Import abgeschlossen: {n} Anmeldungen angelegt"
              + (" (bestehende ersetzt)." if reset else "."), "ok")
    except Exception as exc:  # noqa: BLE001
        flash(f"Import fehlgeschlagen: {exc}", "error")
    finally:
        try:
            os.remove(pfad)
        except OSError:
            pass
    return redirect(url_for("teilnehmer"))


@app.route("/listen")
@chef_required
def listen():
    return render_template("listen.html")


def _startliste_daten(db):
    return db.execute(
        "SELECT t.startnr, t.gruppennr, t.verband, v.name AS verein_name, "
        "v.name || COALESCE(' '||t.verein_zusatz,'') AS verein_voll, "
        "k.bezeichnung AS kat_name, k.sortierung AS kat_sort, w.name AS wk_name, w.id AS wk_id "
        "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
        "JOIN kategorie k ON k.id=t.kategorie_id JOIN wettkampf w ON w.id=t.wettkampf_id "
        "ORDER BY w.id, t.startnr").fetchall()


@app.route("/listen/startliste/druck")
@chef_required
def startliste_druck():
    db = g.db
    nach = request.args.get("nach", "verein")   # verein | kategorie | startnr
    rows = _startliste_daten(db)
    bloecke = []   # Liste von {titel, wk, gruppen: [{kopf, anzahl, zeilen}]}
    for w in db.execute("SELECT * FROM wettkampf ORDER BY id").fetchall():
        wrows = [r for r in rows if r["wk_id"] == w["id"]]
        if not wrows:
            continue
        gruppen = []
        if nach == "verein":
            keyf = lambda r: (r["verein_name"] or "")
            wrows_s = sorted(wrows, key=lambda r: ((r["verein_name"] or ""), r["kat_name"], r["startnr"]))
            from itertools import groupby
            for key, grp in groupby(wrows_s, key=keyf):
                grp = list(grp)
                gruppen.append({"kopf": key, "verband": grp[0]["verband"] or "",
                                "anzahl": len(grp), "zeilen": grp})
        elif nach == "kategorie":
            wrows_s = sorted(wrows, key=lambda r: (r["kat_sort"] or 0, r["kat_name"], r["startnr"]))
            from itertools import groupby
            for key, grp in groupby(wrows_s, key=lambda r: r["kat_name"]):
                grp = list(grp)
                gruppen.append({"kopf": key, "verband": "", "anzahl": len(grp), "zeilen": grp})
        else:  # startnr (flach)
            gruppen.append({"kopf": None, "verband": "", "anzahl": len(wrows),
                            "zeilen": sorted(wrows, key=lambda r: r["startnr"])})
        bloecke.append({"wk": w, "gruppen": gruppen, "gesamt": len(wrows)})
    return render_template("startliste_druck.html", bloecke=bloecke, nach=nach)


@app.route("/listen/statistik/druck")
@chef_required
def statistik_druck():
    db = g.db
    import math
    bloecke = []
    for w in db.execute("SELECT * FROM wettkampf ORDER BY id").fetchall():
        zeilen = []
        tot_gruppen = tot_teiln = 0
        for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY bezeichnung",
                            (w["id"],)).fetchall():
            gruppen = db.execute("SELECT COUNT(*) c FROM teilnehmer WHERE kategorie_id=?",
                                 (k["id"],)).fetchone()["c"]
            mitglieder = k["anzahl_werte"] or (5 if (k["geschlecht"] or "m") == "m" else 4)
            teiln = gruppen * mitglieder
            zeilen.append({"kat": k["bezeichnung"], "einsaetze": gruppen, "teilnehmer": teiln,
                           "a30": math.ceil(gruppen * 0.30), "a33": math.ceil(gruppen * 0.33),
                           "a40": math.ceil(gruppen * 0.40)})
            tot_gruppen += gruppen
            tot_teiln += teiln
        bloecke.append({"wk": w, "zeilen": zeilen, "tot_gruppen": tot_gruppen, "tot_teiln": tot_teiln})
    return render_template("statistik_druck.html", bloecke=bloecke)


@app.route("/vorjahr")
@chef_required
def vorjahr_ansicht():
    db = g.db
    bloecke = {}
    for r in db.execute("SELECT * FROM vorjahr ORDER BY sparte, disziplin, rang").fetchall():
        bloecke.setdefault((r["sparte"], r["disziplin"]), []).append(r)
    return render_template("vorjahr.html", bloecke=bloecke, fmt_zeit=scoring.fmt_zeit)


@app.route("/vorjahr/import", methods=["POST"])
@chef_required
def vorjahr_import():
    from debra import vorjahr as vj
    pfad = (request.form.get("pdf_pfad") or "").strip() or None
    try:
        n = vj.importieren(conn=g.db, pdf_pfad=pfad)
        flash(f"Vorjahres-Rangliste importiert: {n} Stafetten-Resultate.", "ok")
    except Exception as exc:  # pragma: no cover
        flash(f"Import fehlgeschlagen: {exc}", "error")
    return redirect(url_for("einstellungen"))


# Schema beim Import aktualisieren (auch unter waitress, nicht nur bei python app.py)
try:
    init_db()
except Exception:  # noqa: BLE001
    pass


if __name__ == "__main__":
    init_db()
    # Beim ersten Start Demo-Daten anlegen, falls DB leer ist.
    conn = get_db()
    leer = conn.execute("SELECT COUNT(*) c FROM wettkampf").fetchone()["c"] == 0
    conn.close()
    if leer:
        seed()
    # host=0.0.0.0 macht den Server im LAN erreichbar (Mehrplatzbetrieb).
    # Für den produktiven Betrieb: waitress-serve --host=0.0.0.0 --port=5000 app:app
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
