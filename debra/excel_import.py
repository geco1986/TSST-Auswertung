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
import os
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

# Kategorien der Jugend (JTSST) und des JET nie anfassen
_OHNE_JUGEND = "COALESCE(sparte,'') NOT IN ('Knaben','Mädchen') AND COALESCE(sparte,'') NOT LIKE 'JET %'"


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
    """Liefert je Blatt: {sparte, disziplinen:[kürzel], zeilen:[{verein,zusatz,verband,counts}],
    total:{kürzel: n}|None (Total-Zeile der Excel)}."""
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
        zeilen, total = [], None
        for row in rows[header_row + 1:]:
            def zelle(c):
                return row[c] if c is not None and c < len(row) else None
            verein = _norm(zelle(col_verein))
            if verein.lower() in ("total", "total:") and total is None:
                total = {abbr: int(zelle(c)) for c, abbr in disc_cols
                         if isinstance(zelle(c), (int, float))}
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
            sheets.append({"sparte": sparte or titel, "disziplinen": [a for _, a in disc_cols],
                           "zeilen": zeilen, "total": total})
    return sheets


def _kats_je_sparte(conn, sparte):
    gesch = "m" if sparte == "Turner" else "w"
    return conn.execute(
        f"SELECT id, bezeichnung FROM kategorie WHERE geschlecht=? AND {_OHNE_JUGEND} "
        "ORDER BY sortierung, bezeichnung", (gesch,)).fetchall()


def _passend(kats, abbr):
    """Kategorie zum Excel-Kürzel; Anfang der Bezeichnung zuerst („100m“ -> 100m-Lauf, nicht 4x100m)."""
    needle = ALIAS.get(abbr.lower())
    if not needle:
        return None
    treffer = ([k for k in kats if k["bezeichnung"].lower().startswith(needle)]
               or [k for k in kats if needle in k["bezeichnung"].lower()])
    return treffer[0] if treffer else None


def auto_map(conn, sheets):
    """Schlägt je (sparte, kürzel) eine Kategorie-ID vor."""
    vorschlag = {}
    for sh in sheets:
        kats = _kats_je_sparte(conn, sh["sparte"])
        for abbr in sh["disziplinen"]:
            k = _passend(kats, abbr)
            cid = k["id"] if k else None
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
        if sparte not in BASIS:
            continue            # weitere Blätter (z. B. Vorjahreszahlen) ignorieren
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


# --------------------------------------------------------------------------- #
# Import aus einem Ordner (TSST- und JTSST-Excel gemeinsam)
# --------------------------------------------------------------------------- #
STANDARD_ORDNER = os.path.join("Inputs", "Import")   # relativ zum Programmverzeichnis


def _dateien(ordner):
    """Erkennt die Excel-Dateien eines Ordners am Inhalt:
    {'tsst': pfad|None, 'jtsst': pfad|None, 'andere': [dateiname]}."""
    from . import jtsst as J
    if not os.path.isdir(ordner):
        raise FileNotFoundError(f"Ordner nicht gefunden: {ordner}")
    res = {"tsst": None, "jtsst": None, "andere": []}
    for name in sorted(os.listdir(ordner)):
        pfad = os.path.join(ordner, name)
        if name.startswith("~$") or not name.lower().endswith((".xlsx", ".xls")):
            continue
        try:
            if any(sh["sparte"] in BASIS for sh in parse(pfad)):
                art = "tsst"
            elif J.parse_uebersicht(pfad):
                art = "jtsst"
            else:
                art = None
        except Exception:  # noqa: BLE001 – unlesbare Datei nur melden
            art = None
        if art and res[art] is None:
            res[art] = pfad
        else:
            res["andere"].append(name)
    return res


