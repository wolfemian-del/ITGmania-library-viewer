# Implementation Proposal: Persist the Pack / Type / Difficulty Filter Dropdowns (Issue #105)

| | |
|---|---|
| **Status** | Accepted (owner, 2026-11-10) |
| **Author** | Muse (Muse Spark 1.3) |
| **Date** | 2026-11-10 |
| **Base** | main `a5136a9` (PR #112 merged, landing the proposal template; PR #113 merged, completing proposal 0005). §2 was re-checked against main `aeafbbb` for Revision 1 (PRs #115/#116 merged in between): neither touched the settings dict or the filter machinery, and PR #116's deferred startup load leaves §4's shape unchanged. |
| **Related** | Issue #105; proposal 0003 (the settings-key precedent in proposal form); AGENTS.md Workflow (the proposal rule and the PR #102 precedent amendment) |

---

The three filter dropdowns above the table — Pack, Type, Difficulty —
forget their values on every restart and every library load, while the
column layout, the sort, the distribution metric and both dialog
geometries are all remembered. This proposal persists the three values
in the settings file, following the pattern those controls already use,
and restores each one after a load when it still exists in the new
library. The one real decision was what counts as a change worth
saving: whether a Difficulty set by clicking a chart bar, rather than
by picking from the dropdown, also becomes the remembered value. The
owner's answer is yes (§3, §7 Q2) — a clicked Difficulty is a real
filter choice, and it comes back.

## Revision 1 (2026-11-10, from the panel review)

The draft was reviewed by Grok, GLM 5.3, ChatGPT-6 and Claude
(Sonnet 5.5). Grok verified §2 claim by claim and the document's
fidelity to the 0000 template. The other three converged on, and this
revision adopts, a corrected account of the save behaviour: §3 is
rewritten so A1 is recommended on what it actually does, A2 is
described correctly (the draft's version could not have worked), the
precedent that genuinely supports A1 is cited (the Cache/Stats path
entries, not the distribution metric), and the key names change to
`filter_pack` / `filter_type` / `filter_difficulty` because the
issue's names already belong to the dropdown widgets. §4 gains the
startup branches that never reach `_loaded`; §6 gains the tests that
pin the decided behaviour end to end. §1's account of the precedent
exception is corrected, and §7 records the resolutions and the
experiment's verdict. No part of the design's scope changed: option A,
three keys, the restore rule, "Scored only" out.

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

Why a proposal at all: the draft opened by saying the owner had
chosen to run the full process on a change the PR #102 precedent
amendment excused, as a deliberate test of that exception. The review
established that the premise was wrong — the exception did not reach
this change (Claude's reading of the amendment, verified against its
text). The exception covers a design "an accepted proposal already
settled", repeated "in another component with the same contract". The
patterns the issue cited — `distribution_metric`, `sort_keys`,
column state — were never settled by an accepted proposal; the one
accepted proposal with a settings key (0003, window geometry) differs
in shape, with conditional keys and no library-dependent fallback;
and the save-trigger choice in §3 is a genuine two-design decision,
which is proposal trigger (c) alongside the keys' trigger (b). So
this proposal was required, not volunteered, and the experiment's
original question — would a proposal on an excused change earn its
effort? — does not arise here. What the exercise can still answer is
the smaller question: what does a compact proposal and its panel
review earn on a small settings change that does meet the triggers?
§7 records that verdict, cost included, so the record is usable the
next time either question comes up.

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
  other key is always written. No settings keys named for the filters
  exist; `pack_filter` and `type_filter` do occur in the repo — as
  the dropdown *widgets'* attribute names (:161-163, :287-291; the
  third widget is `diff_filter`) — which is why §3 does not use them
  as key names. `_save_settings` already accepts an optional event
  argument (`_save_settings(self, _event=None)`) and returns early
  while `self.tree is None`.
- **Every load resets all three.** `_loaded` (:943) rebuilds each
  combo's value list from the loaded rows inside
  `_batched_filter_changes()` and then sets each variable to its
  "All …" label unconditionally. Both load paths — a fresh scan and a
  snapshot restore (`load_cached_data` → `_loaded(...,
  from_cache=True)`) — pass through this block, so the restart reset
  and the reload reset are one code path. Difficulty's list is ordered
  by `difficulty_sort_key`; Pack and Type sort case-insensitively.
- **A startup does not always reach `_loaded`.** `load_cached_data`
  (:484) calls `_loaded` only on its valid-snapshot branch; its other
  four branches (snapshot missing, unreadable, invalid or outdated,
  saved for different paths) set a status, refresh, and return. After
  such a startup the table is empty and each combo's list still holds
  only its "All …" entry, until the user's first Load runs a scan
  through `_loaded`. §4 step 2 and §6 account for this: the restore
  rule lives in `_loaded` and only there, so a seeded value simply
  waits, unexamined, for the first real load.
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

## 3. The Decision: persist all three, save on picks — with capture accepted

**The headline choice is the issue's option A** — persist all three
dropdown values. The issue's alternatives stay rejected for its
reasons: B (Type only) draws an unprincipled line between identical
controls; C (an explicit "remember these" action or toggle) builds UI
machinery for something the always-visible dropdowns already make
safe; D (named presets) solves an unasked problem.

**The settings contract being set** (stated in full in §4): three new
keys, `filter_pack`, `filter_type`, `filter_difficulty`, holding the
dropdown strings verbatim, including "All …" as a normal value. The
issue suggested `pack_filter` / `type_filter` / `difficulty_filter`;
those names are already taken — they are the dropdown widgets'
attribute names (`self.pack_filter`, `self.type_filter`, and
`self.diff_filter` for the third, which does not even match). The
`filter_*` names group together in the settings file and cannot be
misread as the controls. The keys are **always written** once this
lands, like `distribution_metric` and unlike the geometry keys. The
geometries are conditional because their value can genuinely not
exist yet (the window unplaced); a dropdown always has a value, so
there is no absent state to protect, and always-written keeps the
settings file self-describing.

**How saving actually works in this app** (the review's correction,
and the ground the trigger decision stands on). `_save_settings`
writes the *whole* dict from the *live* variables, and it is called
from many places: the table's `<ButtonRelease-1>` binding (nearly
every mouse release over the table), sorting, column visibility and
reorder, the path Browse buttons, Load, the distribution panel's
visibility and metric controls, and the two dialog geometry
callbacks. The draft §3 said every existing save trigger is a user
gesture or a lifecycle point, never a raw variable write — literally
true, and the panel confirmed no variable trace saves — but the
app's real contract is broader: *all live state is snapshotted on any
of many gestures.* Any design for these keys lives inside that
contract, because the keys are read from the live variables at
whatever save happens next.

