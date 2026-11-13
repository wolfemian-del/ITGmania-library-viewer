import contextlib
import json
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

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

    def test_snapshot_round_trip_preserves_loaded_fields(self):
        # One delegate test pins the complete positional mapping from the
        # snapshot into _loaded: every field gets a distinct value, so a
        # swap in the delegate's argument order fails.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            rows = [self.sample_row()]
            instance._snapshot_store.write(cache_dir, stats_file, rows, 2, 1, 3, True, skipped_blocks=4)

            instance.load_cached_data()

        instance._loaded.assert_called_once()
        args, kwargs = instance._loaded.call_args
        # _loaded's positional args: rows, files, skipped_files,
        # files_without_charts, skipped_blocks, nested_song_tree.
        self.assertEqual(args, (rows, 2, 1, 3, 4, True))

    def test_snapshot_restores_when_source_paths_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            rows = [self.sample_row()]
            instance._snapshot_store.write(cache_dir, stats_file, rows, 1, 0, 0, False)

            instance.load_cached_data()

        instance._loaded.assert_called_once()
        args, kwargs = instance._loaded.call_args
        self.assertEqual(args[0], rows)
        self.assertTrue(kwargs["from_cache"])
        self.assertEqual(kwargs["source_paths"], (str(cache_dir), str(stats_file)))

    def test_snapshot_restores_but_notes_a_moved_cache_folder(self):
        # The snapshot restores on a string match only, so a moved folder is
        # invisible until the next refresh fails; the status line must say so.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            cache_dir.mkdir(parents=True)
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            shutil.rmtree(root / "Cache")
            instance.status = _StubStatus(
                "Showing saved library snapshot · 1 charts · last refreshed 2026-11-10 08:00.")

            instance.load_cached_data()
            instance.load_cached_data()  # a second restore must not duplicate the note

            instance._loaded.assert_called()
            self.assertTrue(instance.status.get().startswith("Showing saved library snapshot"))
            self.assertEqual(instance.status.get().count("no longer exists"), 1)
            self.assertIn("The saved cache folder no longer exists.", instance.status.get())
            self.assertIn("Choose File → Data paths…, then Load / refresh.", instance.status.get())

    def test_snapshot_restores_but_notes_a_moved_stats_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            cache_dir.mkdir(parents=True)
            stats_file.write_text("<Stats/>")
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            stats_file.unlink()
            instance.status = _StubStatus(
                "Showing saved library snapshot · 1 charts · last refreshed 2026-11-10 08:00.")

            instance.load_cached_data()

            self.assertIn("The saved Stats.xml no longer exists.", instance.status.get())
            self.assertIn("Choose File → Data paths…, then Load / refresh.", instance.status.get())

    def test_snapshot_restores_but_notes_both_paths_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            # Neither path was ever created on disk.
            instance.status = _StubStatus(
                "Showing saved library snapshot · 1 charts · last refreshed 2026-11-10 08:00.")

            instance.load_cached_data()

            self.assertIn("The saved cache folder and Stats.xml no longer exist.", instance.status.get())
            self.assertIn("Choose File → Data paths…, then Load / refresh.", instance.status.get())

    def test_snapshot_restores_quietly_when_both_paths_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            stats_file = root / "Stats.xml"
            cache_dir.mkdir(parents=True)
            stats_file.write_text("<Stats/>")
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            success = "Showing saved library snapshot · 1 charts · last refreshed 2026-11-10 08:00."
            instance.status = _StubStatus(success)

            instance.load_cached_data()

            self.assertEqual(instance.status.get(), success)

    def test_snapshot_is_not_restored_for_different_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "CacheB", root / "Stats.xml")
            instance._snapshot_store.write(
                root / "CacheA", root / "Stats.xml", [self.sample_row()], 1, 0, 0, False)

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("different data paths", instance.status.set.call_args.args[0])

    def test_snapshot_with_deeply_nested_json_reports_could_not_be_read(self):
        # Issue #122: a snapshot nested far past the recursion limit raises
        # RecursionError out of json.load; it must be reported like any
        # other unreadable snapshot instead of escaping the callback.
        # The depth is 1,000,000 because the limit is version-dependent:
        # 10,000 levels raise on 3.12 but parse on 3.14 (whose C recursion
        # limit is higher), so the depth must exceed every supported
        # version's limit. json.load fails fast at the limit.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache" / "Songs", root / "Stats.xml")
            instance.library_cache_path.write_text("[" * 1000000 + "]" * 1000000, encoding="utf-8")

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("could not be read", instance.status.set.call_args.args[0])
        # The detail pin (proposal 0008, Revision 3): the status text
        # carries the exception, not just the reason kind. Python 3.14's
        # JSON scanner reports the overflow as "Stack overflow ..."; earlier
        # versions raise RecursionError ("maximum recursion depth exceeded").
        if sys.version_info >= (3, 14):
            self.assertIn("Stack overflow", instance.status.set.call_args.args[0])
        else:
            self.assertIn("recursion", instance.status.set.call_args.args[0])

    @unittest.skipIf(sys.version_info < (3, 11),
                     "the int-string conversion limit is 3.11+")
    def test_snapshot_with_oversized_integer_reports_could_not_be_read(self):
        # Issue #122: an integer past the 4,300-digit conversion limit
        # raises ValueError out of json.load; same handling as above.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache" / "Songs", root / "Stats.xml")
            instance.library_cache_path.write_text("[" + "9" * 5000 + "]", encoding="utf-8")

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("could not be read", instance.status.set.call_args.args[0])
        # The detail pin (proposal 0008, Revision 3): the status text
        # carries the exception, not just the reason kind.
        self.assertIn("integer string conversion", instance.status.set.call_args.args[0])

    def test_snapshot_with_invalid_utf8_reports_could_not_be_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "Cache" / "Songs", root / "Stats.xml")
            instance.library_cache_path.write_bytes(b"\xff\xfe not utf-8")

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("could not be read", instance.status.set.call_args.args[0])
        # The detail pin (proposal 0008, Revision 3): the status text
        # carries the exception, not just the reason kind.
        self.assertIn("codec can't decode", instance.status.set.call_args.args[0])

    def test_snapshot_is_not_restored_with_an_unsupported_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache", root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            with instance.library_cache_path.open("r+", encoding="utf-8") as handle:
                payload = json.load(handle)
                payload["schema_version"] = library_data.LIBRARY_CACHE_SCHEMA_VERSION + 1
                handle.seek(0)
                json.dump(payload, handle)
                handle.truncate()

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.refresh_table.assert_called_once()
        self.assertIn("invalid or outdated", instance.status.set.call_args.args[0])

    def test_snapshot_schema_version_2_is_rejected_as_outdated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache", root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            with instance.library_cache_path.open("r+", encoding="utf-8") as handle:
                payload = json.load(handle)
                payload["schema_version"] = 2
                handle.seek(0)
                json.dump(payload, handle)
                handle.truncate()

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        self.assertIn("invalid or outdated", instance.status.set.call_args.args[0])

    def test_snapshot_row_missing_a_column_is_rejected_as_outdated(self):
        # Issue #49: the HEADERS check independently invalidates a snapshot
        # whose rows predate a new column, even at the current schema version.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache", root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance._snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            with instance.library_cache_path.open("r+", encoding="utf-8") as handle:
                payload = json.load(handle)
                del payload["rows"][0]["Subtitle"]
                handle.seek(0)
                json.dump(payload, handle)
                handle.truncate()

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        self.assertIn("invalid or outdated", instance.status.set.call_args.args[0])

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

    def test_non_finite_time_values_insert_as_blank_instead_of_crashing(self):
        # Issue #123: a snapshot row whose Time is "nan" or "1e999" used to
        # raise inside _insert_batch; now the cell is blank and the batch lands.
        instance, _rows = self.make_instance()
        instance.rows = [
            {"Title": "Song A", "Difficulty": "Hard", "Time": "nan"},
            {"Title": "Song B", "Difficulty": "Hard", "Time": "1e999"},
            {"Title": "Song C", "Difficulty": "Hard", "Time": 120},
        ]
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(instance.rows, 0, 1)
        self.assertEqual(instance.tree.insert.call_count, 3)
        time_index = list(app.HEADERS).index("Time")
        inserted = [kwargs["values"][time_index]
                    for _args, kwargs in instance.tree.insert.call_args_list]
        self.assertEqual(inserted, ["", "", "2:00"])

    def test_count_line_names_an_unreadable_filter_value(self):
        instance, rows = self.make_instance()
        instance.search_var = Mock()
        instance.search_var.get.return_value = "meter:abc"
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        instance.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in meter:abc")

    def test_count_line_names_an_unreadable_grade_value(self):
        instance, rows = self.make_instance()
        instance.search_var = Mock()
        instance.search_var.get.return_value = "grade:banana"
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        instance.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in grade:banana")

    def test_count_line_stays_plain_for_a_readable_filter(self):
        instance, rows = self.make_instance()
        instance.search_var = Mock()
        instance.search_var.get.return_value = "meter:11"
        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._insert_batch(rows, 0, 1)
        instance.count_label.set.assert_called_once_with("3 charts shown · 3 total")


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
        instance._settings_store = library_data.SettingsStore(instance.settings_path)
        instance._settings_store.load()

    def test_loaded_keeps_values_that_are_in_the_new_library(self):
        instance = self.make_loaded_instance(pack="Pack2", type_="dance-single", difficulty="Challenge")
        rows = self.rows(("Pack1", "dance-single", "Hard"), ("Pack2", "dance-double", "Challenge"))

        instance._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        self.assertEqual(instance.pack_var.get(), "Pack2")
        self.assertEqual(instance.type_var.get(), "dance-single")
        self.assertEqual(instance.diff_var.get(), "Challenge")
        instance.refresh_table.assert_called_once()

    def test_loaded_reports_skipped_chart_blocks_in_the_summary(self):
        instance = self.make_loaded_instance()
        rows = self.rows(("Pack1", "dance-single", "Hard"), ("Pack2", "dance-single", "Hard"))

        instance._loaded(rows, len(rows), skipped_blocks=2)

        status = instance.status.set.call_args.args[0]
        self.assertTrue(status.startswith("Scanned 2 files · parsed 2 charts"))
        self.assertIn(" · 2 chart blocks skipped (missing metadata)", status)

    def test_loaded_omits_the_skipped_blocks_fragment_when_zero(self):
        instance = self.make_loaded_instance()
        rows = self.rows(("Pack1", "dance-single", "Hard"))

        instance._loaded(rows, len(rows))

        self.assertNotIn("chart blocks skipped", instance.status.set.call_args.args[0])

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
            instance._settings_store = library_data.SettingsStore(settings_path)
            seeded = instance._settings_store.load()
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
            # load_cached_data reads through the snapshot store (proposal
            # 0008); the missing file returns before the paths are compared,
            # so the variables can stay empty.
            instance.cache_var = Mock()
            instance.cache_var.get.return_value = ""
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = ""
            instance._snapshot_store = library_data.SnapshotStore(
                instance.library_cache_path, app.HEADERS, library_data.LIBRARY_CACHE_SCHEMA_VERSION)

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


