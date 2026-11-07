"""Smoke test for main.py with a stand-in `decky` module (no real Decky Loader)."""

import asyncio
import importlib.util
import json
import logging
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))


class FakeGuard:
    """Stand-in for x360w.loop_guard.LoopGuard: records what main.py does with it."""

    instances = []

    def __init__(self, on_starved, *args, **kwargs):
        self.on_starved, self.started_with, self.stopped = on_starved, None, False
        FakeGuard.instances.append(self)

    def start(self, loop):
        self.started_with = loop

    def stop(self):
        self.stopped = True


class FakeUnit:
    """Stand-in for x360w.poweroff_unit in main.py: never real files under /etc or /var, never a real systemctl."""

    def __init__(self):
        self.calls = []
        self.installed = False
        self.install_result = {"ok": True}
        self.uninstall_result = {"ok": True, "errors": []}
        self.last_run = None

    def install(self, package_dir):
        self.calls.append(("install", Path(package_dir).name))
        if self.install_result.get("ok"):
            self.installed = True
        return self.install_result

    def uninstall(self, *args):
        self.calls.append(("uninstall",))
        self.installed = False
        return self.uninstall_result

    def is_installed(self):
        return self.installed

    def read_last_run(self):
        return self.last_run

    def summarize(self, *args, **kwargs):
        import x360w.poweroff_unit

        return x360w.poweroff_unit.summarize(*args, **kwargs)


