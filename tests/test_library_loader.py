"""Tests for the LibraryLoader component (proposal 0009 Step 4).

The load/sync engine moved out of LibraryApp into library_loader.py; the
tests that call the engine's methods directly live here (headless). The live
load-progress tests stay in tests/test_library_visualizer.py.
"""
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import library_data
import library_loader as loader
import row_tints
import library_visualizer as app
import data_paths_dialog as dialog


class _StubStatus:
    """A status line without a window: a str behind get/set, like StringVar."""

    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


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


class LibrarySnapshotTests(unittest.TestCase):
    @staticmethod
    def make_app(settings_path, cache_dir, stats_file):
        instance = object.__new__(loader.LibraryLoader)
        instance.settings_path = settings_path
        instance.cache_var = Mock()
        instance.cache_var.get.return_value = str(cache_dir)
        instance.stats_var = Mock()
        instance.stats_var.get.return_value = str(stats_file)
        instance.status = Mock()
        instance.on_nothing_loaded = Mock()
        instance._loaded = Mock()
        # The snapshot store the delegate reads through (proposal 0008):
        # the path is derived from the settings path, as in __init__
        # (library_cache_path was a LibraryApp property; here it is a
        # plain attribute on the loader instance).
        instance.library_cache_path = settings_path.with_name("library_cache.json")
        instance.snapshot_store = library_data.SnapshotStore(
            instance.library_cache_path, app.HEADERS, library_data.LIBRARY_CACHE_SCHEMA_VERSION)
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
            instance.snapshot_store.write(cache_dir, stats_file, rows, 2, 1, 3, True, skipped_blocks=4)

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
            instance.snapshot_store.write(cache_dir, stats_file, rows, 1, 0, 0, False)

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
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
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
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
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
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
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
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            success = "Showing saved library snapshot · 1 charts · last refreshed 2026-11-10 08:00."
            instance.status = _StubStatus(success)

            instance.load_cached_data()

            self.assertEqual(instance.status.get(), success)

    def test_snapshot_is_not_restored_for_different_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = self.make_app(root / "settings.json", root / "CacheB", root / "Stats.xml")
            instance.snapshot_store.write(
                root / "CacheA", root / "Stats.xml", [self.sample_row()], 1, 0, 0, False)

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.on_nothing_loaded.assert_called_once()
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
        instance.on_nothing_loaded.assert_called_once()
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
        instance.on_nothing_loaded.assert_called_once()
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
        instance.on_nothing_loaded.assert_called_once()
        self.assertIn("could not be read", instance.status.set.call_args.args[0])
        # The detail pin (proposal 0008, Revision 3): the status text
        # carries the exception, not just the reason kind.
        self.assertIn("codec can't decode", instance.status.set.call_args.args[0])

    def test_snapshot_is_not_restored_with_an_unsupported_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache", root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            with instance.library_cache_path.open("r+", encoding="utf-8") as handle:
                payload = json.load(handle)
                payload["schema_version"] = library_data.LIBRARY_CACHE_SCHEMA_VERSION + 1
                handle.seek(0)
                json.dump(payload, handle)
                handle.truncate()

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        instance.on_nothing_loaded.assert_called_once()
        self.assertIn("invalid or outdated", instance.status.set.call_args.args[0])

    def test_snapshot_schema_version_2_is_rejected_as_outdated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, stats_file = root / "Cache", root / "Stats.xml"
            instance = self.make_app(root / "settings.json", cache_dir, stats_file)
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
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
            instance.snapshot_store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            with instance.library_cache_path.open("r+", encoding="utf-8") as handle:
                payload = json.load(handle)
                del payload["rows"][0]["Subtitle"]
                handle.seek(0)
                json.dump(payload, handle)
                handle.truncate()

            instance.load_cached_data()

        instance._loaded.assert_not_called()
        self.assertIn("invalid or outdated", instance.status.set.call_args.args[0])



