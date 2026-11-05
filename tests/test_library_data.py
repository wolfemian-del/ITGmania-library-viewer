import tempfile
import unittest
from pathlib import Path

import library_data as data


class ParsingTests(unittest.TestCase):
    def test_split_path_normalizes_root_relative_paths(self):
        self.assertEqual(data.split_path("Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("/Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("Songs\\Pack\\Song"), "Pack/Song")
        self.assertEqual(data.split_path("AdditionalSongs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("/AdditionalSongs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("AdditionalSongs\\Pack\\Song"), "Pack/Song")

    def test_split_path_case_insensitivity_and_precedence(self):
        self.assertEqual(data.split_path("additionalsongs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("ADDITIONALSONGS/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("songs/Pack/Song"), "Pack/Song")
        # When both occur in a path, the first matching component wins
        self.assertEqual(
            data.split_path("/Archive/Songs/Backup/AdditionalSongs/Pack/Song"),
            "Backup/AdditionalSongs/Pack/Song",
        )
        self.assertEqual(
            data.split_path("/Archive/AdditionalSongs/Backup/Songs/Pack/Song"),
            "Backup/Songs/Pack/Song",
        )

    def test_split_path_normalizes_filesystem_absolute_paths(self):
        self.assertEqual(
            data.split_path(r"C:\Games\ITGmania\Songs\Pack\Song"), "Pack/Song")
        self.assertEqual(
            data.split_path(r"D:\Games\ITGmania\AdditionalSongs\Pack\Song"), "Pack/Song")
        self.assertEqual(
            data.split_path("/home/player/ITGmania/Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(
            data.split_path("/home/player/ITGmania/AdditionalSongs/Pack/Song"), "Pack/Song")

    def test_split_path_requires_songs_or_additionalsongs_component(self):
        path = r"C:\Games\MySongs\Pack\Song"
        self.assertEqual(data.split_path(path), "C:/Games/MySongs/Pack/Song")
        path2 = r"C:\Games\CustomSongs\Pack\Song"
        self.assertEqual(data.split_path(path2), "C:/Games/CustomSongs/Pack/Song")

    def test_tag_map_parses_escaped_delimiters(self):
        text = (
            "#TITLE:Song Title \\; Subtitle;\n"
            "#ARTIST:Artist \\; Feat;\n"
            "#TAG_WITH_BACKSLASH:Prefix\\\\Suffix;\n"
            "#TAG_ENDING_IN_SEMI:Ending with semi\\;;\n"
            "#TAG_WITH_ESCAPED_BACKSLASH_THEN_SEMI:Path\\\\;\n"
            "#NORMAL:NormalValue;\n"
        )
        tags = data.tag_map(text)
        self.assertEqual(tags["TITLE"], "Song Title ; Subtitle")
        self.assertEqual(tags["ARTIST"], "Artist ; Feat")
        self.assertEqual(tags["TAG_WITH_BACKSLASH"], "Prefix\\Suffix")
        self.assertEqual(tags["TAG_ENDING_IN_SEMI"], "Ending with semi;")
        self.assertEqual(tags["TAG_WITH_ESCAPED_BACKSLASH_THEN_SEMI"], "Path\\")
        self.assertEqual(tags["NORMAL"], "NormalValue")

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
            cache_file = Path(directory) / "peak.cache"
            # Single value (legacy/synthetic)
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

            # Piped player sections (ITGmania standard: P1|P2)
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#PEAKNPS:14.250|14.250;\n",
                encoding="utf-8",
            )
            row_piped = data.parse_cache_file(cache_file, {})[0]
            self.assertEqual(row_piped["Peak NPS"], 14.25)

            # Asymmetric piped player sections
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#PEAKNPS:16.8|10.5;\n",
                encoding="utf-8",
            )
            row_asym = data.parse_cache_file(cache_file, {})[0]
            self.assertEqual(row_asym["Peak NPS"], 16.8)

    def test_cache_file_handles_escaped_delimiters_in_title_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "escaped.cache"
            cache_file.write_text(
                "#TITLE:Song Title \\; Subtitle;\n"
                "#ARTIST:Artist \\; Feat;\n"
                "#SONGFILENAME:Songs/Pack/Special \\; Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:9;\n",
                encoding="utf-8",
            )
            scores = {
                ("pack/special ; song", "dance-single", "hard"): {
                    "Score": "950000", "Grade": "Tier06", "PercentDP": "0.95", "plays": "3",
                }
            }
            rows = data.parse_cache_file(cache_file, scores)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Title"], "Song Title ; Subtitle")
            self.assertEqual(rows[0]["Artist"], "Artist ; Feat")
            self.assertEqual(rows[0]["Course path"], "Pack/Special ; Song")
            self.assertEqual(rows[0]["Score"], 950000)

    def test_stats_index_matches_additionalsongs_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='AdditionalSongs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList NumTimesPlayed='3'>"
                "<HighScore><PercentDP>0.96</PercentDP><Score>456</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "</SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["Score"], "456")

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


class BpmTests(unittest.TestCase):
    def test_parse_bpms_single_and_range(self):
        self.assertEqual(data.parse_bpms("0.000=150.000"), (150.0, 150.0))
        self.assertEqual(data.parse_bpms("0.000=100.000,64.000=300.000"), (100.0, 300.0))
        self.assertIsNone(data.parse_bpms(""))
        self.assertIsNone(data.parse_bpms("not-a-bpm"))

    def test_format_bpm_display_prefers_displaybpm(self):
        self.assertEqual(data.format_bpm_display("*", 100, 300), "*")
        self.assertEqual(data.format_bpm_display("180", 100, 300), "180")
        self.assertEqual(data.format_bpm_display("120:180", 100, 300), "120–180")
        self.assertEqual(data.format_bpm_display("", 150, 150), "150")
        self.assertEqual(data.format_bpm_display("", 100, 300), "100–300")
        self.assertEqual(data.format_bpm_display(None, "", ""), "")

    def test_bpm_sort_key_orders_by_max_then_min(self):
        slow_gimmick = {"bpm_min": 100, "bpm_max": 300}
        steady = {"bpm_min": 120, "bpm_max": 150}
        ordered = sorted([steady, slow_gimmick], key=data.bpm_sort_key)
        self.assertEqual(ordered[0], steady)
        self.assertEqual(ordered[1], slow_gimmick)

    def test_cache_exposes_bpm_range(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#BPMS:0.000=100.000,32.000=300.000;\n"
                "#DISPLAYBPM:100:300;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0]
        self.assertEqual(row["BPM"], "100–300")
        self.assertEqual(row["bpm_min"], 100.0)
        self.assertEqual(row["bpm_max"], 300.0)


class GradeSortTests(unittest.TestCase):
    def test_grade_filter_options_are_defined_labels(self):
        self.assertEqual(data.GRADE_OPTIONS, tuple(data.GRADE_NAMES.values()))

    def test_grade_sort_key_follows_tier_order(self):
        grades = ["S-", "S+", "S", "A+", "A", "D", "★★★★"]
        ordered = sorted(grades, key=data.grade_sort_key)
        self.assertEqual(ordered, ["★★★★", "S+", "S", "S-", "A+", "A", "D"])


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


class SearchQueryTests(unittest.TestCase):
    def test_parse_duration_seconds(self):
        self.assertEqual(data.parse_duration_seconds("120"), 120.0)
        self.assertEqual(data.parse_duration_seconds("2:15"), 135.0)
        self.assertEqual(data.parse_duration_seconds("01:30.5"), 90.5)
        self.assertEqual(data.parse_duration_seconds("1:00:10"), 3610.0)
        self.assertIsNone(data.parse_duration_seconds(""))
        self.assertIsNone(data.parse_duration_seconds("not-a-time"))

    def test_parse_numeric_bound_operators_and_ranges(self):
        self.assertEqual(data.parse_numeric_bound("11"), ("==", 11.0))
        self.assertEqual(data.parse_numeric_bound("10-12"), ("range", 10.0, 12.0))
        self.assertEqual(data.parse_numeric_bound("10..12"), ("range", 10.0, 12.0))
        self.assertEqual(data.parse_numeric_bound(">=10"), (">=", 10.0))
        self.assertEqual(data.parse_numeric_bound("<=12"), ("<=", 12.0))
        self.assertEqual(data.parse_numeric_bound(">200"), (">", 200.0))
        self.assertEqual(data.parse_numeric_bound("<150"), ("<", 150.0))
        self.assertEqual(data.parse_numeric_bound("=9", is_duration=False), ("==", 9.0))
        # Durations
        self.assertEqual(data.parse_numeric_bound("1:30-2:30", is_duration=True), ("range", 90.0, 150.0))
        self.assertEqual(data.parse_numeric_bound(">2:00", is_duration=True), (">", 120.0))

    def test_parse_search_query_directives(self):
        q = "Smiley meter:11 bpm:200-300 time:>2:00 diff:Challenge"
        res = data.parse_search_query(q)
        self.assertEqual(res["free_terms"], ["smiley"])
        self.assertEqual(res["free_text"], "smiley")
        self.assertIn(("meter", "11"), res["directives"])
        self.assertIn(("bpm", "200-300"), res["directives"])
        self.assertIn(("time", ">2:00"), res["directives"])
        self.assertIn(("difficulty", "Challenge"), res["directives"])

    def test_parse_search_query_preserves_quoted_free_text_for_round_trip(self):
        parsed = data.parse_search_query('"In The Groove" meter:11')
        self.assertEqual(parsed["free_terms"], ["in the groove"])
        restored = data.parse_search_query(f'{parsed["free_text"]} meter:11')
        self.assertEqual(restored["free_terms"], parsed["free_terms"])
        self.assertIn(("meter", "11"), restored["directives"])

    def test_match_chart_query_meter_exact_and_range(self):
        row = {"Meter": 11, "Title": "Summer", "Artist": "Smiley", "Pack": "ITG"}
        self.assertTrue(data.match_chart_query(row, "meter:11"))
        self.assertTrue(data.match_chart_query(row, "meter:10-12"))
        self.assertTrue(data.match_chart_query(row, "meter:>=10"))
        self.assertFalse(data.match_chart_query(row, "meter:12"))
        self.assertFalse(data.match_chart_query(row, "meter:<10"))

    def test_match_chart_query_bpm_overlap(self):
        row = {"bpm_min": 180.0, "bpm_max": 240.0, "Title": "Speedy"}
        # Queries that overlap with [180, 240]
        self.assertTrue(data.match_chart_query(row, "bpm:200"))
        self.assertTrue(data.match_chart_query(row, "bpm:200-300"))
        self.assertTrue(data.match_chart_query(row, "bpm:>150"))
        self.assertTrue(data.match_chart_query(row, "bpm:<200"))
        # Queries that do NOT overlap
        self.assertFalse(data.match_chart_query(row, "bpm:100-150"))
        self.assertFalse(data.match_chart_query(row, "bpm:>260"))
        self.assertFalse(data.match_chart_query(row, "bpm:<170"))

    def test_match_chart_query_does_not_crash_when_bpm_is_missing(self):
        row = {"bpm_min": "", "bpm_max": ""}
        self.assertFalse(data.match_chart_query(row, "bpm:200"))
        self.assertFalse(data.match_chart_query(row, "bpm:180-220"))

    def test_match_chart_query_duration_seconds_and_mmss(self):
        row = {"Time": 135.0, "Title": "Song"}
        self.assertTrue(data.match_chart_query(row, "time:>120"))
        self.assertTrue(data.match_chart_query(row, "time:>2:00"))
        self.assertTrue(data.match_chart_query(row, "time:2:00-2:30"))
        self.assertFalse(data.match_chart_query(row, "time:<2:00"))
        self.assertFalse(data.match_chart_query(row, "time:>150"))

    def test_match_chart_query_free_text_and_combined(self):
        row = {
            "Title": "Delirium",
            "Artist": "Smiley",
            "Pack": "In The Groove",
            "Meter": 12,
            "bpm_min": 240.0,
            "bpm_max": 240.0,
            "Time": 115.0,
            "Difficulty": "Challenge",
            "Type": "dance-single",
            "Grade": "S+",
            "Best %": 98.5,
        }
        self.assertTrue(data.match_chart_query(row, "Smiley meter:12"))
        self.assertTrue(data.match_chart_query(row, "delirium bpm:>200 time:<2:00"))
        self.assertTrue(data.match_chart_query(row, 'pack:"in the groove" grade:>=S'))
        self.assertFalse(data.match_chart_query(row, "Smiley meter:10"))
        self.assertFalse(data.match_chart_query(row, "Vertex"))

    def test_score_and_percent_directives_use_their_own_columns(self):
        row = {"Score": 950000, "Best %": 95.0}
        self.assertTrue(data.match_chart_query(row, "score:>=900000"))
        self.assertFalse(data.match_chart_query(row, "score:>=960000"))
        self.assertTrue(data.match_chart_query(row, "percent:>=95"))
        self.assertFalse(data.match_chart_query(row, "percent:>=96"))




class AdvancedSearchDialogTests(unittest.TestCase):
    """The Advanced Search dialog must never drop or change a filter it cannot show."""

    ROWS = [
        {"Title": "Alpha Song", "Artist": "Ann", "Pack": "Pack One", "Difficulty": "Hard",
         "Meter": 10, "bpm_min": 150.0, "bpm_max": 150.0, "Time": 90.0, "Peak NPS": 12.0,
         "Grade": "S", "Best %": 95.0, "Plays": 4, "Jacks": 2},
        {"Title": "Beta Song", "Artist": "Bob", "Pack": "Pack Two", "Difficulty": "Challenge",
         "Meter": 12, "bpm_min": 120.0, "bpm_max": 180.0, "Time": 150.0, "Peak NPS": 15.5,
         "Grade": "B", "Best %": 70.0, "Plays": 1, "Jacks": 0},
        {"Title": "Gamma Song", "Artist": "Cy", "Pack": "Pack One", "Difficulty": "Easy",
         "Meter": 5, "bpm_min": 90.0, "bpm_max": 90.0, "Time": 75.0, "Peak NPS": 4.0,
         "Grade": "", "Best %": "", "Plays": 0, "Jacks": 0},
    ]

    def matches(self, query):
        return [row["Title"] for row in self.ROWS if data.match_chart_query(row, query)]

    def round_trip(self, query):
        return data.build_dialog_query(data.split_dialog_query(query))

    def test_filters_without_a_box_are_kept(self):
        parts = data.split_dialog_query("jacks:>0 plays:>=3 type:single diff:hard pack:One")
        self.assertEqual(parts["pack"], "One")
        self.assertEqual(parts["other"], "jacks:>0 plays:>=3 type:single difficulty:hard")

    def test_peak_nps_loads_into_its_boxes(self):
        parts = data.split_dialog_query("nps:>=10 nps:<=20")
        self.assertEqual(parts["peak_nps"], ("10", "20"))
        self.assertEqual(parts["other"], "")

    def test_filters_the_boxes_would_change_are_kept(self):
        for query in ("grade:<B", "grade:S", "grade:>S", "meter:>10", "bpm:<150",
                      "time:<=90.5", "grade:>=Zzz", "meter:abc", "bpm:"):
            with self.subTest(query=query):
                parts = data.split_dialog_query(query)
                self.assertEqual(parts["other"], query)
                self.assertEqual(parts["grade"], "")
                self.assertEqual(parts["meter"] + parts["bpm"] + parts["time"], ("",) * 6)

    def test_second_filter_for_a_taken_box_is_kept(self):
        parts = data.split_dialog_query("meter:>=8 meter:>=10 title:a title:b")
        self.assertEqual(parts["meter"], ("8", ""))
        self.assertEqual(parts["title"], "a")
        self.assertEqual(parts["other"], "meter:>=10 title:b")

    def test_values_with_spaces_stay_quoted(self):
        parts = data.split_dialog_query('title:"Alpha Song" plays:">= 3" artist:"a b"')
        self.assertEqual(parts["title"], "Alpha Song")
        self.assertEqual(parts["artist"], "a b")
        self.assertEqual(data.build_dialog_query(parts),
                         'title:"Alpha Song" artist:"a b" plays:">= 3"')

    def test_grade_label_is_matched_without_regard_to_case(self):
        self.assertEqual(data.split_dialog_query("grade:>=s")["grade"], "S")
        self.assertEqual(data.split_dialog_query("grade:>=S+")["grade"], "S+")

    def test_building_from_boxes_matches_the_old_dialog_output(self):
        parts = {"free_text": "song", "title": "Alpha Song", "pack": "One",
                 "meter": ("8", "12"), "bpm": ("140", ""), "time": ("1:00", "1:00"),
                 "peak_nps": ("", "20"), "grade": "A", "other": "plays:>=1"}
        self.assertEqual(
            data.build_dialog_query(parts),
            'song title:"Alpha Song" pack:One meter:8-12 bpm:>=140 time:1:00 nps:<=20 '
            'grade:>=A plays:>=1')
        self.assertEqual(data.build_dialog_query({"grade": "Any"}), "")

    def test_applying_the_dialog_never_changes_which_charts_match(self):
        queries = (
            "jacks:>0 plays:>=3", "grade:<B", "grade:S", "grade:>=B", "meter:>10", "meter:10-12",
            "meter:>=5 meter:<=10", "bpm:>=140 bpm:<=160", "bpm:150", "time:<=1:30", "time:<=90.5",
            "nps:>=10", "nps:>10", "title:song artist:ann pack:one", 'pack:"pack one" percent:>80',
            "song meter:>=8 score:>0 diff:hard", "percent:<50", "bpm:", "grade:", "alpha beta",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.matches(self.round_trip(query)), self.matches(query))

    def test_a_second_trip_through_the_dialog_changes_nothing(self):
        for query in ("jacks:>0 meter:>=8 meter:<=12 grade:>=B grade:<S title:alpha",
                      'artist:"a b" plays:">= 3" time:1:00-2:00'):
            with self.subTest(query=query):
                once = self.round_trip(query)
                self.assertEqual(self.round_trip(once), once)