class DataPathsPopupTests(unittest.TestCase):
    """The first-run Data paths popup (UI redesign): _maybe_show_first_run_paths_dialog
    opens it once at startup only when no snapshot restored and the paths are
    not both usable, with the note naming the situation."""

    @staticmethod
    def make_instance(cache_dir, stats_file, saved_settings=None, loaded_source_paths=None):
        instance = object.__new__(app.LibraryApp)
        instance._data_paths_popup_shown = False
        instance.loaded_source_paths = loaded_source_paths
        instance.cache_var = Mock()
        instance.cache_var.get.return_value = str(cache_dir)
        instance.stats_var = Mock()
        instance.stats_var.get.return_value = str(stats_file)
        instance.saved_settings = saved_settings if saved_settings is not None else {}
        instance.open_data_paths_dialog = Mock()
        return instance

    def test_first_run_opens_with_the_first_run_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_instance(root / "Cache" / "Songs", root / "Stats.xml")
            instance._maybe_show_first_run_paths_dialog()
        instance.open_data_paths_dialog.assert_called_once_with(
            note=app.LibraryApp._DATA_PATHS_FIRST_RUN_NOTE)

    def test_dead_saved_paths_get_the_dead_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache" / "Songs", root / "Stats.xml"
            instance = self.make_instance(
                cache_dir, stats_file, saved_settings={"cache_dir": str(cache_dir)})
            instance._maybe_show_first_run_paths_dialog()
        instance.open_data_paths_dialog.assert_called_once_with(
            note=app.LibraryApp._DATA_PATHS_DEAD_NOTE)

    def test_no_popup_when_a_snapshot_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache" / "Songs", root / "Stats.xml"
            instance = self.make_instance(
                cache_dir, stats_file,
                saved_settings={"cache_dir": str(cache_dir)},
                loaded_source_paths=(str(cache_dir), str(stats_file)))
            instance._maybe_show_first_run_paths_dialog()
        instance.open_data_paths_dialog.assert_not_called()

    def test_no_popup_when_both_paths_are_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            cache_dir.mkdir(parents=True)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            instance = self.make_instance(cache_dir, stats_file)
            instance._maybe_show_first_run_paths_dialog()
        instance.open_data_paths_dialog.assert_not_called()

    def test_popup_shows_only_once_per_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_instance(root / "Cache" / "Songs", root / "Stats.xml")
            instance._maybe_show_first_run_paths_dialog()
            instance._maybe_show_first_run_paths_dialog()
        instance.open_data_paths_dialog.assert_called_once()

    def test_bare_instance_without_path_state_returns_silently(self):
        instance = object.__new__(app.LibraryApp)
        instance._maybe_show_first_run_paths_dialog()  # no error, no dialog


