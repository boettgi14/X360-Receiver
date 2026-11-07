"""Tests for actions.py with a dummy backend."""

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import actions, build_battery_request, build_poweroff, build_status_request  # noqa: E402
from x360w.takeover import UsbError  # noqa: E402

STATE_A2 = bytes.fromhex("00000013a2") + bytes(24)
STATE_82 = bytes.fromhex("0000001382") + bytes(24)
EMPTY = bytes.fromhex("000000f000") + bytes(24)
# link report of a gamepad (subtype 0x01), as in tests/test_protocol.py; the same with subtype 0x06 (guitar)
LINK_GAMEPAD = bytes.fromhex("000f00f0f0cc" "fd1f9f70" "c90063b0" "00" "05" "13a7" "201d" "3003" "400150" "01" "ffffff")
LINK_GUITAR = LINK_GAMEPAD[:-4] + bytes([0x06]) + LINK_GAMEPAD[-3:]


class Fake:
    def __init__(self, answer=(), fail_open=False):
        # `answer` only becomes readable after a command is sent (like on the real device)
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


class Scripted(Fake):
    """Answers each command with its own packets (the receiver answers a battery request with a state packet
    and a presence request with the connection packet and the link report)."""

    def __init__(self, answers):
        super().__init__()
        self.answers = answers

    def write(self, ep, data, timeout_ms):
        self.calls.append(("write", ep, data))
        self.replies.extend(self.answers.get(bytes(data), []))


class ActionTests(unittest.TestCase):
    def setUp(self):
        # Let time pass quickly: listen() uses monotonic; the dummy returns None immediately
        self._d, self._b, self._p = actions.DRAIN_S, actions.BATTERY_LISTEN_S, actions.POWEROFF_LISTEN_S
        self._presence = actions.PRESENCE_LISTEN_S
        actions.DRAIN_S = actions.BATTERY_LISTEN_S = actions.POWEROFF_LISTEN_S = actions.PRESENCE_LISTEN_S = 0.05

    def tearDown(self):
        actions.DRAIN_S, actions.BATTERY_LISTEN_S, actions.POWEROFF_LISTEN_S = self._d, self._b, self._p
        actions.PRESENCE_LISTEN_S = self._presence

    def test_query_battery_returns_state_and_sends_only_the_two_known_requests(self):
        fake = Fake(answer=[STATE_A2, EMPTY])
        result = actions.query_battery(1, 2, 1, lambda: fake)
        writes = [c for c in fake.calls if c[0] == "write"]
        self.assertEqual(writes, [("write", 0x03, build_battery_request()), ("write", 0x03, build_status_request())])
        self.assertEqual([c[0] for c in fake.calls][-2:], ["release", "close"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["battery_level"], 2)
        self.assertEqual(result["state"]["power_state_raw"], 2)

    def test_query_battery_without_answer_has_no_state_and_sends_no_presence_request(self):
        fake = Fake()
        result = actions.query_battery(1, 2, 0, lambda: fake)
        self.assertEqual(result, {"ok": True, "state": None})
        self.assertEqual([c for c in fake.calls if c[0] == "write"], [("write", 0x01, build_battery_request())])

    def test_query_battery_learns_the_controller_type_from_the_link_report(self):
        answers = {build_battery_request(): [STATE_A2], build_status_request(): [bytes.fromhex("0880"), LINK_GUITAR]}
        result = actions.query_battery(1, 2, 0, lambda: Scripted(answers))
        self.assertEqual((result["ok"], result["state"]["battery_level"], result["subtype"]), (True, 2, 0x06))
        answers[build_status_request()] = [bytes.fromhex("0880"), LINK_GAMEPAD]
        self.assertEqual(actions.query_battery(1, 2, 0, lambda: Scripted(answers))["subtype"], 0x01)

    def test_query_battery_without_a_link_report_still_returns_the_state(self):
        answers = {build_battery_request(): [STATE_A2]}
        result = actions.query_battery(1, 2, 0, lambda: Scripted(answers))
        self.assertEqual((result["ok"], result["state"]["battery_level"], result["subtype"]), (True, 2, None))

    def test_power_off_sends_c0_to_slot_endpoint_and_reports_confirmation(self):
        fake = Fake()
        result = actions.power_off(1, 2, 3, lambda: fake)
        self.assertEqual([c for c in fake.calls if c[0] == "write"], [("write", 0x07, build_poweroff())])
        self.assertEqual(result, {"ok": True, "confirmed": False})  # no answer: not confirmed
        confirmed = actions.power_off(1, 2, 0, lambda: Fake(answer=[STATE_A2, STATE_82, EMPTY]))
        self.assertEqual(confirmed, {"ok": True, "confirmed": True})

    def test_errors_are_returned_not_raised(self):
        result = actions.power_off(1, 2, 0, lambda: Fake(fail_open=True))
        self.assertFalse(result["ok"])
        self.assertIn("ACCESS", result["error"])
        self.assertNotIn("code", result)  # a technical USB error has no translated message
        self.assertFalse(actions.query_battery(1, 2, 9, lambda: Fake())["ok"])  # invalid slot

    def test_errors_with_a_code_pass_code_and_detail_on(self):
        def factory():
            raise UsbError("libusb could not be loaded: no such file", "libusb_unavailable", "no such file")

        result = actions.query_battery(1, 2, 0, factory)
        self.assertEqual(result, {"ok": False, "error": "libusb could not be loaded: no such file",
                                  "code": "libusb_unavailable", "detail": "no such file"})

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
        self.assertEqual(other["error"], actions.BUSY_ERROR)
        self.assertEqual(other["code"], "busy")
        self.assertTrue(results["a"]["ok"])


if __name__ == "__main__":
    unittest.main()