def load_main(settings_dir, **attrs):
    import x360w.service

    x360w.service.ensure_usbmon = lambda template: None  # never a real modprobe in tests
    stub = types.ModuleType("decky")
    stub.logger = logging.getLogger("decky-stub")
    stub.DECKY_SETTINGS_DIR = settings_dir
    for key, value in attrs.items():
        setattr(stub, key, value)
    sys.modules["decky"] = stub
    spec = importlib.util.spec_from_file_location("x360w_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LoopGuard = FakeGuard  # the real one could end the test process; see tests/test_loop_guard.py
    # The real watchdog would end the test process 4.3 s after any _unload; tests that look at it patch this stand-in.
    module.faulthandler = types.SimpleNamespace(dump_traceback_later=lambda *a, **k: None)
    module.poweroff_unit = module.fake_unit = FakeUnit()  # replaced in main.py only, the real module stays untouched
    return module


class BackendTests(unittest.TestCase):
    def test_lifecycle_and_actions(self):
        async def scenario(tmp):
            main = load_main(tmp)
            main.REFRESH_INTERVAL_S = 0.05
            plugin = main.Plugin()
            await plugin._main()
            try:
                status = await plugin.get_status()
                self.assertEqual(
                    set(status),
                    {"settings", "monitor", "receivers", "led_modes", "diagnostics"},
                )
                self.assertEqual(set(status["settings"]), {"monitor_enabled", "auto_poweroff", "poweroff_on_shutdown",
                                                            "startup_query", "low_battery_toast", "language"})
                self.assertFalse(status["settings"]["poweroff_on_shutdown"])
                self.assertFalse(status["monitor"]["enabled"])
                self.assertEqual(len(status["led_modes"]), 16)
                json.dumps(status)  # must be serializable

                self.assertFalse((await plugin.set_led("../x", 1))["ok"])
                self.assertFalse((await plugin.set_led("xpad0", 99))["ok"])
                self.assertFalse((await plugin.set_auto_poweroff("yes"))["ok"])
                self.assertFalse((await plugin.set_monitor_enabled("yes"))["ok"])

                self.assertTrue((await plugin.set_monitor_enabled(True))["ok"])
                self.assertTrue((await plugin.get_status())["monitor"]["enabled"])
                saved = json.loads((Path(tmp) / "x360w.json").read_text())
                self.assertIs(saved["monitor_enabled"], True)
                await asyncio.sleep(0.2)  # the refresh loop runs
                self.assertTrue((await plugin.set_monitor_enabled(False))["ok"])
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_slot_actions_validate_target_before_touching_usb(self):
        async def scenario(tmp):
            main = load_main(tmp)
            calls = []
            patches = [
                mock.patch.object(main.actions, "query_battery",
                                  lambda *a: calls.append(("q",) + a) or {"ok": True, "state": None}),
                mock.patch.object(main.actions, "power_off",
                                  lambda *a: calls.append(("p",) + a) or {"ok": True, "confirmed": True}),
            ]
            for patch in patches:
                patch.start()
                self.addCleanup(patch.stop)
            plugin = main.Plugin()
            await plugin._main()
            try:
                # there is no receiver in this environment: nothing may go to USB
                self.assertEqual(
                    await plugin.query_battery(1, 2, 0),
                    {"ok": False, "error": "Receiver not found", "code": "receiver_not_found"},
                )
                self.assertEqual((await plugin.power_off(1, 2, 7))["error"], "Slot must be 1 to 4")
                self.assertEqual((await plugin.power_off("1", 2, 0))["error"], "Invalid argument")
                self.assertEqual((await plugin.power_off(True, 2, 0))["error"], "Invalid argument")
                self.assertEqual(calls, [])

                from x360w.discovery import ReceiverInfo
                info = ReceiverInfo("1-3", 0x045E, 0x0719, "R", 1, 2, None, None, None, None)
                plugin.service._find = lambda: [info]
                self.assertTrue((await plugin.query_battery(1, 2, 1))["ok"])
                self.assertTrue((await plugin.power_off(1, 2, 3))["confirmed"])
                self.assertEqual(calls, [("q", 1, 2, 1), ("p", 1, 2, 3)])
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_missing_led_reports_a_translatable_code(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            try:
                with mock.patch.object(main.controls, "LED_BASE", Path(tmp) / "no-leds"):
                    for result in (await plugin.set_led("xpad0", 1), await plugin.reset_led("xpad0")):
                        self.assertFalse(result["ok"])
                        self.assertEqual(result["code"], "led_missing")
                        self.assertIn("xpad0", result["error"])  # the English technical text stays as the fallback
                    self.assertNotIn("code", await plugin.set_led("xpad0", 99))  # a programming error has no code
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_backend_sends_language_neutral_texts(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            try:
                status = await plugin.get_status()
                self.assertTrue(all(text.isascii() for text in status["led_modes"].values()))
                self.assertEqual(status["led_modes"]["0"], "off")
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_enabled_setting_is_restored(self):
        async def scenario(tmp):
            (Path(tmp) / "x360w.json").write_text('{"monitor_enabled": true}')
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            try:
                self.assertTrue(plugin.service.status()["enabled"])
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))


class OptionsAndViewTests(unittest.TestCase):
    def test_status_lists_controllers_per_receiver(self):
        async def scenario(tmp):
            main = load_main(tmp)
            from x360w.discovery import ReceiverInfo
            info = ReceiverInfo("1-3", 0x045E, 0x0719, "R", 1, 2, None, None, None, None)
            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0, 2}):
                plugin = main.Plugin()
                await plugin._main()
                try:
                    plugin.service._find = lambda: [info]
                    status = await plugin.get_status()
                finally:
                    await plugin._unload()
            [receiver] = status["receivers"]
            self.assertEqual([c["slot"] for c in receiver["controllers"]], [0, 2])
            self.assertIs(receiver["unofficial"], False)
            json.dumps(status)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_standby_option_is_saved_and_reapplied_after_restart(self):
        async def scenario(tmp):
            param = Path(tmp) / "auto_poweroff"
            param.write_text("Y\n")
            main = load_main(tmp)
            with mock.patch.object(main.controls, "AUTO_POWEROFF_PARAM", param):
                plugin = main.Plugin()
                await plugin._main()
                self.assertTrue((await plugin.set_auto_poweroff(False))["ok"])
                self.assertEqual(param.read_text().strip(), "N")
                await plugin._unload()

                param.write_text("Y\n")  # reboot: the kernel parameter is back at its default
                plugin = main.Plugin()
                await plugin._main()
                try:
                    self.assertEqual(param.read_text().strip(), "N")  # saved choice applied again
                    self.assertIs((await plugin.get_status())["settings"]["auto_poweroff"], False)
                finally:
                    await plugin._unload()
            saved = json.loads((Path(tmp) / "x360w.json").read_text())
            self.assertIs(saved["auto_poweroff"], False)
            self.assertIs(saved["original_auto_poweroff"], True)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_shutdown_option_validation_and_persistence(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            try:
                self.assertFalse((await plugin.set_poweroff_on_shutdown("yes"))["ok"])
                self.assertFalse((await plugin.set_poweroff_on_shutdown(1))["ok"])
                self.assertTrue((await plugin.set_poweroff_on_shutdown(True))["ok"])
                self.assertTrue((await plugin.get_status())["settings"]["poweroff_on_shutdown"])
            finally:
                await plugin._unload()
            self.assertIs(json.loads((Path(tmp) / "x360w.json").read_text())["poweroff_on_shutdown"], True)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_power_off_all_uses_confirmed_path_and_skips_when_nothing_connected(self):
        async def scenario(tmp):
            main = load_main(tmp)
            seen = []
            with mock.patch.object(main.actions, "power_off",
                                   lambda b, d, s: seen.append((b, d, s)) or {"ok": True, "confirmed": True}):
                plugin = main.Plugin()
                await plugin._main()
                try:
                    plugin._all_targets = lambda: []
                    self.assertEqual(await plugin.power_off_all(), {"ok": True, "sent": 0, "confirmed": 0, "errors": []})
                    self.assertEqual(seen, [])
                    plugin._all_targets = lambda: [(1, 2, 0), (1, 2, 1)]
                    result = await plugin.power_off_all()
                finally:
                    await plugin._unload()
            self.assertEqual(seen, [(1, 2, 0), (1, 2, 1)])
            self.assertEqual((result["sent"], result["confirmed"]), (2, 2))

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))


