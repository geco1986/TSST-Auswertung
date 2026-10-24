"""Jugend-Einzelturntag (JET) gemäss WKB 2026.

Grundlage: Wettkampfbestimmungen Jugend-Einzelturntag JET WTU, Sonntag 5. Juli 2026,
Sportanlage Rheinau.

- 3. Mädchen und Knaben je Kategorie A (15/16 j.), B (13/14 j.), C (11/12 j.) als
  6-Kampf, D (9/10 j.) und E (8 und jünger) als 4-Kampf. Die Kategorie ergibt sich aus
  dem Jahrgang (Alter im Wettkampfjahr).
- Wählbar sind Geräte (Barren/Stufenbarren, Boden, Reck, Minitrampolin), Leichtathletik
  (80m, Hochsprung, Weitsprung, Kugelstossen) und Plausch (Minitramphochsprung,
  Streetball, Klettern). Kat. A–C mind. 2 Geräte und 2 LA, Kat. D/E mind. 1 + 1.
- Geräte: die Note wird direkt erfasst. LA/Plausch: der Messwert wird über die
  Wertungstabelle in eine Note umgerechnet. Gepflegt wird je Disziplin und Kategorie eine
  Formel; daraus erzeugt die App die Tabelle (eine Zeile je Note 10.00 … 6.00).
- Wird eine Disziplin zu viel geturnt, wird das beste Resultat gestrichen; für eine
  falsche Disziplin (Mindestzahl Geräte/LA nicht erfüllt) gilt Note 6.
- 1.9 Auszeichnung: 30 % der angemeldeten Teilnehmenden je Kategorie.

Jede Kategorie (Sparte × A–E) ist eine Rangliste; jede:r Teilnehmende ist ein Eintrag,
die Disziplinen sind die Positionen der Kategorie (resultat.wert = Messwert,
resultat.note = Note).

Kürzel und KategorieNr wie in der DEBRA-Konfiguration (JET98-20), damit die Auswertung
zur alten Software passt.
"""

import glob
import os
import re
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from .db import get_db

EVENT_NAME = "Jugend-Einzelturntag JET WTU 2026"
EVENT_ORT = "Sportanlage, Rheinau"
EVENT_DATUM = "2026-07-05"

KRANZ_PROZENT = 30.0

# (sparte, geschlecht, Kürzel-Präfix, Bezeichnung in Listen)
SPARTEN = [("JET Mädchen", "w", "M", "Mädchen"), ("JET Knaben", "m", "K", "Knaben")]
SPARTE_GESCHLECHT = {s: g for s, g, _, _ in SPARTEN}

# Kategorie -> (Altersangabe, Anzahl Disziplinen, Alter von, Alter bis)
KATEGORIEN = {
    "A": ("15/16 jährig", 6, 15, 16),
    "B": ("13/14 jährig", 6, 13, 14),
    "C": ("11/12 jährig", 6, 11, 12),
    "D": ("9/10 jährig", 4, 9, 10),
    "E": ("8 und jünger", 4, 0, 8),
}
# Mindestanzahl je Gruppe (Wettkampfangebot): Kat. A–C 2 Geräte + 2 LA, D/E je 1
MINIMUM = {"A": 2, "B": 2, "C": 2, "D": 1, "E": 1}
KAT_NR = {("m", "A"): 1001, ("m", "B"): 1002, ("m", "C"): 1003, ("m", "D"): 1004, ("m", "E"): 1005,
          ("w", "A"): 1011, ("w", "B"): 1012, ("w", "C"): 1013, ("w", "D"): 1014, ("w", "E"): 1015}

GRUPPEN = {"geraete": "Geräte", "la": "Leichtathletik", "plausch": "Plausch"}

# abk -> (Bezeichnung, Gruppe, Einheit, Richtung)
DISZIPLINEN = {
    "BA": ("Barren", "geraete", "Note", "hoch"),
    "SSB": ("Schulstufenbarren", "geraete", "Note", "hoch"),
    "BO": ("Boden", "geraete", "Note", "hoch"),
    "RE": ("Reck", "geraete", "Note", "hoch"),
    "GYM": ("Gymnastik", "geraete", "Note", "hoch"),
    "SP": ("Sprung (Minitrampolin)", "geraete", "Note", "hoch"),
    "80": ("Lauf 80m", "la", "s", "tief"),
    "HO": ("Hochsprung", "la", "m", "hoch"),
    "WE": ("Weitsprung", "la", "m", "hoch"),
    "KUG": ("Kugelstossen", "la", "m", "hoch"),
    "MHO": ("Minitramphochsprung", "plausch", "m", "hoch"),
    "STB": ("Streetball", "plausch", "Treffer", "hoch"),
    "KL": ("Klettern", "plausch", "s", "tief"),
}
# Disziplinen je Geschlecht in der Reihenfolge der Erfassung
PROGRAMM = {
    "m": ["BA", "BO", "RE", "SP", "80", "HO", "WE", "KUG", "MHO", "STB", "KL"],
    "w": ["SSB", "BO", "RE", "GYM", "SP", "80", "HO", "WE", "KUG", "MHO", "STB", "KL"],
}
TABELLEN_DISZ = [d for d, (_, gr, _, _) in DISZIPLINEN.items() if gr != "geraete"]

