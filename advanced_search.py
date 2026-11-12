"""The Advanced Search dialog: field filters that build a search query.

Tk-side companion to the dialog-query helpers in library_data.py. The
component owns its dialog; everything it needs from the main window
arrives through its constructor.
"""

from __future__ import annotations

try:
    import tkinter as tk
except ImportError:
    tk = None

import theme
from library_data import (
    GRADE_OPTIONS,
    build_dialog_query,
    format_geometry,
    parse_course_geometry,
    scale_geometry,
    scale_pixels,
    split_dialog_query,
)


class AdvancedSearch:
    """The Advanced Search dialog and its field-filter form.

    parent:         the main window (the dialog's parent)
    entry_factory:  makes a themed entry (LibraryApp._entry)
    button_factory: makes a themed button (LibraryApp._button)
    combo_factory:  makes a themed combobox (LibraryApp._combo)
    search_var:     the main window's search text variable: read to seed
                    the fields when the dialog opens, written on Apply
    saved_geometry: the remembered window geometry from settings, already
                    validated by the app (canonical form), or None
    report_geometry: callable told the window's geometry when it closes,
                    so the app can remember it for the next open; or None
    """

    # The display scale factor (1.0 at 100% DPI): bare instances in tests
    # have no window to measure, so they read canonical units as-is.
    _dpi_scale = 1.0

    def __init__(self, parent, entry_factory, button_factory, combo_factory, search_var,
                 saved_geometry=None, report_geometry=None, dpi_scale=1.0):
        self.parent = parent
        self._entry = entry_factory
        self._button = button_factory
        self._combo = combo_factory
        self._search_var = search_var
        self._saved_geometry = saved_geometry
        self._report_geometry = report_geometry
        # The display scale factor (issue #51): 1.0 at 100% DPI, 1.5 at
        # 150%. Geometry and pixel sizes are stored in canonical 100%
        # units and scaled to physical pixels on open.
        self._dpi_scale = dpi_scale
        self.window = None

    def _geometry_for_open(self):
        """The geometry string to open the dialog with (issue #98).

        The remembered geometry when a meaningful part of the window would
        be visible on the virtual desktop (which spans every monitor): at
        least a grabbable strip of it, so a window left hanging a little off
        an edge comes back as it was, while one left on a since-unplugged
        monitor, or pushed almost entirely off an edge, does not open lost.
        The top edge gets its own rule on top of that: a window can show
        plenty of its body while its title bar sits above every monitor
        (a stacked monitor unplugged since, say), leaving nothing to grab,
        so the top edge must sit within a few pixels of the desktop's top.
        In the fallback cases only the size is used and the window manager
        places the window, so a lost position can never be re-saved on
        close. Without a remembered geometry, the theme default. The same
        rules as the course window's (issue #25).
        """
        if not self._saved_geometry:
            return scale_geometry(theme.ADVANCED_SEARCH_GEOMETRY, self._dpi_scale)
        parsed = parse_course_geometry(self._saved_geometry)
        if parsed is None:
            return scale_geometry(theme.ADVANCED_SEARCH_GEOMETRY, self._dpi_scale)
        # The saved string is in canonical 100% units; the window opens in
        # physical pixels, so scale it — and the visibility thresholds — by
        # this display's factor before comparing against the virtual desktop.
        width, height, x, y = (scale_pixels(value, self._dpi_scale) for value in parsed)
        left = self.parent.winfo_vrootx()
        top = self.parent.winfo_vrooty()
        right = left + self.parent.winfo_vrootwidth()
        bottom = top + self.parent.winfo_vrootheight()
        visible_width = min(x + width, right) - max(x, left)
        visible_height = min(y + height, bottom) - max(y, top)
        if (visible_width >= scale_pixels(100, self._dpi_scale)
                and visible_height >= scale_pixels(32, self._dpi_scale)
                and y >= top - scale_pixels(16, self._dpi_scale)):
            return format_geometry(width, height, x, y)
        return f"{width}x{height}"

    def save_window_geometry(self):
        """Report the dialog's current geometry so the next open restores it (issue #98).

        Called when the dialog closes and when the app exits with the dialog
        open. Does nothing when the dialog is closed, and nothing while the
        window is minimized or maximized: those states report a parked or
        full-screen geometry the user did not choose as the window's place.
        """
        if self.window is None or not self.window.winfo_exists():
            return
        if self.window.state() != "normal":
            return
        # The window reports physical pixels; store canonical 100% units.
        self._saved_geometry = scale_geometry(self.window.geometry(), 1.0 / self._dpi_scale)
        if self._report_geometry is not None:
            self._report_geometry(self._saved_geometry)

    def _close_window(self):
        """Save the geometry and destroy the dialog: the one way this dialog closes.

        Every close path — the Close button, the window's X button, Escape,
        and Apply — funnels through here, so the geometry is remembered no
        matter how the dialog was dismissed (issue #98).
        """
        self.save_window_geometry()
        if self.window is not None:
            self.window.destroy()

    def open_dialog(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()  # raised from behind the main window: give it the keys too
            return

        window = tk.Toplevel(self.parent)
        self.window = window
        window.title("Advanced Search")
        window.geometry(self._geometry_for_open())
        window.minsize(scale_pixels(theme.ADVANCED_SEARCH_MIN_SIZE[0], self._dpi_scale),
                          scale_pixels(theme.ADVANCED_SEARCH_MIN_SIZE[1], self._dpi_scale))
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.parent)

        tk.Label(window, text="Advanced Search", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_DIALOG_TITLE).pack(anchor="w", padx=scale_pixels(18, self._dpi_scale), pady=(scale_pixels(14, self._dpi_scale), scale_pixels(2, self._dpi_scale)))
        tk.Label(window, text="Set field filters and a minimum grade. Free-text terms are ANDed; quote phrases.",
                 fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(anchor="w", padx=scale_pixels(18, self._dpi_scale), pady=(0, scale_pixels(10, self._dpi_scale)))

        form = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale))
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
        current = split_dialog_query(self._search_var.get())
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
            row.pack(fill="x", pady=scale_pixels(3, self._dpi_scale))
            tk.Label(row, text=label_text, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, width=12, anchor="w",
                     font=theme.FONT_BODY).pack(side="left")
            self._entry(row, "", var).pack(side="left", fill="x", expand=True)

        def add_range_row(parent, label_text, min_var, max_var, hint=""):
            row = tk.Frame(parent, bg=theme.BG_WINDOW)
            row.pack(fill="x", pady=scale_pixels(3, self._dpi_scale))
            tk.Label(row, text=label_text, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, width=12, anchor="w",
                     font=theme.FONT_BODY).pack(side="left")
            e1 = self._entry(row, "", min_var)
            e1.pack(side="left", fill="x", expand=True)
            tk.Label(row, text="to", fg=theme.TEXT_HINT, bg=theme.BG_WINDOW, padx=scale_pixels(8, self._dpi_scale), font=theme.FONT_BODY).pack(side="left")
            e2 = self._entry(row, "", max_var)
            e2.pack(side="left", fill="x", expand=True)
            if hint:
                tk.Label(row, text=hint, fg=theme.TEXT_HINT, bg=theme.BG_WINDOW, font=theme.FONT_SMALL, padx=scale_pixels(6, self._dpi_scale)).pack(side="left")

        add_text_row(form, "Text", free_text_var)
        add_text_row(form, "Title", title_var)
        add_text_row(form, "Artist", artist_var)
        add_text_row(form, "Pack", pack_var)

        tk.Frame(form, bg=theme.BG_INPUT, height=scale_pixels(1, self._dpi_scale)).pack(fill="x", pady=scale_pixels(10, self._dpi_scale))

        add_range_row(form, "Meter", meter_min_var, meter_max_var)
        add_range_row(form, "BPM", bpm_min_var, bpm_max_var)
        add_range_row(form, "Time", time_min_var, time_max_var, "e.g. 1:30 or 90")
        add_range_row(form, "Peak NPS", nps_min_var, nps_max_var)

        g_row = tk.Frame(form, bg=theme.BG_WINDOW)
        g_row.pack(fill="x", pady=scale_pixels(3, self._dpi_scale))
        tk.Label(g_row, text="Min Grade", fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, width=12, anchor="w",
                 font=theme.FONT_BODY).pack(side="left")
        g_options = ["Any"] + list(GRADE_OPTIONS)
        self._combo(g_row, grade_min_var, g_options).pack(side="left")

        tk.Frame(form, bg=theme.BG_INPUT, height=scale_pixels(1, self._dpi_scale)).pack(fill="x", pady=scale_pixels(10, self._dpi_scale))
        add_text_row(form, "Other filters", other_var)
        tk.Label(form, text="Kept from your search: filters without a box above. Edit or clear them here.",
                 fg=theme.TEXT_HINT, bg=theme.BG_WINDOW, font=theme.FONT_SMALL, anchor="w").pack(fill="x")

        preview_frame = tk.Frame(window, bg=theme.BG_PREVIEW, padx=scale_pixels(12, self._dpi_scale), pady=scale_pixels(8, self._dpi_scale))
        preview_frame.pack(fill="x", padx=scale_pixels(18, self._dpi_scale), pady=(scale_pixels(10, self._dpi_scale), scale_pixels(4, self._dpi_scale)))
        tk.Label(preview_frame, text="Query:", fg=theme.TEXT_MUTED, bg=theme.BG_PREVIEW,
                 font=theme.FONT_SMALL).pack(side="left", padx=(0, scale_pixels(6, self._dpi_scale)))
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

        btn_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(12, self._dpi_scale))
        btn_row.pack(fill="x", side="bottom")

        def apply_search():
            q = build_query()
            self._search_var.set(q)
            self._close_window()

        def clear_fields():
            for v in (free_text_var, title_var, artist_var, pack_var, meter_min_var, meter_max_var,
                      bpm_min_var, bpm_max_var, time_min_var, time_max_var, nps_min_var, nps_max_var,
                      other_var):
                v.set("")
            grade_min_var.set("Any")

        self._button(btn_row, "Apply", apply_search, primary=True).pack(side="right", padx=(scale_pixels(6, self._dpi_scale), 0))
        self._button(btn_row, "Close", self._close_window).pack(side="right")
        self._button(btn_row, "Clear", clear_fields).pack(side="left")

        def _close(_event=None):
            self._close_window()
            return "break"

        def _apply_and_close(_event=None):
            apply_search()
            return "break"

        window.bind("<Escape>", _close)
        window.bind("<Return>", _apply_and_close)
        window.protocol("WM_DELETE_WINDOW", self._close_window)
        # A new window does not always take keyboard focus (seen on Windows); without it Escape and Return
        # would go to the main window instead of this one.
        window.focus_force()
