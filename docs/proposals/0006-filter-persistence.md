# Implementation Proposal: Persist the Pack / Type / Difficulty Filter Dropdowns (Issue #105)

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-10 |
| **Base** | main `a5136a9` (PR #112 merged, landing the proposal template; PR #113 merged, completing proposal 0005) |
| **Related** | Issue #105; proposal 0003 (the settings-key precedent in proposal form); AGENTS.md Workflow (the proposal rule and the PR #102 precedent amendment) |

---

The three filter dropdowns above the table — Pack, Type, Difficulty —
forget their values on every restart and every library load, while the
column layout, the sort, the distribution metric and both dialog
geometries are all remembered. This proposal persists the three values
in the settings file, following the pattern those controls already use,
and restores each one after a load when it still exists in the new
library. The one real decision is what counts as a change worth saving:
whether a Difficulty set by clicking a chart bar, rather than by picking
from the dropdown, also becomes the remembered value. That answer
decides how the saving is wired (§3).

## 1. Background and Goal

Issue #105 asks for the dropdowns to behave like the app's other
standing controls. "Done" is the issue's acceptance criteria: a filter
set before quitting is restored and applied on the next launch's load;
a saved value missing from a newly loaded library falls back to
"All …" without error, and the fallback replaces the stored value on
the next save; changing a dropdown persists it without needing any
other settings change; same-session loads behave the same way; search
text stays session-only.

The modularity question, up front: this change creates no component
boundary, moves none, and adds no coupling across one. It adds three
keys to the app's existing settings contract, inside `LibraryApp`,
where every other persisted control already lives.

Why a proposal at all: the three keys meet proposal trigger (b) in
AGENTS.md ("persists a new settings key"), and the issue's own process
note argues the PR #102 precedent amendment excuses one, because the
change repeats the settled settings-persistence pattern. The owner has
chosen to run the full process anyway, as a deliberate test of that
exception: it has been relied on several times on the theory that a
proposal for already-settled logic would not earn its effort, and the
theory has never been checked. This proposal is written at the size
the change deserves, no larger. At acceptance, the review resolutions
will record the experiment's verdict — what, if anything, the proposal
and its review surfaced that the issue and the preparation memos had
not already settled — so future appeals to the exception can cite a
result rather than a plausibility.

## 2. Current State (measured on main `a5136a9`)

All line numbers are `library_visualizer.py` on the base above unless
stated.

- **The three variables are never seeded.** `__init__` creates
  `pack_var`, `type_var`, `diff_var` with hardcoded "All packs" /
  "All types" / "All difficulties" (:93-95). Their neighbours in the
  same block are all seeded from `self.saved_settings`: `cache_var`
  (:89), `stats_var` (:90), `column_order` (:98), `column_visibility`
  (:114), `column_widths` (:129), `sort_keys` (:137),
  `show_distribution` (:146), `distribution_metric` (:148-150, with a
  whitelist fallback), and the two dialog geometries (:249, :257).
  `scored_var` ("Scored only", :96) is unseeded in the same way — see
  Q4.
- **No filter keys exist.** `_save_settings` (:597) rebuilds the whole
  settings dict on each save — cache/stats paths, column state,
  sort keys, `show_distribution`, `distribution_metric` — and writes
  it atomically, skipping the write when nothing changed. The two
  geometry keys join the dict only when their value is not None; every
  other key is always written. A grep for `pack_filter`,
  `type_filter`, `difficulty_filter` finds nothing in the repo.
  `_save_settings` already accepts an optional event argument
  (`_save_settings(self, _event=None)`) and returns early while
  `self.tree is None`.
- **Every load resets all three.** `_loaded` (:943) rebuilds each
  combo's value list from the loaded rows inside
  `_batched_filter_changes()` and then sets each variable to its
  "All …" label unconditionally. Both load paths — a fresh scan and a
  snapshot restore (`load_cached_data` → `_loaded(...,
  from_cache=True)`) — pass through this block, so the restart reset
  and the reload reset are one code path. Difficulty's list is ordered
  by `difficulty_sort_key`; Pack and Type sort case-insensitively.
- **The variables' only write hook refreshes; it never saves.** The
  write traces (:190-191) call `_refresh_unless_batching` (:664). The
  one save-on-change precedent is the distribution metric: its handler
  in `distribution_panel.py` calls the app's `_save_settings` through
  the injected callable whenever the metric changes.
- **One other writer of `diff_var` exists.** Since proposal 0005,
  `apply_chart_filter` (:1094) writes `diff_var` (and the search text)
  when a chart bar is clicked or the banner's Clear is pressed, on the
  panel's behalf. Any save wiring keyed to variable writes will see
  those writes too — this is the fact §3's decision turns on.
- **The matcher needs no change.** `_filter_rows` (:995) already
  compares each variable against the row fields and treats the
  "All …" strings as no filter.
- **The reset is pinned by a test.** The test
  `test_loaded_batches_filter_changes_and_refreshes_once`
  (tests/test_library_visualizer.py) asserts `pack_var.set` was
  called with "All packs", and likewise for Type and Difficulty,
  after `_loaded`. (The two preparation memos for this proposal
  disagreed about whether such a pin exists; the code settles it —
  it does, and §6 accounts for it.)
- **No snapshot involvement.** This is `settings.json` only; the
  library snapshot's schema version does not move, unlike issues #48
  and #49.

Coupling inventory, in one line: the change touches `__init__`
(seeding), `_save_settings` (three keys), `_loaded` (restore instead
of reset), and the three combos' selection wiring — all inside
`library_visualizer.py`; nothing in `library_data.py`,
`distribution_panel.py`, or any other component reads or writes these
variables except `apply_chart_filter`'s write to `diff_var` above.

## 3. The Decision: persist all three, and save on dropdown picks

**The headline choice is the issue's option A** — persist all three
dropdown values. The issue's alternatives stay rejected for its
reasons: B (Type only) draws an unprincipled line between identical
controls; C (an explicit "remember these" action or toggle) builds UI
machinery for something the always-visible dropdowns already make
safe; D (named presets) solves an unasked problem.

**The settings contract being set** (stated in full in §4): three new
keys, `pack_filter`, `type_filter`, `difficulty_filter`, holding the
dropdown strings verbatim, including "All …" as a normal value. The
keys are **always written** once this lands, like `distribution_metric`
and unlike the geometry keys. The geometries are conditional because
their value can genuinely not exist yet (the window unplaced); a
dropdown always has a value, so there is no absent state to protect,
and always-written keeps the settings file self-describing.

**The close decision: what triggers a save.**

- **A1 (recommended): save on dropdown picks only.** Bind
  `<<ComboboxSelected>>` on the three combos to `_save_settings`
  (which already accepts the event). This mirrors the metric
  precedent — a user-gesture command, not a variable trace — and it
  satisfies the acceptance line "changing a dropdown persists it
  without needing any other settings change" directly. Its
  consequence, stated precisely: programmatic writes do not trigger a
  save, so a chart-clicked Difficulty is not saved at click time; but
  `_save_settings` writes *all* keys whenever any save happens, so a
  clicked Difficulty still in effect at some later, unrelated save
  would be captured then. Clicks are exploration; the dropdown is the
  standing control; A1 persists picks immediately and clicks only
  incidentally.
- **A2: save on any variable change outside a batch.** Extend the
  existing write traces to call `_save_settings` when not batching.
  Less new wiring, and "filter state persists" in its most literal
  sense — clicks and Clear persist immediately, like picks. The
  costs: transient chart exploration becomes a standing preference by
  default, and the trace must be guarded so `_loaded`'s own batched
  sets cannot fire a save mid-restore (a save fired by a reset before
  the restore would overwrite the stored value with "All …").

This is close. A2 is arguably less code; A1 is recommended because it
matches the precedent the rest of the settings file follows (every
existing save trigger is a user gesture or an explicit lifecycle
point, never a raw variable write), and because it keeps the
distinction the issue itself draws between standing preferences and
session intent. A reviewer who finds "the filter is the filter,
however it was set" more honest has a real case — that is Q2.

## 4. Recommended Design in Detail (Option A with A1)

This change does not touch a component boundary or constructor — it
is a settings key, the case the template's §4 escape hatch names — so
the design is stated in the shape that fits it. The legibility test
applied to the format: *settings.json gains three keys naming the
filter dropdowns' current values, read once at startup and rewritten
on every save* — a reader needs nothing else to understand what the
file change means.

1. **Seed at startup.** In `__init__` (:93-95), create the three
   variables from `saved_settings` under the new keys, falling back
   to the "All …" labels, each guarded by an isinstance check
   (settings.json is hand-editable; a non-string value falls back).
   No membership validation is possible here — the valid values
   depend on the library — and none is needed, per step 2.
2. **Restore on load instead of resetting.** In `_loaded`'s batched
   block, replace each unconditional `var.set(label)` with: keep the
   variable's current value if it is in the rebuilt value list, else
   set the label. One rule covers both acceptance paths — after a
   restart the current value *is* the seeded saved value; on a
   same-session reload it is the user's live selection — and `_loaded`
   never reads settings itself. The batched wrapper already
   suppresses per-variable refreshes during the rebuild, so refresh
   behaviour is unchanged.
3. **Save the values.** Add the three keys to `_save_settings`'
   dict, reading the live variables; bind `<<ComboboxSelected>>` on
   the three combos to `_save_settings`. The existing
   unchanged-check makes repeat saves cost no disk write.
4. **Ordering traps, both settled by the shape above.** The restore
   cannot be validated at startup (each combo holds only its "All …"
   entry until `_loaded` rebuilds the list), which is why validation
   is the membership check in step 2 and not a startup whitelist. And
   no save can fire mid-`_loaded` under A1: the binding fires on user
   picks only, and `_loaded`'s sets are programmatic. (Under A2 this
   trap is live and needs the batching guard — one more reason for
   A1.)

