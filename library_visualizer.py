"""A small desktop browser for ITGmania's song cache and Stats.xml."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


TECH_FIELDS = ("Crossovers", "HalfCrossovers", "FullCrossovers", "Footswitches",
               "UpFootswitches", "DownFootswitches", "Sideswitches", "Jacks",
               "Brackets", "Doublesteps")
RADAR_FIELDS = ("Stream", "Voltage", "Air", "Freeze", "Chaos", "Notes",
                "TapsAndHolds", "Jumps", "Holds", "Rolls", "Mines", "Hands",
                "Lifts", "Fakes")
TAP_FIELDS = ("W1", "W2", "W3", "W4", "W5", "Miss")
GRADE_NAMES = {
    "Tier01": "★★★★", "Tier02": "★★★", "Tier03": "★★", "Tier04": "★",
    "Tier05": "S+", "Tier06": "S", "Tier07": "S-", "Tier08": "A+",
    "Tier09": "A", "Tier10": "A-", "Tier11": "B+", "Tier12": "B",
    "Tier13": "B-", "Tier14": "C+", "Tier15": "C", "Tier16": "C-", "Tier17": "D",
}
HEADERS = ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Chart", "Score",
           "Grade", "Best %", "Plays", "Last played", "Peak NPS", "Taps/Holds", "Jumps",
           "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
           "Miss", "Max combo", *TECH_FIELDS)
NUMERIC_COLUMNS = {"Meter", "Score", "Best %", "Plays", "Peak NPS", "Taps/Holds", "Jumps",
                   "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4",
                   "W5", "Miss", "Max combo", *TECH_FIELDS}


def number(value: str | None, default: float = 0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def tag_map(text: str) -> dict[str, str]:
    return {m.group(1).upper(): m.group(2).strip() for m in
            re.finditer(r"(?m)^#([^:;\r\n]+):([^;\r\n]*);", text)}


def split_path(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    if value.lower().startswith("songs/"):
        value = value[6:]
    return value


def stats_index(stats_file: Path) -> dict[tuple[str, str, str], dict]:
    root = ET.parse(stats_file).getroot()
    result: dict[tuple[str, str, str], dict] = {}
    song_scores = root.find("SongScores")
    if song_scores is None:
        return result
    for song in song_scores.findall("Song"):
        song_path = split_path(song.get("Dir", ""))
        for steps in song.findall("Steps"):
            key = (song_path.casefold(), steps.get("StepsType", "").casefold(),
                   steps.get("Difficulty", "").casefold())
            score_list = steps.find("HighScoreList")
            if score_list is None:
                continue
            scores = score_list.findall("HighScore")
            best = max(scores, key=lambda score: number(score.findtext("PercentDP")), default=None)
            best_data = {}
            if best is not None:
                best_data = {tag: best.findtext(tag, "") for tag in
                             ("Score", "Grade", "PercentDP", "MaxCombo", "DateTime")}
                taps = best.find("TapNoteScores")
                if taps is not None:
                    best_data.update({"tap_" + name: taps.findtext(name, "") for name in TAP_FIELDS})
                radar = best.find("RadarValues")
                if radar is not None:
                    best_data.update({"score_" + name: radar.findtext(name, "") for name in RADAR_FIELDS})
            result[key] = {"plays": score_list.findtext("NumTimesPlayed", "0"),
                           "last_played": score_list.findtext("LastPlayed", ""), **best_data}
    return result


def parse_cache_file(path: Path, scores: dict) -> list[dict]:
    # Cache files are UTF-8 Simfile text; split away the song metadata before chart parsing.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    chunks = re.split(r"(?m)^#NOTEDATA:;\s*\r?\n", text)
    song_tags = tag_map(chunks[0])
    song_file = song_tags.get("SONGFILENAME", "")
    song_dir = split_path(song_file)
    song_dir = song_dir.rsplit("/", 1)[0] if "/" in song_dir else ""
    pack = song_dir.split("/", 1)[0] if song_dir else ""
    rows = []
    for chunk in chunks[1:]:
        tags = tag_map(chunk)
        chart_type = tags.get("STEPSTYPE", "")
        difficulty = tags.get("DIFFICULTY", "")
        if not chart_type or not difficulty:
            continue
        radar = [number(v) for v in tags.get("RADARVALUES", "").split(",")]
        tech = [number(v, -1) for v in tags.get("TECHCOUNTS", "").split(",")]
        key = (song_dir.casefold(), chart_type.casefold(), difficulty.casefold())
        score = scores.get(key, {})
        percent = number(score.get("PercentDP")) * 100
        display_name = tags.get("CHARTNAME") or tags.get("DESCRIPTION", "")
        rows.append({
            "Title": song_tags.get("TITLE", path.stem), "Artist": song_tags.get("ARTIST", ""),
            "Pack": pack, "Type": chart_type, "Difficulty": difficulty,
            "Meter": number(tags.get("METER")), "Chart": display_name,
            "Score": number(score.get("Score")) if score else "",
            "Grade": GRADE_NAMES.get(score.get("Grade", ""), score.get("Grade", "")),
            "Best %": round(percent, 2) if score else "", "Plays": number(score.get("plays")),
            "Last played": score.get("last_played", ""), "Peak NPS": number(tags.get("PEAKNPS")),
            "Taps/Holds": radar[6] if len(radar) > 6 else "", "Jumps": radar[7] if len(radar) > 7 else "",
            "Holds": radar[8] if len(radar) > 8 else "", "Rolls": radar[9] if len(radar) > 9 else "",
            "Mines": radar[10] if len(radar) > 10 else "", "Hands": radar[11] if len(radar) > 11 else "",
            "Lifts": radar[12] if len(radar) > 12 else "",
            **{name: number(score.get("tap_" + name)) if score else "" for name in TAP_FIELDS},
            "Max combo": number(score.get("MaxCombo")) if score else "",
            **{name: tech[i] if i < len(tech) and tech[i] >= 0 else ""
               for i, name in enumerate(TECH_FIELDS)},
        })
    return rows


class LibraryApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ITGmania Library Visualizer")
        self.root.geometry("1500x850")
        self.root.minsize(900, 550)
        self.root.configure(bg="#10151d")
        self.rows: list[dict] = []
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
        saved_order = self.saved_settings.get("column_order", [])
        if not isinstance(saved_order, list):
            saved_order = []
        valid_order = []
        for column in saved_order:
            if column in HEADERS and column not in valid_order:
                valid_order.append(column)
        self.column_order = valid_order + [column for column in HEADERS if column not in valid_order]
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
        self.sort_col = "Pack"
        self.sort_reverse = False
        self._style()
        self._build()
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        for var in (self.pack_var, self.type_var, self.diff_var, self.scored_var):
            var.trace_add("write", lambda *_: self.refresh_table())
        if Path(self.cache_var.get()).is_dir() and Path(self.stats_var.get()).is_file():
            self.load_data()

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#151d28", foreground="#e8edf4", fieldbackground="#151d28",
                        rowheight=27, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#222d3b", foreground="#dbe7f4", relief="flat",
                        font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#285c74")], foreground=[("selected", "white")])
        style.configure("TCombobox", fieldbackground="#202b38", background="#202b38", foreground="#ecf3f9")
        style.configure("Horizontal.TProgressbar", troughcolor="#222d3b", background="#4fc3b0")

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
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
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
        frame = tk.Frame(self.root, bg="#10151d")
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.tree = ttk.Treeview(frame, columns=HEADERS, show="headings", selectmode="browse")
        for col in HEADERS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            width = 130 if col in ("Title", "Artist", "Pack") else 92
            if col in ("Type", "Difficulty", "Meter", "Score", "Grade", "Best %", "Plays", "Jumps", "Holds",
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
        self.tree.bind("<ButtonRelease-1>", self._save_settings, add="+")
        visible_columns = [column for column in self.column_order if self.column_visibility[column].get()]
        if visible_columns:
            self.tree.configure(displaycolumns=visible_columns)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=18, pady=(0, 4))
        footer = tk.Frame(self.root, bg="#10151d", padx=18, pady=7)
        footer.pack(fill="x")
        self.count_label = tk.StringVar(value="0 charts")
        tk.Label(footer, textvariable=self.count_label, fg="#9eacbb", bg="#10151d",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(footer, text="Drag headings to reorder · Drag dividers to resize · Scroll horizontally for details",
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
        edit_menu.add_command(label="Clear search", accelerator="Esc", command=self.clear_search)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        columns_menu = tk.Menu(view_menu, tearoff=False)
        groups = (
            ("Song & chart", ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Chart")),
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
            for path in files:
                try:
                    rows.extend(parse_cache_file(path, scores))
                except (OSError, UnicodeError):
                    continue
            self.root.after(0, lambda: self._loaded(rows, len(files)))
        except Exception as exc:
            self.root.after(0, lambda message=str(exc): self._load_failed(message))

    def _load_failed(self, message):
        self.progress.stop()
        self.status.set("Could not load library.")
        messagebox.showerror("Could not load library", message)

    def _loaded(self, rows, files):
        self.progress.stop()
        self.rows = rows
        for combo, var, label, key in ((self.pack_filter, self.pack_var, "All packs", "Pack"),
                                       (self.type_filter, self.type_var, "All types", "Type"),
                                       (self.diff_filter, self.diff_var, "All difficulties", "Difficulty")):
            values = [label] + sorted({str(r[key]) for r in rows if r[key]}, key=str.casefold)
            combo.configure(values=values)
            var.set(label)
        self.status.set(f"Loaded {files:,} cache files and {len(rows):,} charts.")
        self.refresh_table()

    def refresh_table(self):
        if not hasattr(self, "tree"):
            return
        self._render_generation = getattr(self, "_render_generation", 0) + 1
        generation = self._render_generation
        needle = self.search_var.get().strip().casefold()
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
            if needle and needle not in " ".join(str(row[k]) for k in ("Title", "Artist", "Pack", "Chart", "Type", "Difficulty")).casefold():
                continue
            visible.append(row)
        if self.sort_col in NUMERIC_COLUMNS:
            visible.sort(key=lambda r: (r[self.sort_col] == "", number(str(r[self.sort_col]), -1)),
                         reverse=self.sort_reverse)
        else:
            visible.sort(key=lambda r: str(r[self.sort_col]).casefold(), reverse=self.sort_reverse)
        self.tree.delete(*self.tree.get_children())
        self._insert_batch(visible, 0, generation)
        self.count_label.set(f"{len(visible):,} charts shown · {len(self.rows):,} total")

    def _insert_batch(self, rows, start, generation):
        if generation != self._render_generation:
            return
        stop = min(start + 500, len(rows))
        for row in rows[start:stop]:
            values = []
            for col in HEADERS:
                value = row.get(col, "")
                if isinstance(value, float):
                    value = f"{value:g}"
                values.append(value)
            self.tree.insert("", "end", values=values)
        if stop < len(rows):
            self.root.after(1, lambda: self._insert_batch(rows, stop, generation))

    def sort_by(self, column):
        if self.sort_col == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col, self.sort_reverse = column, False
        self.refresh_table()

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


def main():
    root = tk.Tk()
    LibraryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
