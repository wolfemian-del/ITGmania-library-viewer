import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
        instance.search_entry = Mock()
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


class CourseBuilderValidationTests(unittest.TestCase):
    def test_validate_course_entries_delegates_and_rejects_unsafe_comments(self):
        instance = object.__new__(app.LibraryApp)
        instance.course_window = Mock()
        instance.course_entries = [{"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}]

        mock_mb = Mock()
        with patch.object(app, "messagebox", mock_mb):
            valid = instance.validate_course_entries("Bad // Title")
            self.assertFalse(valid)
            mock_mb.showerror.assert_called_once()
            self.assertIn("//", mock_mb.showerror.call_args[0][1])

    def test_validate_course_entries_accepts_clean_entries(self):
        instance = object.__new__(app.LibraryApp)
        instance.course_window = Mock()
        instance.course_entries = [{"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}]

        mock_mb = Mock()
        with patch.object(app, "messagebox", mock_mb):
            valid = instance.validate_course_entries("Clean Title")
            self.assertTrue(valid)
            mock_mb.showerror.assert_not_called()

    def _validate(self, entries, *title_argument):
        """Run validate_course_entries with a fake message box; return (result, mock message box)."""
        instance = object.__new__(app.LibraryApp)
        instance.course_window = Mock()
        instance.course_entries = entries
        mock_mb = Mock()
        with patch.object(app, "messagebox", mock_mb):
            return instance.validate_course_entries(*title_argument), mock_mb

    def test_append_flow_validates_without_a_title(self):
        # Appending to an existing course calls validate_course_entries() with no title, so a missing title
        # must not be reported as an error.
        entry = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        valid, mock_mb = self._validate([entry])
        self.assertTrue(valid)
        mock_mb.showerror.assert_not_called()

        valid, mock_mb = self._validate([])
        self.assertFalse(valid)
        self.assertEqual(mock_mb.showerror.call_args[0][1], "Add at least one chart to the course.")

        valid, mock_mb = self._validate([{**entry, "Course path": "Pack//Song"}])
        self.assertFalse(valid)
        self.assertIn("//", mock_mb.showerror.call_args[0][1])

    def test_every_validation_error_uses_the_same_dialog_title(self):
        entry = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        cases = (
            ([entry], "Bad // Title"),
            ([entry], "Bad: Title"),
            ([], "Title"),
            ([{**entry, "Difficulty": ""}], "Title"),
            ([{**entry, "Course path": "Pack;Song"}], "Title"),
        )
        titles = set()
        for entries, title in cases:
            with self.subTest(title=title, entries=entries):
                valid, mock_mb = self._validate(entries, title)
                self.assertFalse(valid)
                mock_mb.showerror.assert_called_once()
                titles.add(mock_mb.showerror.call_args[0][0])
        self.assertEqual(len(titles), 1)

    def test_export_course_writes_formatted_new_course(self):
        with tempfile.TemporaryDirectory() as directory:
            out_file = Path(directory) / "test_course.crs"
            instance = object.__new__(app.LibraryApp)
            instance.course_window = Mock()
            instance.course_title_var = Mock(get=Mock(return_value="My Epic Course"))
            instance.course_entries = [
                {"Course path": "Pack/SongA", "Difficulty": "Hard", "Type": "dance-single"},
                {"Course path": "Pack/SongB", "Difficulty": "Challenge", "Type": "dance-single"},
            ]
            instance.status = Mock()

            mock_fd = Mock(asksaveasfilename=Mock(return_value=str(out_file)))
            mock_mb = Mock()

            with patch.object(app, "filedialog", mock_fd), patch.object(app, "messagebox", mock_mb):
                instance.export_course()

            mock_mb.showerror.assert_not_called()
            mock_mb.showinfo.assert_called_once()
            self.assertTrue(out_file.is_file())
            written_content = out_file.read_text(encoding="utf-8")
            expected_body = app.format_new_course(
                "My Epic Course",
                app.course_song_lines(instance.course_entries)
            )
            self.assertEqual(written_content, expected_body)
            self.assertIn("Saved course with 2 charts", instance.status.set.call_args[0][0])

    def test_export_course_blank_title_shows_validation_error(self):
        instance = object.__new__(app.LibraryApp)
        instance.course_window = Mock()
        instance.course_title_var = Mock(get=Mock(return_value="   "))
        instance.course_entries = [{"Course path": "Pack/SongA", "Difficulty": "Hard", "Type": "dance-single"}]
        instance.status = Mock()

        mock_fd = Mock()
        mock_mb = Mock()

        with patch.object(app, "filedialog", mock_fd), patch.object(app, "messagebox", mock_mb):
            instance.export_course()

        mock_mb.showerror.assert_called_once_with(
            "Course problem", "Enter a title for this course.", parent=instance.course_window
        )
        mock_fd.asksaveasfilename.assert_not_called()

    def test_append_course_appends_course_song_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            crs_file = Path(directory) / "existing.crs"
            crs_file.write_text("#COURSE:Existing;\n#SONG:Pack/SongA:Hard:;\n", encoding="utf-8")

            instance = object.__new__(app.LibraryApp)
            instance.course_window = Mock()
            instance.course_entries = [
                {"Course path": "Pack/SongB", "Difficulty": "Challenge", "Type": "dance-single"},
            ]
            instance.status = Mock()

            mock_fd = Mock(askopenfilename=Mock(return_value=str(crs_file)))
            mock_mb = Mock()

            with patch.object(app, "filedialog", mock_fd), patch.object(app, "messagebox", mock_mb):
                instance.append_course()

            mock_mb.showerror.assert_not_called()
            mock_mb.showinfo.assert_called_once()
            content = crs_file.read_text(encoding="utf-8")
            self.assertEqual(
                content,
                "#COURSE:Existing;\n#SONG:Pack/SongA:Hard:;\n#SONG:Pack/SongB:Challenge:;\n"
            )
            self.assertIn("Appended 1 charts", instance.status.set.call_args[0][0])


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
    def test_open_advanced_search_binds_escape_and_return(self):
        instance = object.__new__(app.LibraryApp)
        instance.root = Mock()
        instance.advanced_search_window = None
        instance.search_var = Mock()
        instance.search_entry = Mock()

        mock_window = Mock()
        bindings = {}
        def mock_bind(seq, func):
            bindings[seq] = func
        mock_window.bind.side_effect = mock_bind
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        mock_ttk = Mock()

        with patch.object(app, "tk", mock_tk), patch.object(app, "ttk", mock_ttk):
            instance._button = Mock(return_value=Mock())
            instance.open_advanced_search()

        self.assertIn("<Escape>", bindings)
        self.assertIn("<Return>", bindings)
        # The window takes keyboard focus itself, so Escape and Return reach it without a click first.
        mock_window.focus_force.assert_called_once()

        # Escape closes the dialog without touching the main search text and stops the key event.
        res_esc = bindings["<Escape>"]()
        self.assertEqual(res_esc, "break")
        mock_window.destroy.assert_called_once()
        instance.search_var.set.assert_not_called()

        # Return writes the built query to the main search box, closes the dialog and stops the key event.
        mock_window.destroy.reset_mock()
        res_ret = bindings["<Return>"]()
        self.assertEqual(res_ret, "break")
        instance.search_var.set.assert_called_once()
        mock_window.destroy.assert_called_once()

    def test_open_course_builder_binds_escape(self):
        instance = object.__new__(app.LibraryApp)
        instance.root = Mock()
        instance.course_window = None
        instance.tree = Mock()
        instance.tree.selection.return_value = []

        mock_window = Mock()
        bindings = {}
        def mock_bind(seq, func):
            bindings[seq] = func
        mock_window.bind.side_effect = mock_bind
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        mock_ttk = Mock()

        with patch.object(app, "tk", mock_tk), patch.object(app, "ttk", mock_ttk):
            instance._button = Mock(return_value=Mock())
            instance.open_course_builder()

        self.assertIn("<Escape>", bindings)
        # The window takes keyboard focus itself, so Escape reaches it without a click first.
        mock_window.focus_force.assert_called_once()
        mock_messagebox = Mock()
        with patch.object(app, "messagebox", mock_messagebox):
            # Empty queue: closes at once, no question.
            res_esc = bindings["<Escape>"]()
            self.assertEqual(res_esc, "break")
            mock_window.destroy.assert_called_once()
            mock_messagebox.askyesno.assert_not_called()

            # Queued charts, user answers No: the window stays open.
            mock_window.destroy.reset_mock()
            instance.course_entries = [{"Title": "A"}, {"Title": "B"}]
            mock_messagebox.askyesno.return_value = False
            self.assertEqual(bindings["<Escape>"](), "break")
            mock_messagebox.askyesno.assert_called_once()
            mock_window.destroy.assert_not_called()

            # Queued charts, user answers Yes: the window closes.
            mock_messagebox.askyesno.return_value = True
            self.assertEqual(bindings["<Escape>"](), "break")
            mock_window.destroy.assert_called_once()


    def test_opening_a_dialog_that_is_already_open_raises_it_and_gives_it_focus(self):
        for attribute, opener in (("advanced_search_window", "open_advanced_search"),
                                  ("course_window", "open_course_builder")):
            with self.subTest(dialog=attribute):
                instance = object.__new__(app.LibraryApp)
                existing = Mock()
                existing.winfo_exists.return_value = True
                setattr(instance, attribute, existing)
                mock_tk = Mock()
                with patch.object(app, "tk", mock_tk):
                    getattr(instance, opener)()
                existing.lift.assert_called_once()
                existing.focus_force.assert_called_once()
                mock_tk.Toplevel.assert_not_called()  # no second window

    def test_main_escape_clears_search_only_when_no_dialog_is_open(self):
        instance = object.__new__(app.LibraryApp)
        instance.clear_search = Mock()
        open_window = Mock()
        open_window.winfo_exists.return_value = True
        closed_window = Mock()
        closed_window.winfo_exists.return_value = False

        instance.advanced_search_window = None
        instance.course_window = closed_window
        instance._on_main_escape()
        instance.clear_search.assert_called_once()  # no dialog open: Escape clears the search

        instance.clear_search.reset_mock()
        instance.course_window = open_window
        instance._on_main_escape()
        instance.clear_search.assert_not_called()  # Build course open

        instance.course_window = None
        instance.advanced_search_window = open_window
        instance._on_main_escape()
        instance.clear_search.assert_not_called()  # Advanced Search open


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


if __name__ == "__main__":
    unittest.main()