NOTE_MIN, NOTE_MAX = 6.0, 10.0
NOTE_FALSCH = 6.0

# Standard-Formeln (DEBRA tabDisziplinen JET98-20A..E, damit gerechnet: Rangliste 2026):
# (Knaben, Mädchen); x = Messwert. Die Note wird auf 6.00–10.00 begrenzt.
DEBRA_FORMELN = {
    "80": {"A": ("-x+20.2", "-x+21"), "B": ("-x+21", "-x+21.5"), "C": ("-x+22.2", "-x+22.2"),
           "D": ("-x+22.8", "-x+23.4"), "E": ("-x+24.2", "-x+24.7")},
    "HO": {"A": ("4*x+3.6", "4*x+4"), "B": ("4*x+3.8", "4*x+4.2"), "C": ("4*x+4.2", "4*x+4.6"),
           "D": ("4*x+4.8", "4*x+5"), "E": ("4*x+5.2", "4*x+5.2")},
    "WE": {"A": ("x+4.6", "x+5.2"), "B": ("x+4.9", "x+5.3"), "C": ("x+5.3", "x+5.6"),
           "D": ("x+5.5", "x+6.1"), "E": ("x+6", "x+6.4")},
    "KUG": {"A": ("0.5*x+5.1", "0.8*x+3.6"), "B": ("0.5*x+5.55", "0.8*x+3.6"), "C": ("0.5*x+6", "0.8*x+4.8"),
            "D": ("0.5*x+6.2", "0.8*x+5.4"), "E": ("0.5*x+6.8", "0.8*x+6")},
    "MHO": {"A": ("2.5*x+3.75", "2.5*x+4.25"), "B": ("2.5*x+4", "2.5*x+4.5"), "C": ("2.5*x+4.5", "2.5*x+4.75"),
            "D": ("2.5*x+5", "2.5*x+5"), "E": ("2.5*x+5.25", "2.5*x+5.5")},
    "STB": {k: ("0.4*x+6", "0.4*x+6") for k in "ABCDE"},
    "KL": {"A": ("-6.304*x**0.3+18.5", "-3.596*x**0.415+16.5"), "B": ("-6.304*x**0.3+18.6", "-3.596*x**0.415+16.6"),
           "C": ("-6.304*x**0.3+19.7", "-3.596*x**0.415+16.8"), "D": ("-6.304*x**0.3+19.1", "-3.596*x**0.415+17.2"),
           "E": ("-6.304*x**0.3+19.9", "-3.596*x**0.415+18.1")},
}
# Wertebereich je Disziplin, in dem aus der Formel die Tabelle erzeugt wird (von, bis, -)
FORMEL_RASTER = {"80": (8.0, 26.0, 0.1), "HO": (0.3, 1.8, 0.05), "WE": (0.5, 6.5, 0.1),
                 "KUG": (0.5, 13.0, 0.1), "MHO": (0.3, 2.8, 0.05), "STB": (0, 12, 1), "KL": (1.5, 20.0, 0.05)}
# DEBRA-DisziplinNr -> Kürzel (tabDisziplinen JET98-20; 1010–1074 je Kategorie A–E)
DEBRA_DISZ = {1001: "BA", 1002: "BO", 1003: "RE", 1004: "SP", 1005: "SSB", 1006: "GYM",
              101: "80", 102: "HO", 103: "WE", 104: "KUG", 105: "MHO", 106: "STB", 107: "KL"}


def debra_disz(nr):
    nr = int(nr)
    return DEBRA_DISZ.get(nr) or DEBRA_DISZ.get(nr // 10)


def kat_buchstabe(kat):
    """'A'..'E' einer JET-Kategorie (aus dem Kürzel MA/KB/… oder der Bezeichnung)."""
    abk = kat["abk"] or "" if "abk" in kat.keys() else ""
    if len(abk) == 2 and abk[1] in KATEGORIEN:
        return abk[1]
    m = re.search(r"Kategorie ([A-E])\b", kat["bezeichnung"] or "")
    return m.group(1) if m else "A"


def kategorie_aus_jahrgang(jahrgang, jahr=None):
    """Kategorie A–E aus dem Jahrgang (Alter im Wettkampfjahr); älter als 16 -> None."""
    jahr = jahr or int(EVENT_DATUM[:4])
    try:
        alter = jahr - int(jahrgang)
    except (TypeError, ValueError):
        return None
    for k, (_, _, von, bis) in KATEGORIEN.items():
        if von <= alter <= bis:
            return k
    return None


def ist_jet(kat):
    try:
        return (kat["berechnung"] or "") == "jet"
    except (IndexError, KeyError):
        return False


# --------------------------------------------------------------------------- #
# Anlegen
# --------------------------------------------------------------------------- #
def wettkampf(conn):
    """Wettkampf-Row des JET oder None."""
    return conn.execute(
        "SELECT * FROM wettkampf WHERE name=? OR id IN (SELECT wettkampf_id FROM kategorie "
        "WHERE sparte LIKE 'JET %') ORDER BY id LIMIT 1", (EVENT_NAME,)).fetchone()


def _disziplin_id(cur, abk):
    bez, _, einheit, _ = DISZIPLINEN[abk]
    row = cur.execute("SELECT id FROM disziplin WHERE abk=? AND diszgruppe='JET'", (abk,)).fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)",
                (abk, bez, "JET", einheit))
    return cur.lastrowid


