# Implementation Proposal: Remember the Course Builder Window's Size and Position (Issue #25)

| | |
|---|---|
| **Status** | Accepted — approved by the owner on 2026-11-08, with the review resolutions below |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-08 |
| **Base** | main `c24a36d` (after PR #94) |
| **Related Issue** | #25 (Course builder: remember window size/position) |

---

## Review resolutions (2026-11-08)

Reviewed by Claude (Sonnet 5.5), Grok 4.5, and GLM 5.3 (Vibe) — all three
recommended **Option A**. The owner accepted the following resolutions,
which amend the sections noted:

- **Consensus, no amendment needed:** Q1 (both new inputs optional) and
  Q2 (save-on-close only, no crash-proofing) stand as proposed.
- **Q3 (off-screen restore) — resolved against the draft's "ignore it."**
  The failure is self-perpetuating (a lost position is re-saved on every
  close), so at restore time the saved position is checked against the
  virtual desktop; if it falls outside, only the size is applied and the
  window manager places the window (§4). Saving also never happens while
  the window is minimized or maximized (§4).
- **Q4 — the settings key is `course_geometry`.**
- **Q5 — validation is format plus a minimum-size floor:** values smaller
  than `theme.COURSE_BUILDER_MIN_SIZE` are rejected whole, position
  included (§4).
- **Validator correctness (Claude):** the format check must accept the
  strings Tk actually emits for negative offsets (e.g.
  `1000x620+-8+100`), with both literal forms in the tests (§4, §6).
- **Storage correctness (Claude):** `self.course_geometry` is initialized
  from the validated saved value in `__init__`, so an unrelated settings
  save in a session that never opens the dialog cannot drop the key; a
  test covers that (§4, §6).
- **Wiring test (Claude):** the implementation's tests assert the app
  actually passes both new inputs, so a silent omission cannot disable
  the feature while every other test stays green (§6).
- **Validator placement (GLM 5.3):** the pure parsing lives in
  `library_data.py` (`parse_course_geometry`); the app applies the
  minimum-size floor and rebuilds the canonical string (§4).
- **Issue #91 is folded into the implementation PR:** the README
  paragraph listing the component's inputs gains `library_rows` and the
  two new inputs in one edit (§4).

---

## 1. Background and Goal

The Build a course window opens at a fixed geometry every time
(`theme.COURSE_BUILDER_GEOMETRY`, currently `"1000x620"`). Issue #25 asks for
the window to remember its last size and position, persisted in
`settings.json` "the same way the main window remembers column layout,"
restored on open, with a fallback to the current defaults when the stored
value is missing or invalid. The issue also says to keep it optional: skip
it if it adds more complexity than it is worth.

Everything else about this feature is straightforward. The one real design
question — and the reason for this proposal — is **how the geometry crosses
the boundary between `LibraryApp`, which owns `settings.json`, and
`CourseBuilder`, which owns the window**. Proposal 0001 made the builder a
standalone component with an explicit constructor contract precisely so
that this boundary stays visible; #47 later grew the contract from four
inputs to five, openly, when the ambiguity check needed library-wide rows.
This proposal asks reviewers to weigh the options in §3 before any code is
written.

## 2. Current State (measured on main `c24a36d`)

- [CODE] `CourseBuilder.__init__` takes five inputs: `parent`, `status`,
  `button_factory`, `selected_rows`, `library_rows`. The two callables are
  supplied by `LibraryApp`'s private adapters (`_selected_rows_for_course`,
  `_library_rows_for_course` in `library_visualizer.py`).
- [CODE] `open_dialog` creates the window and calls
  `window.geometry(theme.COURSE_BUILDER_GEOMETRY)` then
  `window.minsize(*theme.COURSE_BUILDER_MIN_SIZE)` — `(700, 440)`.
- [CODE] Settings live in `LibraryApp`: `_read_settings()` loads
  `settings.json` once at startup into `self.saved_settings`;
  `_save_settings()` rebuilds the whole settings dict from live widget
  state (paths, column order/visibility/widths, sort keys, distribution
  preferences), skips the write when the dict is unchanged
  (`_last_saved_settings`), and writes atomically via a `.tmp` file and
  `os.replace`. There is no geometry key today, for any window.
- [CODE] Settings values that come back from disk are not trusted blindly:
  `_valid_column_width` (a `LibraryApp` static method) range-checks column
  widths read from the file, and the snapshot restore validates what it
  applies.
