#!/usr/bin/env python3
"""Test tool: sends commands to ONE slot of the receiver and shows the replies.

Procedure: xpad releases the slot's interface, the tool sends, reads and releases it,
after which xpad binds again. During that time (a few seconds) the slot delivers no input to
Steam. Do not run during a game. Needs root and libusb.

Examples (bus 1, device 2, slot 0 = first controller):
  sudo python3 -I tools/probe_takeover.py --bus 1 --device 2 --slot 0 --battery-request
  sudo python3 -I tools/probe_takeover.py --bus 1 --device 2 --slot 0 --poweroff

A usbmon capture can run in a second terminal at the same time.
Only state and connection packets are shown in plain text; input packets are only counted.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w import (  # noqa: E402
    InputReport,
    build_battery_request,
    build_capabilities_request,
    build_poweroff,
    build_status_request,
)
from x360w.takeover import LibusbBackend, SlotSession, UsbError  # noqa: E402


def describe(report) -> str:
    if isinstance(report, InputReport):
        return "input packet" + (" with state in the header: " + str(report.state) if report.state else "")
    return repr(report)


def show(label: str, packets) -> None:
    inputs = sum(1 for _, _, rep in packets if isinstance(rep, InputReport) and rep.state is None)
    print(f"  {label}: {len(packets)} packets, of which {inputs} plain input packets (not shown)")
    for t, raw, rep in packets:
        if isinstance(rep, InputReport) and rep.state is None:
            continue
        print(f"    +{t:5.2f} s  {raw[:5].hex()}  {describe(rep)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--device", type=int, required=True, help="device address (lsusb: Device)")
    parser.add_argument("--slot", type=int, required=True, choices=range(4))
    parser.add_argument("--presence", action="store_true", help="presence request (08 00 0F C0)")
    parser.add_argument("--battery-request", action="store_true", help="battery request (00 00 00 40)")
    parser.add_argument("--capabilities", action="store_true", help="capabilities request (00 00 02 80), effect unknown")
    parser.add_argument("--poweroff", action="store_true", help="turn the controller off (00 00 08 C0)")
    parser.add_argument("--listen", type=float, default=2.0, help="seconds to listen after each command")
    parser.add_argument("--yes", action="store_true", help="without confirmation")
    args = parser.parse_args()

    steps = []
    if args.presence:
        steps.append(("presence request", build_status_request()))
    if args.battery_request:
        steps.append(("battery request", build_battery_request()))
    if args.capabilities:
        steps.append(("capabilities request", build_capabilities_request()))
    if args.poweroff:
        steps.append(("TURN OFF", build_poweroff()))
    if not steps:
        steps.append(("listen only", None))

    if os.geteuid() != 0:
        print("Please run as root (sudo).", file=sys.stderr)
        return 2

    print(f"Receiver bus {args.bus}, device {args.device}, slot {args.slot} (interface {2 * args.slot}).")
    print("xpad briefly releases this slot's interface. Steps: " + ", ".join(n for n, _ in steps))
    if not args.yes and input("Press Enter to continue, Ctrl+C to abort: ") != "":
        return 1

    try:
        backend = LibusbBackend()
        with SlotSession(backend, args.bus, args.device, args.slot) as session:
            show("before", session.listen(0.3))
            for name, packet in steps:
                if packet is not None:
                    print(f"* {name}: sending {packet.hex()}")
                    session.send(packet)
                show("after", session.listen(args.listen))
    except UsbError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("If the controller does not respond afterwards: bind the interface by hand, e.g.\n"
              "  echo <name from 'ls /sys/bus/usb/drivers/xpad/' or dmesg> | sudo tee /sys/bus/usb/drivers/xpad/bind",
              file=sys.stderr)
        return 1

    print("Done. xpad is bound again.")
    if args.poweroff:
        print("The controller is now OFF and does not reconnect by itself. To reconnect, "
              "press the Guide button on the controller.")
    else:
        print("The controller reconnects in a few seconds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
