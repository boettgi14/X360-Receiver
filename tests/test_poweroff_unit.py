"""Tests for x360w.poweroff_unit: creating/removing the service (only in temp folders, never under /etc or /var)."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "py_modules" / "x360w"
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import poweroff_unit, shutdown  # noqa: E402


class FakeSystemctl:
    def __init__(self, fail_on=None, on_call=None):
        self.calls = []
        self.fail_on = fail_on
        self.on_call = on_call
        self.envs = []

    def __call__(self, argv, **kwargs):
        args = tuple(argv[1:])
        self.calls.append(args)
        self.envs.append((argv[0], kwargs.get("env")))
        if self.on_call:
            self.on_call(args)
        if self.fail_on and args[:1] == (self.fail_on,):
            return SimpleNamespace(returncode=1, stdout="", stderr="Failed: broken")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class Sandbox:
    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.lib = base / "var" / "lib" / "x360-receiver"
        self.units = base / "etc" / "systemd" / "system"
        self.lib.parent.mkdir(parents=True)
        self.units.mkdir(parents=True)

    @property
    def unit_file(self):
        return self.units / poweroff_unit.UNIT_NAME


class UnitTextTests(unittest.TestCase):
    def test_unit_runs_the_helper_on_stop_only_and_survives_its_absence(self):
        text = poweroff_unit.render_unit(Path("/var/lib/x360-receiver"))
        self.assertIn("Type=oneshot", text)
        self.assertIn("RemainAfterExit=yes", text)  # without it there would be nothing to stop on shutdown
        self.assertIn("ExecStop=-/usr/bin/python3 -I /var/lib/x360-receiver/poweroff.py", text)  # "-": no error without the program
        self.assertIn("WantedBy=multi-user.target", text)
        self.assertIn("RequiresMountsFor=/var/lib/x360-receiver", text)
        self.assertNotIn("ExecStart=/usr/bin/python3", text)  # nothing of ours runs on start

    def test_systemd_waits_longer_than_the_poweroff_deadline(self):
        text = poweroff_unit.render_unit()
        timeout = int(next(l for l in text.splitlines() if l.startswith("TimeoutStopSec=")).split("=")[1])
        self.assertGreater(timeout, shutdown.DEADLINE_S + 1)

    def test_unit_text_is_english_and_ascii(self):
        # A system file cannot follow the Steam UI language; the unit text is English on every system.
        text = poweroff_unit.render_unit()
        self.assertTrue(text.isascii())
        self.assertIn("Description=X360 Receiver: turn off controllers on shutdown", text)

    def test_the_copy_gets_its_own_minimal_package_init(self):
        self.assertNotIn("__init__.py", poweroff_unit.HELPER_MODULES)  # the plugin's one imports the whole package
        self.assertNotIn("import", poweroff_unit.INIT_SOURCE)

    def test_every_helper_module_exists(self):
        for name in poweroff_unit.HELPER_MODULES:
            self.assertTrue((PACKAGE / name).is_file(), name)


class InstallTests(unittest.TestCase):
    def install(self, box, runner=None, package=PACKAGE):
        runner = runner or FakeSystemctl()
        result = poweroff_unit.install(package, box.lib, box.units, runner)
        return result, runner

    def test_install_writes_files_with_safe_modes_and_starts_the_service(self):
        box = Sandbox(self)
        result, runner = self.install(box)
        self.assertEqual(result, {"ok": True, "changed": True})
        self.assertEqual(runner.calls, [("daemon-reload",), ("enable", "--now", poweroff_unit.UNIT_NAME)])
        self.assertEqual(box.unit_file.read_text(), poweroff_unit.render_unit(box.lib))
        for name in poweroff_unit.HELPER_MODULES + ("__init__.py",):
            copy = box.lib / "x360w" / name
            if name != "__init__.py":
                self.assertEqual(copy.read_bytes(), (PACKAGE / name).read_bytes())
            self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o644, name)  # only root may write
        self.assertEqual(stat.S_IMODE((box.lib / "poweroff.py").stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(box.unit_file.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(box.lib.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((box.lib / "x360w").stat().st_mode), 0o755)
        self.assertFalse(list(box.lib.rglob("*.tmp")))

    def test_systemctl_calls_are_fixed_and_use_a_clean_environment(self):
        box = Sandbox(self)
        old = os.environ.get("LD_LIBRARY_PATH")
        os.environ["LD_LIBRARY_PATH"] = "/tmp/_MEI123"
        try:
            _, runner = self.install(box)
        finally:
            if old is None:
                del os.environ["LD_LIBRARY_PATH"]
            else:
                os.environ["LD_LIBRARY_PATH"] = old
        for executable, env in runner.envs:
            self.assertTrue(executable.endswith("systemctl"))
            self.assertEqual(set(env), {"PATH", "LANG", "LC_ALL"})
            self.assertEqual((env["LANG"], env["LC_ALL"]), ("C", "C"))  # same output on a German and an English system

    def test_second_install_changes_nothing_and_does_not_reload(self):
        box = Sandbox(self)
        self.install(box)
        result, runner = self.install(box)
        self.assertEqual(result, {"ok": True, "changed": False})
        self.assertEqual(runner.calls, [("enable", "--now", poweroff_unit.UNIT_NAME)])  # idempotent, no restart of the service

    def test_plugin_update_refreshes_the_copy_without_reload(self):
        box = Sandbox(self)
        with tempfile.TemporaryDirectory() as newpkg:
            for name in poweroff_unit.HELPER_MODULES:
                (Path(newpkg) / name).write_bytes((PACKAGE / name).read_bytes())
            self.install(box)
            (Path(newpkg) / "shutdown.py").write_text("# new version\n")
            result, runner = self.install(box, package=Path(newpkg))
        self.assertTrue(result["changed"])
        self.assertEqual((box.lib / "x360w" / "shutdown.py").read_text(), "# new version\n")
        self.assertNotIn(("daemon-reload",), runner.calls)

    def test_modes_do_not_depend_on_the_umask(self):
        # A root program that others could modify would be a back door: only root can write, even with umask 0.
        box = Sandbox(self)
        old = os.umask(0)
        try:
            self.install(box)
        finally:
            os.umask(old)
        for path in [box.unit_file, box.lib / "poweroff.py", *(box.lib / "x360w").iterdir()]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, path)
        self.assertEqual(stat.S_IMODE(box.lib.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((box.lib / "x360w").stat().st_mode), 0o755)

    def test_repairs_wrong_file_modes(self):
        box = Sandbox(self)
        self.install(box)
        os.chmod(box.lib / "x360w" / "actions.py", 0o666)
        self.install(box)
        self.assertEqual(stat.S_IMODE((box.lib / "x360w" / "actions.py").stat().st_mode), 0o644)

    def test_failing_systemctl_reports_error_and_leaves_nothing_behind(self):
        for failing in ("daemon-reload", "enable"):
            box = Sandbox(self)
            result, runner = self.install(box, FakeSystemctl(fail_on=failing))
            self.assertFalse(result["ok"], failing)
            self.assertIn("broken", result["error"])
            self.assertFalse(box.lib.exists(), failing)
            self.assertFalse(box.unit_file.exists(), failing)

    def test_missing_source_module_is_an_error_without_side_effects(self):
        box = Sandbox(self)
        with tempfile.TemporaryDirectory() as empty:
            result, runner = self.install(box, package=Path(empty))
        self.assertFalse(result["ok"])
        self.assertEqual(runner.calls, [])
        self.assertFalse(box.lib.exists())
        self.assertFalse(box.unit_file.exists())

    def test_timeout_is_an_error_not_an_exception(self):
        box = Sandbox(self)

        def hang(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 20)

        result = poweroff_unit.install(PACKAGE, box.lib, box.units, hang)
        self.assertFalse(result["ok"])
        self.assertIn("TimeoutExpired", result["error"])

    def test_symlinked_lib_dir_is_refused(self):
        box = Sandbox(self)
        target = box.lib.parent / "foreign"
        target.mkdir()
        box.lib.symlink_to(target)
        result, runner = self.install(box)
        self.assertFalse(result["ok"])
        self.assertIn("symlink", result["error"])
        self.assertEqual(list(target.iterdir()), [])  # nothing written into the foreign target
        self.assertTrue(target.exists())  # and the target itself not deleted

    def test_symlinked_unit_file_is_refused(self):
        box = Sandbox(self)
        target = box.units.parent / "foreign-file"
        target.write_text("untouched")
        box.unit_file.symlink_to(target)
        result, _ = self.install(box)
        self.assertFalse(result["ok"])
        self.assertEqual(target.read_text(), "untouched")


class UninstallTests(unittest.TestCase):
    def test_removes_program_before_stopping_the_service(self):
        # Stopping runs ExecStop. If the program is already gone, that has no effect; otherwise the
        # controllers would turn off when the option is switched off.
        box = Sandbox(self)
        poweroff_unit.install(PACKAGE, box.lib, box.units, FakeSystemctl())
        seen = {}

        def on_call(args):
            if args[:1] == ("disable",):
                seen["lib_exists"] = box.lib.exists()
                seen["unit_exists"] = box.unit_file.exists()

        runner = FakeSystemctl(on_call=on_call)
        result = poweroff_unit.uninstall(box.lib, box.units, runner)
        self.assertEqual(result, {"ok": True, "errors": []})
        self.assertEqual(seen, {"lib_exists": False, "unit_exists": True})
        self.assertEqual(runner.calls, [("disable", "--now", poweroff_unit.UNIT_NAME), ("daemon-reload",)])
        self.assertFalse(box.lib.exists())
        self.assertFalse(box.unit_file.exists())

    def test_nothing_installed_is_fine_and_calls_nothing(self):
        box = Sandbox(self)
        runner = FakeSystemctl()
        self.assertEqual(poweroff_unit.uninstall(box.lib, box.units, runner), {"ok": True, "errors": []})
        self.assertEqual(runner.calls, [])

    def test_failing_systemctl_is_reported_but_files_are_gone(self):
        box = Sandbox(self)
        poweroff_unit.install(PACKAGE, box.lib, box.units, FakeSystemctl())
        result = poweroff_unit.uninstall(box.lib, box.units, FakeSystemctl(fail_on="disable"))
        self.assertFalse(result["ok"])
        self.assertIn("broken", result["errors"][0])
        self.assertFalse(box.lib.exists())
        self.assertFalse(box.unit_file.exists())

    def test_never_deletes_a_symlink_target_or_a_wrongly_named_folder(self):
        box = Sandbox(self)
        target = box.lib.parent / "foreign"
        target.mkdir()
        (target / "important").write_text("x")
        box.lib.symlink_to(target)
        result = poweroff_unit.uninstall(box.lib, box.units, FakeSystemctl())
        self.assertFalse(result["ok"])
        self.assertTrue((target / "important").exists())
        other = box.lib.parent / "other-folder"
        other.mkdir()
        (other / "important").write_text("x")
        result = poweroff_unit.uninstall(other, box.units, FakeSystemctl())
        self.assertFalse(result["ok"])
        self.assertTrue((other / "important").exists())

    def test_removes_compiled_leftovers_too(self):
        box = Sandbox(self)
        poweroff_unit.install(PACKAGE, box.lib, box.units, FakeSystemctl())
        (box.lib / "x360w" / "__pycache__").mkdir()
        (box.lib / "x360w" / "__pycache__" / "a.pyc").write_bytes(b"x")
        (box.lib / "last-run.json").write_text("{}")
        poweroff_unit.uninstall(box.lib, box.units, FakeSystemctl())
        self.assertFalse(box.lib.exists())


class IsInstalledTests(unittest.TestCase):
    def test_needs_unit_and_program(self):
        box = Sandbox(self)
        self.assertFalse(poweroff_unit.is_installed(box.lib, box.units))
        poweroff_unit.install(PACKAGE, box.lib, box.units, FakeSystemctl())
        self.assertTrue(poweroff_unit.is_installed(box.lib, box.units))
        (box.lib / "poweroff.py").unlink()
        self.assertFalse(poweroff_unit.is_installed(box.lib, box.units))


class CopyIsSelfContainedTests(unittest.TestCase):
    """The copy under /var/lib must run without the rest of the plugin, with the system Python in isolated mode."""

    def test_copy_imports_alone_and_loads_no_module_outside_the_list(self):
        box = Sandbox(self)
        poweroff_unit.install(PACKAGE, box.lib, box.units, FakeSystemctl())
        code = (
            "import sys, json; sys.path.insert(0, sys.argv[1]);"
            "from x360w import poweroff_cli;"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('x360w'))))"
        )
        out = subprocess.run([sys.executable, "-I", "-c", code, str(box.lib)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        loaded = json.loads(out.stdout)
        allowed = {"x360w"} | {"x360w." + n[:-3] for n in poweroff_unit.HELPER_MODULES}
        self.assertLessEqual(set(loaded), allowed)

    def test_entry_script_runs_exits_zero_and_writes_the_report(self):
        box = Sandbox(self)
        poweroff_unit.install(PACKAGE, box.lib, box.units, FakeSystemctl())
        out = subprocess.run([sys.executable, "-I", str(box.lib / "poweroff.py")], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("x360w-poweroff {"))
        report = poweroff_unit.read_last_run(box.lib)
        self.assertIsNotNone(report)
        self.assertIsNone(report["error"])
        self.assertIn("duration_s", report)


class SummaryTests(unittest.TestCase):
    RUN = {"at": 1000.0, "receivers": 1, "targets": [[1, 2, 0], [1, 2, 1]], "duration_s": 2.1,
           "result": {"ok": True, "sent": 2, "confirmed": 1, "errors": []}, "error": None}

    def summarize(self, **kw):
        args = dict(enabled=True, installed=True, last_run=None, install_error=None)
        args.update(kw)
        return poweroff_unit.summarize(args.pop("enabled"), args.pop("installed"), args.pop("last_run"),
                                       args.pop("install_error"), localtime=__import__("time").gmtime)

    def test_nothing_to_show_when_off_and_never_run(self):
        self.assertIsNone(self.summarize(enabled=False, installed=False))

    def test_install_error_comes_first(self):
        result = self.summarize(installed=False, install_error="no systemd", last_run=self.RUN)
        self.assertEqual(result["verdict"], {"code": "install_failed", "error": "no systemd"})

    def test_not_installed_without_error(self):
        self.assertEqual(self.summarize(installed=False)["verdict"], {"code": "not_installed"})

    def test_installed_but_never_run(self):
        result = self.summarize()
        self.assertEqual(result["verdict"], {"code": "not_run_yet"})
        self.assertEqual(result["lines"], [])

    def test_successful_run(self):
        result = self.summarize(last_run=self.RUN)
        self.assertEqual(result["verdict"], {"code": "run_ok", "sent": 2, "total": 2})
        self.assertEqual(result["lines"][0], {"key": "time", "value": "1970-01-01 00:16:40"})
        self.assertIn({"key": "duration", "value": "2.1 s"}, result["lines"])
        self.assertIn({"key": "receivers", "value": "1"}, result["lines"])
        self.assertIn({"key": "targets", "value": "[[1, 2, 0], [1, 2, 1]]"}, result["lines"])

    def test_run_with_errors_names_the_first_one(self):
        run = dict(self.RUN, result={"ok": False, "sent": 1, "confirmed": 1, "errors": ["slot 2: deadline", "other"]})
        self.assertEqual(self.summarize(last_run=run)["verdict"],
                         {"code": "run_partial", "sent": 1, "total": 2, "error": "slot 2: deadline"})

    def test_run_without_controller(self):
        run = dict(self.RUN, targets=[], result={"ok": True, "sent": 0, "confirmed": 0, "errors": []})
        self.assertEqual(self.summarize(last_run=run)["verdict"], {"code": "run_no_controllers"})

    def test_run_that_failed(self):
        run = dict(self.RUN, targets=[], result=None, error="OSError: x")
        result = self.summarize(last_run=run)
        self.assertEqual(result["verdict"], {"code": "run_failed", "error": "OSError: x"})
        self.assertIn({"key": "error", "value": "OSError: x"}, result["lines"])

    def test_old_run_is_still_shown_after_switching_the_option_off(self):
        result = self.summarize(enabled=False, installed=False, last_run=self.RUN)
        self.assertEqual(result["verdict"], {"code": "run_ok", "sent": 2, "total": 2, "option_off": True})

    def test_report_that_could_not_be_written_is_listed(self):
        result = self.summarize(last_run=dict(self.RUN, write_error="disk full"))
        self.assertIn({"key": "write_error", "value": "disk full"}, result["lines"])

    def test_only_documented_codes_and_keys_are_emitted(self):
        # The frontend translates exactly these (tests/test_i18n_contract.py checks that side).
        failed = dict(self.RUN, targets=[], result=None, error="x", write_error="w")
        partial = dict(self.RUN, result={"ok": False, "sent": 1, "confirmed": 1, "errors": ["e"]})
        none = dict(self.RUN, targets=[], result={"ok": True, "sent": 0, "confirmed": 0, "errors": []})
        results = [
            self.summarize(installed=False, install_error="e"),
            self.summarize(installed=False),
            self.summarize(),
            self.summarize(last_run=failed),
            self.summarize(last_run=none),
            self.summarize(last_run=partial),
            self.summarize(last_run=self.RUN),
        ]
        self.assertEqual({r["verdict"]["code"] for r in results}, set(poweroff_unit.VERDICT_CODES))
        keys = {line["key"] for r in results for line in r["lines"]}
        self.assertEqual(keys, set(poweroff_unit.LINE_KEYS))

    def test_read_last_run_ignores_missing_and_broken_files(self):
        box = Sandbox(self)
        self.assertIsNone(poweroff_unit.read_last_run(box.lib))
        box.lib.mkdir()
        for text in ("broken{", "[1]", ""):
            (box.lib / "last-run.json").write_text(text)
            self.assertIsNone(poweroff_unit.read_last_run(box.lib), text)


if __name__ == "__main__":
    unittest.main()
