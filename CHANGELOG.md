# Changelog

Alle wesentlichen Änderungen an DEBRA-Web.

## [Unveröffentlicht]
- Intel NUC als eigenständiger Wettkampf-Server (`nuc/`, Anleitung `NUC.md`): Installationskarte
  per Skript (Ubuntu Server 24.04 autoinstall auf die interne Disk), DHCP-Server im Kabelnetz
  (ohne Passwort), Zugriff über WLAN/Internet nur mit Passwort (Caddy), DuckDNS-Updater und
  optional Tailscale Funnel.

## [0.7.6] – 2026-11-25
- Anlass-Jahr einstellbar: Datum und Ort beim Anlegen von JTSST und JET wählbar, der Name erhält das Jahr
  aus dem Datum („… WTU 2027“). Ändert man im Reiter „Anlass“ nur das Datum, zieht das Jahr im Namen mit.
  „WKB anwenden“ und der Backup-Import behalten das eingestellte Jahr bzw. erkennen JTSST/JET jahresunabhängig.
- Mehrplatzbetrieb: Raster-, Schnell-, Stafetten- und JET-Erfassung speichern nur geänderte Felder. Hat
  jemand anders den Wert inzwischen geändert, wird nicht überschrieben, sondern ein Konflikt gemeldet.
- Rolle Chef mit Passwort, optionale Eingeber-PIN (Einstellungen → Allgemein → Passwörter).
- Vier-Augen-Kontrolle: eigene Eingaben nicht quittierbar; jede spätere Änderung setzt die Kontrolle zurück.
- Nach „Disziplin abschliessen“ bzw. WKL-Freigabe können nur noch Chef/Superuser Resultate ändern;
  eine Änderung setzt „Rangliste gedruckt“ zurück.
- Eingaben werden auf dem Server geprüft: ungültige Zahlen/Zeiten mit Meldung statt still verworfen,
  Werte ausserhalb der Plausibilität mit Warnung, doppelte Startnummern abgelehnt.
- Lückenloses Änderungsprotokoll für Teilnehmende (alle Felder, Nachmeldung, Löschen, Vermerke) und
  Stafetten (alter Wert, Übergabefehler, Löschen).
- Datensicherung: Download über die SQLite-Sicherungsfunktion (inkl. WAL, vorher konnten neueste
  Eingaben fehlen), nur Chef/Superuser; automatische Sicherung alle 15 Minuten nach `sicherungen/`.
- Sicherheit: Schutz vor fremden Formular-Absendungen (Origin-Prüfung), Login-Weiterleitung nur auf eigene
  Seiten, „Wettkampf aktivieren“ nur per Formular, zufälliges Session-Secret statt festem Schlüssel.
- Löschschutz: Vereine, Kategorien und Disziplinen, die noch verwendet werden, lassen sich nicht löschen.
- Seilziehen: Auszeichnungsregel wird nur von „Beste X %“ auf ganze Runden umgestellt; Eingabe leeren nur Chef.
- Behoben: Absturz bei `/liste/abschluss/xlsx`, Serverfehler bei Buchstaben im Kategorie-Formular,
  Absturz der Korrektur-Seite bei Sektionswertung.
- Automatische Tests (`tests/`).

## [0.7.5] – 2026-11-02
- Einsatzplan (Menü „Einsatzplan“, für TSST, JTSST und JET): Anlagen und Minuten je Turner:in werden je
  Disziplin gepflegt und gelten für alle Kategorien, Knaben und Mädchen gemeinsam (0 Anlagen = Disziplin
  nicht im Plan). Bisherige Werte je Kategorie werden als Vorgabe übernommen; unter Einstellungen bleibt
  nur noch die Plausibilität (Warn min/max).
- „Zeit je Gruppe“ für Gruppenvorführungen (JET Gymnastik vorbelegt): die Minuten gelten je Gruppe/Riege
  statt je Turner:in.
- „Verteilen“ je Disziplin (nur nicht schätzbare mit mehreren Anlagen; beim JET vorbelegt): eine Riege wird
  gleichzeitig auf alle Anlagen aufgeteilt, z. B. Klettern – der Verein turnt miteinander.
- Schätzbare Disziplinen (Häkchen, beim JET für die Geräte vorbelegt): jede Kategorie bleibt den ganzen Tag
  auf derselben Anlage (gleiche Wertungsrichter:innen); die Kategorien werden nach Belastung auf die
  Anlagen verteilt.
- Ablösungen (1–4, JET: 2) mit Startzeit je Ablösung (leer = direkt anschliessend). Die Vereine werden so
  verteilt, dass die Ablösungen gleich gross sind; Knaben und Mädchen eines Vereins sind immer in derselben
  Ablösung. Einteilung je Verein manuell änderbar, „Ablösungen automatisch ausgleichen“ verteilt neu.
