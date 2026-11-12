"""A small desktop browser for ITGmania's song cache and Stats.xml."""

from __future__ import annotations

import contextlib
import csv
from datetime import datetime
import queue
import sys
import threading
import time
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

# The release number, shown in Help > About. Keep it equal to the newest heading in CHANGELOG.md (a test checks).
__version__ = "1.2.0"

import row_tints
import theme
from advanced_search import AdvancedSearch
from course_builder import CourseBuilder
from distribution_panel import DistributionPanel
from library_data import (
    TAP_FIELDS,
    TECH_FIELDS,
    CHART_FILTER_FIELDS,
    LIBRARY_CACHE_SCHEMA_VERSION,
    SettingsStore,
    SnapshotStore,
    _normalized_source_path,
    _settings_file_path,
    _valid_column_width,
    _valid_window_geometry,
    bpm_sort_key,
    cache_dir_candidates,
    declare_dpi_awareness,
    difficulty_sort_key,
    dpi_scale_factor,
    find_unreadable_directives,
    first_existing_directory,
    format_duration,
    grade_sort_key,
    looks_like_song_tree,
    match_chart_query,
    number,
    parse_cache_file,
    parse_search_query,
    scale_geometry,
    scale_pixels,
    stats_index,
)

SEARCH_DEBOUNCE_MS = 200
# How long one batch of table-row inserts may run before yielding to the event
# loop (see _insert_batch): long enough to fill quickly, short enough that the
# window stays responsive while a big library streams in.
ROW_INSERT_BUDGET_SECONDS = 0.012
HEADERS = ("Title", "Subtitle", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart", "Score",
           "Grade", "Best %", "Plays", "Last played", "Peak NPS", "Taps/Holds", "Jumps",
           "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
           "Miss", "Max combo", *TECH_FIELDS)
NUMERIC_COLUMNS = {"Meter", "Time", "Score", "Best %", "Plays", "Peak NPS", "Taps/Holds", "Jumps",
                   "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4",
                   "W5", "Miss", "Max combo", *TECH_FIELDS}
