"""Parser für das usbmon-Textformat (/sys/kernel/debug/usb/usbmon/<bus>u).

Zeilenformat laut Kernel-Dokumentation (Documentation/usb/usbmon.rst):
  <urb-tag> <timestamp-us> <event S|C|E> <Xx:bus:dev:ep> <status[:interval]> <length> [= <daten-hex-wörter>]

Hinweis: Das Textformat zeigt nur einen begrenzten Datenanfang. Die Pakete des
Receivers sind 28/29 Bytes lang. Ob alles ankommt, ist in Phase 0 zu prüfen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UsbmonRecord:
    tag: str
    timestamp_us: int
    event: str  # "S" Submit, "C" Complete, "E" Error
    xfer_type: str  # "C" Control, "Z" Iso, "I" Interrupt, "B" Bulk
    direction: str  # "i" oder "o"
    bus: int
    device: int
    endpoint: int
    status: str
    length: int
    data: bytes


def parse_usbmon_line(line: str) -> Optional[UsbmonRecord]:
    parts = line.strip().split()
    if len(parts) < 6:
        return None

    tag, ts, event, addr, status, length = parts[:6]

    if event not in ("S", "C", "E"):
        return None

    addr_parts = addr.split(":")
    if len(addr_parts) != 4 or len(addr_parts[0]) != 2:
        return None

    try:
        timestamp = int(ts)
        bus = int(addr_parts[1])
        device = int(addr_parts[2])
        endpoint = int(addr_parts[3])
        # Bei Control-Transfers steht an Stelle von <length> ein "s" (Setup).
        # Solche Zeilen interessieren hier nicht.
        data_length = int(length)
    except ValueError:
        return None

    data = b""
    if "=" in parts[6:]:
        idx = parts.index("=", 6)
        hex_text = "".join(parts[idx + 1 :])
        try:
            data = bytes.fromhex(hex_text)
        except ValueError:
            return None

    return UsbmonRecord(
        tag=tag,
        timestamp_us=timestamp,
        event=event,
        xfer_type=addr_parts[0][0],
        direction=addr_parts[0][1],
        bus=bus,
        device=device,
        endpoint=endpoint,
        status=status,
        length=data_length,
        data=data,
    )
