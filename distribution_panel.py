"""The distribution panel: the chart beside the song table (proposal 0005).

The component owns the panel end to end — its widgets, the chart, the
click and Clear handlers, and the visibility funnel. Everything it
needs from the main window arrives through its constructor: the four
shared Tk variables (the app creates them from saved settings and
keeps saving them), a way to pull rows when the chart's own metric is
the active filter, a callback that applies a chart filter change as
one batched update, and the app's settings save. The pure chart
arithmetic lives in library_data.py; this module is the Tk side.
"""

from __future__ import annotations

try:
    import tkinter as tk
except ImportError:
    tk = None

# matplotlib is imported lazily, the first time the chart canvas is actually
# needed (_load_matplotlib below): the import costs most of the app's startup
# import time, and the panel may never be opened. Until the first attempt,
# MATPLOTLIB_AVAILABLE is None ("not tried yet"); after it, the flag is True
# or False — exactly what an import-time check would have produced.
Figure = None
FigureCanvasTkAgg = None
MATPLOTLIB_AVAILABLE = None


def _load_matplotlib():
    """Import matplotlib once, on first use, and report whether it is available."""
    global Figure, FigureCanvasTkAgg, MATPLOTLIB_AVAILABLE
    if MATPLOTLIB_AVAILABLE is None:
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as canvas_class
            from matplotlib.figure import Figure as figure_class
        except ImportError:
            MATPLOTLIB_AVAILABLE = False
        else:
            Figure, FigureCanvasTkAgg = figure_class, canvas_class
            MATPLOTLIB_AVAILABLE = True
    return MATPLOTLIB_AVAILABLE

import theme
from library_data import (
    CHART_FILTER_FIELDS,
    aggregate_bpm_distribution,
    aggregate_difficulty_distribution,
    aggregate_meter_distribution,
    chart_bar_at,
    chart_bars,
    chart_clear_decision,
    chart_click_decision,
    distribution_summary_stats,
    get_active_chart_filters,
    parse_search_query,
    scale_pixels,
)


