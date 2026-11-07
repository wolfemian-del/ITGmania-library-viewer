# Implementation proposal: extract the Course Builder into `course_builder.py` (Option B)

| | |
|---|---|
| **Status** | Draft — under review (owner + Claude) |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-07 |
| **Base** | main `2b52abf` (pre-split, v1.0.0) |
| **Implementation PR** | — (to be filled in when opened) |

---

From Muse (Muse Spark), 2026-11-07, against main `2b52abf`.
Status: **PROPOSAL for review** — no code written. Reviewers: the owner (Ian) and Claude.
Decision requested: approve the design below (or amend the open questions in §10),
after which implementation proceeds as a single PR under the split ground rules.

---

## 1. Background and goal

`library_visualizer.py` (1,723 lines) is being split into components in pure-move
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

## 2. What exists today (verified on main `2b52abf`)

The Course Builder is the tail of `LibraryApp`, `library_visualizer.py:1507–1712`
(~206 lines), eight methods plus one nested function:

| Method | Lines | Notes |
|---|---|---|
| `open_course_builder` | 1507–1577 | builds the dialog; nested `_close` handles Escape |
| `add_selected_to_course` | 1579–1587 | reads the main table's selection |
| `refresh_course_queue` | 1589–1604 | rebuilds the queue tree + count line |
| `remove_course_entries` | 1606–1610 | |
| `move_course_entry` | 1612–1628 | |
| `validate_course_entries` | 1630–1648 | delegates to `validate_course_fields` |
| `export_course` | 1650–1673 | save-new flow |
| `append_course` | 1675–1712 | append flow |

State, declared in `__init__` (:224–228): `course_window`, `course_entries`,
`course_title_var`, `course_tree`, `course_count_var`.

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

- the "Build course…" toolbar button (:309) → `open_course_builder`
- `_dialog_is_open` (:580) → reads `course_window`

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
2. If the window already exists, opening **lifts** it instead of rebuilding.
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

    # open(), add_selected(), refresh_queue(), remove_entries(),
    # move_entry(), validate(), export(), append() — §5.2
