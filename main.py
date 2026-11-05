"""Decky-Backend des Plugins „X360 Receiver“.

Läuft mit Root-Rechten ("root" in plugin.json; Decky prüft genau diese Zeichenfolge). Schreibt nur auf die Pfade aus
x360w.controls. Der USB-Monitor (usbmon) ist standardmäßig aus und wird nur mit
ausdrücklicher Zustimmung des Nutzers aktiviert; die Einstellung wird gespeichert.

Gespeicherte Einstellungen (x360w.json): monitor_enabled, auto_poweroff (gewünschter Wert, wird beim
Start angewendet), poweroff_on_shutdown, original_auto_poweroff (Ausgangswert für das Entfernen).

„Beim Herunterfahren ausschalten“ übernimmt ein eigener systemd-Dienst (x360w.poweroff_unit), den das
Plugin beim Einschalten der Option anlegt und beim Ausschalten und Entfernen löscht: Decky stoppt das
Plugin beim Herunterfahren nicht zuverlässig (am Gerät beobachtet).
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# py_modules liegt neben dieser Datei. Sicherheitshalber explizit in den Suchpfad.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_modules"))

import decky  # noqa: E402  (nur unter Decky Loader vorhanden)

from x360w import actions, cleanup, controls, discovery, poweroff_unit, shutdown, view  # noqa: E402
from x360w.battery_cache import BatteryCache  # noqa: E402
from x360w.service import MonitorService  # noqa: E402

REFRESH_INTERVAL_S = 5.0
STARTUP_QUERY_DELAY_S = 1.0  # kurze Pause nach dem Start, damit Decky fertig laden kann
QUERY_BUSY_RETRIES = 5
QUERY_BUSY_WAIT_S = 0.5
PACKAGE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "py_modules" / "x360w"


def _log(level: str, message: str) -> None:
    logger = getattr(decky, "logger", None)
    if logger is not None:
        getattr(logger, level)(message)


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
    unit_error = None  # letzter Fehler beim Einrichten des Dienstes (Text) oder None

    # -- Einstellungen ------------------------------------------------------

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
        """Merkt sich beim ersten Ändern den Ausgangswert, damit das Entfernen ihn wiederherstellen kann."""
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
            _log("error", f"Ausgangswert nicht gespeichert: {exc!r}")

    # -- Lebenszyklus -------------------------------------------------------

    def _apply_auto_poweroff(self, enabled: bool) -> None:
        self._remember_auto_poweroff()
        controls.set_auto_poweroff(enabled)

    async def _main(self):
        self.service = MonitorService()
        self.batteries = BatteryCache()
        self.unit_error = None
        settings = self._load_settings()
        if isinstance(settings.get("auto_poweroff"), bool):
            try:
                self._apply_auto_poweroff(settings["auto_poweroff"])  # Kernelparameter ist nach Neustart zurückgesetzt
            except (ValueError, OSError) as exc:
                _log("error", f"auto_poweroff nicht angewendet: {exc!r}")
        if settings.get("monitor_enabled") is True:
            await asyncio.to_thread(self.service.enable)
        self.refresh_task = asyncio.get_event_loop().create_task(self._refresh_loop())
        self.startup_task = asyncio.get_event_loop().create_task(self._startup_battery_query())
        self.unit_task = asyncio.get_event_loop().create_task(self._sync_unit())
        _log("info", "x360w geladen")

    async def _sync_unit(self) -> None:
        """Gleicht den Dienst mit der Einstellung ab: Option an = Dienst vorhanden und aktuell, aus = Dienst weg.

        Die Einstellung ist maßgeblich. Ohne diesen Abgleich bliebe ein Dienst zurück, wenn die Einstellungen
        verloren gehen (z. B. nach dem Neuinstallieren), und ein Plugin-Update brächte das Programm des Dienstes
        nicht auf den neuen Stand.
        """
        try:
            enabled = self._load_settings().get("poweroff_on_shutdown") is True  # aktuell lesen, nicht beim Start merken
            if enabled:
                result = await asyncio.to_thread(self._install_unit)
                self.unit_error = None if result.get("ok") else result.get("error", "Fehler")
                if self.unit_error:
                    _log("error", f"Dienst nicht eingerichtet: {self.unit_error}")
            elif await asyncio.to_thread(poweroff_unit.is_installed):
                result = await asyncio.to_thread(poweroff_unit.uninstall)
                _log("info", f"Dienst entfernt (Option ist aus): {result}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # darf das Plugin nie am Laden hindern
            self.unit_error = f"{type(exc).__name__}: {exc}"[:300]
            _log("error", f"Abgleich des Dienstes fehlgeschlagen: {exc!r}")

    def _install_unit(self) -> dict:
        return poweroff_unit.install(PACKAGE_DIR)

    async def _startup_battery_query(self):
        """Fragt den Akku aller schon verbundenen Controller einmal ab.

        Der Receiver meldet den Akku nur beim Verbinden; wer vor dem Plugin-Start verbunden war,
        hätte sonst keinen Wert. Kosten: Jeder Controller verschwindet dabei nacheinander für ca. 3 s.
        """
        try:
            await asyncio.sleep(STARTUP_QUERY_DELAY_S)
            targets = await asyncio.to_thread(self._connected_targets)
            _log("info", f"Akkuabfrage nach dem Start: {len(targets)} Controller {targets}")
            for bus, devnum, slot in targets:
                result = await asyncio.to_thread(self._query_and_cache, bus, devnum, slot)
                _log("info", f"Akkuabfrage Bus {bus} Gerät {devnum} Slot {slot + 1}: {result}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # darf das Plugin nie am Laden hindern
            _log("error", f"Akkuabfrage nach dem Start fehlgeschlagen: {exc!r}")

    def _query_and_cache(self, bus: int, devnum: int, slot: int) -> dict:
        """Akkuanfrage (wartet kurz, wenn gerade ein anderer Zugriff läuft) und Ergebnis merken."""
        for attempt in range(QUERY_BUSY_RETRIES + 1):
            result = actions.query_battery(bus, devnum, slot)
            if result.get("error") != actions.BUSY_ERROR or attempt == QUERY_BUSY_RETRIES:
                break
            time.sleep(QUERY_BUSY_WAIT_S)
        if result.get("ok") and result.get("state"):
            self.batteries.store((bus, devnum, slot), result["state"])
        return result

    async def _refresh_loop(self):
        while True:
            await asyncio.sleep(REFRESH_INTERVAL_S)
            try:
                await asyncio.to_thread(self.service.refresh)
            except Exception as exc:  # Schleife darf nie sterben
                _log("error", f"refresh fehlgeschlagen: {exc!r}")

    async def _unload(self):
        for task in (self.refresh_task, self.startup_task, self.unit_task):
            if task is not None:
                task.cancel()
        await asyncio.to_thread(self.service.disable)
        _log("info", "x360w entladen")

    async def _uninstall(self):
        """Von Decky nach `_unload` beim Entfernen aufgerufen (auch beim Neuinstallieren per ZIP).

        Stellt auto_poweroff wieder her, entfernt den systemd-Dienst und löscht die eigenen Ordner unter DECKY_HOME. Der
        Plugin-Ordner selbst wird danach von Decky gelöscht. Nicht rückgängig gemacht werden
        das geladene Kernelmodul usbmon (bis zum Neustart) und LED-Modi (bis zum nächsten
        Verbinden des Controllers).
        """
        try:
            original = self._load_settings().get("original_auto_poweroff")
            if cleanup.restore_auto_poweroff(original):
                _log("info", "auto_poweroff auf den ursprünglichen Wert zurückgesetzt")
        except (OSError, ValueError) as exc:
            _log("error", f"auto_poweroff nicht zurückgesetzt: {exc!r}")
        try:
            result = await asyncio.to_thread(poweroff_unit.uninstall)  # auch wenn die Option aus ist: ein Rest soll nicht liegen bleiben
            _log("info", f"Dienst entfernt: {result}")
        except Exception as exc:  # darf das Entfernen der Ordner nicht verhindern
            _log("error", f"Dienst nicht entfernt: {exc!r}")
        home = getattr(decky, "DECKY_HOME", None)
        _log("info", "x360w wird entfernt")
        for attr in ("DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR"):
            try:
                cleanup.remove_plugin_dir(getattr(decky, attr, None), home)
            except OSError as exc:
                _log("error", f"{attr} nicht gelöscht: {exc!r}")

    # -- Abfragen -----------------------------------------------------------

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

    def _build_status(self) -> dict:
        receivers = self.service.refresh()
        settings = self._load_settings()
        return {
            "settings": {
                "monitor_enabled": self.service.status()["enabled"],
                "auto_poweroff": controls.get_auto_poweroff(),
                "poweroff_on_shutdown": settings.get("poweroff_on_shutdown") is True,
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

    # -- Aktionen -----------------------------------------------------------

    async def set_monitor_enabled(self, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "enabled muss ein Wahrheitswert sein"}
        settings = self._load_settings()
        settings["monitor_enabled"] = enabled
        try:
            self._save_settings(settings)
        except OSError as exc:
            _log("error", f"Einstellung nicht gespeichert: {exc!r}")
        if enabled:
            await asyncio.to_thread(self.service.enable)
        else:
            await asyncio.to_thread(self.service.disable)
        return {"ok": True}

    async def set_led(self, name: str, mode: int) -> dict:
        try:
            controls.set_led_mode(name, mode)
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    async def reset_led(self, name: str) -> dict:
        try:
            controls.reset_led(name)
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    async def set_auto_poweroff(self, enabled: bool) -> dict:
        """Standby: Controller ausschalten (Kernelparameter xpad.auto_poweroff). Wird gespeichert und beim Start erneut gesetzt."""
        try:
            self._apply_auto_poweroff(enabled)
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        settings = self._load_settings()
        settings["auto_poweroff"] = enabled
        try:
            self._save_settings(settings)
        except OSError as exc:
            _log("error", f"Einstellung nicht gespeichert: {exc!r}")
        return {"ok": True}

    async def set_poweroff_on_shutdown(self, enabled: bool) -> dict:
        """Herunterfahren: Controller ausschalten, wenn das System herunterfährt (gilt auch beim Neustart).

        Einschalten richtet den systemd-Dienst ein (Dateien unter /etc/systemd/system und /var/lib), Ausschalten
        entfernt ihn wieder. Schlägt das fehl, bleibt die Option aus und der Fehler wird angezeigt.
        """
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "enabled muss ein Wahrheitswert sein"}
        if enabled:
            result = await asyncio.to_thread(self._install_unit)
            if not result.get("ok"):
                self.unit_error = result.get("error", "Fehler")
                return {"ok": False, "error": f"Dienst nicht eingerichtet: {self.unit_error}"}
            self.unit_error = None
        else:
            result = await asyncio.to_thread(poweroff_unit.uninstall)
            if not result.get("ok"):
                _log("error", f"Dienst nicht vollständig entfernt: {result}")
        settings = self._load_settings()
        settings["poweroff_on_shutdown"] = enabled
        try:
            self._save_settings(settings)
        except OSError as exc:
            return {"ok": False, "error": f"Einstellung nicht gespeichert: {exc}"}
        if not enabled and not result.get("ok"):
            return {"ok": False, "error": "Dienst nicht vollständig entfernt: " + "; ".join(result.get("errors", []))}
        return {"ok": True}

    async def power_off_all(self) -> dict:
        """Schaltet alle verbundenen Controller aus (derselbe Weg wie beim Herunterfahren; zum Ausprobieren)."""
        targets = await asyncio.to_thread(self._all_targets)
        if not targets:
            return {"ok": True, "sent": 0, "confirmed": 0, "errors": []}
        return await asyncio.to_thread(shutdown.power_off_targets, targets)

    # -- Aktionen mit kurzem Zugriff auf einen Slot --------------------------------

    async def _slot_target_error(self, bus, devnum, slot):
        """Nur bekannte Receiver und gültige Slots; das Backend läuft als root."""
        for value in (bus, devnum, slot):
            if isinstance(value, bool) or not isinstance(value, int):
                return "Ungültige Angabe"
        if not 0 <= slot <= 3:
            return "Slot muss 1 bis 4 sein"
        receivers = await asyncio.to_thread(self.service.refresh)
        if not any(r.bus == bus and r.devnum == devnum for r in receivers):
            return "Receiver nicht gefunden"
        return None

    async def query_battery(self, bus: int, devnum: int, slot: int) -> dict:
        """Akkuanfrage an einen Slot (Slot 0..3). Trennt den Controller dieses Slots kurz."""
        error = await self._slot_target_error(bus, devnum, slot)
        if error:
            return {"ok": False, "error": error}
        return await asyncio.to_thread(self._query_and_cache, bus, devnum, slot)

    async def power_off(self, bus: int, devnum: int, slot: int) -> dict:
        """Schaltet den Controller eines Slots (0..3) aus."""
        error = await self._slot_target_error(bus, devnum, slot)
        if error:
            return {"ok": False, "error": error}
        return await asyncio.to_thread(actions.power_off, bus, devnum, slot)

