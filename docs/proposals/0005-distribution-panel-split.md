# Implementation Proposal: Extract the Distribution Panel into Its Own Component

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-09 |
| **Base** | main `a94aa1b` (after PR #108; v1.1.0 tagged) |
| **Related** | The split sequence adopted after proposal 0001 (Course Builder → Advanced Search → **distribution** → settings/snapshot). Measurements in §2 are from a survey by Claude (Sonnet 5.5), 2026-11-09, re-verified against this base by the author. No dedicated issue; the implementation PRs will be the vehicles, as with proposals 0002 and 0004. |

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
  (lines 1118–1371, 244 lines): `_build_distribution_panel`,
  `_ensure_distribution_canvas`, `_set_distribution_visible`,
  `toggle_distribution_panel`, `_sync_distribution_toggle`,
  `_on_distribution_metric_changed`, `_on_chart_click`,
  `clear_chart_filter`, `_metric_filter_present`,
  `_distribution_rows`, and `_update_distribution_panel` (105 lines on
  its own). The `ChartBar` NamedTuple sits at lines 89–95. Collateral
  code outside the block: the matplotlib import (26–33), state in
  `__init__`, the toolbar button and startup pack in `_build`, the View
  menu checkbutton, two settings keys, and one call from
  `refresh_table` — roughly 55 further lines.
- [CODE] It owns 12 attributes: the variables `show_distribution_panel`
  (BooleanVar) and `distribution_metric` (StringVar) plus
  `dist_summary_var`; the widgets `dist_panel`, `dist_chart_frame`,
  `dist_banner_frame`, `dist_banner_label`; the matplotlib trio
  `dist_canvas`, `dist_fig`, `dist_ax`; and the data `_current_dist_bars`
  (the click map) and `_last_visible_rows`. A 13th, `dist_button`, is
  shared: the toolbar creates it, the panel rewrites its label (◀/▶).
  State fills in three stages — variables in `__init__`, widgets in
  `_build_distribution_panel`, the figure lazily on first draw.
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
  `button_press_event` calls `_on_chart_click`. All visibility changes
  already funnel through `_set_distribution_visible`, which sets the
  variable, packs or forgets the panel, rewrites the toolbar label,
  redraws (or calls `update_idletasks()` on hide), and saves settings.
  There is no keyboard shortcut.
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
  bare `LibraryApp`. `_on_chart_click` is heavily covered, including
  real-geometry clicks through matplotlib's Agg backend. Untested today:
  the hide path (pack_forget, the ▶ label, `update_idletasks`), the
  empty-state "No charts match" branch, startup validation of the two
  settings, canvas creation (the Figure and `mpl_connect`; only the
  matplotlib-missing path runs), banner pack/pack_forget, and
  `_sync_distribution_toggle`. Six `MATPLOTLIB_AVAILABLE` patch sites
  exist: five in the distribution tests, one in
  `tests/test_library_visualizer.py`.
- [CODE] CI coupling: the `windows-ui` job runs
  `python -m unittest discover -s tests -p test_ui_distribution.py`.
  The test file's name is load-bearing; renaming it needs a workflow
  edit, which only the owner can make (the app bot has no Workflows
  permission).

## 3. The Decision: The Component's Contract

### Option A (recommended): a standalone `DistributionPanel` component

A new module `distribution_panel.py` holds a component that owns the
panel end to end, mirroring `CourseBuilder` and `AdvancedSearch`: the
twelve attributes, the widget building, the drawing, the click and
Clear handlers, and the visibility funnel. The constructor receives the
seams below. Each seam is stated with its precedent; the ones with a
real alternative are repeated as questions in §7.

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
  the component's `update(visible_rows)` — today's
  `_update_distribution_panel` under its own name. For the pull, the
  component receives `rows_without_metric`, a callable wrapping the
  app's `_filter_rows(ignore_metric=…)` — the `selected_rows` /
  `library_rows` precedent from proposal 0001, used because
  `_filter_rows` itself serves the table as well and stays app-side.
  `_metric_filter_present` needs only the two variables and
  `library_data`, so it moves into the component as-is.
- **Filter changes out: the batching context manager, passed in.**
  A click and a Clear must change `diff_var` and `search_var`
  atomically — one refresh, not several — and that machinery
  (`_batched_filter_changes`, with its debounce cancellation) is the
  app's. The component receives the bound context manager as a
  constructor input and wraps its writes in it, exactly as today; the
  `search_entry` cursor nudge stays in the component, with the entry
  widget handed over at build time (§4). The alternative — one
  `apply_chart_filter(diff, query)` callback that absorbs the batching
  and the nudge — is Q3 in §7; it is fewer inputs but makes the app
  write `diff_var` even when a click changed only the query, a small
  behaviour delta this proposal prefers not to smuggle into a move.
- **Reporting out: a `save_settings` callable.** `_set_distribution_visible`
  and `_on_distribution_metric_changed` save settings today. The
  component receives the app's `_save_settings` as a callable input —
  the report-callable pattern from proposal 0003 (`report_geometry`).
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
`search_var`, `diff_var`, `show_var`, `metric_var`,
`rows_without_metric`, `batched_filter_changes`, `save_settings` —
eight inputs, stated here per the proposal 0001 safeguard. (For scale:
`CourseBuilder` sits at seven after two growth steps; this panel
genuinely has more contact with the app, and the contract says so
openly instead of hiding it.)

**Widget building.** The widgets cannot be built at construction time:
their parent, `content_frame`, is created later in `_build`, and the
show path packs the panel `before` the table frame. So the component
has a `build_panel(content_frame, table_frame, toolbar_button,
search_entry)` step that the app calls where `_build_distribution_panel`
is called today. It creates the panel's widgets (today's method body,
unchanged), stores those four widget-time references, and performs the
startup pack if the show variable is set — with today's arguments,
which omit `before=…`; the pack order still ends up panel-before-table
because the table frame is packed after, exactly as today. One
deliberate, behaviour-neutral change makes this possible: the table
frame's *creation* line moves above the panel build call (its pack
call does not move), so `table_frame` exists to be handed over. Frame
creation has no visual effect; no pack call changes order or
arguments. Reviewers who prefer it can instead give the component a
sibling callable — Q5 in §7.

