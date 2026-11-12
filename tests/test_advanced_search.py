"""Tests for the Advanced Search component (advanced_search.py).

The dialog tests moved here from tests/test_library_visualizer.py with
the component in the proposal 0004 split; they drive it with mocked Tk
widgets, the same shape they had against the app method.
"""

import unittest
from unittest.mock import Mock, patch

import advanced_search
import theme
from advanced_search import AdvancedSearch


def make_component(search_text=""):
    search_var = Mock()
    search_var.get.return_value = search_text
    return AdvancedSearch(
        Mock(),
        Mock(return_value=Mock()),
        Mock(return_value=Mock()),
        Mock(return_value=Mock()),
        search_var,
    )


class AdvancedSearchDialogTests(unittest.TestCase):
    def test_open_dialog_binds_escape_and_return(self):
        component = make_component()

        mock_window = Mock()
        bindings = {}

        def mock_bind(seq, func):
            bindings[seq] = func

        mock_window.bind.side_effect = mock_bind
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window

        with patch.object(advanced_search, "tk", mock_tk):
            component.open_dialog()

        self.assertIn("<Escape>", bindings)
        self.assertIn("<Return>", bindings)
        # The window takes keyboard focus itself, so Escape and Return reach it without a click first.
        mock_window.focus_force.assert_called_once()

        # Escape closes the dialog without touching the main search text and stops the key event.
        res_esc = bindings["<Escape>"]()
        self.assertEqual(res_esc, "break")
        mock_window.destroy.assert_called_once()
        component._search_var.set.assert_not_called()

        # Return writes the built query to the main search box, closes the dialog and stops the key event.
        mock_window.destroy.reset_mock()
        res_ret = bindings["<Return>"]()
        self.assertEqual(res_ret, "break")
        component._search_var.set.assert_called_once()
        mock_window.destroy.assert_called_once()

    def test_opening_a_dialog_that_is_already_open_raises_it_and_gives_it_focus(self):
        component = make_component()
        existing = Mock()
        existing.winfo_exists.return_value = True
        component.window = existing
        mock_tk = Mock()
        with patch.object(advanced_search, "tk", mock_tk):
            component.open_dialog()
        existing.lift.assert_called_once()
        existing.focus_force.assert_called_once()
        mock_tk.Toplevel.assert_not_called()  # no second window


