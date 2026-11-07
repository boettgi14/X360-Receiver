"""Tests for ReceiverMonitor, UsbmonReader, MonitorService and controls."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import (  # noqa: E402
    MonitorService,
    ReceiverMonitor,
    UsbmonReader,
    build_led,
    build_poweroff,
    parse_usbmon_line,
)
from x360w import controls  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "capture_connect.txt"
LINES = FIXTURE.read_text(encoding="ascii").splitlines()


def replay(monitor, lines, start=1000.0):
    now = start
    for line in lines:
        record = parse_usbmon_line(line)
        if record is not None:
            monitor.feed(record, now)
            now += 0.01
    return now


def line(endpoint_dir, ep, data_hex, event="C", bus=1, dev=2):
    n = len(data_hex) // 2
    words = " ".join(data_hex[i:i + 8] for i in range(0, len(data_hex), 8))
    direction = endpoint_dir
    return (f"ffff0000 1000 {event} I{direction}:{bus}:{dev:03d}:{ep} 0:1 {n} = {words}")


class MonitorFixtureTests(unittest.TestCase):
    def setUp(self):
        self.monitor = ReceiverMonitor()
        self.monitor.set_watched([(1, 2)])
        self.end = replay(self.monitor, LINES)

    def slots(self):
        return self.monitor.snapshot(self.end)[0]["slots"]

    def test_slot0_state_from_real_capture(self):
        s = self.slots()[0]
        self.assertTrue(s["connected"])
        self.assertFalse(s["connected_inferred"])
        self.assertEqual(s["subtype_name"], "Gamepad")
        self.assertEqual(s["battery_level"], 2)
        self.assertEqual(s["battery_type_raw"], 1)
        self.assertEqual(s["power_state_raw"], 2)
        self.assertGreater(s["input_count"], 50)
        self.assertEqual(s["last_led_mode"], 2)
        self.assertIsNone(s["last_poweroff_age_s"])

    def test_other_slots_untouched(self):
        for s in self.slots()[1:]:
            self.assertFalse(s["connected"])
            self.assertIsNone(s["battery_level"])

    def test_unwatched_device_is_ignored(self):
        monitor = ReceiverMonitor()
        monitor.set_watched([(1, 9)])
        replay(monitor, LINES)
        self.assertEqual(monitor.snapshot(0)[0]["slots"][0]["input_count"], 0)

    def test_snapshot_contains_no_input_content(self):
        text = repr(self.monitor.snapshot(self.end))
        for forbidden in ("buttons", "stick", "trigger"):
            self.assertNotIn(forbidden, text)

    def test_reconnect_resets_session(self):
        m = ReceiverMonitor()
        m.set_watched([(1, 2)])
        replay(m, LINES)
        m.feed(parse_usbmon_line(line("i", 1, "0800")), 2000.0)  # disconnected
        s = m.snapshot(2000.0)[0]["slots"][0]
        self.assertFalse(s["connected"])
        m.feed(parse_usbmon_line(line("i", 1, "0880")), 2001.0)  # connected
        s = m.snapshot(2001.0)[0]["slots"][0]
        self.assertTrue(s["connected"])
        self.assertIsNone(s["battery_level"])
        self.assertEqual(s["input_count"], 0)
        self.assertEqual(s["last_led_mode"], 2)  # history stays


class MonitorSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.m = ReceiverMonitor()
        self.m.set_watched([(1, 2)])

    def test_slot_mapping_by_endpoint(self):
        self.m.feed(parse_usbmon_line(line("i", 5, "0880")), 1.0)
        slots = self.m.snapshot(1.0)[0]["slots"]
        self.assertEqual([s["connected"] for s in slots], [False, False, True, False])

    def test_audio_endpoint_ignored(self):
        self.m.feed(parse_usbmon_line(line("i", 2, "0880")), 1.0)
        self.assertFalse(any(s["connected"] for s in self.m.snapshot(1.0)[0]["slots"]))

    def test_inferred_connection_from_input(self):
        pkt = "0001" + "00" * 27  # ID 0x00, type 0x01, input packet (29 bytes)
        self.m.feed(parse_usbmon_line(line("i", 1, pkt)), 5.0)
        s = self.m.snapshot(6.0)[0]["slots"][0]
        self.assertTrue(s["connected"])
        self.assertTrue(s["connected_inferred"])
        self.assertEqual(s["input_count"], 1)
        self.assertAlmostEqual(s["last_input_age_s"], 1.0)

    def test_out_commands_recorded(self):
        self.m.feed(parse_usbmon_line(line("o", 3, build_led(10).hex(), event="S")), 10.0)
        self.m.feed(parse_usbmon_line(line("o", 3, build_poweroff().hex(), event="S")), 12.0)
        s = self.m.snapshot(13.0)[0]["slots"][1]
        self.assertEqual(s["last_led_mode"], 10)
        self.assertAlmostEqual(s["last_led_age_s"], 3.0)
        self.assertAlmostEqual(s["last_poweroff_age_s"], 1.0)

    def test_unknown_kinds_bounded_and_header_only(self):
        for i in range(100):
            hexdata = f"00{i:02x}00" + "ab" * 26
            self.m.feed(parse_usbmon_line(line("i", 1, hexdata[:58])), 1.0)
        s = self.m.snapshot(1.0)[0]["slots"][0]
        self.assertLessEqual(len(s["unknown"]), 32)
        for key in s["unknown"]:
            self.assertEqual(len(key), 10)


class ReaderServiceTests(unittest.TestCase):
    def test_reader_replays_file_and_filters_foreign_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "1u"
            foreign = line("i", 1, "0880", dev=7)
            path.write_text("\n".join(LINES + [foreign]) + "\n", encoding="ascii")
            monitor = ReceiverMonitor()
            monitor.set_watched([(1, 2)])
            reader = UsbmonReader(1, monitor, [2], str(Path(tmp) / "{bus}u"))
            reader.start()
            reader.join(timeout=5)
            self.assertFalse(reader.is_alive())
            self.assertTrue(reader.opened)
            self.assertEqual(reader.matched, len(LINES))
            s = monitor.snapshot(time.time())[0]["slots"][0]
            self.assertEqual(s["battery_level"], 2)

    def test_reader_reports_missing_file(self):
        reader = UsbmonReader(1, ReceiverMonitor(), [2], "/nonexistent/{bus}u")
        reader.start()
        reader.join(timeout=5)
        self.assertFalse(reader.opened)
        self.assertIn("FileNotFoundError", reader.error)

    def test_service_enable_disable(self):
        from x360w.discovery import ReceiverInfo

        info = ReceiverInfo("1-3", 0x045E, 0x0719, "Receiver", 1, 2, None, None, None, None)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "1u").write_text("\n".join(LINES) + "\n", encoding="ascii")
            service = MonitorService(find=lambda: [info], usbmon_template=str(Path(tmp) / "{bus}u"))
            service.refresh()
            self.assertEqual(service.status()["readers"], {})  # off: nothing read
            service.enable()
            deadline = time.time() + 5
            while time.time() < deadline:
                snap = service.snapshot()
                if snap and snap[0]["slots"][0]["battery_level"] is not None:
                    break
                time.sleep(0.05)
            self.assertEqual(service.snapshot()[0]["slots"][0]["battery_level"], 2)
            service.disable()
            self.assertEqual(service.snapshot(), [])
            self.assertEqual(service.status()["readers"], {})


class RestartReadersTests(unittest.TestCase):
    class FakeReader:
        instances = []

        def __init__(self, bus, monitor, devnums, template, clock):
            self.bus, self.devnums = bus, set(devnums)
            self.error, self.opened, self.matched = None, True, 0
            self.started = self.stopped = self.joined = False
            self.instances.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self, timeout=None):
            self.joined = True

        def is_alive(self):
            return self.started and not self.stopped

        def set_devices(self, devnums):
            self.devnums = set(devnums)

    def make_service(self):
        from unittest import mock
        from x360w.discovery import ReceiverInfo

        self.FakeReader.instances = []
        info = ReceiverInfo("1-3", 0x045E, 0x0719, "Receiver", 1, 2, None, None, None, None)
        patcher = mock.patch("x360w.service.UsbmonReader", self.FakeReader)
        patcher.start()
        self.addCleanup(patcher.stop)
        return MonitorService(find=lambda: [info], usbmon_template="/nonexistent/{bus}u", ensure=lambda template: None)

    def test_old_readers_are_stopped_and_fresh_ones_started(self):
        service = self.make_service()
        service.enable()
        [old] = self.FakeReader.instances
        service.restart_readers()
        self.assertTrue(old.stopped and old.joined)
        self.assertEqual(len(self.FakeReader.instances), 2)
        new = self.FakeReader.instances[1]
        self.assertTrue(new.started and not new.stopped)
        self.assertEqual(new.devnums, {2})
        self.assertEqual(list(service.status()["readers"]), ["1"])
        service.disable()

    def test_restart_keeps_the_monitor_state_and_does_nothing_when_off(self):
        service = self.make_service()
        service.restart_readers()  # monitor off: nothing to restart
        self.assertEqual(self.FakeReader.instances, [])
        service.enable()
        service.monitor.feed(parse_usbmon_line(line("i", 1, "0880")), 1.0)
        service.restart_readers()
        self.assertTrue(service.snapshot()[0]["slots"][0]["connected"])
        service.disable()


class EnsureUsbmonTests(unittest.TestCase):
    def test_not_called_when_usbmon_present(self):
        from x360w.usbmon_reader import ensure_usbmon

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "1u").write_text("")
            calls = []
            self.assertIsNone(ensure_usbmon(str(Path(tmp) / "{bus}u"), runner=lambda *a, **k: calls.append(a)))
            self.assertEqual(calls, [])

    def test_runs_fixed_modprobe_when_missing_and_reports_errors(self):
        from x360w.usbmon_reader import ensure_usbmon
        import types

        calls = []

        def ok(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0, stderr="")

        def fail(cmd, **kw):
            return types.SimpleNamespace(returncode=1, stderr="Module not found")

        def boom(cmd, **kw):
            raise FileNotFoundError("modprobe")

        template = "/nonexistent/{bus}u"
        self.assertIsNone(ensure_usbmon(template, runner=ok))
        # `run_fixed` resolves the program to an absolute path where one exists (e.g. /usr/sbin/modprobe)
        self.assertEqual([(Path(call[0]).name, call[1:]) for call in calls], [("modprobe", ["usbmon"])])
        self.assertIn("failed", ensure_usbmon(template, runner=fail))
        self.assertIn("Module not found", ensure_usbmon(template, runner=fail))
        self.assertIn("could not be run", ensure_usbmon(template, runner=boom))

    def test_service_enable_records_setup_error(self):
        service = MonitorService(find=lambda: [], usbmon_template="/nonexistent/{bus}u",
                                 ensure=lambda template: "broken")
        service.enable()
        try:
            self.assertEqual(service.status()["setup_error"], "broken")
        finally:
            service.disable()


class ControlsTests(unittest.TestCase):
    def test_led_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "xpad0").mkdir()
            (base / "xpad0" / "brightness").write_text("0")
            (base / "input3::capslock").mkdir()
            self.assertEqual(controls.list_leds(base), ["xpad0"])
            controls.set_led_mode("xpad0", 10, base)
            self.assertEqual((base / "xpad0" / "brightness").read_text().strip(), "10")
            controls.reset_led("xpad0", base)
            self.assertEqual((base / "xpad0" / "brightness").read_text().strip(), "2")
            for bad in ("../xpad0", "xpad", "xpad0/x", "input3::capslock", ""):
                with self.assertRaises(ValueError):
                    controls.set_led_mode(bad, 1, base)
            for bad in (-1, 16, True, "3", 1.5):
                with self.assertRaises(ValueError):
                    controls.set_led_mode("xpad0", bad, base)
            with self.assertRaises(FileNotFoundError):
                controls.set_led_mode("xpad1", 1, base)

    def test_led_mode_descriptions_are_complete_and_language_neutral(self):
        self.assertEqual(sorted(controls.LED_MODES), list(range(16)))
        self.assertTrue(all(text.isascii() and text for text in controls.LED_MODES.values()))

    def test_default_mode_cycles(self):
        self.assertEqual([controls.default_led_mode(f"xpad{n}") for n in (0, 1, 3, 4)], [2, 3, 5, 2])

    def test_auto_poweroff(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "auto_poweroff"
            p.write_text("Y\n")
            self.assertIs(controls.get_auto_poweroff(p), True)
            controls.set_auto_poweroff(False, p)
            self.assertIs(controls.get_auto_poweroff(p), False)
            self.assertIsNone(controls.get_auto_poweroff(Path(tmp) / "missing"))
            with self.assertRaises(ValueError):
                controls.set_auto_poweroff("yes", p)


if __name__ == "__main__":
    unittest.main()
