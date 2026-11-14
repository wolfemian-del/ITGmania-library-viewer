"""Tests for the song table component (proposal 0009 Step 6).

Headless: the table is built on fake Tk objects (the Treeview and
scrollbars are Mocks, patched in), so these run without a display. The
live table tests (selection, drag, sort clicks) stay in
tests/test_library_visualizer.py — the windows-ui job runs exactly two
test files, and a new file would need a workflow edit only the owner can
make.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import library_data
import library_table as table_module
import row_tints
import library_visualizer as app
from library_filter import LibraryFilter
from library_table import LibraryTable


class _ValueVar:
    """A minimal value-carrying stand-in for a Tk variable: get/set over a
    stored string, so tests can preset a value and observe the result."""

    def __init__(self, value, on_set=None):
        self.value = value
        self.on_set = on_set
        self._traces = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        if self.on_set is not None:
            self.on_set()
        for callback in self._traces:
            callback()

    def trace_add(self, mode, callback):
        """Record a write-trace callback, like tk.Variable.trace_add; set() fires it."""
        self._traces.append(callback)
        return f"trace-{len(self._traces)}"


class FakeVariable:
    """A BooleanVar stand-in: get/set over a stored bool."""

    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def make_filter(rows=()):
    """A real LibraryFilter on _ValueVars, holding the given rows."""
    search_var = _ValueVar("")
    filt = LibraryFilter(
        search_var, _ValueVar("All packs"), _ValueVar("All types"),
        _ValueVar("All difficulties"), _ValueVar(False),
        Mock(), Mock(), Mock(), Mock(), Mock())
    filt.set_rows(list(rows))
    return filt


def make_table(column_order=None, column_widths=None, sort_keys=None,
               visible_columns=None, column_visibility=None,
               group_visibility=None, rows=(), show_rows=None,
               save_settings=None, count_label=None, dpi_scale=1.0):
    """A real LibraryTable on fake Tk objects, plus the Mock tree it built.

    The Treeview and scrollbars are patched to Mocks (the table creates
    them in __init__), so no display is needed; the filter is real, so
    refresh_table reads the rows it returns. The table's _rows is set
    directly (not via set_rows) so the setup itself does not refresh —
    tests that exercise set_rows call it explicitly. column_visibility
    and group_visibility default to fresh FakeVariable dicts, or pass
    the app's shared dicts (the save tests do, so _save_settings reads
    the same objects the table mutates).
    """
    parent = Mock()
    tree = Mock()
    tree.get_children.return_value = []
    tree.column.return_value = 100
    if column_visibility is None:
        column_visibility = {
            col: FakeVariable(True if visible_columns is None
                              else col in visible_columns)
            for col in app.HEADERS}
    if group_visibility is None:
        group_visibility = {group: FakeVariable()
                            for group in app.COLUMN_GROUPS}
    filt = make_filter(rows)
    seed = {
        "column_order": list(column_order) if column_order is not None else list(app.HEADERS),
        "column_widths": dict(column_widths) if column_widths is not None else {},
        "sort_keys": [list(item) for item in sort_keys] if sort_keys is not None else [],
    }
    with patch.object(table_module.ttk, "Treeview", return_value=tree), \
            patch.object(table_module.ttk, "Scrollbar", return_value=Mock()):
        table = LibraryTable(
            parent, filt, dpi_scale, column_visibility, group_visibility,
            seed, count_label if count_label is not None else Mock(),
            save_settings if save_settings is not None else Mock(),
            show_rows if show_rows is not None else Mock())
    # The app subscribes the table's refresh to the filter once the table
    # exists; the filter's rows were set before that, so the setup itself
    # does not refresh.
    filt.subscribe(table.refresh_table)
    table._rows = list(rows)
    return table, tree


def rows_for(*specs):
    """Chart rows from (Pack, Type, Difficulty) specs, for filter tests."""
    return [{"Pack": pack, "Type": type_, "Difficulty": difficulty,
             "Title": "Song", "Grade": ""}
            for pack, type_, difficulty in specs]


if __name__ == "__main__":
    unittest.main()
class ColumnGroupTests(unittest.TestCase):
    @staticmethod
    def make_table(visible_columns):
        table, tree = make_table(visible_columns=visible_columns)
        # The table's construction configures the tree (scrollbars, display
        # columns); these tests pin only the calls the gesture makes.
        tree.reset_mock()
        return table

    @staticmethod
    def shown(table):
        return {col for col, var in table.column_visibility.items() if var.get()}

    def test_every_column_is_in_exactly_one_group(self):
        grouped = [column for columns in app.COLUMN_GROUPS.values() for column in columns]
        self.assertEqual(sorted(grouped), sorted(app.HEADERS))

    def test_groups_are_listed_in_menu_order(self):
        self.assertEqual(list(app.COLUMN_GROUPS),
                         ["Song & chart", "Score", "Tap judgments", "Chart counts", "Tech counts"])

    def test_default_columns_are_song_and_chart_plus_score(self):
        # Issue #49: Subtitle is the one exception — in "Song & chart" but
        # hidden by default, while its group-mates default to shown.
        expected = {*app.COLUMN_GROUPS["Song & chart"], *app.COLUMN_GROUPS["Score"]} - {"Subtitle"}
        self.assertEqual(set(app.DEFAULT_VISIBLE_COLUMNS), expected)
        self.assertNotIn("Subtitle", app.DEFAULT_VISIBLE_COLUMNS)
        self.assertIn("Subtitle", app.COLUMN_GROUPS["Song & chart"])
        self.assertTrue({"Title", "Artist", "Pack"} <= set(app.DEFAULT_VISIBLE_COLUMNS))

    def test_group_check_is_on_only_when_the_whole_group_is_shown(self):
        table = self.make_table(app.DEFAULT_VISIBLE_COLUMNS)
        self.assertTrue(table.group_visibility["Score"].get())
        self.assertFalse(table.group_visibility["Tap judgments"].get())
        table.column_visibility["Grade"].set(False)
        table._column_visibility_changed("Grade")
        self.assertFalse(table.group_visibility["Score"].get())

    def test_group_switch_shows_then_hides_a_whole_group_with_one_save(self):
        table = self.make_table(app.DEFAULT_VISIBLE_COLUMNS)
        table.group_visibility["Tap judgments"].set(True)  # what Tk does before calling the command
        table._group_visibility_changed("Tap judgments")
        self.assertTrue(set(library_data.TAP_FIELDS) <= self.shown(table))
        table.tree.configure.assert_called_once()
        table._save_settings.assert_called_once()

        table.group_visibility["Tap judgments"].set(False)
        table._group_visibility_changed("Tap judgments")
        self.assertFalse(set(library_data.TAP_FIELDS) & self.shown(table))
        self.assertEqual(set(table.tree.configure.call_args.kwargs["displaycolumns"]),
                         set(app.DEFAULT_VISIBLE_COLUMNS))

    def test_group_switch_cannot_hide_the_last_visible_columns(self):
        table = self.make_table(app.COLUMN_GROUPS["Score"])
        table.group_visibility["Score"].set(False)
        table._group_visibility_changed("Score")
        self.assertEqual(self.shown(table), set(app.COLUMN_GROUPS["Score"]))
        self.assertTrue(table.group_visibility["Score"].get())
        table.tree.configure.assert_not_called()
        table._save_settings.assert_not_called()

    def test_reset_column_layout_restores_the_default_columns(self):
        table = self.make_table(app.HEADERS)
        table.column_order = list(reversed(app.HEADERS))
        table.reset_column_layout()
        self.assertEqual(self.shown(table), set(app.DEFAULT_VISIBLE_COLUMNS))
        self.assertEqual(table.column_order, list(app.HEADERS))
        self.assertEqual(table.tree.configure.call_args.kwargs["displaycolumns"],
                         [col for col in app.HEADERS if col in app.DEFAULT_VISIBLE_COLUMNS])
        self.assertFalse(table.group_visibility["Tech counts"].get())
        # "Song & chart" reads unchecked after a reset: Subtitle belongs to
        # the group but starts hidden (issue #49), so the group is never
        # fully shown by default.
        self.assertFalse(table.group_visibility["Song & chart"].get())


class ColumnDragTests(unittest.TestCase):
    """Column drag reorder and the displayed-column helpers: which column a
    heading position names, the screen span of a displayed column, and the
    drag that reorders the columns and saves."""

    COLUMNS = ["Title", "Artist", "Pack"]

    @staticmethod
    def make_table():
        table, tree = make_table(column_order=list(ColumnDragTests.COLUMNS))
        table.column_order = list(ColumnDragTests.COLUMNS)
        tree.identify_region.return_value = "heading"
        # Each displayed column owns a 100px span: #1 is 0-99, #2 is
        # 100-199, #3 is 200-299.
        tree.identify_column.side_effect = (
            lambda x: "#1" if x < 100 else ("#2" if x < 200 else "#3"))
        tree.winfo_width.return_value = 300
        # The table's construction configures the tree; these tests pin
        # only the calls the drag makes.
        tree.reset_mock()
        return table

    @staticmethod
    def event(x, y=10):
        event = Mock()
        event.x = x
        event.y = y
        return event

    def test_displayed_column_at_returns_the_visible_column(self):
        table = self.make_table()
        self.assertEqual(table._displayed_column_at(150, 10), "Artist")

    def test_displayed_column_at_returns_none_outside_the_heading(self):
        table = self.make_table()
        table.tree.identify_region.return_value = "cell"
        self.assertIsNone(table._displayed_column_at(150, 10))

    def test_displayed_column_at_returns_none_for_an_unknown_column_id(self):
        table = self.make_table()
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "abc"
        self.assertIsNone(table._displayed_column_at(150, 10))

    def test_displayed_column_at_returns_none_when_the_index_is_out_of_range(self):
        table = self.make_table()
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "#9"
        self.assertIsNone(table._displayed_column_at(150, 10))

    def test_displayed_column_bounds_span_the_columns_screen_range(self):
        table = self.make_table()
        self.assertEqual(table._displayed_column_bounds(0), (0, 100))
        self.assertEqual(table._displayed_column_bounds(1), (100, 200))
        self.assertEqual(table._displayed_column_bounds(2), (200, 300))

    def test_displayed_column_bounds_returns_none_with_no_match(self):
        table = self.make_table()
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "#9"
        self.assertIsNone(table._displayed_column_bounds(0))

    def test_drag_start_records_the_column_and_position(self):
        table = self.make_table()

        table._column_drag_start(self.event(50))

        self.assertEqual(table._dragged_column, "Title")
        self.assertEqual(table._drag_start_x, 50)

    def test_drag_start_outside_the_heading_clears_the_drag(self):
        table = self.make_table()
        table.tree.identify_region.return_value = "cell"

        table._column_drag_start(self.event(50))

        self.assertIsNone(table._dragged_column)
        self.assertIsNone(table._drag_start_x)

    def test_drag_end_without_a_drag_does_nothing(self):
        table = self.make_table()

        result = table._column_drag_end(self.event(250))

        self.assertIsNone(result)
        table.tree.configure.assert_not_called()
        table._save_settings.assert_not_called()

    def test_drag_end_below_the_movement_threshold_does_nothing(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(53))

        self.assertIsNone(result)
        self.assertEqual(table.column_order, self.COLUMNS)
        table._save_settings.assert_not_called()

    def test_drag_end_on_the_same_column_does_nothing(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(55))

        self.assertIsNone(result)
        self.assertEqual(table.column_order, self.COLUMNS)
        table._save_settings.assert_not_called()

    def test_drag_end_on_no_column_does_nothing(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "#9"

        result = table._column_drag_end(self.event(250))

        self.assertIsNone(result)
        self.assertEqual(table.column_order, self.COLUMNS)
        table._save_settings.assert_not_called()

    def test_drag_right_past_the_midpoint_moves_the_column_after_its_target(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(250))

        self.assertEqual(result, "break")
        self.assertEqual(table.column_order, ["Artist", "Pack", "Title"])
        table.tree.configure.assert_called_once_with(
            displaycolumns=["Artist", "Pack", "Title"])
        table._save_settings.assert_called_once()

    def test_drag_right_before_the_midpoint_moves_the_column_before_its_target(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(210))

        self.assertEqual(result, "break")
        self.assertEqual(table.column_order, ["Artist", "Title", "Pack"])
        table.tree.configure.assert_called_once_with(
            displaycolumns=["Artist", "Title", "Pack"])
        table._save_settings.assert_called_once()

    def test_drag_left_moves_the_column_before_its_target(self):
        table = self.make_table()
        table._dragged_column = "Pack"
        table._drag_start_x = 250

        result = table._column_drag_end(self.event(50))

        self.assertEqual(result, "break")
        self.assertEqual(table.column_order, ["Title", "Pack", "Artist"])
        table.tree.configure.assert_called_once_with(
            displaycolumns=["Title", "Pack", "Artist"])
        table._save_settings.assert_called_once()


class RowTintTests(unittest.TestCase):
    # The tag rule, the tag setup, and the selection bookkeeping themselves are
    # tested in test_row_tints.py; this class keeps the table-side wiring honest.
    def test_insert_batch_tags_rows_by_difficulty_and_selection(self):
        rows = [
            {"Title": "Song A", "Difficulty": "Challenge", "Time": 120},
            {"Title": "Song B", "Difficulty": "Hard", "Time": 90},
            {"Title": "Song C", "Difficulty": "CustomUnknown", "Time": 60},
        ]
        table, tree = make_table(rows=rows)
        tree.insert.side_effect = ["item0", "item1", "item2"]
        table._render_generation = 1
        # Song B is pre-selected
        table._insert_batch(rows, 0, 1, selected_rows={id(rows[1])})

        self.assertEqual(tree.insert.call_count, 3)
        # Song A: unselected Challenge
        args0, kwargs0 = tree.insert.call_args_list[0]
        self.assertEqual(kwargs0.get("tags"), ("diff_Challenge",))
        # Song B: selected Hard has selected_row tag
        args1, kwargs1 = tree.insert.call_args_list[1]
        self.assertEqual(kwargs1.get("tags"), ("diff_Hard", "selected_row"))
        # Song C: a difficulty name that is not in the theme gets the gray unknown tag
        args2, kwargs2 = tree.insert.call_args_list[2]
        self.assertEqual(kwargs2.get("tags"), (row_tints.UNKNOWN_DIFFICULTY_TAG,))
        # Only the pre-selected row is remembered as selected
        self.assertEqual(table._tree_tint.items, {"item1"})
        tree.selection_add.assert_called_once_with("item1")


class SelectedRowsForCourseTests(unittest.TestCase):
    def test_selected_rows_for_course_returns_rows_in_selection_order_and_skips_unknown_ids(self):
        # The one seam between the table and the course builder: the dialog's queue is
        # fed from here, so a break here would open the dialog empty.
        rows = {"item1": {"Title": "A"}, "item2": {"Title": "B"}}
        table, tree = make_table()
        tree.selection.return_value = ["item2", "gone", "item1"]
        table.tree_item_rows = rows

        self.assertEqual(table.selected_rows(), [rows["item2"], rows["item1"]])


class LibraryRowsForCourseTests(unittest.TestCase):
    def test_library_rows_for_course_returns_the_loaded_rows(self):
        # The course builder's save-time ambiguity check compares its queue against
        # this list, so it must be the app's current rows, not a snapshot copy.
        rows = [{"Title": "A"}, {"Title": "B"}]
        table, _tree = make_table()
        table.set_rows(rows)

        self.assertIs(table.library_rows(), rows)


class InsertBatchProgressTests(unittest.TestCase):
    """_insert_batch fills the table in time-boxed batches, and the count
    label tells the truth while it does (startup polish)."""

    @staticmethod
    def make_instance(row_count=3):
        rows = [{"Title": f"Song {i}", "Difficulty": "Hard", "Time": 60} for i in range(row_count)]
        table, tree = make_table(rows=rows)
        tree.insert.side_effect = [f"item{i}" for i in range(row_count)]
        table._render_generation = 1
        return table, rows

    def test_a_zero_budget_inserts_one_row_and_reports_progress(self):
        table, rows = self.make_instance()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._insert_batch(rows, 0, 1)
        self.assertEqual(table.tree.insert.call_count, 1)
        table.count_label.set.assert_called_once_with("Loading 1 of 3 charts…")
        table._parent.after.assert_called_once()
        # The scheduled continuation finishes the job and sets the final totals.
        continuation = table._parent.after.call_args.args[1]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()
        self.assertEqual(table.tree.insert.call_count, 3)
        table.count_label.set.assert_called_with("3 charts shown · 3 total")

    def test_a_generous_budget_inserts_everything_in_one_batch(self):
        table, rows = self.make_instance()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        self.assertEqual(table.tree.insert.call_count, 3)
        table.count_label.set.assert_called_once_with("3 charts shown · 3 total")
        table._parent.after.assert_not_called()

    def test_non_finite_time_values_insert_as_blank_instead_of_crashing(self):
        # Issue #123: a snapshot row whose Time is "nan" or "1e999" used to
        # raise inside _insert_batch; now the cell is blank and the batch lands.
        table, _rows = self.make_instance()
        table._rows = [
            {"Title": "Song A", "Difficulty": "Hard", "Time": "nan"},
            {"Title": "Song B", "Difficulty": "Hard", "Time": "1e999"},
            {"Title": "Song C", "Difficulty": "Hard", "Time": 120},
        ]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(table._rows, 0, 1)
        self.assertEqual(table.tree.insert.call_count, 3)
        time_index = list(app.HEADERS).index("Time")
        inserted = [kwargs["values"][time_index]
                    for _args, kwargs in table.tree.insert.call_args_list]
        self.assertEqual(inserted, ["", "", "2:00"])

    def test_count_line_names_an_unreadable_filter_value(self):
        table, rows = self.make_instance()
        table._filter.search_var.set("meter:abc")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        table.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in meter:abc")

    def test_count_line_names_an_unreadable_grade_value(self):
        table, rows = self.make_instance()
        table._filter.search_var.set("grade:banana")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        table.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in grade:banana")

    def test_count_line_stays_plain_for_a_readable_filter(self):
        table, rows = self.make_instance()
        table._filter.search_var.set("meter:11")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        table.count_label.set.assert_called_once_with("3 charts shown · 3 total")


class RefreshDeliversRowsTests(unittest.TestCase):
    """refresh_table delivers the filtered rows to the table and the panel:
    the wiring a load (and later set_rows) must preserve, so a forgotten
    refresh leaves the table visibly empty instead of silently stale."""

    @staticmethod
    def make_table():
        rows = [
            {"Title": "Song A", "Pack": "Pack1", "Type": "dance-single",
             "Difficulty": "Hard", "Grade": "AAA", "Meter": 10, "Time": 60},
            {"Title": "Song B", "Pack": "Pack2", "Type": "dance-double",
             "Difficulty": "Challenge", "Grade": "", "Meter": 12,
             "Time": 90},
        ]
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        tree.insert.side_effect = ["item0", "item1"]
        return table, tree, rows, show_rows

    def test_refresh_table_inserts_the_rows_and_pushes_them_to_the_panel(self):
        table, tree, rows, show_rows = self.make_table()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree.insert.call_count, 2)
        title_index = list(app.HEADERS).index("Title")
        inserted = [kwargs["values"][title_index]
                    for _args, kwargs in tree.insert.call_args_list]
        self.assertEqual(inserted, ["Song A", "Song B"])
        show_rows.assert_called_once_with(rows)
        table.count_label.set.assert_called_once_with(
            "2 charts shown · 2 total")


class RebindingHazardTests(unittest.TestCase):
    """The sort/column rebinding hazard (proposal 0009, Claude's review):
    sort_by rebinds self.sort_keys and reset_column_layout rebinds
    self.column_order, so the state _save_settings persists must be the
    table's own state after the gesture — a shared-input design would go
    stale here. These pins say what reaches disk."""

    @staticmethod
    def make_save_table(settings_path):
        """A bare app whose _save_settings reads a real table's layout_state."""
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = settings_path
        instance.cache_var = Mock(get=Mock(return_value="/cache"))
        instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
        instance.column_visibility = {
            col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
        instance.show_distribution_panel = Mock(
            get=Mock(return_value=False))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.pack_var = Mock(get=Mock(return_value="All packs"))
        instance.type_var = Mock(get=Mock(return_value="All types"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.course_geometry = None
        instance.advanced_search_geometry = None
        instance._settings_store = library_data.SettingsStore(settings_path)
        instance._settings_store.load()
        instance.status = Mock()
        group_visibility = {group: FakeVariable()
                            for group in app.COLUMN_GROUPS}
        table, _tree = make_table(
            column_visibility=instance.column_visibility,
            group_visibility=group_visibility,
            save_settings=instance._save_settings)
        instance._table = table
        return instance, table

    @staticmethod
    def saved(settings_path):
        return json.loads(settings_path.read_text(encoding="utf-8"))

    def test_sort_by_a_new_column_persists_the_new_sort(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance, table = self.make_save_table(settings_path)
            table.refresh_table = Mock()

            table.sort_by("Title")

            table.refresh_table.assert_called_once_with(
                preserve_selection=True)
            self.assertEqual(self.saved(settings_path)["sort_keys"],
                             [["Title", False]])

    def test_sort_by_the_current_first_column_toggles_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance, table = self.make_save_table(settings_path)
            table.sort_keys = [("Title", False)]
            table.refresh_table = Mock()

            table.sort_by("Title")

            self.assertEqual(self.saved(settings_path)["sort_keys"],
                             [["Title", True]])

    def test_reset_column_layout_persists_the_restored_order(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance, table = self.make_save_table(settings_path)
            table.column_order = list(reversed(app.HEADERS))

            table.reset_column_layout()

            self.assertEqual(self.saved(settings_path)["column_order"],
                             list(app.HEADERS))


class TableWiringGuardTests(unittest.TestCase):
    """The Step 6 wiring guard: set_rows refreshes (on its own, and once
    inside a batch); the sort clicks and the column drag land on the table;
    and refresh_table reaches the panel's show_rows with the filtered rows.
    The layout_state pin lives in RebindingHazardTests; the unfiltered
    show_rows pin lives in RefreshDeliversRowsTests."""

    def test_set_rows_on_its_own_refreshes_at_once(self):
        rows = rows_for(("Pack1", "dance-single", "Hard"),
                        ("Pack2", "dance-single", "Hard"))
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        tree.reset_mock()
        show_rows.reset_mock()
        table.count_label.set.reset_mock()

        table.set_rows(rows)

        # The table displays the rows it was given, once.
        self.assertEqual(tree.insert.call_count, 2)
        show_rows.assert_called_once_with(rows)
        table.count_label.set.assert_called_once_with(
            "2 charts shown · 2 total")

    def test_set_rows_inside_a_batch_refreshes_exactly_once_at_the_exit(self):
        rows = rows_for(("Pack1", "dance-single", "Hard"))
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        tree.reset_mock()
        show_rows.reset_mock()

        with table._filter.batch():
            table.set_rows(rows)
            # No refresh while the batch is open.
            show_rows.assert_not_called()

        # The batch exit refreshes once for the whole load.
        show_rows.assert_called_once_with(rows)
        self.assertEqual(tree.insert.call_count, 1)

    def test_heading_commands_sort_via_the_table(self):
        table, tree = make_table()
        # The Title heading was built with a command; the sort-heading
        # rewrite that follows has none, so take the one with a command.
        title_command = None
        for call in tree.heading.call_args_list:
            args, kwargs = call
            if args and args[0] == "Title" and kwargs.get("command") is not None:
                title_command = kwargs["command"]
        self.assertIsNotNone(title_command)
        table.refresh_table = Mock()

        title_command()

        self.assertEqual(table.sort_keys, [("Title", False)])
        table.refresh_table.assert_called_once_with(preserve_selection=True)

    def test_tree_bindings_land_on_the_table(self):
        table, tree = make_table()
        bound = {}
        for call in tree.bind.call_args_list:
            args, _kwargs = call
            bound.setdefault(args[0], []).append(args[1])
        # The drag, the shift-click sort, the save-on-release, and Ctrl+A
        # are the table's own methods (bound-method equality compares
        # __func__ and __self__, so this is an identity check).
        self.assertIn(table._column_drag_start, bound["<ButtonPress-1>"])
        self.assertIn(table._column_drag_end, bound["<ButtonRelease-1>"])
        self.assertIn(table._shift_sort_click, bound["<ButtonRelease-1>"])
        self.assertIn(table._save_settings, bound["<ButtonRelease-1>"])
        self.assertIn(table._select_all_rows, bound["<Control-a>"])
        self.assertIn(table._select_all_rows, bound["<Control-A>"])
        self.assertIn(table._tree_tint.on_select, bound["<<TreeviewSelect>>"])

    def test_refresh_table_pushes_the_filtered_rows_to_the_panel(self):
        rows = rows_for(("Pack1", "dance-single", "Hard"),
                        ("Pack2", "dance-single", "Hard"))
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        table._filter.pack_var.set("Pack2")
        # The pack pick refreshes through the subscription; reset the
        # count so the explicit refresh below is the one pinned.
        show_rows.reset_mock()
        tree.reset_mock()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        show_rows.assert_called_once_with([rows[1]])
        self.assertEqual(tree.insert.call_count, 1)


class LayoutStateTests(unittest.TestCase):
    """layout_state() reports the table's own sort/column state in
    canonical 100% units, which is what _save_settings persists."""

    def test_layout_state_reports_widths_in_canonical_units(self):
        # Issue #51: the table reads physical pixels back from the tree;
        # at 150% a 195 px column is stored as 130, so it comes back the
        # same at any scale.
        table, tree = make_table(dpi_scale=1.5)
        tree.column.return_value = 195
        state = table.layout_state()
        self.assertTrue(state["column_widths"])
        self.assertEqual(set(state["column_widths"].values()), {130})
        self.assertEqual(state["column_order"], list(app.HEADERS))
        self.assertEqual(state["sort_keys"], [["Pack", False]])

    def test_layout_state_reports_the_rebound_state_after_a_sort(self):
        # The rebinding hazard's other half: layout_state reads the
        # table's own sort_keys after sort_by rebinds them, not a copy
        # taken at construction.
        table, _tree = make_table()
        table.refresh_table = Mock()
        table.sort_by("Title")
        self.assertEqual(table.layout_state()["sort_keys"],
                         [["Title", False]])