class StartupBatteryTests(unittest.TestCase):
    STATE = {"battery_level": 2, "battery_type_raw": 1, "power_state_raw": 2, "vibration_level": 0}

    def _run(self, slots, query, monitor_enabled=False, delay=0.0, after=None):
        """Starts the plugin with stand-ins; returns (calls, status after the start)."""
        calls = []
        result = {}

        async def scenario(tmp):
            if monitor_enabled:
                (Path(tmp) / "x360w.json").write_text('{"monitor_enabled": true}')
            main = load_main(tmp)
            main.STARTUP_QUERY_DELAY_S = delay
            main.QUERY_BUSY_WAIT_S = 0.0
            from x360w.discovery import ReceiverInfo
            info = ReceiverInfo("1-3", 0x045E, 0x0719, "R", 1, 2, None, None, None, None)

            def fake_query(bus, devnum, slot):
                calls.append((bus, devnum, slot))
                return query(len(calls))

            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: set(slots)), \
                    mock.patch.object(main.actions, "query_battery", fake_query), \
                    mock.patch.object(main.discovery, "find_receivers", lambda: [info]):
                plugin = main.Plugin()
                # the service finds our stand-in receiver
                orig_init = main.MonitorService.__init__
                main.MonitorService.__init__ = lambda self, *a, **k: (orig_init(self, find=lambda: [info], *a, **k))
                try:
                    await plugin._main()
                finally:
                    main.MonitorService.__init__ = orig_init
                try:
                    if after is None:
                        await plugin.startup_task
                    else:
                        await after(plugin)
                    result["status"] = await plugin.get_status()
                finally:
                    await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))
        return calls, result["status"]

    def test_connected_controllers_are_queried_once_after_start(self):
        calls, status = self._run({0, 2}, lambda n: {"ok": True, "state": dict(self.STATE, battery_level=n)})
        self.assertEqual(calls, [(1, 2, 0), (1, 2, 2)])  # one after the other, each exactly once
        levels = {c["slot"]: (c["battery_level"], c["state_source"]) for c in status["receivers"][0]["controllers"]}
        self.assertEqual(levels, {0: (1, "query"), 2: (2, "query")})  # visible without the monitor too

    def test_no_controller_no_query(self):
        calls, status = self._run(set(), lambda n: {"ok": True, "state": self.STATE})
        self.assertEqual(calls, [])
        self.assertEqual(status["receivers"][0]["controllers"], [])

    def test_no_answer_leaves_value_unknown_and_continues(self):
        calls, status = self._run({0, 1}, lambda n: {"ok": True, "state": None} if n == 1 else {"ok": True, "state": self.STATE})
        self.assertEqual(calls, [(1, 2, 0), (1, 2, 1)])
        levels = {c["slot"]: c["battery_level"] for c in status["receivers"][0]["controllers"]}
        self.assertEqual(levels, {0: None, 1: 2})

    def test_error_in_one_query_does_not_stop_the_others(self):
        calls, status = self._run({0, 1}, lambda n: {"ok": False, "error": "libusb could not be loaded"} if n == 1 else {"ok": True, "state": self.STATE})
        self.assertEqual(len(calls), 2)

    def test_exception_does_not_break_plugin(self):
        def boom(n):
            raise RuntimeError("broken")

        calls, status = self._run({0}, boom)
        self.assertEqual(calls, [(1, 2, 0)])
        self.assertIn("receivers", status)  # plugin keeps running

    def test_busy_receiver_is_retried(self):
        from x360w import actions
        answers = {1: {"ok": False, "error": actions.BUSY_ERROR}, 2: {"ok": False, "error": actions.BUSY_ERROR}}
        calls, status = self._run({0}, lambda n: answers.get(n, {"ok": True, "state": self.STATE}))
        self.assertEqual(len(calls), 3)
        self.assertEqual(status["receivers"][0]["controllers"][0]["battery_level"], 2)

    def test_unload_cancels_pending_startup_query(self):
        async def cancel_before_it_runs(plugin):
            self.assertFalse(plugin.startup_task.done())  # still waiting in the pause after the start
            await plugin._unload()  # unload before the pause is over
            await asyncio.sleep(0)
            self.assertTrue(plugin.startup_task.cancelled())

        calls, _ = self._run({0}, lambda n: {"ok": True, "state": self.STATE}, delay=30.0, after=cancel_before_it_runs)
        self.assertEqual(calls, [])

    def test_manual_query_is_remembered_too(self):
        async def scenario(tmp):
            main = load_main(tmp)
            main.STARTUP_QUERY_DELAY_S = 0.0
            from x360w.discovery import ReceiverInfo
            info = ReceiverInfo("1-3", 0x045E, 0x0719, "R", 1, 2, None, None, None, None)
            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {1}), \
                    mock.patch.object(main.actions, "query_battery", lambda *a: {"ok": True, "state": self.STATE}):
                plugin = main.Plugin()
                await plugin._main()
                try:
                    await plugin.startup_task
                    plugin.service._find = lambda: [info]
                    self.assertTrue((await plugin.query_battery(1, 2, 1))["ok"])
                    status = await plugin.get_status()
                finally:
                    await plugin._unload()
            [controller] = status["receivers"][0]["controllers"]
            self.assertEqual((controller["slot"], controller["battery_level"], controller["state_source"]), (1, 2, "query"))

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))


