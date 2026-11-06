"""Cache for actively queried battery levels (battery request through the short access).

The receiver reports the battery on its own only when a controller connects. A controller that was
already connected before the plugin started therefore never has a value without an active request.
The result of the request is kept here so the UI can show it even without the usbmon monitor.

An entry expires when its slot has not been seen as connected for longer than `grace_s`. The grace
period is needed because the controller itself disappears from the system for a few seconds during
the request (xpad is unbound); that is not a real disconnect.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

Key = Tuple[int, int, int]  # (bus, device, slot)

GRACE_S = 15.0


class BatteryCache:
    def __init__(self, clock: Callable[[], float] = time.time, grace_s: float = GRACE_S) -> None:
        self._clock = clock
        self._grace_s = grace_s
        self._lock = threading.Lock()
        self._entries: Dict[Key, dict] = {}
        self._missing_since: Dict[Key, Optional[float]] = {}

    def store(self, key: Key, state: dict) -> None:
        """`state` is the state dict from `actions.query_battery`."""
        entry = {
            "battery_level": state["battery_level"],
            "battery_type_raw": state.get("battery_type_raw"),
            "power_state_raw": state.get("power_state_raw"),
            "at": self._clock(),
        }
        with self._lock:
            self._entries[key] = entry
            self._missing_since[key] = None

    def snapshot(self) -> Dict[Key, dict]:
        now = self._clock()
        with self._lock:
            return {
                key: {
                    "battery_level": e["battery_level"],
                    "battery_type_raw": e["battery_type_raw"],
                    "power_state_raw": e["power_state_raw"],
                    "age_s": max(0.0, now - e["at"]),
                }
                for key, e in self._entries.items()
            }

    def prune(self, present: Iterable[Key]) -> None:
        """Drops entries of slots that have not been connected for longer than the grace period."""
        present_set: Set[Key] = set(present)
        now = self._clock()
        with self._lock:
            for key in list(self._entries):
                if key in present_set:
                    self._missing_since[key] = None
                    continue
                since = self._missing_since.get(key)
                if since is None:
                    self._missing_since[key] = now
                elif now - since > self._grace_s:
                    del self._entries[key]
                    del self._missing_since[key]
