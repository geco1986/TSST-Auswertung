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
from debra import __version__, scoring
from debra.seed import seed

app = Flask(__name__)
app.secret_key = os.environ.get("DEBRA_SECRET", "debra-turnverein-dev-key")
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024     # Upload von Import-Dateien (ZIP/Backups)

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


# Konfiguration ist für den Superuser vom Umschalter TSST/JTSST/JET ausgenommen (zeigt alle Anlässe).
KONFIGURATION = {"kategorie_form", "kategorie_loeschen"}

# Rollen: eingeber < chef < superuser. Der Superuser wählt den aktiven Anlass und pflegt die
# JET-Wertungsformeln; der Chef bearbeitet nur den aktiv gesetzten Anlass.
ROLLEN = {"eingeber": "Eingeber", "chef": "Chef", "superuser": "Superuser"}


def _ist_chef():
    return session.get("rolle") in ("chef", "superuser")


def _ist_superuser():
    return session.get("rolle") == "superuser"


@app.before_request
def load_context():
    g.db = get_db()
    g.wettkampf = get_active_wettkampf(g.db) if session.get("user") else None
    g.rolle = session.get("rolle", "eingeber")
    # Seiten einer Kategorie/Gruppe nur im oben gewählten Anlass öffnen
    args = request.view_args or {}
    if g.wettkampf and (request.endpoint not in KONFIGURATION or not _ist_superuser()) \
            and ("kid" in args or "tid" in args):
        tabelle, oid = ("kategorie", args["kid"]) if "kid" in args else ("teilnehmer", args["tid"])
        row = g.db.execute(f"SELECT wettkampf_id FROM {tabelle} WHERE id=?", (oid,)).fetchone()
        if row and row["wettkampf_id"] != g.wettkampf["id"]:
            flash("Diese Seite gehört zum anderen Anlass – bitte oben rechts umschalten.", "error")
            return redirect(url_for("dashboard"))


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
        if not _ist_chef():
            flash("Dieser Bereich ist nur für die Rolle „Chef“.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def superuser_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        if not _ist_superuser():
            flash("Dieser Bereich ist nur für den Superuser.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def _eingabe_pfad(text, standard=""):
    """Pfad aus einem Formularfeld: relativ = zum Programmordner; Windows-Schreibweise
    (Inputs\\jet\\Backup) funktioniert auch im Linux-Container. Leer -> standard bzw. None."""
    v = (text or "").strip().strip('"') or standard
    if not v:
        return None
    if os.sep == "/":
        v = v.replace("\\", "/")
    from debra.db import pfad_finden
    return pfad_finden(v if os.path.isabs(v) else os.path.join(os.path.dirname(os.path.abspath(__file__)), v))


UPLOAD_ENDUNGEN = (".zip", ".txt", ".xls", ".xlsx", ".pdf", ".mdb", ".csv")


def _upload_speichern(feld="dateien"):
    """Speichert hochgeladene Import-Dateien in einen neuen Ordner neben der Datenbank
    (…/uploads/<Zeitstempel>) und entpackt ZIP-Dateien. Liefert den Ordner oder None.

    So funktionieren alle Importe auch im Container ohne Zugriff auf Dateipfade.
    """
    import shutil
    import time
    import zipfile
    from datetime import datetime
    dateien = [f for f in request.files.getlist(feld) if f and f.filename]
    if not dateien:
        return None
    basis = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "uploads")
    os.makedirs(basis, exist_ok=True)
    for alt in os.listdir(basis):                      # Uploads älter als 14 Tage aufräumen
        pfad = os.path.join(basis, alt)
        if os.path.isdir(pfad) and time.time() - os.path.getmtime(pfad) > 14 * 86400:
            shutil.rmtree(pfad, ignore_errors=True)
    ziel = os.path.join(basis, datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    os.makedirs(ziel)

    def sicherer_name(name):
        name = os.path.basename(name.replace("\\", "/")).strip().strip(".")
        return "".join(ch for ch in name if ch not in '<>:"|?*' and ord(ch) >= 32) or "datei"

    for f in dateien:
        name = sicherer_name(f.filename)
        if not name.lower().endswith(UPLOAD_ENDUNGEN):
            raise ValueError(f"„{name}“: erlaubt sind {', '.join(UPLOAD_ENDUNGEN)}")
        pfad = os.path.join(ziel, name)
        f.save(pfad)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(pfad) as z:
                for info in z.infolist():
                    teile = [t for t in info.filename.replace("\\", "/").split("/") if t not in ("", ".")]
                    if info.is_dir() or not teile or ".." in teile:
                        continue                       # Verzeichnisse und unsichere Pfade überspringen
                    if not teile[-1].lower().endswith(UPLOAD_ENDUNGEN) or teile[0] == "__MACOSX":
                        continue
                    aus = os.path.join(ziel, *[sicherer_name(t) for t in teile])
                    os.makedirs(os.path.dirname(aus), exist_ok=True)
                    with z.open(info) as quelle, open(aus, "wb") as senke:
                        shutil.copyfileobj(quelle, senke)
            os.remove(pfad)
    return ziel


def _finde_ordner(wurzel, *muster):
    """Erster Ordner unterhalb von wurzel, der Dateien eines der Muster enthält (z. B. 'WT_*.txt')."""
    import glob
    for ordner, _, _ in sorted(os.walk(wurzel), key=lambda x: (x[0].count(os.sep), x[0])):
        if any(glob.glob(os.path.join(ordner, m)) for m in muster):
            return ordner
    return wurzel


def _upload_oder_pfad(feld_pfad, *muster, standard=""):
    """Hochgeladene Dateien (Vorrang) bzw. der eingegebene Pfad auf dem Server."""
    ordner = _upload_speichern()
    if ordner:
        return _finde_ordner(ordner, *muster) if muster else ordner
    return _eingabe_pfad(request.form.get(feld_pfad), standard)


def _darf_anlass(art):
    """Chef: nur der aktive Anlass; Superuser: alle. Sonst Hinweis und False."""
    if _ist_superuser() or (g.wettkampf and _art(g.db, g.wettkampf) == art):
        return True
    flash(f"Der {ANLAESSE.get(art, art)} ist nicht der aktive Anlass – nur der Superuser kann ihn bearbeiten "
          "bzw. aktiv setzen.", "error")
    return False


# Abgemeldete Gruppen erscheinen in keiner Erfassung und zählen nicht zum Fortschritt.
OHNE_ABGEMELDETE = "COALESCE(t.status,'')<>'abgem'"


def _fortschritt(db, kat):
    """(gruppen, erledigt) einer Kategorie für Startseite und Erfassungskontrolle.

    Gruppen = alle ausser abgemeldeten. Erledigt = Resultat erfasst (auch DNS/DNF einzelner
    Mitglieder) oder Gruppe mit Vermerk (n.Ges., Aufg., Unfall, a.K., Disq) – diese
    fliessen in die Auswertung ein, es fehlt also nichts mehr.
    """
    gruppen = db.execute(f"SELECT COUNT(*) c FROM teilnehmer t WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE}",
                         (kat["id"],)).fetchone()["c"]
    resultat = ("EXISTS (SELECT 1 FROM stafette s WHERE s.teilnehmer_id=t.id AND s.rohzeit IS NOT NULL)"
                if kat["ist_stafette"] else
                "EXISTS (SELECT 1 FROM resultat r WHERE r.teilnehmer_id=t.id "
                "AND (r.note IS NOT NULL OR r.status IN ('dns','dnf')))")
    erledigt = db.execute(
        f"SELECT COUNT(*) c FROM teilnehmer t WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} "
        f"AND (COALESCE(t.status,'')<>'' OR {resultat})", (kat["id"],)).fetchone()["c"]
    return gruppen, erledigt


# Die Software kennt drei Anlässe: TSST (Turner/Turnerinnen), JTSST (Jugend, Gruppen) und
# JET (Jugend-Einzelturntag). Eingabe, Listen und Ranglisten zeigen immer nur den oben gewählten.
ANLAESSE = {"tsst": "TSST", "jtsst": "JTSST", "jet": "JET"}
ANLASS_TITEL = {"tsst": "Turn-, Spiel- und Stafettentag", "jtsst": "Jugend Turn-, Spiel- und Stafettentag",
                "jet": "Jugend-Einzelturntag"}


def _anlaesse(db):
    """{'tsst'|'jtsst'|'jet': wettkampf-row|None} – erkannt an Namen und Sparten."""
    from debra.jet import EVENT_NAME as JET_NAME
    from debra.jtsst import EVENT_NAME as JTSST_NAME
    res = {art: None for art in ANLAESSE}
    for w in db.execute(
            "SELECT w.*, MAX(k.sparte LIKE 'JET %') AS jet, MAX(k.sparte IN ('Knaben','Mädchen')) AS jugend, "
            "MAX(k.sparte IN ('Turner','Turnerinnen')) AS aktive FROM wettkampf w "
            "LEFT JOIN kategorie k ON k.wettkampf_id=w.id GROUP BY w.id ORDER BY w.id").fetchall():
        if w["jet"] or w["name"] == JET_NAME:
            art = "jet"
        elif w["jugend"] or w["name"] == JTSST_NAME:
            art = "jtsst"
        else:
            art = "tsst" if w["aktive"] else None
        if art and res[art] is None:
            res[art] = w
    return res


def _art(db, wettkampf):
    """Art des Anlasses ('tsst' | 'jtsst' | 'jet') eines Wettkampfs, sonst None."""
    if not wettkampf:
        return None
    for art, w in _anlaesse(db).items():
        if w and w["id"] == wettkampf["id"]:
            return art
    return None


def _anlass_titel(db):
    try:
        w = db.execute("SELECT name, datum FROM wettkampf ORDER BY aktiv DESC, id LIMIT 1").fetchone()
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
    db = g.get("db")
    anlaesse = _anlaesse(db) if db is not None and session.get("user") else {}
    art = None
    if g.get("wettkampf"):
        art = next((a for a, w in anlaesse.items() if w and w["id"] == g.wettkampf["id"]), None)
    return {"anlaesse": anlaesse,
            "ANLAESSE": ANLAESSE, "ANLASS_TITEL": ANLASS_TITEL, "anlass_art": art,
            "aktueller_user": session.get("user"),
            "aktuelle_rolle": session.get("rolle", "eingeber"),
            "ist_chef": _ist_chef(),
            "ist_superuser": _ist_superuser(),
            "ROLLEN": ROLLEN,
            "VERSION": __version__,
            "kennung": session.get("kennung", ""),
            "aktueller_wettkampf": g.get("wettkampf"),
            "anlass_titel": _anlass_titel(g.db) if g.get("db") is not None else "",
            "fmt_zeit": scoring.fmt_zeit,
            "KATEGORIE_TYPEN": KATEGORIE_TYPEN}


@app.route("/login", methods=["GET", "POST"])
def login():
    from werkzeug.security import check_password_hash, generate_password_hash
    pw_hash = get_setting("superuser_passwort")
    if request.method == "POST":
        rolle = request.form.get("rolle", "eingeber")
        if rolle not in ROLLEN:
            rolle = "eingeber"
        if rolle == "superuser":
            pw = request.form.get("passwort") or ""
            if not pw_hash:
                # erste Anmeldung: Passwort festlegen
                if len(pw) < 6 or pw != (request.form.get("passwort2") or ""):
                    flash("Superuser-Passwort festlegen: mindestens 6 Zeichen, zweimal gleich eingeben.", "error")
                    return render_template("login.html", pw_gesetzt=False, super_offen=True)
                set_setting("superuser_passwort", generate_password_hash(pw))
                flash("Superuser-Passwort festgelegt.", "ok")
            elif not check_password_hash(pw_hash, pw):
                flash("Falsches Superuser-Passwort.", "error")
                return render_template("login.html", pw_gesetzt=True, super_offen=True)
        session.clear()
        session["user"] = ROLLEN[rolle]
        session["rolle"] = rolle
        kennung = (request.form.get("kennung") or "").strip()
        session["kennung"] = kennung or ("Eingabe" if rolle == "eingeber" else ROLLEN[rolle])
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("login.html", pw_gesetzt=bool(pw_hash), super_offen=False)


@app.route("/superuser/passwort", methods=["POST"])
@superuser_required
def superuser_passwort():
    """Superuser-Passwort ändern (Einstellungen → Allgemein → Superuser)."""
    from werkzeug.security import check_password_hash, generate_password_hash
    alt, neu, neu2 = (request.form.get(k) or "" for k in ("alt", "neu", "neu2"))
    if not check_password_hash(get_setting("superuser_passwort") or "", alt):
        flash("Bisheriges Passwort stimmt nicht.", "error")
    elif len(neu) < 6 or neu != neu2:
        flash("Neues Passwort: mindestens 6 Zeichen, zweimal gleich eingeben.", "error")
    else:
        set_setting("superuser_passwort", generate_password_hash(neu))
        flash("Superuser-Passwort geändert.", "ok")
    return redirect(url_for("einstellungen") + "#allgemein/superuser")


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
            f"SELECT COUNT(*) c FROM teilnehmer t WHERE t.wettkampf_id=? AND {OHNE_ABGEMELDETE}", (wk["id"],)
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
            tn, mit = _fortschritt(db, k)
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
    if request.method == "POST" and not _ist_superuser():
        flash("Wettkämpfe anlegen kann nur der Superuser.", "error")
        return redirect(url_for("wettkaempfe"))
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
@superuser_required
def wettkampf_aktiv(wid):
    db = g.db
    db.execute("UPDATE wettkampf SET aktiv=0")
    db.execute("UPDATE wettkampf SET aktiv=1 WHERE id=?", (wid,))
    db.commit()
    flash("Aktiver Wettkampf gewechselt.", "ok")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/anlass/<art>", methods=["POST"])
@superuser_required
def anlass_wechseln(art):
    """Umschalter oben rechts: TSST, JTSST oder JET als aktiven Anlass setzen."""
    if art not in ANLAESSE:
        abort(404)
    db = g.db
    w = _anlaesse(db)[art]
    if w is None and art == "jtsst":
        from debra.jtsst import anlegen
        anlegen(db)
        w = _anlaesse(db)[art]
    if w is None and art == "jet":
        from debra.jet import anlegen
        anlegen(db)
        w = _anlaesse(db)[art]
    if w is None:
        flash("Der TSST ist noch nicht angelegt – unter Einstellungen das DEBRA-Backup bzw. "
              "die Anmeldungen importieren.", "error")
        return redirect(url_for("einstellungen") + "#tsst/import")
    db.execute("UPDATE wettkampf SET aktiv=(id=?)", (w["id"],))
    db.commit()
    flash(f"Aktiver Anlass: {ANLAESSE[art]} – {w['name']}", "ok")
    # Auf der gleichen Seite bleiben – ausser sie gehört zu einer Kategorie/Gruppe des anderen Anlasses
    zurueck = request.form.get("zurueck") or ""
    if not zurueck.startswith("/") or zurueck.startswith("//") or any(c.isdigit() for c in zurueck):
        zurueck = url_for("dashboard")
    return redirect(zurueck)


@app.route("/wettkaempfe/<int:wid>/loeschen", methods=["POST"])
@superuser_required
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


def _aktiver_anlass():
    """Wettkämpfe, die Listen/Auswertungen zeigen: nur der oben gewählte Anlass."""
    return [g.wettkampf] if g.wettkampf else []


@app.route("/kategorien")
@chef_required
def kategorien():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    db = g.db
    # Superuser: Kategorien aller Anlässe; Chef: nur der aktive Anlass
    liste = db.execute(
        "SELECT k.*, w.name AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        + ("" if _ist_superuser() else "WHERE k.wettkampf_id=? ")
        + "ORDER BY k.wettkampf_id, k.sortierung, k.bezeichnung",
        () if _ist_superuser() else (g.wettkampf["id"],)).fetchall()
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


def _jet_kategorie_pruefen(db, kid, jahrgang, geschlecht):
    """JET: passt der Jahrgang (und das Geschlecht) zur Kategorie?

    Liefert (meldung, vorschlag_kategorie_id) bei einer Abweichung, sonst None.
    Die Kategorie ergibt sich aus dem Alter im Wettkampfjahr (WKB 3.).
    """
    from debra import jet
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone() if kid else None
    if not kat or kat["berechnung"] != "jet":
        return None
    jahr = int(((g.wettkampf["datum"] if g.wettkampf else None) or jet.EVENT_DATUM)[:4])
    gesch = geschlecht or kat["geschlecht"]
    if not jahrgang:
        return "Beim JET ist der Jahrgang nötig – er bestimmt die Kategorie.", None
    soll = jet.kategorie_aus_jahrgang(jahrgang, jahr)
    if soll is None:
        return f"Jahrgang {jahrgang} ist im JET {jahr} nicht startberechtigt (Kategorien A–E: " \
               f"{jahr - 16} und jünger).", None
    vorschlag = db.execute("SELECT id, bezeichnung FROM kategorie WHERE wettkampf_id=? AND berechnung='jet' "
                           "AND geschlecht=? AND abk=?", (kat["wettkampf_id"], gesch,
                                                          ("K" if gesch == "m" else "M") + soll)).fetchone()
    if gesch != kat["geschlecht"]:
        return (f"Geschlecht passt nicht zur Kategorie „{kat['bezeichnung']}“."
                + (f" Richtig wäre „{vorschlag['bezeichnung']}“." if vorschlag else "")), \
            vorschlag["id"] if vorschlag else None
    if soll != jet.kat_buchstabe(kat):
        return (f"Jahrgang {jahrgang} gehört in Kategorie {soll}, gewählt ist „{kat['bezeichnung']}“."
                + (f" Richtig wäre „{vorschlag['bezeichnung']}“." if vorschlag else "")), \
            vorschlag["id"] if vorschlag else None
    return None


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
        felder = list(felder)
        ist_jet = _art(db, g.wettkampf) == "jet"
        if ist_jet and not felder[6] and felder[3] and felder[4] in ("m", "w"):
            # JET ohne gewählte Kategorie: aus Jahrgang und Geschlecht bestimmen
            from debra import jet
            k = jet.kategorie_aus_jahrgang(felder[3], int((g.wettkampf["datum"] or jet.EVENT_DATUM)[:4]))
            row = db.execute("SELECT id FROM kategorie WHERE wettkampf_id=? AND berechnung='jet' AND abk=?",
                             (g.wettkampf["id"], ("K" if felder[4] == "m" else "M") + (k or "?"))).fetchone()
            felder[6] = row["id"] if row else None
        if ist_jet and felder[6] and not felder[4]:
            felder[4] = db.execute("SELECT geschlecht FROM kategorie WHERE id=?", (felder[6],)).fetchone()[0]
        pruefung = _jet_kategorie_pruefen(db, felder[6], felder[3], felder[4]) if ist_jet else None
        felder = tuple(felder)
        abweichung_ok = _ist_chef() and request.form.get("abweichung_ok")
        if not felder[2] and not felder[5]:
            flash("Bitte einen Namen oder einen Verein angeben.", "error")
        elif ist_jet and not felder[6]:
            flash("Bitte eine Kategorie wählen (oder Jahrgang und Geschlecht angeben).", "error")
        elif pruefung and not abweichung_ok:
            flash(pruefung[0] + ("" if _ist_chef() else " Nur der Chef kann eine Abweichung übernehmen."),
                  "error")
            eingabe = dict(zip(("startnr", "vorname", "nachname", "jahrgang", "geschlecht", "verein_id",
                                "kategorie_id", "stationsnr", "status", "bemerkung"), felder), id=tid)
            return _teilnehmer_form_seite(db, eingabe, pruefung)
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
    return _teilnehmer_form_seite(db, tn, None)


def _teilnehmer_form_seite(db, tn, pruefung):
    from debra import jet
    vereine = db.execute("SELECT * FROM verein ORDER BY name").fetchall()
    kategorien = db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                            (g.wettkampf["id"],)).fetchall()
    naechste_nr = db.execute("SELECT COALESCE(MAX(startnr),0)+1 n FROM teilnehmer WHERE wettkampf_id=?",
                             (g.wettkampf["id"],)).fetchone()["n"]
    jet_info = None
    if _art(db, g.wettkampf) == "jet":
        # für den Hinweis im Formular: Kategorie -> [Geschlecht, A–E], Altersgrenzen, Wettkampfjahr
        jet_info = {"jahr": int((g.wettkampf["datum"] or jet.EVENT_DATUM)[:4]),
                    "kats": {k["id"]: [k["geschlecht"], jet.kat_buchstabe(k)] for k in kategorien
                             if k["berechnung"] == "jet"},
                    "alter": {k: [v[2], v[3]] for k, v in jet.KATEGORIEN.items()}}
    return render_template("teilnehmer_form.html", tn=tn, vereine=vereine,
                           kategorien=kategorien, naechste_nr=naechste_nr,
                           status_labels=scoring.STATUS_LABELS, jet_info=jet_info, pruefung=pruefung)


@app.route("/teilnehmer/<int:tid>/loeschen", methods=["POST"])
@chef_required
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
        # Löschen nur Chef/Superuser – Eingeber melden ab (bleibt nachvollziehbar, zählt zur Preisbasis)
        if not _ist_chef():
            flash("Löschen kann nur der Chef – Teilnehmende bitte auf „Abgemeldet“ setzen.", "error")
            return redirect(ziel)
        db.execute(f"DELETE FROM teilnehmer WHERE id IN ({marks})", ids)
        for tid in ids:
            _log(db, "loeschen", tid, None, "Teilnehmer", "vorhanden", "gelöscht")
        flash(f"{len(ids)} Anmeldung(en) gelöscht.", "ok")
    elif aktion == "abmelden":
        db.execute(f"UPDATE teilnehmer SET status='abgem' WHERE id IN ({marks})", ids)
        for tid in ids:
            _log(db, "vermerk", tid, None, "Vermerk", "", "abgem")
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
    wk_id = g.wettkampf["id"] if g.wettkampf else 0
    if q:
        if q.isdigit():
            treffer = db.execute(
                "SELECT t.*, v.name AS verein_name, k.bezeichnung AS kat_name, COALESCE(k.sparte, w.name) AS wk_name "
                "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
                "LEFT JOIN kategorie k ON k.id=t.kategorie_id "
                "LEFT JOIN wettkampf w ON w.id=t.wettkampf_id "
                "WHERE t.startnr=? AND t.wettkampf_id=? ORDER BY t.startnr", (int(q), wk_id)).fetchall()
        else:
            treffer = db.execute(
                "SELECT t.*, v.name AS verein_name, k.bezeichnung AS kat_name, COALESCE(k.sparte, w.name) AS wk_name "
                "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
                "LEFT JOIN kategorie k ON k.id=t.kategorie_id "
                "LEFT JOIN wettkampf w ON w.id=t.wettkampf_id "
                "WHERE v.name LIKE ? AND t.wettkampf_id=? ORDER BY v.name, k.sortierung, t.startnr",
                (f"%{q}%", wk_id)).fetchall()
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
    if _art(g.db, g.wettkampf) == "jet":
        return redirect(url_for("jet_erfassung"))
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
    if _art(db, g.wettkampf) == "jet":
        # JET: Erfassung je Teilnehmer:in mit Messwert -> Note über die Wertungstabelle
        return redirect(url_for("jet_schnellerfassung", nr=request.values.get("nr", type=int)))

    if request.method == "POST" and request.form.get("aktion") == "speichern":
        tid = request.form.get("tid", type=int)
        t = db.execute("SELECT * FROM teilnehmer WHERE id=? AND wettkampf_id=?", (tid, wk_id)).fetchone()
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
        # nur Startnummern des oben gewählten Anlasses
        t = db.execute(
            "SELECT t.*, v.name AS verein_name, COALESCE(k.sparte, w.name) AS wk_name FROM teilnehmer t "
            "LEFT JOIN verein v ON v.id=t.verein_id "
            "LEFT JOIN kategorie k ON k.id=t.kategorie_id "
            "LEFT JOIN wettkampf w ON w.id=t.wettkampf_id "
            "WHERE t.startnr=? AND t.wettkampf_id=? LIMIT 1", (nr, wk_id)).fetchone()
        if t is None:
            anders = db.execute("SELECT w.name FROM teilnehmer t JOIN wettkampf w ON w.id=t.wettkampf_id "
                                "WHERE t.startnr=? LIMIT 1", (nr,)).fetchone()
            if anders:
                flash(f"Startnummer {nr} gehört zum anderen Anlass ({anders['name']}) – "
                      "bitte oben umschalten.", "error")
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
    if kat["berechnung"] == "jet":
        return redirect(url_for("jet_erfassung", kat=kid))
    if "ist_stafette" in kat.keys() and kat["ist_stafette"]:
        # Stafetten werden im Stafetten-Modul bzw. per Schnellerfassung erfasst
        if _ist_chef():
            return redirect(url_for("stafette_verwalten", kid=kid))
        flash("Stafetten bitte über die Schnellerfassung erfassen.", "ok")
        return redirect(url_for("schnellerfassung"))
    positionen, diszs, disz_bez, einheit, berechnung, richtung, anzahl_werte = \
        _kat_positionen(db, kat)

    teilnehmende = db.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t "
        f"LEFT JOIN verein v ON v.id=t.verein_id WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} "
        "ORDER BY t.startnr", (kid,)).fetchall()

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
    status = {k["id"]: _rl_status(g.db, k) for k in kategorien}
    return render_template("rangliste_index.html", kategorien=kategorien, status=status,
                           nicht_bereit=_gesamt_pruefung(g.db, g.wettkampf))