```

Attribute mapping (state): `course_window → window`, `course_entries → entries`,
`course_title_var → title_var`, `course_tree → tree`, `course_count_var → count_var`.

### 5.2 Method mapping

Full, consistent renaming (the component's context makes the `course_` prefixes
redundant). Renames are part of the documented substitution set (§7), so the
purity check covers them:

| Today (on `LibraryApp`) | In `CourseBuilder` |
|---|---|
| `open_course_builder` | `open` |
| `add_selected_to_course` | `add_selected` |
| `refresh_course_queue` | `refresh_queue` |
| `remove_course_entries` | `remove_entries` |
| `move_course_entry` | `move_entry` |
| `validate_course_entries` | `validate` |
| `export_course` | `export` |
| `append_course` | `append` |
| nested `_close` | nested `_close` (unchanged) |

(If reviewers prefer keeping the original names to minimize diff noise, that is
open question Q1 in §10 — Muse's recommendation is the rename: inside
`course_builder.py`, `builder.export()` reads better than
`builder.export_course()`, and the purity protocol makes renames safe.)

### 5.3 App-side changes (`library_visualizer.py`, ~25 lines net)

1. **`__init__` declaration block** (:221–228): the five `course_*` attributes and
   their comment are replaced by one declaration with the other dialog state:
   `self.course_builder = None` — "created in _build, once the status variable
   exists". `advanced_search_window` stays as it is.
2. **Construction inside `_build`**: `self.status` is created at :284, before the
   toolbar row that holds the "Build course…" button (:309), and `_build` runs
   exactly once. The builder is constructed between the two, and the button's
   command becomes `self.course_builder.open` — no delegate method on the app.
3. **New app helper** (stays with the table code it reads):

   ```python
   def _selected_rows_for_course(self):
       """The chart rows currently selected in the main table (for the course builder)."""
       return [row for item in self.tree.selection()
               if (row := self.tree_item_rows.get(item)) is not None]
   ```

   `add_selected` then becomes: append each row from `self._selected_rows()`,
   refresh if any were added — identical semantics to today's loop.
4. **`_dialog_is_open`** (:578–584): the window tuple becomes
   `(self.advanced_search_window, self.course_builder.window if self.course_builder else None)`.
   Same `winfo_exists` logic.
5. **Import pruning**: `course_append_bytes`, `course_song_lines`,
   `format_new_course`, `validate_course_fields` are used *only* by the block
   (verified) and leave the visualizer's `library_data` import; pyflakes confirms
   nothing else goes unused. (`number` and `format_duration` stay — used widely.)

Expected sizes: visualizer 1,723 → ~1,520 lines; `course_builder.py` ~230 lines.

### 5.4 What does not move

`main()`, the toolbar layout, `_dialog_is_open`'s Advanced Search half, the
snapshot/settings code, and all of `library_data.py`. No README change: it
documents behaviour, not file layout (the code-layout note belongs to #54).

## 6. Test plan (9 existing tests touched, count stays 185)

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
| `DialogKeyBindingTests.test_open_course_builder_binds_escape` | Constructs a real `CourseBuilder` with Mock parent/status/button-factory and `selected_rows=lambda: []`; patches `course_builder.tk`/`ttk`; calls `builder.open()`; the three Escape scenarios (empty queue / No / Yes) are unchanged, with `builder.entries` set directly |
| `DialogKeyBindingTests.test_main_escape_clears_search_only_when_no_dialog_is_open` | Stays in `test_library_visualizer.py`; its fake app gets `course_builder = Mock()` with `.window` set to the open/closed/None window mocks in place of the old `course_window` attribute |

Untouched: everything else, including `test_library_data.py` (data layer),
`test_end_to_end.py` (fixtures), and `test_ui_distribution.py` (no course usage,
verified by grep).

### 6.3 Suite-level checks

185 tests before and after, run headless (1 skip) and under Xvfb (0 skips);
pyflakes clean on `library_visualizer.py`, `course_builder.py`, `theme.py`,
and the touched test files.

### 6.4 Live smoke (Xvfb, real window)

Load the #52 fixture library → Build course… → the dialog opens pre-populated
with the selected chart → add/remove/reorder → count/duration line updates →
Save new .CRS (check file contents) → Append to that .CRS (check bytes) →
Escape with a non-empty queue shows the discard prompt → reopening starts an
empty queue → closing via X destroys without a prompt (§4.5, preserved).

## 7. Purity protocol (how "no behaviour change" is proven)

B's diff cannot be eyeballed as a relocation, so purity is mechanical:

1. Extract the eight method bodies from main's `library_visualizer.py` and from
   the new `course_builder.py` (by AST, source segments).
2. Apply the documented substitution set to the *old* text:
   `self.course_window → self.window`, `self.course_entries → self.entries`,
   `self.course_title_var → self.title_var`, `self.course_tree → self.tree`,
   `self.course_count_var → self.count_var`, `self.root → self.parent`,
   `self.status → self._status`, the §5.2 method renames (definitions and call
   sites), and the `add_selected` selection loop → the `selected_rows` form.
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
   `_selected_rows_for_course`, `_dialog_is_open`, import pruning).
4. Extend `tests/test_theme.py` per §6.1.
5. Rebuild the course tests per §6.2 (`tests/test_course_builder.py`; trim the
   moved tests out of `test_library_visualizer.py`).
6. Run the purity protocol (§7); resolve any non-empty diff deliberately.
7. Suite both modes + pyflakes (§6.3); live smoke (§6.4).
8. Open the PR with the §7 report and this proposal linked; owner merges.

Estimated PR size: ~460 lines changed (module ~230 new, visualizer ~−205/+20,
tests ~200 moved/rebuilt + theme-guard edit).

## 9. Sequencing and neighbours

- **Claude's Help → About PR** (pending its usage limit) touches the menubar
  region; this move touches :1507–1712, the declaration block, `_build`, and
  `_dialog_is_open`. Ground rule is one window-file PR in flight at a time:
  serialize them (either order works; the regions do not overlap, but the rule
  is the rule).
- **Open course-builder issues** — none in flight, and all four are *easier*
  after the move lands in the new module: #47 (chart-type/Edit ambiguity
  warning), #39 (queue selection after remove), #38 (Delete shortcut, row
  tints), #25 (remember window size/position). The move should land before any
  of them is started. (§4.5's X-button observation may be worth folding into
  one of those, or its own issue — owner's call, out of scope here.)
- **Later split moves** reuse this pattern: measure the coupling, name the
  contract, extend the theme-guard tuple, rebuild that area's tests beside the
  new module.

## 10. Open questions for reviewers

- **Q1 (method names):** full rename per §5.2 (Muse recommends) vs keep the
  original `*_course*` names inside the component for a smaller substitution set.
- **Q2 (test home):** new `tests/test_course_builder.py` (Muse recommends —
  test files mirror modules) vs keep the rebuilt tests in
  `test_library_visualizer.py`.
- **Q3 (construction point):** construct inside `_build` after the status
  variable exists, button wired directly to `builder.open` (Muse recommends)
  vs construct lazily on first open behind an app-level `open_course_builder`
  delegate.
- **Q4 (theme guard):** the tuple-of-window-modules approach in §6.1 — agree it
  belongs in this PR rather than a follow-up?

---

*Prepared by Muse (Muse Spark). All line numbers, counts, and coupling
figures were measured on main `2b52abf` on 2026-11-07 and can be re-derived
with the greps and AST scans described in §2, §3, and §6.1.*
