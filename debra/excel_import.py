"""Import der Anmeldungen aus Excel (.xlsx oder .xls).

Unterstützt beide Formate von 2026:
  - Anmeldezahlen (2026_Anmeldezahlen_TSST.xlsx): Titelzeilen, dann
    Verein | – | Anm.Nr. | <Disziplin-Kürzel …> | TU-Kreuz | Betrag …
    mit Zusatz im Vereinsnamen („Andelfingen DTV“)
  - Export der alten Software (TU_TSST.xls / TI_TSST.xls):
    Verein | Vereinzusatz | Verband | <Disziplin-Kürzel …>
(Blattname TU = Turner, TI = Turnerinnen). Die Disziplin-Spalten enthalten die
Anzahl Gruppen. Spalten werden automatisch den Kategorien zugeordnet; die
endgültige Zuordnung wird im UI bestätigt. Nur Turner/Turnerinnen – die
Jugend-Gruppen (JTSST) bleiben unberührt.
"""
import re

# Excel-Kürzel -> Suchbegriff für die Kategorie (Auto-Zuordnung, case-insensitiv)
ALIAS = {
    "100": "100m", "100m": "100m", "80": "80m", "80m": "80m",
    "ho": "hochsprung", "hoch": "hochsprung",
    "ku": "kugel", "kug": "kugel", "spe": "speer", "speer": "speer",
    "sts": "stein", "stein": "stein", "we": "weit", "weit": "weit",
    "wu": "wurf", "wurf": "wurf", "bw": "wurf", "sb": "schleuder", "schleuder": "schleuder",
    "4x100": "4x100", "4x100m": "4x100", "4x400": "4x400", "4x400m": "4x400",
    "olym": "olymp", "olymp": "olymp", "olymp.": "olymp",
    "ps": "pendel", "pendel": "pendel", "swe": "schweden", "sch": "schweden",
    "schweden": "schweden",
}
# Spalten, die keine Disziplinen sind
IDENT = {"verein", "vereinzusatz", "zusatz", "verband", "anm.nr.", "anm. nr."}
STOP = {"tu-kreuz", "ti-kreuz", "betrag", "teilnehmer", "anmeldung"}

# Basis-Startnummer je Sparte (wie DEBRA 2026: Turner ab 1, Turnerinnen ab 501;
# Jugend ab 1001/2001, siehe jtsst.STARTNR_BASIS)
BASIS = {"Turner": 1, "Turnerinnen": 501}

# Kategorien der Jugend (JTSST) nie anfassen
_OHNE_JUGEND = "COALESCE(sparte,'') NOT IN ('Knaben','Mädchen')"


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip())


