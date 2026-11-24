"""Einsatzplan: Gruppen/Turner:innen auf Anlagen und Startzeiten verteilen.

Pflege je Disziplin (gilt für alle Kategorien, Knaben und Mädchen gemeinsam):
- Anzahl Anlagen (0 = Disziplin nicht im Einsatzplan),
- Minuten je Turner:in auf der Anlage – oder je Gruppe bei Gruppenvorführungen (z. B. Gymnastik),
- „schätzbar“ (Note durch Wertungsrichter:innen): jede Kategorie bleibt auf derselben Anlage,
  damit sie von denselben Richter:innen bewertet wird.

Ablösungen: Die Vereine werden auf 1–4 Ablösungen verteilt (JET: 2), möglichst gleich viele
Turner:innen je Ablösung. Einheit ist der Verein – Knaben und Mädchen eines Vereins sind
damit immer in derselben Ablösung. Die Einteilung kann manuell angepasst werden.

Planung (Heuristik, frühestmöglicher Start):
- TSST/JTSST: jede Gruppe (Anmeldung) einer Disziplin ist ein Einsatz von
  Gruppengrösse × Minuten; ein Verein ist nie zeitgleich an zwei Anlagen.
- JET: Riegen je Verein (Knaben bzw. Mädchen, höchstens „max. Riegengrösse“, nach Kategorie
  sortiert); die Riege besucht alle Disziplinen ihres Programms (Anlagen > 0) nacheinander.
  Schätzbar: die Kategorien der Riege turnen gleichzeitig, jede auf ihrer festen Anlage.
  „Verteilen“ (nicht schätzbar): die Riege wird gleichzeitig auf alle Anlagen aufgeteilt.
"""

import math
import re

from . import jet as J

OHNE_ABGEMELDETE = "COALESCE(t.status,'')<>'abgem'"
MAX_ABLOESUNGEN = 4
STANDARD_DAUER = 10   # Minuten je Einsatz, wenn keine Zeit je Turner:in gepflegt ist
GRUPPEN_DISZIPLINEN = {"GYM"}   # Vorgabe „Zeit je Gruppe“ (Gruppenvorführung)
RIEGE_MAX = 16                  # JET: maximale Riegengrösse (Vorgabe)


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #
def ist_jet(conn, wk):
    return bool(wk) and conn.execute(
        "SELECT 1 FROM kategorie WHERE wettkampf_id=? AND berechnung='jet' LIMIT 1", (wk["id"],)).fetchone() is not None


def disziplin_name(bezeichnung):
    """'Ballwurf Mädchen Kat. A, 13..16 jährig' -> 'Ballwurf'; 'Weitsprung' -> 'Weitsprung'."""
    name = re.split(r"\s+(?:Mädchen|Knaben|Turnerinnen|Turner)\b|\s+Kat\.", bezeichnung or "")[0]
    return name.strip() or (bezeichnung or "").strip()


def zeit_text(minuten):
    if minuten is None:
        return ""
    h, m = divmod(int(minuten), 60)
    return f"{h:02d}:{m:02d}"


def zeit_minuten(text, default=None):
    try:
        h, m = (text or "").strip().split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return default


def anlage_label(name, anzahl, i):
    return f"{name} {i + 1}" if anzahl > 1 else name


def _kat_kurz(k):
    """Kurzname einer Kategorie für Listen: 'Mädchen C' (JET) bzw. Bezeichnung."""
    if J.ist_jet(k):
        return f"{'Mädchen' if k['geschlecht'] == 'w' else 'Knaben'} {J.kat_buchstabe(k)}"
    return k["bezeichnung"]


# --------------------------------------------------------------------------- #
# Einstellungen
# --------------------------------------------------------------------------- #
def _key(wk, name, n=None):
    return f"einsatz_{name}_{wk['id']}" + (f"_{n}" if n is not None else "")


