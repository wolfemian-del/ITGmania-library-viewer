# Changelog

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
