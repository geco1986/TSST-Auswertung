#!/bin/bash
# Läuft im Ubuntu-Installer (autoinstall early-commands): sucht die interne Disk des NUC
# und trägt sie in /autoinstall.yaml ein (Platzhalter __ZIELDISK__).
# Vorrang: interne SATA-/NVMe-SSD vor eMMC. Nie: das Installationsmedium, USB, SD-Karten.
set -u
MEDIUM_PART="$(findmnt -no SOURCE /cdrom 2>/dev/null | head -1)"
MEDIUM_DISK=""
[ -n "$MEDIUM_PART" ] && MEDIUM_DISK="/dev/$(lsblk -no PKNAME "$MEDIUM_PART" | head -1)"
echo "Installationsmedium: ${MEDIUM_PART:-?} (${MEDIUM_DISK:-?})"

best=""; best_prio=0; best_size=0
for d in $(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}'); do
  dev="/dev/$d"
  case "$d" in loop*|sr*|zram*|ram*|mmcblk*boot*|mmcblk*rpmb) continue ;; esac
  [ "$dev" = "$MEDIUM_DISK" ] && { echo "  $dev: Installationsmedium – übersprungen"; continue; }
  size=$(( $(cat "/sys/block/$d/size") * 512 ))
  [ "$size" -lt $((14 * 1000 * 1000 * 1000)) ] && { echo "  $dev: zu klein"; continue; }
  if [[ "$d" == mmcblk* ]]; then
    typ="$(cat "/sys/block/$d/device/type" 2>/dev/null)"
    [ "$typ" = "MMC" ] || { echo "  $dev: SD-Karte – übersprungen"; continue; }
    prio=1                                   # eingebauter eMMC-Speicher
  else
    [ "$(cat "/sys/block/$d/removable")" = 1 ] && { echo "  $dev: wechselbar – übersprungen"; continue; }
    tran="$(lsblk -dno TRAN "$dev" | tr -d ' ')"
    [ "$tran" = "usb" ] && { echo "  $dev: USB – übersprungen"; continue; }
    prio=2                                   # interne SATA-/NVMe-SSD
  fi
  echo "  $dev: Kandidat (Priorität $prio, $((size / 1000000000)) GB)"
  if [ "$prio" -gt "$best_prio" ] || { [ "$prio" -eq "$best_prio" ] && [ "$size" -gt "$best_size" ]; }; then
    best="$dev"; best_prio=$prio; best_size=$size
  fi
done

if [ -z "$best" ]; then
  echo "FEHLER: keine interne Disk gefunden – Installation abgebrochen."
  exit 1
fi
echo "Ziel-Disk: $best"
sed -i "s#__ZIELDISK__#$best#g" /autoinstall.yaml
