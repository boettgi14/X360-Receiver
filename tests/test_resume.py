"""Tests for x360w.resume: detecting a resume from suspend with two clocks."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w.resume import ResumeDetector  # noqa: E402


class Clocks:
    def __init__(self):
        self.wall = 1_000_000.0
        self.mono = 500.0

    def advance(self, seconds, asleep=0.0):
        """Time passes: both clocks advance, the wall clock additionally by the time spent suspended."""
        self.mono += seconds
        self.wall += seconds + asleep


class ResumeDetectorTests(unittest.TestCase):
    def setUp(self):
        self.clocks = Clocks()
        self.detector = ResumeDetector(lambda: self.clocks.wall, lambda: self.clocks.mono, gap_s=10.0)

    def test_normal_ticks_are_not_a_resume(self):
        for _ in range(5):
            self.clocks.advance(5.0)
            self.assertFalse(self.detector.check())

    def test_suspend_is_detected_once(self):
        self.clocks.advance(5.0)
        self.assertFalse(self.detector.check())
        self.clocks.advance(5.0, asleep=3600.0)  # an hour in suspend
        self.assertTrue(self.detector.check())
        self.clocks.advance(5.0)
        self.assertFalse(self.detector.check())

    def test_a_delayed_tick_is_not_a_suspend(self):
        self.clocks.advance(30.0)  # the process was just busy; both clocks agree
        self.assertFalse(self.detector.check())

    def test_clock_changes_below_the_gap_are_ignored(self):
        self.clocks.advance(5.0, asleep=2.0)  # e.g. a small time correction
        self.assertFalse(self.detector.check())


if __name__ == "__main__":
    unittest.main()
