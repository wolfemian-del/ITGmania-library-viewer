import importlib.util
import unittest
import library_data as data


class DistributionTests(unittest.TestCase):
    def test_replace_search_directive_basic(self):
        # Basic replacement
        res = data.replace_search_directive("Smiley meter:10", "meter", "12")
        self.assertEqual(res, "Smiley meter:12")

        # Alias replacement (m -> meter)
        res = data.replace_search_directive("Smiley m:10", "meter", "12")
        self.assertEqual(res, "Smiley meter:12")

        # Append when not present
        res = data.replace_search_directive("Smiley", "meter", "11")
        self.assertEqual(res, "Smiley meter:11")

        # Empty initial query
        res = data.replace_search_directive("", "meter", "11")
        self.assertEqual(res, "meter:11")

    def test_replace_search_directive_removal(self):
        # Remove directive preserving free text
        res = data.replace_search_directive("Smiley meter:10 bpm:>180", "meter", None)
        self.assertEqual(res, "Smiley bpm:>180")

        # Remove alias
        res = data.replace_search_directive("Smiley m:10", "meter", None)
        self.assertEqual(res, "Smiley")

        # Remove when not present
        res = data.replace_search_directive("Smiley", "meter", None)
        self.assertEqual(res, "Smiley")

    def test_replace_search_directive_complex_and_quotes(self):
        # Quoted pack name with spaces and other directives
        query = 'artist:Smiley pack:"In The Groove" meter:10 bpm:>180'
        res = data.replace_search_directive(query, "meter", "11")
        self.assertEqual(res, 'artist:Smiley pack:"In The Groove" meter:11 bpm:>180')

        # Quoted value insertion
        res = data.replace_search_directive("meter:10", "pack", "In The Groove")
        self.assertEqual(res, 'meter:10 pack:"In The Groove"')

        # Removal with quotes preserved
        res = data.replace_search_directive('pack:"In The Groove" bpm:140-159', "bpm", None)
        self.assertEqual(res, 'pack:"In The Groove"')

    @staticmethod
    def search_meaning(query):
        """What the search reads from a query: its free-text terms and its directives."""
        parsed = data.parse_search_query(query)
        return tuple(parsed["free_terms"]), sorted(parsed["directives"])

    def assert_rewrite_keeps_meaning(self, query, target, value, new_values):
        """The rewritten query must read as the original with only the target field's directives swapped."""
        free, directives = self.search_meaning(query)
        field = data.SEARCH_FIELD_ALIASES[target]
        expected = (free, sorted([d for d in directives if d[0] != field] + [(field, v) for v in new_values]))
        rewritten = data.replace_search_directive(query, target, value)
        self.assertEqual(self.search_meaning(rewritten), expected, f"{query!r} -> {rewritten!r}")
        return rewritten

    def test_quoted_phrase_with_a_colon_stays_one_phrase(self):
        # A space before the colon used to split the phrase when the query was rewritten.
        for phrase in ('"Dance Dance: Revolution"', '"Mr. Wonderful: Remix"'):
            rewritten = self.assert_rewrite_keeps_meaning(f"{phrase} meter:11", "meter", None, [])
            self.assertEqual(rewritten, phrase)
            rewritten = self.assert_rewrite_keeps_meaning(phrase, "meter", "12", ["12"])
            self.assertEqual(rewritten, f"{phrase} meter:12")

        # The search already reads a quoted "pack: foo" as a pack filter; the rewrite must not change that.
        self.assert_rewrite_keeps_meaning('"pack: foo" meter:11', "meter", None, [])
        self.assert_rewrite_keeps_meaning('"my pack: foo" meter:11', "meter", None, [])

    def test_quote_for_search_reads_back_unchanged(self):
        for text in ("plain", "two words", 'say "hi"', "it's", "back\\slash", 'a: "b" \\ c', ""):
            self.assertEqual(data.split_search_query(data._quote_for_search(text)) or [""], [text], repr(text))
        self.assertEqual(data._quote_for_search("plain"), "plain")
        self.assertEqual(data._quote_for_search("it's"), "it's")

    def test_rewrite_with_an_unbalanced_quote_keeps_meaning(self):
        # parse_search_query splits on spaces when a quote is never closed, so these are plain words.
        self.assertEqual(data.replace_search_directive("don't stop meter:3", "meter", None), "don't stop")
        # Removing the word that held the stray quote must not change how the rest is read.
        for query in ("m:' :'title'", 'meter::"x ya""'):
            self.assert_rewrite_keeps_meaning(query, "meter", None, [])
        # A new value with a space cannot live in a space-split query, so the quotes are escaped instead.
        self.assert_rewrite_keeps_meaning(' >10 "foo', "pack", "In The Groove", ["In The Groove"])

    def test_rewrite_keeps_meaning_on_random_queries(self):
        import random
        rng = random.Random(2026)
        pieces = ["a", "b", "foo", "pack", "title", "bpm", "meter", "m", "diff", ":", ":", " ", " ",
                  '"', "'", "11", ">10", "x y", "\\"]
        targets = [("meter", None, []), ("meter", "12", ["12"]), ("bpm", (">=120", "<140"), [">=120", "<140"]),
                   ("diff", "Hard", ["Hard"]), ("pack", "In The Groove", ["In The Groove"])]
        for _ in range(3000):
            query = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 9)))
            for target, value, new_values in targets:
                self.assert_rewrite_keeps_meaning(query, target, value, new_values)

    def test_aggregate_meter_distribution(self):
        rows = [
            {"Meter": 10},
            {"Meter": "10.0"},
            {"Meter": "11"},
            {"Meter": "11.5"},
            {"Meter": ""},
            {"Meter": None},
            {"Meter": "invalid"},
        ]
        dist = data.aggregate_meter_distribution(rows, active_val="10")
        # 10 has 2, 11 has 1, 11.5 has 1, ? has 3
        labels = [item[0] for item in dist]
        counts = {item[0]: item[1] for item in dist}
        actives = {item[0]: item[3] for item in dist}

        self.assertIn("10", labels)
        self.assertEqual(counts["10"], 2)
        self.assertTrue(actives["10"])

        self.assertIn("11", labels)
        self.assertEqual(counts["11"], 1)
        self.assertFalse(actives["11"])

        self.assertIn("11.5", labels)
        self.assertEqual(counts["11.5"], 1)

        self.assertIn("?", labels)
        self.assertEqual(counts["?"], 3)
        # ? is non-interactive (filter_token is empty string)
        self.assertEqual(dict(zip([d[0] for d in dist], [d[2] for d in dist]))["?"], "")

    def test_chart_without_a_meter_tag_gets_a_clickable_zero_bar(self):
        # parse_cache_file stores a missing METER tag as 0, so real data never reaches the "?" bar.
        self.assertEqual(data.number(None), 0.0)
        rows = [{"Meter": data.number(None)}, {"Meter": data.number("11")}]
        dist = {label: (count, token) for label, count, token, _ in data.aggregate_meter_distribution(rows)}
        self.assertEqual(dist["0"], (1, "0"))
        self.assertNotIn("?", dist)
        # The bar's number equals the rows the table shows after clicking it.
        query = data.parse_search_query(data.replace_search_directive("", "meter", dist["0"][1]))
        self.assertEqual(sum(data.match_chart_query(row, query) for row in rows), dist["0"][0])

    def test_aggregate_difficulty_distribution(self):
        rows = [
            {"Difficulty": "Beginner"},
            {"Difficulty": "Challenge"},
            {"Difficulty": "Challenge"},
            {"Difficulty": "challenge"},  # case-insensitive
            {"Difficulty": "Hard"},
        ]
        dist = data.aggregate_difficulty_distribution(rows, active_val="Challenge")
        counts = {item[0]: item[1] for item in dist}
        actives = {item[0]: item[3] for item in dist}

        self.assertEqual(counts["Beginner"], 1)
        self.assertEqual(counts["Easy"], 0)
        self.assertEqual(counts["Medium"], 0)
        self.assertEqual(counts["Hard"], 1)
        self.assertEqual(counts["Challenge"], 3)
        self.assertEqual(counts["Edit"], 0)

        self.assertTrue(actives["Challenge"])
        self.assertFalse(actives["Hard"])

        # Order must match DIFFICULTY_ORDER
        diff_order = [item[0] for item in dist[:6]]
        self.assertEqual(diff_order, list(data.DIFFICULTY_ORDER))

    @staticmethod
    def bpm_row(low, high=None):
        return {"bpm_min": low, "bpm_max": low if high is None else high}

    def test_aggregate_bpm_distribution(self):
        rows = [
            self.bpm_row(100),       # <120
            self.bpm_row("130"),     # 120-139
            self.bpm_row(145.5),     # 140-159
            self.bpm_row(170),       # 160-179
            self.bpm_row(190),       # 180-199
            self.bpm_row(220),       # 200+
            {"bpm_min": None, "bpm_max": None},   # ?
            {"bpm_min": "err", "bpm_max": "err"}, # ?
        ]
        dist = data.aggregate_bpm_distribution(rows, active_val=">=120 <140")
        counts = {item[0]: item[1] for item in dist}
        tokens = {item[0]: item[2] for item in dist}
        actives = {item[0]: item[3] for item in dist}

        self.assertEqual(counts["<120"], 1)
        self.assertEqual(tokens["<120"], ("<120",))

        self.assertEqual(counts["120-139"], 1)
        self.assertEqual(tokens["120-139"], (">=120", "<140"))
        self.assertTrue(actives["120-139"])
        self.assertFalse(actives["140-159"])

        self.assertEqual(counts["140-159"], 1)
        self.assertEqual(counts["160-179"], 1)
        self.assertEqual(counts["180-199"], 1)
        self.assertEqual(counts["200+"], 1)
        self.assertEqual(tokens["200+"], (">=200",))

        self.assertEqual(counts["?"], 2)
        self.assertEqual(tokens["?"], "")

    def test_bpm_chart_counts_variable_tempo_in_every_range_it_touches(self):
        rows = [
            self.bpm_row(100, 150),   # touches <120, 120-139, 140-159
            self.bpm_row(139.5),      # 120-139 only
            self.bpm_row(140),        # 140-159 only (ranges are half-open)
        ]
        counts = {label: count for label, count, *_ in data.aggregate_bpm_distribution(rows)}
        self.assertEqual(counts["<120"], 1)
        self.assertEqual(counts["120-139"], 2)
        self.assertEqual(counts["140-159"], 2)
        self.assertEqual(counts["160-179"], 0)

    def test_bpm_bar_count_equals_rows_after_clicking_the_bar(self):
        """Every bar's number must equal the rows its own filter returns."""
        rows = [
            self.bpm_row(low, high)
            for low, high in [
                (100, 150), (90, 110), (120, 250), (139.5, 139.5), (140, 140), (120, 120),
                (119.99, 119.99), (60, 300), (200, 200), (199.5, 200.5), (150, 150),
            ]
        ]
        for label, count, token, _ in data.aggregate_bpm_distribution(rows):
            if not token:
                continue
            query = data.replace_search_directive("", "bpm", token)
            matched = sum(data.match_chart_query(row, data.parse_search_query(query)) for row in rows)
            self.assertEqual(matched, count, f"bar {label} ({query})")

    def test_replace_search_directive_with_several_values(self):
        res = data.replace_search_directive("Smiley bpm:150 meter:11", "bpm", (">=120", "<140"))
        self.assertEqual(res, "Smiley bpm:>=120 bpm:<140 meter:11")
        # Replacing again swaps both directives, and None removes both.
        res = data.replace_search_directive(res, "bpm", (">=140", "<160"))
        self.assertEqual(res, "Smiley bpm:>=140 bpm:<160 meter:11")
        self.assertEqual(data.replace_search_directive(res, "bpm", None), "Smiley meter:11")
        self.assertEqual(data.replace_search_directive("", "bpm", (">=120", "<140")), "bpm:>=120 bpm:<140")

    def test_filter_token_text(self):
        self.assertEqual(data.filter_token_text("11"), "11")
        self.assertEqual(data.filter_token_text((">=120", "<140")), ">=120 <140")
        self.assertEqual(data.filter_token_text(""), "")

    def test_filter_texts_match_ignores_number_format_and_order(self):
        match = data.filter_texts_match
        # Numbers are read the way the search reads them.
        self.assertTrue(match("11.0", "11"))
        self.assertTrue(match("=11", "11"))
        self.assertFalse(match("12", "11"))
        # The order of several values does not matter, and a bar's token tuple is accepted.
        self.assertTrue(match("<140 >=120", (">=120", "<140")))
        self.assertTrue(match(">=120.0 <140.0", ">=120 <140"))
        # Different operators or a missing half are different filters.
        self.assertFalse(match(">=120", ">120"))
        self.assertFalse(match(">=120", (">=120", "<140")))
        # A typed inclusive range is not the same filter as the half-open bar.
        self.assertFalse(match("120-139", (">=120", "<140")))
        # Names are compared ignoring case; empty text never matches.
        self.assertTrue(match("hard", "Hard"))
        self.assertFalse(match("", ""))
        self.assertFalse(match("", "11"))

    def test_bars_highlight_for_filters_typed_a_different_way(self):
        meter_bars = data.aggregate_meter_distribution([{"Meter": 11.0}, {"Meter": 10.0}], active_val="11.0")
        self.assertEqual({label: active for label, _, _, active in meter_bars}, {"10": False, "11": True})

        rows = [self.bpm_row(130)]
        for typed in (">=120 <140", "<140 >=120", ">=120.0 <140.0"):
            bars = data.aggregate_bpm_distribution(rows, active_val=typed)
            self.assertEqual([label for label, _, _, active in bars if active], ["120-139"], typed)

    def test_get_active_chart_filters_lists_every_active_chart_filter(self):
        self.assertEqual(
            data.get_active_chart_filters("Hard", "Smiley meter:11 bpm:>=120 bpm:<140"),
            [("Difficulty", "Hard"), ("Meter", "11"), ("BPM", ">=120 <140")],
        )
        # A diff: directive counts when the dropdown is not set.
        self.assertEqual(
            data.get_active_chart_filters("All difficulties", "diff:Challenge"),
            [("Difficulty", "Challenge")],
        )
        # The dropdown wins over a diff: directive; empty values (half-typed "bpm:") are ignored.
        self.assertEqual(
            data.get_active_chart_filters("Hard", "diff:Challenge bpm:"),
            [("Difficulty", "Hard")],
        )
        self.assertEqual(data.get_active_chart_filters("All difficulties", "Smiley"), [])

    def test_distribution_summary_stats(self):
        rows = [
            {"Meter": 10, "Difficulty": "Hard", "bpm_max": 150},
            {"Meter": 10, "Difficulty": "Hard", "bpm_max": 160},
            {"Meter": 12, "Difficulty": "Challenge", "bpm_max": 180},
        ]
        # Meter stats
        meter_summary = data.distribution_summary_stats("Meter", rows)
        self.assertIn("3 charts", meter_summary)
        self.assertIn("Median: 10", meter_summary)
        self.assertIn("Mode: 10", meter_summary)

        # Multimodal deterministic selection (lowest mode)
        multimodal_rows = [
            {"Meter": 9}, {"Meter": 9},
            {"Meter": 11}, {"Meter": 11},
        ]
        multimodal_summary = data.distribution_summary_stats("Meter", multimodal_rows)
        self.assertIn("Mode: 9", multimodal_summary)

        # Difficulty stats
        diff_summary = data.distribution_summary_stats("Difficulty", rows)
        self.assertIn("3 charts", diff_summary)
        self.assertIn("Mode: Hard (2)", diff_summary)

        # BPM stats
        bpm_summary = data.distribution_summary_stats("BPM", rows)
        self.assertIn("3 charts", bpm_summary)
        self.assertIn("Median: 160", bpm_summary)

        # Empty rows
        self.assertEqual(data.distribution_summary_stats("Meter", []), "0 charts")

    def test_non_finite_values_are_excluded_from_summary_stats(self):
        # Probe-sweep cosmetic 1: a hostile tempo used to print "Mean: inf"
        # / "Mean: nan" in the distribution summary.
        rows = [
            {"Meter": 10, "bpm_max": 150},
            {"Meter": float("inf"), "bpm_max": float("inf")},
            {"Meter": float("nan"), "bpm_max": float("nan")},
            {"Meter": 12, "bpm_max": 180},
        ]
        meter_summary = data.distribution_summary_stats("Meter", rows)
        self.assertIn("Median: 11", meter_summary)
        self.assertNotIn("inf", meter_summary)
        self.assertNotIn("nan", meter_summary)
        bpm_summary = data.distribution_summary_stats("BPM", rows)
        self.assertIn("Median: 165", bpm_summary)
        self.assertNotIn("inf", bpm_summary)
        self.assertNotIn("nan", bpm_summary)
        # All non-finite reads like no values at all.
        hostile = [{"Meter": float("nan"), "bpm_max": float("inf")}]
        self.assertEqual(data.distribution_summary_stats("Meter", hostile), "1 charts")
        self.assertEqual(data.distribution_summary_stats("BPM", hostile), "1 charts")

    def test_nan_meters_form_a_single_bar(self):
        # Probe-sweep cosmetic 2: NaN is not equal to itself, so each NaN
        # row used to make a bar of its own, each claiming the full count.
        rows = [
            {"Meter": 10},
            {"Meter": float("nan")},
            {"Meter": "nan"},
            {"Meter": float("inf")},
        ]
        dist = data.aggregate_meter_distribution(rows)
        labels = [item[0] for item in dist]
        counts = {item[0]: item[1] for item in dist}
        self.assertEqual(labels.count("nan"), 1)
        self.assertEqual(counts["nan"], 2)
        self.assertEqual(counts["10"], 1)
        self.assertEqual(counts["inf"], 1)
        # Bars add up to the row count (no double-counting).
        self.assertEqual(sum(item[1] for item in dist), 4)

    def test_nan_bar_shows_active_when_its_filter_is_typed(self):
        # Probe-sweep cosmetic 3: filter_texts_match("nan", "nan") was False.
        rows = [{"Meter": float("nan")}, {"Meter": 10}]
        dist = data.aggregate_meter_distribution(rows, active_val="nan")
        actives = {item[0]: item[3] for item in dist}
        self.assertTrue(actives["nan"])
        self.assertFalse(actives["10"])

    def test_filter_texts_match_treats_nan_as_nan(self):
        match = data.filter_texts_match
        self.assertTrue(match("nan", "nan"))
        self.assertTrue(match("=nan", "nan"))
        self.assertTrue(match("nan", "=nan"))
        self.assertFalse(match("nan", "inf"))
        self.assertFalse(match("nan", "11"))
        self.assertTrue(match("nan-nan", "nan-nan"))


