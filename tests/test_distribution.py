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

    def test_get_active_chart_filter(self):
        # Difficulty combobox takes priority over search query
        self.assertEqual(
            data.get_active_chart_filter("Challenge", "meter:11 bpm:140-159"),
            ("Difficulty", "Challenge")
        )

        # When diff is "All difficulties", search directives take effect
        self.assertEqual(
            data.get_active_chart_filter("All difficulties", "meter:11 bpm:140-159"),
            ("Meter", "11")
        )

        # BPM search directive
        self.assertEqual(
            data.get_active_chart_filter("All difficulties", "bpm:140-159"),
            ("BPM", "140-159")
        )

        # Free text only
        self.assertIsNone(
            data.get_active_chart_filter("All difficulties", "Smiley Delirium")
        )

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

    def test_aggregate_bpm_distribution(self):
        rows = [
            {"bpm_max": 100},       # <120
            {"bpm_max": "130"},     # 120-139
            {"bpm_max": 145.5},     # 140-159
            {"bpm_max": 170},       # 160-179
            {"bpm_max": 190},       # 180-199
            {"bpm_max": 220},       # 200+
            {"bpm_max": None},      # ?
            {"bpm_max": "err"},     # ?
        ]
        dist = data.aggregate_bpm_distribution(rows, active_val="120-139")
        counts = {item[0]: item[1] for item in dist}
        tokens = {item[0]: item[2] for item in dist}
        actives = {item[0]: item[3] for item in dist}

        self.assertEqual(counts["<120"], 1)
        self.assertEqual(tokens["<120"], "<120")

        self.assertEqual(counts["120-139"], 1)
        self.assertEqual(tokens["120-139"], "120-139")
        self.assertTrue(actives["120-139"])

        self.assertEqual(counts["140-159"], 1)
        self.assertEqual(counts["160-179"], 1)
        self.assertEqual(counts["180-199"], 1)
        self.assertEqual(counts["200+"], 1)
        self.assertEqual(tokens["200+"], ">=200")

        self.assertEqual(counts["?"], 2)
        self.assertEqual(tokens["?"], "")

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


if __name__ == "__main__":
    unittest.main()