class NewOptionTests(unittest.TestCase):
    """Startup query switch, language, low-battery notices, find controller, resume handling."""

    STATE_LOW = {"battery_level": 1, "battery_type_raw": 1, "power_state_raw": 2}

    def run_plugin(self, scenario, settings=None, **attrs):
        async def wrapper(tmp):
            if settings is not None:
                (Path(tmp) / "x360w.json").write_text(json.dumps(settings))
            main = load_main(tmp, **attrs)
            plugin = main.Plugin()
            await plugin._main()
            try:
                return await scenario(main, plugin, tmp)
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            return asyncio.run(wrapper(tmp))

    def receiver(self):
        from x360w.discovery import ReceiverInfo
        return ReceiverInfo("1-3", 0x045E, 0x0719, "R", 1, 2, None, None, None, None)

    def test_startup_query_switch_is_saved_shown_and_respected(self):
        async def scenario(main, plugin, tmp):
            status = (await plugin.get_status())["settings"]
            self.assertEqual((status["startup_query"], status["low_battery_toast"], status["language"]), (True, True, "auto"))
            self.assertFalse((await plugin.set_startup_query("yes"))["ok"])
            self.assertTrue((await plugin.set_startup_query(False))["ok"])
            self.assertIs((await plugin.get_status())["settings"]["startup_query"], False)
            self.assertIs(json.loads((Path(tmp) / "x360w.json").read_text())["startup_battery_query"], False)

        self.run_plugin(scenario)

    def test_no_battery_query_after_start_when_switched_off(self):
        calls = []

        async def wrapper(tmp):
            (Path(tmp) / "x360w.json").write_text('{"startup_battery_query": false}')
            main = load_main(tmp)
            main.STARTUP_QUERY_DELAY_S = 0.0
            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0, 1}), \
                    mock.patch.object(main.discovery, "find_receivers", lambda: [self.receiver()]), \
                    mock.patch.object(main.actions, "query_battery", lambda *a: calls.append(a) or {"ok": True, "state": None}):
                plugin = main.Plugin()
                await plugin._main()
                try:
                    await plugin.startup_task
                finally:
                    await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(wrapper(tmp))
        self.assertEqual(calls, [])

    def test_language_setting_is_validated_saved_and_shown(self):
        async def scenario(main, plugin, tmp):
            for good in ("de", "en", "auto", "pt-BR", "zh-Hans"):
                self.assertTrue((await plugin.set_language(good))["ok"], good)
                self.assertEqual((await plugin.get_status())["settings"]["language"], good)
            for bad in ("../x", "", "DE", "deutsch", 5, None, "de\n", "a" * 40):
                result = await plugin.set_language(bad)
                self.assertFalse(result["ok"], repr(bad))
            self.assertEqual((await plugin.get_status())["settings"]["language"], "zh-Hans")  # bad values changed nothing

        self.run_plugin(scenario)

    def test_a_corrupt_language_in_the_settings_falls_back_to_auto(self):
        async def scenario(main, plugin, tmp):
            self.assertEqual((await plugin.get_status())["settings"]["language"], "auto")

        self.run_plugin(scenario, {"language": "../../etc"})

    def test_low_battery_notice_flow(self):
        async def scenario(main, plugin, tmp):
            plugin.service._find = lambda: [self.receiver()]
            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0}):
                plugin.batteries.store((1, 2, 0), self.STATE_LOW)
                plugin._collect_low_battery()
                self.assertEqual(await plugin.take_low_battery_notices(),
                                 [{"slot": 0, "level": 1, "language": "auto"}])
                self.assertEqual(await plugin.take_low_battery_notices(), [])  # handed out once
                plugin._collect_low_battery()
                self.assertEqual(await plugin.take_low_battery_notices(), [])  # and not repeated while low
                plugin.batteries.store((1, 2, 0), dict(self.STATE_LOW, battery_level=3))
                plugin._collect_low_battery()
                plugin.batteries.store((1, 2, 0), dict(self.STATE_LOW, battery_level=0))
                plugin._collect_low_battery()
                await plugin.set_language("de")
                self.assertEqual(await plugin.take_low_battery_notices(),
                                 [{"slot": 0, "level": 0, "language": "de"}])  # after new batteries, in the UI language
                self.assertTrue((await plugin.set_low_battery_toast(False))["ok"])
                plugin.batteries.store((1, 2, 0), self.STATE_LOW)
                plugin._collect_low_battery()
                self.assertEqual(await plugin.take_low_battery_notices(), [])  # switched off: nothing

        self.run_plugin(scenario, {"startup_battery_query": False})

    def test_pending_notices_are_bounded_and_keep_the_newest(self):
        async def scenario(main, plugin, tmp):
            plugin.service._find = lambda: []
            plugin.low_battery.update = lambda views: [
                {"bus": 1, "devnum": 2, "slot": i % 4, "level": i % 2} for i in range(40)
            ]
            plugin._collect_low_battery()
            notices = await plugin.take_low_battery_notices()
            self.assertEqual(len(notices), main.MAX_NOTICES)
            self.assertEqual((notices[-1]["slot"], notices[-1]["level"]), (39 % 4, 39 % 2))  # the newest survived
            self.assertTrue(all(set(notice) == {"slot", "level", "language"} for notice in notices))

        self.run_plugin(scenario, {"startup_battery_query": False})

    def test_led_mode_is_known_without_the_monitor(self):
        async def scenario(main, plugin, tmp):
            plugin.service._find = lambda: [self.receiver()]
            leds = Path(tmp) / "leds"
            (leds / "xpad0").mkdir(parents=True)
            (leds / "xpad0" / "brightness").write_text("0")
            owners = {"1-3": ["xpad0"]}

            def show():
                [receiver] = plugin._build_status()["receivers"]
                [controller] = receiver["controllers"]
                return controller["last_led_mode"], controller["led_mode_source"]

            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0}), \
                    mock.patch.object(main.controls, "led_owners", lambda: owners), \
                    mock.patch.object(main.controls, "LED_BASE", leds):
                self.assertEqual(show(), (2, "default"))  # what xpad sets itself on connecting: (0 mod 4) + 2
                self.assertTrue((await plugin.set_led("xpad0", 10))["ok"])
                self.assertEqual(show(), (10, "set"))
                self.assertTrue((await plugin.reset_led("xpad0"))["ok"])
                self.assertEqual(show(), (2, "set"))
                self.assertTrue((await plugin.set_led("xpad0", 7))["ok"])
                owners.clear()  # the controller left: the LED is gone
                plugin._build_status()
                owners["1-3"] = ["xpad0"]  # and came back: xpad has reset the LED
                self.assertEqual(show(), (2, "default"))
                self.assertFalse((await plugin.set_led("xpad0", 99))["ok"])
                self.assertEqual(show(), (2, "default"))  # a refused command is not remembered

        self.run_plugin(scenario, {"startup_battery_query": False})

    def test_find_controller_only_rumbles_and_never_touches_the_led(self):
        async def scenario(main, plugin, tmp):
            plugin.service._find = lambda: [self.receiver()]
            played, led = [], []
            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0}), \
                    mock.patch.object(main.discovery, "input_event_nodes", lambda r, slot: ["event5"] if slot == 0 else []), \
                    mock.patch.object(main.controls, "led_owners", lambda: {"1-3": ["xpad0"]}), \
                    mock.patch.object(main.controls, "set_led_mode", lambda name, mode: led.append((name, mode))), \
                    mock.patch.object(main.rumble, "play", lambda path, *a, **k: played.append(path)):
                self.assertEqual(await plugin.find_controller(1, 2, 0), {"ok": True})
                self.assertEqual((played, led), (["/dev/input/event5"], []))  # no LED command at all
                # a slot without an input device: translated error, nothing played
                result = await plugin.find_controller(1, 2, 2)
                self.assertEqual((result["ok"], result["code"]), (False, "rumble_unavailable"))
                self.assertEqual(len(played), 1)
                # unknown receiver and bad arguments never reach the input device
                self.assertEqual((await plugin.find_controller(9, 9, 0))["code"], "receiver_not_found")
                self.assertEqual((await plugin.find_controller(1, 2, 7))["error"], "Slot must be 1 to 4")
                self.assertFalse((await plugin.find_controller("1", 2, 0))["ok"])
                self.assertEqual(len(played), 1)

        self.run_plugin(scenario, {"startup_battery_query": False})

    def test_find_controller_passes_rumble_errors_on(self):
        async def scenario(main, plugin, tmp):
            plugin.service._find = lambda: [self.receiver()]
            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0}), \
                    mock.patch.object(main.discovery, "input_event_nodes", lambda r, slot: ["event5"]), \
                    mock.patch.object(main.controls, "led_owners", lambda: {}), \
                    mock.patch.object(main.rumble, "play", lambda path, *a, **k: None):
                self.assertEqual(await plugin.find_controller(1, 2, 0), {"ok": True})

            def failing(path, *a, **k):
                raise main.rumble.RumbleError("Cannot open x", "rumble_unavailable", "denied")

            with mock.patch.object(main.discovery, "connected_slots_sysfs", lambda r: {0}), \
                    mock.patch.object(main.discovery, "input_event_nodes", lambda r, slot: ["event5"]), \
                    mock.patch.object(main.controls, "led_owners", lambda: {}), \
                    mock.patch.object(main.rumble, "play", failing):
                self.assertEqual(await plugin.find_controller(1, 2, 0),
                                 {"ok": False, "error": "Cannot open x", "code": "rumble_unavailable", "detail": "denied"})

        self.run_plugin(scenario, {"startup_battery_query": False})

    def test_refresh_loop_restarts_the_readers_once_after_a_resume(self):
        async def scenario(main, plugin, tmp):
            restarts = []
            plugin.service.restart_readers = lambda: restarts.append(1)
            await asyncio.sleep(0.3)
            return restarts

        async def wrapper(tmp):
            main = load_main(tmp)
            main.REFRESH_INTERVAL_S = 0.02

            class Detector:
                calls = 0

                def check(self):
                    Detector.calls += 1
                    return Detector.calls == 3  # the third tick is the first one after waking up

            main.ResumeDetector = Detector
            plugin = main.Plugin()
            await plugin._main()
            try:
                return await scenario(main, plugin, tmp)
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(asyncio.run(wrapper(tmp)), [1])