class InitialSnapshotTests(unittest.TestCase):
    """The deferred startup load (startup polish): _load_initial_snapshot is
    the after() callback __init__ schedules so the window paints first."""

    @staticmethod
    def make_instance():
        instance = object.__new__(loader.LibraryLoader)
        instance.progress = Mock()
        instance.load_cached_data = Mock()
        instance._load_generation = 0
        instance.loaded_source_paths = None
        instance.report_discarded_settings = Mock()
        instance.dialog = Mock()
        instance.had_saved_paths = False
        return instance

    def test_it_loads_and_stops_the_progress_bar(self):
        instance = self.make_instance()
        instance._load_initial_snapshot()
        instance.load_cached_data.assert_called_once_with()
        instance.progress.stop.assert_called_once_with()
        instance.report_discarded_settings.assert_called_once_with()
        instance.dialog.maybe_show_first_run.assert_called_once_with(False, False)

    def test_it_does_nothing_when_a_user_scan_has_already_started(self):
        instance = self.make_instance()
        instance._load_generation = 1
        instance._load_initial_snapshot()
        instance.load_cached_data.assert_not_called()
        instance.progress.stop.assert_not_called()
        instance.report_discarded_settings.assert_not_called()
        instance.dialog.maybe_show_first_run.assert_not_called()

    def test_it_stops_the_progress_bar_even_when_loading_fails(self):
        instance = self.make_instance()
        instance.load_cached_data.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            instance._load_initial_snapshot()
        instance.progress.stop.assert_called_once_with()


class SourcePathsChangedTests(unittest.TestCase):
    """The loader's _current_paths_match_loaded and _source_paths_changed:
    whether the selected paths match the loaded snapshot's sources, and the
    status line and dialog note that report the answer."""

    @staticmethod
    def make_instance(cache, stats, loaded=None, rows=(), refreshed_at=""):
        instance = object.__new__(loader.LibraryLoader)
        instance.loaded_source_paths = loaded
        instance.cache_var = Mock()
        instance.cache_var.get.return_value = cache
        instance.stats_var = Mock()
        instance.stats_var.get.return_value = stats
        instance.rows = list(rows)
        instance.last_refreshed_at = refreshed_at
        instance.status = Mock()
        # A real dialog so paths_changed() computes the note from the app's
        # _current_paths_match_loaded; set_note is mocked to record the call
        # (the dialog was never opened, so a real set_note would be a no-op).
        instance.dialog = dialog.DataPathsDialog(
            parent=Mock(), cache_var=instance.cache_var,
            stats_var=instance.stats_var, load_callback=Mock(),
            save_settings=Mock(), button_factory=Mock(), entry_factory=Mock(),
            dpi_scale=1.0,
            paths_match_loaded=lambda: instance._current_paths_match_loaded())
        instance.dialog.set_note = Mock()
        return instance

    def test_no_loaded_snapshot_reports_match(self):
        instance = self.make_instance("/cache", "/stats.xml")
        self.assertTrue(instance._current_paths_match_loaded())

    def test_matching_paths_report_match(self):
        instance = self.make_instance(
            "/cache", "/stats.xml", loaded=("/cache", "/stats.xml"))
        self.assertTrue(instance._current_paths_match_loaded())

    def test_spelling_difference_still_matches(self):
        # _normalized_source_path runs abspath: a "." component in the
        # selected path is the same folder as the saved one. [CODE]
        instance = self.make_instance(
            "/cache/.", "/stats.xml", loaded=("/cache", "/stats.xml"))
        self.assertTrue(instance._current_paths_match_loaded())

    def test_different_cache_path_reports_mismatch(self):
        instance = self.make_instance(
            "/other", "/stats.xml", loaded=("/cache", "/stats.xml"))
        self.assertFalse(instance._current_paths_match_loaded())

    def test_different_stats_path_reports_mismatch(self):
        instance = self.make_instance(
            "/cache", "/other.xml", loaded=("/cache", "/stats.xml"))
        self.assertFalse(instance._current_paths_match_loaded())

    def test_missing_path_variables_report_match(self):
        # A bare instance without path state reports True the same way.
        instance = object.__new__(loader.LibraryLoader)
        instance.loaded_source_paths = ("/cache", "/stats.xml")
        self.assertTrue(instance._current_paths_match_loaded())

    def test_no_loaded_snapshot_leaves_status_and_note_alone(self):
        instance = self.make_instance("/cache", "/stats.xml")

        instance._source_paths_changed()

        instance.status.set.assert_not_called()
        instance.dialog.set_note.assert_not_called()

    def test_matching_paths_show_the_snapshot_line_and_clear_the_note(self):
        instance = self.make_instance(
            "/cache", "/stats.xml", loaded=("/cache", "/stats.xml"),
            rows=[{}, {}, {}])

        instance._source_paths_changed()

        instance.status.set.assert_called_once_with(
            "Showing saved library snapshot · 3 charts · "
            "last refreshed unknown.")
        instance.dialog.set_note.assert_called_once_with("")

    def test_differing_paths_show_the_moved_paths_line_and_the_differ_note(self):
        instance = self.make_instance(
            "/other", "/stats.xml", loaded=("/cache", "/stats.xml"),
            rows=[{}])

        instance._source_paths_changed()

        instance.status.set.assert_called_once_with(
            "Displayed library uses different data paths. Click Load / "
            "refresh to show the selected sources.")
        instance.dialog.set_note.assert_called_once_with(
            dialog.DataPathsDialog._DATA_PATHS_DIFFER_NOTE)


