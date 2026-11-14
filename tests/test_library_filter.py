import unittest
from unittest.mock import Mock

import distribution_panel as dp
import library_filter as filter_module
import library_visualizer as app
from library_filter import LibraryFilter


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


def make_filter(search="", pack="All packs", type_="All types",
                difficulty="All difficulties", scored=False, rows=()):
    """A LibraryFilter on _ValueVars, holding the given rows, with a Mock
    table refresh subscribed (so set_rows and var changes notify it)."""
    search_var = _ValueVar(search)
    pack_var = _ValueVar(pack)
    type_var = _ValueVar(type_)
    diff_var = _ValueVar(difficulty)
    scored_var = _ValueVar(scored)
    filt = LibraryFilter(search_var, pack_var, type_var, diff_var, scored_var,
                         Mock(), Mock(), Mock(), Mock(), Mock())
    filt.subscribe(Mock())
    filt.set_rows(list(rows))
    return filt


ROWS = [
    {"Title": "Song A", "Pack": "Pack1", "Type": "dance-single",
     "Difficulty": "Hard", "Grade": "AAA", "Meter": 10},
    {"Title": "Song B", "Pack": "Pack2", "Type": "dance-double",
     "Difficulty": "Challenge", "Grade": "", "Meter": 12},
    {"Title": "Song C", "Pack": "Pack1", "Type": "dance-single",
     "Difficulty": "Challenge", "Grade": "AA", "Meter": 11},
]


class FilterVariableWiringTests(unittest.TestCase):
    """filter_rows reads the filter's five variables: each variable
    narrows the rows it returns, which is the wiring the LibraryFilter
    move preserves (the filter's variables are the app's variables)."""

    @staticmethod
    def titles(rows):
        return [row["Title"] for row in rows]

    def test_unfiltered_variables_return_every_row(self):
        filt = make_filter(rows=ROWS)
        self.assertEqual(self.titles(filt.filter_rows()),
                         ["Song A", "Song B", "Song C"])

    def test_pack_variable_narrows_the_rows(self):
        filt = make_filter(rows=ROWS)
        filt.pack_var.set("Pack1")
        self.assertEqual(self.titles(filt.filter_rows()),
                         ["Song A", "Song C"])

    def test_type_variable_narrows_the_rows(self):
        filt = make_filter(rows=ROWS)
        filt.type_var.set("dance-double")
        self.assertEqual(self.titles(filt.filter_rows()), ["Song B"])

    def test_difficulty_variable_narrows_the_rows(self):
        filt = make_filter(rows=ROWS)
        filt.diff_var.set("Challenge")
        self.assertEqual(self.titles(filt.filter_rows()),
                         ["Song B", "Song C"])

    def test_scored_variable_keeps_only_scored_rows(self):
        filt = make_filter(rows=ROWS)
        filt.scored_var.set(True)
        self.assertEqual(self.titles(filt.filter_rows()),
                         ["Song A", "Song C"])

    def test_search_text_narrows_the_rows(self):
        filt = make_filter(rows=ROWS)
        filt.search_var.set("song b")
        self.assertEqual(self.titles(filt.filter_rows()), ["Song B"])


