"""Ends the process when the asyncio event loop is starved, so Decky does not have to kill it.

Why: Decky's plugin process reads its socket in a loop (`_listen_for_method_call`, Decky source read
2026-11-07). When Decky closes its end of the socket while stopping the plugin, that loop gets an empty read
every time, does not stop, creates a task per iteration and never gives the event loop a chance to run. The
journal of the user's device shows exactly this: the main thread stuck in `asyncio.create_task`, SIGTERM never
handled on a plain reload, and `_unload` stopping at its first real `await`. The plugin then stays alive until
Decky sends SIGKILL after 5 s.

What this does: the loop updates a heartbeat every `interval_s`; a daemon thread (not an asyncio thing, so it
keeps running while the loop is starved) watches it. If the heartbeat is older than `stale_s` and still has not
moved after `confirm_s`, the loop is starved, and `on_starved` is called (the plugin ends the process). A stall
shorter than `stale_s + confirm_s` is forgiven, e.g. the process being frozen for a moment. `stop()` disarms it
(done first thing in `_unload`, which has its own exit watchdog).
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

INTERVAL_S = 0.25
STALE_S = 1.5
CONFIRM_S = 1.0


class LoopGuard:
    def __init__(
        self,
        on_starved: Callable[[], None],
        interval_s: float = INTERVAL_S,
        stale_s: float = STALE_S,
        confirm_s: float = CONFIRM_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_starved = on_starved
        self._interval_s = interval_s
        self._stale_s = stale_s
        self._confirm_s = confirm_s
        self._clock = clock
        self._beat = clock()
        self._stopped = threading.Event()
        self._loop = None
        self._thread: Optional[threading.Thread] = None

    # -- runs on the event loop ----------------------------------------------

    def start(self, loop) -> None:
        """Call from the loop's thread. Starts the heartbeat and the watching thread."""
        self._loop = loop
        self._beat = self._clock()
        self._stopped.clear()
        loop.call_later(self._interval_s, self._tick)
        self._thread = threading.Thread(target=self._watch, name="x360w-loop-guard", daemon=True)
        self._thread.start()

    def _tick(self) -> None:
        if self._stopped.is_set():
            return
        self._beat = self._clock()
        self._loop.call_later(self._interval_s, self._tick)

    def stop(self) -> None:
        self._stopped.set()

    # -- runs in the watching thread -----------------------------------------

    def _starved_now(self) -> bool:
        return self._clock() - self._beat > self._stale_s

    def _watch(self) -> None:
        while not self._stopped.wait(self._interval_s):
            if not self._starved_now():
                continue
            seen = self._beat
            if self._stopped.wait(self._confirm_s):
                return
            if self._beat == seen and self._starved_now():  # still no heartbeat: the loop is really starved
                self._on_starved()
                return