def _pruefen_tsst(pfad, mapping):
    """Übersicht je Sparte der TSST-Excel; füllt mapping {'sparte|kürzel': bezeichnung|None}."""
    from .tsst import DISZIPLINEN
    sparten, fehler = [], []
    for sh in parse(pfad):
        sp = sh["sparte"]
        if sp not in BASIS:
            continue
        kats = [{"bezeichnung": bez} for _, bez, _ in DISZIPLINEN[sp]]
        summe = {a: sum(z["counts"].get(a, 0) for z in sh["zeilen"]) for a in sh["disziplinen"]}
        disz, warn = [], []
        for abbr in sh["disziplinen"]:
            k = _passend(kats, abbr)
            ziel = k["bezeichnung"] if k else None
            mapping[f"{sp}|{abbr}"] = ziel
            tot = (sh["total"] or {}).get(abbr)
            disz.append({"name": abbr, "kat": ziel, "n": summe[abbr], "total": tot})
            if ziel is None and summe[abbr]:
                fehler.append(f"{sp}: Spalte „{abbr}“ ist keiner Disziplin zuzuordnen.")
            if tot is not None and tot != summe[abbr]:
                warn.append(f"{abbr}: Summe der Vereine {summe[abbr]}, Total-Zeile {tot}")
        if sh["total"] is None:
            warn.append("Keine Total-Zeile gefunden – Summen nicht abgeglichen.")
        gesehen = set()
        for z in sh["zeilen"]:
            if not z["counts"]:
                continue
            key = (z["verein"], z["zusatz"])
            if key in gesehen:
                warn.append(f"„{' '.join(key)}“ ist mehrfach mit Anmeldungen aufgeführt.")
            gesehen.add(key)
        sparten.append({"anlass": "TSST", "sparte": sp, "datei": os.path.basename(pfad),
                        "vereine": len(gesehen), "gruppen": sum(summe.values()),
                        "disziplinen": disz, "warnungen": warn})
    return sparten, fehler


def _pruefen_jtsst(pfad):
    """Übersicht je Sparte der JTSST-Gesamtübersicht."""
    from . import jtsst as J
    info = {}
    daten = J.parse_uebersicht(pfad, info)
    sparten = []
    for sp in ("Mädchen", "Knaben"):
        if sp not in daten:
            continue
        summe = {}
        for counts in daten[sp].values():
            for key, n in counts.items():
                summe[key] = summe.get(key, 0) + n
        tot = info[sp]["total"] or {}
        disz, warn = [], []
        for (abk, kat), n in sorted(summe.items()):
            name = f"{J.DISZIPLINEN[J._disz_abk(abk, kat)][0]} Kat. {kat}"
            disz.append({"name": name, "kat": name, "n": n, "total": tot.get((abk, kat))})
            if (abk, kat) in tot and tot[(abk, kat)] != n:
                warn.append(f"{name}: Summe der Vereine {n}, Total-Zeile {tot[(abk, kat)]}")
        if not tot:
            warn.append("Keine Total-Zeile gefunden – Summen nicht abgeglichen.")
        for v in info[sp]["doppelt"]:
            warn.append(f"„{v}“ ist mehrfach aufgeführt – nur die letzte Zeile zählt.")
        sparten.append({"anlass": "JTSST", "sparte": sp, "datei": os.path.basename(pfad),
                        "vereine": sum(1 for c in daten[sp].values() if any(c.values())),
                        "gruppen": sum(summe.values()), "disziplinen": disz, "warnungen": warn})
    return sparten


def ordner_pruefen(conn, ordner):
    """Liest den Ordner, ohne etwas zu speichern (Prüfschritt vor dem Import).

    {dateien, sparten:[{anlass, sparte, datei, vereine, gruppen, disziplinen, warnungen}],
     fehler:[…], mapping, bestehend:{anmeldungen, resultate}} – bei Fehlern kein Import.
    """
    d = _dateien(ordner)
    bericht = {"dateien": d, "sparten": [], "fehler": [], "mapping": {}}
    if d["tsst"]:
        sparten, fehler = _pruefen_tsst(d["tsst"], bericht["mapping"])
        bericht["sparten"] += sparten
        bericht["fehler"] += fehler
    if d["jtsst"]:
        bericht["sparten"] += _pruefen_jtsst(d["jtsst"])
    if not bericht["sparten"]:
        bericht["fehler"].append("Keine Anmeldungen gefunden: weder TSST (Blätter TU/TI mit "
                                 "Kopfzeile „Verein“) noch JTSST (Blätter Knaben/Mädchen).")

    # Was beim Import ersetzt wird
    bed = []
    if d["tsst"]:
        bed.append("(COALESCE(k.sparte,'') NOT IN ('Knaben','Mädchen') AND COALESCE(k.sparte,'') NOT LIKE 'JET %')")
    if d["jtsst"]:
        bed.append("k.sparte IN ('Knaben','Mädchen')")
    wo = " OR ".join(bed) or "0"
    ids = f"SELECT t.id FROM teilnehmer t JOIN kategorie k ON k.id=t.kategorie_id WHERE {wo}"
    bericht["bestehend"] = {
        "anmeldungen": conn.execute(f"SELECT COUNT(*) FROM ({ids})").fetchone()[0],
        "resultate": conn.execute(f"SELECT COUNT(*) FROM resultat WHERE teilnehmer_id IN ({ids})").fetchone()[0]
        + conn.execute(f"SELECT COUNT(*) FROM stafette WHERE teilnehmer_id IN ({ids})").fetchone()[0],
    }
    return bericht


