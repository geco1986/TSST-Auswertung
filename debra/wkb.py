"""Wendet die Wettkampfbestimmungen (WKB) des Turn-, Spiel- und Stafettentags WTU
auf die Wettkämpfe der Turner und Turnerinnen an.

Grundlage: WKB ZTV-WTU, 06.09.2026, Sportpark Deutweg Winterthur.
- 1.4 Auszeichnungen: pro Disziplin erhalten 30 % der rangierten Gruppen einen Preis.
- 2.5 Bewertung: Turner = Durchschnitt aller 5 Leistungen,
                  Turnerinnen = Durchschnitt aller 4 Leistungen.
      Bei Gleichstand entscheidet das bessere Einzelresultat.
- Läufe und Stafetten werden nach Zeit rangiert (tiefer = besser),
  Sprünge/Würfe nach Weite/Höhe (höher = besser).

Nur Turner/Turnerinnen werden angepasst; die Jugend-Wettkämpfe (Knaben/Mädchen)
bleiben unverändert.
"""

from .db import get_db

EVENT_NAME = "Turn-, Spiel- und Stafettentag WTU"
EVENT_ORT = "Sportpark Deutweg, Winterthur"
EVENT_DATUM = "2026-09-06"

KRANZ_PROZENT = 30.0
MITGLIEDER = {"Turner": 5, "Turnerinnen": 4}   # Gruppengrösse gemäss WKB 2.2

_STAFETTE = ("stafette", "pendel", "schweden", "olymp", "4x100", "4x400", "4 x 100")
_LAUF = ("lauf", "80m", "100m")


def _ist_stafette(bez):
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

    wettkaempfe = cur.execute(
        "SELECT DISTINCT w.id, k.sparte FROM wettkampf w "
        "JOIN kategorie k ON k.wettkampf_id=w.id "
        "WHERE k.sparte IN ('Turner','Turnerinnen')").fetchall()

    if wettkaempfe:
        cur.execute("UPDATE wettkampf SET aktiv=0")  # eindeutigen aktiven Wettkampf sicherstellen

    for w in wettkaempfe:
        sparte = w["sparte"]
        mitglieder = MITGLIEDER.get(sparte, 5)
        # Anlass-Metadaten setzen (Turner-Wettkampf wird aktiviert)
        cur.execute(
            "UPDATE wettkampf SET name=?, ort=?, datum=?, aktiv=? WHERE id=?",
            (f"{EVENT_NAME} – {sparte}", EVENT_ORT, EVENT_DATUM,
             1 if sparte == "Turner" else 0, w["id"]))
        bericht["wettkaempfe"] += 1

        kategorien = cur.execute(
            "SELECT * FROM kategorie WHERE wettkampf_id=?", (w["id"],)).fetchall()
        for kat in kategorien:
            bez = kat["bezeichnung"]
            if _ist_stafette(bez):
                # Stafette: eine Teamzeit, Rangierung nach Zeit (tiefer = besser)
                berechnung, anzahl, richtung, einheit = "summe", 1, "tief", "s"
                ist_staf = 1
                # 4x100m hat Vorlauf + Final; Frauen ein Final, Männer A/B-Final
                hat_final = 1 if "4x100" in bez.replace(" ", "").lower() else 0
                final_typ = ("ab" if sparte == "Turner" else "einzel") if hat_final else None
                cur.execute(
                    "UPDATE kategorie SET typ='einzel', streich=0, kranz_modus='prozent', "
                    "kranz_wert=?, berechnung=?, anzahl_werte=?, richtung=?, einheit=?, "
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
                "kranz_modus='prozent', kranz_wert=?, "
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

    # Diese Software deckt nur Turner/Turnerinnen ab: übrige Wettkämpfe entfernen.
    if wettkaempfe:
        cur.execute(
            "DELETE FROM wettkampf WHERE id NOT IN "
            "(SELECT DISTINCT wettkampf_id FROM kategorie WHERE sparte IN ('Turner','Turnerinnen'))")
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