def einstellungen(conn, wk):
    """{'abloesungen': n, 'starts': ['08:00', '13:00', …]} des Wettkampfs."""
    from .db import get_setting
    jet = ist_jet(conn, wk)
    try:
        n = int(get_setting(_key(wk, "abl"), 2 if jet else 1))
    except ValueError:
        n = 1
    n = min(max(n, 1), MAX_ABLOESUNGEN)
    alt = get_setting("einsatz_start", "08:00")
    vorgabe = ["08:00", "13:00" if jet else "", "", ""]
    starts = [get_setting(_key(wk, "start", i + 1), alt if i == 0 else vorgabe[i]) or "" for i in range(n)]
    try:
        riege = max(1, int(get_setting(_key(wk, "riege"), RIEGE_MAX)))
    except ValueError:
        riege = RIEGE_MAX
    return {"abloesungen": n, "starts": starts, "jet": jet, "riege_max": riege}


def einstellungen_speichern(conn, wk, form):
    from .db import set_setting
    try:
        n = int(form.get("abloesungen") or 1)
    except ValueError:
        n = 1
    n = min(max(n, 1), MAX_ABLOESUNGEN)
    set_setting(_key(wk, "abl"), n)
    for i in range(MAX_ABLOESUNGEN):
        wert = form.get(f"start_{i + 1}")
        if wert is not None:
            set_setting(_key(wk, "start", i + 1), wert.strip())
    if form.get("riege_max"):
        try:
            set_setting(_key(wk, "riege"), max(1, int(form.get("riege_max"))))
        except ValueError:
            pass
    for d in disziplinen(conn, wk):
        if form.get(f"anl_{d['key']}") is None:
            continue
        try:
            anl = max(0, int(form.get(f"anl_{d['key']}") or 0))
        except ValueError:
            anl = d["anlagen"]
        try:
            minuten = max(0.0, float((form.get(f"min_{d['key']}") or "0").replace(",", ".")))
        except ValueError:
            minuten = d["minuten"]
        conn.execute(
            "INSERT INTO einsatz_disziplin(wettkampf_id, disziplin, anlagen, minuten, schaetzbar, pro_gruppe, "
            "verteilen) VALUES(?,?,?,?,?,?,?) ON CONFLICT(wettkampf_id, disziplin) DO UPDATE SET "
            "anlagen=excluded.anlagen, minuten=excluded.minuten, schaetzbar=excluded.schaetzbar, "
            "pro_gruppe=excluded.pro_gruppe, verteilen=excluded.verteilen",
            (wk["id"], d["key"], anl, minuten, 1 if form.get(f"sch_{d['key']}") else 0,
             1 if form.get(f"je_{d['key']}") == "gruppe" else 0, 1 if form.get(f"vt_{d['key']}") else 0))
    conn.commit()


def disziplinen(conn, wk):
    """Disziplinen des Wettkampfs mit Einstellungen und zugehörigen Kategorien.

    [{key, name, anlagen, minuten, schaetzbar, kats: [kategorie-rows], n: Anzahl Turner:innen bzw. Gruppen}]
    """
    if not wk:
        return []
    kats = conn.execute(
        "SELECT k.*, (SELECT COUNT(*) FROM teilnehmer t WHERE t.kategorie_id=k.id AND "
        f"{OHNE_ABGEMELDETE}) AS anz FROM kategorie k WHERE k.wettkampf_id=? AND k.ist_stafette=0 "
        "ORDER BY k.sortierung, k.bezeichnung", (wk["id"],)).fetchall()
    gespeichert = {r["disziplin"]: r for r in conn.execute(
        "SELECT * FROM einsatz_disziplin WHERE wettkampf_id=?", (wk["id"],))}
    res = {}
    jet = any(J.ist_jet(k) for k in kats)
    if jet:
        for abk, (bez, gruppe, _, _) in J.DISZIPLINEN.items():
            ks = [k for k in kats if J.ist_jet(k) and abk in J.PROGRAMM[k["geschlecht"]]]
            if ks:
                res[abk] = {"key": abk, "name": bez, "gruppe": J.GRUPPEN.get(gruppe, ""), "kats": ks,
                            "geraet": gruppe == "geraete"}
    else:
        for k in kats:
            name = disziplin_name(k["bezeichnung"])
            d = res.setdefault(name, {"key": name, "name": name, "gruppe": "", "kats": [], "geraet": False})
            d["kats"].append(k)
    for d in res.values():
        g = gespeichert.get(d["key"])
        if g:
            d.update(anlagen=g["anlagen"], minuten=g["minuten"], schaetzbar=bool(g["schaetzbar"]),
                     pro_gruppe=bool(g["pro_gruppe"]),
                     verteilen=bool(g["verteilen"]) if g["verteilen"] is not None else
                     (jet and not g["schaetzbar"]))
        else:   # Vorgabe: bisherige Werte je Kategorie übernehmen
            d.update(anlagen=max((k["anlagen"] or 1) for k in d["kats"]),
                     minuten=max((k["zeit_pro_turner"] or 0) for k in d["kats"]),
                     schaetzbar=d["geraet"], pro_gruppe=d["key"] in GRUPPEN_DISZIPLINEN,
                     verteilen=jet and not d["geraet"])
        d["n"] = sum(k["anz"] for k in d["kats"])
    return list(res.values())


