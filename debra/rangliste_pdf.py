"""Ranglisten als PDF (A4 hoch) in zwei Gestaltungen:

  modern     (Standard) zeitgemässes Layout mit Barlow-Schrift, Podest-Medaillen,
             Auszeichnungsgrenze, Einzelresultaten und Seitenzahl je Disziplin
  klassisch  wie die offiziellen Ranglisten 2026 (DEBRA-Optik)

Beide zeigen dieselben Informationen. Klassischer Seitenaufbau
(Masse in pt, aus 2026-TSST-Rangliste.pdf gemessen):
  Kopfzeile "WTU Turn-, Spiel- und Stafettentag 2026" links, Datum rechts, Linie
  Sparten-Balken (nur erste Seite einer Disziplin), Disziplin-Balken mit "Total N Vereine"
  Spalten Rang | Verein (+ Einzelresultate klein darunter) | Verband | Total | Auszeichnung
  jede zweite Zeile farbig hinterlegt, Fusslinie; jede Disziplin beginnt auf neuer Seite.
Farben: TSST oliv, JTSST petrol. Gruppen mit Vermerk (AK, NGes, …) folgen am Schluss.

Die Gesamt-Rangliste setzt alle Disziplinen in der eingestellten Reihenfolge zusammen und
fügt die hochgeladenen Zusatzblätter (Deckblatt, Sponsoren, Fundbüro …) an ihrer Position ein.
"""

import io
from datetime import datetime

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import scoring

BREITE, HOEHE = A4
LINKS, RECHTS = 57.0, 550.0
FUSS = 765.0                       # Fusslinie (von oben)

FARBEN = {                         # Sparten-Balken, Disziplin-Balken, Zeilen-Hinterlegung
    "tsst": ((158, 156, 54), (222, 220, 118), (254, 252, 150)),
    "jtsst": ((97, 143, 157), (161, 207, 221), (193, 239, 253)),
}
X_RANG, X_VEREIN, X_VERBAND, X_TOTAL, X_AUSZ = 79.0, 102.8, 312.6, 420.4, 468.5
WERT_ABSTAND = 45.4
ZEILE_MIT_WERTEN, ZEILE_OHNE = 23.75, 17.3
VERMERK_DEBRA = {"ak": "AK", "nges": "NGes", "aufg": "Aufg", "disq": "Disq", "unfall": "Unfall"}
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def _rgb(t):
    return Color(t[0] / 255, t[1] / 255, t[2] / 255)


def datum_lang(iso):
    """'2026-09-06' -> '6. September 2026'."""
    try:
        d = datetime.strptime((iso or "")[:10], "%Y-%m-%d")
        return f"{d.day}. {MONATE[d.month - 1]} {d.year}"
    except ValueError:
        return iso or ""


def kopfzeile_standard(wettkampf, jugend):
    jahr = (wettkampf["datum"] or "")[:4]
    return ("WTU Jugend Turn-, Spiel- und Stafettentag " if jugend
            else "WTU Turn-, Spiel- und Stafettentag ") + jahr


