import unittest
from unittest.mock import Mock, patch

import library_data as data
import library_visualizer as app


class DistributionUITests(unittest.TestCase):
    def test_mock_ui_distribution_lifecycle(self):
        """Test distribution lifecycle using mock Tk widgets to verify logic end-to-end."""
        root = Mock()
        instance = object.__new__(app.LibraryApp)
        instance.root = root
        instance.show_distribution_panel = Mock()
        instance.show_distribution_panel.get.return_value = False
        instance.distribution_metric = Mock()
        instance.distribution_metric.get.return_value = "Meter"
        instance.dist_button = Mock()
        instance.dist_panel = Mock()
        instance.dist_banner_frame = Mock()
        instance.dist_banner_label = Mock()
        instance.dist_summary_var = Mock()
        instance.dist_chart_frame = Mock()
        instance.dist_canvas = Mock()
        instance.dist_fig = Mock()
        instance.dist_ax = Mock()
        instance.dist_ax.spines = {"top": Mock(), "right": Mock(), "left": Mock(), "bottom": Mock()}
        instance.diff_var = Mock()
        instance.diff_var.get.return_value = "All difficulties"
        instance.search_var = Mock()
        instance.search_var.get.return_value = ""
        instance.search_entry = Mock()
        instance.refresh_table = Mock()
        instance._save_settings = Mock()
        instance._current_dist_bars = []
        instance._last_visible_rows = []

        # Toggle open
        instance.toggle_distribution_panel()
        instance.show_distribution_panel.set.assert_called_with(True)
        instance.dist_button.configure.assert_called_with(text="Distribution ◀")
        instance.dist_panel.pack.assert_called_once()

        # Update panel with sample rows
        sample_rows = [
            {"Meter": 10, "Difficulty": "Hard", "bpm_max": 150},
            {"Meter": 11, "Difficulty": "Challenge", "bpm_max": 180},
        ]
        mock_bar1 = Mock(get_y=Mock(return_value=0.0), get_height=Mock(return_value=0.68))
        mock_bar2 = Mock(get_y=Mock(return_value=1.0), get_height=Mock(return_value=0.68))
        instance.dist_ax.barh.return_value = [mock_bar1, mock_bar2]
        instance.show_distribution_panel.get.return_value = True
        instance._update_distribution_panel(sample_rows)
        instance.dist_summary_var.set.assert_called()

        # Simulate chart click on a meter bar
        instance._current_dist_bars = [(0.0, 1.0, "11", "11")]
        click_event = Mock()
        click_event.ydata = 0.5
        instance._on_chart_click(click_event)

        instance.search_var.set.assert_called_with("meter:11")
        instance.refresh_table.assert_called_once()

    def test_live_tk_distribution_ui(self):
        """Test full live Tkinter UI when DISPLAY is available."""
        try:
            root = app.tk.Tk()
        except Exception:
            return  # Headless without X11
        try:
            application = app.LibraryApp(root)
            # Panel initially closed or matches saved settings
            if application.show_distribution_panel.get():
                application.toggle_distribution_panel()
            self.assertFalse(application.show_distribution_panel.get())
            self.assertEqual(application.dist_button.cget("text"), "Distribution ▶")

            # Toggle open
            application.toggle_distribution_panel()
            self.assertTrue(application.show_distribution_panel.get())
            self.assertEqual(application.dist_button.cget("text"), "Distribution ◀")

            # Test updating with sample rows
            application.rows = [
                {"Meter": 10, "Difficulty": "Hard", "bpm_max": 150, "Pack": "Test", "Type": "dance-single", "Grade": "Tier05"},
                {"Meter": 11, "Difficulty": "Challenge", "bpm_max": 180, "Pack": "Test", "Type": "dance-single", "Grade": "Tier06"},
            ]
            application.refresh_table()

            # Test switching metric
            application.distribution_metric.set("Difficulty")
            application._on_distribution_metric_changed()

            application.distribution_metric.set("BPM")
            application._on_distribution_metric_changed()

            # Test clear filter
            application.diff_var.set("Challenge")
            application.clear_chart_filter()
            self.assertEqual(application.diff_var.get(), "All difficulties")
        finally:
            root.destroy()

    def test_question_mark_bar_is_non_interactive(self):
        """Clicking the '?' bar should do nothing and not filter."""
        instance = object.__new__(app.LibraryApp)
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.search_var = Mock(get=Mock(return_value=""))
        instance.refresh_table = Mock()
        instance._current_dist_bars = [(0.0, 1.0, "?", "")]

        event = Mock()
        event.ydata = 0.5
        instance._on_chart_click(event)

        instance.search_var.set.assert_not_called()
        instance.refresh_table.assert_not_called()