class InvalidPathsNoteTests(unittest.TestCase):
    """The Data paths note naming whichever path cannot be used."""

    def test_both_usable_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            cache_dir.mkdir(parents=True)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            self.assertEqual(app.LibraryApp._invalid_paths_note(cache_dir, stats_file), "")

    def test_cache_only_names_the_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            note = app.LibraryApp._invalid_paths_note(root / "Cache" / "Songs", stats_file)
            self.assertIn("cache folder", note)
            self.assertNotIn("Stats.xml", note)

    def test_stats_only_names_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            cache_dir.mkdir(parents=True)
            note = app.LibraryApp._invalid_paths_note(cache_dir, root / "Stats.xml")
            self.assertIn("Stats.xml", note)
            self.assertNotIn("cache folder", note)

    def test_both_missing_names_both(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = app.LibraryApp._invalid_paths_note(root / "Cache" / "Songs", root / "Stats.xml")
            self.assertIn("cache folder", note)
            self.assertIn("Stats.xml", note)


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

    def test_deferred_load_reports_discarded_settings_after_the_snapshot_status(self):
        instance = object.__new__(app.LibraryApp)
        instance.progress = Mock()
        instance._load_generation = 0
        instance._settings_store = library_data.SettingsStore(Path("settings.json"))
        instance._settings_store.last_read_error = "Expecting value: line 1 column 1 (char 0)"
        instance.status = _StubStatus()

        def load():
            instance.status.set("No saved library snapshot yet. Choose your paths, then click Load / refresh.")

        instance.load_cached_data = load

        instance._load_initial_snapshot()

        self.assertIn("No saved library snapshot yet.", instance.status.get())
        self.assertIn("Settings file could not be read", instance.status.get())
        instance.progress.stop.assert_called_once_with()

    def test_deferred_load_does_not_report_when_a_user_scan_supersedes_it(self):
        # A Load / refresh pressed inside the deferral window owns the
        # status line; the startup notice must not scribble over its scan.
        instance = object.__new__(app.LibraryApp)
        instance.progress = Mock()
        instance.load_cached_data = Mock()
        instance._load_generation = 1
        instance._settings_store = library_data.SettingsStore(Path("settings.json"))
        instance._settings_store.last_read_error = "Expecting value: line 1 column 1 (char 0)"
        instance.status = _StubStatus("Loading…")

        instance._load_initial_snapshot()

        self.assertEqual(instance.status.get(), "Loading…")
        instance.progress.stop.assert_not_called()


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
        self.assertEqual(len(application.rows), 3)
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
        window = application._data_paths_window
        self.assertTrue(window.winfo_exists())
        self.assertEqual(window.title(), "Where is your library?")
        self.find_button(window, "Cancel").invoke()
        self.assertFalse(window.winfo_exists())
        self.assertIsNone(application._data_paths_window)

    def test_dialog_is_modal_and_dismisses_with_escape(self):
        root = self.make_root()
        # Usable paths, so the deferred startup load does not open the
        # first-run popup of its own accord while this test pumps.
        _dir, cache_dir, _stats = self.make_settings()
        cache_dir.mkdir(parents=True)
        application = app.LibraryApp(root)
        application.open_data_paths_dialog()
        window = application._data_paths_window
        self.assertEqual(window.grab_status(), "local")
        # A generated key event needs a mapped window: wait until the dialog
        # is viewable, then send Escape and let it land.
        self.pump_until(root, lambda: window.winfo_viewable())
        window.event_generate("<Escape>", when="now")
        for _ in range(3):
            root.update()
            time.sleep(0.02)
        self.assertFalse(window.winfo_exists())
        self.assertIsNone(application._data_paths_window)

    def test_first_run_popup_opens_at_startup_and_does_not_reappear(self):
        root = self.make_root()
        self.make_settings(write_settings=False)
        application = app.LibraryApp(root)
        self.pump_until(root, lambda: application._data_paths_window is not None
                        and application._data_paths_window.winfo_exists())
        window = application._data_paths_window
        self.assertEqual(application._data_paths_note.cget("text"),
                         app.LibraryApp._DATA_PATHS_FIRST_RUN_NOTE)
        self.assertIn("No saved library yet.", application.status.get())
        self.find_button(window, "Cancel").invoke()
        self.assertFalse(window.winfo_exists())
        # Pumping on must not bring it back: dismissed once per session.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertIsNone(application._data_paths_window)

    def test_dead_saved_paths_popup_names_the_dead_paths(self):
        root = self.make_root()
        self.make_settings(write_settings=True)  # paths do not exist on disk
        application = app.LibraryApp(root)
        self.pump_until(root, lambda: application._data_paths_window is not None
                        and application._data_paths_window.winfo_exists())
        self.assertEqual(application._data_paths_note.cget("text"),
                         app.LibraryApp._DATA_PATHS_DEAD_NOTE)
        self.find_button(application._data_paths_window, "Cancel").invoke()

    def test_load_with_invalid_paths_opens_the_dialog(self):
        root = self.make_root()
        self.make_settings(write_settings=True)  # paths do not exist on disk
        application = app.LibraryApp(root)
        # No pumping: the deferred startup load has not run yet, so the
        # dialog here comes from Load, not from the first-run popup.
        application.load_data()
        window = application._data_paths_window
        self.assertTrue(window.winfo_exists())
        self.assertIn("cache folder", application._data_paths_note.cget("text"))
        self.find_button(window, "Cancel").invoke()
        self.assertFalse(window.winfo_exists())

    def test_dialog_load_button_starts_a_scan_with_valid_paths(self):
        root = self.make_root()
        _dir, cache_dir, _stats = self.make_settings(write_settings=True)
        cache_dir.mkdir(parents=True)
        application = app.LibraryApp(root)
        application.open_data_paths_dialog()
        window = application._data_paths_window
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
        self.assertEqual(application._data_paths_note.cget("text"), "")
        application.cache_var.set("/somewhere/else")
        self.assertEqual(application._data_paths_note.cget("text"),
                         app.LibraryApp._DATA_PATHS_DIFFER_NOTE)
        application.cache_var.set(str(cache_dir))
        self.assertEqual(application._data_paths_note.cget("text"), "")
        # And when the dialog opens with the paths already moved, the differ
        # note is there from the start, not only after a later edit.
        application.cache_var.set("/somewhere/else")
        self.find_button(application._data_paths_window, "Cancel").invoke()
        application.open_data_paths_dialog()
        self.assertEqual(application._data_paths_note.cget("text"),
                         app.LibraryApp._DATA_PATHS_DIFFER_NOTE)
        self.find_button(application._data_paths_window, "Cancel").invoke()

    def test_dialog_load_button_with_invalid_paths_stays_open_and_names_them(self):
        root = self.make_root()
        self.make_settings(write_settings=True)  # paths do not exist on disk
        application = app.LibraryApp(root)
        application.open_data_paths_dialog()
        window = application._data_paths_window
        self.find_button(window, "Load library").invoke()
        self.assertTrue(window.winfo_exists())
        # Only the cache is missing here (make_settings writes Stats.xml),
        # so the note names that side alone.
        self.assertIn("cache folder", application._data_paths_note.cget("text"))
        self.assertNotIn("Stats.xml", application._data_paths_note.cget("text"))
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
            instance._snapshot_store = Mock()
            instance.root = Mock()

            # Run worker with stale generation 1
            instance._load_worker(cache_dir, stats_file, generation=1)

            instance._snapshot_store.write.assert_not_called()
            instance.root.after.assert_not_called()
            # Superseded before the first file: nothing is queued at all,
            # not even the progress report.
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
            instance._snapshot_store = Mock()
            instance.root = Mock()

            def newer_refresh_starts_while_parsing(path, scores):
                instance._load_generation = 2  # the only file is parsed, so the scan loop will not notice
                return [], 0

            with patch.object(app, "parse_cache_file", newer_refresh_starts_while_parsing):
                instance._load_worker(cache_dir, stats_file, generation=1)

            instance._snapshot_store.write.assert_not_called()
            instance.root.after.assert_not_called()
            # A scan superseded mid-loop queues no delivery. The (0, 1)
            # progress report sent before the generation moved is dropped
            # by the poller's own generation check.
            kinds = []
            while not instance._load_results.empty():
                kinds.append(instance._load_results.get_nowait()[0])
            self.assertNotIn("loaded", kinds)
            self.assertNotIn("failed", kinds)

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

            # The slow-write seam re-anchors on the store's write (proposal
            # 0008, Revision 3): the worker calls store.write, so the test
            # wraps that method on the instance's own store.
            store = library_data.SnapshotStore(
                instance.library_cache_path, app.HEADERS, library_data.LIBRARY_CACHE_SCHEMA_VERSION)
            real_write = store.write
            old_is_saving, new_has_saved = threading.Event(), threading.Event()

            def slow_write_for_old_folder(cache_dir, *args):
                if Path(cache_dir) == old_folder:
                    old_is_saving.set()
                    new_has_saved.wait(0.3)  # long enough for an unlocked newer scan to finish first
                refreshed_at = real_write(cache_dir, *args)
                if Path(cache_dir) == new_folder:
                    new_has_saved.set()
                return refreshed_at

            store.write = slow_write_for_old_folder
            instance._snapshot_store = store
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
            # Progress and phase reports share the queue; only the
            # deliveries are collected here.
            queued = []
            while not instance._load_results.empty():
                item = instance._load_results.get_nowait()
                if item[0] == "loaded":
                    queued.append((item[0], item[2]["generation"]))
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
            instance._snapshot_store = Mock()
            instance._snapshot_store.write.return_value = "2026-01-01T00:00:00"
            instance.root = Mock()

            instance._load_worker(cache_dir, stats_file, generation=1)

            # The worker thread hands results over through the queue; it never
            # calls root.after (Tk) from its own thread. Progress reports
            # share the queue, so the delivery is found by kind.
            instance.root.after.assert_not_called()
            queued = []
            while not instance._load_results.empty():
                queued.append(instance._load_results.get_nowait())
            loaded = [item for item in queued if item[0] == "loaded"]
            self.assertEqual(len(loaded), 1)
            kind, args, kwargs = loaded[0]
            self.assertEqual(args[1], 1)  # one cache file scanned
            self.assertEqual(kwargs["generation"], 1)

            # A malformed Stats.xml queues a failure the same way.
            stats_file.write_text("<Stats><SongScores>", encoding="utf-8")
            instance._load_worker(cache_dir, stats_file, generation=1)
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("failed", 1))
            self.assertIn("malformed", message)

    def test_load_worker_passes_scan_results_to_store_write_in_order(self):
        # The worker calls store.write with eight positional arguments; the
        # store's own field-order pin calls write directly, so this test pins
        # the call site. skipped_blocks=3 and nested_song_tree=False are
        # distinguishable only by identity (0 == False), so the bool is
        # asserted with assertIs: a swap of the last two arguments fails.
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
            instance._snapshot_store = Mock()
            instance._snapshot_store.write.return_value = "2026-01-01T00:00:00"
            instance.root = Mock()

            row = {"Title": "a"}
            with patch.object(app, "parse_cache_file", return_value=([row], 3)):
                instance._load_worker(cache_dir, stats_file, generation=1)

            args = instance._snapshot_store.write.call_args.args
            self.assertEqual(args[0], cache_dir)
            self.assertEqual(args[1], stats_file)
            self.assertEqual(args[2], [row])
            self.assertEqual(args[3], 1)  # one cache file scanned
            self.assertEqual(args[4], 0)  # skipped_files
            self.assertEqual(args[5], 0)  # files_without_charts
            self.assertIs(args[6], False)  # nested_song_tree
            self.assertEqual(args[7], 3)  # skipped_blocks

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


