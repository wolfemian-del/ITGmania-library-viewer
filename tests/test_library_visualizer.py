import contextlib
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import data_paths_dialog as dialog
import distribution_panel as dp
import library_data
import library_visualizer as app
import row_tints
import theme


class CourseGeometryAppTests(unittest.TestCase):
    """Issue #25: validating, storing, and wiring the course window's geometry."""

    def test_valid_course_geometry_accepts_and_canonicalizes(self):
        self.assertEqual(app.LibraryApp._valid_course_geometry("1000x620+10+10"), "1000x620+10+10")
        # A negative coordinate is rebuilt in Tk's own spelling ("+-8"): the
        # shorter "-8" form means "8px from the right edge" to Tk and would
        # restore the window to the wrong side of the screen.
        self.assertEqual(app.LibraryApp._valid_course_geometry("1000x620+-8+100"), "1000x620+-8+100")
        self.assertEqual(app.LibraryApp._valid_course_geometry("1000x620-8+100"), "1000x620+-8+100")

    def test_valid_course_geometry_rejects_unusable_values(self):
        for value in (None, 42, "garbage", "1000x620", "1x1+0+0",
                      "699x620+0+0", "1000x439+0+0"):
            with self.subTest(value=value):
                self.assertIsNone(app.LibraryApp._valid_course_geometry(value))

    def make_saving_app(self, directory, course_geometry):
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = Path(directory) / "settings.json"
        instance.tree = Mock()
        instance.cache_var = Mock(get=Mock(return_value="/cache"))
        instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
        instance.column_order = list(app.HEADERS)
        instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
        instance.tree.column.return_value = 100
        instance.sort_keys = [("Pack", False)]
        instance.show_distribution_panel = Mock(get=Mock(return_value=False))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.pack_var = Mock(get=Mock(return_value="All packs"))
        instance.type_var = Mock(get=Mock(return_value="All types"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.course_geometry = course_geometry
        instance.advanced_search_geometry = None
        instance._settings_store = library_data.SettingsStore(instance.settings_path)
        instance._settings_store.load()
        return instance

    def test_save_settings_includes_the_key_only_when_a_geometry_is_set(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_saving_app(directory, "1000x620+10+10")
            instance._save_settings()
            data = json.loads(instance.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["course_geometry"], "1000x620+10+10")
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_saving_app(directory, None)
            instance._save_settings()
            data = json.loads(instance.settings_path.read_text(encoding="utf-8"))
            self.assertNotIn("course_geometry", data)

    def test_save_settings_stores_column_widths_in_canonical_units(self):
        # The table reports physical pixels; at 150% a 195 px column is
        # stored as 130, so it comes back the same at any scale (issue #51).
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_saving_app(directory, None)
            instance._dpi_scale = 1.5
            instance.tree.column.return_value = 195
            instance._save_settings()
            data = json.loads(instance.settings_path.read_text(encoding="utf-8"))
            self.assertTrue(data["column_widths"])
            self.assertEqual(set(data["column_widths"].values()), {130})

    def test_stored_geometry_survives_a_save_triggered_by_an_unrelated_change(self):
        # __init__ seeds course_geometry from the file, so a routine save in a
        # session that never opens the dialog must carry the key through.
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_saving_app(directory, "1000x620+10+10")
            instance._save_settings()
            instance.tree.column.return_value = 150  # an unrelated change forces a rewrite
            instance._save_settings()
            data = json.loads(instance.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["course_geometry"], "1000x620+10+10")

    def test_geometry_callback_stores_the_value_and_saves(self):
        instance = object.__new__(app.LibraryApp)
        instance.course_geometry = None
        instance._save_settings = Mock()
        instance._course_geometry_changed("900x620+5+5")
        self.assertEqual(instance.course_geometry, "900x620+5+5")
        instance._save_settings.assert_called_once_with()

    def test_approved_exit_saves_the_geometry_before_destroying_the_root(self):
        instance = object.__new__(app.LibraryApp)
        instance.root = Mock()
        builder = Mock()
        builder.confirm_discard_for_app_exit.return_value = True
        instance.course_builder = builder
        instance.advanced_search = None
        manager = Mock()
        manager.attach_mock(builder, "builder")
        manager.attach_mock(instance.root, "root")
        instance._close_app()
        names = [call[0] for call in manager.mock_calls]
        self.assertLess(names.index("builder.confirm_discard_for_app_exit"),
                        names.index("builder.save_window_geometry"))
        self.assertLess(names.index("builder.save_window_geometry"), names.index("root.destroy"))

    def test_live_app_passes_the_saved_geometry_to_the_builder(self):
        """Wiring guard (live Tk; skipped headless): a construction that forgot to
        pass the geometry inputs would silently disable the whole feature."""
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings_path = Path(settings_dir.name) / "settings.json"
        settings_path.write_text(json.dumps({"course_geometry": "900x620+30+40"}), encoding="utf-8")
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            application = app.LibraryApp(root)
            self.assertEqual(application.course_geometry, "900x620+30+40")
            self.assertEqual(application.course_builder._saved_geometry, "900x620+30+40")
            self.assertEqual(application.course_builder._report_geometry,
                             application._course_geometry_changed)
        finally:
            root.destroy()


class AdvancedSearchGeometryAppTests(unittest.TestCase):
    """Issue #98: validating, storing, and wiring the Advanced Search window's geometry.

    The app-side half; the component half is in tests/test_advanced_search.py.
    The rules are the course window's (issue #25) with this dialog's own
    minimum size, through the shared validator.
    """

    def test_valid_advanced_search_geometry_accepts_and_canonicalizes(self):
        self.assertEqual(app.LibraryApp._valid_advanced_search_geometry("700x640+10+10"), "700x640+10+10")
        self.assertEqual(app.LibraryApp._valid_advanced_search_geometry("700x640-8+100"), "700x640+-8+100")

    def test_valid_advanced_search_geometry_rejects_unusable_values(self):
        for value in (None, "", "abc", "400x600+0+0", "900x500+0+0", "700x640+0", "0x0+0+0"):
            with self.subTest(value=value):
                self.assertIsNone(app.LibraryApp._valid_advanced_search_geometry(value))

    def test_the_floor_is_this_dialogs_own_minimum_not_the_course_windows(self):
        # Big enough for Advanced Search (480x520) but below the course floor (700 wide).
        self.assertEqual(app.LibraryApp._valid_advanced_search_geometry("500x530+10+10"), "500x530+10+10")
        self.assertIsNone(app.LibraryApp._valid_course_geometry("500x530+10+10"))
        # Big enough for the course window (440 tall) but below this dialog's floor (520).
        self.assertEqual(app.LibraryApp._valid_course_geometry("900x500+10+10"), "900x500+10+10")
        self.assertIsNone(app.LibraryApp._valid_advanced_search_geometry("900x500+10+10"))

    def make_saving_app(self, directory, advanced_search_geometry):
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = Path(directory) / "settings.json"
        instance.tree = Mock()
        instance.cache_var = Mock(get=Mock(return_value="/cache"))
        instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
        instance.column_order = list(app.HEADERS)
        instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
        instance.tree.column.return_value = 100
        instance.sort_keys = [("Pack", False)]
        instance.show_distribution_panel = Mock(get=Mock(return_value=False))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.pack_var = Mock(get=Mock(return_value="All packs"))
        instance.type_var = Mock(get=Mock(return_value="All types"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.course_geometry = None
        instance.advanced_search_geometry = advanced_search_geometry
        instance._settings_store = library_data.SettingsStore(instance.settings_path)
        instance._settings_store.load()
        return instance

    def test_save_settings_includes_the_key_only_when_a_geometry_is_set(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_saving_app(directory, "700x640+10+10")
            instance._save_settings()
            data = json.loads((Path(directory) / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(data["advanced_search_geometry"], "700x640+10+10")
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_saving_app(directory, None)
            instance._save_settings()
            data = json.loads((Path(directory) / "settings.json").read_text(encoding="utf-8"))
            self.assertNotIn("advanced_search_geometry", data)

    def test_geometry_callback_stores_the_value_and_saves(self):
        instance = object.__new__(app.LibraryApp)
        instance.advanced_search_geometry = None
        instance._save_settings = Mock()
        instance._advanced_search_geometry_changed("700x640+5+5")
        self.assertEqual(instance.advanced_search_geometry, "700x640+5+5")
        instance._save_settings.assert_called_once_with()


class CacheDefaultTests(unittest.TestCase):
    """Issue #21: the cache field is seeded from the first existing
    per-platform candidate, or left empty when none exists."""

    def make_root(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")

        def destroy_quietly():
            with contextlib.suppress(Exception):
                root.destroy()

        self.addCleanup(destroy_quietly)
        return root

    def construct(self, settings, first_existing):
        root = self.make_root()
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings_path = Path(settings_dir.name) / "settings.json"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        guesser = patch.object(app, "first_existing_directory", return_value=first_existing)
        guesser.start()
        self.addCleanup(guesser.stop)
        return app.LibraryApp(root)

    def test_cache_field_prefills_with_the_first_existing_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "Cache" / "Songs"
            application = self.construct({}, candidate)
            self.assertEqual(application.cache_var.get(), str(candidate))

    def test_cache_field_starts_empty_when_no_candidate_exists(self):
        application = self.construct({}, None)
        self.assertEqual(application.cache_var.get(), "")

    def test_saved_cache_dir_still_wins_over_the_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "Cache" / "Songs"
            application = self.construct({"cache_dir": "/saved/cache"}, candidate)
            self.assertEqual(application.cache_var.get(), "/saved/cache")


class LibrarySnapshotTests(unittest.TestCase):
    @staticmethod
    def make_app(settings_path, cache_dir, stats_file):
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = settings_path
        instance.cache_var = Mock()
        instance.cache_var.get.return_value = str(cache_dir)
        instance.stats_var = Mock()
        instance.stats_var.get.return_value = str(stats_file)
        instance.pack_var = Mock()
        instance.pack_var.get.return_value = "All packs"
        instance.type_var = Mock()
        instance.type_var.get.return_value = "All types"
        instance.diff_var = Mock()
        instance.diff_var.get.return_value = "All difficulties"
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance._loaded = Mock()
        # The snapshot store the delegate reads through (proposal 0008):
        # the path is derived from the settings path, as in __init__.
        instance._snapshot_store = library_data.SnapshotStore(
            instance.library_cache_path, app.HEADERS, library_data.LIBRARY_CACHE_SCHEMA_VERSION)
        instance.course_geometry = None
        instance.advanced_search_geometry = None
        return instance

    @staticmethod
    def sample_row():
        return {key: "" for key in (*app.HEADERS, "Course path")}

    @unittest.skipIf(sys.version_info < (3, 11),
                     "the int-string conversion limit is 3.11+")
    def test_distribution_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache", root / "Stats.xml")
            instance._settings_store = library_data.SettingsStore(root / "settings.json")
            instance._settings_store.load()
            instance.tree = Mock()
            instance.tree.column.return_value = 100
            instance.column_order = list(app.HEADERS)
            instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
            instance.sort_keys = [("Pack", False)]
            instance.show_distribution_panel = Mock(get=Mock(return_value=True))
            instance.distribution_metric = Mock(get=Mock(return_value="Difficulty"))

            instance._save_settings()

            saved = instance._settings_store.load()
            self.assertTrue(saved.get("show_distribution"))
            self.assertEqual(saved.get("distribution_metric"), "Difficulty")

    def test_clear_chart_filter_resets_diff_and_search_directives(self):
        instance = object.__new__(app.LibraryApp)
        instance.diff_var = Mock()
        instance.diff_var.get.return_value = "Challenge"
        instance.search_var = Mock()
        instance.search_var.get.return_value = 'pack:"In The Groove" diff:Challenge meter:10'
        instance.search_entry = Mock()
        instance.refresh_table = Mock()
        instance.pack_var = Mock()
        instance.type_var = Mock()
        instance.scored_var = Mock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.root = Mock()
        instance._filter = app.LibraryFilter(
            instance.search_var, instance.pack_var, instance.type_var,
            instance.diff_var, instance.scored_var,
            instance.search_entry, instance.pack_filter,
            instance.type_filter, instance.diff_filter, instance.root)
        instance._filter.subscribe(instance.refresh_table)
        # The panel component, wired to the app the way _build wires it; the Clear
        # itself is the component's since the split (proposal 0005, step 3).
        panel = object.__new__(dp.DistributionPanel)
        panel.diff_var = instance.diff_var
        panel.search_var = instance.search_var
        panel._apply_chart_filter = instance._filter.apply_chart_filter
        instance.distribution_panel = panel

        panel.clear_chart_filter()

        # Clear removes every chart filter (difficulty and meter here), keeping the pack filter.
        instance.diff_var.set.assert_called_with("All difficulties")
        instance.search_var.set.assert_called_with('pack:"In The Groove"')
        instance.refresh_table.assert_called_once()


class FakeVariable:
    """Stands in for a Tk BooleanVar so column logic can be tested without a window."""

    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ColumnGroupTests(unittest.TestCase):
    @staticmethod
    def make_app(visible_columns):
        instance = object.__new__(app.LibraryApp)
        instance.column_order = list(app.HEADERS)
        instance.column_visibility = {col: FakeVariable(col in visible_columns) for col in app.HEADERS}
        instance.group_visibility = {group: FakeVariable() for group in app.COLUMN_GROUPS}
        instance.default_column_widths = {}
        instance.tree = Mock()
        instance._save_settings = Mock()
        instance._sync_group_checks()
        return instance

    @staticmethod
    def shown(instance):
        return {col for col, var in instance.column_visibility.items() if var.get()}

    def test_every_column_is_in_exactly_one_group(self):
        grouped = [column for columns in app.COLUMN_GROUPS.values() for column in columns]
        self.assertEqual(sorted(grouped), sorted(app.HEADERS))

    def test_groups_are_listed_in_menu_order(self):
        self.assertEqual(list(app.COLUMN_GROUPS),
                         ["Song & chart", "Score", "Tap judgments", "Chart counts", "Tech counts"])

    def test_default_columns_are_song_and_chart_plus_score(self):
        # Issue #49: Subtitle is the one exception — in "Song & chart" but
        # hidden by default, while its group-mates default to shown.
        expected = {*app.COLUMN_GROUPS["Song & chart"], *app.COLUMN_GROUPS["Score"]} - {"Subtitle"}
        self.assertEqual(set(app.DEFAULT_VISIBLE_COLUMNS), expected)
        self.assertNotIn("Subtitle", app.DEFAULT_VISIBLE_COLUMNS)
        self.assertIn("Subtitle", app.COLUMN_GROUPS["Song & chart"])
        self.assertTrue({"Title", "Artist", "Pack"} <= set(app.DEFAULT_VISIBLE_COLUMNS))

    def test_group_check_is_on_only_when_the_whole_group_is_shown(self):
        instance = self.make_app(app.DEFAULT_VISIBLE_COLUMNS)
        self.assertTrue(instance.group_visibility["Score"].get())
        self.assertFalse(instance.group_visibility["Tap judgments"].get())
        instance.column_visibility["Grade"].set(False)
        instance._column_visibility_changed("Grade")
        self.assertFalse(instance.group_visibility["Score"].get())

    def test_group_switch_shows_then_hides_a_whole_group_with_one_save(self):
        instance = self.make_app(app.DEFAULT_VISIBLE_COLUMNS)
        instance.group_visibility["Tap judgments"].set(True)  # what Tk does before calling the command
        instance._group_visibility_changed("Tap judgments")
        self.assertTrue(set(app.TAP_FIELDS) <= self.shown(instance))
        instance.tree.configure.assert_called_once()
        instance._save_settings.assert_called_once()

        instance.group_visibility["Tap judgments"].set(False)
        instance._group_visibility_changed("Tap judgments")
        self.assertFalse(set(app.TAP_FIELDS) & self.shown(instance))
        self.assertEqual(set(instance.tree.configure.call_args.kwargs["displaycolumns"]),
                         set(app.DEFAULT_VISIBLE_COLUMNS))

    def test_group_switch_cannot_hide_the_last_visible_columns(self):
        instance = self.make_app(app.COLUMN_GROUPS["Score"])
        instance.group_visibility["Score"].set(False)
        instance._group_visibility_changed("Score")
        self.assertEqual(self.shown(instance), set(app.COLUMN_GROUPS["Score"]))
        self.assertTrue(instance.group_visibility["Score"].get())
        instance.tree.configure.assert_not_called()
        instance._save_settings.assert_not_called()

    def test_saved_order_without_subtitle_places_it_after_title(self):
        """Issue #49, Finding A: a saved column order from before Subtitle
        existed puts the new column right after Title (mirroring the
        Time/BPM placement), instead of appending it at the far right."""
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        try:
            with tempfile.TemporaryDirectory() as directory:
                settings_path = Path(directory) / "settings.json"
                saved = [col for col in app.HEADERS if col != "Subtitle"]
                settings_path.write_text(json.dumps({"column_order": saved}), encoding="utf-8")
                with patch.object(app.LibraryApp, "_settings_file_path",
                                 staticmethod(lambda: settings_path)):
                    application = app.LibraryApp(root)
                self.assertEqual(application.column_order[0], "Title")
                self.assertEqual(application.column_order[1], "Subtitle")
                self.assertEqual(application.column_order[2:], saved[1:])
        finally:
            root.destroy()

    def test_saved_order_with_subtitle_keeps_its_place(self):
        """A saved order that already places Subtitle is left alone: the
        placement only fills in orders from before the column existed."""
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        try:
            with tempfile.TemporaryDirectory() as directory:
                settings_path = Path(directory) / "settings.json"
                saved = [col for col in app.HEADERS if col != "Subtitle"] + ["Subtitle"]
                settings_path.write_text(json.dumps({"column_order": saved}), encoding="utf-8")
                with patch.object(app.LibraryApp, "_settings_file_path",
                                 staticmethod(lambda: settings_path)):
                    application = app.LibraryApp(root)
                self.assertEqual(application.column_order, saved)
        finally:
            root.destroy()

    def test_reset_column_layout_restores_the_default_columns(self):
        instance = self.make_app(app.HEADERS)
        instance.column_order = list(reversed(app.HEADERS))
        instance.reset_column_layout()
        self.assertEqual(self.shown(instance), set(app.DEFAULT_VISIBLE_COLUMNS))
        self.assertEqual(instance.column_order, list(app.HEADERS))
        self.assertEqual(instance.tree.configure.call_args.kwargs["displaycolumns"],
                         [col for col in app.HEADERS if col in app.DEFAULT_VISIBLE_COLUMNS])
        self.assertFalse(instance.group_visibility["Tech counts"].get())
        # "Song & chart" reads unchecked after a reset: Subtitle belongs to
        # the group but starts hidden (issue #49), so the group is never
        # fully shown by default.
        self.assertFalse(instance.group_visibility["Song & chart"].get())


class ColumnDragTests(unittest.TestCase):
    """Column drag reorder and the displayed-column helpers: which column a
    heading position names, the screen span of a displayed column, and the
    drag that reorders the columns and saves."""

    COLUMNS = ["Title", "Artist", "Pack"]

    @staticmethod
    def make_app():
        instance = object.__new__(app.LibraryApp)
        instance.column_order = list(ColumnDragTests.COLUMNS)
        instance.column_visibility = {
            col: FakeVariable(True) for col in app.HEADERS}
        instance.default_column_widths = {}
        instance.tree = Mock()
        instance.tree.identify_region.return_value = "heading"
        # Each displayed column owns a 100px span: #1 is 0-99, #2 is
        # 100-199, #3 is 200-299.
        instance.tree.identify_column.side_effect = (
            lambda x: "#1" if x < 100 else ("#2" if x < 200 else "#3"))
        instance.tree.winfo_width.return_value = 300
        instance._save_settings = Mock()
        instance._dragged_column = None
        instance._drag_start_x = None
        return instance

    @staticmethod
    def event(x, y=10):
        event = Mock()
        event.x = x
        event.y = y
        return event

    def test_displayed_column_at_returns_the_visible_column(self):
        instance = self.make_app()
        self.assertEqual(instance._displayed_column_at(150, 10), "Artist")

    def test_displayed_column_at_returns_none_outside_the_heading(self):
        instance = self.make_app()
        instance.tree.identify_region.return_value = "cell"
        self.assertIsNone(instance._displayed_column_at(150, 10))

    def test_displayed_column_at_returns_none_for_an_unknown_column_id(self):
        instance = self.make_app()
        instance.tree.identify_column.side_effect = None
        instance.tree.identify_column.return_value = "abc"
        self.assertIsNone(instance._displayed_column_at(150, 10))

    def test_displayed_column_at_returns_none_when_the_index_is_out_of_range(self):
        instance = self.make_app()
        instance.tree.identify_column.side_effect = None
        instance.tree.identify_column.return_value = "#9"
        self.assertIsNone(instance._displayed_column_at(150, 10))

    def test_displayed_column_bounds_span_the_columns_screen_range(self):
        instance = self.make_app()
        self.assertEqual(instance._displayed_column_bounds(0), (0, 100))
        self.assertEqual(instance._displayed_column_bounds(1), (100, 200))
        self.assertEqual(instance._displayed_column_bounds(2), (200, 300))

    def test_displayed_column_bounds_returns_none_with_no_match(self):
        instance = self.make_app()
        instance.tree.identify_column.side_effect = None
        instance.tree.identify_column.return_value = "#9"
        self.assertIsNone(instance._displayed_column_bounds(0))

    def test_drag_start_records_the_column_and_position(self):
        instance = self.make_app()

        instance._column_drag_start(self.event(50))

        self.assertEqual(instance._dragged_column, "Title")
        self.assertEqual(instance._drag_start_x, 50)

    def test_drag_start_outside_the_heading_clears_the_drag(self):
        instance = self.make_app()
        instance.tree.identify_region.return_value = "cell"

        instance._column_drag_start(self.event(50))

        self.assertIsNone(instance._dragged_column)
        self.assertIsNone(instance._drag_start_x)

    def test_drag_end_without_a_drag_does_nothing(self):
        instance = self.make_app()

        result = instance._column_drag_end(self.event(250))

        self.assertIsNone(result)
        instance.tree.configure.assert_not_called()
        instance._save_settings.assert_not_called()

    def test_drag_end_below_the_movement_threshold_does_nothing(self):
        instance = self.make_app()
        instance._dragged_column = "Title"
        instance._drag_start_x = 50

        result = instance._column_drag_end(self.event(53))

        self.assertIsNone(result)
        self.assertEqual(instance.column_order, self.COLUMNS)
        instance._save_settings.assert_not_called()

    def test_drag_end_on_the_same_column_does_nothing(self):
        instance = self.make_app()
        instance._dragged_column = "Title"
        instance._drag_start_x = 50

        result = instance._column_drag_end(self.event(55))

        self.assertIsNone(result)
        self.assertEqual(instance.column_order, self.COLUMNS)
        instance._save_settings.assert_not_called()

    def test_drag_end_on_no_column_does_nothing(self):
        instance = self.make_app()
        instance._dragged_column = "Title"
        instance._drag_start_x = 50
        instance.tree.identify_column.side_effect = None
        instance.tree.identify_column.return_value = "#9"

        result = instance._column_drag_end(self.event(250))

        self.assertIsNone(result)
        self.assertEqual(instance.column_order, self.COLUMNS)
        instance._save_settings.assert_not_called()

    def test_drag_right_past_the_midpoint_moves_the_column_after_its_target(self):
        instance = self.make_app()
        instance._dragged_column = "Title"
        instance._drag_start_x = 50

        result = instance._column_drag_end(self.event(250))

        self.assertEqual(result, "break")
        self.assertEqual(instance.column_order, ["Artist", "Pack", "Title"])
        instance.tree.configure.assert_called_once_with(
            displaycolumns=["Artist", "Pack", "Title"])
        instance._save_settings.assert_called_once()

    def test_drag_right_before_the_midpoint_moves_the_column_before_its_target(self):
        instance = self.make_app()
        instance._dragged_column = "Title"
        instance._drag_start_x = 50

        result = instance._column_drag_end(self.event(210))

        self.assertEqual(result, "break")
        self.assertEqual(instance.column_order, ["Artist", "Title", "Pack"])
        instance.tree.configure.assert_called_once_with(
            displaycolumns=["Artist", "Title", "Pack"])
        instance._save_settings.assert_called_once()

    def test_drag_left_moves_the_column_before_its_target(self):
        instance = self.make_app()
        instance._dragged_column = "Pack"
        instance._drag_start_x = 250

        result = instance._column_drag_end(self.event(50))

        self.assertEqual(result, "break")
        self.assertEqual(instance.column_order, ["Title", "Pack", "Artist"])
        instance.tree.configure.assert_called_once_with(
            displaycolumns=["Title", "Pack", "Artist"])
        instance._save_settings.assert_called_once()


class RowTintTests(unittest.TestCase):
    # The tag rule, the tag setup, and the selection bookkeeping themselves are
    # tested in test_row_tints.py; this class keeps the table-side wiring honest.
    def test_insert_batch_tags_rows_by_difficulty_and_selection(self):
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance._render_generation = 1
        instance.tree_item_rows = {}
        instance.count_label = Mock()
        instance._tree_tint = row_tints.SelectedRowTint(instance.tree)
        instance.root = Mock()
        instance.tree.insert.side_effect = ["item0", "item1", "item2"]
        instance.search_var = _ValueVar("")
        instance._filter = app.LibraryFilter(
            instance.search_var, _ValueVar("All packs"), _ValueVar("All types"),
            _ValueVar("All difficulties"), _ValueVar(False),
            Mock(), Mock(), Mock(), Mock(), instance.root)

        rows = [
            {"Title": "Song A", "Difficulty": "Challenge", "Time": 120},
            {"Title": "Song B", "Difficulty": "Hard", "Time": 90},
            {"Title": "Song C", "Difficulty": "CustomUnknown", "Time": 60},
        ]
        # Song B is pre-selected
        instance._loader = Mock(rows=rows)
        instance._insert_batch(rows, 0, 1, selected_rows={id(rows[1])})

        self.assertEqual(instance.tree.insert.call_count, 3)
        # Song A: unselected Challenge
        args0, kwargs0 = instance.tree.insert.call_args_list[0]
        self.assertEqual(kwargs0.get("tags"), ("diff_Challenge",))
        # Song B: selected Hard has selected_row tag
        args1, kwargs1 = instance.tree.insert.call_args_list[1]
        self.assertEqual(kwargs1.get("tags"), ("diff_Hard", "selected_row"))
        # Song C: a difficulty name that is not in the theme gets the gray unknown tag
        args2, kwargs2 = instance.tree.insert.call_args_list[2]
        self.assertEqual(kwargs2.get("tags"), (row_tints.UNKNOWN_DIFFICULTY_TAG,))
        # Only the pre-selected row is remembered as selected
        self.assertEqual(instance._tree_tint.items, {"item1"})
        instance.tree.selection_add.assert_called_once_with("item1")


class SelectedRowsForCourseTests(unittest.TestCase):
    def test_selected_rows_for_course_returns_rows_in_selection_order_and_skips_unknown_ids(self):
        # The one seam between the table and the course builder: the dialog's queue is
        # fed from here, so a break here would open the dialog empty.
        instance = object.__new__(app.LibraryApp)
        rows = {"item1": {"Title": "A"}, "item2": {"Title": "B"}}
        instance.tree = Mock()
        instance.tree.selection.return_value = ["item2", "gone", "item1"]
        instance.tree_item_rows = rows

        self.assertEqual(instance._selected_rows_for_course(), [rows["item2"], rows["item1"]])


class LibraryRowsForCourseTests(unittest.TestCase):
    def test_library_rows_for_course_returns_the_loaded_rows(self):
        # The course builder's save-time ambiguity check compares its queue against
        # this list, so it must be the app's current rows, not a snapshot copy.
        instance = object.__new__(app.LibraryApp)
        instance._loader = Mock(rows=[{"Title": "A"}, {"Title": "B"}])

        self.assertIs(instance._library_rows_for_course(), instance._loader.rows)

class InsertBatchProgressTests(unittest.TestCase):
    """_insert_batch fills the table in time-boxed batches, and the count
    label tells the truth while it does (startup polish)."""

    @staticmethod
    def make_instance(row_count=3):
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance.tree.insert.side_effect = [f"item{i}" for i in range(row_count)]
        instance._render_generation = 1
        instance.tree_item_rows = {}
        instance.count_label = Mock()
        instance._tree_tint = row_tints.SelectedRowTint(instance.tree)
        instance.root = Mock()
        rows = [{"Title": f"Song {i}", "Difficulty": "Hard", "Time": 60} for i in range(row_count)]
        instance._loader = Mock(rows=rows)
        instance.search_var = _ValueVar("")
        instance._filter = app.LibraryFilter(
            instance.search_var, _ValueVar("All packs"), _ValueVar("All types"),
            _ValueVar("All difficulties"), _ValueVar(False),
            Mock(), Mock(), Mock(), Mock(), instance.root)
        return instance, rows

    def test_a_zero_budget_inserts_one_row_and_reports_progress(self):
        instance, rows = self.make_instance()
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 0):
            instance._insert_batch(rows, 0, 1)
        self.assertEqual(instance.tree.insert.call_count, 1)
        instance.count_label.set.assert_called_once_with("Loading 1 of 3 charts…")
        instance.root.after.assert_called_once()
        # The scheduled continuation finishes the job and sets the final totals.
        continuation = instance.root.after.call_args.args[1]
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()
        self.assertEqual(instance.tree.insert.call_count, 3)
        instance.count_label.set.assert_called_with("3 charts shown · 3 total")

    def test_a_generous_budget_inserts_everything_in_one_batch(self):
        instance, rows = self.make_instance()
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        self.assertEqual(instance.tree.insert.call_count, 3)
        instance.count_label.set.assert_called_once_with("3 charts shown · 3 total")
        instance.root.after.assert_not_called()

    def test_non_finite_time_values_insert_as_blank_instead_of_crashing(self):
        # Issue #123: a snapshot row whose Time is "nan" or "1e999" used to
        # raise inside _insert_batch; now the cell is blank and the batch lands.
        instance, _rows = self.make_instance()
        instance._loader.rows = [
            {"Title": "Song A", "Difficulty": "Hard", "Time": "nan"},
            {"Title": "Song B", "Difficulty": "Hard", "Time": "1e999"},
            {"Title": "Song C", "Difficulty": "Hard", "Time": 120},
        ]
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(instance._loader.rows, 0, 1)
        self.assertEqual(instance.tree.insert.call_count, 3)
        time_index = list(app.HEADERS).index("Time")
        inserted = [kwargs["values"][time_index]
                    for _args, kwargs in instance.tree.insert.call_args_list]
        self.assertEqual(inserted, ["", "", "2:00"])

    def test_count_line_names_an_unreadable_filter_value(self):
        instance, rows = self.make_instance()
        instance.search_var.set("meter:abc")
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        instance.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in meter:abc")

    def test_count_line_names_an_unreadable_grade_value(self):
        instance, rows = self.make_instance()
        instance.search_var.set("grade:banana")
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        instance.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in grade:banana")

    def test_count_line_stays_plain_for_a_readable_filter(self):
        instance, rows = self.make_instance()
        instance.search_var.set("meter:11")
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        instance.count_label.set.assert_called_once_with("3 charts shown · 3 total")


class _ValueVar:
    """A minimal value-carrying stand-in for a Tk variable: get/set over a
    stored string, so tests can preset a value and observe the result."""

    def __init__(self, value, on_set=None):
        self.value = value
        self.on_set = on_set
        self._traces = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        if self.on_set is not None:
            self.on_set()
        for callback in self._traces:
            callback()

    def trace_add(self, mode, callback):
        """Record a write-trace callback, like tk.Variable.trace_add; set() fires it."""
        self._traces.append(callback)
        return f"trace-{len(self._traces)}"


class FilterPersistenceTests(unittest.TestCase):
    """Persisting the Pack/Type/Difficulty dropdowns (proposal 0006):
    the restore rule in _loaded, the saved keys, and the capture of a
    chart-clicked Difficulty by the next save."""

    @staticmethod
    def make_loaded_instance(pack="All packs", type_="All types", difficulty="All difficulties"):
        instance = object.__new__(app.LibraryApp)
        instance.load_button = Mock()
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.search_entry = Mock()
        instance.root = Mock()
        instance.search_var = _ValueVar("")
        instance.pack_var = _ValueVar(pack)
        instance.type_var = _ValueVar(type_)
        instance.diff_var = _ValueVar(difficulty)
        instance.scored_var = _ValueVar(False)
        # The real filter, built from the app's variables the way _build
        # builds it; it installs the variable traces itself.
        instance._filter = app.LibraryFilter(
            instance.search_var, instance.pack_var, instance.type_var,
            instance.diff_var, instance.scored_var,
            instance.search_entry, instance.pack_filter,
            instance.type_filter, instance.diff_filter, instance.root)
        instance._filter.subscribe(instance.refresh_table)
        instance.course_builder = None
        return instance

    @staticmethod
    def rows(*specs):
        return [{"Pack": pack, "Type": type_, "Difficulty": difficulty, "Title": "Song"}
                for pack, type_, difficulty in specs]

    @staticmethod
    def add_save_machinery(instance, settings_path):
        instance.settings_path = settings_path
        instance.cache_var = Mock(get=Mock(return_value="cache"))
        instance.stats_var = Mock(get=Mock(return_value="stats"))
        instance.search_var = _ValueVar("distinctive-search-text")
        instance.tree = Mock()
        instance.tree.column.return_value = 100
        instance.column_order = list(app.HEADERS)
        instance.column_visibility = {column: Mock(get=Mock(return_value=True)) for column in app.HEADERS}
        instance.sort_keys = [("Pack", False)]
        instance.show_distribution_panel = Mock(get=Mock(return_value=False))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.course_geometry = None
        instance.advanced_search_geometry = None
        instance._settings_store = library_data.SettingsStore(instance.settings_path)
        instance._settings_store.load()

    def test_save_settings_writes_the_filter_keys_and_never_search_text(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = self.make_loaded_instance(pack="Pack2", type_="dance-double", difficulty="Hard")
            self.add_save_machinery(instance, settings_path)

            instance._save_settings()

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["filter_pack"], "Pack2")
        self.assertEqual(saved["filter_type"], "dance-double")
        self.assertEqual(saved["filter_difficulty"], "Hard")
        self.assertFalse(any("search" in key for key in saved))
        self.assertNotIn("distinctive-search-text", saved.values())

    def test_a_chart_clicked_difficulty_is_captured_by_the_next_save(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = self.make_loaded_instance()
            self.add_save_machinery(instance, settings_path)

            instance._filter.apply_chart_filter(difficulty="Hard")
            self.assertEqual(instance.diff_var.get(), "Hard")
            # The click alone writes nothing (proposal §3): the value
            # reaches disk only at the next save, here the unrelated one.
            self.assertFalse(settings_path.exists())
            instance._save_settings()

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["filter_difficulty"], "Hard")



class RefreshDeliversRowsTests(unittest.TestCase):
    """refresh_table delivers the filtered rows to the table and the panel:
    the wiring a load (and later set_rows) must preserve, so a forgotten
    refresh leaves the table visibly empty instead of silently stale."""

    @staticmethod
    def make_instance():
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance.tree.insert.side_effect = ["item0", "item1"]
        instance.tree.get_children.return_value = []
        instance._render_generation = 1
        instance.tree_item_rows = {}
        instance.count_label = Mock()
        instance._tree_tint = row_tints.SelectedRowTint(instance.tree)
        instance.root = Mock()
        instance.distribution_panel = Mock()
        instance.search_var = _ValueVar("")
        instance.pack_var = _ValueVar("All packs")
        instance.type_var = _ValueVar("All types")
        instance.diff_var = _ValueVar("All difficulties")
        instance.scored_var = _ValueVar(False)
        instance.search_entry = Mock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.sort_keys = []
        instance._loader = Mock(rows=[
            {"Title": "Song A", "Pack": "Pack1", "Type": "dance-single",
             "Difficulty": "Hard", "Grade": "AAA", "Meter": 10, "Time": 60},
            {"Title": "Song B", "Pack": "Pack2", "Type": "dance-double",
             "Difficulty": "Challenge", "Grade": "", "Meter": 12,
             "Time": 90},
        ])
        instance._filter = app.LibraryFilter(
            instance.search_var, instance.pack_var, instance.type_var,
            instance.diff_var, instance.scored_var,
            instance.search_entry, instance.pack_filter,
            instance.type_filter, instance.diff_filter, instance.root)
        instance._filter.set_rows(instance._loader.rows)
        instance._filter.subscribe(instance.refresh_table)
        return instance

    def test_refresh_table_inserts_the_rows_and_pushes_them_to_the_panel(self):
        instance = self.make_instance()
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance.refresh_table()

        self.assertEqual(instance.tree.insert.call_count, 2)
        title_index = list(app.HEADERS).index("Title")
        inserted = [kwargs["values"][title_index]
                    for _args, kwargs in instance.tree.insert.call_args_list]
        self.assertEqual(inserted, ["Song A", "Song B"])
        instance.distribution_panel.show_rows.assert_called_once_with(
            instance._loader.rows)
        instance.count_label.set.assert_called_once_with(
            "2 charts shown · 2 total")













class _StubStatus:
    """A status line without a window: a str behind get/set, like StringVar."""

    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DiscardedSettingsStatusTests(unittest.TestCase):
    """A settings file that exists but cannot be read is discarded for
    defaults, and the status line must say so once the window is built —
    including after the deferred snapshot load rewrites the status line."""

    def test_report_appends_the_message_once_and_keeps_the_snapshot_line(self):
        instance = object.__new__(app.LibraryApp)
        instance._settings_store = library_data.SettingsStore(Path("settings.json"))
        instance._settings_store.last_read_error = "Expecting value: line 1 column 1 (char 0)"
        instance.status = _StubStatus("Showing saved library snapshot · 3 charts · last refreshed 2026-11-10 08:00.")

        instance._report_discarded_settings()
        instance._report_discarded_settings()  # the build-time and deferred reports must not duplicate it

        self.assertTrue(instance.status.get().startswith("Showing saved library snapshot"))
        self.assertEqual(instance.status.get().count("Settings file could not be read"), 1)
        self.assertIn("using defaults.", instance.status.get())

    def test_report_does_nothing_without_a_recorded_failure(self):
        instance = object.__new__(app.LibraryApp)
        instance._settings_store = library_data.SettingsStore(Path("settings.json"))
        instance.status = _StubStatus("Choose your cache's Songs folder and player Stats.xml, then click Load / refresh.")

        instance._report_discarded_settings()

        self.assertEqual(instance.status.get(),
                         "Choose your cache's Songs folder and player Stats.xml, then click Load / refresh.")


class LiveDiscardedSettingsTests(unittest.TestCase):
    """The same notice in a real window (live Tk; skipped headless)."""

    def make_root(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        self.addCleanup(root.destroy)
        return root

    def make_settings(self, content, binary=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_path = Path(tmp.name) / "settings.json"
        if binary:
            settings_path.write_bytes(content)
        else:
            settings_path.write_text(content, encoding="utf-8")
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        return Path(tmp.name), settings_path

    def pump_until(self, root, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertTrue(predicate(), "timed out waiting for the deferred startup load")

    def test_live_window_reports_corrupt_settings_and_keeps_the_notice(self):
        root = self.make_root()
        self.make_settings("{not json")

        application = app.LibraryApp(root)
        # Visible as soon as the window is built, before the deferred load.
        self.assertIn("Settings file could not be read", application.status.get())
        self.assertIn("using defaults.", application.status.get())
        # And still there once the deferred snapshot load has rewritten the
        # status line (no snapshot file here, so it reports that instead).
        self.pump_until(root, lambda: "No saved library yet." in application.status.get())
        self.assertIn("Settings file could not be read", application.status.get())

    def test_live_window_with_readable_settings_shows_no_notice(self):
        root = self.make_root()
        self.make_settings(json.dumps({"cache_dir": "/cache"}))

        application = app.LibraryApp(root)
        self.pump_until(root, lambda: "No saved library yet." in application.status.get())
        self.assertNotIn("Settings file could not be read", application.status.get())

    def test_live_window_with_a_snapshot_still_reports_discarded_settings(self):
        root = self.make_root()
        settings_dir, settings_path = self.make_settings("{not json")
        # With the settings discarded, the app falls back to its guessed
        # default paths, so the snapshot must be written for those paths
        # to restore — the same paths __init__ derives from the defaults.
        default_cache = app.first_existing_directory(app.cache_dir_candidates())
        cache_dir = str(default_cache) if default_cache is not None else ""
        default_stats = Path.cwd() / "Stats.xml"
        stats_file = str(default_stats) if default_stats.is_file() else ""
        row = {header: "" for header in app.HEADERS}
        row.update({"Title": "Song", "Pack": "P", "Type": "dance-single",
                    "Difficulty": "Hard", "Meter": 10, "Course path": "P/Song"})
        payload = {"schema_version": library_data.LIBRARY_CACHE_SCHEMA_VERSION,
                   "cache_dir": cache_dir, "stats_file": stats_file,
                   "refreshed_at": "2026-11-10T08:00:00-05:00", "files": 1,
                   "skipped_files": 0, "files_without_charts": 0,
                   "nested_song_tree": False, "rows": [dict(row) for _ in range(3)]}
        (settings_dir / "library_cache.json").write_text(json.dumps(payload))

        application = app.LibraryApp(root)
        # The snapshot load owns the status line while it runs.
        self.assertEqual(application.status.get(), "Loading saved library…")
        self.pump_until(root, lambda: len(application.tree.get_children()) >= 3)
        self.assertTrue(application.status.get().startswith("Showing saved library snapshot"))
        self.assertIn("Settings file could not be read", application.status.get())


class LiveStartupSnapshotTests(unittest.TestCase):
    """Startup with a saved snapshot, in a real window: construction returns
    before the snapshot is read; the load lands once the event loop runs."""

    def test_the_snapshot_loads_after_construction_not_during_it(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        self.addCleanup(root.destroy)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name)
        settings_path = settings_dir / "settings.json"
        cache_dir = settings_dir / "Cache"
        stats_file = settings_dir / "Stats.xml"
        stats_file.write_text("<Stats/>")
        settings_path.write_text(json.dumps(
            {"cache_dir": str(cache_dir), "stats_file": str(stats_file)}))
        row = {header: "" for header in app.HEADERS}
        row.update({"Title": "Song", "Pack": "P", "Type": "dance-single",
                    "Difficulty": "Hard", "Meter": 10, "Course path": "P/Song"})
        payload = {"schema_version": library_data.LIBRARY_CACHE_SCHEMA_VERSION,
                   "cache_dir": str(cache_dir), "stats_file": str(stats_file),
                   "refreshed_at": "2026-11-10T08:00:00-05:00", "files": 1,
                   "skipped_files": 0, "files_without_charts": 0,
                   "nested_song_tree": False, "rows": [dict(row) for _ in range(3)]}
        (settings_dir / "library_cache.json").write_text(json.dumps(payload))
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)

        application = app.LibraryApp(root)
        # Nothing has been read yet: the load is scheduled, not done.
        self.assertEqual(application._loader.rows, [])
        self.assertEqual(application.status.get(), "Loading saved library…")
        # Pump the event loop until the deferred load lands and the rows fill in.
        deadline = time.monotonic() + 10
        while len(application.tree.get_children()) < 3 and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertEqual(len(application._loader.rows), 3)
        self.assertTrue(application.status.get().startswith("Showing saved library snapshot"))
        self.assertEqual(len(application.tree.get_children()), 3)

    def test_moved_cache_folder_is_noted_on_the_status_line(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        self.addCleanup(root.destroy)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name)
        settings_path = settings_dir / "settings.json"
        # The cache folder is named in settings and in the snapshot but was
        # never created on disk: ITGmania moved after the snapshot was saved.
        cache_dir = settings_dir / "Cache"
        stats_file = settings_dir / "Stats.xml"
        stats_file.write_text("<Stats/>")
        settings_path.write_text(json.dumps(
            {"cache_dir": str(cache_dir), "stats_file": str(stats_file)}))
        row = {header: "" for header in app.HEADERS}
        row.update({"Title": "Song", "Pack": "P", "Type": "dance-single",
                    "Difficulty": "Hard", "Meter": 10, "Course path": "P/Song"})
        payload = {"schema_version": library_data.LIBRARY_CACHE_SCHEMA_VERSION,
                   "cache_dir": str(cache_dir), "stats_file": str(stats_file),
                   "refreshed_at": "2026-11-10T08:00:00-05:00", "files": 1,
                   "skipped_files": 0, "files_without_charts": 0,
                   "nested_song_tree": False, "rows": [dict(row) for _ in range(3)]}
        (settings_dir / "library_cache.json").write_text(json.dumps(payload))
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)

        application = app.LibraryApp(root)
        deadline = time.monotonic() + 10
        while len(application.tree.get_children()) < 3 and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertEqual(len(application._loader.rows), 3)
        self.assertIn("The saved cache folder no longer exists.", application.status.get())
        self.assertIn("Choose File → Data paths…, then Load / refresh.", application.status.get())


class LiveDataPathsDialogTests(unittest.TestCase):
    """The Data paths dialog in a real window (UI redesign): the paths panel
    is gone from the main window, the dialog is modal and dismissible, the
    first-run popup appears once at startup, Load with invalid paths opens
    the dialog, and the dialog's note tracks paths differing from the snapshot."""

    def make_root(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")

        def destroy_quietly():
            with contextlib.suppress(Exception):
                root.destroy()

        self.addCleanup(destroy_quietly)
        return root

    @staticmethod
    def pump_until(root, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert condition(), "timed out waiting for the condition"

    def make_settings(self, write_settings=True, snapshot_rows=None):
        """A temp settings directory. write_settings writes settings.json
        pointing at its cache and stats paths (nonexistent unless the caller
        creates them); snapshot_rows writes a snapshot payload when given."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name)
        settings_path = settings_dir / "settings.json"
        cache_dir = settings_dir / "Cache"
        stats_file = settings_dir / "Stats.xml"
        stats_file.write_text("<Stats/>")
        if write_settings:
            settings_path.write_text(json.dumps(
                {"cache_dir": str(cache_dir), "stats_file": str(stats_file)}))
        if snapshot_rows is not None:
            payload = {"schema_version": library_data.LIBRARY_CACHE_SCHEMA_VERSION,
                       "cache_dir": str(cache_dir), "stats_file": str(stats_file),
                       "refreshed_at": "2026-11-10T08:00:00-05:00", "files": 1,
                       "skipped_files": 0, "files_without_charts": 0,
                       "nested_song_tree": False, "rows": snapshot_rows}
            (settings_dir / "library_cache.json").write_text(json.dumps(payload))
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        return settings_dir, cache_dir, stats_file

    @staticmethod
    def sample_row(**overrides):
        row = {header: "" for header in app.HEADERS}
        row.update({"Title": "Song", "Pack": "P", "Type": "dance-single",
                    "Difficulty": "Hard", "Meter": 10, "Course path": "P/Song"})
        row.update(overrides)
        return row

    @staticmethod
    def find_button(widget, text):
        for child in widget.winfo_children():
            if isinstance(child, app.tk.Button) and child.cget("text") == text:
                return child
            found = LiveDataPathsDialogTests.find_button(child, text)
            if found is not None:
                return found
        return None

    @staticmethod
    def all_label_texts(widget):
        texts = []
        for child in widget.winfo_children():
            if isinstance(child, app.tk.Label):
                texts.append(child.cget("text"))
            texts.extend(LiveDataPathsDialogTests.all_label_texts(child))
        return texts

    def test_paths_panel_is_gone_from_the_main_window(self):
        root = self.make_root()
        self.make_settings()
        app.LibraryApp(root)
        labels = self.all_label_texts(root)
        self.assertNotIn("Cache / Songs", labels)
        self.assertNotIn("Player Stats.xml", labels)
        self.assertIn("Search", labels)  # the walk itself works

    def test_data_paths_item_is_in_the_file_menu_and_opens_the_dialog(self):
        root = self.make_root()
        self.make_settings()
        application = app.LibraryApp(root)
        menubar = root.nametowidget(root.cget("menu"))
        file_menu = menubar.nametowidget(menubar.entrycget(0, "menu"))
        # Separators have no -label option, so they are skipped.
        labels = [file_menu.entrycget(i, "label") for i in range(file_menu.index("end") + 1)
                  if file_menu.type(i) != "separator"]
        self.assertIn("Data paths…", labels)
        application.open_data_paths_dialog()
        window = application._data_paths_dialog._data_paths_window
        self.assertTrue(window.winfo_exists())
        self.assertEqual(window.title(), "Where is your library?")
        self.find_button(window, "Cancel").invoke()
        self.assertFalse(window.winfo_exists())
        self.assertIsNone(application._data_paths_dialog._data_paths_window)

    def test_dialog_is_modal_and_dismisses_with_escape(self):
        root = self.make_root()
        # Usable paths, so the deferred startup load does not open the
        # first-run popup of its own accord while this test pumps.
        _dir, cache_dir, _stats = self.make_settings()
        cache_dir.mkdir(parents=True)
        application = app.LibraryApp(root)
        application.open_data_paths_dialog()
        window = application._data_paths_dialog._data_paths_window
        self.assertEqual(window.grab_status(), "local")
        # A generated key event needs a mapped window: wait until the dialog
        # is viewable, then send Escape and let it land.
        self.pump_until(root, lambda: window.winfo_viewable())
        window.event_generate("<Escape>", when="now")
        for _ in range(3):
            root.update()
            time.sleep(0.02)
        self.assertFalse(window.winfo_exists())
        self.assertIsNone(application._data_paths_dialog._data_paths_window)

    def test_first_run_popup_opens_at_startup_and_does_not_reappear(self):
        root = self.make_root()
        self.make_settings(write_settings=False)
        application = app.LibraryApp(root)
        self.pump_until(root, lambda: application._data_paths_dialog._data_paths_window is not None
                        and application._data_paths_dialog._data_paths_window.winfo_exists())
        window = application._data_paths_dialog._data_paths_window
        self.assertEqual(application._data_paths_dialog._data_paths_note.cget("text"),
                         dialog.DataPathsDialog._DATA_PATHS_FIRST_RUN_NOTE)
        self.assertIn("No saved library yet.", application.status.get())
        self.find_button(window, "Cancel").invoke()
        self.assertFalse(window.winfo_exists())
        # Pumping on must not bring it back: dismissed once per session.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertIsNone(application._data_paths_dialog._data_paths_window)

    def test_dead_saved_paths_popup_names_the_dead_paths(self):
        root = self.make_root()
        self.make_settings(write_settings=True)  # paths do not exist on disk
        application = app.LibraryApp(root)
        self.pump_until(root, lambda: application._data_paths_dialog._data_paths_window is not None
                        and application._data_paths_dialog._data_paths_window.winfo_exists())
        self.assertEqual(application._data_paths_dialog._data_paths_note.cget("text"),
                         dialog.DataPathsDialog._DATA_PATHS_DEAD_NOTE)
        self.find_button(application._data_paths_dialog._data_paths_window, "Cancel").invoke()

    def test_load_with_invalid_paths_opens_the_dialog(self):
        root = self.make_root()
        self.make_settings(write_settings=True)  # paths do not exist on disk
        application = app.LibraryApp(root)
        # No pumping: the deferred startup load has not run yet, so the
        # dialog here comes from Load, not from the first-run popup.
        application.load_data()
        window = application._data_paths_dialog._data_paths_window
        self.assertTrue(window.winfo_exists())
        self.assertIn("cache folder", application._data_paths_dialog._data_paths_note.cget("text"))
        self.find_button(window, "Cancel").invoke()
        self.assertFalse(window.winfo_exists())

    def test_dialog_load_button_starts_a_scan_with_valid_paths(self):
        root = self.make_root()
        _dir, cache_dir, _stats = self.make_settings(write_settings=True)
        cache_dir.mkdir(parents=True)
        application = app.LibraryApp(root)
        application.open_data_paths_dialog()
        window = application._data_paths_dialog._data_paths_window
        self.find_button(window, "Load library").invoke()
        self.assertFalse(window.winfo_exists())
        self.assertEqual(application.status.get(), "Reading chart cache and player scores…")
        self.assertEqual(str(application.load_button["state"]), "disabled")
        # Wait for the scan to finish before the temp directory is cleaned
        # up: its thread writes the snapshot into that directory. An empty
        # cache reports "No files found", so the button state is the signal.
        self.pump_until(root, lambda: str(application.load_button["state"]) == "normal")

    def test_dialog_note_tracks_paths_differing_from_the_snapshot(self):
        root = self.make_root()
        _dir, cache_dir, _stats = self.make_settings(
            write_settings=True, snapshot_rows=[self.sample_row()])
        application = app.LibraryApp(root)
        self.pump_until(root, lambda: application.status.get().startswith(
            "Showing saved library snapshot"))
        application.open_data_paths_dialog()
        self.assertEqual(application._data_paths_dialog._data_paths_note.cget("text"), "")
        application.cache_var.set("/somewhere/else")
        self.assertEqual(application._data_paths_dialog._data_paths_note.cget("text"),
                         dialog.DataPathsDialog._DATA_PATHS_DIFFER_NOTE)
        application.cache_var.set(str(cache_dir))
        self.assertEqual(application._data_paths_dialog._data_paths_note.cget("text"), "")
        # And when the dialog opens with the paths already moved, the differ
        # note is there from the start, not only after a later edit.
        application.cache_var.set("/somewhere/else")
        self.find_button(application._data_paths_dialog._data_paths_window, "Cancel").invoke()
        application.open_data_paths_dialog()
        self.assertEqual(application._data_paths_dialog._data_paths_note.cget("text"),
                         dialog.DataPathsDialog._DATA_PATHS_DIFFER_NOTE)
        self.find_button(application._data_paths_dialog._data_paths_window, "Cancel").invoke()

    def test_dialog_load_button_with_invalid_paths_stays_open_and_names_them(self):
        root = self.make_root()
        self.make_settings(write_settings=True)  # paths do not exist on disk
        application = app.LibraryApp(root)
        application.open_data_paths_dialog()
        window = application._data_paths_dialog._data_paths_window
        self.find_button(window, "Load library").invoke()
        self.assertTrue(window.winfo_exists())
        # Only the cache is missing here (make_settings writes Stats.xml),
        # so the note names that side alone.
        self.assertIn("cache folder", application._data_paths_dialog._data_paths_note.cget("text"))
        self.assertNotIn("Stats.xml", application._data_paths_dialog._data_paths_note.cget("text"))
        self.find_button(window, "Cancel").invoke()


class LiveFilterPersistenceTests(unittest.TestCase):
    """The persisted filter dropdowns in a real window (proposal 0006):
    seeding at construction, restore on the first load, picks — including
    keyboard picks — saving at once, and the fallback's lazy correction
    surviving a real exit and relaunch. Snapshots are built with the
    app's own snapshot writer, as §6 specifies."""

    def make_root(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")

        def destroy_quietly():
            with contextlib.suppress(Exception):
                root.destroy()

        self.addCleanup(destroy_quietly)
        return root

    @staticmethod
    def pump_until(root, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)

    def prepare_library(self, settings_extra, row_specs):
        """A temp settings directory plus its settings path, with the
        snapshot written by the app's own snapshot writer: a throwaway
        application pointed at the same settings file, never pumped, so
        its own deferred snapshot load never runs."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name)
        settings_path = settings_dir / "settings.json"
        cache_dir = settings_dir / "Cache"
        stats_file = settings_dir / "Stats.xml"
        stats_file.write_text("<Stats/>")
        settings = {"cache_dir": str(cache_dir), "stats_file": str(stats_file)}
        settings.update(settings_extra)
        settings_path.write_text(json.dumps(settings))
        rows = []
        for title, pack, type_, difficulty in row_specs:
            row = {header: "" for header in app.HEADERS}
            row.update({"Title": title, "Pack": pack, "Type": type_,
                        "Difficulty": difficulty, "Meter": 10,
                        "Course path": f"{pack}/{title}"})
            rows.append(row)
        root = self.make_root()
        with patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path)):
            writer = app.LibraryApp(root)
            writer._snapshot_store.write(cache_dir, stats_file, rows, len(rows), 0, 0, False)
        root.destroy()
        return settings_path

    def construct(self, root, settings_path):
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        return app.LibraryApp(root)

    def test_saved_filters_are_seeded_restored_and_applied(self):
        settings_path = self.prepare_library(
            {"filter_pack": "P2", "filter_type": "dance-single", "filter_difficulty": "Challenge"},
            [("One", "P2", "dance-single", "Challenge"),
             ("Two", "P2", "dance-single", "Hard"),
             ("Three", "P1", "dance-single", "Challenge"),
             ("Four", "P2", "dance-double", "Challenge")],
        )
        root = self.make_root()
        application = self.construct(root, settings_path)
        # Seeded at construction, before any load runs.
        self.assertEqual(application.pack_var.get(), "P2")
        self.assertEqual(application.type_var.get(), "dance-single")
        self.assertEqual(application.diff_var.get(), "Challenge")

        self.pump_until(root, lambda: len(application._loader.rows) == 4)
        self.pump_until(root, lambda: len(application.tree.get_children()) >= 1)
        for _ in range(10):
            root.update()

        # All three survived the load, and together they filter the
        # table down to the one row that matches all three.
        self.assertEqual(application.pack_var.get(), "P2")
        self.assertEqual(application.type_var.get(), "dance-single")
        self.assertEqual(application.diff_var.get(), "Challenge")
        self.assertEqual(len(application.tree.get_children()), 1)

    def test_non_string_saved_filters_fall_back_at_startup(self):
        settings_path = self.prepare_library(
            {"filter_pack": 42, "filter_difficulty": ["Hard"]},
            [("One", "P1", "dance-single", "Hard")],
        )
        root = self.make_root()
        application = self.construct(root, settings_path)

        self.assertEqual(application.pack_var.get(), "All packs")
        self.assertEqual(application.diff_var.get(), "All difficulties")

    def test_keyboard_picks_in_each_dropdown_save_at_once(self):
        settings_path = self.prepare_library(
            {},
            [("One", "P1", "dance-single", "Hard"),
             ("Two", "P2", "dance-double", "Challenge")],
        )
        root = self.make_root()
        application = self.construct(root, settings_path)
        self.pump_until(root, lambda: len(application.tree.get_children()) >= 2)

        def pump(turns=5):
            for _ in range(turns):
                root.update()

        for combo, var, key in ((application.pack_filter, application.pack_var, "filter_pack"),
                                (application.type_filter, application.type_var, "filter_type"),
                                (application.diff_filter, application.diff_var, "filter_difficulty")):
            expected = combo.cget("values")[1]
            combo.focus_force()
            root.update()
            # A keyboard selection: Down opens the dropdown (on builds
            # where it instead steps the value directly, the variable
            # has already changed and the remaining keys are unneeded),
            # Down highlights the next value, Return commits it — which
            # is what fires <<ComboboxSelected>>. Each key needs a few
            # event-loop turns for the dropdown's own machinery to
            # settle before the next one lands.
            combo.event_generate("<Down>", when="now")
            pump()
            if var.get() != expected:
                root.event_generate("<Down>", when="now")
                pump()
                root.event_generate("<Return>", when="now")
                pump()
            self.assertEqual(var.get(), expected)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved.get(key), expected)

    def test_a_fallback_survives_exit_and_relaunch_uncorrected(self):
        settings_path = self.prepare_library(
            {"filter_pack": "Ghost Pack"},
            [("One", "P1", "dance-single", "Hard"),
             ("Two", "P1", "dance-double", "Challenge")],
        )
        root = self.make_root()
        application = self.construct(root, settings_path)
        self.pump_until(root, lambda: len(application._loader.rows) == 2)
        # The saved Pack is not in this library: the load falls back.
        self.assertEqual(application.pack_var.get(), "All packs")

        # Exit through the app's real close path with neither dialog
        # ever opened: no save fires, so the stale value stays on disk,
        # exactly as proposal §3 accepted.
        application._close_app()
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved.get("filter_pack"), "Ghost Pack")

        # Relaunch on the same settings: the stale value seeds, the
        # load falls back again, and nothing errors.
        root2 = self.make_root()
        relaunched = self.construct(root2, settings_path)
        self.pump_until(root2, lambda: len(relaunched._loader.rows) == 2)
        self.assertEqual(relaunched.pack_var.get(), "All packs")
        self.assertTrue(relaunched.status.get().startswith("Showing saved library snapshot"))


class LiveFilterWiringTests(unittest.TestCase):
    """The Step 5 wiring guard, live (GLM, PR #167 review): the headless
    guard builds the filter from its own variables, so only a real app
    proves _build wired the filter to the app's variables and the panel
    to the filter."""

    def test_the_filter_and_panel_are_wired_to_the_apps_variables(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        try:
            with tempfile.TemporaryDirectory() as directory:
                settings_path = Path(directory) / "settings.json"
                settings_path.write_text("{}", encoding="utf-8")
                with patch.object(app.LibraryApp, "_settings_file_path",
                                 staticmethod(lambda: settings_path)):
                    application = app.LibraryApp(root)
                self.assertIs(application._filter.search_var,
                              application.search_var)
                self.assertIs(application._filter.pack_var,
                              application.pack_var)
                self.assertIs(application._filter.type_var,
                              application.type_var)
                self.assertIs(application._filter.diff_var,
                              application.diff_var)
                self.assertIs(application._filter.scored_var,
                              application.scored_var)
                self.assertIs(
                    application.distribution_panel._apply_chart_filter.__self__,
                    application._filter)
                self.assertIs(
                    application.distribution_panel._filter_rows.__self__,
                    application._filter)
        finally:
            root.destroy()


class LiveSelectAllTests(unittest.TestCase):
    """Ctrl+A in the results table in a real window (issue #36): the key
    event on the focused tree selects every displayed row, and the
    selection tint follows through the <<TreeviewSelect>> binding."""

    def make_root(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")

        def destroy_quietly():
            with contextlib.suppress(Exception):
                root.destroy()

        self.addCleanup(destroy_quietly)
        return root

    @staticmethod
    def pump_until(root, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)

    def test_ctrl_a_selects_all_displayed_rows_and_tints_them(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name)
        settings_path = settings_dir / "settings.json"
        cache_dir = settings_dir / "Cache"
        stats_file = settings_dir / "Stats.xml"
        stats_file.write_text("<Stats/>")
        settings_path.write_text(json.dumps(
            {"cache_dir": str(cache_dir), "stats_file": str(stats_file)}))
        rows = []
        for title in ("One", "Two", "Three"):
            row = {header: "" for header in app.HEADERS}
            row.update({"Title": title, "Pack": "P", "Type": "dance-single",
                        "Difficulty": "Hard", "Meter": 10,
                        "Course path": f"P/{title}"})
            rows.append(row)
        # The snapshot is written by the app's own writer, from a
        # throwaway application that is never pumped.
        writer_root = self.make_root()
        with patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path)):
            writer = app.LibraryApp(writer_root)
            writer._snapshot_store.write(cache_dir, stats_file, rows, len(rows), 0, 0, False)
        writer_root.destroy()

        root = self.make_root()
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        application = app.LibraryApp(root)
        self.pump_until(root, lambda: len(application.tree.get_children()) == 3)
        children = application.tree.get_children()
        self.assertEqual(len(children), 3)
        self.assertEqual(application.tree.selection(), ())

        application.tree.focus_force()
        for _ in range(5):
            root.update()
        application.tree.event_generate("<Control-a>", when="now")
        # The selection itself lands synchronously in the handler; the
        # tint follows through the <<TreeviewSelect>> event, so pump
        # until the tracker has caught up.
        self.pump_until(root, lambda: application._tree_tint.items == set(children))

        self.assertEqual(set(application.tree.selection()), set(children))
        self.assertEqual(application._tree_tint.items, set(children))


class CourseReloadNotificationTests(unittest.TestCase):
    def _run_loaded(self, course_builder):
        """Run the real _on_library_changed for an empty library on a fake window."""
        instance = object.__new__(app.LibraryApp)
        instance.load_button = Mock()
        instance.progress = Mock()
        instance._filter = MagicMock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.pack_var = Mock()
        instance.type_var = Mock()
        instance.diff_var = Mock()
        instance.status = Mock()
        instance.course_builder = course_builder
        instance._on_library_changed([], preserve_selection=False)

    def test_loaded_tells_the_course_builder_the_library_reloaded(self):
        builder = Mock()
        self._run_loaded(builder)
        builder.on_library_reloaded.assert_called_once_with()

    def test_loaded_without_a_course_builder_still_completes(self):
        self._run_loaded(None)  # the pre-_build state: no builder yet, no error




class LoaderDelegationTests(unittest.TestCase):
    """The app's thin load_data / sync_scores delegation (proposal 0009
    Step 4): the File menu and startup paths call the app, which hands off
    to the loader — the engine methods are not duplicated in LibraryApp."""

    def test_load_data_and_sync_scores_reach_the_loader(self):
        instance = object.__new__(app.LibraryApp)
        instance._loader = Mock()

        instance.load_data()
        instance._loader.load_data.assert_called_once_with()

        instance.sync_scores()
        instance._loader.sync_scores.assert_called_once_with()


class SyncMenuStateTests(unittest.TestCase):
    """The app-side _set_sync_menu_state (it stays in the shell: it touches
    the File menu). The engine half of the sync lives in the loader now."""

    def test_set_sync_menu_state_configures_the_entry(self):
        instance = object.__new__(app.LibraryApp)
        instance._file_menu = Mock()
        instance._set_sync_menu_state("disabled")
        instance._file_menu.entryconfigure.assert_called_once_with(
            "Sync scores from Stats.xml", state="disabled")



class LiveLoadProgressTests(unittest.TestCase):
    """A real scan in a real window: the bar goes determinate, the status
    counts files, and the bar is indeterminate again when the load lands."""

    def test_scan_shows_file_progress_and_restores_the_bar(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        self.addCleanup(root.destroy)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name)
        settings_path = settings_dir / "settings.json"
        cache_dir = settings_dir / "Cache"
        cache_dir.mkdir()
        fixtures = Path(__file__).parent / "fixtures"
        sample = (fixtures / "plain_tune.cache").read_text(encoding="utf-8")
        for index in range(60):
            (cache_dir / f"tune-{index:03}.cache").write_text(sample, encoding="utf-8")
        stats_file = settings_dir / "Stats.xml"
        stats_file.write_text((fixtures / "Stats.xml").read_text(encoding="utf-8"))
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)

        application = app.LibraryApp(root)
        application.cache_var.set(str(cache_dir))
        application.stats_var.set(str(stats_file))
        # Record every status the scan sets, including the ones the poller
        # applies in a single drain between pump turns.
        seen = []
        real_set = application.status.set

        def record(value):
            seen.append(value)
            real_set(value)

        application.status.set = record

        application.load_data()
        deadline = time.monotonic() + 15
        while len(application._loader.rows) == 0 and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertEqual(len(application._loader.rows), 120)  # 60 files, 2 charts each
        # The initial report (0 of 60) and the first loop report (25 of 60)
        # pin the two different progress puts in the worker.
        self.assertIn("Reading chart cache… 0 / 60 files", seen)
        self.assertTrue(any("25 / 60 files" in text for text in seen),
                        f"no loop-report status among: {seen}")
        self.assertTrue(any("about" in text and "s left" in text for text in seen),
                        f"no ETA status among: {seen}")
        self.assertIn("Saving snapshot…", seen)
        self.assertTrue(application.status.get().startswith(
            "Scanned 60 files · parsed 120 charts"))
        # The bar is indeterminate again for the next snapshot restore.
        # ["mode"] is a Tcl index object, so the comparison needs str().
        self.assertEqual(str(application.progress["mode"]), "indeterminate")
        self.assertEqual(application.progress["value"], 0)


class DialogKeyBindingTests(unittest.TestCase):
    # The Advanced Search dialog tests live in tests/test_advanced_search.py,
    # with the component they now test.

    def test_main_escape_clears_search_only_when_no_dialog_is_open(self):
        instance = object.__new__(app.LibraryApp)
        instance._filter = Mock()
        open_window = Mock()
        open_window.winfo_exists.return_value = True
        closed_window = Mock()
        closed_window.winfo_exists.return_value = False

        instance.advanced_search = Mock()
        instance.advanced_search.window = None
        instance.about_window = None
        instance.course_builder = Mock()
        instance.course_builder.window = closed_window
        instance._on_main_escape()
        # No dialog open: Escape clears the search.
        instance._filter.clear_search.assert_called_once()

        instance._filter.clear_search.reset_mock()
        instance.course_builder.window = open_window
        instance._on_main_escape()
        instance._filter.clear_search.assert_not_called()  # Build course open

        instance.course_builder.window = None
        instance.advanced_search.window = open_window
        instance._on_main_escape()
        instance._filter.clear_search.assert_not_called()  # Advanced Search open

        instance.advanced_search.window = None
        instance.about_window = open_window
        instance._on_main_escape()
        instance._filter.clear_search.assert_not_called()  # About open

    def test_select_all_rows_selects_exactly_the_displayed_rows(self):
        # Issue #36's headless pin: the handler selects the tree's
        # current children — the filtered set — in one selection_set.
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance.tree.get_children.return_value = ("row1", "row2", "row3")
        instance._select_all_rows()
        instance.tree.selection_set.assert_called_once_with(("row1", "row2", "row3"))

    def test_live_app_constructs_the_advanced_search_component_with_its_search_variable(self):
        # Proposal 0004's wiring guard: all five constructor inputs are required, so a
        # forgotten one fails loudly at startup; this catches passing the wrong object.
        # The geometry pair (issue #98) is optional, so it is pinned here the same
        # way the course builder's is: a forgotten one would silently disable it.
        if app.tk is None:
            self.skipTest("Tkinter is not installed in this environment")
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            with patch.object(app.LibraryApp, "_settings_file_path", return_value=settings_path), \
                    patch.object(app.LibraryApp, "_valid_advanced_search_geometry",
                                 return_value="700x640+5+5") as mock_valid:
                try:
                    root = app.tk.Tk()
                except app.tk.TclError:
                    self.skipTest("Tk cannot open a display in this environment")
                try:
                    root.withdraw()
                    application = app.LibraryApp(root)
                    self.assertIsNotNone(application.advanced_search)
                    self.assertIs(application.advanced_search._search_var, application.search_var)
                    mock_valid.assert_called_once_with(None)
                    self.assertEqual(application.advanced_search._saved_geometry, "700x640+5+5")
                    self.assertEqual(application.advanced_search._report_geometry,
                                     application._advanced_search_geometry_changed)
                finally:
                    root.destroy()


class AboutDialogTests(unittest.TestCase):
    @staticmethod
    def open_about_with_mocks(about_window=None):
        instance = object.__new__(app.LibraryApp)
        instance.root = Mock()
        instance.about_window = about_window
        instance._button = Mock(return_value=Mock())
        mock_window = Mock()
        bindings = {}
        mock_window.bind.side_effect = lambda seq, func: bindings.__setitem__(seq, func)
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        with patch.object(app, "tk", mock_tk):
            instance.open_about()
        return instance, mock_tk, mock_window, bindings

    def test_about_shows_the_name_and_the_version_from_one_place(self):
        _instance, mock_tk, _window, _bindings = self.open_about_with_mocks()
        shown = [call.kwargs.get("text") for call in mock_tk.Label.call_args_list]
        self.assertIn("ITGmania Library Visualizer", shown)
        self.assertIn(f"Version {app.__version__}", shown)

    def test_about_closes_on_escape_and_return_and_stops_the_key_event(self):
        _instance, _tk, window, bindings = self.open_about_with_mocks()
        for key in ("<Escape>", "<Return>"):
            window.destroy.reset_mock()
            self.assertEqual(bindings[key](), "break")
            window.destroy.assert_called_once()

    def test_about_takes_keyboard_focus_so_escape_reaches_it(self):
        _instance, _tk, window, _bindings = self.open_about_with_mocks()
        window.focus_force.assert_called_once()

    def test_about_opened_twice_raises_the_open_window_instead_of_a_second_one(self):
        existing = Mock()
        existing.winfo_exists.return_value = True
        _instance, mock_tk, _window, _bindings = self.open_about_with_mocks(about_window=existing)
        existing.lift.assert_called_once()
        existing.focus_force.assert_called_once()  # raised from behind the main window: it gets the keys too
        mock_tk.Toplevel.assert_not_called()


class VersionStringTests(unittest.TestCase):
    def test_version_matches_the_newest_changelog_heading(self):
        changelog = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
        match = re.search(r"^## (\d+\.\d+\.\d+)\b", changelog, re.MULTILINE)
        self.assertIsNotNone(match, "CHANGELOG.md has no '## x.y.z' heading")
        self.assertEqual(app.__version__, match.group(1))


class PerformanceAndExportTests(unittest.TestCase):
    def test_save_settings_skips_disk_write_when_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = object.__new__(app.LibraryApp)
            instance.settings_path = settings_path
            instance.tree = Mock()
            instance.cache_var = Mock(get=Mock(return_value="/cache"))
            instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
            instance.column_order = list(app.HEADERS)
            instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
            instance.tree.column.return_value = 100
            instance.sort_keys = [("Pack", False)]
            instance.show_distribution_panel = Mock(get=Mock(return_value=False))
            instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
            instance.pack_var = Mock(get=Mock(return_value="All packs"))
            instance.type_var = Mock(get=Mock(return_value="All types"))
            instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
            instance.course_geometry = None
            instance.advanced_search_geometry = None
            instance._settings_store = library_data.SettingsStore(settings_path)
            instance._settings_store.load()

            # First save writes to disk
            instance._save_settings()
            self.assertTrue(settings_path.is_file())
            first_mtime = settings_path.stat().st_mtime_ns

            # Second save with no changes (e.g. routine table row click) skips write
            with patch("json.dumps") as mock_dumps:
                instance._save_settings()
                mock_dumps.assert_not_called()
            self.assertEqual(settings_path.stat().st_mtime_ns, first_mtime)

            # Changing a column width causes it to save
            instance.tree.column.return_value = 150
            instance._save_settings()
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["column_widths"]["Pack"], 150)

    def test_failed_settings_save_leaves_no_temp_file(self):
        # Proposal 0008 §6 step 1: a failed settings dump leaves no
        # settings.tmp behind. The failure is forced inside os.replace —
        # the dump and the replace are the two failure points, and the
        # replace is the one that survives the move to the store, whose
        # save serializes with json.dumps instead of json.dump.
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = object.__new__(app.LibraryApp)
            instance.settings_path = settings_path
            instance.tree = Mock()
            instance.cache_var = Mock(get=Mock(return_value="/cache"))
            instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
            instance.column_order = list(app.HEADERS)
            instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
            instance.tree.column.return_value = 100
            instance.sort_keys = [("Pack", False)]
            instance.show_distribution_panel = Mock(get=Mock(return_value=False))
            instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
            instance.pack_var = Mock(get=Mock(return_value="All packs"))
            instance.type_var = Mock(get=Mock(return_value="All types"))
            instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
            instance.course_geometry = None
            instance.advanced_search_geometry = None
            instance._settings_store = library_data.SettingsStore(settings_path)
            instance._settings_store.load()
            instance.status = Mock()

            with patch("os.replace", side_effect=OSError("locked")):
                instance._save_settings()

            self.assertEqual([p for p in Path(directory).iterdir()
                              if p.name.endswith(".tmp")], [])
            self.assertIn("Could not save settings", instance.status.set.call_args.args[0])

    def test_save_settings_persists_in_place_column_reorder_after_earlier_save(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = object.__new__(app.LibraryApp)
            instance.settings_path = settings_path
            instance.tree = Mock()
            instance.cache_var = Mock(get=Mock(return_value="/cache"))
            instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
            instance.column_order = list(app.HEADERS)
            instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
            instance.tree.column.return_value = 100
            instance.sort_keys = [("Pack", False)]
            instance.show_distribution_panel = Mock(get=Mock(return_value=False))
            instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
            instance.pack_var = Mock(get=Mock(return_value="All packs"))
            instance.type_var = Mock(get=Mock(return_value="All types"))
            instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
            instance.course_geometry = None
            instance.advanced_search_geometry = None
            instance._settings_store = library_data.SettingsStore(settings_path)
            instance._settings_store.load()

            # An earlier save in the session (any routine click) populates the dedup snapshot.
            instance._save_settings()
            self.assertTrue(settings_path.is_file())
            self.assertNotEqual(json.loads(settings_path.read_text(encoding="utf-8"))["column_order"][0], "Meter")

            # The column drag handler mutates column_order in place (remove/insert) and then saves;
            # the new order must reach disk even though nothing was reassigned.
            instance.column_order.remove("Meter")
            instance.column_order.insert(0, "Meter")
            instance._save_settings()

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["column_order"], instance.column_order)
            self.assertEqual(data["column_order"][0], "Meter")

    def test_export_csv_handles_unwritable_file_error(self):
        instance = object.__new__(app.LibraryApp)
        instance._loader = Mock(rows=[{"Title": "Test Song", "Artist": "Artist"}])
        instance.status = Mock()

        mock_filedialog = Mock(asksaveasfilename=Mock(return_value="/unwritable/path/library.csv"))
        mock_messagebox = Mock()

        with patch.object(app, "filedialog", mock_filedialog), \
             patch.object(app, "messagebox", mock_messagebox), \
             patch("builtins.open", side_effect=PermissionError("Access denied")):
            instance.export_csv()

        mock_messagebox.showerror.assert_called_once()
        self.assertEqual(mock_messagebox.showerror.call_args[0][0], "Export failed")
        self.assertIn("Access denied", mock_messagebox.showerror.call_args[0][1])
        self.assertIn("Could not export CSV", instance.status.set.call_args[0][0])

    def test_export_csv_successful_write(self):
        with tempfile.TemporaryDirectory() as directory:
            out_file = Path(directory) / "export.csv"
            instance = object.__new__(app.LibraryApp)
            instance._loader = Mock(rows=[{"Title": "My Song", "Pack": "My Pack",
                                          "Subtitle": "(Sunset Mix)"}])
            instance.status = Mock()

            mock_filedialog = Mock(asksaveasfilename=Mock(return_value=str(out_file)))
            mock_messagebox = Mock()

            with patch.object(app, "filedialog", mock_filedialog), \
                 patch.object(app, "messagebox", mock_messagebox):
                instance.export_csv()

            mock_messagebox.showerror.assert_not_called()
            self.assertTrue(out_file.is_file())
            content = out_file.read_text(encoding="utf-8-sig")
            self.assertIn("My Song", content)
            self.assertIn("My Pack", content)
            self.assertIn("Subtitle", content)
            self.assertIn("(Sunset Mix)", content)
            self.assertIn("Exported 1 charts", instance.status.set.call_args[0][0])


class RebindingHazardTests(unittest.TestCase):
    """The sort/column rebinding hazard (proposal 0009, Claude's review):
    sort_by rebinds self.sort_keys and reset_column_layout rebinds
    self.column_order, so the state _save_settings persists must be the
    table's own state after the gesture — a shared-input design would go
    stale here. These pins say what reaches disk."""

    @staticmethod
    def make_save_instance(settings_path):
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = settings_path
        instance.tree = Mock()
        instance.tree.column.return_value = 100
        instance.cache_var = Mock(get=Mock(return_value="/cache"))
        instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
        instance.column_order = list(app.HEADERS)
        instance.column_visibility = {
            col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
        instance.group_visibility = {
            group: FakeVariable() for group in app.COLUMN_GROUPS}
        instance.default_column_widths = {
            col: 100 for col in app.HEADERS}
        instance.sort_keys = [("Pack", False)]
        instance.show_distribution_panel = Mock(
            get=Mock(return_value=False))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.pack_var = Mock(get=Mock(return_value="All packs"))
        instance.type_var = Mock(get=Mock(return_value="All types"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.course_geometry = None
        instance.advanced_search_geometry = None
        instance._settings_store = library_data.SettingsStore(settings_path)
        instance._settings_store.load()
        instance.status = Mock()
        return instance

    @staticmethod
    def saved(settings_path):
        return json.loads(settings_path.read_text(encoding="utf-8"))

    def test_sort_by_a_new_column_persists_the_new_sort(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = self.make_save_instance(settings_path)
            instance.refresh_table = Mock()

            instance.sort_by("Title")

            instance.refresh_table.assert_called_once_with(
                preserve_selection=True)
            self.assertEqual(self.saved(settings_path)["sort_keys"],
                             [["Title", False]])

    def test_sort_by_the_current_first_column_toggles_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = self.make_save_instance(settings_path)
            instance.sort_keys = [("Title", False)]
            instance.refresh_table = Mock()

            instance.sort_by("Title")

            self.assertEqual(self.saved(settings_path)["sort_keys"],
                             [["Title", True]])

    def test_reset_column_layout_persists_the_restored_order(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance = self.make_save_instance(settings_path)
            instance.column_order = list(reversed(app.HEADERS))

            instance.reset_column_layout()

            self.assertEqual(self.saved(settings_path)["column_order"],
                             list(app.HEADERS))


class LibraryAppExitTests(unittest.TestCase):
    """Issue #87: File → Exit and the main window's X share one exit path that
    asks the course builder before destroying the root."""

    @staticmethod
    def make_app(builder_answer=None):
        instance = object.__new__(app.LibraryApp)
        instance.root = Mock()
        instance.advanced_search = None
        if builder_answer is None:
            instance.course_builder = None
        else:
            instance.course_builder = Mock()
            instance.course_builder.confirm_discard_for_app_exit.return_value = builder_answer
        return instance

    def test_exit_destroys_the_root_when_there_is_no_course_builder(self):
        instance = self.make_app()
        instance._close_app()
        instance.root.destroy.assert_called_once_with()

    def test_exit_destroys_the_root_when_the_builder_agrees(self):
        instance = self.make_app(builder_answer=True)
        instance._close_app()
        instance.course_builder.confirm_discard_for_app_exit.assert_called_once_with()
        instance.root.destroy.assert_called_once_with()

    def test_exit_is_cancelled_when_the_builder_says_no(self):
        instance = self.make_app(builder_answer=False)
        instance._close_app()
        instance.root.destroy.assert_not_called()

    def test_exit_saves_the_advanced_search_geometry(self):
        instance = self.make_app()
        instance.advanced_search = Mock()
        instance._close_app()
        instance.advanced_search.save_window_geometry.assert_called_once_with()
        instance.root.destroy.assert_called_once_with()


class LiveDpiScaleTests(unittest.TestCase):
    """DPI awareness (issue #51) in a real window: the factor comes from the
    display, and the window, its minimum size, and its column widths are the
    canonical theme values scaled by it."""

    def test_the_window_opens_at_the_scaled_default_geometry(self):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings_path = Path(settings_dir.name) / "settings.json"
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            application = app.LibraryApp(root)
            # Let the geometry manager settle the requested size before
            # reading it back: an unmapped window still reports 1x1.
            root.update_idletasks()
            factor = application._dpi_scale
            self.assertEqual(factor, library_data.dpi_scale_factor(root.winfo_fpixels("1i")))
            self.assertGreater(factor, 0)
            # The exact window size is not asserted here: the window
            # manager clamps it to the screen (the Windows runner's
            # display is ~1024 wide, so 1500x850 comes back smaller).
            # The requested size is covered exactly by the geometry unit
            # tests; the factor reaching the real window is shown by the
            # minimum size and the column width below.
            self.assertEqual(root.minsize(),
                             (library_data.scale_pixels(theme.WINDOW_MIN_SIZE[0], factor),
                              library_data.scale_pixels(theme.WINDOW_MIN_SIZE[1], factor)))
            self.assertEqual(application.tree.column("Title", "width"),
                             library_data.scale_pixels(130, factor))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
