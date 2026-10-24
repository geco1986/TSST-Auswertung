"""Reihenfolge der Sparten und Disziplinen eines Anlasses (kategorie.sortierung).

Die Reihenfolge gilt überall in der App (Ranglisten, Erfassung, Listen, PDF).
Standard ist die Reihenfolge der offiziellen Ranglisten 2026:
  TSST:  Turnerinnen vor Turnern; Läufe/Sprünge/Würfe, danach die Stafetten
  JTSST: Mädchen vor Knaben; Disziplinen alphabetisch, je Kategorie A, B, C
"""

SPARTEN = ["Turnerinnen", "Turner", "Mädchen", "Knaben", "JET Mädchen", "JET Knaben"]

# Disziplin-Reihenfolge der Rangliste 2026 je Sparte (übrige folgen alphabetisch)
TSST_DISZIPLINEN = {
    "Turnerinnen": ["80m-Lauf", "Hochsprung", "Kugelstossen", "Schleuderball", "Weitsprung", "Wurf",
                    "Schwedenstafette", "4x100m", "Pendelstafette 80m"],
    "Turner": ["100m-Lauf", "Hochsprung", "Kugelstossen", "Speer", "Steinstossen", "Weitsprung",
               "4x100m", "4x400m", "Olympische Stafette", "Pendelstafette 80m"],
}


def _schluessel(kat):
    sparte = kat["sparte"] or ""
    s_idx = SPARTEN.index(sparte) if sparte in SPARTEN else len(SPARTEN)
    liste = TSST_DISZIPLINEN.get(sparte)
    if liste is not None:
        bez = kat["bezeichnung"]
        return (s_idx, liste.index(bez) if bez in liste else len(liste), bez)
    # JTSST: Bezeichnung "Ballwurf Mädchen Kat. A, …" -> alphabetisch nach Disziplin, dann Kat.
    return (s_idx, 0, kat["bezeichnung"])


def standard(conn, wettkampf_id):
    """Setzt die Standard-Reihenfolge (wie Rangliste 2026) für einen Anlass."""
    kats = conn.execute("SELECT id, sparte, bezeichnung FROM kategorie WHERE wettkampf_id=?",
                        (wettkampf_id,)).fetchall()
    for pos, k in enumerate(sorted(kats, key=_schluessel), start=1):
        conn.execute("UPDATE kategorie SET sortierung=? WHERE id=?", (pos * 10, k["id"]))
    conn.commit()
    return len(kats)


def setzen(conn, wettkampf_id, ids):
    """Übernimmt eine Reihenfolge aus der Oberfläche (Liste von Kategorie-IDs)."""
    for pos, kid in enumerate(ids, start=1):
        conn.execute("UPDATE kategorie SET sortierung=? WHERE id=? AND wettkampf_id=?",
                     (pos * 10, kid, wettkampf_id))
    conn.commit()
