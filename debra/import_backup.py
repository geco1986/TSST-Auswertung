"""Import eines DEBRA-Backups (Text-Export-Format) in die Web-App.

Das Backup besteht aus ;-getrennten CSV-Dateien in CP1252/CRLF:
  WT_VERE.txt        Vereine (Verein_Code; Verein; VereinZusatz; Verband)
  WI_<nr>.txt        Wettkampf-/Kategorie-Definitionen je WettkampfNr
  WT_<nr>.txt        Teilnehmer/Anmeldungen je WettkampfNr
  WR_<nr>.txt        Resultate je WettkampfNr (Wert/Note/Rang je Mitglied 1..20)
  WT_ZEIT / WT_ADR   Zeitplan / Adressen (optional, nicht importiert)

DEBRA-Kodierung (geprüft am Final-Backup TSST 2026):
  - negative StartNr          = abgemeldete Gruppe (Status 10)
  - Wert -1                   = Mitglied nicht gestartet; Wert 0 = Nuller (zählt mit)
  - Bemerkung AK/NGes/Aufg/…  = Vermerk; Rang 30000/30200 = nicht rangiert
  - Stafetten: ein Wert = Zeit; 4x100m: Rang 1–8 A-Final, 9–16 B-Final (Turner),
    Total ist bei Finalisten die Finalzeit

Jugend-Sparten (Knaben/Mädchen, Jugendwettkampf Knaben/Mädchen) werden übersprungen:
JTSST und JET werden über ihren eigenen Import gepflegt und bleiben unangetastet.

Aufruf:  python -m debra.import_backup /pfad/zum/Backup
"""

import csv
import glob
import os
import re
import sys

from .db import DB_PATH, get_db, init_db

SPARTE_TITEL = {
    "Turner": "Leichtathletik – Turner",
    "Turnerinnen": "Leichtathletik – Turnerinnen",
}
JUGEND = ("Knaben", "Mädchen", "Jugendwettkampf Knaben", "Jugendwettkampf Mädchen")

# Bemerkung in WR -> Vermerk der Web-App
BEMERKUNG_STATUS = {"ak": "ak", "nges": "nges", "aufg": "aufg", "disq": "disq", "unfall": "unfall"}
STATUS_ABGEMELDET = 10
NICHT_RANGIERT = (0, 30000, 30200)


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


def _status(t_row, r_row, startnr_roh):
    """Vermerk aus Bemerkung bzw. DEBRA-Status; negative StartNr = abgemeldet."""
    bem = ((r_row or {}).get("Bemerkung") or "").strip().lower().rstrip(".")
    if bem in BEMERKUNG_STATUS:
        return BEMERKUNG_STATUS[bem]
    if startnr_roh < 0 or _num(t_row.get("Status")) == STATUS_ABGEMELDET:
        return "abgem"
    return None


def _werte(r_row):
    """Liste der Mitglieder-Werte (None = nicht gestartet) ohne leere Positionen."""
    werte = []
    for i in range(1, 21):
        if (r_row.get(f"DisziplinNr{i}") or "0").strip() == "0":
            continue
        roh = (r_row.get(f"Wert{i}") or "").strip()
        werte.append(None if roh in ("", "-1") else _num(roh) or 0)
    return werte


