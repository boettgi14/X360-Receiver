"""Turning controllers off: one target after the other, with a deadline.

Used by the "Turn off all controllers now" button (plugin) and by the service that runs on shutdown
(`poweroff_cli`, see `poweroff_unit`). This module does not check whether the system is shutting
down: the plugin cannot do this job itself while Decky shuts it down, which is why a separate systemd
service takes over.

Error texts are English and language-neutral (they end up in `last-run.json` and in the diagnostics).
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import actions

# With the sequence proven on hardware (discard 0.3 s, send, listen 0.6 s) each slot takes about 1 s.
# The service may be killed after `TimeoutStopSec` (poweroff_unit); the limit stays below that.
DEADLINE_S = 8.0
RETRY_S = 0.2

Target = Tuple[int, int, int]


def power_off_targets(
    targets: Iterable[Target],
    power_off: Optional[Callable[..., dict]] = None,
    deadline_s: float = DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, object]:
    """Sends the turn-off command to all targets in turn, for at most `deadline_s` seconds.

    If another access is running, it retries until the deadline. Returns counters and error texts.
    """
    power_off = power_off or actions.power_off  # bound at run time so tests can replace it
    start = clock()
    sent = confirmed = skipped = 0
    errors: List[str] = []
    pending = list(targets)
    for index, (bus, devnum, slot) in enumerate(pending):
        while True:
            result = power_off(bus, devnum, slot)
            if result.get("error") != actions.BUSY_ERROR or clock() - start >= deadline_s:
                break
            sleep(RETRY_S)
        if result.get("ok"):
            sent += 1
            confirmed += 1 if result.get("confirmed") else 0
        else:
            errors.append(f"bus {bus} device {devnum} slot {slot + 1}: {result.get('error', 'unknown error')}")
        if clock() - start >= deadline_s:
            skipped = len(pending) - index - 1
            break
    if skipped:
        errors.append(f"{skipped} slot(s) not reached any more (deadline)")
    return {"ok": not errors, "sent": sent, "confirmed": confirmed, "errors": errors}
