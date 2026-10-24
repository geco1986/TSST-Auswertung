"""Alle druckbaren Listen und Statistiken eines Anlasses – als PDF (modernes Layout)
und Excel (.xlsx). Jede Liste wird hier einmal beschrieben (liste_ausgabe.Liste);
Formulare (Notenblatt, Serienplan, Abschlussblatt) haben ein eigenes PDF-Layout.

Registry LISTEN: name -> {"titel", "liste": (conn, wk, args) -> Liste, optional "pdf"}.
"""

import io
import math
from itertools import groupby

from reportlab.lib.colors import white

from . import rangliste_pdf as R
from . import scoring
from .liste_ausgabe import Abschnitt, Liste, Spalte, _rahmen

OHNE_ABGEMELDETE = "COALESCE(t.status,'')<>'abgem'"


def _zahl2(v):
    return "" if v is None else f"{v:.2f}"


def _kats(conn, wk, **filter_):
    sql, args = "SELECT * FROM kategorie WHERE wettkampf_id=?", [wk["id"]]
    if filter_.get("ohne_stafetten"):
        sql += " AND ist_stafette=0"
    return conn.execute(sql + " ORDER BY sortierung, bezeichnung", args).fetchall()


def _kat_name(k):
    return f"{k['sparte']} · {R._titel(k)}" if k["sparte"] else R._titel(k)


def _gruppe(verein, zusatz=None, gruppennr=None):
    return " ".join(str(x) for x in (verein or "", gruppennr or "") if x).strip()


# --------------------------------------------------------------------------- #
# Startlisten
# --------------------------------------------------------------------------- #
def startliste_jet(conn, wk, nach):
    """JET: Einzelpersonen – Start-Nr. / Name / Jahrgang; nach Verein mit Unterteilung je Kategorie."""
    rows = conn.execute(
        "SELECT t.startnr, t.nachname, t.vorname, t.jahrgang, v.name AS verein, t.verein_zusatz AS zusatz, "
        "k.id AS kid, k.bezeichnung, k.sortierung FROM teilnehmer t "
        "LEFT JOIN verein v ON v.id=t.verein_id JOIN kategorie k ON k.id=t.kategorie_id "
        f"WHERE t.wettkampf_id=? AND {OHNE_ABGEMELDETE} ORDER BY t.startnr", (wk["id"],)).fetchall()
    titel = {"verein": "nach Verein", "kategorie": "nach Kategorie"}.get(nach, "nach Startnummer")

    def person(r):
        return {"startnr": r["startnr"], "name": f"{r['nachname'] or ''} {r['vorname'] or ''}".strip(),
                "jahrgang": r["jahrgang"], "verein": f"{r['zusatz'] or ''} {r['verein'] or ''}".strip(),
                "kategorie": r["bezeichnung"]}

    startnr = Spalte("startnr", "Start-Nr.", 0.9, rechts=True, zahlformat="0")
    name = Spalte("name", "Name", 3.2, art="fett")
    jg = Spalte("jahrgang", "Jahrgang", 0.9, rechts=True, zahlformat="0")
    info = f"{len(rows)} gemeldete Teilnehmende"
    if nach == "verein":
        spalten = [startnr, name, jg, Spalte("kategorie", "Kategorie", 2.5, nur_excel=True)]
        abschnitte = []
        reihe = sorted(rows, key=lambda r: ((r["verein"] or "").lower(), r["zusatz"] or "", r["sortierung"],
                                            (r["nachname"] or "").lower(), (r["vorname"] or "").lower()))
        for verein, grp in groupby(reihe, key=lambda r: f"{r['zusatz'] or ''} {r['verein'] or '—'}".strip()):
            grp = list(grp)
            zeilen = []
            for _, kgrp in groupby(grp, key=lambda r: r["kid"]):
                kgrp = list(kgrp)
                zeilen.append({"_zwischen": f"{kgrp[0]['bezeichnung']} · {len(kgrp)}"})
                zeilen += [person(r) for r in kgrp]
            abschnitte.append(Abschnitt(verein, f"{len(grp)} Teilnehmende", zeilen))
        return Liste("STARTLISTE", f"Startliste {titel}", spalten, abschnitte, info,
                     abschnitt_label="Verein", neue_seite=True, dateiname="Startliste_nach_Verein")
    if nach == "kategorie":
        spalten = [startnr, name, jg, Spalte("verein", "Verein", 2.6)]
        abschnitte = []
        reihe = sorted(rows, key=lambda r: (r["sortierung"], (r["verein"] or "").lower(),
                                            (r["nachname"] or "").lower(), (r["vorname"] or "").lower()))
        for _, grp in groupby(reihe, key=lambda r: r["kid"]):
            grp = list(grp)
            abschnitte.append(Abschnitt(grp[0]["bezeichnung"], f"{len(grp)} Teilnehmende",
                                        [person(r) for r in grp]))
        return Liste("STARTLISTE", f"Startliste {titel}", spalten, abschnitte, info,
                     abschnitt_label="Kategorie", neue_seite=True, dateiname="Startliste_nach_Kategorie")
    spalten = [startnr, name, jg, Spalte("verein", "Verein", 2.2), Spalte("kategorie", "Kategorie", 2.6)]
    return Liste("STARTLISTE", f"Startliste {titel}", spalten, [Abschnitt("", "", [person(r) for r in rows])],
                 info, dateiname="Startliste_nach_Startnummer")