- JET: Riegen je Verein (Knaben bzw. Mädchen, „Max. Riegengrösse“ einstellbar, Vorgabe 16, nach Kategorie
  sortiert) besuchen miteinander alle Disziplinen ihres Programms; bei schätzbaren Disziplinen turnen die
  Kategorien einer Riege gleichzeitig, jede auf ihrer festen Anlage.
- Einsatzplan-Listen (PDF/Excel, nach Anlage oder Verein) mit Ablösung, Zeit von–bis, Kategorie, Anzahl und
  Start-Nr.; Übersicht der Belegung je Anlage auf der Seite.

## [0.7.4] – 2026-11-01
- JTSST Seilziehen im K.-o.-System (Menü „Seilziehen“) mit so vielen Runden wie möglich (1/32-, 1/64-Final …):
  höchstens ein Freilos (1. Runde bei ungerader Anzahl), bei ungerader Anzahl Sieger kommt ein Lucky Loser
  weiter, bis 4 Gruppen in den Halbfinals stehen – z. B. 51 Gruppen: 25 Züge + Freilos → 13 Züge + Lucky Loser
  → 7 Züge + Lucky Loser → 1/4-Final (passt zur Rangliste 2026).
- Einteilung: Gruppe 1 je Verein nach Vorjahr gesetzt – die beste erhält das Freilos, die Gesetzten treffen
  erst spät aufeinander; 2. Gruppen nie gesetzt. Gruppen desselben Vereins treffen so spät wie möglich
  aufeinander (2 Gruppen frühestens im Final, 3–4 frühestens im Halbfinal …). Ältere Einteilungen ohne
  Resultate werden automatisch erneuert. Automatisch auslosen, manuell anpassbar.
- Turnierbaum zum Ausdrucken (A4, je Kategorie ein Blatt oder alle zusammen) mit Start-Nr. und Verein,
  Feldern für Lucky Loser, Spiel um Platz 3 und Rangierung 1.–4. zum Ausfüllen.
- Eingabe nach Blatt: je Gruppe die erreichte Runde (nur die Runden, die es bei der Teilnehmerzahl gibt);
  Ausgeschiedene einer Runde teilen sich den Platz, Hinweis bei abweichender Anzahl je Runde.
- Auszeichnung „Beste X %, ganze Runden“: so viele ganze Runden, dass der Anteil (30 %) nicht überschritten
  wird – wie in der Rangliste 2026 (z. B. 38 Gruppen: 11 Auszeichnungen).
- JTSST Selektion automatisch: Serien der Pendelstafette und Seilziehen-Tableau teilt das Tool selbst ein –
  nach dem Import der Anmeldungen, nach dem Import des Vorjahres und beim Öffnen der Seiten (solange noch
  nichts eingeteilt ist). Kategorien mit erfassten Resultaten bleiben unverändert. „Alle neu einteilen“ unter
  Stafetten → Selektion & Bahnen; dort erscheinen beim JTSST auch die Seilziehen-Kategorien.
- JTSST Vorjahres-Rangliste: Import der Gesamt-Rangliste als PDF (Einstellungen → JTSST → Import) für
  Pendelstafette, Hindernislauf, Schwedenstafette und Seilziehen; TSST- und JTSST-Vorjahr ersetzen sich
  nicht mehr gegenseitig.
- Serieneinteilung Pendelstafette (TSST PS80 und JTSST): Vorjahresbeste laufen in der letzten Serie; gesetzt
  wird nur mit dem Vorjahresresultat der Gruppe 1 eines Vereins, nie mit dem einer 2. Gruppe. Vorjahr als
  Spalte in „Bahnen & Serien“.

## [0.7.3] – 2026-10-24
- Trennung nach Sparte auch bei Teilnehmer, Top-Leistungen und Stafetten (Selektion & Bahnen).
- Ranglisten-Übersicht ohne Stern-Symbol in den Kacheln.
- Kacheln auf allen Seiten deutlich kompakter (kleinere Abstände/Schrift, Symbol neben dem Titel).

## [0.7.2] – 2026-10-24
- Optische Trennung nach Sparte (Turnerinnen/Turner, Mädchen/Knaben) in der Erfassung, den
  Ranglisten, auf der Übersicht und in der Erfassungskontrolle – eigener Block bzw. Zwischenzeile
  mit Farbe je Sparte.

## [0.7.1] – 2026-10-24
- Alle Importe per Upload im Browser (Dateien oder ZIP): DEBRA-Backup TSST, Excel TSST + JTSST,
  JTSST-Anmeldungen, JET-Anmeldungen (Backup, Excel, Startliste-PDF) und Vorjahr. Uploads liegen
  neben der Datenbank unter `uploads/` und werden nach 14 Tagen aufgeräumt. Pfade auf dem Server
  funktionieren weiterhin.

