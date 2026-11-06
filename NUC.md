# Intel NUC (NUC5PGYH) – eigenständiger Wettkampf-Server

Der NUC wird zum Server fürs Wettkampfnetz: Die PCs hängen per Kabel (über einen Switch)
am NUC, der NUC verteilt die IP-Adressen (DHCP) und stellt die Auswertung bereit. Ins Internet
geht der NUC selbst über WLAN (z. B. Handy-Hotspot).

```
 PCs ──Kabel── Switch ──Kabel── LAN [Intel NUC] WLAN ~~~ Hotspot/Router ── Internet
                                192.168.50.1
                                DHCP + DNS (dnsmasq), Caddy, App (Docker), Ubuntu Server 24.04
```

| Zugriff von …                            | Adresse                           | Passwort |
|------------------------------------------|-----------------------------------|----------|
| Wettkampfnetz (Kabel, 192.168.50.0/24)   | `http://192.168.50.1` / `http://tsst.lan` | nein |
| WLAN-Netz des NUC                        | `http://<WLAN-IP des NUC>`        | ja       |
| Internet über Tailscale Funnel           | `https://tsst.<tailnet>.ts.net`   | ja       |
| Internet über DuckDNS (nur mit Portweiterleitung) | `https://<name>.duckdns.org` | ja |

- Die PCs im Wettkampfnetz bekommen **kein Standard-Gateway**, kommen über den NUC also nicht
  ins Internet.
- Die App lauscht nur auf `127.0.0.1:5000`. Erreichbar ist sie ausschliesslich über Caddy,
  deshalb lässt sich der Passwortschutz nicht umgehen. Für den Zugriff von aussen fragt der
  Browser nach Benutzer und Passwort (Basic Auth), danach folgt die normale Rollenwahl.

## 1. Installationskarte erstellen (Windows)
`nuc\sd-karte-erstellen.ps1` mit Rechtsklick → *Mit PowerShell ausführen* starten. Das Skript:
- fordert Administratorrechte an und fragt nach Benutzer/Passwort, WLAN(s), dem Passwort für
  den Zugriff von aussen sowie optional nach DuckDNS und Tailscale,
- lädt Ubuntu Server 24.04 LTS herunter (ca. 3 GB) und prüft die Prüfsumme,
- formatiert die SD-Karte bzw. den USB-Stick (8 GB FAT32) und kopiert den Installer darauf,
- legt die automatische Installation und die TSST-Einrichtung dazu.

> ⚠️ Die Karte installiert **ohne Rückfrage** und löscht die interne Disk **jedes** Rechners,
> der von ihr bootet. Sie enthält zudem die Passwörter. Nach Gebrauch löschen oder sicher aufbewahren.

## 2. Installation auf dem NUC
1. Im BIOS (F2) prüfen: *Boot → Secure Boot* darf an bleiben. Unter *Boot Devices* müssen
   USB bzw. SD-Karte erlaubt sein.
2. Karte einstecken, einschalten, **F10** (Boot-Menü) drücken und die Karte wählen. Nach
   10 Sekunden startet der Eintrag „TSST: Ubuntu automatisch …“.
3. Ubuntu wird auf die interne Disk installiert. Ist eine interne SATA-SSD vorhanden, kommt
   Ubuntu dorthin, sonst auf den eingebauten eMMC-Speicher. SD-Karten und USB-Laufwerke werden
   nie gewählt. Dauer etwa 15–30 Minuten, danach **schaltet der NUC aus**.
4. **Karte entfernen** und den NUC einschalten. Die TSST-Einrichtung läuft automatisch
   (Docker, App, DHCP, Caddy, DuckDNS/Tailscale) und braucht dafür Internet über WLAN.
   Alternativ geht es vorübergehend auch per Kabel am Heimrouter: Das Kabelnetz wird erst
   ganz am Schluss auf 192.168.50.1 umgestellt.
5. Fortschritt am Bildschirm des NUC verfolgen (anmelden, dann
   `sudo journalctl -fu tsst-setup`) oder per `ssh <benutzer>@tsst.local`.

Bootet der NUC nicht von der SD-Karte, erstellst du das Gleiche mit dem Skript auf einem
**USB-Stick** (mind. 8 GB).

## Zugriff von aussen
**Über einen Handy-Hotspot** (oder ein fremdes WLAN) ist keine Portweiterleitung möglich,
meist ist zusätzlich CGNAT im Spiel. **DuckDNS funktioniert dort nicht.** Dafür gibt es
**Tailscale Funnel** (gratis):
1. Ein Konto auf <https://tailscale.com> anlegen.
2. Im Admin-Bereich unter *DNS* **HTTPS-Zertifikate** aktivieren und **Funnel** erlauben
   (*Access controls*).
3. Unter *Settings → Keys* einen **Auth-Key** erzeugen und beim Erstellen der Karte angeben.
4. Die Adresse `https://tsst.<dein-tailnet>.ts.net` zeigt `sudo tsst-status`.

**DuckDNS** lohnt sich nur an einem WLAN-Router, den du selbst einstellen kannst, mit
öffentlicher IPv4-Adresse und einer Portweiterleitung von 80 und 443 auf die WLAN-IP des NUC.
Caddy holt dann automatisch ein Let's-Encrypt-Zertifikat.

## Betrieb
| Befehl              | Zweck |
|---------------------|-------|
| `sudo tsst-status`  | IP-Adressen, Container, verteilte DHCP-Adressen, Funnel-URL |
| `sudo tsst-update`  | neues App-Image laden und neu starten (braucht Internet) |
| `sudo bash /opt/tsst-install/setup.sh` | Einrichtung wiederholen (z. B. nach Änderung von `/etc/tsst/tsst.conf`) |

- Datenbank: `/opt/tsst/data/debra.sqlite3`. Zum Sichern z. B.
  `scp <benutzer>@tsst.local:/opt/tsst/data/debra.sqlite3 .`
- WLAN ändern: `/etc/netplan/50-cloud-init.yaml` anpassen, dann `sudo netplan apply`.
- Nach der Einrichtung läuft alles **auch ohne Internet**, die App startet mit jedem Boot.
