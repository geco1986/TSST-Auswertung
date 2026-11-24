"""JTSST Seilziehen: K.-o.-System mit höchstens einem Freilos und Lucky Loser.

Runden aus der Teilnehmerzahl – so viele wie möglich: In jeder Runde ziehen je zwei Gruppen
gegeneinander. Ist die Anzahl Gruppen ungerade (nur in der 1. Runde möglich), erhält eine Gruppe
das einzige Freilos. Ist die Anzahl Sieger ungerade, kommt zusätzlich ein Lucky Loser (ein
Verlierer dieser Runde) weiter. So bleiben am Schluss genau 4 Gruppen für die Halbfinals.
Benannt werden die Runden vom Final her: Final, 1/2-, 1/4-, 1/8-, 1/16-, 1/32-Final …
Beispiel 51 Gruppen: 25 Züge + Freilos → 26 → 13 Züge + Lucky Loser → 14 → 7 Züge + Lucky
Loser → 8 → 1/4-Final → 1/2-Final → Final (wie die Rangliste 2026).

Eingabe: Das Wettkampfbüro erhält ein Blatt mit den Plätzen 1–4 (Verein + Gruppen-Nr.)
und den in den Finalrunden Ausgeschiedenen. Alle Ausgeschiedenen einer Runde teilen sich
den Platz. Auszeichnung nach ganzen Runden: so viele Runden, dass höchstens der Prozent-
Anteil (30 %) erreicht wird – nicht genau nach Platzierung (wie die Rangliste 2026).

Einteilung: Gesetzt wird nur die Gruppe 1 eines Vereins, nach Vorjahresrang; die beste erhält
das Freilos, die Gesetzten treffen erst spät aufeinander. 2. und weitere Gruppen eines Vereins
werden nie gesetzt; Gruppen desselben Vereins treffen so spät wie möglich aufeinander.
"""
import random

# Runde -> (Bezeichnung, Reihenfolge; tiefer = weiter gekommen)
RUNDEN = {
    "p1": ("1. Platz", 1), "p2": ("2. Platz", 2), "p3": ("3. Platz", 3), "p4": ("4. Platz", 4),
    "r4": ("1/4-Final", 5), "r8": ("1/8-Final", 6), "r16": ("1/16-Final", 7),
    "r32": ("1/32-Final", 8), "r64": ("1/64-Final", 9), "r128": ("1/128-Final", 10),
    "r256": ("1/256-Final", 11),
    "vorrunde": ("Vorrunde", 12),             # nur noch für ältere Eingaben
}
PLAETZE = ("p1", "p2", "p3", "p4")


def rundenname(groesse):
    """Name der Runde nach Abstand zum Final: 2 Final, 4 1/2-Final, 8 1/4-Final …"""
    return {2: "Final", 4: "1/2-Final"}.get(groesse, f"1/{groesse // 2}-Final")


def tableau(n):
    """Ablauf für n Gruppen.

    runden: Runden vor den Halbfinals, je {key, name, gruppen, zuege, freilos, lucky_loser}.
    stufen: [(runde, erwartete Anzahl Ausgeschiedene)] vom Sieger bis zur ersten Runde.
    freilos: 1, wenn es in der 1. Runde ein Freilos gibt; zuege: Züge der 1. Runde.
    """
    runden, m = [], n
    while m > 4:
        zuege, freilos = m // 2, m % 2
        sieger = zuege + freilos
        ll = sieger % 2                      # ungerade Anzahl Sieger -> Lucky Loser
        runden.append({"gruppen": m, "zuege": zuege, "freilos": freilos, "lucky_loser": ll})
        m = sieger + ll
    for i, r in enumerate(runden):
        groesse = 2 ** (len(runden) - i + 2)   # Runde vor den Halbfinals = 1/4-Final
        r.update(key=f"r{groesse // 2}", name=rundenname(groesse))

    plaetze = {4: PLAETZE, 3: PLAETZE[:3], 2: PLAETZE[:2], 1: PLAETZE[:1]}.get(m, ())
    stufen = [(p, 1) for p in plaetze]
    stufen += [(r["key"], r["zuege"] - r["lucky_loser"]) for r in reversed(runden)]
    return {"runden": runden, "stufen": stufen,
            "freilos": runden[0]["freilos"] if runden else (1 if m == 3 else 0),
            "zuege": runden[0]["zuege"] if runden else m // 2,
            "lucky_loser": sum(r["lucky_loser"] for r in runden),
            "erste": runden[0]["name"] if runden else rundenname(4 if m >= 3 else 2)}


