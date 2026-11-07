"""End-to-end tests over the synthetic fixture library (issue #52).

The fixtures in tests/fixtures/ are small, fully invented, and written in
the formats ITGmania itself writes: cache text with MSD tags (including a
multi-line #BPMS value and backslash-escaped titles) and a Stats.xml whose
play counts and dates are child elements, as the game writes them (#58).

Unlike the unit tests, which build one cache snippet or one Stats entry at
a time, these tests load the whole fixture library from disk and drive it
through the same chain the app uses: stats_index -> parse_cache_file ->
match_chart_query -> LibraryApp.export_csv. Each past bug in that chain
(#41 multi-line #BPMS, #42 Edit-chart score isolation, #43 apostrophes in
search, #58 Stats.xml fixture shape) has a fixture engineered to catch it
if it comes back; see the mutation notes in FixtureChainTests.
"""

import csv
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import library_data as data
import library_visualizer as app

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture_rows():
    """Parse every fixture cache file against the fixture Stats.xml."""
    scores = data.stats_index(FIXTURES / "Stats.xml")
    rows = []
    for cache_file in sorted(FIXTURES.glob("*.cache")):
        rows.extend(data.parse_cache_file(cache_file, scores))
    return rows


class FixtureLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_fixture_rows()

    def row_for(self, title, difficulty, chart=""):
        matches = [row for row in self.rows
                   if row["Title"] == title and row["Difficulty"] == difficulty
                   and row["Chart"] == chart]
        self.assertEqual(len(matches), 1, f"{title} / {difficulty} / {chart!r}")
        return matches[0]

    def test_whole_library_parses(self):
        self.assertEqual(len(self.rows), 11)
        self.assertEqual(
            {row["Title"] for row in self.rows},
            {"Tempo Tangle", "Hearts ; Arrows", "Double Edit Dilemma",
             "Neon Skyline", "Don't Look Back", "Plain Tune"})
        for row in self.rows:
            self.assertEqual(row["Pack"], "Fixture Pack")

    def test_stats_index_keys_cover_the_scored_charts(self):
        scores = data.stats_index(FIXTURES / "Stats.xml")
        # Seven scored charts; the two Edit charts key separately by
        # description, and Plain Tune is absent entirely (never played).
        self.assertEqual(len(scores), 7)
        self.assertIn(("fixture pack/double edit dilemma", "dance-single",
                       "edit", "alpha edit"), scores)
        self.assertIn(("fixture pack/double edit dilemma", "dance-single",
                       "edit", "beta edit"), scores)
        self.assertFalse(any("plain tune" in key[0] for key in scores))

    def test_multiline_bpms_reach_the_row(self):
        # #41: the fixture's #BPMS value spans three lines, as the game
        # writes long timing lists. A parser that stops at the first line
        # reports a flat 100 BPM here.
        row = self.row_for("Tempo Tangle", "Hard", "Main chart")
        self.assertEqual(row["bpm_min"], 100.0)
        self.assertEqual(row["bpm_max"], 200.0)
        self.assertEqual(row["BPM"], "100–200")

    def test_best_score_and_tap_counts_merge_from_stats(self):
        # The fixture holds two HighScores for this chart; the row must
        # carry the better one (98.23%), not the first or the latest.
        row = self.row_for("Tempo Tangle", "Hard", "Main chart")
        self.assertEqual(row["Score"], 982340)
        self.assertEqual(row["Grade"], "S")
        self.assertEqual(row["Best %"], 98.23)
        self.assertEqual(row["Max combo"], 431)
        self.assertEqual(row["Plays"], 14)
        self.assertEqual(row["Last played"], "2026-10-26")
        self.assertEqual(row["W1"], 400)
        self.assertEqual(row["W2"], 25)
        self.assertEqual(row["Miss"], 1)
        # Chart statistics from the cache side of the same row.
        self.assertEqual(row["Meter"], 10)
        self.assertEqual(row["Time"], 187.4)
        self.assertEqual(row["Peak NPS"], 11.25)
        self.assertEqual(row["Taps/Holds"], 438)
        self.assertEqual(row["Jumps"], 96)
        self.assertEqual(row["Crossovers"], 12)
        self.assertEqual(row["Brackets"], 5)

    def test_escaped_title_and_folder_still_match_their_scores(self):
        # The cache escapes the semicolons in the title and folder
        # (Hearts \; Arrows); Stats.xml stores the decoded path. The score
        # only attaches if both sides normalize to the same key.
        row = self.row_for("Hearts ; Arrows", "Medium")
        self.assertEqual(row["Artist"], "DJ Semicolon")
        self.assertEqual(row["Course path"], "Fixture Pack/Hearts ; Arrows")
        self.assertEqual(row["Score"], 965000)
        self.assertEqual(row["Grade"], "S-")
        self.assertEqual(row["Plays"], 3)

    def test_two_edit_charts_keep_separate_scores(self):
        # #42: two Edit charts in one song, keyed by description.
        alpha = self.row_for("Double Edit Dilemma", "Edit", "Alpha Edit")
        beta = self.row_for("Double Edit Dilemma", "Edit", "Beta Edit")
        self.assertEqual((alpha["Score"], alpha["Grade"], alpha["Best %"], alpha["Plays"]),
                         (975500, "S+", 97.55, 7))
        self.assertEqual((beta["Score"], beta["Grade"], beta["Best %"], beta["Plays"]),
                         (889000, "A", 88.9, 5))
        # The song's Challenge chart is a third, independent score.
        challenge = self.row_for("Double Edit Dilemma", "Challenge")
        self.assertEqual((challenge["Grade"], challenge["Plays"]), ("★", 21))

    def test_routine_chart_uses_first_players_peak_nps(self):
        # #PEAKNPS is written per player for routine charts (9.5|8.75);
        # the row shows player 1. The song also carries a #SUBTITLE,
        # which the viewer does not merge into the title.
        row = self.row_for("Neon Skyline", "Hard")
        self.assertEqual(row["Type"], "dance-routine")
        self.assertEqual(row["Peak NPS"], 9.5)
        self.assertEqual(row["Grade"], "A-")
        self.assertEqual(row["Plays"], 9)

    def test_unplayed_song_has_blank_scores(self):
        for difficulty in ("Beginner", "Medium"):
            row = self.row_for("Plain Tune", difficulty)
            self.assertEqual(row["Score"], "")
            self.assertEqual(row["Grade"], "")
            self.assertEqual(row["Best %"], "")
            self.assertEqual(row["Plays"], 0)
            self.assertEqual(row["Last played"], "")
        # Its single-segment #BPMS and #DISPLAYBPM agree on a flat 120.
        self.assertEqual(self.row_for("Plain Tune", "Beginner")["BPM"], "120")