# The groups shown under View > Columns, in menu order. Every column in HEADERS belongs to exactly one group.
COLUMN_GROUPS = {
    "Song & chart": ("Title", "Subtitle", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart"),
    "Score": ("Score", "Grade", "Best %", "Plays", "Last played", "Max combo"),
    "Tap judgments": TAP_FIELDS,
    "Chart counts": ("Peak NPS", "Taps/Holds", "Jumps", "Holds", "Rolls", "Mines", "Hands", "Lifts"),
    "Tech counts": TECH_FIELDS,
}
# Groups whose columns are shown on a fresh install and after "Reset column layout".
DEFAULT_VISIBLE_GROUPS = ("Song & chart", "Score")
# Subtitle is the one exception to the rule that every column of a default
# group starts shown: it belongs to "Song & chart" but starts hidden
# (issue #49, option B), opt-in via View -> Columns.
DEFAULT_VISIBLE_COLUMNS = frozenset(
    column for group in DEFAULT_VISIBLE_GROUPS for column in COLUMN_GROUPS[group]) - {"Subtitle"}

class LibraryApp:
    # Defaults for state that is only set later, so every instance has these attributes.
    _search_refresh_after_id = None
    _batching_filter_changes = False
    _load_started_at = None
    # The display scale factor (1.0 at 100% DPI): bare instances in tests
    # have no window to measure, so they read canonical units as-is.
    _dpi_scale = 1.0

    # The Data paths dialog's note texts (UI redesign): the first-run note is
    # the sketch's wording; the dead-paths sentence is a Muse proposal, to be
    # settled in the build review.
    _DATA_PATHS_FIRST_RUN_NOTE = ("We couldn't find your ITGmania folders automatically — "
                                  "point the app at them once and it will remember.")
    _DATA_PATHS_DEAD_NOTE = ("Your saved paths no longer exist — "
                             "point the app at them again and it will remember.")
    _DATA_PATHS_DIFFER_NOTE = ("These paths differ from the library on screen — "
                               "Load / refresh to rebuild it.")

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ITGmania Library Visualizer")
        # The display scale factor (issue #51): 1.0 at 100% DPI, 1.5 at
        # 150%. Every pixel number below is stored in canonical 100%
        # units and scaled here, at the point it reaches the window.
        self._dpi_scale = dpi_scale_factor(self.root.winfo_fpixels("1i"))
        self.root.geometry(scale_geometry(theme.WINDOW_DEFAULT_GEOMETRY, self._dpi_scale))
        self.root.minsize(scale_pixels(theme.WINDOW_MIN_SIZE[0], self._dpi_scale),
                          scale_pixels(theme.WINDOW_MIN_SIZE[1], self._dpi_scale))
        self.root.configure(bg=theme.BG_WINDOW)
        self.rows: list[dict] = []
        self.loaded_source_paths = None
        self.settings_path = self._settings_file_path()
        # The snapshot store owns library_cache.json (proposal 0008); its
        # path is derived once here from the settings path, and it is built
        # against the current schema version.
        self._snapshot_store = SnapshotStore(
            self.library_cache_path, HEADERS, LIBRARY_CACHE_SCHEMA_VERSION)
        # The settings store owns settings.json (proposal 0008). Loading it
        # seeds the store's dedup baseline; a failure is remembered on the
        # store (last_read_error) and reported once the window is built
        # (_report_discarded_settings), since the file is read before the
        # status line exists.
        self._settings_store = SettingsStore(self.settings_path)
        self.saved_settings = self._settings_store.load()
        default_cache = first_existing_directory(cache_dir_candidates())
        default_stats = Path.cwd() / "Stats.xml"
        self.cache_var = tk.StringVar(value=self.saved_settings.get(
            "cache_dir", str(default_cache) if default_cache is not None else ""))
        self.stats_var = tk.StringVar(value=self.saved_settings.get(
            "stats_file", str(default_stats) if default_stats.is_file() else ""))
        self.search_var = tk.StringVar()
        saved_pack = self.saved_settings.get("filter_pack")
        self.pack_var = tk.StringVar(value=saved_pack if isinstance(saved_pack, str) else "All packs")
        saved_type = self.saved_settings.get("filter_type")
        self.type_var = tk.StringVar(value=saved_type if isinstance(saved_type, str) else "All types")
        saved_difficulty = self.saved_settings.get("filter_difficulty")
        self.diff_var = tk.StringVar(value=saved_difficulty if isinstance(saved_difficulty, str) else "All difficulties")
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
        if "Subtitle" not in valid_order:
            # A saved order from before Subtitle existed appends it at the
            # far right; put it beside Title instead, like Time/BPM above.
            self.column_order.remove("Subtitle")
            title_index = self.column_order.index("Title")
            self.column_order.insert(title_index + 1, "Subtitle")
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
            column: _valid_column_width(saved_widths.get(column), column) for column in HEADERS
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
        self._tree_tint = None  # the song table's SelectedRowTint, created with the table in _build
        self._load_generation = 0  # counts Load / refresh requests; a scan from an older request is dropped
        self._snapshot_lock = threading.Lock()  # one scan at a time may check its generation and write the snapshot
        self._load_results = queue.Queue()  # finished scans wait here; only the main thread delivers them (_poll_load_results)
        # Attributes that are filled in after this point. Declaring them here lists everything the window
        # holds in one place; the comments name where each one is filled in.
        # Widgets and variables created by _build(); None until then:
        self.status = None
        self.search_entry = None
        self.pack_filter = None
        self.type_filter = None
        self.diff_filter = None
        self.dist_button = None
        self.content_frame = None
        self.table_frame = None
        self.tree = None  # refresh_table and _save_settings do nothing until the table exists
        self.progress = None
        self.count_label = None
        self.load_button = None
        # Working state that starts empty:
        self.last_refreshed_at = ""  # when the saved snapshot was written (set by _loaded)
        self._render_generation = 0  # counts table redraws, so an unfinished older redraw stops (refresh_table)
        self.tree_item_rows = {}  # table row id -> its chart row (refresh_table)
        self._dragged_column = None  # heading being dragged, and where the drag began (_column_drag_start)
        self._drag_start_x = None
        # Dialogs: a window attribute is None while that dialog is closed. The course builder is a
        # separate component (course_builder.py) that owns its window and queue; it is created in
        # _build, once the status variable exists. The Advanced Search component
        # (advanced_search.py) and the distribution panel component (distribution_panel.py)
        # follow the same pattern.
        self.advanced_search = None
        self.about_window = None
        self.course_builder = None
        self.distribution_panel = None
        # The Data paths dialog (UI redesign): the window and its note line
        # while it is open, and whether the first-run popup has already shown
        # this session (it never reappears after being dismissed).
        self._data_paths_window = None
        self._data_paths_note = None
        self._data_paths_form = None
        self._data_paths_popup_shown = False
        self._style()
        self._build()
        self._report_discarded_settings()
        self.search_var.trace_add("write", lambda *_: self._schedule_search_refresh())
        for var in (self.pack_var, self.type_var, self.diff_var, self.scored_var):
            var.trace_add("write", lambda *_: self._refresh_unless_batching())
        for var in (self.cache_var, self.stats_var):
            var.trace_add("write", lambda *_: self._source_paths_changed())
        self.root.after(75, self._poll_load_results)
        # The saved snapshot is loaded once the window has painted, not here:
        # reading and rendering it can take a moment at library scale, and doing
        # it before the event loop starts would leave the user watching the
        # console (or an unpainted window) with no explanation.
        if self.library_cache_path.is_file():
            self.status.set("Loading saved library…")
            self.progress.start(12)
        self.root.after(50, self._load_initial_snapshot)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=theme.BG_TABLE, foreground=theme.TEXT_TABLE, fieldbackground=theme.BG_TABLE,
                        rowheight=scale_pixels(theme.TABLE_ROW_HEIGHT, self._dpi_scale), borderwidth=0, font=theme.FONT_BODY)
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
        top = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(14, self._dpi_scale))
        top.pack(fill="x")
        tk.Label(top, text="ITGmania Library Visualizer", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_APP_TITLE).pack(side="left")
        self.status = tk.StringVar(value="No saved library yet. Choose File → Data paths…, then Load / refresh.")
        tk.Label(top, textvariable=self.status, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="right", padx=scale_pixels(8, self._dpi_scale))
        # The course builder component (course_builder.py): created here because it needs the
        # status variable above; the Build course button below calls its open_dialog directly.
        # The geometry it opens with comes from settings (issue #25); it is initialized here,
        # before any save can run, so a session that never opens the dialog carries the stored
        # value through unchanged.
        self.course_geometry = self._valid_course_geometry(self.saved_settings.get("course_geometry"))
        self.course_builder = CourseBuilder(self.root, self.status, self._button, self._selected_rows_for_course,
                                            self._library_rows_for_course,
                                            saved_geometry=self.course_geometry,
                                            report_geometry=self._course_geometry_changed,
                                            dpi_scale=self._dpi_scale)
        # The Advanced Search component (advanced_search.py): it edits the search variable's
        # text through its field form; the Advanced… button below calls its open_dialog directly.
        self.advanced_search_geometry = self._valid_advanced_search_geometry(
            self.saved_settings.get("advanced_search_geometry"))
        self.advanced_search = AdvancedSearch(self.root, self._entry, self._button, self._combo, self.search_var,
                                              saved_geometry=self.advanced_search_geometry,
                                              report_geometry=self._advanced_search_geometry_changed,
                                              dpi_scale=self._dpi_scale)
        # The distribution panel component (distribution_panel.py): it owns the chart panel
        # beside the table. The four variables stay the app's own (the View menu binds one,
        # the settings save reads two), row pulls go through _filter_rows, and the panel's
        # click/Clear changes come back through apply_chart_filter so they batch into one
        # refresh. Its widgets are built by build_panel, below, once their parent exists.
        self.distribution_panel = DistributionPanel(
            button_factory=self._button,
            search_var=self.search_var,
            diff_var=self.diff_var,
            show_distribution_panel=self.show_distribution_panel,
            distribution_metric=self.distribution_metric,
            filter_rows=self._filter_rows,
            apply_chart_filter=self.apply_chart_filter,
            save_settings=self._save_settings,
            dpi_scale=self._dpi_scale)
        # The main window's X button goes through the same exit path as File → Exit (issue #87).
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
        bar = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(12, self._dpi_scale))
        bar.pack(fill="x")
        tk.Label(bar, text="Search", fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(side="left", padx=(0, scale_pixels(6, self._dpi_scale)))
        self.search_entry = self._entry(bar, "", self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, scale_pixels(4, self._dpi_scale)))
        self._button(bar, "Advanced…", self.advanced_search.open_dialog).pack(side="left", padx=(0, scale_pixels(8, self._dpi_scale)))
        self.pack_filter = self._combo(bar, self.pack_var, ["All packs"])
        self.pack_filter.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self.type_filter = self._combo(bar, self.type_var, ["All types"])
        self.type_filter.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self.diff_filter = self._combo(bar, self.diff_var, ["All difficulties"])
        self.diff_filter.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        # A pick in any filter dropdown saves the settings at once (proposal
        # 0006); _save_settings accepts the event the binding passes.
        for combo in (self.pack_filter, self.type_filter, self.diff_filter):
            combo.bind("<<ComboboxSelected>>", self._save_settings)
        tk.Checkbutton(bar, text="Scored only", variable=self.scored_var, bg=theme.BG_WINDOW, fg=theme.TEXT_LABEL,
                       activebackground=theme.BG_WINDOW, activeforeground=theme.TEXT_ON_ACCENT, selectcolor=theme.BG_INPUT,
                       font=theme.FONT_BODY).pack(side="left", padx=scale_pixels(9, self._dpi_scale))
        self.load_button = self._button(bar, "Load / refresh", self.load_data, primary=True)
        self.load_button.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self._button(bar, "Export CSV", self.export_csv).pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self._button(bar, "Build course…", self.course_builder.open_dialog).pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        # The label is the component's to set: build_panel (below) puts the saved state's
        # ◀/▶ text on the button, and the component rewrites it on every visibility change.
        self.dist_button = self._button(bar, "", self.distribution_panel.toggle)
        self.dist_button.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self.content_frame = tk.Frame(self.root, bg=theme.BG_WINDOW)
        self.content_frame.pack(fill="both", expand=True, padx=scale_pixels(18, self._dpi_scale), pady=(0, scale_pixels(8, self._dpi_scale)))
        self.distribution_panel.build_panel(
            self.content_frame, self.dist_button, lambda: self.table_frame)
        self.table_frame = tk.Frame(self.content_frame, bg=theme.BG_WINDOW)
        self.table_frame.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(self.table_frame, columns=HEADERS, show="headings", selectmode="extended")
        for col in HEADERS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            width = 130 if col in ("Title", "Subtitle", "Artist", "Pack") else 92
            if col in ("Type", "Difficulty", "Meter", "Time", "BPM", "Score", "Grade", "Best %", "Plays", "Jumps", "Holds",
                       "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5", "Miss"):
                width = 76
            if col == "Last played":
                width = 105
            if col == "Chart":
                width = 150
            self.default_column_widths[col] = width
            width = self.column_widths[col] or width
            # Canonical widths (saved or default), scaled to this display.
            self.tree.column(col, width=scale_pixels(width, self._dpi_scale),
                             minwidth=scale_pixels(55, self._dpi_scale), stretch=False, anchor="w" if col in
                             ("Title", "Subtitle", "Artist", "Pack", "Chart") else "center")
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
        self.tree.bind("<Control-a>", self._select_all_rows, add="+")
        self.tree.bind("<Control-A>", self._select_all_rows, add="+")
        visible_columns = [column for column in self.column_order if self.column_visibility[column].get()]
        if visible_columns:
            self.tree.configure(displaycolumns=visible_columns)
        self._update_sort_headings()
        row_tints.configure_tree_tags(self.tree)
        self._tree_tint = row_tints.SelectedRowTint(self.tree)
        self.tree.bind("<<TreeviewSelect>>", self._tree_tint.on_select, add="+")
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=scale_pixels(18, self._dpi_scale), pady=(0, scale_pixels(4, self._dpi_scale)))
        footer = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(7, self._dpi_scale))
        footer.pack(fill="x")
        self.count_label = tk.StringVar(value="0 charts")
        tk.Label(footer, textvariable=self.count_label, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left")
        tk.Label(footer, text="Click to sort · Shift-click adds sort keys · Drag headings to reorder · Drag dividers to resize",
                 fg=theme.TEXT_FOOTER, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(side="right")
        self._build_menubar()

    def _close_app(self):
        """The app's single exit path (issue #87): File → Exit and the main
        window's X button both land here. Destroying the root would tear
        down the course dialog without running its discard prompt, so ask
        the course builder first; if it says no, nothing is destroyed and
        the app stays exactly as it was. An approved exit with the dialog
        open also captures the dialog's geometry for next time (issue #25).
        The Advanced Search dialog needs no prompt; its geometry is
        captured the same way (issue #98)."""
        if self.course_builder is not None:
            if not self.course_builder.confirm_discard_for_app_exit():
                return
            self.course_builder.save_window_geometry()
        if self.advanced_search is not None:
            self.advanced_search.save_window_geometry()
        self.root.destroy()

    def _course_geometry_changed(self, geometry):
        """The course window closed with a new geometry (issue #25): remember it in settings."""
        self.course_geometry = geometry
        self._save_settings()

    def _advanced_search_geometry_changed(self, geometry):
        """The Advanced Search window closed with a new geometry (issue #98): remember it in settings."""
        self.advanced_search_geometry = geometry
        self._save_settings()

    def _build_menubar(self):
        menubar = tk.Menu(self.root, tearoff=False)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Load / refresh library", command=self.load_data)
        file_menu.add_command(label="Export CSV…", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Data paths…", command=self.open_data_paths_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close_app)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Find", accelerator="Ctrl+F", command=self.focus_search)
        edit_menu.add_command(label="Advanced search…", accelerator="Ctrl+Shift+F", command=self.advanced_search.open_dialog)
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
            command=self.distribution_panel.sync_toggle,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About ITGmania Library Visualizer…", command=self.open_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menubar)
        self.root.bind("<Control-f>", lambda _event: self.focus_search())
        self.root.bind("<Control-F>", lambda _event: self.focus_search())
        self.root.bind("<Control-Shift-f>", lambda _event: self.advanced_search.open_dialog())
        self.root.bind("<Control-Shift-F>", lambda _event: self.advanced_search.open_dialog())
        self.root.bind("<Escape>", self._on_main_escape)

    @staticmethod
    def _settings_file_path():
        # Thin wrapper over the module-level helper (proposal 0008): the
        # seventeen live-test patch sites redirect the settings file here.
        # The bare name is the imported helper, not this method.
        return _settings_file_path()

    @property
    def library_cache_path(self):
        return self.settings_path.with_name("library_cache.json")

    def _load_initial_snapshot(self):
        """Load the saved snapshot (scheduled from __init__ so the window paints first)."""
        if self._load_generation:
            # A Load / refresh pressed inside the deferral window supersedes
            # the startup restore: the scan owns the progress bar, the Load
            # button, and the status line until it delivers, and its result
            # replaces whatever the restore would have shown.
            return
        try:
            self.load_cached_data()
        finally:
            self.progress.stop()
            # The snapshot load rewrites the status line, so a discarded
            # settings file reported at build time would be erased here;
            # appending it again keeps the notice visible after startup.
            self._report_discarded_settings()
        # Last startup step: if no snapshot restored and the paths are not
        # both usable, ask where the library is before leaving an empty table.
        self._maybe_show_first_run_paths_dialog()

    def load_cached_data(self):
        # The store reads and validates; this method only maps the result
        # onto the status line and delivers the rows (proposal 0008).
        result = self._snapshot_store.read(self.cache_var.get(), self.stats_var.get())
        if result.loaded:
            self._loaded(
                result.rows, result.files, result.skipped_files,
                result.files_without_charts, result.skipped_blocks,
                result.nested_song_tree,
                refreshed_at=result.refreshed_at,
                from_cache=True,
                source_paths=result.source_paths,
            )
            self._report_moved_source_paths(*result.source_paths)
            return
        if result.reason == "missing":
            self.status.set("No saved library yet. Choose File → Data paths…, then Load / refresh.")
        elif result.reason == "unreadable":
            self.status.set(f"Saved library snapshot could not be read ({result.detail}). Click Load / refresh to rebuild it.")
        elif result.reason == "invalid":
            self.status.set("Saved library snapshot is invalid or outdated. Click Load / refresh to rebuild it.")
        else:  # paths_mismatch
            self.status.set("Saved library snapshot is for different data paths. Click Load / refresh to rebuild it.")
        self.refresh_table()

    def _source_paths_changed(self):
        if not self.loaded_source_paths:
            return
        if self._current_paths_match_loaded():
            stamp = self._format_refresh_time(self.last_refreshed_at)
            self.status.set(f"Showing saved library snapshot · {len(self.rows):,} charts · last refreshed {stamp}.")
        else:
            self.status.set("Displayed library uses different data paths. Click Load / refresh to show the selected sources.")
        # While the Data paths dialog is open, the same news shows inside it
        # (the conditional note), not only on the status line behind the modal.
        # At first run there is no snapshot loaded, so the early return above
        # leaves the dialog's first-run note alone.
        self._set_data_paths_note(
            "" if self._current_paths_match_loaded() else self._DATA_PATHS_DIFFER_NOTE)

    def _current_paths_match_loaded(self):
        """Whether the current paths match the loaded snapshot's sources.

        True when no snapshot is loaded: there is nothing to differ from.
        Bare test instances without path state report True the same way.
        """
        loaded = getattr(self, "loaded_source_paths", None)
        if not loaded:
            return True
        cache_var = getattr(self, "cache_var", None)
        stats_var = getattr(self, "stats_var", None)
        if cache_var is None or stats_var is None:
            return True
        current = (cache_var.get(), stats_var.get())
        return all(
            _normalized_source_path(saved) == _normalized_source_path(selected)
            for saved, selected in zip(loaded, current))

    @staticmethod
    def _valid_course_geometry(value):
        """The canonical geometry string to restore the course window with, or None (issue #25)."""
        return _valid_window_geometry(value, theme.COURSE_BUILDER_MIN_SIZE)

    @staticmethod
    def _valid_advanced_search_geometry(value):
        """The canonical geometry string to restore the Advanced Search window with, or None (issue #98)."""
        return _valid_window_geometry(value, theme.ADVANCED_SEARCH_MIN_SIZE)

    def _report_discarded_settings(self):
        """Append the discarded-settings note to the status line, once.

        The wording mirrors the snapshot reader's ("Saved library snapshot
        could not be read (…)", load_cached_data): the file, the reason it
        could not be used, and what the app did instead — run on defaults.
        Appending, rather than replacing, keeps whatever the snapshot load
        reported; the status line is rewritten by the next load or refresh,
        so the notice is startup-scoped like the snapshot messages.
        """
        # load() runs before _build creates the status variable, so a bare
        # instance built for a _load_initial_snapshot test may not have a
        # store; that is "no failure", not an error.
        store = getattr(self, "_settings_store", None)
        reason = store.last_read_error if store is not None else None
        if reason is None:
            return
        message = f"Settings file could not be read ({reason}); using defaults."
        current = self.status.get()
        if message in current:
            return
        self.status.set(f"{current} {message}" if current else message)

    def _report_moved_source_paths(self, cache_dir: str, stats_file: str) -> None:
        """Append a note when a restored snapshot's saved paths no longer exist.

        The snapshot restores on a string match only, so a moved ITGmania
        folder is invisible until the next refresh fails. The note names the
        missing side and points at File → Data paths…, where replacements
        are picked.
        """
        missing = []
        if cache_dir and not Path(cache_dir).is_dir():
            missing.append("cache folder")
        if stats_file and not Path(stats_file).is_file():
            missing.append("Stats.xml")
        if not missing:
            return
        if len(missing) == 2:
            message = ("The saved cache folder and Stats.xml no longer exist. "
                       "Choose File → Data paths…, then Load / refresh.")
        elif missing[0] == "cache folder":
            message = ("The saved cache folder no longer exists. "
                       "Choose File → Data paths…, then Load / refresh.")
        else:
            message = ("The saved Stats.xml no longer exists. "
                       "Choose File → Data paths…, then Load / refresh.")
        # A bare instance built for a snapshot test may carry a Mock status
        # whose get() is not a string; that is "no status line", not an error.
        current = self.status.get()
        if not isinstance(current, str):
            current = ""
        if message in current:
            return
        self.status.set(f"{current} {message}" if current else message)

    def _save_settings(self, _event=None):
        if self.tree is None:
            return
        settings = {
            "cache_dir": self.cache_var.get(),
            "stats_file": self.stats_var.get(),
            "column_order": self.column_order,
            "column_visibility": {column: variable.get() for column, variable in self.column_visibility.items()},
            # Column widths are read back in physical pixels; divide by the
            # factor so the file keeps canonical 100% units (issue #51).
            "column_widths": {column: scale_pixels(self.tree.column(column, "width"), 1.0 / self._dpi_scale) for column in HEADERS},
            "sort_keys": [[column, descending] for column, descending in self.sort_keys],
            "show_distribution": self.show_distribution_panel.get(),
            "distribution_metric": self.distribution_metric.get(),
            "filter_pack": self.pack_var.get(),
            "filter_type": self.type_var.get(),
            "filter_difficulty": self.diff_var.get(),
        }
        # The course window's geometry joins the file only once the user has
        # actually placed the window (issue #25); a settings file that predates
        # the feature stays without the key until then.
        if self.course_geometry is not None:
            settings["course_geometry"] = self.course_geometry
        # The Advanced Search window's geometry, on the same terms (issue #98).
        if self.advanced_search_geometry is not None:
            settings["advanced_search_geometry"] = self.advanced_search_geometry
        # The store owns the dedup baseline and the atomic write (proposal
        # 0008); a failed write raises OSError, which the store leaves for
        # the app to report — and the baseline stays stale so the next
        # gesture retries.
        try:
            self._settings_store.save(settings)
        except OSError as exc:
            self.status.set(f"Could not save settings: {exc}")

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _selected_rows_for_course(self):
        """The chart rows currently selected in the main table (for the course builder)."""
        return [row for item in self.tree.selection()
                if (row := self.tree_item_rows.get(item)) is not None]

    def _library_rows_for_course(self):
        """Every chart row in the loaded library (for the course builder's ambiguity check)."""
        return self.rows

    def _dialog_is_open(self):
        for window in (self.advanced_search.window if self.advanced_search is not None else None,
                       self.course_builder.window if self.course_builder is not None else None,
                       self.about_window):
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
            self.tree.column(column, width=scale_pixels(width, self._dpi_scale))
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
        source = self._dragged_column
        start_x = self._drag_start_x
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
        row.pack(fill="x", pady=scale_pixels(3, self._dpi_scale))
        tk.Label(row, text=label, width=17, anchor="w", bg=theme.BG_PANEL, fg=theme.TEXT_FIELD_LABEL,
                 font=theme.FONT_BODY).pack(side="left")
        entry = self._entry(row, "", variable)
        entry.pack(side="left", fill="x", expand=True, padx=scale_pixels(8, self._dpi_scale))
        self._button(row, "Browse…", command).pack(side="left")
        return entry

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

    def _button(self, parent, text, command, primary=False):
        # An instance method so the padding can scale with this display
        # (issue #51); callers pass it around bound.
        return tk.Button(parent, text=text, command=command, bg=theme.ACCENT_BG if primary else theme.BG_BUTTON,
                         fg=theme.TEXT_ON_ACCENT, activebackground=theme.ACCENT_BG_HOVER if primary else theme.BG_BUTTON_HOVER,
                         activeforeground=theme.TEXT_ON_ACCENT, relief="flat",
                         padx=scale_pixels(theme.BUTTON_PADX, self._dpi_scale), pady=scale_pixels(theme.BUTTON_PADY, self._dpi_scale),
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

    def open_data_paths_dialog(self, note=None):
        """Open the Data paths dialog — the one place the two paths are edited.

        Modal: a local grab keeps the main window unusable until the dialog is
        dismissed (Cancel, the X button, or Escape), so the app never sits
        behind an unanswered first-run question. The dialog does not remember
        its geometry: it is a fixed small form, sized for two path rows.
        """
        if self._data_paths_window is not None and self._data_paths_window.winfo_exists():
            self._data_paths_window.lift()
            self._data_paths_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        self._data_paths_window = window
        window.title("Where is your library?")
        window.geometry(scale_geometry("560x260", self._dpi_scale))
        window.resizable(False, False)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.root)

        form = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale))
        form.pack(fill="x")
        self._data_paths_form = form
        # The note explains why the dialog opened (first run, dead saved
        # paths, invalid paths at Load, paths differing from the snapshot).
        # It is empty when opened from the menu with nothing to explain.
        # When no note is given, show the differ note if a snapshot is loaded
        # and the paths have already moved away from it.
        if note is None:
            note = "" if self._current_paths_match_loaded() else self._DATA_PATHS_DIFFER_NOTE
        self._data_paths_note = tk.Label(
            window, text="", wraplength=scale_pixels(520, self._dpi_scale), anchor="w", justify="left",
            fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY)
        self._set_data_paths_note(note or "")

        cache_entry = self._path_row(form, "Cache / Songs", self.cache_var, self.choose_cache)
        stats_entry = self._path_row(form, "Player Stats.xml", self.stats_var, self.choose_stats)

        btn_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale))
        btn_row.pack(fill="x", pady=(scale_pixels(14, self._dpi_scale), scale_pixels(16, self._dpi_scale)))
        self._button(btn_row, "Load library", self._data_paths_load, primary=True).pack(side="right")
        self._button(btn_row, "Cancel", self._close_data_paths_dialog).pack(side="right", padx=(0, scale_pixels(8, self._dpi_scale)))

        window.protocol("WM_DELETE_WINDOW", self._close_data_paths_dialog)
        window.bind("<Escape>", lambda _event: self._close_data_paths_dialog() or "break")
        # A new window does not always take keyboard focus (seen on Windows); without it Escape
        # would go to the main window instead of closing this one.
        window.grab_set()
        # Focus the entry that needs an answer: the invalid side, or the cache
        # entry when both are missing or both are fine.
        cache_ok = bool(self.cache_var.get()) and Path(self.cache_var.get()).is_dir()
        stats_ok = bool(self.stats_var.get()) and Path(self.stats_var.get()).is_file()
        target = stats_entry if cache_ok and not stats_ok else cache_entry
        target.focus_force()

    def _set_data_paths_note(self, text):
        """Show the Data paths dialog's note line, or hide it when empty.

        Nothing happens when the dialog is closed: the note label exists only
        while it is open.
        """
        note = getattr(self, "_data_paths_note", None)
        if note is None:
            return
        note.configure(text=text)
        if text:
            # The note sits above the path rows even when it appears later (a
            # path edited while the dialog is open).
            form = getattr(self, "_data_paths_form", None)
            if form is not None:
                note.pack(anchor="w", padx=scale_pixels(18, self._dpi_scale), pady=(scale_pixels(14, self._dpi_scale), scale_pixels(2, self._dpi_scale)), before=form)
            else:
                note.pack(anchor="w", padx=scale_pixels(18, self._dpi_scale), pady=(scale_pixels(14, self._dpi_scale), scale_pixels(2, self._dpi_scale)))
        else:
            note.pack_forget()

    def _close_data_paths_dialog(self):
        """Dismiss the Data paths dialog without loading."""
        window = getattr(self, "_data_paths_window", None)
        if window is not None and window.winfo_exists():
            if window.grab_status():
                window.grab_release()
            window.destroy()
        self._data_paths_window = None
        self._data_paths_note = None
        self._data_paths_form = None

    def _data_paths_load(self):
        """Load the library from the dialog's paths, or name what is wrong.

        With an invalid path the dialog stays open and the note says which
        side is wrong, instead of closing onto a Load that would only open
        the dialog again.
        """
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not cache.is_dir() or not stats.is_file():
            self._set_data_paths_note(self._invalid_paths_note(cache, stats))
            return
        self._close_data_paths_dialog()
        self.load_data()

    @staticmethod
    def _invalid_paths_note(cache, stats):
        """The note naming whichever of the two paths cannot be used."""
        cache_ok, stats_ok = cache.is_dir(), stats.is_file()
        if cache_ok and stats_ok:
            return ""
        if not cache_ok and not stats_ok:
            return "The cache folder and Stats.xml were not found. Choose new paths."
        if not cache_ok:
            return "The cache folder was not found. Choose a new Cache / Songs folder."
        return "The Stats.xml file was not found. Choose a new Player Stats.xml."

    def _maybe_show_first_run_paths_dialog(self):
        """Open the Data paths dialog once at startup when there is nothing to show.

        Only when no snapshot restored and the two current paths are not both
        usable. A user with a valid snapshot never sees it (the moved-folders
        status note covers dead paths there instead), and it never reappears
        in the same session after being dismissed. Bare test instances without
        path state return silently.
        """
        if getattr(self, "_data_paths_popup_shown", False):
            return
        if getattr(self, "loaded_source_paths", None) is not None:
            return
        cache_var = getattr(self, "cache_var", None)
        stats_var = getattr(self, "stats_var", None)
        if cache_var is None or stats_var is None:
            return
        cache_ok = bool(cache_var.get()) and Path(cache_var.get()).is_dir()
        stats_ok = bool(stats_var.get()) and Path(stats_var.get()).is_file()
        if cache_ok and stats_ok:
            return
        self._data_paths_popup_shown = True
        # Saved settings that point at dead folders get the dead-paths note;
        # anything else is a first run (or a partial guess).
        saved = getattr(self, "saved_settings", None) or {}
        note = (self._DATA_PATHS_DEAD_NOTE
                if "cache_dir" in saved or "stats_file" in saved
                else self._DATA_PATHS_FIRST_RUN_NOTE)
        self.open_data_paths_dialog(note=note)

    def load_data(self):
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not cache.is_dir() or not stats.is_file():
            # Invalid paths open the Data paths dialog instead of an error box:
            # the fix is in the dialog, so that is where the user should be.
            self.open_data_paths_dialog(note=self._invalid_paths_note(cache, stats))
            return
        self._save_settings()
        self.progress.start(12)
        self.status.set("Reading chart cache and player scores…")
        # Disabled until the scan's result is delivered, so a second click cannot
        # pile up scans; the File menu entry still starts a newer scan, which
        # supersedes this one by generation and owns re-enabling the button.
        self.load_button.configure(state="disabled")
        self._load_generation += 1
        generation = self._load_generation
        # The scan's clock for its time-remaining estimate (see _show_load_progress).
        self._load_started_at = time.monotonic()
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
            total = len(files)
            if self._load_is_stale(generation):
                # Superseded before the first file: queue nothing, not even
                # the progress report below.
                return
            # The total is known before any file is parsed: report it at once
            # so the bar can go determinate, then report as the loop goes.
            self._load_results.put(("progress", 0, total, generation))
            skipped_files = 0
            files_without_charts = 0
            skipped_blocks = 0
            for index, path in enumerate(files, start=1):
                if self._load_is_stale(generation):
                    return
                try:
                    chart_rows, blocks = parse_cache_file(path, scores)
                    skipped_blocks += blocks
                    if not chart_rows:
                        files_without_charts += 1
                    rows.extend(chart_rows)
                except (OSError, UnicodeError):
                    skipped_files += 1
                # Every 25 files, and on the last one: often enough for the
                # bar to move smoothly, rarely enough to churn the queue.
                # A scan superseded mid-loop stops reporting with it.
                if (index % 25 == 0 or index == total) and not self._load_is_stale(generation):
                    self._load_results.put(("progress", index, total, generation))

            nested_song_tree = looks_like_song_tree(cache) if not files else False
            cache_error = ""
            # The generation check and the snapshot write happen under one lock. Without it, an older
            # scan that passed the check could still be writing after a newer scan had written its
            # own snapshot, leaving the older data on disk.
            with self._snapshot_lock:
                if self._load_is_stale(generation):
                    return
                # The bar is already full here; name the phase so the tail
                # of the load does not look like a stall.
                self._load_results.put(("phase", "Saving snapshot…", generation))
                try:
                    refreshed_at = self._snapshot_store.write(
                        cache, stats_file, rows, len(files), skipped_files,
                        files_without_charts, nested_song_tree, skipped_blocks)
                except (OSError, TypeError, ValueError) as exc:
                    refreshed_at = ""
                    cache_error = str(exc)

            # Hand the result to the main thread through the queue. Calling Tk
            # (root.after) from this worker thread is not guaranteed safe.
            self._load_results.put(("loaded", (rows, len(files)), {
                "skipped_files": skipped_files,
                "files_without_charts": files_without_charts,
                "skipped_blocks": skipped_blocks,
                "nested_song_tree": nested_song_tree,
                "refreshed_at": refreshed_at,
                "cache_error": cache_error,
                "source_paths": (str(cache), str(stats_file)),
                "generation": generation,
            }))
        except ET.ParseError as exc:
            self._load_results.put(("failed",
                                    f"Stats.xml is malformed or incomplete and could not be parsed.\n\n{exc}",
                                    generation))
        except OSError as exc:
            self._load_results.put(("failed",
                                    f"Could not read the selected cache folder or Stats.xml.\n\n{exc}",
                                    generation))
        except Exception as exc:
            self._load_results.put(("failed", str(exc), generation))

    def _poll_load_results(self):
        # Runs on the main thread for the life of the window: deliver whatever
        # finished scans queued, then schedule the next poll. _loaded and
        # _load_failed drop results from superseded generations themselves.
        try:
            while True:
                result = self._load_results.get_nowait()
                if result[0] == "loaded":
                    _, args, kwargs = result
                    self._loaded(*args, **kwargs)
                elif result[0] == "progress":
                    _, done, total, generation = result
                    self._show_load_progress(done, total, generation)
                elif result[0] == "phase":
                    _, text, generation = result
                    self._show_load_phase(text, generation)
                else:
                    _, message, generation = result
                    self._load_failed(message, generation=generation)
        except queue.Empty:
            pass
        finally:
            try:
                self.root.after(75, self._poll_load_results)
            except tk.TclError:
                pass  # the window is gone; stop polling

    def _show_load_progress(self, done, total, generation):
        """Show a scan's progress on the main thread: determinate bar, files done, ETA.

        The first message of a scan carries the total, which is when the bar
        can go determinate — until then it bounced while Stats.xml parsed.
        The ETA is a straight line from the average rate so far; it only
        appears once 50 files are done, so the first few files cannot make
        it jump around.
        """
        if generation is not None and self._load_is_stale(generation):
            return
        if total > 0:
            # ["mode"] comes back as a Tcl index object, not a str, so the
            # comparison needs str() — a bare == "determinate" never matches.
            if str(self.progress["mode"]) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=total, value=0)
            self.progress["value"] = done
        text = f"Reading chart cache… {done:,} / {total:,} files"
        started = self._load_started_at
        if started is not None and done >= 50 and done < total:
            elapsed = time.monotonic() - started
            if elapsed > 0:
                remaining = elapsed * (total - done) / done
                text += f" · about {max(1, round(remaining))} s left"
        self.status.set(text)

    def _show_load_phase(self, text, generation):
        """Name a scan phase on the status line (e.g. the snapshot write)."""
        if generation is not None and self._load_is_stale(generation):
            return
        self.status.set(text)

    def _load_failed(self, message, generation=None):
        if generation is not None and self._load_is_stale(generation):
            return
        self.load_button.configure(state="normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.status.set("Could not load library.")
        messagebox.showerror("Could not load library", message)

    def _loaded(self, rows, files, skipped_files=0, files_without_charts=0, skipped_blocks=0,
                nested_song_tree=False,
                refreshed_at="", cache_error="", from_cache=False, source_paths=None, generation=None):
        if generation is not None and self._load_is_stale(generation):
            return
        self.load_button.configure(state="normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.rows = rows
        if source_paths:
            self.loaded_source_paths = source_paths
        self.last_refreshed_at = refreshed_at
        with self._batched_filter_changes():
            for combo, var, label, key in ((self.pack_filter, self.pack_var, "All packs", "Pack"),
                                           (self.type_filter, self.type_var, "All types", "Type")):
                values = [label] + sorted({str(r[key]) for r in rows if r[key]}, key=str.casefold)
                combo.configure(values=values)
                if var.get() not in values:
                    var.set(label)
            difficulties = sorted(
                {str(row["Difficulty"]) for row in rows if row["Difficulty"]},
                key=difficulty_sort_key,
            )
            difficulty_values = ["All difficulties"] + difficulties
            self.diff_filter.configure(values=difficulty_values)
            if self.diff_var.get() not in difficulty_values:
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
            if skipped_blocks:
                summary += f" · {skipped_blocks:,} chart blocks skipped (missing metadata)"
            self.status.set(summary + ".")
        if not from_cache and refreshed_at:
            self.status.set(self.status.get() + f" Snapshot refreshed {self._format_refresh_time(refreshed_at)}.")
        if not from_cache and cache_error:
            self.status.set(self.status.get() + f" Local snapshot not saved: {cache_error}")
        if self.course_builder is not None:
            # A fresh library may no longer match a course queue built from the old
            # one; the builder asks the user what to do with it (issue #82).
            self.course_builder.on_library_reloaded()

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
        if self.tree is None:
            return
        selected_rows = set()
        if preserve_selection:
            selected_rows = {
                id(self.tree_item_rows[item]) for item in self.tree.selection()
                if item in self.tree_item_rows
            }
        self._render_generation += 1
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
        self._tree_tint.reset()
        # The count label is set by _insert_batch: a progress count while rows
        # are still streaming in, the final totals once the last batch lands.
        self._insert_batch(visible, 0, generation, selected_rows)
        self.distribution_panel.show_rows(visible)

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
        # Insert for a short time budget rather than a fixed count: fast
        # machines finish in fewer, fuller batches; slow ones stay responsive.
        # At least one row always goes in, so the loop cannot stall.
        deadline = time.perf_counter() + ROW_INSERT_BUDGET_SECONDS
        stop = start
        while stop < len(rows):
            row = rows[stop]
            values = []
            for col in HEADERS:
                value = row.get(col, "")
                if col == "Time" and value != "":
                    value = format_duration(value)
                elif isinstance(value, float):
                    value = f"{value:g}"
                values.append(value)
            keep_selected = id(row) in selected_rows
            item = self.tree.insert("", "end", values=values, tags=row_tints.row_tags(row, keep_selected))
            self.tree_item_rows[item] = row
            if keep_selected:
                self.tree.selection_add(item)
                self._tree_tint.note_selected(item)
            stop += 1
            if time.perf_counter() >= deadline:
                break
        if stop < len(rows):
            self.count_label.set(f"Loading {stop:,} of {len(rows):,} charts…")
            self.root.after(1, lambda: self._insert_batch(rows, stop, generation, selected_rows))
        else:
            count_text = f"{len(rows):,} charts shown · {len(self.rows):,} total"
            hint = self._unreadable_search_hint()
            if hint:
                count_text += f" — {hint}"
            self.count_label.set(count_text)

    def _unreadable_search_hint(self) -> str:
        """Hint naming the first unreadable search directive, or "" when none.

        Bare instances in tests have no search_var; the real app always does.
        """
        search_var = getattr(self, "search_var", None)
        if search_var is None:
            return ""
        unreadable = find_unreadable_directives(search_var.get())
        return f"Can't read the value in {unreadable[0]}" if unreadable else ""

    def apply_chart_filter(self, difficulty=None, query=None):
        """Apply a distribution chart's filter change as one batched update (proposal 0005).

        The distribution panel computes the new values and calls this; a value left
        as None is not written, so the writes are exactly the ones the chart action
        calls for. Applying a change ends with the search cursor at the end of the
        box, as a chart click or Clear always has; a call with nothing to change
        neither refreshes nor nudges.
        """
        if difficulty is None and query is None:
            return
        with self._batched_filter_changes():
            if difficulty is not None:
                self.diff_var.set(difficulty)
            if query is not None:
                self.search_var.set(query)
        self.search_entry.icursor("end")

    def _select_all_rows(self, _event=None):
        """Ctrl+A in the table (issue #36): select every displayed row.

        The tree's contents are the filtered set, so selecting all of
        get_children() selects exactly what is shown. The selection
        event then updates the selected-row tint like any other
        selection change. Bound on the tree, not the root, so Ctrl+A
        in the search box or a path entry keeps its text meaning."""
        self.tree.selection_set(self.tree.get_children())

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
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.rows)
            self.status.set(f"Exported {len(self.rows):,} charts to {path}")
        except OSError as exc:
            self.status.set(f"Could not export CSV: {exc}")
            messagebox.showerror("Export failed", f"Could not write to {path}:\n\n{exc}")

    def open_about(self):
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            self.about_window.focus_force()  # raised from behind the main window: give it the keys too
            return

        window = tk.Toplevel(self.root)
        self.about_window = window
        window.title("About ITGmania Library Visualizer")
        window.resizable(False, False)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.root)

        tk.Label(window, text="ITGmania Library Visualizer", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_DIALOG_TITLE).pack(anchor="w", padx=scale_pixels(24, self._dpi_scale), pady=(scale_pixels(18, self._dpi_scale), scale_pixels(2, self._dpi_scale)))
        tk.Label(window, text=f"Version {__version__}", fg=theme.TEXT_PRIMARY, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY_BOLD).pack(anchor="w", padx=scale_pixels(24, self._dpi_scale))
        tk.Label(window, text="Released under the MIT License (see the LICENSE file).", fg=theme.TEXT_MUTED,
                 bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(anchor="w", padx=scale_pixels(24, self._dpi_scale), pady=(scale_pixels(10, self._dpi_scale), scale_pixels(14, self._dpi_scale)))

        btn_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(24, self._dpi_scale))
        btn_row.pack(fill="x", pady=(0, scale_pixels(16, self._dpi_scale)))
        self._button(btn_row, "Close", window.destroy, primary=True).pack(side="right")

        def _close(_event=None):
            window.destroy()
            return "break"

        window.bind("<Escape>", _close)
        window.bind("<Return>", _close)
        # A new window does not always take keyboard focus (seen on Windows); without it Escape and Return
        # would go to the main window instead of closing this one.
        window.focus_force()

def main():
    if tk is None:
        sys.exit("Tkinter is required to run the ITGmania Library Visualizer GUI.")
    # Declare DPI awareness before the first window exists (issue #51):
    # without it Windows bitmap-stretches the app at 125%/150%.
    declare_dpi_awareness()
    root = tk.Tk()
    LibraryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
