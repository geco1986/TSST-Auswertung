"""Name, Ort und Datum der drei Anlässe (TSST, JTSST, JET) – einstellbar statt fest im Code.

Die Werte stehen in der Tabelle ``einstellung`` (``anlass_<art>_datum`` / ``anlass_<art>_ort``)
und werden unter Einstellungen gepflegt. Ohne Eintrag gilt die Vorgabe unten; liegt deren Datum
schon in der Vergangenheit, wird das gleiche Datum im nächsten Jahr vorgeschlagen.
Der Name ist immer „<Grundname> <Jahr>“, das Jahr kommt aus dem Datum.
"""

from datetime import date

# art: (Grundname ohne Jahr, Ort, Datum der Vorlage)
STANDARD = {
    "tsst": ("Turn-, Spiel- und Stafettentag WTU", "Sportpark Deutweg, Winterthur", "2026-09-06"),
    "jtsst": ("Jugendwettkämpfe – Turn-, Spiel- und Stafettentag WTU", "Sportpark Deutweg, Winterthur",
              "2026-09-05"),
    "jet": ("Jugend-Einzelturntag JET WTU", "Sportanlage, Rheinau", "2026-07-05"),
}


def grundname(art):
    return STANDARD[art][0]


def _einstellung(conn, schluessel):
    row = conn.execute("SELECT wert FROM einstellung WHERE schluessel=?", (schluessel,)).fetchone()
    return (row[0] or "").strip() if row else ""


def _vorschlag_datum(vorlage):
    d = date.fromisoformat(vorlage)
    heute = date.today()
    while d < heute:
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:                     # 29. Februar
            d = d.replace(year=d.year + 1, day=28)
    return d.isoformat()


def gueltiges_datum(text):
    """'2027-09-04' bzw. '04.09.2027' -> '2027-09-04', sonst None."""
    text = (text or "").strip()
    try:
        if "." in text:
            t, m, j = (int(x) for x in text.split("."))
            return date(j, m, t).isoformat()
        return date.fromisoformat(text[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def name_mit_jahr(art, datum):
    return f"{grundname(art)} {datum[:4]}"


def daten(conn, art):
    """{'name', 'ort', 'datum', 'jahr'} für den Anlass `art` aus den Einstellungen bzw. der Vorgabe."""
    _, ort_std, datum_std = STANDARD[art]
    datum = gueltiges_datum(_einstellung(conn, f"anlass_{art}_datum")) or _vorschlag_datum(datum_std)
    ort = _einstellung(conn, f"anlass_{art}_ort") or ort_std
    return {"name": name_mit_jahr(art, datum), "ort": ort, "datum": datum, "jahr": int(datum[:4])}


def speichern(conn, art, datum=None, ort=None):
    """Datum/Ort eines Anlasses in den Einstellungen ablegen (ohne commit)."""
    for feld, wert in (("datum", datum), ("ort", ort)):
        if wert is None:
            continue
        conn.execute("INSERT INTO einstellung(schluessel, wert) VALUES(?,?) "
                     "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert",
                     (f"anlass_{art}_{feld}", wert))


def ist_name(art, name):
    """Gehört der Wettkampf-Name zum Anlass `art` (egal welches Jahr)?"""
    return (name or "").startswith(grundname(art))
