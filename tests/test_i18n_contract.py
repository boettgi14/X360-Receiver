"""Contract between the language-neutral backend and the translated frontend (src/i18n.ts).

The backend sends error codes, diagnostics verdicts and line keys, LED mode numbers and controller
subtype numbers; the frontend turns them into text in the Steam UI language. These tests read
`src/i18n.ts` and `src/index.tsx` as text and check that both sides know the same things, so a code
added on one side without the other is caught here. (Types and the German catalog matching the English
one are additionally enforced by `npm run typecheck`; the rendered texts by tools/frontend_render_test.mjs.)
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))
sys.path.insert(0, str(ROOT / "tests"))

from test_discovery import make_receiver  # noqa: E402
from x360w import controls, error_codes, poweroff_unit, protocol, view  # noqa: E402
from x360w.discovery import find_receivers  # noqa: E402

I18N = (ROOT / "src" / "i18n.ts").read_text(encoding="utf-8")
INDEX = (ROOT / "src" / "index.tsx").read_text(encoding="utf-8")


def catalog(name: str) -> str:
    """Source text of the `en` or `de` catalog object."""
    if name == "en":
        start, end = "const en = {\n", "\n};\n\nexport type Messages"
    else:
        start, end = "const de: Messages = {\n", "\n};\n\nexport const MESSAGES"
    return I18N.split(start, 1)[1].split(end, 1)[0]


def nested(block: str, name: str) -> str:
    match = re.search(rf"^  {name}: \{{\n(.*?)^  \}},", block, re.S | re.M)
    assert match, f"no object {name!r} in the catalog"
    return match.group(1)


def keys(text: str) -> list:
    return re.findall(r"^    (\w+):", text, re.M)


def numbered_texts(text: str) -> dict:
    return {int(number): value for number, value in re.findall(r'^    (\d+): "(.*)",$', text, re.M)}


class CatalogShapeTests(unittest.TestCase):
    def test_both_languages_define_the_same_messages(self):
        top = lambda block: re.findall(r"^  (\w+):", block, re.M)
        self.assertEqual(top(catalog("en")), top(catalog("de")))
        self.assertGreater(len(top(catalog("en"))), 50)  # sanity check that the catalog was really parsed

    def test_nested_tables_have_the_same_keys_in_both_languages(self):
        for table in ("subtypes", "ledModes", "diagnosticLines", "errors"):
            self.assertEqual(keys(nested(catalog("en"), table)), keys(nested(catalog("de"), table)), table)


class ErrorCodeTests(unittest.TestCase):
    def test_every_backend_error_code_is_translated(self):
        for language in ("en", "de"):
            translated = keys(nested(catalog(language), "errors"))
            self.assertEqual(sorted(translated), sorted(error_codes.ALL), language)

    def test_codes_are_unique_lowercase_identifiers(self):
        self.assertEqual(len(set(error_codes.ALL)), len(error_codes.ALL))
        self.assertTrue(all(re.fullmatch(r"[a-z_]+", code) for code in error_codes.ALL))


class DiagnosticsTests(unittest.TestCase):
    def test_every_verdict_code_is_handled_by_the_frontend(self):
        handled = re.findall(r'case "(\w+)":', I18N.split("export function verdictText", 1)[1])
        self.assertEqual(sorted(handled), sorted(poweroff_unit.VERDICT_CODES))

    def test_every_diagnostic_line_key_has_a_label_in_both_languages(self):
        for language in ("en", "de"):
            labels = keys(nested(catalog(language), "diagnosticLines"))
            self.assertEqual(sorted(labels), sorted(poweroff_unit.LINE_KEYS), language)


class TablesTests(unittest.TestCase):
    def test_led_modes_cover_every_mode_and_english_matches_the_backend_fallback(self):
        english = numbered_texts(nested(catalog("en"), "ledModes"))
        german = numbered_texts(nested(catalog("de"), "ledModes"))
        self.assertEqual(sorted(english), sorted(controls.LED_MODES))
        self.assertEqual(sorted(german), sorted(controls.LED_MODES))
        self.assertEqual(english, controls.LED_MODES)  # the fallback text and the English text must not drift apart

    def test_subtypes_cover_every_backend_name_and_english_matches_the_backend(self):
        english = numbered_texts(nested(catalog("en"), "subtypes"))
        german = numbered_texts(nested(catalog("de"), "subtypes"))
        self.assertEqual(sorted(german), sorted(protocol.SUBTYPE_NAMES))
        self.assertEqual(english, protocol.SUBTYPE_NAMES)


class DataShapeTests(unittest.TestCase):
    """Every field the frontend's `Controller` and `Receiver` types declare is really sent."""

    @staticmethod
    def interface_fields(name: str) -> set:
        body = re.search(rf"^interface {name} \{{\n(.*?)^\}}", INDEX, re.S | re.M).group(1)
        return set(re.findall(r"^  (\w+)\??:", body, re.M))

    def test_frontend_types_are_backed_by_the_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_receiver(Path(tmp), "1-2", "0719", bus=1, devnum=4)
            receivers = find_receivers(Path(tmp))
            [receiver_view] = view.build_receiver_views(receivers, [], {"1-2": ["xpad0"]}, {"1-2": {0}})
        [controller_view] = receiver_view["controllers"]
        self.assertLessEqual(self.interface_fields("Controller"), set(controller_view))
        self.assertLessEqual(self.interface_fields("Receiver"), set(receiver_view))


if __name__ == "__main__":
    unittest.main()