def startliste(conn, wk, args):
    nach = args.get("nach", "verein")
    if conn.execute("SELECT 1 FROM kategorie WHERE wettkampf_id=? AND berechnung='jet' LIMIT 1",
                    (wk["id"],)).fetchone():
        return startliste_jet(conn, wk, nach)
    rows = conn.execute(
        "SELECT t.startnr, t.gruppennr, t.verband, v.name AS verein, t.verein_zusatz AS zusatz, "
        "k.id AS kid, k.sparte, k.bezeichnung, k.sortierung FROM teilnehmer t "
        "LEFT JOIN verein v ON v.id=t.verein_id JOIN kategorie k ON k.id=t.kategorie_id "
        f"WHERE t.wettkampf_id=? AND {OHNE_ABGEMELDETE} ORDER BY t.startnr", (wk["id"],)).fetchall()
    titel = {"verein": "nach Verein", "kategorie": "nach Disziplin"}.get(nach, "nach Startnummer")

    def disz(r):
        return R._titel({"bezeichnung": r["bezeichnung"], "sparte": r["sparte"]})

    startnr = Spalte("startnr", "Start-Nr.", 0.8, rechts=True, zahlformat="0")
    gruppe = Spalte("gruppennr", "Gruppe", 0.6, rechts=True, zahlformat="0")
    if nach == "verein":
        spalten = [startnr, Spalte("sparte", "Sparte", 1.1), Spalte("disziplin", "Disziplin", 3.2), gruppe]
        abschnitte = []
        for verein, grp in groupby(sorted(rows, key=lambda r: ((r["verein"] or "").lower(), r["sortierung"],
                                                                r["startnr"] or 0)),
                                   key=lambda r: r["verein"] or "—"):
            grp = list(grp)
            abschnitte.append(Abschnitt(verein, " · ".join(x for x in (grp[0]["verband"], f"{len(grp)} Gruppen") if x),
                                        [{"startnr": r["startnr"], "sparte": r["sparte"], "disziplin": disz(r),
                                          "gruppennr": r["gruppennr"]} for r in grp]))
        return Liste("STARTLISTE", f"Startliste {titel}", spalten, abschnitte, f"{len(rows)} gemeldete Gruppen",
                     abschnitt_label="Verein", neue_seite=True, dateiname="Startliste_nach_Verein")
    if nach == "kategorie":
        spalten = [startnr, Spalte("verein", "Verein", 3, art="fett"), gruppe, Spalte("verband", "Verband", 1.2)]
        abschnitte = []
        for _, grp in groupby(sorted(rows, key=lambda r: (r["sortierung"], r["bezeichnung"], r["startnr"] or 0)),
                              key=lambda r: r["kid"]):
            grp = list(grp)
            abschnitte.append(Abschnitt(f"{grp[0]['sparte']} · {disz(grp[0])}", f"{len(grp)} Gruppen",
                                        [{"startnr": r["startnr"], "verein": r["verein"], "gruppennr": r["gruppennr"],
                                          "verband": r["verband"]} for r in grp]))
        return Liste("STARTLISTE", f"Startliste {titel}", spalten, abschnitte, f"{len(rows)} gemeldete Gruppen",
                     abschnitt_label="Disziplin", neue_seite=True, dateiname="Startliste_nach_Disziplin")
    spalten = [startnr, Spalte("verein", "Verein", 2.6, art="fett"), gruppe, Spalte("sparte", "Sparte", 1.1),
               Spalte("disziplin", "Disziplin", 3)]
    return Liste("STARTLISTE", f"Startliste {titel}", spalten,
                 [Abschnitt("", "", [{"startnr": r["startnr"], "verein": r["verein"], "gruppennr": r["gruppennr"],
                                      "sparte": r["sparte"], "disziplin": disz(r)} for r in rows])],
                 f"{len(rows)} gemeldete Gruppen", dateiname="Startliste_nach_Startnummer")


# --------------------------------------------------------------------------- #
# Statistik
# --------------------------------------------------------------------------- #
def statistik(conn, wk, args):
    spalten = [Spalte("disziplin", "Disziplin", 2.4), Spalte("gruppen", "Angemeldet", 1.15, True, zahlformat="0"),
               Spalte("abgemeldet", "Abgemeldet", 1.15, True, zahlformat="0"),
               Spalte("einsaetze", "Einsätze", 1, True, zahlformat="0"),
               Spalte("teilnehmer", "Personen", 1, True, zahlformat="0"),
               Spalte("a30", "Ausz. 30%", 1, True, zahlformat="0"),
               Spalte("a33", "Ausz. 33%", 1, True, zahlformat="0"),
               Spalte("a40", "Ausz. 40%", 1, True, zahlformat="0")]
    abschnitte, total = [], {"gruppen": 0, "abgemeldet": 0, "einsaetze": 0, "teilnehmer": 0}
    for sparte, kats in groupby(_kats(conn, wk), key=lambda k: k["sparte"] or ""):
        zeilen = []
        for k in kats:
            alle = conn.execute("SELECT COUNT(*) FROM teilnehmer WHERE kategorie_id=?", (k["id"],)).fetchone()[0]
            abg = conn.execute("SELECT COUNT(*) FROM teilnehmer WHERE kategorie_id=? AND status='abgem'",
                               (k["id"],)).fetchone()[0]
            mitglieder = k["anzahl_werte"] or (5 if (k["geschlecht"] or "m") == "m" else 4)
            zeilen.append({"disziplin": R._titel(k), "gruppen": alle, "abgemeldet": abg, "einsaetze": alle - abg,
                           "teilnehmer": (alle - abg) * mitglieder, "a30": math.ceil(alle * 0.30),
                           "a33": math.ceil(round(alle * 0.33, 6)), "a40": math.ceil(alle * 0.40)})
        summe = {key: sum(z[key] for z in zeilen) for key in total}
        for key in total:
            total[key] += summe[key]
        abschnitte.append(Abschnitt(sparte, f"{len(zeilen)} Disziplinen", zeilen, dict(summe, disziplin=f"Total {sparte}")))
    if len(abschnitte) > 1:
        abschnitte.append(Abschnitt("Total Anlass", "", [], dict(total, disziplin="Total Anlass")))
    return Liste("STATISTIK", "Statistik Anmeldungen", spalten, abschnitte,
                 f"{total['einsaetze']} Gruppen · {total['teilnehmer']} Teilnehmende",
                 abschnitt_label="Sparte", dateiname="Statistik")


