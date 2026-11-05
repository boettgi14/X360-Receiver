"""Tests gegen den Mitschnitt vom 2026-11-05 (gleicher Receiver, ein Gamepad, ca. 393 s).

Ablauf im Mitschnitt: Controller aus und wieder ein (bei 6,4 s / 13,1 s), danach ca. 380 s ohne
Bedienung bis auf eine einzelne Eingabe bei 73,5 s. Die Datei wurde von grep gepuffert und bei
12288 Byte abgeschnitten; die letzte unvollständige Zeile fehlt. Der geplante LED-Test, das
5-Sekunden-Halten der Guide-Taste und die Tastendrücke stehen NICHT darin.
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
        """Kern-Ergebnis: Im Leerlauf kommt nach dem Verbinden kein weiteres Statuspaket."""
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
        # leeres Paket, f8 01, f8 02 und die drei Header-Folgepakete 20 1D / 30 03 / 40 01
        self.assertEqual(len(slot["unknown"]), 6)


if __name__ == "__main__":
    unittest.main()