def _zeit(sek):
    if sek >= 60:
        m = int(sek // 60)
        return f"{m}:{sek - m * 60:05.2f}"
    return f"{sek:.2f}"


def total_text(wert, einheit, stafette):
    """Total wie Vorlage: '11.15 s', '2:37.02', '33.25 m', '171.00'."""
    if wert is None:
        return ""
    if einheit == "s" or stafette:
        return _zeit(wert) + (" s" if wert < 60 else "")
    if einheit == "m":
        return f"{wert:.2f} m"
    return f"{wert:.2f}"


def _titel(kat):
    """Disziplin ohne Sparte: 'Ballwurf Mädchen Kat. A, …' -> 'Ballwurf Kat. A, …'."""
    bez, sparte = kat["bezeichnung"], kat["sparte"] or ""
    return bez.replace(f" {sparte} ", " ", 1) if sparte else bez


def _name(e):
    person = f"{e.get('vorname', '')} {e.get('nachname', '')}".strip()
    if person:
        return person
    return (e.get("verein") or "") + (f" {e['gruppennr']}" if e.get("gruppennr") else "")


class _Seiten:
    """Zeichnet Ranglisten-Seiten auf eine Leinwand (Koordinaten von oben)."""

    def __init__(self, kopf, datum, farben, fortlaufend=False, offset=0):
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle("Rangliste")
        self.kopf, self.datum = kopf, datum
        self.balken, self.disz, self.streifen = (_rgb(f) for f in farben)
        self.seite = 0
        self.y = None                  # aktuelle Position auf der offenen Seite (fortlaufend)

    # Hilfen in Koordinaten "von oben"
    def text(self, x, y, s, font="Helvetica", size=10, farbe=black, rechts=False):
        self.c.setFont(font, size)
        self.c.setFillColor(farbe)
        (self.c.drawRightString if rechts else self.c.drawString)(x, HOEHE - y, s)

    def rechteck(self, y, h, farbe, x=LINKS, w=RECHTS - LINKS):
        self.c.setFillColor(farbe)
        self.c.rect(x, HOEHE - y - h, w, h, stroke=0, fill=1)

    def linie(self, y):
        self.rechteck(y, 0.8, black)

    def neue_seite(self):
        if self.seite:
            self.c.showPage()
        self.seite += 1
        self.text(LINKS, 66.5, self.kopf)
        self.text(RECHTS, 66.5, self.datum, rechts=True)
        self.linie(74)
        self.linie(FUSS)

    def disziplin(self, kat, daten, sparte_balken, einzelwerte, mitglieder, neue_seite=True):
        """Eine Disziplin ab neuer Seite bzw. fortlaufend; liefert die Anzahl neuer Seiten."""
        start = self.seite
        einheit = daten.get("einheit") or kat["einheit"] or ""
        stafette = daten.get("modus") == "stafette"
        nur_rang = einheit == "Rang"               # Seilziehen: Cup-Rang, kein Total
        werte_zeigen = einzelwerte and not stafette and not nur_rang and mitglieder > 1
        zeilen = [(e, "") for e in daten["eintraege"] if e.get("total") is not None or e.get("rang")]
        zeilen += [(e, VERMERK_DEBRA.get(e.get("status"), e.get("status_kurz", "")))
                   for e in daten.get("sonder", [])]
        zeilen += [(e, "") for e in daten["eintraege"] if e.get("total") is None and not e.get("rang")]
        anzahl = len(daten["eintraege"]) + len(daten.get("sonder", []))

        def kopf(erste, mit_werten, oben=None):
            if oben is None:
                self.neue_seite()
                y = 88.0
            else:
                y = oben
            if erste and sparte_balken:
                self.rechteck(y, 20, self.balken)
                self.text(LINKS + 0.5, y + 14.3, kat["sparte"] or "", "Helvetica-Bold", 14, white)
                y += 28
            self.rechteck(y, 20, self.disz)
            self.text(LINKS + 0.5, y + 14.2, _titel(kat), "Helvetica", 14)
            self.text(RECHTS - 0.7, y + 9.8, f"Total  {anzahl} Vereine", "Helvetica-Bold", 10, rechts=True)
            self.text(60.4, y + 33.5, "Rang", "Helvetica-Bold")
            self.text(X_VEREIN, y + 33.5, "Verein", "Helvetica-Bold")
            if not nur_rang:
                self.text(X_TOTAL, y + 33.5, "Total", "Helvetica-Bold")
            if mit_werten:
                for i in range(mitglieder):
                    self.text(X_VEREIN + i * WERT_ABSTAND - 0.3, y + 46.8, f"{i + 1}. Tu/Ti", size=7)
                y += 54
            else:
                y += 38
            self.linie(y)
            return y

        # Kopf mit "1. Tu/Ti …" nur, wenn auf der Seite Einzelwerte folgen (nicht beim AK-Block)
        mit_werten = werte_zeigen and bool(zeilen) and not zeilen[0][1]
        oben = None
        if not neue_seite and self.y is not None:
            # fortlaufend: Balken + Spaltenkopf (~110) und 3 Zeilen müssen noch Platz haben
            oben = self.y + 14
            h0 = ZEILE_MIT_WERTEN if mit_werten else ZEILE_OHNE
            if oben + (28 if sparte_balken else 0) + 20 + (54 if mit_werten else 38) + 3 * h0 > FUSS - 4:
                oben = None
        y = kopf(True, mit_werten, oben)
        for nr, (e, vermerk) in enumerate(zeilen):
            werte = werte_zeigen and not vermerk
            h = ZEILE_MIT_WERTEN if werte else ZEILE_OHNE
            if y + h > FUSS - 4:
                y = kopf(False, werte)
            if nr % 2:
                if werte:
                    self.rechteck(y, 24, self.streifen)
                else:
                    self.rechteck(y + 1.6, 14.2, self.streifen)
            if e.get("rang") and not vermerk:
                self.text(X_RANG, y + 10.8, f"{e['rang']}.", "Helvetica-Bold", rechts=True)
            self.text(X_VEREIN, y + 10.8, _name(e), "Helvetica-Bold")
            self.text(X_VERBAND, y + 10.4, e.get("verband") or "")
            if not nur_rang:
                self.text(X_TOTAL, y + 10.8, total_text(e.get("total"), einheit, stafette), "Helvetica-Bold")
            if vermerk:
                self.text(X_AUSZ, y + 10.8, vermerk)
            elif e.get("marker"):
                self.text(X_AUSZ, y + 10.8, e["marker"], "Helvetica-Bold")
            if werte:
                for i, w in enumerate((e.get("noten") or [])[:mitglieder]):
                    s = "-" if w is None else (_zeit(w) if einheit == "s" else f"{w:.2f}")
                    self.text(X_VEREIN + i * WERT_ABSTAND, y + 21.6, s, size=7)
            y += h
        self.y = y
        return self.seite - start

    def pdf(self):
        if self.seite:
            self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


# --------------------------------------------------------------------------- #
# Moderne Gestaltung
# --------------------------------------------------------------------------- #
import os                                                                    # noqa: E402

from reportlab.lib.colors import HexColor                                   # noqa: E402
from reportlab.pdfbase import pdfmetrics                                    # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont                                # noqa: E402

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_SCHRIFT = {}


def _schriften():
    """Barlow (OFL, liegt in debra/fonts) registrieren; sonst Helvetica."""
    if not _SCHRIFT:
        try:
            for name in ("Regular", "Medium", "SemiBold", "Bold"):
                pdfmetrics.registerFont(TTFont(f"Barlow-{name}", os.path.join(_FONT_DIR, f"Barlow-{name}.ttf")))
            _SCHRIFT.update(r="Barlow-Regular", m="Barlow-Medium", s="Barlow-SemiBold", b="Barlow-Bold")
        except Exception:  # noqa: BLE001 – Schrift fehlt: Standardschrift verwenden
            _SCHRIFT.update(r="Helvetica", m="Helvetica", s="Helvetica-Bold", b="Helvetica-Bold")
    return _SCHRIFT


# Kräftige Farben mit hohem Kontrast (keine Pastelltöne): Akzent, Akzent dunkel
MODERN = {
    "tsst": (HexColor("#556B0B"), HexColor("#3E4F05")),
    "jtsst": (HexColor("#0F6378"), HexColor("#0A4756")),
}
TINTE, GRAU, LINIE, ZEBRA = HexColor("#111827"), HexColor("#374151"), HexColor("#9CA3AF"), HexColor("#EDEFF2")
VERMERK_FARBE = HexColor("#4B5563")
PODEST = {1: HexColor("#A87B00"), 2: HexColor("#5F6B77"), 3: HexColor("#8E4A1C")}
M_L, M_R = 42.5, 552.8
M_RANG, M_NAME, M_VERBAND, M_TOTAL = 58.0, 82.0, 338.0, 512.0
M_WERT = 46.0
M_FUSS = 804.0
M_ZEILE_WERTE, M_ZEILE = 26.0, 19.5


class _ModernSeiten:
    """Moderne Ranglisten-Seiten; gleiche Schnittstelle wie _Seiten."""

    def __init__(self, kopf, datum, ort, art, fortlaufend=False, offset=0):
        self.f = _schriften()
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle("Rangliste")
        self.kopf, self.datum, self.ort = kopf, datum, ort
        self.akzent, self.hell = MODERN[art]
        self.fortlaufend, self.offset = fortlaufend, offset
        self.seite = 0
        self.y = None                  # aktuelle Position auf der offenen Seite (fortlaufend)

    def text(self, x, y, s, font="r", size=9.5, farbe=TINTE, ausrichtung="l", sperrung=0):
        # Laufweite (Tc) bleibt im PDF über Textblöcke hinweg aktiv – darum immer explizit setzen
        self.c.setFillColor(farbe)
        t = self.c.beginText()
        t.setFont(self.f[font], size)
        t.setCharSpace(sperrung)
        breite = pdfmetrics.stringWidth(s, self.f[font], size) + sperrung * max(len(s) - 1, 0)
        versatz = {"l": 0, "r": breite, "c": breite / 2}[ausrichtung]
        t.setTextOrigin(x - versatz, HOEHE - y)
        t.textOut(s)
        self.c.drawText(t)

    def breite(self, s, font, size):
        return pdfmetrics.stringWidth(s, self.f[font], size)

    def rechteck(self, x, y, w, h, farbe, radius=0):
        self.c.setFillColor(farbe)
        if radius:
            self.c.roundRect(x, HOEHE - y - h, w, h, radius, stroke=0, fill=1)
        else:
            self.c.rect(x, HOEHE - y - h, w, h, stroke=0, fill=1)

    def linie(self, y, farbe=LINIE, breite=0.6, x0=M_L, x1=M_R, strich=None):
        self.c.setStrokeColor(farbe)
        self.c.setLineWidth(breite)
        self.c.setDash(*(strich or ([], 0)))
        self.c.line(x0, HOEHE - y, x1, HOEHE - y)
        self.c.setDash([], 0)

    def etikett(self, x, y, s, hintergrund, farbe, size=7, mitte=False):
        """Kleines abgerundetes Etikett (Sparte, Vermerk, Finalrunde)."""
        w = self.breite(s, "b", size) + 0.6 * max(len(s) - 1, 0) + 10
        x0 = x - w / 2 if mitte else x
        self.rechteck(x0, y - size - 1.6, w, size + 5, hintergrund, radius=(size + 5) / 2)
        self.text(x0 + 5, y, s, "b", size, farbe, sperrung=0.6)
        return w

    def seitenrahmen(self, titel, nr, von):
        if self.seite:
            self.c.showPage()
        self.seite += 1
        self.text(M_L, 30, self.kopf.upper(), "b", 7.8, self.akzent, sperrung=0.8)
        rechts = " · ".join(x for x in (self.datum, self.ort) if x)
        self.text(M_R, 30, rechts, "m", 8.2, GRAU, "r")
        self.linie(38)
        self.linie(M_FUSS)
        self.rechteck(M_L, M_FUSS + 5.5, 2.6, 8, self.akzent)
        self.text(M_L + 6, M_FUSS + 12, "Auszeichnung", "m", 7.5, GRAU)
        if self.fortlaufend:
            fuss = f"Seite {self.offset + self.seite}"
        else:
            fuss = f"{titel}  ·  Seite {nr}/{von}" if von > 1 else titel
        self.text(M_R, M_FUSS + 12, fuss, "m", 7.5, GRAU, "r")

    def disziplin(self, kat, daten, sparte_balken, einzelwerte, mitglieder, neue_seite=True):
        start = self.seite
        einheit = daten.get("einheit") or kat["einheit"] or ""
        stafette = daten.get("modus") == "stafette"
        nur_rang = einheit == "Rang"
        werte_zeigen = einzelwerte and not stafette and not nur_rang and mitglieder > 1
        rangiert = [e for e in daten["eintraege"] if e.get("total") is not None or e.get("rang")]
        offen = [e for e in daten["eintraege"] if e.get("total") is None and not e.get("rang")]
        sonder = daten.get("sonder", [])
        anzahl = len(daten["eintraege"]) + len(sonder)
        grenze = daten.get("anz_ausz")
        titel = _titel(kat)

        # 1) Elemente mit Höhe sammeln: Zeilen, Auszeichnungsgrenze, Vermerk-Überschrift
        elemente = []
        letzte_ausz = max((i for i, e in enumerate(rangiert) if e.get("auszeichnung")), default=None)
        for i, e in enumerate(rangiert + offen):
            elemente.append(("zeile", e, M_ZEILE_WERTE if werte_zeigen else M_ZEILE))
            if i == letzte_ausz and i < len(rangiert) + len(offen) - 1:
                elemente.append(("grenze", None, 14))
        if sonder:
            elemente.append(("sonderkopf", None, 24))
            elemente += [("sonder", e, M_ZEILE) for e in sonder]

        # 2) Umbruch: erste Seite hat den grossen Titelblock (Höhe 120 ab Blockanfang B).
        #    Fortlaufend: direkt unter der vorherigen Disziplin, wenn Titel + 3 Zeilen Platz haben.
        neu = neue_seite or self.y is None
        block = 46.0
        if not neu:
            block = self.y + 18
            platz = sum(el[2] for el in elemente[:3])
            if block + 120 + platz > M_FUSS - 6:
                neu, block = True, 46.0
        erste_oben, folge_oben = block + 120, 104.0
        seiten, aktuell, y = [], [], erste_oben
        for i, el in enumerate(elemente):
            hoehe = el[2]
            if el[0] == "grenze":
                # Grenzstrich bleibt immer auf der Seite der letzten ausgezeichneten Gruppe
                aktuell.append(el)
                y += el[2]
                continue
            if i + 1 < len(elemente) and elemente[i + 1][0] == "grenze":
                hoehe += 9          # Platz für den Strich unter der letzten Auszeichnung
            if y + hoehe > M_FUSS - 6 and aktuell:
                seiten.append(aktuell)
                aktuell, y = [], folge_oben
            aktuell.append(el)
            y += el[2]
        seiten.append(aktuell)

        # 3) Zeichnen
        if werte_zeigen:
            beschreibung = f"Durchschnitt aus {mitglieder} Leistungen"
        elif stafette:
            beschreibung = "Teamzeit"
        elif nur_rang:
            beschreibung = "Rangierung im Cup-System"
        else:
            beschreibung = ""
        zeilen_nr = 0
        for snr, inhalt in enumerate(seiten, start=1):
            if snr > 1 or neu:
                self.seitenrahmen(titel, snr, len(seiten))
            if snr == 1:
                if not neu:
                    self.linie(block - 6, LINIE, 0.6)        # Trennlinie zur vorherigen Disziplin
                self.etikett(M_L, block + 18, (kat["sparte"] or "").upper(), self.akzent, white, 7.5)
                self.text(M_L, block + 50, titel, "b", 24, TINTE)
                info = [f"{anzahl} Gruppen"]
                if grenze:
                    info.append(f"{grenze} Auszeichnungen")
                if beschreibung:
                    info.append(beschreibung)
                self.text(M_L, block + 67, "  ·  ".join(info), "m", 9.8, GRAU)
                y = block + 90
            else:
                self.text(M_L, 64, titel, "b", 14, TINTE)
                self.text(M_L + self.breite(titel, "b", 14) + 8, 64, "Fortsetzung", "m", 9.5, GRAU)
                y = 76.0
            # Tabellenkopf
            self.text(M_RANG, y + 14, "RANG", "b", 7, TINTE, "c", 0.7)
            self.text(M_NAME, y + 14, "VEREIN", "b", 7, TINTE, sperrung=0.7)
            self.text(M_VERBAND, y + 14, "VERBAND", "b", 7, TINTE, sperrung=0.7)
            if not nur_rang:
                self.text(M_TOTAL, y + 14, "TOTAL", "b", 7, TINTE, "r", 0.7)
            self.linie(y + 22, TINTE, 0.8)
            y += 26
            for art, e, h in inhalt:
                if art == "grenze":
                    self.linie(y + 6, self.hell, 1.1, strich=([3, 2], 0))
                    s = f"Auszeichnungsgrenze · {grenze} Preise"
                    w = self.breite(s, "b", 7) + 8
                    self.rechteck(M_R - w - 4, y + 1.5, w + 4, 9, white)
                    self.text(M_R - 2, y + 8.8, s, "b", 7, self.hell, "r")
                    y += h
                    continue
                if art == "sonderkopf":
                    self.text(M_L, y + 17, "AUSSER KONKURRENZ / VERMERKE", "b", 7.2, TINTE, sperrung=0.8)
                    self.linie(y + 22)
                    y += h
                    continue
                if zeilen_nr % 2:
                    self.rechteck(M_L, y, M_R - M_L, h, ZEBRA)
                zeilen_nr += 1
                mitte = y + (11.5 if h == M_ZEILE_WERTE else h / 2 + 3.3)
                if art == "zeile" and e.get("auszeichnung"):
                    self.rechteck(M_L, y + 1.5, 3.2, h - 3, self.akzent)
                # Rang bzw. Vermerk
                if art == "sonder":
                    label = VERMERK_DEBRA.get(e.get("status"), e.get("status_kurz", ""))
                    self.etikett(M_RANG, mitte, label, VERMERK_FARBE, white, 6.5, mitte=True)
                elif e.get("rang"):
                    r = e["rang"]
                    if r in PODEST:
                        self.c.setFillColor(PODEST[r])
                        self.c.circle(M_RANG, HOEHE - (mitte - 3.2), 8.2, stroke=0, fill=1)
                        self.text(M_RANG, mitte, str(r), "b", 9.5, white, "c")
                    else:
                        self.text(M_RANG, mitte, f"{r}.", "s", 10, TINTE, "c")
                # Verein + Finalrunde
                name = _name(e)
                self.text(M_NAME, mitte, name, "s", 10.5, TINTE)
                runde = e.get("runde")
                if daten.get("hat_final") and runde in ("A-Final", "B-Final", "Final") and art == "zeile":
                    self.etikett(M_NAME + self.breite(name, "s", 10.5) + 6, mitte - 1, runde.upper(),
                                 self.akzent, white, 6)
                self.text(M_VERBAND, mitte, e.get("verband") or "", "m", 8.8, GRAU)
                # Total
                if not nur_rang:
                    tot = total_text(e.get("total"), einheit, stafette)
                    if tot:
                        zahl, _, unit = tot.partition(" ")
                        self.text(M_TOTAL, mitte, zahl, "b", 11.5, TINTE if art == "zeile" else GRAU, "r")
                        if unit:
                            self.text(M_TOTAL + 2.5, mitte, unit, "m", 8.5, GRAU)
                    elif art == "zeile":
                        self.text(M_TOTAL, mitte, "–", "r", 10, GRAU, "r")
                # Einzelresultate, bestes hervorgehoben
                if werte_zeigen and art == "zeile":
                    werte = (e.get("noten") or [])[:mitglieder]
                    for i, w in enumerate(werte):
                        s = "–" if w is None else (_zeit(w) if einheit == "s" else f"{w:.2f}")
                        bester = w is not None and w == e.get("best")
                        self.text(M_NAME + i * M_WERT, y + 22, s, "b" if bester else "m", 8.2,
                                  self.hell if bester else GRAU)
                y += h
        self.y = y
        return self.seite - start

    def verein(self, name, verband, zeilen, einzelwerte):
        """Vereinsblatt ab neuer Seite: Sparte > Disziplin > Kategorie > Gruppen des Vereins."""
        ausz = sum(1 for z in zeilen if z["auszeichnung"])
        podest = sum(1 for z in zeilen if z["rang"] in PODEST and not z["vermerk"])

        # 1) Elemente: Überschriften je Sparte/Disziplin/Kategorie, dann die Gruppen
        elemente, vorher = [], (None, None, None)
        for z in zeilen:
            if z["sparte"] != vorher[0]:
                elemente.append(("sparte", z["sparte"], 30))
                vorher = (z["sparte"], None, None)
            if z["disziplin"] != vorher[1]:
                info = None if z["kategorie"] else z["info"]
                elemente.append(("disziplin", (z["disziplin"], info), 24))
                vorher = (z["sparte"], z["disziplin"], None)
            if z["kategorie"] and z["kategorie"] != vorher[2]:
                elemente.append(("kategorie", (z["kategorie"], z["info"]), 20))
                vorher = (z["sparte"], z["disziplin"], z["kategorie"])
            mit_werten = einzelwerte and bool(z["werte"])
            elemente.append(("zeile", z, 26.0 if mit_werten else 20.0))

        # 2) Umbruch: Überschriften nie allein am Seitenende (immer mit der ersten Gruppe)
        seiten, aktuell, y = [], [], 152.0
        for i, el in enumerate(elemente):
            hoehe = el[2]
            if el[0] != "zeile":
                j = i + 1
                while j < len(elemente) and elemente[j][0] != "zeile":
                    hoehe += elemente[j][2]
                    j += 1
                if j < len(elemente):
                    hoehe += elemente[j][2]
            if y + hoehe > M_FUSS - 6 and aktuell:
                seiten.append(aktuell)
                aktuell, y = [], 92.0
            aktuell.append(el)
            y += el[2]
        seiten.append(aktuell)

        # 3) Zeichnen
        zeilen_nr = 0
        for snr, inhalt in enumerate(seiten, start=1):
            self.seitenrahmen(f"Vereinsblatt {name}", snr, len(seiten))
            if snr == 1:
                self.etikett(M_L, 64, "VEREINSBLATT", self.akzent, white, 7.5)
                self.text(M_L, 96, name, "b", 24, TINTE)
                info = [x for x in (verband, f"{len(zeilen)} Gruppen") if x]
                info.append(f"{ausz} Auszeichnung{'en' if ausz != 1 else ''}")
                if podest:
                    info.append("1 Podestplatz" if podest == 1 else f"{podest} Podestplätze")
                self.text(M_L, 113, "  ·  ".join(info), "m", 9.8, GRAU)
                y = 122.0
            else:
                self.text(M_L, 64, name, "b", 14, TINTE)
                self.text(M_L + self.breite(name, "b", 14) + 8, 64, "Fortsetzung", "m", 9.5, GRAU)
                y = 62.0
            for art, z, h in inhalt:
                if art == "sparte":
                    self.text(M_L, y + 22, (z or "").upper(), "b", 8, self.akzent, sperrung=1.0)
                    self.linie(y + 27, self.akzent, 1.0)
                    zeilen_nr = 0
                elif art == "disziplin":
                    titel, info = z
                    self.text(M_L, y + 18, titel, "b", 12.5, TINTE)
                    if info:
                        self.text(M_R, y + 18, info, "m", 8.5, GRAU, "r")
                    self.linie(y + 23, LINIE, 0.5)
                    zeilen_nr = 0
                elif art == "kategorie":
                    kat, info = z
                    self.text(M_L + 10, y + 14.5, kat, "s", 10, TINTE)
                    self.text(M_R, y + 14.5, info, "m", 8.5, GRAU, "r")
                    zeilen_nr = 0
                else:
                    self._vereinszeile(z, y, h, einzelwerte, zeilen_nr)
                    zeilen_nr += 1
                y += h

    def _vereinszeile(self, z, y, h, einzelwerte, nr):
        if nr % 2:
            self.rechteck(M_L, y, M_R - M_L, h, ZEBRA)
        mitte = y + (11.5 if h > 22 else h / 2 + 3.3)
        if z["auszeichnung"]:
            self.rechteck(M_L, y + 1.5, 3.2, h - 3, self.akzent)
        if z["vermerk"]:
            self.etikett(M_RANG, mitte, z["vermerk"], VERMERK_FARBE, white, 6.5, mitte=True)
        elif z["rang"] in PODEST:
            self.c.setFillColor(PODEST[z["rang"]])
            self.c.circle(M_RANG, HOEHE - (mitte - 3.2), 8.2, stroke=0, fill=1)
            self.text(M_RANG, mitte, str(z["rang"]), "b", 9.5, white, "c")
        elif z["rang"]:
            self.text(M_RANG, mitte, f"{z['rang']}.", "s", 10, TINTE, "c")
        self.text(M_NAME, mitte, z["gruppe"], "s", 10.5, TINTE)
        if z["runde"]:
            self.etikett(M_NAME + self.breite(z["gruppe"], "s", 10.5) + 6, mitte - 1, z["runde"].upper(),
                         self.akzent, white, 6)
        if einzelwerte and z["werte"] and h > 22:
            for i, (s, bester) in enumerate(z["werte"]):
                self.text(M_NAME + i * M_WERT, y + 22, s, "b" if bester else "m", 8.2,
                          self.hell if bester else GRAU)
        if z["rang"] and not z["vermerk"]:
            self.text(M_VERBAND, mitte, f"Rang {z['rang']} von {z['anzahl']}", "m", 8.8, GRAU)
        if z["total"]:
            zahl, _, unit = z["total"].partition(" ")
            self.text(M_TOTAL, mitte, zahl, "b", 11.5, GRAU if z["vermerk"] else TINTE, "r")
            if unit:
                self.text(M_TOTAL + 2.5, mitte, unit, "m", 8.5, GRAU)
        elif not z["nur_rang"]:
            self.text(M_TOTAL, mitte, "–", "r", 10, GRAU, "r")

    def pdf(self):
        if self.seite:
            self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def _disziplin_kategorie(titel):
    """'Ballwurf Kat. A, 13..16 jährig' -> ('Ballwurf', 'Kat. A, 13..16 jährig'); TSST ohne Kategorie."""
    if " Kat. " in titel:
        disziplin, kat = titel.split(" Kat. ", 1)
        return disziplin, "Kat. " + kat
    return titel, None


def vereine(conn, wettkampf):
    """Resultate je Verein: {verein: {"verband", "zeilen": [...]}} in Disziplin-Reihenfolge."""
    kats = conn.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                        (wettkampf["id"],)).fetchall()
    daten = {}
    for kat in kats:
        r = scoring.rangliste(conn, kat)
        einheit = r.get("einheit") or kat["einheit"] or ""
        stafette = r.get("modus") == "stafette"
        nur_rang = einheit == "Rang"
        anzahl = len(r["eintraege"]) + len(r.get("sonder", []))
        disziplin, kategorie = _disziplin_kategorie(_titel(kat))
        info = f"{anzahl} Gruppen" + (f" · {r['anz_ausz']} Auszeichnungen" if r.get("anz_ausz") else "")
        for e in r["eintraege"] + r.get("sonder", []):
            vermerk = (VERMERK_DEBRA.get(e.get("status"), e.get("status_kurz", "")) if e.get("status") else "")
            werte = []
            if not stafette and not nur_rang and not vermerk:
                for w in (e.get("noten") or []):
                    s = "–" if w is None else (_zeit(w) if einheit == "s" else f"{w:.2f}")
                    werte.append((s, w is not None and w == e.get("best")))
            v = daten.setdefault(e.get("verein") or "—", {"verband": e.get("verband") or "", "zeilen": []})
            v["zeilen"].append({
                "sparte": kat["sparte"] or "", "disziplin": disziplin, "kategorie": kategorie, "info": info,
                "gruppe": _name(e), "rang": None if vermerk else e.get("rang"), "anzahl": anzahl,
                "vermerk": vermerk, "nur_rang": nur_rang,
                "total": "" if nur_rang else total_text(e.get("total"), einheit, stafette),
                "auszeichnung": bool(e.get("auszeichnung")) and not vermerk,
                "runde": (e.get("runde") if r.get("hat_final")
                          and e.get("runde") in ("A-Final", "B-Final", "Final") else ""),
                "werte": werte if len(werte) > 1 else [],
            })
    return dict(sorted(daten.items(), key=lambda kv: kv[0].lower()))