# --------------------------------------------------------------------------- #
# Ablösungen
# --------------------------------------------------------------------------- #
def vereine(conn, wk):
    """[{verein_id, name, m, w, n}] – Anzahl Einsätze (Turner:innen bzw. Gruppen) je Verein."""
    rows = conn.execute(
        "SELECT COALESCE(t.verein_id, 0) AS vid, COALESCE(v.name, '(ohne Verein)') AS name, "
        "SUM(k.geschlecht='m') AS m, SUM(k.geschlecht<>'m') AS w, COUNT(*) AS n "
        "FROM teilnehmer t JOIN kategorie k ON k.id=t.kategorie_id LEFT JOIN verein v ON v.id=t.verein_id "
        f"WHERE t.wettkampf_id=? AND k.ist_stafette=0 AND {OHNE_ABGEMELDETE} "
        "GROUP BY COALESCE(t.verein_id, 0) ORDER BY name", (wk["id"],)).fetchall()
    return [dict(verein_id=r["vid"], name=r["name"], m=r["m"] or 0, w=r["w"] or 0, n=r["n"]) for r in rows]


def _ausgleichen(groessen, anzahl, fest=None):
    """Verteilt {id: grösse} auf `anzahl` Ablösungen (1..n), möglichst gleich gross.

    Grösste zuerst in die kleinste Ablösung, danach verschieben/tauschen, solange die Differenz
    zwischen grösster und kleinster Ablösung sinkt. `fest` = {id: abl} bleibt unverändert.
    """
    fest = fest or {}
    zuteilung = dict(fest)
    summe = {a: 0 for a in range(1, anzahl + 1)}
    for i, a in fest.items():
        summe[a] += groessen.get(i, 0)
    for i in sorted((i for i in groessen if i not in fest), key=lambda i: -groessen[i]):
        a = min(summe, key=lambda a: (summe[a], a))
        zuteilung[i] = a
        summe[a] += groessen[i]
    if anzahl < 2:
        return zuteilung

    def spanne(s):
        return max(s.values()) - min(s.values())

    frei = [i for i in groessen if i not in fest]
    besser = True
    while besser:
        besser = False
        for i in frei:
            for b in summe:     # verschieben
                a = zuteilung[i]
                if a == b:
                    continue
                neu = dict(summe)
                neu[a] -= groessen[i]
                neu[b] += groessen[i]
                if spanne(neu) < spanne(summe):
                    zuteilung[i], summe, besser = b, neu, True
            for j in frei:      # tauschen
                a, b = zuteilung[i], zuteilung[j]
                if a == b or groessen[i] == groessen[j]:
                    continue
                neu = dict(summe)
                neu[a] += groessen[j] - groessen[i]
                neu[b] += groessen[i] - groessen[j]
                if spanne(neu) < spanne(summe):
                    zuteilung[i], zuteilung[j], summe, besser = b, a, neu, True
    return zuteilung


