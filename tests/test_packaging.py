"""Tests für tools/make_zip.py: Aufbau der Decky-Zip."""

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_tool():
    spec = importlib.util.spec_from_file_location("make_zip", ROOT / "tools" / "make_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILT = (ROOT / "dist" / "index.js").is_file()
NEEDS_BUILD = unittest.skipUnless(BUILT, "Frontend nicht gebaut (npm run build)")


class PackagingTests(unittest.TestCase):
    @NEEDS_BUILD
    def test_zip_has_expected_layout_and_nothing_else(self):
        tool = load_tool()
        name = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["name"]
        with tempfile.TemporaryDirectory() as tmp:
            out = tool.build(Path(tmp) / "x.zip")
            names = zipfile.ZipFile(out).namelist()
        self.assertTrue(all(n.startswith(f"{name}/") for n in names))
        for required in ("plugin.json", "package.json", "main.py", "dist/index.js", "py_modules/x360w/protocol.py",
                         "py_modules/x360w/actions.py", "py_modules/x360w/takeover.py",
                         "py_modules/x360w/poweroff_unit.py", "py_modules/x360w/poweroff_cli.py"):
            self.assertIn(f"{name}/{required}", names)
        for n in names:
            self.assertNotIn("__pycache__", n)
            self.assertNotIn("tests/", n)
            self.assertFalse(n.endswith(".map"))

    @NEEDS_BUILD
    def test_zip_contains_every_module_the_service_copies(self):
        # Der Dienst kopiert diese Dateien aus dem installierten Plugin; fehlt eine, scheitert das Einschalten der Option.
        import sys
        sys.path.insert(0, str(ROOT / "py_modules"))
        from x360w import poweroff_unit

        tool = load_tool()
        name = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["name"]
        with tempfile.TemporaryDirectory() as tmp:
            names = set(zipfile.ZipFile(tool.build(Path(tmp) / "x.zip")).namelist())
        for module in poweroff_unit.HELPER_MODULES:
            self.assertIn(f"{name}/py_modules/x360w/{module}", names)

    def test_plugin_json_has_root_flag(self):
        flags = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["flags"]
        self.assertIn("root", flags)
        self.assertNotIn("_root", flags)  # "_root" (Vorlage) lässt Decky das Plugin ohne Root-Rechte starten


if __name__ == "__main__":
    unittest.main()