def anlegen(conn=None, aktivieren=False):
    """Legt den JET-Wettkampf samt 10 Kategorien an (nur falls noch nicht vorhanden)."""
    eigen = conn is None
    if eigen:
        conn = get_db()
    cur = conn.cursor()
    w = wettkampf(conn)
    bericht = {"neu": w is None, "wettkampf_id": w["id"] if w else None, "kategorien": 0}
    if w is None:
        if aktivieren:
            cur.execute("UPDATE wettkampf SET aktiv=0")
        cur.execute("INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,?)",
                    (EVENT_NAME, EVENT_ORT, EVENT_DATUM, 1 if aktivieren else 0))
        wk = cur.lastrowid
        bericht["wettkampf_id"] = wk
        sort = 0
        for sparte, gesch, praefix, kurz in SPARTEN:
            for kat, (alter, anzahl, _, _) in KATEGORIEN.items():
                sort += 10
                cur.execute(
                    "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, typ, geschlecht, streich, "
                    "kranz_modus, kranz_wert, kranz_basis, sortierung, sparte, kat_nr, berechnung, "
                    "anzahl_werte, richtung, warn_min, warn_max) "
                    "VALUES(?,?,?,'einzel',?,0,'prozent',?,'rangiert',?,?,?,'jet',0,'hoch',?,?)",
                    (wk, praefix + kat, f"{kurz} Kategorie {kat}, {alter}, {anzahl} Kampf", gesch,
                     KRANZ_PROZENT, sort, sparte, KAT_NR[(gesch, kat)], NOTE_MIN, NOTE_MAX))
                kid = cur.lastrowid
                for pos, abk in enumerate(PROGRAMM[gesch], start=1):
                    cur.execute("INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) "
                                "VALUES(?,?,?)", (kid, _disziplin_id(cur, abk), pos))
                bericht["kategorien"] += 1
    else:
        bericht["kategorien"] = cur.execute("SELECT COUNT(*) c FROM kategorie WHERE wettkampf_id=?",
                                            (w["id"],)).fetchone()["c"]
    formeln_sicherstellen(conn)
    conn.commit()
    if eigen:
        conn.close()
    return bericht


# --------------------------------------------------------------------------- #
# Wertungstabelle
# --------------------------------------------------------------------------- #
class FormelFehler(ValueError):
    pass


def formel_funktion(text):
    """Formel -> Funktion f(x). x = Messwert; DEBRA-Schreibweise [WT] und ^ wird verstanden.

    Erlaubt sind Zahlen, x, + - * / ** (bzw. ^) und Klammern – nichts anderes wird ausgeführt.
    """
    import ast
    roh = (text or "").strip()
    if not roh:
        raise FormelFehler("Formel ist leer")
    t = roh.replace("[WT]", "x").replace("[wt]", "x").replace("^", "**").replace(",", ".")
    t = re.sub(r"\bX\b", "x", t)
    try:
        baum = ast.parse(t, mode="eval")
    except SyntaxError:
        raise FormelFehler(f"„{roh}“ ist keine gültige Formel")
    erlaubt = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)
    for knoten in ast.walk(baum):
        if not isinstance(knoten, erlaubt) or (isinstance(knoten, ast.Name) and knoten.id != "x") \
                or (isinstance(knoten, ast.Constant) and not isinstance(knoten.value, (int, float))):
            raise FormelFehler(f"„{roh}“: nur Zahlen, x, + - * / ^ und Klammern erlaubt")
    code = compile(baum, "<formel>", "eval")

    def f(x):
        return float(eval(code, {"__builtins__": {}}, {"x": x}))
    return f


def formel_tabelle(text, disziplin):
    """Erzeugt aus einer Formel die Tabelle [(wert, note)]: eine Zeile je Note 10.00 … 6.00
    (Schritt 0.10); der Wert ist die Umkehrung der Formel (Bisektion im Wertebereich).
    Die Note wird auf 6.00–10.00 begrenzt. Fehler, wenn die Formel nicht rechnet oder
    nicht in eine Richtung verläuft (höher = besser bzw. bei Zeiten tiefer = besser).
    """
    f = formel_funktion(text)
    von, bis, _ = FORMEL_RASTER[disziplin]
    steigend = DISZIPLINEN[disziplin][3] == "hoch"
    try:
        stuetz = [f(von + (bis - von) * i / 200) for i in range(201)]
    except (ZeroDivisionError, OverflowError, ValueError, TypeError):
        raise FormelFehler(f"„{text}“ lässt sich im Wertebereich {von:g}–{bis:g} nicht berechnen")
    if any(isinstance(v, complex) for v in stuetz):
        raise FormelFehler(f"„{text}“ ergibt keine reellen Zahlen")
    diffs = [b - a for a, b in zip(stuetz, stuetz[1:])]
    if any((d < -1e-9) if steigend else (d > 1e-9) for d in diffs):
        raise FormelFehler(f"„{text}“: die Note muss {'mit dem Wert steigen' if steigend else 'mit der Zeit sinken'}")
    zeilen = []
    for schritt in range(41):
        n = round(NOTE_MAX - schritt * 0.1, 2)
        lo, hi = von, bis
        if (f(lo) - n) * (f(hi) - n) > 0:
            continue                                  # Note im Wertebereich nicht erreichbar
        for _ in range(80):
            mid = (lo + hi) / 2
            if (f(mid) < n) == steigend:
                lo = mid
            else:
                hi = mid
        zeilen.append((round((lo + hi) / 2, 4), n))
    if not zeilen:
        raise FormelFehler(f"„{text}“ erreicht im Wertebereich {von:g}–{bis:g} keine Note zwischen 6 und 10")
    return zeilen


