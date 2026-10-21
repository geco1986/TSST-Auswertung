"""Vorjahres-Rangliste (Stafetten) als Datenbank für die Bahnen-/Serien-
einteilung. Quellen:
  - DEBRA-Final-Backup des Vorjahres (Ordner mit WI_/WT_/WR_-Dateien) – bevorzugt
  - Rangliste als PDF bzw. die beigelegte Text-Fassung 2025 (`pdftotext -layout`)
"""
import os
import re
import subprocess

from .db import BASE_DIR, get_db

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
