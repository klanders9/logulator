# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Shared LogPane QTextEdit subclass used by MainWindow and FileViewer."""

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

_DEFAULT_CAP = 100_000
_PANE_STYLE = (
    "QTextEdit {"
    "  color: #cccccc;"
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
        doc = self.document()
        while doc.blockCount() > self._cap:
            trim = QTextCursor(doc)
            trim.movePosition(QTextCursor.MoveOperation.Start)
            trim.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
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

        while doc.blockCount() > self._cap:
            trim = QTextCursor(doc)
            trim.movePosition(QTextCursor.MoveOperation.Start)
            trim.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
            trim.removeSelectedText()

        if scroll and was_at_bottom:
            sb.setValue(sb.maximum())


def make_pane(font: QFont, cap: Optional[int] = None) -> LogPane:
    pane = LogPane()
    pane.setReadOnly(True)
    pane.setStyleSheet(_PANE_STYLE)
    pane.setFont(font)
    if cap is not None:
        pane.set_cap(cap)
    return pane
