# Changelog

Alle wesentlichen Änderungen an DEBRA-Web.

## [Unveröffentlicht]
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
