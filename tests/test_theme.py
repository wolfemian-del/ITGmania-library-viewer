"""Guards for theme.py: the window code must take every color and font from it."""
import ast
import re
import unittest
from pathlib import Path

import theme

ROOT = Path(__file__).resolve().parent.parent
# The window code lives in these modules; a split move adds its module here so the
# guards below keep covering all of it.
WINDOW_SOURCES = tuple(
    (ROOT / name).read_text(encoding="utf-8")
    for name in ("library_visualizer.py", "course_builder.py", "row_tints.py",
                 "advanced_search.py", "distribution_panel.py", "data_paths_dialog.py",
                 "library_loader.py")
)
WINDOW_SOURCE = "\n".join(WINDOW_SOURCES)
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")


def theme_names_used_by_window():
    tree = ast.parse(WINDOW_SOURCE)
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "theme"
    }


def relative_luminance(hex_color):
    """WCAG relative luminance of a #rrggbb color."""
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


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

    def test_no_text_size_literals_in_window_code(self):
        found = re.findall(r"\b(?:fontsize|labelsize)\s*=\s*[0-9.]+", WINDOW_SOURCE)
        self.assertEqual(found, [], "chart text sizes belong in theme.py")

    def test_no_layout_literals_in_window_code(self):
        found_rowheight = re.findall(r"\browheight\s*=\s*[0-9]+", WINDOW_SOURCE)
        self.assertEqual(found_rowheight, [], "Treeview rowheight belongs in theme.py")

        found_dist = re.findall(r"^DIST_PANEL_WIDTH\s*=", WINDOW_SOURCE, re.MULTILINE)
        self.assertEqual(found_dist, [], "DIST_PANEL_WIDTH belongs in theme.py")
        found_click = re.findall(r"^CHART_MIN_CLICK_FRACTION\s*=", WINDOW_SOURCE, re.MULTILINE)
        self.assertEqual(found_click, [], "CHART_MIN_CLICK_FRACTION belongs in theme.py")

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
            if name.isupper() and isinstance(value, str) and not name.endswith("_GEOMETRY"):
                self.assertTrue(HEX_COLOR.fullmatch(value) or value.isalpha(), f"{name} = {value!r}")

    def test_difficulty_colors_cover_every_difficulty(self):
        from library_data import DIFFICULTY_ORDER
        for difficulty in DIFFICULTY_ORDER:
            self.assertIn(difficulty, theme.DIFFICULTY_COLORS)

    def test_difficulty_colors_meet_minimum_contrast_on_the_table_background(self):
        # Issue #35: the difficulty colors are row text on BG_TABLE, so
        # each must meet WCAG AA's 4.5:1 for body text. Challenge sat at
        # 4.29:1 (#a855f7) before its move to #c084fc (6.42:1); this
        # guard keeps the next palette edit from reintroducing a
        # sub-AA color.
        for difficulty, color in theme.DIFFICULTY_COLORS.items():
            with self.subTest(difficulty=difficulty):
                self.assertGreaterEqual(contrast_ratio(color, theme.BG_TABLE), 4.5)

    def test_fonts_are_family_size_tuples(self):
        for name in dir(theme):
            if name.startswith("FONT_"):
                family, size, *style = getattr(theme, name)
                self.assertIsInstance(family, str, name)
                self.assertIsInstance(size, int, name)

    def test_layout_constants_are_positive_numbers_or_valid_geometries(self):
        self.assertGreater(theme.TABLE_ROW_HEIGHT, 0)
        self.assertGreater(theme.BUTTON_PADX, 0)
        self.assertGreater(theme.BUTTON_PADY, 0)
        self.assertGreater(theme.DIST_PANEL_WIDTH, 0)
        self.assertGreater(theme.CHART_MIN_CLICK_FRACTION, 0)
        self.assertLess(theme.CHART_MIN_CLICK_FRACTION, 1)
        self.assertGreater(theme.CHART_BAR_HEIGHT, 0)
        self.assertLess(theme.CHART_BAR_HEIGHT, 1)
        for name in ("WINDOW_DEFAULT_GEOMETRY", "ADVANCED_SEARCH_GEOMETRY", "COURSE_BUILDER_GEOMETRY"):
            geom = getattr(theme, name)
            self.assertRegex(geom, r"^\d+x\d+$", name)
        for name in ("WINDOW_MIN_SIZE", "ADVANCED_SEARCH_MIN_SIZE", "COURSE_BUILDER_MIN_SIZE"):
            min_size = getattr(theme, name)
            self.assertIsInstance(min_size, tuple, name)
            self.assertEqual(len(min_size), 2, name)
            self.assertTrue(all(isinstance(v, int) and v > 0 for v in min_size), name)

    def test_theme_does_not_need_tkinter(self):
        self.assertNotIn("tkinter", (ROOT / "theme.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