class DiscardedSettingsStatusTests(unittest.TestCase):
    """A settings file that exists but cannot be read is discarded for
    defaults, and the status line must say so once the window is built —
    including after the deferred snapshot load rewrites the status line."""

    def test_deferred_load_reports_discarded_settings_after_the_snapshot_status(self):
        instance = object.__new__(loader.LibraryLoader)
        instance.progress = Mock()
        instance._load_generation = 0
        instance.loaded_source_paths = None
        instance.dialog = Mock()
        instance.had_saved_paths = False
        instance.status = _StubStatus()
        # The callback is the app's real _report_discarded_settings,
        # bound to a bare app instance sharing this status line and
        # settings store (the settings store stays in the shell).
        fake_app = object.__new__(app.LibraryApp)
        fake_app._settings_store = library_data.SettingsStore(Path("settings.json"))
        fake_app._settings_store.last_read_error = "Expecting value: line 1 column 1 (char 0)"
        fake_app.status = instance.status
        instance.report_discarded_settings = (
            app.LibraryApp._report_discarded_settings.__get__(fake_app))

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
        instance = object.__new__(loader.LibraryLoader)
        instance.progress = Mock()
        instance.load_cached_data = Mock()
        instance._load_generation = 1
        instance._settings_store = library_data.SettingsStore(Path("settings.json"))
        instance._settings_store.last_read_error = "Expecting value: line 1 column 1 (char 0)"
        instance.status = _StubStatus("Loading…")

        instance._load_initial_snapshot()

        self.assertEqual(instance.status.get(), "Loading…")
        instance.progress.stop.assert_not_called()


