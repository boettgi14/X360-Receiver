"""Feste Programmaufrufe mit bereinigter Umgebung.

Das Decky-Backend ist ein PyInstaller-Programm und kann seinen Unterprozessen eine fremde
`LD_LIBRARY_PATH` vererben; Systemprogramme wie `systemctl` laden dann die falschen Bibliotheken
und scheitern. Decky selbst startet seine Unterprozesse deshalb mit leerer Umgebung (`env={}`).
Hier: absoluter Pfad aus einem festen Suchpfad und eine Umgebung mit nur PATH und LANG.

Ob genau das bei `systemctl` im Plugin das Problem war, ist am Gerät nicht belegt; es ist der
wahrscheinlichste Grund, den ich im Quelltext finden konnte.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable, Sequence

SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def safe_env() -> dict:
    return {"PATH": SAFE_PATH, "LANG": "C", "LC_ALL": "C"}


def run_fixed(argv: Sequence[str], timeout: float, runner: Callable = subprocess.run):
    """Führt ein festes Kommando aus. `argv` darf keine Nutzereingaben enthalten."""
    executable = shutil.which(argv[0], path=SAFE_PATH) or argv[0]
    return runner(
        [executable, *argv[1:]],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=safe_env(),
    )
