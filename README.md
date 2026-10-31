# ITGmania Library Visualizer

A small Windows-friendly desktop app for browsing ITGmania cached charts alongside a player's `Stats.xml`. It uses only Python's standard library (including Tkinter), so there is no package installation step.

## Run

Install Python 3.10 or newer with Tcl/Tk, then run:

```powershell
python library_visualizer.py
```

The app starts with the usual Windows ITGmania cache location filled in when it exists. Select the flat `Cache/Songs` folder and the player's `Stats.xml` with **Browse…**, then choose **Load / refresh**. The `Stats.xml` can be selected from a local profile folder; it is read only. After the first refresh, the app saves a local snapshot of the parsed chart library and restores it on later launches. Use **Load / refresh** when you want to reread the cache and scores; the saved snapshot does not update automatically when those files change.

On Linux and macOS, choose the cache and profile paths with **Browse…**; the automatic cache-path guess is Windows-specific.

## Data expectations and troubleshooting

- Select the cache output folder, where cache files are directly inside `Cache/Songs`. The original `Songs/Pack/Song` directory tree is not the cache and is not scanned recursively. If that tree is selected, the app reports that no files were found at the folder level and suggests the cache folder.
- The status line reports the number of files scanned and charts parsed, plus unreadable files and files with no recognized charts. A cache file needs chart metadata including `STEPSTYPE` and `DIFFICULTY` to appear in the table.
- Scores are matched by normalized song directory, steps type, and difficulty, without regard to letter case. When there are multiple scores for a chart, the highest `PercentDP` is shown. A profile with no `SongScores` is valid and simply has no matched scores.
- If `Stats.xml` is malformed, incomplete, or cannot be read, loading stops and the app displays an error. Unreadable individual cache files are skipped and included in the status count.

## Browse

- Search by title, artist, pack, chart name, type, or difficulty. Free text can be combined with structured field directives in the search bar or configured visually via **Advanced…** (or **Edit → Advanced search…**, `Ctrl+Shift+F`):
  - **Meter**: `meter:11`, `meter:10-12`, `meter:>=10`, `meter:<8` (alias: `m:`)
  - **BPM**: `bpm:200-300`, `bpm:>240`, `bpm:180` (matches tempo range overlap)
  - **Length / Time**: `time:>2:00`, `time:>120`, `length:1:30-2:15`, `time:<90` (accepts both `mm:ss` and raw seconds)
  - **Metadata**: `artist:Smiley`, `title:Delirium`, `pack:"In The Groove"`, `diff:Challenge`
  - **Scores & Tech**: `grade:★★★★`, `grade:>=S`, `percent:>95`, `nps:>15`, `crossovers:>10`, `jacks:>0`
  - Mixed queries like `Smiley meter:11 bpm:200-300 time:>1:45` filter across text and ranges simultaneously.
- Filter by pack, steps type, and difficulty; show scored charts only. Difficulties are listed in gameplay order from Beginner through Edit.
- Click a column heading to sort. Click it again to reverse the order. Difficulty sorts in gameplay order from Beginner through Edit. Grade sorts in ITGmania tier order (S+ before S before S−). BPM sorts by maximum tempo, then minimum.
- Drag column headings to reorder them, and drag the divider between headings to resize a column.
- Use **View → Columns** to show or hide columns by category; **View → Reset column layout** restores the defaults.
- Scroll horizontally for the full set of score, radar, and ITGmania tech-count columns.
- **Export CSV** writes the full library (not just the filtered rows) for use in other tools.
- Select charts with Ctrl/Shift-click and choose **Build course…** to create an ordered course queue. You can add more charts, remove entries, reorder them, save a new `.CRS` file, or append the queued charts to an existing course. Appending preserves the existing file bytes and stops with a warning if trailing `#MODS` or `#GAINSECONDS` directives could affect the appended entries.

New courses contain a `#COURSE:title;` line followed by one `#SONG:path:difficulty:;` line per queued chart. The app does not edit existing chart entries or modifiers when appending.

The table includes chart meter, peak NPS, radar note counts, the player's highest `PercentDP` score for the chart, grade, play count, last played date, best-score tap judgments and combo, and cached tech counts. `Stats.xml` scores are matched to cached charts by song directory, steps type, and difficulty.

The **Time** column shows cached song music length as `minutes:seconds`; CSV exports retain that value in seconds. The **BPM** column shows the song's tempo range from the cache (`#BPMS`, with `#DISPLAYBPM` when set). Sorting by BPM uses maximum then minimum tempo so a mostly-fast chart with a brief slow section ranks with other fast charts. Grade sorts in ITGmania tier order (S+ before S before S−, and so on), not alphabetically. The course builder shows each queued song's time and the summed course length.

## Data paths

The cache folder is commonly `%APPDATA%\ITGmania\Cache\Songs`. `Stats.xml` lives inside a player profile's save folder. The app does not edit either source.

The app remembers the selected data paths, column order, visibility, and widths in `%APPDATA%\ITGmania Library Visualizer\settings.json` on Windows. The parsed library snapshot is stored beside it as `library_cache.json`. On other platforms these files use the standard per-user configuration directory.

## Development checks

Run the parser and course-append regression tests with:

```powershell
python -m unittest discover -s tests
```

The UI-independent parsing and course helpers live in `library_data.py`; `tests/test_library_data.py` exercises them without importing Tkinter. Course formatting, parsing, trailing-modifier detection, and field validation live there so CRS features can grow without pulling in the Tk UI. The snapshot lifecycle tests exercise the app module.