class RefreshGenerationTests(unittest.TestCase):
    def test_load_worker_ignores_superseded_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            (cache_dir / "test.cache").write_text("#SONGFILENAME:Songs/P/S/a.ogg;\n#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n", encoding="utf-8")
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(loader.LibraryLoader)
            instance._load_generation = 2
            instance._load_results = queue.Queue()
            instance.snapshot_store = Mock()
            instance.root = Mock()

            # Run worker with stale generation 1
            instance._load_worker(cache_dir, stats_file, generation=1)

            instance.snapshot_store.write.assert_not_called()
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

            instance = object.__new__(loader.LibraryLoader)
            instance._load_generation = 1
            instance._snapshot_lock = threading.Lock()
            instance._load_results = queue.Queue()
            instance.snapshot_store = Mock()
            instance.root = Mock()

            def newer_refresh_starts_while_parsing(path, scores):
                instance._load_generation = 2  # the only file is parsed, so the scan loop will not notice
                return [], 0

            with patch.object(loader, "parse_cache_file", newer_refresh_starts_while_parsing):
                instance._load_worker(cache_dir, stats_file, generation=1)

            instance.snapshot_store.write.assert_not_called()
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

            instance = object.__new__(loader.LibraryLoader)
            instance.settings_path = root / "settings.json"
            instance.library_cache_path = instance.settings_path.with_name("library_cache.json")
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
            instance.snapshot_store = store
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
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 5
        instance.progress = Mock()
        instance.status = Mock()
        instance.on_library_changed = Mock()
        instance.load_button = Mock()
        instance.set_sync_menu_state = Mock()
        mock_mb = Mock()

        with patch.object(loader, "messagebox", mock_mb):
            # Stale _loaded call (generation 4 < 5)
            instance._loaded([], 0, generation=4)
            instance.progress.stop.assert_not_called()
            instance.on_library_changed.assert_not_called()

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

            instance = object.__new__(loader.LibraryLoader)
            instance._load_generation = 1
            instance._snapshot_lock = threading.Lock()
            instance._load_results = queue.Queue()
            instance.snapshot_store = Mock()
            instance.snapshot_store.write.return_value = "2026-01-01T00:00:00"
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

            instance = object.__new__(loader.LibraryLoader)
            instance._load_generation = 1
            instance._snapshot_lock = threading.Lock()
            instance._load_results = queue.Queue()
            instance.snapshot_store = Mock()
            instance.snapshot_store.write.return_value = "2026-01-01T00:00:00"
            instance.root = Mock()

            row = {"Title": "a"}
            with patch.object(loader, "parse_cache_file", return_value=([row], 3)):
                instance._load_worker(cache_dir, stats_file, generation=1)

            args = instance.snapshot_store.write.call_args.args
            self.assertEqual(args[0], cache_dir)
            self.assertEqual(args[1], stats_file)
            self.assertEqual(args[2], [row])
            self.assertEqual(args[3], 1)  # one cache file scanned
            self.assertEqual(args[4], 0)  # skipped_files
            self.assertEqual(args[5], 0)  # files_without_charts
            self.assertIs(args[6], False)  # nested_song_tree
            self.assertEqual(args[7], 3)  # skipped_blocks

    def test_poll_load_results_delivers_queued_results_and_reschedules(self):
        instance = object.__new__(loader.LibraryLoader)
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

            instance = object.__new__(loader.LibraryLoader)
            instance.cache_var = Mock()
            instance.cache_var.get.return_value = str(cache_dir)
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.save_settings = Mock()
            instance.progress = Mock()
            instance.status = Mock()
            instance.load_button = Mock()
            instance.set_sync_menu_state = Mock()
            instance._load_generation = 0

            with patch.object(loader.threading, "Thread") as mock_thread:
                instance.load_data()

            instance.load_button.configure.assert_called_once_with(state="disabled")
            self.assertEqual(instance._load_generation, 1)
            mock_thread.assert_called_once()
            self.assertEqual(mock_thread.call_args.kwargs["args"][2], 1)


