# ITGmania Library Visualizer

A small Windows-friendly desktop app for browsing ITGmania cached charts alongside a player's `Stats.xml`. It runs on Python's standard library alone (including Tkinter), so no package installation is required. One optional package, `matplotlib`, adds the distribution charts (see below).

## Run

Install Python 3.10 or newer with Tcl/Tk, then run:

```powershell
python library_visualizer.py
```

Optional: install `matplotlib` (`pip install matplotlib`, or `pip install -r requirements.txt`) to display interactive collection distribution charts (Meter, Difficulty, and BPM) in the collapsible side panel. Without it the panel shows an install hint and everything else works as usual.

The app starts with the usual ITGmania cache location for your platform filled in when it exists. Choose the flat `Cache/Songs` folder and the player's `Stats.xml` in **File → Data paths…**, then choose **Load / refresh**. The `Stats.xml` can be selected from a local profile folder; it is read only. After the first refresh, the app saves a local snapshot of the parsed chart library and restores it on later launches. Use **Load / refresh** when you want to reread the cache and scores; the saved snapshot does not update automatically when those files change. While it reads, the progress bar shows files done out of the total, with an estimated time left once the scan is under way.

On Linux the usual cache location is `~/.itgmania/Cache/Songs`, and on macOS `~/Library/Application Support/ITGmania/Cache/Songs`; if the guess comes up empty, choose the cache and profile paths in **File → Data paths…**.

## Data expectations and troubleshooting

- Select the cache output folder, where cache files are directly inside `Cache/Songs`. The original `Songs/Pack/Song` directory tree is not the cache and is not scanned recursively. If that tree is selected, the app reports that no files were found at the folder level and suggests the cache folder.
- The status line reports the number of files scanned and charts parsed, plus unreadable files and files with no recognized charts. A cache file needs chart metadata including `STEPSTYPE` and `DIFFICULTY` to appear in the table.
- Scores are matched by normalized song directory, steps type, and difficulty, without regard to letter case; Edit charts are matched by description as well, because several Edits can share a directory, steps type, and difficulty (falling back to the shared Edit score when the cached chart has no description). When there are multiple scores for a chart, the highest `PercentDP` is shown. A profile with no `SongScores` is valid and simply has no matched scores.
- If `Stats.xml` is malformed, incomplete, or cannot be read, loading stops and the app displays an error. Unreadable individual cache files are skipped and included in the status count.

## Browse

- Search by title, subtitle, artist, pack, chart name, type, or difficulty. Free text can be combined with structured field directives in the search bar or configured visually via **Advanced…** (or **Edit → Advanced search…**, `Ctrl+Shift+F`):
  - Free-text terms are ANDed: every term must appear somewhere in the chart's searchable text, including the subtitle. Use double quotes to keep a phrase together, and quote multiword field values (for example, `pack:"In The Groove"`). Apostrophes are ordinary characters, so titles can be typed exactly as written (for example, `don't` or `rock 'n' roll`). A backslash escapes the next character, so wrap a value that contains backslashes in double quotes to search for it literally.
  - **Meter**: `meter:11`, `meter:10-12`, `meter:>=10`, `meter:<8` (alias: `m:`)
  - **BPM**: `bpm:200-300`, `bpm:>240`, `bpm:180` (matches tempo range overlap). The BPM column shows what the game shows, including `#DISPLAYBPM`; `bpm:`, sorting and the distribution chart always use the real `#BPMS` range.
  - A numeric directive with an empty value (for example `meter:` while typing) is ignored; a value that cannot be read (for example `meter:abc`) matches nothing, and the count line says so — "Can't read the value in `meter:abc`". The same hint holds for `grade:`: an unknown grade (for example `grade:banana`, or an operator with an empty target, `grade:>=`) matches nothing with the same hint. An empty `grade:` is different — it matches only unscored charts, the unplayed set.
  - **Length / Time**: `time:>2:00`, `time:>120`, `length:1:30-2:15`, `time:<90` (accepts both `mm:ss` and raw seconds)
  - **Metadata**: `artist:Smiley`, `title:Delirium`, `pack:"In The Groove"`, `diff:Challenge`
  - **Radar counts**: `jumps:>10`, `holds:>=5`, `rolls:>0`, `mines:0`, `hands:0`, `lifts:0`, `taps:>500` (exact counts, `>=`/`>`/`<=`/`<` comparisons, and ranges like `jumps:10-20` and `mines:1..5`). `taps:` counts taps and hold notes together, matching the Taps/Holds column.
  - **Scores & Tech**: `grade:★★★★`, `grade:>=S`, `score:>900000` (raw score), `percent:>95`, `nps:>15`, `crossovers:>10`, `jacks:>0`
  - Mixed queries like `Smiley meter:11 bpm:200-300 time:>1:45` filter across text and ranges simultaneously.
  - The **Advanced…** window fills its boxes from the search bar. Any filter that has no box, or that a box cannot show exactly (for example `plays:>=3`, `jacks:>0`, `grade:<B` or `meter:>10`), appears in **Other filters** and is written back unchanged when you click **Apply**. Edit or clear that line to change those filters. In the **Advanced…** window, **Enter** applies the search and **Escape** closes the window without changing the search bar; **Escape** also closes the **Build course…** window. While either window is open, pressing **Escape** in the main window does not clear the search bar (it asks first if charts are queued, because the queue is lost when the window closes). Quitting the app — **File → Exit** or the main window's close button — asks the same question first when charts are queued in the **Build course…** window, and cancelling it leaves the app open with the queue untouched.
