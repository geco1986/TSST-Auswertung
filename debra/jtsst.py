"""Legt den Jugendwettkampf (JTSST) gemäss WKB 2026 an.

Grundlage: Wettkampfbestimmungen Jugendwettkämpfe, Turn-, Spiel- und
Stafettentag WTU, Samstag 05.09.2026, Sportpark Deutweg Winterthur.

- 2.1/2.2 Knaben und Mädchen, je Kategorie A (Jg. 2010–2013), B (Jg. 2014–2016),
  C (Jg. 2017 und jünger). Gruppen à 6 Tu/Ti, Schwedenstafette à 4 (nur Kat. A).
- 1.4 Auszeichnungen: pro Disziplin und Kategorie die ersten 30 %.
- 3.1 Seilziehen im Cup-System: erfasst wird der erreichte Cup-Rang (tiefer = besser).
- 3.2 Pendelstafette 1 x 80m: Gesamtzeit, Übergabefehler/Fehlstart je +2 s.
- 3.3 Ballwurf: Durchschnitt der 6 besten Würfe, Tiebreak bestes Einzelresultat.
      Kat. A + B 200 g, Kat. C Tennisball.
- 3.4 Hindernislauf: Totalzeit aller 6, jeder Fehler +2 s.
- 3.5 Seilspringen 1 Minute: Durchschnitt der Sprünge aller 6, Tiebreak bestes Einzelresultat.
- 3.6 Schwedenstafette 100/200/300/400m: Zeit; 2. Fehlstart = Disqualifikation (Vermerk).

Jede Disziplin je Sparte/Kategorie ist eine eigene Kategorie (= eigene Rangliste);
jede angemeldete Gruppe ist ein Teilnehmer-Eintrag.

Bezeichnung, Kürzel und KategorieNr folgen dem DEBRA-Backup des letzten Anlasses
(WI_50 Knaben, WI_51 Mädchen), damit Auswertung und alte Software zusammenpassen.
"""

import re

from .db import get_db

EVENT_NAME = "Jugendwettkämpfe – Turn-, Spiel- und Stafettentag WTU 2026"
EVENT_ORT = "Sportpark Deutweg, Winterthur"
EVENT_DATUM = "2026-09-05"

KRANZ_PROZENT = 30.0

SPARTEN = [("Knaben", "K", "m"), ("Mädchen", "M", "w")]
KATEGORIEN = [("A", "13..16 jährig"), ("B", "10..12 jährig"), ("C", "9 und jünger")]

# Disziplin-Katalog: abk -> (bezeichnung, einheit)
DISZIPLINEN = {
    "SZ": ("Seilziehen", "Anzahl"),
    "PS": ("Pendelstafette 1 x 80m", "Zeit"),
    "BW": ("Ballwurf 200g", "Weite"),
    "BWT": ("Ballwurf (Tennisball)", "Weite"),
    "HL": ("Hindernislauf", "Zeit"),
    "SS": ("Seilspringen 1 Minute", "Anzahl"),
    "SCH": ("Schwedenstafette", "Zeit"),
}

# DEBRA-Definition: Name und Kürzel-Präfix je Disziplin (Kürzel = Präfix + Kategorie)
DEBRA_DISZ = {"SZ": ("Seilziehen", "S"), "PS": ("Pendelstafette", "PS"),
              "BW": ("Ballwurf", "W"), "BWT": ("Ballwurf", "W"),
              "HL": ("Hindernislauf", "H"), "SS": ("Seilspringen", "SS"),
              "SCH": ("Schwedenstafette", "SCH")}
