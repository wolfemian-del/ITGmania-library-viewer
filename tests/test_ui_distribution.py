import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import distribution_panel as dp
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
        instance.search_var = Mock()
        instance.search_var.get.return_value = ""
        instance.diff_var = Mock()
        instance.diff_var.get.return_value = "All difficulties"
        instance.search_entry = Mock()
        instance.refresh_table = Mock()
        # The panel component, wired to the app the way _build wires it.
        panel = object.__new__(dp.DistributionPanel)
        panel._button = Mock()
        panel.search_var = instance.search_var
        panel.diff_var = instance.diff_var
        panel.show_distribution_panel = instance.show_distribution_panel
        panel.distribution_metric = instance.distribution_metric
        panel._filter_rows = Mock(return_value=[])
        panel._apply_chart_filter = instance.apply_chart_filter
        panel._save_settings = Mock()
        panel.dist_button = Mock()
        panel.dist_panel = Mock()
        panel._sibling_frame = lambda: Mock()
        panel.dist_banner_frame = Mock()
        panel.dist_banner_label = Mock()
        panel.dist_summary_var = Mock()
        panel.dist_chart_frame = Mock()
        panel.dist_canvas = Mock()
        panel.dist_fig = Mock()
        panel.dist_ax = Mock()
        panel.dist_ax.spines = {"top": Mock(), "right": Mock(), "left": Mock(), "bottom": Mock()}
        panel._current_dist_bars = []
        panel._last_visible_rows = []
        instance.distribution_panel = panel

        # Toggle open
        panel.toggle()
        instance.show_distribution_panel.set.assert_called_with(True)
        panel.dist_button.configure.assert_called_with(text="Distribution ◀")
        panel.dist_panel.pack.assert_called_once()

        # Update panel with sample rows
        sample_rows = [
            {"Meter": 10, "Difficulty": "Hard", "bpm_max": 150},
            {"Meter": 11, "Difficulty": "Challenge", "bpm_max": 180},
        ]
        mock_bar1 = Mock(get_y=Mock(return_value=0.0), get_height=Mock(return_value=0.68))
        mock_bar2 = Mock(get_y=Mock(return_value=1.0), get_height=Mock(return_value=0.68))
        panel.dist_ax.barh.return_value = [mock_bar1, mock_bar2]
        instance.show_distribution_panel.get.return_value = True
        panel.show_rows(sample_rows)
        panel.dist_summary_var.set.assert_called()

        # Simulate chart click on a meter bar
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "11", "11")]
        click_event = Mock()
        click_event.ydata = 0.5
        click_event.xdata = 0.1
        panel._on_chart_click(click_event)

        # The click's write lands through the app's callback, as one batched refresh.
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
            panel = application.distribution_panel
            # Panel initially closed or matches saved settings
            if application.show_distribution_panel.get():
                panel.toggle()
            self.assertFalse(application.show_distribution_panel.get())
            self.assertEqual(application.dist_button.cget("text"), "Distribution ▶")

            # Toggle open
            panel.toggle()
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
            panel._on_distribution_metric_changed()

            application.distribution_metric.set("BPM")
            panel._on_distribution_metric_changed()

            # Test clear filter
            application.diff_var.set("Challenge")
            panel.clear_chart_filter()
            self.assertEqual(application.diff_var.get(), "All difficulties")
        finally:
            root.destroy()

    def test_panel_width_and_wraplengths_scale_with_the_display_factor(self):
        """The panel frame is built at the theme width scaled by the display factor (issue #51),
        and the label wraplengths keep their proportional margins (Grok's #145 review nit: the
        fixed 24/90 subtractions would otherwise drift at high DPI)."""
        if app.tk is None:
            self.skipTest("Tkinter is not installed")
        try:
            root = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("No display available for Tk")
        try:
            content = app.tk.Frame(root)
            panel = dp.DistributionPanel(
                button_factory=Mock(return_value=Mock()),
                search_var=Mock(), diff_var=Mock(),
                show_distribution_panel=Mock(get=Mock(return_value=False)),
                distribution_metric=Mock(get=Mock(return_value="Meter")),
                filter_rows=Mock(return_value=[]),
                apply_chart_filter=Mock(), save_settings=Mock(),
                dpi_scale=1.5)
            panel.build_panel(content, Mock(), lambda: Mock())
            self.assertEqual(int(panel.dist_panel.cget("width")), 480)
            summary_label = next(
                child for child in panel.dist_panel.winfo_children()
                if isinstance(child, app.tk.Label)
                and str(child.cget("textvariable")) == str(panel.dist_summary_var))
            self.assertEqual(int(summary_label.cget("wraplength")), 480 - 36)
            self.assertEqual(int(panel.dist_banner_label.cget("wraplength")), 480 - 135)
        finally:
            root.destroy()

    def test_question_mark_bar_is_non_interactive(self):
        """Clicking the '?' bar should do nothing and not filter."""
        panel = object.__new__(dp.DistributionPanel)
        panel.distribution_metric = Mock(get=Mock(return_value="Meter"))
        panel.diff_var = Mock(get=Mock(return_value="All difficulties"))
        panel.search_var = Mock(get=Mock(return_value=""))
        panel._apply_chart_filter = Mock()
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "?", "")]

        event = Mock()
        event.ydata = 0.5
        event.xdata = 0.1
        panel._on_chart_click(event)

        panel._apply_chart_filter.assert_not_called()
        panel.search_var.set.assert_not_called()


