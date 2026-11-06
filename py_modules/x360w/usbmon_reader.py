"""Reads usbmon text (/sys/kernel/debug/usb/usbmon/<bus>u) in a thread.

Privacy: usbmon delivers the entire bus. Each line is first checked, as plain bytes only, for the
address marker ":<bus>:<device>:" of the watched receivers. Lines of other devices are discarded
before they are decoded and are never stored or logged.

Not tested on real hardware: non-blocking reading with select() on the usbmon file.
Fallback if that does not work: a blocking read() in this thread.
"""

from __future__ import annotations

import os
import select
import subprocess
import threading
import time
from typing import Callable, Iterable, Optional, Tuple

from .monitor import ReceiverMonitor
from .safe_exec import run_fixed
from .usbmon import parse_usbmon_line

DEFAULT_TEMPLATE = "/sys/kernel/debug/usb/usbmon/{bus}u"
MAX_PARTIAL_LINE = 1 << 20  # 1 MiB: protection against lines without an end


def ensure_usbmon(
    template: str = DEFAULT_TEMPLATE,
    runner=subprocess.run,
) -> Optional[str]:
    """Loads the usbmon kernel module if the interface is missing. Returns an error message or None.

    Fixed call without user input: `modprobe usbmon`. Not persistent; after a reboot the plugin
    loads the module again when the monitor is switched on. Confirmed by hand on the device
    (`sudo modprobe usbmon` works); the call from inside the plugin is untested.
    The messages are English and language-neutral; the frontend shows them as technical details.
    """
    if os.path.exists(template.format(bus=1)):
        return None
    try:
        result = run_fixed(["modprobe", "usbmon"], 15, runner)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"modprobe usbmon could not be run: {exc}"
    if result.returncode != 0:
        return f"modprobe usbmon failed: {(result.stderr or '').strip()[:200]}"
    return None


def _markers(bus: int, devnums: Iterable[int]) -> Tuple[bytes, ...]:
    return tuple(f":{bus}:{dev:03d}:".encode("ascii") for dev in devnums)


class UsbmonReader(threading.Thread):
    def __init__(
        self,
        bus: int,
        monitor: ReceiverMonitor,
        devnums: Iterable[int],
        path_template: str = DEFAULT_TEMPLATE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(daemon=True, name=f"x360w-usbmon-{bus}")
        self.bus = bus
        self._monitor = monitor
        self._markers = _markers(bus, devnums)
        self._path = path_template.format(bus=bus)
        self._clock = clock
        self._stop_event = threading.Event()
        self.opened = False
        self.error: Optional[str] = None
        self.matched = 0  # lines of the watched devices (counter only, no content)

    def set_devices(self, devnums: Iterable[int]) -> None:
        self._markers = _markers(self.bus, devnums)  # atomic assignment

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return
        self.opened = True
        buffer = b""
        try:
            while not self._stop_event.is_set():
                ready, _, _ = select.select([fd], [], [], 0.5)
                if not ready:
                    continue
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
                    break
                if not chunk:
                    break  # end of file (only with test files, usbmon never ends on its own)
                buffer += chunk
                *lines, buffer = buffer.split(b"\n")
                if len(buffer) > MAX_PARTIAL_LINE:
                    buffer = b""
                for raw in lines:
                    self._process_line(raw)
        finally:
            os.close(fd)

    def _process_line(self, raw: bytes) -> None:
        markers = self._markers
        if not any(marker in raw for marker in markers):
            return  # foreign device: do not decode, do not store
        record = parse_usbmon_line(raw.decode("ascii", "replace"))
        if record is None:
            return
        self.matched += 1
        self._monitor.feed(record, self._clock())