class WorkerWiringTests(unittest.TestCase):
    """load_data and sync_scores hand off to the app's own workers, with the
    current generation captured on the main thread: the wiring the
    LibraryLoader move must preserve."""

    def test_load_data_hands_the_scan_to_the_apps_load_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(loader.LibraryLoader)
            instance.cache_var = Mock()
            instance.cache_var.get.return_value = str(cache_dir)
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.save_settings = Mock()
            instance.progress = Mock()
            instance.status = Mock()
            instance.load_button = Mock()
            instance.set_sync_menu_state = Mock()
            instance._load_generation = 0

            with patch.object(loader.threading, "Thread") as mock_thread:
                instance.load_data()

            self.assertEqual(instance._load_generation, 1)
            mock_thread.assert_called_once()
            target = mock_thread.call_args.kwargs["target"]
            self.assertIs(target.__self__, instance)
            self.assertIs(target.__func__,
                          loader.LibraryLoader._load_worker)
            self.assertEqual(mock_thread.call_args.kwargs["args"],
                             (cache_dir, stats_file, 1))

    def test_sync_scores_hands_the_sync_to_the_apps_sync_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")

            instance = object.__new__(loader.LibraryLoader)
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
            instance.set_sync_menu_state = Mock()

            with patch.object(loader.threading, "Thread") as mock_thread:
                instance.sync_scores()

            self.assertTrue(instance._sync_in_flight)
            mock_thread.assert_called_once()
            target = mock_thread.call_args.kwargs["target"]
            self.assertIs(target.__self__, instance)
            self.assertIs(target.__func__,
                          loader.LibraryLoader._sync_scores_worker)
            self.assertEqual(mock_thread.call_args.kwargs["args"],
                             (cache_dir, stats_file, instance.rows, 1))


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
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance._snapshot_lock = threading.Lock()
        instance._load_results = queue.Queue()
        instance.snapshot_store = library_data.SnapshotStore(
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
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance.progress = Mock()
        instance.status = Mock()
        instance.on_library_changed = Mock()
        instance.set_sync_menu_state = Mock()
        rows = [{"Title": "Song"}]
        instance._scores_synced(rows, 2, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)

        self.assertIs(instance.rows, rows)
        self.assertEqual(instance.last_refreshed_at, "2026-02-02T10:00:00+00:00")
        status = instance.status.set.call_args.args[0]
        self.assertIn("Scores synced · 2 charts updated", status)
        instance.on_library_changed.assert_called_once_with(rows, preserve_selection=True)

    def test_scores_synced_handler_reports_up_to_date_when_nothing_changed(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance.progress = Mock()
        instance.status = Mock()
        instance.on_library_changed = Mock()
        instance.set_sync_menu_state = Mock()
        instance._scores_synced([], 0, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)
        status = instance.status.set.call_args.args[0]
        self.assertIn("Scores are already up to date", status)
        instance.on_library_changed.assert_called_once_with([], preserve_selection=True)

    def test_scores_synced_handler_with_cache_error_keeps_old_refresh_stamp(self):
        # A sync whose snapshot was skipped (Stats.xml changed mid-sync)
        # still refreshes the table, but the stamp does not move, so the
        # startup hint fires, and the status says the snapshot was not saved
        # and to sync again for current scores.
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance.progress = Mock()
        instance.status = Mock()
        instance.status.get.return_value = "Scores synced · 1 chart updated."
        instance.on_library_changed = Mock()
        instance.set_sync_menu_state = Mock()
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
        instance.on_library_changed.assert_called_once_with(
            [{"Title": "Song"}], preserve_selection=True)

    def test_scores_synced_handler_drops_stale_generation(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 5
        instance.progress = Mock()
        instance.status = Mock()
        instance.on_library_changed = Mock()
        instance._scores_synced([], 1, generation=4)
        instance.progress.stop.assert_not_called()
        instance.status.set.assert_not_called()
        instance.on_library_changed.assert_not_called()

    def test_sync_scores_refuses_while_a_scan_is_in_flight(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._scan_in_flight = True
        instance.rows = [{"Title": "Song"}]
        instance.status = Mock()
        instance.sync_scores()
        instance.status.set.assert_called_once_with(
            "A library load is in progress. Wait for it to finish, then sync scores.")

    def test_sync_scores_refuses_with_no_library_loaded(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._scan_in_flight = False
        instance.rows = []
        instance.status = Mock()
        instance.sync_scores()
        instance.status.set.assert_called_once_with(
            "No library loaded. Load / refresh first, then sync scores.")

    def test_sync_scores_refuses_when_the_selected_paths_differ(self):
        instance = object.__new__(loader.LibraryLoader)
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
        instance = object.__new__(loader.LibraryLoader)
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
            instance = object.__new__(loader.LibraryLoader)
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
            instance.set_sync_menu_state = Mock()
            with patch.object(loader.threading, "Thread") as mock_thread:
                instance.sync_scores()
            self.assertTrue(instance._sync_in_flight)
            instance.set_sync_menu_state.assert_called_once_with("disabled")
            mock_thread.assert_called_once()

    def test_scores_synced_handler_clears_the_sync_flag_and_re_enables_the_menu(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance._sync_in_flight = True
        instance.progress = Mock()
        instance.status = Mock()
        instance.on_library_changed = Mock()
        instance.set_sync_menu_state = Mock()
        instance._scores_synced([{"Title": "Song"}], 1, refreshed_at="2026-02-02T10:00:00+00:00", generation=1)
        self.assertFalse(instance._sync_in_flight)
        instance.set_sync_menu_state.assert_called_once_with("normal")

    def test_scores_sync_failed_handler_clears_the_sync_flag_and_re_enables_the_menu(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance._sync_in_flight = True
        instance.progress = Mock()
        instance.status = Mock()
        instance.set_sync_menu_state = Mock()
        with patch.object(loader, "messagebox"):
            instance._scores_sync_failed("boom", generation=1)
        self.assertFalse(instance._sync_in_flight)
        instance.set_sync_menu_state.assert_called_once_with("normal")

    def test_stale_scores_synced_clears_the_flag_but_leaves_the_menu_to_the_scan(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 5
        instance._sync_in_flight = True
        instance.progress = Mock()
        instance.status = Mock()
        instance.on_library_changed = Mock()
        instance.set_sync_menu_state = Mock()
        instance._scores_synced([], 1, generation=4)
        self.assertFalse(instance._sync_in_flight)
        instance.set_sync_menu_state.assert_not_called()
        instance.progress.stop.assert_not_called()
        instance.status.set.assert_not_called()
        instance.on_library_changed.assert_not_called()

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
            with patch.object(loader, "stats_index", side_effect=stats_index_then_rewrite):
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
            with patch.object(loader, "stats_index", side_effect=stats_index_then_delete):
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
            instance = object.__new__(loader.LibraryLoader)
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
            instance = object.__new__(loader.LibraryLoader)
            instance.last_refreshed_at = "2999-01-01T00:00:00+00:00"
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.status = Mock()
            instance._report_newer_stats_file()
            instance.status.set.assert_not_called()

    def test_load_data_marks_a_scan_in_flight_and_disables_the_sync_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")
            instance = object.__new__(loader.LibraryLoader)
            instance.cache_var = Mock()
            instance.cache_var.get.return_value = str(cache_dir)
            instance.stats_var = Mock()
            instance.stats_var.get.return_value = str(stats_file)
            instance.save_settings = Mock()
            instance.progress = Mock()
            instance.status = Mock()
            instance.load_button = Mock()
            instance.set_sync_menu_state = Mock()
            instance._load_generation = 0
            instance._scan_in_flight = False
            with patch.object(loader.threading, "Thread") as mock_thread:
                instance.load_data()
            self.assertTrue(instance._scan_in_flight)
            instance.set_sync_menu_state.assert_called_once_with("disabled")
            mock_thread.assert_called_once()

    def test_load_failed_clears_the_scan_flag_and_re_enables_the_sync_entry(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance.load_button = Mock()
        instance.set_sync_menu_state = Mock()
        instance.progress = Mock()
        instance.status = Mock()
        instance._scan_in_flight = True
        with patch.object(loader, "messagebox"):
            instance._load_failed("Some error", generation=1)
        self.assertFalse(instance._scan_in_flight)
        instance.set_sync_menu_state.assert_called_once_with("normal")

    def test_poll_load_results_delivers_scores_synced_and_failed(self):
        instance = object.__new__(loader.LibraryLoader)
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
        instance = object.__new__(loader.LibraryLoader)
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
        instance = object.__new__(loader.LibraryLoader)
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


def _make_wired_loader(app_instance):
    """A LibraryLoader whose on_library_changed is the app instance's real
    handler, so a load exercises the loader -> app handoff end to end.
    The loader shares the app instance's status, progress, and Load button,
    the way the real __init__ wires them."""
    instance = object.__new__(loader.LibraryLoader)
    instance.status = app_instance.status
    instance.progress = app_instance.progress
    instance.load_button = app_instance.load_button
    instance.set_sync_menu_state = Mock()
    instance.on_library_changed = app_instance._on_library_changed
    instance.on_nothing_loaded = Mock()
    instance.dialog = Mock()
    instance.save_settings = Mock()
    instance.root = Mock()
    instance.report_discarded_settings = Mock()
    instance.had_saved_paths = False
    instance.rows = []
    instance.loaded_source_paths = None
    instance.last_refreshed_at = ""
    instance._load_generation = 0
    instance._scan_in_flight = False
    instance._sync_in_flight = False
    instance._snapshot_lock = threading.Lock()
    instance._load_results = queue.Queue()
    instance._load_started_at = None
    # The app reads its rows through the loader (loader.rows), the way
    # the real __init__ attaches it; the real refresh_table needs this.
    app_instance._loader = instance
    return instance


class LoaderFilterPersistenceTests(unittest.TestCase):
    """The load handoff (proposal 0009 Step 4): the loader's _loaded sets
    the status and counters, and the app's on_library_changed resets the
    Pack/Type/Difficulty dropdowns (proposal 0006's restore rule)."""

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
        loaded = _make_wired_loader(instance)

        loaded._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        self.assertEqual(instance.pack_var.get(), "Pack2")
        self.assertEqual(instance.type_var.get(), "dance-single")
        self.assertEqual(instance.diff_var.get(), "Challenge")
        instance.refresh_table.assert_called_once()

    def test_loaded_reports_skipped_chart_blocks_in_the_summary(self):
        instance = self.make_loaded_instance()
        rows = self.rows(("Pack1", "dance-single", "Hard"), ("Pack2", "dance-single", "Hard"))
        loaded = _make_wired_loader(instance)

        loaded._loaded(rows, len(rows), skipped_blocks=2)

        status = instance.status.set.call_args.args[0]
        self.assertTrue(status.startswith("Scanned 2 files · parsed 2 charts"))
        self.assertIn(" · 2 chart blocks skipped (missing metadata)", status)

    def test_loaded_omits_the_skipped_blocks_fragment_when_zero(self):
        instance = self.make_loaded_instance()
        rows = self.rows(("Pack1", "dance-single", "Hard"))
        loaded = _make_wired_loader(instance)

        loaded._loaded(rows, len(rows))

        self.assertNotIn("chart blocks skipped", instance.status.set.call_args.args[0])

    def test_loaded_falls_back_for_values_missing_from_the_new_library(self):
        instance = self.make_loaded_instance(pack="Gone", type_="gone-type", difficulty="Gone")
        rows = self.rows(("Pack1", "dance-single", "Hard"))
        loaded = _make_wired_loader(instance)

        loaded._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        self.assertEqual(instance.pack_var.get(), "All packs")
        self.assertEqual(instance.type_var.get(), "All types")
        self.assertEqual(instance.diff_var.get(), "All difficulties")
        instance.refresh_table.assert_called_once()

    def test_successive_loads_keep_a_selection_then_fall_back(self):
        instance = self.make_loaded_instance()
        loaded = _make_wired_loader(instance)
        first = self.rows(("Pack1", "dance-single", "Hard"), ("Pack2", "dance-single", "Hard"))
        loaded._loaded(first, len(first), from_cache=True, refreshed_at="2026-01-01T00:00:00")
        instance.pack_var.set("Pack2")

        second = self.rows(("Pack2", "dance-single", "Hard"), ("Pack3", "dance-single", "Hard"))
        loaded._loaded(second, len(second), from_cache=True, refreshed_at="2026-01-01T00:00:00")
        self.assertEqual(instance.pack_var.get(), "Pack2")

        third = self.rows(("Pack3", "dance-single", "Hard"))
        loaded._loaded(third, len(third), from_cache=True, refreshed_at="2026-01-01T00:00:00")
        self.assertEqual(instance.pack_var.get(), "All packs")

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
            loaded = _make_wired_loader(instance)
            loaded._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")
            self.assertEqual(instance.pack_var.get(), "All packs")
            self.add_save_machinery(instance, settings_path)

            instance._save_settings()

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["filter_pack"], "All packs")

    def test_seeded_value_survives_a_startup_that_never_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.make_loaded_instance(type_="dance-double")
            instance.settings_path = Path(directory) / "settings.json"
            loaded = _make_wired_loader(instance)
            # The initial refresh arrives through on_nothing_loaded, wired
            # to the app's real handler, which calls the (mocked) refresh.
            loaded.on_nothing_loaded = instance._on_nothing_loaded
            # load_cached_data reads through the snapshot store (proposal
            # 0008); the missing file returns before the paths are compared,
            # so the variables can stay empty.
            loaded.cache_var = Mock()
            loaded.cache_var.get.return_value = ""
            loaded.stats_var = Mock()
            loaded.stats_var.get.return_value = ""
            loaded.snapshot_store = library_data.SnapshotStore(
                instance.settings_path.with_name("library_cache.json"),
                app.HEADERS, library_data.LIBRARY_CACHE_SCHEMA_VERSION)
            loaded._loaded = Mock()

            loaded.load_cached_data()

            loaded._loaded.assert_not_called()
            self.assertEqual(instance.type_var.get(), "dance-double")
            instance.refresh_table.assert_called_once()


class LoadDeliversRowsTests(unittest.TestCase):
    """The load handoff delivers the rows to the table and the panel through
    the real refresh (Codex, PR #163 review): the direct refresh_table pin
    would still pass if the load completion path stopped refreshing."""

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
        instance.sort_keys = []
        instance.rows = [
            {"Title": "Song A", "Pack": "Pack1", "Type": "dance-single",
             "Difficulty": "Hard", "Grade": "AAA", "Meter": 10, "Time": 60},
            {"Title": "Song B", "Pack": "Pack2", "Type": "dance-double",
             "Difficulty": "Challenge", "Grade": "", "Meter": 12,
             "Time": 90},
        ]
        return instance

    def test_loaded_delivers_the_rows_through_the_real_refresh(self):
        instance = self.make_instance()
        instance.load_button = Mock()
        instance.progress = Mock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.status = Mock()
        instance.course_builder = None
        instance._batched_filter_changes = (
            app.LibraryApp._batched_filter_changes.__get__(instance))
        instance._batching_filter_changes = False
        instance._search_refresh_after_id = None
        loaded = _make_wired_loader(instance)

        with patch.object(app, "ROW_INSERT_BUDGET_SECONDS", 60):
            loaded._loaded(instance.rows, 2)

        self.assertEqual(instance.tree.insert.call_count, 2)
        title_index = list(app.HEADERS).index("Title")
        inserted = [kwargs["values"][title_index]
                    for _args, kwargs in instance.tree.insert.call_args_list]
        self.assertEqual(inserted, ["Song A", "Song B"])
        instance.distribution_panel.show_rows.assert_called_once_with(
            instance.rows)
        instance.count_label.set.assert_called_once_with(
            "2 charts shown · 2 total")


class LoadBatchesFilterChangesTests(unittest.TestCase):
    """_loaded batches the filter changes so the table refreshes exactly
    once, even though three dropdowns change (Step 1 pin, re-pointed at
    the loader)."""

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
        # Tk would run the write traces on each set; simulate them the way
        # the long-standing _loaded pinning test does.
        instance._refresh_unless_batching = app.LibraryApp._refresh_unless_batching.__get__(instance)
        instance.diff_var.set.side_effect = lambda *args: instance._refresh_unless_batching()
        instance.pack_var.set.side_effect = lambda *args: instance._refresh_unless_batching()
        instance.type_var.set.side_effect = lambda *args: instance._refresh_unless_batching()
        loaded = _make_wired_loader(instance)

        rows = [
            {"Title": "Song A", "Pack": "Pack1", "Type": "dance-single", "Difficulty": "Hard"},
            {"Title": "Song B", "Pack": "Pack2", "Type": "dance-double", "Difficulty": "Challenge"},
        ]
        loaded._loaded(rows, len(rows), from_cache=True, refreshed_at="2026-01-01T00:00:00")

        instance.load_button.configure.assert_called_once_with(state="normal")
        instance.refresh_table.assert_called_once()
        instance.pack_var.set.assert_called_with("All packs")
        instance.type_var.set.assert_called_with("All types")
        instance.diff_var.set.assert_called_with("All difficulties")
