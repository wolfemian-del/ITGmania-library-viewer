import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