def _rl_status(db, kat):
    """Workflow-Status einer Rangliste: eingegeben → kontrolliert → gedruckt → Fertig (WKL).

    eingegeben: jede:r Teilnehmende (ohne Abgemeldete) hat ein Resultat oder einen Vermerk.
    kontrolliert: alle erfassten Resultate per Kontrollblatt quittiert (Stafetten: entfällt).
    offen: Teilnehmende ohne Eintrag – solange es solche gibt, kann nicht „gedruckt“ werden.
    """
    kid = kat["id"]
    gruppen, erledigt = _fortschritt(db, kat)
    offen = db.execute(
        f"SELECT t.startnr, t.vorname, t.nachname, v.name AS verein, t.gruppennr FROM teilnehmer t "
        f"LEFT JOIN verein v ON v.id=t.verein_id WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} "
        "AND COALESCE(t.status,'')='' AND NOT EXISTS (SELECT 1 FROM resultat r WHERE r.teilnehmer_id=t.id "
        "AND (r.note IS NOT NULL OR r.status IN ('dns','dnf'))) AND NOT EXISTS (SELECT 1 FROM stafette s "
        "WHERE s.teilnehmer_id=t.id AND s.rohzeit IS NOT NULL) ORDER BY t.startnr", (kid,)).fetchall()
    if kat["ist_stafette"]:
        kontrolliert = None                     # Stafetten laufen nicht über das Kontrollblatt
    else:
        mit = db.execute(f"SELECT COUNT(*) c, SUM(t.kontrolliert_am IS NOT NULL) k FROM teilnehmer t "
                         f"WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} AND EXISTS (SELECT 1 FROM resultat r "
                         "WHERE r.teilnehmer_id=t.id)", (kid,)).fetchone()
        kontrolliert = bool(mit["c"]) and (mit["k"] or 0) >= mit["c"]
    return {
        "gruppen": gruppen, "erledigt": erledigt, "offen": len(offen),
        "offen_liste": [(o["startnr"], (f"{o['vorname'] or ''} {o['nachname'] or ''}".strip()
                         or f"{o['verein'] or ''} {o['gruppennr'] or ''}".strip())) for o in offen[:12]],
        "eingegeben": gruppen > 0 and not offen,
        "kontrolliert": kontrolliert,
        "gedruckt": bool(kat["rl_gedruckt"]),
        "fertig": bool(kat["rl_fertig"]),
        "fertig_von": kat["rl_fertig_von"] or "",
    }