class DistributionVisibilityTests(unittest.TestCase):
    """The visibility funnel (proposal 0005, step 1): hide, re-show, and the View-menu sync.

    Until now only the show direction was exercised, and without its pack arguments —
    the `before=` argument is the one a botched component move is most likely to drop,
    leaving the panel squeezed to zero width next to the table.
    """

    @staticmethod
    def make_instance(shown=True):
        panel = object.__new__(dp.DistributionPanel)
        panel.show_distribution_panel = Mock()
        panel.show_distribution_panel.get.return_value = shown
        panel.distribution_metric = Mock()
        panel.distribution_metric.get.return_value = "Meter"
        panel.dist_button = Mock()
        panel.dist_panel = Mock()
        panel.table_frame = Mock()  # the sibling the show path packs before (a test handle)
        panel._sibling_frame = lambda: panel.table_frame
        panel._save_settings = Mock()
        panel._last_visible_rows = [{"Meter": 10, "Difficulty": "Hard", "bpm_max": 150}]
        return panel

    def test_hide_then_show_repacks_with_full_arguments_and_saves(self):
        panel = self.make_instance(shown=True)

        panel.set_visible(False)
        panel.show_distribution_panel.set.assert_called_once_with(False)
        panel.dist_panel.pack_forget.assert_called_once_with()
        panel.dist_button.configure.assert_called_once_with(text="Distribution ▶")
        # The hide path calls update_idletasks on the panel frame itself (proposal 0005, Q6).
        panel.dist_panel.update_idletasks.assert_called_once_with()
        panel._save_settings.assert_called_once_with()

        panel.dist_panel.reset_mock()
        panel.dist_button.reset_mock()
        panel.show_distribution_panel.reset_mock()
        panel._save_settings.reset_mock()
        panel.show_rows = Mock()
        panel.set_visible(True)
        panel.show_distribution_panel.set.assert_called_once_with(True)
        # The full recorded pack arguments, including before= the table frame.
        panel.dist_panel.pack.assert_called_once_with(
            side="right", fill="y", padx=(10, 0), before=panel.table_frame)
        panel.dist_button.configure.assert_called_once_with(text="Distribution ◀")
        # Re-showing redraws from the rows stored while the panel was hidden.
        panel.show_rows.assert_called_once_with(panel._last_visible_rows)
        panel._save_settings.assert_called_once_with()
        # update_idletasks belongs to the hide path only.
        panel.dist_panel.update_idletasks.assert_not_called()

    def test_sync_distribution_toggle_applies_the_variable(self):
        # The View-menu checkbutton has already flipped the variable; sync applies it.
        panel = self.make_instance(shown=True)
        panel.show_rows = Mock()
        panel.sync_toggle()
        panel.dist_panel.pack.assert_called_once_with(
            side="right", fill="y", padx=(10, 0), before=panel.table_frame)

        panel = self.make_instance(shown=False)
        panel.sync_toggle()
        panel.dist_panel.pack_forget.assert_called_once_with()
        panel.dist_button.configure.assert_called_once_with(text="Distribution ▶")

    def test_before_build_panel_every_visibility_entry_is_a_no_op(self):
        # A toggle that fires before the app's _build has called build_panel must do nothing:
        # no variable write, no pack, no button label, no settings save. The constructor
        # itself leaves the panel unbuilt; a row push is only stored (proposal 0005 §5).
        show_var, save, sibling = Mock(), Mock(), Mock()
        panel = dp.DistributionPanel(
            button_factory=Mock(), search_var=Mock(), diff_var=Mock(),
            show_distribution_panel=show_var, distribution_metric=Mock(),
            filter_rows=Mock(), apply_chart_filter=Mock(), save_settings=save)
        panel._sibling_frame = sibling
        self.assertIsNone(panel.dist_panel)
        panel.set_visible(True)
        panel.set_visible(False)
        panel.toggle()
        panel.sync_toggle()
        panel.show_rows([{"Meter": 10}])
        show_var.set.assert_not_called()
        save.assert_not_called()
        sibling.assert_not_called()
        self.assertEqual(panel._last_visible_rows, [{"Meter": 10}])

    def test_canvas_creation_builds_the_figure_and_binds_the_click(self):
        panel = object.__new__(dp.DistributionPanel)
        panel.dist_canvas = None
        panel.dist_fig = None
        panel.dist_ax = None
        panel.dist_chart_frame = Mock()
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True), \
                patch.object(dp, "Figure", create=True) as figure_cls, \
                patch.object(dp, "FigureCanvasTkAgg", create=True) as canvas_cls:
            self.assertTrue(panel._ensure_distribution_canvas())
            figure_cls.assert_called_once_with(figsize=(3.0, 4.0), dpi=100, facecolor=theme.BG_PANEL)
            figure_cls.return_value.add_subplot.assert_called_once_with(111)
            canvas_cls.assert_called_once_with(figure_cls.return_value, master=panel.dist_chart_frame)
            canvas = canvas_cls.return_value
            canvas.mpl_connect.assert_called_once_with("button_press_event", panel._on_chart_click)
            canvas.get_tk_widget.return_value.pack.assert_called_once_with(fill="both", expand=True)
            # The created objects are the ones stored for later updates.
            self.assertIs(panel.dist_fig, figure_cls.return_value)
            self.assertIs(panel.dist_ax, figure_cls.return_value.add_subplot.return_value)
            self.assertIs(panel.dist_canvas, canvas)
            # A second call reuses the canvas instead of building another.
            self.assertTrue(panel._ensure_distribution_canvas())
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
        # The panel component, wired to the app the way _build wires it: the pull is the
        # app's own row filter, and filter changes go through the app's apply_chart_filter.
        panel = object.__new__(dp.DistributionPanel)
        panel._button = Mock()
        panel.search_var = instance.search_var
        panel.diff_var = instance.diff_var
        panel.show_distribution_panel = instance.show_distribution_panel
        panel.distribution_metric = instance.distribution_metric
        panel._filter_rows = instance._filter_rows
        panel._apply_chart_filter = instance.apply_chart_filter
        panel._save_settings = Mock()
        panel.dist_button = Mock()
        panel.dist_panel = Mock()
        panel.dist_banner_frame = Mock()
        panel.dist_banner_label = Mock()
        panel.dist_summary_var = Mock()
        panel.dist_chart_frame = Mock()
        panel.dist_canvas = Mock()
        panel.dist_fig = Mock()
        panel.dist_ax = Mock()
        panel.dist_ax.spines = {name: Mock() for name in ("top", "right", "left", "bottom")}
        panel._current_dist_bars = []
        panel._last_visible_rows = []
        instance.distribution_panel = panel
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
        panel = instance.distribution_panel
        visible = instance._filter_rows()
        self.assertEqual([row["Meter"] for row in visible], [11])

        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(visible)

        # Bars are drawn top-down (reversed): meter 12, 11, 10 -> counts 1, 1, 2.
        self.assertEqual(panel.dist_ax.barh.call_args.args[1], [1, 1, 2])
        self.assertEqual([bar[2] for bar in panel._current_dist_bars], ["12", "11", "10"])
        # The summary describes the bars shown, and the banner still names the active filter.
        self.assertIn("4 charts", panel.dist_summary_var.set.call_args.args[0])
        panel.dist_banner_label.configure.assert_called_with(text="Filtered by: Meter 11")

    def test_chart_ignores_only_its_own_filter(self):
        # Difficulty chart with meter:10 active: all difficulties among meter-10 charts, not meter 11/12.
        instance = self.make_app(query="meter:10", diff="Hard", metric="Difficulty")
        panel = instance.distribution_panel
        visible = instance._filter_rows()
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(6)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(visible)
        labels = [bar[2] for bar in panel._current_dist_bars]
        counts = dict(zip(labels, panel.dist_ax.barh.call_args.args[1]))
        self.assertEqual(counts["Hard"], 1)
        self.assertEqual(counts["Challenge"], 1)
        self.assertEqual(counts["Easy"], 0)

    def draw_difficulty_chart(self, diff="All difficulties", query=""):
        instance = self.make_app(query=query, diff=diff, metric="Difficulty")
        panel = instance.distribution_panel
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(6)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        return instance, {bar[2]: bar[3] for bar in panel._current_dist_bars}

    def test_rows_with_no_charts_are_not_clickable(self):
        instance, tokens = self.draw_difficulty_chart()
        panel = instance.distribution_panel
        self.assertEqual(tokens["Hard"], "Hard")
        self.assertEqual(tokens["Challenge"], "Challenge")
        for empty in ("Beginner", "Easy", "Medium", "Edit"):
            self.assertEqual(tokens[empty], "", empty)

        # Clicking an empty row changes nothing.
        y_of_easy = next(bar.y_min for bar in panel._current_dist_bars if bar.label == "Easy")
        panel._on_chart_click(Mock(ydata=y_of_easy + 0.1, xdata=0.1))
        instance.search_var.set.assert_not_called()
        instance.refresh_table.assert_not_called()

    def test_an_empty_row_that_is_the_active_filter_stays_clickable(self):
        # The dropdown is on "Easy", which has no charts here; clicking it again must switch it off.
        instance, tokens = self.draw_difficulty_chart(diff="Easy")
        self.assertEqual(tokens["Easy"], "Easy")
        self.assertEqual(tokens["Beginner"], "")

    def test_without_own_filter_chart_reuses_table_rows(self):
        instance = self.make_app(query="", metric="Meter", pack="Q")
        panel = instance.distribution_panel
        panel._filter_rows = Mock()
        panel._last_visible_rows = [self.ROWS[3]]
        self.assertEqual(panel._distribution_rows("Meter"), [self.ROWS[3]])
        panel._filter_rows.assert_not_called()

    def test_clicking_another_bar_replaces_filter_and_same_bar_clears_it(self):
        instance = self.make_app(query="Smiley meter:11", metric="Meter")
        panel = instance.distribution_panel
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "12", "12"), data.ChartBar(1.0, 2.0, "11", "11")]
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley meter:12")
        panel._on_chart_click(Mock(ydata=1.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

    def test_clicks_outside_a_bars_click_zone_do_nothing(self):
        instance = self.make_app(metric="Meter")
        panel = instance.distribution_panel
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "11", "11", 4.0)]
        # Past the end of the zone, left of the axis, off the row, or outside the plot (no position).
        for x, y in ((4.5, 0.5), (100.0, 0.5), (-0.5, 0.5), (1.0, 1.5), (None, 0.5), (1.0, None)):
            panel._on_chart_click(Mock(xdata=x, ydata=y))
        instance.search_var.set.assert_not_called()
        instance.refresh_table.assert_not_called()
        # Both ends of the zone count.
        panel._on_chart_click(Mock(xdata=4.0, ydata=0.5))
        instance.search_var.set.assert_called_with("meter:11")
        instance.search_var.set.reset_mock()
        panel._on_chart_click(Mock(xdata=0.0, ydata=0.5))
        instance.search_var.set.assert_called_with("meter:11")

    def test_click_zone_is_the_bar_plus_a_minimum_width(self):
        instance = self.make_app(metric="Meter")
        panel = instance.distribution_panel
        # 22 charts of meter 10, one of 11 and one of 12: the long bar sets the chart's width.
        instance.rows = list(self.ROWS[:1]) * 20 + list(self.ROWS)
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        widths = {bar.label: bar.click_width for bar in panel._current_dist_bars}
        minimum = 22 * theme.CHART_AXIS_HEADROOM * theme.CHART_MIN_CLICK_FRACTION  # the chart is 22 * headroom units wide
        self.assertEqual(set(widths), {"12", "11", "10"})
        self.assertAlmostEqual(widths["12"], minimum)   # one chart: widened to the minimum
        self.assertAlmostEqual(widths["11"], minimum)
        self.assertAlmostEqual(widths["10"], 22)         # the long bar: its own length
        panel.dist_ax.set_xlim.assert_called_with(0, 22 * theme.CHART_AXIS_HEADROOM)

    def test_clicking_a_bar_switches_off_a_hand_typed_version_of_its_filter(self):
        instance = self.make_app(query="Smiley meter:11.0", metric="Meter")
        panel = instance.distribution_panel
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "11", "11")]
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

        instance = self.make_app(query="Smiley bpm:<140 bpm:>=120", metric="BPM")
        panel = instance.distribution_panel
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "120-139", (">=120", "<140"))]
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

    def test_clicking_a_bpm_bar_sets_both_range_directives(self):
        instance = self.make_app(query="Smiley bpm:150", metric="BPM")
        panel = instance.distribution_panel
        panel._current_dist_bars = [data.ChartBar(0.0, 1.0, "120-139", (">=120", "<140"))]
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley bpm:>=120 bpm:<140")

        # Clicking the highlighted bar again removes both directives.
        instance.search_var.get.return_value = "Smiley bpm:>=120 bpm:<140"
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        instance.search_var.set.assert_called_with("Smiley")

    def test_banner_packs_with_a_filter_and_forgets_without_one(self):
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        instance = self.make_app(query="meter:11")
        panel = instance.distribution_panel
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        panel.dist_banner_frame.pack.assert_called_once_with(
            fill="x", pady=(0, 6), before=panel.dist_chart_frame)
        panel.dist_banner_frame.pack_forget.assert_not_called()

        instance = self.make_app(query="")
        panel = instance.distribution_panel
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        panel.dist_banner_frame.pack_forget.assert_called_once_with()
        panel.dist_banner_frame.pack.assert_not_called()

    def test_empty_state_draws_the_message_and_no_bars(self):
        instance = self.make_app()
        panel = instance.distribution_panel
        instance.rows = []
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows([])
        panel.dist_ax.text.assert_called_once()
        self.assertIn("No charts match", panel.dist_ax.text.call_args.args[2])
        panel.dist_ax.axis.assert_called_with("off")
        panel.dist_ax.barh.assert_not_called()
        self.assertEqual(panel._current_dist_bars, [])
        panel.dist_canvas.draw_idle.assert_called()

    def test_metric_change_redraws_for_the_new_metric_and_saves(self):
        instance = self.make_app(metric="Meter")
        panel = instance.distribution_panel
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(6)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
            self.assertEqual([bar[2] for bar in panel._current_dist_bars], ["12", "11", "10"])

            # Empty the library underneath the panel, and make the row pull return
            # nothing too: a redraw that recalculated its rows (instead of using the
            # stored ones) would now find nothing either way.
            instance.rows = []
            panel._filter_rows = Mock(return_value=[])
            instance.distribution_metric.get.return_value = "Difficulty"
            panel._on_distribution_metric_changed()

        panel._save_settings.assert_called_once_with()
        # The redraw used the stored rows and the new metric, not the meter bars again.
        labels = [bar[2] for bar in panel._current_dist_bars]
        self.assertIn("Hard", labels)
        self.assertIn("Challenge", labels)
        self.assertNotIn("10", labels)

    def test_bar_colours_and_the_active_bars_white_edge(self):
        instance, _tokens = self.draw_difficulty_chart(diff="Hard")
        panel = instance.distribution_panel
        labels = [bar.label for bar in panel._current_dist_bars]
        drawn = panel.dist_ax.barh.call_args
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
        panel = instance.distribution_panel
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        self.assertEqual(panel.dist_ax.barh.call_args.kwargs["color"], [theme.ACCENT] * 3)

        # A row with no meter value lands in the "?" bar, which takes its own colour.
        instance = self.make_app(metric="Meter")
        panel = instance.distribution_panel
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(2)]
        panel.dist_ax.barh.return_value = bars
        rows = [{"Meter": 10, "Difficulty": "Hard", "bpm_max": 150.0},
                {"Difficulty": "Hard", "bpm_max": 150.0}]
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(rows)
        labels = [bar.label for bar in panel._current_dist_bars]
        colours = panel.dist_ax.barh.call_args.kwargs["color"]
        self.assertEqual(colours[labels.index("?")], theme.CHART_BAR_UNKNOWN)
        self.assertEqual(colours[labels.index("10")], theme.ACCENT)

    def test_a_difficulty_name_the_table_does_not_know_gets_the_unknown_colour(self):
        instance = self.make_app(metric="Difficulty")
        panel = instance.distribution_panel
        instance.rows = [dict(self.ROWS[0], Difficulty="Quirky"), dict(self.ROWS[1], Difficulty="Hard")]
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(7)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        labels = [bar.label for bar in panel._current_dist_bars]
        colours = panel.dist_ax.barh.call_args.kwargs["color"]
        self.assertEqual(colours[labels.index("Quirky")], theme.DIFFICULTY_COLOR_UNKNOWN)
        self.assertEqual(colours[labels.index("Hard")], theme.DIFFICULTY_COLORS["Hard"])

    def test_a_normal_draw_ends_with_a_repaint(self):
        # Without draw_idle the chart is built but never shown until something else repaints it.
        instance = self.make_app(metric="Meter")
        panel = instance.distribution_panel
        bars = [Mock(get_y=Mock(return_value=float(i)), get_height=Mock(return_value=0.68)) for i in range(3)]
        panel.dist_ax.barh.return_value = bars
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(instance._filter_rows())
        panel.dist_canvas.draw_idle.assert_called_once_with()

    def test_rows_arriving_while_the_panel_is_hidden_are_stored_and_nothing_is_drawn(self):
        # The table keeps refreshing while the panel is closed; re-showing redraws from these rows.
        instance = self.make_app(metric="Meter")
        panel = instance.distribution_panel
        instance.show_distribution_panel.get.return_value = False
        panel._ensure_distribution_canvas = Mock()
        rows = [self.ROWS[0]]
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            panel.show_rows(rows)
        self.assertIs(panel._last_visible_rows, rows)
        # Hidden means hidden: no canvas is built, nothing is drawn, the banner and summary are left alone.
        panel._ensure_distribution_canvas.assert_not_called()
        panel.dist_ax.barh.assert_not_called()
        panel.dist_summary_var.set.assert_not_called()
        panel.dist_banner_frame.pack.assert_not_called()
        panel.dist_banner_frame.pack_forget.assert_not_called()


