"""Fixed program calls with a sanitized environment.

The Decky backend is a PyInstaller program and can pass a foreign `LD_LIBRARY_PATH` on to its
child processes; system programs such as `systemctl` then load the wrong libraries and fail. Decky
itself therefore starts its child processes with an empty environment (`env={}`).
Here: an absolute path from a fixed search path and an environment with only PATH and LANG.
`LANG=C` and `LC_ALL=C` also make the output of external programs independent of the system language,
so the plugin behaves the same on a German and an English system.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable, Sequence

SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def safe_env() -> dict:
    return {"PATH": SAFE_PATH, "LANG": "C", "LC_ALL": "C"}


def run_fixed(argv: Sequence[str], timeout: float, runner: Callable = subprocess.run):
    """Runs a fixed command. `argv` must not contain user input."""
    executable = shutil.which(argv[0], path=SAFE_PATH) or argv[0]
    return runner(
        [executable, *argv[1:]],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=safe_env(),
    )