## 5. What Does Not Change

- Search text stays session-only; nothing about search persistence is
  implied by this proposal.
- The library snapshot, its schema version, and `library_data.py` are
  untouched; no cache file or Stats.xml handling changes.
- `_filter_rows`, `apply_chart_filter`, and the distribution panel
  are untouched — the panel keeps writing `diff_var` exactly as now.
- The "All …" values, the fallback semantics of every other settings
  key, and the geometry keys' conditional writing are unchanged.
- No new UI: no toggle, no menu entry, no dialog. The dropdowns
  themselves are the visible state, and the count line already shows
  a restored filter's effect.
- "Scored only" (`scored_var`) keeps resetting, unless Q4 decides
  otherwise.

## 6. Test Plan (for the implementation PR)

- **The existing pin is re-pinned, not deleted.**
  `test_loaded_batches_filter_changes_and_refreshes_once` currently
  asserts the three unconditional label sets. Under the restore rule
  its fake variables' current values are Mocks — not members of the
  rebuilt lists — so the fallback path is what it exercises; the test
  is extended (or a sibling added on the same harness) with
  value-carrying fakes to pin both branches: current value in the new
  list → no set to the label (value kept); current value absent →
  set to the label. The single-refresh assertion stays.
- **Seeding:** settings dicts carrying the three keys produce
  variables holding the saved values; a non-string saved value falls
  back to the label. Shape follows the existing settings round-trip
  test (`test_distribution_settings_round_trip`).
