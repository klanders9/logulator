# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Inline bar for injecting a MARK line into the session log.

Marks note events that happen outside the log — pulling power, swapping an
antenna, starting a test step — so the log can be lined up with them
afterwards. Deliberately separate from the send bar: a mark is recorded, never
transmitted, and mixing the two would put a note on the wire by accident.
"""

from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class MarkBar(QWidget):
    mark_requested = Signal(str)  # note text, possibly empty
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Mark:"))

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Note an external event — Enter to record it in the log"
        )
        self._input.returnPressed.connect(self._commit)
        self._input.installEventFilter(self)

        self._add_btn = QPushButton("Add mark")
        self._add_btn.setToolTip("Record a >>>MARK line with a UTC timestamp")
        self._add_btn.clicked.connect(self._commit)

        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(24)
        close_btn.clicked.connect(self._close)

        layout.addWidget(self._input, stretch=1)
        layout.addWidget(self._add_btn)
        layout.addWidget(close_btn)

    # ---- Event handling ----

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._close()
                return True
        return super().eventFilter(obj, event)

    def _commit(self):
        # The bar stays open: marking a run of test steps is the common case,
        # and reopening it per step would make a sequence tedious.
        self.mark_requested.emit(self._input.text())
        self._input.clear()

    def _close(self):
        self.setVisible(False)
        self.closed.emit()

    # ---- Public API ----

    def show_and_focus(self):
        self.setVisible(True)
        self._input.setFocus()
        self._input.selectAll()

    def set_connected(self, connected: bool) -> None:
        """A mark is only meaningful while a session log is open to hold it."""
        self._input.setEnabled(connected)
        self._add_btn.setEnabled(connected)