# KategorieNr aus dem Backup: (sparte, abk, kat) -> nr
DEBRA_KAT_NR = {
    ("Knaben", "PS", "A"): 1101, ("Knaben", "PS", "B"): 1102, ("Knaben", "PS", "C"): 1103,
    ("Knaben", "BW", "B"): 1104, ("Knaben", "BWT", "C"): 1105,
    ("Knaben", "SZ", "A"): 1106, ("Knaben", "SZ", "B"): 1107, ("Knaben", "SZ", "C"): 1108,
    ("Knaben", "SCH", "A"): 1110,
    ("Knaben", "HL", "A"): 1111, ("Knaben", "HL", "B"): 1112, ("Knaben", "HL", "C"): 1113,
    ("Knaben", "BW", "A"): 1114,
    ("Knaben", "SS", "A"): 1116, ("Knaben", "SS", "B"): 1117, ("Knaben", "SS", "C"): 1118,
    ("Mädchen", "SS", "A"): 1120, ("Mädchen", "SS", "B"): 1121, ("Mädchen", "SS", "C"): 1122,
    ("Mädchen", "PS", "A"): 1123, ("Mädchen", "PS", "B"): 1124, ("Mädchen", "PS", "C"): 1125,
    ("Mädchen", "SZ", "A"): 1126, ("Mädchen", "SZ", "B"): 1127, ("Mädchen", "SZ", "C"): 1128,
    ("Mädchen", "SCH", "A"): 1129,
    ("Mädchen", "HL", "A"): 1130, ("Mädchen", "HL", "B"): 1131, ("Mädchen", "HL", "C"): 1132,
    ("Mädchen", "BW", "A"): 1135, ("Mädchen", "BW", "B"): 1136, ("Mädchen", "BWT", "C"): 1137,
}


def _debra(sparte, kat, abk):
    """(kürzel, bezeichnung, kat_nr) einer Kategorie gemäss DEBRA-Backup."""
    name, praefix = DEBRA_DISZ[abk]
    alter = dict(KATEGORIEN)[kat]
    return (f"{praefix}{kat}", f"{name} {sparte} Kat. {kat}, {alter}",
            DEBRA_KAT_NR[(sparte, abk, kat)])


def _programm(kat):
    """Disziplinen einer Kategorie in der Reihenfolge der WKB 2.1/2.2."""
    liste = ["SZ", "PS", "BWT" if kat == "C" else "BW", "HL", "SS"]
    if kat == "A":
        liste.append("SCH")
    return liste


# Wertungsparameter je Disziplin (abk) – Spalten der Tabelle kategorie
def _wertung(abk):
    basis = dict(typ="einzel", streich=0, kranz_modus="prozent", kranz_wert=KRANZ_PROZENT,
                 berechnung="durchschnitt", anzahl_werte=6, richtung="hoch", einheit=None,
                 ist_stafette=0, hat_final=0, final_typ=None,
                 zuschlag_a=0.0, zuschlag_b=0.0, zuschlag_a_label=None, zuschlag_b_label=None,
                 bahnen=8, warn_min=None, warn_max=None)
    if abk == "SZ":
        basis.update(berechnung="summe", anzahl_werte=1, richtung="tief", einheit="Rang",
                     warn_min=1, warn_max=64)
    elif abk == "PS":
        basis.update(ist_stafette=1, richtung="tief", einheit="s", zuschlag_a=2.0,
                     zuschlag_a_label="Übergabefehler/Fehlstart", zuschlag_b_label="—")
    elif abk == "HL":
        basis.update(ist_stafette=1, richtung="tief", einheit="s", zuschlag_a=2.0,
                     zuschlag_a_label="Fehler", zuschlag_b_label="—")
    elif abk == "SCH":
        basis.update(ist_stafette=1, anzahl_werte=4, richtung="tief", einheit="s",
                     zuschlag_a_label="—", zuschlag_b_label="—")
    elif abk == "BW":
        basis.update(einheit="m", warn_min=5, warn_max=80)
    elif abk == "BWT":
        basis.update(einheit="m", warn_min=3, warn_max=60)
    elif abk == "SS":
        basis.update(einheit="Sprünge", warn_min=0, warn_max=250)
    return basis


