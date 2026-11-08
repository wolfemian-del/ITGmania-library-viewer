# Implementation proposal: extract the Course Builder into `course_builder.py` (Option B)

| | |
|---|---|
| **Status** | Accepted — approved by the owner on 2026-11-07, after Claude's review (see "Revision notes") |
| **Author** | Muse (Muse Spark); revised by Claude (Sonnet 5.5) |
| **Date** | 2026-11-07 |
| **Base** | Measured on main `2b52abf` (pre-split, v1.0.0); re-verified and updated for main `7def1a4` (after #78 and #79) |
| **Implementation PR** | — (to be filled in when opened) |

---

From Muse (Muse Spark), 2026-11-07, against main `2b52abf`.
Status: **ACCEPTED** by the owner on 2026-11-07, after review by Claude. No code written yet; implementation follows in its own PR.
Decision requested: approve the design below, after which implementation proceeds as a
single PR under the split ground rules.

### Revision notes (Claude, 2026-11-07, applied at the owner's request)

Claude reviewed this proposal against main `7def1a4`; the full findings are in the PR
comment. The coupling inventory in §3 was re-run (AST scan) on both `2b52abf` and
`7def1a4` and is **identical**. What changed in this document:

1. **Stale base.** #78 (Help → About) and #79 (dialogs take focus) merged after the
   measurements. Line numbers are now given for `7def1a4`; `_dialog_is_open` has a
   third window (`about_window`) that §5.3 item 4 must keep; the block gained two
   `focus_force()` calls, now in §4 as behaviour 8; the test count is 191, not 185.
2. **One more unused import after the move: `re`** (§5.3 item 5).
3. **Method names (Q1, decided by the owner):** the shortened names, except that
   `open`, `export` and `append` become `open_dialog`, `save_new` and
   `append_to_existing`, because `export`/`append` call Python's built-in `open()` for
   file I/O and `append` sits next to `entries.append(...)` (§5.2).
4. **README:** it does describe file layout (lines 73–75), so §5.4 now calls for a short
   layout note (the owner can defer it to #54).
5. **Q2, Q3, Q4:** agreed as Muse recommended (§10).

---

## 1. Background and goal

`library_visualizer.py` (1,723 lines when measured; 1,771 on `7def1a4`) is being split into components in pure-move
PRs, one area per PR, in the agreed order: **Course Builder first**, then
Advanced Search / distribution panel (middle order still being settled between
Claude and Muse), settings/snapshot last.

The owner's deciding design principle: **maximize legibility for a hypothetical
human reviewer.** Assessed against that principle, the Course Builder is
extracted as a standalone component class (Option B) rather than a mixin
(Option A). A mixin would leave every non-course `self.` reference unresolvable
from the new file; a component's constructor states its entire outside world.
For this component that world is provably small (§3), which is what makes B
both legible and safe here. The same test must be re-run, with its own
measurements, for each later area.

## 2. What exists today (verified on main `2b52abf`; line numbers updated for `7def1a4`)

The Course Builder is the tail of `LibraryApp`, `library_visualizer.py:1553–1759` on
`7def1a4` (was 1507–1712 on `2b52abf`; ~207 lines), eight methods plus one nested
function:

| Method | Lines (`7def1a4`) | Notes |
|---|---|---|
| `open_course_builder` | 1553–1625 | builds the dialog; nested `_close` handles Escape; takes keyboard focus (#79) |
| `add_selected_to_course` | 1627–1635 | reads the main table's selection |
| `refresh_course_queue` | 1637–1652 | rebuilds the queue tree + count line |
| `remove_course_entries` | 1654–1658 | |
| `move_course_entry` | 1660–1676 | |
| `validate_course_entries` | 1678–1696 | delegates to `validate_course_fields` |
| `export_course` | 1698–1721 | save-new flow |
| `append_course` | 1723–1759 | append flow |

State, declared in `__init__` (`7def1a4`: :227 and :229–232, with `about_window` at :228
between them): `course_window`, `course_entries`, `course_title_var`, `course_tree`,
`course_count_var`.

All computation already lives in `library_data.py` (#31/#68): `course_song_lines`,
`validate_course_fields`, `format_new_course`, `course_append_bytes`, plus
`number` and `format_duration`. **The data layer does not change.**

## 3. Complete coupling inventory (measured, not estimated)

Inside the block, the references that reach outside the component's own state:

| External reference | Count | Becomes |
|---|---|---|
| `self._button(...)` (staticmethod button factory) | 6 | the injected `button_factory`, stored as `self._button` so call sites are unchanged |
| `self.status.set(...)` (in `export_course`, `append_course`) | 2 | the injected `status` StringVar, stored as `self._status` |
| `self.root` (Toplevel parent, `transient`) | 2 | the injected `parent` |
| `self.tree.selection()` + `self.tree_item_rows.get(...)` (in `add_selected_to_course` only) | 1 loop | the injected `selected_rows` callable |

Everything else in the block is the component's own: its five state attributes,
its own methods calling each other, `theme.*` constants, `tk`/`ttk` widgets,
`filedialog`/`messagebox` **always parented to the course window itself**,
`re.sub` (in `export_course`), and the `library_data` functions above.

Outside the block, exactly **two** references point in (verified by grep over
the whole repo; no menu entry, keyboard shortcut, context menu, or other module
references these methods):

- the "Build course…" toolbar button (`7def1a4`: :313; was :309) → `open_course_builder`
- `_dialog_is_open` (`7def1a4`: :588; was :580) → reads `course_window` (alongside
  `advanced_search_window` and, since #78, `about_window`)

**Constructor contract (the whole interface):**

```python
CourseBuilder(parent, status, button_factory, selected_rows)
```

- `parent`: the root window.
- `status`: the app's status `tk.StringVar` (the component only calls `.set`).
- `button_factory`: `LibraryApp._button` (a staticmethod — passed as a plain function).
- `selected_rows`: a zero-argument callable returning the main table's currently
  selected chart rows (see §5.3).

Read-back: the component exposes `window` for `_dialog_is_open` (§5.4).
If implementation finds the contract needs a fifth input, that is reported
before the PR is opened — not added silently.

## 4. Behaviours that must be preserved exactly

Read from the current code; the move changes none of these:

1. Opening the dialog **resets the queue** (`course_entries` is rebound to `[]`)
   and **pre-populates** it from the main table's current selection
   (`open_course_builder` ends by calling `add_selected_to_course`).
2. If the window already exists, opening **lifts** it and **gives it keyboard focus**
   (`focus_force()`, #79) instead of rebuilding.
3. `course_window` is **never set back to `None`** after close; liveness is
   always tested with `winfo_exists()` (both in `open_course_builder` and in
   `_dialog_is_open`). The component keeps the same convention for `window`.
4. **Escape** in the dialog runs `_close`: with a non-empty queue it asks
   "Discard course queue?" first; empty queue closes silently; either way it
   returns `"break"`.
5. Observed, and preserved: the window's **X button has no close handler**
   (`WM_DELETE_WINDOW` is never set), so closing via X destroys the window
   *without* the discard prompt that Escape shows. Whether that asymmetry is
   desirable is a separate question (noted in §9) — the move does not touch it.
6. All dialogs the component opens are parented to the course window
   (`parent=self.window` after the move).
7. Validation errors all use the single dialog title "Course problem", for both
   save-new and append (tests pin this).
8. **A newly created dialog takes keyboard focus** (`window.focus_force()` right after
   the Escape binding, #79), so Escape reaches it without a click first. Both
   `focus_force()` calls (this one and the raise-again path in item 2) must survive
   the move; two tests pin them (`test_open_course_builder_binds_escape` and
   `test_opening_a_dialog_that_is_already_open_raises_it_and_gives_it_focus`).

## 5. Target design

### 5.1 New module `course_builder.py`

Mirrors the visualizer's import pattern (including the `tkinter` try/except
fallback to `None`, which the tests rely on when patching the module's `tk`):

```python
"""The Build-a-course dialog: queue charts and save or append .CRS files.

Tk-side companion to the course helpers in library_data.py. The component
owns its dialog and queue; everything it needs from the main window arrives
through its constructor.
"""

from __future__ import annotations

import re
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

import theme
from library_data import (
    course_append_bytes,
    course_song_lines,
    format_duration,
    format_new_course,
    number,
    validate_course_fields,
)


class CourseBuilder:
    """The course-builder dialog and its chart queue.

    parent:         the main window (the dialog's parent)
    status:         the main window's status variable (set on save/append)
    button_factory: makes a themed button (LibraryApp._button)
    selected_rows:  callable returning the main table's selected chart rows
    """

    def __init__(self, parent, status, button_factory, selected_rows):
        self.parent = parent
        self._status = status
        self._button = button_factory
        self._selected_rows = selected_rows
        self.window = None
        self.entries: list[dict] = []
        self.title_var = None
        self.tree = None
        self.count_var = None

    # open_dialog(), add_selected(), refresh_queue(), remove_entries(),
    # move_entry(), validate(), save_new(), append_to_existing() — §5.2
```

Attribute mapping (state): `course_window → window`, `course_entries → entries`,
`course_title_var → title_var`, `course_tree → tree`, `course_count_var → count_var`.

### 5.2 Method mapping

Consistent renaming (the component's context makes the `course_` prefixes redundant).
Renames are part of the documented substitution set (§7), so the purity check covers
them. **Decided by the owner (Q1):** three names differ from Muse's original draft
(`open`, `export`, `append`) because they would clash with everyday Python words:
`export` and `append` call the built-in `open(path, ...)` for file I/O (on `7def1a4`:
lines 1714, 1734 and 1751), so a method named `open` beside those calls reads like the
same thing, and `append` sits next to `self.entries.append(row)` in `add_selected`.
(It would work, since a bare `open(...)` inside a method resolves to the built-in, but a
reader has to know that rule.)

| Today (on `LibraryApp`) | In `CourseBuilder` |
|---|---|
| `open_course_builder` | `open_dialog` |
| `add_selected_to_course` | `add_selected` |
| `refresh_course_queue` | `refresh_queue` |
| `remove_course_entries` | `remove_entries` |
| `move_course_entry` | `move_entry` |
| `validate_course_entries` | `validate` |
| `export_course` | `save_new` (matches the "Save new .CRS…" button) |
| `append_course` | `append_to_existing` (matches "Append to .CRS…") |
| nested `_close` | nested `_close` (unchanged) |

### 5.3 App-side changes (`library_visualizer.py`, ~25 lines net)

1. **`__init__` declaration block** (`7def1a4`: :225–232): the five `course_*` attributes
   and their comment are replaced by one declaration with the other dialog state:
   `self.course_builder = None` — "created in _build, once the status variable
   exists". `advanced_search_window` and `about_window` stay as they are.
2. **Construction inside `_build`**: `self.status` is created at :288 (`7def1a4`; was
   :284), before the toolbar row that holds the "Build course…" button (:313; was
   :309), and `_build` runs exactly once (called from `__init__`, :235). Re-verified
   on `7def1a4`: `status` is assigned only there (and as `None` in `__init__`), so the
   builder never holds a stale variable. The builder is constructed between the two,
   and the button's command becomes `self.course_builder.open_dialog` — no delegate
   method on the app.
3. **New app helper** (stays with the table code it reads):

   ```python
   def _selected_rows_for_course(self):
       """The chart rows currently selected in the main table (for the course builder)."""
       return [row for item in self.tree.selection()
               if (row := self.tree_item_rows.get(item)) is not None]
   ```

   `add_selected` then becomes: append each row from `self._selected_rows()`,
   refresh if any were added — identical semantics to today's loop.
4. **`_dialog_is_open`** (`7def1a4`: :586–591): the tuple on `7def1a4` is
   `(self.advanced_search_window, self.course_window, self.about_window)`. Only the
   middle entry changes, so it becomes
   `(self.advanced_search_window, self.course_builder.window if self.course_builder is not None else None, self.about_window)`.
   **`about_window` must stay** (#78): dropping it would make Escape in the main window
   clear the search while About is open, and the existing test
   `test_main_escape_clears_search_only_when_no_dialog_is_open` has an "About open"
   case that would fail. Same `winfo_exists` logic.
5. **Import pruning**: `course_append_bytes`, `course_song_lines`,
   `format_new_course`, `validate_course_fields` are used *only* by the block
   (verified) and leave the visualizer's `library_data` import. **So does `import re`**
   at the top of `library_visualizer.py`: its only use is `re.sub` in `export_course`
   (checked by AST scan, and by running pyflakes on a copy with the eight methods cut
   out: it flags `re` plus those four names, five in all). Pyflakes confirms nothing
   else goes unused. (`number` and `format_duration` stay — used elsewhere, at :974
   and :1041 on `7def1a4`.)

Expected sizes: visualizer 1,771 → ~1,595 lines (on `7def1a4`; the earlier ~1,520
figure was against 1,723); `course_builder.py` ~230 lines.

### 5.4 What does not move

`main()`, the toolbar layout, `_dialog_is_open`'s Advanced Search and About halves, the
snapshot/settings code, and all of `library_data.py`.

**README:** it does describe file layout (README lines 73–75 say what `theme.py` and
`library_data.py` hold, and line 63 says a test guards `library_visualizer.py` against
typed-in colors and fonts, which will also cover `course_builder.py`). The move PR
should add one or two lines naming `course_builder.py` and adjust line 63 — or the
owner can explicitly defer both to #54. Behaviour does not change, so this is
documentation tidiness, not a requirement of the move.

## 6. Test plan (10 existing tests touched; count stays 191 on `7def1a4`)

### 6.1 Theme guards — the check that changed this design

`tests/test_theme.py` reads **only** `library_visualizer.py`, and one guard
asserts every `theme` name is used *by that file*. Two names —
`FONT_COURSE_TITLE`, `FONT_ENTRY_LARGE` — are used **only** in the Course
Builder block (verified by AST scan). Without a test change, the move fails
`test_every_theme_name_is_used`, and the literal scans (hex/named colors, font
tuples) would silently stop covering the moved code.

Change (part of the move, principled: the guard's subject is "window code",
which now lives in two files): `WINDOW_SOURCE` becomes `WINDOW_SOURCES`, a
tuple of the window-module paths — `library_visualizer.py`, `course_builder.py`
— read and concatenated. Later split moves append their module to the tuple.
All 10 theme tests keep their count and assertions.

### 6.2 Course tests — rebuilt in a new `tests/test_course_builder.py`

Mirrors the module split. A `make_builder` helper builds the component the same
way today's tests fake the app (`object.__new__` + attribute injection), and
patch targets move from `app.*` to `course_builder.*`:

| Test (today, in `test_library_visualizer.py`) | Rebuilt as |
|---|---|
| `CourseBuilderValidationTests` ×7 (validate ×2, `_validate`-driven ×2, export ×2, append ×1) | Same names/assertions on a fake `CourseBuilder` (`window`, `entries`, `title_var`, `_status` injected); `patch.object(course_builder, "messagebox"/"filedialog")`; the export test takes `format_new_course`/`course_song_lines` from `library_data` directly instead of via `app.` |
| `DialogKeyBindingTests.test_open_course_builder_binds_escape` | Constructs a real `CourseBuilder` with Mock parent/status/button-factory and `selected_rows=lambda: []`; patches `course_builder.tk`/`ttk`; calls `builder.open_dialog()`; the three Escape scenarios (empty queue / No / Yes) are unchanged, with `builder.entries` set directly; **keeps the `mock_window.focus_force.assert_called_once()` assertion added by #79** |
| `DialogKeyBindingTests.test_opening_a_dialog_that_is_already_open_raises_it_and_gives_it_focus` (#79) | Has two halves in one loop (Advanced Search and Build course). The Build course half moves to `test_course_builder.py` (set `builder.window` to an existing mock, call `builder.open_dialog()`, assert `lift` and `focus_force` once and no new `Toplevel`); the Advanced Search half stays |
| `DialogKeyBindingTests.test_main_escape_clears_search_only_when_no_dialog_is_open` | Stays in `test_library_visualizer.py`; its fake app gets `course_builder = Mock()` with `.window` set to the open/closed/None window mocks in place of the old `course_window` attribute; **keeps its `about_window` cases (#78)** |

Untouched: everything else, including `test_library_data.py` (data layer),
`test_end_to_end.py` (fixtures), and `test_ui_distribution.py` (no course usage,
verified by grep).

### 6.3 Suite-level checks

191 tests before and after on `7def1a4` (re-run: Python 3.13 sandbox, OK, 1 skip), run
headless (1 skip) and under Xvfb (0 skips); pyflakes clean on `library_visualizer.py`,
`course_builder.py`, `theme.py`, and the touched test files. (Count the actual total
again at implementation time; it moves whenever another PR lands.)

### 6.4 Live smoke (Xvfb, real window)

Load the #52 fixture library → Build course… → the dialog opens pre-populated
with the selected chart → add/remove/reorder → count/duration line updates →
Save new .CRS (check file contents) → Append to that .CRS (check bytes) →
Escape with a non-empty queue shows the discard prompt → reopening starts an
empty queue → closing via X destroys without a prompt (§4.5, preserved).

## 7. Purity protocol (how "no behaviour change" is proven)

B's diff cannot be eyeballed as a relocation, so purity is mechanical:

1. Extract the eight method bodies from **current** main's `library_visualizer.py`
   (the commit the branch is cut from, not `2b52abf`: the block gained two
   `focus_force()` calls in #79, and a stale base would report them as differences or
   hide their loss) and from the new `course_builder.py` (by AST, source segments).
2. Apply the documented substitution set to the *old* text:
   `self.course_window → self.window`, `self.course_entries → self.entries`,
   `self.course_title_var → self.title_var`, `self.course_tree → self.tree`,
   `self.course_count_var → self.count_var`, `self.root → self.parent`,
   `self.status → self._status`, the §5.2 method renames (definitions and call
   sites; note the built-in `open(path, ...)` calls in `save_new` and
   `append_to_existing` are **not** renamed), and the `add_selected` selection loop →
   the `selected_rows` form.
   (`self._button` is deliberately *not* substituted — the factory is stored
   under that name, so those call sites are byte-identical.)
3. Diff. Expected result: **empty**, except the items listed in the PR body.
   Anything else in the diff is a behaviour change and must be called out —
   the report (script + output) is included in the PR.

The substitution script is run by hand during implementation; it is a
verification artifact for the PR, not shipped code.

## 8. Implementation sequence

1. Branch `refactor/extract-course-builder` off the then-current main
   (sequencing per §9).
2. Create `course_builder.py`: copy the block, apply substitutions with a
   script (not by hand), add the module docstring, class docstring, `__init__`.
3. App-side edits per §5.3 (declaration, construction + button wiring,
   `_selected_rows_for_course`, `_dialog_is_open` keeping `about_window`, import
   pruning including `re`).
4. Extend `tests/test_theme.py` per §6.1.
5. Rebuild the course tests per §6.2 (`tests/test_course_builder.py`; trim the
   moved tests out of `test_library_visualizer.py`).
6. Run the purity protocol (§7); resolve any non-empty diff deliberately.
7. Suite both modes + pyflakes (§6.3); live smoke (§6.4).
8. Open the PR with the §7 report and this proposal linked; owner merges.

Estimated PR size: ~460 lines changed (module ~230 new, visualizer ~−205/+20,
tests ~200 moved/rebuilt + theme-guard edit).

## 9. Sequencing and neighbours

- **Help → About (#78) and dialog focus (#79) have merged** (main `7def1a4`), so
  they are no longer neighbours to serialize against; their effects on this move
  are folded into §4, §5.3, §6 and §7 above. Ground rule remains one window-file PR
  in flight at a time: check the open PR list when branching.
- **Open course-builder issues** — none in flight, and all four are *easier*
  after the move lands in the new module: #47 (chart-type/Edit ambiguity
  warning), #39 (queue selection after remove), #38 (Delete shortcut, row
  tints), #25 (remember window size/position). The move should land before any
  of them is started. (§4.5's X-button observation is now its own issue, #80,
  to be done after this move; out of scope here.)
- **Later split moves** reuse this pattern: measure the coupling, name the
  contract, extend the theme-guard tuple, rebuild that area's tests beside the
  new module.

## 10. Open questions for reviewers

All four are answered; recorded here so the implementer does not reopen them.

- **Q1 (method names): decided by the owner.** The shortened names of §5.2, with
  `open_dialog`, `save_new` and `append_to_existing` in place of `open`, `export`
  and `append` (the three that clash with built-in or list vocabulary).
- **Q2 (test home): agreed.** New `tests/test_course_builder.py` (test files mirror
  modules; CI runs `unittest discover`, so it is picked up automatically).
- **Q3 (construction point): agreed.** Construct inside `_build` after the status
  variable exists, button wired directly to `builder.open_dialog`. Re-checked on
  `7def1a4`: `status` is created before the toolbar button and never reassigned.
- **Q4 (theme guard): agreed.** The tuple-of-window-modules approach in §6.1 belongs in
  this PR. Re-checked: `ast.parse` accepts the two window modules joined into one
  text even though each starts with `from __future__ import annotations`.

---

*Prepared by Muse (Muse Spark). All line numbers, counts, and coupling
figures were measured on main `2b52abf` on 2026-11-07 and can be re-derived
with the greps and AST scans described in §2, §3, and §6.1. Revised by Claude
(Sonnet 5.5) the same day: coupling counts re-run on `7def1a4` (identical), line
numbers and test count updated to `7def1a4`, and the corrections listed under
"Revision notes" applied.*
