"""Cleaning up when the plugin is removed (Decky calls `_uninstall` before deleting the plugin folder).

Decky deletes only the plugin folder itself. The directories under DECKY_HOME/settings, /data and
/logs would otherwise stay behind. The backend runs as root, so only what certainly belongs to the
plugin is deleted (see `remove_plugin_dir`).

Decky also calls `_uninstall` when the same plugin is installed again (update from a ZIP). Saved
settings are lost in that case; the monitor is off again afterwards.
"""

from __future__ import annotations

import os
import shutil
from typing import Callable, Optional

from . import controls

ALLOWED_PARENTS = ("settings", "data", "logs")


def remove_plugin_dir(path: Optional[str], decky_home: Optional[str], rmtree: Callable = shutil.rmtree) -> bool:
    """Deletes `path` only if it is exactly `<decky_home>/<settings|data|logs>/<name>`.

    No symlink, no path outside DECKY_HOME, no entry containing `..`. Returns True if something was
    deleted. A missing directory is not an error (False).
    """
    if not path or not decky_home:
        return False
    if not os.path.isabs(path) or not os.path.isabs(decky_home):
        return False
    path = os.path.normpath(path)
    home = os.path.normpath(decky_home)
    parent, name = os.path.split(path)
    grand, kind = os.path.split(parent)
    if grand != home or kind not in ALLOWED_PARENTS or name in ("", ".", ".."):
        return False
    if os.path.islink(path) or not os.path.isdir(path):
        return False
    # /home is a symlink to /var/home on Bazzite; so resolve DECKY_HOME itself,
    # but allow no further symlink below it.
    if os.path.realpath(path) != os.path.join(os.path.realpath(home), kind, name):
        return False
    rmtree(path)
    return True


def restore_auto_poweroff(original: object, setter: Callable = controls.set_auto_poweroff,
                          getter: Callable = controls.get_auto_poweroff) -> bool:
    """Restores the value `auto_poweroff` had before the plugin first changed it."""
    if not isinstance(original, bool):
        return False
    if getter() is original:
        return False
    setter(original)
    return True