- Filter by pack, steps type, and difficulty; show scored charts only. Difficulties are listed in gameplay order from Beginner through Edit.
- Toggle the **Distribution** side panel (or **View → Show distribution panel**) to view live distribution charts of Meter levels, Difficulty tiers, or BPM ranges for the currently filtered view. Clicking any category or bar immediately filters the table; clicking it again removes that filter, and **Clear** removes every chart filter (difficulty, meter and BPM) at once. Each chart keeps showing all of its bars after you click one, so you can click another bar to switch; it still respects the other filters (pack, steps type, scored only, search text, and the other charts' filters), and only skips its own metric's filter.
  - BPM bars count a chart in every range its tempo touches, so a chart that runs 100–150 BPM is counted in the under-120, 120–139 and 140–159 bars, and the bars add up to more than the number of charts. Clicking a bar writes two search filters, such as `bpm:>=120 bpm:<140`, so the table shows exactly the number of charts on the bar.
- Click a column heading to sort. Click it again to reverse the order. Difficulty sorts in gameplay order from Beginner through Edit. Grade sorts in ITGmania tier order (S+ before S before S−). BPM sorts by maximum tempo, then minimum.
- Table rows are softly tinted by chart difficulty (Beginner sky blue, Easy yellow, Medium rose, Hard green, Challenge purple, Edit gray; any other difficulty name is also gray), matching the distribution chart palette. When a row is selected, its text turns white on the selection background to maintain high contrast.
- Drag column headings to reorder them, and drag the divider between headings to resize a column.
- Use **View → Columns** to show or hide columns by category. The categories are Song & chart, Score, Tap judgments, Chart counts and Tech counts. Each category's menu starts with **Show whole group**, which is checked while every column of that category is shown; clicking it shows or hides the whole category at once. At least one column always stays visible.
- A fresh install, and **View → Reset column layout**, show only the Song & chart and Score columns. The Subtitle column is the exception: it belongs to Song & chart but stays hidden until you turn it on under **View → Columns**. Columns you have already shown or hidden keep your choice. The Tap judgments columns (W1–W5 and Miss) come from the same best score as the Score columns.
- Scroll horizontally if the columns you turn on are wider than the window.
- **Export CSV** writes the full library (not just the filtered rows) for use in other tools.
- Select charts with Ctrl/Shift-click (or press `Ctrl+A` with the table focused to select everything displayed) and choose **Build course…** to create an ordered course queue. You can add more charts, remove entries, reorder them, save a new `.CRS` file, or append the queued charts to an existing course. Appending preserves the existing file bytes and stops with a warning if trailing `#MODS` or `#GAINSECONDS` directives could affect the appended entries (including after `#SONGSELECT` directives). The window remembers its size and position from last time.
- In the course queue, rows are tinted by difficulty the same way as the main table, and a selected row's text turns white. With the queue focused (click a row first), **Delete** or **Backspace** removes the selected entries, the same as **Remove**. After a removal the entry that took the removed one's place stays selected (or the new last entry, if the end was removed), so repeated presses keep removing in order. **Undo remove** — or **Ctrl+Z** while the queue has focus — restores the entries from the most recent removal at their original positions, with the restored entries selected; only the last removal is remembered, and adding or moving entries forgets it, as does reloading the library — with the queue already empty, or by clearing the queue when asked — so Undo never brings back charts from the previous library.

New courses contain a `#COURSE:title;` line followed by one `#SONG:path:difficulty:;` line per queued chart. Existing courses can use either two-field (`#SONG:path:diff;`) or three-field directives, or `#SONGSELECT`. Titles, paths, and difficulties cannot contain semicolons, colons, newlines, or `//` comment markers. The app does not edit existing chart entries or modifiers when appending.

The table includes chart meter, peak NPS, radar note counts, the player's highest `PercentDP` score for the chart, grade, play count, last played date, best-score tap judgments and combo, and cached tech counts. `Stats.xml` scores are matched to cached charts by song directory, steps type, and difficulty (Edit charts also by description).

The **Time** column shows cached song music length as `minutes:seconds`; CSV exports retain that value in seconds. The **BPM** column shows each chart's tempo range from the cache (`#BPMS`, with `#DISPLAYBPM` when set). A chart's own `#BPMS` and `#DISPLAYBPM` are used when present, otherwise the song's; zero and negative tempos are ignored, so a warp-only `#BPMS` counts as no tempo. Sorting by BPM uses maximum then minimum tempo so a mostly-fast chart with a brief slow section ranks with other fast charts. Grade sorts in ITGmania tier order (S+ before S before S−, and so on), not alphabetically. The course builder shows each queued song's time and the summed course length.

## Data paths

The cache folder is commonly `%APPDATA%\ITGmania\Cache\Songs`. `Stats.xml` lives inside a player profile's save folder. The app does not edit either source. Change the paths in **File → Data paths…**; on a first run with no usable paths the app asks for them itself before showing an empty library.

The app remembers the selected data paths, the Pack/Type/Difficulty filter selections, column order, visibility, and widths, and the course and Advanced Search windows' sizes and positions, in `%APPDATA%\ITGmania Library Visualizer\settings.json` on Windows. The parsed library snapshot is stored beside it as `library_cache.json`. On other platforms these files use the standard per-user configuration directory. If the settings file exists but cannot be read (corrupt, mis-encoded, or not a JSON object), the app starts with its defaults and says so on the status line.

## Changing the look

Every color and font the window uses is defined, with a note on what it is for, in `theme.py`. To restyle the app, edit the values there and restart it; the window code only refers to the names (for example `theme.BG_WINDOW`), and a test fails if a color or font is typed directly into the window code (`library_visualizer.py`, `course_builder.py`, `row_tints.py`, `advanced_search.py`, or `distribution_panel.py`) again. `theme.DIFFICULTY_COLORS` controls both the distribution chart bars and the song table row tints. Row heights, panel widths, and window sizes are likewise fixed numbers in `theme.py`, so a much larger font may also need those adjusted. Those numbers are in 100% units: on Windows the app declares itself DPI-aware, so at 125% or 150% display scaling they are scaled up and the text stays sharp instead of being bitmap-stretched, and the sizes and positions the app remembers are stored in 100% units, so they come back the same at any scale.

## Development checks

Run the parser and course-append regression tests with:

```powershell
python -m unittest discover -s tests
```

`theme.py` holds the colors and fonts; `tests/test_theme.py` checks the window code uses it.

The UI-independent parsing and course helpers live in `library_data.py`; `tests/test_library_data.py` exercises them without importing Tkinter. Course formatting, parsing, trailing-modifier detection, and field validation live there so CRS features can grow without pulling in the Tk UI. The snapshot and settings stores live there too, with their tests in `tests/test_snapshot_store.py` and `tests/test_settings_store.py`; the app-side wiring tests stay in `tests/test_library_visualizer.py`.

The Build-a-course dialog is a separate component in `course_builder.py`, constructed by the main window with the few things it needs (its parent window, the status variable, the button factory, a way to read the table's selected rows, a way to read every row in the library, the remembered window geometry, a callback that reports the geometry when the window closes, and the display scale factor); its tests are in `tests/test_course_builder.py`.

The Advanced Search dialog is likewise a separate component in `advanced_search.py`, constructed by the main window with its parent window, the three widget factories, the search variable it edits, the remembered window geometry, a callback that reports the geometry when the window closes, and the display scale factor; its tests are in `tests/test_advanced_search.py`.

The distribution panel beside the table is a separate component in `distribution_panel.py`, constructed by the main window with the button factory, the four variables it shares with the window (the search and difficulty variables, its show/hide variable, and its metric selector), a way to pull rows when the chart's own metric is the active filter, a callback that applies a chart click or Clear as one batched filter change, the settings save, and the display scale factor; its tests are in `tests/test_ui_distribution.py`. The two dialogs and the panel persist differently by design: a dialog's geometry is a value passed in and a callback reporting it back out, while the panel's variables are shared objects, because the View menu and the settings save both bind them directly.

## License

Released under the MIT License; see `LICENSE`. **Help → About** shows the version and license. The version number is `__version__` in `library_visualizer.py`, and a test checks that it matches the newest heading in `CHANGELOG.md`, so change both together when releasing.
