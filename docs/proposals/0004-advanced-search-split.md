# Implementation Proposal: Extract the Advanced Search Dialog into Its Own Component

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse (Muse Spark) |
| **Date** | 2026-11-08 |
| **Base** | main `55896f6` (after PR #96) |
| **Related** | The split sequence adopted after proposal 0001 (Course Builder → **Advanced Search** → distribution → settings/snapshot). No dedicated issue; the implementation PR will be the vehicle, as with proposal 0002. |

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
end to end, mirroring `CourseBuilder`: it keeps `self.window` (None when
closed) and an `open_dialog()` whose already-open path lifts and focuses
the existing window. The constructor receives the parent window, the three
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
button_factory, combo_factory, search_var)` — five inputs. All dialog
state (the 14 field variables, the preview label) becomes instance state
created in `open_dialog`, exactly as the locals are created today; the
nested helpers become private methods or stay nested — implementation
detail, as long as the moved code is recognisably the same code.

**Opening.** `open_dialog()` is today's method body: the already-open
early return (lift + `focus_force`), window creation at the theme
geometry, seeding via `split_dialog_query(self._search_var.get())`,
preview traces, bindings (`<Escape>` close, `<Return>` apply-and-close),
and the final `focus_force()`. Apply sets `self._search_var` and destroys
the window, as today.

**App side.** `LibraryApp` constructs the component in `__init__` once
`search_var` and the factories exist, and `open_advanced_search()` becomes
a one-line delegation (`self.advanced_search.open_dialog()`), so the
button, menu item, and both Ctrl+Shift+F bindings keep calling the name
they call today. `_dialog_is_open()` reads `self.advanced_search.window`
instead of `self.advanced_search_window` — the same shape as the
`course_builder.window` read on the next line of that function — and the
old attribute disappears. The component attribute is declared `None`
before construction, mirroring `course_builder`, so early `_dialog_is_open`
calls stay safe.

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
- The existing dialog tests move to `tests/test_advanced_search.py` and
  re-point at the component: Escape/Return bindings, Apply writes the
  built query, seeding from a query with unshowable filters, the
  already-open lift path.
- App-side tests keep covering the entry points and `_dialog_is_open`
  (now reading the component's window), plus a wiring assertion that
  `__init__` passes the real `search_var` — the silent-omission guard
  proposal 0003's review added for the geometry inputs.
- Full suite green, including zero skips under Xvfb, and a live smoke:
  open the dialog, Apply a filtered query, confirm the table's search
  text changes; reopen and confirm the fields re-seed from it.

## 7. Open Questions for Reviewers

- **Q1.** The query seam: **A1** (`search_var` passed directly, the
  `status` precedent) or **A2** (callable pair, the rows precedent)? This
  proposal recommends A1; it is the one real decision here.
- **Q2.** Keep `LibraryApp.open_advanced_search` as a one-line delegation
  (entry points untouched), or repoint the button, menu, and bindings at
  the component directly, as the Build course button does
  (`course_builder.open_dialog`)? Delegation is recommended for the
  smaller app-side diff, but the direct form is the closer match to the
  course builder precedent.
- **Q3.** Construct the component eagerly in `__init__` (course builder
  precedent; needs the None-guard in `_dialog_is_open`), or lazily on
  first open (no unused component, but a construction branch in the open
  path)? Eager is recommended for symmetry with the existing component.

---

*Written by Muse (Muse Spark). No code accompanies this proposal; if it
is accepted, implementation follows in its own PR, which will link back
here.*
