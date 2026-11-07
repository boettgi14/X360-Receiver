"""Tests for x360w.loop_guard: ending the process when the event loop is starved."""

import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w.loop_guard import LoopGuard  # noqa: E402

FAST = dict(interval_s=0.05, stale_s=0.3, confirm_s=0.3)


def run_loop(body, guard):
    async def main():
        guard.start(asyncio.get_running_loop())
        try:
            await body()
        finally:
            guard.stop()

    asyncio.run(main())


class LoopGuardTests(unittest.TestCase):
    def setUp(self):
        self.fired = threading.Event()
        self.guard = LoopGuard(self.fired.set, **FAST)

    def test_a_healthy_loop_is_left_alone(self):
        async def body():
            for _ in range(20):  # 1 s of ordinary work with awaits
                await asyncio.sleep(0.05)

        run_loop(body, self.guard)
        self.assertFalse(self.fired.is_set())

    def test_a_starved_loop_is_reported_once(self):
        calls = []
        guard = LoopGuard(lambda: calls.append(time.monotonic()), **FAST)

        async def body():
            time.sleep(1.2)  # a loop that never gets back to the event loop, like Decky's spinning socket reader

        run_loop(body, guard)
        self.assertEqual(len(calls), 1)

    def test_it_fires_well_before_deckys_five_seconds(self):
        started = time.monotonic()
        fired_at = []
        guard = LoopGuard(lambda: fired_at.append(time.monotonic() - started))  # the real default limits

        async def body():
            time.sleep(3.6)

        run_loop(body, guard)
        self.assertEqual(len(fired_at), 1)
        self.assertLess(fired_at[0], 3.2)  # stale 1.5 s + confirmation 1.0 s + polling; Decky waits 5 s

    def test_a_short_stall_is_forgiven(self):
        async def body():
            await asyncio.sleep(0.1)
            time.sleep(0.45)  # longer than stale_s, shorter than stale_s + confirm_s
            await asyncio.sleep(0.6)

        run_loop(body, self.guard)
        self.assertFalse(self.fired.is_set())

    def test_stop_disarms_it(self):
        async def body():
            self.guard.stop()
            time.sleep(1.0)

        run_loop(body, self.guard)
        self.assertFalse(self.fired.is_set())

    def test_stop_during_the_confirmation_wait_also_disarms_it(self):
        async def body():
            time.sleep(0.45)  # stale is detected, the confirmation wait begins
            self.guard.stop()
            time.sleep(0.8)

        run_loop(body, self.guard)
        self.assertFalse(self.fired.is_set())

    def test_the_watching_thread_is_a_daemon_so_it_never_keeps_the_process_alive(self):
        async def body():
            self.assertTrue(self.guard._thread.daemon)

        run_loop(body, self.guard)


if __name__ == "__main__":
    unittest.main()
