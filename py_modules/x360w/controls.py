"""Steuerung über die Kernel-Schnittstellen von xpad (sysfs). Kein Shell-Aufruf.

Geschrieben wird ausschließlich in:
  /sys/class/leds/xpadN/brightness           (N = Zahl; nur Namen der Form xpadN)
  /sys/module/xpad/parameters/auto_poweroff

Die LED-Modi stammen aus den Kommentaren in drivers/input/joystick/xpad.c. Die LED xpadN
existiert nur, solange ein Controller verbunden ist (am Gerät bestätigt).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

LED_BASE = Path("/sys/class/leds")
AUTO_POWEROFF_PARAM = Path("/sys/module/xpad/parameters/auto_poweroff")
LED_NAME_RE = re.compile(r"xpad[0-9]{1,3}")

LED_MODES: Dict[int, str] = {
    0: "aus",
    1: "alle blinken, dann vorheriger Zustand",
    2: "Position 1 blinkt, dann an",
    3: "Position 2 blinkt, dann an",
    4: "Position 3 blinkt, dann an",
    5: "Position 4 blinkt, dann an",
    6: "Position 1 an",
    7: "Position 2 an",
    8: "Position 3 an",
    9: "Position 4 an",
    10: "rotierend",
    11: "blinkend, nach vorherigem Zustand",
    12: "langsam blinkend, nach vorherigem Zustand",
    13: "rotierend mit zwei Lichtern",
    14: "dauerhaft langsam alle blinkend",
    15: "einmal blinken, dann vorheriger Zustand",
}


def _led_number(name: str) -> int:
    return int(name[4:])


def list_leds(base: Optional[Path] = None) -> List[str]:
    base = base or LED_BASE
    try:
        names = [p.name for p in base.iterdir() if LED_NAME_RE.fullmatch(p.name)]
    except OSError:
        return []
    return sorted(names, key=_led_number)


def led_owner(name: str, base: Optional[Path] = None) -> Optional[str]:
    """USB-Pfad des Receivers (z. B. "1-3"), dem die LED gehört.

    xpad registriert die LED am USB-Gerät des Receivers (`led_classdev_register(&xpad->udev->dev …)`),
    der aufgelöste Pfad endet also auf `<usb_path>/leds/<name>`. Einem einzelnen Slot lässt sich die
    LED so nicht zuordnen. Aus dem Quelltext abgeleitet, am Gerät nicht geprüft.
    """
    if not isinstance(name, str) or not LED_NAME_RE.fullmatch(name):
        return None
    try:
        real = ((base or LED_BASE) / name).resolve()
    except OSError:
        return None
    if real.parent.name != "leds":
        return None
    return real.parent.parent.name or None


def led_owners(base: Optional[Path] = None) -> Dict[str, List[str]]:
    """LED-Namen je Receiver-USB-Pfad."""
    owners: Dict[str, List[str]] = {}
    for name in list_leds(base):
        owner = led_owner(name, base)
        if owner is not None:
            owners.setdefault(owner, []).append(name)
    return owners


def default_led_mode(name: str) -> int:
    """Was xpad nach dem Verbinden selbst setzt: (N mod 4) + 2."""
    _check_name(name)
    return (_led_number(name) % 4) + 2


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not LED_NAME_RE.fullmatch(name):
        raise ValueError(f"Ungültiger LED-Name: {name!r}")


def set_led_mode(name: str, mode: int, base: Optional[Path] = None) -> None:
    _check_name(name)
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 15:
        raise ValueError(f"LED-Modus muss eine ganze Zahl von 0 bis 15 sein, nicht {mode!r}")
    path = (base or LED_BASE) / name / "brightness"
    if not path.exists():
        raise FileNotFoundError(f"{name} existiert nicht (Controller verbunden?)")
    with open(path, "w", encoding="ascii") as handle:
        handle.write(f"{mode}\n")


def reset_led(name: str, base: Optional[Path] = None) -> None:
    set_led_mode(name, default_led_mode(name), base)


def get_auto_poweroff(path: Optional[Path] = None) -> Optional[bool]:
    try:
        text = (path or AUTO_POWEROFF_PARAM).read_text(encoding="ascii").strip().lower()
    except OSError:
        return None
    if text in ("y", "1"):
        return True
    if text in ("n", "0"):
        return False
    return None


def set_auto_poweroff(enabled: bool, path: Optional[Path] = None) -> None:
    if not isinstance(enabled, bool):
        raise ValueError("enabled muss True oder False sein")
    target = path or AUTO_POWEROFF_PARAM
    with open(target, "w", encoding="ascii") as handle:
        handle.write("Y\n" if enabled else "N\n")
