# Implementation Proposal: Extract the Distribution Panel into Its Own Component

| | |
|---|---|
| **Status** | Draft — Revision 2 (panel review complete; the resolutions in §7 were accepted by the owner on 2026-11-09, and §6 carries the staging amendments from the confirmation round) |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-09 |
| **Base** | main `a94aa1b` (after PR #108; v1.1.0 tagged) |
| **Related** | The split sequence adopted after proposal 0001 (Course Builder → Advanced Search → **distribution** → settings/snapshot). Measurements in §2 are from a survey by Claude (Sonnet 5.5), 2026-11-09, re-verified against this base by the author. No dedicated issue; the implementation PRs will be the vehicles, as with proposals 0002 and 0004. |

---

## Revision 1 (2026-11-09, from the panel review)

Reviewed by Claude (Sonnet 5.5), Grok 4.5, ChatGPT-6, and GLM 5.3
(Vibe — which also produced the staging review signed "Mistral": one
model, two separately-prompted reports). All four recommend accepting
the proposal. The owner accepted the resolutions below on 2026-11-09.
The changes, each folded into the text so later readers see the
corrected version:

- **Q3 overturned (Claude):** the component does not receive the
  batching context manager. It computes the new filter values and
  calls an app-side `apply_chart_filter(difficulty=None, query=None)`
  callback; `None` means "leave it alone", so the app makes exactly
  today's writes, inside its own batching, and nudges the cursor
  itself. Claude verified the equivalence with a prototype run (6
  click and 3 Clear scenarios; writes, refresh counts and cursor
  nudges matched). `search_entry` leaves the design entirely.
- **Q5 overturned (Claude):** `_build`'s order is untouched. The
  component receives the table frame through a `sibling_frame`
  callable, resolved when the panel is shown — avoiding an inferred
  risk that moving the frame's creation line would change the Tab
  focus order.
- **Q6 simplified (Claude):** the hide path calls the panel frame's
  own `update_idletasks()` (application-wide in Tk). Neither a root
  input nor `winfo_toplevel()` is needed.
- **Q4 amended (Claude):** `build_panel` also sets the toolbar
  button's initial label, so the "Distribution ◀/▶" strings live in
  one place.
- **Q2 simplified (Claude):** the app's `_filter_rows` is passed
  directly as the pull callable — `ignore_metric` is already its
  first parameter, so no wrapper is needed.
- **§2 corrected (Claude, Grok, GLM):** the method block spans 254
  lines of file, of which the eleven method bodies total 244; the
  method list now follows the file's order; `dist_summary_var` is
  created in `_build_distribution_panel`, not `__init__`; the
  visibility funnel claim is qualified (the startup pack and initial
  label are set directly in `_build`); and three distribution tests
  live in `tests/test_library_visualizer.py`, not one.
- **§6 expanded (Claude; GLM 5.3's staging review):** Step 1 gains a
  hide→show test pinning the re-show's full pack arguments, a
  metric-change effect test, and a bar-colour/edge test, and marks
  the canvas-creation and startup-validation gaps as live tests;
  Step 2's click-zone function takes the theme fraction and axis
  multiplier as parameters and returns `axis_max`, pins Clear's
  no-op early return, and re-points the tests' `ChartBar`
  references; Step 3's wiring guard covers all six entry points,
  asserts the cursor nudge and that `build_panel` ran, and its
  acceptance criterion is stated in CI terms. The row-push method is
  renamed `show_rows` (Tk widgets already have an `update()`).
- **Q2's rejected alternative reworded:** the eager push's cost is an
  extra filter pass per refresh, stated as unmeasured; the argument
  for the lazy pull is the laziness itself, not a measured cost.

---

## Revision 2 (2026-11-09, from the confirmation round)

Grok's fidelity audit confirmed Revision 1 is a faithful
transcription of the accepted resolutions. GLM 5.3's adversarial
re-check of §6 then found amendments of the same kinds its first
review had found, all confined to §6 and folded in here:

- **Step 2's zone function takes a third parameter**,
  `theme.CHART_BAR_HEIGHT`'s value: the bars' y-coordinates derive
  from the positions and the bar height, not from the drawn
  matplotlib bars (Revision 1 named only two of the three theme-fed
  values, leaving a literal implementer to hard-code the third).
- **Step 3 pins the no-op Clear at the component level**: a Clear
  with nothing active does not call `apply_chart_filter` at all, and
  the app-side tests pin that a no-change call to it neither
  refreshes nor nudges the cursor.
- **The wiring guard counts seven entry points**, adding the chart
  click, and the cursor-nudge assertion is placed on the app-side
  `apply_chart_filter` tests, where the nudge now lives.
- **Step 1 pins two more behaviours**: the settings save on a
  visibility change (in the hide→show test) and the startup pack's
  arguments (in the live startup test, via `pack_info()`).
- **Wording**: "all new window-side tests"; "after hide then show";
  the `SingleRefreshTests` sentence scoped to what the five tests
  actually exercise; and the `MATPLOTLIB_AVAILABLE` count stated
  precisely (five patch sites and one save-and-restore assignment —
  re-verified against the test files during this round).

Claude and ChatGPT-6 will see this revision, not Revision 1, when
they confirm their amendments after their usage cooldowns.

---

## 1. Background and Goal

The distribution panel — the optional chart at the right of the window
that plots Meter, Difficulty or BPM for the current view and filters the
table when a bar is clicked — is the third piece in the split sequence.
Today it is eleven methods and 244 lines inside `LibraryApp`, the
largest of the four splits, and the first one that is *bidirectional*:
the two dialogs read or write a variable on their own schedule, but the
panel sits inside the filter loop. Every table refresh pushes rows into
it, and its clicks write back into the search box and the difficulty
dropdown. It is also switched on and off from three places and rewrites
another widget's label (the toolbar button's).

That is why this proposal exists before any code moves, and why it is
longer than 0004: the seams here are genuinely new. Nothing about the
panel's appearance or behaviour changes; the goal is one component
owning the panel end to end, with a constructor contract a reader can
see in one place, as with `CourseBuilder` and `AdvancedSearch`.

## 2. Current State (measured on main `a94aa1b`)

- [CODE] The panel is 11 methods in one block of `library_visualizer.py`
  spanning lines 1118–1371 (254 lines of file; the method bodies total
  244): `_build_distribution_panel`, `_ensure_distribution_canvas`,
  `_set_distribution_visible`, `toggle_distribution_panel`,
  `_sync_distribution_toggle`, `_on_distribution_metric_changed`,
  `clear_chart_filter`, `_on_chart_click`, `_metric_filter_present`,
  `_distribution_rows`, and `_update_distribution_panel` (105 lines on
  its own). The `ChartBar` NamedTuple sits at lines 89–95. Collateral
  code outside the block: the matplotlib import (26–33), state in
  `__init__`, the toolbar button and startup pack in `_build`, the View
  menu checkbutton, two settings keys, and one call from
  `refresh_table` — roughly 55 further lines.
- [CODE] It owns 12 attributes: the variables `show_distribution_panel`
  (BooleanVar) and `distribution_metric` (StringVar); `dist_summary_var`
  (a third variable, created later — see the stages below); the widgets
  `dist_panel`, `dist_chart_frame`, `dist_banner_frame`,
  `dist_banner_label`; the matplotlib trio `dist_canvas`, `dist_fig`,
  `dist_ax`; and the data `_current_dist_bars` (the click map) and
  `_last_visible_rows`. A 13th, `dist_button`, is shared: the toolbar
  creates it, the panel rewrites its label (◀/▶). State fills in three
  stages — the two settings variables in `__init__`, the widgets
  (including `dist_summary_var`, which `__init__` only declares as
  `None`) in `_build_distribution_panel`, and the figure lazily on
  first draw.
- [CODE] Outside references from the panel methods, counted by AST:
  `search_var` (8 uses, read *and* written), `diff_var` (6, read and
  written), `_button` (2), `_save_settings` (2), `dist_button` (2),
  `_batched_filter_changes` (2), `search_entry` (2, the `icursor("end")`
  nudge after a click or a Clear), `content_frame` (1), `table_frame`
  (1, the `pack(before=…)` sibling), `root` (1, `update_idletasks()` on
  hide), and `_filter_rows` (1 — the panel is the only caller of its
  `ignore_metric` parameter). Eleven distinct references; proposals
  0001 and 0004 counted four to five for their components.
- [CODE] Entry points: `refresh_table` pushes the visible rows via
  `_update_distribution_panel(visible)` on every redraw; the toolbar
  button and the panel's own ✕ call `toggle_distribution_panel`; the
  View ▸ Show distribution panel checkbutton calls
  `_sync_distribution_toggle` (Tk has already flipped the variable);
  the metric radio buttons call `_on_distribution_metric_changed`; the
  banner's Clear button calls `clear_chart_filter`; a matplotlib
  `button_press_event` calls `_on_chart_click`. After startup, all
  visibility changes funnel through `_set_distribution_visible`, which
  sets the variable, packs or forgets the panel, rewrites the toolbar
  label, redraws (or calls `update_idletasks()` on hide), and saves
  settings. The startup pack and the initial toolbar label are set
  directly in `_build`, outside that funnel — so the label text
  currently lives in two places. There is no keyboard shortcut.
- [CODE] Rows flow both ways. The push is the visible list from
  `refresh_table`, stored in `_last_visible_rows` even while the panel
  is hidden. The pull: when the chart's own metric is the active filter,
  `_distribution_rows` calls `_filter_rows(ignore_metric=metric)` so
  the chart keeps showing every bar for its own metric.
- [CODE] A click or a Clear changes two filter variables at once, so
  both run inside `_batched_filter_changes()`, the app's context
  manager that suppresses the per-variable refreshes and refreshes
  once on exit; the cursor nudge follows outside the block.
- [CODE] Settings: `show_distribution` and `distribution_metric` are
  read in `__init__` (lines 171–177; the metric falls back to "Meter"
  for any value outside Meter/Difficulty/BPM) and written
  unconditionally by `_save_settings` (lines 631–632) from the two
  variables. Unlike the geometry keys, they are always present. The
  panel's width is a fixed theme constant, not remembered, so this
  split has no geometry-memory part and does not trigger issue #103.
- [CODE] The number-crunching half is already out: eight functions in
  `library_data.py` (the three aggregates, `distribution_summary_stats`,
  `get_active_chart_filters`, `filter_texts_match`,
  `replace_search_directive`, `CHART_FILTER_FIELDS`) with 19 Tk-free
  tests. Still mixed into the window methods, though it needs no Tk:
  the bar hit test in `_on_chart_click`, the click-to-filter decision,
  the Clear decision, and the click-zone arithmetic (`axis_max`,
  `min_click_width`, the clickable rule) in `_update_distribution_panel`.
- [CODE] Window-side coverage: 21 tests in `tests/test_ui_distribution.py`,
  built on a `make_app` fixture that hand-sets about 20 attributes on a
  bare `LibraryApp`, plus three distribution tests in
  `tests/test_library_visualizer.py` (the settings round trip, Clear,
  and the matplotlib-missing fallback). `_on_chart_click` is heavily
  covered, including real-geometry clicks through matplotlib's Agg
  backend. Untested today: the hide path (pack_forget, the ▶ label,
  `update_idletasks`) and the re-show's pack arguments, the
  empty-state "No charts match" branch, startup validation of the two
  settings, canvas creation (the Figure and `mpl_connect`; only the
  matplotlib-missing path runs), banner pack/pack_forget,
  `_sync_distribution_toggle`, the *effect* of a metric change, bar
  colours and the active-bar edge, and the cursor nudge after a click
  or Clear. Six places patch or assign
  `MATPLOTLIB_AVAILABLE`: five `patch.object` sites in the
  distribution tests, and one save-and-restore assignment in
  `tests/test_library_visualizer.py`.
- [CODE] CI coupling: the `windows-ui` job runs
  `python -m unittest discover -s tests -p test_ui_distribution.py`.
  The test file's name is load-bearing; renaming it needs a workflow
  edit, which only the owner can make (the app bot has no Workflows
  permission). The headless ubuntu jobs run the whole suite but skip
  the live tests by design, so a live test placed in any other file
  runs in no CI job that has a display.

## 3. The Decision: The Component's Contract

### Option A (recommended): a standalone `DistributionPanel` component

A new module `distribution_panel.py` holds a component that owns the
panel end to end, mirroring `CourseBuilder` and `AdvancedSearch`: the
twelve attributes, the widget building, the drawing, the click and
Clear handlers, and the visibility funnel. The constructor receives the
seams below. Each seam is stated with its precedent; the ones that had
a real alternative are recorded as resolved questions in §7.

- **The four Tk variables, passed directly.** `search_var`, `diff_var`,
  `show_distribution_panel` and `distribution_metric` are each assigned
  exactly once in `__init__` and never replaced — the fact that settled
  proposal 0004's Q1 (option A1) — so the staleness argument for
  callables does not apply, and `AdvancedSearch`'s `search_var` and
  `CourseBuilder`'s `status` are the governing precedents. The two panel
  variables must in any case be single shared objects: the View menu
  checkbutton binds `show_distribution_panel`, the metric radios bind
  `distribution_metric`, and `_save_settings` reads both. The app keeps
  creating them from saved settings in `__init__`, with today's
  validation, and keeps reading them in `_save_settings`; the component
  receives them as inputs. Settings handling does not move (§5).
- **Rows in: a push, plus one pull callable.** `refresh_table` calls
  the component's `show_rows(visible_rows)` — today's
  `_update_distribution_panel` renamed, because Tk widgets already
  have an `update()` and the two would be easy to confuse. For the
  pull, the component receives the app's `_filter_rows` itself as the
  callable: its first parameter is already `ignore_metric`, so the
  component calls it with the metric when the chart's own filter is
  present — the callable precedent from proposal 0001
  (`selected_rows` / `library_rows`), with no wrapper. `_filter_rows`
  stays app-side because it also serves the table.
  `_metric_filter_present` needs only the two variables and
  `library_data`, so it moves into the component as-is.
- **Filter changes out: an `apply_chart_filter` callback.** A click
  and a Clear must change `diff_var` and `search_var` atomically — one
  refresh, not several — and the batching machinery that guarantees
  that is the app's. The component computes the new values (after §6's
  extraction, via the `library_data` decision functions, which return
  exactly those two values) and calls the app's
  `apply_chart_filter(difficulty=None, query=None)`: a value left as
  `None` is not written, so the app makes exactly the writes today's
  code makes — a Meter click writes only the query, a Difficulty click
  writes the difficulty and, when it changed, the query — inside
  `_batched_filter_changes()`, and then moves the search cursor to the
  end, as today. The app-side method is about six lines, and the
  "write the variables only inside a batch" rule gets a single owner
  instead of travelling with the component as an unwritten convention.
  The draft's alternative — handing the component the bound context
  manager, plus the search entry for the nudge — was overturned in
  review (§7, Q3): the callback reproduces today's behaviour
  write-for-write (prototype-verified in review) with a smaller
  component, and the component only ever *reads* the two variables.
