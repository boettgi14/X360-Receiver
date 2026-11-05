"""Einrichten und Entfernen des systemd-Dienstes „Controller beim Herunterfahren ausschalten“.

Warum: Decky stoppt das Plugin beim Herunterfahren nicht zuverlässig (am Gerät beobachtet: Das Plugin
bekam das Stoppsignal, rief `_unload` aber nie auf und wurde nach 5 s mit SIGKILL beendet; zwei andere
Plugins ebenso). Ein systemd-Dienst läuft unabhängig davon: `ExecStop` wird beim Herunterfahren und
Neustart ausgeführt, solange USB noch da ist.

Was angelegt wird (nur auf ausdrücklichen Wunsch, wenn die Option „Beim Herunterfahren ausschalten“
eingeschaltet wird, und beim Ausschalten der Option und beim Entfernen des Plugins wieder gelöscht):
  /etc/systemd/system/x360-receiver-poweroff.service   Dienst (Type=oneshot, RemainAfterExit)
  /var/lib/x360-receiver/                              Kopie des Programms (root-eigen, nicht schreibbar für andere)
      poweroff.py, x360w/*.py, last-run.json (Bericht des letzten Laufs)

Fremde Aufrufe (fest, ohne Nutzereingabe, über `safe_exec.run_fixed`): `systemctl daemon-reload`,
`systemctl enable --now <Dienst>`, `systemctl disable --now <Dienst>`.

Sicherheit: Das Programm läuft als Root. Verzeichnis und Dateien gehören deshalb Root und sind nur für Root
schreibbar; Symlinks an den Zielorten werden abgelehnt.

Am Gerät bestätigt (Nutzer, 2026-11-05): Der Dienst läuft auf Bazzite und schaltet die Controller beim
Herunterfahren aus. Nicht gezielt geprüft: Neustart und mehrere Controller.
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
SYSTEMCTL_TIMEOUT_S = 20.0  # daemon-reload und enable --now können einen Moment dauern

# Alle Module, die `poweroff_cli` zum Laufen braucht (ein Test prüft, dass die Kopie für sich allein importierbar ist).
# Die `__init__.py` des Plugins zieht das ganze Paket nach (Dienst, Monitor …); die Kopie bekommt eine leere.
HELPER_MODULES = (
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

INIT_SOURCE = '''"""x360w, Kopie für den Dienst x360-receiver-poweroff (vom Plugin X360 Receiver angelegt)."""
'''

ENTRY_SOURCE = '''"""Einstieg des Dienstes x360-receiver-poweroff (vom Plugin X360 Receiver angelegt)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from x360w import poweroff_cli  # noqa: E402

sys.exit(poweroff_cli.main(HERE))
'''

Runner = Callable[..., object]


def render_unit(lib_dir: Path = LIB_DIR) -> str:
    entry = lib_dir / ENTRY_NAME
    return (
        "[Unit]\n"
        "Description=X360 Receiver: Controller beim Herunterfahren ausschalten (vom Decky-Plugin angelegt)\n"
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
        raise UnitError(f"{path} ist ein Symlink und wird nicht benutzt")


def _write_file(path: Path, data: bytes, mode: int = 0o644) -> bool:
    """Schreibt atomar, nur wenn sich der Inhalt ändert. Gibt zurück, ob geschrieben wurde."""
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
        raise UnitError(f"systemctl {' '.join(args)} (Rückgabewert {code}): {detail}")


def install(
    package_dir: Path,
    lib_dir: Path = LIB_DIR,
    unit_dir: Path = UNIT_DIR,
    runner: Optional[Runner] = None,
) -> Dict[str, object]:
    """Legt Programm und Dienst an (oder aktualisiert sie) und startet den Dienst. Wirft nie."""
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
        _systemctl(runner, "enable", "--now", UNIT_NAME)  # ohne --now wäre er erst nach dem nächsten Start aktiv
        return {"ok": True, "changed": changed or unit_changed}
    except Exception as exc:  # OSError, UnitError, subprocess.TimeoutExpired …
        error = f"{type(exc).__name__}: {exc}"[:300]
        uninstall(lib_dir, unit_dir, runner)  # nichts Halbfertiges liegen lassen
        return {"ok": False, "error": error}


def _remove_lib_dir(lib_dir: Path) -> None:
    if lib_dir.name != "x360-receiver":
        raise UnitError(f"unerwarteter Ordner {lib_dir}")
    if lib_dir.is_symlink():
        raise UnitError(f"{lib_dir} ist ein Symlink und wird nicht gelöscht")
    if lib_dir.is_dir():
        shutil.rmtree(lib_dir)


def uninstall(
    lib_dir: Path = LIB_DIR,
    unit_dir: Path = UNIT_DIR,
    runner: Optional[Runner] = None,
) -> Dict[str, object]:
    """Entfernt Dienst und Programm. Fehlt etwas, ist das kein Fehler. Wirft nie."""
    runner = runner or subprocess.run
    errors: List[str] = []
    unit_path = unit_dir / UNIT_NAME
    had_unit = unit_path.exists() or unit_path.is_symlink()
    try:
        # Zuerst das Programm löschen: Das Stoppen des Dienstes führt ExecStop aus, das ohne Programm
        # wegen des „-“ vor dem Befehl ohne Wirkung bleibt (sonst würden die Controller jetzt ausgehen).
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
    """Urteil und Zeilen für die Diagnose-Anzeige; None, wenn es nichts zu zeigen gibt."""
    if not enabled and last_run is None:
        return None
    lines: List[str] = []
    if enabled and install_error:
        verdict = "Der Dienst ist nicht eingerichtet: " + install_error
    elif enabled and not installed:
        verdict = "Der Dienst ist nicht eingerichtet."
    elif last_run is None:
        verdict = "Der Dienst ist eingerichtet und hat noch nicht gelaufen. Er läuft beim nächsten Herunterfahren."
    else:
        verdict = _verdict_of_run(last_run)
        if not enabled:
            verdict += " (Option ist jetzt aus.)"
    if last_run is not None:
        lines = _lines_of_run(last_run, localtime)
    return {"verdict": verdict, "lines": lines}


def _verdict_of_run(run: dict) -> str:
    if run.get("error"):
        return "Der Dienst lief beim letzten Herunterfahren, scheiterte aber: " + str(run["error"])
    result = run.get("result") or {}
    targets = run.get("targets") or []
    if not targets:
        return "Der Dienst lief beim letzten Herunterfahren, fand aber keinen verbundenen Controller."
    sent, errors = result.get("sent", 0), result.get("errors") or []
    if errors:
        return f"Der Dienst lief beim letzten Herunterfahren: {sent} von {len(targets)} Controllern ausgeschaltet, Fehler: {errors[0]}"
    return f"Der Dienst lief beim letzten Herunterfahren: {sent} von {len(targets)} Controllern ausgeschaltet."


def _lines_of_run(run: dict, localtime: Callable[[float], time.struct_time]) -> List[str]:
    lines = []
    at = run.get("at")
    if isinstance(at, (int, float)):
        lines.append("Zeit: " + time.strftime("%Y-%m-%d %H:%M:%S", localtime(at)))
    lines.append(f"Dauer: {run.get('duration_s', '?')} s, Receiver: {run.get('receivers', '?')}")
    lines.append(f"Ziele (Bus, Gerät, Slot): {run.get('targets')}")
    result = run.get("result")
    if result is not None:
        lines.append(f"Ergebnis: {result}")
    if run.get("error"):
        lines.append(f"Fehler: {run['error']}")
    if run.get("write_error"):
        lines.append(f"Bericht nicht geschrieben: {run['write_error']}")
    return lines
