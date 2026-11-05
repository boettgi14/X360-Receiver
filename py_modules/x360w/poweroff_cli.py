"""Programm des systemd-Dienstes: schaltet beim Herunterfahren alle verbundenen Controller aus.

Läuft als Root im Dienst (`poweroff_unit`), unabhängig von Decky und vom Plugin: Decky stoppt das Plugin
beim Herunterfahren nicht zuverlässig (am Gerät beobachtet), systemd führt `ExecStop` des Dienstes aber aus.

Ermittelt die Ziele selbst (Receiver per sysfs, belegte Slots per sysfs und LEDs, ohne usbmon-Monitor) und
sendet dann denselben Ausschaltbefehl wie der Knopf „Alle Controller jetzt ausschalten“. Das Ergebnis
steht in `last-run.json` (das Plugin zeigt es unter „Diagnose“) und als eine Zeile im Journal.

Datenschutz: Es werden nur Zähler, Ziele und Fehlertexte geschrieben, keine Eingaben.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import controls, discovery, shutdown, view

LAST_RUN_NAME = "last-run.json"


def plan_targets() -> Tuple[int, List[Tuple[int, int, int]]]:
    """(Anzahl Receiver, Ziele) wie `Plugin._all_targets`, nur ohne Monitor-Daten."""
    receivers = discovery.find_receivers()
    views = view.build_receiver_views(
        receivers,
        [],
        controls.led_owners(),
        {r.usb_path: discovery.connected_slots_sysfs(r) for r in receivers},
    )
    return len(receivers), view.plan_targets(views)


def run(
    plan: Callable[[], Tuple[int, List[Tuple[int, int, int]]]] = plan_targets,
    power_off_targets: Optional[Callable[..., Dict[str, object]]] = None,
    clock: Callable[[], float] = time.time,
) -> Dict[str, object]:
    """Führt den Ablauf aus und gibt den Bericht zurück. Wirft nie."""
    power_off_targets = power_off_targets or shutdown.power_off_targets
    began = clock()
    report: Dict[str, object] = {"at": round(began, 2), "receivers": 0, "targets": [], "result": None, "error": None}
    try:
        receivers, targets = plan()
        report["receivers"] = receivers
        report["targets"] = [list(t) for t in targets]
        if targets:
            report["result"] = power_off_targets(targets)
        else:
            report["result"] = {"ok": True, "sent": 0, "confirmed": 0, "errors": []}
    except Exception as exc:  # Herunterfahren darf nie an diesem Dienst scheitern
        report["error"] = f"{type(exc).__name__}: {exc}"[:300]
    report["duration_s"] = round(clock() - began, 2)
    return report


def write_report(directory: str, report: Dict[str, object]) -> None:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, LAST_RUN_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(report, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def main(directory: str) -> int:
    report = run()
    try:
        write_report(directory, report)
    except OSError as exc:
        report["write_error"] = str(exc)[:200]
    print("x360w-poweroff " + json.dumps(report, separators=(",", ":")), flush=True)
    return 0  # nie ein Fehlerstatus: er würde das Herunterfahren nicht aufhalten, aber das Journal verschmutzen
