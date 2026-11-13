# Changelog

## 1.2.1 - 2026-11-12

### Library table
- A song with a non-finite tempo (`#BPMS` of `inf`, `#DISPLAYBPM` of `nan`/`inf`) no longer fails the whole library load; its BPM cell is blank instead. A snapshot row with a non-finite `Time` (`"nan"`/`"1e999"`) no longer crashes the table build; its Time cell is blank.
- The distribution panel no longer prints `Mean: inf` or `Mean: nan` for a corrupt cache; summary stats use finite values only, and all NaN meters form a single bar with the true count.

### Startup and loading
- The cache path field now fills in with the usual ITGmania cache location for your platform when it exists, instead of always guessing a Windows-shaped path; on a fresh install with no cache folder yet, the field starts empty.
- When `settings.json` exists but can't be read, the status line says so and that defaults are being used, instead of silently discarding the file.
- When a restored snapshot's saved cache folder or Stats.xml no longer exists, the status line says so and points at File → Data paths…, instead of failing silently on the next refresh.
- The Data paths dialog is now a single modal window titled 'Where is your library?'; it opens once per session at startup when no snapshot was restored and the paths are not both usable, and Load / refresh opens it when the paths are invalid.
- Load / refresh now shows a determinate progress bar with a files-done count and an ETA, and a 'Saving snapshot…' phase at the end.

### Other
- The app is now DPI-aware on Windows, so it renders at the right physical size on 125% and 150% displays; stored window geometry and column widths are in canonical 100% units.
- A failed settings save no longer leaves a `settings.tmp` file behind.
- The snapshot and settings persistence now live in their own components in `library_data.py` (`SnapshotStore` and `SettingsStore`); these moves were not intended to change behavior.

## 1.2.0 - 2026-11-11

### Library table
- New Subtitle column: shows each song's subtitle, searchable by free text, hidden by default (turn it on under View → Columns).
- BPM now uses real tempos for filtering, sorting and the distribution chart; the BPM column shows `#DISPLAYBPM`, and a chart's own `#BPMS`/`#DISPLAYBPM` win over the song's when present. Tempos of zero or below are ignored.
- Ctrl+A selects all rows in the results table.
- The Pack, Type and Difficulty filter dropdowns are remembered across restarts, and fall back to "All …" when a saved value no longer exists.
- The count line now says when a search filter value cannot be read (for example `meter:abc`), and reports cache chart blocks skipped for missing metadata.

### Startup and loading
- The window paints before the saved library loads, and large libraries insert rows in time-boxed batches, so startup feels faster.
- Cache parsing is faster (about 11% of the parse loop).
- A mis-encoded or BOM-saved `settings.json` no longer crashes startup or silently loses settings, and deeply nested or oversized-number JSON no longer crashes the readers.

### Other
- Challenge difficulty tint lightened to meet contrast (`#c084fc`).
- First-run welcome text names the Load button.
- The distribution panel now lives in its own component; this move was not intended to change behavior.
- Proposal, PR and issue templates added for contributors.

## 1.1.0 - 2026-11-09

### Search
- Filter by a chart's radar note counts: directives such as `jumps:>10`, `mines:0` and `hands:0`, with comparisons (`>=`, `>`, `<=`, `<`) and ranges (`jumps:10-20`, `mines:1..5`). `taps:` counts taps and hold notes together, matching the Taps/Holds column.

### Courses
- Ctrl+Z undoes the last removal from the course queue (one step).
- Quitting the app asks before discarding a course queue you have not saved, and the dialog's close button asks the same as Escape does.
- Reloading the library with a queue in progress asks what to do with the queue instead of discarding it silently.
- Saving warns before writing when a queued entry matches more than one chart in the library.
- Queue rows use the same difficulty tints as the main table, selected rows keep white text, and Delete/Backspace removes the selected rows.
- The Course Builder window remembers its size and position, including across restarts, and recovers if it was left partly off-screen. Its default size is wider, so the controls row fits.

### Windows
- The Advanced Search window remembers its size and position too, with the same off-screen recovery.

### Under the hood
- The Course Builder and the Advanced Search dialog now live in their own modules (`course_builder.py`, `advanced_search.py`) and share the row-tint rule from `row_tints.py`; layout sizes are centralized in `theme.py`. These moves were not intended to change behavior.
- README corrections: score matching also keys on an Edit chart's description, and the layout constants live in `theme.py`.

## 1.0.0 - 2026-11-07

First release. Written against ITGmania v1.3.0 stable. Needs Python 3.10 or newer.

### Library table
- Reads ITGmania's song cache and a player's `Stats.xml` (read-only) into one table with chart details, best scores, grades, play counts and tech counts.
- Saves a snapshot of the parsed library, so later launches start from it until you choose Load / refresh.
- Sort by any column; drag headings to reorder and dividers to resize; show or hide columns by group.
- Rows are tinted by difficulty.
- Export the full library to CSV.

### Search and filters
- Free-text search plus field filters: meter, BPM, length, title, artist, pack, difficulty, grade, score, percent, NPS and tech counts.
- Advanced search window that fills from the search bar and keeps any filter it has no box for.
- Filter by pack, steps type, difficulty, and scored charts only.

### Distribution panel
- Optional side panel (needs `matplotlib`) charting Meter, Difficulty and BPM for the current view; clicking a bar filters the table.

### Courses
- Course builder: queue charts, reorder them, then save a new `.CRS` file or append to an existing one without changing its existing contents. It warns when trailing `#MODS` or `#GAINSECONDS` directives could affect the appended entries.

### Other
- Help → About shows the version and license.
- Every color and font is defined in `theme.py`.
- Released under the MIT License.
