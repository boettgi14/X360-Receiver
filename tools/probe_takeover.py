#!/usr/bin/env python3
"""Prüfwerkzeug (Phase 0d): sendet Befehle an EINEN Slot des Receivers und zeigt die Antworten.

Ablauf: xpad gibt die Schnittstelle des Slots frei, das Werkzeug sendet, liest und gibt frei,
danach bindet xpad wieder. Der Slot liefert in dieser Zeit (wenige Sekunden) keine Eingaben an
Steam. Nicht während eines Spiels ausführen. Braucht root und libusb.

Beispiele (Bus 1, Gerät 2, Slot 0 = erster Controller):
  sudo python3 -I tools/probe_takeover.py --bus 1 --device 2 --slot 0 --battery-request
  sudo python3 -I tools/probe_takeover.py --bus 1 --device 2 --slot 0 --poweroff

Gleichzeitig kann in einem zweiten Terminal ein usbmon-Mitschnitt laufen.
Nicht an Hardware getestet. Es werden nur Status- und Verbindungspakete im Klartext angezeigt;
Eingabepakete werden nur gezählt.
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
        return "Eingabepaket" + (" mit Zustand im Header: " + str(report.state) if report.state else "")
    return repr(report)


def show(label: str, packets) -> None:
    inputs = sum(1 for _, _, rep in packets if isinstance(rep, InputReport) and rep.state is None)
    print(f"  {label}: {len(packets)} Pakete, davon {inputs} reine Eingabepakete (nicht angezeigt)")
    for t, raw, rep in packets:
        if isinstance(rep, InputReport) and rep.state is None:
            continue
        print(f"    +{t:5.2f} s  {raw[:5].hex()}  {describe(rep)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--device", type=int, required=True, help="Geräteadresse (lsusb: Device)")
    parser.add_argument("--slot", type=int, required=True, choices=range(4))
    parser.add_argument("--presence", action="store_true", help="Anwesenheitsabfrage (08 00 0F C0)")
    parser.add_argument("--battery-request", action="store_true", help="Akkuanfrage (00 00 00 40), Wirkung unbekannt")
    parser.add_argument("--capabilities", action="store_true", help="Fähigkeitenanfrage (00 00 02 80), Wirkung unbekannt")
    parser.add_argument("--poweroff", action="store_true", help="Controller ausschalten (00 00 08 C0)")
    parser.add_argument("--listen", type=float, default=2.0, help="Sekunden Lauschen nach jedem Befehl")
    parser.add_argument("--yes", action="store_true", help="ohne Rückfrage")
    args = parser.parse_args()

    steps = []
    if args.presence:
        steps.append(("Anwesenheitsabfrage", build_status_request()))
    if args.battery_request:
        steps.append(("Akkuanfrage", build_battery_request()))
    if args.capabilities:
        steps.append(("Fähigkeitenanfrage", build_capabilities_request()))
    if args.poweroff:
        steps.append(("AUSSCHALTEN", build_poweroff()))
    if not steps:
        steps.append(("nur Lauschen", None))

    if os.geteuid() != 0:
        print("Bitte als root ausführen (sudo).", file=sys.stderr)
        return 2

    print(f"Receiver Bus {args.bus}, Gerät {args.device}, Slot {args.slot} (Schnittstelle {2 * args.slot}).")
    print("xpad gibt die Schnittstelle dieses Slots kurz frei. Schritte: " + ", ".join(n for n, _ in steps))
    if not args.yes and input("Weiter mit Enter, Abbruch mit Strg+C: ") != "":
        return 1

    try:
        backend = LibusbBackend()
        with SlotSession(backend, args.bus, args.device, args.slot) as session:
            show("vorher", session.listen(0.3))
            for name, packet in steps:
                if packet is not None:
                    print(f"* {name}: sende {packet.hex()}")
                    session.send(packet)
                show("danach", session.listen(args.listen))
    except UsbError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        print("Falls der Controller danach nicht reagiert: Schnittstelle von Hand binden, z. B.\n"
              "  echo <Name aus 'ls /sys/bus/usb/drivers/xpad/' bzw. dmesg> | sudo tee /sys/bus/usb/drivers/xpad/bind",
              file=sys.stderr)
        return 1

    print("Fertig. xpad ist wieder gebunden.")
    if args.poweroff:
        print("Der Controller ist jetzt AUS und verbindet sich nicht von selbst. Zum Wiederverbinden "
              "am Controller die Guide-Taste drücken.")
    else:
        print("Der Controller meldet sich in wenigen Sekunden neu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