class MatplotlibMissingTests(unittest.TestCase):
    """The panel without matplotlib: no canvas, but the summary still updates.

    Moved from tests/test_library_visualizer.py in the component split (proposal
    0005, step 3); the availability flag now lives in the panel's own module.
    """

    def test_absence_fallback_when_matplotlib_unavailable(self):
        panel = object.__new__(dp.DistributionPanel)
        panel.show_distribution_panel = Mock(get=Mock(return_value=True))
        panel.distribution_metric = Mock(get=Mock(return_value="Meter"))
        panel.diff_var = Mock(get=Mock(return_value="All difficulties"))
        panel.search_var = Mock(get=Mock(return_value=""))
        panel._filter_rows = Mock(return_value=[])
        panel.dist_panel = Mock()
        panel.dist_banner_frame = Mock()
        panel.dist_banner_label = Mock()
        panel.dist_summary_var = Mock()
        panel.dist_chart_frame = None
        panel._matplotlib_missing_label = None
        panel._last_visible_rows = []

        original_avail = dp.MATPLOTLIB_AVAILABLE
        try:
            dp.MATPLOTLIB_AVAILABLE = False
            # When matplotlib is unavailable, _ensure_distribution_canvas returns False
            self.assertFalse(panel._ensure_distribution_canvas())
            # And show_rows does not crash
            panel.show_rows([{"Meter": 10}])
            panel.dist_summary_var.set.assert_called()
        finally:
            dp.MATPLOTLIB_AVAILABLE = original_avail

