import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import library_visualizer as app


class ParsingTests(unittest.TestCase):
    def test_split_path_normalizes_separators_and_prefix(self):
        self.assertEqual(app.split_path(r"Songs\Pack\Song"), "Pack/Song")

    def test_cache_chart_matches_stats_by_normalized_key(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#MUSICLENGTH:123;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            scores = {
                ("pack/song", "dance-single", "hard"): {
                    "Score": "987654", "Grade": "Tier05", "PercentDP": "0.98", "plays": "4",
                }
            }
            rows = app.parse_cache_file(cache_file, scores)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Course path"], "Pack/Song")
        self.assertEqual(rows[0]["Score"], 987654)
        self.assertEqual(rows[0]["Best %"], 98.0)
        self.assertEqual(rows[0]["Plays"], 4)

    def test_cache_radar_and_tech_counts_use_their_named_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            radar = list(range(len(app.RADAR_FIELDS))) * 2
            tech = list(range(len(app.TECH_FIELDS))) * 2
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Challenge;\n"
                f"#RADARVALUES:{','.join(map(str, radar))};\n"
                f"#TECHCOUNTS:{','.join(map(str, tech))};\n",
                encoding="utf-8",
            )
            row = app.parse_cache_file(cache_file, {})[0]

        self.assertEqual(row["Taps/Holds"], 6)
        self.assertEqual(row["Jumps"], 7)
        self.assertEqual(row["Holds"], 8)
        self.assertEqual(row["Mines"], 9)
        self.assertEqual(row["Hands"], 10)
        self.assertEqual(row["Rolls"], 11)
        self.assertEqual(row["Lifts"], 12)
        for index, field in enumerate(app.TECH_FIELDS):
            self.assertEqual(row[field], index)

    def test_cache_short_radar_and_tech_lists_leave_missing_values_blank(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "short.cache"
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Challenge;\n"
                "#RADARVALUES:0,1,2,3,4,5,6,7,8,9,10;\n"
                "#TECHCOUNTS:1,2;\n",
                encoding="utf-8",
            )
            row = app.parse_cache_file(cache_file, {})[0]

        self.assertEqual(row["Mines"], 9)
        self.assertEqual(row["Hands"], 10)
        self.assertEqual(row["Rolls"], "")
        self.assertEqual(row["Lifts"], "")
        self.assertEqual(row["Crossovers"], 1)
        self.assertEqual(row["HalfCrossovers"], 2)
        self.assertEqual(row["FullCrossovers"], "")

    def test_stats_index_reads_score_and_ignores_case_in_matching_key(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'><HighScoreList NumTimesPlayed='2'>"
                "<HighScore><PercentDP>0.97</PercentDP><Score>123</Score></HighScore>"
                "</HighScoreList></Steps></Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = app.stats_index(stats_file)

        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["Score"], "123")

    def test_stats_index_accepts_profile_with_no_song_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text("<Stats />", encoding="utf-8")
            self.assertEqual(app.stats_index(stats_file), {})


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


class DifficultySortTests(unittest.TestCase):
    def test_difficulty_key_matches_filter_gameplay_order(self):
        values = ["Edit", "Hard", "Challenge", "Medium", "Easy", "Beginner", "Custom"]
        self.assertEqual(
            sorted(values, key=app.difficulty_sort_key),
            ["Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit", "Custom"],
        )

    def test_difficulty_key_is_case_insensitive(self):
        values = ["hard", "Beginner", "EASY"]
        self.assertEqual(sorted(values, key=app.difficulty_sort_key), ["Beginner", "EASY", "hard"])


class CourseAppendTests(unittest.TestCase):
    def test_appends_to_crlf_file_without_rewriting_existing_bytes(self):
        existing = b"#COURSE:Existing;\r\n#SONG:Pack/One:Hard:;\r\n"
        addition = app.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])
        self.assertEqual(addition, b"#SONG:Pack/Two:Challenge:;\r\n")
        self.assertEqual(existing + addition,
                         b"#COURSE:Existing;\r\n#SONG:Pack/One:Hard:;\r\n"
                         b"#SONG:Pack/Two:Challenge:;\r\n")

    def test_adds_separator_if_existing_file_has_no_final_newline(self):
        addition = app.course_append_bytes(
            b"#COURSE:Existing;\n#SONG:Pack/One:Hard:;",
            ["#SONG:Pack/Two:Challenge:;"],
        )
        self.assertEqual(addition, b"\n#SONG:Pack/Two:Challenge:;\n")

    def test_refuses_trailing_modifiers(self):
        for directive in ("#MODS:xmod;", "#GAINSECONDS:10;"):
            with self.subTest(directive=directive):
                existing = f"#COURSE:Existing;\n#SONG:Pack/One:Hard:;\n{directive}".encode()
                with self.assertRaisesRegex(ValueError, "ends with"):
                    app.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])

    def test_refuses_files_that_are_not_courses(self):
        with self.assertRaisesRegex(ValueError, "#COURSE"):
            app.course_append_bytes(b"#TITLE:Not a course;", ["#SONG:Pack/Two:Challenge:;"])


if __name__ == "__main__":
    unittest.main()
