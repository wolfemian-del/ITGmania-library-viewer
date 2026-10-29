import tempfile
import unittest
from pathlib import Path

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