class FilterWiringGuardTests(unittest.TestCase):
    """The Step 5 wiring guard (proposal 0009 §6): the filter's five
    variables are the app's variables, set_rows refreshes, the traces,
    the debounce, and the panel's apply_chart_filter all land on the
    filter, and a batched change refreshes exactly once."""

    @staticmethod
    def make_app_and_filter():
        """A bare app holding the same five variables the filter was
        built from, the way __init__ shares them with _build."""
        instance = object.__new__(app.LibraryApp)
        instance.search_var = _ValueVar("")
        instance.pack_var = _ValueVar("All packs")
        instance.type_var = _ValueVar("All types")
        instance.diff_var = _ValueVar("All difficulties")
        instance.scored_var = _ValueVar(False)
        instance.search_entry = Mock()
        instance.pack_filter = Mock()
        instance.type_filter = Mock()
        instance.diff_filter = Mock()
        instance.root = Mock()
        instance.refresh_table = Mock()
        instance._filter = LibraryFilter(
            instance.search_var, instance.pack_var, instance.type_var,
            instance.diff_var, instance.scored_var,
            instance.search_entry, instance.pack_filter,
            instance.type_filter, instance.diff_filter, instance.root)
        instance._filter.subscribe(instance.refresh_table)
        return instance

    def test_the_filters_variables_are_the_apps_variables(self):
        instance = self.make_app_and_filter()
        filt = instance._filter
        self.assertIs(filt.search_var, instance.search_var)
        self.assertIs(filt.pack_var, instance.pack_var)
        self.assertIs(filt.type_var, instance.type_var)
        self.assertIs(filt.diff_var, instance.diff_var)
        self.assertIs(filt.scored_var, instance.scored_var)

    def test_set_rows_refreshes_and_the_rows_are_the_ones_shown(self):
        instance = self.make_app_and_filter()
        filt = instance._filter
        # Before any set_rows the filter holds nothing: a forgotten call
        # leaves the table silently empty, which is what this guard is for.
        self.assertEqual(filt.filter_rows(), [])
        filt.set_rows(list(ROWS))
        instance.refresh_table.assert_called_once_with()
        self.assertEqual(filt.filter_rows(), list(ROWS))

    def test_a_dropdown_pick_refreshes_through_the_filter(self):
        instance = self.make_app_and_filter()
        instance._filter.set_rows(list(ROWS))
        instance.refresh_table.reset_mock()
        instance.pack_var.set("Pack1")
        instance.refresh_table.assert_called_once_with()

    def test_a_search_keystroke_schedules_the_debounce_on_the_filter(self):
        instance = self.make_app_and_filter()
        filt = instance._filter
        instance.search_var.set("song")
        # The trace lands on the filter: it schedules the debounce on
        # the filter's root, for the filter's own refresh.
        instance.root.after.assert_called_once_with(
            filter_module.SEARCH_DEBOUNCE_MS, filt._run_search_refresh)
        instance.refresh_table.assert_not_called()
        filt._run_search_refresh()
        instance.refresh_table.assert_called_once_with()

    def test_the_panels_apply_chart_filter_is_the_filters(self):
        instance = self.make_app_and_filter()
        filt = instance._filter
        panel = dp.DistributionPanel(
            button_factory=Mock(), search_var=instance.search_var,
            diff_var=instance.diff_var,
            show_distribution_panel=Mock(get=Mock(return_value=False)),
            distribution_metric=Mock(get=Mock(return_value="Meter")),
            filter_rows=filt.filter_rows,
            apply_chart_filter=filt.apply_chart_filter,
            save_settings=Mock(), dpi_scale=1.0)
        # The panel holds the filter's own methods (bound-method equality
        # compares __func__ and __self__, so this is an identity check).
        self.assertEqual(panel._filter_rows, filt.filter_rows)
        self.assertEqual(panel._apply_chart_filter, filt.apply_chart_filter)
        # A chart click through the panel lands on the filter: the
        # difficulty is set and the table refreshes exactly once.
        filt.set_rows(list(ROWS))
        instance.refresh_table.reset_mock()
        panel._apply_chart_filter(difficulty="Hard")
        self.assertEqual(instance.diff_var.get(), "Hard")
        instance.refresh_table.assert_called_once_with()

    def test_a_batched_change_refreshes_exactly_once(self):
        instance = self.make_app_and_filter()
        instance._filter.set_rows(list(ROWS))
        instance.refresh_table.reset_mock()
        with instance._filter.batch():
            instance.pack_var.set("Pack1")
            instance.type_var.set("dance-single")
            instance.diff_var.set("Hard")
        instance.refresh_table.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
