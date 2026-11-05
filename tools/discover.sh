#!/usr/bin/env bash
# Phase 0: Nur lesend. Sammelt Informationen über Receiver, xpad, LEDs, Akku-Schnittstellen
# und usbmon-Verfügbarkeit. Ändert nichts am System.
#
# Aufruf (Desktop-Modus, Terminal):  bash tools/discover.sh | tee discover.txt

set -u

section() { printf '\n===== %s =====\n' "$1"; }

section "Kernel / Distribution"
uname -r
grep -E '^(NAME|VARIANT_ID|VERSION)=' /etc/os-release 2>/dev/null

section "Xbox 360 Wireless Receiver am USB-Bus (VID 045e)"
lsusb 2>/dev/null | grep -i '045e' || echo "kein Microsoft-USB-Gerät gefunden oder lsusb fehlt"
for dev in /sys/bus/usb/devices/*; do
  [ -f "$dev/idVendor" ] || continue
  vid=$(cat "$dev/idVendor"); pid=$(cat "$dev/idProduct")
  case "$vid:$pid" in
    045e:0291|045e:0719|045e:02a9)
      echo "--- $dev ($vid:$pid)"
      for f in manufacturer product serial bcdDevice busnum devnum; do
        [ -f "$dev/$f" ] && printf '%s: %s\n' "$f" "$(cat "$dev/$f")"
      done
      for intf in "$dev":*; do
        [ -d "$intf" ] || continue
        drv=$(basename "$(readlink -f "$intf/driver" 2>/dev/null)" 2>/dev/null)
        printf '%s  class=%s sub=%s proto=%s  driver=%s\n' \
          "$(basename "$intf")" \
          "$(cat "$intf/bInterfaceClass" 2>/dev/null)" \
          "$(cat "$intf/bInterfaceSubClass" 2>/dev/null)" \
          "$(cat "$intf/bInterfaceProtocol" 2>/dev/null)" \
          "${drv:-<keiner>}"
      done
      ;;
  esac
done

section "xpad-Modul und Parameter"
lsmod | grep -E '^xpad' || echo "xpad nicht als Modul geladen (evtl. fest im Kernel)"
for p in /sys/module/xpad/parameters/*; do
  [ -f "$p" ] && printf '%s = %s\n' "$(basename "$p")" "$(cat "$p")"
done

section "LED-Klasse (xpadN)"
ls -l /sys/class/leds 2>/dev/null | grep -i xpad || echo "keine xpad-LEDs"

section "Eingabegeräte"
grep -B1 -A6 -i 'xbox' /proc/bus/input/devices 2>/dev/null || echo "keine Xbox-Eingabegeräte"

section "Akku-Schnittstellen (power_supply)"
ls /sys/class/power_supply 2>/dev/null || echo "leer"
command -v upower >/dev/null && upower -d | grep -i -B2 -A8 -E 'xbox|xpad|gaming|controller' || echo "upower: nichts Controller-Bezogenes"

section "usbmon-Verfügbarkeit"
lsmod | grep -E '^usbmon' || echo "usbmon nicht geladen"
ls /dev/usbmon* 2>/dev/null || echo "keine /dev/usbmon*-Knoten"
mount | grep -E 'debugfs' || echo "debugfs nicht gemountet"
ls /sys/kernel/debug/usb/usbmon 2>/dev/null || echo "kein debugfs-usbmon (evtl. kein Root oder nicht geladen)"
grep -E '^CONFIG_USB_MON' "/boot/config-$(uname -r)" 2>/dev/null || zcat /proc/config.gz 2>/dev/null | grep -E '^CONFIG_USB_MON' || echo "Kernel-Konfiguration nicht auslesbar"
cat /sys/kernel/security/lockdown 2>/dev/null || echo "kein Lockdown-Status"

section "SELinux"
getenforce 2>/dev/null || echo "getenforce nicht verfügbar"

section "Fertig"
echo "Ergebnis bitte vollständig weitergeben. Das Skript hat nichts verändert."