def importieren(backup_dir, reset=True):
    if not os.path.isdir(backup_dir):
        # evtl. wurde der übergeordnete Ordner angegeben
        cand = os.path.join(backup_dir, "Backup")
        if os.path.isdir(cand):
            backup_dir = cand
        else:
            raise FileNotFoundError(f"Ordner nicht gefunden: {backup_dir}")

    from .jet import EVENT_NAME as JET_NAME
    from .jtsst import EVENT_NAME as JTSST_NAME
    from .wkb import ist_stafette

    init_db()
    conn = get_db()
    cur = conn.cursor()

    if reset:
        # Alles ausser dem Jugendwettkampf ersetzen (Kategorien, Gruppen, Resultate
        # und Zeitplan hängen per ON DELETE CASCADE am Wettkampf). Vereine bleiben,
        # weil die JTSST-Gruppen auf sie verweisen.
        # Der JET (eigener Anlass) bleibt ebenfalls erhalten.
        cur.execute("DELETE FROM wettkampf WHERE name<>? AND name<>? AND id NOT IN "
                    "(SELECT wettkampf_id FROM kategorie WHERE sparte LIKE 'JET %')",
                    (JTSST_NAME, JET_NAME))
        cur.execute("DELETE FROM disziplin WHERE id NOT IN "
                    "(SELECT DISTINCT disziplin_id FROM kategorie_disziplin)")

    bericht = {"vereine": 0, "wettkaempfe": 0, "kategorien": 0,
               "teilnehmer": 0, "resultate": 0, "abgemeldet": 0, "uebersprungen": []}

    # ---- Vereine -------------------------------------------------------- #
    verein_by_key = {}      # (name, zusatz, verband) -> id
    verein_by_name = {}     # name -> id (Fallback)
    for v in cur.execute("SELECT id, name, zusatz, verband FROM verein ORDER BY id"):
        verein_by_key.setdefault((v["name"], v["zusatz"] or "", v["verband"] or ""), v["id"])
        verein_by_name.setdefault(v["name"], v["id"])

    def verein_finden(name, zusatz, verband, nummer=None):
        name = (name or "").strip()
        if not name:
            return None
        zusatz, verband = (zusatz or "").strip(), (verband or "").strip()
        for key in [(name, zusatz, verband), (name, zusatz, "")]:
            if key in verein_by_key:
                return verein_by_key[key]
        if name in verein_by_name:
            return verein_by_name[name]
        cur.execute("INSERT INTO verein(nummer, name, zusatz, verband) VALUES(?,?,?,?)",
                    (nummer, name, zusatz, verband))
        vid = cur.lastrowid
        verein_by_key[(name, zusatz, verband)] = vid
        verein_by_name.setdefault(name, vid)
        bericht["vereine"] += 1
        return vid

    vere_pfad = os.path.join(backup_dir, "WT_VERE.txt")
    if os.path.exists(vere_pfad):
        for row in _read_csv(vere_pfad):
            verein_finden(row.get("Verein"), row.get("VereinZusatz"), row.get("Verband"),
                          (row.get("Verein_Code") or "").strip() or None)

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
        if sparte in JUGEND:
            bericht["uebersprungen"].append(f"WI_{nr} ({sparte})")
            continue
        titel = SPARTE_TITEL.get(sparte, f"Wettkampf {nr}" + (f" – {sparte}" if sparte else ""))
        gesch = _sparte_zu_geschlecht(sparte) or "alle"

        cur.execute("INSERT INTO wettkampf(name, ort, datum, aktiv) VALUES(?,?,?,?)",
                    (titel, "", "", 1 if zuerst else 0))
        wk_id = cur.lastrowid
        zuerst = False
        bericht["wettkaempfe"] += 1

        # Kategorien (= Disziplinen/Events dieses Wettkampfs)
        kat_by_nr = {}
        for i, row in enumerate(wi_rows):
            kat_nr = _num(row.get("KategorieNr"))
            bez = (row.get("Bezeichnung") or "").strip()
            abk = (row.get("Abkürzung") or "").strip()
            if kat_nr is None or not bez:
                continue
            cur.execute(
                "INSERT INTO kategorie(wettkampf_id, abk, bezeichnung, typ, geschlecht, "
                "streich, kranz_modus, kranz_wert, sortierung, sparte, kat_nr) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (wk_id, abk, bez, "einzel", gesch, 0, "keiner", 0.0, i, sparte, kat_nr))
            kid = cur.lastrowid
            kat_by_nr[kat_nr] = {"id": kid, "bez": bez, "stafette": ist_stafette(bez),
                                 "4x100": "4x100" in bez.replace(" ", "").lower()}
            bericht["kategorien"] += 1
            # eine Disziplin je Event, damit Resultate erfasst werden können
            cur.execute("INSERT INTO disziplin(abk, bezeichnung, diszgruppe, einheit) VALUES(?,?,?,?)",
                        (abk or bez[:6], bez, sparte, "Note"))
            cur.execute("INSERT INTO kategorie_disziplin(kategorie_id, disziplin_id, position) VALUES(?,?,?)",
                        (kid, cur.lastrowid, 1))

        wr_pfad = os.path.join(backup_dir, f"WR_{nr}.txt")
        wr = {r["StartNr"]: r for r in _read_csv(wr_pfad)} if os.path.exists(wr_pfad) else {}

        # Teilnehmer/Anmeldungen inkl. Resultate
        wt_pfad = os.path.join(backup_dir, f"WT_{nr}.txt")
        if not os.path.exists(wt_pfad):
            continue
        for row in _read_csv(wt_pfad):
            kat = kat_by_nr.get(_num(row.get("KategorieNr")))
            roh = _num(row.get("StartNr"))
            if kat is None or roh is None:
                continue
            res = wr.get(row["StartNr"])
            status = _status(row, res, roh)
            zusatz = (row.get("VereinZusatz") or "").strip()
            verband = (row.get("Verband") or "").strip()
            vid = verein_finden(row.get("Verein"), zusatz, verband)
            gesch_t = {1: "m", 2: "w"}.get(_num(row.get("Geschlecht"))) or (
                gesch if gesch != "alle" else None)
            rang = _num(res.get("Rang")) if res else None
            rang = None if rang in NICHT_RANGIERT else rang
            total = _num(res.get("Total")) if res else None
            cur.execute(
                "INSERT INTO teilnehmer(wettkampf_id, startnr, vorname, nachname, jahrgang, "
                "geschlecht, verein_id, verein_zusatz, verband, gruppennr, kategorie_id, status, "
                "total_off, rang_off, ausz_off) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (wk_id, abs(roh), (row.get("Vorname") or "").strip() or None,
                 (row.get("Name") or "").strip() or None, _num(row.get("Jahrgang")),
                 gesch_t, vid, zusatz or None, verband or None, _num(row.get("GruppenNr")),
                 kat["id"], status, total or None, rang,
                 1 if res and (res.get("Auszeichnung") or "").strip() else 0))
            tid = cur.lastrowid
            bericht["teilnehmer"] += 1
            if status == "abgem":
                bericht["abgemeldet"] += 1
            if not res:
                continue

            werte = _werte(res)
            if not any(w is not None for w in werte):
                continue
            if kat["stafette"]:
                # Stafette: eine Teamzeit. 4x100m-Finalisten anhand des offiziellen Rangs.
                runde, gruppe = "final", None
                if kat["4x100"]:
                    if rang and rang <= 8:
                        gruppe = "A" if sparte == "Turner" else "F"
                    elif rang and rang <= 16 and sparte == "Turner":
                        gruppe = "B"
                    else:
                        runde = "vorlauf"
                cur.execute("INSERT INTO stafette(teilnehmer_id, runde, rohzeit) VALUES(?,?,?)",
                            (tid, runde, werte[0]))
                if gruppe:
                    cur.execute("UPDATE teilnehmer SET final_gruppe=? WHERE id=?", (gruppe, tid))
                bericht["resultate"] += 1
                continue
            for pos, wert in enumerate(werte, start=1):
                cur.execute(
                    "INSERT INTO resultat(teilnehmer_id, position, note, wert, status) VALUES(?,?,?,?,?)",
                    (tid, pos, wert, wert, None if wert is not None else "dns"))
                bericht["resultate"] += 1

    conn.commit()
    conn.close()
    return bericht


if __name__ == "__main__":
    pfad = sys.argv[1] if len(sys.argv) > 1 else "Backup"
    b = importieren(pfad, reset=True)
    print("Import abgeschlossen in", DB_PATH)
    for k, v in b.items():
        print(f"  {k:12} {v}")
