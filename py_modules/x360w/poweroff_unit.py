"""Setting up and removing the systemd service "turn off controllers on shutdown".

Why: Decky does not reliably stop the plugin on shutdown (observed on the device: the plugin
received the stop signal, never called `_unload` and was killed with SIGKILL after 5 s; two other
plugins behaved the same). A systemd service runs independently of that: `ExecStop` runs on
shutdown and reboot while USB is still there.

What gets created (only on explicit request, when the option "Turn off on shutdown" is switched on,
and deleted again when the option is switched off and when the plugin is removed):
  /etc/systemd/system/x360-receiver-poweroff.service   service (Type=oneshot, RemainAfterExit)
  /var/lib/x360-receiver/                              copy of the program (owned by root, not writable by others)
      poweroff.py, x360w/*.py, last-run.json (report of the last run)

External calls (fixed, no user input, through `safe_exec.run_fixed`): `systemctl daemon-reload`,
`systemctl enable --now <service>`, `systemctl disable --now <service>`.

Security: The program runs as root. Directory and files therefore belong to root and are writable
only by root; symlinks at the target locations are rejected.

Confirmed on the device (user, 2026-11-05): The service runs on Bazzite and turns the controllers
off on shutdown. Not specifically tested: reboot and several controllers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .safe_exec import run_fixed

UNIT_NAME = "x360-receiver-poweroff.service"
UNIT_DIR = Path("/etc/systemd/system")
LIB_DIR = Path("/var/lib/x360-receiver")
ENTRY_NAME = "poweroff.py"
PACKAGE_NAME = "x360w"
LAST_RUN_NAME = "last-run.json"
SYSTEMCTL_TIMEOUT_S = 20.0  # daemon-reload and enable --now can take a moment

# All modules `poweroff_cli` needs to run (a test checks that the copy can be imported on its own).
# The plugin's `__init__.py` pulls in the whole package (service, monitor …); the copy gets an empty one.
HELPER_MODULES = (
    "error_codes.py",
    "protocol.py",
    "usbmon.py",
    "monitor.py",
    "takeover.py",
    "actions.py",
    "discovery.py",
    "controls.py",
    "view.py",
    "shutdown.py",
    "poweroff_cli.py",
)

INIT_SOURCE = '''"""x360w, copy for the x360-receiver-poweroff service (created by the X360 Receiver plugin)."""
'''

ENTRY_SOURCE = '''"""Entry point of the x360-receiver-poweroff service (created by the X360 Receiver plugin)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from x360w import poweroff_cli  # noqa: E402