def standard_formel(geschlecht, disziplin, kat):
    return DEBRA_FORMELN[disziplin][kat][0 if geschlecht == "m" else 1]


def formeln(conn, geschlecht, disziplin):
    """{'A': formel, …} einer Disziplin (fehlende = Standard)."""
    res = {k: standard_formel(geschlecht, disziplin, k) for k in KATEGORIEN}
    for r in conn.execute("SELECT kat, formel FROM jet_formel WHERE geschlecht=? AND disziplin=?",
                          (geschlecht, disziplin)):
        res[r["kat"]] = r["formel"]
    return res


def formel_speichern(conn, geschlecht, disziplin, neu):
    """Speichert Formeln {kat: text} und erzeugt daraus die Wertungstabelle der Disziplin.

    Erst werden alle Formeln geprüft – bei einem Fehler wird nichts gespeichert (FormelFehler).
    """
    tabellen = {k: formel_tabelle(text, disziplin) for k, text in neu.items()}
    for k, text in neu.items():
        conn.execute("INSERT INTO jet_formel(geschlecht, disziplin, kat, formel) VALUES(?,?,?,?) "
                     "ON CONFLICT(geschlecht, disziplin, kat) DO UPDATE SET formel=excluded.formel",
                     (geschlecht, disziplin, k, text.strip()))
        conn.execute("DELETE FROM jet_tabelle WHERE geschlecht=? AND disziplin=? AND kat=?",
                     (geschlecht, disziplin, k))
        conn.executemany("INSERT INTO jet_tabelle(geschlecht, disziplin, kat, wert, note) VALUES(?,?,?,?,?)",
                         [(geschlecht, disziplin, k, w, n) for w, n in tabellen[k]])
    conn.commit()
    return sum(len(t) for t in tabellen.values())


def formeln_standard(conn, geschlecht=None, disziplin=None):
    """Setzt die Formeln auf den Standard (DEBRA-Konfiguration, wie Rangliste 2026) und
    erzeugt die Tabellen neu; ohne Angabe für alle Disziplinen beider Sparten."""
    n = 0
    for g in ([geschlecht] if geschlecht else ["m", "w"]):
        for d in ([disziplin] if disziplin else TABELLEN_DISZ):
            n += formel_speichern(conn, g, d, {k: standard_formel(g, d, k) for k in KATEGORIEN})
    return n


def formeln_sicherstellen(conn):
    """Beim ersten Start: Standard-Formeln anlegen und die Tabellen daraus erzeugen
    (ersetzt eine früher geladene WKB-Tabelle) – erfasste Noten werden nachgerechnet."""
    if conn.execute("SELECT 1 FROM jet_formel LIMIT 1").fetchone():
        return False
    formeln_standard(conn)
    noten_neu_berechnen(conn)
    return True


def tabelle(conn, geschlecht, disziplin):
    """{'A': [(wert, note), …], …} einer Disziplin, nach Wert sortiert."""
    res = {k: [] for k in KATEGORIEN}
    for r in conn.execute("SELECT kat, wert, note FROM jet_tabelle WHERE geschlecht=? AND disziplin=? "
                          "ORDER BY wert", (geschlecht, disziplin)):
        res.setdefault(r["kat"], []).append((r["wert"], r["note"]))
    return res


def tabelle_raster(conn, geschlecht, disziplin):
    """Anzeige wie in der WKB: Zeilen je Note, Spalten A–E mit dem Wert."""
    tab = tabelle(conn, geschlecht, disziplin)
    noten = sorted({n for rows in tab.values() for _, n in rows}, reverse=True)
    raster = []
    for n in noten:
        zeile = {"note": n}
        for k, rows in tab.items():
            werte = [w for w, nn in rows if nn == n]
            zeile[k] = werte[0] if len(werte) == 1 else (werte if werte else None)
        raster.append(zeile)
    return raster


def _abrunden(x):
    """Auf Hundertstel abrunden (DEBRA 'Ab'), dezimal gerechnet."""
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_FLOOR))


def note_aus_tabelle(zeilen, wert, richtung="hoch"):
    """Note zu einem Messwert: lineare Interpolation zwischen den Tabellenzeilen.

    Besser als die beste Zeile -> deren Note (10.00), schlechter als die letzte -> deren
    Note (6.00). Gleicher Wert mehrfach (z. B. 0.00 m) -> beste Note dieses Werts.
    """
    if wert is None or not zeilen:
        return None
    punkte = {}
    for w, n in zeilen:
        punkte[w] = max(n, punkte.get(w, n))
    xs = sorted(punkte)
    if richtung == "tief":            # kleinere Zeit = bessere Note
        if wert <= xs[0]:
            return punkte[xs[0]]
        if wert >= xs[-1]:
            return punkte[xs[-1]]
    else:
        if wert >= xs[-1]:
            return punkte[xs[-1]]
        if wert <= xs[0]:
            return punkte[xs[0]]
    for a, b in zip(xs, xs[1:]):
        if a <= wert <= b:
            na, nb = Decimal(repr(punkte[a])), Decimal(repr(punkte[b]))
            da, db, dw = Decimal(repr(a)), Decimal(repr(b)), Decimal(repr(float(wert)))
            n = na + (nb - na) * (dw - da) / (db - da)
            return float(n.quantize(Decimal("0.01"), rounding=ROUND_FLOOR))
    return None