class ScoresSyncTests(unittest.TestCase):
    """The scores-only sync (issue #147): re-read Stats.xml, no cache re-parse."""

    def _write_song(self, root):
        cache_dir = root / "Cache"
        cache_dir.mkdir()
        (cache_dir / "song.cache").write_text(
            "#TITLE:Song;\n"
            "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
            "#NOTEDATA:;\n"
            "#STEPSTYPE:dance-single;\n"
            "#DIFFICULTY:Hard;\n"
            "#METER:10;\n",
            encoding="utf-8")
        stats_file = root / "Stats.xml"
        stats_file.write_text(
            "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
            "<Steps StepsType='dance-single' Difficulty='Hard'>"
            "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
            "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade></HighScore>"
            "</HighScoreList></Steps>"
            "</Song></SongScores></Stats>",
            encoding="utf-8")
        return cache_dir, stats_file

    def _fresh_stats(self, stats_file):
        stats_file.write_text(
            "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
            "<Steps StepsType='dance-single' Difficulty='Hard'>"
            "<HighScoreList><NumTimesPlayed>8</NumTimesPlayed><LastPlayed>2026-02-02</LastPlayed>"
            "<HighScore><PercentDP>0.975</PercentDP><Score>975000</Score><Grade>Tier02</Grade></HighScore>"
            "</HighScoreList></Steps>"
            "</Song></SongScores></Stats>",
            encoding="utf-8")

    def _sync_instance(self, root, rows):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance._snapshot_lock = threading.Lock()
        instance._load_results = queue.Queue()
        instance._snapshot_store = library_data.SnapshotStore(
            root / "library_cache.json", app.HEADERS,
            library_data.LIBRARY_CACHE_SCHEMA_VERSION)
        instance.root = Mock()
        instance.rows = rows
        return instance

    def test_sync_worker_merges_scores_saves_snapshot_and_delivers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self.assertEqual(rows[0]["Score"], 900000)
            self._fresh_stats(stats_file)
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            # The rows carry the fresh scores, the snapshot on disk does too,
            # and the delivery reports one changed chart.
            self.assertEqual(rows[0]["Score"], 975000)
            self.assertEqual(rows[0]["Best %"], 97.5)
            snapshot = json.loads((root / "library_cache.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["rows"][0]["Score"], 975000)
            queued = []
            while not instance._load_results.empty():
                queued.append(instance._load_results.get_nowait())
            synced = [item for item in queued if item[0] == "scores_synced"]
            self.assertEqual(len(synced), 1)
            kind, args, kwargs = synced[0]
            self.assertEqual(args[1], 1)  # one chart changed
            self.assertEqual(kwargs["generation"], 1)
            self.assertTrue(kwargs["refreshed_at"])

    def test_sync_worker_superseded_does_not_save_or_deliver(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self._fresh_stats(stats_file)
            instance = self._sync_instance(root, rows)
            instance._load_generation = 2  # a newer Load / refresh exists
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertFalse((root / "library_cache.json").exists())
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_malformed_stats_fails_without_changes_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            stats_file.write_text("<Stats><SongScores>", encoding="utf-8")
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("malformed", message)
            self.assertTrue(instance._load_results.empty())

    def test_scores_synced_handler_reports_count_and_refreshes_preserving_selection(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        rows = [{"Title": "Song"}]
        instance._scores_synced(rows, 2, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)

        self.assertIs(instance.rows, rows)
        self.assertEqual(instance.last_refreshed_at, "2026-02-02T10:00:00+00:00")
        status = instance.status.set.call_args.args[0]
        self.assertIn("Scores synced · 2 charts updated", status)
        instance.refresh_table.assert_called_once_with(preserve_selection=True)

    def test_scores_synced_handler_reports_up_to_date_when_nothing_changed(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance._scores_synced([], 0, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)
        status = instance.status.set.call_args.args[0]
        self.assertIn("Scores are already up to date", status)
        instance.refresh_table.assert_called_once_with(preserve_selection=True)

    def test_scores_synced_handler_with_cache_error_keeps_old_refresh_stamp(self):
        # A sync whose snapshot was skipped (Stats.xml changed mid-sync)
        # still refreshes the table, but the stamp does not move, so the
        # startup hint fires, and the status says the snapshot was not saved
        # and to sync again for current scores.
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance.progress = Mock()
        instance.status = Mock()
        instance.status.get.return_value = "Scores synced · 1 chart updated."
        instance.refresh_table = Mock()
        instance.last_refreshed_at = "2026-01-01T00:00:00+00:00"
        instance._scores_synced(
            [{"Title": "Song"}], 1, refreshed_at="",
            cache_error="Stats.xml changed during the sync. "
            "Sync again for current scores.", generation=1)
        self.assertEqual(instance.last_refreshed_at, "2026-01-01T00:00:00+00:00")
        status = instance.status.set.call_args.args[0]
        self.assertIn(
            "Local snapshot not saved: Stats.xml changed during the sync", status)
        self.assertIn("Sync again for current scores", status)
        instance.refresh_table.assert_called_once_with(preserve_selection=True)

    def test_scores_synced_handler_drops_stale_generation(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 5
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance._scores_synced([], 1, generation=4)
        instance.progress.stop.assert_not_called()
        instance.status.set.assert_not_called()
        instance.refresh_table.assert_not_called()

    def test_sync_scores_refuses_while_a_scan_is_in_flight(self):
        instance = object.__new__(app.LibraryApp)
        instance._scan_in_flight = True
        instance.rows = [{"Title": "Song"}]
        instance.status = Mock()
        instance.sync_scores()
        instance.status.set.assert_called_once_with(
            "A library load is in progress. Wait for it to finish, then sync scores.")

    def test_sync_scores_refuses_with_no_library_loaded(self):
        instance = object.__new__(app.LibraryApp)
        instance._scan_in_flight = False
        instance.rows = []
        instance.status = Mock()
        instance.sync_scores()
        instance.status.set.assert_called_once_with(
            "No library loaded. Load / refresh first, then sync scores.")

    def test_sync_scores_refuses_when_the_selected_paths_differ(self):
        instance = object.__new__(app.LibraryApp)
        instance._scan_in_flight = False
        instance.rows = [{"Title": "Song"}]
        instance.status = Mock()
        instance.loaded_source_paths = ("/old/cache", "/old/Stats.xml")
        instance.cache_var = Mock()
        instance.cache_var.get.return_value = "/new/cache"
        instance.stats_var = Mock()
        instance.stats_var.get.return_value = "/new/Stats.xml"
        instance.sync_scores()
        instance.status.set.assert_called_once_with(
            "The selected data paths differ from the loaded library. Load / refresh first, then sync scores.")

    def test_sync_scores_refuses_while_a_sync_is_in_flight(self):
        instance = object.__new__(app.LibraryApp)
        instance._scan_in_flight = False
        instance._sync_in_flight = True
        instance.rows = [{"Title": "Song"}]
        instance.status = Mock()
        instance.sync_scores()
        instance.status.set.assert_called_once_with(
            "A scores sync is already in progress. Wait for it to finish, then sync again.")

    def test_sync_scores_sets_the_flag_and_disables_the_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            instance = object.__new__(app.LibraryApp)
            instance._scan_in_flight = False
            instance._sync_in_flight = False
            instance._load_generation = 1
            instance.rows = [{"Title": "Song"}]
            instance.cache_var = Mock()
            instance.cache_var.get.return_value = str(cache_dir)
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.progress = Mock()
            instance.status = Mock()
            instance._file_menu = Mock()
            with patch.object(app.threading, "Thread") as mock_thread:
                instance.sync_scores()
            self.assertTrue(instance._sync_in_flight)
            instance._file_menu.entryconfigure.assert_called_once_with(
                "Sync scores from Stats.xml", state="disabled")
            mock_thread.assert_called_once()

    def test_scores_synced_handler_clears_the_sync_flag_and_re_enables_the_menu(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance._sync_in_flight = True
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance._file_menu = Mock()
        instance._scores_synced([{"Title": "Song"}], 1, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)
        self.assertFalse(instance._sync_in_flight)
        instance._file_menu.entryconfigure.assert_called_once_with(
            "Sync scores from Stats.xml", state="normal")

    def test_scores_sync_failed_handler_clears_the_sync_flag_and_re_enables_the_menu(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance._sync_in_flight = True
        instance.progress = Mock()
        instance.status = Mock()
        instance._file_menu = Mock()
        with patch.object(app, "messagebox"):
            instance._scores_sync_failed("boom", generation=1)
        self.assertFalse(instance._sync_in_flight)
        instance._file_menu.entryconfigure.assert_called_once_with(
            "Sync scores from Stats.xml", state="normal")

    def test_stale_scores_synced_clears_the_flag_but_leaves_the_menu_to_the_scan(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 5
        instance._sync_in_flight = True
        instance.progress = Mock()
        instance.status = Mock()
        instance.refresh_table = Mock()
        instance._file_menu = Mock()
        instance._scores_synced([], 1, generation=4)
        self.assertFalse(instance._sync_in_flight)
        instance._file_menu.entryconfigure.assert_not_called()
        instance.progress.stop.assert_not_called()
        instance.status.set.assert_not_called()
        instance.refresh_table.assert_not_called()

    def test_sync_worker_unexpected_stats_error_fails_without_changes_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            # A bogus encoding in the XML declaration raises LookupError,
            # which is neither ParseError nor OSError.
            stats_file.write_bytes(b'<?xml version="1.0" encoding="not-a-real-codec"?><Stats/>')
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("Could not sync scores", message)
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_missing_stats_file_fails_without_changes_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            missing = root / "Stats-gone.xml"
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, missing, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("Could not read", message)
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_empty_stats_fails_without_blanking_or_save(self):
        # A Stats.xml with no scores at all would blank every score and
        # report success. The sync refuses it instead, so nothing changes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self.assertEqual(rows[0]["Score"], 900000)
            stats_file.write_text("<Stats/>", encoding="utf-8")
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged, not blanked
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("contains no scores", message)
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_empty_song_scores_fails_without_blanking_or_save(self):
        # An empty <SongScores> element is the same shape: no scores.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            stats_file.write_text("<Stats><SongScores/></Stats>", encoding="utf-8")
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged, not blanked
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("contains no scores", message)
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_empty_high_score_list_fails_without_blanking_or_save(self):
        # A HighScoreList with no HighScore entries still lands in the
        # index (plays/last_played only), so the refusal must look for
        # actual score records, not just a non-empty index.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self.assertEqual(rows[0]["Score"], 900000)
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Challenge'>"
                "<HighScoreList><NumTimesPlayed>0</NumTimesPlayed>"
                "<LastPlayed>2026-01-01</LastPlayed>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged, not blanked
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("contains no scores", message)
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_stats_with_no_matching_scores_fails_without_blanking_or_save(self):
        # A Stats.xml with real scores, but none for the songs in this
        # library (for example a profile from another install), would
        # blank every score and report success. The sync refuses it
        # instead, so nothing changes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self.assertEqual(rows[0]["Score"], 900000)
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/OtherPack/OtherSong'>"
                "<Steps StepsType='dance-single' Difficulty='Challenge'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            instance = self._sync_instance(root, rows)
            instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # unchanged, not blanked
            self.assertFalse((root / "library_cache.json").exists())
            kind, message, generation = instance._load_results.get_nowait()
            self.assertEqual((kind, generation), ("scores_sync_failed", 1))
            self.assertIn("no scores for the songs in this library", message)
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_stats_changed_mid_sync_skips_snapshot_but_keeps_rows(self):
        # Stats.xml rewritten between the worker's read and the snapshot
        # write: the merged scores are stale, so the snapshot is not
        # saved (its stamp stays put, so the startup hint fires), but the
        # rows in memory still carry the scores from the read.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self.assertEqual(rows[0]["Score"], 900000)

            real_stats_index = library_data.stats_index

            def stats_index_then_rewrite(stats_path):
                scores = real_stats_index(stats_path)
                self._fresh_stats(stats_path)
                # Force a distinct mtime: the rewrite alone might land in
                # the same filesystem timestamp.
                new_mtime = Path(stats_path).stat().st_mtime + 10
                os.utime(stats_path, (new_mtime, new_mtime))
                return scores

            instance = self._sync_instance(root, rows)
            with patch.object(app, "stats_index", side_effect=stats_index_then_rewrite):
                instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # the pre-change score
            self.assertFalse((root / "library_cache.json").exists())
            kind, args, kwargs = instance._load_results.get_nowait()
            self.assertEqual(kind, "scores_synced")
            self.assertEqual(args[1], 0)  # nothing changed: the read saw the old scores
            self.assertEqual(kwargs["refreshed_at"], "")
            self.assertIn("changed during the sync", kwargs["cache_error"])
            self.assertTrue(instance._load_results.empty())

    def test_sync_worker_stats_vanished_mid_sync_skips_snapshot_but_keeps_rows(self):
        # Stats.xml deleted between the worker's read and the snapshot
        # write: the re-check stat fails, so the snapshot is not saved
        # (its stamp stays put, so the startup hint fires), but the rows
        # in memory still carry the scores from the read.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = self._write_song(root)
            rows, _ = library_data.parse_cache_file(
                cache_dir / "song.cache", library_data.stats_index(stats_file))
            self.assertEqual(rows[0]["Score"], 900000)

            real_stats_index = library_data.stats_index

            def stats_index_then_delete(stats_path):
                scores = real_stats_index(stats_path)
                Path(stats_path).unlink()
                return scores

            instance = self._sync_instance(root, rows)
            with patch.object(app, "stats_index", side_effect=stats_index_then_delete):
                instance._sync_scores_worker(cache_dir, stats_file, rows, generation=1)

            self.assertEqual(rows[0]["Score"], 900000)  # the read score
            self.assertFalse((root / "library_cache.json").exists())
            kind, args, kwargs = instance._load_results.get_nowait()
            self.assertEqual(kind, "scores_synced")
            self.assertEqual(args[1], 0)  # nothing changed: the read saw the old scores
            self.assertEqual(kwargs["refreshed_at"], "")
            self.assertIn("changed during the sync", kwargs["cache_error"])
            self.assertTrue(instance._load_results.empty())

    def test_report_newer_stats_file_hints_when_stats_is_newer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")
            instance = object.__new__(app.LibraryApp)
            instance.last_refreshed_at = "2026-01-01T00:00:00+00:00"
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.status = Mock()
            instance.status.get.return_value = "Showing saved library snapshot."
            instance._report_newer_stats_file()
            status = instance.status.set.call_args.args[0]
            self.assertIn("Stats.xml is newer than the saved library", status)
            self.assertIn("Sync scores from Stats.xml", status)

    def test_report_newer_stats_file_stays_quiet_when_stats_is_older(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")
            instance = object.__new__(app.LibraryApp)
            instance.last_refreshed_at = "2999-01-01T00:00:00+00:00"
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.status = Mock()
            instance._report_newer_stats_file()
            instance.status.set.assert_not_called()

    def test_set_sync_menu_state_configures_the_entry(self):
        instance = object.__new__(app.LibraryApp)
        instance._file_menu = Mock()
        instance._set_sync_menu_state("disabled")
        instance._file_menu.entryconfigure.assert_called_once_with(
            "Sync scores from Stats.xml", state="disabled")

    def test_load_data_marks_a_scan_in_flight_and_disables_the_sync_entry(self):
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
            instance._file_menu = Mock()
            instance._load_generation = 0
            instance._scan_in_flight = False
            with patch.object(app.threading, "Thread") as mock_thread:
                instance.load_data()
            self.assertTrue(instance._scan_in_flight)
            instance._file_menu.entryconfigure.assert_called_once_with(
                "Sync scores from Stats.xml", state="disabled")
            mock_thread.assert_called_once()

    def test_load_failed_clears_the_scan_flag_and_re_enables_the_sync_entry(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance.load_button = Mock()
        instance._file_menu = Mock()
        instance.progress = Mock()
        instance.status = Mock()
        instance._scan_in_flight = True
        with patch.object(app, "messagebox"):
            instance._load_failed("Some error", generation=1)
        self.assertFalse(instance._scan_in_flight)
        instance._file_menu.entryconfigure.assert_called_once_with(
            "Sync scores from Stats.xml", state="normal")

    def test_poll_load_results_delivers_scores_synced_and_failed(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_results = queue.Queue()
        instance._scores_synced = Mock()
        instance._scores_sync_failed = Mock()
        instance.root = Mock()
        instance._load_results.put(("scores_synced", ([], 2), {"refreshed_at": "2026-02-02T10:00:00+00:00", "generation": 1}))
        instance._load_results.put(("scores_sync_failed", "boom", 1))
        instance._poll_load_results()
        instance._scores_synced.assert_called_once_with(
            [], 2, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)
        instance._scores_sync_failed.assert_called_once_with("boom", generation=1)
        instance.root.after.assert_called_once()


class LoadProgressTests(unittest.TestCase):
    """The scan's progress readout: determinate bar, files done, ETA."""

    def make_progress_app(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_generation = 1
        instance._load_started_at = None
        instance.status = _StubStatus()
        instance.progress = MagicMock()
        instance.progress.__getitem__.return_value = "indeterminate"
        return instance

    def test_first_progress_switches_the_bar_to_determinate_and_counts_files(self):
        instance = self.make_progress_app()

        instance._show_load_progress(0, 7000, 1)

        instance.progress.stop.assert_called_once()
        instance.progress.configure.assert_called_once_with(
            mode="determinate", maximum=7000, value=0)
        instance.progress.__setitem__.assert_called_once_with("value", 0)
        self.assertEqual(instance.status.get(), "Reading chart cache… 0 / 7,000 files")

    def test_later_progress_does_not_reconfigure_the_bar(self):
        instance = self.make_progress_app()
        instance.progress.__getitem__.return_value = "determinate"

        instance._show_load_progress(25, 7000, 1)

        instance.progress.stop.assert_not_called()
        instance.progress.configure.assert_not_called()
        instance.progress.__setitem__.assert_called_once_with("value", 25)
        self.assertEqual(instance.status.get(), "Reading chart cache… 25 / 7,000 files")

    def test_eta_appears_once_fifty_files_are_done(self):
        instance = self.make_progress_app()
        instance._load_started_at = time.monotonic() - 10

        instance._show_load_progress(100, 1000, 1)

        # Ten seconds for 100 of 1,000 files: 90 seconds left.
        self.assertEqual(
            instance.status.get(),
            "Reading chart cache… 100 / 1,000 files · about 90 s left")

    def test_no_eta_before_fifty_files_or_at_the_total(self):
        instance = self.make_progress_app()
        instance._load_started_at = time.monotonic() - 10

        instance._show_load_progress(25, 1000, 1)
        self.assertNotIn("s left", instance.status.get())

        instance._show_load_progress(1000, 1000, 1)
        self.assertNotIn("s left", instance.status.get())

    def test_stale_progress_and_phase_are_ignored(self):
        instance = self.make_progress_app()
        instance._load_generation = 2

        instance._show_load_progress(25, 100, 1)
        instance._show_load_phase("Saving snapshot…", 1)

        instance.progress.stop.assert_not_called()
        instance.progress.configure.assert_not_called()
        self.assertEqual(instance.status.get(), "")

    def test_phase_sets_the_status_line(self):
        instance = self.make_progress_app()

        instance._show_load_phase("Saving snapshot…", 1)

        self.assertEqual(instance.status.get(), "Saving snapshot…")

    def test_poll_load_results_routes_progress_and_phase(self):
        instance = object.__new__(app.LibraryApp)
        instance._load_results = queue.Queue()
        instance._show_load_progress = Mock()
        instance._show_load_phase = Mock()
        instance._loaded = Mock()
        instance._load_failed = Mock()
        instance.root = Mock()
        instance._load_results.put(("progress", 25, 100, 1))
        instance._load_results.put(("phase", "Saving snapshot…", 1))

        instance._poll_load_results()

        instance._show_load_progress.assert_called_once_with(25, 100, 1)
        instance._show_load_phase.assert_called_once_with("Saving snapshot…", 1)
        instance._loaded.assert_not_called()
        instance._load_failed.assert_not_called()
        instance.root.after.assert_called_once()
        delay, callback = instance.root.after.call_args[0]
        self.assertEqual(delay, 75)
        self.assertEqual(callback, instance._poll_load_results)


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
        while len(application.rows) == 0 and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        self.assertEqual(len(application.rows), 120)  # 60 files, 2 charts each
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
            instance.rows = [{"Title": "My Song", "Pack": "My Pack", "Subtitle": "(Sunset Mix)"}]
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
