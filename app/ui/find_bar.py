# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Find bar widget for FileViewer. Toggled with Ctrl+F, dismissed with Escape."""

from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class FindBar(QWidget):
    text_changed = Signal(str)
    go_next = Signal()
    go_prev = Signal()
    filter_to_matches = Signal(str)  # search text to add as include rule
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Find:"))

        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in file…")
        self._input.textChanged.connect(self.text_changed)
        self._input.returnPressed.connect(self._on_return)
        self._input.installEventFilter(self)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(28)
        self._prev_btn.setToolTip("Previous match (Shift+Enter)")
        self._prev_btn.clicked.connect(self.go_prev)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(28)
        self._next_btn.setToolTip("Next match (Enter)")
        self._next_btn.clicked.connect(self.go_next)

        self._count_label = QLabel("")
        self._count_label.setMinimumWidth(72)

        self._filter_btn = QPushButton("Filter to matches")
        self._filter_btn.setToolTip("Add current search as a filter rule")
        self._filter_btn.clicked.connect(self._on_filter_to_matches)

        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(24)
        close_btn.clicked.connect(self._close)

        layout.addWidget(self._input, stretch=1)
        layout.addWidget(self._prev_btn)
        layout.addWidget(self._next_btn)
        layout.addWidget(self._count_label)
        layout.addWidget(self._filter_btn)
        layout.addWidget(close_btn)

    # ---- Event handling ----

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._close()
                return True
        return super().eventFilter(obj, event)

    def _on_return(self):
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.go_prev.emit()
        else:
            self.go_next.emit()

    def _on_filter_to_matches(self):
        text = self._input.text().strip()
        if text:
            self.filter_to_matches.emit(text)

    def _close(self):
        self.setVisible(False)
        self.closed.emit()

    # ---- Public API ----

    def show_and_focus(self):
        self.setVisible(True)
        self._input.setFocus()
        self._input.selectAll()

    def get_text(self) -> str:
        return self._input.text()

    def set_match_status(self, current: int, total: int, has_query: bool = True):
        if not has_query:
            self._count_label.setText("")
            self._input.setStyleSheet("")
        elif total == 0:
            self._count_label.setText("No matches")
            self._input.setStyleSheet("QLineEdit { background: #3a0000; }")
        else:
            self._count_label.setText(f"{current} of {total}")
            self._input.setStyleSheet("")

    def clear_status(self):
        self._count_label.setText("")
        self._input.setStyleSheet("")
