"""Short, controlled access to a controller slot through libusb (ctypes).

Procedure: the slot's interface is claimed with automatic detaching of the kernel driver (`xpad`
releases it), commands are sent and replies read, then libusb releases the interface and re-attaches
`xpad` (`libusb_set_auto_detach_kernel_driver`). During this time (seconds) this slot delivers no
input to Steam. Other slots are not affected.

Confirmed on hardware, with `tools/probe_takeover.py` and inside the Decky process (one receiver, one
gamepad): detaching xpad, sending, reading, releasing and re-binding xpad all work. The logic is
additionally tested with a dummy backend.

Writes only to endpoints of the chosen slot and only commands from x360w.protocol.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import time
from typing import Callable, List, Optional, Protocol, Tuple

from .error_codes import LIBUSB_UNAVAILABLE
from .protocol import decode_in_packet

LIBUSB_ERROR_TIMEOUT = -7
SLOT_COUNT = 4
PACKET_LEN = 29
VENDOR_MICROSOFT = 0x045E


class UsbError(RuntimeError):
    """USB access failed.

    `str(error)` is an English technical message. `code` and `detail` are optional and let the
    frontend show a translated message for failures a user can act on (see `main.py`).
    """

    def __init__(self, message: str, code: Optional[str] = None, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


class Backend(Protocol):
    def open(self, bus: int, address: int) -> None: ...
    def claim(self, interface: int) -> None: ...
    def write(self, endpoint: int, data: bytes, timeout_ms: int) -> None: ...
    def read(self, endpoint: int, length: int, timeout_ms: int) -> Optional[bytes]: ...
    def release(self, interface: int) -> None: ...
    def close(self) -> None: ...


def slot_endpoints(slot: int) -> Tuple[int, int, int]:
    """(interface, OUT endpoint, IN endpoint) for slot 0..3."""
    if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < SLOT_COUNT:
        raise ValueError(f"Slot must be 0..{SLOT_COUNT - 1}, not {slot!r}")
    return 2 * slot, 0x01 + 2 * slot, 0x81 + 2 * slot


class LibusbBackend:
    def __init__(self, library: Optional[str] = None) -> None:
        name = library or ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0"
        try:
            self._lib = ctypes.CDLL(name)
        except OSError as exc:
            raise UsbError(f"libusb could not be loaded: {exc}", LIBUSB_UNAVAILABLE, str(exc)) from exc
        lib = self._lib
        lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.libusb_exit.argtypes = [ctypes.c_void_p]
        lib.libusb_get_device_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
        lib.libusb_get_device_list.restype = ctypes.c_ssize_t
        lib.libusb_free_device_list.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        lib.libusb_get_bus_number.argtypes = [ctypes.c_void_p]
        lib.libusb_get_bus_number.restype = ctypes.c_uint8
        lib.libusb_get_device_address.argtypes = [ctypes.c_void_p]
        lib.libusb_get_device_address.restype = ctypes.c_uint8
        lib.libusb_open.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.libusb_close.argtypes = [ctypes.c_void_p]
        lib.libusb_set_auto_detach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_interrupt_transfer.argtypes = [
            ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_char_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
        ]
        lib.libusb_error_name.argtypes = [ctypes.c_int]
        lib.libusb_error_name.restype = ctypes.c_char_p
        self._ctx = ctypes.c_void_p()
        self._handle: Optional[ctypes.c_void_p] = None
        self._check(lib.libusb_init(ctypes.byref(self._ctx)), "libusb_init")

    def _check(self, code: int, what: str) -> int:
        if code < 0:
            name = self._lib.libusb_error_name(code)
            raise UsbError(f"{what}: {name.decode() if name else code}")
        return code

    def open(self, bus: int, address: int) -> None:
        lib = self._lib
        devices = ctypes.POINTER(ctypes.c_void_p)()
        count = self._check(lib.libusb_get_device_list(self._ctx, ctypes.byref(devices)), "get_device_list")
        try:
            for i in range(count):
                dev = devices[i]
                if lib.libusb_get_bus_number(dev) == bus and lib.libusb_get_device_address(dev) == address:
                    handle = ctypes.c_void_p()
                    self._check(lib.libusb_open(dev, ctypes.byref(handle)), "libusb_open")
                    self._handle = handle
                    self._check(lib.libusb_set_auto_detach_kernel_driver(handle, 1), "auto_detach")
                    return
        finally:
            lib.libusb_free_device_list(devices, 1)
        raise UsbError(f"Device on bus {bus}, address {address} not found")

    def claim(self, interface: int) -> None:
        self._check(self._lib.libusb_claim_interface(self._handle, interface), "claim_interface")

    def write(self, endpoint: int, data: bytes, timeout_ms: int) -> None:
        done = ctypes.c_int(0)
        self._check(
            self._lib.libusb_interrupt_transfer(self._handle, endpoint, data, len(data), ctypes.byref(done), timeout_ms),
            "interrupt_write",
        )
        if done.value != len(data):
            raise UsbError(f"interrupt_write: only {done.value} of {len(data)} bytes")

    def read(self, endpoint: int, length: int, timeout_ms: int) -> Optional[bytes]:
        buf = ctypes.create_string_buffer(length)
        done = ctypes.c_int(0)
        code = self._lib.libusb_interrupt_transfer(self._handle, endpoint, buf, length, ctypes.byref(done), timeout_ms)
        if code == LIBUSB_ERROR_TIMEOUT:
            return None
        self._check(code, "interrupt_read")
        return bytes(buf.raw[: done.value])

    def release(self, interface: int) -> None:
        # Releases the interface; libusb re-attaches the kernel driver in the process.
        self._check(self._lib.libusb_release_interface(self._handle, interface), "release_interface")

    def close(self) -> None:
        if self._handle is not None:
            self._lib.libusb_close(self._handle)
            self._handle = None
        if self._ctx:
            self._lib.libusb_exit(self._ctx)
            self._ctx = ctypes.c_void_p()


class SlotSession:
    """Context manager: claims a slot and is guaranteed to release it again."""

    def __init__(self, backend: Backend, bus: int, address: int, slot: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._backend = backend
        self._bus, self._address = bus, address
        self.interface, self.out_ep, self.in_ep = slot_endpoints(slot)
        self._clock = clock
        self._opened = False
        self._claimed = False

    def __enter__(self) -> "SlotSession":
        try:
            self._backend.open(self._bus, self._address)
            self._opened = True
            self._backend.claim(self.interface)
            self._claimed = True
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc) -> None:
        errors: List[str] = []
        if self._claimed:
            try:
                self._backend.release(self.interface)
            except UsbError as exc:
                errors.append(str(exc))
            self._claimed = False
        if self._opened:
            try:
                self._backend.close()
            except UsbError as exc:
                errors.append(str(exc))
            self._opened = False
        if errors:
            raise UsbError("; ".join(errors))

    def send(self, packet: bytes, timeout_ms: int = 1000) -> None:
        if len(packet) != 12:
            raise ValueError("Commands are 12 bytes long")
        self._backend.write(self.out_ep, packet, timeout_ms)

    def listen(self, seconds: float, poll_ms: int = 100) -> List[Tuple[float, bytes, object]]:
        """Reads IN packets for `seconds`. Returns (seconds since start, raw data, decoded)."""
        start = self._clock()
        found: List[Tuple[float, bytes, object]] = []
        while self._clock() - start < seconds:
            data = self._backend.read(self.in_ep, PACKET_LEN, poll_ms)
            if data:
                found.append((self._clock() - start, data, decode_in_packet(data)))
        return found
