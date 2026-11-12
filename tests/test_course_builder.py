"""Tests for the course builder component (course_builder.py)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import course_builder
import library_data
import row_tints
import theme
from course_builder import CourseBuilder


def make_builder(entries=(), library_rows=()):
    """A CourseBuilder with fake state and no real window (the object.__new__ idiom)."""
    builder = object.__new__(CourseBuilder)
    builder.window = Mock()
    builder.entries = list(entries)
    builder._last_removal = None
    builder._saved_geometry = None
    builder._report_geometry = None
    builder.title_var = None
    builder._tint = row_tints.SelectedRowTint(None)  # as __init__ leaves it (issue #92)
    builder._status = Mock()
    builder._library_rows = lambda: list(library_rows)
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

    def _validate_with_library(self, entries, library_rows, answer=True):
        """Run validate against a library; return (result, mock message box)."""
        builder = make_builder(entries, library_rows)
        mock_mb = Mock()
        mock_mb.askyesno.return_value = answer
        with patch.object(course_builder, "messagebox", mock_mb):
            return builder.validate("Title"), mock_mb

    def test_validate_warns_about_an_entry_matched_by_another_chart_type(self):
        entry = {"Course path": "Pack/Song", "Title": "Song", "Difficulty": "Hard", "Type": "dance-single"}
        library = [entry, {"Course path": "Pack/Song", "Title": "Song",
                           "Difficulty": "Hard", "Type": "dance-double"}]

        valid, mock_mb = self._validate_with_library([entry], library, answer=False)
        self.assertFalse(valid)  # the user said no: nothing is saved
        mock_mb.askyesno.assert_called_once()
        title, description = mock_mb.askyesno.call_args[0][:2]
        self.assertEqual(title, "Ambiguous chart entries")
        self.assertIn("Song — Hard", description)

        valid, _ = self._validate_with_library([entry], library, answer=True)
        self.assertTrue(valid)

    def test_validate_warns_about_an_edit_matched_by_a_second_edit(self):
        entry = {"Course path": "Pack/Song", "Title": "Song", "Difficulty": "Edit", "Type": "dance-single"}
        library = [entry, {"Course path": "Pack/Song", "Title": "Song",
                           "Difficulty": "Edit", "Type": "dance-single"}]
        valid, mock_mb = self._validate_with_library([entry], library, answer=False)
        self.assertFalse(valid)
        self.assertEqual(mock_mb.askyesno.call_args[0][0], "Ambiguous chart entries")
        self.assertIn("Song — Edit", mock_mb.askyesno.call_args[0][1])

    def test_validate_offers_no_ambiguity_notice_for_unique_charts(self):
        entry = {"Course path": "Pack/Song", "Title": "Song", "Difficulty": "Hard", "Type": "dance-single"}
        library = [entry, {"Course path": "Pack/Song", "Title": "Song",
                           "Difficulty": "Challenge", "Type": "dance-single"}]
        valid, mock_mb = self._validate_with_library([entry], library)
        self.assertTrue(valid)
        mock_mb.askyesno.assert_not_called()

    def test_validate_mixed_type_confirmation_still_fires_without_ambiguity(self):
        entries = [
            {"Course path": "Pack/One", "Title": "One", "Difficulty": "Hard", "Type": "dance-single"},
            {"Course path": "Pack/Two", "Title": "Two", "Difficulty": "Hard", "Type": "dance-double"},
        ]
        valid, mock_mb = self._validate_with_library(entries, entries, answer=False)
        self.assertFalse(valid)
        mock_mb.askyesno.assert_called_once()
        self.assertEqual(mock_mb.askyesno.call_args[0][0], "Mixed chart types")

    def test_save_new_stops_before_the_file_dialog_when_the_warning_is_declined(self):
        entry = {"Course path": "Pack/Song", "Title": "Song", "Difficulty": "Hard", "Type": "dance-single"}
        library = [entry, {"Course path": "Pack/Song", "Title": "Song",
                           "Difficulty": "Hard", "Type": "dance-double"}]
        builder = make_builder([entry], library)
        builder.title_var = Mock(get=Mock(return_value="My Course"))
        mock_fd = Mock()
        mock_mb = Mock()
        mock_mb.askyesno.return_value = False
        with patch.object(course_builder, "filedialog", mock_fd), patch.object(course_builder, "messagebox", mock_mb):
            builder.save_new()
        mock_fd.asksaveasfilename.assert_not_called()

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
            library_rows=lambda: [],
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
            library_rows=lambda: [],
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
            library_rows=lambda: [],
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
        self.assertEqual(configured.get("selected_row"), theme.TEXT_ON_ACCENT)

        bindings = {call.args[0]: call.args[1] for call in mock_tree.bind.call_args_list}
        self.assertIn("<Delete>", bindings)
        self.assertIn("<BackSpace>", bindings)
        self.assertIn("<<TreeviewSelect>>", bindings)

        # The Delete handler removes the selected entry and keeps a selection (issue #39).
        builder.entries = [queue_row("A"), queue_row("B")]
        mock_tree.selection.return_value = ("0",)
        self.assertEqual(bindings["<Delete>"](), "break")
        self.assertEqual([row["Title"] for row in builder.entries], ["B"])
        mock_tree.selection_set.assert_called_once_with("0")

    def test_open_dialog_wires_the_x_button_to_the_same_close_prompt(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
            library_rows=lambda: [],
        )
        mock_window = Mock()
        bindings = {}
        mock_window.bind.side_effect = lambda seq, func: bindings.__setitem__(seq, func)
        protocols = {}
        mock_window.protocol.side_effect = lambda name, func: protocols.__setitem__(name, func)
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        mock_ttk = Mock()
        mock_ttk.Treeview.return_value.get_children.return_value = ()

        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", mock_ttk):
            builder.open_dialog()

        self.assertIn("WM_DELETE_WINDOW", protocols)
        self.assertIs(protocols["WM_DELETE_WINDOW"], bindings["<Escape>"])
        mock_messagebox = Mock()
        with patch.object(course_builder, "messagebox", mock_messagebox):
            # Empty queue: the X closes at once, no question, exactly like Escape.
            self.assertEqual(protocols["WM_DELETE_WINDOW"](), "break")
            mock_window.destroy.assert_called_once()
            mock_messagebox.askyesno.assert_not_called()

            # Queued charts, user answers No: the window stays open.
            mock_window.destroy.reset_mock()
            builder.entries = [{"Title": "A"}]
            mock_messagebox.askyesno.return_value = False
            protocols["WM_DELETE_WINDOW"]()
            mock_messagebox.askyesno.assert_called_once()
            mock_window.destroy.assert_not_called()

    def test_opening_the_course_builder_when_already_open_raises_it_and_gives_it_focus(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
            library_rows=lambda: [],
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

    def test_a_new_builder_has_working_tint_state_before_any_dialog_opens(self):
        builder = make_builder()
        builder._tint.reset(["0", "2"])
        builder._tint.note_selected("3")
        builder._tint.on_select()  # no tree yet: nothing to read, and it must not raise
        self.assertEqual(builder._tint.items, {"0", "2", "3"})

    def test_reopening_the_dialog_forgets_which_rows_were_selected_last_time(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
            library_rows=lambda: [],
        )
        builder._tint.items = {"1", "3"}  # left over from a dialog that was closed with rows selected
        mock_tk = Mock()
        mock_ttk = Mock()
        mock_ttk.Treeview.return_value.get_children.return_value = ()

        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", mock_ttk):
            builder.open_dialog()

        self.assertEqual(builder._tint.items, set())


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

    def test_refresh_queue_borns_a_kept_selection_with_the_white_tag(self):
        builder = make_queue_builder(["A", "B", "C"])

        builder.refresh_queue([1])

        tags = [call.kwargs["tags"] for call in builder.tree.insert.call_args_list]
        self.assertEqual(tags, [("diff_Hard",), ("diff_Hard", "selected_row"), ("diff_Hard",)])
        self.assertEqual(builder._tint.items, {"1"})



class CourseReloadTests(unittest.TestCase):
    def _builder(self, titles, window_exists=True):
        builder = make_queue_builder(titles)
        builder.window = Mock()
        builder.window.winfo_exists.return_value = window_exists
        return builder

    def test_reload_without_an_open_dialog_does_nothing(self):
        builder = self._builder(["A"])
        builder.window = None
        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            builder.on_library_reloaded()
        mock_mb.askyesno.assert_not_called()
        self.assertEqual(len(builder.entries), 1)

    def test_reload_with_a_closed_window_or_empty_queue_does_nothing(self):
        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            closed = self._builder(["A"], window_exists=False)
            closed.on_library_reloaded()
            empty = self._builder([])
            empty.on_library_reloaded()
        mock_mb.askyesno.assert_not_called()

    def test_reload_keeps_the_queue_when_the_user_says_no(self):
        builder = self._builder(["A", "B"])
        mock_mb = Mock()
        mock_mb.askyesno.return_value = False
        with patch.object(course_builder, "messagebox", mock_mb):
            builder.on_library_reloaded()
        mock_mb.askyesno.assert_called_once()
        self.assertEqual([row["Title"] for row in builder.entries], ["A", "B"])

    def test_reload_clears_the_queue_when_the_user_says_yes(self):
        builder = self._builder(["A", "B"])
        mock_mb = Mock()
        mock_mb.askyesno.return_value = True
        with patch.object(course_builder, "messagebox", mock_mb):
            builder.on_library_reloaded()
        self.assertEqual(builder.entries, [])
        builder.count_var.set.assert_called_once_with("0 charts · 0:00 total")


class CourseAppExitTests(unittest.TestCase):
    def _builder(self, titles, window_exists=True):
        builder = make_queue_builder(titles)
        builder.window = Mock()
        builder.window.winfo_exists.return_value = window_exists
        return builder

    def test_exit_without_an_open_dialog_needs_no_prompt(self):
        builder = self._builder(["A"])
        builder.window = None
        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            self.assertTrue(builder.confirm_discard_for_app_exit())
        mock_mb.askyesno.assert_not_called()
        self.assertEqual(len(builder.entries), 1)

    def test_exit_with_a_closed_window_or_empty_queue_needs_no_prompt(self):
        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            closed = self._builder(["A"], window_exists=False)
            self.assertTrue(closed.confirm_discard_for_app_exit())
            empty = self._builder([])
            self.assertTrue(empty.confirm_discard_for_app_exit())
        mock_mb.askyesno.assert_not_called()

    def test_exit_is_cancelled_when_the_user_says_no(self):
        builder = self._builder(["A", "B"])
        mock_mb = Mock()
        mock_mb.askyesno.return_value = False
        with patch.object(course_builder, "messagebox", mock_mb):
            self.assertFalse(builder.confirm_discard_for_app_exit())
        mock_mb.askyesno.assert_called_once()
        title, description = mock_mb.askyesno.call_args[0][:2]
        self.assertEqual(title, "Discard course queue?")
        self.assertIn("2 queued chart(s)", description)
        self.assertIs(mock_mb.askyesno.call_args.kwargs["parent"], builder.window)
        self.assertEqual([row["Title"] for row in builder.entries], ["A", "B"])

    def test_exit_proceeds_when_the_user_says_yes(self):
        builder = self._builder(["A"])
        mock_mb = Mock()
        mock_mb.askyesno.return_value = True
        with patch.object(course_builder, "messagebox", mock_mb):
            self.assertTrue(builder.confirm_discard_for_app_exit())
        mock_mb.askyesno.assert_called_once()


class CourseUndoRemoveTests(unittest.TestCase):
    """Issue #85, option A: single-step undo for queue removals."""

    def _builder(self, titles):
        builder = make_queue_builder(titles)
        builder.window = Mock()
        builder.window.winfo_exists.return_value = True
        return builder

    @staticmethod
    def _titles(builder):
        return [row["Title"] for row in builder.entries]

    def test_undo_restores_a_single_removal_at_its_position(self):
        builder = self._builder(["A", "B", "C"])
        builder.tree.selection.return_value = ("1",)
        builder.remove_entries()
        self.assertEqual(self._titles(builder), ["A", "C"])
        builder.tree.selection_set.reset_mock()

        builder.undo_remove()

        self.assertEqual(self._titles(builder), ["A", "B", "C"])
        builder.tree.selection_set.assert_called_once_with("1")

    def test_undo_restores_a_nonadjacent_multiselection(self):
        builder = self._builder(["A", "B", "C", "D"])
        builder.tree.selection.return_value = ("0", "2")
        builder.remove_entries()
        self.assertEqual(self._titles(builder), ["B", "D"])
        builder.tree.selection_set.reset_mock()

        builder.undo_remove()

        self.assertEqual(self._titles(builder), ["A", "B", "C", "D"])
        builder.tree.selection_set.assert_called_once_with("0", "2")

    def test_a_second_removal_replaces_the_remembered_one(self):
        builder = self._builder(["A", "B", "C"])
        builder.tree.selection.return_value = ("1",)
        builder.remove_entries()
        builder.tree.selection.return_value = ("1",)
        builder.remove_entries()
        self.assertEqual(self._titles(builder), ["A"])

        builder.undo_remove()
        self.assertEqual(self._titles(builder), ["A", "C"])
        builder.undo_remove()
        self.assertEqual(self._titles(builder), ["A", "C"])

    def test_undo_with_nothing_remembered_is_a_noop(self):
        builder = self._builder(["A", "B"])
        builder.undo_remove()
        self.assertEqual(self._titles(builder), ["A", "B"])

    def test_adding_entries_forgets_the_removal(self):
        builder = self._builder(["A", "B"])
        builder._selected_rows = lambda: [queue_row("D")]
        builder.tree.selection.return_value = ("0",)
        builder.remove_entries()
        builder.add_selected()
        self.assertEqual(self._titles(builder), ["B", "D"])

        builder.undo_remove()
        self.assertEqual(self._titles(builder), ["B", "D"])

    def test_moving_an_entry_forgets_the_removal(self):
        builder = self._builder(["A", "B", "C"])
        builder.tree.selection.return_value = ("0",)
        builder.remove_entries()
        builder.tree.selection.return_value = ("0",)
        builder.move_entry(1)
        self.assertEqual(self._titles(builder), ["C", "B"])

        builder.undo_remove()
        self.assertEqual(self._titles(builder), ["C", "B"])

    def test_a_reload_clear_forgets_the_removal(self):
        builder = self._builder(["A", "B"])
        builder.tree.selection.return_value = ("0",)
        builder.remove_entries()
        mock_mb = Mock()
        mock_mb.askyesno.return_value = True
        with patch.object(course_builder, "messagebox", mock_mb):
            builder.on_library_reloaded()
        self.assertEqual(builder.entries, [])

        builder.undo_remove()
        self.assertEqual(builder.entries, [])

    def test_a_reload_with_an_emptied_queue_forgets_the_removal(self):
        builder = self._builder(["A", "B"])
        builder.tree.selection.return_value = ("0", "1")
        builder.remove_entries()
        self.assertEqual(builder.entries, [])
        mock_mb = Mock()
        with patch.object(course_builder, "messagebox", mock_mb):
            builder.on_library_reloaded()
        mock_mb.askyesno.assert_not_called()  # nothing queued, so nothing to ask

        builder.undo_remove()
        self.assertEqual(builder.entries, [])

    def test_keeping_the_queue_at_reload_keeps_the_removal_undoable(self):
        builder = self._builder(["A", "B"])
        builder.tree.selection.return_value = ("0",)
        builder.remove_entries()
        mock_mb = Mock()
        mock_mb.askyesno.return_value = False
        with patch.object(course_builder, "messagebox", mock_mb):
            builder.on_library_reloaded()
        self.assertEqual(self._titles(builder), ["B"])

        builder.undo_remove()
        self.assertEqual(self._titles(builder), ["A", "B"])

    def test_open_dialog_binds_ctrl_z_and_offers_an_undo_button(self):
        button_factory = Mock(return_value=Mock())
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=button_factory,
            selected_rows=lambda: [],
            library_rows=lambda: [],
        )
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = Mock()
        mock_ttk = Mock()
        mock_tree = mock_ttk.Treeview.return_value
        mock_tree.get_children.return_value = ()

        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", mock_ttk):
            builder.open_dialog()

        self.assertIn("Undo remove", [call.args[1] for call in button_factory.call_args_list])
        bindings = {call.args[0]: call.args[1] for call in mock_tree.bind.call_args_list}
        self.assertIn("<Control-z>", bindings)
        # Caps Lock makes Tk report the key as "Z", so the capital must be bound too.
        self.assertIn("<Control-Z>", bindings)

        for undo_binding in ("<Control-z>", "<Control-Z>"):
            builder.entries = [queue_row("A"), queue_row("B")]
            mock_tree.selection.return_value = ("0",)
            bindings["<Delete>"]()
            self.assertEqual(self._titles(builder), ["B"])
            self.assertEqual(bindings[undo_binding](), "break")
            self.assertEqual(self._titles(builder), ["A", "B"])