def erste_runde(n):
    """Runde, in der die nicht auf dem Blatt aufgeführten Gruppen ausgeschieden sind."""
    stufen = tableau(n)["stufen"]
    return stufen[-1][0] if stufen else "p1"


def raenge(runden):
    """{tid: runde} -> {tid: rang}: Plätze 1–4 wie erfasst, danach je Runde ein gemeinsamer Platz."""
    rang, besser = {}, 0
    for stufe in sorted(RUNDEN, key=lambda k: RUNDEN[k][1]):
        tids = [t for t, r in runden.items() if r == stufe]
        if not tids:
            continue
        nr = int(stufe[1]) if stufe in PLAETZE else besser + 1
        for t in tids:
            rang[t] = nr
        besser += len(tids)
    return rang


def pruefen(runden):
    """Fehler (Liste von Texten), die das Speichern verhindern."""
    fehler = []
    for p in PLAETZE:
        n = sum(1 for r in runden.values() if r == p)
        if n > 1:
            fehler.append(f"{RUNDEN[p][0]} ist {n}× vergeben.")
    erlaubt = {s for s, _ in tableau(len(runden))["stufen"]}
    for r in sorted(set(runden.values()) - erlaubt, key=lambda k: RUNDEN[k][1]):
        fehler.append(f"{RUNDEN[r][0]} gibt es bei {len(runden)} Gruppen nicht.")
    return fehler


def hinweise(runden):
    """Abweichungen von der erwarteten Anzahl je Runde (verhindern das Speichern nicht)."""
    out = []
    for stufe, soll in tableau(len(runden))["stufen"]:
        ist = sum(1 for r in runden.values() if r == stufe)
        if ist != soll:
            was = RUNDEN[stufe][0] if stufe in PLAETZE else f"im {RUNDEN[stufe][0]} ausgeschieden"
            out.append(f"{was}: {ist} statt {soll} Gruppen.")
    return out


def _treffen(a, b):
    """Runde (1 = erste), in der sich die Plätze a und b der 1. Runde frühestens treffen.

    Platz 2z und 2z+1 bilden Zug z; das Freilos ist der Platz nach dem letzten Zug. Der Sieger
    von Eintrag e zieht in der nächsten Runde im Eintrag e // 2 (ein Lucky Loser ergänzt den
    letzten Eintrag) – darum treffen sich zwei Plätze dort, wo ihre Bits übereinstimmen.
    """
    return (a ^ b).bit_length()