class LazyMatplotlibTests(unittest.TestCase):
    """The panel's matplotlib import is deferred to first use (startup polish):
    the module starts unresolved, and the resolver settles the flag once."""

    def test_the_resolver_imports_once_and_reports_availability(self):
        original_flag, original_figure = dp.MATPLOTLIB_AVAILABLE, dp.Figure
        try:
            dp.MATPLOTLIB_AVAILABLE = None
            dp.Figure = None
            self.assertTrue(dp._load_matplotlib())  # matplotlib is installed here
            self.assertIs(dp.MATPLOTLIB_AVAILABLE, True)
            self.assertIsNotNone(dp.Figure)
            # A second call is a no-op: the settled flag is reported as-is.
            self.assertTrue(dp._load_matplotlib())
        finally:
            dp.MATPLOTLIB_AVAILABLE, dp.Figure = original_flag, original_figure

    def test_a_settled_flag_is_not_re_resolved(self):
        original_flag = dp.MATPLOTLIB_AVAILABLE
        try:
            dp.MATPLOTLIB_AVAILABLE = False
            self.assertFalse(dp._load_matplotlib())
        finally:
            dp.MATPLOTLIB_AVAILABLE = original_flag


class ComponentCallbackTests(unittest.TestCase):
    """Clicks and Clears at the component's boundary (proposal 0005, step 3):
    the (difficulty, query) a chart action passes to apply_chart_filter, and
    the paths that must not call it at all."""

    @staticmethod
    def make_panel(metric="Meter", query="", diff="All difficulties", bars=None):
        panel = object.__new__(dp.DistributionPanel)
        panel.distribution_metric = Mock(get=Mock(return_value=metric))
        panel.diff_var = Mock(get=Mock(return_value=diff))
        panel.search_var = Mock(get=Mock(return_value=query))
        panel._apply_chart_filter = Mock()
        panel._current_dist_bars = bars if bars is not None else [data.ChartBar(0.0, 1.0, "11", "11")]
        return panel

    def test_a_meter_click_passes_the_query_only(self):
        panel = self.make_panel(query="Smiley")
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        panel._apply_chart_filter.assert_called_once_with(difficulty=None, query="Smiley meter:11")

    def test_a_difficulty_click_passes_the_dropdown_and_the_cleaned_query(self):
        panel = self.make_panel(metric="Difficulty", query="Smiley diff:hard",
                                bars=[data.ChartBar(0.0, 1.0, "Hard", "Hard")])
        panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        panel._apply_chart_filter.assert_called_once_with(
            difficulty="All difficulties", query="Smiley")

    def test_a_dead_click_calls_nothing(self):
        panel = self.make_panel()
        panel._on_chart_click(Mock(ydata=5.5, xdata=0.1))
        panel._apply_chart_filter.assert_not_called()

    def test_clear_passes_the_reset_difficulty_and_the_stripped_query(self):
        panel = self.make_panel(query="meter:11 Smiley", diff="Hard")
        panel.clear_chart_filter()
        panel._apply_chart_filter.assert_called_once_with(
            difficulty="All difficulties", query="Smiley")

    def test_clear_with_nothing_active_does_not_call_the_callback(self):
        # Proposal 0005 §5: a Clear with no active chart filter is a complete
        # no-op — pinned here, at the level where the moved code decides it.
        panel = self.make_panel(query="Smiley")
        panel.clear_chart_filter()
        panel._apply_chart_filter.assert_not_called()


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