**The trigger decision, on those grounds.**

- **A1 (adopted): a dropdown pick saves immediately.** Bind
  `<<ComboboxSelected>>` on the three combos to `_save_settings`
  (which already accepts the event). This satisfies the acceptance
  line "changing a dropdown persists it without needing any other
  settings change" directly and deterministically.
- **What A1 does about chart clicks — decided, not incidental.** A
  chart-clicked Difficulty is not saved at click time, but it *is*
  written by the next save that happens for any reason, because that
  save reads the live `diff_var`. Given the table-click binding,
  "the next save" is normally seconds later. The draft presented this
  as a caveat to A1; the panel (GLM 5.3 and ChatGPT-6 independently,
  Claude confirming) showed it is the common case, and the owner has
  decided it is also the *correct* case: a clicked Difficulty is a
  real filter choice. Nothing in the UI marks it as tentative — the
  panel reads `diff_var` directly, so a clicked value and a picked
  one are the same control in the same state — and the value is
  always visible in the dropdown and reversible with one pick. If
  you click a Hard bar, click a row, and quit, Hard comes back next
  launch. That is the behaviour being adopted, and §6 pins it.
- **The precedent that supports this is the path entries, not the
  metric.** The Cache/Stats path boxes are typeable entries on the
  same variables their Browse buttons set; typing triggers only a
  status update, and the typed value reaches disk at Load or at the
  next incidental save. The app already accepts capture-by-later-save
  for visible, user-set state. The distribution metric, the draft's
  cited precedent, cannot settle this question: it has exactly one
  writer (its radio buttons), while Difficulty has two — and the
  second writer is the whole question.
