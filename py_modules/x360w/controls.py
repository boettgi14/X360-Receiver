"""Control through xpad's kernel interfaces (sysfs). No shell calls.

Writes only to:
  /sys/class/leds/xpadN/brightness           (N = number; only names of the form xpadN)
  /sys/module/xpad/parameters/auto_poweroff

The LED modes come from the comments in drivers/input/joystick/xpad.c. The LED xpadN exists
only while a controller is connected (confirmed on hardware).

The mode descriptions here are English and language-neutral. The frontend shows its own
translated names and uses these only as a fallback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

LED_BASE = Path("/sys/class/leds")
AUTO_POWEROFF_PARAM = Path("/sys/module/xpad/parameters/auto_poweroff")
LED_NAME_RE = re.compile(r"xpad[0-9]{1,3}")

LED_MODES: Dict[int, str] = {
    0: "off",
    1: "all blinking, then previous state",
    2: "position 1 blinking, then on",
    3: "position 2 blinking, then on",
    4: "position 3 blinking, then on",
    5: "position 4 blinking, then on",
    6: "position 1 on",
    7: "position 2 on",
    8: "position 3 on",
    9: "position 4 on",
    10: "rotating",
    11: "blinking, based on previous state",
    12: "slow blinking, based on previous state",
    13: "rotating with two lights",
    14: "all slowly blinking, permanently",
    15: "blink once, then previous state",
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
    """USB path of the receiver (e.g. "1-3") that owns the LED.

    xpad registers the LED on the receiver's USB device (`led_classdev_register(&xpad->udev->dev …)`),
    so the resolved path ends in `<usb_path>/leds/<name>`. This does not tie a LED to a single slot.
    Derived from the source code, not checked on the device.
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
    """LED names per receiver USB path."""
    owners: Dict[str, List[str]] = {}
    for name in list_leds(base):
        owner = led_owner(name, base)
        if owner is not None:
            owners.setdefault(owner, []).append(name)
    return owners


def default_led_mode(name: str) -> int:
    """What xpad itself sets after connecting: (N mod 4) + 2."""
    _check_name(name)
    return (_led_number(name) % 4) + 2


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not LED_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid LED name: {name!r}")


def set_led_mode(name: str, mode: int, base: Optional[Path] = None) -> None:
    _check_name(name)
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 15:
        raise ValueError(f"LED mode must be an integer from 0 to 15, not {mode!r}")
    path = (base or LED_BASE) / name / "brightness"
    if not path.exists():
        raise FileNotFoundError(f"{name} does not exist (controller connected?)")
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
        raise ValueError("enabled must be True or False")
    target = path or AUTO_POWEROFF_PARAM
    with open(target, "w", encoding="ascii") as handle:
        handle.write("Y\n" if enabled else "N\n")
