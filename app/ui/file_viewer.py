# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Standalone log file viewer window.

Adds chunked background loading, tail/follow mode and an inline find bar on top
of the shared pane/filter/minimap behaviour in `LogWindowMixin`."""

import warnings
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFileSystemWatcher, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.settings import AppSettings
from app.ui.find_bar import FindBar
from app.ui.find_controller import FindController
from app.ui.file_loader import FileLoaderWorker
from app.ui.log_window import LogWindowMixin

# File viewers don't enforce a display cap — file content is finite and static.
# Set a generous cap to prevent runaway memory for pathological files.
_FILE_PANE_CAP = 2_000_000


class FileViewer(LogWindowMixin, QMainWindow):
    """Independent file viewer window. Multiple instances may coexist."""

    _instances: list = []

    about_to_close = Signal()

    def __init__(self, settings: AppSettings, path: Path, parent=None):
        super().__init__(parent)
        self._init_log_window(settings)
        self._path = path
        self._total_lines = 0
        self._loading = False
        self._worker: Optional[FileLoaderWorker] = None

        # Tail/follow state
        self._follow = False
        self._follow_paused = False
        self._follow_pos = 0         # byte offset after last read
        self._tail_buffer = ""       # incomplete last line from previous read
        self._programmatic_scroll = False
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        self._settings_dialog: Optional[QDialog] = None
        self._sidebar = None  # built lazily with the settings dialog
        FileViewer._instances.append(self)

        self.setWindowTitle(path.name)
        self.resize(1100, 700)

        # ---- Font ----
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(settings.font_size())

        # ---- Panes, minimaps, filter bar and splitter ----
        self._build_log_panes(font, cap=_FILE_PANE_CAP)

        # ---- Find bar ----
        self._find_bar = FindBar()
        self._find = FindController(self._find_bar, self._raw_pane, self)

        # ---- Layout ----
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._splitter, stretch=1)
        body_layout.addWidget(self._find_bar)

        self.setCentralWidget(body)

        # ---- Toolbar ----
        toolbar = self.addToolBar("FileViewer")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)

        new_win_action = toolbar.addAction("New Window")
        new_win_action.triggered.connect(self._on_new_connection)

        open_file_action = toolbar.addAction("Open File…")
        open_file_action.setShortcut(QKeySequence("Ctrl+O"))
        open_file_action.triggered.connect(self._on_open_file_action)

        settings_action = toolbar.addAction("⚙ Settings")
        settings_action.triggered.connect(self._on_settings_action)

        toolbar.addSeparator()

        self._filter_action = toolbar.addAction("▽ Filter")
        self._filter_action.setCheckable(True)
        self._filter_action.toggled.connect(self._on_filter_action_toggled)

        self._follow_action = toolbar.addAction("Follow")
        self._follow_action.setCheckable(True)
        self._follow_action.setChecked(False)
        self._follow_action.toggled.connect(self._on_follow_toggled)

        self._resume_action = toolbar.addAction("⬇ Resume")
        self._resume_action.setVisible(False)
        self._resume_action.triggered.connect(self._on_resume)

        # ---- Ctrl+F shortcut ----
        find_action = QAction(self)
        find_action.setShortcut(QKeySequence("Ctrl+F"))
        find_action.triggered.connect(self._find_bar.show_and_focus)
        self.addAction(find_action)

        # ---- Status bar ----
        self._status_label = QLabel("Loading…")
        self.statusBar().addWidget(self._status_label)

        # ---- Signal wiring (pane/filter/minimap wiring is in the mixin) ----
        self._find_bar.filter_to_matches.connect(self._on_filter_to_matches)
        # Follow mode pauses when the user scrolls away from the bottom.
        self._raw_pane.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        self._apply_minimap_settings()

        # ---- Restore geometry ----
        geometry = settings.load_viewer_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = settings.load_viewer_splitter()
        if splitter_state:
            self._splitter.restoreState(splitter_state)
            self._splitter_initialized = True

        # ---- Start loading ----
        self._start_load()

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _detach_worker(self) -> None:
        """Disconnect the current loader, so a replaced one goes quiet.

        `cancel()` only sets a flag the worker checks between lines, so emits
        already queued for the GUI thread still deliver — and the slots have
        no idea which worker sent them. A second truncation arriving while the
        first reload is still streaming would splice the old worker's chunks
        into the new document, and its `load_complete` would overwrite
        `_follow_pos` with an offset belonging to the wrong pass.
        """
        if self._worker is None:
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for signal, slot in (
                (self._worker.chunk_ready, self._on_chunk_ready),
                (self._worker.load_complete, self._on_load_complete),
                (self._worker.error_occurred, self._on_load_error),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass

    def _start_load(self) -> None:
        # Every reload replaces self._worker, so detaching here covers the
        # truncation restart and anything added later.
        self._detach_worker()
        self._loading = True
        self._worker = FileLoaderWorker(self._path)
        self._worker.chunk_ready.connect(self._on_chunk_ready)
        self._worker.load_complete.connect(self._on_load_complete)
        self._worker.error_occurred.connect(self._on_load_error)
        self._worker.start()

    def _on_chunk_ready(self, lines: list) -> None:
        self._raw_pane.setUpdatesEnabled(False)
        for line in lines:
            self._append_display_line(line, scroll=False)
        self._raw_pane.setUpdatesEnabled(True)
        self._total_lines += len(lines)
        self._update_status()

    def _on_load_complete(self, total: int) -> None:
        self._loading = False
        self._total_lines = total
        # Record file position for tail mode
        if self._path.exists():
            self._follow_pos = self._path.stat().st_size
        # Scroll both panes to bottom after full load
        for pane in (self._raw_pane, self._filtered_pane):
            sb = pane.verticalScrollBar()
            sb.setValue(sb.maximum())
        self._update_status()
        # Rebuild filtered pane now that full file is loaded (catches all matches)
        if self._rules:
            self._rebuild_filtered_pane()
        # Re-run any active search
        self._find.research()
        # Tail the file by default — turn Follow off per-window if unwanted.
        self._follow_action.setChecked(True)
        self._update_minimap_viewport()
        self._update_filtered_minimap_viewport()

    def _on_load_error(self, message: str) -> None:
        self._loading = False
        self._update_status()
        QMessageBox.critical(self, "Error loading file", message)

    def _update_status(self) -> None:
        suffix = "…" if self._loading else ""
        self._status_label.setText(
            f"{self._path.name}  |  {self._total_lines:,} lines{suffix}"
        )
        self._update_pane_headers()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _on_filters_changed(self, rules: list, mode: str) -> None:
        self._rules = rules
        self._filter_mode = mode
        self._update_filtered_visibility()
        if rules:
            if not self._loading:
                self._rebuild_filtered_pane()
            # During loading, _on_chunk_ready appends matching lines in real-time;
            # _on_load_complete does a full rebuild when done.
            self._update_pane_headers()
        else:
            self._filtered_pane.clear()
            self._filtered_minimap.clear()
            self._update_pane_headers()

    def _on_filter_to_matches(self, text: str) -> None:
        # Case-insensitive to mirror QTextDocument.find, so the filtered pane
        # holds exactly the lines the find counter just reported.
        self._filter_bar.add_rule(text, "substring", "include", ignore_case=True)
        # Open the chip strip if not visible (filter bar shows chips automatically)
        if not self._filter_bar.is_input_bar_open():
            self._filter_action.setChecked(True)

    # ------------------------------------------------------------------
    # Tail / follow mode
    # ------------------------------------------------------------------

    def _on_follow_toggled(self, checked: bool) -> None:
        self._follow = checked
        self._follow_paused = False
        self._resume_action.setVisible(False)
        if checked:
            if self._path.exists():
                self._follow_pos = self._path.stat().st_size
            self._tail_buffer = ""
            self._watcher.addPath(str(self._path))
            self._scroll_to_follow_bottom()
        else:
            watched = self._watcher.files()
            if watched:
                self._watcher.removePaths(watched)

    def _restart_follow_after_truncation(self) -> None:
        """Reload from scratch after the followed file shrank.

        Reloading rather than appending from offset 0 keeps the pane matching
        the file: the old content is gone, so continuing to show it would
        misrepresent what is on disk.
        """
        if self._worker is not None:
            self._worker.cancel()
        self._follow_pos = 0
        self._tail_buffer = ""
        self._total_lines = 0
        self._raw_pane.clear()
        self._filtered_pane.clear()
        self._minimap.clear()
        self._filtered_minimap.clear()
        self._start_load()

    def _scroll_to_follow_bottom(self) -> None:
        self._programmatic_scroll = True
        for pane in (self._raw_pane, self._filtered_pane):
            if pane.isVisible():
                sb = pane.verticalScrollBar()
                sb.setValue(sb.maximum())
        self._programmatic_scroll = False

    def _on_file_changed(self, path: str) -> None:
        if not self._follow:
            return
        # Re-add path if the watcher dropped it (some platforms remove it after a change)
        if str(self._path) not in self._watcher.files():
            if self._path.exists():
                self._watcher.addPath(str(self._path))
        try:
            size = self._path.stat().st_size
            if size < self._follow_pos:
                # Truncated or rotated. _follow_pos only ever grew, so a seek
                # past the new end returned nothing forever and follow was
                # silently dead for the life of the window. Restart from the
                # top of the replacement file.
                self._restart_follow_after_truncation()
                return
            with open(self._path, "rb") as f:
                f.seek(self._follow_pos)
                new_bytes = f.read()
        except OSError:
            return
        if not new_bytes:
            return
        self._follow_pos += len(new_bytes)

        text = self._tail_buffer + new_bytes.decode("utf-8", errors="replace")
        parts = text.split("\n")
        self._tail_buffer = parts[-1]
        complete_lines = parts[:-1]

        for raw_line in complete_lines:
            self._append_display_line(raw_line.rstrip("\r"), scroll=False)

        if complete_lines:
            self._total_lines += len(complete_lines)
            self._update_status()
            if not self._follow_paused:
                self._scroll_to_follow_bottom()

    def _on_scroll_changed(self, value: int) -> None:
        if self._programmatic_scroll or not self._follow:
            return
        sb = self._raw_pane.verticalScrollBar()
        at_bottom = value >= sb.maximum() - 4
        if at_bottom:
            if self._follow_paused:
                self._follow_paused = False
                self._resume_action.setVisible(False)
        else:
            if not self._follow_paused:
                self._follow_paused = True
                self._resume_action.setVisible(True)

    def _on_resume(self) -> None:
        self._follow_paused = False
        self._resume_action.setVisible(False)
        self._scroll_to_follow_bottom()

    # ------------------------------------------------------------------
    # File opening / new window / settings
    # ------------------------------------------------------------------

    def open_file(self, path: Path) -> None:
        self._settings.add_recent_file(path)
        viewer = FileViewer(self._settings, path)
        viewer.show()

    def _on_open_file_action(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Log File", "", "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.open_file(Path(path))

    def _on_new_connection(self) -> None:
        from app.main_window import MainWindow
        MainWindow.open_new()

    def _on_settings_action(self) -> None:
        if self._settings_dialog is None:
            from app.ui.settings_sidebar import SettingsSidebar
            dlg = QDialog(self)
            dlg.setWindowTitle("Settings")
            dlg.resize(300, 520)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(0, 0, 0, 0)
            # Held on the window (not just the dialog) so the shared theme
            # broadcast can find it and repaint its per-theme colour swatches.
            sidebar = SettingsSidebar(self._settings)
            sidebar.settings_changed.connect(self._on_settings_changed)
            sidebar.theme_changed.connect(self._on_theme_changed)
            sidebar.font_size_changed.connect(self._on_font_size_changed)
            sidebar.buffer_cap_changed.connect(lambda _: None)
            layout.addWidget(sidebar)
            self._sidebar = sidebar
            self._settings_dialog = dlg
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._settings.save_viewer_geometry(self.saveGeometry())
        self._settings.save_viewer_splitter(self._splitter.saveState())
        watched = self._watcher.files()
        if watched:
            self._watcher.removePaths(watched)
        if self._worker is not None:
            self._worker.stop()
        self.about_to_close.emit()
        self._release_log_window()
        if self in FileViewer._instances:
            FileViewer._instances.remove(self)
        super().closeEvent(event)
