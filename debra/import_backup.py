"""Import eines DEBRA-Backups (Text-Export-Format) in die Web-App.

Das Backup besteht aus ;-getrennten CSV-Dateien in CP1252/CRLF:
  WT_VERE.txt        Vereine (Verein_Code; Verein; VereinZusatz; Verband)
  WI_<nr>.txt        Wettkampf-/Kategorie-Definitionen je WettkampfNr
  WT_<nr>.txt        Teilnehmer/Anmeldungen je WettkampfNr
  WR_<nr>.txt        Resultate je WettkampfNr (Note/Wert/Rang je Disziplin)
  WT_ZEIT / WT_ADR   Zeitplan / Adressen (optional)

Aufruf:  python -m debra.import_backup /pfad/zum/Backup
"""

import csv
import glob
import os
import re
import sys

from .db import DB_PATH, get_db, init_db

SPARTE_TITEL = {
    "Knaben": "Leichtathletik – Knaben",
    "Mädchen": "Leichtathletik – Mädchen",
    "Turner": "Leichtathletik – Turner",
    "Turnerinnen": "Leichtathletik – Turnerinnen",
}


def _read_csv(pfad):
    """Liest eine DEBRA-Exportdatei als Liste von dicts (CP1252, ;-getrennt)."""
    with open(pfad, encoding="cp1252", newline="") as f:
        text = f.read()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.DictReader(text.splitlines(), delimiter=";", quotechar='"')
    return list(reader)


def _num(v):
    v = (v or "").strip()
    if v in ("", "-1"):
        return None
    try:
        f = float(v.replace(",", "."))
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def _sparte_zu_geschlecht(sparte):
    s = (sparte or "").lower()
    if s.startswith("knaben") or s.startswith("turner") and "innen" not in s:
        return "m"
    if "mädchen" in s or "turnerinnen" in s:
        return "w"
    return None