- **A2 (rejected, on its corrected description).** The draft
  described A2 as "extend the write traces to call `_save_settings`
  when not batching — less new wiring". That cannot work:
  `apply_chart_filter` and `_loaded` write inside
  `_batched_filter_changes()`, whose exit only refreshes, so a
  not-batching trace would never see a chart click, a Clear, or a
  restore — exactly the writes A2 exists to catch. A working A2
  (save at the batch wrapper's exit, or an explicit save inside
  `apply_chart_filter`) is comparable wiring to A1, and what it buys
  is only immediacy for clicks — worth nothing once capture itself
  is accepted as correct. Rejected.
- **The strict design (rejected).** Storing the last *picked* value
  separately and having `_save_settings` write that instead of the
  live variable would make clicks never persist. It adds a second
  source of truth for one control, and it conflicts with acceptance
  criterion 2, which needs the load-time fallback — a fact about the
  live variable — to replace the stored value. Rejected.
- **The fallback's timing, accepted as-is.** After a load falls back
  to "All …", the stored value is corrected at the next save,
  whenever that happens. One sequence can postpone it indefinitely:
  fall back, then quit via File → Exit without ever placing a dialog
  (app exit saves only through the dialogs' geometry callbacks, which
  return early when a dialog was never opened). The disk then keeps
  the stale value, and the next launch simply falls back again — no
  error, no wrong filter applied. Criterion 2 is worded "on the next
  save", so this is within the accepted contract; §6 pins the
  sequence end to end rather than designing the laziness away.

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
   behaviour is unchanged. On the startup branches that never reach
   `_loaded` (§2), nothing runs this rule: the seeded values wait
   over the empty table, and the first real load — a scan, or a later
   restore — applies the rule then. No special case is wanted; a
   value whose library has not loaded yet has nothing to be checked
   against.
3. **Save the values.** Add the three keys to `_save_settings`'
   dict, reading the live variables; bind `<<ComboboxSelected>>` on
   the three combos to `_save_settings`. The existing
   unchanged-check makes repeat saves cost no disk write.
4. **Ordering traps, both settled by the shape above.** The restore
   cannot be validated at startup (each combo holds only its "All …"
   entry until `_loaded` rebuilds the list), which is why validation
   is the membership check in step 2 and not a startup whitelist. And
   no save can fire mid-`_loaded` under A1: the binding fires on user
   picks only, and `_loaded`'s sets are programmatic. (Under the
   corrected A2 this trap is one of several the batch-exit save would
   have to be guarded against — one more reason it lost.)

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
- "Scored only" (`scored_var`) keeps resetting (Q4: out of scope
  here, a one-line follow-up if wanted).

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
- **Seeded value survives a load-less startup:** with a saved Type in
  settings and no snapshot file (the `load_cached_data` branch that
  never reaches `_loaded`), the variable still holds the saved value
  afterwards and no fallback has run — the restore waits for the
  first real load, per §4 step 2.
- **Round trip:** with the three variables set, `_save_settings`'
  output contains the three keys with those values; the
  unchanged-write skip (`test_save_settings_skips_disk_write_when_
  unchanged`) still holds. The same test asserts the written dict's
  key set contains no search text — criterion 5's pin.
- **Save on pick:** invoking the selection handler with a variable
  set writes the new value to the settings file — headless, by
  calling the bound handler directly.
