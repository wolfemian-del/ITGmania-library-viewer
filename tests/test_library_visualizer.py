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


if __name__ == "__main__":
    unittest.main()