def importieren(backup_dir, reset=True):
    if not os.path.isdir(backup_dir):
        # evtl. wurde der übergeordnete Ordner angegeben
        cand = os.path.join(backup_dir, "Backup")
        if os.path.isdir(cand):
            backup_dir = cand
        else:
            raise FileNotFoundError(f"Ordner nicht gefunden: {backup_dir}")

    init_db()
    conn = get_db()
    cur = conn.cursor()

    if reset:
        for t in ["resultat", "teilnehmer", "kategorie_disziplin", "kategorie",
                  "zeitplan", "disziplin", "verein", "wettkampf", "einstellung"]:
            cur.execute(f"DELETE FROM {t}")
        # AUTOINCREMENT-Zähler zurücksetzen
        cur.execute("DELETE FROM sqlite_sequence")

    bericht = {"vereine": 0, "wettkaempfe": 0, "kategorien": 0,
               "teilnehmer": 0, "resultate": 0}

    # ---- Vereine -------------------------------------------------------- #
    verein_by_key = {}      # (name, zusatz, verband) -> id
    verein_by_name = {}     # name -> id (Fallback)
    vere_pfad = os.path.join(backup_dir, "WT_VERE.txt")
    if os.path.exists(vere_pfad):
        for row in _read_csv(vere_pfad):
            name = (row.get("Verein") or "").strip()
            if not name:
                continue
            zusatz = (row.get("VereinZusatz") or "").strip()
            verband = (row.get("Verband") or "").strip()
            code = (row.get("Verein_Code") or "").strip()
            cur.execute(
                "INSERT INTO verein(nummer, name, zusatz, verband) VALUES(?,?,?,?)",
                (code, name, zusatz, verband))
            vid = cur.lastrowid
            verein_by_key[(name, zusatz, verband)] = vid
            verein_by_name.setdefault(name, vid)
            bericht["vereine"] += 1

    def verein_finden(name, zusatz, verband):
        name = (name or "").strip()
        if not name:
            return None
        for key in [(name, (zusatz or "").strip(), (verband or "").strip()),
                    (name, (zusatz or "").strip(), "")]:
            if key in verein_by_key:
                return verein_by_key[key]
        if name in verein_by_name:
            return verein_by_name[name]
        # unbekannten Verein anlegen
        cur.execute("INSERT INTO verein(name, zusatz, verband) VALUES(?,?,?)",
                    (name, zusatz, verband))
        vid = cur.lastrowid
        verein_by_key[(name, (zusatz or "").strip(), (verband or "").strip())] = vid
        verein_by_name.setdefault(name, vid)
        return vid

    # ---- Wettkämpfe (WI/WT/WR je Nummer) -------------------------------- #
    wi_dateien = sorted(glob.glob(os.path.join(backup_dir, "WI_*.txt")))
    zuerst = True
    for wi_pfad in wi_dateien:
        m = re.search(r"WI_(\d+)\.txt$", wi_pfad)
        if not m:
            continue
        nr = int(m.group(1))
        wi_rows = _read_csv(wi_pfad)
        if not wi_rows:
            continue
        sparte = (wi_rows[0].get("Sparte") or "").strip()
        titel = SPARTE_TITEL.get(sparte, f"Wettkampf {nr}" + (f" – {sparte}" if sparte else ""))

        cur.execute("INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,?)",
                    (titel, "", "", 1 if zuerst else 0))
        wk_id = cur.lastrowid
        zuerst = False
        bericht["wettkaempfe"] += 1

        # Kategorien (= Disziplinen/Events dieses Wettkampfs)
        kat_id_by_nr = {}
        disz_id_by_kat = {}
        for i, row in enumerate(wi_rows):
            kat_nr = _num(row.get("KategorieNr"))
            bez = (row.get("Bezeichnung") or "").strip()
            abk = (row.get("Abkürzung") or row.get("Abk\u00fcrzung") or "").strip()
            if kat_nr is None or not bez:
                continue
            gesch = _sparte_zu_geschlecht(sparte) or "alle"
            cur.execute(
                "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, typ, geschlecht, "
                "streich, kranz_modus, kranz_wert, sortierung, sparte, kat_nr) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (wk_id, abk, bez, "einzel", gesch, 0, "keiner", 0.0, i, sparte, kat_nr))
            kid = cur.lastrowid
            kat_id_by_nr[kat_nr] = kid
            bericht["kategorien"] += 1
            # eine Disziplin je Event, damit Resultate erfasst werden können
            cur.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)",
                        (abk or bez[:6], bez, sparte, "Note"))
            did = cur.lastrowid
            cur.execute("INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) VALUES(?,?,?)",
                        (kid, did, 1))
            disz_id_by_kat[kid] = did

        # Teilnehmer/Anmeldungen
        wt_pfad = os.path.join(backup_dir, f"WT_{nr}.txt")
        startnr_to_tid = {}
        if os.path.exists(wt_pfad):
            for row in _read_csv(wt_pfad):
                startnr = _num(row.get("StartNr"))
                kat_nr = _num(row.get("KategorieNr"))
                kid = kat_id_by_nr.get(kat_nr)
                if kid is None:
                    continue
                verein = (row.get("Verein") or "").strip()
                zusatz = (row.get("VereinZusatz") or "").strip()
                verband = (row.get("Verband") or "").strip()
                vid = verein_finden(verein, zusatz, verband)
                gesch = _num(row.get("Geschlecht"))
                gesch = {1: "m", 2: "w"}.get(gesch)
                cur.execute(
                    "INSERT INTO teilnehmer(wettkampf_id, startnr, vorname, nachname, jahrgang, "
                    "geschlecht, verein_id, verein_zusatz, verband, gruppennr, kategorie_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (wk_id, startnr, (row.get("Vorname") or "").strip() or None,
                     (row.get("Name") or "").strip() or None, _num(row.get("Jahrgang")),
                     gesch, vid, zusatz, verband, _num(row.get("GruppenNr")), kid))
                tid = cur.lastrowid
                startnr_to_tid[startnr] = (tid, kid)
                bericht["teilnehmer"] += 1

        # Resultate (nur echte Werte übernehmen)
        wr_pfad = os.path.join(backup_dir, f"WR_{nr}.txt")
        if os.path.exists(wr_pfad):
            for row in _read_csv(wr_pfad):
                startnr = _num(row.get("StartNr"))
                if startnr not in startnr_to_tid:
                    continue
                tid, kid = startnr_to_tid[startnr]
                # Position 1 = das Event dieser Kategorie
                note = _num(row.get("Note1"))
                wert = _num(row.get("Wert1"))
                if note not in (None, 0) or wert not in (None, 0):
                    cur.execute(
                        "INSERT INTO resultat(teilnehmer_id, position, note, wert) VALUES(?,?,?,?) "
                        "ON CONFLICT(teilnehmer_id, position) DO UPDATE SET note=excluded.note, wert=excluded.wert",
                        (tid, 1, note, wert))
                    bericht["resultate"] += 1
                total = _num(row.get("Total"))
                rang = _num(row.get("Rang"))
                ausz = _num(row.get("Auszeichnung"))
                if total not in (None, 0) or rang not in (None, 0):
                    cur.execute(
                        "UPDATE teilnehmer SET total_off=?, rang_off=?, ausz_off=? WHERE id=?",
                        (total, rang, 1 if ausz else 0, tid))

    conn.commit()
    conn.close()
    return bericht


if __name__ == "__main__":
    pfad = sys.argv[1] if len(sys.argv) > 1 else "Backup"
    b = importieren(pfad, reset=True)
    print("Import abgeschlossen in", DB_PATH)
    for k, v in b.items():
        print(f"  {k:12} {v}")