def abloesungen(conn, wk, neu=False):
    """{verein_id: abloesung}; fehlende Vereine werden ausgleichend ergänzt und gespeichert.

    neu=True: alle Vereine automatisch neu verteilen.
    """
    anzahl = einstellungen(conn, wk)["abloesungen"]
    liste = vereine(conn, wk)
    groessen = {v["verein_id"]: v["n"] for v in liste}
    if anzahl == 1:
        return {i: 1 for i in groessen}
    fest = {} if neu else {
        r["verein_id"]: r["abloesung"] for r in conn.execute(
            "SELECT verein_id, abloesung FROM einsatz_abloesung WHERE wettkampf_id=?", (wk["id"],))
        if r["verein_id"] in groessen and 1 <= r["abloesung"] <= anzahl}
    if neu or set(fest) != set(groessen):
        zuteilung = _ausgleichen(groessen, anzahl, fest)
        abloesungen_speichern(conn, wk, zuteilung)
        return zuteilung
    return fest


def abloesungen_speichern(conn, wk, zuteilung):
    conn.execute("DELETE FROM einsatz_abloesung WHERE wettkampf_id=?", (wk["id"],))
    conn.executemany("INSERT INTO einsatz_abloesung(wettkampf_id, verein_id, abloesung) VALUES(?,?,?)",
                     [(wk["id"], vid, a) for vid, a in zuteilung.items()])
    conn.commit()


# --------------------------------------------------------------------------- #
# Generieren
# --------------------------------------------------------------------------- #
def _frueheste(base, intervall_listen, dauer):
    """Kleinste Startzeit >= base, zu der alle Intervall-Listen für `dauer` Minuten frei sind."""
    belegt = sorted(iv for liste in intervall_listen for iv in liste)
    t = base
    for s, e in belegt:
        if s >= t + dauer:
            break
        if e > t:
            t = e
    return t


def _kat_auf_anlagen(kats_last, anzahl):
    """Schätzbare Disziplin: {kategorie_id: Anlage-Index}, grösste Kategorie zuerst auf die
    am wenigsten belegte Anlage – jede Kategorie bleibt den ganzen Tag auf derselben Anlage."""
    last = [0.0] * anzahl
    res = {}
    for kid, l in sorted(kats_last.items(), key=lambda x: -x[1]):
        i = min(range(anzahl), key=lambda i: (last[i], i))
        res[kid] = i
        last[i] += l
    return res


def _dauer(d, personen, gruppen=1):
    """Dauer: Minuten × Personen, bei Gruppenvorführungen Minuten × Anzahl Gruppen (Kategorien)."""
    if not d["minuten"]:
        return STANDARD_DAUER
    return max(1, math.ceil(d["minuten"] * (gruppen if d.get("pro_gruppe") else personen)))


def _aufteilen(liste, n):
    """Liste in n möglichst gleich grosse, zusammenhängende Teile (Reihenfolge bleibt)."""
    n = max(1, min(n, len(liste)))
    q, r = divmod(len(liste), n)
    teile, i = [], 0
    for k in range(n):
        g = q + (1 if k < r else 0)
        teile.append(liste[i:i + g])
        i += g
    return teile


def _riegen(teiln, abl_von, riege_max):
    """JET: Riegen je Ablösung, Verein und Geschlecht; grosse Vereine in gleich grosse Riegen
    (höchstens riege_max), sortiert nach Kategorie – ein Verein turnt so möglichst miteinander."""
    gruppen = {}
    for t in teiln:
        gruppen.setdefault((abl_von.get(t["vid"], 1), t["vid"], t["geschlecht"]), []).append(t)
    riegen = []
    for (abl, vid, g), ts in gruppen.items():
        anzahl = math.ceil(len(ts) / riege_max)
        for teil in _aufteilen(ts, anzahl):
            riegen.append({"abl": abl, "vid": vid, "geschlecht": g, "jet": True,
                           "mitglieder": [(t["id"], t["kategorie_id"]) for t in teil], "personen": len(teil)})
    return riegen


