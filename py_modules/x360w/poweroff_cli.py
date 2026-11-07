"""Program of the systemd service: turns off all connected controllers on shutdown.

Runs as root inside the service (`poweroff_unit`), independent of Decky and of the plugin: the plugin
cannot turn controllers off while Decky shuts it down, but systemd does run the service's `ExecStop`.

It finds the targets itself (receivers through sysfs, occupied slots through sysfs and LEDs, without
the usbmon monitor) and then sends the same turn-off command as the "Turn off all controllers now"
button. The result goes to `last-run.json` (the plugin shows it under "Diagnostics") and to the
journal as a single line.

Privacy: Only counters, targets and error texts are written, never any input.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import controls, discovery, shutdown, view

LAST_RUN_NAME = "last-run.json"


def plan_targets() -> Tuple[int, List[Tuple[int, int, int]]]:
    """(number of receivers, targets) like `Plugin._all_targets`, just without monitor data."""
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
    """Runs the procedure and returns the report. Never raises."""
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
    except Exception as exc:  # shutting down must never fail because of this service
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
    return 0  # never an error status: it would not stop the shutdown, but it would clutter the journal
