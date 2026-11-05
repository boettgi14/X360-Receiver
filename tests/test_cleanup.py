"""Tests für x360w.cleanup: Löschen nur genau der eigenen Decky-Ordner."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import cleanup  # noqa: E402


class RemovePluginDirTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name).resolve() / "homebrew"
        (self.home / "settings" / "P").mkdir(parents=True)
        (self.home / "settings" / "P" / "f").write_text("x")
        self.calls = []

    def remove(self, path, home=None):
        return cleanup.remove_plugin_dir(str(path), str(home or self.home), rmtree=self.calls.append)

    def test_removes_exact_plugin_dir(self):
        self.assertTrue(self.remove(self.home / "settings" / "P"))
        self.assertEqual(self.calls, [str(self.home / "settings" / "P")])

    def test_real_deletion(self):
        self.assertTrue(cleanup.remove_plugin_dir(str(self.home / "settings" / "P"), str(self.home)))
        self.assertFalse((self.home / "settings" / "P").exists())
        self.assertTrue((self.home / "settings").exists())

    def test_refuses_everything_else(self):
        (self.home / "other" / "P").mkdir(parents=True)
        (self.home / "settings" / "P" / "tief").mkdir()
        cases = [
            "", "relativ/pfad",
            self.home,                                  # DECKY_HOME selbst
            self.home / "settings",                     # Elternordner
            self.home / "other" / "P",                  # unbekannte Art
            self.home / "settings" / "P" / "tief",      # zu tief
            self.home / "settings" / "fehlt",           # existiert nicht
            self.home / "settings" / "..",              # normalisiert zu DECKY_HOME
            Path("/"), Path("/etc"), Path("/home"),
        ]
        for case in cases:
            self.assertFalse(self.remove(case), repr(case))
        self.assertFalse(cleanup.remove_plugin_dir(None, str(self.home), rmtree=self.calls.append))
        self.assertEqual(self.calls, [])

    def test_dotdot_inside_path_is_normalized_not_trusted(self):
        # Landet nach Normalisierung auf dem erlaubten Pfad, darf also gelöscht werden;
        # ein Ausbruch aus DECKY_HOME wird dagegen abgewiesen.
        self.assertTrue(self.remove(self.home / "settings" / "x" / ".." / "P"))
        (self.home / "settings" / "Q").mkdir()
        self.assertFalse(self.remove(self.home / "settings" / "Q" / ".." / ".." / ".." / "etc"))

    def test_refuses_without_home(self):
        self.assertFalse(cleanup.remove_plugin_dir(str(self.home / "settings" / "P"), None, rmtree=self.calls.append))
        self.assertFalse(cleanup.remove_plugin_dir(str(self.home / "settings" / "P"), "", rmtree=self.calls.append))
        self.assertEqual(self.calls, [])

    def test_refuses_symlink_as_plugin_dir(self):
        target = Path(self._tmp.name).resolve() / "wichtig"
        target.mkdir()
        (self.home / "data").mkdir()
        os.symlink(target, self.home / "data" / "P")
        self.assertFalse(self.remove(self.home / "data" / "P"))
        self.assertEqual(self.calls, [])

    def test_refuses_symlinked_kind_directory(self):
        target = Path(self._tmp.name).resolve() / "woanders"
        (target / "P").mkdir(parents=True)
        os.symlink(target, self.home / "logs")
        self.assertFalse(self.remove(self.home / "logs" / "P"))
        self.assertEqual(self.calls, [])

    def test_symlinked_decky_home_is_allowed(self):
        # Bazzite: /home -> /var/home. DECKY_HOME darf über einen Symlink erreichbar sein.
        link = Path(self._tmp.name).resolve() / "link"
        os.symlink(self.home, link)
        self.assertTrue(self.remove(link / "settings" / "P", home=link))


class RestoreAutoPoweroffTests(unittest.TestCase):
    def test_restores_when_different(self):
        written = []
        self.assertTrue(cleanup.restore_auto_poweroff(True, setter=written.append, getter=lambda: False))
        self.assertEqual(written, [True])

    def test_noop_when_same_or_unknown(self):
        written = []
        self.assertFalse(cleanup.restore_auto_poweroff(True, setter=written.append, getter=lambda: True))
        for bad in (None, "Y", 1, 0):
            self.assertFalse(cleanup.restore_auto_poweroff(bad, setter=written.append, getter=lambda: False))
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
