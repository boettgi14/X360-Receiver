"""Decky backend of the "X360 Receiver" plugin.

Runs with root rights ("root" in plugin.json; Decky checks for exactly this string). Writes only to the
paths named in x360w.controls. The USB monitor (usbmon) is off by default and is only switched on with
the user's explicit consent; the setting is saved.

The backend is language-neutral: it never produces text in the user's language. Failed actions return
{"ok": False, "error": <English text>} and, for failures a user can act on, an additional "code" (and
optionally "detail") that the frontend (src/i18n.ts) turns into a message in the Steam UI language.
The codes are listed in x360w.error_codes.

Saved settings (x360w.json): monitor_enabled, auto_poweroff (desired value, applied on start),
poweroff_on_shutdown, original_auto_poweroff (initial value, restored on removal), startup_battery_query
(default on), low_battery_toast (default on), language ("auto", or a language code chosen in the UI).

"Turn off on shutdown" is handled by a separate systemd service (x360w.poweroff_unit) that the
plugin creates when the option is switched on and deletes when it is switched off or the plugin is
removed: Decky does not reliably stop the plugin on shutdown (observed on the device).
"""

import asyncio
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# py_modules sits next to this file. Add it to the search path explicitly to be safe.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_modules"))

import decky  # noqa: E402  (only available under Decky Loader)

from x360w import (  # noqa: E402
    actions,
    cleanup,
    controls,
    discovery,
    error_codes,
    poweroff_unit,
    rumble,
    shutdown,
    view,
)
from x360w.battery_cache import BatteryCache  # noqa: E402
from x360w.low_battery import LowBatteryWatcher  # noqa: E402
from x360w.resume import ResumeDetector  # noqa: E402
from x360w.service import MonitorService  # noqa: E402

REFRESH_INTERVAL_S = 5.0
STARTUP_QUERY_DELAY_S = 1.0  # short pause after start so Decky can finish loading
QUERY_BUSY_RETRIES = 5
QUERY_BUSY_WAIT_S = 0.5
MAX_NOTICES = 16  # pending low-battery notices; older ones are dropped
LANGUAGE_RE = re.compile(r"auto|[a-z]{2}(-[A-Za-z]{2,4})?")
PACKAGE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "py_modules" / "x360w"


def _log(level: str, message: str) -> None:
    logger = getattr(decky, "logger", None)
    if logger is not None:
        getattr(logger, level)(message)


def _error(message: str, code: Optional[str] = None, detail: Optional[str] = None) -> dict:
    """Failure result: English `message`, optional `code` and `detail` for the frontend to translate."""
    result: dict = {"ok": False, "error": message}
    if code:
        result["code"] = code
        if detail:
            result["detail"] = detail
    return result


def _settings_path() -> str:
    base = getattr(decky, "DECKY_PLUGIN_SETTINGS_DIR", None) or getattr(
        decky, "DECKY_SETTINGS_DIR", os.getcwd()
    )
    return os.path.join(base, "x360w.json")


