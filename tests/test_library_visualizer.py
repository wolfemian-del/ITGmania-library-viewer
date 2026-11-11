import contextlib
import json
import queue
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import distribution_panel as dp
import library_visualizer as app
import row_tints


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
        instance._last_saved_settings = None
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
        instance._last_saved_settings = None
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
        instance.course_geometry = None
        instance.advanced_search_geometry = None
        instance._last_saved_settings = None
        return instance

    @staticmethod
    def sample_row():
        return {key: "" for key in (*app.HEADERS, "Course path")}

    def test_snapshot_restores_when_source_paths_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            rows = [self.sample_row()]
            instance._save_library_cache(cache_dir, stats_file, rows, 1, 0, 0, False)

            instance.load_cached_data()

        instance._loaded.assert_called_once()
        args, kwargs = instance._loaded.call_args
        self.assertEqual(args[0], rows)
        self.assertTrue(kwargs["from_cache"])
        self.assertEqual(kwargs["source_paths"], (str(cache_dir), str(stats_file)))

    def test_snapshot_is_not_restored_for_different_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "CacheB", root / "Stats.xml")
            instance._save_library_cache(
                root / "CacheA", root / "Stats.xml", [self.sample_row()], 1, 0, 0, False)

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("different data paths", instance.status.set.call_args.args[0])

    def test_snapshot_with_invalid_utf8_reports_could_not_be_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache" / "Songs", root / "Stats.xml")
            instance.library_cache_path.write_bytes(b"\xff\xfe not utf-8")

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("could not be read", instance.status.set.call_args.args[0])

    def test_snapshot_is_not_restored_with_an_unsupported_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache", root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._save_library_cache(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            with instance.library_cache_path.open("r+", encoding="utf-8") as handle:
                payload = app.json.load(handle)
                payload["schema_version"] = app.LIBRARY_CACHE_SCHEMA_VERSION + 1
                handle.seek(0)
                app.json.dump(payload, handle)
                handle.truncate()

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        self.assertIn("invalid or outdated", instance.status.set.call_args.args[0])

    def test_distribution_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache", root / "Stats.xml")
            instance.tree = Mock()
            instance.tree.column.return_value = 100
            instance.column_order = list(app.HEADERS)
            instance.column_visibility = {col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
            instance.sort_keys = [("Pack", False)]
            instance.show_distribution_panel = Mock(get=Mock(return_value=True))
            instance.distribution_metric = Mock(get=Mock(return_value="Difficulty"))

            instance._save_settings()

            saved = instance._read_settings()
            self.assertTrue(saved.get("show_distribution"))
            self.assertEqual(saved.get("distribution_metric"), "Difficulty")

    def test_settings_with_invalid_utf8_returns_empty_dict(self):
        # A mis-encoded hand-edited settings.json must not crash startup:
        # _read_settings runs in __init__, so an uncaught decode error
        # would kill the app before the window appears. Same gap PR #116
        # closed for the snapshot reader (load_cached_data).
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache", root / "Stats.xml")
            instance.settings_path.write_bytes(b"\xff\xfe not utf-8")

            self.assertEqual(instance._read_settings(), {})

    def test_clear_chart_filter_resets_diff_and_search_directives(self):
        instance = object.__new__(app.LibraryApp)
        instance.diff_var = Mock()
        instance.diff_var.get.return_value = "Challenge"
        instance.search_var = Mock()
        instance.search_var.get.return_value = 'pack:"In The Groove" diff:Challenge meter:10'
        instance.search_entry = Mock()
        instance.refresh_table = Mock()
        # The panel component, wired to the app the way _build wires it; the Clear
        # itself is the component's since the split (proposal 0005, step 3).
        panel = object.__new__(dp.DistributionPanel)
        panel.diff_var = instance.diff_var
        panel.search_var = instance.search_var
        panel._apply_chart_filter = instance.apply_chart_filter
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
        expected = {*app.COLUMN_GROUPS["Song & chart"], *app.COLUMN_GROUPS["Score"]}
        self.assertEqual(set(app.DEFAULT_VISIBLE_COLUMNS), expected)

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

    def test_reset_column_layout_restores_the_default_columns(self):
        instance = self.make_app(app.HEADERS)
        instance.column_order = list(reversed(app.HEADERS))
        instance.reset_column_layout()
        self.assertEqual(self.shown(instance), set(app.DEFAULT_VISIBLE_COLUMNS))
        self.assertEqual(instance.column_order, list(app.HEADERS))
        self.assertEqual(instance.tree.configure.call_args.kwargs["displaycolumns"],
                         [col for col in app.HEADERS if col in app.DEFAULT_VISIBLE_COLUMNS])
        self.assertFalse(instance.group_visibility["Tech counts"].get())
        self.assertTrue(instance.group_visibility["Song & chart"].get())


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

        rows = [
            {"Title": "Song A", "Difficulty": "Challenge", "Time": 120},
            {"Title": "Song B", "Difficulty": "Hard", "Time": 90},
            {"Title": "Song C", "Difficulty": "CustomUnknown", "Time": 60},
        ]
        # Song B is pre-selected
        instance.rows = rows
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
        instance.rows = [{"Title": "A"}, {"Title": "B"}]

        self.assertIs(instance._library_rows_for_course(), instance.rows)

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
        instance.rows = rows
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


class _ValueVar:
    """A minimal value-carrying stand-in for a Tk variable: get/set over a
    stored string, so tests can preset a value and observe the result."""

    def __init__(self, value, on_set=None):
        self.value = value
        self.on_set = on_set

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        if self.on_set is not None:
            self.on_set()


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
        instance._batched_filter_changes = app.LibraryApp._batched_filter_changes.__get__(instance)
        instance._batching_filter_changes = False
        instance._refresh_unless_batching = app.LibraryApp._refresh_unless_batching.__get__(instance)
        # Tk would run the write traces on each set; simulate them the way
        # the long-standing _loaded pinning test does.
        instance.pack_var = _ValueVar(pack, on_set=instance._refresh_unless_batching)
        instance.type_var = _ValueVar(type_, on_set=instance._refresh_unless_batching)
        instance.diff_var = _ValueVar(difficulty, on_set=instance._refresh_unless_batching)
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
        instance._last_saved_settings = None

    def test_loaded_keeps_values_that_are_in_the_new_library(self):
        instance = self.make_loaded_instance(pack="Pack2", type_="dance-single", difficulty="Challenge")
        rows = self.rows(("Pack1", "dance-single", "Hard"), ("Pack2", "dance-double", "Challenge"))

        instance._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        self.assertEqual(instance.pack_var.get(), "Pack2")
        self.assertEqual(instance.type_var.get(), "dance-single")
        self.assertEqual(instance.diff_var.get(), "Challenge")
        instance.refresh_table.assert_called_once()

    def test_loaded_falls_back_for_values_missing_from_the_new_library(self):
        instance = self.make_loaded_instance(pack="Gone", type_="gone-type", difficulty="Gone")
        rows = self.rows(("Pack1", "dance-single", "Hard"))

        instance._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        self.assertEqual(instance.pack_var.get(), "All packs")
        self.assertEqual(instance.type_var.get(), "All types")
        self.assertEqual(instance.diff_var.get(), "All difficulties")
        instance.refresh_table.assert_called_once()

    def test_successive_loads_keep_a_selection_then_fall_back(self):
        instance = self.make_loaded_instance()
        first = self.rows(("Pack1", "dance-single", "Hard"), ("Pack2", "dance-single", "Hard"))
        instance._loaded(first, len(first), from_cache=True, refreshed_at="2026-01-01T00:00:00")
        instance.pack_var.set("Pack2")

        second = self.rows(("Pack2", "dance-single", "Hard"), ("Pack3", "dance-single", "Hard"))
        instance._loaded(second, len(second), from_cache=True, refreshed_at="2026-01-01T00:00:00")
        self.assertEqual(instance.pack_var.get(), "Pack2")

        third = self.rows(("Pack3", "dance-single", "Hard"))
        instance._loaded(third, len(third), from_cache=True, refreshed_at="2026-01-01T00:00:00")
        self.assertEqual(instance.pack_var.get(), "All packs")

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
            instance.search_entry = Mock()

            instance.apply_chart_filter(difficulty="Hard")
            self.assertEqual(instance.diff_var.get(), "Hard")
            # The click alone writes nothing (proposal §3): the value
            # reaches disk only at the next save, here the unrelated one.
            self.assertFalse(settings_path.exists())
            instance._save_settings()

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["filter_difficulty"], "Hard")

    def test_fallback_replaces_the_stored_value_on_the_next_save(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            settings_path.write_text(json.dumps({"filter_pack": "Gone Pack"}), encoding="utf-8")
            instance = self.make_loaded_instance()
            # Seed the variable from the real settings file through the
            # real reader, the way __init__ seeds it at startup.
            instance.settings_path = settings_path
            seeded = instance._read_settings()
            instance.pack_var = _ValueVar(seeded.get("filter_pack", "All packs"),
                                          on_set=instance._refresh_unless_batching)
            rows = self.rows(("Pack1", "dance-single", "Hard"))
            instance._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")
            self.assertEqual(instance.pack_var.get(), "All packs")
            self.add_save_machinery(instance, settings_path)

            instance._save_settings()

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["filter_pack"], "All packs")

    def test_seeded_value_survives_a_startup_that_never_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_loaded_instance(type_="dance-double")
            instance.settings_path = Path(directory) / "settings.json"
            instance._loaded = Mock()

            instance.load_cached_data()

            instance._loaded.assert_not_called()
            self.assertEqual(instance.type_var.get(), "dance-double")
            instance.refresh_table.assert_called_once()


