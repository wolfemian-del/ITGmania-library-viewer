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

import theme
from library_data import (
    course_append_bytes,
    course_song_lines,
    format_duration,
    format_new_course,
    number,
    validate_course_fields,
)

UNKNOWN_DIFFICULTY_TAG = "diff_unknown"  # queue tag for a difficulty name that theme.DIFFICULTY_COLORS lacks


class CourseBuilder:
    """The course-builder dialog and its chart queue.

    parent:         the main window (the dialog's parent)
    status:         the main window's status variable (set on save/append)
    button_factory: makes a themed button (LibraryApp._button)
    selected_rows:  callable returning the main table's selected chart rows
    """

    def __init__(self, parent, status, button_factory, selected_rows):
        self.parent = parent
        self._status = status
        self._button = button_factory
        self._selected_rows = selected_rows
        self.window = None
        self.entries: list[dict] = []
        self.title_var = None
        self.tree = None
        self.count_var = None
        self._selected_items = set()  # queue rows currently carrying the white "selected_row" tag

    def open_dialog(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        window = tk.Toplevel(self.parent)
        self.window = window
        window.title("Build a course")
        window.geometry("900x620")
        window.minsize(700, 440)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.parent)
        self.entries: list[dict] = []
        self._selected_items = set()  # a new queue tree has no selected rows, whatever the last dialog left behind

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
        # Difficulty tints: the same tags and colors as the main table (theme.DIFFICULTY_COLORS).
        for diff, color in theme.DIFFICULTY_COLORS.items():
            self.tree.tag_configure(f"diff_{diff}", foreground=color)
        self.tree.tag_configure(UNKNOWN_DIFFICULTY_TAG, foreground=theme.DIFFICULTY_COLOR_UNKNOWN)
        # Keep this one last: in this order a selected row shows white text instead of its
        # difficulty color (checked in the window on Windows). A row has both tags while selected.
        self.tree.tag_configure("selected_row", foreground=theme.TEXT_ON_ACCENT)
        self.tree.bind("<<TreeviewSelect>>", self._on_queue_select)
        # The Remove button has keyboard equivalents while the queue has focus.
        self.tree.bind("<Delete>", self._remove_on_key)
        self.tree.bind("<BackSpace>", self._remove_on_key)

        controls = tk.Frame(window, bg=theme.BG_WINDOW, padx=18, pady=12)
        controls.pack(fill="x")
        self._button(controls, "Add selected charts", self.add_selected, primary=True).pack(side="left")
        self._button(controls, "Remove", self.remove_entries).pack(side="left", padx=(8, 0))
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
            window.destroy()
            return "break"

        window.bind("<Escape>", _close)
        # A new window does not always take keyboard focus by itself (seen on Windows);
        # without this, Escape would go to the main window instead of closing this one.
        window.focus_force()

        self.add_selected()

    def add_selected(self):
        added = 0
        for row in self._selected_rows():
            self.entries.append(row)
            added += 1
        if added:
            self.refresh_queue()

    def refresh_queue(self, selected_indices=None):
        selected_indices = selected_indices or []
        valid = [index for index in selected_indices if 0 <= index < len(self.entries)]
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.entries):
            tags = [self._difficulty_tag(row)]
            if index in valid:
                tags.append("selected_row")  # a kept selection is born with the white tag (see _on_queue_select)
            self.tree.insert("", "end", iid=str(index), values=(
                row.get("Pack", ""), row.get("Title", ""), row.get("Type", ""),
                row.get("Difficulty", ""), row.get("Meter", ""),
                format_duration(row.get("Time", 0)) if row.get("Time", "") != "" else "",
            ), tags=tuple(tags))
        total_seconds = sum(number(row.get("Time")) for row in self.entries)
        self.count_var.set(f"{len(self.entries)} charts · {format_duration(total_seconds)} total")
        if valid:
            self.tree.selection_set(*(str(index) for index in valid))
            self.tree.focus(str(valid[0]))
            self.tree.see(str(valid[0]))
        self._selected_items = {str(index) for index in valid}

    def _on_queue_select(self, _event=None):
        """Give the white "selected_row" tag to the rows that just became selected and take it from the rest."""
        current = set(self.tree.selection())
        for item in self._selected_items - current:
            if self.tree.exists(item):  # a refresh may have removed the row already
                self._set_selected_tag(item, False)
        for item in current - self._selected_items:
            self._set_selected_tag(item, True)
        self._selected_items = current

    def _set_selected_tag(self, item, selected):
        tags = [tag for tag in self.tree.item(item, "tags") if tag != "selected_row"]
        if selected:
            tags.append("selected_row")
        self.tree.item(item, tags=tags)

    @staticmethod
    def _difficulty_tag(row):
        """The queue tag that tints a row by its difficulty (the main table's rule, same tag names)."""
        name = str(row.get("Difficulty", "")).strip()
        return f"diff_{name}" if name in theme.DIFFICULTY_COLORS else UNKNOWN_DIFFICULTY_TAG

    def _remove_on_key(self, _event=None):
        self.remove_entries()
        return "break"

    def remove_entries(self):
        indices = sorted((int(item) for item in self.tree.selection()), reverse=True)
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

    def move_entry(self, direction):
        moving = {int(item) for item in self.tree.selection()}
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