class Umrechner:
    """Rechnet Messwerte über die Wertungstabelle in Noten um (Tabellen gecacht)."""

    def __init__(self, conn):
        self.conn = conn
        self._cache = {}

    def zeilen(self, geschlecht, disziplin, kat):
        key = (geschlecht, disziplin)
        if key not in self._cache:
            self._cache[key] = tabelle(self.conn, geschlecht, disziplin)
        return self._cache[key].get(kat, [])

    def note(self, geschlecht, disziplin, kat, wert):
        if wert is None:
            return None
        bez, gruppe, _, richtung = DISZIPLINEN[disziplin]
        if gruppe == "geraete":
            return round(float(wert), 2)
        if float(wert) == 0:
            return NOTE_FALSCH          # Nuller (kein gültiger Versuch) = Note 6 wie DEBRA
        return note_aus_tabelle(self.zeilen(geschlecht, disziplin, kat), wert, richtung)

    def alle(self, geschlecht):
        """Tabellen aller Mess-Disziplinen {disz: {kat: [[w, n]…]}} – für die Live-Berechnung im Browser."""
        return {d: {k: [list(z) for z in rows] for k, rows in tabelle(self.conn, geschlecht, d).items()}
                for d in TABELLEN_DISZ}


def noten_neu_berechnen(conn, geschlecht=None):
    """Alle JET-Noten aus den gespeicherten Messwerten neu rechnen (nach Tabellen-Änderung)."""
    um = Umrechner(conn)
    sql = ("SELECT r.id, r.wert, r.note, d.abk, k.geschlecht, k.abk AS kabk, k.bezeichnung "
           "FROM resultat r JOIN teilnehmer t ON t.id=r.teilnehmer_id "
           "JOIN kategorie k ON k.id=t.kategorie_id "
           "JOIN kategorie_disziplin kd ON kd.kategorie_id=k.id AND kd.position=r.position "
           "JOIN disziplin d ON d.id=kd.disziplin_id WHERE k.berechnung='jet' AND r.wert IS NOT NULL")
    args = []
    if geschlecht:
        sql += " AND k.geschlecht=?"
        args.append(geschlecht)
    n = 0
    for r in conn.execute(sql, args).fetchall():
        if DISZIPLINEN.get(r["abk"], ("", "geraete"))[1] == "geraete":
            continue
        kat = kat_buchstabe({"abk": r["kabk"], "bezeichnung": r["bezeichnung"]})
        note = um.note(r["geschlecht"], r["abk"], kat, r["wert"])
        if note != r["note"]:
            conn.execute("UPDATE resultat SET note=? WHERE id=?", (note, r["id"]))
            n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------- #
# Wertung
# --------------------------------------------------------------------------- #
def wertung(abks, noten, kat):
    """Total eines JET-Starts.

    abks/noten: Disziplin-Kürzel und Note je Position (None = nicht geturnt).
    Liefert {total, gestrichen: {idx}, falsch: {idx}, fehlend, hinweise, folge}:
    - mehr Disziplinen als verlangt -> die besten streichen (Mindestzahlen bleiben erfüllt)
    - Mindestzahl Geräte/LA nicht erfüllt -> die überzähligen übrigen Disziplinen (die
      besten) zählen als falsche Disziplin mit Note 6
    - fehlende Disziplinen zählen nicht (Hinweis)
    """
    anzahl = KATEGORIEN[kat][1]
    minimum = MINIMUM[kat]
    items = [(i, abks[i], DISZIPLINEN.get(abks[i], ("", "geraete"))[1], n)
             for i, n in enumerate(noten) if n is not None]
    gestrichen, falsch, hinweise = set(), set(), []

    def zaehle(gruppe, ohne=()):
        return sum(1 for i, _, gr, _ in items if gr == gruppe and i not in gestrichen and i not in ohne)

    # zu viele Disziplinen: beste streichen, solange die Mindestzahlen erfüllt bleiben
    while len(items) - len(gestrichen) > anzahl:
        kandidaten = sorted((it for it in items if it[0] not in gestrichen), key=lambda it: -it[3])
        for i, _, gr, _ in kandidaten:
            if gr == "plausch" or zaehle(gr, (i,)) >= minimum:
                gestrichen.add(i)
                break
        else:
            gestrichen.add(kandidaten[0][0])
    if gestrichen:
        hinweise.append(f"{len(gestrichen)} Disziplin(en) zu viel – beste gestrichen")

    # Pflichtplätze: je `minimum` Geräte und LA; die übrigen Plätze sind frei wählbar.
    # Mehr freie Disziplinen als freie Plätze -> falsche Disziplin(en), Note 6.
    frei = []
    for gruppe in ("geraete", "la", "plausch"):
        liste = sorted((it for it in items if it[2] == gruppe and it[0] not in gestrichen),
                       key=lambda it: it[3])
        if gruppe != "plausch":
            if len(liste) < minimum:
                hinweise.append(f"zu wenig {GRUPPEN[gruppe]} ({len(liste)} statt {minimum})")
            liste = liste[minimum:] if len(liste) > minimum else []
            # die schwächsten zählen als Pflicht, die stärkeren als frei gewählt
        frei += liste
    plaetze = anzahl - 2 * minimum
    if len(frei) > plaetze:
        for i, abk, _, _ in sorted(frei, key=lambda it: -it[3])[:len(frei) - plaetze]:
            falsch.add(i)
            hinweise.append(f"{abk} gilt als falsche Disziplin (Note 6)")

    gezaehlt = [(i, NOTE_FALSCH if i in falsch else n) for i, _, _, n in items if i not in gestrichen]
    fehlend = max(0, anzahl - len(gezaehlt))
    if fehlend and items:
        hinweise.append(f"{fehlend} Disziplin(en) fehlen")
    total = sum(Decimal(repr(float(n))) for _, n in gezaehlt) if gezaehlt else None
    return {"total": float(total) if total is not None else None, "gestrichen": gestrichen,
            "falsch": falsch, "fehlend": fehlend, "hinweise": hinweise,
            "folge": [n for _, n in gezaehlt]}


