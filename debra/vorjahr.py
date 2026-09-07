"""Vorjahres-Rangliste (Stafetten) als Datenbank für die Bahnen-/Serien-
einteilung. Liest die als Text beigelegte Rangliste (aus dem PDF mit
`pdftotext -layout` extrahiert) und speichert die Stafetten-Resultate.
"""
import os
import re
import subprocess

from .db import get_db

# Relevante Stafetten-Disziplinen (Grundlage für die Bahnensetzung)
RELAY_NAMES = {"4x100m", "4x400m", "Schwedenstafette",
               "Olympische Stafette", "Pendelstafette 80m"}

FIXTURE = os.path.join(os.path.dirname(__file__), "vorjahr_2025.txt")

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


def importieren(conn=None, pdf_pfad=None, text=None):
    """Vorjahres-Stafettenresultate importieren (ersetzt bestehende)."""
    eigen = conn is None
    if eigen:
        conn = get_db()
    if text is None:
        if pdf_pfad:
            text = _text_aus_pdf(pdf_pfad)
        if text is None and os.path.exists(FIXTURE):
            text = open(FIXTURE, encoding="utf-8").read()
    if not text:
        if eigen:
            conn.close()
        return 0
    rows = parse_text(text)
    cur = conn.cursor()
    cur.execute("DELETE FROM vorjahr")
    cur.executemany(
        "INSERT INTO vorjahr(sparte, disziplin, verein, gruppennr, rang, zeit) "
        "VALUES(?,?,?,?,?,?)", rows)
    conn.commit()
    if eigen:
        conn.close()
    return len(rows)


if __name__ == "__main__":
    import sys
    n = importieren(pdf_pfad=sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Vorjahr importiert: {n} Stafetten-Resultate")