def _zelle(v):
    """Excel-Zahl als Text ohne '.0' (xlrd liefert 100.0 für die Spalte '100')."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return _norm(v)


def _verein_split(text):
    """'Andelfingen DTV' -> ('Andelfingen', 'DTV'); Zusatz = Kürzel in Grossbuchstaben am Ende."""
    teile = text.split(" ")
    i = len(teile)
    while i > 1 and re.fullmatch(r"[A-ZÄÖÜ]{2,5}", teile[i - 1]):
        i -= 1
    return " ".join(teile[:i]), " ".join(teile[i:])


def parse(path):
    """Liefert je Blatt: {sparte, disziplinen:[kürzel], zeilen:[{verein,zusatz,verband,counts}]}."""
    from .jtsst import _rows
    sheets = []
    for titel, rows in _rows(path):
        header_row = next((r for r, row in enumerate(rows[:25])
                           if row and _zelle(row[0]).lower() == "verein"), None)
        if header_row is None:
            continue
        headers = {c: _zelle(h) for c, h in enumerate(rows[header_row])}
        low = {c: h.lower() for c, h in headers.items()}
        col_verein = next((c for c, h in low.items() if h == "verein"), 0)
        col_zusatz = next((c for c, h in low.items() if h in ("vereinzusatz", "zusatz")), None)
        col_verband = next((c for c, h in low.items() if h == "verband"), None)
        disc_cols = []
        for c, h in sorted(low.items()):
            if h in STOP:
                break           # rechts davon folgen Betrag, Kontakte …
            if h and h not in IDENT:
                disc_cols.append((c, headers[c]))
        title = titel.upper()
        sparte = "Turner" if title.startswith("TU") else (
            "Turnerinnen" if title.startswith("TI") else None)
        if sparte is None:
            for row in rows[:header_row]:
                v = _zelle(row[0] if row else "").lower()
                if v in ("turner", "turnerinnen"):
                    sparte = v.capitalize(); break
        zeilen = []
        for row in rows[header_row + 1:]:
            def zelle(c):
                return row[c] if c is not None and c < len(row) else None
            verein = _norm(zelle(col_verein))
            if not verein or verein.lower().startswith("total"):
                continue
            zusatz = _norm(zelle(col_zusatz))
            if col_zusatz is None:
                verein, zusatz = _verein_split(verein)
            counts = {}
            for c, abbr in disc_cols:
                v = zelle(c)
                if isinstance(v, (int, float)) and v > 0:
                    counts[abbr] = int(v)
            zeilen.append({"verein": verein, "zusatz": zusatz,
                           "verband": _norm(zelle(col_verband)), "counts": counts})
        if zeilen:
            sheets.append({"sparte": sparte or titel,
                           "disziplinen": [a for _, a in disc_cols], "zeilen": zeilen})
    return sheets


def _kats_je_sparte(conn, sparte):
    gesch = "m" if sparte == "Turner" else "w"
    return conn.execute(
        f"SELECT id, bezeichnung FROM kategorie WHERE geschlecht=? AND {_OHNE_JUGEND} "
        "ORDER BY sortierung, bezeichnung", (gesch,)).fetchall()


def auto_map(conn, sheets):
    """Schlägt je (sparte, kürzel) eine Kategorie-ID vor."""
    vorschlag = {}
    for sh in sheets:
        kats = _kats_je_sparte(conn, sh["sparte"])
        for abbr in sh["disziplinen"]:
            needle = ALIAS.get(abbr.lower())
            cid = None
            if needle:
                for k in kats:
                    if needle in k["bezeichnung"].lower():
                        cid = k["id"]; break
            vorschlag[f"{sh['sparte']}|{abbr}"] = cid
    return vorschlag


def kategorien_je_sparte(conn):
    return {s: _kats_je_sparte(conn, s) for s in ("Turner", "Turnerinnen")}


def importieren(conn, path, mapping, reset=True, offsets=None):
    """Legt Vereine/Anmeldungen an. mapping: {'sparte|kürzel': kat_id}.

    Startnummern: Block je Sparte, innerhalb der Sparte fortlaufend
    (Vereine alphabetisch, pro Verein in Disziplin-Reihenfolge).
    Die Gruppenzahl je Disziplin wird als Anmeldestand bei Meldeschluss gespeichert
    (Basis der Auszeichnungen).
    """
    sheets = parse(path)
    cur = conn.cursor()
    offsets = offsets or BASIS
    angelegt = 0
    meldeschluss = {}

    def verein_id(name, verband):
        """(id, verband) – fehlt der Verband in der Excel, gilt der des Vereins."""
        row = cur.execute("SELECT id, verband FROM verein WHERE name=?", (name,)).fetchone()
        if row:
            if verband:
                cur.execute("UPDATE verein SET verband=? WHERE id=? AND (verband IS NULL OR verband='')",
                            (verband, row["id"]))
            return row["id"], verband or row["verband"]
        cur.execute("INSERT INTO verein(name, verband) VALUES(?,?)", (name, verband or None))
        return cur.lastrowid, verband

    for sh in sheets:
        sparte = sh["sparte"]
        gesch = "m" if sparte == "Turner" else "w"
        if reset:
            cur.execute(
                "DELETE FROM teilnehmer WHERE kategorie_id IN "
                f"(SELECT id FROM kategorie WHERE geschlecht=? AND {_OHNE_JUGEND})", (gesch,))
        ctr = offsets.get(sparte, 100)
        for z in sorted(sh["zeilen"], key=lambda x: x["verein"].lower()):
            if not z["counts"]:
                continue        # Verein ohne Anmeldung (leere Zeile in der Anmeldeliste)
            vid, verband = verein_id(z["verein"], z["verband"])
            items = []
            for abbr, n in z["counts"].items():
                cid = mapping.get(f"{sparte}|{abbr}")
                if not cid:
                    continue
                cat = cur.execute(
                    "SELECT id, wettkampf_id, sortierung FROM kategorie WHERE id=?", (cid,)).fetchone()
                if cat:
                    items.append((cat["sortierung"] or 0, cat, n))
            items.sort(key=lambda x: x[0])
            for _, cat, n in items:
                meldeschluss[cat["id"]] = meldeschluss.get(cat["id"], 0) + n
                for gnr in range(1, n + 1):
                    cur.execute(
                        "INSERT INTO teilnehmer(wettkampf_id, startnr, verein_id, verein_zusatz, "
                        "verband, kategorie_id, gruppennr, geschlecht) VALUES(?,?,?,?,?,?,?,?)",
                        (cat["wettkampf_id"], ctr, vid, z["zusatz"] or None,
                         verband or None, cat["id"], gnr, gesch))
                    ctr += 1
                    angelegt += 1
    cur.executemany("UPDATE kategorie SET anz_meldeschluss=? WHERE id=?",
                    [(n, kid) for kid, n in meldeschluss.items()])
    conn.commit()
    return angelegt
