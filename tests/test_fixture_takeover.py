"""Tests against a capture made with tools/probe_takeover.py.

Sequence (seconds since the start, controller in slot 1 on): presence request at 41.3 s,
battery request at 64.0 s, turn-off at 85.4 s, after which the controller is switched back
on by hand at about 105.4 s. Each time xpad releases the interface (URB status -108) and
binds it again after about 2 s (its own presence request plus LED command).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import (  # noqa: E402
    ConnectionEvent,
    LinkReport,
    ReceiverMonitor,
    StateReport,
    build_battery_request,
    build_led,
    build_poweroff,
    build_status_request,
    decode_in_packet,
    parse_usbmon_line,
)

FIXTURE = ROOT / "tests" / "fixtures" / "capture_takeover.txt"


class TakeoverCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = [
            r for r in (parse_usbmon_line(l) for l in FIXTURE.read_text(encoding="ascii").splitlines()) if r
        ]
        cls.t0 = cls.records[0].timestamp_us
        rel = lambda r: (r.timestamp_us - cls.t0) / 1e6
        cls.out = [(rel(r), r.data) for r in cls.records if r.direction == "o" and r.event == "S"]
        cls.inc = [(rel(r), decode_in_packet(r.data)) for r in cls.records
                   if r.direction == "i" and r.event == "C" and r.data]
        cls.detached = [rel(r) for r in cls.records
                        if r.direction == "i" and r.event == "C" and str(r.status).startswith("-108")]

    def after(self, t, window=0.2):
        return [(round(tt - t, 3), rep) for tt, rep in self.inc if t <= tt <= t + window]

    def out_time(self, data, nth=0):
        return [t for t, d in self.out if d == data][nth]

    def test_xpad_is_detached_three_times(self):
        self.assertEqual([round(t) for t in self.detached], [41, 64, 85])

    def test_presence_request_is_answered_with_connection_and_link(self):
        t = self.out_time(build_status_request(), 0)
        kinds = [type(rep).__name__ for _, rep in self.after(t)]
        self.assertEqual(kinds, ["ConnectionEvent", "LinkReport"])

    def test_battery_request_is_answered_with_a_state_packet_within_50ms(self):
        t = self.out_time(build_battery_request())
        self.assertAlmostEqual(t, 64.04, places=2)
        states = [(dt, rep) for dt, rep in self.after(t, 0.5) if isinstance(rep, StateReport)]
        self.assertEqual(len(states), 1)
        dt, state = states[0]
        self.assertLess(dt, 0.05)
        self.assertEqual((int(state.battery_level), state.power_state, state.battery_type, state.unknown_bit),
                         (2, 2, 1, 0))

    def test_poweroff_gives_state_then_state_power0_then_disconnect(self):
        t = self.out_time(build_poweroff())
        got = [(rep.power_state if isinstance(rep, StateReport) else rep) for _, rep in self.after(t, 0.2)
               if isinstance(rep, (StateReport, ConnectionEvent))]
        self.assertEqual(got, [2, 0, ConnectionEvent(False, False)])

    def test_xpad_rebinds_after_each_run_with_presence_and_led(self):
        for run_end in (41.5, 64.5, 85.7):
            later = [(t, d) for t, d in self.out if run_end < t < run_end + 3.0]
            self.assertIn(build_status_request(), [d for _, d in later])
        t = self.out_time(build_status_request(), 1)
        self.assertEqual([d for tt, d in self.out if t <= tt <= t + 0.1],
                         [build_status_request(), build_led(2)])

    def test_after_poweroff_presence_says_gone_then_manual_poweron_reconnects_normally(self):
        poweroff = self.out_time(build_poweroff())
        later = [(round(t - poweroff, 1), rep) for t, rep in self.inc
                 if t > poweroff + 1.0 and isinstance(rep, (ConnectionEvent, LinkReport, StateReport))]
        self.assertEqual(later[0], (2.1, ConnectionEvent(False, False)))
        self.assertEqual(later[1], (20.0, ConnectionEvent(True, False)))
        self.assertIsInstance(later[2][1], LinkReport)
        self.assertIsInstance(later[3][1], StateReport)
        self.assertEqual(later[3][1].power_state, 2)
        # xpad (bound again) sets the player LED right after
        reconnect = poweroff + 20.0
        self.assertEqual([d for t, d in self.out if reconnect - 0.05 <= t <= reconnect + 0.05], [build_led(2)])

    def test_monitor_follows_the_whole_session(self):
        monitor = ReceiverMonitor()
        monitor.set_watched([(1, 2)])
        marks = {}
        for r in self.records:
            now = (r.timestamp_us - self.t0) / 1e6
            monitor.feed(r, now)
            slot = monitor.snapshot(now)[0]["slots"][0]
            if 85.49 <= now < 85.50:
                marks["state_power0"] = slot["power_state_raw"]
            if 85.51 <= now < 90:
                marks["after_off"] = slot["connected"]
        final = monitor.snapshot((self.records[-1].timestamp_us - self.t0) / 1e6)[0]["slots"][0]
        self.assertEqual(marks["state_power0"], 0)
        self.assertFalse(marks["after_off"])
        self.assertTrue(final["connected"])
        self.assertEqual(final["power_state_raw"], 2)
        self.assertEqual(final["state_source"], "report")
        self.assertIsNotNone(final["last_poweroff_age_s"])  # the monitor also sees the tool's command
        self.assertEqual(final["last_led_mode"], 2)


if __name__ == "__main__":
    unittest.main()