# --------------------------------------------------------------------------- #
# Einsatzplan
# --------------------------------------------------------------------------- #
def einsatzplan(conn, wk, args):
    nach = args.get("nach", "anlage")
    rows = conn.execute(
        "SELECT t.startnr, t.gruppennr, t.anlage, t.startzeit, v.name AS verein, k.sparte, k.bezeichnung "
        "FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id JOIN kategorie k ON k.id=t.kategorie_id "
        f"WHERE k.ist_stafette=0 AND t.startzeit IS NOT NULL AND t.wettkampf_id=? AND {OHNE_ABGEMELDETE}",
        (wk["id"],)).fetchall()
    zeit = Spalte("startzeit", "Zeit", 0.7)
    start = Spalte("startnr", "Start-Nr.", 0.8, True, zahlformat="0")
    if nach == "verein":
        schluessel, label = (lambda r: r["verein"] or "—"), "Verein"
        spalten = [zeit, start, Spalte("gruppe", "Gruppe", 1.6, art="fett"), Spalte("disziplin", "Disziplin", 2.6),
                   Spalte("anlage", "Anlage", 1.8)]
    else:
        schluessel, label = (lambda r: r["anlage"] or "—"), "Anlage"
        spalten = [zeit, start, Spalte("gruppe", "Verein / Gruppe", 2.4, art="fett"),
                   Spalte("disziplin", "Disziplin", 2.6)]
    abschnitte = []
    for kopf, grp in groupby(sorted(rows, key=lambda r: (schluessel(r).lower(), r["startzeit"] or "")), key=schluessel):
        grp = list(grp)
        abschnitte.append(Abschnitt(kopf, f"{len(grp)} Einsätze", [
            {"startzeit": r["startzeit"], "startnr": r["startnr"], "gruppe": _gruppe(r["verein"], None, r["gruppennr"]),
             "disziplin": R._titel({"bezeichnung": r["bezeichnung"], "sparte": r["sparte"]}) +
             (f" ({r['sparte']})" if r["sparte"] else ""), "anlage": r["anlage"]} for r in grp]))
    return Liste("EINSATZPLAN", f"Einsatzplan Vormittag nach {label}", spalten, abschnitte,
                 f"{len(rows)} Einsätze" if rows else "Noch kein Einsatzplan erzeugt",
                 abschnitt_label=label, neue_seite=nach == "verein", dateiname=f"Einsatzplan_nach_{label}")


# --------------------------------------------------------------------------- #
# Kranzliste und Top-Leistungen
# --------------------------------------------------------------------------- #
def _resultat(total, einheit, stafette):
    return R.total_text(total, einheit, stafette)


def kranzliste(conn, wk, args):
    spalten = [Spalte("rang", "Rang", 0.7, art="rang", zahlformat="0"), Spalte("gruppe", "Gruppe", 2.6, art="fett"),
               Spalte("verband", "Verband", 1.2), Spalte("resultat", "Resultat", 1.1, True),
               Spalte("auszeichnung", "Auszeichnung", 1.1)]
    abschnitte, anzahl = [], 0
    for k in _kats(conn, wk):
        d = scoring.rangliste(conn, k)
        einheit, stafette = d.get("einheit") or k["einheit"] or "", d.get("modus") == "stafette"
        ausgez = [e for e in d["eintraege"] if e.get("auszeichnung")]
        if not ausgez:
            continue
        anzahl += len(ausgez)
        abschnitte.append(Abschnitt(_kat_name(k), f"{len(ausgez)} Auszeichnungen", [
            {"rang": e["rang"], "gruppe": R._name(e), "verband": e.get("verband"),
             "resultat": "" if einheit == "Rang" else _resultat(e.get("total"), einheit, stafette),
             "auszeichnung": "Podest" if e["rang"] <= 3 else "Auszeichnung", "_akzent": True} for e in ausgez]))
    return Liste("KRANZLISTE", "Kranzliste", spalten, abschnitte,
                 f"{anzahl} Auszeichnungen in {len(abschnitte)} Disziplinen" if abschnitte
                 else "Noch keine Auszeichnungen – es sind noch keine Resultate erfasst",
                 abschnitt_label="Disziplin", dateiname="Kranzliste")


