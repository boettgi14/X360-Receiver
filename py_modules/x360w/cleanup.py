"""Undoing what the plugin changed, when it is removed (Decky calls `_uninstall`).

Only the kernel parameter `auto_poweroff` is restored here. The plugin deliberately does not delete its
settings, data and log folders under DECKY_HOME: Decky leaves them behind and they can be removed by hand
(see README). The systemd service is removed by `poweroff_unit.uninstall`.

Decky also calls `_uninstall` when the same plugin is installed again (update from a ZIP). The saved settings
stay in that case and are read again by the new version.
"""

from __future__ import annotations

from typing import Callable

from . import controls


def restore_auto_poweroff(original: object, setter: Callable = controls.set_auto_poweroff,
                          getter: Callable = controls.get_auto_poweroff) -> bool:
    """Restores the value `auto_poweroff` had before the plugin first changed it."""
    if not isinstance(original, bool):
        return False
    if getter() is original:
        return False
    setter(original)
    return True
