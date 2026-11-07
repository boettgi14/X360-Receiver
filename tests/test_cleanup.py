"""Tests for x360w.cleanup: restoring what the plugin changed when it is removed."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from x360w import cleanup  # noqa: E402


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

    def test_the_plugin_has_no_code_that_deletes_folders_as_root(self):
        # The settings/data/log folders are deliberately left alone (see the README). Keep it that way.
        self.assertFalse(hasattr(cleanup, "remove_plugin_dir"))
        self.assertNotIn("rmtree", (ROOT / "main.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