def auslosen(teams, setzung, zufall=None):
    """Erste Runde: {tid: (zug, seite)}; ein Team allein im Zug hat das Freilos (letzter Zug).

    teams: Dicts mit id, verein, gruppennr, startnr. setzung: {verein: vorjahresrang} der
    Gruppe 1. Gesetzte Gruppen 1 so verteilt, dass sie sich möglichst spät treffen (die beste
    erhält das Freilos); ohne Gesetzte erhält eine ausgeloste Gruppe 1 das Freilos. Danach
    kommen Gruppen desselben Vereins möglichst weit auseinander (2 Gruppen frühestens im Final,
    3–4 frühestens im Halbfinal …).
    """
    n = len(teams)
    if n == 0:
        return {}
    zufall = zufall or random.Random()
    g1 = [t for t in teams if (t["gruppennr"] or 1) == 1]
    gesetzt = sorted((t for t in g1 if setzung.get(t["verein"]) is not None),
                     key=lambda t: (setzung[t["verein"]], t["startnr"] or 0))
    offen1 = [t for t in g1 if setzung.get(t["verein"]) is None]
    weitere = [t for t in teams if (t["gruppennr"] or 1) != 1]
    zufall.shuffle(offen1)
    zufall.shuffle(weitere)

    plaetze = [None] * n                        # Plätze 0..n-1; bei ungeradem n ist n-1 das Freilos
    vereinsplaetze = {}

    def setze(t, pos):
        plaetze[pos] = t
        vereinsplaetze.setdefault(t["verein"], []).append(pos)

    reihe = gesetzt + offen1 + weitere
    if n % 2:                                   # das einzige Freilos an die vorderste Gruppe
        setze(reihe[0], n - 1)
        rest_gesetzt = gesetzt[1:] if gesetzt else []
        rest = [t for t in reihe[1:] if t not in rest_gesetzt]
    else:
        rest_gesetzt, rest = gesetzt, offen1 + weitere

    gesetzt_pos = [p for p, t in enumerate(plaetze) if t]
    for t in rest_gesetzt:                      # Gesetzte: möglichst spät auf Bessere treffen
        frei = [p for p in range(n) if plaetze[p] is None]
        pos = max(frei, key=lambda p: (min((_treffen(p, q) for q in gesetzt_pos), default=99), -p))
        setze(t, pos)
        gesetzt_pos.append(pos)

    anzahl = {}
    for t in teams:
        anzahl[t["verein"]] = anzahl.get(t["verein"], 0) + 1

    def wert(pos, verein):
        runden = sorted(_treffen(pos, q) for q in vereinsplaetze.get(verein, []))
        return tuple(runden) + (99,)            # ohne Vereinskollegen = bester Wert

    for t in sorted(rest, key=lambda t: -anzahl[t["verein"]]):   # grosse Vereine zuerst
        frei = [p for p in range(n) if plaetze[p] is None]
        pos = max(frei, key=lambda p: (wert(p, t["verein"]), zufall.random()))
        setze(t, pos)

    return {t["id"]: (pos // 2 + 1, pos % 2 + 1) for pos, t in enumerate(plaetze)}


def turnierbaum(zuege, n, breite=194.0, hoehe=250.0):
    """Turnierbaum zum Ausdrucken (Masse in mm) aus der Einteilung der ersten Runde.

    zuege: {zug_nr: [team, team?]} (Teams als Dicts mit startnr, name), n: Anzahl Gruppen.
    Liefert {"spalten": [{"name", "x", "w"}], "boxen": [{x, y, w, h, linien, zug}], "linien": [SVG-Pfade]}.
    Linie = Team-Dict, {"freilos": True}, {"lucky_loser": True} oder None (leer zum Ausfüllen).
    """
    eintraege = max(1, (n + 1) // 2, max(zuege, default=1))
    # Spalten: Anzahl Einträge je Runde, Lucky Loser wo die Anzahl ungerade ist
    runden = [eintraege]
    while runden[-1] > 1:
        runden.append((runden[-1] + 1) // 2)
    anz_sp = len(runden)
    links, erste_b = 4.0, 44.0
    rest_b = (breite - links - erste_b - 4.0) / anz_sp          # weitere Runden + Sieger
    zeile = hoehe / eintraege
    h0 = min(zeile * 0.86, 12.0)

    spalten, boxen, pfade, mitte = [], [], [], []
    for k, anz in enumerate(runden):
        if k == 0:
            x, w = links, erste_b
        else:
            x = links + erste_b + 4.0 + (k - 1) * rest_b + 4.0
            w = rest_b - 4.0
        spalten.append({"name": rundenname(2 ** (anz_sp - k)), "x": x, "w": w})
        h = h0 if k == 0 else min(max(h0, zeile * 1.2), 13.0)
        neu = []
        for i in range(anz):
            if k == 0:
                y = (i + 0.5) * zeile
                liste = zuege.get(i + 1, [])
                linien = [liste[0] if liste else None,
                          liste[1] if len(liste) > 1 else ({"freilos": True} if liste else None)]
            else:
                quellen = [j for j in (2 * i, 2 * i + 1) if j < len(mitte)]
                y = sum(mitte[j] for j in quellen) / len(quellen)
                linien = [None, None if len(quellen) == 2 else {"lucky_loser": True}]
                for nr, j in enumerate(quellen):              # Verbindung zur Linie nr
                    vx, vy = boxen_vorher[j]
                    zy = y - h / 4 if nr == 0 else y + h / 4
                    xm = (vx + x) / 2
                    pfade.append(f"M{vx:.1f},{vy:.1f} H{xm:.1f} V{zy:.1f} H{x:.1f}")
            neu.append(y)
            boxen.append({"x": x, "y": y - h / 2, "w": w, "h": h, "linien": linien,
                          "zug": i + 1 if k == 0 else None, "spalte": k})
        if k == 1:                              # Freilos: direkt in der 2. Runde eintragen
            for j, b in enumerate(b for b in boxen if b["spalte"] == 0):
                a, z = b["linien"]
                if a and z and z.get("freilos"):
                    ziel = [bb for bb in boxen if bb["spalte"] == 1][j // 2]
                    ziel["linien"][j % 2] = a
        boxen_vorher = [(x + w, y) for y in neu]
        mitte = neu
    # Sieger
    x = links + erste_b + 4.0 + (anz_sp - 1) * rest_b + 4.0
    w = rest_b - 4.0
    spalten.append({"name": "Sieger", "x": x, "w": w})
    vx, vy = boxen_vorher[0]
    pfade.append(f"M{vx:.1f},{vy:.1f} H{x:.1f}")
    boxen.append({"x": x, "y": vy - 3.5, "w": w, "h": 7.0, "linien": [None], "zug": None, "spalte": anz_sp})
    return {"spalten": spalten, "boxen": boxen, "linien": pfade, "breite": breite, "hoehe": hoehe,
            "sieger_x": x, "sieger_w": w, "zeile": zeile}