- **Round trip:** with the three variables set, `_save_settings`'
  output contains the three keys with those values; the
  unchanged-write skip (`test_save_settings_skips_disk_write_when_
  unchanged`) still holds.
- **Save on pick:** invoking the selection handler with a variable
  set writes the new value to the settings file — headless, by
  calling the bound handler directly.
- **Live check:** one real-window startup test in the style of the
  distribution startup tests: a settings file with a saved Type,
  the app constructed and its first load pumped, the variable still
  holding the saved value and the table filtered by it. Placement
  follows wherever the CI blind-spot decision puts live guards of
  this kind; the headless tests above carry the weight either way.
- **Suite and docs:** full suite green under Xvfb with zero
  unexpected skips; the README's account of what the app remembers
  is updated if it enumerates the persisted controls (checked at
  implementation time). Owner's Windows smoke: set Type to a
  non-"All" value, quit, relaunch, load — restored and applied; then
  load a library missing a saved Pack — falls back to "All packs"
  with no error.

## 7. Open Questions for Reviewers

- **Q1.** Option A as scoped — persist all three, always-written
  keys, restore-if-present with "All …" fallback. Recommendation:
  yes; the issue argues it and §2 found no obstacle.
- **Q2.** The save trigger: A1 (dropdown picks only, clicks persist
  only incidentally via later saves) or A2 (any change outside a
  batch, clicks included)? Recommendation: A1, for the precedent and
  the standing-vs-session distinction — flagged in §3 as the close
  one.
- **Q3.** Key names `pack_filter` / `type_filter` /
  `difficulty_filter`, as the issue suggests. Recommendation: keep.
- **Q4.** `scored_only`: fold a fourth key into this change, or keep
  #105 to the three dropdowns and leave it as a one-line follow-up?
  Recommendation: keep out — the issue names three, and widening a
  proposal mid-review is how scope creeps; the follow-up is genuinely
  one line if wanted later.

---

*Written by Muse (Muse Spark). Sources: issue #105 and two
preparation memos by Muse (2026-11-10); every code claim in §2 was
re-verified against main `a5136a9` for this draft. This is the first
proposal written from the 0000 template that PR #112 landed.*