class Plugin:
    service: MonitorService
    refresh_task = None
    startup_task = None
    unit_task = None
    batteries: BatteryCache
    unit_error = None  # last error while setting up the service (text) or None
    low_battery: LowBatteryWatcher

    # -- Settings -----------------------------------------------------------

    def _load_settings(self) -> dict:
        try:
            with open(_settings_path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self, data: dict) -> None:
        path = _settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _remember_auto_poweroff(self) -> None:
        """On the first change, remembers the initial value so removal can restore it."""
        settings = self._load_settings()
        if "original_auto_poweroff" in settings:
            return
        current = controls.get_auto_poweroff()
        if current is None:
            return
        settings["original_auto_poweroff"] = current
        try:
            self._save_settings(settings)
        except OSError as exc:
            _log("error", f"Initial value not saved: {exc!r}")

    # -- Lifecycle ----------------------------------------------------------

    def _apply_auto_poweroff(self, enabled: bool) -> None:
        self._remember_auto_poweroff()
        controls.set_auto_poweroff(enabled)

    async def _main(self):
        self.service = MonitorService()
        self.batteries = BatteryCache()
        self.unit_error = None
        self._unit_lock = asyncio.Lock()  # one change of the service at a time (start reconciliation vs. toggle)
        self.low_battery = LowBatteryWatcher()
        self._notices = []
        self._notices_lock = threading.Lock()
        settings = self._load_settings()
        if isinstance(settings.get("auto_poweroff"), bool):
            try:
                self._apply_auto_poweroff(settings["auto_poweroff"])  # the kernel parameter is reset after a reboot
            except (ValueError, OSError) as exc:
                _log("error", f"auto_poweroff not applied: {exc!r}")
        if settings.get("monitor_enabled") is True:
            await asyncio.to_thread(self.service.enable)
        self.refresh_task = asyncio.get_event_loop().create_task(self._refresh_loop())
        self.startup_task = asyncio.get_event_loop().create_task(self._startup_battery_query())
        self.unit_task = asyncio.get_event_loop().create_task(self._sync_unit())
        _log("info", "x360w loaded")

    async def _sync_unit(self) -> None:
        """Reconciles the service with the setting: option on = service present and current, off = service gone.

        The setting is authoritative. Without this reconciliation a service would be left behind when the
        settings are lost (e.g. after reinstalling), and a plugin update would not bring the service's
        program up to date.
        """
        try:
            # Under the lock, so a toggle that is just being applied has saved its setting before we read it.
            async with self._unit_lock:
                enabled = self._load_settings().get("poweroff_on_shutdown") is True  # read now, do not remember from start
                if enabled:
                    result = await asyncio.to_thread(self._install_unit)
                    self.unit_error = None if result.get("ok") else result.get("error", "Unknown error")
                    if self.unit_error:
                        _log("error", f"Service not set up: {self.unit_error}")
                elif await asyncio.to_thread(poweroff_unit.is_installed):
                    result = await asyncio.to_thread(poweroff_unit.uninstall)
                    _log("info", f"Service removed (option is off): {result}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # must never keep the plugin from loading
            self.unit_error = f"{type(exc).__name__}: {exc}"[:300]
            _log("error", f"Service reconciliation failed: {exc!r}")

    def _install_unit(self) -> dict:
        return poweroff_unit.install(PACKAGE_DIR)

    async def _startup_battery_query(self):
        """Queries the battery of all already connected controllers once.

        The receiver reports the battery only when a controller connects; anyone who was connected
        before the plugin started would otherwise have no value. Cost: Each controller disappears in turn for about 3 s.
        """
        try:
            await asyncio.sleep(STARTUP_QUERY_DELAY_S)
            if self._load_settings().get("startup_battery_query") is False:
                _log("info", "Battery query after start is switched off")
                return
            targets = await asyncio.to_thread(self._connected_targets)
            _log("info", f"Battery query after start: {len(targets)} controllers {targets}")
            for bus, devnum, slot in targets:
                result = await asyncio.to_thread(self._query_and_cache, bus, devnum, slot)
                _log("info", f"Battery query bus {bus} device {devnum} slot {slot + 1}: {result}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # must never keep the plugin from loading
            _log("error", f"Battery query after start failed: {exc!r}")

    def _query_and_cache(self, bus: int, devnum: int, slot: int) -> dict:
        """Battery request (waits briefly if another access is running) and remembers the result."""
        for attempt in range(QUERY_BUSY_RETRIES + 1):
            result = actions.query_battery(bus, devnum, slot)
            if result.get("error") != actions.BUSY_ERROR or attempt == QUERY_BUSY_RETRIES:
                break
            time.sleep(QUERY_BUSY_WAIT_S)
        if result.get("ok") and result.get("state"):
            self.batteries.store((bus, devnum, slot), result["state"])
        return result

    async def _refresh_loop(self):
        detector = ResumeDetector()
        while True:
            await asyncio.sleep(REFRESH_INTERVAL_S)
            try:
                if detector.check():
                    _log("info", "Resume from suspend detected: restarting the usbmon readers")
                    await asyncio.to_thread(self.service.restart_readers)
                else:
                    await asyncio.to_thread(self.service.refresh)
                await asyncio.to_thread(self._collect_low_battery)
            except Exception as exc:  # the loop must never die
                _log("error", f"refresh failed: {exc!r}")

    def _collect_low_battery(self) -> None:
        """Queues a notice for every controller whose battery level has just become low."""
        if self._load_settings().get("low_battery_toast") is False:
            self.low_battery.reset()
            with self._notices_lock:
                self._notices.clear()
            return
        notices = self.low_battery.update(self._views(self.service.refresh()))
        if notices:
            with self._notices_lock:
                self._notices.extend({"slot": n["slot"], "level": n["level"]} for n in notices)
                del self._notices[:-MAX_NOTICES]

    async def _unload(self):
        for task in (self.refresh_task, self.startup_task, self.unit_task):
            if task is not None:
                task.cancel()
        await asyncio.to_thread(self.service.disable)
        _log("info", "x360w unloaded")

    async def _uninstall(self):
        """Called by Decky after `_unload` on removal (also when reinstalling from a ZIP).

        Restores auto_poweroff, removes the systemd service and deletes the plugin's own folders under
        DECKY_HOME. Decky deletes the plugin folder itself afterwards. Not undone: the loaded kernel
        module usbmon (until reboot) and LED modes (until the controller connects the next time).

        Decky kills a plugin that needs more than about 5 s to shut down (observed on the device), and
        removing the service runs `systemctl`, which can take a few seconds. So the folders are deleted
        at the same time as the service, not after it. Every refusal is logged with its reason.
        """
        try:
            original = self._load_settings().get("original_auto_poweroff")
            if cleanup.restore_auto_poweroff(original):
                _log("info", "auto_poweroff reset to its original value")
        except (OSError, ValueError) as exc:
            _log("error", f"auto_poweroff not reset: {exc!r}")
        _log("info", "x360w is being removed")

        async def remove_service() -> None:
            try:
                result = await asyncio.to_thread(poweroff_unit.uninstall)  # even if the option is off: leave no remnant behind
                _log("info", f"Service removed: {result}")
            except Exception as exc:  # must not keep the folders from being removed
                _log("error", f"Service not removed: {exc!r}")

        async def remove_folders() -> None:
            home = getattr(decky, "DECKY_HOME", None)
            for attr in ("DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR"):
                path = getattr(decky, attr, None)
                reason = cleanup.refusal_reason(path, home)
                if reason is not None:
                    _log("warning", f"{attr} not deleted: {reason}")
                    continue
                try:
                    await asyncio.to_thread(cleanup.remove_plugin_dir, path, home)
                except OSError as exc:
                    _log("error", f"{attr} not deleted: {exc!r}")

        await asyncio.gather(remove_service(), remove_folders())

    # -- Queries ------------------------------------------------------------

    async def get_receivers(self) -> list:
        return [r.to_dict() for r in await asyncio.to_thread(self.service.refresh)]

    def _views(self, receivers) -> list:
        views = view.build_receiver_views(
            receivers,
            self.service.snapshot(),
            controls.led_owners(),
            {r.usb_path: discovery.connected_slots_sysfs(r) for r in receivers},
            self.batteries.snapshot(),
        )
        self.batteries.prune(view.connected_targets(views))
        return views

    def _all_targets(self) -> list:
        return view.plan_targets(self._views(self.service.refresh()))

    def _connected_targets(self) -> list:
        return view.connected_targets(self._views(self.service.refresh()))

    @staticmethod
    def _language_setting(settings: dict) -> str:
        value = settings.get("language")
        return value if isinstance(value, str) and LANGUAGE_RE.fullmatch(value) else "auto"

    def _build_status(self) -> dict:
        receivers = self.service.refresh()
        settings = self._load_settings()
        return {
            "settings": {
                "monitor_enabled": self.service.status()["enabled"],
                "auto_poweroff": controls.get_auto_poweroff(),
                "poweroff_on_shutdown": settings.get("poweroff_on_shutdown") is True,
                "startup_query": settings.get("startup_battery_query") is not False,
                "low_battery_toast": settings.get("low_battery_toast") is not False,
                "language": self._language_setting(settings),
            },
            "monitor": self.service.status(),
            "receivers": self._views(receivers),
            "led_modes": {str(k): v for k, v in controls.LED_MODES.items()},
            "diagnostics": poweroff_unit.summarize(
                settings.get("poweroff_on_shutdown") is True,
                poweroff_unit.is_installed(),
                poweroff_unit.read_last_run(),
                self.unit_error,
            ),
        }

    async def get_status(self) -> dict:
        return await asyncio.to_thread(self._build_status)

    async def take_low_battery_notices(self) -> list:
        """Hands out (and forgets) the pending low-battery notices; the frontend shows them as toasts.

        Pulled by the frontend instead of pushed, so nothing is lost if the UI is not loaded yet when a
        notice arises. Each notice is {"slot", "level", "language"}; "language" is the UI language setting.
        """
        with self._notices_lock:
            notices, self._notices = self._notices, []
        language = self._language_setting(self._load_settings())
        return [dict(notice, language=language) for notice in notices]

    # -- Actions ------------------------------------------------------------

    def _set_flag(self, key: str, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            return _error("enabled must be a boolean")
        settings = self._load_settings()
        settings[key] = enabled
        try:
            self._save_settings(settings)
        except OSError as exc:
            return _error(f"Setting not saved: {exc}", error_codes.SETTINGS_NOT_SAVED, str(exc))
        return {"ok": True}

    async def set_startup_query(self, enabled: bool) -> dict:
        """Whether already connected controllers are queried once when the plugin starts."""
        return self._set_flag("startup_battery_query", enabled)

    async def set_low_battery_toast(self, enabled: bool) -> dict:
        """Whether a notification appears when a controller reports a low battery level."""
        return self._set_flag("low_battery_toast", enabled)

    async def set_language(self, language: str) -> dict:
        """UI language: "auto" (follow Steam) or a language code. The frontend decides what it supports."""
        if not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language):
            return _error("Invalid language")
        settings = self._load_settings()
        settings["language"] = language
        try:
            self._save_settings(settings)
        except OSError as exc:
            return _error(f"Setting not saved: {exc}", error_codes.SETTINGS_NOT_SAVED, str(exc))
        return {"ok": True}

    async def set_monitor_enabled(self, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            return _error("enabled must be a boolean")
        settings = self._load_settings()
        settings["monitor_enabled"] = enabled
        try:
            self._save_settings(settings)
        except OSError as exc:
            _log("error", f"Setting not saved: {exc!r}")
        if enabled:
            await asyncio.to_thread(self.service.enable)
        else:
            await asyncio.to_thread(self.service.disable)
        return {"ok": True}

    async def set_led(self, name: str, mode: int) -> dict:
        try:
            controls.set_led_mode(name, mode)
        except FileNotFoundError as exc:  # the LED only exists while the controller is connected
            return _error(str(exc), error_codes.LED_MISSING)
        except (ValueError, OSError) as exc:
            return _error(str(exc))
        return {"ok": True}

    async def reset_led(self, name: str) -> dict:
        try:
            controls.reset_led(name)
        except FileNotFoundError as exc:
            return _error(str(exc), error_codes.LED_MISSING)
        except (ValueError, OSError) as exc:
            return _error(str(exc))
        return {"ok": True}

    async def set_auto_poweroff(self, enabled: bool) -> dict:
        """Standby: turn controllers off (kernel parameter xpad.auto_poweroff). Saved and set again on start."""
        try:
            self._apply_auto_poweroff(enabled)
        except (ValueError, OSError) as exc:
            return _error(str(exc))
        settings = self._load_settings()
        settings["auto_poweroff"] = enabled
        try:
            self._save_settings(settings)
        except OSError as exc:
            _log("error", f"Setting not saved: {exc!r}")
        return {"ok": True}

    async def set_poweroff_on_shutdown(self, enabled: bool) -> dict:
        """Shutdown: turn controllers off when the system shuts down (also applies on reboot).

        Switching on sets up the systemd service (files under /etc/systemd/system and /var/lib), switching
        off removes it again. If that fails, the option stays off and the error is shown.
        """
        if not isinstance(enabled, bool):
            return _error("enabled must be a boolean")
        async with self._unit_lock:  # the start reconciliation must not run between install and saving the option
            if enabled:
                result = await asyncio.to_thread(self._install_unit)
                if not result.get("ok"):
                    self.unit_error = result.get("error", "Unknown error")
                    return _error(f"Service not set up: {self.unit_error}", error_codes.UNIT_SETUP_FAILED, self.unit_error)
                self.unit_error = None
            else:
                result = await asyncio.to_thread(poweroff_unit.uninstall)
                if not result.get("ok"):
                    _log("error", f"Service not removed completely: {result}")
            settings = self._load_settings()
            settings["poweroff_on_shutdown"] = enabled
            try:
                self._save_settings(settings)
            except OSError as exc:
                return _error(f"Setting not saved: {exc}", error_codes.SETTINGS_NOT_SAVED, str(exc))
            if not enabled and not result.get("ok"):
                detail = "; ".join(result.get("errors", []))
                return _error(f"Service not removed completely: {detail}", error_codes.UNIT_REMOVAL_FAILED, detail)
            return {"ok": True}

    async def power_off_all(self) -> dict:
        """Turns off all connected controllers (same path as on shutdown; for trying it out)."""
        targets = await asyncio.to_thread(self._all_targets)
        if not targets:
            return {"ok": True, "sent": 0, "confirmed": 0, "errors": []}
        return await asyncio.to_thread(shutdown.power_off_targets, targets)

    # -- Actions with short access to a slot ------------------------------------

    async def _slot_target_error(self, bus, devnum, slot) -> Optional[dict]:
        """Only known receivers and valid slots; the backend runs as root."""
        for value in (bus, devnum, slot):
            if isinstance(value, bool) or not isinstance(value, int):
                return _error("Invalid argument")
        if not 0 <= slot <= 3:
            return _error("Slot must be 1 to 4")
        receivers = await asyncio.to_thread(self.service.refresh)
        if not any(r.bus == bus and r.devnum == devnum for r in receivers):
            return _error("Receiver not found", error_codes.RECEIVER_NOT_FOUND)
        return None

    async def query_battery(self, bus: int, devnum: int, slot: int) -> dict:
        """Battery request to a slot (slot 0..3). Briefly disconnects this slot's controller."""
        error = await self._slot_target_error(bus, devnum, slot)
        if error:
            return error
        return await asyncio.to_thread(self._query_and_cache, bus, devnum, slot)

    async def power_off(self, bus: int, devnum: int, slot: int) -> dict:
        """Turns off the controller of a slot (0..3)."""
        error = await self._slot_target_error(bus, devnum, slot)
        if error:
            return error
        return await asyncio.to_thread(actions.power_off, bus, devnum, slot)

    def _find_controller(self, bus: int, devnum: int, slot: int) -> dict:
        receivers = self.service.refresh()
        receiver = next((r for r in receivers if r.bus == bus and r.devnum == devnum), None)
        if receiver is None:
            return _error("Receiver not found", error_codes.RECEIVER_NOT_FOUND)
        nodes = discovery.input_event_nodes(receiver, slot)
        if not nodes:
            return _error("No input device found for this slot (controller connected?)",
                          error_codes.RUMBLE_UNAVAILABLE)
        try:
            path = rumble.device_path(nodes[0])
        except ValueError as exc:  # cannot happen for names from discovery, but the path is checked anyway
            return _error(str(exc))
        blinked = self._blink_led(receivers, bus, devnum, slot)
        try:
            rumble.play(path)
        except rumble.RumbleError as exc:
            return _error(str(exc), exc.code, exc.detail)
        return {"ok": True, "led": blinked}

    def _blink_led(self, receivers, bus: int, devnum: int, slot: int) -> bool:
        """Blinks the controller's LED once (mode 15, then back to the previous state), if it is known."""
        for receiver_view in self._views(receivers):
            if receiver_view.get("bus") != bus or receiver_view.get("devnum") != devnum:
                continue
            for controller in receiver_view["controllers"]:
                if controller["slot"] == slot and controller.get("led"):
                    try:
                        controls.set_led_mode(controller["led"], 15)
                    except (ValueError, OSError):
                        return False
                    return True
        return False

    async def find_controller(self, bus: int, devnum: int, slot: int) -> dict:
        """Identifies a controller: vibrates it for about a second and blinks its LED once (slot 0..3)."""
        error = await self._slot_target_error(bus, devnum, slot)
        if error:
            return error
        return await asyncio.to_thread(self._find_controller, bus, devnum, slot)