**Visibility.** `set_visible(bool)`, `toggle()` and `sync_toggle()`
are today's three methods, moved: the toolbar button and the panel's
✕ point at `toggle`, the View checkbutton at `sync_toggle` with the
shared show variable, and `set_visible` remains the single funnel —
setting the variable, packing or forgetting, rewriting the toolbar
button's label (the button reference arrives via `build_panel`),
redrawing from the stored rows on show, calling the root's
`update_idletasks()` on hide, and invoking the `save_settings`
callable. The component reaches the root for `update_idletasks()`
through the panel frame's `winfo_toplevel()`, or takes the root as a
ninth input; the draft leaves this to Q6, with a slight preference for
`winfo_toplevel()` — the panel frame's toplevel *is* the root, and it
keeps the contract at eight.

**Updating and clicking.** `update(visible_rows)` is
`_update_distribution_panel` moved: store the rows, return early while
hidden, compute chart rows (stored rows, or the
`rows_without_metric` pull when the chart's own filter is present),
banner, summary, canvas, bars. `_on_chart_click` and
`clear_chart_filter` keep today's shape: compute the new filter values
(after §6's extraction, by calling the `library_data` decision
functions), apply them to the variables inside the
`batched_filter_changes` block, then nudge the cursor. The matplotlib
guarded import and `MATPLOTLIB_AVAILABLE` move into
`distribution_panel.py` with the canvas code; the app keeps no
matplotlib import.

**App side after the move.** Deleted from `LibraryApp`: the eleven
methods, `ChartBar` (it moves to `library_data.py` in §6's step), the
ten widget/data attribute declarations (the two variables stay — they
are inputs now), the matplotlib import block, and seven `library_data`
imports that only the panel used (the three aggregates,
`distribution_summary_stats`, `get_active_chart_filters`,
`filter_texts_match`, `replace_search_directive`). `CHART_FILTER_FIELDS`
and `parse_search_query` stay — `_filter_rows` uses both. The README's
architecture paragraphs gain a sentence for the new component, next to
the other two.

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
  of the search box and exactly one table refresh.
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
the boundary moves, so the move PR can be judged as a move.

**Step 1 — test hardening (no production code changes).** Write the
missing tests against today's `LibraryApp` methods, so they pin
current behaviour before anything relocates: the hide path
(`pack_forget`, the ▶ label, `update_idletasks`), the empty-state
branch, startup validation of both settings keys (the metric fallback
included), canvas creation with a real Figure (and that
`mpl_connect` binds the click handler), banner pack/pack_forget
transitions, and `_sync_distribution_toggle`. Step 3 re-points these
tests at the component rather than rewriting them.

**Step 2 — pure-logic extraction to `library_data.py`.** Move
`ChartBar` and add the Tk-free decision functions the window methods
already contain: the bar hit test (today's `next(...)` expression in
`_on_chart_click`), the click decision (metric, clicked token, current
difficulty text and query → the new difficulty and query, including
the toggle-off and Difficulty special cases), the Clear decision
(every active chart filter → the reset difficulty and the stripped
query), and the click-zone computation (`axis_max`, `min_click_width`,
and the clickable rule: a bar is clickable when its count is positive
or it is the active filter). The app calls them from the existing
methods; tests join `tests/test_distribution.py`. Bar colours stay in
the window code: `library_data` is theme-free, and choosing a colour
is presentation.

**Step 3 — the component move.** `distribution_panel.py` as §4
describes. Specifically:

- Move purity: the eleven methods move recognisably (a normalized
  diff, as for proposals 0001 and 0004), with renames limited to the
  seams (`self.search_var` → the constructor input, and so on).
- The theme guard must keep covering the moved code: add
  `distribution_panel.py` to `WINDOW_SOURCES` in
  `tests/test_theme.py` and to README's styling paragraph — the
  proposal 0004 lesson, learned when the same list went stale on
  PR #89.
- The tests keep their file: `tests/test_ui_distribution.py` is
  re-pointed at the component (its fixtures build a `DistributionPanel`
  with fake inputs instead of hand-setting ~20 attributes on a bare
  app — the ergonomics payoff of the split, as issue #92 was for the
  course builder), and the file keeps its name so the `windows-ui` CI
  pattern needs no workflow edit (Q8). The one distribution test in
  `tests/test_library_visualizer.py` (the matplotlib-missing fallback)
  moves into it, and the six `MATPLOTLIB_AVAILABLE` patch sites
  re-point at `distribution_panel.MATPLOTLIB_AVAILABLE`.
- A wiring guard, per the existing components' pattern: a live test
  asserting the component's four variables *are* the app's variables,
  that `refresh_table` reaches `update`, and that all three visibility
  entry points land on the component.
- Full suite green with zero skips under Xvfb, and a live smoke:
  toggle the panel from the toolbar, the View menu and the ✕; switch
  metrics; click a bar and click it again to toggle off; Clear from
  the banner; quit and relaunch to confirm both settings persist.

## 7. Open Questions for Reviewers

Each question states the draft's recommendation; reviewers are asked
to ratify or overturn it, as with proposal 0004's Q1–Q3.

- **Q1. Variable ownership.** The four variables are app-created in
  `__init__` (with today's settings validation) and passed directly
  (recommended — the 0004 A1 reasoning, and the menu/radio/save
  bindings leave no other honest shape), or the component creates the
  two panel variables and the app reads them back for the menu and
  `_save_settings`?
- **Q2. The rows seam.** Push via `update(visible_rows)` plus the
  `rows_without_metric` pull callable (recommended), or the app pushes
  both row lists (visible, and the metric-ignoring variant computed
  eagerly on every refresh — simpler contract, wasted work whenever
  the chart's own filter is inactive)?
- **Q3. Applying a filter change.** Pass the bound
  `_batched_filter_changes` context manager and keep the cursor nudge
  in the component (recommended — the moved code stays verbatim), or
  one `apply_chart_filter(diff, query)` app-side callback that absorbs
  both, accepting that `diff_var` is then written even by clicks that
  changed only the query?
- **Q4. The toolbar button.** The app creates it (it is toolbar
  furniture, built before the panel exists) and hands it to
  `build_panel`; the component sets only its label (recommended), or
  the component creates the button and the app packs it — splitting
  the toolbar's construction across two owners?
- **Q5. Construction shape.** Two-phase — constructor in `_build`
  beside the other components, `build_panel(...)` at today's call
  site, enabled by moving the table frame's creation line (not its
  pack) above that call (recommended), or a sibling callable the
  component consults when showing, leaving `_build`'s order untouched?
- **Q6. `update_idletasks` on hide.** Reach the root through the panel
  frame's `winfo_toplevel()` (slight preference — the contract stays
  at eight inputs), or pass the root as a ninth constructor input, as
  both existing components receive their parent?
- **Q7. Staging.** The three PRs of §6 in order (recommended), or
  fewer: extraction and move combined (a bigger PR whose middle state
  no test run ever sees), or the move alone with the step-1 tests
  folded into it?
- **Q8. The test file's name.** Keep `tests/test_ui_distribution.py`
  so the `windows-ui` workflow pattern is untouched (recommended), or
  rename to `tests/test_distribution_panel.py` for symmetry with the
  module and let the owner edit the workflow in the web UI?
- **Q9. Matplotlib ownership.** The guarded import and
  `MATPLOTLIB_AVAILABLE` move into `distribution_panel.py`, and all
  six patch sites re-point there (recommended), or the flag stays
  app-side and is passed in — leaving the app importing matplotlib it
  no longer uses?
- **Q10. Settings.** No change in this split: keys, validation and
  `_save_settings` stay as they are, and the settings/snapshot move
  inherits them (recommended), or should this proposal also settle
  how the panel's two keys will be represented after that move?

---

*Written by Muse (Muse Spark). Draft for review by Claude
(Sonnet 5.5), Grok 4.5, GLM 5.3 (Vibe), Mistral and ChatGPT-6;
resolutions will be recorded at the top when the owner accepts.
Implementation follows in the staged PRs of §6, each linking back
here.*
