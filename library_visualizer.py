"""A small desktop browser for ITGmania's song cache and Stats.xml."""

from __future__ import annotations

import contextlib
import csv
import sys
import time
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
from pathlib import Path

# The release number, shown in Help > About. Keep it equal to the newest heading in CHANGELOG.md (a test checks).
__version__ = "1.2.1"

import row_tints
import theme
from advanced_search import AdvancedSearch
from course_builder import CourseBuilder
from data_paths_dialog import DataPathsDialog
from library_loader import LibraryLoader
from distribution_panel import DistributionPanel
from library_data import (
    TAP_FIELDS,
    TECH_FIELDS,
    CHART_FILTER_FIELDS,
    LIBRARY_CACHE_SCHEMA_VERSION,
    SettingsStore,
    SnapshotStore,
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
    match_chart_query,
    number,
    parse_search_query,
    scale_geometry,
    scale_pixels,
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
    # The display scale factor (1.0 at 100% DPI): bare instances in tests
    # have no window to measure, so they read canonical units as-is.
    _dpi_scale = 1.0

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
        # The Data paths dialog (UI redesign, proposal 0009 Step 3): the
        # component owns its window and note line. It is built first; its
        # load_callback and paths_match_loaded are late-bound lambdas (the
        # proposal 0005 precedent) so they resolve to the loader's methods
        # once the loader exists (Step 4).
        self._data_paths_dialog = DataPathsDialog(
            self.root, self.cache_var, self.stats_var,
            load_callback=lambda: self._loader.load_data(),
            save_settings=self._save_settings,
            button_factory=self._button, entry_factory=self._entry,
            dpi_scale=self._dpi_scale,
            paths_match_loaded=lambda: self._loader._current_paths_match_loaded())
        self._style()
        self._build()
        # The loader (proposal 0009 Step 4): built once the status
        # widgets exist. The dialog was built first, with late-bound
        # lambdas, so it can take the loader's methods here.
        saved = self.saved_settings
        self._loader = LibraryLoader(
            self._snapshot_store, self.cache_var, self.stats_var,
            self.status, self.progress, self.load_button,
            self._set_sync_menu_state, self._on_library_changed,
            self._on_nothing_loaded, self._data_paths_dialog,
            self._save_settings, self.root,
            self._report_discarded_settings,
            "cache_dir" in saved or "stats_file" in saved)
        self._report_discarded_settings()
        self.search_var.trace_add("write", lambda *_: self._schedule_search_refresh())
        for var in (self.pack_var, self.type_var, self.diff_var, self.scored_var):
            var.trace_add("write", lambda *_: self._refresh_unless_batching())
        for var in (self.cache_var, self.stats_var):
            var.trace_add("write", lambda *_: self._loader._source_paths_changed())
        self.root.after(75, self._loader._poll_load_results)
        # The saved snapshot is loaded once the window has painted, not here:
        # reading and rendering it can take a moment at library scale, and doing
        # it before the event loop starts would leave the user watching the
        # console (or an unpainted window) with no explanation.
        if self.library_cache_path.is_file():
            self.status.set("Loading saved library…")
            self.progress.start(12)
        self.root.after(50, self._loader._load_initial_snapshot)

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
        file_menu.add_command(label="Sync scores from Stats.xml", command=self.sync_scores)
        file_menu.add_command(label="Export CSV…", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Data paths…", command=self.open_data_paths_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close_app)
        menubar.add_cascade(label="File", menu=file_menu)
        self._file_menu = file_menu  # the sync entry is disabled while a scan runs (issue #147)

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
        return self._loader.rows

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

    def open_data_paths_dialog(self, note=None):
        """Open the Data paths dialog (proposal 0009 Step 3).

        A thin delegation to the DataPathsDialog component, which owns the
        dialog. Kept so the File menu and the loader paths that open it do
        not change.
        """
        self._data_paths_dialog.open(note)

    def load_data(self):
        """Start a library load (thin delegation to the loader)."""
        self._loader.load_data()

    def sync_scores(self):
        """Start a scores-only sync (thin delegation to the loader)."""
        self._loader.sync_scores()

    def _on_library_changed(self, rows, preserve_selection):
        """The app-side part of a finished load or sync (Q2).

        preserve_selection distinguishes a sync from a load: a sync
        re-scores the same rows, so only the table refreshes (keeping
        the selection); a load brings fresh rows, so the dropdowns
        reset (batched, so the table refreshes exactly once) and the
        Course Builder is told the library changed.
        """
        if preserve_selection:
            self.refresh_table(preserve_selection=True)
            return
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
        if self.course_builder is not None:
            # A fresh library may no longer match a course queue built from the old
            # one; the builder asks the user what to do with it (issue #82).
            self.course_builder.on_library_reloaded()

    def _on_nothing_loaded(self):
        """The initial refresh when no snapshot was restored."""
        self.refresh_table()

    def _set_sync_menu_state(self, state):
        """Enable or disable the File -> Sync scores entry (issue #147).

        A bare instance built for a load test may have no menubar; that is
        "no menu to update", not an error.
        """
        file_menu = getattr(self, "_file_menu", None)
        if file_menu is None:
            return
        file_menu.entryconfigure("Sync scores from Stats.xml", state=state)

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
        for row in self._loader.rows:
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
            count_text = f"{len(rows):,} charts shown · {len(self._loader.rows):,} total"
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
        if not self._loader.rows:
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
                writer.writerows(self._loader.rows)
            self.status.set(f"Exported {len(self._loader.rows):,} charts to {path}")
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
