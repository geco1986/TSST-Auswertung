"""Wendet die Wettkampfbestimmungen (WKB) des Turn-, Spiel- und Stafettentags WTU
auf die Wettkämpfe der Turner und Turnerinnen an.

Grundlage: WKB ZTV-WTU, 06.09.2026, Sportpark Deutweg Winterthur.
- 1.4 Auszeichnungen: pro Disziplin erhalten 30 % der Gruppen einen Preis. Basis ist
      wie in DEBRA die Zahl der Anmeldungen (inkl. Abmeldungen), aufgerundet –
      an den offiziellen Resultaten 2026 geprüft (z. B. 100m: 59 Anm. -> 18 Preise).
- Durchschnitte: Zeiten auf-, Weiten/Höhen auf Hundertstel abgerundet (DEBRA).
- 2.5 Bewertung: Turner = Durchschnitt aller 5 Leistungen,
                  Turnerinnen = Durchschnitt aller 4 Leistungen.
      Bei Gleichstand entscheidet das bessere Einzelresultat.
- Läufe und Stafetten werden nach Zeit rangiert (tiefer = besser),
  Sprünge/Würfe nach Weite/Höhe (höher = besser).

Nur Turner/Turnerinnen werden angepasst; die Jugend-Wettkämpfe (Knaben/Mädchen)
bleiben unverändert.
"""

from .db import get_db

EVENT_NAME = "Turn-, Spiel- und Stafettentag WTU 2026"
EVENT_ORT = "Sportpark Deutweg, Winterthur"
EVENT_DATUM = "2026-09-06"

KRANZ_PROZENT = 30.0
MITGLIEDER = {"Turner": 5, "Turnerinnen": 4}   # Gruppengrösse gemäss WKB 2.2

_STAFETTE = ("stafette", "pendel", "schweden", "olymp", "4x100", "4x400", "4 x 100")
_LAUF = ("lauf", "80m", "100m")


def ist_stafette(bez):
    b = bez.lower()
    return any(k in b for k in _STAFETTE)


def _ist_lauf(bez):
    b = bez.lower()
    return any(k in b for k in _LAUF)


