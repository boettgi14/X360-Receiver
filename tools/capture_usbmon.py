#!/usr/bin/env python3
"""Phase 0: Reads usbmon text and shows only the receiver's packets, decoded.

Privacy: usbmon sees the ENTIRE bus, including keyboards and mice on the same bus. This
script filters strictly by bus and device address and outputs nothing else. Lines of other
devices are discarded immediately and never stored.

Examples (as root):
  sudo modprobe usbmon
  sudo python3 -I tools/capture_usbmon.py --bus 1 --device 4 --seconds 60
  python3 -I tools/capture_usbmon.py --file example.txt --bus 1 --device 4   # offline test

Bus and device are in the output of tools/discover.sh (busnum/devnum).
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
        return f"CONNECTION controller={report.controller} headset={report.headset}"
    if isinstance(report, StateReport):
        return (
            f"STATE battery_level={int(report.battery_level)} ({report.battery_level.name}) "
            f"battery_type_raw={report.battery_type} power_state_raw={report.power_state} "
            f"headset={report.headset} chatpad={report.chatpad} "
            f"vibration={report.vibration_level}"
        )
    if isinstance(report, LinkReport):
        return (
            f"LINK subtype={report.subtype_name} device_id=0x{report.device_id:08X} "
            f"protocol=0x{report.protocol:04X} vendor_raw={report.vendor_id_data.hex()}"
        )
    if isinstance(report, InputReport):
        return "INPUT (not shown)"
    return f"OTHER {type(report).__name__} {getattr(report, 'raw', b'').hex()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--file", help="read from a file instead of usbmon (test)")
    parser.add_argument("--show-input", action="store_true", help="also output input packets")
    args = parser.parse_args()

    source_path = args.file or f"/sys/kernel/debug/usb/usbmon/{args.bus}u"
    deadline = time.monotonic() + args.seconds
    counts: dict[str, int] = {}

    try:
        stream = open(source_path, "r", encoding="ascii", errors="replace")
    except OSError as exc:
        print(f"Cannot open {source_path}: {exc}", file=sys.stderr)
        return 1

    with stream:
        for line in stream:
            record = parse_usbmon_line(line)
            if record is None or record.bus != args.bus or record.device != args.device:
                continue  # foreign devices: discard immediately

            if record.xfer_type != "I" or not record.data:
                continue

            # Odd endpoints = controller interfaces (1,3,5,7 = slot 0..3),
            # even = audio/headset (not evaluated here).
            if record.endpoint % 2 == 0:
                continue
            slot = (record.endpoint - 1) // 2
            arrow = "IN " if record.direction == "i" else "OUT"
            if record.direction == "i":
                report = decode_in_packet(record.data)
                text = describe(report) if report is not None else "too short"
                if isinstance(report, InputReport) and not args.show_input:
                    counts["INPUT"] = counts.get("INPUT", 0) + 1
                    continue
            else:
                text = "COMMAND " + record.data.hex()
            key = text.split()[0]
            counts[key] = counts.get(key, 0) + 1
            print(f"{record.timestamp_us/1e6:12.3f} {arrow} ep=0x{record.endpoint:02X} slot={slot} {text}")

            if not args.file and time.monotonic() > deadline:
                break

    print("\nSummary:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
