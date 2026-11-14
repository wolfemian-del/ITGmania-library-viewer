"""The background data engine: loads the library, syncs scores, reports progress.

LibraryLoader (proposal 0009 Step 4) owns the scan/sync workers, the result
queue, the polling, the progress and status reporting, and the load results
(rows, loaded_source_paths, last_refreshed_at, the snapshot-summary counters).
It never touches the table or the filter variables directly; everything the
UI needs arrives through the callbacks in its constructor (on_library_changed,
on_nothing_loaded), and the DataPathsDialog component it is given.
"""

from __future__ import annotations

import queue
import threading
import time
try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:
    tk = None
    messagebox = None
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from library_data import (
    _normalized_source_path,
    any_scores_match,
    format_refresh_time,
    invalid_paths_note,
    looks_like_song_tree,
    merge_scores,
    parse_cache_file,
    stats_index,
)


class LibraryLoader:
    """Load the library (scan or snapshot), sync scores, report progress/status.

    snapshot_store:       the snapshot store, passed in (already standalone).
    cache_var, stats_var: the path variables, read.
    status:               the status StringVar, for progress/status reporting.
    progress:             the progress-bar widget.
    load_button:          the Load button widget, disabled during a load.
    set_sync_menu_state:  callable, enabling/disabling File -> Sync scores.
    on_library_changed:   callback (rows, preserve_selection), delivered when
                          a load or a sync finishes, for the table/filter/
                          Course Builder part only (Q2).
    on_nothing_loaded:    callback, delivered when load_cached_data finds no
                          snapshot, so the app does the initial refresh.
    dialog:               the DataPathsDialog component, for open(), set_note(),
                          and maybe_show_first_run().
    save_settings:        callable.
    root:                 for after() scheduling of the result polling.
    report_discarded_settings: callback, for the discarded-settings note the
                          shell reports (the settings store stays in the
                          shell, so _report_discarded_settings stays app-side
                          and the loader calls it through this callback).
    had_saved_paths:      whether saved settings contained path keys, for the
                          dialog's first-run check (the loader never sees the
                          settings file).
    """

    def __init__(self, snapshot_store, cache_var, stats_var, status, progress,
                 load_button, set_sync_menu_state, on_library_changed,
                 on_nothing_loaded, dialog, save_settings, root,
                 report_discarded_settings, had_saved_paths):
        self.snapshot_store = snapshot_store
        self.cache_var = cache_var
        self.stats_var = stats_var
        self.status = status
        self.progress = progress
        self.load_button = load_button
        self.set_sync_menu_state = set_sync_menu_state
        self.on_library_changed = on_library_changed
        self.on_nothing_loaded = on_nothing_loaded
        self.dialog = dialog
        self.save_settings = save_settings
        self.root = root
        self.report_discarded_settings = report_discarded_settings
        self.had_saved_paths = had_saved_paths
        # Load results and worker state (the engine's own state, §2).
        self.rows: list[dict] = []
        self.loaded_source_paths = None
        self.last_refreshed_at = ""
        self._load_generation = 0  # counts Load / refresh requests; a scan from an older request is dropped
        self._scan_in_flight = False  # a scan is running; the scores sync refuses to start while one is (issue #147)
        self._sync_in_flight = False  # a scores sync is running; a second sync refuses to start while one is (issue #147)
        self._snapshot_lock = threading.Lock()  # one scan at a time may check its generation and write the snapshot
        self._load_results = queue.Queue()  # finished scans wait here; only the main thread delivers them (_poll_load_results)
        self._load_started_at = None

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
            self.report_discarded_settings()
        # Last startup step: if no snapshot restored and the paths are not
        # both usable, ask where the library is before leaving an empty table.
        # The dialog's first-run check takes its two facts as arguments
        # (Step 3): whether a snapshot is loaded, and whether saved
        # settings contained path keys (had_saved_paths, a constructor
        # input, since the loader never sees the settings file).
        snapshot_loaded = self.loaded_source_paths is not None
        self.dialog.maybe_show_first_run(snapshot_loaded, self.had_saved_paths)

    def load_cached_data(self):
        # The store reads and validates; this method only maps the result
        # onto the status line and delivers the rows (proposal 0008).
        result = self.snapshot_store.read(self.cache_var.get(), self.stats_var.get())
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
            self._report_newer_stats_file()
            return
        if result.reason == "missing":
            self.status.set("No saved library yet. Choose File → Data paths…, then Load / refresh.")
        elif result.reason == "unreadable":
            self.status.set(f"Saved library snapshot could not be read ({result.detail}). Click Load / refresh to rebuild it.")
        elif result.reason == "invalid":
            self.status.set("Saved library snapshot is invalid or outdated. Click Load / refresh to rebuild it.")
        else:  # paths_mismatch
            self.status.set("Saved library snapshot is for different data paths. Click Load / refresh to rebuild it.")
        # No snapshot restored: the app does the initial refresh, so the
        # table is not left empty. [CODE] on_nothing_loaded covers the
        # path load_cached_data used to refresh directly.
        self.on_nothing_loaded()

    def _source_paths_changed(self):
        if not self.loaded_source_paths:
            return
        if self._current_paths_match_loaded():
            stamp = format_refresh_time(self.last_refreshed_at)
            self.status.set(f"Showing saved library snapshot · {len(self.rows):,} charts · last refreshed {stamp}.")
        else:
            self.status.set("Displayed library uses different data paths. Click Load / refresh to show the selected sources.")
        # While the Data paths dialog is open, the same news shows inside it
        # (the conditional note), not only on the status line behind the modal.
        # At first run there is no snapshot loaded, so the early return above
        # leaves the dialog's first-run note alone.
        self.dialog.set_note(self.dialog.paths_changed())

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

    def _report_newer_stats_file(self):
        """Append a hint when Stats.xml is newer than the restored snapshot (issue #147).

        A play session changes Stats.xml without touching the cache, so the
        saved scores can go stale while the snapshot still restores fine.
        The hint compares the *selected* Stats.xml path against the
        snapshot's refreshed_at -- that is the file a sync would read. One
        benign wrinkle: a Stats.xml change during a scan reads as newer
        than the snapshot just written, so the hint can fire for a sync
        that changes nothing.
        """
        refreshed_at = getattr(self, "last_refreshed_at", "")
        if not refreshed_at:
            return
        stats = Path(self.stats_var.get())
        if not stats.is_file():
            return
        try:
            mtime = stats.stat().st_mtime
            stamp = datetime.fromisoformat(refreshed_at).timestamp()
        except (OSError, ValueError, TypeError):
            return
        if mtime <= stamp:
            return
        message = ("Stats.xml is newer than the saved library. "
                   "Choose File → Sync scores from Stats.xml to refresh scores.")
        # A bare instance built for a snapshot test may carry a Mock status
        # whose get() is not a string; that is "no status line", not an error.
        current = self.status.get()
        if not isinstance(current, str):
            current = ""
        if message in current:
            return
        self.status.set(f"{current} {message}" if current else message)

    def load_data(self):
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not cache.is_dir() or not stats.is_file():
            # Invalid paths open the Data paths dialog instead of an error box:
            # the fix is in the dialog, so that is where the user should be.
            self.dialog.open(note=invalid_paths_note(cache, stats))
            return
        self.save_settings()
        self.progress.start(12)
        self.status.set("Reading chart cache and player scores…")
        # Disabled until the scan's result is delivered, so a second click cannot
        # pile up scans; the File menu entry still starts a newer scan, which
        # supersedes this one by generation and owns re-enabling the button.
        self.load_button.configure(state="disabled")
        self._load_generation += 1
        generation = self._load_generation
        # A scan is in flight until its result is delivered; the scores sync
        # refuses to start while one is, and its menu entry is disabled.
        self._scan_in_flight = True
        self.set_sync_menu_state("disabled")
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
                    refreshed_at = self.snapshot_store.write(
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

    def sync_scores(self):
        """Re-read Stats.xml and refresh the score fields of the loaded rows (issue #147).

        A manual File -> Sync scores action: the cache is not re-parsed, so
        a sync is ~4-5 s at 35k charts in the sandbox against ~20 s for a
        full Load / refresh. New songs still need a full refresh -- there
        is no row to merge their scores into.
        """
        if getattr(self, "_scan_in_flight", False):
            self.status.set("A library load is in progress. Wait for it to finish, then sync scores.")
            return
        if getattr(self, "_sync_in_flight", False):
            self.status.set("A scores sync is already in progress. Wait for it to finish, then sync again.")
            return
        if not self.rows:
            self.status.set("No library loaded. Load / refresh first, then sync scores.")
            return
        if not self._current_paths_match_loaded():
            self.status.set("The selected data paths differ from the loaded library. Load / refresh first, then sync scores.")
            return
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not stats.is_file():
            # Invalid paths open the Data paths dialog instead of an error box:
            # the fix is in the dialog, so that is where the user should be.
            self.dialog.open(note=invalid_paths_note(cache, stats))
            return
        self._sync_in_flight = True
        self.set_sync_menu_state("disabled")
        self.progress.start(12)
        self.status.set("Syncing scores from Stats.xml…")
        # Capture the rows and the generation on the main thread: a Load
        # pressed during the sync replaces self.rows and bumps the
        # generation, which the worker and the delivery both check.
        threading.Thread(
            target=self._sync_scores_worker,
            args=(cache, stats, self.rows, self._load_generation),
            daemon=True).start()

    def _sync_scores_worker(self, cache, stats_file, rows, generation):
        # A sync whose generation is no longer the latest stops quietly: a
        # Load pressed during it owns the rows and the snapshot now.
        try:
            # Stats.xml is the worker's input; if the game rewrites it
            # after the read, the merged scores are stale. Capture the
            # mtime before the read and check it again before persisting,
            # so a mid-sync change never lands in the snapshot silently.
            stats_mtime = Path(stats_file).stat().st_mtime
            scores = stats_index(stats_file)
        except ET.ParseError as exc:
            self._load_results.put(("scores_sync_failed",
                                    "Stats.xml is malformed or incomplete and "
                                    "could not be parsed.\n\n"
                                    f"{exc}",
                                    generation))
            return
        except OSError as exc:
            self._load_results.put(("scores_sync_failed",
                                    f"Could not read the selected Stats.xml.\n\n{exc}",
                                    generation))
            return
        except Exception as exc:
            # Anything else stats_index can raise (for example a LookupError
            # for an unsupported encoding in the XML declaration) must still
            # reach the main thread, or the progress bar spins forever.
            self._load_results.put(("scores_sync_failed",
                                    f"Could not sync scores from Stats.xml.\n\n{exc}",
                                    generation))
            return
        if not any("PercentDP" in entry for entry in scores.values()):
            # A Stats.xml with no actual scores (a fresh profile, the
            # wrong file, or HighScoreLists with no HighScore entries)
            # would blank every score and report success. Refuse the
            # sync instead, so nothing is changed.
            self._load_results.put(("scores_sync_failed",
                                    "The selected Stats.xml contains no scores.\n\n"
                                    "Check that you picked the right file — "
                                    "no scores were changed.",
                                    generation))
            return
        if not any_scores_match(rows, scores):
            # The Stats.xml has scores, but none for the songs in this
            # library (for example a profile from another install).
            # Merging it would blank every score and report success.
            # Refuse the sync instead, so nothing is changed.
            self._load_results.put(("scores_sync_failed",
                                    "The selected Stats.xml has no scores "
                                    "for the songs in this library.\n\n"
                                    "Check that you picked the right file — "
                                    "no scores were changed.",
                                    generation))
            return
        try:
            changed = merge_scores(rows, scores)
        except Exception as exc:
            # A row with a non-text Course path / Type / Difficulty / Chart
            # would otherwise end the thread silently; deliver the failure.
            self._load_results.put(("scores_sync_failed",
                                    f"Could not sync scores from Stats.xml.\n\n{exc}",
                                    generation))
            return
        # The generation check and the snapshot write happen under one lock,
        # exactly like the scan worker's: without it, a sync that passed the
        # check could still be writing after a newer scan had written its
        # own snapshot, leaving the older data on disk.
        cache_error = ""
        refreshed_at = ""
        with self._snapshot_lock:
            if self._load_is_stale(generation):
                return
            try:
                current_mtime = Path(stats_file).stat().st_mtime
            except OSError:
                current_mtime = None
            if current_mtime != stats_mtime:
                # Stats.xml changed between the read and the snapshot
                # write: the merged scores are stale. Do not persist them;
                # the snapshot's stamp stays put, so the startup hint fires
                # and the user re-syncs for the latest scores.
                cache_error = ("Stats.xml changed during the sync. "
                               "Sync again for current scores.")
            else:
                try:
                    refreshed_at = self.snapshot_store.write(
                        cache, stats_file, rows,
                        getattr(self, "_snapshot_files", 0),
                        getattr(self, "_snapshot_skipped_files", 0),
                        getattr(self, "_snapshot_files_without_charts", 0),
                        getattr(self, "_snapshot_nested_song_tree", False),
                        getattr(self, "_snapshot_skipped_blocks", 0))
                except (OSError, TypeError, ValueError) as exc:
                    refreshed_at = ""
                    cache_error = str(exc)
        self._load_results.put(("scores_synced", (rows, changed), {
            "refreshed_at": refreshed_at,
            "cache_error": cache_error,
            "generation": generation,
        }))

    def _scores_synced(self, rows, changed, refreshed_at="", cache_error="", generation=None):
        if generation is not None and self._load_is_stale(generation):
            # A Load superseded this sync: the sync is over, so clear the
            # flag, but the Load owns the progress bar, status line and menu.
            self._sync_in_flight = False
            return
        self._sync_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.rows = rows
        # The snapshot's stamp only moves when the save succeeded; a failed
        # save leaves the in-memory scores fresh but the snapshot stale.
        if refreshed_at:
            self.last_refreshed_at = refreshed_at
        if changed:
            noun = "chart" if changed == 1 else "charts"
            message = f"Scores synced · {changed:,} {noun} updated"
        else:
            message = "Scores are already up to date"
        if refreshed_at:
            message += f" · last refreshed {format_refresh_time(refreshed_at)}"
        self.status.set(message + ".")
        if cache_error:
            self.status.set(self.status.get() + f" Local snapshot not saved: {cache_error}")
        # Full re-insert for v1 (issue #147): the merge is the fast part,
        # and a targeted cell patch would have to decide what to do about
        # the scored-only filter and the count label. Preserve the
        # selection, which a full reload currently drops.
        # The table refresh (preserving the selection) arrives through
        # the callback. [CODE] Q2: the handlers' engine half moves in.
        self.on_library_changed(rows, preserve_selection=True)

    def _scores_sync_failed(self, message, generation=None):
        if generation is not None and self._load_is_stale(generation):
            # A Load superseded this sync: the sync is over, so clear the
            # flag, but the Load owns the progress bar, status line and menu.
            self._sync_in_flight = False
            return
        self._sync_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.status.set("Could not sync scores.")
        messagebox.showerror("Could not sync scores", message)

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
                elif result[0] == "scores_synced":
                    _, args, kwargs = result
                    self._scores_synced(*args, **kwargs)
                elif result[0] == "scores_sync_failed":
                    _, message, generation = result
                    self._scores_sync_failed(message, generation=generation)
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
                pass

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
        self._scan_in_flight = False
        self.set_sync_menu_state("normal")
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
        self._scan_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.rows = rows
        # The scores sync re-saves the snapshot with the merged rows, so it
        # needs the scan's summary values; keep them alongside the rows.
        self._snapshot_files = files
        self._snapshot_skipped_files = skipped_files
        self._snapshot_files_without_charts = files_without_charts
        self._snapshot_nested_song_tree = nested_song_tree
        self._snapshot_skipped_blocks = skipped_blocks
        if source_paths:
            self.loaded_source_paths = source_paths
        self.last_refreshed_at = refreshed_at
        # The app-side part (reset the dropdowns, tell the Course Builder,
        # set the table's rows) arrives through the callback, in the same
        # position the dropdown reset occupied, so the table still refreshes
        # before the status text below. [CODE] Q2: the handlers' engine half
        # moves into the loader; the app keeps on_library_changed.
        self.on_library_changed(rows, preserve_selection=False)
        if from_cache:
            stamp = format_refresh_time(refreshed_at)
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
            self.status.set(
                self.status.get()
                + f" Snapshot refreshed {format_refresh_time(refreshed_at)}.")
        if not from_cache and cache_error:
            self.status.set(self.status.get() + f" Local snapshot not saved: {cache_error}")
