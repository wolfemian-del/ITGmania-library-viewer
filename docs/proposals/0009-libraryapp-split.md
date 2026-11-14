# Implementation Proposal: Split LibraryApp into Its Own Components

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse (Muse Spark 1.3) |
| **Date** | 2026-11-13 |
| **Base** | main `c3fb7e3` (after PR #158 merged; Ruff adopted, guards merged) |
| **Related** | The split sequence adopted after proposal 0001 (Course Builder → Advanced Search → distribution panel → settings/snapshot → **the app shell itself**). No dedicated issue; the implementation PRs will be the vehicles, as with proposals 0002 and 0004. |

---

In plain language: the main window class, `LibraryApp`, is the last big un-split piece of the app — one class with 74 methods that does the window, the table, the loading and syncing, and the dialogs. This proposal splits it into three standalone components, following the same pattern as the Course Builder, Advanced Search, and Distribution Panel: a Data Paths dialog, a background data engine (loading and syncing), and the table with its filter pipeline. Nothing the user sees changes. The one real decision is where the table's boundary falls — whether the filter pipeline lives inside the table component or beside it as its own component (§7, Q1).

## 1. Background and Goal

The split sequence is nearly complete. Course Builder (proposal 0001), Advanced Search (0004), the Distribution Panel (0005), and the settings/snapshot stores (0008) are all standalone components with constructor contracts a reader can see in one place. What remains is the shell they hang off: `LibraryApp` itself. It is the largest single concentration left in the codebase, and the only class that still mixes window management, data loading, and display logic in one place.

That is why this proposal exists before any code moves. The seams here are the most coupled in the app — the table, the filter, and the loader all read and write the same state — so the boundary decisions need to be made up front, not discovered mid-move. Nothing about the app's appearance or behaviour changes; the goal is three components owning their areas end to end, with constructor contracts a reader can see in one place, as with the four splits before this one. "Done" means `LibraryApp` is a thin shell — it builds the window, creates the stores and the components, wires them together, and owns the settings save — and each component is understandable from its own one-sentence description without holding the rest of the file in mind.

This change creates three new component boundaries and three new constructor contracts, so it needs a proposal. It does not persist a new settings key or file format.

## 2. Current State (measured on main `c3fb7e3`)

- [CODE] `library_visualizer.py` is 1,788 lines. The `LibraryApp` class spans lines 91–1774 (1,684 lines) and holds **74 methods** (including `__init__`). By comparison the four extracted components are 454 lines (Course Builder), 361 (Distribution Panel), 288 (Advanced Search), and the two stores live in `library_data.py`. `library_data.py` itself is 2,060 lines with 75 module functions — large, but flat functions, not a god class.
- [CODE] The 74 methods fall into four clusters, counted by AST (method-body lines; the class total includes blank lines and comments between methods):

  | Cluster | Methods | Lines | What it is |
  |---|---|---|---|
  | Data Paths dialog | 9 | 157 | The dialog where the two library paths are edited, opened at startup and from the File menu |
  | Load / sync engine | 21 | 596 | The background data engine: scan, snapshot restore, scores sync, progress and status |
  | Table + filter pipeline | 25 | 297 | The Treeview, its columns and sorting, the filter pipeline, and selection |
  | Shell (stays in the app) | 16 | 514 | Window building, menubar, settings save, geometry, exit, export, About |
  | Shared widget factories | 3 | 19 | `_entry`, `_combo`, `_button` — used by the app and the dialog |

  The three moving clusters total 1,050 method-body lines across 55 methods. The shell's 514 lines include `__init__` (161) and `_build` (125), both of which shrink sharply as state moves out — `__init__` currently assigns 55 `self.*` attributes, most of which belong to a component.
- [CODE] **Data Paths dialog (9 methods):** `open_data_paths_dialog`, `_set_data_paths_note`, `_close_data_paths_dialog`, `_data_paths_load`, `_invalid_paths_note`, `_maybe_show_first_run_paths_dialog`, `choose_cache`, `choose_stats`, `_path_row`. It touches `cache_var` and `stats_var` (the two path variables, read and written), the dialog state (`_data_paths_window`, `_data_paths_form`, `_data_paths_note`, `_data_paths_popup_shown`), the widget factories, and three note constants (`_DATA_PATHS_FIRST_RUN_NOTE`, `_DATA_PATHS_DEAD_NOTE`, `_DATA_PATHS_DIFFER_NOTE`). Outside calls into it: `_load_initial_snapshot` calls `_maybe_show_first_run_paths_dialog`; `_source_paths_changed` calls `_set_data_paths_note`; `load_data` and `sync_scores` call `open_data_paths_dialog` when the paths are invalid; `_data_paths_load` calls back into `load_data`. `_invalid_paths_note` has no `self.*` references at all — it is a pure function of the two paths.
- [CODE] **Load / sync engine (21 methods):** `load_data`, `_load_worker`, `sync_scores`, `_sync_scores_worker`, `_scores_synced`, `_scores_sync_failed`, `_poll_load_results`, `_show_load_progress`, `_show_load_phase`, `_load_failed`, `_loaded`, `_load_initial_snapshot`, `load_cached_data`, `_source_paths_changed`, `_current_paths_match_loaded`, `_report_discarded_settings`, `_report_moved_source_paths`, `_report_newer_stats_file`, `_set_sync_menu_state`, `_load_is_stale`, `_format_refresh_time`. It owns the worker state (`_load_generation`, `_render_generation`, `_load_results` queue, `_snapshot_lock`, `_scan_in_flight`, `_sync_in_flight`, `_load_started_at`, the `_snapshot_*` counters) and the two stores. The workers themselves are already isolated: `_load_worker` and `_sync_scores_worker` touch only `_load_is_stale`, `_load_results`, `_snapshot_lock`, and `_snapshot_store` — no widgets. The coupling is in the handlers: `_loaded` touches the filter dropdowns (`diff_filter`, `diff_var`, `pack_filter`, `pack_var`, `type_filter`, `type_var`) to reset them after a load, and calls `_batched_filter_changes`; `_scores_synced` calls `refresh_table`; `_poll_load_results` dispatches to `_loaded`, `_scores_synced`, `_scores_sync_failed`, `_load_failed`, `_show_load_progress`, and `_show_load_phase` via `root.after`. The engine writes the status line and the progress bar directly, and disables/enables `load_button` and the File → Sync menu entry.
- [CODE] **Table + filter pipeline (25 methods):** `refresh_table`, `_insert_batch`, `_update_sort_headings`, `sort_by`, `_shift_sort_click`, `_select_all_rows`, `_column_visibility_changed`, `_sync_group_checks`, `_group_visibility_changed`, `reset_column_layout`, `_column_drag_start`, `_column_drag_end`, `_displayed_column_at`, `_displayed_column_bounds`, `_filter_rows`, `_unreadable_search_hint`, `_schedule_search_refresh`, `_run_search_refresh`, `_refresh_unless_batching`, `_batched_filter_changes`, `apply_chart_filter`, `focus_search`, `clear_search`, `_selected_rows_for_course`, `_library_rows_for_course`. It owns the Treeview (`tree`, `tree_item_rows`, `_tree_tint`), the count label, the sort state (`sort_keys`), and the column state (`column_order`, `column_visibility`, `column_widths`, `default_column_widths`, `group_visibility`, `_dragged_column`, `_drag_start_x`). `refresh_table` is the hub: every filter change, sort, load, and sync funnels through it — it calls `_filter_rows`, then `_insert_batch`, then pushes the visible rows to the Distribution Panel (`distribution_panel.show_rows`). `_filter_rows` reads five filter variables (`search_var`, `diff_var`, `pack_var`, `type_var`, `scored_var`) and `self.rows`. The filter dropdowns are built in `_build` and write to those variables; the View menu checkbuttons bind `column_visibility` and `group_visibility`. `_selected_rows_for_course` and `_library_rows_for_course` are the two callables passed to the Course Builder (proposal 0001's seam). `apply_chart_filter` is the Distribution Panel's callback (proposal 0005's seam).
- [CODE] **Shell (16 methods, stays):** `__init__`, `_style`, `_build`, `_close_app`, `_course_geometry_changed`, `_advanced_search_geometry_changed`, `_build_menubar`, `_settings_file_path`, `library_cache_path`, `_valid_course_geometry`, `_valid_advanced_search_geometry`, `_save_settings`, `_dialog_is_open`, `_on_main_escape`, `export_csv`, `open_about`. `_save_settings` reads state from every cluster (the filter variables, the column state, the sort keys, the distribution variables, the geometry) — it is the one method that must keep seeing the whole app, and it stays app-side for that reason.
- [CODE] **Entry points into the three moving clusters, from outside them:** the Data Paths dialog is opened by `_load_initial_snapshot`, `load_data`, `sync_scores`, and the File menu; the loader is started by `load_data`, `sync_scores`, and `_load_initial_snapshot` (via `load_cached_data`); the table is refreshed by the filter variable traces (via `_refresh_unless_batching`), the search debounce, `sort_by`, `_loaded`, `_scores_synced`, and the Distribution Panel's `apply_chart_filter` callback. No other module imports `library_visualizer.py`'s internals; the components are constructed only in `_build`.
- [CODE] **Test coverage:** `tests/test_library_visualizer.py` is 3,326 lines with 160 tests in ~30 classes, most of them building a bare `LibraryApp` with `object.__new__` and hand-setting attributes — the fixture pattern the splits exist to replace (issue #92's payoff for the Course Builder, proposal 0005 §6 for the panel). The live tests (needing a real Tk root) live in `tests/test_library_visualizer.py` (seven `Live*` classes) and `tests/test_ui_distribution.py`. The `windows-ui` CI job runs exactly those two test files; the ubuntu jobs run the whole suite. A new test file would run on ubuntu but not on `windows-ui` without a workflow edit, which only the owner can make (the app bot has no Workflows permission).
- [CODE] **File lists a move must update:** `WINDOW_SOURCES` in `tests/test_theme.py` (currently five files: `library_visualizer.py`, `course_builder.py`, `row_tints.py`, `advanced_search.py`, `distribution_panel.py`) — the proposal 0004 lesson, learned when the same list went stale on PR #89. The README's architecture paragraphs (lines 88–92) describe the three existing components; each new component gains a sentence there.

## 3. The Decision: Three Components, Staged

### Option A (recommended): three standalone components, one per cluster

Three new modules, each owning one cluster end to end, mirroring the existing components: the dialog owns its widgets and its note logic; the loader owns its workers, its queue, and its progress/status reporting; the table owns the Treeview and the whole refresh pipeline. The app keeps the shell and coordinates: it creates the stores and the components, passes each its constructor inputs, and wires the callbacks. Each component's constructor contract is stated in §4, and the one-sentence description each must pass is given there too.

The alternative granularities were considered and are recorded as open questions in §7, because they are real choices a reviewer may overturn: splitting the filter pipeline out of the table as its own component (Q1), and where the loader's result handlers live (Q2).

### Option B: extract the pure logic only, keep the window in the app

Move `_invalid_paths_note` and any other Tk-free helpers to `library_data.py` (the §6 extraction step does this for the note) and stop there. Worth doing on its own merits — this proposal includes it as a step — but as the whole answer it leaves 55 methods and 1,050 lines inside `LibraryApp`; the split's point is not achieved.

### Option C: a mixin class for `LibraryApp`

Rejected for the same reason as in proposals 0001, 0004, and 0005: it hides the boundary instead of stating it, against the owner's standing guideline of legibility for a human reviewer.

## 4. Recommended Design in Detail (Option A)

**DataPathsDialog** (`data_paths_dialog.py`). One sentence: the one dialog where the two library paths are edited, which opens at startup when there is nothing to show and re-opens from the File menu. Its constructor inputs, stated per the proposal 0001 safeguard:
1. `parent` — the root window, for the Toplevel.
2. `cache_var`, `stats_var` — the two path variables, shared objects; the dialog edits them, the app and the loader read them.
3. `load_callback` — called with the dialog's paths when the user presses Load (today's `load_data`).
4. `save_settings` — callable, invoked when a path is chosen (today `choose_cache`/`choose_stats` save).
5. `button_factory`, `entry_factory`, `combo_factory` — the themed widget factories, the precedent from the other components.
6. `dpi_scale` — the display scale factor, for the path rows and the note line.
7. `paths_match_loaded` — a zero-argument callable returning whether the dialog's paths match the loaded snapshot's sources (today's `_current_paths_match_loaded`), so the dialog can show the "differs from loaded" note.

The three note constants move into the dialog module (they are dialog text). `_invalid_paths_note` moves to `library_data.py` in §6's extraction step — it is pure — and the dialog imports it. The dialog exposes `open()`, `maybe_show_first_run()`, and `set_note(text)`; the app and the loader call those where they call the methods today. The dialog does not reach back into the app: it never touches the table, the stores, or the status line.

**LibraryLoader** (`library_loader.py`). One sentence: the background data engine — it loads the library (scan or snapshot), syncs scores, and reports progress and status, all off the main thread. Its constructor inputs:
1. `snapshot_store`, `settings_store` — the two stores, passed in (they are already standalone).
2. `cache_var`, `stats_var` — the path variables, read.
3. `status` — the status StringVar, for the progress and status reporting the engine already does.
4. `progress` — the progress-bar widget.
5. `load_button` — the Load button widget, disabled during a load and re-enabled after.
6. `set_sync_menu_state` — callable, enabling/disabling the File → Sync scores entry.
7. `on_loaded` — callback, delivered when a load finishes with (rows, loaded paths, refreshed_at, snapshot counts); the app implements it by setting the rows, resetting the filter dropdowns, and refreshing the table (today's `_loaded`, split at the seam — see Q2).
8. `on_scores_synced`, `on_scores_sync_failed`, `on_load_failed` — callbacks, delivered with the same payloads today's handlers receive.
9. `open_data_paths_dialog` — callable, for when the paths are invalid or there is nothing to show.
10. `save_settings` — callable.
11. `root` — for `after()` scheduling of the result polling.

The workers move unchanged (`_load_worker`, `_sync_scores_worker` already touch no widgets). The result queue, the polling, and the progress/phase reporting move with them. The generation counters and the in-flight flags move too — they are the engine's own state. The engine never touches the table or the filter variables directly; everything the UI needs arrives through the callbacks in (7) and (8).

**LibraryTable** (`library_table.py`). One sentence: the table and everything that decides what's in it — the Treeview, its columns and sorting, the filter pipeline, and selection. Its constructor inputs, counted as individual values (the precedent from proposal 0005, which counted eight):
- `parent` — the table frame, for the Treeview.
- The five filter variables, shared objects: `search_var`, `diff_var`, `pack_var`, `type_var`, `scored_var`. The app builds the dropdowns that write them; the table reads them.
- The column state, shared objects: `column_order`, `column_visibility`, `column_widths`, `default_column_widths`, `group_visibility`. The View menu binds the visibility variables; the table owns the drag/reorder.
- `sort_keys` — the sort state, a shared list.
- `count_label` — the label showing the row count.
- `tree_tint` — the row-tint helper.
- `search_entry` — the search box widget, for focus, clear, and the cursor nudge after a chart-filter change.
- `root` — for `after()` scheduling of the search debounce and the insert batches.
- `dpi_scale` — the display scale factor.
- `save_settings` — callable, invoked when the sort, the columns, or the layout change.
- `show_rows` — a callable the table invokes with the visible rows after each refresh, so the Distribution Panel keeps receiving its push (today `refresh_table` calls `distribution_panel.show_rows` directly).

That is nineteen inputs — more than twice the Distribution Panel's eight, and the proposal says so openly instead of hiding it: the table genuinely has more contact with the app than any component so far, because the filter pipeline and the column state are shared with the app's menus. The constructor list is the honest record of that contact, and it is also the strongest argument for splitting the filter pipeline out as its own component (Q1). The app pushes the full library rows after a load or a sync via a `set_rows(rows)` method on the table (the push precedent from the Distribution Panel's `show_rows`); that is a method call, not a constructor input.

The table exposes `refresh()`, `selected_rows()`, and `library_rows()` — the last two are today's `_selected_rows_for_course` and `_library_rows_for_course`, which the app passes to the Course Builder. The table does not touch the stores, the paths, or the status line (except through the count label, which it owns).

**App side after the move.** Deleted from `LibraryApp`: the 55 methods of the three clusters, the `_data_paths_*` and worker state attributes, and the filter/column/sort state declarations (those become constructor inputs to the table). `__init__` shrinks to creating the shell, the stores, and the components; `_build` shrinks to laying out the frames and constructing the components in order — the table before the Distribution Panel (which receives the table's `show_rows` push), the loader after the status widgets exist. The app gains four small coordinator methods: the `on_loaded` / `on_scores_synced` / `on_scores_sync_failed` / `on_load_failed` callbacks that set the rows, reset the filter dropdowns via the table, and refresh. The widget factories (`_button`, `_entry`, `_combo`) stay app-side and are passed to the components, as today. The README's architecture paragraphs gain a sentence per new component, next to the other three.

## 5. What Does Not Change

- Everything the user sees: the window layout, the table, the columns and their drag/reorder, the sort behaviour, the filter dropdowns and search box, the Data Paths dialog (its fields, buttons, and note lines), the load progress bar and its phases, the status messages (including the discarded-settings, moved-paths, and newer-Stats hints), the sync refusal messages, and the About dialog.
- Load and sync semantics exactly: the scan, the snapshot restore, the scores-only sync, the mid-sync mtime guard, the empty-scores and matched-nothing refusals, the generation/staleness checks, and the snapshot write under the lock. The workers move unchanged.
- The filter semantics: `_filter_rows` keeps its exact behaviour (pack, type, difficulty, scored, and search filters, including the unreadable-directive hint), the batching rule (one refresh per batched change), and the search debounce.
- The settings keys, the snapshot format (schema version 4), and their place in `_save_settings`. No new settings key, no file-format change.
- The three existing components (Course Builder, Advanced Search, Distribution Panel) and their contracts. The table's `show_rows` push to the panel keeps today's ordering (rows stored before the hidden check, per proposal 0005 §5). No geometry memory is added for anything new, and no keyboard shortcut appears.
- The `.CRS` output, the CSV export, and the course-builder ambiguity check.

## 6. Test Plan (for the implementation PRs)

Five pull requests, in order. Each is independently green, and the order is the point: the safety net exists before any boundary moves, and the easiest component moves first, so each move PR can be judged as a move.

**Step 1 — test hardening (no production code changes).** Write the missing tests against today's `LibraryApp` methods, so they pin current behaviour before anything relocates. The gaps, from the §2 inventory: the Data Paths dialog's note transitions (first-run, dead-paths, differs-from-loaded) as headless tests; the loader's `_source_paths_changed` and `_current_paths_match_loaded` branches; the table's column-drag reorder and `_displayed_column_at`/`_displayed_column_bounds` edge cases; and the wiring guards (see Steps 4 and 5) written first against the app, so the move PRs re-point them rather than inventing them.

**Step 2 — pure-logic extraction to `library_data.py`.** Move `_invalid_paths_note` (pure: two paths in, a note string out) and add Tk-free tests for it in `tests/test_library_data.py`. No behaviour change; the dialog and the loader call the moved function. This is the Option B step, done first so the component moves are pure moves.

**Step 3 — the Data Paths dialog move.** `data_paths_dialog.py` as §4 describes. Move purity: the nine methods move recognisably (a normalized diff, as for proposals 0001, 0004, and 0005), with renames limited to the seams (`self.cache_var` → the constructor input, and so on). The tests for the dialog move to `tests/test_data_paths_dialog.py` (headless; the ubuntu job runs the whole suite, so they are covered there) except the live dialog tests, which stay in `tests/test_library_visualizer.py` — the `windows-ui` job runs exactly two test files, and a new file would need a workflow edit only the owner can make (see Q3). Add `data_paths_dialog.py` to `WINDOW_SOURCES` in `tests/test_theme.py` and to the README's architecture paragraphs — the proposal 0004 lesson.

**Step 4 — the LibraryLoader move.** `library_loader.py` as §4 describes. Move purity: the 21 methods move recognisably, with the handlers (`_loaded`, `_scores_synced`, `_scores_sync_failed`, `_load_failed`) split at the callback seam per Q2's resolution. The loader's tests move to `tests/test_library_loader.py` (headless; the worker tests already run headless today) except the live load-progress tests, which stay in `tests/test_library_visualizer.py`. The wiring guard: a test asserting the loader's workers are the app's workers (the generation counters and the in-flight flags are the loader's, not the app's), that `load_data` and `sync_scores` reach the loader, and that a load delivers rows to the table.

**Step 5 — the LibraryTable move.** `library_table.py` as §4 describes. Move purity: the 25 methods move recognisably, with renames limited to the seams and the one deliberate rename, `refresh_table` → `refresh` (the app already has no other `refresh`, but the shorter name matches the component's vocabulary; if reviewers prefer the move to be rename-free, the method keeps its name — see Q4). The table's tests move to `tests/test_library_table.py` (headless) except the live table tests (selection, drag, sort clicks), which stay in `tests/test_library_visualizer.py`. The wiring guard: a test asserting the table's five filter variables *are* the app's variables; that `set_rows` actually refreshes (without this, a forgotten call leaves the table silently empty); that the filter traces, the sort clicks, and the Distribution Panel's `apply_chart_filter` all land on the table; and that `refresh` reaches the panel's `show_rows`. Acceptance, in CI terms: the full suite green on the ubuntu jobs (live tests skipping there, as today) and the live tests green with zero skips on the `windows-ui` job. Plus a live smoke: load the library, type a search, change a filter, sort a column, drag a column, open and close the Data Paths dialog, sync scores, quit and relaunch to confirm the settings persist.

## 7. Open Questions for Reviewers

- **Q1. Should the filter pipeline be its own component, or stay inside the table?** Recommended: stay inside the table (Option A). The filter and the table are one refresh pipeline — `refresh_table` is the hub, the filter variables trigger it via traces, and splitting them would create a tight two-way coupling (the filter notifies, the table pulls) that is harder to follow than one component owning the pipeline. The nineteen-input constructor is the honest record of that contact, and it is the strongest argument for the split — this is the closest call in the proposal, and the reviewers may overturn it. The alternative — a separate `LibraryFilter` owning the five variables, `_filter_rows`, the batching, and the debounce, with the table as a pure view that receives filtered rows — would shrink the table's constructor to about ten inputs, at the cost of a fourth component and a notification seam between the two. If reviewers find nineteen inputs indefensible, the split is the fallback, and the staging gains a PR between Steps 4 and 5.
- **Q2. Where do the loader's result handlers live?** Recommended: the handlers (`_loaded`, `_scores_synced`, `_scores_sync_failed`, `_load_failed`) stay in the app as the loader's callbacks, because they touch app state (the rows, `last_refreshed_at`, `loaded_source_paths`) and the table (the filter reset) — they are coordination, not engine work. The alternative — moving the handlers into the loader and giving it the rows and the filter-reset callback — would make the loader own app state it should not. The handlers are small (118 lines combined) and the app is their natural home.
- **Q3. Where do the new components' live tests live?** Recommended: the headless component tests go in new files (`tests/test_data_paths_dialog.py`, `tests/test_library_loader.py`, `tests/test_library_table.py` — covered by the ubuntu job, which runs the whole suite); the live tests stay in `tests/test_library_visualizer.py`, which the `windows-ui` job already runs. The alternative — adding the new files to the `windows-ui` job — needs a workflow edit, which only the owner can make (the app bot has no Workflows permission). If the owner prefers the workflow edit, it is a one-line change per file and the live tests move with their components.
- **Q4. Is `refresh_table` renamed to `refresh` in the move, or does the move stay rename-free?** Recommended: rename to `refresh` (the component's vocabulary is shorter, and the app has no other `refresh` to confuse it with). The alternative — keeping `refresh_table` — makes the move a pure move with zero renames, which is easier to verify by normalized diff. Either is fine; the reviewers decide.

---

*Written by Muse (Muse Spark 1.3). Measurements in §2 are from the code on main `c3fb7e3`, counted by AST.*
