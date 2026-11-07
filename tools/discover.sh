#!/usr/bin/env bash
# Read-only. Collects information about the receiver, xpad, LEDs, battery interfaces
# and usbmon availability. Changes nothing on the system.
#
# Usage (desktop mode, terminal):  bash tools/discover.sh | tee discover.txt
#
# LC_ALL=C: the output of the tools used below does not depend on the system language, so a German
# and an English system give comparable results.

set -u
export LC_ALL=C

section() { printf '\n===== %s =====\n' "$1"; }

section "Kernel / distribution"
uname -r
grep -E '^(NAME|VARIANT_ID|VERSION)=' /etc/os-release 2>/dev/null

section "Xbox 360 Wireless receiver on the USB bus (VID 045e)"
lsusb 2>/dev/null | grep -i '045e' || echo "no Microsoft USB device found or lsusb is missing"
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
          "${drv:-<none>}"
      done
      ;;
  esac
done

section "xpad module and parameters"
lsmod | grep -E '^xpad' || echo "xpad not loaded as a module (possibly built into the kernel)"
for p in /sys/module/xpad/parameters/*; do
  [ -f "$p" ] && printf '%s = %s\n' "$(basename "$p")" "$(cat "$p")"
done

section "LED class (xpadN)"
ls -l /sys/class/leds 2>/dev/null | grep -i xpad || echo "no xpad LEDs"

section "Input devices"
grep -B1 -A6 -i 'xbox' /proc/bus/input/devices 2>/dev/null || echo "no Xbox input devices"

section "Battery interfaces (power_supply)"
ls /sys/class/power_supply 2>/dev/null || echo "empty"
command -v upower >/dev/null && upower -d | grep -i -B2 -A8 -E 'xbox|xpad|gaming|controller' || echo "upower: nothing controller-related"

section "usbmon availability"
lsmod | grep -E '^usbmon' || echo "usbmon not loaded"
ls /dev/usbmon* 2>/dev/null || echo "no /dev/usbmon* nodes"
mount | grep -E 'debugfs' || echo "debugfs not mounted"
ls /sys/kernel/debug/usb/usbmon 2>/dev/null || echo "no debugfs usbmon (possibly not root or not loaded)"
grep -E '^CONFIG_USB_MON' "/boot/config-$(uname -r)" 2>/dev/null || zcat /proc/config.gz 2>/dev/null | grep -E '^CONFIG_USB_MON' || echo "kernel configuration cannot be read"
cat /sys/kernel/security/lockdown 2>/dev/null || echo "no lockdown status"

section "SELinux"
getenforce 2>/dev/null || echo "getenforce not available"

section "Done"
echo "Please pass on the complete result. The script has changed nothing."