class FullDistributionTests(unittest.TestCase):
    """The chart keeps every bar after you click one; the table narrows as before."""

    ROWS = [
        {"Meter": 10, "Difficulty": "Hard", "Pack": "P", "Type": "dance-single", "Grade": "",
         "bpm_min": 130.0, "bpm_max": 130.0},
        {"Meter": 10, "Difficulty": "Challenge", "Pack": "P", "Type": "dance-single", "Grade": "",
         "bpm_min": 100.0, "bpm_max": 150.0},
        {"Meter": 11, "Difficulty": "Hard", "Pack": "P", "Type": "dance-single", "Grade": "",
         "bpm_min": 170.0, "bpm_max": 170.0},
        {"Meter": 12, "Difficulty": "Hard", "Pack": "Q", "Type": "dance-single", "Grade": "",
         "bpm_min": 130.0, "bpm_max": 130.0},
    ]

    @classmethod
    def make_app(cls, query="", diff="All difficulties", metric="Meter", pack="All packs"):
        instance = object.__new__(app.LibraryApp)
        instance.rows = list(cls.ROWS)
        instance.pack_var = Mock(get=Mock(return_value=pack))
        instance.type_var = Mock(get=Mock(return_value="All types"))
        instance.diff_var = Mock(get=Mock(return_value=diff))
        instance.scored_var = Mock(get=Mock(return_value=False))
        instance.search_var = Mock(get=Mock(return_value=query))
        instance.search_entry = Mock()
        instance.refresh_table = Mock()
        instance.distribution_metric = Mock(get=Mock(return_value=metric))
        instance.show_distribution_panel = Mock(get=Mock(return_value=True))
        instance.dist_panel = Mock()
        instance.dist_banner_frame = Mock()
        instance.dist_banner_label = Mock()
        instance.dist_summary_var = Mock()
        instance.dist_chart_frame = Mock()
        instance.dist_canvas = Mock()
        instance.dist_fig = Mock()
        instance.dist_ax = Mock()
        instance.dist_ax.spines = {name: Mock() for name in ("top", "right", "left", "bottom")}
        instance._current_dist_bars = []
        instance._last_visible_rows = []
        return instance

    def test_filter_rows_can_skip_one_charts_own_filter(self):
        instance = self.make_app(query="meter:10 bpm:>=120 bpm:<140", diff="Hard")
        def meter_and_difficulty(ignore_metric=None):
            return [(row["Meter"], row["Difficulty"]) for row in instance._filter_rows(ignore_metric)]

        # All filters: Hard, meter 10, BPM touching 120-139.
        self.assertEqual(meter_and_difficulty(), [(10, "Hard")])
        # Skipping one metric leaves the other filters in force.
        self.assertEqual(meter_and_difficulty("Meter"), [(10, "Hard"), (12, "Hard")])
        self.assertEqual(meter_and_difficulty("Difficulty"), [(10, "Hard"), (10, "Challenge")])
        self.assertEqual(meter_and_difficulty("BPM"), [(10, "Hard")])

    def test_meter_chart_shows_all_meters_while_meter_filter_is_active(self):
        instance = self.make_app(query="meter:11", metric="Meter")
        visible = instance._filter_rows()
        self.assertEqual([row["Meter"] for row in visible], [11])

        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(visible)

        # Bars are drawn top-down (reversed): meter 12, 11, 10 -> counts 1, 1, 2.
        self.assertEqual(instance.dist_ax.barh.call_args.args[1], [1, 1, 2])
        self.assertEqual([bar[2] for bar in instance._current_dist_bars], ["12", "11", "10"])
        # The summary describes the bars shown, and the banner still names the active filter.
        self.assertIn("4 charts", instance.dist_summary_var.set.call_args.args[0])
        instance.dist_banner_label.configure.assert_called_with(text="Filtered by: Meter 11")

    def test_chart_ignores_only_its_own_filter(self):
        # Difficulty chart with meter:10 active: all difficulties among meter-10 charts, not meter 11/12.
        instance = self.make_app(query="meter:10", diff="Hard", metric="Difficulty")
        visible = instance._filter_rows()
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(6)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(visible)
        labels = [bar[2] for bar in instance._current_dist_bars]
        counts = dict(zip(labels, instance.dist_ax.barh.call_args.args[1]))
        self.assertEqual(counts["Hard"], 1)
        self.assertEqual(counts["Challenge"], 1)
        self.assertEqual(counts["Easy"], 0)

    def test_without_own_filter_chart_reuses_table_rows(self):
        instance = self.make_app(query="", metric="Meter", pack="Q")
        instance._filter_rows = Mock()
        instance._last_visible_rows = [self.ROWS[3]]
        self.assertEqual(instance._distribution_rows("Meter"), [self.ROWS[3]])
        instance._filter_rows.assert_not_called()

    def test_clicking_another_bar_replaces_filter_and_same_bar_clears_it(self):
        instance = self.make_app(query="Smiley meter:11", metric="Meter")
        instance._current_dist_bars = [(0.0, 1.0, "12", "12"), (1.0, 2.0, "11", "11")]
        instance._on_chart_click(Mock(ydata=0.5))
        instance.search_var.set.assert_called_with("Smiley meter:12")
        instance._on_chart_click(Mock(ydata=1.5))
        instance.search_var.set.assert_called_with("Smiley")

    def test_clicking_a_bpm_bar_sets_both_range_directives(self):
        instance = self.make_app(query="Smiley bpm:150", metric="BPM")
        instance._current_dist_bars = [(0.0, 1.0, "120-139", (">=120", "<140"))]
        instance._on_chart_click(Mock(ydata=0.5))
        instance.search_var.set.assert_called_with("Smiley bpm:>=120 bpm:<140")

        # Clicking the highlighted bar again removes both directives.
        instance.search_var.get.return_value = "Smiley bpm:>=120 bpm:<140"
        instance._on_chart_click(Mock(ydata=0.5))
        instance.search_var.set.assert_called_with("Smiley")


if __name__ == "__main__":
    unittest.main()
