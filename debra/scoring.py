"""Wertungs- und Ranglisten-Logik (das "Auswertung"-Modul von DEBRA).

Grundmodell des Schweizer Vereinsturnens:
- Ein Teilnehmer erhält je Disziplin eine Note (typisch 6.00–10.00).
- Das Total ist die Summe der Noten, abzüglich der `streich` schlechtesten
  Resultate (Streichresultat), falls die Kategorie das vorsieht.
- Der Rang ergibt sich aus dem Total absteigend; Gleichstände teilen den Rang.
- Auszeichnung (Kranz): entweder die besten X % einer Kategorie oder alle
  ab einer Total-Schwelle – je nach Kategorie-Einstellung.

Die exakten Sonderformeln der Original-Wettkampftypen (&H12 … &H60) lassen sich
über die Kategorie-Felder (streich, kranz_modus, kranz_wert, typ) nachbilden und
bei Bedarf feinjustieren.
"""

from math import ceil

# Statusvermerke pro Start (nicht gewertet). Kurzform fürs Drucken in Klammern.
STATUS_LABELS = {
    "disq": "Disqualifiziert (Disq)",
    "ak": "Ausser Konkurrenz (a.K.)",
    "unfall": "Unfall",
    "nges": "Nicht gestartet (n.Ges.)",
    "aufg": "Aufgegeben (Aufg.)",
}
STATUS_KURZ = {"disq": "Disq", "ak": "a.K.", "unfall": "Unfall",
               "nges": "n.Ges.", "aufg": "Aufg."}


def gruppen_score(werte, berechnung="summe", streich=0, richtung="hoch"):
    """Score einer Gruppe/eines Teilnehmers aus den erfassten Werten.

    berechnung 'durchschnitt': Mittelwert aller erfassten Werte (WKB-Bewertung
      Turner/Turnerinnen). 'summe': Summe, schlechteste `streich` gestrichen.
    Gibt (score, anzahl_erfasst, gestrichene_indizes, best_einzel) zurück.
    best_einzel dient als Tiebreak bei Gleichstand (bessere Einzelleistung).
    """
    werte_idx = [(i, n) for i, n in enumerate(werte) if n is not None]
    anzahl = len(werte_idx)
    if anzahl == 0:
        return None, 0, set(), None
    vals = [n for _, n in werte_idx]
    best = max(vals) if richtung == "hoch" else min(vals)
    gestrichen = set()
    if berechnung == "durchschnitt":
        score = sum(vals) / anzahl
    else:
        if streich > 0 and anzahl > streich:
            # schlechteste `streich` Werte streichen (kleinster Wert = schlechteste)
            for idx, _ in sorted(werte_idx, key=lambda x: x[1])[:streich]:
                gestrichen.add(idx)
        score = sum(n for i, n in werte_idx if i not in gestrichen)
    return round(score, 2), anzahl, gestrichen, best


# Rückwärtskompatibler Wrapper (Summenwertung wie bisher)
def teilnehmer_total(noten, streich=0):
    score, anzahl, gestrichen, _ = gruppen_score(noten, "summe", streich, "hoch")
    return score, anzahl, gestrichen


def _rang_zuweisen(eintraege, richtung="hoch"):
    """Rangierung nach Score; Richtung 'tief' = kleinerer Score ist besser.

    Gleichstand-Tiebreak: bessere Einzelleistung ('best'). Nur wenn Score UND
    beste Einzelleistung gleich sind, teilen sich zwei Einträge den Rang.
    Einträge ohne Resultat (total is None) landen ohne Rang am Ende.
    """
    mit = [e for e in eintraege if e.get("total") is not None]
    ohne = [e for e in eintraege if e.get("total") is None]

    def sortkey(e):
        s = e["total"]
        b = e.get("best")
        if richtung == "tief":
            return (s, b if b is not None else float("inf"))
        return (-s, -(b if b is not None else float("-inf")))

    mit.sort(key=lambda e: sortkey(e) + (e.get("anzeige", ""),))

    letzter_key = None
    letzter_rang = 0
    for pos, e in enumerate(mit, start=1):
        key = sortkey(e)
        if letzter_key is not None and key == letzter_key:
            e["rang"] = letzter_rang            # echter Gleichstand -> gleicher Rang
        else:
            e["rang"] = pos
            letzter_rang = pos
            letzter_key = key
    for e in ohne:
        e["rang"] = None
    return mit + ohne


