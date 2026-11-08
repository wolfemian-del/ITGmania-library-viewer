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
    builder.title_var = None
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

    def test_reopening_the_dialog_forgets_which_rows_were_selected_last_time(self):
        builder = CourseBuilder(
            parent=Mock(),
            status=Mock(),
            button_factory=Mock(return_value=Mock()),
            selected_rows=lambda: [],
            library_rows=lambda: [],
        )
        builder._tint = row_tints.SelectedRowTint(Mock())
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
    builder._tint = row_tints.SelectedRowTint(builder.tree)
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

        builder.entries = [queue_row("A"), queue_row("B")]
        mock_tree.selection.return_value = ("0",)
        bindings["<Delete>"]()
        self.assertEqual(self._titles(builder), ["B"])
        self.assertEqual(bindings["<Control-z>"](), "break")
        self.assertEqual(self._titles(builder), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
