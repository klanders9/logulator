# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Reusable controller binding a FindBar to a LogPane. Owns all search state:
match cursors, current index, debounce timer, and highlight application.
Used by FileViewer (static file search) and MainWindow (live buffer search)."""

from typing import List

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.ui.find_bar import FindBar
from app.ui.log_pane import LogPane

_MATCH_BG = QColor("#443900")  # non-current match: dark amber

# Maximum ExtraSelections applied at once (performance guard)
_MAX_HIGHLIGHTS = 5000

_SEARCH_DEBOUNCE_MS = 300


class FindController(QObject):
    def __init__(self, find_bar: FindBar, pane: LogPane, parent=None):
        super().__init__(parent)
        self._bar = find_bar
        self._pane = pane
        self._match_cursors: List[QTextCursor] = []
        self._current_match_idx = -1

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._do_search)

        find_bar.text_changed.connect(self._on_text_changed)
        find_bar.go_next.connect(self._on_next)
        find_bar.go_prev.connect(self._on_prev)
        find_bar.closed.connect(self._on_closed)

    # ---- Public API ----

    def research(self) -> None:
        """Re-run the current search (e.g. after the document changed)."""
        if self._bar.isVisible() and self._bar.get_text():
            self._do_search()

    # ---- Internals ----

    def _on_text_changed(self, text: str) -> None:
        if not text:
            self._clear_highlights()
            self._bar.set_match_status(0, 0, has_query=False)
            return
        self._search_timer.start()

    def _do_search(self) -> None:
        text = self._bar.get_text()
        if not text:
            self._clear_highlights()
            return

        doc = self._pane.document()
        self._match_cursors = []
        cursor = doc.find(text, 0)
        while not cursor.isNull():
            self._match_cursors.append(cursor)
            cursor = doc.find(text, cursor)

        total = len(self._match_cursors)
        if total == 0:
            self._clear_highlights()
            self._bar.set_match_status(0, 0)
            return

        self._current_match_idx = 0
        self._apply_highlights()
        self._bar.set_match_status(1, total)

    def _on_next(self) -> None:
        if not self._match_cursors:
            return
        self._current_match_idx = (self._current_match_idx + 1) % len(
            self._match_cursors
        )
        self._apply_highlights()
        self._bar.set_match_status(
            self._current_match_idx + 1, len(self._match_cursors)
        )

    def _on_prev(self) -> None:
        if not self._match_cursors:
            return
        self._current_match_idx = (self._current_match_idx - 1) % len(
            self._match_cursors
        )
        self._apply_highlights()
        self._bar.set_match_status(
            self._current_match_idx + 1, len(self._match_cursors)
        )

    def _on_closed(self) -> None:
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

        self._pane.setExtraSelections(selections)

        # Jump to current match using the text cursor (standard selection highlight)
        if 0 <= self._current_match_idx < total:
            cur = self._match_cursors[self._current_match_idx]
            self._pane.setTextCursor(cur)
            self._pane.ensureCursorVisible()
            rect = self._pane.cursorRect()
            sb = self._pane.verticalScrollBar()
            target = sb.value() + rect.center().y() - self._pane.viewport().height() // 2
            sb.setValue(max(0, target))

    def _clear_highlights(self) -> None:
        self._pane.setExtraSelections([])
