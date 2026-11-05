"""Zwischenspeicher für aktiv abgefragte Akkustände (Akkuanfrage über den kurzen Zugriff).

Der Receiver meldet den Akku von sich aus nur beim Verbinden. Ein Controller, der schon vor dem
Start des Plugins verbunden war, hat daher ohne aktive Anfrage nie einen Wert. Das Ergebnis der
Anfrage steht hier, damit die Oberfläche es auch ohne den usbmon-Monitor zeigen kann.

Ein Eintrag verfällt, wenn sein Slot länger als `grace_s` nicht mehr als verbunden gesehen wurde.
Die Frist ist nötig, weil der Controller während der Anfrage selbst für einige Sekunden aus dem
System verschwindet (xpad ist gelöst); das ist keine echte Trennung.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

Key = Tuple[int, int, int]  # (Bus, Gerät, Slot)

GRACE_S = 15.0


class BatteryCache:
    def __init__(self, clock: Callable[[], float] = time.time, grace_s: float = GRACE_S) -> None:
        self._clock = clock
        self._grace_s = grace_s
        self._lock = threading.Lock()
        self._entries: Dict[Key, dict] = {}
        self._missing_since: Dict[Key, Optional[float]] = {}

    def store(self, key: Key, state: dict) -> None:
        """`state` ist das Statuswörterbuch aus `actions.query_battery`."""
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
        """Verwirft Einträge von Slots, die länger als die Frist nicht mehr verbunden waren."""
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
