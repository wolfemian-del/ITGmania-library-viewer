# Implementation Proposal: Split the Settings and Snapshot Machinery out of `LibraryApp`

| | |
|---|---|
| **Status** | Accepted (owner, 2026-11-12) |
| **Author** | Muse (Muse Spark 1.3) |
| **Date** | 2026-11-12 |
| **Base** | main `d8f9207` (PR #145 merged: DPI awareness) |
| **Related** | Survey `~/workspace/settings-snapshot-survey/REPORT.md` (2026-11-10, base `bf93dbc`); proposals 0001 (Course Builder), 0004 (Advanced Search), 0005 (Distribution Panel), 0006 (filter persistence), 0007 (BPM/subtitle, schema 2 → 3); PRs #118, #124, #128, #133, #139, #141, #142, #143, #144, #145 |

---

This is the last item in the split sequence agreed after proposal 0001: Course Builder, Advanced Search, and the Distribution Panel are all separate components now, and the settings/snapshot machinery is the only piece of `LibraryApp` never split. The proposal moves it out as **two** small components that own files and nothing else — a `SnapshotStore` for `library_cache.json` and a persist-only `SettingsStore` for `settings.json` — staged across two PRs, SnapshotStore first. Nothing the owner sees changes: same settings file, same snapshot format, same status messages, same 14 save triggers. The one real decision is whether two file-owning components are worth it when neither owns any widgets, and this proposal says yes — for the snapshot half unambiguously, for the settings half on the narrower ground that its dedup-and-write mechanics become testable without Tk fakes.

## Revision 1 (2026-11-12, owner's decisions)

The owner accepted all seven of §7's recommendations on 2026-11-12. No design text changes: §3 is retitled The Decisions and §7 is retitled Resolved, recording the outcomes. On Q1 he added that it is a good example of future legibility being worth some more work up front — the standing guideline (legibility for a hypothetical human reviewer outranks saving effort) applied to the split itself.

## 1. Background and Goal

Every previous split began as a survey, and this one has its survey already: the overnight survey of 2026-11-10 measured the machinery at ≈277 lines / ~22% of `library_visualizer.py`, inventoried 13 settings keys and 14 save triggers, and sketched four candidate designs with eight open questions (Q1–Q8). This proposal answers the survey's questions against the code as it stands today, and re-measures everything the survey counted, because the code has moved since: the schema bump, the encoding fixes, and the Subtitle column all landed in between — and since the draft's first version, the status-message work (#141), the moved-folders note (#142), the UI redesign (#143), the load-progress readout (#144), and DPI awareness (#145).

The modularity question up front: this change creates two new component boundaries and two constructor contracts, and it gives the snapshot file format a named owner. It does not add a feature, a settings key, or a widget. "Done" means `LibraryApp` no longer contains any file IO for `settings.json` or `library_cache.json` — it assembles a settings dict and hands it to a store, and it hands scan results to a store and maps the store's answer onto the status line — with the full test suite green and the behaviour pinned branch-for-branch before anything moves.

**Why a proposal at all.** This hits all three of the proposal-rule triggers in the repo AGENTS.md [CODE]: (a) it creates component boundaries and constructor contracts; (b) it persists a file format — the snapshot schema (now version 3) gains a named owner and its constant moves module; (c) there are two or more defensible designs where the choice constrains later work (one component vs two; assemble vs persist-only; `library_data.py` vs a new module).

## 2. Current State (measured on main `d8f9207`)

All counts below were re-taken on the base above with `grep`/AST, not carried over from the survey or from the draft's first version [RAN]. Line numbers are `library_visualizer.py` at `d8f9207` unless stated.

### 2.1 Shape of the machinery

`library_visualizer.py` is 1,647 lines [RAN] (1,303 at the draft's first base). The settings/snapshot core sits in one contiguous block, lines 508–820 (313 lines), plus the seeding region in `__init__` and glue in `_build`/`_close_app`. Method spans [RAN]:

| Method | Lines | Span | Role |
|---|---|---|---|
| `_settings_file_path` (static) | 508–518 | 11 | Platform config-dir resolution → `settings.json` path |
| `library_cache_path` (property) | 521–522 | 2 | `settings_path.with_name("library_cache.json")` |
| `_normalized_source_path` (static) | 525–526 | 2 | Path comparison normalizer |
| `_save_library_cache` | 528–555 | 28 | Snapshot write (atomic, §2.5) |
| `_load_initial_snapshot` | 557–575 | 19 | Deferred startup restore + generation guard; re-reports discarded settings and opens the first-run dialog |
| `load_cached_data` | 577–623 | 47 | Snapshot read + validation + delivery |
| `_nonnegative_int` (static) | 626–627 | 2 | Snapshot counter sanitizer |
| `_source_paths_changed` | 629–642 | 14 | Snapshot-related status on path edits; also syncs the dialog note |
| `_current_paths_match_loaded` | 644–660 | 17 | The match logic extracted from `_source_paths_changed` (#143) |
| `_valid_column_width` (static) | 663–668 | 6 | Saved column-width validator |
| `_valid_window_geometry` (static) | 671–693 | 23 | Shared dialog-geometry validator |
| `_valid_course_geometry` / `_valid_advanced_search_geometry` (static) | 696–698 / 701–703 | 3 + 3 | Per-dialog minimum-size wrappers |
| `_read_settings` | 705–724 | 20 | Settings read; failure recorded and reported (#141) |
| `_report_discarded_settings` | 726–746 | 21 | Status-line report when the settings file could not be read (#141) |
| `_report_moved_source_paths` | 748–779 | 32 | Status-line note when the snapshot's paths no longer exist (#142) |
| `_save_settings` | 781–820 | 40 | Dict assembly + dedup + atomic write |

Supporting state and glue outside the block [CODE]:

- `__init__` lines 106–258 (153 lines): `settings_path` computed at :120, `saved_settings` read at :124 — before `_style()`/`_build()`, before any widget or the status variable exists. The DPI scale is computed at :112–115 (`self._dpi_scale`, class default `1.0`).
- `__init__` lines 127–199 (≈73 lines): the seeding region — nearly every line consumes `saved_settings` (13 `saved_settings.get` call sites in the file: 11 in `__init__`, 2 in `_build` [RAN, grep]). It has grown one idiom since the survey: a saved order from before Subtitle existed gets Subtitle re-inserted after Title, mirroring the older Time/BPM re-insertions.
- `__init__` line 241: `self._last_saved_settings = copy.deepcopy(self.saved_settings)`; line 244: `_report_discarded_settings()` is called at the end of `__init__`, after `_build` (it needs the status variable).
- `__init__` lines 250–258: the load-progress poller is started, the progress bar is started if a snapshot file exists, and `root.after(50, self._load_initial_snapshot)` defers the restore.
- `_build` lines 312 and 321–322: the two dialog geometries validated out of `saved_settings` and handed to the components as constructor inputs (now also with `dpi_scale=self._dpi_scale`).
- `_close_app` lines 425–440: exit-path geometry capture via the components' `save_window_geometry()`.
- Outside the core block, the Data paths dialog is 136 lines of new app-side UI (#143): `open_data_paths_dialog` (1026–1079), `_set_data_paths_note` (1081–1100), `_close_data_paths_dialog` (1102–1111), `_data_paths_load` (1113–1125), `_invalid_paths_note` (1128–1137), `_maybe_show_first_run_paths_dialog` (1139–1167). The split as designed would not move any of it (§4.1).

Adding the core block (313) and the seeding region (≈73) gives **≈386 lines, about 23% of the file**, that exist to serve these two files [RAN arithmetic on the spans above]. As the survey noted, not all of it would move in any split: the seeding region is variable *creation*, which stays app-side under every candidate in §3.

### 2.2 What has changed since the survey — the settled questions

Two of the survey's open questions are settled by merges since 2026-11-10, and the draft states them as settled rather than re-asking them:

- **Survey Q7 (sequencing vs the schema bump) is settled.** `LIBRARY_CACHE_SCHEMA_VERSION = 3` [CODE, `library_visualizer.py:63`], landed via PR #128 (merged 2026-11-11; proposal 0007). The bump the survey worried about sequencing against is done, the snapshot payload now also carries `skipped_blocks` [CODE, :541], and the split happens *after* the bump rather than before it. The remaining sequencing point is the reverse: the split should name the schema's owner going forward, so the next bump has one place to land (§4).
- **Survey Q6 (the `_read_settings` UnicodeDecodeError gap) is settled — fixed, not split.** `_read_settings` now opens with `encoding="utf-8-sig"` and catches `(OSError, ValueError, RecursionError)` [CODE, :708–716]: PR #118 widened the catch to `ValueError` (which covers both `UnicodeDecodeError` and `JSONDecodeError`), PR #124 added the BOM-tolerant encoding, and PR #133 added the `RecursionError` arm. `load_cached_data` gained the same `RecursionError` arm [CODE, :585]. There is no longer a defect for the split to fold in; the split moves already-hardened code. The settings writer still leaves a partial `settings.tmp` behind on a failed dump (no `finally`-unlink, unlike the snapshot writer) [CODE, :809–818] — that asymmetry survives, and §4 recommends resolving it inside the split via the shared helper.

Two further changes since the draft's first version, both settled by merges and recorded here so reviewers do not re-litigate them:

- **Settings-read failure is no longer silent (#141).** `_read_settings` records the failure in `self._settings_read_error`, and `_report_discarded_settings` reports it on the status line ("Settings file could not be read ({reason}); using defaults."), called at the end of `__init__` and again in `_load_initial_snapshot`'s `finally`. The failure is still total (returns `{}`) — only the silence is gone (§2.3).
- **The UI redesign (#143) settled the paths-UI questions outside the survey's scope** (one modal dialog, title "Where is your library?", fixed 560×260, no geometry key, Load-opens-dialog) and reworded the four snapshot branch texts (§2.5). It did not change the machinery's shape: the same file, the same five branches, the same 14 triggers.

The third framing fact from the survey still holds and matters more now: **this is the last big architecture item.** The Course Builder (proposal 0001), Advanced Search (proposal 0004), and Distribution Panel (proposal 0005) splits are all done. Nothing else in `LibraryApp` is of this size waiting for the same treatment [INFERRED from the survey's sequence and the current file].

### 2.3 The settings read and write paths (re-verified)

`_read_settings` (:705) is twenty lines: open with `encoding="utf-8-sig"`, `json.load`, return the dict if it is one, else raise `ValueError("settings must be a JSON object")`; `FileNotFoundError` returns `{}` silently (first run); any `OSError`/`ValueError`/`RecursionError` records `self._settings_read_error = str(exc)` and returns `{}`. One caller, `__init__` (:124) [CODE]. Its result is kept as `self.saved_settings` and consumed during construction only — after `__init__`/`_build`, nothing reads `saved_settings` again [CODE, grep: all 13 `.get` sites are at lines 127–199 and 312/321]. Failure is still total, by necessity: no status variable exists yet at :124 [CODE/INFERRED] — but it is no longer silent, because `_report_discarded_settings` runs after `_build` (:244) and again in `_load_initial_snapshot`'s `finally` (:572).

`_save_settings(self, _event=None)` (:781) still does three jobs in 40 lines: assemble the dict from live app state, dedup against `self._last_saved_settings`, write atomically (`settings.tmp`, `mkdir`, `json.dump(..., indent=2)`, `os.replace`) [CODE]. The load-bearing details the survey found are all still true [CODE]: the `tree is None` early return (:782–783) guards construction order; the `copy.deepcopy` of the assembled dict (:818) is load-bearing because the live `column_order` list is mutated in place by the drag handler; the dedup baseline starts as the raw file dict (:241), so the first gesture of a session performs one write that also garbage-collects obsolete keys; `OSError` on write is reported via `self.status.set(...)` (:819–820). One new detail: the `column_widths` entry now divides the live tree widths by the DPI factor (`scale_pixels(..., 1.0 / self._dpi_scale)`, :790–791, #145), so the stored value stays in canonical 100% units — the assembly contract is unchanged in shape, only the tree read is now an explicit physical→canonical conversion (§2.4).

### 2.4 The settings keys — unchanged at 13

11 always written, 2 conditional [CODE, :784–804 and the seeding region]. The table is identical to the survey's: `cache_dir`, `stats_file`, `column_order`, `column_visibility`, `column_widths`, `sort_keys`, `show_distribution`, `distribution_metric`, `filter_pack`, `filter_type`, `filter_difficulty`, plus conditional `course_geometry` and `advanced_search_geometry`. No new key has accreted since the survey; the Subtitle column arrived as a header, not a key, and the Data paths dialog (#143) adds none — its geometry is fixed, with no key [CODE]. Two details re-verified [CODE]:

- Seeding still validates defensively at seed time, each key in its own idiom, with no shared "parse a saved value" helper. The geometry *parser* the validators use, `parse_course_geometry`, already lives in `library_data.py` (:438–460) — the pure-logic module.
- `column_widths` is still the one key whose saved value is not sourced from app state: `_save_settings` re-reads the widths live from the `tree` widget (:791), now divided by the DPI factor so the stored value stays canonical. The startup-validated `self.column_widths` dict is used by `_build` and then never read again. This remains the settings half's hardest coupling (§2.7).

The settings default for `cache_dir` now comes from `first_existing_directory(cache_dir_candidates())` [CODE, :125] (PR #136, issue #21) — the per-platform defaults live in `library_data.py`, which is where a store's path derivation would also sit.

### 2.5 The snapshot machinery (re-verified)

**Write side.** `_save_library_cache` (:528) assembles the payload — `schema_version`, `cache_dir`, `stats_file`, `refreshed_at`, `files`, `skipped_files`, `files_without_charts`, `skipped_blocks`, `nested_song_tree`, `rows` — and writes it atomically with a per-process-and-thread unique temp name, compact JSON (`separators=(",", ":")`, `ensure_ascii=False`), `os.replace`, and a `finally`-unlink [CODE]. Sole caller is `_load_worker` (:1239), under `self._snapshot_lock` after re-checking the generation, so a superseded scan can neither write its snapshot nor deliver its rows [CODE]. Write failures are caught in the worker, not the writer [CODE].

**Read side.** `_load_initial_snapshot` (:557) runs once, 50 ms after construction, and returns untouched if the user pressed Load / refresh inside the window [CODE]; its `finally` re-reports discarded settings and opens the first-run dialog when the paths are not yet usable. `load_cached_data` (:577) still has the same five branches [CODE], with the texts reworded by #143: missing → "No saved library yet. Choose File → Data paths…, then Load / refresh."; unreadable (`OSError`/`ValueError`/`RecursionError`) → "Saved library snapshot could not be read ({exc}). Click Load / refresh to rebuild it."; invalid/outdated (rows shape, `schema_version != 3`, paths not strings) → "Saved library snapshot is invalid or outdated. Click Load / refresh to rebuild it."; different paths → "Saved library snapshot is for different data paths. Click Load / refresh to rebuild it."; valid → `_loaded(..., from_cache=True, source_paths=(…))` with counters sanitized by `_nonnegative_int`, followed by a `_report_moved_source_paths(...)` call (:622, #142). Nobody else in the repo reads or writes `library_cache.json` [RAN, grep]; `library_data.py` does not know the file exists — its `parse_cache_file` reads ITGmania's own per-song cache files, a different thing with a similar name [CODE].

One traffic change from #144, not a snapshot change: the worker now also queues `("progress", …)` and `("phase", …)` messages (the "Saving snapshot…" phase is queued inside the lock, before the write), and `_poll_load_results` dispatches four queue kinds instead of two. The write itself is untouched.

### 2.6 Every save trigger, re-counted: still 14

`_save_settings` is reached from 14 distinct trigger points [RAN, grep] — the same count as the survey, with line numbers moved:

| # | Site | Gesture / lifecycle point |
|---|---|---|
| 1 | `choose_cache` :1016 | Cache folder picked in the Browse dialog |
| 2 | `choose_stats` :1024 | Stats.xml picked in the Browse dialog |
| 3 | `load_data` :1176 | Load / refresh pressed — saves paths *before* the scan starts |
| 4 | `sort_by` :1580 | Any sort change |
| 5 | tree `<ButtonRelease-1>` binding :404 | **Every mouse release over the table** — the catch-all |
| 6 | `_column_drag_end` :958 | A heading drag that actually reordered a column |
| 7 | `_column_visibility_changed` :896 | A Columns-menu column check toggled |
| 8 | `_group_visibility_changed` :917 | A Columns-menu group check toggled |
| 9 | `reset_column_layout` :928 | View → Reset column layout |
| 10 | filter combos' `<<ComboboxSelected>>` binding :358 | A Pack/Type/Difficulty pick (proposal 0006) |
| 11 | `_course_geometry_changed` :445 | Course Builder's `report_geometry` callback |
| 12 | `_advanced_search_geometry_changed` :450 | Advanced Search's `report_geometry` callback |
| 13 | `DistributionPanel.set_visible` (panel :214) | Panel shown/hidden, via the injected `save_settings` callable (:302) |
| 14 | `DistributionPanel._on_distribution_metric_changed` (panel :225) | A metric radio picked, via the same callable |

The survey's structural points all still hold [CODE/INFERRED]: the method is idempotent-by-dedup, which is what makes the catch-all trigger (#5) affordable; no trigger passes state — every call is "save whatever is live now"; there is no partial-save API and no caller that wants one. Two nuances from #143: `choose_cache`/`choose_stats` are now invoked from the dialog's path rows, but the methods and their saves are unchanged; and `load_data` now opens the dialog and returns early when the paths are invalid, so the save in #3 happens only on the valid-paths path, where it still precedes the scan.

### 2.7 Coupling inventory — what fights a boundary

The survey's §3 inventory re-verified against the current code [CODE unless noted]:

1. **Dict assembly reads a live widget.** `column_widths` comes from `self.tree.column(...)` at save time (§2.4), now divided by the DPI factor. Any boundary either leaves assembly app-side or imports the tree / a widths callable into the contract — and a widths callable would now need the factor too [INFERRED].
2. **The other 12 assembly sources are all app-owned Tk state.** Two path variables, the live `column_order` list, a dict of BooleanVars, `sort_keys`, two panel variables, three filter variables, two plain geometry attributes. A component that assembles the dict needs all 13 — wider than the Distribution Panel's 8-input contract, with none of the panel's widget ownership to show for it.
3. **Dedup compares against two different baselines over the app's life.** Raw file dict at startup (:241), assembled dict thereafter. Moving dedup into a component means the component must be seeded with the raw loaded dict *and* own the transition — currently invisible because both sides live in one class [INFERRED].
4. **The two writers share a pattern but not an implementation.** Settings and snapshot both do mkdir → temp file → `json.dump` → `os.replace`, and differ in temp naming (fixed `settings.tmp` vs pid/thread-unique), formatting (indented vs compact, `ensure_ascii=False`), cleanup (none vs `finally`-unlink), error handling (caught-and-status vs raised-to-caller), and threading (main thread only vs worker thread under a lock). Each difference is deliberate except the missing cleanup, which is litter, not corruption [INFERRED].
5. **Status ownership.** Both failure paths report through the app's `status` variable: settings write errors (:819), all four snapshot read branches (§2.5), plus `_source_paths_changed` (:629) re-deriving a snapshot-related status on path edits — and since the draft's first version, two more reporters: `_report_discarded_settings` (:726, #141) and `_report_moved_source_paths` (:748, #142), plus the three `_DATA_PATHS_*` note constants (:99–103) and `_source_paths_changed`'s dialog-note sync (:641–642). The snapshot branch texts are user-facing copy with tests behind them.
6. **The geometry quasi-boundary already exists — and it is the template.** `course_geometry`/`advanced_search_geometry` are app attributes with a full protocol: validated out of `saved_settings` in `_build`, passed to components as `saved_geometry`, mutated only via `report_geometry` callbacks that immediately save, captured on exit through `_close_app` → `save_window_geometry()` [CODE, :312/:321–322, :425–440, :445/:450]. The protocol now also carries a scale factor (#145): both dialogs take `dpi_scale=1.0`, `_geometry_for_open` scales the saved string *and* the 100/32/16 visibility thresholds, and `save_window_geometry` divides back before storing.
7. **Construction order is load-bearing.** Settings are read before widgets exist (:124), seeded during `__init__`, geometries read again in `_build`. The boundary would sit *below* the seeding region, not replace it [INFERRED]. One addition: `_report_discarded_settings` must run after `_build` (:244), because it needs the status variable.
8. **The snapshot's delivery is the app's busiest method.** Branch 5 delivers into `_loaded` — the same funnel a fresh scan uses, with `from_cache` switching its status text. A store cannot own branch 5 end-to-end without calling back into `_loaded` or duplicating the delivery [INFERRED].
9. **The worker thread + lock stay entangled with scanning.** `_snapshot_lock` and `_load_generation` belong to the scan lifecycle. The snapshot write is one step inside `_load_worker`'s guarded section; extracting the writer without the lock discipline would reintroduce the older-scan-overwrites-newer race pinned by `test_older_scan_cannot_overwrite_newer_snapshot` [CODE]. The worker's traffic grew (#144: progress/phase messages, each stale-checked), but the lock and generation re-check around the write are identical.
10. **The test harness tax has grown.** `tests/test_library_visualizer.py` now holds 139 test methods (92 at the draft's first base) [RAN], in 2,752 lines. 59 exercise this machinery by name and subject [RAN, grep + class listing]: `CourseGeometryAppTests` (8), `AdvancedSearchGeometryAppTests` (5), `LibrarySnapshotTests` (19), `FilterPersistenceTests` (9), `InitialSnapshotTests` (3), `LiveStartupSnapshotTests` (2), `LiveFilterPersistenceTests` (4), `PerformanceAndExportTests` (5, the dedup pair), `LibraryAppExitTests` (4), plus the seeded-survives test — and 32 more in the new machinery classes: `DiscardedSettingsStatusTests` (10), `LiveDiscardedSettingsTests` (3), `DataPathsPopupTests` (6), `LiveDataPathsDialogTests` (9), `InvalidPathsNoteTests` (4). Counting the load-machinery classes as well, 121 of the 139 tests sit in classes touching this machinery. The headless harnesses build `LibraryApp` via `object.__new__` and hand-populate exactly the attributes `_save_settings` reads. Five line references in tests touch `app.LIBRARY_CACHE_SCHEMA_VERSION` directly [CODE, `tests/test_library_visualizer.py:462,1411,1450,1495,1559`].

One new coupling note since the survey: the theme guard in `tests/test_theme.py` lists the window-code modules (`library_visualizer.py`, `course_builder.py`, `row_tints.py`, `advanced_search.py`, `distribution_panel.py`) with the comment "a split move adds its module here" [CODE]. Where the new components live decides whether that list changes (§3, Q4).

## 3. The Decisions (owner's, 2026-11-12)

**Decided on Q1 (is there a component here at all?): yes — two of them.** Not the no-split option (d), and not on the survey's weakest ground. The case splits by half, and the proposal does not pretend otherwise:

- **The snapshot half is a real component, unambiguously.** It owns a file *format* with a versioned schema, a five-branch read vocabulary, and an atomic write with threading constraints — the kind of thing that has exactly one correct owner, and today has none: the schema constant sits in the window file at :63, the validation lives in a 47-line app method, and the next schema bump would again be edited across the app's read, write, and tests. It also passes the repo's own placement rule without contortion: nothing in it needs the window, so it belongs in `library_data.py` (AGENTS.md: "Keep logic that does not need the window in library_data.py"), where `parse_cache_file` and `cache_dir_candidates()` already live — and since the draft's first version, the pure geometry helpers a store would use (`dpi_scale_factor`, `scale_pixels`, `format_geometry`, `scale_geometry`) have joined them there (#145), which strengthens the placement argument. A reader can state it in one sentence (see §4), and its tests need no Tk fakes at all — a real gain, since the snapshot tests today run through `object.__new__` app husks.
- **The settings half is a real component on narrower ground: persist-only.** The survey is right that a store which only loads a dict, dedups, and writes atomically is ~40 lines and leaves the 13-source assembly exactly as coupled as today. The proposal recommends it anyway, for three concrete reasons: (1) the dedup-baseline transition (§2.7.3) is currently invisible and is the subtlest contract in the machinery — making `load()` seed the baseline turns it into an explicit, testable contract; (2) the settings half becomes testable without the fake-harness tax that PR #117 paid (six fakes grew three variables when the dict grew); (3) it gives the shared atomic-write helper a second caller, which is what justifies extracting it (§4). What it is *not* is an assembly component: the 13-source gather, headed by the live-tree `column_widths` read, stays app-side. An assembling settings component would be a wider constructor contract than the Distribution Panel's with no widget ownership to justify it — the survey's Q2, answered persist-only.

**Decided on Q3 (one component or two?): two.** A combined `Persistence` component fails the legibility test the owner applies: its one-sentence description would be "the thing that reads and writes files," which describes a drawer, not a boundary. The two files share a directory and a write pattern and almost nothing else — different writers (any gesture on the main thread vs one worker thread under a lock), different readers, different failure vocabularies, different change rhythms (keys accrete per feature; the schema bumps per format change). The only genuinely shared piece is the atomic-write pattern, and that becomes one shared module-level helper the two components both call — shared code, not a shared component. Two components also stage cleanly: the snapshot half first (bigger win, no Tk anywhere near it), the settings half second.

**Alternatives considered and not recommended:**

- **(d) No split, cleanups only.** The cleanups are real — the atomic-write helper, the validators moving next to `parse_course_geometry` — but they leave the schema without an owner and the dedup contract invisible, and the next settings key repeats the 13-source assembly edit and the fake-harness tax. The cost of the split is two small, reviewable PRs; the cost of not splitting is paid on every future key and every future schema bump. Close, but not the recommendation.
- **(c) One combined component.** Saves one class and one constructor, costs the boundary its statability. Rejected on legibility, per above.
- **Settings assembly inside the component.** Would move the 13-source gather plus a live-tree read across the boundary — the widest contract in the codebase, for no widget ownership. Rejected; assembly stays app-side (§4).

## 4. Recommended Design in Detail (Option: two components, staged)

### 4.1 The boundary, stated

- **`SnapshotStore` (in `library_data.py`) owns `library_cache.json`.** It owns the schema constant, the payload shape, the atomic write, and the five-branch read validation. It never touches Tk, the app, or the status line.
- **`SettingsStore` (in `library_data.py`) owns `settings.json`.** It owns loading the last saved dict, the dedup baseline, and the atomic write. It never assembles a dict, never reads a widget, never touches the status line.
- **The app keeps:** all seeding/validation in `__init__`/`_build` (unchanged), dict assembly in `_save_settings` (now a thin assemble-and-delegate), all 14 triggers (unchanged — they still call the app's `_save_settings`), the `_load_initial_snapshot` generation guard, delivery into `_loaded`, all status copy (including the #141 discarded-settings report and the #142 moved-folders note), the worker's lock discipline, the geometry protocol (§4.5), and the Data paths dialog with its note constants and first-run/modal behaviour (§2.1).
- **Shared:** one module-level atomic-write helper in `library_data.py`, used by both stores. It takes the snapshot writer's shape — pid/thread-unique temp name, `finally`-unlink — for both files, which also resolves the settings writer's litter asymmetry (§2.2) with no user-visible change [INFERRED: the temp file is never read].

### 4.2 Legibility test

- SnapshotStore: *"It writes a scan's rows to the library snapshot under the current schema version, and reads one back — returning the rows, or the reason it could not."*
- SettingsStore: *"It loads the last saved settings dict, and saves a new one only when it differs, writing atomically."*

Both sentences state what the component does and what it is given without holding the rest of the file in mind. The combined component's sentence — "it does file IO" — does not, which is the §3 argument against it in one line.

### 4.3 `SnapshotStore` — constructor contract

```python
class SnapshotStore:
    def __init__(self, snapshot_path, headers, schema_version=LIBRARY_CACHE_SCHEMA_VERSION): ...
    def write(self, cache_dir, stats_file, rows, files, skipped_files,
              files_without_charts, skipped_blocks, nested_song_tree) -> str: ...
              # returns refreshed_at; raises OSError/TypeError/ValueError exactly as today
    def read(self, current_cache_dir, current_stats_file) -> SnapshotResult: ...
```

- **Inputs (3):** the snapshot path (derived once in the app from the settings path, as today — the path coupling stays where it is), the `HEADERS` tuple for row validation, the schema version (defaulting to the constant, so a future bump is one edit). No Tk, no status, no callbacks into the app for the read itself.
- **`SnapshotResult`** is a small value the app and tests share: either *loaded* (rows, counters, `refreshed_at`, source paths) or *not loaded* with a reason kind (`missing` / `unreadable` / `invalid` / `paths_mismatch`). The app maps each reason kind to today's status text and calls `refresh_table()` — the copy stays app-side, verbatim, so the user-facing strings do not move (§4.6).
- **Moves:** `library_cache_path` (2 lines), `_save_library_cache` (28), the IO + validation of `load_cached_data` (~35 of 47), `_nonnegative_int` (2), and `LIBRARY_CACHE_SCHEMA_VERSION` itself (≈68 lines + the constant). **Stays:** `_load_initial_snapshot` and the generation guard, delivery into `_loaded`, the status copy, and the worker's lock — the worker calls `store.write(...)` inside the same locked, generation-checked section, so the older-scan race stays pinned by the same test.
- **The schema constant moves with the store** into `library_data.py`, and `library_visualizer.py` imports it, so `app.LIBRARY_CACHE_SCHEMA_VERSION` keeps working and the five test sites that reference it need no change [CODE, §2.7.10]. Proposal 0007's text still says version 2 in its history; it is a record of the decision at the time and is left alone.

### 4.4 `SettingsStore` — constructor contract

```python
class SettingsStore:
    def __init__(self, settings_path): ...
    def load(self) -> dict: ...        # _read_settings as it stands (utf-8-sig, ValueError/RecursionError arms)
    def save(self, settings: dict) -> None: ...
            # dedup + atomic write; raises OSError exactly as today
```

- **Inputs (1):** the settings path. One input, no Tk, no status.
- **The dedup baseline is seeded by `load()`:** the app's `__init__` does `store = SettingsStore(path); saved = store.load()`, and the store keeps the loaded dict as its baseline — the raw-file-vs-assembled transition (§2.7.3) becomes an explicit contract instead of two lines 110 lines apart. The `copy.deepcopy` on save stays, for the same in-place-mutation reason [CODE, §2.3].
- **Error reporting:** `save()` raises `OSError`; the app's thin `_save_settings` catches it and sets the status, exactly as today. The store never receives the status variable — it has no Tk to report through, and the Course Builder precedent (component receives `status`) does not apply to a component that owns no window. The `load()` failure recording (`_settings_read_error`) moves with the store; the app keeps the reporting (`_report_discarded_settings`), which needs the status variable and stays app-side.
- **Moves:** `_settings_file_path` (11), `_read_settings` (20), the write half of `_save_settings` (~20 of 40), and the `_last_saved_settings` attribute (≈51 lines). **Stays:** dict assembly (all 13 sources, including the live-tree `column_widths` read), all seeding/validation, all 14 triggers, and the `tree is None` guard — which lives in the app's thin `_save_settings` before assembly, where the construction-order knowledge already sits.
- **The pure validators move too, as a cleanup inside this stage:** `_valid_column_width`, `_valid_window_geometry`, and the two per-dialog wrappers are pure functions whose parser already lives in `library_data.py`; they move there alongside the store. The geometry *protocol* does not move (§4.5) — only the validators.

### 4.5 The geometry keys keep their special protocol (survey Q4)

`course_geometry` / `advanced_search_geometry` stay exactly as they are: conditional keys, attribute-mediated, validated in `_build`, passed as `saved_geometry`, mutated only via `report_geometry` callbacks that immediately save, captured on exit through `_close_app` → `save_window_geometry()` [CODE, §2.7.6]. The protocol now also carries the DPI scale factor through the dialogs (#145), and that stays as it is — the store just persists whatever dict the app assembles, conditional keys included. The protocol is an accepted pattern from proposals 0001/0004, and the standing rule is that accepted patterns are not departed from silently. Regularizing the geometry keys into the general store would invent a key for a never-placed window — the constraint the protocol exists to enforce.

### 4.6 Status copy stays app-side (survey Q5)

The four snapshot branch texts, the settings-save error, the discarded-settings report, and `_source_paths_changed` all stay in `LibraryApp` [CODE, §2.7.5]. The components return reason kinds and raise errors; the app turns them into messages. Rationale: both components live in `library_data.py` with no Tk, and the snapshot texts are user-facing copy with tests behind them — moving them would move the copy into a module that cannot display it and split the tests that pin it.

### 4.7 Staging

Two PRs, in this order, each independently reviewable and mergeable:

- **PR 1 — `SnapshotStore` + the shared atomic-write helper.** Moves the snapshot machinery and the schema constant; introduces the helper with the snapshot writer's temp-naming and cleanup; re-points the snapshot tests at the store (new `tests/test_snapshot_store.py`, headless, tmp paths). The settings writer keeps its own inline write in this PR — it switches to the helper in PR 2, so PR 1's diff contains no settings behaviour at all.
- **PR 2 — `SettingsStore` + the validators move.** Moves the settings load/dedup/write and the four pure validators; the settings writer switches to the shared helper (gaining the `finally`-unlink, losing the litter); re-points the settings tests at the store (new `tests/test_settings_store.py`).

Either PR can land without the other; PR 1 first because it is the bigger win and the one with no Tk anywhere near it. No flag day, no intermediate state in which half a file is owned by two places.

## 5. What Does Not Change

- **Behaviour:** none that the owner can see. Same settings file, same snapshot format, same status messages, same 14 save triggers, same dedup contract (including the first-gesture write that garbage-collects obsolete keys), same five snapshot branches, same geometry protocol, same worker lock discipline and generation guard.
- **Formats:** the snapshot schema stays version 3; the payload keys are unchanged. The settings keys stay at 13 — no key added, removed, or renamed.
- **Neighbouring components:** Course Builder, Advanced Search, and the Distribution Panel are untouched; their `saved_geometry` / `report_geometry` / injected-`save_settings` contracts are unchanged. The app's `_save_settings` keeps its name and signature (`_event=None`) so the two bindings and the injected callable keep working.
- **File locations for the user:** `settings.json` and `library_cache.json` stay in the same config directory, derived the same way. The settings writer's temp file becomes pid/thread-unique and is cleaned up on failure — the only on-disk difference, and it is litter removal, not a format change.
- **What this proposal does not do:** it does not regularize the geometry keys, move the seeding region, add a partial-save API, change any status text, or touch the scan itself.

## 6. Test Plan (for the implementation PRs)

Pin-before-move first, then move, then re-point — the same order as the distribution split:

1. **Pin current behaviour before either PR moves code.** The existing suite already pins most of it [CODE, §2.7.10]: the five snapshot branches (`LibrarySnapshotTests`), the dedup pair (`PerformanceAndExportTests` — unchanged-skip and in-place reorder), the geometry classes, the exit capture (`LibraryAppExitTests`), the race test (`test_older_scan_cannot_overwrite_newer_snapshot`), the filter persistence classes, and the new status classes (`DiscardedSettingsStatusTests`, `LiveDiscardedSettingsTests`, `DataPathsPopupTests`, `LiveDataPathsDialogTests`, `InvalidPathsNoteTests`). Before PR 1, add a pin test for the one behaviour the shared helper changes: a failed settings dump leaves no `settings.tmp` behind (today it does — the litter asymmetry, §2.2). That test must fail on main and pass after PR 2.
2. **PR 1 — SnapshotStore.** New `tests/test_snapshot_store.py`: headless, `tmp_path`, no `object.__new__` app husks — write/read round trip, all four not-loaded reason kinds (missing, unreadable incl. invalid UTF-8, invalid incl. wrong schema version, paths mismatch), counter sanitization, and the `refreshed_at` return. Move `LibrarySnapshotTests`' component-behaviour cases into it; leave the app-wiring cases (deferral, generation guard, delivery via `_loaded`, status texts) in `test_library_visualizer.py` against the thin delegate. `tests/test_theme.py` needs no change: the store lives in `library_data.py`, which is not window code and is already outside the guard's module list [CODE, §2.7]. README: no behaviour change, so no README change; note the new owner in the module docstring instead.
3. **PR 2 — SettingsStore.** New `tests/test_settings_store.py`: headless, `tmp_path` — load of a valid dict, corrupt/missing/non-dict/BOM/deeply-nested inputs all returning `{}`, dedup skip on identical dict, save on changed dict, the deepcopy pin (mutate the passed dict after save; the next identical save must still write), and the temp-cleanup pin from step 1. Move the settings-behaviour cases out of the fake harnesses; the harnesses shrink to what the thin delegate actually needs (a `tree`, the variables, the store). The four validators move with their tests.
4. **Mutation checks, per the project's standing practice:** the dedup test must fail if the `deepcopy` is removed; the race test must fail if the worker's lock is dropped (it must not be — the lock stays app-side, but the test is the tripwire); a snapshot test must fail if the schema check is removed. Run the full suite (`python -m unittest discover -s tests`) after each PR; expectation is all green, zero skips beyond the existing headless skips.
5. **Live smoke (owner, Windows):** after each PR — start with a saved snapshot and confirm it restores; change a filter, a sort, and a column width, restart, confirm all three persist; open and move the Course Builder and Advanced Search windows, restart, confirm both geometries restore; press Load / refresh twice in quick succession and confirm the snapshot on disk is the newer scan's. These are the checks the fake harnesses cannot do.

## 7. Open Questions — Resolved

- **Q1. Two components, or no split?** Recommendation: two components, staged (§3). The snapshot half is a component on its own merits; the settings half is a component on the narrower persist-only ground. The no-split alternative (§3) is defensible and cheaper — the owner decides whether the legibility and testability gain is worth two small PRs.
  **Resolution (2026-11-12): two components, staged, as recommended.** The owner added that Q1 is a good example of future legibility being worth some more work up front.
- **Q2. One component or two?** Recommendation: two (§3). The combined component fails the one-sentence test; the only shared piece is the atomic-write helper. The owner decides — this is a naming/legibility call.
  **Resolution (2026-11-12): two, as recommended.**
- **Q3. Staging order — SnapshotStore first, then SettingsStore?** Recommendation: yes (§4.7). The snapshot half is the bigger win with no Tk in it; either order works mechanically, and the owner may prefer the settings half first if the dedup contract is what he most wants pinned.
  **Resolution (2026-11-12): SnapshotStore first, as recommended.**
- **Q4. Do both components live in `library_data.py`, or does this deserve a new module?** Recommendation: `library_data.py`. It is already the home of the pure logic (AGENTS.md), it already holds `parse_course_geometry` and `cache_dir_candidates()`, and it keeps `tests/test_theme.py`'s module list untouched. The alternative — a new `persistence.py` — is cleaner naming for ~110 lines but adds a file and a theme-guard entry for code that uses no theme values. Panel-decidable; the owner ratifies.
  **Resolution (2026-11-12): `library_data.py`, as recommended.**
- **Q5. Does the settings writer adopt the snapshot writer's temp naming and cleanup via the shared helper?** Recommendation: yes (§4.1). User-visible change: none, except a failed dump no longer litters `settings.tmp`. The owner ratifies as part of acceptance, since it is a (trivial) behaviour change.
  **Resolution (2026-11-12): yes, as recommended.**
- **Q6. Do the `object.__new__` fake harnesses get re-pointed at the components, or left exercising the thin delegates?** Recommendation: re-point the component-behaviour cases into the new headless test files and leave only the app-wiring cases on the harnesses (§6). Panel-decidable — test-plan territory.
  **Resolution (2026-11-12): re-point, as recommended.**
- **Q7. Is the schema constant's move (into `library_data.py`, re-imported by the app) the right home for the next bump?** Recommendation: yes (§4.3). The next schema change then lands in the store and its tests, not across the app. The owner ratifies; proposal 0007's historical text is left as written.
  **Resolution (2026-11-12): yes, as recommended.**

**Settled, not open — recorded here so reviewers do not re-litigate them:** the survey's Q6 (the `_read_settings` UnicodeDecodeError gap) was fixed by PRs #118/#124/#133, and the survey's Q7 (sequencing vs the schema bump) was settled by PR #128 landing the 2 → 3 bump. The survey's Q2 (assemble vs persist-only) is answered persist-only in §3; its Q4 (geometry protocol) and Q5 (status copy) are answered in §§4.5–4.6; its Q8 (harnesses) is Q6 above. Since the draft's first version: settings-read failure is now reported, not silent (#141); the snapshot branch texts were reworded and two status messages added (#141, #142); the paths UI is a modal dialog (#143); the worker queues progress/phase messages (#144); the geometry protocol carries a DPI factor (#145).

---

*Written by Muse (Muse Spark 1.3). Based on the overnight survey of 2026-11-10, re-measured on main `d8f9207` (2026-11-12, PR #145 merged); no other model reviewed this draft before filing.*
