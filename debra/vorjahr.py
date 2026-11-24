"""Vorjahres-Rangliste (Stafetten) als Datenbank für die Bahnen-/Serien-
einteilung. Quellen:
  - DEBRA-Final-Backup des Vorjahres (Ordner mit WI_/WT_/WR_-Dateien) – bevorzugt
  - Rangliste als PDF bzw. die beigelegte Text-Fassung 2025 (`pdftotext -layout`)
  - JTSST: Gesamt-Rangliste als PDF (Pendelstafette, Hindernislauf, Schwedenstafette
    und Seilziehen je Sparte Knaben/Mädchen und Kategorie)

Gesetzt wird immer nur mit dem Resultat der Gruppe 1 eines Vereins – nie mit dem
einer 2. oder weiteren Gruppe.
"""
import os
import re
import subprocess

from .db import BASE_DIR, get_db

JTSST_SPARTEN = ("Knaben", "Mädchen")
# JTSST-Disziplinen mit Setzung nach Vorjahr (Name in der Rangliste)
JTSST_NAMES = ("Pendelstafette", "Hindernislauf", "Schwedenstafette", "Seilziehen")

# Relevante Stafetten-Disziplinen (Grundlage für die Bahnensetzung)
RELAY_NAMES = {"4x100m", "4x400m", "Schwedenstafette",
               "Olympische Stafette", "Pendelstafette 80m"}

FIXTURE = os.path.join(os.path.dirname(__file__), "vorjahr_2025.txt")
# Standardablage des letzten Final-Backups (wird ohne Pfadangabe verwendet)
BACKUP_STANDARD = os.path.join(BASE_DIR, "Inputs", "TSST", "Backup-Final TSST")

# Rang  Verein ...  ZTV-WTU|TGTV  Zeit  [s]  [***|*]
_ZEILE = re.compile(
    r"^\s*(\d+)\.\s+(.+?)\s+(?:ZTV-WTU|TGTV)\s+(\d+:\d+\.\d+|\d+\.\d+)\s*s?\s*\**\s*$")
_HEADER = re.compile(r"^(.+?)\s{2,}Total\s+\d+\s+Vereine")


def _zeit(text):
    text = text.strip()
    if ":" in text:
        m, s = text.split(":", 1)
        return round(int(m) * 60 + float(s), 2)
    return round(float(text), 2)