def _gesamt_pruefung(db, wk):
    """Ranglisten der Gesamt-Rangliste, die noch nicht kontrolliert bzw. von der WKL freigegeben sind."""
    nicht_bereit = []
    for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? AND rl_drucken=1 "
                        "ORDER BY sortierung, bezeichnung", (wk["id"],)).fetchall():
        st = _rl_status(db, k)
        if not st["gruppen"]:
            continue
        fehlt = []
        if not st["eingegeben"]:
            fehlt.append(f"{st['offen']} ohne Eintrag")
        if st["kontrolliert"] is False:
            fehlt.append("nicht kontrolliert")
        if not st["fertig"]:
            fehlt.append("WKL-Freigabe fehlt")
        if fehlt:
            nicht_bereit.append({"kat": k, "fehlt": fehlt})
    return nicht_bereit


@app.route("/rangliste/<int:kid>/status", methods=["POST"])
@chef_required
def rangliste_status(kid):
    db = g.db
    kat = db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    feld = request.form.get("feld")
    if feld == "gedruckt":
        if kat["rl_gedruckt"]:
            db.execute("UPDATE kategorie SET rl_gedruckt=0 WHERE id=?", (kid,))
        else:
            st = _rl_status(db, kat)
            if not st["eingegeben"]:
                flash(f"Noch nicht als gedruckt markierbar: {st['offen']} Teilnehmende ohne Resultat oder "
                      "Vermerk.", "error")
                return redirect(url_for("rangliste", kid=kid))
            db.execute("UPDATE kategorie SET rl_gedruckt=1 WHERE id=?", (kid,))
            _log(db, "rangliste", None, kid, "gedruckt", "", session.get("kennung", ""))
    elif feld == "fertig":
        neu = 0 if kat["rl_fertig"] else 1
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
    if status["eingegeben"]:          # Druck markiert „gedruckt“ – nur wenn alles eingegeben ist
        db.execute("UPDATE kategorie SET rl_gedruckt=1 WHERE id=?", (kid,))
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


