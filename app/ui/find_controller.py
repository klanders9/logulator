# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Reusable controller binding a FindBar to a LogPane. Owns all search state:
match positions, current index, debounce timer, and highlight application.
Used by FileViewer (static file search) and MainWindow (live buffer search)."""

from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.theme import active_colors
from app.ui.find_bar import FindBar
from app.ui.log_pane import LogPane

# Maximum ExtraSelections applied at once (performance guard)
_MAX_HIGHLIGHTS = 5000

_SEARCH_DEBOUNCE_MS = 300


class FindController(QObject):
    def __init__(self, find_bar: FindBar, pane: LogPane, parent=None):
        super().__init__(parent)
        self._bar = find_bar
        self._pane = pane
        # (start position, length) rather than QTextCursor. Every live cursor
        # is repositioned by Qt on every document edit, so holding one per
        # match made appends scale with the match count: measured at 7.5x
        # slower with 60k matches, enough to stall the main window's live
        # buffer under a busy serial feed. Cursors are now built on demand,
        # only for the matches actually being highlighted.
        self._matches: List[Tuple[int, int]] = []
        self._current_match_idx = -1
        self._doc_revision = -1

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

    def _do_search(self, keep_index: bool = False) -> None:
        text = self._bar.get_text()
        if not text:
            self._clear_highlights()
            return

        doc = self._pane.document()
        self._matches = []
        cursor = doc.find(text, 0)
        while not cursor.isNull():
            start = cursor.selectionStart()
            self._matches.append((start, cursor.selectionEnd() - start))
            cursor = doc.find(text, cursor)
        self._doc_revision = doc.revision()

        total = len(self._matches)
        if total == 0:
            self._current_match_idx = -1
            self._clear_highlights()
            self._bar.set_match_status(0, 0)
            return

        if keep_index and self._current_match_idx >= 0:
            self._current_match_idx = min(self._current_match_idx, total - 1)
        else:
            self._current_match_idx = 0
        self._apply_highlights()
        self._bar.set_match_status(self._current_match_idx + 1, total)

    def _refresh_if_stale(self) -> None:
        """Re-run the search when the document changed under us.

        Positions are plain integers, so an append or a buffer trim invalidates
        them. Qt bumps the document revision on every edit, which makes the
        check cheap enough to do on each navigation.
        """
        if self._doc_revision != self._pane.document().revision():
            self._do_search(keep_index=True)

    def _step(self, delta: int) -> None:
        self._refresh_if_stale()
        if not self._matches:
            return
        self._current_match_idx = (self._current_match_idx + delta) % len(self._matches)
        self._apply_highlights()
        self._bar.set_match_status(self._current_match_idx + 1, len(self._matches))

    def _on_next(self) -> None:
        self._step(1)

    def _on_prev(self) -> None:
        self._step(-1)

    def _on_closed(self) -> None:
        self._clear_highlights()
        self._matches = []
        self._current_match_idx = -1
        self._doc_revision = -1

    def _cursor_for(self, index: int) -> Optional[QTextCursor]:
        """Build a cursor for one match, or None if it no longer fits.

        Clamped against the current document: a match recorded before the
        buffer was trimmed can point past the end.
        """
        start, length = self._matches[index]
        doc = self._pane.document()
        end = start + length
        if start < 0 or end > doc.characterCount():
            return None
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def _apply_highlights(self) -> None:
        non_current_fmt = QTextCharFormat()
        non_current_fmt.setBackground(QColor(active_colors()["match_highlight"]))

        # Cap highlights for performance; always include a window around current
        total = len(self._matches)
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
            cursor = self._cursor_for(i)
            if cursor is None:
                continue
            sel = QTextEdit.ExtraSelection()
            sel.format = non_current_fmt
            sel.cursor = cursor
            selections.append(sel)

        self._pane.setExtraSelections(selections)

        # Jump to current match using the text cursor (standard selection highlight)
        if 0 <= self._current_match_idx < total:
            cur = self._cursor_for(self._current_match_idx)
            if cur is None:
                return
            self._pane.setTextCursor(cur)
            self._pane.ensureCursorVisible()
            rect = self._pane.cursorRect()
            sb = self._pane.verticalScrollBar()
            target = sb.value() + rect.center().y() - self._pane.viewport().height() // 2
            sb.setValue(max(0, target))

    def _clear_highlights(self) -> None:
        self._pane.setExtraSelections([])