# --------------------------------------------------------------------------- #
# Import der Anmeldungen
# --------------------------------------------------------------------------- #
# Export der Anmeldung (JR_JET.xls / MR_JET.xls): Name | Vorname | Jg | Verein | Zusatz |
# Verband | Kategorie (KA … ME). Die Kategorie wird aus dem Jahrgang bestimmt; die Spalte
# dient nur zur Kontrolle. Alternativ: DEBRA-Startliste nach Kategorie als PDF (mit Startnummern).
STARTNR_BASIS = {"m": 1, "w": 500}


def _geschlecht_aus(text):
    t = (text or "").lower()
    if "knab" in t or os.path.basename(t).startswith("jr"):
        return "m"
    if "dchen" in t or "maedchen" in t or os.path.basename(t).startswith("mr"):
        return "w"
    return None


def parse_excel(path):
    """[{nachname, vorname, jahrgang, verein, zusatz, verband, kat_excel}] aus dem Anmelde-Export."""
    from .jtsst import _rows
    personen = []
    for _, rows in _rows(path):
        for row in rows:
            row = list(row) + [""] * 7
            nach, vor, jg = str(row[0] or "").strip(), str(row[1] or "").strip(), row[2]
            if not nach or str(nach).lower() in ("name", "nachname"):
                continue
            try:
                jg = int(float(jg))
            except (TypeError, ValueError):
                continue
            personen.append({"nachname": nach, "vorname": vor, "jahrgang": jg,
                             "verein": str(row[3] or "").strip(), "zusatz": str(row[4] or "").strip(),
                             "verband": str(row[5] or "").strip(), "kat_excel": str(row[6] or "").strip(),
                             "startnr": None})
    return personen


def parse_startliste_pdf(path):
    """Personen aus der DEBRA-Startliste 'nach Kategorie' (PDF) inkl. Startnummer."""
    import pymupdf
    zeilen = []
    with pymupdf.open(path) as doc:
        for page in doc:
            zeilen += [z.strip() for z in page.get_text().splitlines()]
    personen, kat = [], None
    i = 0
    while i < len(zeilen):
        m = re.match(r"Kategorie ([A-E]),", zeilen[i])
        if m:
            kat = m.group(1)
            i += 1
            continue
        if kat and re.fullmatch(r"\d{1,4}", zeilen[i]) and i + 3 < len(zeilen) \
                and re.fullmatch(r"(19|20)\d\d", zeilen[i + 2]):
            name = zeilen[i + 1]
            teile = name.split(" ")
            # "Oliveira Tinoco Nuno": letzter Teil = Vorname
            nach, vor = (" ".join(teile[:-1]), teile[-1]) if len(teile) > 1 else (name, "")
            verein = zeilen[i + 3]
            zusatz = ""
            mz = re.match(r"(JR|MR|TV|DR)\s+(.*)", verein)
            if mz:
                zusatz, verein = mz.group(1), mz.group(2)
            verband = zeilen[i + 4] if i + 4 < len(zeilen) and zeilen[i + 4].startswith("ZTV") else ""
            personen.append({"nachname": nach, "vorname": vor, "jahrgang": int(zeilen[i + 2]),
                             "verein": verein, "zusatz": zusatz, "verband": verband,
                             "kat_excel": kat, "startnr": int(zeilen[i])})
            i += 5 if verband else 4
            continue
        i += 1
    return personen


