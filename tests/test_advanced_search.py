"""Tests for the Advanced Search component (advanced_search.py).

The dialog tests moved here from tests/test_library_visualizer.py with
the component in the proposal 0004 split; they drive it with mocked Tk
widgets, the same shape they had against the app method.
"""

import unittest
from unittest.mock import Mock, patch

import advanced_search
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


if __name__ == "__main__":
    unittest.main()
