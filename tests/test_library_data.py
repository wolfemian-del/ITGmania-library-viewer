import tempfile
import unittest
from pathlib import Path

import library_data as data


class ParsingTests(unittest.TestCase):
    def test_split_path_normalizes_root_relative_paths(self):
        self.assertEqual(data.split_path("Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("/Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("Songs\\Pack\\Song"), "Pack/Song")

    def test_split_path_normalizes_filesystem_absolute_paths(self):
        self.assertEqual(
            data.split_path(r"C:\Games\ITGmania\Songs\Pack\Song"), "Pack/Song")
        self.assertEqual(
            data.split_path("/home/player/ITGmania/Songs/Pack/Song"), "Pack/Song")

    def test_split_path_requires_songs_component(self):
        path = r"C:\Games\MySongs\Pack\Song"
        self.assertEqual(data.split_path(path), "C:/Games/MySongs/Pack/Song")

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
            rows = data.parse_cache_file(cache_file, scores)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Course path"], "Pack/Song")
        self.assertEqual(rows[0]["Score"], 987654)
        self.assertEqual(rows[0]["Best %"], 98.0)
        self.assertEqual(rows[0]["Plays"], 4)

    def test_cache_radar_and_tech_counts_use_their_named_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            radar = list(range(len(data.RADAR_FIELDS))) * 2
            tech = list(range(len(data.TECH_FIELDS))) * 2
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Challenge;\n"
                f"#RADARVALUES:{','.join(map(str, radar))};\n"
                f"#TECHCOUNTS:{','.join(map(str, tech))};\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0]

        self.assertEqual(row["Taps/Holds"], 6)
        self.assertEqual(row["Jumps"], 7)
        self.assertEqual(row["Holds"], 8)
        self.assertEqual(row["Mines"], 9)
        self.assertEqual(row["Hands"], 10)
        self.assertEqual(row["Rolls"], 11)
        self.assertEqual(row["Lifts"], 12)
        for index, field in enumerate(data.TECH_FIELDS):
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
            row = data.parse_cache_file(cache_file, {})[0]

        self.assertEqual(row["Mines"], 9)
        self.assertEqual(row["Hands"], 10)
        self.assertEqual(row["Rolls"], "")
        self.assertEqual(row["Lifts"], "")
        self.assertEqual(row["Crossovers"], 1)
        self.assertEqual(row["HalfCrossovers"], 2)
        self.assertEqual(row["FullCrossovers"], "")
        self.assertEqual(row["Peak NPS"], "")

    def test_cache_peak_nps_is_parsed_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "peak-nps.cache"
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#PEAKNPS:12.5;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0]

        self.assertEqual(row["Peak NPS"], 12.5)

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
            scores = data.stats_index(stats_file)

        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["Score"], "123")

    def test_stats_index_keeps_best_score_across_duplicate_normalized_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='/home/player/ITGmania/Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList NumTimesPlayed='8' LastPlayed='2026-01-01'>"
                "<HighScore><PercentDP>0.99</PercentDP><Score>999</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList NumTimesPlayed='5' LastPlayed='2026-02-01'>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "</SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

        entry = scores[("pack/song", "dance-single", "hard")]
        self.assertEqual(entry["Score"], "999")
        self.assertEqual(entry["PercentDP"], "0.99")

    def test_stats_index_accepts_profile_with_no_song_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text("<Stats />", encoding="utf-8")
            self.assertEqual(data.stats_index(stats_file), {})


class DifficultySortTests(unittest.TestCase):
    def test_difficulty_key_matches_filter_gameplay_order(self):
        values = ["Edit", "Hard", "Challenge", "Medium", "Easy", "Beginner", "Custom"]
        self.assertEqual(
            sorted(values, key=data.difficulty_sort_key),
            ["Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit", "Custom"],
        )

    def test_difficulty_key_is_case_insensitive(self):
        values = ["hard", "Beginner", "EASY"]
        self.assertEqual(sorted(values, key=data.difficulty_sort_key), ["Beginner", "EASY", "hard"])