def _split_gruppe(verein):
    """'Buch am Irchel 2' -> ('Buch am Irchel', 2)."""
    m = re.match(r"^(.*\S)\s+(\d+)$", verein.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return verein.strip(), None


def parse_text(text):
    """Liefert Liste von (sparte, disziplin, verein, gruppennr, rang, zeit)."""
    sparte = None
    disziplin = None
    zeilen = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "Turnerinnen":
            sparte = "Turnerinnen"; continue
        if stripped == "Turner":
            sparte = "Turner"; continue
        h = _HEADER.match(line)
        if h:
            disziplin = h.group(1).strip()
            continue
        if disziplin in RELAY_NAMES:
            m = _ZEILE.match(line)
            if m:
                rang = int(m.group(1))
                verein, gruppennr = _split_gruppe(m.group(2))
                zeilen.append((sparte, disziplin, verein, gruppennr, rang, _zeit(m.group(3))))
    return zeilen


def _text_aus_pdf(pfad):
    try:
        out = subprocess.run(["pdftotext", "-layout", pfad, "-"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    try:
        import pdfplumber
        with pdfplumber.open(pfad) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return None


def parse_backup(ordner):
    """Rangierte Stafetten-Resultate aus einem DEBRA-Backup: Liste wie parse_text."""
    import glob
    from .import_backup import NICHT_RANGIERT, _num, _read_csv
    zeilen = []
    for wi_pfad in sorted(glob.glob(os.path.join(ordner, "WI_*.txt"))):
        nr = re.search(r"WI_(\d+)\.txt$", wi_pfad).group(1)
        kats = {r["KategorieNr"]: r for r in _read_csv(wi_pfad)
                if (r.get("Bezeichnung") or "").strip() in RELAY_NAMES}
        wt_pfad = os.path.join(ordner, f"WT_{nr}.txt")
        wr_pfad = os.path.join(ordner, f"WR_{nr}.txt")
        if not kats or not (os.path.exists(wt_pfad) and os.path.exists(wr_pfad)):
            continue
        wr = {r["StartNr"]: r for r in _read_csv(wr_pfad)}
        for t in _read_csv(wt_pfad):
            k, r = kats.get(t["KategorieNr"]), wr.get(t["StartNr"])
            rang = _num(r.get("Rang")) if r else None
            if not k or rang in NICHT_RANGIERT or rang is None:
                continue
            zeilen.append(((k.get("Sparte") or "").strip() or None, k["Bezeichnung"].strip(),
                           (t.get("Verein") or "").strip(), _num(t.get("GruppenNr")),
                           rang, _num(r.get("Total"))))
    return zeilen


def importieren(conn=None, pdf_pfad=None, text=None):
    """Vorjahres-Stafettenresultate importieren (ersetzt bestehende).

    pdf_pfad darf auch ein DEBRA-Backup-Ordner sein. Ohne Angabe wird das
    Final-Backup unter Inputs/TSST verwendet, sonst die beigelegte Rangliste 2025.
    """
    eigen = conn is None
    if eigen:
        conn = get_db()
    rows = None
    if text is None:
        ordner = pdf_pfad if pdf_pfad and os.path.isdir(pdf_pfad) else (
            BACKUP_STANDARD if not pdf_pfad and os.path.isdir(BACKUP_STANDARD) else None)
        if ordner:
            rows = parse_backup(ordner)
        elif pdf_pfad:
            text = _text_aus_pdf(pdf_pfad)
        if rows is None and text is None and os.path.exists(FIXTURE):
            text = open(FIXTURE, encoding="utf-8").read()
    if rows is None and not text:
        if eigen:
            conn.close()
        return 0
    if rows is None:
        rows = parse_text(text)
    cur = conn.cursor()
    cur.execute("DELETE FROM vorjahr WHERE sparte IS NULL OR sparte NOT IN (?,?)", JTSST_SPARTEN)
    cur.executemany(
        "INSERT INTO vorjahr(sparte, disziplin, verein, gruppennr, rang, zeit) "
        "VALUES(?,?,?,?,?,?)", rows)
    conn.commit()
    if eigen:
        conn.close()
    return len(rows)


# --------------------------------------------------------------------------- #
# JTSST
# --------------------------------------------------------------------------- #
_JT_KOPF = re.compile(r"^(%s) Kat\. ([ABC])\b" %"|".join(JTSST_NAMES))
_JT_RANG = re.compile(r"^(\d+)\.$")
_JT_WERT = re.compile(r"^(\d+:\d+\.\d+|\d+\.\d+)(?:\s*\w+)?$")
_JT_VERBAND = re.compile(r"^[A-Z]{2,}(?:-[A-Z]+)?$")


def jtsst_disziplin(name, kat):
    """Schlüssel in der Tabelle vorjahr, z. B. 'Pendelstafette Kat. A'."""
    return f"{name} Kat. {kat}"


def parse_jtsst_text(seiten):
    """JTSST-Gesamtrangliste (Text je PDF-Seite, Zeile für Zeile wie PyMuPDF sie liefert):
    Verein N / Verband / Rang. / [Total] / [***]. Liefert Zeilen wie parse_text."""
    zeilen = []
    sparte = disziplin = None
    for text in seiten:
        lines = [l.strip() for l in text.splitlines()]
        kopf = next((l for l in lines[:3] if l in JTSST_SPARTEN), None)
        if kopf:
            sparte = kopf
        k = next((m for m in map(_JT_KOPF.match, lines) if m), None)
        if k:
            disziplin = jtsst_disziplin(k.group(1), k.group(2))
        elif kopf:
            disziplin = None            # neue Disziplin ohne Setzung (Ballwurf, Seilspringen)
        if not (sparte and disziplin):
            continue
        for i in range(len(lines) - 2):
            m = _JT_RANG.match(lines[i + 2])
            if not (m and _JT_VERBAND.match(lines[i + 1]) and lines[i]):
                continue
            verein, gruppennr = _split_gruppe(lines[i])
            w = _JT_WERT.match(lines[i + 3]) if i + 3 < len(lines) else None
            zeit = _zeit(w.group(1)) if w and not disziplin.startswith("Seilziehen") else None
            zeilen.append((sparte, disziplin, verein, gruppennr, int(m.group(1)), zeit))
    return zeilen


def importieren_jtsst(conn, pdf_pfad):
    """JTSST-Vorjahresrangliste (PDF) importieren – ersetzt nur die Knaben/Mädchen-Daten."""
    import pymupdf
    with pymupdf.open(pdf_pfad) as doc:
        rows = parse_jtsst_text([p.get_text() for p in doc])
    if not rows:
        return 0
    cur = conn.cursor()
    cur.execute("DELETE FROM vorjahr WHERE sparte IN (?,?)", JTSST_SPARTEN)
    cur.executemany(
        "INSERT INTO vorjahr(sparte, disziplin, verein, gruppennr, rang, zeit) "
        "VALUES(?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def schluessel(kat):
    """(sparte, disziplin) einer Kategorie in der Tabelle vorjahr."""
    if kat["sparte"] in JTSST_SPARTEN:
        m = re.match(r"^(\S+)\b.*\bKat\. ([ABC])\b", kat["bezeichnung"] or "")
        if m:
            return kat["sparte"], jtsst_disziplin(m.group(1), m.group(2))
    sparte = "Turner" if (kat["geschlecht"] or "m") == "m" else "Turnerinnen"
    return sparte, kat["bezeichnung"]


def setzwerte(conn, kat):
    """{verein: (rang, zeit)} der Gruppe 1 je Verein aus dem Vorjahr (nie die 2. Gruppe)."""
    sparte, disziplin = schluessel(kat)
    werte = {}
    for r in conn.execute(
            "SELECT verein, rang, zeit FROM vorjahr WHERE disziplin=? AND (sparte=? OR sparte IS NULL) "
            "AND COALESCE(gruppennr, 1)=1 ORDER BY rang", (disziplin, sparte)):
        werte.setdefault(r["verein"], (r["rang"], r["zeit"]))
    return werte


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "jtsst":
        c = get_db()
        print(f"JTSST-Vorjahr importiert: {importieren_jtsst(c, sys.argv[2])} Resultate")
        c.close()
    else:
        n = importieren(pdf_pfad=sys.argv[1] if len(sys.argv) > 1 else None)
        print(f"Vorjahr importiert: {n} Stafetten-Resultate")