def top_leistungen(conn, wk, args):
    spalten = [Spalte("sparte", "Sparte", 1.1), Spalte("disziplin", "Disziplin", 2.6),
               Spalte("gruppe", "Führende Gruppe", 2.4, art="fett"), Spalte("bestwert", "Bestwert", 1.1, True)]
    zeilen = []
    for k in _kats(conn, wk):
        d = scoring.rangliste(conn, k)
        einheit, stafette = d.get("einheit") or k["einheit"] or "", d.get("modus") == "stafette"
        beste = next((e for e in d["eintraege"] if e.get("rang") == 1 and e.get("total") is not None), None)
        zeilen.append({"sparte": k["sparte"], "disziplin": R._titel(k), "gruppe": R._name(beste) if beste else "–",
                       "bestwert": (_resultat(beste["total"], einheit, stafette) if beste and einheit != "Rang"
                                    else ("1. Rang" if beste else "–"))})
    return Liste("TOP-LEISTUNGEN", "Top-Leistungen", spalten, [Abschnitt("", "", zeilen)],
                 "Aktuell beste Leistung je Disziplin – für den Speaker", dateiname="Top_Leistungen")


# --------------------------------------------------------------------------- #
# Kontrollblatt (4-Augen-Kontrolle)
# --------------------------------------------------------------------------- #
def _positionen(conn, k):
    if k["anzahl_werte"]:
        return list(range(1, k["anzahl_werte"] + 1))
    return [r[0] for r in conn.execute("SELECT position FROM kategorie_disziplin WHERE kategorie_id=? "
                                       "ORDER BY position", (k["id"],))] or [1]


def kontroll_spalten(conn, k):
    """Wert-Spalten des Kontrollblatts: [(position, key, kopf)].

    JET: eine Spalte je Disziplin mit deren Kürzel als Kopf; sonst die Einzelwerte 1., 2., …
    """
    if (k["berechnung"] or "") == "jet":
        return [(r["position"], r["abk"], r["abk"]) for r in conn.execute(
            "SELECT kd.position, d.abk FROM kategorie_disziplin kd JOIN disziplin d ON d.id=kd.disziplin_id "
            "WHERE kd.kategorie_id=? ORDER BY kd.position", (k["id"],))]
    return [(p, f"w{i}", f"{i}.") for i, p in enumerate(_positionen(conn, k), start=1)]


def kontroll_werte(conn, k, tid):
    """{position: Text} wie erfasst – beim JET der Messwert (Geräte: Note), sonst die Note."""
    jet = (k["berechnung"] or "") == "jet"
    werte = {}
    for r in conn.execute("SELECT r.position, r.note, r.wert, r.status, d.einheit FROM resultat r "
                          "LEFT JOIN kategorie_disziplin kd ON kd.kategorie_id=? AND kd.position=r.position "
                          "LEFT JOIN disziplin d ON d.id=kd.disziplin_id WHERE r.teilnehmer_id=?", (k["id"], tid)):
        if r["status"]:
            werte[r["position"]] = r["status"].upper()
        elif jet and r["wert"] is not None:
            werte[r["position"]] = scoring.fmt_zeit(r["wert"]) if r["einheit"] == "s" else f"{r['wert']:g}"
        else:
            werte[r["position"]] = _zahl2(r["note"])
    return werte


def kontrollblatt(conn, wk, args):
    kennung = args.get("kennung", "")
    nur_offen = args.get("offen", "1") == "1"
    kat_filter = int(args["kat"]) if str(args.get("kat", "")).isdigit() else None
    abschnitte, kopf = [], {}
    for k in _kats(conn, wk, ohne_stafetten=True):
        if kat_filter and k["id"] != kat_filter:
            continue
        sp = kontroll_spalten(conn, k)
        zeilen = []
        for t in conn.execute(
                "SELECT DISTINCT t.id, t.startnr, t.kontrolliert_am FROM teilnehmer t "
                "JOIN resultat r ON r.teilnehmer_id=t.id "
                "WHERE t.kategorie_id=? AND r.erfasst_von=? ORDER BY t.startnr", (k["id"], kennung)).fetchall():
            if nur_offen and t["kontrolliert_am"]:
                continue
            werte = kontroll_werte(conn, k, t["id"])
            zeile = {"startnr": t["startnr"], "kontrolliert": bool(t["kontrolliert_am"])}
            zeile.update({key: werte.get(p, "") for p, key, _ in sp})
            zeilen.append(zeile)
        if zeilen:
            for _, key, label in sp:
                kopf.setdefault(key, label)
            abschnitte.append(Abschnitt(_kat_name(k), f"{len(zeilen)} Einträge", zeilen))
    # gemeinsame Spalten aller Abschnitte (JET: Mädchen und Knaben haben andere Geräte)
    from .jet import DISZIPLINEN as JET_DISZ
    reihe = list(JET_DISZ)
    keys = sorted(kopf, key=lambda key: (reihe.index(key) if key in reihe else 100 + int(key[1:])))
    spalten = [Spalte("startnr", "Start-Nr.", 1.2, True, zahlformat="0")]
    spalten += [Spalte(key, kopf[key], 0.75, True) for key in keys]
    spalten.append(Spalte("kontrolliert", "Kontrolliert", 1.3, art="box"))
    from datetime import datetime
    return Liste("KONTROLLBLATT", "Kontrollblatt (4-Augen-Kontrolle)", spalten, abschnitte,
                 f"Kennung {kennung or '–'} · Stand {datetime.now():%d.%m.%Y %H:%M}"
                 + (" · nur nicht kontrollierte" if nur_offen else ""),
                 abschnitt_label="Disziplin", dateiname=f"Kontrollblatt_{kennung or 'alle'}")


