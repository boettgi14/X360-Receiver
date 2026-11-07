"""Rumble test ("find controller") through the kernel's force-feedback interface.

xpad registers a force-feedback (rumble) effect handler on the input device it creates for every
connected controller. This module uploads one short rumble effect to that device's evdev node
(`/dev/input/eventN`), plays it and removes it again. No USB access, no takeover: the controller
stays connected and nothing is detached.

Safety and privacy:
  - The node name must match `event<number>` (`device_path`); the caller takes it from sysfs, under
    the interface of a known receiver's slot (`discovery.input_event_nodes`).
  - The node is opened write-only. This module never reads from it, so no input is ever seen.
  - Strength and duration are fixed constants; the duration is capped at `MAX_DURATION_S`.
  - The effect is always removed again, also on errors, and the descriptor is always closed.

STATUS: Derived from the kernel's uapi (`linux/input.h`, `struct ff_effect`, `EVIOCSFF`/`EVIOCRMFF`);
the structure layout and ioctl numbers are checked against the known x86-64 values in the unit tests.
NOT tried on a real controller yet. Whether Steam Input being active changes anything is unknown.
"""

from __future__ import annotations

import ctypes
import os
import re
import threading
import time
from typing import Callable, Optional

from . import error_codes

EVENT_NODE_RE = re.compile(r"event[0-9]{1,4}")
INPUT_DIR = "/dev/input"

FF_RUMBLE = 0x50
EV_FF = 0x15

DEFAULT_DURATION_S = 3.0
MAX_DURATION_S = 5.0
STRONG_MAGNITUDE = 0xA000  # of 0xFFFF
WEAK_MAGNITUDE = 0xA000

BUSY_TEXT = "A rumble test is already running."


class RumbleError(RuntimeError):
    """Rumble failed. `code` and `detail` let the frontend show a translated message."""

    def __init__(self, message: str, code: str = error_codes.RUMBLE_UNAVAILABLE, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


# -- Kernel structures (linux/input.h) ---------------------------------------------------------------------


class _Envelope(ctypes.Structure):
    _fields_ = [
        ("attack_length", ctypes.c_uint16),
        ("attack_level", ctypes.c_uint16),
        ("fade_length", ctypes.c_uint16),
        ("fade_level", ctypes.c_uint16),
    ]


class _Constant(ctypes.Structure):
    _fields_ = [("level", ctypes.c_int16), ("envelope", _Envelope)]


class _Ramp(ctypes.Structure):
    _fields_ = [("start_level", ctypes.c_int16), ("end_level", ctypes.c_int16), ("envelope", _Envelope)]


class _Periodic(ctypes.Structure):
    _fields_ = [
        ("waveform", ctypes.c_uint16),
        ("period", ctypes.c_uint16),
        ("magnitude", ctypes.c_int16),
        ("offset", ctypes.c_int16),
        ("phase", ctypes.c_uint16),
        ("envelope", _Envelope),
        ("custom_len", ctypes.c_uint32),
        ("custom_data", ctypes.c_void_p),
    ]


class _Condition(ctypes.Structure):
    _fields_ = [
        ("right_saturation", ctypes.c_uint16),
        ("left_saturation", ctypes.c_uint16),
        ("right_coeff", ctypes.c_int16),
        ("left_coeff", ctypes.c_int16),
        ("deadband", ctypes.c_uint16),
        ("center", ctypes.c_int16),
    ]


class _RumbleEffect(ctypes.Structure):
    _fields_ = [("strong_magnitude", ctypes.c_uint16), ("weak_magnitude", ctypes.c_uint16)]


class _Payload(ctypes.Union):
    _fields_ = [
        ("constant", _Constant),
        ("ramp", _Ramp),
        ("periodic", _Periodic),
        ("condition", _Condition * 2),
        ("rumble", _RumbleEffect),
    ]


class _Trigger(ctypes.Structure):
    _fields_ = [("button", ctypes.c_uint16), ("interval", ctypes.c_uint16)]


class _Replay(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("delay", ctypes.c_uint16)]


class _Effect(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint16),
        ("id", ctypes.c_int16),
        ("direction", ctypes.c_uint16),
        ("trigger", _Trigger),
        ("replay", _Replay),
        ("u", _Payload),
    ]


class _InputEvent(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_long),
        ("tv_usec", ctypes.c_long),
        ("type", ctypes.c_uint16),
        ("code", ctypes.c_uint16),
        ("value", ctypes.c_int32),
    ]


def _iow(type_char: str, number: int, size: int) -> int:
    """_IOW(type, nr, size) with the generic Linux layout (x86 and ARM)."""
    return (1 << 30) | (size << 16) | (ord(type_char) << 8) | number


EVIOCSFF = _iow("E", 0x80, ctypes.sizeof(_Effect))
EVIOCRMFF = _iow("E", 0x81, ctypes.sizeof(ctypes.c_int))

_lock = threading.Lock()


def device_path(node: str, input_dir: str = INPUT_DIR) -> str:
    """`/dev/input/<node>` for a node name like "event5"; anything else is refused."""
    if not isinstance(node, str) or not EVENT_NODE_RE.fullmatch(node):
        raise ValueError(f"Invalid input node name: {node!r}")
    return f"{input_dir}/{node}"


def _event(effect_id: int, value: int) -> bytes:
    return bytes(_InputEvent(0, 0, EV_FF, effect_id, value))


def _default_ioctl() -> Callable:
    try:
        import fcntl
    except ImportError as exc:  # not Linux
        raise RumbleError("fcntl is not available on this system", detail=str(exc)) from exc
    return fcntl.ioctl


def play(
    path: str,
    duration_s: float = DEFAULT_DURATION_S,
    strong: int = STRONG_MAGNITUDE,
    weak: int = WEAK_MAGNITUDE,
    *,
    opener: Callable = os.open,
    closer: Callable = os.close,
    writer: Callable = os.write,
    ioctl: Optional[Callable] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Plays one rumble effect on the evdev node `path` and removes it again. Raises `RumbleError`."""
    if not _lock.acquire(blocking=False):
        raise RumbleError(BUSY_TEXT, error_codes.BUSY)
    try:
        ioctl = ioctl or _default_ioctl()
        duration_s = max(0.1, min(float(duration_s), MAX_DURATION_S))
        try:
            fd = opener(path, os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
        except OSError as exc:
            raise RumbleError(f"Cannot open {path}: {exc}", detail=str(exc)) from exc
        effect_id = None
        try:
            buffer = bytearray(ctypes.sizeof(_Effect))
            effect = _Effect.from_buffer(buffer)
            effect.type = FF_RUMBLE
            effect.id = -1  # the kernel assigns a free id and writes it back into the buffer
            effect.replay.length = int(duration_s * 1000)
            effect.u.rumble.strong_magnitude = strong
            effect.u.rumble.weak_magnitude = weak
            ioctl(fd, EVIOCSFF, buffer, True)
            effect_id = effect.id
            writer(fd, _event(effect_id, 1))
            sleep(duration_s)
            writer(fd, _event(effect_id, 0))
        except OSError as exc:
            raise RumbleError(f"Rumble failed on {path}: {exc}", detail=str(exc)) from exc
        finally:
            if effect_id is not None and effect_id >= 0:
                try:
                    ioctl(fd, EVIOCRMFF, effect_id)
                except OSError:
                    pass
            closer(fd)
    finally:
        _lock.release()
