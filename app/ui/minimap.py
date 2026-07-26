# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Minimap: a slim colored-band strip next to a LogPane showing a
down-sampled overview of per-line severity colors, with a draggable
viewport indicator for quick navigation.

Used beside the raw and filtered panes of both MainWindow and FileViewer;
`LogWindowMixin` owns the wiring. Off by default — see
`AppSettings.minimap_enabled` / `minimap_apply_to`."""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

_WIDTH = 16
_NEUTRAL_COLOR = QColor("#444444")


class Minimap(QWidget):
    """One thin band per tracked line, nearest-neighbor sampled down to the
    widget's pixel height on paint — repaint cost is O(height), not O(line
    count), so it stays cheap even with hundreds of thousands of lines."""

    position_clicked = Signal(float)  # fraction 0..1 of total scrollable content

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._colors: List[QColor] = []
        self._cap = 100_000
        self._viewport_start = 0.0
        self._viewport_end = 1.0
        self.setFixedWidth(_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border-left: 1px solid #555555;")

    def set_cap(self, cap: int) -> None:
        self._cap = cap
        if len(self._colors) > cap:
            del self._colors[: len(self._colors) - cap]
            self.update()

    def append_color(self, color: QColor) -> None:
        self._colors.append(color)
        if len(self._colors) > self._cap:
            del self._colors[0]
        self.update()

    def set_colors(self, colors: List[QColor]) -> None:
        self._colors = colors[-self._cap :] if self._cap else list(colors)
        self.update()

    def clear(self) -> None:
        self._colors = []
        self.update()

    def set_viewport(self, start_frac: float, end_frac: float) -> None:
        self._viewport_start = start_frac
        self._viewport_end = end_frac
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, self.palette().base())

        n = len(self._colors)
        h = rect.height()
        w = rect.width()
        if n and h:
            for y in range(h):
                idx = min(n - 1, (y * n) // h)
                painter.fillRect(0, y, w, 1, self._colors[idx])

        vy0 = int(self._viewport_start * h)
        vy1 = max(vy0 + 2, int(self._viewport_end * h))
        highlight = self.palette().highlight().color()
        highlight.setAlpha(90)
        painter.fillRect(0, vy0, w, vy1 - vy0, highlight)
        painter.end()

    def _emit_from_pos(self, y: int) -> None:
        h = self.height()
        if h <= 0:
            return
        frac = max(0.0, min(1.0, y / h))
        self.position_clicked.emit(frac)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._emit_from_pos(int(event.position().y()))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._emit_from_pos(int(event.position().y()))
        super().mouseMoveEvent(event)