# --------------------------------------------------------------------------- #
# Vereinsblatt und Ranglisten (PDF eigenes Layout, hier die Excel-Fassung)
# --------------------------------------------------------------------------- #
def vereinsblatt(conn, wk, args):
    verein = args.get("verein") or None
    max_w = 1
    abschnitte = []
    for name, v in R.vereine(conn, wk).items():
        if verein and name != verein:
            continue
        zeilen = []
        for z in v["zeilen"]:
            max_w = max(max_w, len(z["werte"]))
            zeile = {"sparte": z["sparte"], "disziplin": z["disziplin"], "kategorie": z["kategorie"] or "",
                     "gruppe": z["gruppe"], "rang": z["rang"], "anzahl": z["anzahl"], "total": z["total"],
                     "auszeichnung": "ja" if z["auszeichnung"] else "", "vermerk": z["vermerk"],
                     "runde": z["runde"], "_akzent": z["auszeichnung"]}
            zeile.update({f"w{i}": s for i, (s, _) in enumerate(z["werte"], start=1)})
            zeilen.append(zeile)
        abschnitte.append(Abschnitt(name, v["verband"], zeilen))
    spalten = [Spalte("sparte", "Sparte"), Spalte("disziplin", "Disziplin", 1.6), Spalte("kategorie", "Kategorie", 1.4),
               Spalte("gruppe", "Gruppe", 1.4, art="fett"), Spalte("rang", "Rang", 0.6, art="rang", zahlformat="0"),
               Spalte("anzahl", "von", 0.5, True, zahlformat="0"), Spalte("total", "Total", 0.9, True),
               Spalte("auszeichnung", "Auszeichnung", 0.9), Spalte("vermerk", "Vermerk", 0.7),
               Spalte("runde", "Runde", 0.8)]
    spalten += [Spalte(f"w{i}", f"Einzel {i}", 0.6, True) for i in range(1, max_w + 1)]
    return Liste("VEREINSBLATT", f"Vereinsblatt {verein}" if verein else "Vereinsblatt", spalten, abschnitte,
                 abschnitt_label="Verein", quer=True, dateiname=f"Vereinsblatt_{verein or 'alle_Vereine'}")


def rangliste(conn, wk, args):
    kid = int(args["kid"]) if str(args.get("kid", "")).isdigit() else None
    kats = [k for k in _kats(conn, wk) if (k["id"] == kid if kid else k["rl_drucken"])]
    abschnitte, max_w = [], 1
    for k in kats:
        d = scoring.rangliste(conn, k)
        einheit, stafette = d.get("einheit") or k["einheit"] or "", d.get("modus") == "stafette"
        zeilen = []
        for e in d["eintraege"] + d.get("sonder", []):
            vermerk = R.VERMERK_DEBRA.get(e.get("status"), e.get("status_kurz", "")) if e.get("status") else ""
            zeile = {"rang": None if vermerk else e.get("rang"), "gruppe": R._name(e), "verband": e.get("verband"),
                     "total": e.get("total") if einheit != "Rang" else None,
                     "auszeichnung": e.get("marker", "") if not vermerk else "", "vermerk": vermerk,
                     "runde": e.get("runde") if d.get("hat_final") else "", "_akzent": bool(e.get("auszeichnung"))}
            if not stafette:
                for i, w in enumerate(e.get("noten") or [], start=1):
                    zeile[f"w{i}"] = w
                    max_w = max(max_w, i)
            zeilen.append(zeile)
        abschnitte.append(Abschnitt(_kat_name(k), f"{len(zeilen)} Gruppen · {d.get('anz_ausz') or 0} Auszeichnungen",
                                    zeilen))
    spalten = [Spalte("rang", "Rang", 0.6, art="rang", zahlformat="0"), Spalte("gruppe", "Gruppe", 2, art="fett"),
               Spalte("verband", "Verband", 1), Spalte("total", "Total", 0.9, True, fmt=_zahl2, zahlformat="0.00"),
               Spalte("auszeichnung", "Ausz.", 0.6), Spalte("vermerk", "Vermerk", 0.7), Spalte("runde", "Runde", 0.8)]
    spalten += [Spalte(f"w{i}", f"Einzel {i}", 0.7, True, fmt=_zahl2, zahlformat="0.00") for i in range(1, max_w + 1)]
    titel = f"Rangliste {_kat_name(kats[0])}" if kid and kats else "Rangliste"
    return Liste("RANGLISTE", titel, spalten, abschnitte, abschnitt_label="Disziplin", blatt_je_abschnitt=True,
                 dateiname=f"Rangliste_{R._titel(kats[0]) if kid and kats else 'gesamt'}")


# --------------------------------------------------------------------------- #
# Formulare: Notenblatt, Serienplan, Abschlussblatt (eigene PDF-Layouts)
# --------------------------------------------------------------------------- #
def _kat(conn, wk, args):
    kid = int(args["kid"]) if str(args.get("kid", "")).isdigit() else None
    k = conn.execute("SELECT * FROM kategorie WHERE id=? AND wettkampf_id=?", (kid, wk["id"])).fetchone()
    if not k:
        raise LookupError("Disziplin nicht gefunden")
    return k


def _gruppen(conn, k):
    return conn.execute(
        "SELECT t.*, v.name AS verein FROM teilnehmer t LEFT JOIN verein v ON v.id=t.verein_id "
        f"WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE} ORDER BY t.startnr", (k["id"],)).fetchall()


