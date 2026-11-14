"""The filter pipeline: which rows pass, and telling the table when something changed.

LibraryFilter (proposal 0009 Step 5) owns the five filter variables (shared
with the app, which builds the dropdowns that write them), the search box,
and the rows it filters. It does not touch the Treeview, the stores, or the
status line: when something changed it notifies its subscribers (the app's
refresh_table), so the table refreshes.
"""

from __future__ import annotations

import contextlib

from library_data import (
    CHART_FILTER_FIELDS,
    difficulty_sort_key,
    find_unreadable_directives,
    match_chart_query,
    parse_search_query,
)

SEARCH_DEBOUNCE_MS = 200


class LibraryFilter:
    """Decide which rows pass, and tell the table when something changed.

    search_var, pack_var, type_var, diff_var, scored_var: the five filter
        variables, shared objects; the app builds the dropdowns that write
        them, the filter reads them.
    search_entry: the search box widget, for focus, clear, and the cursor
        nudge after a chart-filter change.
    pack_filter, type_filter, diff_filter: the three dropdown widgets, so
        the dropdown reset after a load is set_choices(rows).
    root: for after() scheduling of the search debounce.

    The filter holds the rows it filters (set via set_rows(rows)). It
    exposes set_rows(rows), set_choices(rows), filter_rows(ignore_metric=None),
    search_hint(), batch(), apply_chart_filter, focus_search, clear_search,
    and subscribe(callback) — the callback is invoked when something changed,
    so the table refreshes. The filter installs the variable traces
    itself: a dropdown or scored pick refreshes at once, a search
    keystroke refreshes after a short pause (the debounce).
    """

    def __init__(self, search_var, pack_var, type_var, diff_var, scored_var,
                 search_entry, pack_filter, type_filter, diff_filter, root):
        self.search_var = search_var
        self.pack_var = pack_var
        self.type_var = type_var
        self.diff_var = diff_var
        self.scored_var = scored_var
        self.search_entry = search_entry
        self.pack_filter = pack_filter
        self.type_filter = type_filter
        self.diff_filter = diff_filter
        self.root = root
        # The rows the filter filters, and the table refresh it notifies.
        self._rows: list[dict] = []
        self._subscribers = []
        self._batching_filter_changes = False
        self._search_refresh_after_id = None
        # The variable traces: a dropdown or scored pick refreshes at
        # once, a search keystroke refreshes after a short pause.
        self.search_var.trace_add("write", lambda *_: self._schedule_search_refresh())
        for var in (self.pack_var, self.type_var, self.diff_var, self.scored_var):
            var.trace_add("write", lambda *_: self._refresh_unless_batching())

    def set_rows(self, rows):
        """Hold the rows the filter filters, and refresh the table.

        The refresh goes through _refresh_unless_batching, so a set_rows
        inside batch() is covered by the batch exit's refresh instead of
        refreshing twice; a set_rows on its own refreshes at once, so a
        forgotten call cannot leave the table silently empty.
        """
        self._rows = rows
        self._refresh_unless_batching()

    def set_choices(self, rows):
        """Rebuild the dropdown choices from the loaded rows.

        A choice that is no longer in the library falls back to its "All …"
        value; one that is still there is kept. Called inside batch() by
        the app's on_library_changed, so the table refreshes exactly once
        for the whole reset. set_choices does not batch itself: outside a
        batch each stale pick refreshes at once.
        """
        for combo, var, label, key in (
                (self.pack_filter, self.pack_var, "All packs", "Pack"),
                (self.type_filter, self.type_var, "All types", "Type")):
            values = [label] + sorted(
                {str(r[key]) for r in rows if r[key]}, key=str.casefold)
            combo.configure(values=values)
            if var.get() not in values:
                var.set(label)
        difficulties = sorted(
            {str(row["Difficulty"]) for row in rows if row["Difficulty"]},
            key=difficulty_sort_key,
        )
        difficulty_values = ["All difficulties"] + difficulties
        self.diff_filter.configure(values=difficulty_values)
        if self.diff_var.get() not in difficulty_values:
            self.diff_var.set("All difficulties")

    def subscribe(self, callback):
        """Register a callback invoked when something changed (the table refresh)."""
        self._subscribers.append(callback)

    def _notify(self):
        for callback in self._subscribers:
            callback()

    def filter_rows(self, ignore_metric=None):
        """Return the rows that pass the pack, type, difficulty, scored and search filters.

        ignore_metric ("Meter", "Difficulty" or "BPM") leaves out that chart's own filter, both the
        search directive and, for Difficulty, the dropdown. The distribution chart uses this to keep
        showing every bar after you click one.
        """
        query_text = self.search_var.get().strip()
        criteria = parse_search_query(query_text) if query_text else None
        ignored_field = CHART_FILTER_FIELDS.get(ignore_metric)
        if criteria and ignored_field:
            criteria = {**criteria, "directives": [
                directive for directive in criteria["directives"] if directive[0] != ignored_field]}
        pack, chart_type, diff = self.pack_var.get(), self.type_var.get(), self.diff_var.get()
        if ignore_metric == "Difficulty":
            diff = "All difficulties"
        rows = []
        for row in self._rows:
            if pack != "All packs" and row["Pack"] != pack:
                continue
            if chart_type != "All types" and row["Type"] != chart_type:
                continue
            if diff != "All difficulties" and row["Difficulty"] != diff:
                continue
            if self.scored_var.get() and not row["Grade"]:
                continue
            if criteria and not match_chart_query(row, criteria):
                continue
            rows.append(row)
        return rows

    def search_hint(self) -> str:
        """Hint naming the first unreadable search directive, or "" when none."""
        unreadable = find_unreadable_directives(self.search_var.get())
        return f"Can't read the value in {unreadable[0]}" if unreadable else ""

    @contextlib.contextmanager
    def batch(self):
        """Change several filter variables, then refresh the table once.

        Each filter variable refreshes the table by itself when it changes (the search box after a
        short delay), so one chart click that sets two of them would rebuild the table and the chart
        several times. Inside this block those automatic refreshes are skipped, and one refresh runs
        when the block ends. The flag is on/off, not a depth count: a batch
        started inside another refreshes when the inner block ends, so
        nested batches refresh more than once.
        """
        self._batching_filter_changes = True
        try:
            yield
        finally:
            self._batching_filter_changes = False
        if self._search_refresh_after_id is not None:
            self.root.after_cancel(self._search_refresh_after_id)
            self._search_refresh_after_id = None
        self._notify()

    def apply_chart_filter(self, difficulty=None, query=None):
        """Apply a distribution chart's filter change as one batched update (proposal 0005).

        The distribution panel computes the new values and calls this; a value left
        as None is not written, so the writes are exactly the ones the chart action
        calls for. Applying a change ends with the search cursor at the end of the
        box, as a chart click or Clear always has; a call with nothing to change
        neither refreshes nor nudges.
        """
        if difficulty is None and query is None:
            return
        with self.batch():
            if difficulty is not None:
                self.diff_var.set(difficulty)
            if query is not None:
                self.search_var.set(query)
        self.search_entry.icursor("end")

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _refresh_unless_batching(self):
        if not self._batching_filter_changes:
            self._notify()

    def _schedule_search_refresh(self):
        """Refresh the table once the user pauses typing in the search box."""
        if self._batching_filter_changes:
            return
        if self._search_refresh_after_id is not None:
            self.root.after_cancel(self._search_refresh_after_id)
        self._search_refresh_after_id = self.root.after(
            SEARCH_DEBOUNCE_MS, self._run_search_refresh)

    def _run_search_refresh(self):
        self._search_refresh_after_id = None
        self._notify()