def anwenden(conn=None):
    eigen = conn is None
    if eigen:
        conn = get_db()
    cur = conn.cursor()
    bericht = {"wettkaempfe": 0, "kategorien": 0}

    wettkaempfe = [r["wettkampf_id"] for r in cur.execute(
        "SELECT DISTINCT wettkampf_id FROM kategorie WHERE sparte IN ('Turner','Turnerinnen') "
        "ORDER BY wettkampf_id")]

    if wettkaempfe:
        # Turner und Turnerinnen bilden einen Anlass (TSST) – wie Knaben/Mädchen beim JTSST.
        # Ein DEBRA-Backup liefert sie als zwei Wettkämpfe: hier zusammenführen.
        tsst = wettkaempfe[0]
        for alt in wettkaempfe[1:]:
            for tabelle in ("kategorie", "teilnehmer", "zeitplan"):
                cur.execute(f"UPDATE {tabelle} SET wettkampf_id=? WHERE wettkampf_id=?", (tsst, alt))
            cur.execute("DELETE FROM wettkampf WHERE id=?", (alt,))
        # Nach einem Import (zwei Wettkämpfe zusammengeführt): Reihenfolge wie Rangliste 2026.
        # Eine selbst gewählte Reihenfolge bleibt bei erneutem "WKB anwenden" erhalten.
        if len(wettkaempfe) > 1:
            from .reihenfolge import standard
            standard(conn, tsst)
        cur.execute("UPDATE wettkampf SET aktiv=0")  # eindeutigen aktiven Wettkampf sicherstellen
        cur.execute("UPDATE wettkampf SET name=?, ort=?, datum=?, aktiv=1 WHERE id=?",
                    (EVENT_NAME, EVENT_ORT, EVENT_DATUM, tsst))
        bericht["wettkaempfe"] = 1

        kategorien = cur.execute(
            "SELECT * FROM kategorie WHERE wettkampf_id=? AND sparte IN ('Turner','Turnerinnen')",
            (tsst,)).fetchall()
        for kat in kategorien:
            sparte = kat["sparte"]
            mitglieder = MITGLIEDER.get(sparte, 5)
            bez = kat["bezeichnung"]
            if ist_stafette(bez):
                # Stafette: eine Teamzeit, Rangierung nach Zeit (tiefer = besser)
                berechnung, anzahl, richtung, einheit = "summe", 1, "tief", "s"
                ist_staf = 1
                # 4x100m hat Vorlauf + Final; Frauen ein Final, Männer A/B-Final
                hat_final = 1 if "4x100" in bez.replace(" ", "").lower() else 0
                final_typ = ("ab" if sparte == "Turner" else "einzel") if hat_final else None
                cur.execute(
                    "UPDATE kategorie SET typ='einzel', streich=0, kranz_modus='prozent', "
                    "kranz_wert=?, kranz_basis='angemeldet', berechnung=?, anzahl_werte=?, richtung=?, einheit=?, "
                    "geschlecht=?, ist_stafette=1, hat_final=?, final_typ=?, "
                    "zuschlag_a=?, zuschlag_b=?, zuschlag_a_label=?, zuschlag_b_label=?, bahnen=8 "
                    "WHERE id=?",
                    (KRANZ_PROZENT, berechnung, anzahl, richtung, einheit,
                     "m" if sparte == "Turner" else "w", hat_final, final_typ,
                     2.0, 10.0, "Übergabefehler in Zone", "Übergabefehler ausserhalb", kat["id"]))
                cur.execute(
                    "UPDATE disziplin SET einheit='Zeit' WHERE id IN "
                    "(SELECT disziplin_id FROM kategorie_disziplin WHERE kategorie_id=?)",
                    (kat["id"],))
                bericht["kategorien"] += 1
                continue
            elif _ist_lauf(bez):
                # Lauf: Durchschnitt der Einzelzeiten, tiefer = besser
                berechnung, anzahl, richtung, einheit = "durchschnitt", mitglieder, "tief", "s"
            else:
                # Sprung/Wurf: Durchschnitt der Weiten/Höhen, höher = besser
                berechnung, anzahl, richtung, einheit = "durchschnitt", mitglieder, "hoch", "m"

            cur.execute(
                "UPDATE kategorie SET typ='einzel', streich=0, "
                "kranz_modus='prozent', kranz_wert=?, kranz_basis='angemeldet', "
                "berechnung=?, anzahl_werte=?, richtung=?, einheit=?, "
                "geschlecht=?, ist_stafette=0, hat_final=0 WHERE id=?",
                (KRANZ_PROZENT, berechnung, anzahl, richtung, einheit,
                 "m" if sparte == "Turner" else "w", kat["id"]))
            # Einheit auch auf der zugeordneten Disziplin nachführen
            cur.execute(
                "UPDATE disziplin SET einheit=? WHERE id IN "
                "(SELECT disziplin_id FROM kategorie_disziplin WHERE kategorie_id=?)",
                ("Zeit" if einheit == "s" else "Weite", kat["id"]))
            bericht["kategorien"] += 1

    # Die Software kennt nur die beiden Anlässe TSST und JTSST: übrige Wettkämpfe entfernen.
    if wettkaempfe:
        from .jtsst import EVENT_NAME as JTSST_NAME
        cur.execute(
            "DELETE FROM wettkampf WHERE name<>? AND id NOT IN "
            "(SELECT DISTINCT wettkampf_id FROM kategorie WHERE sparte IN ('Turner','Turnerinnen'))",
            (JTSST_NAME,))
        # verwaiste Disziplinen (keiner Turner/Turnerinnen-Kategorie zugeordnet) löschen
        cur.execute(
            "DELETE FROM disziplin WHERE id NOT IN "
            "(SELECT DISTINCT disziplin_id FROM kategorie_disziplin)")

    conn.commit()
    if eigen:
        conn.close()
    return bericht


if __name__ == "__main__":
    b = anwenden()
    print("WKB angewendet:")
    for k, v in b.items():
        print(f"  {k:12} {v}")
