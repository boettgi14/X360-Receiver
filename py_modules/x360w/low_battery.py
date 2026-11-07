"""Finds controllers whose battery level has just become low, to notify the user once.

ASSUMPTION (not verified on a device): level 0 means empty and level 1 low, as in XInput (the plugin
has only ever seen level 2). The receiver reports the level only when a controller connects (or when it is
queried), so a notice appears at those moments, not while a battery drains.

A controller is notified once. It is notified again only after its level has gone back above the
threshold, or after it has been gone for longer than `grace_s` (a power cycle). The grace period is needed
because the controller itself disappears for a few seconds during a battery query (xpad is unbound).
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Iterable, List, Set, Tuple

Key = Tuple[int, int, int]  # (bus, device, slot)

LOW_LEVEL = 1  # levels 0..LOW_LEVEL count as low
GRACE_S = 15.0


class LowBatteryWatcher:
    def __init__(self, max_level: int = LOW_LEVEL, grace_s: float = GRACE_S,
                 clock: Callable[[], float] = time.time) -> None:
        self._max_level = max_level
        self._grace_s = grace_s
        self._clock = clock
        self._notified: Set[Key] = set()
        self._missing_since: Dict[Key, float] = {}

    def reset(self) -> None:
        self._notified.clear()
        self._missing_since.clear()

    def update(self, views: Iterable[dict]) -> List[dict]:
        """`views` as built by `view.build_receiver_views`. Returns new notices {bus, devnum, slot, level}."""
        now = self._clock()
        present: Dict[Key, object] = {}
        for receiver in views:
            bus, devnum = receiver.get("bus"), receiver.get("devnum")
            if bus is None or devnum is None:
                continue
            for controller in receiver["controllers"]:
                present[(bus, devnum, controller["slot"])] = controller.get("battery_level")

        notices: List[dict] = []
        for key, level in present.items():
            self._missing_since.pop(key, None)
            if not isinstance(level, int):
                continue  # level unknown: nothing to say, keep what we know
            if level <= self._max_level:
                if key not in self._notified:
                    self._notified.add(key)
                    notices.append({"bus": key[0], "devnum": key[1], "slot": key[2], "level": level})
            else:
                self._notified.discard(key)

        for key in list(self._notified):
            if key in present:
                continue
            since = self._missing_since.setdefault(key, now)
            if now - since > self._grace_s:
                self._notified.discard(key)
                del self._missing_since[key]
        return notices