class ApplyChartFilterTests(unittest.TestCase):
    """The app side of the chart-filter callback (proposal 0005, step 3):
    apply_chart_filter writes what it is given, in one batch, and nudges the
    search cursor — and a call with nothing to change does none of that."""

    @staticmethod
    def make_app(query="", diff="All difficulties"):
        instance = object.__new__(app.LibraryApp)
        instance.root = FakeRoot()
        instance.search_var, instance.diff_var = FakeVar(query), FakeVar(diff)
        instance.search_entry = Mock()
        instance.refreshes = 0
        instance.refresh_table = lambda *args, **kwargs: setattr(instance, "refreshes", instance.refreshes + 1)
        # The same wiring LibraryApp.__init__ does.
        instance.search_var.traces.append(instance._schedule_search_refresh)
        instance.diff_var.traces.append(instance._refresh_unless_batching)
        return instance

    def test_writing_both_refreshes_once_and_nudges_the_cursor(self):
        instance = self.make_app()
        instance.apply_chart_filter(difficulty="Hard", query="meter:11")
        self.assertEqual(instance.diff_var.get(), "Hard")
        self.assertEqual(instance.search_var.get(), "meter:11")
        instance.root.run_pending()
        self.assertEqual(instance.refreshes, 1)
        instance.search_entry.icursor.assert_called_once_with("end")

    def test_a_query_only_write_leaves_the_difficulty_alone(self):
        instance = self.make_app(diff="Hard")
        instance.apply_chart_filter(query="Smiley")
        self.assertEqual(instance.diff_var.get(), "Hard")
        self.assertEqual(instance.search_var.get(), "Smiley")
        instance.search_entry.icursor.assert_called_once_with("end")

    def test_nothing_to_change_neither_refreshes_nor_nudges(self):
        instance = self.make_app(query="Smiley", diff="Hard")
        instance.apply_chart_filter()
        instance.root.run_pending()
        self.assertEqual((instance.diff_var.get(), instance.search_var.get()), ("Hard", "Smiley"))
        self.assertEqual(instance.refreshes, 0)
        instance.search_entry.icursor.assert_not_called()


