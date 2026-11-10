import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import library_data as data
import library_visualizer as app
import theme


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
        instance.table_frame = Mock()
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
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "11", "11")]
        click_event = Mock()
        click_event.ydata = 0.5
        click_event.xdata = 0.1
        instance._on_chart_click(click_event)

        instance.search_var.set.assert_called_with("meter:11")
        instance.refresh_table.assert_called_once()

    def test_live_tk_distribution_ui(self):
        """Test full live Tkinter UI; skipped when Tk or a display is not available."""
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        # Keep the test away from the player's real settings file and saved library snapshot (the
        # snapshot path is derived from the settings path).
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings_path = Path(settings_dir.name) / "settings.json"
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
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
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "?", "")]

        event = Mock()
        event.ydata = 0.5
        event.xdata = 0.1
        instance._on_chart_click(event)

        instance.search_var.set.assert_not_called()
        instance.refresh_table.assert_not_called()


class DistributionVisibilityTests(unittest.TestCase):
    """The visibility funnel (proposal 0005, step 1): hide, re-show, and the View-menu sync.

    Until now only the show direction was exercised, and without its pack arguments —
    the `before=` argument is the one a botched component move is most likely to drop,
    leaving the panel squeezed to zero width next to the table.
    """

    @staticmethod
    def make_instance(shown=True):
        instance = object.__new__(app.LibraryApp)
        instance.root = Mock()
        instance.show_distribution_panel = Mock()
        instance.show_distribution_panel.get.return_value = shown
        instance.distribution_metric = Mock()
        instance.distribution_metric.get.return_value = "Meter"
        instance.dist_button = Mock()
        instance.dist_panel = Mock()
        instance.table_frame = Mock()
        instance._save_settings = Mock()
        instance._last_visible_rows = [{"Meter": 10, "Difficulty": "Hard", "bpm_max": 150}]
        return instance

    def test_hide_then_show_repacks_with_full_arguments_and_saves(self):
        instance = self.make_instance(shown=True)

        instance._set_distribution_visible(False)
        instance.show_distribution_panel.set.assert_called_once_with(False)
        instance.dist_panel.pack_forget.assert_called_once_with()
        instance.dist_button.configure.assert_called_once_with(text="Distribution ▶")
        instance.root.update_idletasks.assert_called_once_with()
        instance._save_settings.assert_called_once_with()

        instance.dist_panel.reset_mock()
        instance.dist_button.reset_mock()
        instance.root.reset_mock()
        instance.show_distribution_panel.reset_mock()
        instance._save_settings.reset_mock()
        instance._update_distribution_panel = Mock()
        instance._set_distribution_visible(True)
        instance.show_distribution_panel.set.assert_called_once_with(True)
        # The full recorded pack arguments, including before= the table frame.
        instance.dist_panel.pack.assert_called_once_with(
            side="right", fill="y", padx=(10, 0), before=instance.table_frame)
        instance.dist_button.configure.assert_called_once_with(text="Distribution ◀")
        # Re-showing redraws from the rows stored while the panel was hidden.
        instance._update_distribution_panel.assert_called_once_with(instance._last_visible_rows)
        instance._save_settings.assert_called_once_with()
        # update_idletasks belongs to the hide path only.
        instance.root.update_idletasks.assert_not_called()

    def test_sync_distribution_toggle_applies_the_variable(self):
        # The View-menu checkbutton has already flipped the variable; sync applies it.
        instance = self.make_instance(shown=True)
        instance._update_distribution_panel = Mock()
        instance._sync_distribution_toggle()
        instance.dist_panel.pack.assert_called_once_with(
            side="right", fill="y", padx=(10, 0), before=instance.table_frame)

        instance = self.make_instance(shown=False)
        instance._sync_distribution_toggle()
        instance.dist_panel.pack_forget.assert_called_once_with()
        instance.dist_button.configure.assert_called_once_with(text="Distribution ▶")

    def test_canvas_creation_builds_the_figure_and_binds_the_click(self):
        instance = object.__new__(app.LibraryApp)
        instance.dist_canvas = None
        instance.dist_fig = None
        instance.dist_ax = None
        instance.dist_chart_frame = Mock()
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True), \
                patch.object(app, "Figure", create=True) as figure_cls, \
                patch.object(app, "FigureCanvasTkAgg", create=True) as canvas_cls:
            self.assertTrue(instance._ensure_distribution_canvas())
            figure_cls.assert_called_once_with(figsize=(3.0, 4.0), dpi=100, facecolor=theme.BG_PANEL)
            figure_cls.return_value.add_subplot.assert_called_once_with(111)
            canvas_cls.assert_called_once_with(figure_cls.return_value, master=instance.dist_chart_frame)
            canvas = canvas_cls.return_value
            canvas.mpl_connect.assert_called_once_with("button_press_event", instance._on_chart_click)
            canvas.get_tk_widget.return_value.pack.assert_called_once_with(fill="both", expand=True)
            # The created objects are the ones stored for later updates.
            self.assertIs(instance.dist_fig, figure_cls.return_value)
            self.assertIs(instance.dist_ax, figure_cls.return_value.add_subplot.return_value)
            self.assertIs(instance.dist_canvas, canvas)
            # A second call reuses the canvas instead of building another.
            self.assertTrue(instance._ensure_distribution_canvas())
            figure_cls.assert_called_once()


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

    def draw_difficulty_chart(self, diff="All difficulties", query=""):
        instance = self.make_app(query=query, diff=diff, metric="Difficulty")
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(6)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        return instance, {bar[2]: bar[3] for bar in instance._current_dist_bars}

    def test_rows_with_no_charts_are_not_clickable(self):
        instance, tokens = self.draw_difficulty_chart()
        self.assertEqual(tokens["Hard"], "Hard")
        self.assertEqual(tokens["Challenge"], "Challenge")
        for empty in ("Beginner", "Easy", "Medium", "Edit"):
            self.assertEqual(tokens[empty], "", empty)

        # Clicking an empty row changes nothing.
        y_of_easy = next(bar.y_min for bar in instance._current_dist_bars if bar.label == "Easy")
        instance._on_chart_click(Mock(ydata=y_of_easy + 0.1, xdata=0.1))
        instance.search_var.set.assert_not_called()
        instance.refresh_table.assert_not_called()

    def test_an_empty_row_that_is_the_active_filter_stays_clickable(self):
        # The dropdown is on "Easy", which has no charts here; clicking it again must switch it off.
        instance, tokens = self.draw_difficulty_chart(diff="Easy")
        self.assertEqual(tokens["Easy"], "Easy")
        self.assertEqual(tokens["Beginner"], "")

    def test_without_own_filter_chart_reuses_table_rows(self):
        instance = self.make_app(query="", metric="Meter", pack="Q")
        instance._filter_rows = Mock()
        instance._last_visible_rows = [self.ROWS[3]]
        self.assertEqual(instance._distribution_rows("Meter"), [self.ROWS[3]])
        instance._filter_rows.assert_not_called()

    def test_clicking_another_bar_replaces_filter_and_same_bar_clears_it(self):
        instance = self.make_app(query="Smiley meter:11", metric="Meter")
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "12", "12"), app.ChartBar(1.0, 2.0, "11", "11")]
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley meter:12")
        instance._on_chart_click(Mock(ydata=1.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

    def test_clicks_outside_a_bars_click_zone_do_nothing(self):
        instance = self.make_app(metric="Meter")
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "11", "11", 4.0)]
        # Past the end of the zone, left of the axis, off the row, or outside the plot (no position).
        for x, y in ((4.5, 0.5), (100.0, 0.5), (-0.5, 0.5), (1.0, 1.5), (None, 0.5), (1.0, None)):
            instance._on_chart_click(Mock(xdata=x, ydata=y))
        instance.search_var.set.assert_not_called()
        instance.refresh_table.assert_not_called()
        # Both ends of the zone count.
        instance._on_chart_click(Mock(xdata=4.0, ydata=0.5))
        instance.search_var.set.assert_called_with("meter:11")
        instance.search_var.set.reset_mock()
        instance._on_chart_click(Mock(xdata=0.0, ydata=0.5))
        instance.search_var.set.assert_called_with("meter:11")

    def test_click_zone_is_the_bar_plus_a_minimum_width(self):
        instance = self.make_app(metric="Meter")
        # 22 charts of meter 10, one of 11 and one of 12: the long bar sets the chart's width.
        instance.rows = list(self.ROWS[:1]) * 20 + list(self.ROWS)
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        widths = {bar.label: bar.click_width for bar in instance._current_dist_bars}
        minimum = 22 * 1.25 * theme.CHART_MIN_CLICK_FRACTION  # the chart is 22 * 1.25 units wide
        self.assertEqual(set(widths), {"12", "11", "10"})
        self.assertAlmostEqual(widths["12"], minimum)   # one chart: widened to the minimum
        self.assertAlmostEqual(widths["11"], minimum)
        self.assertAlmostEqual(widths["10"], 22)         # the long bar: its own length
        instance.dist_ax.set_xlim.assert_called_with(0, 22 * 1.25)

    def test_clicking_a_bar_switches_off_a_hand_typed_version_of_its_filter(self):
        instance = self.make_app(query="Smiley meter:11.0", metric="Meter")
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "11", "11")]
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

        instance = self.make_app(query="Smiley bpm:<140 bpm:>=120", metric="BPM")
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "120-139", (">=120", "<140"))]
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

    def test_clicking_a_bpm_bar_sets_both_range_directives(self):
        instance = self.make_app(query="Smiley bpm:150", metric="BPM")
        instance._current_dist_bars = [app.ChartBar(0.0, 1.0, "120-139", (">=120", "<140"))]
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley bpm:>=120 bpm:<140")

        # Clicking the highlighted bar again removes both directives.
        instance.search_var.get.return_value = "Smiley bpm:>=120 bpm:<140"
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

    def test_banner_packs_with_a_filter_and_forgets_without_one(self):
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        instance = self.make_app(query="meter:11")
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        instance.dist_banner_frame.pack.assert_called_once_with(
            fill="x", pady=(0, 6), before=instance.dist_chart_frame)
        instance.dist_banner_frame.pack_forget.assert_not_called()

        instance = self.make_app(query="")
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        instance.dist_banner_frame.pack_forget.assert_called_once_with()
        instance.dist_banner_frame.pack.assert_not_called()

    def test_empty_state_draws_the_message_and_no_bars(self):
        instance = self.make_app()
        instance.rows = []
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel([])
        instance.dist_ax.text.assert_called_once()
        self.assertIn("No charts match", instance.dist_ax.text.call_args.args[2])
        instance.dist_ax.axis.assert_called_with("off")
        instance.dist_ax.barh.assert_not_called()
        self.assertEqual(instance._current_dist_bars, [])
        instance.dist_canvas.draw_idle.assert_called()

    def test_metric_change_redraws_for_the_new_metric_and_saves(self):
        instance = self.make_app(metric="Meter")
        instance._save_settings = Mock()
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(6)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
            self.assertEqual([bar[2] for bar in instance._current_dist_bars], ["12", "11", "10"])

            # Empty the library underneath the panel: a redraw that recalculated
            # its rows (instead of using the stored ones) would now find nothing.
            instance.rows = []
            instance.distribution_metric.get.return_value = "Difficulty"
            instance._on_distribution_metric_changed()

        instance._save_settings.assert_called_once_with()
        # The redraw used the stored rows and the new metric, not the meter bars again.
        labels = [bar[2] for bar in instance._current_dist_bars]
        self.assertIn("Hard", labels)
        self.assertIn("Challenge", labels)
        self.assertNotIn("10", labels)

    def test_bar_colours_and_the_active_bars_white_edge(self):
        instance, _tokens = self.draw_difficulty_chart(diff="Hard")
        labels = [bar.label for bar in instance._current_dist_bars]
        drawn = instance.dist_ax.barh.call_args
        self.assertEqual(drawn.kwargs["height"], theme.CHART_BAR_HEIGHT)
        colours, edges, widths = drawn.kwargs["color"], drawn.kwargs["edgecolor"], drawn.kwargs["linewidth"]
        hard = labels.index("Hard")
        self.assertEqual(colours[hard], theme.DIFFICULTY_COLORS["Hard"])
        self.assertEqual(edges[hard], theme.WHITE)   # the active bar's white edge
        self.assertEqual(widths[hard], 1.5)
        challenge = labels.index("Challenge")
        self.assertEqual(colours[challenge], theme.DIFFICULTY_COLORS["Challenge"])
        self.assertEqual(edges[challenge], theme.BG_INPUT)
        self.assertEqual(widths[challenge], 0.8)

        # Meter bars all take the accent colour.
        instance = self.make_app(metric="Meter")
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        self.assertEqual(instance.dist_ax.barh.call_args.kwargs["color"], [theme.ACCENT] * 3)

        # A row with no meter value lands in the "?" bar, which takes its own colour.
        instance = self.make_app(metric="Meter")
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(2)]
        instance.dist_ax.barh.return_value = bars
        rows = [{"Meter": 10, "Difficulty": "Hard", "bpm_max": 150.0},
                {"Difficulty": "Hard", "bpm_max": 150.0}]
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(rows)
        labels = [bar.label for bar in instance._current_dist_bars]
        colours = instance.dist_ax.barh.call_args.kwargs["color"]
        self.assertEqual(colours[labels.index("?")], theme.CHART_BAR_UNKNOWN)
        self.assertEqual(colours[labels.index("10")], theme.ACCENT)

    def test_a_difficulty_name_the_table_does_not_know_gets_the_unknown_colour(self):
        instance = self.make_app(metric="Difficulty")
        instance.rows = [dict(self.ROWS[0], Difficulty="Quirky"), dict(self.ROWS[1], Difficulty="Hard")]
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(7)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        labels = [bar.label for bar in instance._current_dist_bars]
        colours = instance.dist_ax.barh.call_args.kwargs["color"]
        self.assertEqual(colours[labels.index("Quirky")], theme.DIFFICULTY_COLOR_UNKNOWN)
        self.assertEqual(colours[labels.index("Hard")], theme.DIFFICULTY_COLORS["Hard"])

    def test_a_normal_draw_ends_with_a_repaint(self):
        # Without draw_idle the chart is built but never shown until something else repaints it.
        instance = self.make_app(metric="Meter")
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        instance.dist_ax.barh.return_value = bars
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(instance._filter_rows())
        instance.dist_canvas.draw_idle.assert_called_once_with()

    def test_rows_arriving_while_the_panel_is_hidden_are_stored_and_nothing_is_drawn(self):
        # The table keeps refreshing while the panel is closed; re-showing redraws from these rows.
        instance = self.make_app(metric="Meter")
        instance.show_distribution_panel.get.return_value = False
        instance._ensure_distribution_canvas = Mock()
        rows = [self.ROWS[0]]
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            instance._update_distribution_panel(rows)
        self.assertIs(instance._last_visible_rows, rows)
        # Hidden means hidden: no canvas is built, nothing is drawn, the banner and summary are left alone.
        instance._ensure_distribution_canvas.assert_not_called()
        instance.dist_ax.barh.assert_not_called()
        instance.dist_summary_var.set.assert_not_called()
        instance.dist_banner_frame.pack.assert_not_called()
        instance.dist_banner_frame.pack_forget.assert_not_called()


