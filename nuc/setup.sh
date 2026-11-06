#!/bin/bash
# =====================================================================
# TSST-Auswertung – Einrichtung auf dem Intel NUC (Ubuntu Server 24.04)
#
# Läuft beim ersten Start von der internen Disk automatisch (tsst-setup.service)
# und kann jederzeit erneut gestartet werden:   sudo bash /opt/tsst-install/setup.sh
#
# Aufbau:
#   Ethernet = Wettkampfnetz (Kabel/Switch), NUC = 192.168.50.1, DHCP-Server (dnsmasq)
#              -> Zugriff auf die App OHNE Passwort
#   WLAN     = Internet (Handy-Hotspot/Router) -> DuckDNS-Update, Tailscale Funnel
#              -> Zugriff von dort / von aussen nur MIT Passwort
#   App (Docker) lauscht nur auf 127.0.0.1:5000, davor Caddy (Port 80/443).
# =====================================================================
set -uo pipefail

ETC=/etc/tsst
APP=/opt/tsst
LOG=/var/log/tsst-setup.log

exec > >(tee -a "$LOG") 2>&1
log()  { echo "[$(date '+%F %T')] $*"; }
fail() { log "FEHLER: $*"; exit 1; }

[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo starten."; exit 1; }
log "=== TSST-Einrichtung startet ==="

# ---------------------------------------------------------------------
# 1) Konfiguration
# ---------------------------------------------------------------------
[ -f "$ETC/tsst.conf" ] || fail "Konfiguration $ETC/tsst.conf fehlt."
chmod 700 "$ETC"; chmod 600 "$ETC/tsst.conf"
sed -i 's/\r$//' "$ETC/tsst.conf"
# shellcheck disable=SC1091
. "$ETC/tsst.conf"

WEB_BENUTZER="${WEB_BENUTZER:-tsst}"
LAN_IP="${LAN_IP:-192.168.50.1}"
LAN_NETZ="${LAN_IP%.*}"
DHCP_START="${DHCP_START:-$LAN_NETZ.100}"
DHCP_ENDE="${DHCP_ENDE:-$LAN_NETZ.200}"
IMAGE="${IMAGE:-ghcr.io/geco1986/tsst-auswertung:latest}"
DUCKDNS_DOMAIN="${DUCKDNS_DOMAIN:-}"; DUCKDNS_DOMAIN="${DUCKDNS_DOMAIN%.duckdns.org}"
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-}"
TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"
[ -n "${WEB_PASSWORT:-}" ] || fail "WEB_PASSWORT fehlt in der Konfiguration."