## [0.7.0] – 2026-10-24
- Versionsnummer unten links in der Seitenleiste.
### Hinzugefügt (JET – Jugend-Einzelturntag)
- Dritter Anlass „JET“ im Umschalter oben rechts (WKB JET 2026, 05.07.2026 Rheinau): Mädchen/Knaben
  Kat. A–C (6-Kampf) und D/E (4-Kampf), Geräte, Leichtathletik und Plausch frei wählbar (`debra/jet.py`).
- Die drei Anlässe sind für die Eingabe klar getrennt: eigene Farbe je Anlass (TSST oliv, JTSST petrol,
  JET violett), Anlass-Band über jeder Seite, Navigation je Anlass, Startnummern nur im gewählten Anlass.
- JET-Erfassung: Raster je Kategorie, Verein (Riege), Disziplin (Posten) oder Startnummer; Geräte als
  Note, LA/Plausch als Messwert – Note, Streichresultat, „falsche Disziplin“ (Note 6) und Total live.
- Wertungstabelle pflegbar (Seite „Wertungstabelle“): Note je Kategorie A–E, lineare Interpolation,
  Vorlagen „WKB-Tabelle 2026“ und „DEBRA-Formeln“; erfasste Noten werden beim Speichern neu berechnet.
- JET-Import mit Prüfschritt: DEBRA-Backup (WT_/WR_, inkl. Startnummern, Abmeldungen, Resultate),
  Anmelde-Export JR_JET.xls/MR_JET.xls (Kategorie aus dem Jahrgang) oder DEBRA-Startliste (PDF).
- JET-Ranglisten (Bildschirm, PDF modern/klassisch) mit Wert (Note) je Disziplin; gleiches Total =
  gleicher Rang, Auszeichnung 30 % der Rangierten. Abgeglichen mit der Rangliste JET 2026
  (430 von 432 Totalen identisch mit DEBRA-Formeln).
- TSST-/JTSST-Importe und „WKB anwenden“ lassen den JET unangetastet.
- JET-Einzelerfassung: Startnummer eingeben -> Disziplinen untereinander (Geräte, LA, Plausch),
  Enter springt nach unten, „Nächste Startnummer“ speichert und lädt die nächste Person.
- Einstellungen auf einer Seite mit Reitern: Allgemein, TSST, JTSST, JET; je Anlass Unterreiter
  (Anlass, Auszeichnungen, Stafetten, Zeitplan & Plausibilität, Wertungstabelle, Import). Speichern und
  „Anteil auf alle Kategorien“ wirken nur noch auf den gewählten Anlass.
- JET-Wertung über Formeln: je Disziplin, Sparte und Kategorie eine Formel (x = Messwert); beim
  Speichern wird daraus die Wertungstabelle erzeugt (Note 10.00 … 6.00), erfasste Noten werden neu
  berechnet. Formeln werden geprüft (nur Zahlen, x, + - * / ^, Klammern; Note muss in eine Richtung
  verlaufen). Standard = DEBRA-Formeln (wie Rangliste 2026).
- Rolle Superuser (mit Passwort, beim ersten Login festzulegen): wählt den aktiven Anlass, legt
  Wettkämpfe an/löscht sie und pflegt die JET-Wertungsformeln. Der Chef bearbeitet nur den aktiven
  Anlass (Einstellungen, Kategorien). Importe (DEBRA-Backup, Excel, JTSST, JET, Vorjahr) und das
  Anlegen von JTSST/JET kann nur der Superuser.
- JET-Schnellerfassung als eigener Menüpunkt (wie TSST/JTSST): grosses Startnummernfeld, Disziplinen
  untereinander; Erfassung mehrerer Personen unter „Nach Kategorie / Riege“.
- Ranglisten-Übersicht mit Status je Rangliste (Eingabe, Kontrolliert, Gedruckt, WKL). „Gedruckt“ ist
  erst möglich, wenn alle Teilnehmenden ein Resultat oder einen Vermerk haben (auch der HTML-Druck
  markiert erst dann); die Markierung lässt sich zurücknehmen. Vor dem Druck der Gesamt-Rangliste
  Warnung mit Liste der noch nicht kontrollierten bzw. nicht freigegebenen Ranglisten.
- Kontrollblatt (alle Anlässe): nur noch die Startnummer statt Verein/Name; beim JET stehen die
  Disziplinen als Spaltenköpfe und der erfasste Messwert wird gezeigt.

### Hinzugefügt (Import)
- Ordner-Import der Anmeldungen (Einstellungen → „Ordner prüfen“, Standard `Inputs\Import`):
  erkennt TSST-Anmeldezahlen (TU/TI) und JTSST-Gesamtübersicht (Knaben/Mädchen) am Inhalt,
  zeigt je Sparte Gruppen und Abgleich mit der Total-Zeile, sichert die DB und ersetzt die Anmeldungen.
