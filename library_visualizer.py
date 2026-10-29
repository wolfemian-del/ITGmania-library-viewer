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
DIFFICULTY_ORDER = ("Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit")
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
HEADERS = ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "Chart", "Score",
           "Grade", "Best %", "Plays", "Last played", "Peak NPS", "Taps/Holds", "Jumps",
           "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
           "Miss", "Max combo", *TECH_FIELDS)
NUMERIC_COLUMNS = {"Meter", "Time", "Score", "Best %", "Plays", "Peak NPS", "Taps/Holds", "Jumps",
                   "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4",
                   "W5", "Miss", "Max combo", *TECH_FIELDS}


def number(value: str | None, default: float = 0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def format_duration(seconds) -> str:
    total = max(0, int(round(number(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


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
            "Pack": pack, "Type": chart_type, "Difficulty": difficulty, "Course path": song_dir,
            "Meter": number(tags.get("METER")),
            "Time": number(song_tags.get("MUSICLENGTH")) if song_tags.get("MUSICLENGTH") else "",
            "Chart": display_name,
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


def looks_like_song_tree(cache: Path) -> bool:
    """Return whether the selected folder resembles Songs/Pack/Song/*.sm|*.ssc."""
    for pack in cache.iterdir():
        if not pack.is_dir():
            continue
        for song in pack.iterdir():
            if song.is_dir() and any(
                chart.is_file() and chart.suffix.casefold() in {".sm", ".ssc"}
                for chart in song.iterdir()
            ):
                return True
    return False


def course_append_bytes(existing: bytes, song_lines: list[str]) -> bytes:
    """Validate an existing CRS and return only the bytes safe to append."""
    text = existing.decode("utf-8-sig")
    songs = list(re.finditer(r"#SONG\s*:", text, re.IGNORECASE))
    if not re.search(r"#COURSE\s*:", text, re.IGNORECASE) or not songs:
        raise ValueError("The selected file must contain #COURSE and at least one #SONG entry.")
    risky = re.search(r"#(MODS|GAINSECONDS)\s*:", text[songs[-1].end():], re.IGNORECASE)
    if risky:
        raise ValueError(
            f"This course ends with #{risky.group(1).upper()}, which may affect the chart entries being appended. "
            "The existing course was left unchanged. Remove or resolve that directive in the course file, then try again."
        )
    if not song_lines:
        raise ValueError("Add at least one chart before appending to a course.")

    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    prefix = newline if existing and not existing.endswith((b"\n", b"\r")) else b""
    return prefix + newline.join(line.encode("utf-8") for line in song_lines) + newline


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
        if "Time" not in valid_order:
            self.column_order.remove("Time")
            meter_index = self.column_order.index("Meter")
            self.column_order.insert(meter_index + 1, "Time")
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
        self._button(bar, "Build course…", self.open_course_builder).pack(side="left", padx=4)
        frame = tk.Frame(self.root, bg="#10151d")
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.tree = ttk.Treeview(frame, columns=HEADERS, show="headings", selectmode="extended")
        for col in HEADERS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            width = 130 if col in ("Title", "Artist", "Pack") else 92
            if col in ("Type", "Difficulty", "Meter", "Time", "Score", "Grade", "Best %", "Plays", "Jumps", "Holds",
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
        edit_menu.add_command(label="Clear search", accelerator="Esc", command=self.clear_search)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        columns_menu = tk.Menu(view_menu, tearoff=False)
        groups = (
            ("Song & chart", ("Title", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "Chart")),
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
            self.root.after(0, lambda: self._loaded(
                rows, len(files), skipped_files, files_without_charts, nested_song_tree))
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

    def _loaded(self, rows, files, skipped_files=0, files_without_charts=0, nested_song_tree=False):
        self.progress.stop()
        self.rows = rows
        for combo, var, label, key in ((self.pack_filter, self.pack_var, "All packs", "Pack"),
                                       (self.type_filter, self.type_var, "All types", "Type")):
            values = [label] + sorted({str(r[key]) for r in rows if r[key]}, key=str.casefold)
            combo.configure(values=values)
            var.set(label)
        difficulty_rank = {difficulty.casefold(): index for index, difficulty in enumerate(DIFFICULTY_ORDER)}
        difficulties = sorted(
            {str(row["Difficulty"]) for row in rows if row["Difficulty"]},
            key=lambda difficulty: (difficulty_rank.get(difficulty.casefold(), len(DIFFICULTY_ORDER)),
                                    difficulty.casefold()),
        )
        self.diff_filter.configure(values=["All difficulties"] + difficulties)
        self.diff_var.set("All difficulties")
        if files == 0:
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
        self.refresh_table()

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
        for column, descending in reversed(self.sort_keys):
            present = [row for row in visible if row.get(column) not in (None, "")]
            missing = [row for row in visible if row.get(column) in (None, "")]
            if column in NUMERIC_COLUMNS:
                present.sort(key=lambda row: number(str(row.get(column))), reverse=descending)
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
