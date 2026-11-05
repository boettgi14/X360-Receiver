"""Liest usbmon-Text (/sys/kernel/debug/usb/usbmon/<bus>u) in einem Thread.

Datenschutz: usbmon liefert den gesamten Bus. Jede Zeile wird zuerst nur als Bytefolge auf die
Adressmarke ":<bus>:<gerät>:" der beobachteten Receiver geprüft. Zeilen anderer Geräte werden
verworfen, bevor sie decodiert werden, und nirgends gespeichert oder protokolliert.

Nicht an echter Hardware getestet: das nicht blockierende Lesen mit select() auf der usbmon-Datei.
Rückfall, falls das nicht klappt: blockierendes read() in diesem Thread.
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
MAX_PARTIAL_LINE = 1 << 20  # 1 MiB: Schutz vor Zeilen ohne Ende


def ensure_usbmon(
    template: str = DEFAULT_TEMPLATE,
    runner=subprocess.run,
) -> Optional[str]:
    """Lädt das Kernelmodul usbmon, falls die Schnittstelle fehlt. Gibt eine Fehlermeldung oder None zurück.

    Fester Aufruf ohne Nutzereingabe: `modprobe usbmon`. Nicht dauerhaft; nach einem Neustart
    lädt das Plugin das Modul beim Einschalten des Monitors erneut. Am Gerät von Hand bestätigt
    (`sudo modprobe usbmon` funktioniert); der Aufruf aus dem Plugin ist ungetestet.
    """
    if os.path.exists(template.format(bus=1)):
        return None
    try:
        result = run_fixed(["modprobe", "usbmon"], 15, runner)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"modprobe usbmon nicht ausführbar: {exc}"
    if result.returncode != 0:
        return f"modprobe usbmon fehlgeschlagen: {(result.stderr or '').strip()[:200]}"
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
        self.matched = 0  # Zeilen der beobachteten Geräte (nur Zähler, kein Inhalt)

    def set_devices(self, devnums: Iterable[int]) -> None:
        self._markers = _markers(self.bus, devnums)  # atomare Zuweisung

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
                    break  # Dateiende (nur bei Testdateien, usbmon endet nie von selbst)
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
            return  # fremdes Gerät: nicht decodieren, nicht speichern
        record = parse_usbmon_line(raw.decode("ascii", "replace"))
        if record is None:
            return
        self.matched += 1
        self._monitor.feed(record, self._clock())
