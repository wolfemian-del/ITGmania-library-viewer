"""Guards for theme.py: the window code must take every color and font from it."""
import ast
import re
import unittest
from pathlib import Path

import theme

ROOT = Path(__file__).resolve().parent.parent
WINDOW_SOURCE = (ROOT / "library_visualizer.py").read_text(encoding="utf-8")
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")


def theme_names_used_by_window():
    tree = ast.parse(WINDOW_SOURCE)
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "theme"
    }


class WindowUsesThemeTests(unittest.TestCase):
    def test_no_color_literals_in_window_code(self):
        # Strings starting with "#" that are not colors (such as "#1" column ids) do not match HEX_COLOR.
        found = sorted(set(HEX_COLOR.findall(WINDOW_SOURCE)))
        self.assertEqual(found, [], "hex colors belong in theme.py")

    def test_no_named_color_literals_in_window_code(self):
        found = re.findall(
            r"""\b(?:fg|bg|activebackground|activeforeground|insertbackground|selectcolor)\s*=\s*["'][a-z]+["']""",
            WINDOW_SOURCE,
        )
        self.assertEqual(found, [], "color names belong in theme.py")

    def test_no_font_literals_in_window_code(self):
        found = re.findall(r"""\bfont\s*=\s*\(""", WINDOW_SOURCE)
        self.assertEqual(found, [], "fonts belong in theme.py")

    def test_every_theme_name_the_window_uses_exists(self):
        missing = sorted(name for name in theme_names_used_by_window() if not hasattr(theme, name))
        self.assertEqual(missing, [], "a typo here would only crash when that dialog opens")

    def test_every_theme_name_is_used(self):
        defined = {name for name in dir(theme) if name.isupper()}
        self.assertEqual(sorted(defined - theme_names_used_by_window()), [], "remove unused theme entries")


class ThemeValuesTests(unittest.TestCase):
    def test_colors_are_six_digit_hex_or_plain_names(self):
        for name in dir(theme):
            value = getattr(theme, name)
            if name.isupper() and isinstance(value, str):
                self.assertTrue(HEX_COLOR.fullmatch(value) or value.isalpha(), f"{name} = {value!r}")

    def test_difficulty_colors_cover_every_difficulty(self):
        from library_data import DIFFICULTY_ORDER
        for difficulty in DIFFICULTY_ORDER:
            self.assertIn(difficulty, theme.DIFFICULTY_COLORS)

    def test_fonts_are_family_size_tuples(self):
        for name in dir(theme):
            if name.startswith("FONT_"):
                family, size, *style = getattr(theme, name)
                self.assertIsInstance(family, str, name)
                self.assertIsInstance(size, int, name)

    def test_theme_does_not_need_tkinter(self):
        self.assertNotIn("tkinter", (ROOT / "theme.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