class PoweroffServiceTests(unittest.TestCase):
    """“Turn off on shutdown” sets up the systemd service and removes it again."""

    def _run(self, scenario, settings=None, prepare=None):
        async def wrapper(tmp):
            if settings is not None:
                (Path(tmp) / "x360w.json").write_text(json.dumps(settings))
            main = load_main(tmp)
            if prepare is not None:
                prepare(main.fake_unit)
            plugin = main.Plugin()
            await plugin._main()
            try:
                return await scenario(main, plugin, tmp)
            finally:
                await plugin._unload()

        with tempfile.TemporaryDirectory() as tmp:
            return asyncio.run(wrapper(tmp))

    def test_enabling_installs_the_service_from_the_plugin_package(self):
        async def scenario(main, plugin, tmp):
            self.assertEqual((await plugin.set_poweroff_on_shutdown(True)), {"ok": True})
            self.assertEqual(main.fake_unit.calls, [("install", "x360w")])  # source: py_modules/x360w
            self.assertTrue((await plugin.get_status())["settings"]["poweroff_on_shutdown"])
            return json.loads((Path(tmp) / "x360w.json").read_text())["poweroff_on_shutdown"]

        self.assertIs(self._run(scenario), True)

    def test_failed_install_keeps_the_option_off_and_reports_the_error(self):
        async def scenario(main, plugin, tmp):
            main.fake_unit.install_result = {"ok": False, "error": "systemctl broken"}
            result = await plugin.set_poweroff_on_shutdown(True)
            self.assertFalse(result["ok"])
            self.assertIn("systemctl broken", result["error"])
            # a translatable code, with the technical reason as detail
            self.assertEqual((result["code"], result["detail"]), ("unit_setup_failed", "systemctl broken"))
            self.assertFalse((await plugin.get_status())["settings"]["poweroff_on_shutdown"])
            self.assertFalse((Path(tmp) / "x360w.json").exists() and
                             json.loads((Path(tmp) / "x360w.json").read_text()).get("poweroff_on_shutdown"))

        self._run(scenario)

    def test_disabling_removes_the_service_and_saves_off(self):
        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            await plugin.set_poweroff_on_shutdown(True)
            main.fake_unit.calls.clear()
            self.assertEqual(await plugin.set_poweroff_on_shutdown(False), {"ok": True})
            self.assertEqual(main.fake_unit.calls, [("uninstall",)])
            return json.loads((Path(tmp) / "x360w.json").read_text())["poweroff_on_shutdown"]

        self.assertIs(self._run(scenario), False)

    def test_incomplete_removal_is_reported_but_option_is_off(self):
        async def scenario(main, plugin, tmp):
            await plugin.set_poweroff_on_shutdown(True)
            main.fake_unit.uninstall_result = {"ok": False, "errors": ["systemctl disable broken"]}
            result = await plugin.set_poweroff_on_shutdown(False)
            self.assertFalse(result["ok"])
            self.assertIn("systemctl disable broken", result["error"])
            self.assertEqual((result["code"], result["detail"]), ("unit_removal_failed", "systemctl disable broken"))
            self.assertFalse((await plugin.get_status())["settings"]["poweroff_on_shutdown"])

        self._run(scenario)

    def test_invalid_values_touch_nothing(self):
        async def scenario(main, plugin, tmp):
            for bad in ("yes", 1, None):
                self.assertFalse((await plugin.set_poweroff_on_shutdown(bad))["ok"])
            self.assertEqual(main.fake_unit.calls, [])

        self._run(scenario)

    def test_start_with_option_on_installs_or_updates_the_service(self):
        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            return main.fake_unit.calls

        self.assertEqual(self._run(scenario, {"poweroff_on_shutdown": True}), [("install", "x360w")])

    def test_start_with_option_off_removes_a_leftover_service(self):
        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            return main.fake_unit.calls

        self.assertEqual(self._run(scenario, {"poweroff_on_shutdown": False}, lambda u: setattr(u, "installed", True)),
                         [("uninstall",)])
        self.assertEqual(self._run(scenario, {}, lambda u: setattr(u, "installed", True)), [("uninstall",)])  # default: off

    def test_start_with_option_off_and_no_service_does_nothing(self):
        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            return main.fake_unit.calls

        self.assertEqual(self._run(scenario, {"poweroff_on_shutdown": False}), [])

    def test_failed_install_at_start_is_shown_in_diagnostics(self):
        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            return (await plugin.get_status())["diagnostics"]

        diagnostics = self._run(scenario, {"poweroff_on_shutdown": True},
                                lambda u: setattr(u, "install_result", {"ok": False, "error": "no systemd"}))
        self.assertEqual(diagnostics["verdict"], {"code": "install_failed", "error": "no systemd"})

    def test_toggle_right_after_start_is_not_undone_by_the_start_sync(self):
        async def scenario(main, plugin, tmp):
            await plugin.set_poweroff_on_shutdown(True)  # before the reconciliation at start has run
            await plugin.unit_task
            self.assertTrue(main.fake_unit.installed)
            self.assertNotIn(("uninstall",), main.fake_unit.calls)

        self._run(scenario)

    def test_exception_during_sync_does_not_break_the_plugin(self):
        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            self.assertIn("RuntimeError", plugin.unit_error)

        def boom(unit):
            def install(package_dir):
                raise RuntimeError("broken")
            unit.install = install

        self._run(scenario, {"poweroff_on_shutdown": True}, boom)

    def test_status_shows_the_last_run_of_the_service(self):
        run = {"at": 1000.0, "receivers": 1, "targets": [[1, 2, 0], [1, 2, 1]], "duration_s": 2.1,
               "result": {"ok": True, "sent": 2, "confirmed": 2, "errors": []}, "error": None}

        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            return (await plugin.get_status())["diagnostics"]

        diagnostics = self._run(scenario, {"poweroff_on_shutdown": True},
                                lambda u: (setattr(u, "last_run", run), setattr(u, "installed", True)))
        self.assertEqual(diagnostics["verdict"], {"code": "run_ok", "sent": 2, "total": 2})

    def test_no_diagnostics_when_off_and_never_run(self):
        async def scenario(main, plugin, tmp):
            return (await plugin.get_status())["diagnostics"]

        self.assertIsNone(self._run(scenario))

    def test_unload_leaves_the_service_alone_and_never_powers_off(self):
        # The plugin turns nothing off when it is unloaded: the service does that, even if Decky does not
        # stop the plugin properly on shutdown at all.
        sent = []

        async def scenario(main, plugin, tmp):
            await plugin.unit_task
            main.fake_unit.calls.clear()
            with mock.patch.object(main.shutdown, "power_off_targets", lambda *a, **k: sent.append(a)):
                await plugin._unload()
            return main.fake_unit.calls

        self.assertEqual(self._run(scenario, {"poweroff_on_shutdown": True}), [])
        self.assertEqual(sent, [])

    def test_unload_cancels_a_pending_sync(self):
        async def scenario(main, plugin, tmp):
            await plugin._unload()
            await asyncio.sleep(0)
            self.assertTrue(plugin.unit_task.done())

        self._run(scenario, {"poweroff_on_shutdown": True})


