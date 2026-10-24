# Changelog

Alle wesentlichen Änderungen an DEBRA-Web.

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
