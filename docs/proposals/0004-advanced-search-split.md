# Implementation Proposal: Extract the Advanced Search Dialog into Its Own Component

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-08 |
| **Base** | main `55896f6` (after PR #96) |
| **Related** | The split sequence adopted after proposal 0001 (Course Builder → **Advanced Search** → distribution → settings/snapshot). No dedicated issue; the implementation PR will be the vehicle, as with proposal 0002. |

---

## Revision 1 (2026-11-08, from Claude's review)

Claude (Sonnet 5.5) reviewed the draft and agreed with Option A1 and with
eager construction. It also found four gaps, all verified against the code
by the author and folded in here, so later reviewers see the corrected
text:

1. **Construction site (§4).** The draft said "construct in `__init__`";
   the existing precedent constructs `CourseBuilder` inside `_build()`,
   and the entry points are built there too — the component must exist
   before they are built if they point at it directly. Construction is
   now specified for `_build`, beside the course builder's.
2. **Theme guard (§6).** The implementation must add `advanced_search.py`
   to the file lists in `tests/test_theme.py` and README, or the
   no-hard-coded-colors guard silently stops covering the dialog.
3. **Locals stay locals (§4).** The 14 field variables and the nested
   helpers remain locals of `open_dialog`, as today — they do not become
   instance state. Only the constructor inputs and `window` are attributes.
4. **`window` wording (§3, §4).** It is None only until the dialog is
   first opened; afterwards it holds the (possibly destroyed) window and
   readers check `winfo_exists()`, as with `CourseBuilder.window`.

And one recommendation changed: **Q2 now recommends repointing the entry
points directly** (the draft recommended delegation). With the
construction site fixed, repointing is safe, matches the Build course
button precedent, and removes the app method entirely; Claude leaned the
same way. Q1 and Q3 remain open for the remaining reviewers, with
Claude's answers recorded in §7.

---

## 1. Background and Goal

The Advanced Search dialog — the form of field filters, ranges, and a
minimum grade behind the **Advanced…** button and Ctrl+Shift+F — is the
second piece in the split sequence. Today it is a single ~160-line method,
`LibraryApp.open_advanced_search`, with every helper nested inside it.
Proposal 0001 extracted the course builder into a standalone component with
an explicit constructor contract, and the follow-on work (#47, #25) showed
the contract can grow openly when a real need appears. This proposal asks
reviewers to weigh the same move for Advanced Search before any code moves.

The extraction is behaviour-preserving: same fields, same seeding, same
query text produced, same key bindings. Nothing the user sees changes.

## 2. Current State (measured on main `55896f6`)

- [CODE] `open_advanced_search` (`library_visualizer.py`, lines 1423–1584)
  builds the whole dialog: 14 local `StringVar`s (free text, title, artist,
  pack, meter/BPM/time/peak-NPS ranges, minimum grade, "Other filters"),
  seeded from `split_dialog_query(self.search_var.get())` so filters the
  boxes cannot show survive in "Other filters"; a live query preview driven
  by write traces; and Apply / Clear / Close buttons with Escape and Return
  bindings and a `focus_force()` (dialogs take keyboard focus, #79).
- [CODE] The dialog's query language is already split out:
  `split_dialog_query` and `build_dialog_query` live in `library_data.py`
  with Tk-free tests. Only the window half remains in the app.
- [CODE] The method's entire contact with app state is: `self.root` (parent
  window and `transient`), the themed widget factories `self._entry`,
  `self._button`, `self._combo`, `self.search_var` (read once to seed,
  written once by Apply — the write triggers the app's existing debounced
  refresh; the dialog never calls `refresh_table` itself), and
  `self.advanced_search_window`, the already-open handle used by the
  lift-and-focus early return.
- [CODE] One other reader of that handle: `LibraryApp._dialog_is_open()`
  checks `self.advanced_search_window` alongside `course_builder.window`
  and `about_window`, so Escape pressed in the main window does not wipe
  the search bar while a dialog is open (`_on_main_escape`).
- [CODE] Entry points: the "Advanced…" button, Edit → Advanced search…
  (Ctrl+Shift+F), and two root bindings — all calling
  `self.open_advanced_search`. The dialog is transient but not modal, has
  no discard prompt (closing simply loses unapplied edits; the next open
  re-seeds from the current query), and opens at
  `theme.ADVANCED_SEARCH_GEOMETRY` ("560x620", min (480, 520)) every time.
- [CODE] Existing tests: `tests/test_library_visualizer.py` drives
  `open_advanced_search` on a fake app with mocked Tk (Escape/Return
  bindings, the already-open lift path, `_dialog_is_open` interplay).

## 3. The Decision: The Component's Contract

### Option A (recommended): a standalone `AdvancedSearch` component

A new module `advanced_search.py` holds a component that owns the window
end to end, mirroring `CourseBuilder`: it keeps `self.window` (None until
the dialog is first opened; afterwards the window itself, with readers
checking `winfo_exists()` — the `CourseBuilder.window` pattern) and an
`open_dialog()` whose already-open path lifts and focuses the existing
window. The constructor receives the parent window, the three
widget factories, and **one seam for the query**, which is the real choice
in this proposal:

- **A1 — pass `search_var` itself.** The dialog exists to edit that one
  variable's text: it reads it when the window opens (seed) and writes it
  on Apply. A `StringVar` is mutated in place and never goes stale, so
  handing over the variable is honest, and it has direct precedent —
  `CourseBuilder` receives the app's `status` StringVar the same way.
  One input, no adapter code.
- **A2 — a callable pair, `current_query()` and `apply_query(query)`.**
  Precedent: `selected_rows` / `library_rows`. Keeps the variable private
  to the app, at the cost of two one-line adapters. The callables exist
  there because the underlying rows list is *replaced* on reload, so a
  captured value would go stale; a captured `StringVar` cannot.

This proposal recommends **A1**: the staleness argument that justified
callables for the rows does not apply to a Tk variable, and the `status`
precedent is the closer match — the variable *is* the thing being edited.

### Option B: move only the form helpers, keep the window in the app

Extract the row builders and query assembly into functions and leave
`open_advanced_search` owning the window. Fewer lines in the method, but
the window, its lifecycle, and its tests stay in `library_visualizer.py`;
the split's point — one component owning one window, findable by role —
is not achieved.

### Option C: a mixin class for `LibraryApp`

The dialog becomes methods on a mixin the app inherits. Rejected for the
same reason as in proposal 0001: it hides the boundary instead of stating
it, and the owner's standing guideline is legibility for a human reviewer.

## 4. Recommended Design in Detail (Option A1)

**Component.** `AdvancedSearch.__init__(self, parent, entry_factory,
button_factory, combo_factory, search_var)` — five inputs, and the only
instance attributes besides `window`: the dialog's 14 field variables and
its nested helpers stay **locals** of `open_dialog`, exactly as they are
locals of the method today (turning them into attributes set during open
would recreate the hidden-state pattern the #66/#67 cleanup removed, and
keeping them local is what makes the moved code recognisably the same
code).

**Opening.** `open_dialog()` is today's method body: the already-open
early return (lift + `focus_force`), window creation at the theme
geometry, seeding via `split_dialog_query(self._search_var.get())`,
preview traces, bindings (`<Escape>` close, `<Return>` apply-and-close),
and the final `focus_force()`. Apply sets `self._search_var` and destroys
the window, as today.

**App side.** The component is constructed in `_build`, beside the
`CourseBuilder` construction — not in `__init__` after `_build()` has
run. The entry points are built inside `_build` (the toolbar button, and
the menubar via `_build_menubar`), and direct references to
`self.advanced_search.open_dialog` are evaluated while they are built, so
the component must exist by then; everything it needs does (`search_var`
is created in `__init__`, and the factories are static methods). The four
entry points — the "Advanced…" button, Edit → Advanced search…, and the
two Ctrl+Shift+F root bindings — are repointed at
`self.advanced_search.open_dialog` directly, as the Build course button
calls `course_builder.open_dialog`, and `LibraryApp.open_advanced_search`
is deleted. `_dialog_is_open()` reads `self.advanced_search.window`
instead of `self.advanced_search_window` — the same shape as the
`course_builder.window` read on the next line of that function — and the
old attribute disappears. The component attribute is declared `None` in
`__init__`, mirroring `course_builder`, so early `_dialog_is_open` calls
stay safe.

**Contract bookkeeping.** A new component with five constructor inputs,
stated here per the proposal 0001 safeguard. The README's architecture
paragraphs gain a sentence for the new component, next to the course
builder's.

## 5. What Does Not Change

- Every field, the seeding rules (including "Other filters" preservation),
  the preview, Clear, Apply-on-Return, Escape-to-close, focus behaviour,
  and the exact query strings produced — `build_dialog_query` output is
  untouched, and its round-trip tests in `tests/test_library_data.py` do
  not move.
- No settings involvement, no geometry memory for this dialog (#25 was
  course-window only), no prompts added or removed.
- `.CRS`, the course builder, and the distribution panel are untouched;
  per the sequence rule, no other window code moves in the same PR.

## 6. Test Plan (for the implementation PR)

- Move purity: the dialog body moves recognisably (a normalized diff of
  the method against the component, as was done for proposal 0001), with
  renames limited to the seam (`self.search_var` → the constructor input,
  `self.advanced_search_window` → `self.window`).
- The theme guard must keep covering the moved code: add
  `advanced_search.py` to the file lists in `tests/test_theme.py`
  (`WINDOW_SOURCES`) and in README's styling paragraph, which repeats
  the list. Without this the guard passes while checking nothing in the
  new file — the same list went stale once before, on PR #89.
- Import hygiene travels with the move: `GRADE_OPTIONS`,
  `split_dialog_query`, and `build_dialog_query` become unused in
  `library_visualizer.py` and leave its import list; the new module takes
  the same `try: import tkinter` guard as `course_builder.py`, so the
  Tk-free tests can still import it.
- The existing dialog tests move to `tests/test_advanced_search.py` and
  re-point at the component: Escape/Return bindings, Apply writes the
  built query, seeding from a query with unshowable filters, the
  already-open lift path. Their patch targets change with the module
  (`advanced_search.tk`, not `app.tk`), and the main-window Escape test
  fakes the component (`instance.advanced_search`) instead of a bare
  window attribute.
- App-side tests keep covering `_dialog_is_open` (now reading the
  component's window). All five constructor inputs are required, so a
  forgotten one fails loudly at startup; the wiring guard is therefore a
  one-line identity assertion in a live test — the component's search
  variable *is* the app's `search_var` — against passing the wrong object.
- Full suite green, including zero skips under Xvfb, and a live smoke:
  open the dialog, Apply a filtered query, confirm the table's search
  text changes; reopen and confirm the fields re-seed from it.

## 7. Open Questions for Reviewers

- **Q1.** The query seam: **A1** (`search_var` passed directly, the
  `status` precedent) or **A2** (callable pair, the rows precedent)? This
  proposal recommends A1; it is the one real decision here. *Claude:
  A1 — `search_var` is assigned exactly once and never replaced, so the
  staleness argument for callables does not apply.*
- **Q2.** ~~Keep `LibraryApp.open_advanced_search` as a one-line
  delegation, or repoint the entry points at the component directly?~~
  **Revised in Revision 1: repoint directly** and delete the app method,
  as the Build course button does. The draft's delegation recommendation
  rested on a smaller app-side diff, but with the construction site
  corrected (the component exists before the entry points are built),
  repointing is safe, and one less forwarding method is one less thing
  for a reader to follow. *Claude: leans repoint, weakly.* Reviewers who
  disagree should say so now.
- **Q3.** Construct the component eagerly — now specified as **in
  `_build`, beside the course builder** (Revision 1) — or lazily on first
  open? Lazy would also rule out direct repointing (a bound method of a
  not-yet-existing component cannot be referenced while the button is
  built). *Claude: eager.*

---

*Written by Muse (Muse Spark). No code accompanies this proposal; if it
is accepted, implementation follows in its own PR, which will link back
here.*
