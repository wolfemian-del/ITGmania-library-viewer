# ITGmania Library Visualizer

A small Windows-friendly desktop app for browsing ITGmania cached charts alongside a player's `Stats.xml`. It uses only Python's standard library (including Tkinter), so there is no package installation step.

## Run

Install Python 3.10 or newer with Tcl/Tk, then run:

```powershell
python library_visualizer.py
```

The app starts with the usual Windows ITGmania cache location filled in when it exists. Select the `Cache/Songs` folder and the player's `Stats.xml` with **Browse…**, then choose **Load / refresh**. The `Stats.xml` can be selected from a local profile folder; it is read only.

## Browse

- Search by title, artist, pack, chart name, type, or difficulty.
- Filter by pack, steps type, and difficulty; show scored charts only. Difficulties are listed in gameplay order from Beginner through Edit.
- Click a column heading to sort. Click it again to reverse the order.
- Drag column headings to reorder them, and drag the divider between headings to resize a column.
- Use **View → Columns** to show or hide columns by category; **View → Reset column layout** restores the defaults.
- Scroll horizontally for the full set of score, radar, and ITGmania tech-count columns.
- **Export CSV** writes the full library (not just the filtered rows) for use in other tools.

The table includes chart meter, peak NPS, radar note counts, the player's highest `PercentDP` score for the chart, grade, play count, last played date, best-score tap judgments and combo, and cached tech counts. `Stats.xml` scores are matched to cached charts by song directory, steps type, and difficulty.

## Data paths

The cache folder is commonly `%APPDATA%\ITGmania\Cache\Songs`. `Stats.xml` lives inside a player profile's save folder. The app does not edit either source.

The app remembers the selected data paths, column order, visibility, and widths in `%APPDATA%\ITGmania Library Visualizer\settings.json` on Windows. On other platforms it uses the standard per-user configuration directory.
