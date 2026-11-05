#!/usr/bin/env python3
"""Phase 0: Liest usbmon-Text und zeigt nur Pakete des Receivers, dekodiert.

Datenschutz: usbmon sieht den GESAMTEN Bus, also auch Tastaturen und Mäuse am selben
Bus. Dieses Skript filtert strikt nach Bus und Geräteadresse und gibt nichts anderes
aus. Zeilen anderer Geräte werden sofort verworfen und nie gespeichert.

Beispiele (als root):
  sudo modprobe usbmon
  sudo python3 -I tools/capture_usbmon.py --bus 1 --device 4 --seconds 60
  python3 -I tools/capture_usbmon.py --file beispiel.txt --bus 1 --device 4   # Offline-Test

Bus und Gerät stehen in der Ausgabe von tools/discover.sh (busnum/devnum).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w import parse_usbmon_line, decode_in_packet  # noqa: E402
from x360w.protocol import (  # noqa: E402
    ConnectionEvent,
    InputReport,
    LinkReport,
    StateReport,
)


def describe(report) -> str:
    if isinstance(report, ConnectionEvent):
        return f"VERBINDUNG controller={report.controller} headset={report.headset}"
    if isinstance(report, StateReport):
        return (
            f"STATUS akku_stufe={int(report.battery_level)} ({report.battery_level.name}) "
            f"akku_typ_roh={report.battery_type} power_roh={report.power_state} "
            f"headset={report.headset} chatpad={report.chatpad} "
            f"vibration={report.vibration_level}"
        )
    if isinstance(report, LinkReport):
        return (
            f"LINK subtype={report.subtype_name} device_id=0x{report.device_id:08X} "
            f"protokoll=0x{report.protocol:04X} vendor_roh={report.vendor_id_data.hex()}"
        )
    if isinstance(report, InputReport):
        return "EINGABE (nicht ausgegeben)"
    return f"SONST {type(report).__name__} {getattr(report, 'raw', b'').hex()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--file", help="statt usbmon aus Datei lesen (Test)")
    parser.add_argument("--show-input", action="store_true", help="Eingabepakete mit ausgeben")
    args = parser.parse_args()

    source_path = args.file or f"/sys/kernel/debug/usb/usbmon/{args.bus}u"
    deadline = time.monotonic() + args.seconds
    counts: dict[str, int] = {}

    try:
        stream = open(source_path, "r", encoding="ascii", errors="replace")
    except OSError as exc:
        print(f"Kann {source_path} nicht öffnen: {exc}", file=sys.stderr)
        return 1

    with stream:
        for line in stream:
            record = parse_usbmon_line(line)
            if record is None or record.bus != args.bus or record.device != args.device:
                continue  # fremde Geräte: sofort verwerfen

            if record.xfer_type != "I" or not record.data:
                continue

            # Ungerade Endpunkte = Controller-Schnittstellen (1,3,5,7 = Slot 0..3),
            # gerade = Audio/Headset (hier nicht ausgewertet).
            if record.endpoint % 2 == 0:
                continue
            slot = (record.endpoint - 1) // 2
            arrow = "IN " if record.direction == "i" else "OUT"
            if record.direction == "i":
                report = decode_in_packet(record.data)
                text = describe(report) if report is not None else "zu kurz"
                if isinstance(report, InputReport) and not args.show_input:
                    counts["EINGABE"] = counts.get("EINGABE", 0) + 1
                    continue
            else:
                text = "BEFEHL " + record.data.hex()
            key = text.split()[0]
            counts[key] = counts.get(key, 0) + 1
            print(f"{record.timestamp_us/1e6:12.3f} {arrow} ep=0x{record.endpoint:02X} slot={slot} {text}")

            if not args.file and time.monotonic() > deadline:
                break

    print("\nZusammenfassung:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