def _kranz_grenze(anz_rangiert, kategorie):
    """Anzahl auszuzeichnender Ränge: Prozent-Anteil oder fester Rang."""
    modus = _kf(kategorie, "kranz_modus", "prozent")
    wert = kategorie["kranz_wert"] or 0
    if modus == "prozent":
        return int(ceil(anz_rangiert * wert / 100.0))
    if modus == "rang":
        return int(wert)
    return None


def _kf(row, key, default=None):
    """Feld aus sqlite3.Row lesen, das in älteren DBs fehlen kann."""
    try:
        val = row[key]
    except (IndexError, KeyError):
        return default
    return default if val is None else val


def _apply_rang_manuell(gewertet):
    """Überschreibt berechnete Ränge mit manuell gesetzten und sortiert neu."""
    if not any(e.get("rang_manuell") for e in gewertet):
        return gewertet
    for e in gewertet:
        if e.get("rang_manuell"):
            e["rang"] = e["rang_manuell"]
    gewertet.sort(key=lambda e: (e["rang"] if e["rang"] is not None else 10 ** 9))
    return gewertet


def rangliste_einzel(conn, kategorie):
    """Rangliste einer Kategorie inkl. Score, Rang und Auszeichnung.

    Jede Zeile ist ein Teilnehmer bzw. – bei den WKB-Gruppenwettkämpfen – eine
    Gruppe; die Werte sind dann die Einzelleistungen der Gruppenmitglieder.
    """
    berechnung = _kf(kategorie, "berechnung", "summe")
    richtung = _kf(kategorie, "richtung", "hoch")
    einheit = _kf(kategorie, "einheit", "")
    anzahl_werte = _kf(kategorie, "anzahl_werte", 0)

    kat_diszs = conn.execute(
        "SELECT kd.position, d.abk, d.bezeichnung "
        "FROM kategorie_disziplin kd JOIN disziplin d ON d.id = kd.disziplin_id "
        "WHERE kd.kategorie_id=? ORDER BY kd.position",
        (kategorie["id"],),
    ).fetchall()
    if anzahl_werte and anzahl_werte > 0:
        positionen = list(range(1, anzahl_werte + 1))
    else:
        positionen = [k["position"] for k in kat_diszs]
        if not positionen:
            positionen = [r["position"] for r in conn.execute(
                "SELECT DISTINCT r.position FROM resultat r "
                "JOIN teilnehmer t ON t.id=r.teilnehmer_id "
                "WHERE t.kategorie_id=? ORDER BY r.position", (kategorie["id"],)
            ).fetchall()]

    teilnehmende = conn.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t "
        "LEFT JOIN verein v ON v.id=t.verein_id WHERE t.kategorie_id=? ",
        (kategorie["id"],),
    ).fetchall()

    eintraege = []
    for t in teilnehmende:
        res_rows = conn.execute(
            "SELECT position, note, status FROM resultat WHERE teilnehmer_id=?",
            (t["id"],)).fetchall()
        noten_map = {r["position"]: r["note"] for r in res_rows}
        # Einzelne Mitglieder als DNS/DNF -> Wert zählt nicht im Durchschnitt
        dnsdnf = {r["position"]: (r["status"] if "status" in r.keys() else None)
                  for r in res_rows if ("status" in r.keys() and r["status"] in ("dns", "dnf"))}
        noten = [noten_map.get(p) for p in positionen]
        erfasst_any = any(n is not None for n in noten) or bool(dnsdnf)
        score, anzahl, gestrichen, best = gruppen_score(
            noten, berechnung, kategorie["streich"], richtung)
        person = ((t["vorname"] or "") + " " + (t["nachname"] or "")).strip()
        verein = t["verein_name"] or ""
        zusatz = t["verein_zusatz"] or ""
        anzeige = person or (verein + (" " + zusatz if zusatz else "")
                             + (f" ({t['gruppennr']})" if t["gruppennr"] else "")).strip()
        off_total = t["total_off"]
        tot_man = t["total_manuell"] if "total_manuell" in t.keys() else None
        rang_man = t["rang_manuell"] if "rang_manuell" in t.keys() else None
        status = (t["status"] if "status" in t.keys() else None) or ""
        # Gruppe mit DNS/DNF-Mitglied wird automatisch ausser Konkurrenz (a.K.)
        if not status and dnsdnf:
            status = "ak"
        eintraege.append({
            "teilnehmer_id": t["id"],
            "startnr": t["startnr"],
            "vorname": t["vorname"] or "",
            "nachname": t["nachname"] or "",
            "anzeige": anzeige,
            "jahrgang": t["jahrgang"],
            "verein": verein,
            "verein_zusatz": zusatz,
            "verband": (t["verband"] if "verband" in t.keys() else None) or "",
            "gruppennr": t["gruppennr"],
            "noten": noten,
            "dnsdnf": dnsdnf,
            "gestrichen": gestrichen,
            "best": best,
            "status": status,
            "status_kurz": STATUS_KURZ.get(status, ""),
            "status_label": STATUS_LABELS.get(status, ""),
            "bemerkung": (t["bemerkung"] if "bemerkung" in t.keys() else None) or "",
            "total": tot_man if tot_man is not None else (
                score if erfasst_any else (off_total if off_total not in (None, 0) else None)),
            "rang_manuell": rang_man,
            "rang_off": t["rang_off"],
            "ausz_off": t["ausz_off"],
            "anzahl": anzahl,
        })

    # Einträge mit Vermerk (Disq, a.K., …) werden nicht gewertet, sondern separat gezeigt
    sonder = [e for e in eintraege if e["status"]]
    gewertet = [e for e in eintraege if not e["status"]]
    for e in sonder:
        e["rang"] = None
        e["auszeichnung"] = False
        e["marker"] = ""

    gewertet = _rang_zuweisen(gewertet, richtung)
    gewertet = _apply_rang_manuell(gewertet)

    rangiert = [e for e in gewertet if e["rang"] is not None]
    grenze = _kranz_grenze(len(rangiert), kategorie)
    for e in gewertet:
        e["auszeichnung"] = False
        e["marker"] = ""
        if e["rang"] is None:
            continue
        if kategorie["kranz_modus"] in ("prozent", "rang") and grenze is not None:
            e["auszeichnung"] = e["rang"] <= grenze
        elif kategorie["kranz_modus"] == "schwelle":
            schwelle = kategorie["kranz_wert"] or 0
            e["auszeichnung"] = e["total"] is not None and (
                e["total"] <= schwelle if richtung == "tief" else e["total"] >= schwelle)
        # Auszeichnungs-Marker wie in der offiziellen Rangliste: nur ausgezeichnete
        # Gruppen erhalten einen Marker, davon die besten drei "***", die übrigen "*".
        if e["auszeichnung"]:
            e["marker"] = "***" if e["rang"] <= 3 else "*"

    return {"positionen": positionen, "disziplinen": kat_diszs, "eintraege": gewertet,
            "sonder": sonder, "anz_gewertet": len(rangiert),
            "berechnung": berechnung, "richtung": richtung, "einheit": einheit,
            "anzahl_werte": anzahl_werte}


