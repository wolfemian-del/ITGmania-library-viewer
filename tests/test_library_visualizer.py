import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import library_visualizer as app


class LibrarySnapshotTests(unittest.TestCase):
    @staticmethod
    def make_app(settings_path, cache_dir, stats_file):
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = settings_path
        instance.cache_var = Mock()
        instance.cache_var.get.return_value = str(cache_dir)
        instance.stats_var = Mock()
        instance.stats_var.get.return_value = str(stats_file)
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance._loaded = Mock()
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

    def test_clear_chart_filter_resets_diff_and_search_directives(self):
        instance = object.__new__(app.LibraryApp)
        instance.diff_var = Mock()
        instance.diff_var.get.return_value = "Challenge"
        instance.search_var = Mock()
        instance.search_var.get.return_value = 'pack:"In The Groove" diff:Challenge meter:10'
        instance.refresh_table = Mock()

        instance.clear_chart_filter()

        # Clear removes every chart filter (difficulty and meter here), keeping the pack filter.
        instance.diff_var.set.assert_called_with("All difficulties")
        instance.search_var.set.assert_called_with('pack:"In The Groove"')
        instance.refresh_table.assert_called_once()

    def test_absence_fallback_when_matplotlib_unavailable(self):
        instance = object.__new__(app.LibraryApp)
        instance.show_distribution_panel = Mock(get=Mock(return_value=True))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.search_var = Mock(get=Mock(return_value=""))
        instance.dist_panel = Mock()
        instance.dist_banner_frame = Mock()
        instance.dist_banner_label = Mock()
        instance.dist_summary_var = Mock()

        original_avail = app.MATPLOTLIB_AVAILABLE
        try:
            app.MATPLOTLIB_AVAILABLE = False
            # When matplotlib is unavailable, _ensure_distribution_canvas returns False
            self.assertFalse(instance._ensure_distribution_canvas())
            # And _update_distribution_panel does not crash
            instance._update_distribution_panel([{"Meter": 10}])
            instance.dist_summary_var.set.assert_called()
        finally:
            app.MATPLOTLIB_AVAILABLE = original_avail


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
    def test_setup_tree_tags_configures_all_difficulties_and_selection(self):
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()

        instance._setup_tree_tags()
        # One tag per difficulty, one for unknown difficulties, and the selection tag.
        self.assertEqual(instance.tree.tag_configure.call_count, len(app.theme.DIFFICULTY_COLORS) + 2)
        for diff, color in app.theme.DIFFICULTY_COLORS.items():
            instance.tree.tag_configure.assert_any_call(f"diff_{diff}", foreground=color)
        instance.tree.tag_configure.assert_any_call(
            app.UNKNOWN_DIFFICULTY_TAG, foreground=app.theme.DIFFICULTY_COLOR_UNKNOWN)
        # The selection tag must be configured last, or selected rows would not turn white.
        self.assertEqual(instance.tree.tag_configure.call_args_list[-1].args[0], "selected_row")
        instance.tree.tag_configure.assert_any_call("selected_row", foreground=app.theme.TEXT_ON_ACCENT)

    def test_insert_batch_tags_rows_by_difficulty_and_selection(self):
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance._render_generation = 1
        instance.tree_item_rows = {}
        instance._selected_tree_items = set()
        instance.root = Mock()
        instance.tree.insert.side_effect = ["item0", "item1", "item2"]

        rows = [
            {"Title": "Song A", "Difficulty": "Challenge", "Time": 120},
            {"Title": "Song B", "Difficulty": "Hard", "Time": 90},
            {"Title": "Song C", "Difficulty": "CustomUnknown", "Time": 60},
        ]
        # Song B is pre-selected
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
        self.assertEqual(kwargs2.get("tags"), (app.UNKNOWN_DIFFICULTY_TAG,))
        # Only the pre-selected row is remembered as selected
        self.assertEqual(instance._selected_tree_items, {"item1"})
        instance.tree.selection_add.assert_called_once_with("item1")

    def test_on_tree_select_toggles_selected_row_tag(self):
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance.tree.exists.return_value = True
        instance._selected_tree_items = {"item1"}

        # Initial tags
        instance.tree.item.side_effect = lambda item_id, option=None, **kwargs: (
            ["diff_Challenge", "selected_row"] if item_id == "item1" else ["diff_Hard"]
        )

        # Selection changes: item1 deselected, item2 selected
        instance.tree.selection.return_value = ["item2"]
        instance._on_tree_select()

        # item1 should have selected_row removed
        instance.tree.item.assert_any_call("item1", tags=["diff_Challenge"])
        # item2 should have selected_row added
        instance.tree.item.assert_any_call("item2", tags=["diff_Hard", "selected_row"])
        self.assertEqual(instance._selected_tree_items, {"item2"})

    def test_on_tree_select_skips_rows_a_refresh_already_removed(self):
        instance = object.__new__(app.LibraryApp)
        instance.tree = Mock()
        instance.tree.exists.return_value = False
        instance._selected_tree_items = {"gone"}
        instance.tree.selection.return_value = []

        instance._on_tree_select()

        instance.tree.item.assert_not_called()
        self.assertEqual(instance._selected_tree_items, set())


if __name__ == "__main__":
    unittest.main()