class FakeVar:
    """Stands in for a Tk variable: set() runs the 'write' traces straight away, as Tk does."""

    def __init__(self, value=""):
        self.value, self.traces = value, []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for trace in self.traces:
            trace()


class FakeRoot:
    """Stands in for the Tk root: after() queues a callback that run_pending() runs later."""

    def __init__(self):
        self.pending, self.counter = {}, 0

    def after(self, _milliseconds, callback):
        self.counter += 1
        self.pending[self.counter] = callback
        return self.counter

    def after_cancel(self, identifier):
        self.pending.pop(identifier, None)

    def run_pending(self):
        for identifier in sorted(self.pending):
            self.pending.pop(identifier)()


class SingleRefreshTests(unittest.TestCase):
    """One chart click or Clear rebuilds the table once, not once per filter variable."""

    @staticmethod
    def make_app(metric, query="", diff="All difficulties", bars=None):
        instance = object.__new__(app.LibraryApp)
        instance.root = FakeRoot()
        instance.search_var, instance.diff_var = FakeVar(query), FakeVar(diff)
        instance.search_entry = Mock()
        instance.distribution_metric = FakeVar(metric)
        instance._current_dist_bars = bars or [app.ChartBar(0.0, 1.0, "11", "11")]
        instance.refreshes = 0
        instance.refresh_table = lambda *args, **kwargs: setattr(instance, "refreshes", instance.refreshes + 1)
        # The same wiring LibraryApp.__init__ does.
        instance.search_var.traces.append(instance._schedule_search_refresh)
        instance.diff_var.traces.append(instance._refresh_unless_batching)
        return instance

    def refreshes_after_everything_settles(self, instance):
        instance.root.run_pending()  # lets any delayed search refresh fire
        return instance.refreshes

    def test_meter_click_refreshes_once(self):
        instance = self.make_app("Meter", "Smiley")
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)

    def test_difficulty_click_that_also_cleans_the_search_box_refreshes_once(self):
        instance = self.make_app("Difficulty", "Smiley diff:hard", bars=[app.ChartBar(0.0, 1.0, "Hard", "Hard")])
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        self.assertEqual(instance.search_var.get(), "Smiley")
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)

    def test_clear_with_several_filters_refreshes_once(self):
        instance = self.make_app("Meter", "meter:11 Smiley", diff="Hard")
        instance.clear_chart_filter()
        self.assertEqual((instance.diff_var.get(), instance.search_var.get()), ("All difficulties", "Smiley"))
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)

    def test_typing_still_waits_for_the_delay(self):
        instance = self.make_app("Meter")
        for text in ("s", "sm", "smi"):
            instance.search_var.set(text)
        self.assertEqual(instance.refreshes, 0)
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)

    def test_pending_typing_refresh_is_not_repeated_after_a_click(self):
        instance = self.make_app("Meter", "Smiley")
        instance.search_var.set("Smiley x")  # typing, delayed refresh queued
        instance._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib is not installed")
