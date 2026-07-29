# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Shared LogPane QTextEdit subclass used by MainWindow and FileViewer."""

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from app.ansi import DEFAULT_STYLE, Style
from app.theme import active_colors

_DEFAULT_CAP = 100_000

# Marks a format whose colour came off the wire as an escape sequence rather
# than from the colorizer. Pane rebuilds (theme switch, colorization change,
# filter change) re-colorize from block text, which no longer holds the
# escapes — so without a marker the wire colours would be lost the first time
# anything triggered a rebuild. Formats are value types stored per character
# run, so these survive being copied into the rebuilt document.
#
# The style is recorded alongside the marker rather than only being painted,
# so a run that is currently displayed plain (colorization off, or an
# apply-to setting that excludes this pane) can be restored in full when the
# setting comes back. Painting it and reading the colour back off the
# foreground would make those switches one-way.
ANSI_PROPERTY = QTextFormat.Property.UserProperty + 1
ANSI_COLOR_PROPERTY = QTextFormat.Property.UserProperty + 2
ANSI_FLAGS_PROPERTY = QTextFormat.Property.UserProperty + 3

_BOLD, _ITALIC, _UNDERLINE = 1, 2, 4


def _pane_style() -> str:
    return "QTextEdit { border: 1px solid %s; }" % active_colors()["border"]


def _plain_color() -> str:
    """Default text color for a line with no recognised structure."""
    return active_colors()["plain_text"]


def _fmt(hex_color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    return f


def ansi_fmt(style: Style, active: bool = True) -> QTextCharFormat:
    """Build a format from an ANSI style, tagged with the style itself.

    `active` False records the style but displays the run plain — used when
    colorization is switched off, or set to a pane this one isn't.

    Only foreground and the three font flags are ever painted — never family
    or point size, so the sidebar's font-size control still applies here.
    """
    f = QTextCharFormat()
    f.setForeground(QColor(style.color if active and style.color else _plain_color()))
    if active:
        if style.bold:
            f.setFontWeight(QFont.Weight.Bold)
        if style.italic:
            f.setFontItalic(True)
        if style.underline:
            f.setFontUnderline(True)
    f.setProperty(ANSI_PROPERTY, True)
    f.setProperty(ANSI_COLOR_PROPERTY, style.color or "")
    f.setProperty(
        ANSI_FLAGS_PROPERTY,
        (_BOLD if style.bold else 0)
        | (_ITALIC if style.italic else 0)
        | (_UNDERLINE if style.underline else 0),
    )
    return f


def _fmt_ansi_style(fmt: QTextCharFormat) -> Style:
    """Recover the wire style recorded on a format by ansi_fmt()."""
    flags = fmt.property(ANSI_FLAGS_PROPERTY) or 0
    return Style(
        fmt.property(ANSI_COLOR_PROPERTY) or None,
        bool(flags & _BOLD),
        bool(flags & _ITALIC),
        bool(flags & _UNDERLINE),
    )


def ansi_segments(
    text: str, spans, active: bool = True
) -> List[Tuple[str, QTextCharFormat]]:
    """Segments for a line whose colours came off the wire.

    Gaps between spans get the default style, the way a terminal falls back to
    the default foreground, and are tagged too so the whole block round-trips
    through a rebuild as one unit.
    """
    segments: List[Tuple[str, QTextCharFormat]] = []
    at = 0
    for start, length, style in spans:
        if start > at:
            segments.append((text[at:start], ansi_fmt(DEFAULT_STYLE, active)))
        segments.append((text[start:start + length], ansi_fmt(style, active)))
        at = start + length
    if at < len(text):
        segments.append((text[at:], ansi_fmt(DEFAULT_STYLE, active)))
    return segments


def block_ansi_styles(block) -> Optional[List[Tuple[str, Style]]]:
    """Stored (text, Style) runs of a block that was painted from escapes.

    Returns None for an ordinary block, so the caller can re-colorize it
    normally. Styles rather than formats, so the caller re-applies the current
    colorization settings through the same path a fresh line takes.
    """
    runs: List[Tuple[str, Style]] = []
    tagged = False
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid():
            fmt = fragment.charFormat()
            if fmt.property(ANSI_PROPERTY):
                tagged = True
            runs.append((fragment.text(), _fmt_ansi_style(fmt)))
        it += 1
    return runs if tagged else None


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

    def createMimeDataFromSelection(self) -> QMimeData:
        """Put only plain text on the clipboard.

        QTextEdit's default also offers text/html (with the colour spans),
        text/markdown and ODF, so pasting a log line into any rich-text target
        carried the colouring along.

        This is the QTextEdit virtual; an earlier `createMimeData(selection)`
        override matched no Qt hook and never ran.

        QTextCursor.selectedText() separates blocks with U+2029, which pastes
        as an unreadable single line, so translate those back to newlines.
        """
        mime = QMimeData()
        mime.setText(self.textCursor().selectedText().replace(" ", "\n"))
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

    def _select_last_block(self, doc) -> QTextCursor:
        """Cursor selecting the last block's text, without its separator."""
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        return cursor

    def replace_last_line(
        self, segments: List[Tuple[str, QTextCharFormat]], scroll: bool = True
    ) -> None:
        """Rewrite the last block in place.

        Used for a provisional line — a shell prompt or other unterminated
        tail — that grows as more bytes arrive. Appending each revision would
        stack up partial copies of the same line.
        """
        sb = self.verticalScrollBar()
        was_at_bottom = sb.value() >= sb.maximum() - 4

        cursor = self._select_last_block(self.document())
        cursor.removeSelectedText()
        for text, fmt in segments:
            cursor.insertText(text, fmt)

        if scroll and was_at_bottom:
            sb.setValue(sb.maximum())

    def drop_last_line(self) -> None:
        """Remove the last block entirely, separator included."""
        doc = self.document()
        cursor = self._select_last_block(doc)
        cursor.removeSelectedText()
        if doc.blockCount() > 1:
            cursor.deletePreviousChar()

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


def _style_pane_header(header: QLabel) -> None:
    header.setStyleSheet(
        "color: %s; font-size: 11px; padding: 1px 4px;"
        % active_colors()["header_text"]
    )


def restyle_pane(pane: LogPane) -> None:
    """Re-apply theme-derived styling after a theme switch."""
    pane.setStyleSheet(_pane_style())


def restyle_pane_header(header: QLabel) -> None:
    _style_pane_header(header)


def make_pane(font: QFont, cap: Optional[int] = None) -> LogPane:
    pane = LogPane()
    pane.setReadOnly(True)
    pane.setStyleSheet(_pane_style())
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
    header.setObjectName("paneHeader")
    _style_pane_header(header)
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