def vereinsblatt_pdf(conn, wettkampf, verein=None):
    """Vereinsblätter im modernen Layout – alle Vereine oder einer; jeder Verein ab neuer Seite."""
    opt = einstellungen(conn, wettkampf)
    seiten = _ModernSeiten(opt["kopfzeile"], datum_lang(wettkampf["datum"]), wettkampf["ort"] or "", opt["art"])
    for name, v in vereine(conn, wettkampf).items():
        if verein is None or name == verein:
            seiten.verein(name, v["verband"], v["zeilen"], opt["einzelwerte"])
    return seiten.pdf() if seiten.seite else b""


def _anlass(conn, wettkampf_id):
    jugend = conn.execute("SELECT 1 FROM kategorie WHERE wettkampf_id=? AND sparte IN ('Knaben','Mädchen') "
                          "LIMIT 1", (wettkampf_id,)).fetchone() is not None
    return "jtsst" if jugend else "tsst"


def einstellungen(conn, wettkampf):
    """Kopfzeile und Einzelresultate je Anlass (Tabelle einstellung)."""
    art = _anlass(conn, wettkampf["id"])

    def wert(schluessel, standard):
        r = conn.execute("SELECT wert FROM einstellung WHERE schluessel=?",
                         (f"{schluessel}_{wettkampf['id']}",)).fetchone()
        return r["wert"] if r and r["wert"] is not None else standard

    return {"art": art,
            "kopfzeile": wert("rl_kopf", kopfzeile_standard(wettkampf, art == "jtsst")),
            "einzelwerte": wert("rl_einzelwerte", "1" if art == "tsst" else "0") == "1",
            "design": wert("rl_design", "modern")}