def sicherung(conn, grund="vor-import"):
    """Kopie der Datenbank neben der DB-Datei (…sqlite3.<grund>-JJJJMMTT-HHMMSS.bak)."""
    import sqlite3
    from datetime import datetime
    from .db import DB_PATH
    ziel = f"{DB_PATH}.{grund}-{datetime.now():%Y%m%d-%H%M%S}.bak"
    dst = sqlite3.connect(ziel)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    return ziel


def ordner_importieren(conn, ordner):
    """Importiert TSST- und JTSST-Anmeldungen aus dem Ordner und ersetzt die bestehenden.

    Vorher wird die Datenbank gesichert; fehlende TSST-Disziplinen werden angelegt.
    """
    from . import jtsst as J
    from .tsst import anlegen as tsst_anlegen
    pruefung = ordner_pruefen(conn, ordner)
    if pruefung["fehler"]:
        raise ValueError(" ".join(pruefung["fehler"]))
    d = pruefung["dateien"]
    bericht = {"sicherung": sicherung(conn), "tsst": None, "jtsst": None}
    if d["tsst"]:
        wk = tsst_anlegen(conn)["wettkampf_id"]
        ids = {(k["sparte"], k["bezeichnung"]): k["id"] for k in conn.execute(
            "SELECT id, sparte, bezeichnung FROM kategorie WHERE wettkampf_id=?", (wk,))}
        mapping = {key: ids.get((key.split("|")[0], bez))
                   for key, bez in pruefung["mapping"].items() if bez}
        conn.execute("UPDATE kategorie SET anz_meldeschluss=NULL WHERE wettkampf_id=?", (wk,))
        bericht["tsst"] = importieren(conn, d["tsst"], mapping, reset=True)
    if d["jtsst"]:
        bericht["jtsst"] = J.importieren(conn, J.parse_uebersicht(d["jtsst"]), quelle="uebersicht")
    if d["tsst"]:
        conn.execute("UPDATE wettkampf SET aktiv=(id=?)", (wk,))
        conn.commit()
    return bericht


if __name__ == "__main__":
    import sys
    from .db import get_db, init_db
    init_db()
    c = get_db()
    ordner = sys.argv[1] if len(sys.argv) > 1 else STANDARD_ORDNER
    p = ordner_pruefen(c, ordner)
    for s in p["sparten"]:
        print(f"{s['anlass']:5} {s['sparte']:12} {s['vereine']:3} Vereine {s['gruppen']:4} Gruppen  ({s['datei']})")
        for w in s["warnungen"]:
            print("      Hinweis:", w)
    for f in p["fehler"]:
        print("FEHLER:", f)
    if p["fehler"]:
        sys.exit(1)
    if "--ja" not in sys.argv:
        print(f"Ersetzt {p['bestehend']['anmeldungen']} Anmeldungen "
              f"({p['bestehend']['resultate']} Resultate). Zum Importieren mit --ja aufrufen.")
        sys.exit(0)
    b = ordner_importieren(c, ordner)
    print(f"Importiert: TSST {b['tsst']} Gruppen, JTSST {(b['jtsst'] or {}).get('gruppen')} Gruppen.")
    print("Sicherung:", b["sicherung"])
