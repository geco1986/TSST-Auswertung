# Changelog

Alle wesentlichen Änderungen an DEBRA-Web.

## [Unveröffentlicht]
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