# --------------------------------------------------------------------------- #
# Ranglisten als PDF (Design der offiziellen Ranglisten 2026) + Gesamt-Rangliste
# --------------------------------------------------------------------------- #
def _pdf_antwort(pdf, name):
    from flask import make_response
    r = make_response(pdf)
    r.headers["Content-Type"] = "application/pdf"
    r.headers["Content-Disposition"] = f'inline; filename="{name}"'
    return r


def _dateiname(text):
    import re
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöü._-]+", "_", text).strip("_") or "Rangliste"


@app.route("/liste/<name>/<fmt>")
@login_required
def liste_ausgabe(name, fmt):
    """Alle Listen/Statistiken als PDF (modernes Layout) oder Excel (.xlsx).
    ?download=1 lädt herunter, sonst wird inline angezeigt (Vorschau)."""
    from flask import make_response
    from debra import listen
    if name not in listen.LISTEN or fmt not in ("pdf", "xlsx"):
        abort(404)
    if name != "kontrollblatt" and not _ist_chef():
        flash("Dieser Bereich ist nur für die Rolle „Chef“.", "error")
        return redirect(url_for("dashboard"))
    if not _require_wettkampf():
        return redirect(url_for("dashboard"))
    args = request.args.to_dict()
    if name == "kontrollblatt" and not args.get("kennung"):
        args["kennung"] = session.get("kennung", "")
    try:
        daten, dateiname, mime = listen.ausgeben(g.db, g.wettkampf, name, fmt, args)
    except LookupError:
        abort(404)
    r = make_response(daten)
    r.headers["Content-Type"] = mime
    art = "attachment" if (fmt == "xlsx" or request.args.get("download")) else "inline"
    r.headers["Content-Disposition"] = f'{art}; filename="{_dateiname(dateiname.rsplit(".", 1)[0])}.{fmt}"'
    return r


@app.route("/rangliste/<int:kid>.pdf")
@chef_required
def rangliste_pdf(kid):
    from debra import rangliste_pdf as R
    kat = g.db.execute("SELECT * FROM kategorie WHERE id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    pdf = R.einzel_pdf(g.db, g.wettkampf, kat)
    if not pdf:
        flash("Für diese Disziplin gibt es noch keine Einträge.", "error")
        return redirect(url_for("rangliste", kid=kid))
    return _pdf_antwort(pdf, f"Rangliste_{_dateiname((kat['sparte'] or '') + '_' + kat['bezeichnung'])}.pdf")


@app.route("/rangliste/gesamt.pdf")
@chef_required
def rangliste_gesamt_pdf():
    from debra import rangliste_pdf as R
    if not _require_wettkampf():
        return redirect(url_for("dashboard"))
    fortlaufend = request.args.get("umbruch") == "fortlaufend"
    pdf = R.gesamt_pdf(g.db, g.wettkampf, fortlaufend=fortlaufend)
    return _pdf_antwort(pdf, f"Rangliste_{_dateiname(g.wettkampf['name'])}"
                             f"{'_fortlaufend' if fortlaufend else ''}.pdf")


def _positionen(kategorien):
    """Auswahlliste der Einfügestellen für Zusatzblätter: [(wert, text)]."""
    from debra.rangliste_pdf import _titel
    pos = [("anfang", "Am Anfang (z. B. Deckblatt)")]
    sparten = []
    for k in kategorien:
        if (k["sparte"] or "") not in sparten:
            sparten.append(k["sparte"] or "")
    for s in sparten:
        pos.append((f"vor_sparte:{s}", f"Vor {s}"))
        pos += [(f"nach_kat:{k['id']}", f"   nach {s}: {_titel(k)}")
                for k in kategorien if (k["sparte"] or "") == s]
        pos.append((f"nach_sparte:{s}", f"Nach {s}"))
    pos.append(("ende", "Am Schluss"))
    return pos


@app.route("/rangliste/gesamt", methods=["GET", "POST"])
@chef_required
def rangliste_gesamt():
    """Gesamt-Rangliste: Reihenfolge, Auswahl, Kopfzeile und Zusatzblätter."""
    from debra import rangliste_pdf as R, reihenfolge
    if not _require_wettkampf():
        return redirect(url_for("dashboard"))
    db, wk = g.db, g.wettkampf
    if request.method == "POST":
        aktion = request.form.get("aktion")
        if aktion == "reihenfolge":
            ids = [int(i) for i in request.form.get("ordnung", "").split(",") if i.strip().isdigit()]
            reihenfolge.setzen(db, wk["id"], ids)
            gewaehlt = set(request.form.getlist("drucken", type=int))
            for kid in ids:
                db.execute("UPDATE kategorie SET rl_drucken=? WHERE id=? AND wettkampf_id=?",
                           (1 if kid in gewaehlt else 0, kid, wk["id"]))
            db.commit()
            flash("Reihenfolge und Auswahl gespeichert – gilt überall in der App.", "ok")
        elif aktion == "standard":
            reihenfolge.standard(db, wk["id"])
            flash("Reihenfolge wie Rangliste 2026 gesetzt.", "ok")
        elif aktion == "kopf":
            design = "klassisch" if request.form.get("design") == "klassisch" else "modern"
            for schluessel, wert in ((f"rl_kopf_{wk['id']}", request.form.get("kopfzeile", "").strip()),
                                     (f"rl_einzelwerte_{wk['id']}", "1" if request.form.get("einzelwerte") else "0"),
                                     (f"rl_design_{wk['id']}", design)):
                db.execute("INSERT INTO einstellung(schluessel, wert) VALUES(?,?) "
                           "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert", (schluessel, wert))
            db.commit()
            flash("Gestaltung gespeichert.", "ok")
        elif aktion == "hochladen":
            datei = request.files.get("datei")
            daten = datei.read() if datei else b""
            if not daten.startswith(b"%PDF"):
                flash("Bitte eine PDF-Datei auswählen.", "error")
            else:
                try:
                    seiten = R.seiten_zaehlen(daten)
                except Exception as exc:  # noqa: BLE001
                    flash(f"PDF konnte nicht gelesen werden: {exc}", "error")
                else:
                    titel = (request.form.get("titel") or "").strip() or os.path.splitext(datei.filename)[0]
                    db.execute("INSERT INTO zusatzblatt(wettkampf_id, titel, dateiname, pdf, seiten, position, "
                               "sortierung) VALUES(?,?,?,?,?,?,?)",
                               (wk["id"], titel, datei.filename, daten, seiten,
                                request.form.get("position", "ende"),
                                request.form.get("sortierung", type=int) or 0))
                    db.commit()
                    flash(f"Zusatzblatt „{titel}“ ({seiten} Seite{'n' if seiten != 1 else ''}) eingefügt.", "ok")
        elif aktion == "blaetter":
            for b in db.execute("SELECT id FROM zusatzblatt WHERE wettkampf_id=?", (wk["id"],)).fetchall():
                if request.form.get(f"pos_{b['id']}") is not None:
                    db.execute("UPDATE zusatzblatt SET titel=?, position=?, sortierung=?, aktiv=? WHERE id=?",
                               ((request.form.get(f"titel_{b['id']}") or "").strip() or "Zusatzblatt",
                                request.form.get(f"pos_{b['id']}"),
                                request.form.get(f"sort_{b['id']}", type=int) or 0,
                                1 if request.form.get(f"aktiv_{b['id']}") else 0, b["id"]))
            db.commit()
            flash("Zusatzblätter gespeichert.", "ok")
        elif aktion == "loeschen":
            db.execute("DELETE FROM zusatzblatt WHERE id=? AND wettkampf_id=?",
                       (request.form.get("zid", type=int), wk["id"]))
            db.commit()
            flash("Zusatzblatt entfernt.", "ok")
        return redirect(url_for("rangliste_gesamt"))

    kategorien = db.execute(
        "SELECT k.*, (SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=k.id "
        f"AND {OHNE_ABGEMELDETE}) AS n FROM kategorie k WHERE k.wettkampf_id=? "
        "ORDER BY k.sortierung, k.bezeichnung", (wk["id"],)).fetchall()
    blaetter = db.execute("SELECT id, titel, dateiname, seiten, position, sortierung, aktiv FROM zusatzblatt "
                          "WHERE wettkampf_id=? ORDER BY sortierung, id", (wk["id"],)).fetchall()
    return render_template("rangliste_gesamt.html", kategorien=kategorien, blaetter=blaetter,
                           nicht_bereit=_gesamt_pruefung(db, wk),
                           positionen=_positionen(kategorien), opt=R.einstellungen(db, wk),
                           ablauf=R.ablauf(db, wk), titel_von=R._titel)


@app.route("/rangliste/zusatz/<int:zid>.pdf")
@chef_required
def zusatzblatt_pdf(zid):
    b = g.db.execute("SELECT * FROM zusatzblatt WHERE id=?", (zid,)).fetchone()
    if not b:
        abort(404)
    return _pdf_antwort(b["pdf"], _dateiname(b["dateiname"] or b["titel"]))


@app.route("/vereinsblatt")
@chef_required
def vereinsblatt():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe"))
    from debra import rangliste_pdf as R
    vereine = [{"name": n, "verband": v["verband"], "gruppen": len(v["zeilen"]),
                "auszeichnungen": sum(1 for z in v["zeilen"] if z["auszeichnung"]),
                "podest": sum(1 for z in v["zeilen"] if z["rang"] in (1, 2, 3) and not z["vermerk"])}
               for n, v in R.vereine(g.db, g.wettkampf).items()]
    return render_template("vereinsblatt.html", vereine=vereine)


@app.route("/vereinsblatt.pdf")
@chef_required
def vereinsblatt_pdf():
    """Vereinsblätter im modernen Ranglisten-Layout (alle oder ?verein=…)."""
    from debra import rangliste_pdf as R
    if not _require_wettkampf():
        return redirect(url_for("dashboard"))
    verein = request.args.get("verein") or None
    pdf = R.vereinsblatt_pdf(g.db, g.wettkampf, verein)
    if not pdf:
        flash("Keine Resultate für dieses Vereinsblatt.", "error")
        return redirect(url_for("vereinsblatt"))
    return _pdf_antwort(pdf, f"Vereinsblatt_{_dateiname(verein or 'alle_Vereine')}.pdf")


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


@app.route("/konfiguration/wkb", methods=["POST"])
@chef_required
def wkb_anwenden():
    """Wendet die Wettkampfbestimmungen auf Turner/Turnerinnen an."""
    if not _darf_anlass("tsst"):
        return redirect(url_for("einstellungen"))
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


@app.route("/konfiguration/jtsst", methods=["POST"])
@superuser_required
def jtsst_anlegen():
    """Legt den Jugendwettkampf (JTSST) gemäss WKB 2026 an."""
    from debra.jtsst import anlegen
    try:
        b = anlegen(g.db)
        if b["neu"]:
            flash("Jugendwettkampf JTSST 2026 angelegt und aktiviert: "
                  "{kategorien} Disziplinen/Kategorien.".format(**b), "ok")
        else:
            flash("Jugendwettkampf JTSST 2026 ist bereits vorhanden – {angeglichen} "
                  "Disziplinen an das DEBRA-Backup angeglichen.".format(**b), "ok")
    except Exception as e:  # noqa: BLE001
        flash(f"JTSST konnte nicht angelegt werden: {e}", "error")
    return redirect(url_for("dashboard"))


@app.route("/konfiguration/jtsst/import", methods=["POST"])
@superuser_required
def jtsst_import():
    """Importiert die JTSST-Anmeldungen (Gesamtübersicht + Alt-Export) aus einem Ordner."""
    from debra.jtsst import import_ordner
    quelle = request.form.get("quelle", "uebersicht")
    try:
        ordner = _upload_oder_pfad("ordner", "*.xlsx", "*.xls", standard=os.path.join("Inputs", "JTSST"))
        b = import_ordner(g.db, ordner, quelle)
        flash("JTSST-Anmeldungen importiert ({quelle}): {gruppen} Gruppen "
              "(Knaben {k}, Mädchen {m}).".format(
                  quelle="Gesamtübersicht" if b["quelle"] == "uebersicht" else "Alt-Export",
                  gruppen=b["gruppen"], k=b["je_sparte"].get("Knaben", 0),
                  m=b["je_sparte"].get("Mädchen", 0)), "ok")
        if b["abweichungen"]:
            flash(f"{len(b['abweichungen'])} Abweichungen zwischen Gesamtübersicht und Alt-Export: "
                  + "; ".join(b["abweichungen"][:20])
                  + (" …" if len(b["abweichungen"]) > 20 else ""), "error")
    except Exception as e:  # noqa: BLE001
        flash(f"JTSST-Import fehlgeschlagen: {e}", "error")
    return redirect(url_for("teilnehmer"))


@app.route("/konfiguration/import", methods=["POST"])
@superuser_required
def backup_import():
    """Importiert ein DEBRA-Backup (Ordner mit WT_/WR_/WI_-Textdateien)."""
    from debra.import_backup import importieren
    from debra.wkb import anwenden
    try:
        pfad = _upload_oder_pfad("import_pfad", "WT_*.txt")
    except Exception as e:  # noqa: BLE001
        flash(f"Upload fehlgeschlagen: {e}", "error")
        return redirect(url_for("einstellungen") + "#tsst/import")
    if not pfad:
        flash("Bitte die Backup-Dateien hochladen oder den Pfad zum Backup-Ordner angeben.", "error")
        return redirect(url_for("einstellungen") + "#tsst/import")
    try:
        b = importieren(pfad, reset=True)
        anwenden(g.db)
        flash("Backup importiert und WKB angewendet: {wettkaempfe} Wettkämpfe, {kategorien} "
              "Kategorien, {teilnehmer} Anmeldungen (davon {abgemeldet} abgemeldet), "
              "{vereine} neue Vereine, {resultate} Resultate.".format(**b), "ok")
        if b["uebersprungen"]:
            flash("Übersprungen (Jugend – bitte JTSST-Import verwenden): "
                  + ", ".join(b["uebersprungen"]), "error")
    except FileNotFoundError as e:
        flash(str(e), "error")
    except Exception as e:  # noqa: BLE001
        flash(f"Import fehlgeschlagen: {e}", "error")
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Einstellungsseite (Chef) – konsolidierte Wettkampf-Konfiguration
# --------------------------------------------------------------------------- #
@app.route("/einstellungen")
@chef_required
def einstellungen():
    """Alle Einstellungen auf einer Seite: Reiter Allgemein + je Anlass, darin Reiter je Art."""
    db = g.db
    anlaesse = []
    aktiv = _art(db, g.wettkampf)
    for art, w in _anlaesse(db).items():
        if not _ist_superuser() and art != aktiv:
            continue
        kategorien = db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                                (w["id"],)).fetchall() if w else []
        teilnehmer = db.execute(f"SELECT COUNT(*) c FROM teilnehmer t WHERE t.wettkampf_id=? AND {OHNE_ABGEMELDETE}",
                                (w["id"],)).fetchone()["c"] if w else 0
        anlaesse.append({"art": art, "w": w, "kategorien": kategorien, "teilnehmer": teilnehmer,
                         "stafetten": [k for k in kategorien if k["ist_stafette"]]})
    vorjahr_n = db.execute("SELECT COUNT(*) c FROM vorjahr").fetchone()["c"]
    start = _art(db, g.wettkampf) or "allgemein"
    return render_template("einstellungen.html", liste=anlaesse, modi=KRANZ_MODI, vorjahr_n=vorjahr_n,
                           db_pfad=DB_PATH, start=start)