def rangliste_sektion(conn, kategorie):
    """Sektions-/Gruppenrangliste: Vereine nach Summe der Mitglieder-Totale.

    Vereinfachtes, aber transparentes Modell: das Sektionstotal ist die Summe
    der Einzel-Totale aller Teilnehmer des Vereins in dieser Kategorie.
    """
    einzel = rangliste_einzel(conn, kategorie)
    gruppen = {}
    for e in einzel["eintraege"]:
        key = e["verein"] or "—"
        g = gruppen.setdefault(key, {"verein": key, "mitglieder": 0,
                                     "total": 0.0, "hat_resultat": False})
        g["mitglieder"] += 1
        if e["total"] is not None:
            g["total"] += e["total"]
            g["hat_resultat"] = True
    liste = []
    for g in gruppen.values():
        g["total"] = round(g["total"], 2) if g["hat_resultat"] else None
        liste.append(g)
    liste = _rang_zuweisen(liste)
    grenze = _kranz_grenze(len([x for x in liste if x["rang"]]), kategorie)
    for g in liste:
        g["auszeichnung"] = bool(grenze and g["rang"] and g["rang"] <= grenze)
    return {"eintraege": liste}


def parse_zeit(text):
    """Zeit als Sekunden parsen: '2:33.17', '153.17' oder '52,86' -> Float."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        if ":" in text:
            m, s = text.split(":", 1)
            return round(int(m) * 60 + float(s), 2)
        return round(float(text), 2)
    except (ValueError, TypeError):
        return None


def fmt_zeit(sekunden):
    """Sekunden als 'm:ss.ss' (ab 60 s) bzw. 'ss.ss' formatieren."""
    if sekunden is None:
        return "–"
    if sekunden >= 60:
        m = int(sekunden // 60)
        s = sekunden - m * 60
        return f"{m}:{s:05.2f}"
    return f"{sekunden:.2f}"


def stafette_endzeit(row, kat):
    """Endzeit = Rohzeit + Übergabefehler × Zuschlag (aus Kategorie)."""
    if row is None or row["rohzeit"] is None:
        return None
    za = _kf(kat, "zuschlag_a", 0) or 0
    zb = _kf(kat, "zuschlag_b", 0) or 0
    return round(row["rohzeit"] + (row["fehler_a"] or 0) * za + (row["fehler_b"] or 0) * zb, 2)


def _stafette_basis(conn, kategorie):
    """Baut die Basiseinträge einer Stafette (Vorlauf-/Finalzeit, Status)."""
    teilnehmende = conn.execute(
        "SELECT t.*, v.name AS verein_name FROM teilnehmer t "
        "LEFT JOIN verein v ON v.id=t.verein_id WHERE t.kategorie_id=? ",
        (kategorie["id"],)).fetchall()
    eintraege = []
    for t in teilnehmende:
        runden = {r["runde"]: r for r in conn.execute(
            "SELECT * FROM stafette WHERE teilnehmer_id=?", (t["id"],)).fetchall()}
        vz = stafette_endzeit(runden.get("vorlauf"), kategorie)
        fz = stafette_endzeit(runden.get("final"), kategorie)
        person = ((t["vorname"] or "") + " " + (t["nachname"] or "")).strip()
        verein = t["verein_name"] or ""
        zusatz = t["verein_zusatz"] or ""
        anzeige = person or (verein + (" " + zusatz if zusatz else "")
                             + (f" ({t['gruppennr']})" if t["gruppennr"] else "")).strip()
        status = (t["status"] if "status" in t.keys() else None) or ""
        eintraege.append({
            "teilnehmer_id": t["id"], "startnr": t["startnr"], "anzeige": anzeige,
            "verein": verein, "verband": (t["verband"] if "verband" in t.keys() else "") or "",
            "vorlauf": vz, "final": fz,
            "final_gruppe": (t["final_gruppe"] if "final_gruppe" in t.keys() else None),
            "status": status, "status_kurz": STATUS_KURZ.get(status, ""),
            "status_label": STATUS_LABELS.get(status, ""),
            "bemerkung": (t["bemerkung"] if "bemerkung" in t.keys() else None) or "",
            "noten": [], "gestrichen": set(), "best": None, "jahrgang": None,
            "rang_manuell": (t["rang_manuell"] if "rang_manuell" in t.keys() else None),
        })
    return eintraege


def rangliste_stafette(conn, kategorie):
    """Stafetten-Rangliste inkl. Vorlauf/Final, Selektion und Auszeichnung."""
    hat_final = _kf(kategorie, "hat_final", 0)
    final_typ = _kf(kategorie, "final_typ", None)
    einheit = _kf(kategorie, "einheit", "s")
    inf = float("inf")
    alle = _stafette_basis(conn, kategorie)
    sonder = [e for e in alle if e["status"]]
    gewertet = [e for e in alle if not e["status"]]
    for e in sonder:
        e["rang"] = None
        e["auszeichnung"] = False
        e["marker"] = ""
        e["total"] = e["final"] if e["final"] is not None else e["vorlauf"]
        e["runde"] = ""

    if hat_final:
        def by_final(e):
            return e["final"] if e["final"] is not None else inf

        def by_vorlauf(e):
            return e["vorlauf"] if e["vorlauf"] is not None else inf

        ordered = []
        if final_typ == "ab":
            gA = sorted([e for e in gewertet if e["final_gruppe"] == "A"], key=by_final)
            gB = sorted([e for e in gewertet if e["final_gruppe"] == "B"], key=by_final)
            rest = sorted([e for e in gewertet if e["final_gruppe"] not in ("A", "B")], key=by_vorlauf)
            r = 1
            for e in gA:
                e["rang"] = r; e["total"] = e["final"]; e["runde"] = "A-Final"; r += 1; ordered.append(e)
            r = 9
            for e in gB:
                e["rang"] = r; e["total"] = e["final"]; e["runde"] = "B-Final"; r += 1; ordered.append(e)
            r = 17
            for e in rest:
                e["total"] = e["vorlauf"]; e["runde"] = "Vorlauf"
                e["rang"] = r if e["vorlauf"] is not None else None
                if e["vorlauf"] is not None:
                    r += 1
                ordered.append(e)
        else:  # einzel: ein Final der besten 8
            gF = sorted([e for e in gewertet if e["final_gruppe"] in ("F", "A")], key=by_final)
            rest = sorted([e for e in gewertet if e["final_gruppe"] not in ("F", "A")], key=by_vorlauf)
            r = 1
            for e in gF:
                e["rang"] = r; e["total"] = e["final"]; e["runde"] = "Final"; r += 1; ordered.append(e)
            r = len(gF) + 1
            for e in rest:
                e["total"] = e["vorlauf"]; e["runde"] = "Vorlauf"
                e["rang"] = r if e["vorlauf"] is not None else None
                if e["vorlauf"] is not None:
                    r += 1
                ordered.append(e)
        gewertet = ordered
    else:
        # einfacher Endlauf: nach Finalzeit (bzw. einziger Zeit) rangieren
        for e in gewertet:
            e["total"] = e["final"]
            e["runde"] = "Final"
        gewertet = _rang_zuweisen(gewertet, "tief")

    gewertet = _apply_rang_manuell(gewertet)
    rangiert = [e for e in gewertet if e["rang"] is not None]
    grenze = _kranz_grenze(len(rangiert), kategorie)
    for e in gewertet:
        e.setdefault("marker", "")
        e["auszeichnung"] = bool(grenze and e["rang"] and e["rang"] <= grenze)
        if e["auszeichnung"]:
            e["marker"] = "***" if e["rang"] <= 3 else "*"

    return {"eintraege": gewertet, "sonder": sonder, "anz_gewertet": len(rangiert),
            "hat_final": hat_final, "final_typ": final_typ, "einheit": einheit,
            "berechnung": "zeit", "richtung": "tief", "anzahl_werte": 1, "positionen": [],
            "disziplinen": []}


def rangliste(conn, kategorie):
    """Passende Rangliste je nach Kategorietyp."""
    if _kf(kategorie, "ist_stafette", 0):
        res = rangliste_stafette(conn, kategorie)
        res["modus"] = "stafette"
        return res
    if kategorie["typ"] in ("sektion", "gruppe"):
        res = rangliste_sektion(conn, kategorie)
        res["modus"] = "sektion"
        return res
    res = rangliste_einzel(conn, kategorie)
    res["modus"] = "einzel"
    return res


def vereinsblatt(conn, wettkampf_id):
    """Alle Resultate nach Verein gruppiert (das "Vereinsblatt")."""
    kategorien = conn.execute(
        "SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
        (wettkampf_id,),
    ).fetchall()
    pro_verein = {}
    for kat in kategorien:
        einzel = rangliste_einzel(conn, kat)
        for e in einzel["eintraege"]:
            key = e["verein"] or "—"
            block = pro_verein.setdefault(key, [])
            block.append({
                "kategorie": kat["bezeichnung"],
                "name": e["anzeige"],
                "jahrgang": e["jahrgang"],
                "total": e["total"],
                "rang": e["rang"],
                "auszeichnung": e["auszeichnung"],
            })
    for block in pro_verein.values():
        block.sort(key=lambda x: (x["kategorie"], x["rang"] or 9999))
    return dict(sorted(pro_verein.items()))