def _varianten(d, e, fix):
    """Mögliche Belegungen einer Disziplin durch eine Einheit: [[(anlage, [tids], dauer), …], …].
    Innerhalb einer Variante turnen alle Teile gleichzeitig."""
    m = e["mitglieder"]
    tids = [tid for tid, _ in m]
    if d["schaetzbar"]:
        # gleiche Kategorie immer auf derselben Anlage; die Kategorien einer Riege turnen parallel
        je_anlage = {}
        for tid, kid in m:
            i = fix.get(d["key"], {}).get(kid, 0) if d["anlagen"] > 1 else 0
            je_anlage.setdefault(i, []).append((tid, kid))
        teile = []
        for i, mm in sorted(je_anlage.items()):
            personen = len(mm) if e.get("jet") else e["personen"]
            teile.append((anlage_label(d["name"], d["anlagen"], i), [t for t, _ in mm],
                          _dauer(d, personen, len({k for _, k in mm}))))
        return [teile]
    if d["verteilen"] and d["anlagen"] > 1:
        # Riege gleichzeitig auf alle Anlagen verteilen
        if e.get("jet"):
            return [[(anlage_label(d["name"], d["anlagen"], i), [t for t, _ in st],
                      _dauer(d, len(st), len({k for _, k in st})))
                     for i, st in enumerate(_aufteilen(m, d["anlagen"]))]]
        pro = math.ceil(e["personen"] / d["anlagen"])
        return [[(anlage_label(d["name"], d["anlagen"], i), tids, _dauer(d, pro)) for i in range(d["anlagen"])]]
    gruppen = len({k for _, k in m})
    return [[(anlage_label(d["name"], d["anlagen"], i), tids, _dauer(d, e["personen"], gruppen))]
            for i in range(d["anlagen"])]


def _start(base, teile, anlage_busy, weitere):
    """Frühester gemeinsamer Start aller Teile einer Variante."""
    t = base
    laenge = max(dauer for _, _, dauer in teile)
    while True:
        neu = t
        for lab, _, dauer in teile:
            neu = max(neu, _frueheste(neu, [anlage_busy.setdefault(lab, [])], dauer))
        neu = max(neu, _frueheste(neu, weitere, laenge))
        if neu == t:
            return t
        t = neu