class DistributionPanel:
    """The distribution chart panel and its filter interactions.

    button_factory:           makes a themed button (LibraryApp._button)
    search_var:               the search box's variable (shared with the app)
    diff_var:                 the difficulty dropdown's variable (shared with the app)
    show_distribution_panel:  the View menu's show/hide variable (shared with the app)
    distribution_metric:      the Meter/Difficulty/BPM selector variable (shared with the app)
    filter_rows:              the app's row filter; called with ignore_metric=<metric>
                              when the chart's own metric is the active filter
    apply_chart_filter:       applies a (difficulty, query) change as one batched
                              update; a value of None is not written
    save_settings:            the app's settings save (visibility and metric persist)
    """

    # The display scale factor (1.0 at 100% DPI): bare instances in tests
    # have no window to measure, so they read canonical units as-is.
    _dpi_scale = 1.0

    def __init__(self, button_factory, search_var, diff_var, show_distribution_panel,
                 distribution_metric, filter_rows, apply_chart_filter, save_settings, dpi_scale=1.0):
        self._button = button_factory
        self.search_var = search_var
        self.diff_var = diff_var
        self.show_distribution_panel = show_distribution_panel
        self.distribution_metric = distribution_metric
        self._filter_rows = filter_rows
        self._apply_chart_filter = apply_chart_filter
        self._save_settings = save_settings
        # The display scale factor (issue #51): 1.0 at 100% DPI, 1.5 at
        # 150%. Pixel sizes are stored in canonical 100% units and scaled
        # to physical pixels when the panel is built.
        self._dpi_scale = dpi_scale
        # Filled in by build_panel(); None until then — the panel does nothing before it exists:
        self.dist_panel = None  # the panel frame; also the built-panel marker the guards check
        self.dist_summary_var = None
        self.dist_banner_frame = None
        self.dist_banner_label = None
        self.dist_chart_frame = None
        self.dist_button = None  # the app's toolbar button, whose label this component owns
        self._sibling_frame = None  # callable returning the app's table frame, for pack(before=…)
        # The matplotlib trio, created lazily on the first draw:
        self.dist_canvas = None
        self.dist_fig = None
        self.dist_ax = None
        self._matplotlib_missing_label = None  # the install note, created if the import fails
        self._current_dist_bars = []
        self._last_visible_rows = []

    def build_panel(self, content_frame, toolbar_button, sibling_frame):
        """Build the panel's widgets inside content_frame (called once, from the app's _build).

        The widgets cannot be built at construction time: their parent frame is
        created later in the app's build, as is the table frame the show path
        packs before — sibling_frame is a zero-argument callable returning that
        frame, resolved only when the panel is shown, so the app's build order
        does not change. This also sets the toolbar button's initial label (the
        ◀/▶ texts live only here) and performs the startup pack when the saved
        setting says the panel starts visible — with no before=, exactly as the
        app used to: the table frame is packed afterwards, so the panel still
        ends up ahead of it.
        """
        self.dist_button = toolbar_button
        self._sibling_frame = sibling_frame
        # The panel width is a pixel value in canonical 100% units; the
        # wraplengths below derive from the scaled width.
        panel_width = scale_pixels(theme.DIST_PANEL_WIDTH, self._dpi_scale)
        self.dist_panel = tk.Frame(content_frame, bg=theme.BG_PANEL, width=panel_width,
                                   padx=scale_pixels(10, self._dpi_scale), pady=scale_pixels(10, self._dpi_scale))
        self.dist_panel.pack_propagate(False)

        # Header: Title + Close button
        hdr = tk.Frame(self.dist_panel, bg=theme.BG_PANEL)
        hdr.pack(fill="x", pady=(0, scale_pixels(6, self._dpi_scale)))
        tk.Label(hdr, text="Distribution", fg=theme.TEXT_TITLE, bg=theme.BG_PANEL,
                 font=theme.FONT_PANEL_TITLE).pack(side="left")
        self._button(hdr, "✕", self.toggle).pack(side="right")

        # Metric selector
        metric_bar = tk.Frame(self.dist_panel, bg=theme.BG_PANEL)
        metric_bar.pack(fill="x", pady=(scale_pixels(4, self._dpi_scale), scale_pixels(6, self._dpi_scale)))
        for m in ("Meter", "Difficulty", "BPM"):
            b = tk.Radiobutton(
                metric_bar, text=m, value=m, variable=self.distribution_metric,
                indicatoron=False, bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY, selectcolor=theme.ACCENT_BG,
                activebackground=theme.ACCENT_BG, activeforeground=theme.WHITE, font=theme.FONT_SMALL,
                command=self._on_distribution_metric_changed, padx=scale_pixels(6, self._dpi_scale), pady=scale_pixels(3, self._dpi_scale),
            )
            b.pack(side="left", padx=scale_pixels(2, self._dpi_scale), expand=True, fill="x")

        # Summary line
        self.dist_summary_var = tk.StringVar(value="")
        tk.Label(self.dist_panel, textvariable=self.dist_summary_var, fg=theme.TEXT_MUTED, bg=theme.BG_PANEL,
                 font=theme.FONT_SMALL, wraplength=panel_width - 24, justify="left").pack(fill="x", pady=(0, scale_pixels(6, self._dpi_scale)))

        # Active filter banner: shown just above the chart, only while a chart filter is active.
        # It is built here but not packed; show_rows packs it before the chart container.
        self.dist_banner_frame = tk.Frame(self.dist_panel, bg=theme.BG_INPUT, padx=scale_pixels(8, self._dpi_scale), pady=scale_pixels(5, self._dpi_scale))
        self.dist_banner_label = tk.Label(self.dist_banner_frame, text="", fg=theme.ACCENT, bg=theme.BG_INPUT,
                                          font=theme.FONT_BODY, wraplength=panel_width - 90,
                                          justify="left", anchor="w")
        self.dist_banner_label.pack(side="left", fill="x", expand=True)
        self._button(self.dist_banner_frame, "Clear", self.clear_chart_filter).pack(side="right")

        # Chart container
        self.dist_chart_frame = tk.Frame(self.dist_panel, bg=theme.BG_PANEL)
        self.dist_chart_frame.pack(fill="both", expand=True)

        self.dist_button.configure(
            text="Distribution ◀" if self.show_distribution_panel.get() else "Distribution ▶")
        if self.show_distribution_panel.get():
            self.dist_panel.pack(side="right", fill="y", padx=(scale_pixels(10, self._dpi_scale), 0))

    def _ensure_distribution_canvas(self):
        if not _load_matplotlib():
            self._show_matplotlib_missing()
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

    def _show_matplotlib_missing(self):
        """Put the install-matplotlib note in the chart area (the import was tried and failed)."""
        if self.dist_chart_frame is None or self._matplotlib_missing_label is not None:
            return
        self._matplotlib_missing_label = tk.Label(
            self.dist_chart_frame,
            text="Install matplotlib to enable\ndistribution charts\n\nRun:\npip install matplotlib",
            fg=theme.TEXT_MUTED, bg=theme.BG_PANEL, font=theme.FONT_BODY, justify="center",
        )
        self._matplotlib_missing_label.pack(expand=True, pady=scale_pixels(40, self._dpi_scale))

    def set_visible(self, visible: bool):
        """Single source of truth for panel visibility (toolbar + View menu)."""
        if self.dist_panel is None:
            return
        self.show_distribution_panel.set(visible)
        if visible:
            self.dist_panel.pack(side="right", fill="y", padx=(scale_pixels(10, self._dpi_scale), 0), before=self._sibling_frame())
            self.dist_button.configure(text="Distribution ◀")
            self.show_rows(self._last_visible_rows)
        else:
            self.dist_panel.pack_forget()
            self.dist_button.configure(text="Distribution ▶")
            self.dist_panel.update_idletasks()
        self._save_settings()

    def toggle(self):
        """Toolbar button: flip current visibility."""
        self.set_visible(not self.show_distribution_panel.get())

    def sync_toggle(self):
        """View-menu checkbutton: BooleanVar already toggled by Tk; apply it to the UI."""
        self.set_visible(self.show_distribution_panel.get())

    def _on_distribution_metric_changed(self):
        self._save_settings()
        self.show_rows(self._last_visible_rows)

    def clear_chart_filter(self):
        """Remove every filter the distribution charts can set (difficulty, meter and BPM)."""
        decision = chart_clear_decision(self.diff_var.get(), self.search_var.get())
        if decision is None:
            return
        new_difficulty, new_query = decision
        self._apply_chart_filter(difficulty=new_difficulty, query=new_query)

    def _on_chart_click(self, event):
        # xdata and ydata are None when the click is outside the plot area (for example on a row label).
        clicked = chart_bar_at(self._current_dist_bars, event.xdata, event.ydata)
        if clicked is None:
            # Blank space, a '?' row or a row with nothing to filter to is not clickable.
            return
        new_difficulty, new_query = chart_click_decision(
            self.distribution_metric.get(), clicked.token, self.diff_var.get(), self.search_var.get())
        self._apply_chart_filter(difficulty=new_difficulty, query=new_query)

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

    def show_rows(self, visible_rows):
        self._last_visible_rows = visible_rows
        if self.dist_panel is None or not self.show_distribution_panel.get():
            return

        metric = self.distribution_metric.get()
        chart_rows = self._distribution_rows(metric)

        # Update active filter banner (every chart filter narrowing the table, not just this chart's)
        active_filters = get_active_chart_filters(self.diff_var.get(), self.search_var.get())
        if active_filters:
            banner = " · ".join(f"{name} {value}" for name, value in active_filters)
            self.dist_banner_label.configure(text=f"Filtered by: {banner}")
            self.dist_banner_frame.pack(fill="x", pady=(0, scale_pixels(6, self._dpi_scale)), before=self.dist_chart_frame)
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

        display_items = list(reversed(data_items))
        labels = [item[0] for item in display_items]
        counts = [item[1] for item in display_items]
        actives = [item[3] for item in display_items]

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

        self.dist_ax.barh(
            y_positions, counts, align="center",
            color=bar_colors, edgecolor=edge_colors, linewidth=linewidths, height=theme.CHART_BAR_HEIGHT,
        )

        max_count = max(counts) if counts else 1
        self._current_dist_bars, axis_max = chart_bars(
            display_items,
            min_click_fraction=theme.CHART_MIN_CLICK_FRACTION,
            bar_height=theme.CHART_BAR_HEIGHT,
            axis_headroom=theme.CHART_AXIS_HEADROOM,
        )
        for chart_bar, count in zip(self._current_dist_bars, counts):
            if count > 0:
                self.dist_ax.text(
                    count + max_count * 0.03, chart_bar.y_min + theme.CHART_BAR_HEIGHT / 2, str(count),
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
