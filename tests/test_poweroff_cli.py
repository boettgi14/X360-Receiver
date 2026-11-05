"""Tests für x360w.poweroff_cli: Programm des Dienstes."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w import poweroff_cli  # noqa: E402


class RunTests(unittest.TestCase):
    def test_powers_off_all_planned_targets_and_reports(self):
        seen = []

        def power_off(targets):
            seen.append(list(targets))
            return {"ok": True, "sent": 2, "confirmed": 2, "errors": []}

        ticks = iter([100.0, 102.5])
        report = poweroff_cli.run(lambda: (1, [(1, 2, 0), (1, 2, 1)]), power_off, lambda: next(ticks))
        self.assertEqual(seen, [[(1, 2, 0), (1, 2, 1)]])
        self.assertEqual(report["targets"], [[1, 2, 0], [1, 2, 1]])
        self.assertEqual(report["receivers"], 1)
        self.assertEqual(report["duration_s"], 2.5)
        self.assertIsNone(report["error"])
        json.dumps(report)  # muss als JSON schreibbar sein

    def test_no_controller_sends_nothing(self):
        def power_off(targets):
            raise AssertionError("nichts zu senden")

        report = poweroff_cli.run(lambda: (1, []), power_off)
        self.assertEqual(report["result"], {"ok": True, "sent": 0, "confirmed": 0, "errors": []})

    def test_errors_are_reported_never_raised(self):
        def plan():
            raise OSError("sysfs weg")

        report = poweroff_cli.run(plan, lambda t: {})
        self.assertIn("OSError: sysfs weg", report["error"])
        def power_off(targets):
            raise RuntimeError("usb weg")

        report = poweroff_cli.run(lambda: (1, [(1, 2, 0)]), power_off)
        self.assertIn("RuntimeError: usb weg", report["error"])

    def test_default_plan_uses_the_same_rules_as_the_button(self):
        # Ohne Receiver (wie im Testcontainer) gibt es nichts zu tun
        receivers, targets = poweroff_cli.plan_targets()
        self.assertIsInstance(receivers, int)
        self.assertIsInstance(targets, list)


class MainTests(unittest.TestCase):
    def test_main_writes_report_prints_one_line_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            original = poweroff_cli.run
            poweroff_cli.run = lambda: {"at": 1.0, "targets": [], "result": None, "error": None}
            try:
                with contextlib.redirect_stdout(out):
                    code = poweroff_cli.main(tmp)
            finally:
                poweroff_cli.run = original
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((Path(tmp) / "last-run.json").read_text())["at"], 1.0)
            self.assertFalse(list(Path(tmp).glob("*.tmp")))
        line = out.getvalue()
        self.assertEqual(line.count("\n"), 1)
        self.assertTrue(line.startswith("x360w-poweroff {"))

    def test_unwritable_directory_does_not_fail(self):
        out = io.StringIO()
        original = poweroff_cli.run
        poweroff_cli.run = lambda: {"at": 1.0, "targets": [], "result": None, "error": None}
        try:
            with contextlib.redirect_stdout(out):
                code = poweroff_cli.main("/proc/nicht/schreibbar")
        finally:
            poweroff_cli.run = original
        self.assertEqual(code, 0)
        self.assertIn("write_error", out.getvalue())


if __name__ == "__main__":
    unittest.main()
