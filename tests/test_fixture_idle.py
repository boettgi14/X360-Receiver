"""Tests against the capture of 2026-11-05 (same receiver, one gamepad, about 393 s).

Sequence in the capture: controller off and on again (at 6.4 s / 13.1 s), then about 380 s without
any operation except a single input at 73.5 s. grep buffered the file and it was cut off at
12288 bytes; the last incomplete line is missing. The planned LED test, holding the Guide button
for 5 seconds and the button presses are NOT in it.
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
    UnknownReport,
    build_led,
    decode_in_packet,
    parse_usbmon_line,
)

FIXTURE = ROOT / "tests" / "fixtures" / "capture_idle_gamepad_2026-11-05.txt"


class IdleCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = [
            r for r in (parse_usbmon_line(l) for l in FIXTURE.read_text(encoding="ascii").splitlines()) if r
        ]
        cls.t0 = cls.records[0].timestamp_us
        cls.incoming = [
            ((r.timestamp_us - cls.t0) / 1e6, r, decode_in_packet(r.data))
            for r in cls.records
            if r.direction == "i" and r.event == "C" and r.data
        ]

    def test_span_and_connection(self):
        self.assertAlmostEqual((self.records[-1].timestamp_us - self.t0) / 1e6, 393.4, places=1)
        events = [(round(t, 1), rep) for t, _, rep in self.incoming if isinstance(rep, ConnectionEvent)]
        self.assertEqual(events, [(6.4, ConnectionEvent(False, False)), (13.1, ConnectionEvent(True, False))])

    def test_no_further_state_after_connect(self):
        """Key result: when idle, no further state packet arrives after connecting."""
        connect = next(t for t, _, rep in self.incoming if rep == ConnectionEvent(True, False))
        late = [t for t, _, rep in self.incoming if t > connect + 1.0 and isinstance(rep, (StateReport, LinkReport))]
        self.assertEqual(late, [])
        late_inputs = [t for t, _, rep in self.incoming if t > connect + 1.0 and isinstance(rep, InputReport)]
        self.assertEqual([round(t, 1) for t in late_inputs], [73.5])
        late_state_in_input = [rep for t, _, rep in self.incoming
                               if t > connect + 1.0 and isinstance(rep, InputReport) and rep.state]
        self.assertEqual(late_state_in_input, [])

    def test_state_burst_at_connect_has_same_value_everywhere(self):
        values = set()
        for t, _, rep in self.incoming:
            if t < 13.0 or t > 14.0:
                continue
            if isinstance(rep, StateReport):
                values.add(rep.battery_level)
            elif isinstance(rep, LinkReport) and rep.state:
                values.add(rep.state.battery_level)
            elif isinstance(rep, InputReport) and rep.state:
                values.add(rep.state.battery_level)
        self.assertEqual([int(v) for v in values], [2])

    def test_state_can_ride_on_input_frame(self):
        carriers = [rep for _, _, rep in self.incoming if isinstance(rep, InputReport) and rep.state]
        self.assertEqual(len(carriers), 1)
        self.assertEqual(carriers[0].state.power_state, 2)

    def test_only_xpad_led_commands_in_window(self):
        out = [r.data for r in self.records if r.direction == "o" and r.event == "S"]
        self.assertEqual(out, [build_led(0), build_led(2)])

    def test_f8_toggle_strictly_alternates_with_slow_spacing(self):
        pulses = [(t, rep.raw[2]) for t, _, rep in self.incoming
                  if isinstance(rep, UnknownReport) and rep.packet_type == 0xF8]
        self.assertEqual(len(pulses), 50)
        values = [v for _, v in pulses]
        self.assertTrue(all(a != b for a, b in zip(values, values[1:])))
        self.assertEqual(set(values), {1, 2})
        gaps = [b[0] - a[0] for a, b in zip(pulses, pulses[1:])]
        self.assertGreater(min(gaps), 2.0)

    def test_monitor_keeps_connect_time_value_with_age(self):
        monitor = ReceiverMonitor()
        monitor.set_watched([(1, 2)])
        end = 0.0
        for _, r, _ in [(0, r, 0) for r in self.records]:
            now = (r.timestamp_us - self.t0) / 1e6
            monitor.feed(r, now)
            end = now
        slot = monitor.snapshot(end)[0]["slots"][0]
        self.assertTrue(slot["connected"])
        self.assertEqual(slot["battery_level"], 2)
        self.assertGreater(slot["state_age_s"], 375)
        self.assertEqual(slot["input_count"], 3)
        # empty packet, f8 01, f8 02 and the three follow-up header packets 20 1D / 30 03 / 40 01
        self.assertEqual(len(slot["unknown"]), 6)


if __name__ == "__main__":
    unittest.main()