- TSST-Disziplinen (Turner 10, Turnerinnen 9) werden ohne DEBRA-Backup angelegt (`debra/tsst.py`).
- Kommandozeile: `python -m debra.excel_import [Ordner] [--ja]`.

### Hinzugefügt (Listen)
- Alle druckbaren Listen im modernen Layout als PDF und als Excel (.xlsx): Startlisten (Verein,
  Disziplin, Startnummer), Statistik, Einsatzplan, Kranzliste, Top-Leistungen, Kontrollblatt,
  Vereinsblatt, Ranglisten, Notenblätter, Serienpläne, Abschlussblatt.
- Bei jeder Druckoption: Vorschau (Fenster), PDF-Download und Excel-Download.
- Vereinsblatt neu nach Sparte, Disziplin und Kategorie (Stafetten korrekt gewertet).

### Hinzugefügt (Ranglisten-PDF)
- Ranglisten als PDF, einzeln je Disziplin und als Gesamt-Rangliste aller Disziplinen.
  Gestaltung „Modern“ (Standard: Schrift Barlow/OFL, Podest-Medaillen, Auszeichnungsgrenze,
  A-/B-Final-Etiketten, bestes Einzelresultat hervorgehoben, Seitenzahl je Disziplin) oder
  „Klassisch“ wie die offiziellen Ranglisten 2026 (TSST oliv, JTSST petrol).
- Reihenfolge der Sparten/Disziplinen einstellbar (gilt überall), Auswahl je Disziplin.
- Gesamt-Rangliste wahlweise „je Disziplin neue Seite“ oder „fortlaufend“ (durchgehende Seitenzahlen;
  bei Zusatzblättern beginnt eine neue Seite).
- Zusatzblätter (Deckblatt, Sponsoren, Fundbüro …) als PDF hochladen und an beliebiger Stelle einfügen.
- Umschalter TSST/JTSST oben rechts; alle Seiten ausser der Konfiguration zeigen nur den gewählten Anlass.

### Geändert (abgeglichen mit den offiziellen DEBRA-Resultaten TSST 2026)
- Durchschnitte wie DEBRA gerundet: Zeiten auf-, Weiten/Höhen auf Hundertstel abgerundet.
- Gleichstand: Einzelleistungen der Reihe nach vergleichen (beste, zweitbeste, …);
  Stafetten-Finals teilen bei gleicher Zeit den Rang.
- Auszeichnungen: 30 % der Anmeldungen bei Meldeschluss (Excel-Import), aufgerundet;
  Basis je Disziplin einstellbar (Anmeldungen/Rangierte).
- Neuer Vermerk „Abgemeldet“ (nicht in Ranglisten/Startlisten, zählt zur Preisbasis).
- DEBRA-Backup-Import: alle Einzelwerte, Nuller/nicht gestartet, Vermerke, Abmeldungen,
  Stafettenzeiten inkl. A-/B-Final; WKB wird direkt angewendet; JTSST bleibt erhalten.
- Excel-Import: auch .xls und Anmeldezahlen-Format (Zusatz im Vereinsnamen);
  Jugend-Gruppen werden nicht mehr gelöscht; Startnummern Turner ab 1, Turnerinnen ab 501.
- Vorjahr (Bahneneinteilung) direkt aus dem DEBRA-Final-Backup.
- JTSST-Disziplinen mit Kürzel, Bezeichnung und KategorieNr aus dem DEBRA-Backup.

### Hinzugefügt
- Containerisierung (Docker/Compose) inkl. TrueNAS-Anleitung und GHCR-Workflow.
- Automatische DB-Migration beim Start (ergänzt fehlende Spalten/Tabellen ohne Datenverlust).
- Sortierbare Listen/Ranglisten (inkl. korrekter Zeit-Sortierung).
- Manuelle Korrektur von Rang/Total/Status je Gruppe vor Erstellung der Rangliste.
- Ranglisten-Status (Alles eingegeben / Eingabe kontrolliert / Gedruckt / Fertig WKL).
- Vier-Augen-Kontrolle mit Kontrollblatt (nach Erfasser-Kennung) und lokalem Backup.
- Einsatzplan-Generator (Vormittag) ohne Vereins-Parallelität.
- Excel-Import der Anmeldungen (Verein/Zusatz/Verband) mit Prüfschritt.
- Druck/PDF: Titel je Seite mit Anlass + Datum, A4-Seitenumbrüche, Serienplan quer.
- Statistik mit Auszeichnungen bei 30/33/40 %.

## Grundfunktionen
- Erfassung (Schnellerfassung, Raster), Wertung nach WKB, Stafetten mit A/B-Final,
  Bahnen-/Serieneinteilung nach Vorjahr, Ranglisten, Kranzliste, Notenblätter,
  Startlisten, Rollen (Eingeber/Chef).