def parse_backup(ordner, geschlecht):
    """Personen (inkl. Startnummer, Kategorie, Vermerk und Resultate) aus einem DEBRA-Backup.

    Der Wettkampf der Sparte wird an der KategorieNr in WI_<nr>.txt erkannt (Knaben
    1001–1005, Mädchen 1011–1015). Wert -1 = nicht geturnt; negative StartNr = abgemeldet.
    """
    from .import_backup import _read_csv
    kat_von_nr = {nr: k for (g, k), nr in KAT_NR.items() if g == geschlecht}
    personen = []
    for wi in sorted(glob.glob(os.path.join(ordner, "WI_*.txt"))):
        nr = os.path.basename(wi)[3:-4]
        kats = {int(r["KategorieNr"]) for r in _read_csv(wi) if (r.get("KategorieNr") or "").isdigit()}
        if not kats & set(kat_von_nr):
            continue
        wt, wr = os.path.join(ordner, f"WT_{nr}.txt"), os.path.join(ordner, f"WR_{nr}.txt")
        if not os.path.isfile(wt):
            continue
        res = {}
        if os.path.isfile(wr):
            for r in _read_csv(wr):
                werte = {}
                for i in range(1, 21):
                    dnr = (r.get(f"DisziplinNr{i}") or "0").strip()
                    if dnr in ("", "0"):
                        continue
                    w = (r.get(f"Wert{i}") or "").strip().replace(",", ".")
                    if w in ("", "-1"):
                        continue
                    abk = debra_disz(dnr)
                    if abk:
                        n = (r.get(f"Note{i}") or "").strip().replace(",", ".")
                        werte[abk] = (float(w), float(n) if n not in ("", "-1") else None)
                res[r["StartNr"].strip()] = {"werte": werte, "bemerkung": (r.get("Bemerkung") or "").strip()}
        for t in _read_csv(wt):
            try:
                startnr = int(t["StartNr"])
                knr = int(t["KategorieNr"])
            except (TypeError, ValueError, KeyError):
                continue
            if knr not in kat_von_nr:
                continue
            r = res.get(t["StartNr"].strip(), {})
            bem = r.get("bemerkung", "").lower().rstrip(".")
            status = {"ak": "ak", "nges": "nges", "aufg": "aufg", "disq": "disq", "unfall": "unfall"}.get(bem)
            if startnr < 0 or (t.get("Status") or "").strip() == "10":
                status = "abgem"
            try:
                jg = int(float(t.get("Jahrgang") or 0)) or None
            except ValueError:
                jg = None
            personen.append({"nachname": (t.get("Name") or "").strip(), "vorname": (t.get("Vorname") or "").strip(),
                             "jahrgang": jg, "verein": (t.get("Verein") or "").strip(),
                             "zusatz": (t.get("VereinZusatz") or "").strip(),
                             "verband": (t.get("Verband") or "").strip(), "kat_excel": kat_von_nr[knr],
                             "kat_fix": kat_von_nr[knr], "startnr": abs(startnr), "status": status,
                             "resultate": r.get("werte", {})})
    return personen


def lesen(path, geschlecht=None):
    if os.path.isdir(path):
        return parse_backup(path, geschlecht)
    if str(path).lower().endswith(".pdf"):
        return parse_startliste_pdf(path)
    return parse_excel(path)


def pruefen(dateien, jahr=None):
    """{geschlecht: {datei, personen, je_kat, warnungen}} zur Anzeige vor dem Import.

    dateien: {'m': pfad|None, 'w': pfad|None}
    """
    bericht = {}
    for g, pfad in dateien.items():
        if not pfad:
            continue
        if not os.path.exists(pfad):
            bericht[g] = {"datei": pfad, "personen": [], "je_kat": {}, "warnungen": ["Datei nicht gefunden."]}
            continue
        personen = lesen(pfad, g)
        warn, je_kat, abweichend = [], {k: 0 for k in KATEGORIEN}, 0
        for p in personen:
            p["kat"] = p.get("kat_fix") or kategorie_aus_jahrgang(p["jahrgang"], jahr)
            if p.get("kat_fix") and kategorie_aus_jahrgang(p["jahrgang"], jahr) != p["kat_fix"]:
                warn.append(f"{p['nachname']} {p['vorname']} ({p['jahrgang']}): im Backup in Kategorie "
                            f"{p['kat_fix']} – wird übernommen")
            if p["kat"] is None:
                warn.append(f"{p['nachname']} {p['vorname']} ({p['jahrgang']}): kein JET-Jahrgang")
                continue
            je_kat[p["kat"]] += 1
            k_ex = p["kat_excel"][-1:] if p["kat_excel"] else ""
            if k_ex in KATEGORIEN and k_ex != p["kat"]:
                abweichend += 1
        if abweichend and not any(p.get("kat_fix") for p in personen):
            warn.append(f"{abweichend} Einträge: Kategorie-Spalte passt nicht zum Jahrgang – "
                        "es gilt der Jahrgang (WKB 3.).")
        ohne_nr = sum(1 for p in personen if p["startnr"] is None)
        bericht[g] = {"datei": pfad, "personen": personen, "je_kat": je_kat, "warnungen": warn,
                      "mit_startnr": ohne_nr == 0 and bool(personen),
                      "vereine": len({p["verein"] for p in personen}),
                      "abgemeldet": sum(1 for p in personen if p.get("status") == "abgem"),
                      "resultate": sum(len(p.get("resultate") or {}) for p in personen),
                      "quelle": ("DEBRA-Backup" if os.path.isdir(pfad) else
                                 "Startliste (PDF)" if pfad.lower().endswith(".pdf") else "Excel")}
    return bericht


