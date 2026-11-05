"""Findet Xbox-360-Wireless-Receiver über sysfs. Nur lesend, keine Abhängigkeiten."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Set

# 0x0291/0x0719 laut argon.md, 0x02a9 laut xpad.c ("Unofficial")
RECEIVER_IDS = {
    (0x045E, 0x0291): "Xbox 360 Wireless Receiver (0291)",
    (0x045E, 0x0719): "Xbox 360 Wireless Receiver (0719)",
    (0x045E, 0x02A9): "Xbox 360 Wireless Receiver (inoffiziell, 02A9)",
}

DEFAULT_SYSFS_USB = Path("/sys/bus/usb/devices")


@dataclass
class InterfaceInfo:
    name: str
    number: int
    slot: Optional[int]  # 0..3 für Controller-Schnittstellen, None für Audio
    role: str  # "controller" oder "audio" oder "other"
    driver: Optional[str]


@dataclass
class ReceiverInfo:
    usb_path: str
    vendor_id: int
    product_id: int
    label: str
    bus: Optional[int]
    devnum: Optional[int]
    manufacturer: Optional[str]
    product: Optional[str]
    serial: Optional[str]
    firmware_bcd: Optional[str]
    interfaces: List[InterfaceInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _read_int(path: Path, base: int = 10) -> Optional[int]:
    text = _read(path)
    if text is None:
        return None
    try:
        return int(text, base)
    except ValueError:
        return None


def _driver_name(interface_dir: Path) -> Optional[str]:
    link = interface_dir / "driver"
    try:
        return link.resolve().name if link.exists() else None
    except OSError:
        return None


def _describe_interface(path: Path) -> Optional[InterfaceInfo]:
    number = _read_int(path / "bInterfaceNumber", 16)
    proto = _read_int(path / "bInterfaceProtocol", 16)
    sub = _read_int(path / "bInterfaceSubClass", 16)
    if number is None:
        return None
    if sub == 0x5D and proto == 0x81:
        role, slot = "controller", number // 2
    elif sub == 0x5D and proto == 0x82:
        role, slot = "audio", number // 2
    else:
        role, slot = "other", None
    return InterfaceInfo(
        name=path.name,
        number=number,
        slot=slot if role == "controller" else None,
        role=role,
        driver=_driver_name(path),
    )


def connected_slots_sysfs(receiver: ReceiverInfo, sysfs_usb: Path = DEFAULT_SYSFS_USB) -> Set[int]:
    """Slots, an denen xpad ein Eingabegerät angelegt hat (also ein Controller verbunden ist).

    xpad legt das Eingabegerät beim Verbinden an (`input_dev->dev.parent = &xpad->intf->dev`),
    es erscheint als `<Schnittstelle>/input/inputN`. Aus dem Quelltext abgeleitet, am Gerät nicht
    geprüft. Während eines kurzen Zugriffs (Treiber gelöst) fehlt es für einige Sekunden.
    """
    slots: Set[int] = set()
    for interface in receiver.interfaces:
        if interface.role != "controller" or interface.slot is None:
            continue
        try:
            if any(child.name.startswith("input") for child in (sysfs_usb / interface.name / "input").iterdir()):
                slots.add(interface.slot)
        except OSError:
            continue
    return slots


def find_receivers(sysfs_usb: Path = DEFAULT_SYSFS_USB) -> List[ReceiverInfo]:
    receivers: List[ReceiverInfo] = []
    if not sysfs_usb.is_dir():
        return receivers

    for dev in sorted(sysfs_usb.iterdir()):
        # Schnittstellen heißen "1-2:1.0", Geräte "1-2" bzw. "usb1"
        if ":" in dev.name:
            continue
        vid = _read_int(dev / "idVendor", 16)
        pid = _read_int(dev / "idProduct", 16)
        if vid is None or pid is None or (vid, pid) not in RECEIVER_IDS:
            continue

        info = ReceiverInfo(
            usb_path=dev.name,
            vendor_id=vid,
            product_id=pid,
            label=RECEIVER_IDS[(vid, pid)],
            bus=_read_int(dev / "busnum"),
            devnum=_read_int(dev / "devnum"),
            manufacturer=_read(dev / "manufacturer"),
            product=_read(dev / "product"),
            serial=_read(dev / "serial"),
            firmware_bcd=_read(dev / "bcdDevice"),
        )
        for child in sorted(dev.glob(f"{dev.name}:*")):
            interface = _describe_interface(child)
            if interface is not None:
                info.interfaces.append(interface)
        receivers.append(info)

    return receivers