def generieren(conn, wk):
    """Erzeugt den Einsatzplan neu. Gibt eine Zusammenfassung zurück."""
    cfg = einstellungen(conn, wk)
    jet = cfg["jet"]
    diszs = [d for d in disziplinen(conn, wk) if d["anlagen"] > 0]
    abl_von = abloesungen(conn, wk)
    teiln = conn.execute(
        "SELECT t.id, t.startnr, t.gruppennr, COALESCE(t.verein_id, 0) AS vid, t.kategorie_id, "
        "k.geschlecht, k.anzahl_werte, v.name AS verein "
        "FROM teilnehmer t JOIN kategorie k ON k.id=t.kategorie_id LEFT JOIN verein v ON v.id=t.verein_id "
        f"WHERE t.wettkampf_id=? AND k.ist_stafette=0 AND {OHNE_ABGEMELDETE} "
        "ORDER BY k.sortierung, v.name, t.gruppennr, t.startnr", (wk["id"],)).fetchall()

    # Einheiten: {abl, vid, mitglieder: [(teilnehmer_id, kategorie_id)], personen, diszs}
    if jet:
        einheiten = _riegen(teiln, abl_von, cfg["riege_max"])
        for e in einheiten:
            e["diszs"] = [d for d in diszs if d["key"] in J.PROGRAMM[e["geschlecht"]]]
    else:
        einheiten = []
        d_von_kat = {k["id"]: d for d in diszs for k in d["kats"]}
        for t in teiln:
            d = d_von_kat.get(t["kategorie_id"])
            if not d:
                continue
            mitglieder = t["anzahl_werte"] or (5 if (t["geschlecht"] or "m") == "m" else 4)
            einheiten.append({"abl": abl_von.get(t["vid"], 1), "personen": mitglieder, "vid": t["vid"],
                              "mitglieder": [(t["id"], t["kategorie_id"])], "diszs": [d]})

    # Schätzbare Disziplinen: Kategorie -> feste Anlage (nach Belastung ausgeglichen)
    fix = {}
    for d in diszs:
        if d["schaetzbar"] and d["anlagen"] > 1:
            last = {}
            for e in einheiten:
                if any(x["key"] == d["key"] for x in e["diszs"]):
                    for _, kid in e["mitglieder"]:
                        last[kid] = last.get(kid, 0) + e["personen"] / len(e["mitglieder"])
            if d.get("pro_gruppe"):
                last = {kid: 1 for kid in last}
            fix[d["key"]] = _kat_auf_anlagen(last, d["anlagen"])

    anlage_busy = {}   # label -> [(s, e)]  (über alle Ablösungen)
    zeilen, bericht = [], {"abloesungen": [], "warnungen": []}
    ende_vorher = None
    for abl in range(1, cfg["abloesungen"] + 1):
        start_txt = cfg["starts"][abl - 1] if abl - 1 < len(cfg["starts"]) else ""
        base = zeit_minuten(start_txt)
        if base is None:
            base = ende_vorher if ende_vorher is not None else 8 * 60
        elif ende_vorher is not None and base < ende_vorher:
            bericht["warnungen"].append(
                f"Ablösung {abl} beginnt um {start_txt}, Ablösung {abl - 1} dauert aber bis "
                f"{zeit_text(ende_vorher)} – Anlagen sind dann teilweise noch belegt.")
        eigene = [e for e in einheiten if e["abl"] == abl]
        verein_busy, einheit_ende = {}, base
        # grosse Riegen zuerst; bei Gruppen (TSST/JTSST) Reihenfolge wie bisher (Disziplin, Verein)
        if jet:
            eigene.sort(key=lambda e: -e["personen"] * len(e["diszs"]))
        for e in eigene:
            eigen_busy = []
            offen = list(e["diszs"])
            while offen:
                best = None
                weitere = [eigen_busy] + ([] if jet else [verein_busy.setdefault(e["vid"], [])])
                for d in offen:
                    for teile in _varianten(d, e, fix):
                        t0 = _start(base, teile, anlage_busy, weitere)
                        if best is None or t0 < best[0]:
                            best = (t0, d, teile)
                t0, d, teile = best
                laenge = max(dauer for _, _, dauer in teile)
                for lab, tids, dauer in teile:
                    anlage_busy[lab].append((t0, t0 + dauer))
                    for tid in tids:
                        zeilen.append((wk["id"], tid, d["key"], lab, abl, t0, t0 + dauer))
                eigen_busy.append((t0, t0 + laenge))
                if not jet:
                    verein_busy[e["vid"]].append((t0, t0 + laenge))
                einheit_ende = max(einheit_ende, t0 + laenge)
                offen.remove(d)
        n_pers = sum(e["personen"] for e in eigene) if jet else len(eigene)
        bericht["abloesungen"].append({"nr": abl, "start": zeit_text(base), "ende": zeit_text(einheit_ende),
                                       "einheiten": len(eigene), "personen": n_pers,
                                       "vereine": len({e["vid"] for e in eigene})})
        ende_vorher = einheit_ende

    conn.execute("DELETE FROM einsatz WHERE wettkampf_id=?", (wk["id"],))
    conn.executemany("INSERT INTO einsatz(wettkampf_id, teilnehmer_id, disziplin, anlage, abloesung, start, ende) "
                     "VALUES(?,?,?,?,?,?,?)", zeilen)
    if not jet:   # Notenblätter/Listen von TSST/JTSST lesen Anlage und Startzeit am Teilnehmer
        conn.execute("UPDATE teilnehmer SET anlage=NULL, bahn=NULL, startzeit=NULL WHERE wettkampf_id=? AND "
                     "kategorie_id IN (SELECT id FROM kategorie WHERE ist_stafette=0)", (wk["id"],))
        zaehler, gesetzt = {}, set()
        for _, tid, _, lab, _, t0, _ in sorted(zeilen, key=lambda z: (z[3], z[5])):
            zaehler[lab] = zaehler.get(lab, 0) + 1
            if tid in gesetzt:      # auf mehrere Anlagen verteilt: erste Anlage am Teilnehmer
                continue
            gesetzt.add(tid)
            conn.execute("UPDATE teilnehmer SET anlage=?, bahn=?, startzeit=? WHERE id=?",
                         (lab, zaehler[lab], zeit_text(t0), tid))
    conn.commit()
    bericht["einsaetze"] = len(zeilen)
    bericht["kat_anlagen"] = {k: v for k, v in fix.items()}
    return bericht


