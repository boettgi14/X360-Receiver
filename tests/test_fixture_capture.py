"""Tests gegen einen echten Mitschnitt (Bazzite, Receiver 045e:0719, ein Gamepad).

Aufgezeichnet am 2026-11-04 über usbmon, gefiltert auf den Receiver. Enthält:
Trennen, erneutes Verbinden, Link-Report, Statuspaket und Tastendrücke.
Nicht enthalten: Guide-Taste, Start/Back, Ausschalten, Akkuwechsel.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import (  # noqa: E402
    BatteryLevel,
    ConnectionEvent,
    InputReport,
    LinkReport,
    StateReport,
    build_led,
    decode_in_packet,
    parse_usbmon_line,
)

FIXTURE = ROOT / "tests" / "fixtures" / "capture_connect_gamepad_2026-11-04.txt"


def load():
    records = []
    for line in FIXTURE.read_text(encoding="ascii").splitlines():
        record = parse_usbmon_line(line)
        if record is not None:
            records.append(record)
    return records


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load()
        cls.incoming = [
            (r, decode_in_packet(r.data))
            for r in cls.records
            if r.direction == "i" and r.event == "C" and r.data
        ]
        cls.outgoing = [r for r in cls.records if r.direction == "o" and r.event == "S" and r.data]

    def test_connection_sequence(self):
        events = [rep for _, rep in self.incoming if isinstance(rep, ConnectionEvent)]
        self.assertEqual(events, [ConnectionEvent(False, False), ConnectionEvent(True, False)])

    def test_link_report_is_gamepad(self):
        links = [rep for _, rep in self.incoming if isinstance(rep, LinkReport)]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].subtype, 0x01)
        self.assertEqual(links[0].protocol, 0x1D20)

    def test_single_state_packet(self):
        states = [rep for _, rep in self.incoming if isinstance(rep, StateReport)]
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.battery_level, BatteryLevel.MEDIUM)  # Zuordnung ungeprüft
        self.assertEqual(state.battery_type, 1)
        self.assertEqual(state.power_state, 2)
        self.assertFalse(state.headset or state.chatpad)

    def test_xpad_led_commands_match_our_encoder(self):
        # xpad sendet beim Trennen LED 0 (aus) und beim Verbinden LED 2 (Slot 1)
        self.assertEqual([r.data for r in self.outgoing], [build_led(0), build_led(2)])

    def test_button_masks_follow_xinput_layout(self):
        masks = {rep.buttons for _, rep in self.incoming if isinstance(rep, InputReport)}
        for expected in (0x1000, 0x2000, 0x4000, 0x8000,  # A B X Y
                         0x0100, 0x0200,                  # LB RB
                         0x0040, 0x0080,                  # L3 R3
                         0x0001, 0x0002, 0x0004, 0x0008):  # D-Pad
            self.assertIn(expected, masks)

    def test_triggers_reach_full_range(self):
        inputs = [rep for _, rep in self.incoming if isinstance(rep, InputReport)]
        self.assertEqual(max(r.left_trigger for r in inputs), 255)
        self.assertEqual(max(r.right_trigger for r in inputs), 255)


if __name__ == "__main__":
    unittest.main()