@app.route("/einstellungen/<art>", methods=["GET", "POST"])
@chef_required
def einstellungen_anlass(art):
    """Speichert die Einstellungen eines Anlasses (Formular eines Reiters); GET springt zum Reiter."""
    if art not in ANLAESSE:
        abort(404)
    db = g.db
    w = _anlaesse(db)[art]
    if request.method == "POST" and not _darf_anlass(art):
        return redirect(url_for("einstellungen"))
    if request.method == "POST" and w:
        wid = w["id"]
        name = request.form.get("wk_name")
        if name is not None:
            db.execute("UPDATE wettkampf SET name=?, ort=?, datum=? WHERE id=?",
                       (name.strip(), request.form.get("wk_ort", "").strip(),
                        request.form.get("wk_datum", "").strip(), wid))
        kats = db.execute("SELECT id, ist_stafette FROM kategorie WHERE wettkampf_id=?", (wid,)).fetchall()
        # Auszeichnung pro Kategorie (Modus + Wert)
        for kat in kats:
            modus = request.form.get(f"km_{kat['id']}")
            if modus:
                wert = request.form.get(f"kw_{kat['id']}", type=float)
                basis = request.form.get(f"kb_{kat['id']}", "angemeldet")
                melde = request.form.get(f"ms_{kat['id']}", type=int)
                db.execute("UPDATE kategorie SET kranz_modus=?, kranz_wert=?, kranz_basis=?, "
                           "anz_meldeschluss=? WHERE id=?",
                           (modus, wert or 0, basis if basis in ("angemeldet", "rangiert") else "angemeldet",
                            melde, kat["id"]))
        # Auszeichnungs-Prozentsatz auf alle Kategorien dieses Anlasses anwenden (optional)
        proz = request.form.get("kranz_prozent", type=float)
        if proz is not None and request.form.get("kranz_auf_alle"):
            db.execute("UPDATE kategorie SET kranz_modus='prozent', kranz_wert=? WHERE wettkampf_id=?", (proz, wid))
        for kat in kats:
            # Stafetten-Zuschläge
            za = request.form.get(f"za_{kat['id']}", type=float)
            if kat["ist_stafette"] and za is not None:
                db.execute("UPDATE kategorie SET zuschlag_a=?, zuschlag_b=?, bahnen=? WHERE id=?",
                           (za, request.form.get(f"zb_{kat['id']}", type=float) or 0,
                            request.form.get(f"bahnen_{kat['id']}", type=int) or 8, kat["id"]))
            # Zeitplan & Plausibilität
            if request.form.get(f"anl_{kat['id']}") is not None:
                db.execute("UPDATE kategorie SET anlagen=?, zeit_pro_turner=?, warn_min=?, warn_max=? WHERE id=?",
                           (request.form.get(f"anl_{kat['id']}", type=int) or 1,
                            request.form.get(f"zpt_{kat['id']}", type=float) or 0,
                            request.form.get(f"wmin_{kat['id']}", type=float),
                            request.form.get(f"wmax_{kat['id']}", type=float), kat["id"]))
        db.commit()
        flash(f"Einstellungen {ANLAESSE[art]} gespeichert.", "ok")
    reiter = request.form.get("reiter") or art
    return redirect(url_for("einstellungen") + "#" + reiter)


