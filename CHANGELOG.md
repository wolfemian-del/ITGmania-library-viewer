# Changelog

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
