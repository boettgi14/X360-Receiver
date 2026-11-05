"""Tests für x360w.shutdown: Ausschalten mehrerer Ziele mit Zeitlimit."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w import actions, shutdown  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class PowerOffTargetsTests(unittest.TestCase):
    def run_targets(self, fake, targets, deadline=6.0):
        clock = Clock()
        wrapped = lambda *a, **k: (setattr(clock, "now", clock.now + 0.5), fake(*a, **k))[1]  # jeder Zugriff kostet 0,5 s
        return shutdown.power_off_targets(targets, wrapped, deadline, clock, clock.sleep)

    def test_all_ok_in_order(self):
        calls = []
        fake = lambda bus, dev, slot: calls.append((bus, dev, slot)) or {"ok": True, "confirmed": slot == 0}
        result = self.run_targets(fake, [(1, 4, 0), (1, 4, 1)])
        self.assertEqual(calls, [(1, 4, 0), (1, 4, 1)])
        self.assertEqual(result, {"ok": True, "sent": 2, "confirmed": 1, "errors": []})

    def test_busy_is_retried_then_succeeds(self):
        answers = [{"ok": False, "error": actions.BUSY_ERROR}, {"ok": False, "error": actions.BUSY_ERROR}, {"ok": True, "confirmed": True}]
        result = self.run_targets(lambda *a, **k: answers.pop(0), [(1, 4, 0)])
        self.assertTrue(result["ok"])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(answers, [])

    def test_busy_forever_stops_at_deadline(self):
        result = self.run_targets(lambda *a, **k: {"ok": False, "error": actions.BUSY_ERROR}, [(1, 4, 0)], deadline=2.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["sent"], 0)
        self.assertIn(actions.BUSY_ERROR, result["errors"][0])

    def test_error_in_one_slot_does_not_stop_the_others(self):
        def fake(bus, dev, slot):
            return {"ok": False, "error": "kaputt"} if slot == 1 else {"ok": True, "confirmed": False}

        result = self.run_targets(fake, [(1, 4, 0), (1, 4, 1), (1, 4, 2)])
        self.assertEqual(result["sent"], 2)
        self.assertEqual(result["errors"], ["Bus 1 Gerät 4 Slot 2: kaputt"])

    def test_deadline_skips_remaining_targets(self):
        calls = []
        fake = lambda bus, dev, slot: calls.append(slot) or {"ok": True, "confirmed": True}
        result = self.run_targets(fake, [(1, 4, s) for s in range(4)], deadline=1.0)  # 2 Zugriffe passen hinein
        self.assertEqual(calls, [0, 1])
        self.assertFalse(result["ok"])
        self.assertIn("2 Slot(s) nicht mehr erreicht", result["errors"][-1])

    def test_uses_current_actions_power_off_by_default(self):
        original = actions.power_off
        seen = []
        actions.power_off = lambda bus, dev, slot: seen.append(slot) or {"ok": True, "confirmed": True}
        try:
            shutdown.power_off_targets([(1, 4, 3)])
        finally:
            actions.power_off = original
        self.assertEqual(seen, [3])


if __name__ == "__main__":
    unittest.main()
