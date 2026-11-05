"""Tests gegen reale Beispielpakete aus der xboxdrv-PROTOCOL-Datei."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w import (  # noqa: E402
    BatteryLevel,
    ConnectionEvent,
    LinkReport,
    StateReport,
    UnknownReport,
    build_battery_request,
    build_capabilities_request,
    build_led,
    build_poweroff,
    build_rumble,
    build_status_request,
    decode_in_packet,
    parse_usbmon_line,
)


def pkt(*head: int, total: int = 29) -> bytes:
    data = bytes(head)
    return data + bytes(total - len(data))


class DecodeTests(unittest.TestCase):
    def test_connection_controller(self):
        self.assertEqual(
            decode_in_packet(bytes([0x08, 0x80])), ConnectionEvent(True, False)
        )

    def test_connection_controller_and_headset(self):
        self.assertEqual(
            decode_in_packet(bytes([0x08, 0xC0])), ConnectionEvent(True, True)
        )

    def test_connection_none(self):
        self.assertEqual(
            decode_in_packet(bytes([0x08, 0x00])), ConnectionEvent(False, False)
        )

    def test_state_a2(self):
        # xboxdrv-Beispiel "Battery Message?": 00 00 00 13 a2
        state = decode_in_packet(pkt(0x00, 0x00, 0x00, 0x13, 0xA2))
        self.assertIsInstance(state, StateReport)
        self.assertEqual(state.vibration_level, 3)
        self.assertFalse(state.headset)
        self.assertFalse(state.chatpad)
        self.assertEqual(state.battery_type, 1)
        self.assertEqual(state.power_state, 2)
        self.assertEqual(state.battery_level, BatteryLevel.MEDIUM)

    def test_state_e0_e2_e6_full(self):
        for b1, expected_type in ((0xE0, 0), (0xE2, 1), (0xE6, 3)):
            state = decode_in_packet(pkt(0x00, 0x00, 0x00, 0x13, b1))
            self.assertEqual(state.battery_level, BatteryLevel.FULL)
            self.assertEqual(state.battery_type, expected_type)

    def test_state_headset_flag(self):
        state = decode_in_packet(pkt(0x00, 0x00, 0x00, 0x17, 0xE0))
        self.assertTrue(state.headset)
        self.assertFalse(state.chatpad)

    def test_non_state_type0_is_unknown(self):
        # Marker-Nibble != 0x1 muss ignoriert werden (laut argon.md)
        for head in ((0x00, 0x00, 0x00, 0xF0, 0x00), (0x00, 0x00, 0x00, 0x20, 0x1D)):
            self.assertIsInstance(decode_in_packet(pkt(*head)), UnknownReport)

    def test_link_report(self):
        raw = bytes.fromhex(
            "000f00f0f0cc"  # Header (5) + 0xCC
            "fd1f9f70"      # unk1
            "c90063b0"      # deviceID
            "00"            # type
            "05"            # revision
            "13a7"          # state
            "201d"          # protocol
            "3003"          # unk2
            "400150"        # vendorIDData
            "01"            # subtype
            "ffffff"
        )
        self.assertEqual(len(raw), 29)
        report = decode_in_packet(raw)
        self.assertIsInstance(report, LinkReport)
        self.assertEqual(report.subtype, 0x01)
        self.assertEqual(report.subtype_name, "Gamepad")
        self.assertEqual(report.protocol, 0x1D20)
        self.assertEqual(report.device_id, 0xB06300C9)
        self.assertEqual(report.state.battery_level, BatteryLevel.MEDIUM)
        self.assertEqual(report.vendor_id_data, bytes([0x40, 0x01, 0x50]))

    def test_too_short(self):
        self.assertIsNone(decode_in_packet(b"\x00"))


class BuildTests(unittest.TestCase):
    def test_lengths(self):
        for builder in (
            build_status_request,
            build_battery_request,
            build_capabilities_request,
            build_poweroff,
        ):
            self.assertEqual(len(builder()), 12)

    def test_documented_bytes(self):
        self.assertEqual(build_poweroff(), bytes.fromhex("0000 08c0 0000 0000 0000 0000".replace(" ", "")))
        self.assertEqual(build_battery_request(), bytes.fromhex("00000040" + "00" * 8))
        self.assertEqual(build_capabilities_request(), bytes.fromhex("00000280" + "00" * 8))
        self.assertEqual(build_status_request(), bytes.fromhex("08000fc0" + "00" * 8))

    def test_led(self):
        self.assertEqual(build_led(6)[3], 0x46)
        self.assertEqual(build_led(0)[3], 0x40)
        with self.assertRaises(ValueError):
            build_led(16)

    def test_rumble_matches_kernel_layout(self):
        packet = build_rumble(0x80, 0x40)
        self.assertEqual(packet[:7], bytes([0x00, 0x01, 0x0F, 0xC0, 0x00, 0x80, 0x40]))
        self.assertEqual(len(packet), 12)


class UsbmonTests(unittest.TestCase):
    LINE = (
        "ffff8881 3539437764 C Ii:1:004:1 0:8 29 = "
        "00000013 a2000000 00000000 00000000 00000000 00000000 00000000 00"
    )

    def test_parse_in_completion(self):
        record = parse_usbmon_line(self.LINE)
        self.assertIsNotNone(record)
        self.assertEqual((record.bus, record.device, record.endpoint), (1, 4, 1))
        self.assertEqual(record.direction, "i")
        self.assertEqual(record.event, "C")
        self.assertEqual(len(record.data), 29)
        state = decode_in_packet(record.data)
        self.assertEqual(state.battery_level, BatteryLevel.MEDIUM)

    def test_ignores_control_setup_lines(self):
        line = "d5ea89a0 3575914555 S Ci:1:001:0 s a3 00 0000 0003 0004 4 <"
        self.assertIsNone(parse_usbmon_line(line))

    def test_garbage(self):
        self.assertIsNone(parse_usbmon_line(""))
        self.assertIsNone(parse_usbmon_line("not a usbmon line at all really"))


if __name__ == "__main__":
    unittest.main()
