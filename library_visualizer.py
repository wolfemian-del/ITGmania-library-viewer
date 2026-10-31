"""A small desktop browser for ITGmania's song cache and Stats.xml."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import os
import re
import sys
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from library_data import (
    DIFFICULTY_ORDER,
    GRADE_OPTIONS,
    GRADE_NAMES,
    TAP_FIELDS,
    TECH_FIELDS,
    bpm_sort_key,
    course_append_bytes,
    difficulty_sort_key,
    format_duration,
    grade_sort_key,
    looks_like_song_tree,
    match_chart_query,
    number,
    parse_cache_file,
    parse_numeric_bound,
    parse_search_query,
    stats_index,
)

SEARCH_DEBOUNCE_MS = 200
LIBRARY_CACHE_SCHEMA_VERSION = 2
HEADERS = ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart", "Score",
           "Grade", "Best %", "Plays", "Last played", "Peak NPS", "Taps/Holds", "Jumps",
           "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
           "Miss", "Max combo", *TECH_FIELDS)
NUMERIC_COLUMNS = {"Meter", "Time", "Score", "Best %", "Plays", "Peak NPS", "Taps/Holds", "Jumps",
                   "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4",
                   "W5", "Miss", "Max combo", *TECH_FIELDS}


class LibraryApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ITGmania Library Visualizer")
        self.root.geometry("1500x850")
        self.root.minsize(900, 550)
        self.root.configure(bg="#10151d")
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
        self.column_visibility = {
            column: tk.BooleanVar(value=saved_visibility.get(column)
                                  if isinstance(saved_visibility.get(column), bool) else True)
            for column in HEADERS
        }
        if not any(variable.get() for variable in self.column_visibility.values()):
            self.column_visibility[HEADERS[0]].set(True)
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
        self._style()
        self._build()
        self.search_var.trace_add("write", lambda *_: self._schedule_search_refresh())
        for var in (self.pack_var, self.type_var, self.diff_var, self.scored_var):
            var.trace_add("write", lambda *_: self.refresh_table())
        for var in (self.cache_var, self.stats_var):
            var.trace_add("write", lambda *_: self._source_paths_changed())
        self.load_cached_data()

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#151d28", foreground="#e8edf4", fieldbackground="#151d28",
                        rowheight=27, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#222d3b", foreground="#dbe7f4", relief="flat",
                        font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#285c74")], foreground=[("selected", "white")])
        style.configure("TCombobox", fieldbackground="#202b38", background="#202b38", foreground="#ecf3f9")
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", "focus", "#202b38"),
                ("readonly", "pressed", "#202b38"),
                ("readonly", "#202b38"),
                ("focus", "#202b38"),
                ("pressed", "#202b38"),
                ("active", "#202b38"),
            ],
            foreground=[
                ("disabled", "#8794a3"),
                ("readonly", "focus", "#ecf3f9"),
                ("readonly", "pressed", "#ecf3f9"),
                ("readonly", "#ecf3f9"),
                ("focus", "#ecf3f9"),
                ("pressed", "#ecf3f9"),
                ("active", "#ecf3f9"),
            ],
            selectbackground=[("readonly", "#287c78"), ("focus", "#287c78")],
            selectforeground=[("readonly", "#ffffff"), ("focus", "#ffffff")],
            background=[("pressed", "#202b38"), ("active", "#202b38")],
            arrowcolor=[("disabled", "#8794a3"), ("!disabled", "#ecf3f9")],
        )
        style.configure("Horizontal.TProgressbar", troughcolor="#222d3b", background="#4fc3b0")
        self.root.option_add("*TCombobox*Listbox.background", "#202b38")
        self.root.option_add("*TCombobox*Listbox.foreground", "#ecf3f9")
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#287c78")
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _build(self):
        top = tk.Frame(self.root, bg="#10151d", padx=18, pady=14)
        top.pack(fill="x")
        tk.Label(top, text="ITGmania Library", fg="#f2f6fa", bg="#10151d",
                 font=("Segoe UI Semibold", 19)).pack(side="left")
        self.status = tk.StringVar(value="Choose your cache's Songs folder and player Stats.xml to get started.")
        tk.Label(top, textvariable=self.status, fg="#9eacbb", bg="#10151d",
                 font=("Segoe UI", 9)).pack(side="right", padx=8)
        paths = tk.Frame(self.root, bg="#171f2a", padx=12, pady=10)
        paths.pack(fill="x", padx=18)
        self._path_row(paths, "Cache / Songs", self.cache_var, self.choose_cache)
        self._path_row(paths, "Player Stats.xml", self.stats_var, self.choose_stats)
        bar = tk.Frame(self.root, bg="#10151d", padx=18, pady=12)
        bar.pack(fill="x")
        tk.Label(bar, text="Search", fg="#9eacbb", bg="#10151d", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.search_entry = self._entry(bar, "", self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._button(bar, "Advanced…", self.open_advanced_search).pack(side="left", padx=(0, 8))
        self.pack_filter = self._combo(bar, self.pack_var, ["All packs"])
        self.pack_filter.pack(side="left", padx=4)
        self.type_filter = self._combo(bar, self.type_var, ["All types"])
        self.type_filter.pack(side="left", padx=4)
        self.diff_filter = self._combo(bar, self.diff_var, ["All difficulties"])
        self.diff_filter.pack(side="left", padx=4)
        tk.Checkbutton(bar, text="Scored only", variable=self.scored_var, bg="#10151d", fg="#dce5ee",
                       activebackground="#10151d", activeforeground="white", selectcolor="#202b38",
                       font=("Segoe UI", 9)).pack(side="left", padx=9)
        self._button(bar, "Load / refresh", self.load_data, primary=True).pack(side="left", padx=4)
        self._button(bar, "Export CSV", self.export_csv).pack(side="left", padx=4)
        self._button(bar, "Build course…", self.open_course_builder).pack(side="left", padx=4)
        frame = tk.Frame(self.root, bg="#10151d")
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.tree = ttk.Treeview(frame, columns=HEADERS, show="headings", selectmode="extended")
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
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.tree.bind("<ButtonPress-1>", self._column_drag_start, add="+")
        self.tree.bind("<ButtonRelease-1>", self._column_drag_end, add="+")
        self.tree.bind("<ButtonRelease-1>", self._shift_sort_click, add="+")
        self.tree.bind("<ButtonRelease-1>", self._save_settings, add="+")
        visible_columns = [column for column in self.column_order if self.column_visibility[column].get()]
        if visible_columns:
            self.tree.configure(displaycolumns=visible_columns)
        self._update_sort_headings()
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=18, pady=(0, 4))
        footer = tk.Frame(self.root, bg="#10151d", padx=18, pady=7)
        footer.pack(fill="x")
        self.count_label = tk.StringVar(value="0 charts")
        tk.Label(footer, textvariable=self.count_label, fg="#9eacbb", bg="#10151d",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(footer, text="Click to sort · Shift-click adds sort keys · Drag headings to reorder · Drag dividers to resize",
                 fg="#6f7e8e", bg="#10151d", font=("Segoe UI", 9)).pack(side="right")
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
        groups = (
            ("Song & chart", ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart")),
            ("Score", ("Score", "Grade", "Best %", "Plays", "Last played", "Max combo")),
            ("Chart counts", ("Peak NPS", "Taps/Holds", "Jumps", "Holds", "Rolls", "Mines", "Hands", "Lifts")),
            ("Tap judgments", TAP_FIELDS),
            ("Tech counts", TECH_FIELDS),
        )
        for group, columns in groups:
            group_menu = tk.Menu(columns_menu, tearoff=False)
            for column in columns:
                group_menu.add_checkbutton(
                    label=column,
                    variable=self.column_visibility[column],
                    command=lambda col=column: self._column_visibility_changed(col),
                )
            columns_menu.add_cascade(label=group, menu=group_menu)
        view_menu.add_cascade(label="Columns", menu=columns_menu)
        view_menu.add_command(label="Reset column layout", command=self.reset_column_layout)
        menubar.add_cascade(label="View", menu=view_menu)
        self.root.configure(menu=menubar)
        self.root.bind("<Control-f>", lambda _event: self.focus_search())
        self.root.bind("<Control-F>", lambda _event: self.focus_search())
        self.root.bind("<Control-Shift-f>", lambda _event: self.open_advanced_search())
        self.root.bind("<Control-Shift-F>", lambda _event: self.open_advanced_search())
        self.root.bind("<Escape>", lambda _event: self.clear_search())

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

    def _schedule_search_refresh(self):
        """Refresh the table once the user pauses typing in the search box."""
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
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def reset_column_layout(self):
        self.column_order = list(HEADERS)
        for variable in self.column_visibility.values():
            variable.set(True)
        for column, width in self.default_column_widths.items():
            self.tree.column(column, width=width)
        self.tree.configure(displaycolumns=self.column_order)
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
        row = tk.Frame(parent, bg="#171f2a")
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, width=17, anchor="w", bg="#171f2a", fg="#bdc9d5",
                 font=("Segoe UI", 9)).pack(side="left")
        entry = self._entry(row, "", variable)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        self._button(row, "Browse…", command).pack(side="left")

    @staticmethod
    def _entry(parent, placeholder, variable):
        entry = tk.Entry(parent, textvariable=variable, bg="#202b38", fg="#ecf3f9", insertbackground="white",
                         relief="flat", font=("Segoe UI", 9), highlightthickness=1,
                         highlightbackground="#2c3948", highlightcolor="#4fc3b0")
        if placeholder:
            entry.insert(0, placeholder)
            entry.bind("<FocusIn>", lambda e: e.widget.delete(0, "end") if e.widget.get() == placeholder else None)
        return entry

    @staticmethod
    def _combo(parent, variable, values):
        return ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=18,
                            font=("Segoe UI", 9))

    @staticmethod
    def _button(parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg="#287c78" if primary else "#263443",
                         fg="white", activebackground="#368f89" if primary else "#344659",
                         activeforeground="white", relief="flat", padx=11, pady=7,
                         font=("Segoe UI Semibold", 9), cursor="hand2")

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
        threading.Thread(target=self._load_worker, args=(cache, stats), daemon=True).start()

    def _load_worker(self, cache: Path, stats_file: Path):
        try:
            scores = stats_index(stats_file)
            rows = []
            files = [p for p in cache.iterdir() if p.is_file()]
            skipped_files = 0
            files_without_charts = 0
            for path in files:
                try:
                    chart_rows = parse_cache_file(path, scores)
                    if not chart_rows:
                        files_without_charts += 1
                    rows.extend(chart_rows)
                except (OSError, UnicodeError):
                    skipped_files += 1
            nested_song_tree = looks_like_song_tree(cache) if not files else False
            cache_error = ""
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
                source_paths=(str(cache), str(stats_file))))
        except ET.ParseError as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(
                f"Stats.xml is malformed or incomplete and could not be parsed.\n\n{message}"))
        except OSError as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(
                f"Could not read the selected cache folder or Stats.xml.\n\n{message}"))
        except Exception as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(message))

    def _load_failed(self, message):
        self.progress.stop()
        self.status.set("Could not load library.")
        messagebox.showerror("Could not load library", message)

    def _loaded(self, rows, files, skipped_files=0, files_without_charts=0, nested_song_tree=False,
                refreshed_at="", cache_error="", from_cache=False, source_paths=None):
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
        query_text = self.search_var.get().strip()
        criteria = parse_search_query(query_text) if query_text else None
        pack, chart_type, diff = self.pack_var.get(), self.type_var.get(), self.diff_var.get()
        visible = []
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
            visible.append(row)
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
        self._insert_batch(visible, 0, generation, selected_rows)
        self.count_label.set(f"{len(visible):,} charts shown · {len(self.rows):,} total")

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
            item = self.tree.insert("", "end", values=values)
            self.tree_item_rows[item] = row
            if id(row) in selected_rows:
                self.tree.selection_add(item)
        if stop < len(rows):
            self.root.after(1, lambda: self._insert_batch(rows, stop, generation, selected_rows))

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
        window.geometry("560x540")
        window.minsize(480, 440)
        window.configure(bg="#10151d")
        window.transient(self.root)

        tk.Label(window, text="Advanced Search", fg="#f2f6fa", bg="#10151d",
                 font=("Segoe UI Semibold", 15)).pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(window, text="Search charts by specific fields, tempo, length, or difficulty.",
                 fg="#9eacbb", bg="#10151d", font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 10))

        form = tk.Frame(window, bg="#10151d", padx=18)
        form.pack(fill="both", expand=True)

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

        # Parse current search string to prepopulate fields
        curr_q = self.search_var.get().strip()
        if curr_q:
            parsed = parse_search_query(curr_q)
            for field, val in parsed.get("directives", []):
                if field == "title":
                    title_var.set(val)
                elif field == "artist":
                    artist_var.set(val)
                elif field == "pack":
                    pack_var.set(val)
                elif field == "meter":
                    b = parse_numeric_bound(val)
                    if b:
                        if b[0] == "range":
                            meter_min_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                            meter_max_var.set(str(int(b[2]) if b[2].is_integer() else b[2]))
                        elif b[0] in (">=", ">"):
                            meter_min_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                        elif b[0] in ("<=", "<"):
                            meter_max_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                        elif b[0] == "==":
                            meter_min_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                            meter_max_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                elif field == "bpm":
                    b = parse_numeric_bound(val)
                    if b:
                        if b[0] == "range":
                            bpm_min_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                            bpm_max_var.set(str(int(b[2]) if b[2].is_integer() else b[2]))
                        elif b[0] in (">=", ">"):
                            bpm_min_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                        elif b[0] in ("<=", "<"):
                            bpm_max_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                        elif b[0] == "==":
                            bpm_min_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                            bpm_max_var.set(str(int(b[1]) if b[1].is_integer() else b[1]))
                elif field == "time":
                    b = parse_numeric_bound(val, is_duration=True)
                    if b:
                        if b[0] == "range":
                            time_min_var.set(format_duration(b[1]))
                            time_max_var.set(format_duration(b[2]))
                        elif b[0] in (">=", ">"):
                            time_min_var.set(format_duration(b[1]))
                        elif b[0] in ("<=", "<"):
                            time_max_var.set(format_duration(b[1]))
                        elif b[0] == "==":
                            time_min_var.set(format_duration(b[1]))
                            time_max_var.set(format_duration(b[1]))
                elif field == "grade":
                    clean_g = val.lstrip(">=< ")
                    if clean_g in GRADE_OPTIONS:
                        grade_min_var.set(clean_g)

        def add_text_row(parent, label_text, var):
            row = tk.Frame(parent, bg="#10151d")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, fg="#9eacbb", bg="#10151d", width=12, anchor="w",
                     font=("Segoe UI", 9)).pack(side="left")
            self._entry(row, "", var).pack(side="left", fill="x", expand=True)

        def add_range_row(parent, label_text, min_var, max_var, hint=""):
            row = tk.Frame(parent, bg="#10151d")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, fg="#9eacbb", bg="#10151d", width=12, anchor="w",
                     font=("Segoe UI", 9)).pack(side="left")
            e1 = self._entry(row, "", min_var)
            e1.pack(side="left", fill="x", expand=True)
            tk.Label(row, text="to", fg="#607285", bg="#10151d", padx=8, font=("Segoe UI", 9)).pack(side="left")
            e2 = self._entry(row, "", max_var)
            e2.pack(side="left", fill="x", expand=True)
            if hint:
                tk.Label(row, text=hint, fg="#607285", bg="#10151d", font=("Segoe UI", 8), padx=6).pack(side="left")

        add_text_row(form, "Title", title_var)
        add_text_row(form, "Artist", artist_var)
        add_text_row(form, "Pack", pack_var)

        tk.Frame(form, bg="#202b38", height=1).pack(fill="x", pady=10)

        add_range_row(form, "Meter", meter_min_var, meter_max_var)
        add_range_row(form, "BPM", bpm_min_var, bpm_max_var)
        add_range_row(form, "Time", time_min_var, time_max_var, "e.g. 1:30 or 90")
        add_range_row(form, "Peak NPS", nps_min_var, nps_max_var)

        g_row = tk.Frame(form, bg="#10151d")
        g_row.pack(fill="x", pady=3)
        tk.Label(g_row, text="Min Grade", fg="#9eacbb", bg="#10151d", width=12, anchor="w",
                 font=("Segoe UI", 9)).pack(side="left")
        g_options = ["Any"] + list(GRADE_OPTIONS)
        self._combo(g_row, grade_min_var, g_options).pack(side="left")

        preview_frame = tk.Frame(window, bg="#17202c", padx=12, pady=8)
        preview_frame.pack(fill="x", padx=18, pady=(10, 4))
        tk.Label(preview_frame, text="Query:", fg="#9eacbb", bg="#17202c",
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        query_preview = tk.Label(preview_frame, text="", fg="#dce5ee", bg="#17202c",
                                 font=("Consolas", 9, "bold"), anchor="w")
        query_preview.pack(side="left", fill="x", expand=True)

        def build_query():
            tokens = []
            t = title_var.get().strip()
            if t:
                tokens.append(f'title:"{t}"' if " " in t else f"title:{t}")
            a = artist_var.get().strip()
            if a:
                tokens.append(f'artist:"{a}"' if " " in a else f"artist:{a}")
            p = pack_var.get().strip()
            if p:
                tokens.append(f'pack:"{p}"' if " " in p else f"pack:{p}")

            def add_range(name, min_v, max_v):
                min_s = min_v.get().strip()
                max_s = max_v.get().strip()
                if min_s and max_s:
                    if min_s == max_s:
                        tokens.append(f"{name}:{min_s}")
                    else:
                        tokens.append(f"{name}:{min_s}-{max_s}")
                elif min_s:
                    tokens.append(f"{name}:>={min_s}")
                elif max_s:
                    tokens.append(f"{name}:<={max_s}")

            add_range("meter", meter_min_var, meter_max_var)
            add_range("bpm", bpm_min_var, bpm_max_var)
            add_range("time", time_min_var, time_max_var)
            add_range("nps", nps_min_var, nps_max_var)

            g = grade_min_var.get()
            if g and g != "Any":
                tokens.append(f"grade:>={g}")

            return " ".join(tokens)

        def update_preview(*_):
            query_preview.config(text=build_query())

        for v in (title_var, artist_var, pack_var, meter_min_var, meter_max_var,
                  bpm_min_var, bpm_max_var, time_min_var, time_max_var, nps_min_var, nps_max_var, grade_min_var):
            v.trace_add("write", update_preview)
        update_preview()

        btn_row = tk.Frame(window, bg="#10151d", padx=18, pady=12)
        btn_row.pack(fill="x", side="bottom")

        def apply_search():
            q = build_query()
            self.search_var.set(q)
            window.destroy()

        def clear_fields():
            for v in (title_var, artist_var, pack_var, meter_min_var, meter_max_var,
                      bpm_min_var, bpm_max_var, time_min_var, time_max_var, nps_min_var, nps_max_var):
                v.set("")
            grade_min_var.set("Any")

        self._button(btn_row, "Apply", apply_search, primary=True).pack(side="right", padx=(6, 0))
        self._button(btn_row, "Close", window.destroy).pack(side="right")
        self._button(btn_row, "Clear", clear_fields).pack(side="left")

    def open_course_builder(self):
        if getattr(self, "course_window", None) is not None and self.course_window.winfo_exists():
            self.course_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.course_window = window
        window.title("Build a course")
        window.geometry("900x620")
        window.minsize(700, 440)
        window.configure(bg="#10151d")
        window.transient(self.root)
        self.course_entries: list[dict] = []

        tk.Label(window, text="Build a new course", fg="#f2f6fa", bg="#10151d",
                 font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(window, text="Select charts in the library, then add them here and arrange the course order.",
                 fg="#9eacbb", bg="#10151d", font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))

        title_row = tk.Frame(window, bg="#10151d", padx=18)
        title_row.pack(fill="x", pady=(0, 10))
        tk.Label(title_row, text="Course title", width=13, anchor="w", fg="#bdc9d5", bg="#10151d",
                 font=("Segoe UI", 9)).pack(side="left")
        self.course_title_var = tk.StringVar()
        tk.Entry(title_row, textvariable=self.course_title_var, bg="#202b38", fg="#ecf3f9",
                 insertbackground="white", relief="flat", font=("Segoe UI", 10),
                 highlightthickness=1, highlightbackground="#2c3948", highlightcolor="#4fc3b0").pack(
                     side="left", fill="x", expand=True)

        queue_frame = tk.Frame(window, bg="#10151d")
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

        controls = tk.Frame(window, bg="#10151d", padx=18, pady=12)
        controls.pack(fill="x")
        self._button(controls, "Add selected charts", self.add_selected_to_course, primary=True).pack(side="left")
        self._button(controls, "Remove", self.remove_course_entries).pack(side="left", padx=(8, 0))
        self._button(controls, "Move up", lambda: self.move_course_entry(-1)).pack(side="left", padx=(8, 0))
        self._button(controls, "Move down", lambda: self.move_course_entry(1)).pack(side="left", padx=(8, 0))
        self.course_count_var = tk.StringVar(value="0 charts · 0:00 total")
        tk.Label(controls, textvariable=self.course_count_var, fg="#9eacbb", bg="#10151d",
                 font=("Segoe UI", 9)).pack(side="left", padx=12)
        self._button(controls, "Append to .CRS…", self.append_course).pack(side="right", padx=(0, 8))
        self._button(controls, "Save new .CRS…", self.export_course, primary=True).pack(side="right")

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
        title = (title or "").strip()
        if title and any(char in title for char in (";", ":", "\r", "\n")):
            messagebox.showerror(
                "Unsupported course text",
                "Course titles cannot contain semicolons, colons, or newlines.",
                parent=self.course_window,
            )
            return False
        if not self.course_entries:
            messagebox.showerror("No charts added", "Add at least one chart to the course.", parent=self.course_window)
            return False
        if any(not row.get("Course path") or not row.get("Difficulty") for row in self.course_entries):
            messagebox.showerror("Missing chart data", "One or more selected charts are missing a song path or difficulty.",
                                 parent=self.course_window)
            return False
        text_fields = [row["Course path"] for row in self.course_entries]
        if any(any(char in value for char in (";", ":", "\r", "\n")) for value in text_fields):
            messagebox.showerror(
                "Unsupported course text",
                "Song paths cannot contain semicolons, colons, or newlines.",
                parent=self.course_window,
            )
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
    root = tk.Tk()
    LibraryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