class AdvancedSearchGeometryTests(unittest.TestCase):
    """Window geometry memory (issue #98): restore on open, report on close.

    Mirrors the course window's tests (issue #25) against the same rules.
    """

    def open_component(self, saved_geometry=None, report_geometry=None, vroot=(0, 0, 1920, 1080), dpi_scale=1.0):
        parent = Mock()
        parent.winfo_vrootx.return_value = vroot[0]
        parent.winfo_vrooty.return_value = vroot[1]
        parent.winfo_vrootwidth.return_value = vroot[2]
        parent.winfo_vrootheight.return_value = vroot[3]
        search_var = Mock()
        search_var.get.return_value = ""
        button_factory = Mock(return_value=Mock())
        component = AdvancedSearch(
            parent,
            Mock(return_value=Mock()),
            button_factory,
            Mock(return_value=Mock()),
            search_var,
            saved_geometry=saved_geometry,
            report_geometry=report_geometry,
            dpi_scale=dpi_scale,
        )
        mock_window = Mock()
        bindings = {}
        mock_window.bind.side_effect = lambda seq, func: bindings.__setitem__(seq, func)
        protocols = {}
        mock_window.protocol.side_effect = lambda name, func: protocols.__setitem__(name, func)
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        with patch.object(advanced_search, "tk", mock_tk):
            component.open_dialog()
        return component, mock_window, bindings, protocols, button_factory

    def test_open_restores_the_saved_geometry_when_its_position_is_visible(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(
            saved_geometry="700x640+30+40")
        mock_window.geometry.assert_called_once_with("700x640+30+40")

    def test_open_scales_the_saved_geometry_at_150_percent(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(
            saved_geometry="700x640+30+40", dpi_scale=1.5)
        mock_window.geometry.assert_called_once_with("1050x960+45+60")

    def test_open_scales_the_theme_default_without_a_saved_geometry(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(dpi_scale=1.5)
        mock_window.geometry.assert_called_once_with("840x930")

    def test_open_scales_the_minimum_size(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(dpi_scale=1.5)
        mock_window.minsize.assert_called_once_with(720, 780)

    def test_open_uses_the_scaled_threshold_for_a_narrow_sliver(self):
        # 135 physical pixels would show at the unscaled 100 px threshold
        # but not at the scaled 150 px one, so the position is dropped.
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(
            saved_geometry="700x640+-610+40", dpi_scale=1.5)
        mock_window.geometry.assert_called_once_with("1050x960")

    def test_save_window_geometry_reports_canonical_units(self):
        component, mock_window, _bindings, _protocols, _buttons, report = self.open_for_close()
        component._dpi_scale = 1.5
        mock_window.geometry.return_value = "1050x960+45+60"
        component.save_window_geometry()
        report.assert_called_once_with("700x640+30+40")
        self.assertEqual(component._saved_geometry, "700x640+30+40")

    def test_open_uses_the_theme_default_without_a_saved_geometry(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component()
        mock_window.geometry.assert_called_once_with(theme.ADVANCED_SEARCH_GEOMETRY)

    def test_open_falls_back_to_size_only_when_the_saved_position_is_off_screen(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(
            saved_geometry="700x640+5000+40")
        mock_window.geometry.assert_called_once_with("700x640")

    def test_open_falls_back_to_size_only_when_only_a_sliver_would_show(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(
            saved_geometry="700x640+1880+40")
        mock_window.geometry.assert_called_once_with("700x640")

    def test_open_falls_back_to_size_only_when_the_title_bar_is_out_of_reach(self):
        _component, mock_window, _bindings, _protocols, _buttons = self.open_component(
            saved_geometry="700x640+30-40")
        mock_window.geometry.assert_called_once_with("700x640")

    def open_for_close(self):
        report = Mock()
        component, mock_window, bindings, protocols, button_factory = self.open_component(
            report_geometry=report)
        mock_window.state.return_value = "normal"
        mock_window.geometry.return_value = "700x640+30+40"
        return component, mock_window, bindings, protocols, button_factory, report

    def test_escape_reports_the_geometry_and_destroys(self):
        _component, mock_window, bindings, _protocols, _buttons, report = self.open_for_close()
        bindings["<Escape>"]()
        report.assert_called_once_with("700x640+30+40")
        mock_window.destroy.assert_called_once()

    def test_window_close_button_reports_the_geometry_and_destroys(self):
        _component, mock_window, _bindings, protocols, _buttons, report = self.open_for_close()
        protocols["WM_DELETE_WINDOW"]()
        report.assert_called_once_with("700x640+30+40")
        mock_window.destroy.assert_called_once()

    def test_close_button_reports_the_geometry_and_destroys(self):
        _component, mock_window, _bindings, _protocols, button_factory, report = self.open_for_close()
        close_command = next(call.args[2] for call in button_factory.call_args_list
                             if call.args[1] == "Close")
        close_command()
        report.assert_called_once_with("700x640+30+40")
        mock_window.destroy.assert_called_once()

    def test_apply_reports_the_geometry_and_destroys(self):
        _component, mock_window, bindings, _protocols, _buttons, report = self.open_for_close()
        bindings["<Return>"]()
        report.assert_called_once_with("700x640+30+40")
        mock_window.destroy.assert_called_once()

    def test_close_still_destroys_but_does_not_report_while_minimized(self):
        _component, mock_window, bindings, _protocols, _buttons, report = self.open_for_close()
        mock_window.state.return_value = "iconic"
        bindings["<Escape>"]()
        report.assert_not_called()
        mock_window.destroy.assert_called_once()

    def test_save_window_geometry_without_a_window_is_a_no_op(self):
        report = Mock()
        component = make_component()
        component._report_geometry = report
        component.save_window_geometry()  # window is None: must not raise
        report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