def _disziplin_id(cur, abk):
    bez, einheit = DISZIPLINEN[abk]
    row = cur.execute("SELECT id FROM disziplin WHERE bezeichnung=? AND diszgruppe='Jugend'",
                      (bez,)).fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)",
                (abk, bez, "Jugend", einheit))
    return cur.lastrowid


def _kategorien(cur, wk):
    """{(sparte, disziplin-abk, kat): kategorie-row} des JTSST-Wettkampfs."""
    rows = cur.execute(
        "SELECT k.id, k.abk, k.bezeichnung, k.sparte, k.sortierung, d.abk AS disz "
        "FROM kategorie k JOIN kategorie_disziplin kd ON kd.kategorie_id=k.id AND kd.position=1 "
        "JOIN disziplin d ON d.id=kd.disziplin_id WHERE k.wettkampf_id=?", (wk,)).fetchall()
    kats = {}
    for k in rows:
        m = re.search(r"Kat\. ([ABC])\b", k["bezeichnung"])
        if m and k["sparte"]:
            kats[(k["sparte"], k["disz"], m.group(1))] = k
    return kats


def _angleichen(cur, wk):
    """Bringt Kürzel, Bezeichnung und KategorieNr bestehender Kategorien auf DEBRA-Stand."""
    n = 0
    for (sparte, abk, kat), k in _kategorien(cur, wk).items():
        if (sparte, abk, kat) not in DEBRA_KAT_NR:
            continue
        kuerzel, bez, nr = _debra(sparte, kat, abk)
        cur.execute("UPDATE kategorie SET abk=?, bezeichnung=?, kat_nr=? WHERE id=?",
                    (kuerzel, bez, nr, k["id"]))
        n += 1
    return n


def anlegen(conn=None, aktivieren=True):
    """Legt den JTSST-Wettkampf samt Kategorien an (nur falls noch nicht vorhanden)."""
    eigen = conn is None
    if eigen:
        conn = get_db()
    cur = conn.cursor()
    bericht = {"neu": False, "wettkampf_id": None, "kategorien": 0}

    vorhanden = cur.execute("SELECT id FROM wettkampf WHERE name=?", (EVENT_NAME,)).fetchone()
    if vorhanden:
        bericht["wettkampf_id"] = vorhanden["id"]
        bericht["kategorien"] = cur.execute(
            "SELECT COUNT(*) c FROM kategorie WHERE wettkampf_id=?", (vorhanden["id"],)
        ).fetchone()["c"]
        bericht["angeglichen"] = _angleichen(cur, vorhanden["id"])
    else:
        if aktivieren:
            cur.execute("UPDATE wettkampf SET aktiv=0")
        cur.execute("INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,?)",
                    (EVENT_NAME, EVENT_ORT, EVENT_DATUM, 1 if aktivieren else 0))
        wk = cur.lastrowid
        bericht.update(neu=True, wettkampf_id=wk)

        sort = 0
        for sparte, _, geschlecht in SPARTEN:
            for kat, _ in KATEGORIEN:
                for abk in _programm(kat):
                    did = _disziplin_id(cur, abk)
                    w = _wertung(abk)
                    kuerzel, bez, kat_nr = _debra(sparte, kat, abk)
                    sort += 1
                    cur.execute(
                        "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, typ, geschlecht, "
                        "streich, kranz_modus, kranz_wert, sortierung, sparte, kat_nr, berechnung, "
                        "anzahl_werte, richtung, einheit, ist_stafette, hat_final, final_typ, "
                        "zuschlag_a, zuschlag_b, zuschlag_a_label, zuschlag_b_label, bahnen, "
                        "warn_min, warn_max) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (wk, kuerzel, bez,
                         w["typ"], geschlecht, w["streich"], w["kranz_modus"], w["kranz_wert"],
                         sort, sparte, kat_nr, w["berechnung"], w["anzahl_werte"], w["richtung"],
                         w["einheit"], w["ist_stafette"], w["hat_final"], w["final_typ"],
                         w["zuschlag_a"], w["zuschlag_b"], w["zuschlag_a_label"],
                         w["zuschlag_b_label"], w["bahnen"], w["warn_min"], w["warn_max"]))
                    cur.execute("INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) "
                                "VALUES(?,?,1)", (cur.lastrowid, did))
                    bericht["kategorien"] += 1
        from .reihenfolge import standard
        standard(conn, wk)

    conn.commit()
    if eigen:
        conn.close()
    return bericht