# --------------------------------------------------------------------------- #
# Auswertung / Listen
# --------------------------------------------------------------------------- #
def eintraege(conn, wk):
    """Einsätze zusammengefasst je Riege/Gruppe:
    [{abloesung, anlage, disziplin, start, ende, verein, zusatz, kat, anzahl, startnr, gruppennr}]"""
    rows = conn.execute(
        "SELECT e.*, t.startnr, t.gruppennr, t.verein_zusatz, COALESCE(v.name, '') AS verein, "
        "k.id AS kid, k.bezeichnung, k.geschlecht, k.abk, k.berechnung, k.sparte "
        "FROM einsatz e JOIN teilnehmer t ON t.id=e.teilnehmer_id JOIN kategorie k ON k.id=t.kategorie_id "
        "LEFT JOIN verein v ON v.id=t.verein_id WHERE e.wettkampf_id=?", (wk["id"],)).fetchall()
    gruppen = {}
    for r in rows:
        key = (r["abloesung"], r["anlage"], r["start"], r["verein"], r["verein_zusatz"] or "", r["kid"])
        g = gruppen.get(key)
        if g is None:
            g = gruppen[key] = {"abloesung": r["abloesung"], "anlage": r["anlage"], "disziplin": r["disziplin"],
                                "start": r["start"], "ende": r["ende"], "verein": r["verein"],
                                "zusatz": r["verein_zusatz"] or "", "kat": _kat_kurz(r), "sparte": r["sparte"],
                                "anzahl": 0, "startnr": [], "gruppennr": r["gruppennr"]}
        g["anzahl"] += 1
        if r["startnr"] is not None:
            g["startnr"].append(r["startnr"])
    res = list(gruppen.values())
    for g in res:
        g["startnr"].sort()
        g["von"], g["bis"] = zeit_text(g["start"]), zeit_text(g["ende"])
    res.sort(key=lambda g: (g["abloesung"], g["start"], g["anlage"]))
    return res


def uebersicht(conn, wk):
    """Belegung je Anlage: [{anlage, abloesung, von, bis, einsaetze, personen}] und Kategorie-Zuordnung."""
    anl = {}
    for g in eintraege(conn, wk):
        a = anl.setdefault((g["abloesung"], g["anlage"]), {"anlage": g["anlage"], "abloesung": g["abloesung"],
                                                            "von": g["start"], "bis": g["ende"], "einsaetze": 0,
                                                            "personen": 0, "kats": set()})
        a["von"], a["bis"] = min(a["von"], g["start"]), max(a["bis"], g["ende"])
        a["einsaetze"] += 1
        a["personen"] += g["anzahl"]
        a["kats"].add(g["kat"])
    res = sorted(anl.values(), key=lambda a: (a["abloesung"], a["anlage"]))
    for a in res:
        a["von"], a["bis"] = zeit_text(a["von"]), zeit_text(a["bis"])
        a["kats"] = sorted(a["kats"])
    return res
