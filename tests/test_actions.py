"""Tests für actions.py mit Attrappen-Backend."""

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import actions, build_battery_request, build_poweroff  # noqa: E402
from x360w.takeover import UsbError  # noqa: E402

STATE_A2 = bytes.fromhex("00000013a2") + bytes(24)
STATE_82 = bytes.fromhex("0000001382") + bytes(24)
EMPTY = bytes.fromhex("000000f000") + bytes(24)


class Fake:
    def __init__(self, answer=(), fail_open=False):
        # `answer` wird erst nach dem Senden eines Befehls lesbar (wie am echten Gerät)
        self.calls, self.answer, self.replies, self.fail_open = [], list(answer), [], fail_open

    def open(self, bus, address):
        if self.fail_open:
            raise UsbError("libusb_open: LIBUSB_ERROR_ACCESS")
        self.calls.append(("open", bus, address))

    def claim(self, i):
        self.calls.append(("claim", i))

    def write(self, ep, data, timeout_ms):
        self.calls.append(("write", ep, data))
        self.replies.extend(self.answer)

    def read(self, ep, length, timeout_ms):
        return self.replies.pop(0) if self.replies else None

    def release(self, i):
        self.calls.append(("release", i))

    def close(self):
        self.calls.append(("close",))


class ActionTests(unittest.TestCase):
    def setUp(self):
        # Zeit schnell ablaufen lassen: listen() nutzt monotonic; Attrappe liefert sofort None
        self._d, self._b, self._p = actions.DRAIN_S, actions.BATTERY_LISTEN_S, actions.POWEROFF_LISTEN_S
        actions.DRAIN_S = actions.BATTERY_LISTEN_S = actions.POWEROFF_LISTEN_S = 0.05

    def tearDown(self):
        actions.DRAIN_S, actions.BATTERY_LISTEN_S, actions.POWEROFF_LISTEN_S = self._d, self._b, self._p

    def test_query_battery_returns_state_and_sends_only_the_request(self):
        fake = Fake(answer=[STATE_A2, EMPTY])
        result = actions.query_battery(1, 2, 1, lambda: fake)
        writes = [c for c in fake.calls if c[0] == "write"]
        self.assertEqual(writes, [("write", 0x03, build_battery_request())])
        self.assertEqual([c[0] for c in fake.calls][-2:], ["release", "close"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["battery_level"], 2)
        self.assertEqual(result["state"]["power_state_raw"], 2)

    def test_query_battery_without_answer_has_no_state(self):
        result = actions.query_battery(1, 2, 0, lambda: Fake())
        self.assertEqual(result, {"ok": True, "state": None})

    def test_power_off_sends_c0_to_slot_endpoint_and_reports_confirmation(self):
        fake = Fake()
        result = actions.power_off(1, 2, 3, lambda: fake)
        self.assertEqual([c for c in fake.calls if c[0] == "write"], [("write", 0x07, build_poweroff())])
        self.assertEqual(result, {"ok": True, "confirmed": False})  # keine Antwort: nicht bestätigt
        confirmed = actions.power_off(1, 2, 0, lambda: Fake(answer=[STATE_A2, STATE_82, EMPTY]))
        self.assertEqual(confirmed, {"ok": True, "confirmed": True})

    def test_errors_are_returned_not_raised(self):
        result = actions.power_off(1, 2, 0, lambda: Fake(fail_open=True))
        self.assertFalse(result["ok"])
        self.assertIn("ACCESS", result["error"])
        self.assertFalse(actions.query_battery(1, 2, 9, lambda: Fake())["ok"])  # ungültiger Slot

    def test_second_access_is_refused_while_busy(self):
        gate = threading.Event()
        release = threading.Event()

        class Slow(Fake):
            def claim(self, i):
                gate.set()
                release.wait(2)
                super().claim(i)

        results = {}
        t = threading.Thread(target=lambda: results.update(a=actions.query_battery(1, 2, 0, Slow)))
        t.start()
        self.assertTrue(gate.wait(2))
        other = actions.query_battery(1, 2, 0, Fake)
        release.set()
        t.join(5)
        self.assertFalse(other["ok"])
        self.assertIn("bereits", other["error"])
        self.assertTrue(results["a"]["ok"])


if __name__ == "__main__":
    unittest.main()
