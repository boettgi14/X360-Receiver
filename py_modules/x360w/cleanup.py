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


def refusal_reason(path: Optional[str], decky_home: Optional[str]) -> Optional[str]:
    """Why `remove_plugin_dir` would not delete `path`, or None if it would.

    Allowed is exactly `<decky_home>/<settings|data|logs>/<name>`: no symlink, no path outside
    DECKY_HOME, no entry containing `..`. The reason is English text for the log.
    """
    if not path or not decky_home:
        return f"path or DECKY_HOME missing (path={path!r}, DECKY_HOME={decky_home!r})"
    if not os.path.isabs(path) or not os.path.isabs(decky_home):
        return f"path or DECKY_HOME is not absolute (path={path!r}, DECKY_HOME={decky_home!r})"
    path = os.path.normpath(path)
    home = os.path.normpath(decky_home)
    parent, name = os.path.split(path)
    grand, kind = os.path.split(parent)
    if grand != home or kind not in ALLOWED_PARENTS or name in ("", ".", ".."):
        return f"{path!r} is not exactly DECKY_HOME/(settings|data|logs)/<name> (DECKY_HOME={home!r})"
    if os.path.islink(path):
        return f"{path!r} is a symlink"
    if not os.path.isdir(path):
        return f"{path!r} does not exist"
    # /home is a symlink to /var/home on Bazzite; so resolve DECKY_HOME itself,
    # but allow no further symlink below it.
    expected = os.path.join(os.path.realpath(home), kind, name)
    if os.path.realpath(path) != expected:
        return f"{path!r} resolves to {os.path.realpath(path)!r} instead of {expected!r} (symlink in the path?)"
    return None


def remove_plugin_dir(path: Optional[str], decky_home: Optional[str], rmtree: Callable = shutil.rmtree) -> bool:
    """Deletes `path` only if `refusal_reason` finds nothing against it. Returns True if something was deleted.

    A missing directory is not an error (False).
    """
    if refusal_reason(path, decky_home) is not None:
        return False
    rmtree(os.path.normpath(path))
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