def notenblatt(conn, wk, args):
    """Excel-Fassung: alle Gruppen der Disziplin mit leeren Feldern je Mitglied."""
    k = _kat(conn, wk, args)
    n = k["anzahl_werte"] or (5 if (k["geschlecht"] or "m") == "m" else 4)
    spalten = [Spalte("startnr", "Start-Nr.", 0.8, True, zahlformat="0"), Spalte("gruppe", "Verein / Gruppe", 2, art="fett"),
               Spalte("anlage", "Anlage", 1)] + [Spalte(f"m{i}", f"{i}. Tu/Ti", 0.9, art="leer") for i in range(1, n + 1)] \
        + [Spalte("total", "Total", 1, art="leer")]
    zeilen = [{"startnr": t["startnr"], "gruppe": _gruppe(t["verein"], None, t["gruppennr"]), "anlage": t["anlage"]}
              for t in _gruppen(conn, k)]
    return Liste("NOTENBLATT", f"Notenblatt {_kat_name(k)}", spalten, [Abschnitt("", "", zeilen)],
                 f"{len(zeilen)} Gruppen", quer=True, zeilenhoehe=24, dateiname=f"Notenblatt_{R._titel(k)}")


def notenblatt_pdf(conn, wk, args, opt):
    """Ein Notenblatt je Gruppe (A4 quer) zum Ausfüllen durch Riegenleiter und Kampfrichter."""
    k = _kat(conn, wk, args)
    n = k["anzahl_werte"] or (5 if (k["geschlecht"] or "m") == "m" else 4)
    gruppen = _gruppen(conn, k)
    hoch = "hoch" in R._titel(k).lower()
    liste = Liste("NOTENBLATT", f"Notenblatt {_kat_name(k)}", [], [], quer=True)
    c, z, buf, kopf, (W, H, L, RR, FUSS), akzent, dunkel = _rahmen(liste, wk, opt)
    sparte_tag = (k["sparte"] or "").upper()
    for nr, t in enumerate(gruppen):
        if nr:
            c.showPage()
        kopf(False)
        y = 82.0
        # Kopf: Verein, Gruppe, Disziplin, Start-Nr.
        z.etikett(L, y + 8, sparte_tag, akzent)
        z.text(L, y + 40, _gruppe(t["verein"], None, None), "b", 24, R.TINTE)
        z.text(L, y + 58, f"Gruppe {t['gruppennr'] or '–'}  ·  {R._titel(k)}", "s", 12, R.GRAU)
        z.rechteck(RR - 150, y, 150, 62, akzent, radius=8)
        z.text(RR - 75, y + 18, "START-NR.", "b", 7.5, white, "c", 0.8)
        z.text(RR - 75, y + 50, str(t["startnr"] or ""), "b", 30, white, "c")
        z.text(RR - 330, y + 22, "ANLAGE", "b", 7, R.TINTE, sperrung=0.6)
        z.linie(y + 50, RR - 330, RR - 170, R.TINTE, 0.8)
        if t["anlage"]:
            z.text(RR - 330, y + 46, t["anlage"], "s", 12, R.TINTE)
        y += 82
        # Tabelle Versuche
        spalten = [("Serie", 0.6), ("Bahn", 0.6), ("Name / Vorname", 3.2), ("1. Versuch", 1), ("2. Versuch", 1),
                   ("3. Versuch", 1)] + ([("4. Versuch", 1), ("5. Versuch", 1)] if hoch else []) + [("Bestleistung", 1.3)]
        gesamt = sum(b for _, b in spalten)
        xs, x = [], L
        for label, b in spalten:
            w = (RR - L) * b / gesamt
            xs.append((label, x, w))
            x += w
        for label, x, w in xs:
            z.text(x + 4, y + 12, label.upper(), "b", 7, R.TINTE, sperrung=0.6)
        z.linie(y + 18, L, RR, R.TINTE, 1)
        y += 18
        zh = min(44.0, (FUSS - 120 - y) / n)
        for i in range(n):
            if i % 2:
                z.rechteck(L, y, RR - L, zh, R.ZEBRA)
            z.text(L + 4, y + zh / 2 + 3, f"{i + 1}", "b", 9, R.GRAU)
            for _, x, w in xs[1:]:
                z.linie(y, x, x, R.LINIE)
            z.linie(y + zh, L, RR, R.LINIE)
            y += zh
        # Unterschriften und Total
        y += 26
        for label, dy in (("Riegenleiter", 0), ("Kampfrichter", 34)):
            z.text(L, y + dy, label.upper(), "b", 7.5, R.TINTE, sperrung=0.6)
            z.linie(y + dy + 4, L + 80, L + 330, R.TINTE, 0.8)
        for label, dy in (("Total Gruppe", 0), ("Durchschnittsleistung", 34)):
            z.text(RR - 200, y + dy, label.upper(), "b", 7.5, R.TINTE, "r", 0.6)
            z.rechteck(RR - 190, y + dy - 14, 190, 24, white, radius=4, rand=R.GRAU)
    if not gruppen:
        kopf(False)
        z.text(L, 100, "Keine Gruppen in dieser Disziplin.", "m", 11, R.GRAU)
    c.showPage()
    c.save()
    return buf.getvalue()