# --------------------------------------------------------------------------- #
# Import der Anmeldungen
# --------------------------------------------------------------------------- #
# Gesamtübersicht (Anmeldungen JTSST <Jahr>.xlsx): Blätter „Knaben“/„Mädchen“,
# Zeile 1 Disziplin-Namen, Zeile 2 Kategorie A/B/C, ab Zeile 3 ein Verein je Zeile.
UEBERSICHT_DISZ = {"hindernislauf": "HL", "pendelstafette": "PS", "ballwurf": "BW",
                   "seilspringen": "SS", "seilziehen": "SZ", "schwedenstafette": "SCH"}
# Export der alten Software (JR_TSST.xls / MR_TSST.xls):
# Verein | Vereinzusatz | Verband | HA HB HC PSA … SCH … (Anzahl Gruppen)
ALT_DISZ = {"H": "HL", "PS": "PS", "W": "BW", "S": "SZ", "SS": "SS", "SCH": "SCH"}

# Startnummern-Block je Sparte (eindeutig über alle Wettkämpfe)
STARTNR_BASIS = {"Knaben": 1001, "Mädchen": 2001}


def _sparte(text):
    t = str(text or "").strip().lower()
    if t.startswith("knab") or t in ("jr", "jugendriege"):
        return "Knaben"
    if "dchen" in t or t in ("mr", "mädchenriege"):
        return "Mädchen"
    return None


def _disz_abk(abk, kat):
    """Ballwurf in Kategorie C ist der Tennisball-Wurf."""
    return "BWT" if abk == "BW" and kat == "C" else abk


def _rows(path):
    """Liefert [(blattname, [zeilen als Listen])] für .xlsx und .xls."""
    if str(path).lower().endswith(".xls"):
        import xlrd
        wb = xlrd.open_workbook(path)
        return [(sh.name, [sh.row_values(r) for r in range(sh.nrows)]) for sh in wb.sheets()]
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]


