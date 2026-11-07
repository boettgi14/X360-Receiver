"""Tests for x360w.rumble with a stand-in kernel (no input device, no hardware)."""

import ctypes
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import rumble  # noqa: E402


class FakeKernel:
    """Records what would be sent to the evdev node and plays the kernel's part in the upload."""

    def __init__(self, effect_id=3, fail_open=False, fail_upload=False, fail_start=False):
        self.log = []
        self.effect_id = effect_id
        self.fail_open, self.fail_upload, self.fail_start = fail_open, fail_upload, fail_start
        self.uploaded = None

    def opener(self, path, flags):
        self.log.append(("open", path, flags))
        if self.fail_open:
            raise PermissionError(13, "Permission denied")
        return 42

    def ioctl(self, fd, request, arg, mutate=None):
        if request == rumble.EVIOCSFF:
            if self.fail_upload:
                raise OSError(22, "Invalid argument")
            effect = rumble._Effect.from_buffer(arg)
            self.uploaded = (effect.type, effect.id, effect.replay.length,
                             effect.u.rumble.strong_magnitude, effect.u.rumble.weak_magnitude)
            effect.id = self.effect_id  # the kernel writes the assigned id back into the buffer
            self.log.append(("upload",))
            return 0
        if request == rumble.EVIOCRMFF:
            self.log.append(("remove", arg))
            return 0
        raise AssertionError(f"unexpected ioctl {request:#x}")

    def writer(self, fd, data):
        event = rumble._InputEvent.from_buffer_copy(data)
        self.log.append(("write", event.type, event.code, event.value))
        if self.fail_start and event.value == 1:
            raise OSError(5, "Input/output error")
        return len(data)

    def closer(self, fd):
        self.log.append(("close", fd))

    def sleep(self, seconds):
        self.log.append(("sleep", seconds))

    def play(self, **kwargs):
        rumble.play("/dev/input/event5", opener=self.opener, closer=self.closer, writer=self.writer,
                    ioctl=self.ioctl, sleep=self.sleep, **kwargs)


class LayoutTests(unittest.TestCase):
    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "known values are for 64-bit")
    def test_structures_and_ioctl_numbers_match_the_known_x86_64_values(self):
        self.assertEqual(ctypes.sizeof(rumble._Effect), 48)  # struct ff_effect
        self.assertEqual(ctypes.sizeof(rumble._InputEvent), 24)  # struct input_event
        self.assertEqual(rumble.EVIOCSFF, 0x40304580)
        self.assertEqual(rumble.EVIOCRMFF, 0x40044581)

    def test_field_offsets_follow_the_kernel_header(self):
        self.assertEqual(rumble._Effect.type.offset, 0)
        self.assertEqual(rumble._Effect.id.offset, 2)
        self.assertEqual(rumble._Effect.replay.offset, 10)
        self.assertEqual(rumble._Payload.rumble.offset, 0)
        self.assertEqual(rumble._RumbleEffect.weak_magnitude.offset, 2)


class PlayTests(unittest.TestCase):
    def test_uploads_plays_stops_removes_and_closes_in_order(self):
        kernel = FakeKernel(effect_id=3)
        kernel.play()
        self.assertEqual([entry[0] for entry in kernel.log],
                         ["open", "upload", "write", "sleep", "write", "remove", "close"])
        self.assertEqual(kernel.log[2], ("write", rumble.EV_FF, 3, 1))  # start effect 3
        self.assertEqual(kernel.log[4], ("write", rumble.EV_FF, 3, 0))  # stop effect 3
        self.assertEqual(kernel.log[5], ("remove", 3))
        self.assertEqual(kernel.uploaded,
                         (rumble.FF_RUMBLE, -1, 3000, rumble.STRONG_MAGNITUDE, rumble.WEAK_MAGNITUDE))

    def test_node_is_opened_write_only_so_input_can_never_be_read(self):
        kernel = FakeKernel()
        kernel.play()
        flags = kernel.log[0][2]
        self.assertEqual(flags & os.O_ACCMODE, os.O_WRONLY)

    def test_default_duration_is_a_few_seconds_and_within_the_cap(self):
        self.assertEqual(rumble.DEFAULT_DURATION_S, 3.0)
        self.assertLessEqual(rumble.DEFAULT_DURATION_S, rumble.MAX_DURATION_S)

    def test_duration_is_capped(self):
        kernel = FakeKernel()
        kernel.play(duration_s=99)
        self.assertEqual(kernel.uploaded[2], int(rumble.MAX_DURATION_S * 1000))
        self.assertIn(("sleep", rumble.MAX_DURATION_S), kernel.log)
        short = FakeKernel()
        short.play(duration_s=0)
        self.assertEqual(short.uploaded[2], 100)

    def test_open_failure_is_a_rumble_error_and_nothing_else_happens(self):
        kernel = FakeKernel(fail_open=True)
        with self.assertRaises(rumble.RumbleError) as caught:
            kernel.play()
        self.assertEqual(caught.exception.code, "rumble_unavailable")
        self.assertIn("Permission denied", caught.exception.detail)
        self.assertEqual([entry[0] for entry in kernel.log], ["open"])

    def test_upload_failure_closes_without_removing(self):
        kernel = FakeKernel(fail_upload=True)
        with self.assertRaises(rumble.RumbleError) as caught:
            kernel.play()
        self.assertEqual(caught.exception.code, "rumble_unavailable")
        self.assertEqual([entry[0] for entry in kernel.log], ["open", "close"])

    def test_failure_while_playing_still_removes_the_effect_and_closes(self):
        kernel = FakeKernel(effect_id=7, fail_start=True)
        with self.assertRaises(rumble.RumbleError):
            kernel.play()
        self.assertEqual(kernel.log[-2:], [("remove", 7), ("close", 42)])

    def test_second_rumble_is_refused_while_one_is_running(self):
        self.assertTrue(rumble._lock.acquire(blocking=False))
        try:
            with self.assertRaises(rumble.RumbleError) as caught:
                FakeKernel().play()
            self.assertEqual(caught.exception.code, "busy")
        finally:
            rumble._lock.release()
        FakeKernel().play()  # and works again afterwards


class DevicePathTests(unittest.TestCase):
    def test_only_event_nodes_are_accepted(self):
        self.assertEqual(rumble.device_path("event5"), "/dev/input/event5")
        self.assertEqual(rumble.device_path("event12", "/x"), "/x/event12")
        for bad in ("../event5", "event", "event5/x", "js0", "mouse0", "event12345", "", None, 5, "event5\n"):
            with self.assertRaises(ValueError):
                rumble.device_path(bad)


if __name__ == "__main__":
    unittest.main()