class UninstallTests(unittest.TestCase):
    def _setup(self, tmp):
        home = Path(tmp).resolve() / "homebrew"
        dirs = {kind: home / kind / "X360 Receiver" for kind in ("settings", "data", "logs")}
        for d in dirs.values():
            d.mkdir(parents=True)
            (d / "file").write_text("x")
        param = Path(tmp) / "auto_poweroff"
        return home, dirs, param

    def _load(self, home, dirs):
        return load_main(
            str(dirs["settings"]),
            DECKY_HOME=str(home),
            DECKY_PLUGIN_SETTINGS_DIR=str(dirs["settings"]),
            DECKY_PLUGIN_RUNTIME_DIR=str(dirs["data"]),
            DECKY_PLUGIN_LOG_DIR=str(dirs["logs"]),
        )

    def test_uninstall_restores_auto_poweroff_removes_the_service_and_leaves_the_folders(self):
        async def scenario(tmp):
            home, dirs, param = self._setup(tmp)
            param.write_text("Y\n")
            main = self._load(home, dirs)
            main.controls.AUTO_POWEROFF_PARAM = param
            plugin = main.Plugin()
            await plugin._main()
            self.assertTrue((await plugin.set_auto_poweroff(False))["ok"])
            self.assertTrue((await plugin.set_auto_poweroff(True))["ok"])
            self.assertTrue((await plugin.set_auto_poweroff(False))["ok"])
            self.assertEqual(param.read_text().strip(), "N")
            saved = json.loads((dirs["settings"] / "x360w.json").read_text())
            self.assertIs(saved["original_auto_poweroff"], True)  # value before the first change

            await plugin._unload()
            await plugin._uninstall()
            self.assertEqual(param.read_text().strip(), "Y")
            self.assertEqual(main.fake_unit.calls, [("uninstall",)])
            for d in dirs.values():  # the plugin never deletes these (decision of the user)
                self.assertTrue((d / "file").exists(), d)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_uninstall_without_changes_touches_nothing(self):
        async def scenario(tmp):
            home, dirs, param = self._setup(tmp)
            param.write_text("N\n")
            main = self._load(home, dirs)
            main.controls.AUTO_POWEROFF_PARAM = param
            plugin = main.Plugin()
            await plugin._main()
            await plugin._unload()
            await plugin._uninstall()
            self.assertEqual(param.read_text(), "N\n")  # never changed, so not touched

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_uninstall_removes_the_service_even_if_the_option_is_off_and_survives_its_failure(self):
        async def scenario(tmp):
            home, dirs, param = self._setup(tmp)
            main = self._load(home, dirs)

            def boom(*args):
                raise RuntimeError("broken")

            plugin = main.Plugin()
            await plugin._main()
            await plugin._unload()
            await plugin._uninstall()
            self.assertEqual(main.fake_unit.calls, [("uninstall",)])
            main.fake_unit.uninstall = boom
            with self.assertLogs("decky-stub", level="ERROR") as logs:
                await plugin._uninstall()  # must not raise
            self.assertIn("remove service: failed", "\n".join(logs.output))

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_the_shutdown_path_starts_no_thread_and_uses_no_executor(self):
        # On the device the shutdown stopped logging at the first thread start / executor call, every time (journal
        # of 2026-11-07). Whatever the cause, `_unload` and `_uninstall` must not depend on either.
        async def scenario(tmp):
            home, dirs, param = self._setup(tmp)
            main = self._load(home, dirs)
            plugin = main.Plugin()
            await plugin._main()

            async def broken_to_thread(*args, **kwargs):
                raise AssertionError("asyncio.to_thread must not be used while shutting down")

            def broken_start(self_, *args, **kwargs):
                raise AssertionError("no thread may be started while shutting down")

            with mock.patch.object(main.asyncio, "to_thread", broken_to_thread), \
                    mock.patch.object(main.threading.Thread, "start", broken_start), \
                    self.assertLogs("decky-stub", level="INFO") as logs:
                await plugin._unload()
                await plugin._uninstall()
            text = "\n".join(logs.output)
            for step in ("x360w unloading", "stop monitor: done", "x360w unloaded", "x360w is being removed",
                         "remove service: done"):
                self.assertIn(step, text)
            self.assertEqual(main.fake_unit.calls, [("uninstall",)])

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_a_failing_monitor_stop_is_logged_and_unload_still_finishes(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()

            def broken():
                raise RuntimeError("broken")

            plugin.service.disable = broken
            with self.assertLogs("decky-stub", level="INFO") as logs:
                await plugin._unload()
            text = "\n".join(logs.output)
            self.assertIn("stop monitor: failed", text)
            self.assertIn("x360w unloaded", text)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_unload_arms_the_exit_watchdog_before_the_first_step_that_can_hang(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            armed = []
            order = []
            real_step = plugin._step

            def spy(name, function):
                order.append((name, bool(armed)))  # was the watchdog armed before the first step?
                return real_step(name, function)

            plugin._step = spy
            with mock.patch.object(main.faulthandler, "dump_traceback_later",
                                   lambda timeout, **kw: armed.append((timeout, kw.get("exit")))):
                await plugin._unload()
            self.assertEqual(len(armed), 1)
            timeout, exit_flag = armed[0]
            self.assertTrue(exit_flag, "the watchdog must end the process, not only print")
            self.assertLess(timeout, 5.0, "it has to fire before Decky's SIGKILL after 5 s")
            self.assertGreater(timeout, 1.0, "and leave the normal steps time to finish")
            self.assertEqual(order, [("stop monitor", True)])

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_unload_and_uninstall_never_suspend(self):
        # Decky's socket reader can spin and starve the loop (x360w.loop_guard). A coroutine that really suspends
        # is then never resumed. So `_unload` and `_uninstall` must finish in their first step.
        async def scenario(tmp):
            home, dirs, param = self._setup(tmp)
            main = self._load(home, dirs)
            plugin = main.Plugin()
            await plugin._main()
            for coroutine in (plugin._unload(), plugin._uninstall()):
                with self.assertRaises(StopIteration):  # finished without ever yielding to the loop
                    coroutine.send(None)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_main_starts_a_loop_guard_and_unload_disarms_it_first(self):
        async def scenario(tmp):
            main = load_main(tmp)
            FakeGuard.instances.clear()
            plugin = main.Plugin()
            await plugin._main()
            [guard] = FakeGuard.instances
            self.assertIs(guard.started_with, asyncio.get_running_loop())
            self.assertFalse(guard.stopped)
            order = []
            plugin._arm_exit_watchdog = lambda: order.append(("watchdog", guard.stopped))
            await plugin._unload()
            self.assertTrue(guard.stopped)
            self.assertEqual(order, [("watchdog", True)])  # disarmed before the exit watchdog takes over

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_a_starved_loop_ends_the_process_and_says_so(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            exits = []
            with mock.patch.object(main.os, "_exit", exits.append), \
                    self.assertLogs("decky-stub", level="WARNING") as logs:
                FakeGuard.instances[-1].on_starved()
            self.assertEqual(exits, [0])
            self.assertIn("event loop is starved", "\n".join(logs.output))

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))

    def test_the_watchdog_falls_back_to_the_next_stream_and_never_raises(self):
        async def scenario(tmp):
            main = load_main(tmp)
            plugin = main.Plugin()
            await plugin._main()
            calls = []

            def flaky(timeout, **kw):
                calls.append(kw["file"])
                if len(calls) == 1:
                    raise ValueError("bad file descriptor")

            with mock.patch.object(main.faulthandler, "dump_traceback_later", flaky):
                plugin._arm_exit_watchdog()
            self.assertEqual(len(calls), 2)  # the second stream worked
            with mock.patch.object(main.faulthandler, "dump_traceback_later", side_effect=OSError("nope")):
                plugin._arm_exit_watchdog()  # all streams fail: only a warning

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(tmp))


if __name__ == "__main__":
    unittest.main()