# Ethernet-Schnittstelle (Wettkampfnetz) ermitteln: erste physische, nicht-WLAN-Schnittstelle
if [ -z "${LAN_IF:-}" ]; then
  for n in /sys/class/net/*; do
    i="$(basename "$n")"
    [ -e "$n/device" ] && [ ! -e "$n/wireless" ] && [ ! -e "$n/phy80211" ] && { LAN_IF="$i"; break; }
  done
fi
[ -n "${LAN_IF:-}" ] || fail "keine Ethernet-Schnittstelle gefunden."
log "Wettkampfnetz auf Schnittstelle $LAN_IF ($LAN_IP/24)"

# ---------------------------------------------------------------------
# 2) Auf Internet warten (WLAN – oder vorübergehend Kabel am Heimrouter)
# ---------------------------------------------------------------------
log "Warte auf Internet ..."
ok=0
for _ in $(seq 1 120); do
  if curl -sS -o /dev/null --max-time 5 https://archive.ubuntu.com; then ok=1; break; fi
  sleep 5
done
[ "$ok" = 1 ] || fail "kein Internet nach 10 Minuten – WLAN prüfen (/etc/netplan), dann: sudo systemctl restart tsst-setup"
log "Internet ok."

# ---------------------------------------------------------------------
# 3) Pakete + Docker
# ---------------------------------------------------------------------
# dnsmasq-Konfiguration VOR der Installation anlegen, sonst kollidiert dnsmasq beim
# Paketstart mit systemd-resolved (Port 53).
mkdir -p /etc/dnsmasq.d
cat > /etc/dnsmasq.d/tsst.conf <<EOF
# TSST-Wettkampfnetz – nur $LAN_IF
interface=$LAN_IF
bind-dynamic
domain-needed
bogus-priv
domain=lan
local=/lan/
host-record=tsst.lan,tsst,$LAN_IP
dhcp-range=$DHCP_START,$DHCP_ENDE,255.255.255.0,12h
# kein Standard-Gateway: die PCs erreichen nur den NUC, nicht das Internet
dhcp-option=option:router
dhcp-option=option:dns-server,$LAN_IP
dhcp-authoritative
EOF

export DEBIAN_FRONTEND=noninteractive
apt-get update || fail "apt-get update"
apt-get install -y -o Dpkg::Options::=--force-confold dnsmasq curl ca-certificates openssl avahi-daemon \
  || fail "Pakete installieren"
if ! command -v docker >/dev/null 2>&1; then
  log "Installiere Docker ..."
  curl -fsSL https://get.docker.com | sh || fail "Docker-Installation"
fi
systemctl enable --now docker
U="$(getent passwd 1000 | cut -d: -f1)"; [ -n "$U" ] && usermod -aG docker "$U"

# ---------------------------------------------------------------------
# 4) App + Caddy (Docker Compose)
# ---------------------------------------------------------------------
log "Richte App unter $APP ein ..."
mkdir -p "$APP/data" "$APP/Inputs" "$APP/caddy-data" "$APP/caddy-config"
chmod 700 "$APP"
[ -s "$ETC/secret" ] || { openssl rand -hex 32 > "$ETC/secret"; chmod 600 "$ETC/secret"; }
SECRET="$(cat "$ETC/secret")"

docker pull caddy:2 || fail "caddy-Image laden"
HASH="$(docker run --rm -e PW="$WEB_PASSWORT" caddy:2 sh -c 'caddy hash-password --plaintext "$PW"')" \
  || fail "Passwort-Hash"

{
cat <<EOF
# erzeugt von setup.sh – Änderungen: /etc/tsst/tsst.conf anpassen und setup.sh erneut starten
{
	admin off
}

(app) {
	reverse_proxy 127.0.0.1:5000
}

(passwort) {
	basic_auth {
		$WEB_BENUTZER $HASH
	}
}

# Port 80 auf allen Schnittstellen:
#   Wettkampfnetz ($LAN_NETZ.0/24) -> ohne Passwort
#   alles andere (WLAN, Portweiterleitung) -> mit Passwort
:80 {
	@lan remote_ip $LAN_NETZ.0/24
	handle @lan {
		import app
	}
	handle {
		import passwort
		import app
	}
}

# Ziel für Tailscale Funnel (kommt immer von localhost) -> immer mit Passwort
:8080 {
	bind 127.0.0.1
	import passwort
	import app
}
EOF
if [ -n "$DUCKDNS_DOMAIN" ]; then
cat <<EOF

# DuckDNS (nur mit Portweiterleitung 80/443 am WLAN-Router) -> HTTPS + Passwort
$DUCKDNS_DOMAIN.duckdns.org {
	import passwort
	import app
}
EOF
fi
} > "$APP/Caddyfile"

cat > "$APP/docker-compose.yml" <<EOF
# erzeugt von setup.sh
services:
  tsst-auswertung:
    image: $IMAGE
    pull_policy: missing          # startet auch ohne Internet; Update: sudo tsst-update
    container_name: tsst-auswertung
    restart: unless-stopped
    ports:
      - "127.0.0.1:5000:5000"     # nur lokal – Zugriff immer über Caddy
    volumes:
      - ./data:/data
      - ./Inputs:/app/Inputs
    environment:
      DEBRA_DB: /data/debra.sqlite3
      DEBRA_SECRET: "$SECRET"
      DEBRA_SEED: "0"
      PORT: "5000"

  caddy:
    image: caddy:2
    pull_policy: missing
    container_name: tsst-caddy
    restart: unless-stopped
    network_mode: host            # damit Caddy die echte Absender-IP sieht
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./caddy-data:/data
      - ./caddy-config:/config
EOF
chmod 600 "$APP/docker-compose.yml" "$APP/Caddyfile"

log "Lade App-Image $IMAGE ..."
pulled=0
for _ in 1 2 3; do
  if docker compose -f "$APP/docker-compose.yml" pull; then pulled=1; break; fi
  sleep 10
done
[ "$pulled" = 1 ] || fail "App-Image nicht ladbar (Internet? GHCR-Paket öffentlich?)."
docker compose -f "$APP/docker-compose.yml" up -d --force-recreate || fail "Container starten"

# ---------------------------------------------------------------------
# 5) Hilfsbefehle
# ---------------------------------------------------------------------
cat > /usr/local/bin/tsst-update <<'EOF'
#!/bin/bash
# App-Image aktualisieren (braucht Internet)
set -e
cd /opt/tsst
docker compose pull
docker compose up -d
docker image prune -f
EOF
cat > /usr/local/bin/tsst-status <<'EOF'
#!/bin/bash
echo "== Adressen =="; ip -4 -br addr show | grep -v '^lo'
echo; echo "== Container =="; docker ps --format '{{.Names}}\t{{.Status}}'
echo; echo "== DHCP-Leases (Wettkampfnetz) =="; cat /var/lib/misc/dnsmasq.leases 2>/dev/null || echo "(keine)"
if command -v tailscale >/dev/null; then echo; echo "== Tailscale Funnel =="; tailscale funnel status 2>&1; fi
EOF
chmod 755 /usr/local/bin/tsst-update /usr/local/bin/tsst-status

# ---------------------------------------------------------------------
# 6) DuckDNS-Updater (alle 5 Minuten)
# ---------------------------------------------------------------------
if [ -n "$DUCKDNS_DOMAIN" ] && [ -n "$DUCKDNS_TOKEN" ]; then
  log "Richte DuckDNS ($DUCKDNS_DOMAIN.duckdns.org) ein ..."
  cat > /usr/local/bin/tsst-duckdns <<'EOF'
#!/bin/bash
. /etc/tsst/tsst.conf
D="${DUCKDNS_DOMAIN%.duckdns.org}"
[ -n "$D" ] && [ -n "${DUCKDNS_TOKEN:-}" ] || exit 0
r="$(curl -fsS --max-time 20 "https://www.duckdns.org/update?domains=$D&token=$DUCKDNS_TOKEN&ip=")"
echo "DuckDNS $D: $r"
[ "$r" = "OK" ]
EOF
  chmod 700 /usr/local/bin/tsst-duckdns
  cat > /etc/systemd/system/tsst-duckdns.service <<'EOF'
[Unit]
Description=DuckDNS-Update (TSST)
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/tsst-duckdns
EOF
  cat > /etc/systemd/system/tsst-duckdns.timer <<'EOF'
[Unit]
Description=DuckDNS-Update alle 5 Minuten (TSST)
[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now tsst-duckdns.timer
  /usr/local/bin/tsst-duckdns || log "DuckDNS-Update fehlgeschlagen – Domain/Token prüfen."
fi

# ---------------------------------------------------------------------
# 7) Tailscale Funnel (Zugriff von aussen auch hinter Handy-Hotspot/CGNAT)
# ---------------------------------------------------------------------
if [ -n "$TAILSCALE_AUTHKEY" ]; then
  log "Richte Tailscale Funnel ein ..."
  command -v tailscale >/dev/null 2>&1 || curl -fsSL https://tailscale.com/install.sh | sh \
    || log "Tailscale-Installation fehlgeschlagen."
  if command -v tailscale >/dev/null 2>&1; then
    tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname="$(hostname)" || log "tailscale up fehlgeschlagen (Auth-Key?)"
    timeout 60 tailscale funnel --bg 8080 \
      || log "Funnel nicht aktiv – im Tailscale-Admin HTTPS + Funnel erlauben, dann: sudo tailscale funnel --bg 8080"
    tailscale funnel status || true
  fi
fi

# ---------------------------------------------------------------------
# 8) Zum Schluss: Ethernet = Wettkampfnetz mit fester IP + DHCP-Server
#    (erst jetzt, damit die Einrichtung notfalls auch per Kabel am Heimrouter läuft)
# ---------------------------------------------------------------------
log "Stelle $LAN_IF auf $LAN_IP/24 (Wettkampfnetz) um ..."
cat > /etc/netplan/99-tsst-lan.yaml <<EOF
# TSST-Wettkampfnetz – überschreibt die DHCP-Einstellung aus der Installation
network:
  version: 2
  ethernets:
    lan:
      match:
        name: "$LAN_IF"
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      addresses: [ "$LAN_IP/24" ]
      optional: true
EOF
chmod 600 /etc/netplan/*.yaml
netplan apply || log "netplan apply meldet einen Fehler – nach einem Neustart prüfen."
systemctl enable dnsmasq
systemctl restart dnsmasq || fail "dnsmasq startet nicht (journalctl -u dnsmasq)"

touch "$ETC/.installed"
WLAN_IP="$(ip -4 -o addr show 2>/dev/null | awk '$2 ~ /^wl/ {print $4}' | cut -d/ -f1 | head -1)"
log "=== Einrichtung abgeschlossen ==="
log "Wettkampfnetz (Kabel, ohne Passwort): http://$LAN_IP  bzw.  http://tsst.lan"
[ -n "$WLAN_IP" ] && log "Aus dem WLAN (mit Passwort):        http://$WLAN_IP"
[ -n "$DUCKDNS_DOMAIN" ] && log "DuckDNS (mit Passwort):             https://$DUCKDNS_DOMAIN.duckdns.org"
log "Status: sudo tsst-status    Update: sudo tsst-update"
exit 0