sys.exit(poweroff_cli.main(HERE))
'''

Runner = Callable[..., object]

# What `summarize` can emit; the frontend (src/i18n.ts) has a translation for each
# (checked by tests/test_i18n_contract.py).
VERDICT_CODES = (
    "install_failed",
    "not_installed",
    "not_run_yet",
    "run_failed",
    "run_no_controllers",
    "run_partial",
    "run_ok",
)
LINE_KEYS = ("time", "duration", "receivers", "targets", "result", "error", "write_error")


def render_unit(lib_dir: Path = LIB_DIR) -> str:
    entry = lib_dir / ENTRY_NAME
    return (
        "[Unit]\n"
        "Description=X360 Receiver: turn off controllers on shutdown (created by the Decky plugin)\n"
        f"RequiresMountsFor={lib_dir}\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        "ExecStart=/usr/bin/true\n"
        f"ExecStop=-/usr/bin/python3 -I {entry}\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        "TimeoutStopSec=12\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


class UnitError(RuntimeError):
    pass


def _check_not_symlink(path: Path) -> None:
    if path.is_symlink():
        raise UnitError(f"{path} is a symlink and will not be used")


def _write_file(path: Path, data: bytes, mode: int = 0o644) -> bool:
    """Writes atomically, only if the content changes. Returns whether anything was written."""
    _check_not_symlink(path)
    try:
        if path.read_bytes() == data and (path.stat().st_mode & 0o777) == mode:
            return False
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return True


def _make_dir(path: Path) -> None:
    _check_not_symlink(path)
    path.mkdir(mode=0o755, exist_ok=True)
    os.chmod(path, 0o755)


def _systemctl(runner: Runner, *args: str) -> None:
    result = run_fixed(["systemctl", *args], SYSTEMCTL_TIMEOUT_S, runner)
    code = getattr(result, "returncode", 0)
    if code != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()[:200]
        raise UnitError(f"systemctl {' '.join(args)} (return code {code}): {detail}")


def install(
    package_dir: Path,
    lib_dir: Path = LIB_DIR,
    unit_dir: Path = UNIT_DIR,
    runner: Optional[Runner] = None,
) -> Dict[str, object]:
    """Creates (or updates) program and service and starts the service. Never raises."""
    runner = runner or subprocess.run
    try:
        sources = {name: (package_dir / name).read_bytes() for name in HELPER_MODULES}
        _make_dir(lib_dir)
        _make_dir(lib_dir / PACKAGE_NAME)
        changed = False
        for name, data in sources.items():
            changed |= _write_file(lib_dir / PACKAGE_NAME / name, data)
        changed |= _write_file(lib_dir / PACKAGE_NAME / "__init__.py", INIT_SOURCE.encode("utf-8"))
        changed |= _write_file(lib_dir / ENTRY_NAME, ENTRY_SOURCE.encode("utf-8"))
        unit_changed = _write_file(unit_dir / UNIT_NAME, render_unit(lib_dir).encode("utf-8"))
        if unit_changed:
            _systemctl(runner, "daemon-reload")
        _systemctl(runner, "enable", "--now", UNIT_NAME)  # without --now it would only be active after the next boot
        return {"ok": True, "changed": changed or unit_changed}
    except Exception as exc:  # OSError, UnitError, subprocess.TimeoutExpired …
        error = f"{type(exc).__name__}: {exc}"[:300]
        uninstall(lib_dir, unit_dir, runner)  # leave nothing half-finished behind
        return {"ok": False, "error": error}


def _remove_lib_dir(lib_dir: Path) -> None:
    if lib_dir.name != "x360-receiver":
        raise UnitError(f"unexpected directory {lib_dir}")
    if lib_dir.is_symlink():
        raise UnitError(f"{lib_dir} is a symlink and will not be deleted")
    if lib_dir.is_dir():
        shutil.rmtree(lib_dir)


def uninstall(
    lib_dir: Path = LIB_DIR,
    unit_dir: Path = UNIT_DIR,
    runner: Optional[Runner] = None,
) -> Dict[str, object]:
    """Removes service and program. Something missing is not an error. Never raises."""
    runner = runner or subprocess.run
    errors: List[str] = []
    unit_path = unit_dir / UNIT_NAME
    had_unit = unit_path.exists() or unit_path.is_symlink()
    try:
        # Delete the program first: stopping the service runs ExecStop, which has no effect without
        # the program because of the "-" before the command (otherwise the controllers would turn off now).
        _remove_lib_dir(lib_dir)
    except (OSError, UnitError) as exc:
        errors.append(str(exc)[:200])
    if had_unit:
        try:
            _systemctl(runner, "disable", "--now", UNIT_NAME)
        except Exception as exc:
            errors.append(str(exc)[:200])
        try:
            unit_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append(str(exc)[:200])
        try:
            _systemctl(runner, "daemon-reload")
        except Exception as exc:
            errors.append(str(exc)[:200])
    return {"ok": not errors, "errors": errors}


def is_installed(lib_dir: Path = LIB_DIR, unit_dir: Path = UNIT_DIR) -> bool:
    return (unit_dir / UNIT_NAME).is_file() and (lib_dir / ENTRY_NAME).is_file()


def read_last_run(lib_dir: Path = LIB_DIR) -> Optional[dict]:
    try:
        data = json.loads((lib_dir / LAST_RUN_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def summarize(
    enabled: bool,
    installed: bool,
    last_run: Optional[dict],
    install_error: Optional[str] = None,
    localtime: Callable[[float], time.struct_time] = time.localtime,
) -> Optional[Dict[str, object]]:
    """Verdict and detail lines for the diagnostics display; None if there is nothing to show.

    The result is language-neutral: `verdict` is a dict with a `code` and its parameters, `lines` is
    a list of {"key", "value"} pairs. The frontend turns both into text in the user's language.

    Verdict codes (parameters in brackets):
      install_failed (error)   not_installed   not_run_yet
      run_failed (error)       run_no_controllers
      run_partial (sent, total, error)   run_ok (sent, total)
    The run_* verdicts carry `option_off: True` when the option has been switched off since.
    """
    if not enabled and last_run is None:
        return None
    verdict: Dict[str, object]
    if enabled and install_error:
        verdict = {"code": "install_failed", "error": install_error}
    elif enabled and not installed:
        verdict = {"code": "not_installed"}
    elif last_run is None:
        verdict = {"code": "not_run_yet"}
    else:
        verdict = _verdict_of_run(last_run)
        if not enabled:
            verdict["option_off"] = True
    lines: List[Dict[str, str]] = []
    if last_run is not None:
        lines = _lines_of_run(last_run, localtime)
    return {"verdict": verdict, "lines": lines}


def _verdict_of_run(run: dict) -> Dict[str, object]:
    if run.get("error"):
        return {"code": "run_failed", "error": str(run["error"])}
    result = run.get("result") or {}
    targets = run.get("targets") or []
    if not targets:
        return {"code": "run_no_controllers"}
    sent, errors = result.get("sent", 0), result.get("errors") or []
    if errors:
        return {"code": "run_partial", "sent": sent, "total": len(targets), "error": str(errors[0])}
    return {"code": "run_ok", "sent": sent, "total": len(targets)}


def _lines_of_run(run: dict, localtime: Callable[[float], time.struct_time]) -> List[Dict[str, str]]:
    """Detail lines as {"key", "value"}: keys time, duration, receivers, targets, result, error, write_error."""
    lines: List[Dict[str, str]] = []

    def add(key: str, value: object) -> None:
        lines.append({"key": key, "value": str(value)})

    at = run.get("at")
    if isinstance(at, (int, float)):
        add("time", time.strftime("%Y-%m-%d %H:%M:%S", localtime(at)))
    add("duration", f"{run.get('duration_s', '?')} s")
    add("receivers", run.get("receivers", "?"))
    add("targets", run.get("targets"))
    result = run.get("result")
    if result is not None:
        add("result", result)
    if run.get("error"):
        add("error", run["error"])
    if run.get("write_error"):
        add("write_error", run["write_error"])
    return lines
