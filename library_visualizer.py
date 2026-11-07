"""A small desktop browser for ITGmania's song cache and Stats.xml."""

from __future__ import annotations

import contextlib
import csv
from datetime import datetime
import json
import os
import re
import sys
import threading
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

DIST_PANEL_WIDTH = 320
# A bar can be clicked across at least this fraction of the chart's width, so a very short bar (one chart
# among hundreds) is still easy to hit, while a click far to the right of it does nothing.
CHART_MIN_CLICK_FRACTION = 0.15

import theme
from library_data import (
    DIFFICULTY_ORDER,
    GRADE_OPTIONS,
    TAP_FIELDS,
    TECH_FIELDS,
    CHART_FILTER_FIELDS,
    aggregate_bpm_distribution,
    aggregate_difficulty_distribution,
    aggregate_meter_distribution,
    bpm_sort_key,
    build_dialog_query,
    course_append_bytes,
    difficulty_sort_key,
    distribution_summary_stats,
    filter_texts_match,
    format_duration,
    get_active_chart_filters,
    grade_sort_key,
    looks_like_song_tree,
    match_chart_query,
    number,
    parse_cache_file,
    parse_search_query,
    replace_search_directive,
    split_dialog_query,
    stats_index,
    validate_course_fields,
)

SEARCH_DEBOUNCE_MS = 200
LIBRARY_CACHE_SCHEMA_VERSION = 2
UNKNOWN_DIFFICULTY_TAG = "diff_unknown"  # table tag for a difficulty name that theme.DIFFICULTY_COLORS lacks
HEADERS = ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart", "Score",
           "Grade", "Best %", "Plays", "Last played", "Peak NPS", "Taps/Holds", "Jumps",
           "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
           "Miss", "Max combo", *TECH_FIELDS)
NUMERIC_COLUMNS = {"Meter", "Time", "Score", "Best %", "Plays", "Peak NPS", "Taps/Holds", "Jumps",
                   "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4",
                   "W5", "Miss", "Max combo", *TECH_FIELDS}
# The groups shown under View > Columns, in menu order. Every column in HEADERS belongs to exactly one group.
COLUMN_GROUPS = {
    "Song & chart": ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart"),
    "Score": ("Score", "Grade", "Best %", "Plays", "Last played", "Max combo"),
    "Tap judgments": TAP_FIELDS,
    "Chart counts": ("Peak NPS", "Taps/Holds", "Jumps", "Holds", "Rolls", "Mines", "Hands", "Lifts"),
    "Tech counts": TECH_FIELDS,
}
# Groups whose columns are shown on a fresh install and after "Reset column layout".
DEFAULT_VISIBLE_GROUPS = ("Song & chart", "Score")
DEFAULT_VISIBLE_COLUMNS = frozenset(
    column for group in DEFAULT_VISIBLE_GROUPS for column in COLUMN_GROUPS[group])


class ChartBar(NamedTuple):
    """One row of the distribution chart, in the chart's own coordinates, as the click handler needs it."""
    y_min: float
    y_max: float
    label: str
    token: str | tuple  # the filter value(s) a click applies; "" when the row cannot be clicked
    click_width: float = float("inf")  # a click to the right of this x does nothing