class CourseGeometryTests(unittest.TestCase):
    """Window geometry memory (issue #25, proposal 0003): restore on open, report on close."""

    def open_builder(self, saved_geometry=None, report_geometry=None, vroot=(0, 0, 1920, 1080), dpi_scale=1.0):
        parent = Mock()
        parent.winfo_vrootx.return_value = vroot[0]
        parent.winfo_vrooty.return_value = vroot[1]
        parent.winfo_vrootwidth.return_value = vroot[2]
        parent.winfo_vrootheight.return_value = vroot[3]
        builder = CourseBuilder(
            parent=parent,
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
            library_rows=lambda: [],
            saved_geometry=saved_geometry,
            report_geometry=report_geometry,
            dpi_scale=dpi_scale,
        )
        mock_window = Mock()
        bindings = {}
        mock_window.bind.side_effect = lambda seq, func: bindings.__setitem__(seq, func)
        mock_tk = Mock()
        mock_tk.Toplevel.return_value = mock_window
        with patch.object(course_builder, "tk", mock_tk), patch.object(course_builder, "ttk", Mock()):
            builder.open_dialog()
        return builder, mock_window, bindings

    def test_open_restores_the_saved_geometry_when_its_position_is_visible(self):
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+30+40")
        mock_window.geometry.assert_called_once_with("900x620+30+40")

    def test_open_scales_the_saved_geometry_at_150_percent(self):
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+30+40", dpi_scale=1.5)
        mock_window.geometry.assert_called_once_with("1350x930+45+60")

    def test_open_scales_the_theme_default_without_a_saved_geometry(self):
        _builder, mock_window, _bindings = self.open_builder(dpi_scale=1.5)
        mock_window.geometry.assert_called_once_with("1500x930")

    def test_open_scales_the_minimum_size(self):
        _builder, mock_window, _bindings = self.open_builder(dpi_scale=1.5)
        mock_window.minsize.assert_called_once_with(1050, 660)

    def test_open_uses_the_scaled_threshold_for_a_narrow_sliver(self):
        # 120 physical pixels would show at the unscaled 100 px threshold
        # but not at the scaled 150 px one, so the position is dropped.
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+-820+40", dpi_scale=1.5)
        mock_window.geometry.assert_called_once_with("1350x930")

    def test_save_window_geometry_reports_canonical_units(self):
        builder = make_builder()
        builder._dpi_scale = 1.5
        builder.window.state.return_value = "normal"
        builder.window.geometry.return_value = "1350x930+45+60"
        builder._report_geometry = Mock()
        builder.save_window_geometry()
        builder._report_geometry.assert_called_once_with("900x620+30+40")
        self.assertEqual(builder._saved_geometry, "900x620+30+40")

    def test_open_uses_the_theme_default_without_a_saved_geometry(self):
        _builder, mock_window, _bindings = self.open_builder()
        mock_window.geometry.assert_called_once_with(theme.COURSE_BUILDER_GEOMETRY)

    def test_open_falls_back_to_size_only_when_the_saved_position_is_off_screen(self):
        # The remembered monitor is gone: the position falls outside the virtual desktop.
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+5000+40")
        mock_window.geometry.assert_called_once_with("900x620")

    def test_open_falls_back_to_size_only_when_only_a_sliver_would_show(self):
        # Top-left technically on the desktop, but almost the whole window beyond the edge.
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+1919+40")
        mock_window.geometry.assert_called_once_with("900x620")
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+40+1070")
        mock_window.geometry.assert_called_once_with("900x620")

    def test_open_restores_a_window_hanging_slightly_off_an_edge(self):
        # Mostly visible, just overhanging: it comes back exactly as it was left.
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+-30+40")
        mock_window.geometry.assert_called_once_with("900x620+-30+40")

    def test_open_falls_back_when_the_title_bar_would_be_above_the_screen(self):
        # Plenty of the body would show, but with the title bar above every
        # monitor there is nothing to grab, so the position is not restored.
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+100+-500")
        mock_window.geometry.assert_called_once_with("900x620")
        # A top edge within a few pixels of the desktop's top still counts as grabbable.
        _builder, mock_window, _bindings = self.open_builder(saved_geometry="900x620+100+-16")
        mock_window.geometry.assert_called_once_with("900x620+100+-16")

    def test_open_restores_a_negative_position_on_a_monitor_left_of_the_primary(self):
        # Virtual desktop starts at x=-1920; Tk's "+-" spelling must survive the round trip.
        _builder, mock_window, _bindings = self.open_builder(
            saved_geometry="900x620+-1500+40", vroot=(-1920, 0, 3840, 1080))
        mock_window.geometry.assert_called_once_with("900x620+-1500+40")

    def test_close_reports_the_geometry_before_destroying_the_window(self):
        report = Mock()
        builder, mock_window, bindings = self.open_builder(report_geometry=report)
        mock_window.state.return_value = "normal"
        mock_window.geometry.return_value = "1000x620+10+10"
        manager = Mock()
        manager.attach_mock(report, "report")
        manager.attach_mock(mock_window, "window")
        with patch.object(course_builder, "messagebox", Mock()):
            self.assertEqual(bindings["<Escape>"](), "break")
        names = [call[0] for call in manager.mock_calls]
        self.assertIn("report", names)
        self.assertLess(names.index("report"), names.index("window.destroy"))
        report.assert_called_once_with("1000x620+10+10")
        self.assertEqual(builder._saved_geometry, "1000x620+10+10")

    def test_cancelled_discard_saves_no_geometry(self):
        report = Mock()
        builder, mock_window, bindings = self.open_builder(report_geometry=report)
        builder.entries = [{"Title": "A"}]
        mock_messagebox = Mock()
        mock_messagebox.askyesno.return_value = False
        with patch.object(course_builder, "messagebox", mock_messagebox):
            self.assertEqual(bindings["<Escape>"](), "break")
        report.assert_not_called()
        mock_window.destroy.assert_not_called()

    def test_save_window_geometry_reports_and_updates_the_saved_value(self):
        builder = make_builder()
        builder.window.state.return_value = "normal"
        builder.window.geometry.return_value = "900x620+5+5"
        builder._report_geometry = Mock()
        builder.save_window_geometry()
        builder._report_geometry.assert_called_once_with("900x620+5+5")
        self.assertEqual(builder._saved_geometry, "900x620+5+5")

    def test_save_window_geometry_noops_without_a_normal_open_window(self):
        report = Mock()
        builder = make_builder()
        builder._report_geometry = report
        # Minimized: the reported geometry would be the parked position, not the user's place.
        builder.window.state.return_value = "iconic"
        builder.save_window_geometry()
        report.assert_not_called()
        self.assertIsNone(builder._saved_geometry)
        # No dialog at all.
        builder.window = None
        builder.save_window_geometry()
        report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