# --------------------------------------------------------------------------- #
# Erfassungskontrolle – fehlende Resultate
# --------------------------------------------------------------------------- #
@app.route("/erfassungskontrolle")
@login_required
def erfassungskontrolle():
    if not _require_wettkampf():
        return redirect(url_for("wettkaempfe") if _ist_chef() else url_for("dashboard"))
    db = g.db
    bloecke = []
    for w in _aktiver_anlass():
        zeilen = []
        for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                            (w["id"],)).fetchall():
            tn, mit = _fortschritt(db, k)
            zeilen.append({"kat": k, "tn": tn, "mit": mit, "fehlt": tn - mit,
                           "kontrolliert": db.execute(
                               f"SELECT COUNT(*) c FROM teilnehmer t WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} "
                               "AND t.kontrolliert_am IS NOT NULL", (k["id"],)).fetchone()["c"],
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
        "SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name, "
        f"(SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=k.id AND {OHNE_ABGEMELDETE}) AS anz "
        "FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=0 AND k.wettkampf_id=? ORDER BY k.sortierung",
        (g.wettkampf["id"] if g.wettkampf else 0,)).fetchall()
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
    for k in db.execute("SELECT * FROM kategorie WHERE ist_stafette=0 AND wettkampf_id=? "
                        "ORDER BY sortierung, bezeichnung", (g.wettkampf["id"] if g.wettkampf else 0,)).fetchall():
        mitglieder = k["anzahl_werte"] or (5 if (k["geschlecht"] or "m") == "m" else 4)
        dauer = max(1, math.ceil((k["zeit_pro_turner"] or 0) * mitglieder)) if k["zeit_pro_turner"] else 10
        anlagen = k["anlagen"] or 1
        labels = [(f"{k['bezeichnung']} {n + 1}" if anlagen > 1 else k["bezeichnung"])
                  for n in range(anlagen)]
        for t in db.execute(
                "SELECT t.id, t.verein_id FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
                f"WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} ORDER BY v.name, t.gruppennr, t.startnr",
                (k["id"],)).fetchall():
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
        f"WHERE k.ist_stafette=0 AND t.startzeit IS NOT NULL AND t.wettkampf_id=? AND {OHNE_ABGEMELDETE}",
        (g.wettkampf["id"] if g.wettkampf else 0,)).fetchall()
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
        "SELECT DISTINCT r.erfasst_von FROM resultat r JOIN teilnehmer t ON t.id=r.teilnehmer_id "
        "WHERE r.erfasst_von IS NOT NULL AND r.erfasst_von<>'' AND t.wettkampf_id=? "
        "ORDER BY r.erfasst_von", (g.wettkampf["id"] if g.wettkampf else 0,)).fetchall()]
    gewaehlt = request.args.get("kennung", "") or (kennungen[0] if kennungen else "")
    nur_offen = request.args.get("offen", "1") == "1"
    kat_filter = request.args.get("kat", type=int)

    bloecke = []
    kat_rows = db.execute(
        "SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=0 AND k.wettkampf_id=? ORDER BY k.sortierung",
        (g.wettkampf["id"] if g.wettkampf else 0,)).fetchall()
    from debra.listen import kontroll_spalten, kontroll_werte
    for k in kat_rows:
        if kat_filter and k["id"] != kat_filter:
            continue
        spalten = kontroll_spalten(db, k)
        rows = db.execute(
            "SELECT DISTINCT t.id, t.startnr, t.kontrolliert_am, t.kontrolliert_von FROM teilnehmer t "
            "JOIN resultat r ON r.teilnehmer_id=t.id "
            "WHERE t.kategorie_id=? AND r.erfasst_von=? ORDER BY t.startnr", (k["id"], gewaehlt)).fetchall()
        eintraege = []
        for t in rows:
            if nur_offen and t["kontrolliert_am"]:
                continue
            werte = kontroll_werte(db, k, t["id"])
            eintraege.append({"t": t, "werte": [werte.get(p, "") for p, _, _ in spalten]})
        if eintraege:
            bloecke.append({"kat": k, "kopf": [label for _, _, label in spalten], "eintraege": eintraege})
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
    flash("Disziplin abgeschlossen – das Fertig-Blatt steht in der Erfassungskontrolle bereit.", "ok")
    return redirect(url_for("erfassungskontrolle"))


@app.route("/disziplin/<int:kid>/fertig")
@chef_required
def disziplin_fertig(kid):
    db = g.db
    kat = db.execute("SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
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
           "LEFT JOIN teilnehmer t ON t.id=a.teilnehmer_id LEFT JOIN verein v ON v.id=t.verein_id "
           "WHERE COALESCE(t.wettkampf_id, k.wettkampf_id)=? ")
    wk_id = g.wettkampf["id"] if g.wettkampf else 0
    params = [wk_id]
    if kennung:
        sql += "AND a.kennung=? "
        params.append(kennung)
    sql += "ORDER BY a.id DESC LIMIT 500"
    eintraege = db.execute(sql, params).fetchall()
    kennungen = [r["kennung"] for r in db.execute(
        "SELECT DISTINCT a.kennung FROM aenderung a LEFT JOIN kategorie k ON k.id=a.kategorie_id "
        "LEFT JOIN teilnehmer t ON t.id=a.teilnehmer_id WHERE a.kennung IS NOT NULL AND a.kennung<>'' "
        "AND COALESCE(t.wettkampf_id, k.wettkampf_id)=? ORDER BY a.kennung", (wk_id,)).fetchall()]
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
    for w in _aktiver_anlass():
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
    for w in _aktiver_anlass():
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
        "SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.wettkampf_id=? ORDER BY k.sortierung", (g.wettkampf["id"],)).fetchall()
    return render_template("notenblaetter.html", kategorien=kategorien)


@app.route("/notenblaetter/<int:kid>/druck")
@chef_required
def notenblatt_druck(kid):
    db = g.db
    kat = db.execute("SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name FROM kategorie k "
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
        f"WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} ORDER BY t.startnr", (kid,)).fetchall()
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
        "SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
        "WHERE k.ist_stafette=1 AND k.wettkampf_id=? ORDER BY k.sortierung", (g.wettkampf["id"],)).fetchall()
    return render_template("stafetten_index.html", kategorien=kategorien)


def _stafette_teams(db, kid):
    return db.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
        f"WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} ORDER BY t.startnr", (kid,)).fetchall()


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
    # Schutz: Finalisten mit Finalzeit, aber ohne Vorlaufzeit (z. B. aus dem DEBRA-Backup)
    # würden sonst aus dem Final fallen.
    ohne_vorlauf = db.execute(
        "SELECT COUNT(*) c FROM teilnehmer t JOIN stafette f ON f.teilnehmer_id=t.id AND f.runde='final' "
        "AND f.rohzeit IS NOT NULL WHERE t.kategorie_id=? AND NOT EXISTS (SELECT 1 FROM stafette v "
        "WHERE v.teilnehmer_id=t.id AND v.runde='vorlauf' AND v.rohzeit IS NOT NULL)", (kid,)).fetchone()["c"]
    if ohne_vorlauf:
        flash(f"Selektion nicht ausgeführt: {ohne_vorlauf} Team(s) haben eine Finalzeit, aber keine Vorlaufzeit. "
              "Die Final-Zuteilung bitte manuell anpassen.", "error")
        return redirect(url_for("stafette_verwalten", kid=kid))
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
    kat = db.execute("SELECT k.*, COALESCE(k.sparte, w.name) AS wk_name FROM kategorie k JOIN wettkampf w ON w.id=k.wettkampf_id "
                     "WHERE k.id=?", (kid,)).fetchone()
    if not kat:
        abort(404)
    runde = request.args.get("runde", "vorlauf" if kat["hat_final"] else "final")
    serien = _serien_lanes(db, kat, runde)
    return render_template("notenblatt_lauf_druck.html", kat=kat, runde=runde, serien=serien)


@app.route("/import/excel", methods=["GET", "POST"])
@superuser_required
def excel_import():
    """Schritt 1: Excel hochladen -> Spalten automatisch zuordnen -> prüfen."""
    from debra import excel_import as X
    if request.method == "POST":
        datei = request.files.get("datei")
        if not datei or not datei.filename:
            flash("Bitte eine Excel-Datei (.xlsx oder .xls) auswählen.", "error")
            return redirect(url_for("excel_import"))
        import tempfile
        endung = ".xls" if datei.filename.lower().endswith(".xls") else ".xlsx"
        fd, pfad = tempfile.mkstemp(suffix=endung, prefix="debra_up_")
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
@superuser_required
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


def _import_ordner_pfad():
    from debra.excel_import import STANDARD_ORDNER
    return _eingabe_pfad(request.values.get("ordner"), STANDARD_ORDNER)


@app.route("/import/ordner")
@superuser_required
def import_ordner():
    """Schritt 1: TSST- und JTSST-Excel eines Ordners lesen und zur Prüfung anzeigen."""
    from debra import excel_import as X
    ordner = _import_ordner_pfad()
    try:
        p = X.ordner_pruefen(g.db, ordner)
    except Exception as exc:  # noqa: BLE001
        flash(f"Ordner konnte nicht gelesen werden: {exc}", "error")
        return redirect(url_for("einstellungen"))
    return render_template("import_ordner.html", pruefung=p, ordner=ordner)


@app.route("/import/hochladen", methods=["POST"])
@superuser_required
def import_ordner_hochladen():
    """Excel-Anmeldungen (TSST + JTSST) hochladen und zum Prüfschritt weiterleiten."""
    try:
        ordner = _upload_speichern()
    except Exception as e:  # noqa: BLE001
        flash(f"Upload fehlgeschlagen: {e}", "error")
        return redirect(url_for("einstellungen") + "#allgemein/import")
    if not ordner:
        flash("Bitte Excel-Dateien (oder ein ZIP) auswählen.", "error")
        return redirect(url_for("einstellungen") + "#allgemein/import")
    return redirect(url_for("import_ordner", ordner=_finde_ordner(ordner, "*.xlsx", "*.xls")))


@app.route("/import/ordner", methods=["POST"])
@superuser_required
def import_ordner_uebernehmen():
    """Schritt 2: Anmeldungen übernehmen (ersetzt TSST/JTSST-Anmeldungen, vorher Sicherung)."""
    from debra import excel_import as X
    try:
        b = X.ordner_importieren(g.db, _import_ordner_pfad())
        teile = []
        if b["tsst"] is not None:
            teile.append(f"TSST {b['tsst']} Gruppen")
        if b["jtsst"]:
            teile.append("JTSST {gruppen} Gruppen".format(**b["jtsst"]))
        flash("Anmeldungen importiert: " + ", ".join(teile)
              + f". Sicherung: {os.path.basename(b['sicherung'])}", "ok")
        if b["jtsst"] and b["jtsst"]["fehlende_kategorien"]:
            flash("Keine JTSST-Kategorie für: " + "; ".join(b["jtsst"]["fehlende_kategorien"]), "error")
    except Exception as exc:  # noqa: BLE001
        flash(f"Import fehlgeschlagen: {exc}", "error")
        return redirect(url_for("einstellungen"))
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
        "WHERE COALESCE(t.status,'')<>'abgem' ORDER BY w.id, t.startnr").fetchall()


