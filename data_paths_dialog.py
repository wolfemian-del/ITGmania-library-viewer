"""The Data paths dialog: the one place the two library paths are edited.

Tk-side companion to the path helpers in library_data.py. The component
owns its dialog; everything it needs from the main window arrives through
its constructor. It never touches the table, the stores, or the status line.
"""

from __future__ import annotations

from pathlib import Path
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    tk = None
    filedialog = None

import theme
from library_data import invalid_paths_note, scale_geometry, scale_pixels


class DataPathsDialog:
    """The dialog where the two library paths are edited.

    parent:             the root window, for the Toplevel
    cache_var:          the cache-path variable, shared with the app and
                        the loader; the dialog edits it, they read it
    stats_var:          the Stats.xml-path variable, shared the same way
    load_callback:      a zero-argument callable, invoked when the user
                        presses Load (today's load_data)
    save_settings:      callable, invoked when a path is chosen
    button_factory:     makes a themed button (LibraryApp._button)
    entry_factory:      makes a themed entry (LibraryApp._entry)
    dpi_scale:          the display scale factor, for the path rows and
                        the note line
    paths_match_loaded: a zero-argument callable returning whether the
                        dialog's paths match the loaded snapshot's sources
                        (today's _current_paths_match_loaded)
    """

    # The dialog's note texts (UI redesign): the first-run note is the
    # sketch's wording; the dead-paths sentence is a Muse proposal, to be
    # settled in the build review.
    _DATA_PATHS_FIRST_RUN_NOTE = ("We couldn't find your ITGmania folders automatically — "
                                  "point the app at them once and it will remember.")
    _DATA_PATHS_DEAD_NOTE = ("Your saved paths no longer exist — "
                             "point the app at them again and it will remember.")
    _DATA_PATHS_DIFFER_NOTE = ("These paths differ from the library on screen — "
                               "Load / refresh to rebuild it.")

    def __init__(self, parent, cache_var, stats_var, load_callback,
                 save_settings, button_factory, entry_factory, dpi_scale,
                 paths_match_loaded):
        self.parent = parent
        self.cache_var = cache_var
        self.stats_var = stats_var
        self.load_callback = load_callback
        self.save_settings = save_settings
        self.button_factory = button_factory
        self.entry_factory = entry_factory
        self.dpi_scale = dpi_scale
        self.paths_match_loaded = paths_match_loaded
        # The window and its note line while it is open, and whether the
        # first-run popup has already shown this session (it never reappears
        # after being dismissed).
        self._data_paths_window = None
        self._data_paths_note = None
        self._data_paths_form = None
        self._data_paths_popup_shown = False

    def open(self, note=None):
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
        window = tk.Toplevel(self.parent)
        self._data_paths_window = window
        window.title("Where is your library?")
        window.geometry(scale_geometry("560x260", self.dpi_scale))
        window.resizable(False, False)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.parent)

        form = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(18, self.dpi_scale))
        form.pack(fill="x")
        self._data_paths_form = form
        # The note explains why the dialog opened (first run, dead saved
        # paths, invalid paths at Load, paths differing from the snapshot).
        # It is empty when opened from the menu with nothing to explain.
        # When no note is given, show the differ note if a snapshot is loaded
        # and the paths have already moved away from it.
        if note is None:
            note = "" if self.paths_match_loaded() else self._DATA_PATHS_DIFFER_NOTE
        self._data_paths_note = tk.Label(
            window, text="", wraplength=scale_pixels(520, self.dpi_scale), anchor="w", justify="left",
            fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY)
        self.set_note(note or "")

        cache_entry = self._path_row(form, "Cache / Songs", self.cache_var, self.choose_cache)
        stats_entry = self._path_row(form, "Player Stats.xml", self.stats_var, self.choose_stats)

        btn_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(18, self.dpi_scale))
        btn_row.pack(fill="x", pady=(scale_pixels(14, self.dpi_scale), scale_pixels(16, self.dpi_scale)))
        self.button_factory(btn_row, "Load library", self._load, primary=True).pack(side="right")
        self.button_factory(btn_row, "Cancel", self.close).pack(side="right", padx=(0, scale_pixels(8, self.dpi_scale)))

        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _event: self.close() or "break")
        # A new window does not always take keyboard focus (seen on Windows); without it Escape
        # would go to the main window instead of closing this one.
        window.grab_set()
        # Focus the entry that needs an answer: the invalid side, or the cache
        # entry when both are missing or both are fine.
        cache_ok = bool(self.cache_var.get()) and Path(self.cache_var.get()).is_dir()
        stats_ok = bool(self.stats_var.get()) and Path(self.stats_var.get()).is_file()
        target = stats_entry if cache_ok and not stats_ok else cache_entry
        target.focus_force()

    def set_note(self, text):
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
                note.pack(anchor="w", padx=scale_pixels(18, self.dpi_scale), pady=(scale_pixels(14, self.dpi_scale), scale_pixels(2, self.dpi_scale)), before=form)
            else:
                note.pack(anchor="w", padx=scale_pixels(18, self.dpi_scale), pady=(scale_pixels(14, self.dpi_scale), scale_pixels(2, self.dpi_scale)))
        else:
            note.pack_forget()

    def close(self):
        """Dismiss the Data paths dialog without loading."""
        window = getattr(self, "_data_paths_window", None)
        if window is not None and window.winfo_exists():
            if window.grab_status():
                window.grab_release()
            window.destroy()
        self._data_paths_window = None
        self._data_paths_note = None
        self._data_paths_form = None

    def paths_changed(self):
        """Return the note the dialog should show when the paths may have moved.

        Empty when the dialog's paths match the loaded snapshot's sources,
        the differ note when they have moved away from it. [CODE] The loader's
        _source_paths_changed calls this instead of importing the dialog's
        note constant.
        """
        return "" if self.paths_match_loaded() else self._DATA_PATHS_DIFFER_NOTE

    def maybe_show_first_run(self, snapshot_loaded, had_saved_paths):
        """Open the Data paths dialog once at startup when there is nothing to show.

        Only when no snapshot is loaded and the two current paths are not both
        usable. A user with a loaded snapshot never sees it (the moved-folders
        status note covers dead paths there instead), and it never reappears
        in the same session after being dismissed. The two facts it cannot
        derive from its inputs arrive as arguments: whether a snapshot is
        loaded, and whether saved settings contained path keys (the
        paths_match_loaded callable returns True both when nothing is loaded
        and when the paths match, so it cannot tell the two apart).
        """
        if self._data_paths_popup_shown:
            return
        if snapshot_loaded:
            return
        cache_ok = bool(self.cache_var.get()) and Path(self.cache_var.get()).is_dir()
        stats_ok = bool(self.stats_var.get()) and Path(self.stats_var.get()).is_file()
        if cache_ok and stats_ok:
            return
        self._data_paths_popup_shown = True
        # Saved settings that point at dead folders get the dead-paths note;
        # anything else is a first run (or a partial guess).
        note = (self._DATA_PATHS_DEAD_NOTE if had_saved_paths
                else self._DATA_PATHS_FIRST_RUN_NOTE)
        self.open(note=note)

    def choose_cache(self):
        path = filedialog.askdirectory(title="Select the ITGmania Cache/Songs folder")
        if path:
            self.cache_var.set(path)
            self.save_settings()

    def choose_stats(self):
        path = filedialog.askopenfilename(title="Select player Stats.xml", filetypes=[("Stats.xml", "Stats.xml"),
                                                                                       ("XML files", "*.xml"),
                                                                                       ("All files", "*.*")])
        if path:
            self.stats_var.set(path)
            self.save_settings()

    def _path_row(self, parent, label, variable, command):
        row = tk.Frame(parent, bg=theme.BG_PANEL)
        row.pack(fill="x", pady=scale_pixels(3, self.dpi_scale))
        tk.Label(row, text=label, width=17, anchor="w", bg=theme.BG_PANEL, fg=theme.TEXT_FIELD_LABEL,
                 font=theme.FONT_BODY).pack(side="left")
        entry = self.entry_factory(row, "", variable)
        entry.pack(side="left", fill="x", expand=True, padx=scale_pixels(8, self.dpi_scale))
        self.button_factory(row, "Browse…", command).pack(side="left")
        return entry

    def _load(self):
        """Load the library from the dialog's paths, or name what is wrong.

        With an invalid path the dialog stays open and the note says which
        side is wrong, instead of closing onto a Load that would only open
        the dialog again.
        """
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not cache.is_dir() or not stats.is_file():
            self.set_note(invalid_paths_note(cache, stats))
            return
        self.close()
        self.load_callback()
