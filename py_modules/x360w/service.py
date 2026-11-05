"""Verbindet Receiver-Erkennung (sysfs) und usbmon-Leser (je Bus ein Thread).

`refresh()` wird regelmäßig aufgerufen (Hot-Plug, neue Geräteadresse nach erneutem Einstecken).
Der Monitor ist abschaltbar; ausgeschaltet wird kein USB-Verkehr gelesen.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Set

from .discovery import ReceiverInfo, find_receivers
from .monitor import ReceiverMonitor
from .usbmon_reader import DEFAULT_TEMPLATE, UsbmonReader, ensure_usbmon

RETRY_AFTER_ERROR_S = 30.0


class MonitorService:
    def __init__(
        self,
        find: Callable[[], List[ReceiverInfo]] = find_receivers,
        usbmon_template: str = DEFAULT_TEMPLATE,
        clock: Callable[[], float] = time.time,
        ensure: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.monitor = ReceiverMonitor()
        self._find = find
        self._template = usbmon_template
        self._clock = clock
        self._ensure = ensure or ensure_usbmon  # zur Laufzeit gebunden, damit Tests ersetzen können
        self.setup_error: Optional[str] = None
        self._lock = threading.RLock()
        self._enabled = False
        self._readers: Dict[int, UsbmonReader] = {}
        self._retry_at: Dict[int, float] = {}
        self._receivers: List[ReceiverInfo] = []

    # -- Steuerung ----------------------------------------------------------

    def enable(self) -> None:
        self.setup_error = self._ensure(self._template)
        with self._lock:
            self._enabled = True
        self.refresh()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            readers = list(self._readers.values())
            self._readers.clear()
            self._retry_at.clear()
        for reader in readers:
            reader.stop()
        for reader in readers:
            reader.join(timeout=2.0)
        self.monitor.set_watched([])

    def refresh(self) -> List[ReceiverInfo]:
        receivers = self._find()
        with self._lock:
            self._receivers = receivers
            if not self._enabled:
                return receivers

            by_bus: Dict[int, Set[int]] = {}
            for receiver in receivers:
                if receiver.bus is not None and receiver.devnum is not None:
                    by_bus.setdefault(receiver.bus, set()).add(receiver.devnum)

            self.monitor.set_watched(
                (bus, dev) for bus, devs in by_bus.items() for dev in devs
            )

            now = self._clock()
            for bus in list(self._readers):
                reader = self._readers[bus]
                if bus not in by_bus:
                    reader.stop()
                    del self._readers[bus]
                elif not reader.is_alive():
                    if reader.error:
                        self._retry_at[bus] = now + RETRY_AFTER_ERROR_S
                    del self._readers[bus]

            for bus, devs in by_bus.items():
                reader: Optional[UsbmonReader] = self._readers.get(bus)
                if reader is not None:
                    reader.set_devices(devs)
                elif now >= self._retry_at.get(bus, 0.0):
                    reader = UsbmonReader(bus, self.monitor, devs, self._template, self._clock)
                    self._readers[bus] = reader
                    reader.start()
        return receivers

    # -- Abfrage ------------------------------------------------------------

    def receivers(self) -> List[ReceiverInfo]:
        with self._lock:
            return list(self._receivers)

    def snapshot(self) -> List[dict]:
        return self.monitor.snapshot(self._clock())

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "setup_error": self.setup_error,
                "readers": {
                    str(bus): {
                        "alive": reader.is_alive(),
                        "opened": reader.opened,
                        "error": reader.error,
                        "matched_lines": reader.matched,
                    }
                    for bus, reader in self._readers.items()
                },
                "retry_pending": sorted(self._retry_at),
            }