@app.route("/listen/startliste/druck")
@chef_required
def startliste_druck():
    db = g.db
    nach = request.args.get("nach", "verein")   # verein | kategorie | startnr
    rows = _startliste_daten(db)
    bloecke = []   # Liste von {titel, wk, gruppen: [{kopf, anzahl, zeilen}]}
    for w in _aktiver_anlass():
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
    for w in _aktiver_anlass():
        zeilen = []
        tot_gruppen = tot_teiln = 0
        for k in db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
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
@superuser_required
def vorjahr_import():
    import glob
    from debra import vorjahr as vj
    try:
        pfad = _upload_oder_pfad("pdf_pfad", "WT_*.txt", "*.pdf")
        if pfad and os.path.isdir(pfad) and not glob.glob(os.path.join(pfad, "WT_*.txt")):
            pdfs = glob.glob(os.path.join(pfad, "*.pdf"))   # hochgeladene Rangliste als PDF
            pfad = pdfs[0] if pdfs else pfad
        n = vj.importieren(conn=g.db, pdf_pfad=pfad)
        flash(f"Vorjahres-Rangliste importiert: {n} Stafetten-Resultate.", "ok")
    except Exception as exc:  # pragma: no cover
        flash(f"Import fehlgeschlagen: {exc}", "error")
    return redirect(url_for("einstellungen") + "#tsst/import")


# --------------------------------------------------------------------------- #
# JET – Jugend-Einzelturntag: Erfassung, Wertungstabelle, Import
# --------------------------------------------------------------------------- #
def _jet_wettkampf():
    """Aktiver Wettkampf, falls er der JET ist – sonst Hinweis und None."""
    if g.wettkampf and _art(g.db, g.wettkampf) == "jet":
        return g.wettkampf
    flash("Diese Seite gehört zum JET – bitte oben rechts auf „JET“ umschalten.", "error")
    return None


def _jet_args(**neu):
    """Aktuelle Filter der JET-Erfassung (für Links und Redirects)."""
    args = {k: request.values.get(k) for k in ("g", "kat", "verein", "disz", "nr")}
    args.update(neu)
    return {k: v for k, v in args.items() if v not in (None, "")}


@app.route("/jet/schnellerfassung", methods=["GET", "POST"])
@login_required
def jet_schnellerfassung():
    """JET-Schnellerfassung wie bei TSST/JTSST: Startnummer eingeben, Disziplinen untereinander."""
    return jet_erfassung.__wrapped__()


@app.route("/jet/erfassung", methods=["GET", "POST"])
@login_required
def jet_erfassung():
    """JET-Eingabe: Messwert bzw. Gerätenote je Disziplin, Note und Total werden berechnet.

    Filter: Sparte, Kategorie, Verein (= Riege), Disziplin (Posten-Erfassung) oder Startnummer.
    """
    from debra import jet
    wk = _jet_wettkampf()
    if wk is None:
        return redirect(url_for("dashboard"))
    db = g.db
    kats = db.execute("SELECT * FROM kategorie WHERE wettkampf_id=? AND berechnung='jet' "
                      "ORDER BY sortierung", (wk["id"],)).fetchall()
    kat_map = {k["id"]: k for k in kats}
    gesch = request.values.get("g") or None
    kid = request.values.get("kat", type=int)
    vid = request.values.get("verein", type=int)
    disz = request.values.get("disz") or None
    nr = request.values.get("nr", type=int)

    bed, args = [f"t.wettkampf_id=?", OHNE_ABGEMELDETE], [wk["id"]]
    if nr is not None:
        t = db.execute("SELECT t.kategorie_id FROM teilnehmer t WHERE t.wettkampf_id=? AND t.startnr=?",
                       (wk["id"], nr)).fetchone()
        if t is None:
            anders = db.execute("SELECT w.name FROM teilnehmer t JOIN wettkampf w ON w.id=t.wettkampf_id "
                                "WHERE t.startnr=? LIMIT 1", (nr,)).fetchone()
            flash(f"Startnummer {nr} gibt es im JET nicht"
                  + (f" (sie gehört zu {anders['name']})." if anders else "."), "error")
            return redirect(url_for(request.endpoint, **_jet_args(nr=None)))
        kid, vid, disz = t["kategorie_id"], None, None
        bed.append("t.startnr=?")
        args.append(nr)
    if kid in kat_map:
        gesch = kat_map[kid]["geschlecht"]
        bed.append("t.kategorie_id=?")
        args.append(kid)
    else:
        kid = None
    if vid:
        bed.append("t.verein_id=?")
        args.append(vid)
    if gesch in ("m", "w"):
        bed.append("k.geschlecht=?")
        args.append(gesch)
    else:
        gesch = None
    aktiv = bool(kid or vid or nr is not None) and gesch is not None

    programm = jet.PROGRAMM.get(gesch or "w", [])
    spalten = [a for a in programm if not disz or a == disz]
    if disz and disz not in programm:
        disz, spalten = None, programm
    pos_von = {a: programm.index(a) + 1 for a in programm}

    teilnehmende = []
    if aktiv:
        teilnehmende = db.execute(
            "SELECT t.*, v.name AS verein_name, k.abk AS kat_abk, k.bezeichnung AS kat_bez FROM teilnehmer t "
            "JOIN kategorie k ON k.id=t.kategorie_id LEFT JOIN verein v ON v.id=t.verein_id "
            f"WHERE {' AND '.join(bed)} ORDER BY k.sortierung, t.startnr", args).fetchall()

    if request.method == "POST" and aktiv:
        um = jet.Umrechner(db)
        kennung, jetzt = session.get("kennung", ""), _jetzt()
        n_neu, fehler = 0, []
        for t in teilnehmende:
            kat_bst = jet.kat_buchstabe(kat_map[t["kategorie_id"]])
            alt = {r["position"]: r for r in db.execute(
                "SELECT position, wert, note FROM resultat WHERE teilnehmer_id=?", (t["id"],)).fetchall()}
            for abk in spalten:
                feld = f"w_{t['id']}_{abk}"
                if feld not in request.form:
                    continue
                roh = (request.form.get(feld) or "").strip()
                p = pos_von[abk]
                alt_txt = "" if p not in alt or alt[p]["wert"] is None else f"{alt[p]['wert']:g}"
                if roh == "":
                    if p in alt:
                        db.execute("DELETE FROM resultat WHERE teilnehmer_id=? AND position=?", (t["id"], p))
                        _log(db, "resultat", t["id"], t["kategorie_id"], abk, alt_txt, "")
                    continue
                wert = scoring.parse_zeit(roh) if jet.DISZIPLINEN[abk][2] == "s" else None
                if wert is None:
                    try:
                        wert = round(float(roh.replace(",", ".")), 2)
                    except ValueError:
                        fehler.append(f"Nr. {t['startnr']} {abk}: „{roh}“ ist keine Zahl")
                        continue
                if jet.DISZIPLINEN[abk][1] == "geraete" and not 0 <= wert <= 10:
                    fehler.append(f"Nr. {t['startnr']} {abk}: Note {wert} ausserhalb 0–10")
                    continue
                note = um.note(t["geschlecht"] or gesch, abk, kat_bst, wert)
                if p in alt and alt[p]["wert"] == wert and alt[p]["note"] == note:
                    continue
                db.execute(
                    "INSERT INTO resultat(teilnehmer_id, position, wert, note, status, erfasst_von, erfasst_am) "
                    "VALUES(?,?,?,?,NULL,?,?) ON CONFLICT(teilnehmer_id, position) DO UPDATE SET "
                    "wert=excluded.wert, note=excluded.note, status=NULL, erfasst_von=excluded.erfasst_von, "
                    "erfasst_am=excluded.erfasst_am", (t["id"], p, wert, note, kennung, jetzt))
                _log(db, "resultat", t["id"], t["kategorie_id"], abk, alt_txt, f"{wert:g}")
                n_neu += 1
            if f"st_{t['id']}" in request.form:
                status = request.form.get(f"st_{t['id']}", "").strip() or None
                if status != (t["status"] or None):
                    db.execute("UPDATE teilnehmer SET status=? WHERE id=?", (status, t["id"]))
                    _log(db, "vermerk", t["id"], t["kategorie_id"], "Vermerk", t["status"] or "", status or "")
        db.commit()
        for f in fehler:
            flash(f, "error")
        if len(teilnehmende) == 1:
            t = teilnehmende[0]
            flash(f"Nr. {t['startnr']} {t['vorname']} {t['nachname']}: {n_neu} Resultat(e) gespeichert.", "ok")
        else:
            flash(f"{n_neu} Resultat(e) gespeichert.", "ok")
        weiter = request.form.get("weiter", type=int)
        if weiter is not None and not fehler:
            return redirect(url_for(request.endpoint, nr=weiter))
        return redirect(url_for(request.endpoint, gespeichert=1 if nr is not None else None, **_jet_args()))

    # Anzeige: Werte, Noten und Wertung je Teilnehmer:in
    zeilen = []
    for t in teilnehmende:
        res = {r["position"]: r for r in db.execute(
            "SELECT position, wert, note FROM resultat WHERE teilnehmer_id=?", (t["id"],)).fetchall()}
        noten = [res[p]["note"] if p in res else None for p in range(1, len(programm) + 1)]
        w = jet.wertung(programm, noten, jet.kat_buchstabe(kat_map[t["kategorie_id"]]))
        zellen = {}
        for abk in programm:
            r = res.get(pos_von[abk])
            zellen[abk] = {"wert": "" if not r or r["wert"] is None else
                           (scoring.fmt_zeit(r["wert"]) if jet.DISZIPLINEN[abk][2] == "s" else f"{r['wert']:g}"),
                           "note": r["note"] if r else None,
                           "gestrichen": pos_von[abk] - 1 in w["gestrichen"],
                           "falsch": pos_von[abk] - 1 in w["falsch"]}
        zeilen.append({"t": t, "kat": jet.kat_buchstabe(kat_map[t["kategorie_id"]]), "zellen": zellen,
                       "wertung": w})

    vereine = db.execute(
        "SELECT DISTINCT v.id, v.name FROM teilnehmer t JOIN verein v ON v.id=t.verein_id "
        "JOIN kategorie k ON k.id=t.kategorie_id WHERE t.wettkampf_id=?"
        + (" AND k.geschlecht=?" if gesch else "") + " ORDER BY v.name",
        (wk["id"], gesch) if gesch else (wk["id"],)).fetchall()
    uebersicht = []
    for k in kats:
        tn, mit = _fortschritt(db, k)
        uebersicht.append({"k": k, "tn": tn, "mit": mit})
    tabellen = jet.Umrechner(db).alle(gesch) if aktiv else {}
    gruppen_kopf = []                  # Kopfzeile Geräte | Leichtathletik | Plausch
    for a in spalten:
        gr = jet.DISZIPLINEN[a][1]
        if gruppen_kopf and gruppen_kopf[-1][0] == gr:
            gruppen_kopf[-1][1] += 1
        else:
            gruppen_kopf.append([gr, 1])
    # eine Person (Startnummer): Disziplinen untereinander statt Raster
    einzeln = nr is not None and len(zeilen) == 1
    schnell = request.endpoint == "jet_schnellerfassung"
    if schnell and aktiv and not einzeln:
        # Schnellerfassung zeigt nur einzelne Personen – Raster in der Erfassung nach Kategorie
        return redirect(url_for("jet_erfassung", **_jet_args()))
    return render_template("jet_erfassung.html", kats=kats, gruppen_kopf=gruppen_kopf, einzeln=einzeln,
                           schnell=schnell, gesch=gesch, kid=kid, vid=vid, disz=disz, nr=nr,
                           aktiv=aktiv, spalten=spalten, zeilen=zeilen, vereine=vereine,
                           uebersicht=uebersicht, jet=jet, tabellen=tabellen,
                           status_labels=scoring.STATUS_LABELS)