- **Reporting out: a `save_settings` callable.**
  `_set_distribution_visible` and `_on_distribution_metric_changed`
  save settings today. The component receives the app's
  `_save_settings` as a callable input — the report-callable pattern
  from proposal 0003 (`report_geometry`).
- **The widget factories.** The panel builds its ✕ and Clear buttons
  with the app's themed `_button`; it is passed in, as both existing
  components receive it. Everything else the panel builds with plain
  `tk` constructors, as today.

### Option B: extract the pure logic only, keep the window in the app

Move the hit test and the click/Clear decisions to `library_data.py`
(the §6 extraction PR) and stop there. Worth doing on its own merits —
this proposal includes it as a step — but as the whole answer it
leaves eleven methods, twelve attributes and three visibility entry
points inside `LibraryApp`; the split's point is not achieved.

### Option C: a mixin class for `LibraryApp`

Rejected for the same reason as in proposals 0001 and 0004: it hides
the boundary instead of stating it, against the owner's standing
guideline of legibility for a human reviewer.

## 4. Recommended Design in Detail (Option A)

**Construction.** The component is constructed in `_build`, beside the
`CourseBuilder` (line 285) and `AdvancedSearch` (line 293)
constructions — before the toolbar button (line ~321), the menubar
(line 377) and every other entry point that names it, so all entry
points can be repointed directly, per proposal 0004's Q2 resolution.
Its constructor inputs are the state seams: `button_factory`,
`search_var`, `diff_var`, `show_var`, `metric_var`, the pull callable
(the app's `_filter_rows`), `apply_chart_filter`, `save_settings` —
eight inputs, stated here per the proposal 0001 safeguard. (For scale:
`CourseBuilder` sits at seven after two growth steps; this panel
genuinely has more contact with the app, and the contract says so
openly instead of hiding it.)

**Widget building.** The widgets cannot be built at construction time:
their parent, `content_frame`, is created later in `_build`, and the
show path packs the panel `before` the table frame, which is also
created later. So the component has a
`build_panel(content_frame, toolbar_button, sibling_frame)` step that
the app calls where `_build_distribution_panel` is called today.
`sibling_frame` is a zero-argument callable returning the app's table
frame, resolved only when the panel is shown — `_build`'s order is
not changed at all. `build_panel` creates the panel's widgets
(today's method body, unchanged), stores those widget-time
references, sets the toolbar button's initial label from the show
variable (so the "Distribution ◀/▶" strings exist only in the
component), and performs the startup pack if the show variable is
set — with today's arguments, which omit `before=…`; the pack order
still ends up panel-before-table because the table frame is packed
after, exactly as today.

**Visibility.** `set_visible(bool)`, `toggle()` and `sync_toggle()`
are today's three methods, moved: the toolbar button and the panel's
✕ point at `toggle`, the View checkbutton at `sync_toggle` with the
shared show variable, and `set_visible` remains the single funnel —
setting the variable, packing (with `before=sibling_frame()`) or
forgetting, rewriting the toolbar button's label, redrawing from the
stored rows on show, calling the panel frame's own
`update_idletasks()` on hide (the call is application-wide in Tk, so
no root reference is needed), and invoking the `save_settings`
callable.

**Updating and clicking.** `show_rows(visible_rows)` is
`_update_distribution_panel` moved: store the rows *first* (today's
ordering — the stored copy updates even while the panel is hidden),
return early while hidden, compute chart rows (stored rows, or the
`_filter_rows` pull when the chart's own filter is present), banner,
summary, canvas, bars. `_on_chart_click` and `clear_chart_filter`
keep today's shape, except that applying the result goes through the
`apply_chart_filter` callback: compute the decision, call the
callback with whichever of (difficulty, query) changed, done. The
matplotlib guarded import and `MATPLOTLIB_AVAILABLE` move into
`distribution_panel.py` with the canvas code; the app keeps no
matplotlib import.

**App side after the move.** Deleted from `LibraryApp`: the eleven
methods, `ChartBar` (it moves to `library_data.py` in §6's step), the
ten widget/data attribute declarations (the two variables stay — they
are inputs now), the matplotlib import block, and seven `library_data`
imports that only the panel used (the three aggregates,
`distribution_summary_stats`, `get_active_chart_filters`,
`filter_texts_match`, `replace_search_directive`). `CHART_FILTER_FIELDS`
and `parse_search_query` stay — `_filter_rows` uses both. The app
gains one small method, `apply_chart_filter` (§3). The README's
architecture paragraphs gain a sentence for the new component, next
to the other two, and note that two persistence patterns coexist by
design: dialog geometry is a value in and a report out, while the
panel's variables are shared objects, because the View menu and the
settings save both bind them.

## 5. What Does Not Change

- Everything the user sees: the panel's widgets and layout, the pack
  arguments (including the startup pack's missing `before=…`), the
  toolbar label texts ("Distribution ◀" / "Distribution ▶"), the
  banner's wording and placement, the summary line, the chart's
  drawing (colours, active-bar white edge, count labels, click
  widths), the empty-state message, and the matplotlib-missing
  fallback label.
- Click and Clear semantics exactly: clicking the active bar toggles
  its filter off; a Difficulty click also removes any redundant `diff`
  directive from the query; Clear removes every chart filter and
  resets the difficulty dropdown; both end with the cursor at the end
  of the search box and exactly one table refresh; a Clear with no
  active chart filter does nothing at all — no refresh, no cursor
  move. Which variables each path writes is preserved write-for-write
  (§3), and `show_rows` keeps today's ordering of storing the pushed
  rows before the hidden check.
- The two settings keys, their startup validation, and their place in
  `_save_settings`. The settings/snapshot move — last in the sequence —
  inherits the arrangement §3 settles: the variables stay app-created
  and app-saved, so that move meets two ordinary variable reads, not a
  component negotiation.
- `_filter_rows`, the table, the course builder, Advanced Search and
  `.CRS` output. No geometry memory is added for the panel (its width
  stays a theme constant), no keyboard shortcut appears, and no other
  window code moves in any of the staging PRs (§6), per the rule
  proposal 0004 §5 recorded.

## 6. How the Work Is Staged

Three pull requests, in order. Each is independently green, and the
order is the point: the safety net and the pure logic exist before
the boundary moves, so the move PR can be judged as a move. All new
window-side tests for the panel live in `tests/test_ui_distribution.py` — the
only test file the display-equipped `windows-ui` CI job runs (§2).

**Step 1 — test hardening (no production code changes).** Write the
missing tests against today's `LibraryApp` methods, so they pin
current behaviour before anything relocates:

- a hide→**show** test: hiding forgets the panel, flips the toolbar
  label to ▶ and calls `update_idletasks`; hiding and re-showing
  each invoke the settings save (a visibility change persists
  today, and nothing else pins it); re-showing packs with the
  full recorded arguments (`side="right"`, `fill="y"`,
  `padx=(10, 0)`, `before=` the table frame — the argument a botched
  move is most likely to drop, leaving the panel squeezed to zero
  width) and redraws from the stored rows. A live test adds the
  end-to-end assertion after hide then show: the panel is mapped
  with width > 0;
- the empty-state branch;
- banner pack/pack_forget transitions;
- `_sync_distribution_toggle`;
- the *effect* of a metric change (the chart redraws for the new
  metric and settings are saved — today the handler is only called,
  in the live test, with its effect unasserted);
- bar colours and the active bar's white edge;
- two gaps that are **live tests** (they need a real Tk root, so they
  carry the live test's skip pattern and run on `windows-ui`):
  startup validation of the two settings keys (the metric fallback
  included), and canvas creation. The startup test also asserts
  the startup pack itself — `pack_info()` shows the side, fill and
  padx of §5 and no `before=`, pinning the second pack site, which
  only a real `_build` reaches. The headless form of the canvas
  test patches `Figure` and `FigureCanvasTkAgg` (`create=True` where
  the names may not exist) and asserts the Figure's arguments and
  that `mpl_connect` binds the click handler — it proves the calls;
  the real click path through the TkAgg machinery is what the live
  test adds, and `RealChartClickTests` already cover the geometry
  headlessly through an Agg canvas.

Step 3 re-points these tests at the component rather than rewriting
them.

**Step 2 — pure-logic extraction to `library_data.py`.** Move
`ChartBar` and add the Tk-free decision functions the window methods
already contain: the bar hit test (today's `next(...)` expression in
`_on_chart_click`), the click decision (metric, clicked token, current
difficulty text and query → the new difficulty and query, including
the toggle-off and Difficulty special cases), the Clear decision
(every active chart filter → the reset difficulty and the stripped
query; pin its early return — a Clear with nothing active is a
complete no-op), and the click-zone computation. The zone function
takes three theme-fed values as parameters — the values of
`theme.CHART_MIN_CLICK_FRACTION` and `theme.CHART_BAR_HEIGHT` and
the `1.25` axis multiplier — because `library_data` imports no
theme, and all three are presentation tuning of the same kind as
the bar colours. It derives each bar's y-coordinates from the bar
positions and the bar height rather than reading them back from
the drawn matplotlib bars (which would drag presentation objects
into `library_data`), and returns `axis_max` alongside the bars, so the window's
`set_xlim` and the click widths stay one source of truth. Bar colours
themselves stay in the window code for the same reason. The app calls
the new functions from the existing methods, and the tests that build
`app.ChartBar` are re-pointed at `library_data` in this step. The
decision tests join `tests/test_distribution.py`.

**Step 3 — the component move.** `distribution_panel.py` as §4
describes. Specifically:

- Move purity: the eleven methods move recognisably (a normalized
  diff, as for proposals 0001 and 0004), with renames limited to the
  seams (`self.search_var` → the constructor input, and so on) and
  the one deliberate rename, `_update_distribution_panel` →
  `show_rows`.
- The theme guard must keep covering the moved code: add
  `distribution_panel.py` to `WINDOW_SOURCES` in
  `tests/test_theme.py` and to README's styling paragraph — the
  proposal 0004 lesson, learned when the same list went stale on
  PR #89.
- The tests keep their file and their name, so the `windows-ui` CI
  pattern needs no workflow edit (Q8). `tests/test_ui_distribution.py`
  is re-pointed at the component — its fixtures build a
  `DistributionPanel` with fake inputs instead of hand-setting ~20
  attributes on a bare app, the ergonomics payoff of the split, as
  issue #92 was for the course builder. Of the three distribution
  tests in `tests/test_library_visualizer.py`: the Clear test
  re-points at the component, the matplotlib-missing fallback moves
  into `tests/test_ui_distribution.py`, and the settings round trip
  stays exactly as it is (the variables remain app-side, §5). The
  six places that patch or assign `MATPLOTLIB_AVAILABLE` (five
  `patch.object` sites in the distribution tests, one
  save-and-restore assignment in `tests/test_library_visualizer.py`)
  re-point at `distribution_panel.MATPLOTLIB_AVAILABLE`. The
  `SingleRefreshTests` stay app-side, where the batching lives:
  the click-triggered ones are rerouted through `apply_chart_filter`
  as tests of it, and the two that exercise the search debounce's
  interaction with batching remain tests of that machinery. The
  component tests assert which `(difficulty, query)` a click or
  Clear passes to the callback — and that a Clear with nothing
  active does not call it at all, pinning §5's complete no-op at
  the level where the moved code decides it.
- A wiring guard, per the existing components' pattern: a live test
  asserting the component's four variables *are* the app's variables;
  that `build_panel` actually ran (the panel widget exists — without
  this, a forgotten call leaves the component silently inert behind
  its `None` guards); that `refresh_table` reaches `show_rows`; and
  that **all seven entry points** land on the component — the toolbar
  toggle, the panel's ✕, the View checkbutton's sync, the metric
  radios, the banner's Clear button, the refresh push, and the chart
  click (whose hookup the canvas test's `mpl_connect` assertion
  covers at creation; this guard asserts the connected handler is
  the component's). The cursor nudge is asserted where it now
  lives: the app-side `apply_chart_filter` tests check that
  applying a change ends with `icursor("end")` on the search entry,
  and that a call with nothing to change neither refreshes nor
  nudges.
- Acceptance, in CI terms: the full suite green on the ubuntu jobs
  (live tests skipping there, as today) and the live tests green
  with zero skips on the `windows-ui` job. Plus a live smoke: toggle
  the panel from the toolbar, the View menu and the ✕; switch
  metrics; click a bar and click it again to toggle off; Clear from
  the banner; quit and relaunch to confirm both settings persist.

## 7. Open Questions — Resolved

All ten were answered in the panel review and accepted by the owner
on 2026-11-09 (see "Revision 1" at the top):

- **Q1. Variable ownership. Resolved: the draft's recommendation** —
  the four variables are app-created in `__init__` (with today's
  settings validation) and passed directly. Unanimous; the menu,
  radio and save bindings leave no other honest shape.
- **Q2. The rows seam. Resolved: push plus pull, simplified** —
  `show_rows(visible_rows)` for the push, and the app's `_filter_rows`
  passed directly as the pull callable (Claude's simplification: no
  wrapper, since `ignore_metric` is its first parameter). The
  rejected alternative — the app eagerly pushing both row lists —
  costs an extra filter pass on every refresh whether or not the
  chart's own filter is active; that cost is unmeasured, and the
  argument for the lazy pull is the laziness itself.
- **Q3. Applying a filter change. Resolved: the `apply_chart_filter`
  callback** (Claude, overturning the draft's context-manager
  recommendation; the owner accepted). The None-means-unchanged
  signature reproduces today's writes exactly — prototype-verified
  in review across 6 click and 3 Clear scenarios — the batching rule
  gets a single owner, and `search_entry` leaves the component
  entirely. ChatGPT-6's observation that the batching context
  manager is non-reentrant stands as a property of the app's
  existing helper, unchanged by this split; with the callback, the
  component never touches it.
- **Q4. The toolbar button. Resolved: the draft's recommendation,
  amended** — the app creates the button and hands it to
  `build_panel`, which also sets its initial label, so the label
  strings exist only in the component.
- **Q5. Construction shape. Resolved: two-phase, with the sibling
  callable** (Claude, overturning the draft's creation-line move;
  the owner accepted). Moving the table frame's creation line
  risked changing the Tab focus order, which follows widget
  creation order [INFERRED in review; the callable makes the
  question moot, so no owner check is needed]. ChatGPT-6 confirmed
  the *pack* order argument was sound; the focus order was the
  unexamined half.
- **Q6. `update_idletasks` on hide. Resolved: the panel frame's own
  call** — application-wide in Tk, so neither the root nor
  `winfo_toplevel()` is needed (Claude's simplification;
  ChatGPT-6 had found `winfo_toplevel()` sound but it is one hop
  more than necessary).
- **Q7. Staging. Resolved: the three PRs of §6, in order**
  (unanimous), with review's cautions folded into §6: the zone
  function's theme parameters, the canvas test's patching form, and
  the `ChartBar` test re-pointing settled in Step 2.
- **Q8. The test file's name. Resolved: keep
  `tests/test_ui_distribution.py`** (unanimous), with Claude's
  addition that the new tests and guards live in that file, since
  it is the only one the display-equipped CI job runs.
- **Q9. Matplotlib ownership. Resolved: the draft's
  recommendation** — the guarded import and `MATPLOTLIB_AVAILABLE`
  move into `distribution_panel.py`; all six patch sites re-point
  there. Unanimous.
- **Q10. Settings. Resolved: no change in this split** (unanimous).
  The settings/snapshot move inherits the keys as they are, and the
  README notes the two coexisting persistence patterns (§4).

---

*Written by Muse (Muse Spark). Revision 1 incorporates the
reviews of Claude (Sonnet 5.5), Grok 4.5, ChatGPT-6, and GLM 5.3
(Vibe — also the staging review signed "Mistral"); the resolutions
in §7 were accepted by the owner on 2026-11-09. Revision 2,
incorporating the §6 staging amendments from GLM 5.3's adversarial
re-check after Grok's fidelity audit confirmed Revision 1, followed
the same day. Implementation follows in the staged PRs of §6, each
linking back here.*
