"""Demo-Daten: ein kleiner, realistischer Turnwettkampf zum sofortigen Ausprobieren."""

import random

from .db import get_db, init_db


def seed(reset=False):
    init_db()
    conn = get_db()
    cur = conn.cursor()

    if reset:
        for t in ["resultat", "teilnehmer", "kategorie_disziplin", "kategorie",
                  "zeitplan", "verein", "disziplin", "wettkampf", "einstellung"]:
            cur.execute(f"DELETE FROM {t}")

    if cur.execute("SELECT COUNT(*) AS c FROM wettkampf").fetchone()["c"] > 0:
        conn.close()
        return  # bereits befüllt

    # Wettkampf
    cur.execute(
        "INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,1)",
        ("Kantonaler Jugendwettkampf 2025", "Winterthur", "2025-06-14"),
    )
    wk = cur.lastrowid

    # Vereine
    vereine = [
        ("1", "TV Winterthur", "Jugi", "Winterthur"),
        ("2", "STV Wülflingen", "", "Winterthur"),
        ("3", "TV Seen", "Ki+Ju", "Winterthur"),
        ("4", "DTV Töss", "", "Winterthur"),
        ("5", "TV Oberwinterthur", "", "Winterthur"),
    ]
    verein_ids = []
    for nr, name, zusatz, ort in vereine:
        cur.execute("INSERT INTO verein(nummer, name, zusatz, ort) VALUES(?,?,?,?)",
                    (nr, name, zusatz, ort))
        verein_ids.append(cur.lastrowid)

    # Disziplinen (Geräteturnen + Leichtathletik)
    disziplinen = [
        ("BO", "Boden", "Gerät", "Note"),
        ("RE", "Reck", "Gerät", "Note"),
        ("SP", "Sprung", "Gerät", "Note"),
        ("BA", "Barren", "Gerät", "Note"),
        ("W", "Weitsprung", "Leichtathletik", "Note"),
        ("L", "Lauf 60m", "Leichtathletik", "Note"),
        ("BW", "Ballwurf", "Leichtathletik", "Note"),
    ]
    disz_ids = {}
    for abk, bez, grp, einh in disziplinen:
        cur.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)",
                    (abk, bez, grp, einh))
        disz_ids[abk] = cur.lastrowid

    # Kategorien
    kategorien = [
        # abk, bez, typ, geschlecht, streich, kranz_modus, kranz_wert, disziplinen
        ("K1", "Jugend Kunstturnen Tu", "einzel", "m", 0, "prozent", 33.0, ["BO", "RE", "SP", "BA"]),
        ("K2", "Jugend Kunstturnen Ti", "einzel", "w", 0, "prozent", 33.0, ["BO", "RE", "SP", "BA"]),
        ("K3", "Jugend Leichtathletik", "einzel", "alle", 0, "prozent", 33.0, ["W", "L", "BW"]),
        ("S1", "Sektion Jugend", "sektion", "alle", 0, "prozent", 50.0, ["BO", "SP", "L"]),
    ]
    kat_map = {}
    for i, (abk, bez, typ, gesch, streich, km, kw, dlist) in enumerate(kategorien):
        cur.execute(
            "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, typ, geschlecht, "
            "streich, kranz_modus, kranz_wert, sortierung) VALUES(?,?,?,?,?,?,?,?,?)",
            (wk, abk, bez, typ, gesch, streich, km, kw, i),
        )
        kid = cur.lastrowid
        kat_map[abk] = (kid, dlist)
        for pos, d in enumerate(dlist, start=1):
            cur.execute(
                "INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) VALUES(?,?,?)",
                (kid, disz_ids[d], pos),
            )

    # Teilnehmer + Resultate
    vornamen_m = ["Luca", "Noah", "Elias", "Jan", "Nino", "Levi", "Fynn", "Timo"]
    vornamen_w = ["Mia", "Lena", "Sofia", "Emma", "Lara", "Nina", "Alina", "Zoe"]
    nachnamen = ["Meier", "Müller", "Keller", "Steiner", "Baumann", "Frei",
                 "Graf", "Schmid", "Widmer", "Hofer", "Suter", "Brunner"]
    rnd = random.Random(42)

    startnr = 1
    for abk, (kid, dlist) in kat_map.items():
        if abk == "S1":
            continue  # Sektion nutzt dieselben Teilnehmer wie Einzel? Eigene TN für Demo:
        n = 10
        gesch = next(k[4] for k in [k for k in kategorien] if k[0] == abk)
        for _ in range(n):
            if gesch == "w":
                vn = rnd.choice(vornamen_w); g = "w"
            elif gesch == "m":
                vn = rnd.choice(vornamen_m); g = "m"
            else:
                g = rnd.choice(["m", "w"])
                vn = rnd.choice(vornamen_m if g == "m" else vornamen_w)
            nn = rnd.choice(nachnamen)
            jg = rnd.randint(2010, 2014)
            vid = rnd.choice(verein_ids)
            cur.execute(
                "INSERT INTO teilnehmer(wettkampf_id, startnr, vorname, nachname, "
                "jahrgang, geschlecht, verein_id, kategorie_id) VALUES(?,?,?,?,?,?,?,?)",
                (wk, startnr, vn, nn, jg, g, vid, kid),
            )
            tid = cur.lastrowid
            startnr += 1
            for pos in range(1, len(dlist) + 1):
                note = round(rnd.uniform(7.0, 9.8), 2)
                cur.execute(
                    "INSERT INTO resultat(teilnehmer_id, position, note) VALUES(?,?,?)",
                    (tid, pos, note),
                )

    # Sektion S1: Teilnehmer je Verein
    kid, dlist = kat_map["S1"]
    for vid in verein_ids:
        for _ in range(4):
            g = rnd.choice(["m", "w"])
            vn = rnd.choice(vornamen_m if g == "m" else vornamen_w)
            nn = rnd.choice(nachnamen)
            cur.execute(
                "INSERT INTO teilnehmer(wettkampf_id, startnr, vorname, nachname, "
                "jahrgang, geschlecht, verein_id, kategorie_id) VALUES(?,?,?,?,?,?,?,?)",
                (wk, startnr, vn, nn, rnd.randint(2010, 2014), g, vid, kid),
            )
            tid = cur.lastrowid
            startnr += 1
            for pos in range(1, len(dlist) + 1):
                cur.execute(
                    "INSERT INTO resultat(teilnehmer_id, position, note) VALUES(?,?,?)",
                    (tid, pos, round(rnd.uniform(7.5, 9.5), 2)),
                )

    # Zeitplan
    zeitplan = [
        ("08:00", "Türöffnung / Einturnen", "Sporthalle", ""),
        ("09:00", "Start Jugend Kunstturnen", "Halle 1", ""),
        ("11:30", "Start Leichtathletik", "Aussenanlage", ""),
        ("14:00", "Sektionswettkampf", "Halle 1+2", ""),
        ("16:30", "Rangverkündigung", "Festzelt", "mit Auszeichnungen"),
    ]
    for i, (zeit, pp, ort, bem) in enumerate(zeitplan):
        cur.execute(
            "INSERT INTO zeitplan(wettkampf_id, zeit, programmpunkt, ort, bemerkung, sortierung) "
            "VALUES(?,?,?,?,?,?)",
            (wk, zeit, pp, ort, bem, i),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed(reset=True)
    print("Demo-Daten erstellt.")