class CourseModelTests(unittest.TestCase):
    def test_course_song_line_formats_path_and_difficulty(self):
        self.assertEqual(
            data.course_song_line("Pack/Song", "Hard"),
            "#SONG:Pack/Song:Hard:;",
        )

    def test_course_song_lines_from_rows(self):
        rows = [
            {"Course path": "Pack/One", "Difficulty": "Hard"},
            {"Course path": "Pack/Two", "Difficulty": "Challenge"},
        ]
        self.assertEqual(
            data.course_song_lines(rows),
            ["#SONG:Pack/One:Hard:;", "#SONG:Pack/Two:Challenge:;"],
        )

    def test_format_new_course_includes_title_and_trailing_newline(self):
        body = data.format_new_course("My Course", ["#SONG:Pack/One:Hard:;"])
        self.assertEqual(body, "#COURSE:My Course;\n#SONG:Pack/One:Hard:;\n")

    def test_parse_course_text_reads_title_and_songs(self):
        text = (
            "#COURSE:Example;\n"
            "#SONG:Pack/One:Hard:;\n"
            "#SONG:Pack/Two:Challenge:;\n"
        )
        parsed = data.parse_course_text(text)
        self.assertTrue(parsed["has_course"])
        self.assertEqual(parsed["title"], "Example")
        self.assertEqual(
            [(song["path"], song["difficulty"]) for song in parsed["songs"]],
            [("Pack/One", "Hard"), ("Pack/Two", "Challenge")],
        )
        self.assertIsNone(parsed["trailing_risk"])

    def test_course_trailing_risk_detects_mods_after_last_song(self):
        text = "#COURSE:Example;\n#SONG:Pack/One:Hard:;\n#MODS:xmod;\n"
        self.assertEqual(data.course_trailing_risk(text), "MODS")
        self.assertEqual(data.parse_course_text(text)["trailing_risk"], "MODS")

    def test_course_trailing_risk_ignores_directives_before_last_song(self):
        text = "#COURSE:Example;\n#MODS:xmod;\n#SONG:Pack/One:Hard:;\n"
        self.assertIsNone(data.course_trailing_risk(text))

    def test_validate_course_fields_rejects_empty_and_unsafe_text(self):
        self.assertEqual(data.validate_course_fields([]), "Add at least one chart to the course.")
        self.assertEqual(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="",
            ),
            "Enter a title for this course.",
        )
        self.assertEqual(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="   ",
            ),
            "Enter a title for this course.",
        )
        self.assertIn(
            "titles",
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="Bad:Title",
            ).casefold(),
        )
        self.assertIn(
            "paths",
            data.validate_course_fields(
                [{"Course path": "Pack:One", "Difficulty": "Hard"}],
            ).casefold(),
        )
        self.assertIn(
            "difficulties",
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard:Extra"}],
            ).casefold(),
        )
        self.assertIsNone(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
            )
        )
        self.assertIsNone(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="Safe Title",
            )
        )


class CourseAppendTests(unittest.TestCase):
    def test_appends_to_crlf_file_without_rewriting_existing_bytes(self):
        existing = b"#COURSE:Existing;\r\n#SONG:Pack/One:Hard:;\r\n"
        addition = data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])
        self.assertEqual(addition, b"#SONG:Pack/Two:Challenge:;\r\n")
        self.assertEqual(existing + addition,
                         b"#COURSE:Existing;\r\n#SONG:Pack/One:Hard:;\r\n"
                         b"#SONG:Pack/Two:Challenge:;\r\n")

    def test_adds_separator_if_existing_file_has_no_final_newline(self):
        addition = data.course_append_bytes(
            b"#COURSE:Existing;\n#SONG:Pack/One:Hard:;",
            ["#SONG:Pack/Two:Challenge:;"],
        )
        self.assertEqual(addition, b"\n#SONG:Pack/Two:Challenge:;\n")

    def test_refuses_trailing_modifiers(self):
        for directive in ("#MODS:xmod;", "#GAINSECONDS:10;"):
            with self.subTest(directive=directive):
                existing = f"#COURSE:Existing;\n#SONG:Pack/One:Hard:;\n{directive}".encode()
                with self.assertRaisesRegex(ValueError, "ends with"):
                    data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])

    def test_refuses_files_that_are_not_courses(self):
        with self.assertRaisesRegex(ValueError, "#COURSE"):
            data.course_append_bytes(b"#TITLE:Not a course;", ["#SONG:Pack/Two:Challenge:;"])


if __name__ == "__main__":
    unittest.main()
