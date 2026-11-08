"""Tests for the course builder component (course_builder.py)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import course_builder
import library_data
import theme
from course_builder import CourseBuilder


def make_builder(entries=()):
    """A CourseBuilder with fake state and no real window (the object.__new__ idiom)."""
    builder = object.__new__(CourseBuilder)
    builder.window = Mock()
    builder.entries = list(entries)
    builder.title_var = None
    builder._status = Mock()
    return builder


class CourseBuilderValidationTests(unittest.TestCase):
    def test_validate_course_entries_delegates_and_rejects_unsafe_comments(self):
        builder = make_builder([{"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}])

        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            valid = builder.validate("Bad // Title")
            self.assertFalse(valid)
            mock_mb.showerror.assert_called_once()
            self.assertIn("//", mock_mb.showerror.call_args[0][1])

    def test_validate_course_entries_accepts_clean_entries(self):
        builder = make_builder([{"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}])

        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            valid = builder.validate("Clean Title")
            self.assertTrue(valid)
            mock_mb.showerror.assert_not_called()

    def _validate(self, entries, *title_argument):
        """Run validate with a fake message box; return (result, mock message box)."""
        builder = make_builder(entries)
        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            return builder.validate(*title_argument), mock_mb

    def test_append_flow_validates_without_a_title(self):
        # Appending to an existing course calls validate() with no title, so a missing title
        # must not be reported as an error.
        entry = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        valid, mock_mb = self._validate([entry])
        self.assertTrue(valid)
        mock_mb.showerror.assert_not_called()

        valid, mock_mb = self._validate([])
        self.assertFalse(valid)
        self.assertEqual(mock_mb.showerror.call_args[0][1], "Add at least one chart to the course.")

        valid, mock_mb = self._validate([{**entry, "Course path": "Pack//Song"}])
        self.assertFalse(valid)
        self.assertIn("//", mock_mb.showerror.call_args[0][1])

    def test_every_validation_error_uses_the_same_dialog_title(self):
        entry = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        cases = (
            ([entry], "Bad // Title"),
            ([entry], "Bad: Title"),
            ([], "Title"),
            ([{**entry, "Difficulty": ""}], "Title"),
            ([{**entry, "Course path": "Pack;Song"}], "Title"),
        )
        titles = set()
        for entries, title in cases:
            with self.subTest(title=title, entries=entries):
                valid, mock_mb = self._validate(entries, title)
                self.assertFalse(valid)
                mock_mb.showerror.assert_called_once()
                titles.add(mock_mb.showerror.call_args[0][0])
        self.assertEqual(len(titles), 1)

    def test_export_course_writes_formatted_new_course(self):
        with tempfile.TemporaryDirectory() as directory:
            out_file = Path(directory) / "test_course.crs"
            builder = make_builder([
                {"Course path": "Pack/SongA", "Difficulty": "Hard", "Type": "dance-single"},
                {"Course path": "Pack/SongB", "Difficulty": "Challenge", "Type": "dance-single"},
            ])
            builder.title_var = Mock(get=Mock(return_value="My Epic Course"))

            mock_fd = Mock(asksaveasfilename=Mock(return_value=str(out_file)))
            mock_mb = Mock()

            with patch.object(course_builder, "filedialog", mock_fd), patch.object(course_builder, "messagebox", mock_mb):
                builder.save_new()

            mock_mb.showerror.assert_not_called()
            mock_mb.showinfo.assert_called_once()
            self.assertTrue(out_file.is_file())
            written_content = out_file.read_text(encoding="utf-8")
            expected_body = library_data.format_new_course(
                "My Epic Course",
                library_data.course_song_lines(builder.entries)
            )
            self.assertEqual(written_content, expected_body)
            self.assertIn("Saved course with 2 charts", builder._status.set.call_args[0][0])

    def test_export_course_blank_title_shows_validation_error(self):
        builder = make_builder([{"Course path": "Pack/SongA", "Difficulty": "Hard", "Type": "dance-single"}])
        builder.title_var = Mock(get=Mock(return_value="   "))

        mock_fd = Mock()
        mock_mb = Mock()

        with patch.object(course_builder, "filedialog", mock_fd), patch.object(course_builder, "messagebox", mock_mb):
            builder.save_new()

        mock_mb.showerror.assert_called_once_with(
            "Course problem", "Enter a title for this course.", parent=builder.window
        )
        mock_fd.asksaveasfilename.assert_not_called()

    def test_append_course_appends_course_song_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            crs_file = Path(directory) / "existing.crs"
            crs_file.write_text("#COURSE:Existing;\n#SONG:Pack/SongA:Hard:;\n", encoding="utf-8")

            builder = make_builder([
                {"Course path": "Pack/SongB", "Difficulty": "Challenge", "Type": "dance-single"},
            ])

            mock_fd = Mock(askopenfilename=Mock(return_value=str(crs_file)))
            mock_mb = Mock()

            with patch.object(course_builder, "filedialog", mock_fd), patch.object(course_builder, "messagebox", mock_mb):
                builder.append_to_existing()

            mock_mb.showerror.assert_not_called()
            mock_mb.showinfo.assert_called_once()
            content = crs_file.read_text(encoding="utf-8")
            self.assertEqual(
                content,
                "#COURSE:Existing;\n#SONG:Pack/SongA:Hard:;\n#SONG:Pack/SongB:Challenge:;\n"
            )
            self.assertIn("Appended 1 charts", builder._status.set.call_args[0][0])


class CourseBuilderDialogTests(unittest.TestCase):
    def test_open_dialog_binds_escape(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
        )

        mock_window = Mock()
        bindings = {}
        def mock_bind(seq, func):
            bindings[seq] = func
        mock_window.bind.side_effect = mock_bind
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        mock_ttk = Mock()

        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", mock_ttk):
            builder.open_dialog()

        self.assertIn("<Escape>", bindings)
        # The window takes keyboard focus itself, so Escape reaches it without a click first.
        mock_window.focus_force.assert_called_once()
        mock_messagebox = Mock()
        with patch.object(course_builder, "messagebox", mock_messagebox):
            # Empty queue: closes at once, no question.
            res_esc = bindings["<Escape>"]()
            self.assertEqual(res_esc, "break")
            mock_window.destroy.assert_called_once()
            mock_messagebox.askyesno.assert_not_called()

            # Queued charts, user answers No: the window stays open.
            mock_window.destroy.reset_mock()
            builder.entries = [{"Title": "A"}, {"Title": "B"}]
            mock_messagebox.askyesno.return_value = False
            self.assertEqual(bindings["<Escape>"](), "break")
            mock_messagebox.askyesno.assert_called_once()
            mock_window.destroy.assert_not_called()

            # Queued charts, user answers Yes: the window closes.
            mock_messagebox.askyesno.return_value = True
            self.assertEqual(bindings["<Escape>"](), "break")
            mock_window.destroy.assert_called_once()

    def test_open_dialog_prepopulates_the_queue_from_selected_rows(self):
        rows = [
            {"Pack": "PackA", "Title": "Song A", "Type": "dance-single", "Difficulty": "Hard",
             "Meter": "10", "Time": 120, "Course path": "PackA/Song A"},
            {"Pack": "PackA", "Title": "Song B", "Type": "dance-single", "Difficulty": "Expert",
             "Meter": "12", "Time": 150, "Course path": "PackA/Song B"},
        ]
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: rows,
        )
        mock_window = Mock()
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        mock_ttk = Mock()
        # refresh_queue unpacks the tree's children with *, so a bare Mock is not enough.
        mock_ttk.Treeview.return_value.get_children.return_value = ()

        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", mock_ttk):
            builder.open_dialog()

        self.assertEqual(builder.entries, rows)
        self.assertEqual(builder.tree.insert.call_count, 2)

    def test_open_dialog_configures_tints_and_delete_keys(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
        )
        mock_window = Mock()
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        mock_ttk = Mock()
        mock_tree = mock_ttk.Treeview.return_value
        mock_tree.get_children.return_value = ()

        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", mock_ttk):
            builder.open_dialog()

        configured = {call.args[0]: call.kwargs.get("foreground")
                      for call in mock_tree.tag_configure.call_args_list}
        for name, color in theme.DIFFICULTY_COLORS.items():
            self.assertEqual(configured.get(f"diff_{name}"), color)
        self.assertEqual(configured.get("diff_unknown"), theme.DIFFICULTY_COLOR_UNKNOWN)

        bindings = {call.args[0]: call.args[1] for call in mock_tree.bind.call_args_list}
        self.assertIn("<Delete>", bindings)
        self.assertIn("<BackSpace>", bindings)

        # The Delete handler removes the selected entry and keeps a selection (issue #39).
        builder.entries = [queue_row("A"), queue_row("B")]
        mock_tree.selection.return_value = ("0",)
        self.assertEqual(bindings["<Delete>"](), "break")
        self.assertEqual([row["Title"] for row in builder.entries], ["B"])
        mock_tree.selection_set.assert_called_once_with("0")

    def test_opening_the_course_builder_when_already_open_raises_it_and_gives_it_focus(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
        )
        existing = Mock()
        existing.winfo_exists.return_value = True
        builder.window = existing
        mock_tk = Mock()
        with patch.object(course_builder, "tk", mock_tk):
            builder.open_dialog()
        existing.lift.assert_called_once()
        existing.focus_force.assert_called_once()
        mock_tk.Toplevel.assert_not_called()  # no second window


def queue_row(title, difficulty="Hard"):
    return {"Pack": "PackA", "Title": title, "Type": "dance-single", "Difficulty": difficulty,
            "Meter": "10", "Time": 60, "Course path": f"PackA/{title}"}


def make_queue_builder(titles):
    """A builder holding one entry per title, with a fake queue tree (refresh unpacks
    the tree's children with *, so get_children returns a real empty tuple)."""
    builder = make_builder([queue_row(title) for title in titles])
    builder.tree = Mock()
    builder.tree.get_children.return_value = ()
    builder.count_var = Mock()
    return builder


class CourseQueueTests(unittest.TestCase):
    def test_remove_entries_keeps_selection_at_the_removed_position(self):
        builder = make_queue_builder(["A", "B", "C", "D", "E"])
        builder.tree.selection.return_value = ("1",)

        builder.remove_entries()

        self.assertEqual([row["Title"] for row in builder.entries], ["A", "C", "D", "E"])
        builder.tree.selection_set.assert_called_once_with("1")  # C slid into B's slot

    def test_remove_entries_selects_the_new_last_entry_when_the_tail_is_removed(self):
        builder = make_queue_builder(["A", "B", "C", "D", "E"])
        builder.tree.selection.return_value = ("4",)

        builder.remove_entries()

        self.assertEqual([row["Title"] for row in builder.entries], ["A", "B", "C", "D"])
        builder.tree.selection_set.assert_called_once_with("3")

    def test_remove_entries_with_several_selected_keeps_the_first_gap_selected(self):
        builder = make_queue_builder(["A", "B", "C", "D", "E"])
        builder.tree.selection.return_value = ("1", "2")

        builder.remove_entries()

        self.assertEqual([row["Title"] for row in builder.entries], ["A", "D", "E"])
        builder.tree.selection_set.assert_called_once_with("1")

    def test_remove_entries_emptying_the_queue_selects_nothing(self):
        builder = make_queue_builder(["A", "B"])
        builder.tree.selection.return_value = ("0", "1")

        builder.remove_entries()

        self.assertEqual(builder.entries, [])
        builder.tree.selection_set.assert_not_called()

    def test_refresh_queue_tints_each_row_by_difficulty(self):
        builder = make_queue_builder([])
        builder.entries = [queue_row("A", "Hard"), queue_row("B", "Edit"), queue_row("C", "Unlisted")]

        builder.refresh_queue()

        tags = [call.kwargs["tags"] for call in builder.tree.insert.call_args_list]
        self.assertEqual(tags, [("diff_Hard",), ("diff_Edit",), ("diff_unknown",)])


if __name__ == "__main__":
    unittest.main()