class LibraryApp:
    # Defaults for state that is only set later, so every instance has these attributes.
    _search_refresh_after_id = None
    _batching_filter_changes = False

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ITGmania Library Visualizer")
        self.root.geometry("1500x850")
        self.root.minsize(900, 550)
        self.root.configure(bg=theme.BG_WINDOW)
        self.rows: list[dict] = []
        self.loaded_source_paths = None
        self.settings_path = self._settings_file_path()
        self.saved_settings = self._read_settings()
        default_cache = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "ITGmania" / "Cache" / "Songs"
        default_stats = Path.cwd() / "Stats.xml"
        self.cache_var = tk.StringVar(value=self.saved_settings.get("cache_dir", str(default_cache)))
        self.stats_var = tk.StringVar(value=self.saved_settings.get(
            "stats_file", str(default_stats) if default_stats.is_file() else ""))
        self.search_var = tk.StringVar()
        self.pack_var = tk.StringVar(value="All packs")
        self.type_var = tk.StringVar(value="All types")
        self.diff_var = tk.StringVar(value="All difficulties")
        self.scored_var = tk.BooleanVar(value=False)
        self._search_refresh_after_id = None
        saved_order = self.saved_settings.get("column_order", [])
        if not isinstance(saved_order, list):
            saved_order = []
        valid_order = []
        for column in saved_order:
            if column in HEADERS and column not in valid_order:
                valid_order.append(column)
        self.column_order = valid_order + [column for column in HEADERS if column not in valid_order]
        if "Time" not in valid_order:
            self.column_order.remove("Time")
            meter_index = self.column_order.index("Meter")
            self.column_order.insert(meter_index + 1, "Time")
        if "BPM" not in valid_order:
            self.column_order.remove("BPM")
            time_index = self.column_order.index("Time")
            self.column_order.insert(time_index + 1, "BPM")
        saved_visibility = self.saved_settings.get("column_visibility", {})
        if not isinstance(saved_visibility, dict):
            saved_visibility = {}
        # A column with no saved choice follows the default set; saved choices are always kept.
        self.column_visibility = {
            column: tk.BooleanVar(value=saved_visibility.get(column)
                                  if isinstance(saved_visibility.get(column), bool)
                                  else column in DEFAULT_VISIBLE_COLUMNS)
            for column in HEADERS
        }
        if not any(variable.get() for variable in self.column_visibility.values()):
            self.column_visibility[HEADERS[0]].set(True)
        # One check box per group in the Columns menu; it is checked while every column of the group is shown.
        self.group_visibility = {group: tk.BooleanVar() for group in COLUMN_GROUPS}
        self._sync_group_checks()
        saved_widths = self.saved_settings.get("column_widths", {})
        if not isinstance(saved_widths, dict):
            saved_widths = {}
        self.column_widths = {
            column: self._valid_column_width(saved_widths.get(column), column) for column in HEADERS
        }
        self.default_column_widths = {}
        self.sort_keys = []
        saved_sort_keys = self.saved_settings.get("sort_keys", [])
        if isinstance(saved_sort_keys, list):
            for item in saved_sort_keys:
                if (isinstance(item, list) and len(item) == 2 and item[0] in HEADERS
                        and isinstance(item[1], bool) and item[0] not in {col for col, _ in self.sort_keys}):
                    self.sort_keys.append((item[0], item[1]))
        if not self.sort_keys:
            self.sort_keys = [("Pack", False)]
        self.show_distribution_panel = tk.BooleanVar(
            value=bool(self.saved_settings.get("show_distribution", False))
        )
        saved_metric = self.saved_settings.get("distribution_metric", "Meter")
        self.distribution_metric = tk.StringVar(
            value=saved_metric if saved_metric in ("Meter", "Difficulty", "BPM") else "Meter"
        )
        self.dist_canvas = None
        self.dist_fig = None
        self.dist_ax = None
        self._current_dist_bars = []
        self._last_visible_rows = []
        self._selected_tree_items = set()  # table rows currently carrying the white "selected_row" tag
        self._load_generation = 0  # counts Load / refresh requests; a scan from an older request is dropped
        self._snapshot_lock = threading.Lock()  # one scan at a time may check its generation and write the snapshot
        self._style()
        self._build()
        self.search_var.trace_add("write", lambda *_: self._schedule_search_refresh())
        for var in (self.pack_var, self.type_var, self.diff_var, self.scored_var):
            var.trace_add("write", lambda *_: self._refresh_unless_batching())
        for var in (self.cache_var, self.stats_var):
            var.trace_add("write", lambda *_: self._source_paths_changed())
        self.load_cached_data()

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=theme.BG_TABLE, foreground=theme.TEXT_TABLE, fieldbackground=theme.BG_TABLE,
                        rowheight=27, borderwidth=0, font=theme.FONT_BODY)
        style.configure("Treeview.Heading", background=theme.BG_TABLE_HEADING, foreground=theme.TEXT_HEADING, relief="flat",
                        font=theme.FONT_BODY_BOLD)
        style.map("Treeview", background=[("selected", theme.SELECTION_BG)], foreground=[("selected", theme.TEXT_ON_ACCENT)])
        style.configure("TCombobox", fieldbackground=theme.BG_INPUT, background=theme.BG_INPUT, foreground=theme.TEXT_PRIMARY)
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", "focus", theme.BG_INPUT),
                ("readonly", "pressed", theme.BG_INPUT),
                ("readonly", theme.BG_INPUT),
                ("focus", theme.BG_INPUT),
                ("pressed", theme.BG_INPUT),
                ("active", theme.BG_INPUT),
            ],
            foreground=[
                ("disabled", theme.TEXT_DISABLED),
                ("readonly", "focus", theme.TEXT_PRIMARY),
                ("readonly", "pressed", theme.TEXT_PRIMARY),
                ("readonly", theme.TEXT_PRIMARY),
                ("focus", theme.TEXT_PRIMARY),
                ("pressed", theme.TEXT_PRIMARY),
                ("active", theme.TEXT_PRIMARY),
            ],
            selectbackground=[("readonly", theme.ACCENT_BG), ("focus", theme.ACCENT_BG)],
            selectforeground=[("readonly", theme.WHITE), ("focus", theme.WHITE)],
            background=[("pressed", theme.BG_INPUT), ("active", theme.BG_INPUT)],
            arrowcolor=[("disabled", theme.TEXT_DISABLED), ("!disabled", theme.TEXT_PRIMARY)],
        )
        style.configure("Horizontal.TProgressbar", troughcolor=theme.BG_TABLE_HEADING, background=theme.ACCENT)
        self.root.option_add("*TCombobox*Listbox.background", theme.BG_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme.ACCENT_BG)
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme.WHITE)

    def _build(self):
        top = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=18, pady=14)
        top.pack(fill="x")
        tk.Label(top, text="ITGmania Library", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_APP_TITLE).pack(side="left")
        self.status = tk.StringVar(value="Choose your cache's Songs folder and player Stats.xml to get started.")
        tk.Label(top, textvariable=self.status, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="right", padx=8)
        paths = tk.Frame(self.root, bg=theme.BG_PANEL, padx=12, pady=10)
        paths.pack(fill="x", padx=18)
        self._path_row(paths, "Cache / Songs", self.cache_var, self.choose_cache)
        self._path_row(paths, "Player Stats.xml", self.stats_var, self.choose_stats)
        bar = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=18, pady=12)
        bar.pack(fill="x")
        tk.Label(bar, text="Search", fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(side="left", padx=(0, 6))
        self.search_entry = self._entry(bar, "", self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._button(bar, "Advanced…", self.open_advanced_search).pack(side="left", padx=(0, 8))
        self.pack_filter = self._combo(bar, self.pack_var, ["All packs"])
        self.pack_filter.pack(side="left", padx=4)
        self.type_filter = self._combo(bar, self.type_var, ["All types"])
        self.type_filter.pack(side="left", padx=4)
        self.diff_filter = self._combo(bar, self.diff_var, ["All difficulties"])
        self.diff_filter.pack(side="left", padx=4)
        tk.Checkbutton(bar, text="Scored only", variable=self.scored_var, bg=theme.BG_WINDOW, fg=theme.TEXT_LABEL,
                       activebackground=theme.BG_WINDOW, activeforeground=theme.TEXT_ON_ACCENT, selectcolor=theme.BG_INPUT,
                       font=theme.FONT_BODY).pack(side="left", padx=9)
        self._button(bar, "Load / refresh", self.load_data, primary=True).pack(side="left", padx=4)
        self._button(bar, "Export CSV", self.export_csv).pack(side="left", padx=4)
        self._button(bar, "Build course…", self.open_course_builder).pack(side="left", padx=4)
        self.dist_button = self._button(
            bar,
            "Distribution ◀" if self.show_distribution_panel.get() else "Distribution ▶",
            self.toggle_distribution_panel,
        )
        self.dist_button.pack(side="left", padx=4)
        self.content_frame = tk.Frame(self.root, bg=theme.BG_WINDOW)
        self.content_frame.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self._build_distribution_panel()
        if self.show_distribution_panel.get():
            self.dist_panel.pack(side="right", fill="y", padx=(10, 0))
        self.table_frame = tk.Frame(self.content_frame, bg=theme.BG_WINDOW)
        self.table_frame.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(self.table_frame, columns=HEADERS, show="headings", selectmode="extended")
        for col in HEADERS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            width = 130 if col in ("Title", "Artist", "Pack") else 92
            if col in ("Type", "Difficulty", "Meter", "Time", "BPM", "Score", "Grade", "Best %", "Plays", "Jumps", "Holds",
                       "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5", "Miss"):
                width = 76
            if col == "Last played":
                width = 105
            if col == "Chart":
                width = 150
            self.default_column_widths[col] = width
            width = self.column_widths[col] or width
            self.tree.column(col, width=width, minwidth=55, stretch=False, anchor="w" if col in
                             ("Title", "Artist", "Pack", "Chart") else "center")
        vs = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(self.table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)
        self.tree.bind("<ButtonPress-1>", self._column_drag_start, add="+")
        self.tree.bind("<ButtonRelease-1>", self._column_drag_end, add="+")
        self.tree.bind("<ButtonRelease-1>", self._shift_sort_click, add="+")
        self.tree.bind("<ButtonRelease-1>", self._save_settings, add="+")
        visible_columns = [column for column in self.column_order if self.column_visibility[column].get()]
        if visible_columns:
            self.tree.configure(displaycolumns=visible_columns)
        self._update_sort_headings()
        self._setup_tree_tags()
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select, add="+")
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=18, pady=(0, 4))
        footer = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=18, pady=7)
        footer.pack(fill="x")
        self.count_label = tk.StringVar(value="0 charts")
        tk.Label(footer, textvariable=self.count_label, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left")
        tk.Label(footer, text="Click to sort · Shift-click adds sort keys · Drag headings to reorder · Drag dividers to resize",
                 fg=theme.TEXT_FOOTER, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(side="right")
        self._build_menubar()

    def _build_menubar(self):
        menubar = tk.Menu(self.root, tearoff=False)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Load / refresh library", command=self.load_data)
        file_menu.add_command(label="Export CSV…", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Find", accelerator="Ctrl+F", command=self.focus_search)
        edit_menu.add_command(label="Advanced search…", accelerator="Ctrl+Shift+F", command=self.open_advanced_search)
        edit_menu.add_command(label="Clear search", accelerator="Esc", command=self.clear_search)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        columns_menu = tk.Menu(view_menu, tearoff=False)
        for group, columns in COLUMN_GROUPS.items():
            group_menu = tk.Menu(columns_menu, tearoff=False)
            group_menu.add_checkbutton(
                label="Show whole group",
                variable=self.group_visibility[group],
                command=lambda name=group: self._group_visibility_changed(name),
            )
            group_menu.add_separator()
            for column in columns:
                group_menu.add_checkbutton(
                    label=column,
                    variable=self.column_visibility[column],
                    command=lambda col=column: self._column_visibility_changed(col),
                )
            columns_menu.add_cascade(label=group, menu=group_menu)
        view_menu.add_cascade(label="Columns", menu=columns_menu)
        view_menu.add_command(label="Reset column layout", command=self.reset_column_layout)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Show distribution panel",
            variable=self.show_distribution_panel,
            command=self._sync_distribution_toggle,
        )
        menubar.add_cascade(label="View", menu=view_menu)
        self.root.configure(menu=menubar)
        self.root.bind("<Control-f>", lambda _event: self.focus_search())
        self.root.bind("<Control-F>", lambda _event: self.focus_search())
        self.root.bind("<Control-Shift-f>", lambda _event: self.open_advanced_search())
        self.root.bind("<Control-Shift-F>", lambda _event: self.open_advanced_search())
        self.root.bind("<Escape>", self._on_main_escape)

    @staticmethod
    def _settings_file_path():
        appdata = os.getenv("APPDATA")
        if appdata:
            config_root = Path(appdata)
        elif os.name == "nt":
            config_root = Path.home() / "AppData" / "Roaming"
        elif sys.platform == "darwin":
            config_root = Path.home() / "Library" / "Application Support"
        else:
            config_root = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        return config_root / "ITGmania Library Visualizer" / "settings.json"

    @property
    def library_cache_path(self):
        return self.settings_path.with_name("library_cache.json")

    @staticmethod
    def _normalized_source_path(path):
        return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))

    def _save_library_cache(self, cache_dir, stats_file, rows, files, skipped_files,
                            files_without_charts, nested_song_tree):
        refreshed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        payload = {
            "schema_version": LIBRARY_CACHE_SCHEMA_VERSION,
            "cache_dir": str(cache_dir),
            "stats_file": str(stats_file),
            "refreshed_at": refreshed_at,
            "files": files,
            "skipped_files": skipped_files,
            "files_without_charts": files_without_charts,
            "nested_song_tree": nested_song_tree,
            "rows": rows,
        }
        path = self.library_cache_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return refreshed_at

    def load_cached_data(self):
        try:
            with self.library_cache_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            self.status.set("No saved library snapshot yet. Choose your paths, then click Load / refresh.")
            self.refresh_table()
            return
        except (OSError, json.JSONDecodeError) as exc:
            self.status.set(f"Saved library snapshot could not be read ({exc}). Click Load / refresh to rebuild it.")
            self.refresh_table()
            return

        valid_rows = isinstance(payload, dict) and isinstance(payload.get("rows"), list) \
            and all(isinstance(row, dict) and all(key in row for key in (*HEADERS, "Course path"))
                    for row in payload["rows"])
        if (not valid_rows or payload.get("schema_version") != LIBRARY_CACHE_SCHEMA_VERSION
                or not isinstance(payload.get("cache_dir"), str)
                or not isinstance(payload.get("stats_file"), str)):
            self.status.set("Saved library snapshot is invalid or outdated. Click Load / refresh to rebuild it.")
            self.refresh_table()
            return

        paths_match = (
            self._normalized_source_path(payload.get("cache_dir", ""))
            == self._normalized_source_path(self.cache_var.get())
            and self._normalized_source_path(payload.get("stats_file", ""))
            == self._normalized_source_path(self.stats_var.get())
        )
        if not paths_match:
            self.status.set("Saved library snapshot is for different data paths. Click Load / refresh to rebuild it.")
            self.refresh_table()
            return

        self._loaded(
            payload["rows"], self._nonnegative_int(payload.get("files")),
            self._nonnegative_int(payload.get("skipped_files")),
            self._nonnegative_int(payload.get("files_without_charts")),
            payload.get("nested_song_tree") is True,
            refreshed_at=payload.get("refreshed_at", "") if isinstance(payload.get("refreshed_at", ""), str) else "",
            from_cache=True,
            source_paths=(payload["cache_dir"], payload["stats_file"]),
        )

    @staticmethod
    def _nonnegative_int(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def _source_paths_changed(self):
        if not self.loaded_source_paths:
            return
        current = (self.cache_var.get(), self.stats_var.get())
        paths_match = all(
            self._normalized_source_path(saved) == self._normalized_source_path(selected)
            for saved, selected in zip(self.loaded_source_paths, current)
        )
        if paths_match:
            stamp = self._format_refresh_time(getattr(self, "last_refreshed_at", ""))
            self.status.set(f"Showing saved library snapshot · {len(self.rows):,} charts · last refreshed {stamp}.")
        else:
            self.status.set("Displayed library uses different data paths. Click Load / refresh to show the selected sources.")

    @staticmethod
    def _valid_column_width(value, column):
        try:
            width = int(value)
        except (TypeError, ValueError):
            return None
        return width if 55 <= width <= 2000 else None

    def _read_settings(self):
        try:
            with self.settings_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self, _event=None):
        if not hasattr(self, "tree"):
            return
        settings = {
            "cache_dir": self.cache_var.get(),
            "stats_file": self.stats_var.get(),
            "column_order": self.column_order,
            "column_visibility": {column: variable.get() for column, variable in self.column_visibility.items()},
            "column_widths": {column: self.tree.column(column, "width") for column in HEADERS},
            "sort_keys": [[column, descending] for column, descending in self.sort_keys],
            "show_distribution": self.show_distribution_panel.get() if hasattr(self, "show_distribution_panel") else False,
            "distribution_metric": self.distribution_metric.get() if hasattr(self, "distribution_metric") else "Meter",
        }
        temporary = self.settings_path.with_suffix(".tmp")
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=2)
            os.replace(temporary, self.settings_path)
        except OSError as exc:
            if hasattr(self, "status"):
                self.status.set(f"Could not save settings: {exc}")

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _dialog_is_open(self):
        for name in ("advanced_search_window", "course_window"):
            window = getattr(self, name, None)
            if window is not None and window.winfo_exists():
                return True
        return False

    def _on_main_escape(self, _event=None):
        # Escape in a dialog is handled by the dialog. This covers focus left in the main window while a
        # dialog is open, where Escape should not silently wipe the search bar.
        if not self._dialog_is_open():
            self.clear_search()

    def _refresh_unless_batching(self):
        if not self._batching_filter_changes:
            self.refresh_table()

    @contextlib.contextmanager
    def _batched_filter_changes(self):
        """Change several filter variables, then refresh the table once.

        Each filter variable refreshes the table by itself when it changes (the search box after a
        short delay), so one chart click that sets two of them would rebuild the table and the chart
        several times. Inside this block those automatic refreshes are skipped, and one refresh runs
        when the block ends.
        """
        self._batching_filter_changes = True
        try:
            yield
        finally:
            self._batching_filter_changes = False
        if self._search_refresh_after_id is not None:
            self.root.after_cancel(self._search_refresh_after_id)
            self._search_refresh_after_id = None
        self.refresh_table()

    def _schedule_search_refresh(self):
        """Refresh the table once the user pauses typing in the search box."""
        if self._batching_filter_changes:
            return
        if self._search_refresh_after_id is not None:
            self.root.after_cancel(self._search_refresh_after_id)
        self._search_refresh_after_id = self.root.after(
            SEARCH_DEBOUNCE_MS, self._run_search_refresh)

    def _run_search_refresh(self):
        self._search_refresh_after_id = None
        self.refresh_table()

    def _column_visibility_changed(self, changed_column):
        visible = [column for column in self.column_order if self.column_visibility[column].get()]
        if not visible:
            self.column_visibility[changed_column].set(True)
            return
        self._sync_group_checks()
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def _sync_group_checks(self):
        for group, variable in self.group_visibility.items():
            variable.set(all(self.column_visibility[column].get() for column in COLUMN_GROUPS[group]))

    def _group_visibility_changed(self, group):
        """Show or hide every column of a group at once, then redraw and save a single time."""
        show = self.group_visibility[group].get()
        previous = {column: self.column_visibility[column].get() for column in COLUMN_GROUPS[group]}
        for column in previous:
            self.column_visibility[column].set(show)
        visible = [column for column in self.column_order if self.column_visibility[column].get()]
        if not visible:
            # Same rule as a single column: at least one column must stay on, so the click is undone.
            for column, was_visible in previous.items():
                self.column_visibility[column].set(was_visible)
            self._sync_group_checks()
            return
        self._sync_group_checks()
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def reset_column_layout(self):
        self.column_order = list(HEADERS)
        for column, variable in self.column_visibility.items():
            variable.set(column in DEFAULT_VISIBLE_COLUMNS)
        self._sync_group_checks()
        for column, width in self.default_column_widths.items():
            self.tree.column(column, width=width)
        visible = [column for column in self.column_order if self.column_visibility[column].get()]
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def _column_drag_start(self, event):
        if self.tree.identify_region(event.x, event.y) == "heading":
            column = self._displayed_column_at(event.x, event.y)
            self._dragged_column = column
            self._drag_start_x = event.x
        else:
            self._dragged_column = None
            self._drag_start_x = None

    def _column_drag_end(self, event):
        source = getattr(self, "_dragged_column", None)
        start_x = getattr(self, "_drag_start_x", None)
        self._dragged_column = None
        self._drag_start_x = None
        if source is None or start_x is None or abs(event.x - start_x) < 5:
            return
        target = self._displayed_column_at(event.x, event.y)
        if target is None or target == source:
            return
        visible = [column for column in self.column_order if self.column_visibility[column].get()]
        target_index = visible.index(target)
        bounds = self._displayed_column_bounds(target_index)
        insert_after = bounds is not None and event.x >= (bounds[0] + bounds[1]) / 2
        self.column_order.remove(source)
        insert_at = self.column_order.index(target) + int(insert_after)
        self.column_order.insert(insert_at, source)
        visible = [column for column in self.column_order if self.column_visibility[column].get()]
        self.tree.configure(displaycolumns=visible)
        self._save_settings()
        return "break"

    def _displayed_column_at(self, x, y):
        if self.tree.identify_region(x, y) != "heading":
            return None
        display_id = self.tree.identify_column(x)
        try:
            index = int(display_id[1:]) - 1
            visible = [column for column in self.column_order if self.column_visibility[column].get()]
            return visible[index] if 0 <= index < len(visible) else None
        except (ValueError, IndexError):
            return None

    def _displayed_column_bounds(self, index):
        display_id = f"#{index + 1}"
        matches = [x for x in range(self.tree.winfo_width())
                   if self.tree.identify_column(x) == display_id]
        return (matches[0], matches[-1] + 1) if matches else None

    def _path_row(self, parent, label, variable, command):
        row = tk.Frame(parent, bg=theme.BG_PANEL)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, width=17, anchor="w", bg=theme.BG_PANEL, fg=theme.TEXT_FIELD_LABEL,
                 font=theme.FONT_BODY).pack(side="left")
        entry = self._entry(row, "", variable)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        self._button(row, "Browse…", command).pack(side="left")

    @staticmethod
    def _entry(parent, placeholder, variable):
        entry = tk.Entry(parent, textvariable=variable, bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY, insertbackground=theme.CURSOR,
                         relief="flat", font=theme.FONT_BODY, highlightthickness=1,
                         highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
        if placeholder:
            entry.insert(0, placeholder)
            entry.bind("<FocusIn>", lambda e: e.widget.delete(0, "end") if e.widget.get() == placeholder else None)
        return entry

    @staticmethod
    def _combo(parent, variable, values):
        return ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=18,
                            font=theme.FONT_BODY)

    @staticmethod
    def _button(parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg=theme.ACCENT_BG if primary else theme.BG_BUTTON,
                         fg=theme.TEXT_ON_ACCENT, activebackground=theme.ACCENT_BG_HOVER if primary else theme.BG_BUTTON_HOVER,
                         activeforeground=theme.TEXT_ON_ACCENT, relief="flat", padx=11, pady=7,
                         font=theme.FONT_BODY_BOLD, cursor="hand2")

    def choose_cache(self):
        path = filedialog.askdirectory(title="Select the ITGmania Cache/Songs folder")
        if path:
            self.cache_var.set(path)
            self._save_settings()

    def choose_stats(self):
        path = filedialog.askopenfilename(title="Select player Stats.xml", filetypes=[("Stats.xml", "Stats.xml"),
                                                                                       ("XML files", "*.xml"),
                                                                                       ("All files", "*.*")])
        if path:
            self.stats_var.set(path)
            self._save_settings()

    def load_data(self):
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not cache.is_dir():
            messagebox.showerror("Cache folder not found", "Select the ITGmania Cache/Songs folder.")
            return
        if not stats.is_file():
            messagebox.showerror("Stats.xml not found", "Select the player's Stats.xml file.")
            return
        self._save_settings()
        self.progress.start(12)
        self.status.set("Reading chart cache and player scores…")
        self._load_generation += 1
        generation = self._load_generation
        threading.Thread(target=self._load_worker, args=(cache, stats, generation), daemon=True).start()

    def _load_is_stale(self, generation):
        return self._load_generation != generation

    def _load_worker(self, cache: Path, stats_file: Path, generation: int):
        # A scan whose generation is no longer the latest stops quietly. The newer scan keeps the
        # progress bar running, and _loaded / _load_failed ignore anything from an older generation.
        try:
            scores = stats_index(stats_file)
            rows = []
            files = [p for p in cache.iterdir() if p.is_file()]
            skipped_files = 0
            files_without_charts = 0
            for path in files:
                if self._load_is_stale(generation):
                    return
                try:
                    chart_rows = parse_cache_file(path, scores)
                    if not chart_rows:
                        files_without_charts += 1
                    rows.extend(chart_rows)
                except (OSError, UnicodeError):
                    skipped_files += 1

            nested_song_tree = looks_like_song_tree(cache) if not files else False
            cache_error = ""
            # The generation check and the snapshot write happen under one lock. Without it, an older
            # scan that passed the check could still be writing after a newer scan had written its
            # own snapshot, leaving the older data on disk.
            with self._snapshot_lock:
                if self._load_is_stale(generation):
                    return
                try:
                    refreshed_at = self._save_library_cache(
                        cache, stats_file, rows, len(files), skipped_files,
                        files_without_charts, nested_song_tree)
                except (OSError, TypeError, ValueError) as exc:
                    refreshed_at = ""
                    cache_error = str(exc)

            self.root.after(0, lambda: self._loaded(
                rows, len(files), skipped_files, files_without_charts, nested_song_tree,
                refreshed_at=refreshed_at, cache_error=cache_error,
                source_paths=(str(cache), str(stats_file)),
                generation=generation))
        except ET.ParseError as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(
                f"Stats.xml is malformed or incomplete and could not be parsed.\n\n{message}",
                generation=generation))
        except OSError as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(
                f"Could not read the selected cache folder or Stats.xml.\n\n{message}",
                generation=generation))
        except Exception as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(message, generation=generation))

    def _load_failed(self, message, generation=None):
        if generation is not None and self._load_is_stale(generation):
            return
        self.progress.stop()
        self.status.set("Could not load library.")
        messagebox.showerror("Could not load library", message)

    def _loaded(self, rows, files, skipped_files=0, files_without_charts=0, nested_song_tree=False,
                refreshed_at="", cache_error="", from_cache=False, source_paths=None, generation=None):
        if generation is not None and self._load_is_stale(generation):
            return
        self.progress.stop()
        self.rows = rows
        if source_paths:
            self.loaded_source_paths = source_paths
        self.last_refreshed_at = refreshed_at
        for combo, var, label, key in ((self.pack_filter, self.pack_var, "All packs", "Pack"),
                                       (self.type_filter, self.type_var, "All types", "Type")):
            values = [label] + sorted({str(r[key]) for r in rows if r[key]}, key=str.casefold)
            combo.configure(values=values)
            var.set(label)
        difficulties = sorted(
            {str(row["Difficulty"]) for row in rows if row["Difficulty"]},
            key=difficulty_sort_key,
        )
        self.diff_filter.configure(values=["All difficulties"] + difficulties)
        self.diff_var.set("All difficulties")
        if from_cache:
            stamp = self._format_refresh_time(refreshed_at)
            self.status.set(f"Showing saved library snapshot · {len(rows):,} charts · last refreshed {stamp}.")
        elif files == 0:
            hint = " This looks like a regular Songs tree; select the flat Cache/Songs folder instead." \
                if nested_song_tree else " Select the flat Cache/Songs folder."
            self.status.set("No files found at this folder level." + hint)
        else:
            summary = f"Scanned {files:,} files · parsed {len(rows):,} charts"
            if skipped_files:
                summary += f" · skipped {skipped_files:,} unreadable"
            if files_without_charts:
                summary += f" · {files_without_charts:,} with no charts"
            self.status.set(summary + ".")
        if not from_cache and refreshed_at:
            self.status.set(self.status.get() + f" Snapshot refreshed {self._format_refresh_time(refreshed_at)}.")
        if not from_cache and cache_error:
            self.status.set(self.status.get() + f" Local snapshot not saved: {cache_error}")
        self.refresh_table()

    @staticmethod
    def _format_refresh_time(value):
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return "unknown"

    def _filter_rows(self, ignore_metric=None):
        """Return the rows that pass the pack, type, difficulty, scored and search filters.

        ignore_metric ("Meter", "Difficulty" or "BPM") leaves out that chart's own filter, both the
        search directive and, for Difficulty, the dropdown. The distribution chart uses this to keep
        showing every bar after you click one.
        """
        query_text = self.search_var.get().strip()
        criteria = parse_search_query(query_text) if query_text else None
        ignored_field = CHART_FILTER_FIELDS.get(ignore_metric)
        if criteria and ignored_field:
            criteria = {**criteria, "directives": [
                directive for directive in criteria["directives"] if directive[0] != ignored_field]}
        pack, chart_type, diff = self.pack_var.get(), self.type_var.get(), self.diff_var.get()
        if ignore_metric == "Difficulty":
            diff = "All difficulties"
        rows = []
        for row in self.rows:
            if pack != "All packs" and row["Pack"] != pack:
                continue
            if chart_type != "All types" and row["Type"] != chart_type:
                continue
            if diff != "All difficulties" and row["Difficulty"] != diff:
                continue
            if self.scored_var.get() and not row["Grade"]:
                continue
            if criteria and not match_chart_query(row, criteria):
                continue
            rows.append(row)
        return rows

    def refresh_table(self, preserve_selection=False):
        if not hasattr(self, "tree"):
            return
        selected_rows = set()
        if preserve_selection:
            selected_rows = {
                id(self.tree_item_rows[item]) for item in self.tree.selection()
                if item in getattr(self, "tree_item_rows", {})
            }
        self._render_generation = getattr(self, "_render_generation", 0) + 1
        generation = self._render_generation
        self._update_sort_headings()
        visible = self._filter_rows()
        for column, descending in reversed(self.sort_keys):
            present = [row for row in visible if row.get(column) not in (None, "")]
            missing = [row for row in visible if row.get(column) in (None, "")]
            if column in NUMERIC_COLUMNS:
                present.sort(key=lambda row: number(str(row.get(column))), reverse=descending)
            elif column == "Difficulty":
                present.sort(key=lambda row: difficulty_sort_key(row.get(column, "")), reverse=descending)
            elif column == "BPM":
                present.sort(key=bpm_sort_key, reverse=descending)
            elif column == "Grade":
                present.sort(key=lambda row: grade_sort_key(row.get(column, "")), reverse=descending)
            else:
                present.sort(key=lambda row: str(row.get(column, "")).casefold(), reverse=descending)
            visible = present + missing
        self.tree.delete(*self.tree.get_children())
        self.tree_item_rows = {}
        self._selected_tree_items = set()
        self._insert_batch(visible, 0, generation, selected_rows)
        self.count_label.set(f"{len(visible):,} charts shown · {len(self.rows):,} total")
        self._update_distribution_panel(visible)

    def _update_sort_headings(self):
        priorities = {column: (index, descending) for index, (column, descending) in enumerate(self.sort_keys, 1)}
        for column in HEADERS:
            if column in priorities:
                index, descending = priorities[column]
                marker = "↓" if descending else "↑"
                heading = f"{column} {marker}{index}"
            else:
                heading = column
            self.tree.heading(column, text=heading)

    def _setup_tree_tags(self):
        for diff, color in theme.DIFFICULTY_COLORS.items():
            self.tree.tag_configure(f"diff_{diff}", foreground=color)
        self.tree.tag_configure(UNKNOWN_DIFFICULTY_TAG, foreground=theme.DIFFICULTY_COLOR_UNKNOWN)
        # Keep this one last: in this order a selected row shows white text instead of its difficulty
        # color (checked in the window on Windows). A row has both tags while it is selected.
        self.tree.tag_configure("selected_row", foreground=theme.TEXT_ON_ACCENT)

    @staticmethod
    def _difficulty_tag(row):
        name = str(row.get("Difficulty", "")).strip()
        return f"diff_{name}" if name in theme.DIFFICULTY_COLORS else UNKNOWN_DIFFICULTY_TAG

    def _on_tree_select(self, _event=None):
        """Give the white "selected_row" tag to the rows that just became selected and take it from the rest."""
        current = set(self.tree.selection())
        for item in self._selected_tree_items - current:
            if self.tree.exists(item):  # a refresh may have removed the row already
                self._set_selected_tag(item, False)
        for item in current - self._selected_tree_items:
            self._set_selected_tag(item, True)
        self._selected_tree_items = current

    def _set_selected_tag(self, item, selected):
        tags = [tag for tag in self.tree.item(item, "tags") if tag != "selected_row"]
        if selected:
            tags.append("selected_row")
        self.tree.item(item, tags=tags)

    def _insert_batch(self, rows, start, generation, selected_rows=None):
        if generation != self._render_generation:
            return
        selected_rows = selected_rows or set()
        stop = min(start + 500, len(rows))
        for row in rows[start:stop]:
            values = []
            for col in HEADERS:
                value = row.get(col, "")
                if col == "Time" and value != "":
                    value = format_duration(value)
                elif isinstance(value, float):
                    value = f"{value:g}"
                values.append(value)
            tags = [self._difficulty_tag(row)]
            keep_selected = id(row) in selected_rows
            if keep_selected:
                tags.append("selected_row")
            item = self.tree.insert("", "end", values=values, tags=tuple(tags))
            self.tree_item_rows[item] = row
            if keep_selected:
                self.tree.selection_add(item)
                self._selected_tree_items.add(item)
        if stop < len(rows):
            self.root.after(1, lambda: self._insert_batch(rows, stop, generation, selected_rows))

    def _build_distribution_panel(self):
        self.dist_panel = tk.Frame(self.content_frame, bg=theme.BG_PANEL, width=DIST_PANEL_WIDTH, padx=10, pady=10)
        self.dist_panel.pack_propagate(False)

        # Header: Title + Close button
        hdr = tk.Frame(self.dist_panel, bg=theme.BG_PANEL)
        hdr.pack(fill="x", pady=(0, 6))
        tk.Label(hdr, text="Distribution", fg=theme.TEXT_TITLE, bg=theme.BG_PANEL,
                 font=theme.FONT_PANEL_TITLE).pack(side="left")
        self._button(hdr, "✕", self.toggle_distribution_panel).pack(side="right")

        # Metric selector
        metric_bar = tk.Frame(self.dist_panel, bg=theme.BG_PANEL)
        metric_bar.pack(fill="x", pady=(4, 6))
        for m in ("Meter", "Difficulty", "BPM"):
            b = tk.Radiobutton(
                metric_bar, text=m, value=m, variable=self.distribution_metric,
                indicatoron=False, bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY, selectcolor=theme.ACCENT_BG,
                activebackground=theme.ACCENT_BG, activeforeground=theme.WHITE, font=theme.FONT_SMALL,
                command=self._on_distribution_metric_changed, padx=6, pady=3,
            )
            b.pack(side="left", padx=2, expand=True, fill="x")

        # Summary line
        self.dist_summary_var = tk.StringVar(value="")
        tk.Label(self.dist_panel, textvariable=self.dist_summary_var, fg=theme.TEXT_MUTED, bg=theme.BG_PANEL,
                 font=theme.FONT_SMALL, wraplength=DIST_PANEL_WIDTH - 24, justify="left").pack(fill="x", pady=(0, 6))

        # Active filter banner: shown just above the chart, only while a chart filter is active.
        # It is built here but not packed; _update_distribution_panel packs it before the chart container.
        self.dist_banner_frame = tk.Frame(self.dist_panel, bg=theme.BG_INPUT, padx=8, pady=5)
        self.dist_banner_label = tk.Label(self.dist_banner_frame, text="", fg=theme.ACCENT, bg=theme.BG_INPUT,
                                          font=theme.FONT_BODY, wraplength=DIST_PANEL_WIDTH - 90,
                                          justify="left", anchor="w")
        self.dist_banner_label.pack(side="left", fill="x", expand=True)
        self._button(self.dist_banner_frame, "Clear", self.clear_chart_filter).pack(side="right")

        # Chart container
        self.dist_chart_frame = tk.Frame(self.dist_panel, bg=theme.BG_PANEL)
        self.dist_chart_frame.pack(fill="both", expand=True)

        if not MATPLOTLIB_AVAILABLE:
            tk.Label(
                self.dist_chart_frame,
                text="Install matplotlib to enable\ndistribution charts\n\nRun:\npip install matplotlib",
                fg=theme.TEXT_MUTED, bg=theme.BG_PANEL, font=theme.FONT_BODY, justify="center",
            ).pack(expand=True, pady=40)

    def _ensure_distribution_canvas(self):
        if not MATPLOTLIB_AVAILABLE:
            return False
        if self.dist_canvas is None:
            self.dist_fig = Figure(figsize=(3.0, 4.0), dpi=100, facecolor=theme.BG_PANEL)
            self.dist_ax = self.dist_fig.add_subplot(111)
            self.dist_canvas = FigureCanvasTkAgg(self.dist_fig, master=self.dist_chart_frame)
            self.dist_canvas.mpl_connect("button_press_event", self._on_chart_click)
            # No resize binding is needed here: the canvas widget fills the chart frame, and matplotlib's
            # Tk canvas already resizes the figure and redraws when its widget changes size.
            self.dist_canvas.get_tk_widget().pack(fill="both", expand=True)
        return True

    def _set_distribution_visible(self, visible: bool):
        """Single source of truth for panel visibility (toolbar + View menu)."""
        if not hasattr(self, "dist_panel"):
            return
        self.show_distribution_panel.set(visible)
        if visible:
            self.dist_panel.pack(side="right", fill="y", padx=(10, 0), before=self.table_frame)
            self.dist_button.configure(text="Distribution ◀")
            self._update_distribution_panel(getattr(self, "_last_visible_rows", []))
        else:
            self.dist_panel.pack_forget()
            self.dist_button.configure(text="Distribution ▶")
            self.root.update_idletasks()
        self._save_settings()

    def toggle_distribution_panel(self):
        """Toolbar button: flip current visibility."""
        self._set_distribution_visible(not self.show_distribution_panel.get())

    def _sync_distribution_toggle(self):
        """View-menu checkbutton: BooleanVar already toggled by Tk; apply it to the UI."""
        self._set_distribution_visible(self.show_distribution_panel.get())

    def _on_distribution_metric_changed(self):
        self._save_settings()
        self._update_distribution_panel(getattr(self, "_last_visible_rows", []))

    def clear_chart_filter(self):
        """Remove every filter the distribution charts can set (difficulty, meter and BPM)."""
        active = get_active_chart_filters(self.diff_var.get(), self.search_var.get())
        if not active:
            return
        query = self.search_var.get()
        with self._batched_filter_changes():
            for metric, _ in active:
                if metric == "Difficulty":
                    self.diff_var.set("All difficulties")
                query = replace_search_directive(query, CHART_FILTER_FIELDS[metric], None)
            self.search_var.set(query)
        if hasattr(self, "search_entry"):
            self.search_entry.icursor("end")

    def _on_chart_click(self, event):
        # xdata and ydata are None when the click is outside the plot area (for example on a row label).
        if event.xdata is None or event.ydata is None or not self._current_dist_bars:
            return
        clicked = next(
            (bar for bar in self._current_dist_bars
             if bar.y_min <= event.ydata <= bar.y_max and 0 <= event.xdata <= bar.click_width),
            None,
        )
        if clicked is None or not clicked.token or clicked.label == "?":
            # Blank space, a '?' row or a row with nothing to filter to is not clickable.
            return
        target_token = clicked.token

        metric = self.distribution_metric.get()
        query = self.search_var.get()
        current = dict(get_active_chart_filters(self.diff_var.get(), query)).get(metric)
        already_active = current is not None and filter_texts_match(current, target_token)

        with self._batched_filter_changes():
            if metric == "Difficulty":
                self.diff_var.set("All difficulties" if already_active else target_token)
                # Remove redundant diff from search bar so they don't fight
                new_query = replace_search_directive(query, "diff", None)
                if new_query != query:
                    self.search_var.set(new_query)
            else:
                new_query = replace_search_directive(
                    query, CHART_FILTER_FIELDS[metric], None if already_active else target_token)
                self.search_var.set(new_query)

        if hasattr(self, "search_entry"):
            self.search_entry.icursor("end")

    def _metric_filter_present(self, metric):
        """Whether the table is currently filtered by this chart's own metric."""
        if metric == "Difficulty" and self.diff_var.get() != "All difficulties":
            return True
        field = CHART_FILTER_FIELDS[metric]
        directives = parse_search_query(self.search_var.get()).get("directives", [])
        return any(directive_field == field for directive_field, _ in directives)

    def _distribution_rows(self, metric):
        """Rows behind the chart: every filter except the chart's own, so all bars stay visible."""
        if self._metric_filter_present(metric):
            return self._filter_rows(ignore_metric=metric)
        return self._last_visible_rows

    def _update_distribution_panel(self, visible_rows):
        self._last_visible_rows = visible_rows
        if not hasattr(self, "dist_panel") or not self.show_distribution_panel.get():
            return

        metric = self.distribution_metric.get()
        chart_rows = self._distribution_rows(metric)

        # Update active filter banner (every chart filter narrowing the table, not just this chart's)
        active_filters = get_active_chart_filters(self.diff_var.get(), self.search_var.get())
        if active_filters:
            banner = " · ".join(f"{name} {value}" for name, value in active_filters)
            self.dist_banner_label.configure(text=f"Filtered by: {banner}")
            self.dist_banner_frame.pack(fill="x", pady=(0, 6), before=self.dist_chart_frame)
        else:
            self.dist_banner_frame.pack_forget()

        # Update summary text
        self.dist_summary_var.set(distribution_summary_stats(metric, chart_rows))

        if not self._ensure_distribution_canvas():
            return

        # Redraw chart
        self.dist_ax.clear()
        self._current_dist_bars = []

        if not chart_rows:
            self.dist_ax.text(
                0.5, 0.5, "No charts match\ncurrent filters",
                color=theme.TEXT_MUTED, fontsize=theme.CHART_TEXT_SIZE_MESSAGE, ha="center", va="center",
                transform=self.dist_ax.transAxes,
            )
            self.dist_ax.axis("off")
            self.dist_canvas.draw_idle()
            return

        self.dist_ax.axis("on")
        active_val = dict(active_filters).get(metric)

        if metric == "Meter":
            data_items = aggregate_meter_distribution(chart_rows, active_val=active_val)
        elif metric == "Difficulty":
            data_items = aggregate_difficulty_distribution(chart_rows, active_val=active_val)
        else:  # BPM
            data_items = aggregate_bpm_distribution(chart_rows, active_val=active_val)

        labels = [item[0] for item in reversed(data_items)]
        counts = [item[1] for item in reversed(data_items)]
        tokens = [item[2] for item in reversed(data_items)]
        actives = [item[3] for item in reversed(data_items)]

        y_positions = list(range(len(labels)))
        bar_colors = []
        edge_colors = []
        linewidths = []

        for label, is_act in zip(labels, actives):
            if metric == "Difficulty":
                base_color = theme.DIFFICULTY_COLORS.get(label, theme.DIFFICULTY_COLOR_UNKNOWN)
            else:
                base_color = theme.ACCENT if label != "?" else theme.CHART_BAR_UNKNOWN

            bar_colors.append(base_color)
            if is_act:
                edge_colors.append(theme.WHITE)
                linewidths.append(1.5)
            else:
                edge_colors.append(theme.BG_INPUT)
                linewidths.append(0.8)

        bars = self.dist_ax.barh(
            y_positions, counts, align="center",
            color=bar_colors, edgecolor=edge_colors, linewidth=linewidths, height=0.68,
        )

        max_count = max(counts) if counts else 1
        axis_max = max_count * 1.25
        min_click_width = axis_max * CHART_MIN_CLICK_FRACTION
        for i, (bar, count) in enumerate(zip(bars, counts)):
            y = bar.get_y()
            h = bar.get_height()
            # An empty row has nothing to filter to, so it is not clickable, unless it is the active
            # filter, which has to stay clickable so that clicking it again can switch it off.
            clickable = counts[i] > 0 or actives[i]
            self._current_dist_bars.append(ChartBar(
                y, y + h, labels[i], tokens[i] if clickable else "", max(count, min_click_width)))
            if count > 0:
                self.dist_ax.text(
                    count + max_count * 0.03, y + h / 2, str(count),
                    va="center", ha="left", color=theme.TEXT_PRIMARY, fontsize=theme.CHART_TEXT_SIZE_COUNT,
                )

        self.dist_ax.set_yticks(y_positions)
        self.dist_ax.set_yticklabels(labels, color=theme.TEXT_PRIMARY, fontsize=theme.CHART_TEXT_SIZE_LABEL)
        self.dist_ax.set_xlim(0, axis_max)
        self.dist_ax.set_facecolor(theme.BG_PANEL)
        self.dist_fig.patch.set_facecolor(theme.BG_PANEL)
        self.dist_ax.tick_params(colors=theme.TEXT_MUTED, labelsize=theme.CHART_TEXT_SIZE_LABEL, left=False, bottom=True)
        self.dist_ax.spines["top"].set_visible(False)
        self.dist_ax.spines["right"].set_visible(False)
        self.dist_ax.spines["left"].set_visible(False)
        self.dist_ax.spines["bottom"].set_color(theme.CHART_AXIS_LINE)
        self.dist_fig.tight_layout(pad=1.0)
        self.dist_canvas.draw_idle()

    def _shift_sort_click(self, event):
        if not event.state & 0x0001 or self.tree.identify_region(event.x, event.y) != "heading":
            return
        column = self._displayed_column_at(event.x, event.y)
        if column is not None:
            self.sort_by(column, additive=True)
            return "break"

    def sort_by(self, column, additive=False):
        keys = list(self.sort_keys)
        existing_index = next((index for index, (name, _) in enumerate(keys) if name == column), None)
        if additive:
            if existing_index is None:
                keys.append((column, False))
            else:
                name, descending = keys[existing_index]
                keys[existing_index] = (name, not descending)
        else:
            if existing_index == 0:
                name, descending = keys[0]
                keys[0] = (name, not descending)
            else:
                keys = [(column, False)]
        self.sort_keys = keys
        self.refresh_table(preserve_selection=True)
        self._save_settings()

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo("No charts", "Load a library before exporting.")
            return
        path = filedialog.asksaveasfilename(title="Export chart library", defaultextension=".csv",
                                            filetypes=[("CSV files", "*.csv")],
                                            initialfile="itgmania-library.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)
        self.status.set(f"Exported {len(self.rows):,} charts to {path}")

    def open_advanced_search(self):
        if getattr(self, "advanced_search_window", None) is not None and self.advanced_search_window.winfo_exists():
            self.advanced_search_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.advanced_search_window = window
        window.title("Advanced Search")
        window.geometry("560x620")
        window.minsize(480, 520)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.root)

        tk.Label(window, text="Advanced Search", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_DIALOG_TITLE).pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(window, text="Set field filters and a minimum grade. Free-text terms are ANDed; quote phrases.",
                 fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(anchor="w", padx=18, pady=(0, 10))

        form = tk.Frame(window, bg=theme.BG_WINDOW, padx=18)
        form.pack(fill="both", expand=True)

        free_text_var = tk.StringVar()
        title_var = tk.StringVar()
        artist_var = tk.StringVar()
        pack_var = tk.StringVar()
        meter_min_var = tk.StringVar()
        meter_max_var = tk.StringVar()
        bpm_min_var = tk.StringVar()
        bpm_max_var = tk.StringVar()
        time_min_var = tk.StringVar()
        time_max_var = tk.StringVar()
        nps_min_var = tk.StringVar()
        nps_max_var = tk.StringVar()
        grade_min_var = tk.StringVar(value="Any")
        other_var = tk.StringVar()

        # Fill the boxes from the current search text; filters the boxes cannot show exactly
        # go in "Other filters" so that Apply keeps them.
        current = split_dialog_query(self.search_var.get())
        free_text_var.set(current["free_text"])
        title_var.set(current["title"])
        artist_var.set(current["artist"])
        pack_var.set(current["pack"])
        meter_min_var.set(current["meter"][0])
        meter_max_var.set(current["meter"][1])
        bpm_min_var.set(current["bpm"][0])
        bpm_max_var.set(current["bpm"][1])
        time_min_var.set(current["time"][0])
        time_max_var.set(current["time"][1])
        nps_min_var.set(current["peak_nps"][0])
        nps_max_var.set(current["peak_nps"][1])
        if current["grade"]:
            grade_min_var.set(current["grade"])
        other_var.set(current["other"])

        def add_text_row(parent, label_text, var):
            row = tk.Frame(parent, bg=theme.BG_WINDOW)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, width=12, anchor="w",
                     font=theme.FONT_BODY).pack(side="left")
            self._entry(row, "", var).pack(side="left", fill="x", expand=True)

        def add_range_row(parent, label_text, min_var, max_var, hint=""):
            row = tk.Frame(parent, bg=theme.BG_WINDOW)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, width=12, anchor="w",
                     font=theme.FONT_BODY).pack(side="left")
            e1 = self._entry(row, "", min_var)
            e1.pack(side="left", fill="x", expand=True)
            tk.Label(row, text="to", fg=theme.TEXT_HINT, bg=theme.BG_WINDOW, padx=8, font=theme.FONT_BODY).pack(side="left")
            e2 = self._entry(row, "", max_var)
            e2.pack(side="left", fill="x", expand=True)
            if hint:
                tk.Label(row, text=hint, fg=theme.TEXT_HINT, bg=theme.BG_WINDOW, font=theme.FONT_SMALL, padx=6).pack(side="left")

        add_text_row(form, "Text", free_text_var)
        add_text_row(form, "Title", title_var)
        add_text_row(form, "Artist", artist_var)
        add_text_row(form, "Pack", pack_var)

        tk.Frame(form, bg=theme.BG_INPUT, height=1).pack(fill="x", pady=10)

        add_range_row(form, "Meter", meter_min_var, meter_max_var)
        add_range_row(form, "BPM", bpm_min_var, bpm_max_var)
        add_range_row(form, "Time", time_min_var, time_max_var, "e.g. 1:30 or 90")
        add_range_row(form, "Peak NPS", nps_min_var, nps_max_var)

        g_row = tk.Frame(form, bg=theme.BG_WINDOW)
        g_row.pack(fill="x", pady=3)
        tk.Label(g_row, text="Min Grade", fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, width=12, anchor="w",
                 font=theme.FONT_BODY).pack(side="left")
        g_options = ["Any"] + list(GRADE_OPTIONS)
        self._combo(g_row, grade_min_var, g_options).pack(side="left")

        tk.Frame(form, bg=theme.BG_INPUT, height=1).pack(fill="x", pady=10)
        add_text_row(form, "Other filters", other_var)
        tk.Label(form, text="Kept from your search: filters without a box above. Edit or clear them here.",
                 fg=theme.TEXT_HINT, bg=theme.BG_WINDOW, font=theme.FONT_SMALL, anchor="w").pack(fill="x")

        preview_frame = tk.Frame(window, bg=theme.BG_PREVIEW, padx=12, pady=8)
        preview_frame.pack(fill="x", padx=18, pady=(10, 4))
        tk.Label(preview_frame, text="Query:", fg=theme.TEXT_MUTED, bg=theme.BG_PREVIEW,
                 font=theme.FONT_SMALL).pack(side="left", padx=(0, 6))
        query_preview = tk.Label(preview_frame, text="", fg=theme.TEXT_LABEL, bg=theme.BG_PREVIEW,
                                 font=theme.FONT_MONO_BOLD, anchor="w")
        query_preview.pack(side="left", fill="x", expand=True)

        def build_query():
            return build_dialog_query({
                "free_text": free_text_var.get(), "title": title_var.get(),
                "artist": artist_var.get(), "pack": pack_var.get(),
                "meter": (meter_min_var.get(), meter_max_var.get()),
                "bpm": (bpm_min_var.get(), bpm_max_var.get()),
                "time": (time_min_var.get(), time_max_var.get()),
                "peak_nps": (nps_min_var.get(), nps_max_var.get()),
                "grade": grade_min_var.get(), "other": other_var.get(),
            })

        def update_preview(*_):
            query_preview.config(text=build_query())

        for v in (free_text_var, title_var, artist_var, pack_var, meter_min_var, meter_max_var,
                  bpm_min_var, bpm_max_var, time_min_var, time_max_var, nps_min_var, nps_max_var, grade_min_var,
                  other_var):
            v.trace_add("write", update_preview)
        update_preview()

        btn_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=18, pady=12)
        btn_row.pack(fill="x", side="bottom")

        def apply_search():
            q = build_query()
            self.search_var.set(q)
            window.destroy()

        def clear_fields():
            for v in (free_text_var, title_var, artist_var, pack_var, meter_min_var, meter_max_var,
                      bpm_min_var, bpm_max_var, time_min_var, time_max_var, nps_min_var, nps_max_var,
                      other_var):
                v.set("")
            grade_min_var.set("Any")

        self._button(btn_row, "Apply", apply_search, primary=True).pack(side="right", padx=(6, 0))
        self._button(btn_row, "Close", window.destroy).pack(side="right")
        self._button(btn_row, "Clear", clear_fields).pack(side="left")

        def _close(_event=None):
            window.destroy()
            return "break"

        def _apply_and_close(_event=None):
            apply_search()
            return "break"

        window.bind("<Escape>", _close)
        window.bind("<Return>", _apply_and_close)

    def open_course_builder(self):
        if getattr(self, "course_window", None) is not None and self.course_window.winfo_exists():
            self.course_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.course_window = window
        window.title("Build a course")
        window.geometry("900x620")
        window.minsize(700, 440)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.root)
        self.course_entries: list[dict] = []

        tk.Label(window, text="Build a new course", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_COURSE_TITLE).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(window, text="Select charts in the library, then add them here and arrange the course order.",
                 fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(anchor="w", padx=18, pady=(0, 12))

        title_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=18)
        title_row.pack(fill="x", pady=(0, 10))
        tk.Label(title_row, text="Course title", width=13, anchor="w", fg=theme.TEXT_FIELD_LABEL, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left")
        self.course_title_var = tk.StringVar()
        tk.Entry(title_row, textvariable=self.course_title_var, bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY,
                 insertbackground=theme.CURSOR, relief="flat", font=theme.FONT_ENTRY_LARGE,
                 highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT).pack(
                     side="left", fill="x", expand=True)

        queue_frame = tk.Frame(window, bg=theme.BG_WINDOW)
        queue_frame.pack(fill="both", expand=True, padx=18)
        columns = ("Pack", "Title", "Type", "Difficulty", "Meter", "Time")
        self.course_tree = ttk.Treeview(queue_frame, columns=columns, show="headings", selectmode="extended")
        widths = {"Pack": 180, "Title": 300, "Type": 130, "Difficulty": 120, "Meter": 80, "Time": 80}
        for column in columns:
            self.course_tree.heading(column, text=column)
            self.course_tree.column(column, width=widths[column], minwidth=65, stretch=column == "Title",
                                    anchor="w" if column in ("Pack", "Title") else "center")
        queue_scroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.course_tree.yview)
        self.course_tree.configure(yscrollcommand=queue_scroll.set)
        self.course_tree.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")
        queue_frame.grid_rowconfigure(0, weight=1)
        queue_frame.grid_columnconfigure(0, weight=1)

        controls = tk.Frame(window, bg=theme.BG_WINDOW, padx=18, pady=12)
        controls.pack(fill="x")
        self._button(controls, "Add selected charts", self.add_selected_to_course, primary=True).pack(side="left")
        self._button(controls, "Remove", self.remove_course_entries).pack(side="left", padx=(8, 0))
        self._button(controls, "Move up", lambda: self.move_course_entry(-1)).pack(side="left", padx=(8, 0))
        self._button(controls, "Move down", lambda: self.move_course_entry(1)).pack(side="left", padx=(8, 0))
        self.course_count_var = tk.StringVar(value="0 charts · 0:00 total")
        tk.Label(controls, textvariable=self.course_count_var, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left", padx=12)
        self._button(controls, "Append to .CRS…", self.append_course).pack(side="right", padx=(0, 8))
        self._button(controls, "Save new .CRS…", self.export_course, primary=True).pack(side="right")

        def _close(_event=None):
            # Reopening this window starts an empty queue, so closing with charts queued loses them.
            queued = len(self.course_entries)
            if queued and not messagebox.askyesno(
                    "Discard course queue?",
                    f"Closing this window discards the {queued} queued chart(s). Close anyway?",
                    parent=window):
                return "break"
            window.destroy()
            return "break"

        window.bind("<Escape>", _close)

        self.add_selected_to_course()

    def add_selected_to_course(self):
        if not getattr(self, "course_entries", None):
            self.course_entries = []
        added = 0
        for item in self.tree.selection():
            row = getattr(self, "tree_item_rows", {}).get(item)
            if row is not None:
                self.course_entries.append(row)
                added += 1
        if added:
            self.refresh_course_queue()

    def refresh_course_queue(self, selected_indices=None):
        self.course_tree.delete(*self.course_tree.get_children())
        for index, row in enumerate(self.course_entries):
            self.course_tree.insert("", "end", iid=str(index), values=(
                row.get("Pack", ""), row.get("Title", ""), row.get("Type", ""),
                row.get("Difficulty", ""), row.get("Meter", ""),
                format_duration(row.get("Time", 0)) if row.get("Time", "") != "" else "",
            ))
        total_seconds = sum(number(row.get("Time")) for row in self.course_entries)
        self.course_count_var.set(f"{len(self.course_entries)} charts · {format_duration(total_seconds)} total")
        selected_indices = selected_indices or []
        valid = [index for index in selected_indices if 0 <= index < len(self.course_entries)]
        if valid:
            self.course_tree.selection_set(*(str(index) for index in valid))
            self.course_tree.focus(str(valid[0]))
            self.course_tree.see(str(valid[0]))

    def remove_course_entries(self):
        indices = sorted((int(item) for item in self.course_tree.selection()), reverse=True)
        for index in indices:
            del self.course_entries[index]
        self.refresh_course_queue()

    def move_course_entry(self, direction):
        moving = {int(item) for item in self.course_tree.selection()}
        if direction < 0:
            for index in sorted(moving):
                if index > 0 and index - 1 not in moving:
                    self.course_entries[index - 1], self.course_entries[index] = (
                        self.course_entries[index], self.course_entries[index - 1])
                    moving.remove(index)
                    moving.add(index - 1)
        else:
            for index in sorted(moving, reverse=True):
                if index + 1 < len(self.course_entries) and index + 1 not in moving:
                    self.course_entries[index + 1], self.course_entries[index] = (
                        self.course_entries[index], self.course_entries[index + 1])
                    moving.remove(index)
                    moving.add(index + 1)
        self.refresh_course_queue(sorted(moving))

    def validate_course_entries(self, title=None):
        error = validate_course_fields(self.course_entries, title)
        if error:
            # One title for every validation error: the message says what is wrong, and this check runs for
            # both saving a new course and appending to one.
            messagebox.showerror("Course problem", error, parent=self.course_window)
            return False

        types = sorted({row.get("Type", "") for row in self.course_entries if row.get("Type")})
        if len(types) > 1:
            description = (
                "This course contains multiple chart types:\n\n" + "\n".join(types) +
                "\n\nA .CRS entry stores the song and difficulty, not its specific chart type. "
                "ITGmania may resolve an entry to a different chart type when the course is played.\n\n"
                "Save the course anyway?"
            )
            if not messagebox.askyesno("Mixed chart types", description, parent=self.course_window):
                return False
        return True

    def course_song_lines(self):
        return [f"#SONG:{row['Course path']}:{row['Difficulty']}:;" for row in self.course_entries]

    def export_course(self):
        title = self.course_title_var.get().strip()
        if not title:
            messagebox.showerror("Course title required", "Enter a title for this course.", parent=self.course_window)
            return
        if not self.validate_course_entries(title):
            return

        safe_name = re.sub(r'[<>:"/\\|?*]+', "_", title).strip(" .") or "Course"
        path = filedialog.asksaveasfilename(
            parent=self.course_window, title="Save new course", defaultextension=".crs",
            filetypes=[("ITGmania course files", "*.crs")], initialfile=safe_name + ".crs",
            confirmoverwrite=True,
        )
        if not path:
            return
        lines = [f"#COURSE:{title};", *self.course_song_lines()]
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError as exc:
            messagebox.showerror("Could not save course", str(exc), parent=self.course_window)
            return
        self.status.set(f"Saved course with {len(self.course_entries)} charts to {path}")
        messagebox.showinfo("Course saved", f"Saved {title} with {len(self.course_entries)} charts.\n\n{path}",
                            parent=self.course_window)

    def append_course(self):
        if not self.validate_course_entries():
            return
        path = filedialog.askopenfilename(
            parent=self.course_window, title="Choose course to append to",
            filetypes=[("ITGmania course files", "*.crs"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "rb") as handle:
                existing = handle.read()
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Could not read course", str(exc), parent=self.course_window)
            return
        try:
            addition = course_append_bytes(existing, self.course_song_lines())
        except UnicodeError as exc:
            messagebox.showerror("Could not read course", f"The course could not be read as UTF-8.\n\n{exc}",
                                 parent=self.course_window)
            return
        except ValueError as exc:
            title = "Cannot append safely" if "ends with #" in str(exc) else "Not a readable course"
            messagebox.showwarning(title, str(exc), parent=self.course_window)
            return

        try:
            with open(path, "ab") as handle:
                handle.write(addition)
        except OSError as exc:
            messagebox.showerror("Could not append to course", str(exc), parent=self.course_window)
            return

        self.status.set(f"Appended {len(self.course_entries)} charts to {path}")
        messagebox.showinfo("Course updated", f"Appended {len(self.course_entries)} charts.\n\n{path}",
                            parent=self.course_window)


def main():
    if tk is None:
        sys.exit("Tkinter is required to run the ITGmania Library Visualizer GUI.")
    root = tk.Tk()
    LibraryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