class SingleRefreshTests(unittest.TestCase):
    """One chart click or Clear rebuilds the table once, not once per filter variable."""

    @staticmethod
    def make_app(metric, query="", diff="All difficulties", bars=None):
        instance = object.__new__(app.LibraryApp)
        instance.root = FakeRoot()
        instance.search_var, instance.diff_var = FakeVar(query), FakeVar(diff)
        instance.search_entry = Mock()
        instance.distribution_metric = FakeVar(metric)
        instance.refreshes = 0
        instance.refresh_table = lambda *args, **kwargs: setattr(instance, "refreshes", instance.refreshes + 1)
        # The same wiring LibraryApp.__init__ does.
        instance.search_var.traces.append(instance._schedule_search_refresh)
        instance.diff_var.traces.append(instance._refresh_unless_batching)
        # The panel component, wired to the app the way _build wires it.
        panel = object.__new__(dp.DistributionPanel)
        panel.search_var = instance.search_var
        panel.diff_var = instance.diff_var
        panel.show_distribution_panel = FakeVar(False)
        panel.distribution_metric = instance.distribution_metric
        panel._filter_rows = instance._filter_rows
        panel._apply_chart_filter = instance.apply_chart_filter
        panel._save_settings = Mock()
        panel._current_dist_bars = bars or [data.ChartBar(0.0, 1.0, "11", "11")]
        panel._last_visible_rows = []
        instance.distribution_panel = panel
        return instance

    def refreshes_after_everything_settles(self, instance):
        instance.root.run_pending()  # lets any delayed search refresh fire
        return instance.refreshes

    def test_meter_click_refreshes_once(self):
        instance = self.make_app("Meter", "Smiley")
        instance.distribution_panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)

    def test_difficulty_click_that_also_cleans_the_search_box_refreshes_once(self):
        instance = self.make_app("Difficulty", "Smiley diff:hard", bars=[data.ChartBar(0.0, 1.0, "Hard", "Hard")])
        instance.distribution_panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        self.assertEqual(instance.search_var.get(), "Smiley")
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)

    def test_clear_with_several_filters_refreshes_once(self):
        instance = self.make_app("Meter", "meter:11 Smiley", diff="Hard")
        instance.distribution_panel.clear_chart_filter()
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
        instance.distribution_panel._on_chart_click(Mock(ydata=0.5, xdata=0.1))
        self.assertEqual(self.refreshes_after_everything_settles(instance), 1)


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib is not installed")
class RealChartClickTests(unittest.TestCase):
    """Draws the real chart with matplotlib's Agg backend (no Tk needed) and clicks at real positions."""

    def setUp(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        self.instance = FullDistributionTests.make_app(metric="Meter")
        self.panel = self.instance.distribution_panel
        row = {"Difficulty": "Hard", "Pack": "P", "Type": "dance-single", "Grade": "",
               "bpm_min": 130.0, "bpm_max": 130.0}
        # One chart each of meter 12 and 11, thirty of meter 10: a very short bar next to a long one.
        self.instance.rows = ([dict(row, Meter=12), dict(row, Meter=11)]
                              + [dict(row, Meter=10) for _ in range(30)])
        figure = Figure(figsize=(3.0, 4.0), dpi=100)
        self.panel.dist_fig, self.panel.dist_ax = figure, figure.add_subplot(111)
        self.panel.dist_canvas = FigureCanvasAgg(figure)
        with patch.object(dp, "MATPLOTLIB_AVAILABLE", True):
            self.panel.show_rows(self.instance._filter_rows())
        self.panel.dist_canvas.draw()
        self.row_y = {bar.label: (bar.y_min + bar.y_max) / 2 for bar in self.panel._current_dist_bars}

    def click(self, x_data, label):
        """Click at a chart position; return the search text the click applied, or None."""
        x_px, y_px = self.panel.dist_ax.transData.transform((x_data, self.row_y[label]))
        return self.click_pixels(x_px, y_px)

    def click_pixels(self, x_px, y_px):
        from matplotlib.backend_bases import MouseEvent

        self.instance.search_var.set.reset_mock()
        self.panel._on_chart_click(
            MouseEvent("button_press_event", self.panel.dist_canvas, x_px, y_px, button=1))
        call = self.instance.search_var.set.call_args
        return call.args[0] if call else None

    def test_a_short_bar_is_easy_to_hit_and_far_blank_space_is_not(self):
        self.assertEqual(self.click(0.5, "12"), "meter:12")    # on the one-chart bar
        self.assertEqual(self.click(3.0, "12"), "meter:12")    # beside it, inside the minimum zone
        self.assertIsNone(self.click(10.0, "12"))              # far to its right: nothing
        self.assertEqual(self.click(15.0, "10"), "meter:10")   # on the long bar
        self.assertIsNone(self.click(34.0, "10"))              # past the long bar's end

    def test_clicking_a_row_label_does_nothing(self):
        axes_box = self.panel.dist_ax.get_window_extent()
        row_px = self.panel.dist_ax.transData.transform((0, self.row_y["12"]))[1]
        self.assertIsNone(self.click_pixels(axes_box.x0 - 12, row_px))


class LiveWindowCase(unittest.TestCase):
    """Opens a real LibraryApp for the live tests below. It has no tests of its own, so the
    classes that share it do not each re-run the other's tests."""

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


class LiveDistributionStartupTests(LiveWindowCase):
    """Startup behaviour with a real window (proposal 0005, step 1): the two settings
    keys are validated, and the startup pack — the second pack site, reached only by
    a real _build — puts the panel ahead of the table with its recorded arguments."""

    def test_startup_validates_the_metric_and_packs_the_panel_first(self):
        application = self.make_live_app({"show_distribution": True, "distribution_metric": "Bogus"})
        panel = application.distribution_panel
        # An unrecognised saved metric falls back to Meter; a valid show flag is honoured.
        self.assertEqual(application.distribution_metric.get(), "Meter")
        self.assertTrue(application.show_distribution_panel.get())
        self.assertEqual(application.dist_button.cget("text"), "Distribution ◀")
        # The startup pack's arguments (an absent before= cannot be asserted from
        # pack_info; the slaves order below is the observable consequence).
        info = panel.dist_panel.pack_info()
        self.assertEqual(info["side"], "right")
        self.assertEqual(info["fill"], "y")
        self.assertEqual(self.padx_pair(info), (10, 0))
        slaves = application.content_frame.pack_slaves()
        self.assertLess(slaves.index(panel.dist_panel), slaves.index(application.table_frame))
        # The chart canvas is created lazily on the first update while visible.
        if dp._load_matplotlib():
            application.refresh_table()
            self.assertIsNotNone(panel.dist_canvas)
            self.assertIsNotNone(panel.dist_fig)

    def test_startup_keeps_a_valid_metric_and_stays_hidden_when_saved_so(self):
        application = self.make_live_app({"show_distribution": False, "distribution_metric": "BPM"})
        panel = application.distribution_panel
        self.assertEqual(application.distribution_metric.get(), "BPM")
        self.assertFalse(application.show_distribution_panel.get())
        self.assertEqual(panel.dist_panel.winfo_manager(), "")
        self.assertEqual(application.dist_button.cget("text"), "Distribution ▶")

    def test_live_hide_then_show_keeps_the_panel_mapped_with_width(self):
        application = self.make_live_app(None)
        panel = application.distribution_panel
        root = application.root
        root.deiconify()
        if not application.show_distribution_panel.get():
            panel.toggle()
        root.update()
        self.assertTrue(panel.dist_panel.winfo_ismapped())
        panel.toggle()
        root.update()
        self.assertFalse(panel.dist_panel.winfo_ismapped())
        panel.toggle()
        root.update()
        # A smoke check that hide/show leaves the panel genuinely mapped at width
        # (the before= argument itself is pinned exactly by the mock tests).
        self.assertTrue(panel.dist_panel.winfo_ismapped())
        self.assertGreater(panel.dist_panel.winfo_width(), 0)

    def test_live_canvas_click_reaches_the_handler_and_filters(self):
        # The live half of the canvas pin (proposal 0005 §6): the headless test
        # proves the calls; here a click goes through the real TkAgg canvas's own
        # callback registry, the path a user's click actually takes.
        if not dp._load_matplotlib():
            self.skipTest("matplotlib is not installed")
        from matplotlib.backend_bases import MouseEvent

        application = self.make_live_app({"show_distribution": True})
        panel = application.distribution_panel
        application.rows = [
            {"Meter": 10, "Difficulty": "Hard", "bpm_max": 150.0, "Pack": "Test", "Type": "dance-single", "Grade": ""},
            {"Meter": 11, "Difficulty": "Challenge", "bpm_max": 180.0, "Pack": "Test", "Type": "dance-single", "Grade": ""},
        ]
        application.refresh_table()
        panel.dist_canvas.draw()
        bar = next(b for b in panel._current_dist_bars if b.label == "11")
        x_px, y_px = panel.dist_ax.transData.transform((0.5, (bar.y_min + bar.y_max) / 2))
        event = MouseEvent("button_press_event", panel.dist_canvas, x_px, y_px, button=1)
        panel.dist_canvas.callbacks.process("button_press_event", event)
        self.assertEqual(application.search_var.get(), "meter:11")


class LiveDistributionWiringTests(LiveWindowCase):
    """The wiring guard for the component (proposal 0005, step 3): in a real window,
    the component holds the app's own variables, build_panel actually ran, refresh
    reaches show_rows, and all seven entry points land on the component."""

    def test_the_component_shares_the_apps_variables_and_was_built(self):
        application = self.make_live_app({"show_distribution": True})
        panel = application.distribution_panel
        # The four variables are the same objects, not copies.
        self.assertIs(panel.search_var, application.search_var)
        self.assertIs(panel.diff_var, application.diff_var)
        self.assertIs(panel.show_distribution_panel, application.show_distribution_panel)
        self.assertIs(panel.distribution_metric, application.distribution_metric)
        # build_panel actually ran: without it the component would sit inert
        # behind its None guards and every other check here would pass vacuously.
        self.assertIsNotNone(panel.dist_panel)
        self.assertIn(panel.dist_panel, application.content_frame.winfo_children())
        self.assertIs(panel.dist_button, application.dist_button)

    def test_refresh_reaches_show_rows(self):
        application = self.make_live_app({"show_distribution": True})
        panel = application.distribution_panel
        with patch.object(panel, "show_rows", wraps=panel.show_rows) as spy:
            application.refresh_table()
        spy.assert_called()

    def test_all_seven_entry_points_land_on_the_component(self):
        application = self.make_live_app({"show_distribution": True})
        panel = application.distribution_panel
        root = application.root
        root.deiconify()
        root.update()
        self.assertTrue(application.show_distribution_panel.get())

        # 1. The toolbar button toggles through the component.
        application.dist_button.invoke()
        root.update()
        self.assertFalse(application.show_distribution_panel.get())
        self.assertFalse(panel.dist_panel.winfo_ismapped())

        # 2. The View menu's checkbutton syncs through the component.
        menubar = root.nametowidget(root.cget("menu"))
        view_menu = None
        for i in range(menubar.index("end") + 1):
            if menubar.type(i) == "cascade" and menubar.entrycget(i, "label") == "View":
                view_menu = root.nametowidget(menubar.entrycget(i, "menu"))
                break
        self.assertIsNotNone(view_menu)
        view_menu.invoke(view_menu.index("Show distribution panel"))
        root.update()
        self.assertTrue(application.show_distribution_panel.get())
        self.assertTrue(panel.dist_panel.winfo_ismapped())

        # 3. The panel's own ✕ hides it again.
        header = panel.dist_panel.winfo_children()[0]
        close_button = next(w for w in header.winfo_children() if isinstance(w, app.tk.Button))
        close_button.invoke()
        root.update()
        self.assertFalse(application.show_distribution_panel.get())

        # Show it again for the remaining entry points.
        panel.set_visible(True)
        root.update()

        # 4. A metric radio runs the component's metric handler. A Tk radio button sets its own
        # variable whether or not a command is attached, so the variable alone proves nothing
        # about the wiring; spy on what the handler does (save settings, redraw) instead.
        metric_bar = panel.dist_panel.winfo_children()[1]
        radios = {w.cget("value"): w for w in metric_bar.winfo_children()
                  if isinstance(w, app.tk.Radiobutton)}
        with patch.object(panel, "_save_settings") as save, patch.object(panel, "show_rows") as redraw:
            radios["BPM"].invoke()
        self.assertEqual(application.distribution_metric.get(), "BPM")
        save.assert_called_once_with()
        redraw.assert_called_once_with(panel._last_visible_rows)
        radios["Meter"].invoke()
        self.assertEqual(application.distribution_metric.get(), "Meter")

        # 5. The banner's Clear button runs the component's Clear.
        application.search_var.set("meter:11")
        application.refresh_table()
        root.update()
        clear_button = next(w for w in panel.dist_banner_frame.winfo_children()
                            if isinstance(w, app.tk.Button))
        clear_button.invoke()
        self.assertEqual(application.search_var.get(), "")

        # 6. The refresh push is covered by test_refresh_reaches_show_rows.

        # 7. The chart click: the handler registered on the canvas is the component's.
        if dp._load_matplotlib():
            application.refresh_table()
            self.assertIsNotNone(panel.dist_canvas)
            handlers = [ref() for ref in
                        panel.dist_canvas.callbacks.callbacks["button_press_event"].values()]
            self.assertIn(panel._on_chart_click, handlers)


if __name__ == "__main__":
    unittest.main()
