"""Tests für x360w.battery_cache: abgefragte Akkustände mit Alter und Verfallsfrist."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w.battery_cache import BatteryCache  # noqa: E402

STATE = {"battery_level": 2, "battery_type_raw": 1, "power_state_raw": 2, "vibration_level": 0}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class BatteryCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = BatteryCache(self.clock, grace_s=15.0)

    def test_store_and_age(self):
        self.cache.store((1, 2, 0), STATE)
        self.clock.now += 42
        entry = self.cache.snapshot()[(1, 2, 0)]
        self.assertEqual((entry["battery_level"], entry["battery_type_raw"], entry["power_state_raw"]), (2, 1, 2))
        self.assertAlmostEqual(entry["age_s"], 42.0)

    def test_newer_value_replaces_older(self):
        self.cache.store((1, 2, 0), STATE)
        self.clock.now += 100
        self.cache.store((1, 2, 0), dict(STATE, battery_level=1))
        entry = self.cache.snapshot()[(1, 2, 0)]
        self.assertEqual(entry["battery_level"], 1)
        self.assertAlmostEqual(entry["age_s"], 0.0)

    def test_short_absence_keeps_entry(self):
        # Während der Anfrage verschwindet der Controller selbst kurz aus dem System.
        self.cache.store((1, 2, 0), STATE)
        self.cache.prune([])
        self.clock.now += 10
        self.cache.prune([])
        self.assertIn((1, 2, 0), self.cache.snapshot())

    def test_long_absence_drops_entry(self):
        self.cache.store((1, 2, 0), STATE)
        self.cache.prune([])
        self.clock.now += 16
        self.cache.prune([])
        self.assertEqual(self.cache.snapshot(), {})

    def test_return_resets_absence(self):
        self.cache.store((1, 2, 0), STATE)
        self.cache.prune([])
        self.clock.now += 10
        self.cache.prune([(1, 2, 0)])  # wieder da
        self.clock.now += 10
        self.cache.prune([])  # neue Abwesenheit beginnt erst jetzt
        self.clock.now += 10
        self.cache.prune([])
        self.assertIn((1, 2, 0), self.cache.snapshot())

    def test_only_absent_slots_are_dropped(self):
        self.cache.store((1, 2, 0), STATE)
        self.cache.store((1, 2, 1), STATE)
        self.cache.prune([(1, 2, 1)])
        self.clock.now += 20
        self.cache.prune([(1, 2, 1)])
        self.assertEqual(set(self.cache.snapshot()), {(1, 2, 1)})


if __name__ == "__main__":
    unittest.main()