def _render(conn, wettkampf, kategorien, opt, fortlaufend=False, offset=0):
    """Setzt Disziplinen in ein PDF. fortlaufend: jede Disziplin direkt anschliessend
    (statt auf neuer Seite); offset: Seiten davor (für durchgehende Seitenzahlen)."""
    if opt.get("design") == "klassisch":
        seiten = _Seiten(opt["kopfzeile"], datum_lang(wettkampf["datum"]), FARBEN[opt["art"]],
                         fortlaufend, offset)
    else:
        seiten = _ModernSeiten(opt["kopfzeile"], datum_lang(wettkampf["datum"]), wettkampf["ort"] or "",
                               opt["art"], fortlaufend, offset)
    for kat in kategorien:
        daten = scoring.rangliste(conn, kat)
        if not daten["eintraege"] and not daten.get("sonder"):
            continue
        mitglieder = kat["anzahl_werte"] or len(daten.get("positionen") or []) or 1
        seiten.disziplin(kat, daten, True, opt["einzelwerte"], mitglieder, neue_seite=not fortlaufend)
    return seiten.pdf() if seiten.seite else b""


def einzel_pdf(conn, wettkampf, kat):
    """Rangliste einer Disziplin als PDF."""
    return _render(conn, wettkampf, [kat], einstellungen(conn, wettkampf))


