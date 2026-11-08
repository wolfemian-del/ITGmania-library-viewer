"""Tests for the shared row-tint module (row_tints.py, issue #84)."""
import unittest
from unittest.mock import Mock

import row_tints
import theme


class DifficultyTagTests(unittest.TestCase):
    def test_known_difficulties_get_their_own_tag(self):
        self.assertEqual(row_tints.difficulty_tag({"Difficulty": "Hard"}), "diff_Hard")
        self.assertEqual(row_tints.difficulty_tag({"Difficulty": "Edit"}), "diff_Edit")

    def test_unknown_and_missing_difficulties_get_the_unknown_tag(self):
        self.assertEqual(row_tints.difficulty_tag({"Difficulty": "CustomUnknown"}),
                         row_tints.UNKNOWN_DIFFICULTY_TAG)
        self.assertEqual(row_tints.difficulty_tag({}), row_tints.UNKNOWN_DIFFICULTY_TAG)

    def test_the_difficulty_name_is_stripped(self):
        self.assertEqual(row_tints.difficulty_tag({"Difficulty": " Hard "}), "diff_Hard")

    def test_row_tags_add_the_white_tag_only_when_selected(self):
        row = {"Difficulty": "Hard"}
        self.assertEqual(row_tints.row_tags(row), ("diff_Hard",))
        self.assertEqual(row_tints.row_tags(row, selected=True), ("diff_Hard", "selected_row"))


class ConfigureTreeTagsTests(unittest.TestCase):
    def test_configures_all_difficulties_unknown_and_selection_last(self):
        tree = Mock()
        row_tints.configure_tree_tags(tree)
        # One tag per difficulty, one for unknown difficulties, and the selection tag.
        self.assertEqual(tree.tag_configure.call_count, len(theme.DIFFICULTY_COLORS) + 2)
        for diff, color in theme.DIFFICULTY_COLORS.items():
            tree.tag_configure.assert_any_call(f"diff_{diff}", foreground=color)
        tree.tag_configure.assert_any_call(
            row_tints.UNKNOWN_DIFFICULTY_TAG, foreground=theme.DIFFICULTY_COLOR_UNKNOWN)
        # The selection tag must be configured last, or selected rows would not turn white.
        self.assertEqual(tree.tag_configure.call_args_list[-1].args[0], "selected_row")
        tree.tag_configure.assert_any_call("selected_row", foreground=theme.TEXT_ON_ACCENT)


class SelectedRowTintTests(unittest.TestCase):
    def _tint_with_store(self, titles=("A", "B")):
        """A SelectedRowTint over a fake tree whose item tags live in a dict."""
        tree = Mock()
        store = {str(index): ("diff_Hard",) for index in range(len(titles))}

        def fake_item(item_id, option=None, **kwargs):
            if "tags" in kwargs:
                store[item_id] = tuple(kwargs["tags"])
                return ""
            return store.get(item_id, ())

        tree.item.side_effect = fake_item
        tree.exists.return_value = True
        return row_tints.SelectedRowTint(tree), tree, store

    def test_on_select_moves_the_white_tag_with_the_selection(self):
        tint, tree, store = self._tint_with_store()

        tree.selection.return_value = ("1",)
        tint.on_select()
        self.assertEqual(store["1"], ("diff_Hard", "selected_row"))
        self.assertEqual(store["0"], ("diff_Hard",))
        self.assertEqual(tint.items, {"1"})

        tree.selection.return_value = ("0",)
        tint.on_select()
        self.assertEqual(store["0"], ("diff_Hard", "selected_row"))
        self.assertEqual(store["1"], ("diff_Hard",))
        self.assertEqual(tint.items, {"0"})

    def test_on_select_skips_rows_a_refresh_already_removed(self):
        tint, tree, _store = self._tint_with_store()
        tree.exists.return_value = False
        tint.items = {"gone"}
        tree.selection.return_value = []

        tint.on_select()

        tree.item.assert_not_called()
        self.assertEqual(tint.items, set())

    def test_note_selected_and_reset_track_inserted_rows(self):
        tint, _tree, _store = self._tint_with_store()
        tint.note_selected("0")
        self.assertEqual(tint.items, {"0"})
        tint.reset(["1"])
        self.assertEqual(tint.items, {"1"})
        tint.reset()
        self.assertEqual(tint.items, set())


if __name__ == "__main__":
    unittest.main()
