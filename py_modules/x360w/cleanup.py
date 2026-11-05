"""Aufräumen beim Entfernen des Plugins (Decky ruft `_uninstall` vor dem Löschen des Plugin-Ordners).

Decky löscht nur den Plugin-Ordner selbst. Die Verzeichnisse unter DECKY_HOME/settings, /data
und /logs bleiben sonst liegen. Das Backend läuft als root, deshalb wird nur gelöscht, was
sicher zum Plugin gehört (siehe `remove_plugin_dir`).

Decky ruft `_uninstall` auch beim Neuinstallieren desselben Plugins (Update per ZIP) auf.
Gespeicherte Einstellungen gehen dabei verloren; der Monitor ist danach wieder aus.
"""

from __future__ import annotations

import os
import shutil
from typing import Callable, Optional

from . import controls

ALLOWED_PARENTS = ("settings", "data", "logs")


def remove_plugin_dir(path: Optional[str], decky_home: Optional[str], rmtree: Callable = shutil.rmtree) -> bool:
    """Löscht `path` nur, wenn es genau `<decky_home>/<settings|data|logs>/<Name>` ist.

    Kein Symlink, kein Pfad außerhalb von DECKY_HOME, kein Eintrag mit `..`. Gibt True zurück,
    wenn gelöscht wurde. Fehlt das Verzeichnis, ist das kein Fehler (False).
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
    # /home ist auf Bazzite ein Symlink nach /var/home; deshalb DECKY_HOME selbst auflösen,
    # darunter aber keinen weiteren Symlink zulassen.
    if os.path.realpath(path) != os.path.join(os.path.realpath(home), kind, name):
        return False
    rmtree(path)
    return True


def restore_auto_poweroff(original: object, setter: Callable = controls.set_auto_poweroff,
                          getter: Callable = controls.get_auto_poweroff) -> bool:
    """Stellt den Wert wieder her, den `auto_poweroff` vor der ersten Änderung durch das Plugin hatte."""
    if not isinstance(original, bool):
        return False
    if getter() is original:
        return False
    setter(original)
    return True