class ChartClickLogicTests(unittest.TestCase):
    """The chart's pure decision logic, extracted from the window methods (proposal 0005 step 2).

    The tuning values are passed as literals, the way the window passes the theme constants,
    so these tests stay free of theme like library_data itself.
    """

    ZONE = dict(min_click_fraction=0.15, bar_height=0.68, axis_headroom=1.25)

    def test_zone_extents_widths_and_axis(self):
        bars, axis_max = data.chart_bars(
            [("10", 2, "10", False), ("11", 1, "11", False), ("12", 4, "12", False)], **self.ZONE)
        self.assertEqual(axis_max, 4 * 1.25)
        # Bar i is centred on position i; y_max is y_min + bar_height, never position + bar_height/2.
        for i, bar in enumerate(bars):
            self.assertEqual(bar.y_min, i - 0.68 / 2)
            self.assertEqual(bar.y_max, bar.y_min + 0.68)
        self.assertEqual([bar.click_width for bar in bars], [2, 1, 4])
        self.assertEqual([bar.label for bar in bars], ["10", "11", "12"])
        self.assertEqual([bar.token for bar in bars], ["10", "11", "12"])

    def test_zone_minimum_width_widens_short_bars(self):
        bars, axis_max = data.chart_bars([("10", 100, "10", False), ("11", 1, "11", False)], **self.ZONE)
        self.assertEqual(axis_max, 125.0)
        self.assertEqual(bars[0].click_width, 100)
        self.assertEqual(bars[1].click_width, 125.0 * 0.15)  # one chart, widened to the minimum

    def test_zone_empty_rows_lose_their_token_unless_active(self):
        bars, _axis_max = data.chart_bars(
            [("Easy", 0, "Easy", False), ("Hard", 0, "Hard", True), ("?", 3, "", False)], **self.ZONE)
        self.assertEqual([bar.token for bar in bars], ["", "Hard", ""])

    def test_zone_no_items(self):
        self.assertEqual(data.chart_bars([], **self.ZONE), ([], 1.25))

    def test_hit_test_inside_outside_and_tokenless(self):
        bars, _axis_max = data.chart_bars([("10", 2, "10", False), ("11", 1, "11", False)], **self.ZONE)
        self.assertIs(data.chart_bar_at(bars, 0.5, 0.0), bars[0])
        self.assertIs(data.chart_bar_at(bars, 2.0, 0.0), bars[0])   # the zone's right edge counts
        self.assertIs(data.chart_bar_at(bars, 0.5, 1.0), bars[1])
        self.assertIsNone(data.chart_bar_at(bars, 2.5, 0.0))         # past the click zone
        self.assertIsNone(data.chart_bar_at(bars, -0.1, 0.0))        # left of the axis
        self.assertIsNone(data.chart_bar_at(bars, 0.5, 0.5))         # the gap between two bars
        self.assertIsNone(data.chart_bar_at(bars, None, 0.0))        # a click on a row label
        self.assertIsNone(data.chart_bar_at(bars, 0.5, None))
        self.assertIsNone(data.chart_bar_at([], 0.5, 0.0))
        # An empty row is in the zone but has nothing to filter to.
        empty, _axis_max = data.chart_bars([("Easy", 0, "Easy", False)], **self.ZONE)
        self.assertIsNone(data.chart_bar_at(empty, 0.1, 0.0))
        self.assertIsNone(data.chart_bar_at([data.ChartBar(-0.34, 0.34, "?", "")], 0.1, 0.0))

    def test_hit_test_question_mark_difficulty_bar_is_not_clickable(self):
        # A difficulty literally named "?" passes through the aggregate as its own token,
        # so the token check alone would let it be clicked; the hit test keeps the window
        # handler's rule that a bar labelled "?" is never clickable.
        self.assertIsNone(data.chart_bar_at([data.ChartBar(-0.34, 0.34, "?", "?")], 0.1, 0.0))
        items = data.aggregate_difficulty_distribution([{"Difficulty": "?"}])
        bars, _axis_max = data.chart_bars(items, **self.ZONE)
        question_index = next(i for i, bar in enumerate(bars) if bar.label == "?")
        self.assertEqual(bars[question_index].token, "?")
        self.assertIsNone(data.chart_bar_at(bars, 0.1, float(question_index)))

    def test_click_decision_meter_set_and_toggle_off(self):
        self.assertEqual(
            data.chart_click_decision("Meter", "11", "All difficulties", "Smiley"),
            (None, "Smiley meter:11"))
        self.assertEqual(
            data.chart_click_decision("Meter", "11", "All difficulties", "Smiley meter:11"),
            (None, "Smiley"))
        # A hand-typed equivalent filter still toggles off.
        self.assertEqual(
            data.chart_click_decision("Meter", "11", "All difficulties", "Smiley meter:11.0"),
            (None, "Smiley"))

    def test_click_decision_difficulty_writes_the_dropdown(self):
        # Setting a difficulty writes only the dropdown; the query is untouched.
        self.assertEqual(
            data.chart_click_decision("Difficulty", "Hard", "All difficulties", "Smiley"),
            ("Hard", None))
        # A redundant diff directive is removed, and only then is the query written.
        self.assertEqual(
            data.chart_click_decision("Difficulty", "Hard", "All difficulties", "Smiley diff:easy"),
            ("Hard", "Smiley"))
        # Clicking the active difficulty toggles it off.
        self.assertEqual(
            data.chart_click_decision("Difficulty", "Hard", "Hard", "Smiley"),
            ("All difficulties", None))
        self.assertEqual(
            data.chart_click_decision("Difficulty", "Hard", "All difficulties", "Smiley diff:hard"),
            ("All difficulties", "Smiley"))

    def test_click_decision_bpm_pair_set_and_toggle_off(self):
        token = (">=120", "<140")
        self.assertEqual(
            data.chart_click_decision("BPM", token, "All difficulties", "Smiley bpm:150"),
            (None, "Smiley bpm:>=120 bpm:<140"))
        self.assertEqual(
            data.chart_click_decision("BPM", token, "All difficulties", "Smiley bpm:>=120 bpm:<140"),
            (None, "Smiley"))

    def test_clear_decision(self):
        # Nothing active: the complete no-op.
        self.assertIsNone(data.chart_clear_decision("All difficulties", "Smiley"))
        # Difficulty and query filters together.
        self.assertEqual(
            data.chart_clear_decision("Hard", "Smiley meter:11"),
            ("All difficulties", "Smiley"))
        # Query filters only: the dropdown is not written.
        self.assertEqual(
            data.chart_clear_decision("All difficulties", "Smiley meter:11 bpm:>=120 bpm:<140"),
            (None, "Smiley"))
        # Difficulty active through a directive is reset the same way.
        self.assertEqual(
            data.chart_clear_decision("All difficulties", "Smiley diff:hard meter:11"),
            ("All difficulties", "Smiley"))
        # The dropdown alone: the query is still written, with its (unchanged) stripped text.
        self.assertEqual(
            data.chart_clear_decision("Hard", "Smiley"),
            ("All difficulties", "Smiley"))


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib is not installed")
class ChartBarsAggTests(unittest.TestCase):
    """Draws the chart with matplotlib's Agg backend and compares extents exactly.

    The zone function's derived y-extents must equal the drawn bars' get_y()/get_height()
    extents bit for bit; a formula that recomputes y_max from the position diverges in the
    last digit on roughly a quarter of bars (proposal 0005, acceptance round).
    """

    def test_zone_extents_match_a_drawn_chart_exactly(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        items = [(f"bar{i}", (i * 7) % 13, str(i), False) for i in range(40)]
        bars, _axis_max = data.chart_bars(
            items, min_click_fraction=0.15, bar_height=0.68, axis_headroom=1.25)
        figure = Figure(figsize=(3.0, 4.0), dpi=100)
        ax = figure.add_subplot(111)
        drawn = ax.barh(list(range(len(items))), [item[1] for item in items], align="center", height=0.68)
        FigureCanvasAgg(figure).draw()
        self.assertEqual(len(bars), len(drawn))
        for bar, patch in zip(bars, drawn):
            self.assertEqual(bar.y_min, patch.get_y())
            self.assertEqual(bar.y_max, patch.get_y() + patch.get_height())


if __name__ == "__main__":
    unittest.main()
