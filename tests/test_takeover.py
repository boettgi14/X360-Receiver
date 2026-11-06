"""Tests for takeover.py with a dummy backend (no hardware)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import build_poweroff, build_status_request  # noqa: E402
from x360w.takeover import LibusbBackend, SlotSession, UsbError, slot_endpoints  # noqa: E402


class FakeBackend:
    def __init__(self, replies=(), fail_claim=False, fail_release=False):
        self.calls = []
        self.replies = list(replies)
        self.fail_claim = fail_claim
        self.fail_release = fail_release

    def open(self, bus, address):
        self.calls.append(("open", bus, address))

    def claim(self, interface):
        self.calls.append(("claim", interface))
        if self.fail_claim:
            raise UsbError("claim_interface: LIBUSB_ERROR_BUSY")

    def write(self, endpoint, data, timeout_ms):
        self.calls.append(("write", endpoint, data))

    def read(self, endpoint, length, timeout_ms):
        self.calls.append(("read", endpoint))
        return self.replies.pop(0) if self.replies else None

    def release(self, interface):
        self.calls.append(("release", interface))
        if self.fail_release:
            raise UsbError("release_interface: LIBUSB_ERROR_NO_DEVICE")

    def close(self):
        self.calls.append(("close",))


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.1
        return self.t


class TakeoverTests(unittest.TestCase):
    def test_slot_endpoints(self):
        self.assertEqual([slot_endpoints(s) for s in range(4)],
                         [(0, 0x01, 0x81), (2, 0x03, 0x83), (4, 0x05, 0x85), (6, 0x07, 0x87)])
        for bad in (-1, 4, True, "0", None):
            with self.assertRaises(ValueError):
                slot_endpoints(bad)

    def test_send_goes_to_slot_endpoint_and_release_follows(self):
        backend = FakeBackend()
        with SlotSession(backend, 1, 2, 2) as session:
            session.send(build_poweroff())
        self.assertEqual(backend.calls, [
            ("open", 1, 2), ("claim", 4), ("write", 0x05, build_poweroff()), ("release", 4), ("close",),
        ])

    def test_release_even_when_body_raises(self):
        backend = FakeBackend()
        with self.assertRaises(RuntimeError):
            with SlotSession(backend, 1, 2, 0):
                raise RuntimeError("boom")
        self.assertEqual(backend.calls[-2:], [("release", 0), ("close",)])

    def test_failed_claim_closes_without_release(self):
        backend = FakeBackend(fail_claim=True)
        with self.assertRaises(UsbError):
            SlotSession(backend, 1, 2, 0).__enter__()
        self.assertEqual(backend.calls, [("open", 1, 2), ("claim", 0), ("close",)])

    def test_close_still_runs_when_release_fails(self):
        backend = FakeBackend(fail_release=True)
        with self.assertRaises(UsbError):
            with SlotSession(backend, 1, 2, 0):
                pass
        self.assertEqual(backend.calls[-1], ("close",))

    def test_rejects_wrong_length_command(self):
        with SlotSession(FakeBackend(), 1, 2, 0) as session:
            with self.assertRaises(ValueError):
                session.send(b"\x00\x00")

    def test_listen_decodes_and_stops(self):
        link = bytes.fromhex("08" + "80")
        backend = FakeBackend(replies=[link])
        with SlotSession(backend, 1, 2, 0, clock=Clock()) as session:
            session.send(build_status_request())
            found = session.listen(0.5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], link)
        self.assertEqual(type(found[0][2]).__name__, "ConnectionEvent")

    def test_usb_error_carries_an_optional_code_and_detail(self):
        plain = UsbError("claim_interface: LIBUSB_ERROR_BUSY")
        self.assertEqual((plain.code, plain.detail), (None, None))
        coded = UsbError("text", "some_code", "why")
        self.assertEqual((str(coded), coded.code, coded.detail), ("text", "some_code", "why"))

    def test_missing_libusb_reports_a_translatable_code(self):
        with self.assertRaises(UsbError) as caught:
            LibusbBackend("/nonexistent/libusb-1.0.so.0")
        self.assertEqual(caught.exception.code, "libusb_unavailable")
        self.assertTrue(caught.exception.detail)  # the loader's reason
        self.assertIn("libusb could not be loaded", str(caught.exception))

    def test_libusb_loads_and_reports_missing_device(self):
        try:
            backend = LibusbBackend()
        except UsbError:
            self.skipTest("libusb not installed")
        try:
            with self.assertRaises(UsbError):
                backend.open(250, 250)
        finally:
            backend.close()


if __name__ == "__main__":
    unittest.main()