def _serien(conn, k, runde):
    teams = {t["id"]: t for t in _gruppen(conn, k)}
    serien = {}
    for r in conn.execute("SELECT teilnehmer_id, serie, bahn FROM stafette WHERE runde=? AND serie IS NOT NULL",
                          (runde,)).fetchall():
        t = teams.get(r["teilnehmer_id"])
        if t and r["bahn"]:
            serien.setdefault(r["serie"], {})[r["bahn"]] = t
    return serien


def serienplan(conn, wk, args):
    k = _kat(conn, wk, args)
    runde = args.get("runde") or ("vorlauf" if k["hat_final"] else "final")
    bahnen = k["bahnen"] or 8
    abschnitte = []
    for s, belegt in sorted(_serien(conn, k, runde).items()):
        abschnitte.append(Abschnitt(f"{s}. Serie", "", [
            {"bahn": b, "startnr": belegt[b]["startnr"] if b in belegt else None,
             "verein": _gruppe(belegt[b]["verein"], None, belegt[b]["gruppennr"]) if b in belegt else ""}
            for b in range(1, bahnen + 1)]))
    rundentext = "Vorläufe" if runde == "vorlauf" else ("Finals" if k["hat_final"] else "Endläufe")
    spalten = [Spalte("bahn", "Bahn", 0.6, True, zahlformat="0"), Spalte("startnr", "Start-Nr.", 0.8, True, zahlformat="0"),
               Spalte("verein", "Verein", 3, art="fett"), Spalte("zeit", "Zeit", 1.2, art="leer"),
               Spalte("disq", "Disq. (Grund)", 1.4, art="leer")]
    return Liste("SERIENPLAN", f"Serienplan {_kat_name(k)} · {rundentext}", spalten, abschnitte,
                 f"{len(abschnitte)} Serien à {bahnen} Bahnen" if abschnitte else "Noch keine Bahnen zugeteilt",
                 abschnitt_label="Serie", quer=True, neue_seite=True, zeilenhoehe=34,
                 dateiname=f"Serienplan_{R._titel(k)}_{rundentext}")


def serienplan_pdf(conn, wk, args, opt):
    """Eine Serie je Seite (A4 quer), Zeilen und Schrift so gross wie die Seite es zulässt."""
    k = _kat(conn, wk, args)
    runde = args.get("runde") or ("vorlauf" if k["hat_final"] else "final")
    bahnen = k["bahnen"] or 8
    serien = sorted(_serien(conn, k, runde).items())
    rundentext = "Vorläufe" if runde == "vorlauf" else ("Finals" if k["hat_final"] else "Endläufe")
    liste = Liste("SERIENPLAN", f"Serienplan {_kat_name(k)} · {rundentext}", [], [], quer=True)
    c, z, buf, _, (W, H, L, RR, FUSS), akzent, dunkel = _rahmen(liste, wk, opt)
    rechts = " · ".join(x for x in (R.datum_lang(wk["datum"]), wk["ort"] or "") if x)
    spalten = [("Bahn", 0.75), ("Start-Nr.", 1.05), ("Verein / Gruppe", 3.5), ("Zeit", 1.5), ("Disq. (Grund)", 1.7)]
    gesamt = sum(b for _, b in spalten)
    xs, x = [], L
    for label, b in spalten:
        w = (RR - L) * b / gesamt
        xs.append((label, x, w))
        x += w

    def serienname(s):
        if runde == "final" and k["hat_final"]:
            return ("A-Final" if s == 1 else "B-Final") if k["final_typ"] == "ab" else "Final"
        return f"{s}. Serie"

    for nr, (s, belegt) in enumerate(serien):
        if nr:
            c.showPage()
        # Kopf: Anlass, Disziplin, Serie
        z.text(L, 26, opt["kopfzeile"].upper(), "b", 8, akzent, sperrung=0.8)
        z.text(RR, 26, rechts, "m", 8.5, R.GRAU, "r")
        z.linie(33, L, RR)
        box_w = 190
        z.rechteck(RR - box_w, 42, box_w, 58, akzent, radius=8)
        z.text(RR - box_w / 2, 92, z.kuerzen(serienname(s), "b", 34, box_w - 16), "b", 34, white, "c")
        z.text(L, 66, f"{(k['sparte'] or '').upper()}  ·  {rundentext.upper()}", "b", 11, akzent, sperrung=0.8)
        titel_size = 30
        titel = R._titel(k)
        while titel_size > 16 and z.breite(titel, "b", titel_size) > RR - L - box_w - 20:
            titel_size -= 1
        z.text(L, 96, titel, "b", titel_size, R.TINTE)
        # Tabelle über die ganze restliche Höhe
        y = 112
        for label, x, w in xs:
            z.text(x + 6, y + 15, label.upper(), "b", 10, R.TINTE, sperrung=0.6)
        z.linie(y + 22, L, RR, R.TINTE, 1.2)
        y += 22
        zh = (FUSS - 8 - y) / bahnen
        gross = min(zh * 0.55, 40)          # Schriftgrösse aus der Zeilenhöhe
        for b in range(1, bahnen + 1):
            t = belegt.get(b)
            if b % 2 == 0:
                z.rechteck(L, y, RR - L, zh, R.ZEBRA)
            mitte = y + zh / 2 + gross * 0.36
            (_, x0, w0), (_, x1, w1), (_, x2, w2), (_, x3, w3), (_, x4, w4) = xs
            z.text(x0 + w0 / 2, mitte, str(b), "b", gross, akzent, "c")
            if t:
                z.text(x1 + w1 - 10, mitte, str(t["startnr"] or ""), "s", gross, R.TINTE, "r")
                verein = _gruppe(t["verein"], None, t["gruppennr"])
                size = gross
                while size > 12 and z.breite(verein, "b", size) > w2 - 16:
                    size -= 0.5
                z.text(x2 + 8, y + zh / 2 + size * 0.36, z.kuerzen(verein, "b", size, w2 - 16), "b", size, R.TINTE)
            else:
                z.text(x2 + 8, mitte, "– frei –", "m", gross * 0.6, R.GRAU)
            c.setStrokeColor(R.LINIE)
            c.setLineWidth(0.8)
            for x in (x1, x2, x3, x4):      # senkrechte Spaltentrenner
                c.line(x, H - y, x, H - y - zh)
            z.linie(y + zh, L, RR, R.LINIE, 0.8)
            y += zh
    if not serien:
        z.text(L, 26, opt["kopfzeile"].upper(), "b", 8, akzent, sperrung=0.8)
        z.text(L, 96, R._titel(k), "b", 30, R.TINTE)
        z.text(L, 130, "Noch keine Bahnen zugeteilt.", "m", 14, R.GRAU)
    c.showPage()
    c.save()
    return buf.getvalue()


