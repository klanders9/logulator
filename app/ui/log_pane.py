# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Shared LogPane QTextEdit subclass used by MainWindow and FileViewer."""

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

_DEFAULT_CAP = 100_000
_PANE_STYLE = (
    "QTextEdit {"
    "  border: 1px solid #555555;"
    "}"
)
_PLAIN_COLOR = "#cccccc"


def _fmt(hex_color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    return f


class LogPane(QTextEdit):
    """QTextEdit that (a) copies as plain text, (b) enforces a configurable
    line cap, (c) emits line_double_clicked on double-click, and (d) emits
    file_dropped when a local file URL is dropped onto it."""

    line_double_clicked = Signal(str)
    file_dropped = Signal(object)  # emits Path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap = _DEFAULT_CAP

    def set_cap(self, new_cap: int) -> None:
        self._cap = new_cap
        self._trim_to_cap(self.document())

    def _trim_to_cap(self, doc) -> None:
        """Drop the oldest blocks in one edit.

        Removing a block per iteration made lowering the cap O(excess) cursor
        edits — measurably slow at the 500,000 maximum. One extended selection
        does the same work in a single removal.
        """
        excess = doc.blockCount() - self._cap
        if excess <= 0:
            return
        trim = QTextCursor(doc)
        trim.movePosition(QTextCursor.MoveOperation.Start)
        trim.movePosition(
            QTextCursor.MoveOperation.NextBlock,
            QTextCursor.MoveMode.KeepAnchor,
            excess,
        )
        trim.removeSelectedText()

    def mouseDoubleClickEvent(self, event) -> None:
        cursor = self.cursorForPosition(event.pos())
        line = cursor.block().text()
        super().mouseDoubleClickEvent(event)
        if line:
            self.line_double_clicked.emit(line)

    def createMimeData(self, selection) -> QMimeData:
        mime = QMimeData()
        mime.setText(selection.toPlainText())
        return mime

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.file_dropped.emit(Path(url.toLocalFile()))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def append_line(
        self, segments: List[Tuple[str, QTextCharFormat]], scroll: bool = True
    ) -> None:
        sb = self.verticalScrollBar()
        was_at_bottom = sb.value() >= sb.maximum() - 4

        doc = self.document()
        is_empty = doc.blockCount() == 1 and doc.lastBlock().text() == ""

        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not is_empty:
            cursor.insertBlock()
        for text, fmt in segments:
            cursor.insertText(text, fmt)

        self._trim_to_cap(doc)

        if scroll and was_at_bottom:
            sb.setValue(sb.maximum())

    def replace_lines(self, segmented_lines) -> None:
        """Rebuild the whole pane from an iterable of segment lists.

        Builds a fresh document with one cursor and swaps it in, rather than
        clearing and calling append_line() per line. That skips the per-line
        scrollbar and cap bookkeeping, and lets the caller pass a generator
        reading the current document — no need to materialise every line as a
        Python list first, which mattered at the 500,000-line cap.
        """
        new_doc = QTextDocument(self)
        new_doc.setDefaultFont(self.font())
        cursor = QTextCursor(new_doc)
        first = True
        for segments in segmented_lines:
            if not first:
                cursor.insertBlock()
            for text, fmt in segments:
                cursor.insertText(text, fmt)
            first = False
        self._trim_to_cap(new_doc)
        self.setDocument(new_doc)


def make_pane(font: QFont, cap: Optional[int] = None) -> LogPane:
    pane = LogPane()
    pane.setReadOnly(True)
    pane.setStyleSheet(_PANE_STYLE)
    pane.setFont(font)
    if cap is not None:
        pane.set_cap(cap)
    return pane


def doc_line_count(pane: LogPane) -> int:
    """Number of lines displayed in a pane (0 for an empty document — Qt
    reports blockCount() == 1 for an empty QTextDocument)."""
    doc = pane.document()
    n = doc.blockCount()
    if n == 1 and doc.firstBlock().text() == "":
        return 0
    return n


def pane_with_header(
    pane: LogPane, title: str, side_widget: Optional[QWidget] = None
) -> Tuple[QWidget, QLabel]:
    """Wrap a pane in a container with a slim header label above it.
    Returns (container, header_label) — the container goes in the splitter,
    the label can be updated live (e.g. filtered match counts). If
    side_widget is given (e.g. a Minimap), it's placed beside the pane,
    below the header, so it lines up with the pane's rows rather than
    spanning the header too."""
    header = QLabel(title)
    header.setStyleSheet("color: #999999; font-size: 11px; padding: 1px 4px;")
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(1)
    layout.addWidget(header)
    if side_widget is not None:
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(pane, stretch=1)
        content_layout.addWidget(side_widget)
        layout.addWidget(content, stretch=1)
    else:
        layout.addWidget(pane, stretch=1)
    return container, header