- [CODE] The dialog has exactly two teardown paths: its own `_close`
  (Escape and the dialog's `WM_DELETE_WINDOW`, behind the discard prompt
  from #80), and destruction of the root window through
  `LibraryApp._close_app` (#87), which asks the builder's
  `confirm_discard_for_app_exit()` first. Any other destroy path would
  have to be created deliberately.
- [CODE] The main window does **not** remember its own geometry; it opens
  at `theme.WINDOW_DEFAULT_GEOMETRY` every time. Remembering the *main*
  window's geometry is not part of issue #25 and is not proposed here.

## 3. The Decision: How Geometry Crosses the Boundary

### Option A (recommended): a saved value in, a report callable out

Grow the constructor by two inputs, both optional (default `None`):

- `saved_geometry` — the geometry string from settings, or `None`. A plain
  value, not a callable: unlike the library rows, it cannot change during
  a session except through this dialog, so a callable would be ceremony.
  The app validates it before handing it over (§4).
- `report_geometry` — a callable the builder invokes with the final
  geometry string when the dialog closes. The app stores it and routes it
  into `_save_settings()` under a new `course_geometry` key.

The component keeps owning its window end to end; the app keeps owning
the file. With both inputs `None` (as in most existing tests), the builder
behaves exactly as today.

### Option B: a callable pair, symmetric with the rows inputs

`saved_geometry()` (callable returning the string or `None`) plus the same
`report_geometry` as Option A. Perfectly consistent with
`selected_rows`/`library_rows`, but the symmetry is bought with an
indirection that can never observe a different value: settings are read
once at startup, before the builder is constructed, and nothing else
writes the key. More moving parts for no behavioural gain.

### Option C: no contract growth — the app reaches into `builder.window`

`LibraryApp` already reads `course_builder.window` (e.g. in
`_dialog_is_open`). It could apply the saved geometry to the window right
after `open_dialog` returns and bind its own handler to notice closes.
Rejected: it splits ownership of the window the component exists to own
(proposal 0001), the dialog can paint once at the default geometry before
the app moves it, the already-open early return in `open_dialog` makes
the hook-up easy to miss, and noticing "the dialog closed" from outside
means re-hooking the very protocol handler the component manages.

### Option D: the builder reads and writes `settings.json` itself

Rejected outright: the settings file, its atomic write, and its
change-detection are the app's; two writers would race `_save_settings`'s
full-dict rebuild and silently lose each other's keys.

## 4. Recommended Design in Detail (Option A)

**Restore.** In `open_dialog`, replace the fixed geometry with the saved
one when present:

```python
window.geometry(self._saved_geometry or theme.COURSE_BUILDER_GEOMETRY)
```

`minsize` is applied right after, as today, so a stale small size cannot
squeeze the dialog below `(700, 440)`.

One addition from review (Q3): before applying the saved string, its
position is checked against the virtual desktop (the window's
`winfo_vrootx/y` and `winfo_vrootwidth/height`, which span every monitor).
If the saved top-left corner falls outside it — the remembered monitor
was unplugged, say — only the `WxH` size is applied and the window
manager places the window, so the dialog can never open lost and then
re-save the same lost position on close.

**Validation.** The app validates the stored value before constructing
the builder. The pure parsing is `library_data.parse_course_geometry`,
which returns `(width, height, x, y)` or `None`: the value must be a
string in full geometry form, and the pattern must accept offsets the
way Tk actually writes them — a negative offset can appear as `-8` or,
after the sign, as `+-8` (e.g. `1000x620+-8+100`) — with both literal
forms covered by tests, so the app can never reject its own saved value.
The app then applies the floor from Q5: a parsed size smaller than
`theme.COURSE_BUILDER_MIN_SIZE` rejects the whole value, position
included (this is what disposes of a bogus `1x1+0+0`), and rebuilds the
canonical string `WxH+X+Y`. Anything else — missing key, wrong type, a
bare `"900x620"`, garbage — becomes `None` and the theme default
applies. A corrupt settings value can never reach `window.geometry()`.

**Save.** A new builder method,

```python
def save_window_geometry(self):
    """Report the dialog's current geometry for later restore (issue #25)."""
```

reads `self.window.geometry()` (size *and* position), updates
`self._saved_geometry` — so closing and reopening within one session also
uses the latest geometry — and calls `self._report_geometry(...)` when a
callback was provided. It no-ops when the dialog is not open, and — from
review — it also no-ops when the window is not in its normal state: a
minimized window reports a parked off-screen position and a maximized
one a size the user did not choose, and neither should become the
remembered geometry. It is called
from exactly the two teardown paths in §2:

- in the dialog's `_close`, after the discard prompt passes and before
  `window.destroy()`;
- in `LibraryApp._close_app`, after `confirm_discard_for_app_exit()`
  approves and before `root.destroy()`, so quitting the app with the
  dialog open saves the geometry too.

No `<Configure>` bindings, debounce timers, or `<Destroy>` hooks:
`window.geometry()` at close time already holds the final size and
position, and saving during root teardown (when `_save_settings` reads
main-window widgets) is avoided because the app-exit call happens
*before* `root.destroy()` is invoked.

**Storage.** `self.course_geometry` is initialized in `__init__` from
the validated saved value — this matters because `_save_settings()` runs
on ordinary interaction (it is bound to table clicks), and a session
that never opens the dialog must carry the stored value through
unchanged rather than dropping the key. `_save_settings()` adds
`"course_geometry": self.course_geometry` to its dict only when a value
is set, so a settings
file that predates the feature does not gain the key until the user has
actually moved the course window. The app-side adapter mirrors the
existing ones:

```python
def _course_geometry_changed(self, geometry):
    self.course_geometry = geometry
    self._save_settings()
```

**Contract bookkeeping.** The constructor grows from five inputs to seven
(two optional). Per the safeguard from proposal 0001, that growth is
stated here and will be stated again in the implementation PR. The
README's paragraph describing the component's inputs gains the two new
inputs, and — per the review resolutions — issue #91's correction (the
same list still omits `library_rows`) is folded into the implementation
PR, so the list becomes accurate in one edit.

## 5. What Does Not Change

- `.CRS` output, queue behaviour, and every prompt (#80/#82/#85/#87) are
  untouched; the discard prompts still run first, and cancelling a close
  or a quit saves nothing and changes nothing.
- The main window's geometry is not remembered (separate idea, separate
  issue if ever wanted).
- No new settings file, no new dependency, standard library only.

## 6. Test Plan (for the implementation PR)

- Parser/validator unit tests: a full geometry string parses, including
  both negative-offset literal forms (`-8` and `+-8`); `None`,
  non-strings, a bare `"1000x620"`, `"0x0+0+0"`, and garbage are
  rejected; a parsed size below the minimum size is rejected by the
  app's floor check.
- Builder tests (mocked Tk, in the style of the existing wiring tests):
  `open_dialog` applies the saved geometry when one was provided and the
  theme default otherwise; a saved position outside the virtual desktop
  falls back to size-only; closing via the dialog's protocol handler
  reports the window's geometry before destroying it; `save_window_geometry`
  no-ops with no dialog open or a non-normal window state, and updates
  the value a reopen would use.
- App tests: the `LibraryApp` construction passes both new inputs to
  `CourseBuilder` (so a wiring omission fails loudly); `_close_app` with
  the dialog open triggers the builder's save before destroying the
  root; `_save_settings` includes `course_geometry` when set and omits
  it when not, and a settings file that already contains the key keeps
  it through a save triggered by an unrelated change.
- A live Xvfb smoke test with a real dialog: open at a saved geometry
  (including a negative-offset position), move/resize programmatically,
  close, reopen, and confirm the second open lands at the final size
  *and position* of the first.

## 7. Open Questions for Reviewers — Resolved

All five were answered in review and accepted by the owner on
2026-11-08 (see "Review resolutions" at the top):

- **Q1.** *Optional or required inputs?* **Resolved: optional** with
  `None` defaults, as proposed (unanimous), plus the wiring test in §6.
- **Q2.** *Save-on-close or crash-proofing?* **Resolved: save-on-close
  only**, as proposed (unanimous). A crash loses at most one session's
  resize.
- **Q3.** *Off-screen restore?* **Resolved: validate the position at
  restore and fall back to size-only when it lies outside the virtual
  desktop** (Claude's option (ii), with GLM 5.3's clamp as the same idea
  in cheaper form; Grok's "ignore for v1" was the minority view). The
  draft's "ignore it" did not survive the observation that the failure
  re-saves itself on every close.
- **Q4.** *Settings key name?* **Resolved: `course_geometry`** (Grok and
  GLM 5.3; Claude leaned the other way but called it owner's
  preference).
- **Q5.** *How much validation?* **Resolved: format plus the
  minimum-size floor** (Claude; Grok and GLM 5.3 would have settled for
  format-only). No upper bound.

---

*Written by Muse (Muse Spark). Reviewed by Claude (Sonnet 5.5), Grok
4.5, and GLM 5.3 (Vibe); accepted by the owner on 2026-11-08 with the
resolutions recorded at the top. Implementation follows in its own PR,
which will link back here.*
