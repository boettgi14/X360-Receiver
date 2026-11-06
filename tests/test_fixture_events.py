"""Tests against the capture of 2026-11-05 with LED commands, buttons, re-binding and turning off.

Sequence (seconds since the start): idle; LED command 10 at 114.3 s and 2 at 132.4 s; A, B, Guide
tapped at 137.7 / 139.2 / 140.2 s; xpad unbound at 201.7 s and bound at 213.3 s; Guide held
from 223.8 s to 228.9 s; controller switched back on at 241.3 s. Complete, not cut off.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import (  # noqa: E402
    ConnectionEvent,
    InputReport,
    LinkReport,
    ReceiverMonitor,
    StateReport,
    build_led,
    build_poweroff,
    build_status_request,
    decode_in_packet,
    parse_usbmon_line,
)

FIXTURE = ROOT / "tests" / "fixtures" / "capture_events_gamepad_2026-11-05.txt"
SPAN = 246.711


class EventCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = [
            r for r in (parse_usbmon_line(l) for l in FIXTURE.read_text(encoding="ascii").splitlines()) if r
        ]
        cls.t0 = cls.records[0].timestamp_us
        cls.out = [((r.timestamp_us - cls.t0) / 1e6, r) for r in cls.records if r.direction == "o" and r.event == "S"]
        cls.inc = [
            ((r.timestamp_us - cls.t0) / 1e6, r, decode_in_packet(r.data))
            for r in cls.records
            if r.direction == "i" and r.event == "C" and r.data
        ]

    def at(self, t, tol=0.01):
        return [(tt, r, rep) for tt, r, rep in self.inc if abs(tt - t) <= tol]

    def test_complete_and_clean_end(self):
        self.assertAlmostEqual((self.records[-1].timestamp_us - self.t0) / 1e6, SPAN, places=2)

    def test_out_commands_in_order_and_endpoint(self):
        expected = [
            (114.3, build_led(10)),
            (132.4, build_led(2)),
            (201.7, build_led(0)),          # xpad when unbinding
            (213.3, build_status_request()),  # xpad when binding: presence request
            (213.3, build_led(2)),
            (228.9, build_poweroff()),
            (228.9, build_led(0)),
            (241.3, build_led(2)),
        ]
        got = [(round(t, 1), r.data) for t, r in self.out]
        self.assertEqual(got, expected)
        self.assertEqual({r.endpoint for _, r in self.out}, {1})  # LED xpad0 belongs to slot 1 (endpoint 1)

    def test_led_and_buttons_trigger_no_state(self):
        start, end = 114.0, 141.0
        states = [rep for t, _, rep in self.inc if start <= t <= end and isinstance(rep, (StateReport, LinkReport))]
        self.assertEqual(states, [])
        inputs = [(round(t, 1), rep.buttons) for t, _, rep in self.inc
                  if start <= t <= end and isinstance(rep, InputReport) and rep.buttons]
        self.assertEqual(inputs, [(137.7, 0x1000), (139.2, 0x2000), (140.2, 0x0400)])  # A, B, Guide

    def test_rebind_returns_connection_and_link_but_no_state_burst(self):
        window = [(round(t, 3), rep) for t, _, rep in self.inc if 213.2 <= t <= 220.0]
        kinds = [type(rep).__name__ for _, rep in window]
        self.assertEqual(kinds.count("ConnectionEvent"), 1)
        self.assertEqual(kinds.count("LinkReport"), 1)
        self.assertEqual(kinds.count("StateReport"), 0)
        link = next(rep for _, rep in window if isinstance(rep, LinkReport))
        self.assertEqual(int(link.state.battery_level), 2)
        self.assertEqual(link.state.unknown_bit, 1)

    def test_link_report_is_byte_identical_after_rebind_and_after_real_connect(self):
        links = [r.data for _, r, rep in self.inc if isinstance(rep, LinkReport)]
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0], links[1])

    def test_guide_hold_triggers_poweroff_after_five_seconds_on_next_packet(self):
        guide_down = next(t for t, _, rep in self.inc if isinstance(rep, InputReport) and rep.buttons == 0x0400 and t > 220)
        poweroff = next(t for t, r in self.out if r.data == build_poweroff())
        self.assertAlmostEqual(poweroff - guide_down, 5.056, places=2)
        release = self.at(poweroff)
        self.assertTrue(any(isinstance(rep, InputReport) and rep.buttons == 0 for _, _, rep in release))

    def test_poweroff_is_followed_by_state_power0_then_disconnect(self):
        poweroff = next(t for t, r in self.out if r.data == build_poweroff())
        after = [(t - poweroff, rep) for t, _, rep in self.inc if poweroff < t < poweroff + 1.0
                 and isinstance(rep, (StateReport, ConnectionEvent))]
        self.assertEqual(len(after), 2)
        state = after[0][1]
        self.assertIsInstance(state, StateReport)
        self.assertEqual(state.power_state, 0)
        self.assertEqual(int(state.battery_level), 2)
        self.assertEqual(after[1][1], ConnectionEvent(False, False))
        self.assertLess(after[1][0], 0.1)

    def test_monitor_marks_link_only_state_and_final_report(self):
        monitor = ReceiverMonitor()
        monitor.set_watched([(1, 2)])
        seen = {}
        for r in self.records:
            now = (r.timestamp_us - self.t0) / 1e6
            monitor.feed(r, now)
            slot = monitor.snapshot(now)[0]["slots"][0]
            if 213.289 <= now < 213.4:
                seen["rebind"] = (slot["battery_level"], slot["state_source"])
            if 241.28 <= now < 241.31:
                seen["after_connect"] = slot["state_source"]
        self.assertEqual(seen["rebind"][1], "link")
        self.assertEqual(seen["after_connect"], "report")
        final = monitor.snapshot(SPAN)[0]["slots"][0]
        self.assertEqual(final["power_state_raw"], 2)
        self.assertIsNotNone(final["last_poweroff_age_s"])
        self.assertEqual(final["last_led_mode"], 2)


if __name__ == "__main__":
    unittest.main()