- **Capture, pinned (Q2's decided behaviour):** set `diff_var` via
  `apply_chart_filter` (the chart-click path), then invoke an
  unrelated save, and assert the written `filter_difficulty` is the
  clicked value. This is the behaviour §3 adopts; the test exists so
  it cannot silently change character later.
- **Fallback replaces the stored value on the next save:** seed a
  settings file with a Pack the library does not contain, run
  `_loaded`, invoke a save, re-read the file, and assert
  `filter_pack` is now "All packs" — criterion 2's consequence, end
  to end, not just its two halves separately.
- **Successive loads:** `_loaded` with a first library; set a
  non-default selection; `_loaded` with a second library containing
  that value → still selected; `_loaded` with a third lacking it →
  fallback. Criterion 4 as the sequence the user actually performs.
- **Live check:** one real-window startup test in the style of the
  distribution startup tests: a settings file with a saved Type and a
  valid snapshot (built with the app's own snapshot writer, so the
  `_loaded` branch is the one exercised), the app constructed and its
  first load pumped, the variable still holding the saved value and
  the table filtered by it. One selection in it is driven by keyboard
  rather than mouse, pinning that `<<ComboboxSelected>>` fires for
  arrow-key selection in the readonly combos. Placement follows
  wherever the CI blind-spot decision puts live guards of this kind;
  the headless tests above carry the weight either way.
- **Suite and docs:** full suite green under Xvfb with zero
  unexpected skips; the README's account of what the app remembers
  is updated if it enumerates the persisted controls (checked at
  implementation time). Owner's Windows smoke: set Type to a
  non-"All" value, quit, relaunch, load — restored and applied; then
  load a library missing a saved Pack — falls back to "All packs"
  with no error; click a Difficulty bar in the chart, click any row,
  quit, relaunch — the clicked Difficulty is back (§3's decided
  behaviour).

## 7. Open Questions — Resolved

- **Q1. Option A as scoped** — persist all three, always-written
  keys, restore-if-present with "All …" fallback. **Resolved: yes**
  (panel unanimous; §2 found no obstacle).
- **Q2. The save trigger.** **Resolved: A1 as §3 states it** — a
  dropdown pick saves immediately, and a chart-clicked Difficulty
  captured by any later save is correct behaviour that comes back
  next launch (owner's decision, 2026-11-10). A2 is rejected on its
  corrected description (its draft form could not have worked; its
  working form buys only immediacy for clicks), and the strict
  picked-value-only design is rejected (a second source of truth,
  and a conflict with criterion 2).
- **Q3. Key names.** **Resolved: `filter_pack`, `filter_type`,
  `filter_difficulty`** (owner, 2026-11-10, on Claude's
  recommendation) — the issue's `pack_filter` set already names the
  dropdown widgets, the third inconsistently at that.
- **Q4. `scored_only`.** **Resolved: out** (panel unanimous). #105
  stays the three dropdowns; persisting "Scored only" is a one-line
  follow-up if the owner wants it later.

**The experiment's verdict.** The exercise set out to test the
PR #102 precedent exception on its strongest-looking case, and the
review's first result is that the case was misjudged: the exception
did not apply (§1), so this proposal neither vindicates nor damages
it, and the record should not be cited either way on the exception
itself. A change that genuinely repeats an accepted proposal's
pattern, same contract and all, remains its proper test case.

What the process earned on a change that *did* meet the triggers,
for the cost of one 281-line draft, four reviews and this revision:

- The capture consequence (§3): it changed the grounds of the one
  real decision, produced the owner's Q2 ruling in its honest form,
  and added a pinning test. This is the finding that earns its place
  outright.
- The startup-branch gap (§2, §4 step 2, §6): a real behaviour the
  draft's design and test plan had silently assumed away.
- The key-name improvement (Q3): small, permanent, and exactly the
  kind of thing that is cheap now and annoying forever later.
- The A2 specification error: it sat in the rejected option, so it
  would have cost nothing this time — but a record that recommends
  against an option for a wrong reason is a trap for whoever revisits
  the decision, and it is corrected.
- The §2 correction of the preparation memos (the pinned reset test)
  is recorded with its discount: implementation would have surfaced
  it on the first test run anyway.

One pattern worth naming: the two findings that changed the design
came from the adversarial brief and the precedent brief, not from
re-verifying §2's ledger, which was accurate as far as it went. On
this evidence, a compact proposal at this size earns its effort when
a change meets trigger (b) or (c) — and the exception stands
untested, awaiting a case that actually fits it.

---

*Written by Muse (Muse Spark 1.3). Sources: issue #105 and two
preparation memos by Muse (2026-11-10); every code claim in §2 was
re-verified against main `a5136a9` for the draft, and the claims
Revision 1 adds were verified against the same base and re-checked
on main `aeafbbb`. This is the first proposal written from the 0000
template that PR #112 landed. Revision 1 incorporates the reviews of
Claude (Sonnet 5.5), Grok, GLM 5.3 and ChatGPT-6; the resolutions in
§7, including the owner's Q2 and Q3 decisions, were accepted by the
owner on 2026-11-10. Implementation follows in its own PR, branched
from main and naming this proposal.*
