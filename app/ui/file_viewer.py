# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Standalone log file viewer window. Supports lazy/chunked loading, the same
compact filter bar as the main window (Phase 2a), and an inline find bar (Phase 2b)."""

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QFileSystemWatcher, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.colorizer import Colorizer, detect_level
from app.settings import AppSettings
from app.ui.filter_bar import FilterBar
from app.ui.find_bar import FindBar
from app.ui.find_controller import FindController
from app.ui.file_loader import FileLoaderWorker
from app.ui.log_pane import (
    LogPane,
    _fmt,
    _PANE_STYLE,
    _PLAIN_COLOR,
    doc_line_count,
    make_pane,
    pane_with_header,
)
from app.ui.minimap import Minimap

# File viewers don't enforce a display cap — file content is finite and static.
# Set a generous cap to prevent runaway memory for pathological files.
_FILE_PANE_CAP = 2_000_000


class FileViewer(QMainWindow):
    """Independent file viewer window. Multiple instances may coexist."""

    _instances: list = []

    about_to_close = Signal()

    def __init__(self, settings: AppSettings, path: Path, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._colorizer = Colorizer(settings)
        self._plain_fmt = _fmt(_PLAIN_COLOR)
        self._path = path
        self._rules: list = []
        self._filter_mode = "OR"
        self._total_lines = 0
        self._loading = False
        self._splitter_initialized = False
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
        FileViewer._instances.append(self)

        self.setWindowTitle(path.name)
        self.resize(1100, 700)

        # ---- Font ----
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(settings.font_size())

        # ---- Panes ----
        self._raw_pane = make_pane(font, cap=_FILE_PANE_CAP)
        self._filtered_pane = make_pane(font, cap=_FILE_PANE_CAP)

        # ---- Minimaps: colored-band overview, optional (Settings), off by default ----
        self._minimap = Minimap()
        self._minimap.set_cap(_FILE_PANE_CAP)
        self._minimap.position_clicked.connect(self._on_minimap_clicked)
        self._filtered_minimap = Minimap()
        self._filtered_minimap.set_cap(_FILE_PANE_CAP)
        self._filtered_minimap.position_clicked.connect(self._on_filtered_minimap_clicked)

        raw_box, self._raw_header = pane_with_header(self._raw_pane, "Raw", self._minimap)
        self._filtered_box, self._filtered_header = pane_with_header(
            self._filtered_pane, "Filtered", self._filtered_minimap
        )
        # ---- Filter bar (no settings persistence for file viewers) ----
        self._filter_bar = FilterBar(settings=None, parent=None)
        self._filtered_box.layout().insertWidget(1, self._filter_bar)
        self._filtered_box.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(raw_box)
        self._splitter.addWidget(self._filtered_box)

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

        # ---- Signal wiring ----
        self._filter_bar.filters_changed.connect(self._on_filters_changed)
        self._filter_bar.input_bar_closed.connect(self._on_filter_bar_closed)
        self._raw_pane.selectionChanged.connect(self._on_raw_selection_changed)
        self._filtered_pane.selectionChanged.connect(self._on_filtered_selection_changed)
        self._filtered_pane.line_double_clicked.connect(self._jump_to_raw_line)
        self._raw_pane.file_dropped.connect(self.open_file)
        self._filtered_pane.file_dropped.connect(self.open_file)

        self._find_bar.filter_to_matches.connect(self._on_filter_to_matches)

        self._raw_pane.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self._raw_pane.verticalScrollBar().valueChanged.connect(self._update_minimap_viewport)
        self._raw_pane.verticalScrollBar().rangeChanged.connect(self._update_minimap_viewport)
        self._filtered_pane.verticalScrollBar().valueChanged.connect(self._update_filtered_minimap_viewport)
        self._filtered_pane.verticalScrollBar().rangeChanged.connect(self._update_filtered_minimap_viewport)

        self._apply_minimap_settings()

        # ---- Start loading ----
        self._start_load()

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _start_load(self) -> None:
        self._loading = True
        self._worker = FileLoaderWorker(self._path)
        self._worker.chunk_ready.connect(self._on_chunk_ready)
        self._worker.load_complete.connect(self._on_load_complete)
        self._worker.error_occurred.connect(self._on_load_error)
        self._worker.start()

    def _on_chunk_ready(self, lines: list) -> None:
        self._raw_pane.setUpdatesEnabled(False)
        minimap_visible = self._minimap.isVisible()
        filtered_minimap_visible = self._filtered_minimap.isVisible()
        for line in lines:
            segs = self._get_segments(line, "raw")
            self._raw_pane.append_line(segs, scroll=False)
            if minimap_visible:
                self._minimap.append_color(self._minimap_color_for(line))
            if self._rules and filter_engine.match(line, self._rules, self._filter_mode):
                self._filtered_pane.append_line(
                    self._get_segments(line, "filtered"), scroll=False
                )
                if filtered_minimap_visible:
                    self._filtered_minimap.append_color(self._minimap_color_for(line))
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

    def _update_pane_headers(self) -> None:
        if self._filtered_box.isVisible():
            n = doc_line_count(self._filtered_pane)
            m = doc_line_count(self._raw_pane)
            self._filtered_header.setText(f"Filtered — {n:,} of {m:,} lines")

    # ------------------------------------------------------------------
    # Colorization
    # ------------------------------------------------------------------

    def _get_segments(
        self, line: str, pane: str
    ) -> List[Tuple[str, QTextCharFormat]]:
        if not self._settings.color_enabled():
            return [(line, self._plain_fmt)]
        apply_to = self._settings.color_apply_to()
        if apply_to == "none":
            return [(line, self._plain_fmt)]
        if apply_to == "raw" and pane != "raw":
            return [(line, self._plain_fmt)]
        if apply_to == "filtered" and pane != "filtered":
            return [(line, self._plain_fmt)]
        return self._colorizer.colorize(line)

    # ------------------------------------------------------------------
    # Filters (Phase 2a)
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

    def _ensure_filtered_box_visible(self) -> None:
        if not self._splitter_initialized:
            self._splitter_initialized = True
            h = self._splitter.height()
            if h > 0:
                self._splitter.setSizes([int(h * 0.6), int(h * 0.4)])
        self._filtered_box.show()

    def _update_filtered_visibility(self) -> None:
        # The filter bar's input row now lives above the filtered pane, so the
        # container must stay visible while it's open even before any rule
        # exists — otherwise there's no way to reach it to add the first rule.
        show = bool(self._rules) or self._filter_bar.is_input_bar_open()
        if show:
            self._ensure_filtered_box_visible()
        else:
            self._filtered_box.hide()
            self._filtered_pane.clear()

    def _rebuild_filtered_pane(self) -> None:
        doc = self._raw_pane.document()
        block = doc.begin()
        self._filtered_pane.setUpdatesEnabled(False)
        self._filtered_pane.clear()
        while block != doc.end():
            text = block.text()
            if filter_engine.match(text, self._rules, self._filter_mode):
                self._filtered_pane.append_line(
                    self._get_segments(text, "filtered"), scroll=False
                )
            block = block.next()
        self._filtered_pane.setUpdatesEnabled(True)
        sb = self._filtered_pane.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._update_pane_headers()
        if self._filtered_minimap.isVisible():
            self._rebuild_filtered_minimap()

    def _on_filter_action_toggled(self, checked: bool) -> None:
        if checked:
            # Show the container before opening the row so it can take focus.
            self._ensure_filtered_box_visible()
        if checked != self._filter_bar.is_input_bar_open():
            self._filter_bar.toggle_input_bar()
        if not checked:
            self._update_filtered_visibility()

    def _on_filter_bar_closed(self) -> None:
        self._filter_action.blockSignals(True)
        self._filter_action.setChecked(False)
        self._filter_action.blockSignals(False)
        self._update_filtered_visibility()

    def _on_filter_to_matches(self, text: str) -> None:
        self._filter_bar.add_rule(text, "substring", "include")
        # Open the chip strip if not visible (filter bar shows chips automatically)
        if not self._filter_bar.is_input_bar_open():
            self._filter_action.setChecked(True)

    # ------------------------------------------------------------------
    # Selection mutual exclusion
    # ------------------------------------------------------------------

    def _on_raw_selection_changed(self) -> None:
        cursor = self._filtered_pane.textCursor()
        if cursor.hasSelection():
            self._filtered_pane.blockSignals(True)
            cursor.clearSelection()
            self._filtered_pane.setTextCursor(cursor)
            self._filtered_pane.blockSignals(False)

    def _on_filtered_selection_changed(self) -> None:
        cursor = self._raw_pane.textCursor()
        if cursor.hasSelection():
            self._raw_pane.blockSignals(True)
            cursor.clearSelection()
            self._raw_pane.setTextCursor(cursor)
            self._raw_pane.blockSignals(False)

    def _jump_to_raw_line(self, line: str) -> None:
        doc = self._raw_pane.document()
        block = doc.begin()
        while block != doc.end():
            if block.text() == line:
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                self._raw_pane.setTextCursor(cursor)
                self._raw_pane.setFocus()
                self._raw_pane.ensureCursorVisible()
                rect = self._raw_pane.cursorRect()
                sb = self._raw_pane.verticalScrollBar()
                sb.setValue(
                    sb.value()
                    + rect.center().y()
                    - self._raw_pane.viewport().height() // 2
                )
                return
            block = block.next()

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

        minimap_visible = self._minimap.isVisible()
        filtered_minimap_visible = self._filtered_minimap.isVisible()
        for raw_line in complete_lines:
            line = raw_line.rstrip("\r")
            segs = self._get_segments(line, "raw")
            self._raw_pane.append_line(segs, scroll=False)
            if minimap_visible:
                self._minimap.append_color(self._minimap_color_for(line))
            if self._rules and filter_engine.match(line, self._rules, self._filter_mode):
                self._filtered_pane.append_line(
                    self._get_segments(line, "filtered"), scroll=False
                )
                if filtered_minimap_visible:
                    self._filtered_minimap.append_color(self._minimap_color_for(line))

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
            sidebar = SettingsSidebar(self._settings)
            sidebar.settings_changed.connect(self._on_settings_changed)
            sidebar.theme_changed.connect(self._on_theme_changed)
            sidebar.font_size_changed.connect(self._on_font_size_changed)
            sidebar.buffer_cap_changed.connect(lambda _: None)
            layout.addWidget(sidebar)
            self._settings_dialog = dlg
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_settings_changed(self) -> None:
        self._rebuild_raw_pane()
        if self._filtered_pane.isVisible():
            self._rebuild_filtered_pane()
        self._apply_minimap_settings()

    def _on_theme_changed(self, theme: str) -> None:
        from app.theme import apply_palette
        apply_palette(QApplication.instance(), theme)

    def _on_font_size_changed(self, size: int) -> None:
        for pane in (self._raw_pane, self._filtered_pane):
            f = pane.font()
            f.setPointSize(size)
            pane.setFont(f)

    def _rebuild_raw_pane(self) -> None:
        doc = self._raw_pane.document()
        block = doc.begin()
        lines = []
        while block != doc.end():
            lines.append(block.text())
            block = block.next()
        self._raw_pane.setUpdatesEnabled(False)
        self._raw_pane.clear()
        for line in lines:
            self._raw_pane.append_line(self._get_segments(line, "raw"), scroll=False)
        self._raw_pane.setUpdatesEnabled(True)
        sb = self._raw_pane.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._minimap.isVisible():
            self._rebuild_raw_minimap()

    # ------------------------------------------------------------------
    # Minimap
    # ------------------------------------------------------------------

    def _minimap_color_for(self, line: str) -> QColor:
        if line.startswith(">> "):
            return QColor(self._settings.tx_color())
        if line.startswith("---"):
            return QColor("#555555")
        level = detect_level(line)
        if level:
            return QColor(self._settings.level_color(level))
        return QColor("#444444")

    def _rebuild_raw_minimap(self) -> None:
        doc = self._raw_pane.document()
        colors = []
        if not (doc.blockCount() == 1 and doc.firstBlock().text() == ""):
            block = doc.begin()
            while block != doc.end():
                colors.append(self._minimap_color_for(block.text()))
                block = block.next()
        self._minimap.set_colors(colors)

    def _rebuild_filtered_minimap(self) -> None:
        doc = self._filtered_pane.document()
        colors = []
        if not (doc.blockCount() == 1 and doc.firstBlock().text() == ""):
            block = doc.begin()
            while block != doc.end():
                colors.append(self._minimap_color_for(block.text()))
                block = block.next()
        self._filtered_minimap.set_colors(colors)

    def _apply_minimap_settings(self) -> None:
        enabled = self._settings.minimap_enabled()
        apply_to = self._settings.minimap_apply_to()
        show_raw = enabled and apply_to in ("all", "raw")
        show_filtered = enabled and apply_to in ("all", "filtered")
        self._minimap.setVisible(show_raw)
        self._filtered_minimap.setVisible(show_filtered)
        if show_raw:
            self._rebuild_raw_minimap()
        else:
            self._minimap.clear()
        if show_filtered:
            self._rebuild_filtered_minimap()
        else:
            self._filtered_minimap.clear()

    def _update_minimap_viewport(self, *_args) -> None:
        sb = self._raw_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        if total <= 0:
            self._minimap.set_viewport(0.0, 1.0)
            return
        self._minimap.set_viewport(sb.value() / total, (sb.value() + sb.pageStep()) / total)

    def _on_minimap_clicked(self, frac: float) -> None:
        sb = self._raw_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        target = int(frac * total - sb.pageStep() / 2)
        sb.setValue(max(0, min(sb.maximum(), target)))

    def _update_filtered_minimap_viewport(self, *_args) -> None:
        sb = self._filtered_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        if total <= 0:
            self._filtered_minimap.set_viewport(0.0, 1.0)
            return
        self._filtered_minimap.set_viewport(sb.value() / total, (sb.value() + sb.pageStep()) / total)

    def _on_filtered_minimap_clicked(self, frac: float) -> None:
        sb = self._filtered_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        target = int(frac * total - sb.pageStep() / 2)
        sb.setValue(max(0, min(sb.maximum(), target)))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        watched = self._watcher.files()
        if watched:
            self._watcher.removePaths(watched)
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(500)
        self.about_to_close.emit()
        if self in FileViewer._instances:
            FileViewer._instances.remove(self)
        super().closeEvent(event)
