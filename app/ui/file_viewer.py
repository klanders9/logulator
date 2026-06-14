# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Standalone log file viewer window. Supports lazy/chunked loading, the same
compact filter bar as the main window (Phase 2a), and an inline find bar (Phase 2b)."""

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.colorizer import Colorizer
from app.settings import AppSettings
from app.ui.filter_bar import FilterBar
from app.ui.find_bar import FindBar
from app.ui.file_loader import FileLoaderWorker
from app.ui.log_pane import LogPane, _fmt, _PANE_STYLE, _PLAIN_COLOR, make_pane

_DEFAULT_FONT_SIZE = 12
# File viewers don't enforce a display cap — file content is finite and static.
# Set a generous cap to prevent runaway memory for pathological files.
_FILE_PANE_CAP = 2_000_000

# Highlight colours for find bar
_MATCH_BG = QColor("#443900")        # non-current match: dark amber
_MATCH_CURRENT_BG = QColor("#1a5fa8")  # current match: same as selection blue
_MATCH_CURRENT_FG = QColor("#ffffff")

# Maximum ExtraSelections applied at once (performance guard)
_MAX_HIGHLIGHTS = 5000

_SEARCH_DEBOUNCE_MS = 300


class FileViewer(QMainWindow):
    """Independent file viewer window. Multiple instances may coexist."""

    about_to_close = Signal()
    open_file_requested = Signal(object)  # emits Path — so caller can open new viewers

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

        # Find state
        self._match_cursors: List[QTextCursor] = []
        self._current_match_idx = -1
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._do_search)

        self.setWindowTitle(path.name)
        self.resize(1100, 700)

        # ---- Font ----
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(_DEFAULT_FONT_SIZE)

        # ---- Panes ----
        self._raw_pane = make_pane(font, cap=_FILE_PANE_CAP)
        self._filtered_pane = make_pane(font, cap=_FILE_PANE_CAP)
        self._filtered_pane.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._raw_pane)
        self._splitter.addWidget(self._filtered_pane)

        # ---- Filter bar (no settings persistence for file viewers) ----
        self._filter_bar = FilterBar(settings=None, parent=None)

        # ---- Find bar ----
        self._find_bar = FindBar()

        # ---- Layout ----
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._filter_bar)
        body_layout.addWidget(self._splitter, stretch=1)
        body_layout.addWidget(self._find_bar)

        self.setCentralWidget(body)

        # ---- Toolbar ----
        toolbar = self.addToolBar("FileViewer")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self._filter_action = toolbar.addAction("▽ Filter")
        self._filter_action.setCheckable(True)
        self._filter_action.toggled.connect(self._on_filter_action_toggled)

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
        self._raw_pane.file_dropped.connect(lambda p: self.open_file_requested.emit(p))
        self._filtered_pane.file_dropped.connect(lambda p: self.open_file_requested.emit(p))

        self._find_bar.text_changed.connect(self._on_find_text_changed)
        self._find_bar.go_next.connect(self._on_find_next)
        self._find_bar.go_prev.connect(self._on_find_prev)
        self._find_bar.closed.connect(self._on_find_bar_closed)
        self._find_bar.filter_to_matches.connect(self._on_filter_to_matches)

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
        for line in lines:
            segs = self._get_segments(line, "raw")
            self._raw_pane.append_line(segs, scroll=False)
            if self._rules and filter_engine.match(line, self._rules, self._filter_mode):
                self._filtered_pane.append_line(
                    self._get_segments(line, "filtered"), scroll=False
                )
        self._raw_pane.setUpdatesEnabled(True)
        self._total_lines += len(lines)
        self._update_status()

    def _on_load_complete(self, total: int) -> None:
        self._loading = False
        self._total_lines = total
        # Scroll both panes to bottom after full load
        for pane in (self._raw_pane, self._filtered_pane):
            sb = pane.verticalScrollBar()
            sb.setValue(sb.maximum())
        self._update_status()
        # Rebuild filtered pane now that full file is loaded (catches all matches)
        if self._rules:
            self._rebuild_filtered_pane()
        # Re-run any active search
        if self._find_bar.isVisible() and self._find_bar.get_text():
            self._do_search()

    def _on_load_error(self, message: str) -> None:
        self._loading = False
        self._update_status()
        QMessageBox.critical(self, "Error loading file", message)

    def _update_status(self) -> None:
        suffix = "…" if self._loading else ""
        self._status_label.setText(
            f"{self._path.name}  |  {self._total_lines:,} lines{suffix}"
        )

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
        if rules:
            if not self._splitter_initialized:
                self._splitter_initialized = True
                h = self._splitter.height()
                if h > 0:
                    self._splitter.setSizes([int(h * 0.6), int(h * 0.4)])
            self._filtered_pane.show()
            if not self._loading:
                self._rebuild_filtered_pane()
            # During loading, _on_chunk_ready appends matching lines in real-time;
            # _on_load_complete does a full rebuild when done.
        else:
            self._filtered_pane.hide()
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

    def _on_filter_action_toggled(self, checked: bool) -> None:
        if checked != self._filter_bar.is_input_bar_open():
            self._filter_bar.toggle_input_bar()

    def _on_filter_bar_closed(self) -> None:
        self._filter_action.blockSignals(True)
        self._filter_action.setChecked(False)
        self._filter_action.blockSignals(False)

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
    # Find bar (Phase 2b)
    # ------------------------------------------------------------------

    def _on_find_text_changed(self, text: str) -> None:
        if not text:
            self._clear_highlights()
            self._find_bar.set_match_status(0, 0, has_query=False)
            return
        self._search_timer.start()

    def _do_search(self) -> None:
        text = self._find_bar.get_text()
        if not text:
            self._clear_highlights()
            return

        doc = self._raw_pane.document()
        self._match_cursors = []
        cursor = doc.find(text, 0)
        while not cursor.isNull():
            self._match_cursors.append(cursor)
            cursor = doc.find(text, cursor)

        total = len(self._match_cursors)
        if total == 0:
            self._clear_highlights()
            self._find_bar.set_match_status(0, 0)
            return

        self._current_match_idx = 0
        self._apply_highlights()
        self._find_bar.set_match_status(1, total)

    def _on_find_next(self) -> None:
        if not self._match_cursors:
            return
        self._current_match_idx = (self._current_match_idx + 1) % len(
            self._match_cursors
        )
        self._apply_highlights()
        self._find_bar.set_match_status(
            self._current_match_idx + 1, len(self._match_cursors)
        )

    def _on_find_prev(self) -> None:
        if not self._match_cursors:
            return
        self._current_match_idx = (self._current_match_idx - 1) % len(
            self._match_cursors
        )
        self._apply_highlights()
        self._find_bar.set_match_status(
            self._current_match_idx + 1, len(self._match_cursors)
        )

    def _on_find_bar_closed(self) -> None:
        self._clear_highlights()
        self._match_cursors = []
        self._current_match_idx = -1

    def _apply_highlights(self) -> None:
        non_current_fmt = QTextCharFormat()
        non_current_fmt.setBackground(_MATCH_BG)

        # Cap highlights for performance; always include a window around current
        total = len(self._match_cursors)
        if total <= _MAX_HIGHLIGHTS:
            indices_to_highlight = range(total)
        else:
            half = _MAX_HIGHLIGHTS // 2
            start = max(0, self._current_match_idx - half)
            end = min(total, start + _MAX_HIGHLIGHTS)
            indices_to_highlight = range(start, end)

        selections = []
        for i in indices_to_highlight:
            if i == self._current_match_idx:
                continue
            sel = QTextEdit.ExtraSelection()
            sel.format = non_current_fmt
            sel.cursor = self._match_cursors[i]
            selections.append(sel)

        self._raw_pane.setExtraSelections(selections)

        # Jump to current match using the text cursor (standard selection highlight)
        if 0 <= self._current_match_idx < total:
            cur = self._match_cursors[self._current_match_idx]
            self._raw_pane.setTextCursor(cur)
            self._raw_pane.ensureCursorVisible()
            rect = self._raw_pane.cursorRect()
            sb = self._raw_pane.verticalScrollBar()
            target = sb.value() + rect.center().y() - self._raw_pane.viewport().height() // 2
            sb.setValue(max(0, target))

    def _clear_highlights(self) -> None:
        self._raw_pane.setExtraSelections([])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(500)
        self.about_to_close.emit()
        super().closeEvent(event)