class RealChartClickTests(unittest.TestCase):
    """Draws the real chart with matplotlib's Agg backend (no Tk needed) and clicks at real positions."""

    def setUp(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        self.instance = FullDistributionTests.make_app(metric="Meter")
        row = {"Difficulty": "Hard", "Pack": "P", "Type": "dance-single", "Grade": "",
               "bpm_min": 130.0, "bpm_max": 130.0}
        # One chart each of meter 12 and 11, thirty of meter 10: a very short bar next to a long one.
        self.instance.rows = ([dict(row, Meter=12), dict(row, Meter=11)]
                              + [dict(row, Meter=10) for _ in range(30)])
        figure = Figure(figsize=(3.0, 4.0), dpi=100)
        self.instance.dist_fig, self.instance.dist_ax = figure, figure.add_subplot(111)
        self.instance.dist_canvas = FigureCanvasAgg(figure)
        with patch.object(app, "MATPLOTLIB_AVAILABLE", True):
            self.instance._update_distribution_panel(self.instance._filter_rows())
        self.instance.dist_canvas.draw()
        self.row_y = {bar.label: (bar.y_min + bar.y_max) / 2 for bar in self.instance._current_dist_bars}

    def click(self, x_data, label):
        """Click at a chart position; return the search text the click applied, or None."""
        from matplotlib.backend_bases import MouseEvent

        x_px, y_px = self.instance.dist_ax.transData.transform((x_data, self.row_y[label]))
        return self.click_pixels(x_px, y_px)

    def click_pixels(self, x_px, y_px):
        from matplotlib.backend_bases import MouseEvent

        self.instance.search_var.set.reset_mock()
        self.instance._on_chart_click(
            MouseEvent("button_press_event", self.instance.dist_canvas, x_px, y_px, button=1))
        call = self.instance.search_var.set.call_args
        return call.args[0] if call else None

    def test_a_short_bar_is_easy_to_hit_and_far_blank_space_is_not(self):
        self.assertEqual(self.click(0.5, "12"), "meter:12")    # on the one-chart bar
        self.assertEqual(self.click(3.0, "12"), "meter:12")    # beside it, inside the minimum zone
        self.assertIsNone(self.click(10.0, "12"))              # far to its right: nothing
        self.assertEqual(self.click(15.0, "10"), "meter:10")   # on the long bar
        self.assertIsNone(self.click(34.0, "10"))              # past the long bar's end

    def test_clicking_a_row_label_does_nothing(self):
        axes_box = self.instance.dist_ax.get_window_extent()
        row_px = self.instance.dist_ax.transData.transform((0, self.row_y["12"]))[1]
        self.assertIsNone(self.click_pixels(axes_box.x0 - 12, row_px))


class LiveDistributionStartupTests(unittest.TestCase):
    """Startup behaviour with a real window (proposal 0005, step 1): the two settings
    keys are validated, and the startup pack — the second pack site, reached only by
    a real _build — puts the panel ahead of the table with its recorded arguments."""

    def make_live_app(self, settings):
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings_path = Path(settings_dir.name) / "settings.json"
        if settings is not None:
            settings_path.write_text(json.dumps(settings))
        patcher = patch.object(app.LibraryApp, "_settings_file_path", staticmethod(lambda: settings_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(root.destroy)
        return app.LibraryApp(root)

    @staticmethod
    def padx_pair(info):
        padx = info["padx"]
        if isinstance(padx, int):
            return (padx, padx)
        return tuple(int(part) for part in str(padx).strip("()").replace(",", " ").split())

    def test_startup_validates_the_metric_and_packs_the_panel_first(self):
        application = self.make_live_app({"show_distribution": True, "distribution_metric": "Bogus"})
        # An unrecognised saved metric falls back to Meter; a valid show flag is honoured.
        self.assertEqual(application.distribution_metric.get(), "Meter")
        self.assertTrue(application.show_distribution_panel.get())
        self.assertEqual(application.dist_button.cget("text"), "Distribution ◀")
        # The startup pack's arguments (an absent before= cannot be asserted from
        # pack_info; the slaves order below is the observable consequence).
        info = application.dist_panel.pack_info()
        self.assertEqual(info["side"], "right")
        self.assertEqual(info["fill"], "y")
        self.assertEqual(self.padx_pair(info), (10, 0))
        slaves = application.content_frame.pack_slaves()
        self.assertLess(slaves.index(application.dist_panel), slaves.index(application.table_frame))
        # The chart canvas is created lazily on the first update while visible.
        if app.MATPLOTLIB_AVAILABLE:
            application.refresh_table()
            self.assertIsNotNone(application.dist_canvas)
            self.assertIsNotNone(application.dist_fig)

    def test_startup_keeps_a_valid_metric_and_stays_hidden_when_saved_so(self):
        application = self.make_live_app({"show_distribution": False, "distribution_metric": "BPM"})
        self.assertEqual(application.distribution_metric.get(), "BPM")
        self.assertFalse(application.show_distribution_panel.get())
        self.assertEqual(application.dist_panel.winfo_manager(), "")
        self.assertEqual(application.dist_button.cget("text"), "Distribution ▶")

    def test_live_hide_then_show_keeps_the_panel_mapped_with_width(self):
        application = self.make_live_app(None)
        root = application.root
        root.deiconify()
        if not application.show_distribution_panel.get():
            application.toggle_distribution_panel()
        root.update()
        self.assertTrue(application.dist_panel.winfo_ismapped())
        application.toggle_distribution_panel()
        root.update()
        self.assertFalse(application.dist_panel.winfo_ismapped())
        application.toggle_distribution_panel()
        root.update()
        # A smoke check that hide/show leaves the panel genuinely mapped at width
        # (the before= argument itself is pinned exactly by the mock tests).
        self.assertTrue(application.dist_panel.winfo_ismapped())
        self.assertGreater(application.dist_panel.winfo_width(), 0)

    def test_live_canvas_click_reaches_the_handler_and_filters(self):
        # The live half of the canvas pin (proposal 0005 §6): the headless test
        # proves the calls; here a click goes through the real TkAgg canvas's own
        # callback registry, the path a user's click actually takes.
        if not app.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib is not installed")
        from matplotlib.backend_bases import MouseEvent

        application = self.make_live_app({"show_distribution": True})
        application.rows = [
            {"Meter": 10, "Difficulty": "Hard", "bpm_max": 150.0, "Pack": "Test", "Type": "dance-single", "Grade": ""},
            {"Meter": 11, "Difficulty": "Challenge", "bpm_max": 180.0, "Pack": "Test", "Type": "dance-single", "Grade": ""},
        ]
        application.refresh_table()
        application.dist_canvas.draw()
        bar = next(b for b in application._current_dist_bars if b.label == "11")
        x_px, y_px = application.dist_ax.transData.transform((0.5, (bar.y_min + bar.y_max) / 2))
        event = MouseEvent("button_press_event", application.dist_canvas, x_px, y_px, button=1)
        application.dist_canvas.callbacks.process("button_press_event", event)
        self.assertEqual(application.search_var.get(), "meter:11")


if __name__ == "__main__":
    unittest.main()
