# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Input row for sending characters out the serial port. Enter (or the Send
button) emits send_requested(text, ending). Up/Down arrows recall previously
sent lines. The line-ending selector is persisted via AppSettings; the history
is in-memory only. Disabled while disconnected."""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from app.settings import AppSettings

_ENDING_LABELS = ["CRLF", "LF", "CR", "None"]
_ENDING_VALUES = ["crlf", "lf", "cr", "none"]
_ENDING_CHARS = {"crlf": "\r\n", "lf": "\n", "cr": "\r", "none": ""}

_HISTORY_MAX = 100


class _HistoryLineEdit(QLineEdit):
    """QLineEdit with shell-style up/down history recall."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[str] = []
        self._idx = 0  # == len(_history) means "editing a new line"
        self._pending = ""  # text in progress before history navigation began

    def add_history(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            del self._history[:-_HISTORY_MAX]
        self._idx = len(self._history)
        self._pending = ""

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Up:
            if self._idx > 0:
                if self._idx == len(self._history):
                    self._pending = self.text()
                self._idx -= 1
                self.setText(self._history[self._idx])
            event.accept()
            return
        if event.key() == Qt.Key.Key_Down:
            if self._idx < len(self._history):
                self._idx += 1
                self.setText(
                    self._history[self._idx]
                    if self._idx < len(self._history)
                    else self._pending
                )
            event.accept()
            return
        super().keyPressEvent(event)


class SendBar(QWidget):
    send_requested = Signal(str, str)  # (text, line-ending characters)

    def __init__(self, settings: Optional[AppSettings] = None, parent=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else AppSettings()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Send:"))

        self._input = _HistoryLineEdit()
        self._input.setPlaceholderText("Type to send — Enter to send, ↑/↓ for history")
        self._input.returnPressed.connect(self._on_send)
        layout.addWidget(self._input, stretch=1)

        self._ending_combo = QComboBox()
        self._ending_combo.addItems(_ENDING_LABELS)
        self._ending_combo.setToolTip("Line ending appended to sent text")
        cur = self._settings.tx_line_ending()
        self._ending_combo.setCurrentIndex(
            _ENDING_VALUES.index(cur) if cur in _ENDING_VALUES else 0
        )
        self._ending_combo.currentIndexChanged.connect(
            lambda i: self._settings.set_tx_line_ending(_ENDING_VALUES[i])
        )
        layout.addWidget(self._ending_combo)

        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        layout.addWidget(self._send_btn)

        self.set_connected(False)

    def _on_send(self) -> None:
        text = self._input.text()
        self._input.add_history(text)
        ending = _ENDING_CHARS[_ENDING_VALUES[self._ending_combo.currentIndex()]]
        # Empty text is deliberately allowed: sending a bare line ending is a
        # common way to nudge a shell prompt out of the target.
        self.send_requested.emit(text, ending)
        self._input.clear()

    def set_connected(self, connected: bool) -> None:
        self._input.setEnabled(connected)
        self._send_btn.setEnabled(connected)
        if connected:
            self._input.setFocus()