def _zahl(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def parse_uebersicht(path, info=None):
    """{sparte: {verein: {(abk, kat): anzahl}}} aus der Gesamtübersicht.

    info (optional, dict) erhält je Sparte die Total-Zeile der Excel ("total") und
    mehrfach aufgeführte Vereine ("doppelt") – für die Prüfung vor dem Import.
    """
    daten = {}
    for titel, rows in _rows(path):
        sparte = _sparte(titel)
        if not sparte or len(rows) < 3:
            continue
        cols, aktuell = {}, None
        for i, (d, k) in enumerate(zip(rows[0], rows[1])):
            name = str(d or "").strip().lower()
            if name:
                aktuell = UEBERSICHT_DISZ.get(name)
            if aktuell and str(k or "").strip() in ("A", "B", "C"):
                cols[i] = (aktuell, str(k).strip())
        vereine, total, doppelt = {}, None, []
        for row in rows[2:]:
            verein = str(row[0] or "").strip()
            if verein.lower().startswith("total"):
                total = {key: _zahl(row[i]) for i, key in cols.items()}
                break
            if verein:
                if verein in vereine:
                    doppelt.append(verein)
                vereine[verein] = {key: _zahl(row[i]) for i, key in cols.items()}
        daten[sparte] = vereine
        if info is not None:
            info[sparte] = {"total": total, "doppelt": doppelt}
    return daten


def parse_alt(path):
    """{sparte: {verein: {"counts": {(abk, kat): n}, "zusatz", "verband"}}} aus dem Alt-Export."""
    daten = {}
    for titel, rows in _rows(path):
        if not rows or str(rows[0][0] or "").strip().lower() != "verein":
            continue
        hdr = [str(h or "").strip() for h in rows[0]]
        vereine = {}
        sparte = _sparte(titel)
        for row in rows[1:]:
            verein = str(row[0] or "").strip()
            if not verein:
                continue
            sparte = sparte or _sparte(row[1])
            counts = {}
            for i, h in enumerate(hdr[3:], 3):
                if h == "SCH":
                    counts[("SCH", "A")] = _zahl(row[i])
                elif h[:-1] in ALT_DISZ and h[-1] in "ABC":
                    counts[(ALT_DISZ[h[:-1]], h[-1])] = _zahl(row[i])
            vereine[verein] = {"counts": counts, "zusatz": str(row[1] or "").strip(),
                               "verband": str(row[2] or "").strip()}
        if sparte:
            daten[sparte] = vereine
    return daten


def vergleichen(uebersicht, alt):
    """Abweichungen zwischen Gesamtübersicht und Alt-Export (Liste von Texten)."""
    diffs = []
    for sparte in sorted(set(uebersicht) | set(alt)):
        ue, al = uebersicht.get(sparte, {}), alt.get(sparte, {})
        for verein in sorted(set(ue) | set(al)):
            if verein not in ue or verein not in al:
                wo = "Übersicht" if verein in ue else "Alt-Export"
                diffs.append(f"{sparte} {verein}: nur in {wo}")
                continue
            for key in sorted(set(ue[verein]) | set(al[verein]["counts"])):
                a, b = ue[verein].get(key, 0), al[verein]["counts"].get(key, 0)
                if a != b:
                    diffs.append(f"{sparte} {verein} {DISZIPLINEN[_disz_abk(*key)][0]} "
                                 f"Kat. {key[1]}: Übersicht {a}, Alt-Export {b}")
    return diffs


def importieren(conn, uebersicht=None, alt=None, quelle="uebersicht"):
    """Legt die Gruppen des JTSST-Wettkampfs an (ersetzt bestehende JTSST-Anmeldungen).

    quelle 'uebersicht': Anzahl Gruppen aus der Gesamtübersicht, Vereinszusatz/Verband
    aus dem Alt-Export (falls vorhanden). quelle 'alt': alles aus dem Alt-Export.
    Startnummern: Block je Sparte, Vereine alphabetisch, je Verein in
    Disziplin-/Kategorie-Reihenfolge.
    """
    uebersicht, alt = uebersicht or {}, alt or {}
    zaehlung = uebersicht if quelle == "uebersicht" else {
        s: {v: d["counts"] for v, d in vs.items()} for s, vs in alt.items()}
    if not zaehlung:
        raise ValueError("Keine Anmeldedaten gefunden.")

    b = anlegen(conn, aktivieren=False)
    wk = b["wettkampf_id"]
    cur = conn.cursor()
    kats = _kategorien(cur, wk)

    cur.execute("DELETE FROM teilnehmer WHERE wettkampf_id=?", (wk,))
    bericht = {"gruppen": 0, "vereine": 0, "je_sparte": {}, "fehlende_kategorien": []}
    meldeschluss = {}   # kategorie_id -> angemeldete Gruppen (Basis der Auszeichnungen)

    for sparte in ("Knaben", "Mädchen"):
        nr = STARTNR_BASIS[sparte]
        default_zusatz = "JR" if sparte == "Knaben" else "MR"
        anzahl = 0
        for verein in sorted(zaehlung.get(sparte, {}), key=str.lower):
            info = alt.get(sparte, {}).get(verein, {})
            verband = info.get("verband") or None
            zusatz = info.get("zusatz") or default_zusatz
            row = cur.execute("SELECT id, verband FROM verein WHERE name=?", (verein,)).fetchone()
            if row:
                vid = row["id"]
                if not verband:
                    verband = row["verband"]    # fehlt in der Gesamtübersicht
                else:
                    cur.execute("UPDATE verein SET verband=? WHERE id=? AND (verband IS NULL OR verband='')",
                                (verband, vid))
            else:
                cur.execute("INSERT INTO verein(name, verband) VALUES(?,?)", (verein, verband))
                vid = cur.lastrowid
                bericht["vereine"] += 1
            items = []
            for (abk, kat), n in zaehlung[sparte][verein].items():
                if n <= 0:
                    continue
                k = kats.get((sparte, _disz_abk(abk, kat), kat))
                if k is None:
                    bericht["fehlende_kategorien"].append(f"{sparte} {abk} {kat} ({verein})")
                    continue
                items.append((k["sortierung"], k["id"], n))
            for _, kid, n in sorted(items):
                meldeschluss[kid] = meldeschluss.get(kid, 0) + n
                for gnr in range(1, n + 1):
                    cur.execute(
                        "INSERT INTO teilnehmer(wettkampf_id, startnr, verein_id, verein_zusatz, "
                        "verband, kategorie_id, gruppennr, geschlecht) VALUES(?,?,?,?,?,?,?,?)",
                        (wk, nr, vid, zusatz, verband, kid, gnr,
                         "m" if sparte == "Knaben" else "w"))
                    nr += 1
                    anzahl += 1
        bericht["je_sparte"][sparte] = anzahl
        bericht["gruppen"] += anzahl
    cur.execute("UPDATE kategorie SET anz_meldeschluss=NULL WHERE wettkampf_id=?", (wk,))
    cur.executemany("UPDATE kategorie SET anz_meldeschluss=? WHERE id=?",
                    [(n, kid) for kid, n in meldeschluss.items()])
    conn.commit()
    return bericht


def import_ordner(conn, ordner, quelle="uebersicht"):
    """Sucht im Ordner die Gesamtübersicht (*Anmeldungen*.xlsx) und die Alt-Exporte (*.xls)."""
    import glob
    import os
    if not os.path.isdir(ordner):
        raise FileNotFoundError(f"Ordner nicht gefunden: {ordner}")
    ue_dateien = [p for p in glob.glob(os.path.join(ordner, "*.xlsx"))
                  if "anmeldung" in os.path.basename(p).lower()]
    alt_dateien = glob.glob(os.path.join(ordner, "*.xls"))
    uebersicht = parse_uebersicht(ue_dateien[0]) if ue_dateien else {}
    alt = {}
    for p in alt_dateien:
        alt.update(parse_alt(p))
    if quelle == "uebersicht" and not uebersicht:
        quelle = "alt"
    bericht = importieren(conn, uebersicht, alt, quelle)
    bericht["quelle"] = quelle
    bericht["dateien"] = [os.path.basename(p) for p in ue_dateien + alt_dateien]
    bericht["abweichungen"] = vergleichen(uebersicht, alt) if uebersicht and alt else []
    return bericht


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "import":
        quelle = sys.argv[3] if len(sys.argv) > 3 else "uebersicht"
        c = get_db()
        b = import_ordner(c, sys.argv[2], quelle)
        c.close()
        print(f"Import aus {', '.join(b['dateien'])} (Quelle: {b['quelle']})")
        print(f"  {b['gruppen']} Gruppen angelegt {b['je_sparte']}, {b['vereine']} neue Vereine")
        for f in b["fehlende_kategorien"]:
            print("  Keine Kategorie für:", f)
        if b["abweichungen"]:
            print(f"  {len(b['abweichungen'])} Abweichungen Übersicht <-> Alt-Export:")
            for d in b["abweichungen"]:
                print("   -", d)
    else:
        b = anlegen()
        status = "angelegt" if b["neu"] else "war bereits vorhanden"
        print(f"JTSST-Wettkampf {status} (ID {b['wettkampf_id']}), {b['kategorien']} Disziplinen/Kategorien.")