def abschluss_pdf(conn, wk, args, opt):
    """Abschlussblatt 'Disziplin fertig erfasst' mit Unterschriften."""
    k = _kat(conn, wk, args)
    anz = conn.execute(f"SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=? AND {OHNE_ABGEMELDETE}",
                       (k["id"],)).fetchone()[0]
    liste = Liste("ABSCHLUSS", f"Disziplin fertig · {_kat_name(k)}", [], [])
    c, z, buf, kopf, (W, H, L, RR, FUSS), akzent, dunkel = _rahmen(liste, wk, opt)
    kopf(False)
    z.etikett(L, 100, (k["sparte"] or "").upper(), akzent)
    z.text(L, 140, R._titel(k), "b", 28, R.TINTE)
    z.rechteck(L, 170, RR - L, 64, akzent, radius=10)
    z.text((L + RR) / 2, 210, "DISZIPLIN FERTIG ERFASST", "b", 20, white, "c", 1.5)
    y = 280
    for label, wert in (("Anzahl Gruppen", str(anz)), ("Abgeschlossen von", k["abgeschlossen_von"] or ""),
                        ("Datum / Uhrzeit", k["abgeschlossen_am"] or "")):
        z.text(L, y, label.upper(), "b", 8, R.GRAU, sperrung=0.7)
        z.text(L + 170, y, wert, "s", 13, R.TINTE)
        z.linie(y + 8, L, RR, R.LINIE)
        y += 34
    y += 90
    for i, label in enumerate(("Erfassung", "Kontrolle (4-Augen)")):
        x0 = L + i * (RR - L) / 2 + (20 if i else 0)
        x1 = x0 + (RR - L) / 2 - 20
        z.linie(y, x0, x1, R.TINTE, 1)
        z.text((x0 + x1) / 2, y + 14, label.upper(), "b", 7.5, R.TINTE, "c", 0.7)
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------- #
LISTEN = {
    "startliste": {"titel": "Startliste", "liste": startliste},
    "statistik": {"titel": "Statistik", "liste": statistik},
    "einsatzplan": {"titel": "Einsatzplan", "liste": einsatzplan},
    "kranzliste": {"titel": "Kranzliste", "liste": kranzliste},
    "top-leistungen": {"titel": "Top-Leistungen", "liste": top_leistungen},
    "kontrollblatt": {"titel": "Kontrollblatt", "liste": kontrollblatt},
    "vereinsblatt": {"titel": "Vereinsblatt", "liste": vereinsblatt,
                     "pdf": lambda conn, wk, args, opt: R.vereinsblatt_pdf(conn, wk, args.get("verein") or None)},
    "rangliste": {"titel": "Rangliste", "liste": rangliste,
                  "pdf": lambda conn, wk, args, opt: (
                      R.einzel_pdf(conn, wk, _kat(conn, wk, args)) if args.get("kid")
                      else R.gesamt_pdf(conn, wk, fortlaufend=args.get("umbruch") == "fortlaufend"))},
    "notenblatt": {"titel": "Notenblatt", "liste": notenblatt, "pdf": notenblatt_pdf},
    "serienplan": {"titel": "Serienplan", "liste": serienplan, "pdf": serienplan_pdf},
    "abschluss": {"titel": "Abschlussblatt", "liste": None, "pdf": abschluss_pdf},
}


def ausgeben(conn, wk, name, fmt, args):
    """(bytes, dateiname, mimetype) einer Liste im Format 'pdf' oder 'xlsx'."""
    from . import liste_ausgabe as A
    eintrag = LISTEN[name]
    opt = R.einstellungen(conn, wk)
    if fmt == "pdf" and eintrag.get("pdf"):
        daten = eintrag["pdf"](conn, wk, args, opt)
        liste = eintrag["liste"](conn, wk, args) if eintrag["liste"] else None
        basis = liste.dateiname if liste else f"{eintrag['titel']}"
    else:
        liste = eintrag["liste"](conn, wk, args)
        daten = A.pdf(liste, wk, opt) if fmt == "pdf" else A.xlsx(liste, wk, opt)
        basis = liste.dateiname
    mime = "application/pdf" if fmt == "pdf" else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return daten, f"{basis}.{fmt}", mime