class FixtureChainTests(unittest.TestCase):
    """The parsed rows, pushed through search and out through CSV export."""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_fixture_rows()

    def matching(self, query):
        return [row for row in self.rows if data.match_chart_query(row, query)]

    def test_apostrophe_title_is_searchable(self):
        # #43, end to end: the title comes out of a cache file, not a
        # hand-built row, and is found by free text, by a quoted title
        # directive, and by its (also apostrophed) artist.
        expected = {("Don't Look Back", "Hard"), ("Don't Look Back", "Challenge")}
        for query in ("don't", 'title:"Don\'t Look Back"', 'artist:"Guns N\' Fixtures"'):
            found = {(row["Title"], row["Difficulty"]) for row in self.matching(query)}
            self.assertEqual(found, expected, query)

    def test_search_filters_compose_over_fixture_rows(self):
        self.assertEqual(len(self.matching('pack:"Fixture Pack"')), 11)
        edits = self.matching("difficulty:Edit")
        self.assertEqual({row["Chart"] for row in edits}, {"Alpha Edit", "Beta Edit"})
        self.assertEqual(len(self.matching("type:dance-routine")), 1)
        # grade:"" is the unplayed set: exactly the charts Stats.xml omits
        # plus the fixture songs' unscored charts.
        unplayed = {(row["Title"], row["Difficulty"]) for row in self.matching('grade:""')}
        self.assertEqual(unplayed, {("Don't Look Back", "Challenge"),
                                     ("Plain Tune", "Beginner"),
                                     ("Plain Tune", "Medium"),
                                     ("Tempo Tangle", "Easy")})
        # A BPM ceiling search sees the multi-line #BPMS range (#41 again,
        # one joint further down the chain).
        fast = {(row["Title"], row["Difficulty"]) for row in self.matching("bpm:>=150")}
        self.assertIn(("Tempo Tangle", "Hard"), fast)
        self.assertIn(("Double Edit Dilemma", "Challenge"), fast)
        self.assertNotIn(("Plain Tune", "Medium"), fast)

    def test_filtered_rows_export_to_csv(self):
        import tempfile
        edits = self.matching("difficulty:Edit")
        with tempfile.TemporaryDirectory() as directory:
            out_file = Path(directory) / "edits.csv"
            instance = object.__new__(app.LibraryApp)
            instance.rows = edits
            instance.status = Mock()
            with patch.object(app, "filedialog",
                              Mock(asksaveasfilename=Mock(return_value=str(out_file)))), \
                 patch.object(app, "messagebox", Mock()):
                instance.export_csv()
            with open(out_file, newline="", encoding="utf-8-sig") as handle:
                exported = list(csv.DictReader(handle))
        self.assertEqual(len(exported), 2)
        by_chart = {row["Chart"]: row for row in exported}
        self.assertEqual(by_chart["Alpha Edit"]["Grade"], "S+")
        self.assertEqual(by_chart["Alpha Edit"]["Title"], "Double Edit Dilemma")
        self.assertEqual(by_chart["Beta Edit"]["Grade"], "A")
        self.assertEqual(by_chart["Beta Edit"]["Best %"], "88.9")


if __name__ == "__main__":
    unittest.main()
