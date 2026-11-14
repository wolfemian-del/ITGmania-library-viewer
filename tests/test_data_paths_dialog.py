"""Tests for the Data paths dialog component (proposal 0009 Step 3).

Headless: the dialog is built bare or with Mock widgets, so these run
without a display. The live dialog tests stay in
tests/test_library_visualizer.py — the windows-ui job runs exactly two test
files, and a new file would need a workflow edit only the owner can make.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from data_paths_dialog import DataPathsDialog


class DataPathsPopupTests(unittest.TestCase):
    """The first-run Data paths popup (UI redesign): maybe_show_first_run
    opens it once at startup only when no snapshot is loaded and the paths
    are not both usable, with the note naming the situation."""

    @staticmethod
    def make_dialog(cache_dir, stats_file):
        dialog = DataPathsDialog(
            parent=Mock(), cache_var=Mock(), stats_var=Mock(),
            load_callback=Mock(), save_settings=Mock(),
            button_factory=Mock(), entry_factory=Mock(), dpi_scale=1.0,
            paths_match_loaded=Mock(return_value=True))
        dialog.cache_var.get.return_value = str(cache_dir)
        dialog.stats_var.get.return_value = str(stats_file)
        dialog.open = Mock()
        return dialog

    def test_first_run_opens_with_the_first_run_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dialog = self.make_dialog(root / "Cache" / "Songs", root / "Stats.xml")
            dialog.maybe_show_first_run(snapshot_loaded=False, had_saved_paths=False)
        dialog.open.assert_called_once_with(
            note=DataPathsDialog._DATA_PATHS_FIRST_RUN_NOTE)

    def test_dead_saved_paths_get_the_dead_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dialog = self.make_dialog(root / "Cache" / "Songs", root / "Stats.xml")
            dialog.maybe_show_first_run(snapshot_loaded=False, had_saved_paths=True)
        dialog.open.assert_called_once_with(
            note=DataPathsDialog._DATA_PATHS_DEAD_NOTE)

    def test_no_popup_when_a_snapshot_is_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dialog = self.make_dialog(root / "Cache" / "Songs", root / "Stats.xml")
            dialog.maybe_show_first_run(snapshot_loaded=True, had_saved_paths=True)
        dialog.open.assert_not_called()

    def test_no_popup_when_both_paths_are_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            cache_dir.mkdir(parents=True)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            dialog = self.make_dialog(cache_dir, stats_file)
            dialog.maybe_show_first_run(snapshot_loaded=False, had_saved_paths=False)
        dialog.open.assert_not_called()

    def test_popup_shows_only_once_per_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dialog = self.make_dialog(root / "Cache" / "Songs", root / "Stats.xml")
            dialog.maybe_show_first_run(snapshot_loaded=False, had_saved_paths=False)
            dialog.maybe_show_first_run(snapshot_loaded=False, had_saved_paths=False)
        dialog.open.assert_called_once()


class DataPathsNoteTests(unittest.TestCase):
    """The Data paths dialog's note line (set_note): it shows the note above
    the path rows when there is one, hides the label when there is not, and
    does nothing when the dialog is closed."""

    @staticmethod
    def make_dialog(note=None, form=None):
        dialog = object.__new__(DataPathsDialog)
        dialog.dpi_scale = 1.0
        if note is not None:
            dialog._data_paths_note = note
        if form is not None:
            dialog._data_paths_form = form
        return dialog

    def test_no_dialog_open_is_a_no_op(self):
        dialog = self.make_dialog()
        dialog.set_note("anything")  # no error, no label

    def test_non_empty_note_is_shown_above_the_form(self):
        note, form = Mock(), Mock()
        dialog = self.make_dialog(note, form)

        dialog.set_note("The cache folder was not found.")

        note.configure.assert_called_once_with(
            text="The cache folder was not found.")
        note.pack.assert_called_once()
        self.assertIs(note.pack.call_args.kwargs["before"], form)
        note.pack_forget.assert_not_called()

    def test_empty_note_hides_the_label(self):
        note = Mock()
        dialog = self.make_dialog(note, Mock())

        dialog.set_note("")

        note.configure.assert_called_once_with(text="")
        note.pack_forget.assert_called_once()
        note.pack.assert_not_called()


class PathsChangedTests(unittest.TestCase):
    """paths_changed: the note the dialog should show when the paths may
    have moved — empty when they match the loaded snapshot, the differ note
    when they have moved away from it."""

    @staticmethod
    def make_dialog(match):
        dialog = object.__new__(DataPathsDialog)
        dialog.paths_match_loaded = Mock(return_value=match)
        return dialog

    def test_matching_paths_have_no_note(self):
        dialog = self.make_dialog(match=True)
        self.assertEqual(dialog.paths_changed(), "")

    def test_differing_paths_get_the_differ_note(self):
        dialog = self.make_dialog(match=False)
        self.assertEqual(
            dialog.paths_changed(), DataPathsDialog._DATA_PATHS_DIFFER_NOTE)


if __name__ == "__main__":
    unittest.main()