@app.route("/jet/wertungstabelle", methods=["GET", "POST"])
@superuser_required
def jet_wertungstabelle():
    """Formel je Disziplin und Kategorie pflegen; daraus wird die Wertungstabelle erzeugt."""
    from debra import jet
    db = g.db
    gesch = request.values.get("g", "w")
    gesch = gesch if gesch in ("m", "w") else "w"
    disz = request.values.get("d", "WE")
    disz = disz if disz in jet.TABELLEN_DISZ else "WE"
    jet.formeln_sicherstellen(db)
    name = f"{jet.DISZIPLINEN[disz][0]} {'Knaben' if gesch == 'm' else 'Mädchen'}"
    eingabe = None

    if request.method == "POST":
        aktion = request.form.get("aktion", "speichern")
        try:
            if aktion == "speichern":
                eingabe = {k: (request.form.get(f"f_{k}") or "").strip() for k in jet.KATEGORIEN}
                alt = jet.formeln(db, gesch, disz)
                neu = {k: v for k, v in eingabe.items() if v != alt[k]}
                if neu:
                    n = jet.formel_speichern(db, gesch, disz, neu)
                    flash(f"{name}: Formel Kat. {', '.join(neu)} gespeichert – Tabelle neu erzeugt ({n} Zeilen).", "ok")
                else:
                    flash("Keine Formel geändert.", "ok")
            elif aktion == "standard":
                alle = request.form.get("umfang") == "alle"
                jet.formeln_standard(db, None if alle else gesch, None if alle else disz)
                flash(("Alle Formeln" if alle else f"Formeln {name}") + " auf Standard zurückgesetzt, Tabellen neu erzeugt.", "ok")
        except jet.FormelFehler as e:
            flash(f"Nicht gespeichert – {e}", "error")
            return _jet_tabelle_seite(gesch, disz, eingabe)
        geaendert = jet.noten_neu_berechnen(db)
        if geaendert:
            flash(f"{geaendert} bereits erfasste Note(n) neu berechnet.", "ok")
        return redirect(url_for("jet_wertungstabelle", g=gesch, d=disz))
    return _jet_tabelle_seite(gesch, disz, None)


def _jet_tabelle_seite(gesch, disz, eingabe):
    from debra import jet
    db = g.db
    gespeichert = jet.formeln(db, gesch, disz)
    raster = jet.tabelle_raster(db, gesch, disz)
    for z in raster:
        for k in jet.KATEGORIEN:
            if isinstance(z.get(k), list):
                z[k] = z[k][0]
    tab = jet.tabelle(db, gesch, disz)
    return render_template("jet_tabelle.html", jet=jet, gesch=gesch, disz=disz, raster=raster,
                           formeln=eingabe or gespeichert, gespeichert=gespeichert,
                           standard={k: jet.standard_formel(gesch, disz, k) for k in jet.KATEGORIEN},
                           tabelle_json={k: [list(r) for r in v] for k, v in tab.items()})


@app.route("/jet/import", methods=["GET", "POST"])
@superuser_required
def jet_import():
    """JET-Anmeldungen: DEBRA-Backup, Anmelde-Export (Excel) oder Startliste (PDF) mit Prüfschritt."""
    from debra import excel_import as X, jet
    db = g.db
    basis = os.path.dirname(os.path.abspath(__file__))
    vorschlag = jet.standard_dateien(os.path.join(basis, jet.STANDARD_ORDNER))

    def pfad(name):
        return _eingabe_pfad(request.values.get(name))

    dateien = {"m": pfad("knaben"), "w": pfad("maedchen")}
    if request.method == "POST":
        try:
            sich = X.sicherung(db, "vor-jet-import")
            b = jet.importieren(db, {k: v for k, v in dateien.items() if v})
            w = _anlaesse(db)["jet"]
            db.execute("UPDATE wettkampf SET aktiv=(id=?)", (w["id"],))
            db.commit()
            flash(f"JET-Anmeldungen importiert: {b['personen']} Teilnehmende (Knaben {b['je_sparte'].get('m', 0)}, "
                  f"Mädchen {b['je_sparte'].get('w', 0)}), {b['vereine']} neue Vereine, {b['resultate']} Resultate. "
                  f"Sicherung: {os.path.basename(sich)}", "ok")
            if b["uebersprungen"]:
                flash(f"{b['uebersprungen']} Personen ohne JET-Jahrgang übersprungen.", "error")
        except Exception as e:  # noqa: BLE001
            flash(f"JET-Import fehlgeschlagen: {e}", "error")
            return redirect(url_for("jet_import"))
        return redirect(url_for("jet_erfassung"))

    pruefung = None
    if any(dateien.values()):
        pruefung = jet.pruefen({k: v for k, v in dateien.items() if v})
    w = _anlaesse(db)["jet"]
    bestehend = {"m": 0, "w": 0, "resultate": 0}
    if w:
        for r in db.execute("SELECT k.geschlecht, COUNT(*) c FROM teilnehmer t JOIN kategorie k "
                            "ON k.id=t.kategorie_id WHERE t.wettkampf_id=? GROUP BY k.geschlecht", (w["id"],)):
            bestehend[r["geschlecht"]] = r["c"]
        bestehend["resultate"] = db.execute(
            "SELECT COUNT(*) c FROM resultat r JOIN teilnehmer t ON t.id=r.teilnehmer_id "
            "WHERE t.wettkampf_id=? AND r.erfasst_von<>'Import'", (w["id"],)).fetchone()["c"]

    def rel(p):
        if not p:
            return ""
        r = os.path.relpath(p, basis)
        return p if r.startswith("..") else r          # Uploads (neben der DB) absolut zeigen
    return render_template("jet_import.html", pruefung=pruefung, bestehend=bestehend, jet=jet,
                           knaben=rel(dateien["m"]) if dateien["m"] else rel(vorschlag["m"]),
                           maedchen=rel(dateien["w"]) if dateien["w"] else rel(vorschlag["w"]),
                           geprueft=any(dateien.values()))


@app.route("/jet/import/hochladen", methods=["POST"])
@superuser_required
def jet_import_hochladen():
    """JET-Anmeldungen hochladen (DEBRA-Backup, JR_/MR_JET.xls oder Startlisten-PDF) und prüfen."""
    from debra import jet
    try:
        ordner = _upload_speichern()
    except Exception as e:  # noqa: BLE001
        flash(f"Upload fehlgeschlagen: {e}", "error")
        return redirect(url_for("jet_import"))
    if not ordner:
        flash("Bitte Dateien (oder ein ZIP) auswählen.", "error")
        return redirect(url_for("jet_import"))
    backup = _finde_ordner(ordner, "WT_*.txt")
    dateien = {}
    if any(f.startswith("WT_") for f in os.listdir(backup)):
        dateien = {g_: backup for g_ in ("m", "w") if jet.parse_backup(backup, g_)}
    else:
        for wurzel, _, namen in os.walk(ordner):
            for n in sorted(namen):
                g_ = jet._geschlecht_aus(n)
                if g_ and g_ not in dateien and n.lower().endswith((".xls", ".xlsx", ".pdf")):
                    dateien[g_] = os.path.join(wurzel, n)
    if not dateien:
        flash("In den hochgeladenen Dateien wurden keine JET-Anmeldungen erkannt (DEBRA-Backup mit "
              "WT_-Dateien, JR_JET.xls/MR_JET.xls oder Startliste Knaben/Mädchen als PDF).", "error")
        return redirect(url_for("jet_import"))
    return redirect(url_for("jet_import", knaben=dateien.get("m", ""), maedchen=dateien.get("w", "")))


@app.route("/konfiguration/jet", methods=["POST"])
@superuser_required
def jet_anlegen():
    """Legt den Jugend-Einzelturntag (JET) gemäss WKB 2026 an."""
    from debra.jet import anlegen
    b = anlegen(g.db)
    if b["neu"]:
        flash(f"JET 2026 angelegt: {b['kategorien']} Kategorien (Mädchen/Knaben A–E).", "ok")
    else:
        flash(f"JET ist bereits vorhanden ({b['kategorien']} Kategorien).", "ok")
    return redirect(url_for("einstellungen") + "#jet/import")


# Schema beim Import aktualisieren (auch unter waitress, nicht nur bei python app.py)
try:
    init_db()
    _c = get_db()
    if _c.execute("SELECT 1 FROM kategorie WHERE berechnung='jet' LIMIT 1").fetchone():
        from debra.jet import formeln_sicherstellen
        formeln_sicherstellen(_c)       # JET-Formeln anlegen und Tabellen daraus erzeugen
    _c.close()
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