def importieren(conn, dateien, jahr=None):
    """Ersetzt die JET-Anmeldungen der angegebenen Sparten durch die Personen der Dateien.

    Startnummern aus der Startliste (PDF) bzw. neu vergeben: Mädchen ab 500, Knaben ab 1,
    je Kategorie, Verein und Name.
    """
    b = anlegen(conn)
    wk = b["wettkampf_id"]
    cur = conn.cursor()
    kats = {(k["geschlecht"], kat_buchstabe(k)): k["id"] for k in cur.execute(
        "SELECT * FROM kategorie WHERE wettkampf_id=? AND berechnung='jet'", (wk,)).fetchall()}
    pruefung = pruefen(dateien, jahr)
    bericht = {"personen": 0, "je_sparte": {}, "vereine": 0, "uebersprungen": 0, "resultate": 0}
    um = Umrechner(conn)
    meldeschluss = {}
    for g, info in pruefung.items():
        if not info["personen"]:
            continue
        cur.execute("DELETE FROM teilnehmer WHERE wettkampf_id=? AND kategorie_id IN "
                    "(SELECT id FROM kategorie WHERE wettkampf_id=? AND geschlecht=?)", (wk, wk, g))
        personen = [p for p in info["personen"] if p["kat"]]
        bericht["uebersprungen"] += len(info["personen"]) - len(personen)
        if not info.get("mit_startnr"):
            personen.sort(key=lambda p: (p["kat"], p["verein"].lower(), p["nachname"].lower(),
                                         p["vorname"].lower()))
            for nr, p in enumerate(personen, start=STARTNR_BASIS[g]):
                p["startnr"] = nr
        for p in personen:
            row = cur.execute("SELECT id FROM verein WHERE name=?", (p["verein"],)).fetchone()
            if row:
                vid = row["id"]
            else:
                cur.execute("INSERT INTO verein(name, verband) VALUES(?,?)", (p["verein"], p["verband"] or None))
                vid = cur.lastrowid
                bericht["vereine"] += 1
            kid = kats[(g, p["kat"])]
            meldeschluss[kid] = meldeschluss.get(kid, 0) + 1
            cur.execute(
                "INSERT INTO teilnehmer(wettkampf_id, startnr, vorname, nachname, jahrgang, geschlecht, "
                "verein_id, verein_zusatz, verband, kategorie_id, status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (wk, p["startnr"], p["vorname"], p["nachname"], p["jahrgang"], g, vid,
                 p["zusatz"] or ("JR" if g == "m" else "MR"), p["verband"] or None, kid, p.get("status")))
            tid = cur.lastrowid
            for abk, (wert, note) in (p.get("resultate") or {}).items():
                if abk not in PROGRAMM[g]:
                    continue
                if note is None:
                    note = um.note(g, abk, p["kat"], wert)
                cur.execute("INSERT INTO resultat(teilnehmer_id, position, wert, note, erfasst_von, erfasst_am) "
                            "VALUES(?,?,?,?,?,datetime('now','localtime'))",
                            (tid, PROGRAMM[g].index(abk) + 1, wert, note, "Import"))
                bericht["resultate"] += 1
        bericht["je_sparte"][g] = len(personen)
        bericht["personen"] += len(personen)
        cur.execute("UPDATE kategorie SET anz_meldeschluss=NULL WHERE wettkampf_id=? AND geschlecht=?", (wk, g))
    cur.executemany("UPDATE kategorie SET anz_meldeschluss=? WHERE id=?",
                    [(n, kid) for kid, n in meldeschluss.items()])
    conn.commit()
    return bericht


STANDARD_ORDNER = os.path.join("Inputs", "jet", "Anmeldedaten")
STANDARD_BACKUP = os.path.join("Inputs", "jet", "Backup")


def standard_dateien(ordner=STANDARD_ORDNER):
    """Vorschlag: DEBRA-Backup (Inputs/jet/Backup), sonst JR_JET.xls / MR_JET.xls."""
    from .db import pfad_finden
    res = {"m": None, "w": None}
    backup = pfad_finden(STANDARD_BACKUP)
    ordner = pfad_finden(ordner)
    if os.path.isdir(backup) and glob.glob(os.path.join(backup, "WT_*.txt")):
        for g in res:
            if parse_backup(backup, g):
                res[g] = backup
        if all(res.values()):
            return res
    if not os.path.isdir(ordner):
        return res
    for name in sorted(os.listdir(ordner)):
        if not name.lower().endswith((".xls", ".xlsx")):
            continue
        g = _geschlecht_aus(name)
        if g and res[g] is None:
            res[g] = os.path.join(ordner, name)
    return res


if __name__ == "__main__":
    import sys
    c = get_db()
    if len(sys.argv) >= 2 and sys.argv[1] == "import":
        d = standard_dateien(sys.argv[2] if len(sys.argv) > 2 else STANDARD_ORDNER)
        b = importieren(c, d)
        print(f"JET: {b['personen']} Teilnehmende importiert {b['je_sparte']}, {b['vereine']} neue Vereine")
    else:
        b = anlegen(c)
        print(f"JET-Wettkampf {'angelegt' if b['neu'] else 'war vorhanden'} (ID {b['wettkampf_id']}), "
              f"{b['kategorien']} Kategorien.")
    c.close()