def gesamt_pdf(conn, wettkampf, fortlaufend=False):
    """Gesamt-Rangliste aller Disziplinen (Reihenfolge, Auswahl) mit Zusatzblättern.

    fortlaufend=False: jede Disziplin auf neuer Seite; True: direkt anschliessend. Wo ein
    Zusatzblatt eingefügt wird, beginnt auch fortlaufend eine neue Seite.
    """
    kats = conn.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                        (wettkampf["id"],)).fetchall()
    opt = einstellungen(conn, wettkampf)
    blaetter = {}
    for b in conn.execute("SELECT * FROM zusatzblatt WHERE wettkampf_id=? AND aktiv=1 "
                          "ORDER BY sortierung, id", (wettkampf["id"],)).fetchall():
        blaetter.setdefault(b["position"], []).append(b)

    out = PdfWriter()
    abschnitt = []                     # Disziplinen, die am Stück gesetzt werden

    def setzen():
        if abschnitt:
            pdf = _render(conn, wettkampf, abschnitt, opt, fortlaufend, offset=len(out.pages))
            if pdf:
                for page in PdfReader(io.BytesIO(pdf)).pages:
                    out.add_page(page)
            abschnitt.clear()

    def zusatz(position):
        if blaetter.get(position):
            setzen()
        for b in blaetter.get(position, []):
            for page in PdfReader(io.BytesIO(b["pdf"])).pages:
                out.add_page(page)

    zusatz("anfang")
    for i, k in enumerate(kats):
        sparte = k["sparte"] or ""
        if i == 0 or (kats[i - 1]["sparte"] or "") != sparte:
            zusatz(f"vor_sparte:{sparte}")
        if k["rl_drucken"]:
            abschnitt.append(k)
            if not fortlaufend:
                setzen()
        zusatz(f"nach_kat:{k['id']}")
        if i == len(kats) - 1 or (kats[i + 1]["sparte"] or "") != sparte:
            zusatz(f"nach_sparte:{sparte}")
    setzen()
    zusatz("ende")
    out.add_metadata({"/Title": f"Rangliste {wettkampf['name']}"})
    buf = io.BytesIO()
    out.write(buf)
    return buf.getvalue()


