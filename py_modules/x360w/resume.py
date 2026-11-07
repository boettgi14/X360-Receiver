"""Detects a resume from suspend, so the usbmon readers can be rebuilt afterwards.

On Linux `CLOCK_MONOTONIC` does not advance while the system is suspended, the wall clock does.
If the wall clock moved on by clearly more than the monotonic clock between two checks, the system
has been asleep in between.

ASSUMPTION (not verified on a device): after a resume the open usbmon handles may stay silent, so the
plugin restarts them. Restarting is harmless if they would have kept working.
"""

from __future__ import annotations

import time
from typing import Callable

SUSPEND_GAP_S = 10.0  # well above normal scheduling delays, well below any real suspend


class ResumeDetector:
    def __init__(
        self,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        gap_s: float = SUSPEND_GAP_S,
    ) -> None:
        self._wall = wall
        self._mono = mono
        self._gap_s = gap_s
        self._last_wall = wall()
        self._last_mono = mono()

    def check(self) -> bool:
        """True if the system was suspended since the last call. Call this regularly."""
        wall, mono = self._wall(), self._mono()
        slept = (wall - self._last_wall) - (mono - self._last_mono)
        self._last_wall, self._last_mono = wall, mono
        return slept > self._gap_s