class InitialSnapshotTests(unittest.TestCase):
    """The deferred startup load (startup polish): _load_initial_snapshot is
    the after() callback __init__ schedules so the window paints first."""

    @staticmethod
    def make_instance():
        instance = object.__new__(app.LibraryApp)
        instance.progress = Mock()
        instance.load_cached_data = Mock()
        instance._load_generation = 0
        return instance

    def test_it_loads_and_stops_the_progress_bar(self):
        instance = self.make_instance()
        instance._load_initial_snapshot()
        instance.load_cached_data.assert_called_once_with()
        instance.progress.stop.assert_called_once_with()

    def test_it_does_nothing_when_a_user_scan_has_already_started(self):
        instance = self.make_instance()
        instance._load_generation = 1
        instance._load_initial_snapshot()
        instance.load_cached_data.assert_not_called()
        instance.progress.stop.assert_not_called()

    def test_it_stops_the_progress_bar_even_when_loading_fails(self):
        instance = self.make_instance()
        instance.load_cached_data.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            instance._load_initial_snapshot()
        instance.progress.stop.assert_called_once_with()


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
        payload = {"schema_version": app.LIBRARY_CACHE_SCHEMA_VERSION,
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
        self.assertEqual(application.rows, [])
        self.assertEqual(application.status.get(), "Loading saved library…")
        # Pump the event loop until the deferred load lands and the rows fill in.
        deadline = time.monotonic() + 10
        while len(application.tree.get_children()) < 3 and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertEqual(len(application.rows), 3)
        self.assertTrue(application.status.get().startswith("Showing saved library snapshot"))
        self.assertEqual(len(application.tree.get_children()), 3)


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
            writer._save_library_cache(cache_dir, stats_file, rows, len(rows), 0, 0, False)
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

        self.pump_until(root, lambda: len(application.rows) == 4)
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
        self.pump_until(root, lambda: len(application.rows) == 2)
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
        self.pump_until(root2, lambda: len(relaunched.rows) == 2)
        self.assertEqual(relaunched.pack_var.get(), "All packs")
        self.assertTrue(relaunched.status.get().startswith("Showing saved library snapshot"))


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
            writer._save_library_cache(cache_dir, stats_file, rows, len(rows), 0, 0, False)
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
        """Run the real _loaded for an empty library on a fake window."""
        instance = object.__new__(app.LibraryApp)
        instance.load_button = Mock()
        instance.progress = Mock()
        instance._batched_filter_changes = MagicMock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.pack_var = Mock()
        instance.type_var = Mock()
        instance.diff_var = Mock()
        instance.status = Mock()
        instance.course_builder = course_builder
        instance._loaded([], 0)

    def test_loaded_tells_the_course_builder_the_library_reloaded(self):
        builder = Mock()
        self._run_loaded(builder)
        builder.on_library_reloaded.assert_called_once_with()

    def test_loaded_without_a_course_builder_still_completes(self):
        self._run_loaded(None)  # the pre-_build state: no builder yet, no error


class RefreshGenerationTests(unittest.TestCase):
    def test_load_worker_ignores_superseded_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            (cache_dir / "test.cache").write_text("#SONGFILENAME:Songs/P/S/a.ogg;\n#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n", encoding="utf-8")
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(app.LibraryApp)
            instance._load_generation = 2
            instance._load_results = queue.Queue()
            instance._save_library_cache = Mock()
            instance.root = Mock()

            # Run worker with stale generation 1
            instance._load_worker(cache_dir, stats_file, generation=1)

            instance._save_library_cache.assert_not_called()
            instance.root.after.assert_not_called()
            self.assertTrue(instance._load_results.empty())

    def test_load_worker_superseded_after_scan_does_not_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            (cache_dir / "test.cache").write_text("#SONGFILENAME:Songs/P/S/a.ogg;\n", encoding="utf-8")
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(app.LibraryApp)
            instance._load_generation = 1
            instance._snapshot_lock = threading.Lock()
            instance._load_results = queue.Queue()
            instance._save_library_cache = Mock()
            instance.root = Mock()

            def newer_refresh_starts_while_parsing(path, scores):
                instance._load_generation = 2  # the only file is parsed, so the scan loop will not notice
                return []

            with patch.object(app, "parse_cache_file", newer_refresh_starts_while_parsing):
                instance._load_worker(cache_dir, stats_file, generation=1)

            instance._save_library_cache.assert_not_called()
            instance.root.after.assert_not_called()
            self.assertTrue(instance._load_results.empty())

    def test_older_scan_cannot_overwrite_newer_snapshot(self):
        sample = "#SONGFILENAME:Songs/P/S/a.ogg;\n#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_folder, new_folder = root / "old_folder", root / "new_folder"
            for folder in (old_folder, new_folder):
                folder.mkdir()
                (folder / "a.cache").write_text(sample, encoding="utf-8")
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(app.LibraryApp)
            instance.settings_path = root / "settings.json"
            instance._load_generation = 1
            instance._snapshot_lock = threading.Lock()
            instance._load_results = queue.Queue()
            instance.root = Mock()

            real_save = app.LibraryApp._save_library_cache
            old_is_saving, new_has_saved = threading.Event(), threading.Event()

            def slow_save_for_old_folder(cache_dir, *args):
                if Path(cache_dir) == old_folder:
                    old_is_saving.set()
                    new_has_saved.wait(0.3)  # long enough for an unlocked newer scan to finish first
                refreshed_at = real_save(instance, cache_dir, *args)
                if Path(cache_dir) == new_folder:
                    new_has_saved.set()
                return refreshed_at

            instance._save_library_cache = slow_save_for_old_folder
            old_scan = threading.Thread(target=instance._load_worker, args=(old_folder, stats_file, 1))
            old_scan.start()
            self.assertTrue(old_is_saving.wait(5))
            instance._load_generation = 2  # a newer Load / refresh is requested during the old save
            new_scan = threading.Thread(target=instance._load_worker, args=(new_folder, stats_file, 2))
            new_scan.start()
            old_scan.join(5)
            new_scan.join(5)

            snapshot = json.loads((root / "library_cache.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(snapshot["cache_dir"]), new_folder)

            # Both scans queued their results for the main thread (the older
            # one's delivery is dropped by _loaded's generation check).
            queued = []
            while not instance._load_results.empty():
                kind, _, kwargs = instance._load_results.get_nowait()
                queued.append((kind, kwargs["generation"]))
            self.assertEqual(queued, [("loaded", 1), ("loaded", 2)])

    def test_loaded_and_load_failed_ignore_stale_generation(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 5
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance.load_button = Mock()
        mock_mb = Mock()

        with patch.object(app, "messagebox", mock_mb):
            # Stale _loaded call (generation 4 < 5)
            instance._loaded([], 0, generation=4)
            instance.progress.stop.assert_not_called()
            instance.refresh_table.assert_not_called()

            # Stale _load_failed call: a superseded scan must not stop the
            # progress bar or re-enable the Load button the newer scan owns.
            instance._load_failed("Some error", generation=4)
            instance.progress.stop.assert_not_called()
            instance.load_button.configure.assert_not_called()
            mock_mb.showerror.assert_not_called()

            # Current generation works
            instance._load_failed("Real error", generation=5)
            instance.progress.stop.assert_called_once()
            instance.load_button.configure.assert_called_once_with(state="normal")
            mock_mb.showerror.assert_called_once_with("Could not load library", "Real error")

    def test_load_worker_queues_results_instead_of_calling_tk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            (cache_dir / "test.cache").write_text("#SONGFILENAME:Songs/P/S/a.ogg;\n#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n", encoding="utf-8")
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(app.LibraryApp)
            instance._load_generation = 1
            instance._snapshot_lock = threading.Lock()
            instance._load_results = queue.Queue()
            instance._save_library_cache = Mock(return_value="2026-01-01T00:00:00")
            instance.root = Mock()

            instance._load_worker(cache_dir, stats_file, generation=1)

            # The worker thread hands results over through the queue; it never
            # calls root.after (Tk) from its own thread.
            instance.root.after.assert_not_called()
            kind, args, kwargs = instance._load_results.get_nowait()
            self.assertEqual(kind, "loaded")
            self.assertEqual(args[1], 1)  # one cache file scanned
            self.assertEqual(kwargs["generation"], 1)
            self.assertTrue(instance._load_results.empty())

            # A malformed Stats.xml queues a failure the same way.
            stats_file.write_text("<Stats><SongScores>", encoding="utf-8")
            instance._load_worker(cache_dir, stats_file, generation=1)
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("failed", 1))
            self.assertIn("malformed", message)

    def test_poll_load_results_delivers_queued_results_and_reschedules(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_results = queue.Queue()
        instance._loaded = Mock()
        instance._load_failed = Mock()
        instance.root = Mock()
        instance._load_results.put(("loaded", ([], 3), {"generation": 2}))
        instance._load_results.put(("failed", "boom", 2))

        instance._poll_load_results()

        instance._loaded.assert_called_once_with([], 3, generation=2)
        instance._load_failed.assert_called_once_with("boom", generation=2)
        instance.root.after.assert_called_once()
        delay, callback = instance.root.after.call_args[0]
        self.assertEqual(delay, 75)
        self.assertEqual(callback, instance._poll_load_results)

    def test_load_data_disables_the_load_button_and_starts_the_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(app.LibraryApp)
            instance.cache_var = Mock()
            instance.cache_var.get.return_value = str(cache_dir)
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance._save_settings = Mock()
            instance.progress = Mock()
            instance.status = Mock()
            instance.load_button = Mock()
            instance._load_generation = 0

            with patch.object(app.threading, "Thread") as mock_thread:
                instance.load_data()

            instance.load_button.configure.assert_called_once_with(state="disabled")
            self.assertEqual(instance._load_generation, 1)
            mock_thread.assert_called_once()
            self.assertEqual(mock_thread.call_args.kwargs["args"][2], 1)


class DialogKeyBindingTests(unittest.TestCase):
    # The Advanced Search dialog tests live in tests/test_advanced_search.py,
    # with the component they now test.

    def test_main_escape_clears_search_only_when_no_dialog_is_open(self):
        instance = object.__new__(app.LibraryApp)
        instance.clear_search = Mock()
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
        instance.clear_search.assert_called_once()  # no dialog open: Escape clears the search

        instance.clear_search.reset_mock()
        instance.course_builder.window = open_window
        instance._on_main_escape()
        instance.clear_search.assert_not_called()  # Build course open

        instance.course_builder.window = None
        instance.advanced_search.window = open_window
        instance._on_main_escape()
        instance.clear_search.assert_not_called()  # Advanced Search open

        instance.advanced_search.window = None
        instance.about_window = open_window
        instance._on_main_escape()
        instance.clear_search.assert_not_called()  # About open

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
    def test_loaded_batches_filter_changes_and_refreshes_once(self):
        instance = object.__new__(app.LibraryApp)
        instance.load_button = Mock()
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.pack_var = Mock()
        instance.type_var = Mock()
        instance.diff_var = Mock()
        instance._batched_filter_changes = app.LibraryApp._batched_filter_changes.__get__(instance)
        instance._batching_filter_changes = False
        instance.course_builder = None  # declared in __init__ since the split; this fake predates it

        # When setting diff_var/pack_var/type_var, Tk would run traces. Simulate that write traces call _refresh_unless_batching:
        instance._refresh_unless_batching = app.LibraryApp._refresh_unless_batching.__get__(instance)
        instance.diff_var.set.side_effect = lambda *args: instance._refresh_unless_batching()
        instance.pack_var.set.side_effect = lambda *args: instance._refresh_unless_batching()
        instance.type_var.set.side_effect = lambda *args: instance._refresh_unless_batching()

        rows = [
            {"Pack": "Pack1", "Type": "dance-single", "Difficulty": "Hard", "Title": "Song1"},
            {"Pack": "Pack2", "Type": "dance-single", "Difficulty": "Challenge", "Title": "Song2"},
        ]

        instance._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        instance.load_button.configure.assert_called_once_with(state="normal")
        # Must refresh table exactly once despite setting pack_var, type_var, and diff_var
        instance.refresh_table.assert_called_once()
        instance.pack_var.set.assert_called_with("All packs")
        instance.type_var.set.assert_called_with("All types")
        instance.diff_var.set.assert_called_with("All difficulties")

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
            instance._last_saved_settings = None

            # First save writes to disk
            instance._save_settings()
            self.assertTrue(settings_path.is_file())
            first_mtime = settings_path.stat().st_mtime_ns

            # Second save with no changes (e.g. routine table row click) skips write
            with patch("json.dump") as mock_dump:
                instance._save_settings()
                mock_dump.assert_not_called()
            self.assertEqual(settings_path.stat().st_mtime_ns, first_mtime)

            # Changing a column width causes it to save
            instance.tree.column.return_value = 150
            instance._save_settings()
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["column_widths"]["Pack"], 150)

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
            instance._last_saved_settings = None

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
        instance.rows = [{"Title": "Test Song", "Artist": "Artist"}]
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
            instance.rows = [{"Title": "My Song", "Pack": "My Pack"}]
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
            self.assertIn("Exported 1 charts", instance.status.set.call_args[0][0])


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


if __name__ == "__main__":
    unittest.main()
