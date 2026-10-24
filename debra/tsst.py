"""Legt den Turn-, Spiel- und Stafettentag (TSST) mit seinen Disziplinen an.

Bisher entstanden die Disziplinen der Turner/Turnerinnen nur über das DEBRA-Backup.
Damit die Anmeldungen auch ohne Backup direkt aus der Excel importiert werden
können, sind sie hier fest hinterlegt – Kürzel, Bezeichnung und KategorieNr wie im
DEBRA-Backup 2026 (WI_52 Turnerinnen, WI_53 Turner). Die Wertung (Durchschnitt,
Stafetten, Auszeichnungen) setzt anschliessend wkb.anwenden().
"""

from .db import get_db
from .wkb import EVENT_DATUM, EVENT_NAME, EVENT_ORT

# sparte -> [(kürzel, bezeichnung, kat_nr)]
DISZIPLINEN = {
    "Turnerinnen": [
        ("80", "80m-Lauf", 1151), ("BW", "Wurf", 1152), ("4x100", "4x100m", 1153),
        ("SCH", "Schwedenstafette", 1154), ("PS80", "Pendelstafette 80m", 1155),
        ("HO", "Hochsprung", 1156), ("WE", "Weitsprung", 1157), ("KUG", "Kugelstossen", 1158),
        ("SB", "Schleuderball", 1159),
    ],
    "Turner": [
        ("100", "100m-Lauf", 1161), ("STS", "Steinstossen", 1162),
        ("PS80", "Pendelstafette 80m", 1163), ("4x400", "4x400m", 1164),
        ("OLYMP", "Olympische Stafette", 1165), ("4x100", "4x100m", 1166),
        ("HO", "Hochsprung", 1167), ("WE", "Weitsprung", 1168), ("KU", "Kugelstossen", 1169),
        ("SP", "Speer", 1170),
    ],
}


def anlegen(conn=None):
    """Legt den TSST-Wettkampf und fehlende Disziplinen an (bestehende bleiben unverändert)."""
    eigen = conn is None
    if eigen:
        conn = get_db()
    cur = conn.cursor()
    bericht = {"neu": 0, "wettkampf_id": None}

    row = cur.execute(
        "SELECT DISTINCT wettkampf_id AS id FROM kategorie WHERE sparte IN ('Turner','Turnerinnen') "
        "ORDER BY wettkampf_id").fetchone() or cur.execute(
        "SELECT id FROM wettkampf WHERE name=?", (EVENT_NAME,)).fetchone()
    if row:
        wk = row["id"]
    else:
        cur.execute("INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,0)",
                    (EVENT_NAME, EVENT_ORT, EVENT_DATUM))
        wk = cur.lastrowid
    bericht["wettkampf_id"] = wk

    for sparte, liste in DISZIPLINEN.items():
        gesch = "m" if sparte == "Turner" else "w"
        for abk, bez, kat_nr in liste:
            if cur.execute("SELECT 1 FROM kategorie WHERE wettkampf_id=? AND sparte=? AND bezeichnung=?",
                           (wk, sparte, bez)).fetchone():
                continue
            cur.execute(
                "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, geschlecht, sparte, kat_nr) "
                "VALUES(?,?,?,?,?,?)", (wk, abk, bez, gesch, sparte, kat_nr))
            kid = cur.lastrowid
            cur.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)",
                        (abk, bez, sparte, "Note"))
            cur.execute("INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) "
                        "VALUES(?,?,1)", (kid, cur.lastrowid))
            bericht["neu"] += 1

    from .wkb import anwenden
    anwenden(conn)          # Wertung gemäss WKB, aktiviert den TSST
    if bericht["neu"]:
        from .reihenfolge import standard
        standard(conn, wk)
    conn.commit()
    if eigen:
        conn.close()
    return bericht
