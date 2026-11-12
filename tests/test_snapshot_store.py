"""Headless tests for the snapshot store (proposal 0008, PR 1).

The store lives in library_data.py and takes no Tk: these tests run
against tmp paths with no app husk. The headers tuple here is a
representative subset of the app's HEADERS — the store validates against
whatever tuple it is given, so the subset pins the logic (including the
"Course path" key the store adds) without importing the window module.
"""

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import library_data
from library_data import SnapshotStore

HEADERS = ("Title", "Subtitle", "Artist", "Pack", "Type", "Difficulty",
           "Meter", "Time", "BPM", "Chart")


class SnapshotStoreTests(unittest.TestCase):
    @staticmethod
    def make_store(directory):
        path = Path(directory) / "library_cache.json"
        return SnapshotStore(path, HEADERS), path

    @staticmethod
    def sample_row():
        return {key: "" for key in (*HEADERS, "Course path")}

    def test_write_read_round_trip_preserves_rows_and_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache" / "Songs"
            stats_file = Path(directory) / "Stats.xml"
            rows = [self.sample_row()]

            refreshed_at = store.write(
                cache_dir, stats_file, rows, 2, 1, 0, True, skipped_blocks=3)
            result = store.read(cache_dir, stats_file)

        self.assertTrue(result.loaded)
        self.assertEqual(result.rows, rows)
        self.assertEqual(result.files, 2)
        self.assertEqual(result.skipped_files, 1)
        self.assertEqual(result.files_without_charts, 0)
        self.assertEqual(result.skipped_blocks, 3)
        self.assertIs(result.nested_song_tree, True)
        self.assertEqual(result.refreshed_at, refreshed_at)
        self.assertIsInstance(result.refreshed_at, str)
        self.assertTrue(result.refreshed_at)
        self.assertEqual(result.source_paths, (str(cache_dir), str(stats_file)))
        self.assertIsNone(result.reason)
        self.assertIsNone(result.detail)

    def test_write_field_order_pin(self):
        # skipped_blocks and nested_song_tree are adjacent positional
        # arguments; if their order were swapped, the payload would carry
        # skipped_blocks=True and nested_song_tree=3, and the read would
        # sanitize them to 0 and False. This pin fails on a swap.
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, [self.sample_row()],
                        1, 0, 0, True, skipped_blocks=3)

            result = store.read(cache_dir, stats_file)

        self.assertEqual(result.skipped_blocks, 3)
        self.assertIs(result.nested_song_tree, True)

    def test_read_missing_snapshot_reports_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)

            result = store.read(Path(directory) / "Cache", Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "missing")
        self.assertIsNone(result.detail)

    def test_read_invalid_utf8_reports_unreadable_with_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            path.write_bytes(b"\xff\xfe not utf-8")

            result = store.read(Path(directory) / "Cache", Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "unreadable")
        self.assertIn("codec can't decode", result.detail)

    def test_read_bad_json_reports_unreadable_with_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            path.write_text("{not json", encoding="utf-8")

            result = store.read(Path(directory) / "Cache", Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "unreadable")
        self.assertIn("Expecting property name", result.detail)

    def test_read_deeply_nested_json_reports_unreadable(self):
        # The depth is 1,000,000 because the limit is version-dependent:
        # 10,000 levels raise on 3.12 but parse on 3.14 (whose C recursion
        # limit is higher), so the depth must exceed every supported
        # version's limit. json.load fails fast at the limit.
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            path.write_text("[" * 1000000 + "]" * 1000000, encoding="utf-8")

            result = store.read(Path(directory) / "Cache", Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "unreadable")
        # Python 3.14's JSON scanner reports the overflow as "Stack overflow ...";
        # earlier versions raise RecursionError ("maximum recursion depth exceeded").
        if sys.version_info >= (3, 14):
            self.assertIn("Stack overflow", result.detail)
        else:
            self.assertIn("recursion", result.detail)

    def test_read_wrong_schema_version_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["schema_version"] = library_data.LIBRARY_CACHE_SCHEMA_VERSION + 1
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = store.read(cache_dir, stats_file)

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")
        self.assertIsNone(result.detail)

    def test_read_schema_version_2_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = store.read(cache_dir, stats_file)

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_row_missing_a_column_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["rows"][0]["Subtitle"]
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = store.read(cache_dir, stats_file)

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_row_missing_course_path_reports_invalid(self):
        # "Course path" is not in HEADERS, so the store must add it to the
        # validation itself; HEADERS alone would accept this row, and
        # course building would then fail on the missing key.
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["rows"][0]["Course path"]
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = store.read(cache_dir, stats_file)

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_different_source_paths_reports_paths_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            stats_file = Path(directory) / "Stats.xml"
            store.write(Path(directory) / "CacheA", stats_file, [self.sample_row()], 1, 0, 0, False)

            result = store.read(Path(directory) / "CacheB", stats_file)

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "paths_mismatch")
        self.assertIsNone(result.detail)

    def test_read_paths_match_after_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            store.write("Cache", "Stats.xml", [self.sample_row()], 1, 0, 0, False)

            result = store.read("./Cache", "./Stats.xml")

        self.assertTrue(result.loaded)

    def test_read_sanitizes_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.update({"files": 2.5, "skipped_files": -1,
                            "files_without_charts": True, "skipped_blocks": "3",
                            "nested_song_tree": 1, "refreshed_at": 123})
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = store.read(cache_dir, stats_file)

        self.assertTrue(result.loaded)
        self.assertEqual(result.files, 0)
        self.assertEqual(result.skipped_files, 0)
        self.assertEqual(result.files_without_charts, 0)
        self.assertEqual(result.skipped_blocks, 0)
        self.assertIs(result.nested_song_tree, False)
        self.assertEqual(result.refreshed_at, "")

    def test_schema_version_parameter_is_honoured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library_cache.json"
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store = SnapshotStore(path, HEADERS, schema_version=99)
            store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)

            self.assertTrue(store.read(cache_dir, stats_file).loaded)
            default_store = SnapshotStore(path, HEADERS)
            self.assertEqual(default_store.read(cache_dir, stats_file).reason, "invalid")

    def test_failed_replace_leaves_no_temp_file(self):
        # The shared helper's finally-unlink: a write that fails after the
        # temp file exists must not leave litter behind.
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            with patch("library_data.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    store.write(cache_dir, stats_file, [self.sample_row()], 1, 0, 0, False)
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_atomic_helper_signature_takes_payload_then_path(self):
        # Proposal 0008 §4.1 pins the helper's signature: the serialized
        # payload first, the target path second.
        parameters = list(inspect.signature(library_data.write_file_atomically).parameters)
        self.assertEqual(parameters, ["text", "path"])

    def test_read_rejects_malformed_payload_shapes_as_invalid(self):
        # The invalid branch guards the payload shape as well as the schema
        # version and row keys: a non-dict top level, a non-list rows, a
        # non-dict row, and non-string source paths are all invalid.
        malformed = [
            ["not", "a", "dict"],
            {"schema_version": 3, "cache_dir": "Cache", "stats_file": "Stats.xml",
             "rows": "not a list"},
            {"schema_version": 3, "cache_dir": "Cache", "stats_file": "Stats.xml",
             "rows": ["not a dict"]},
            {"schema_version": 3, "cache_dir": 123, "stats_file": "Stats.xml", "rows": []},
            {"schema_version": 3, "cache_dir": "Cache", "stats_file": None, "rows": []},
        ]
        for payload in malformed:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                store, path = self.make_store(directory)
                path.write_text(json.dumps(payload), encoding="utf-8")
                result = store.read(Path(directory) / "Cache", Path(directory) / "Stats.xml")
                self.assertFalse(result.loaded)
                self.assertEqual(result.reason, "invalid")

    def test_read_returns_raw_source_paths(self):
        # Revision 3 pins the loaded result to carry the payload's raw,
        # un-normalized source paths: a path with a ".." segment and a
        # trailing slash must come back exactly as written.
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            cache_dir = "Cache/../Cache"
            stats_file = "Stats.xml/"
            store.write(cache_dir, stats_file, [], 0, 0, 0, False)
            result = store.read("./Cache/../Cache", "./Stats.xml/")
        self.assertTrue(result.loaded)
        self.assertEqual(result.source_paths, (cache_dir, stats_file))



if __name__ == "__main__":
    unittest.main()
