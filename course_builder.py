"""The Build-a-course dialog: queue charts and save or append .CRS files.

Tk-side companion to the course helpers in library_data.py. The component
owns its dialog and queue; everything it needs from the main window arrives
through its constructor.
"""

from __future__ import annotations

import re
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

import row_tints
import theme
from library_data import (
    course_append_bytes,
    course_song_lines,
    find_ambiguous_course_entries,
    format_duration,
    format_new_course,
    number,
    parse_course_geometry,
    validate_course_fields,
)

class CourseBuilder:
    """The course-builder dialog and its chart queue.

    parent:         the main window (the dialog's parent)
    status:         the main window's status variable (set on save/append)
    button_factory: makes a themed button (LibraryApp._button)
    selected_rows:  callable returning the main table's selected chart rows
    library_rows:   callable returning every chart row in the loaded library
                    (the save-time ambiguity check compares the queue against it)
    """

    def __init__(self, parent, status, button_factory, selected_rows, library_rows,
                 saved_geometry=None, report_geometry=None):
        self.parent = parent
        self._status = status
        self._button = button_factory
        self._selected_rows = selected_rows
        self._library_rows = library_rows
        # Window geometry memory (issue #25, proposal 0003): the geometry to restore
        # on open, and the callback that receives the final geometry on close. Both
        # are optional; without them the window opens at the theme default and
        # reports nothing.
        self._saved_geometry = saved_geometry
        self._report_geometry = report_geometry
        self.window = None
        self.entries: list[dict] = []
        self._last_removal = None  # [(index, row), ...] of the latest removal, for Undo remove (issue #85)
        self.title_var = None
        self.tree = None
        self.count_var = None
        # The tint exists from construction so selection bookkeeping never meets
        # None (issue #92); open_dialog replaces it with one bound to the queue tree.
        self._tint = row_tints.SelectedRowTint(None)

    def _geometry_for_open(self):
        """The geometry string to open the dialog with (issue #25).

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
        close. Without a remembered geometry, the theme default.
        """
        if not self._saved_geometry:
            return theme.COURSE_BUILDER_GEOMETRY
        parsed = parse_course_geometry(self._saved_geometry)
        if parsed is None:
            return theme.COURSE_BUILDER_GEOMETRY
        width, height, x, y = parsed
        left = self.parent.winfo_vrootx()
        top = self.parent.winfo_vrooty()
        right = left + self.parent.winfo_vrootwidth()
        bottom = top + self.parent.winfo_vrootheight()
        visible_width = min(x + width, right) - max(x, left)
        visible_height = min(y + height, bottom) - max(y, top)
        if visible_width >= 100 and visible_height >= 32 and y >= top - 16:
            return self._saved_geometry
        return f"{width}x{height}"

    def open_dialog(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        window = tk.Toplevel(self.parent)
        self.window = window
        window.title("Build a course")
        window.geometry(self._geometry_for_open())
        window.minsize(*theme.COURSE_BUILDER_MIN_SIZE)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.parent)
        self.entries: list[dict] = []
        self._last_removal = None  # a reopened window starts a fresh queue, with nothing to undo

        tk.Label(window, text="Build a new course", fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_COURSE_TITLE).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(window, text="Select charts in the library, then add them here and arrange the course order.",
                 fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(anchor="w", padx=18, pady=(0, 12))

        title_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=18)
        title_row.pack(fill="x", pady=(0, 10))
        tk.Label(title_row, text="Course title", width=13, anchor="w", fg=theme.TEXT_FIELD_LABEL, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left")
        self.title_var = tk.StringVar()
        tk.Entry(title_row, textvariable=self.title_var, bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY,
                 insertbackground=theme.CURSOR, relief="flat", font=theme.FONT_ENTRY_LARGE,
                 highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT).pack(
                     side="left", fill="x", expand=True)

        queue_frame = tk.Frame(window, bg=theme.BG_WINDOW)
        queue_frame.pack(fill="both", expand=True, padx=18)
        columns = ("Pack", "Title", "Type", "Difficulty", "Meter", "Time")
        self.tree = ttk.Treeview(queue_frame, columns=columns, show="headings", selectmode="extended")
        widths = {"Pack": 180, "Title": 300, "Type": 130, "Difficulty": 120, "Meter": 80, "Time": 80}
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=widths[column], minwidth=65, stretch=column == "Title",
                                    anchor="w" if column in ("Pack", "Title") else "center")
        queue_scroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=queue_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")
        queue_frame.grid_rowconfigure(0, weight=1)
        queue_frame.grid_columnconfigure(0, weight=1)
        # Difficulty tints and the white selected-row tag, shared with the song table (row_tints).
        row_tints.configure_tree_tags(self.tree)
        self._tint = row_tints.SelectedRowTint(self.tree)  # a new tree starts with no rows selected
        self.tree.bind("<<TreeviewSelect>>", self._tint.on_select)
        # The Remove button has keyboard equivalents while the queue has focus.
        self.tree.bind("<Delete>", self._remove_on_key)
        self.tree.bind("<BackSpace>", self._remove_on_key)
        # So does Undo remove. Tk names the key "z" or "Z" depending on Caps Lock (and Shift),
        # so both are bound; without the second, Ctrl+Z does nothing while Caps Lock is on.
        self.tree.bind("<Control-z>", self._undo_on_key)
        self.tree.bind("<Control-Z>", self._undo_on_key)

        controls = tk.Frame(window, bg=theme.BG_WINDOW, padx=18, pady=12)
        controls.pack(fill="x")
        self._button(controls, "Add selected charts", self.add_selected, primary=True).pack(side="left")
        self._button(controls, "Remove", self.remove_entries).pack(side="left", padx=(8, 0))
        self._button(controls, "Undo remove", self.undo_remove).pack(side="left", padx=(8, 0))
        self._button(controls, "Move up", lambda: self.move_entry(-1)).pack(side="left", padx=(8, 0))
        self._button(controls, "Move down", lambda: self.move_entry(1)).pack(side="left", padx=(8, 0))
        self.count_var = tk.StringVar(value="0 charts · 0:00 total")
        tk.Label(controls, textvariable=self.count_var, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left", padx=12)
        self._button(controls, "Append to .CRS…", self.append_to_existing).pack(side="right", padx=(0, 8))
        self._button(controls, "Save new .CRS…", self.save_new, primary=True).pack(side="right")

        def _close(_event=None):
            # Reopening this window starts an empty queue, so closing with charts queued loses them.
            queued = len(self.entries)
            if queued and not messagebox.askyesno(
                    "Discard course queue?",
                    f"Closing this window discards the {queued} queued chart(s). Close anyway?",
                    parent=window):
                return "break"
            self.save_window_geometry()
            window.destroy()
            return "break"

        window.bind("<Escape>", _close)
        window.protocol("WM_DELETE_WINDOW", _close)  # the X button gets the same discard prompt as Escape
        # A new window does not always take keyboard focus by itself (seen on Windows);
        # without this, Escape would go to the main window instead of closing this one.
        window.focus_force()

        self.add_selected()

    def on_library_reloaded(self):
        """Ask what to do with the queue after the main window loads a fresh library.

        The queued rows came from the previous library, so if it changed they may
        no longer match what a save would suggest. The owner's choice (issue #82,
        option 1) is to ask here, at reload time; agreeing clears the queue so it
        can be rebuilt from the new library. Called by LibraryApp after a load;
        does nothing unless the dialog is open. With an empty queue there is
        nothing to ask about, but a removal remembered for Undo remove still holds
        rows from the previous library, so it is forgotten here.
        """
        if self.window is None or not self.window.winfo_exists():
            return
        if not self.entries:
            self._last_removal = None  # no prompt, but undo must not bring back previous-library rows
            return
        queued = len(self.entries)
        if messagebox.askyesno(
                "Library reloaded",
                f"The library was reloaded while a course is being built. The {queued} queued "
                "chart(s) came from the previous library and may no longer match it.\n\n"
                "Clear the queue so it can be rebuilt from the reloaded library?",
                parent=self.window):
            self.entries = []
            self._last_removal = None  # the remembered removal belonged to the cleared queue
            self.refresh_queue()

    def confirm_discard_for_app_exit(self):
        """Ask whether quitting the app may discard the queue (issue #87).

        The main window calls this on its single exit path: destroying the
        root would tear this dialog down without running its own close
        prompt, so the discard decision has to be asked for here, where the
        queue lives. Returns True when quitting may proceed — the dialog is
        closed, the queue is empty, or the user agrees to discard it.
        """
        if self.window is None or not self.window.winfo_exists() or not self.entries:
            return True
        queued = len(self.entries)
        return messagebox.askyesno(
            "Discard course queue?",
            f"Quitting the app discards the {queued} queued chart(s). Quit anyway?",
            parent=self.window)

    def save_window_geometry(self):
        """Report the dialog's current geometry so the next open restores it (issue #25).

        Called when the dialog closes and when the app exits with the dialog
        open. Does nothing when the dialog is closed, and nothing while the
        window is minimized or maximized: those states report a parked or
        full-screen geometry the user did not choose as the window's place.
        """
        if self.window is None or not self.window.winfo_exists():
            return
        if self.window.state() != "normal":
            return
        self._saved_geometry = self.window.geometry()
        if self._report_geometry is not None:
            self._report_geometry(self._saved_geometry)

    def add_selected(self):
        added = 0
        for row in self._selected_rows():
            self.entries.append(row)
            added += 1
        if added:
            self._last_removal = None  # the queue changed, so the remembered positions no longer apply
            self.refresh_queue()

    def refresh_queue(self, selected_indices=None):
        selected_indices = selected_indices or []
        valid = [index for index in selected_indices if 0 <= index < len(self.entries)]
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.entries):
            self.tree.insert("", "end", iid=str(index), values=(
                row.get("Pack", ""), row.get("Title", ""), row.get("Type", ""),
                row.get("Difficulty", ""), row.get("Meter", ""),
                format_duration(row.get("Time", 0)) if row.get("Time", "") != "" else "",
            ), tags=row_tints.row_tags(row, index in valid))  # a kept selection is born with the white tag
        total_seconds = sum(number(row.get("Time")) for row in self.entries)
        self.count_var.set(f"{len(self.entries)} charts · {format_duration(total_seconds)} total")
        if valid:
            self.tree.selection_set(*(str(index) for index in valid))
            self.tree.focus(str(valid[0]))
            self.tree.see(str(valid[0]))
        self._tint.reset(str(index) for index in valid)

    def _remove_on_key(self, _event=None):
        self.remove_entries()
        return "break"

    def remove_entries(self):
        indices = sorted((int(item) for item in self.tree.selection()), reverse=True)
        if indices:
            # Remember the removal (ascending, with positions) so Undo remove can put the
            # entries back where they were; a new removal replaces the remembered one.
            self._last_removal = [(index, self.entries[index]) for index in reversed(indices)]
        for index in indices:
            del self.entries[index]
        if not indices:
            self.refresh_queue()
            return
        # Keep a selection where the removal happened, so repeated removals (the Remove
        # button or the Delete key) do not need a fresh click each time: the entry that
        # slid into the first removed slot, or the new last entry when the tail was
        # removed. An emptied queue selects nothing.
        keep = min(indices[-1], len(self.entries) - 1)
        self.refresh_queue([keep] if keep >= 0 else [])

    def _undo_on_key(self, _event=None):
        self.undo_remove()
        return "break"

    def undo_remove(self):
        """Put back the entries the last removal took out (issue #85, option A).

        Only the most recent removal is remembered, with its positions, and
        anything else that changes the queue — adding entries, moving them, a
        library reload clearing the queue, reopening the window — forgets it,
        because the stored positions would no longer mean the same thing. The
        restored entries come back selected, so the user sees what returned.
        """
        if not self._last_removal:
            return
        restored = []
        for index, row in self._last_removal:
            self.entries.insert(index, row)
            restored.append(index)
        self._last_removal = None
        self.refresh_queue(restored)

    def move_entry(self, direction):
        moving = {int(item) for item in self.tree.selection()}
        selected_before = sorted(moving)
        if direction < 0:
            for index in sorted(moving):
                if index > 0 and index - 1 not in moving:
                    self.entries[index - 1], self.entries[index] = (
                        self.entries[index], self.entries[index - 1])
                    moving.remove(index)
                    moving.add(index - 1)
        else:
            for index in sorted(moving, reverse=True):
                if index + 1 < len(self.entries) and index + 1 not in moving:
                    self.entries[index + 1], self.entries[index] = (
                        self.entries[index], self.entries[index + 1])
                    moving.remove(index)
                    moving.add(index + 1)
        if sorted(moving) != selected_before:
            self._last_removal = None  # entries moved, so the remembered positions no longer apply
        self.refresh_queue(sorted(moving))

    def validate(self, title=None):
        error = validate_course_fields(self.entries, title)
        if error:
            # One title for every validation error: the message says what is wrong, and this check runs for
            # both saving a new course and appending to one.
            messagebox.showerror("Course problem", error, parent=self.window)
            return False

        types = sorted({row.get("Type", "") for row in self.entries if row.get("Type")})
        if len(types) > 1:
            description = (
                "This course contains multiple chart types:\n\n" + "\n".join(types) +
                "\n\nA .CRS entry stores the song and difficulty, not its specific chart type. "
                "ITGmania may resolve an entry to a different chart type when the course is played.\n\n"
                "Save the course anyway?"
            )
            if not messagebox.askyesno("Mixed chart types", description, parent=self.window):
                return False

        ambiguous = find_ambiguous_course_entries(self.entries, self._library_rows())
        if ambiguous:
            listing = "\n".join(
                f"{row.get('Title', '')} — {row.get('Difficulty', '')}" for row in ambiguous)
            description = (
                "A .CRS entry stores the song and difficulty, not the chart type or which "
                "Edit chart. More than one chart in the library matches each of these "
                "entries, so the entry does not say which chart was picked:\n\n" + listing +
                "\n\nSave the course anyway?"
            )
            if not messagebox.askyesno("Ambiguous chart entries", description, parent=self.window):
                return False
        return True

    def save_new(self):
        title = self.title_var.get().strip()
        if not self.validate(title):
            return

        safe_name = re.sub(r'[<>:"/\\|?*]+', "_", title).strip(" .") or "Course"
        path = filedialog.asksaveasfilename(
            parent=self.window, title="Save new course", defaultextension=".crs",
            filetypes=[("ITGmania course files", "*.crs")], initialfile=safe_name + ".crs",
            confirmoverwrite=True,
        )
        if not path:
            return
        song_lines = course_song_lines(self.entries)
        body = format_new_course(title, song_lines)
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(body)
        except OSError as exc:
            messagebox.showerror("Could not save course", str(exc), parent=self.window)
            return
        self._status.set(f"Saved course with {len(self.entries)} charts to {path}")
        messagebox.showinfo("Course saved", f"Saved {title} with {len(self.entries)} charts.\n\n{path}",
                            parent=self.window)

    def append_to_existing(self):
        if not self.validate():
            return
        path = filedialog.askopenfilename(
            parent=self.window, title="Choose course to append to",
            filetypes=[("ITGmania course files", "*.crs"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "rb") as handle:
                existing = handle.read()
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Could not read course", str(exc), parent=self.window)
            return
        try:
            addition = course_append_bytes(existing, course_song_lines(self.entries))
        except UnicodeError as exc:
            messagebox.showerror("Could not read course", f"The course could not be read as UTF-8.\n\n{exc}",
                                 parent=self.window)
            return
        except ValueError as exc:
            title = "Cannot append safely" if "ends with #" in str(exc) else "Not a readable course"
            messagebox.showwarning(title, str(exc), parent=self.window)
            return

        try:
            with open(path, "ab") as handle:
                handle.write(addition)
        except OSError as exc:
            messagebox.showerror("Could not append to course", str(exc), parent=self.window)
            return

        self._status.set(f"Appended {len(self.entries)} charts to {path}")
        messagebox.showinfo("Course updated", f"Appended {len(self.entries)} charts.\n\n{path}",
                            parent=self.window)
