"""Tests for x360w.cleanup: deleting exactly the plugin's own Decky folders and nothing else."""

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
        (self.home / "settings" / "P" / "deep").mkdir()
        cases = [
            "", "relative/path",
            self.home,                                  # DECKY_HOME itself
            self.home / "settings",                     # parent folder
            self.home / "other" / "P",                  # unknown kind
            self.home / "settings" / "P" / "deep",      # too deep
            self.home / "settings" / "missing",           # does not exist
            self.home / "settings" / "..",              # normalizes to DECKY_HOME
            Path("/"), Path("/etc"), Path("/home"),
        ]
        for case in cases:
            self.assertFalse(self.remove(case), repr(case))
        self.assertFalse(cleanup.remove_plugin_dir(None, str(self.home), rmtree=self.calls.append))
        self.assertEqual(self.calls, [])

    def test_dotdot_inside_path_is_normalized_not_trusted(self):
        # Ends up on the allowed path after normalization, so it may be deleted;
        # an escape from DECKY_HOME is refused.
        self.assertTrue(self.remove(self.home / "settings" / "x" / ".." / "P"))
        (self.home / "settings" / "Q").mkdir()
        self.assertFalse(self.remove(self.home / "settings" / "Q" / ".." / ".." / ".." / "etc"))

    def test_refuses_without_home(self):
        self.assertFalse(cleanup.remove_plugin_dir(str(self.home / "settings" / "P"), None, rmtree=self.calls.append))
        self.assertFalse(cleanup.remove_plugin_dir(str(self.home / "settings" / "P"), "", rmtree=self.calls.append))
        self.assertEqual(self.calls, [])

    def test_refuses_symlink_as_plugin_dir(self):
        target = Path(self._tmp.name).resolve() / "important"
        target.mkdir()
        (self.home / "data").mkdir()
        os.symlink(target, self.home / "data" / "P")
        self.assertFalse(self.remove(self.home / "data" / "P"))
        self.assertEqual(self.calls, [])

    def test_refuses_symlinked_kind_directory(self):
        target = Path(self._tmp.name).resolve() / "elsewhere"
        (target / "P").mkdir(parents=True)
        os.symlink(target, self.home / "logs")
        self.assertFalse(self.remove(self.home / "logs" / "P"))
        self.assertEqual(self.calls, [])

    def test_symlinked_decky_home_is_allowed(self):
        # Bazzite: /home -> /var/home. DECKY_HOME may be reached through a symlink.
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
