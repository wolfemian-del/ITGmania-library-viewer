"""Tests for the course builder component (course_builder.py)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import course_builder
import library_data
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


if __name__ == "__main__":
    unittest.main()