def ablauf(conn, wettkampf):
    """Vorschau der Gesamt-Rangliste: Liste (art, text) in Druckreihenfolge."""
    kats = conn.execute("SELECT * FROM kategorie WHERE wettkampf_id=? ORDER BY sortierung, bezeichnung",
                        (wettkampf["id"],)).fetchall()
    blaetter = {}
    for b in conn.execute("SELECT * FROM zusatzblatt WHERE wettkampf_id=? AND aktiv=1 "
                          "ORDER BY sortierung, id", (wettkampf["id"],)).fetchall():
        blaetter.setdefault(b["position"], []).append(b)
    liste = []

    def zusatz(position):
        liste.extend(("blatt", f"{b['titel']} ({b['seiten']} S.)") for b in blaetter.get(position, []))

    zusatz("anfang")
    for i, k in enumerate(kats):
        sparte = k["sparte"] or ""
        if i == 0 or (kats[i - 1]["sparte"] or "") != sparte:
            zusatz(f"vor_sparte:{sparte}")
            liste.append(("sparte", sparte))
        if k["rl_drucken"]:
            liste.append(("disziplin", _titel(k)))
        zusatz(f"nach_kat:{k['id']}")
        if i == len(kats) - 1 or (kats[i + 1]["sparte"] or "") != sparte:
            zusatz(f"nach_sparte:{sparte}")
    zusatz("ende")
    return liste


def seiten_zaehlen(pdf_bytes):
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
