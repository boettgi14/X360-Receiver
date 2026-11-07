"""Tests for x360w.low_battery: notify once when a battery level becomes low."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w.low_battery import LowBatteryWatcher  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def views(*controllers, bus=1, devnum=2):
    """One receiver with controllers given as (slot, battery_level)."""
    return [{"bus": bus, "devnum": devnum,
             "controllers": [{"slot": slot, "battery_level": level} for slot, level in controllers]}]


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.watcher = LowBatteryWatcher(max_level=1, grace_s=15.0, clock=self.clock)

    def test_levels_zero_and_one_are_low_two_and_three_are_not(self):
        notices = self.watcher.update(views((0, 0), (1, 1), (2, 2), (3, 3)))
        self.assertEqual([(n["slot"], n["level"]) for n in notices], [(0, 0), (1, 1)])
        self.assertEqual(notices[0], {"bus": 1, "devnum": 2, "slot": 0, "level": 0})

    def test_notified_only_once_while_the_level_stays_low(self):
        self.assertEqual(len(self.watcher.update(views((0, 1)))), 1)
        self.assertEqual(self.watcher.update(views((0, 1))), [])
        self.assertEqual(self.watcher.update(views((0, 0))), [])  # getting emptier is not announced again

    def test_unknown_level_says_nothing_and_keeps_the_state(self):
        self.assertEqual(self.watcher.update(views((0, None))), [])
        self.watcher.update(views((0, 1)))
        self.assertEqual(self.watcher.update(views((0, None))), [])
        self.assertEqual(self.watcher.update(views((0, 1))), [])  # still the same notified controller

    def test_notified_again_after_the_level_went_back_up(self):
        self.watcher.update(views((0, 1)))
        self.assertEqual(self.watcher.update(views((0, 3))), [])  # new batteries
        self.assertEqual(len(self.watcher.update(views((0, 1)))), 1)

    def test_brief_absence_during_a_query_does_not_repeat_the_notice(self):
        self.watcher.update(views((0, 1)))
        self.assertEqual(self.watcher.update(views()), [])  # xpad is unbound for a few seconds
        self.clock.now += 10
        self.watcher.update(views())
        self.clock.now += 3
        self.assertEqual(self.watcher.update(views((0, 1))), [])

    def test_power_cycle_longer_than_the_grace_period_notifies_again(self):
        self.watcher.update(views((0, 1)))
        self.watcher.update(views())
        self.clock.now += 20
        self.watcher.update(views())
        self.assertEqual(len(self.watcher.update(views((0, 1)))), 1)

    def test_controllers_are_told_apart_by_receiver_and_slot(self):
        both = views((0, 1), bus=1, devnum=2) + views((0, 1), bus=3, devnum=7)
        self.assertEqual(len(self.watcher.update(both)), 2)
        self.assertEqual(self.watcher.update(both), [])

    def test_receiver_without_bus_is_skipped_and_reset_forgets(self):
        self.assertEqual(self.watcher.update([{"bus": None, "devnum": None, "controllers": [{"slot": 0, "battery_level": 0}]}]), [])
        self.watcher.update(views((0, 1)))
        self.watcher.reset()
        self.assertEqual(len(self.watcher.update(views((0, 1)))), 1)


if __name__ == "__main__":
    unittest.main()
