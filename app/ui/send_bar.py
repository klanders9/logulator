# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Input row for sending characters out the serial port. Enter (or the Send
button) emits send_requested(text, ending). Up/Down arrows recall previously
sent lines. The line-ending selector is persisted via AppSettings; the history
is in-memory only. Disabled while disconnected."""

import sys
from typing import List, Optional

from PySide6.QtCore import QEvent, Qt, Signal
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

# The modifier that means "physical Control key". Qt maps ControlModifier to
# Command on macOS and MetaModifier to the actual Control key, so the platforms
# need opposite values here. On macOS this also means control characters never
# collide with the app's Cmd-based shortcuts.
_CTRL_MOD = (
    Qt.KeyboardModifier.MetaModifier
    if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)

# Modifiers that rule out a control character: they signal a different gesture
# (Ctrl+Shift+F is an app shortcut, not ^F).
_DISQUALIFYING_MODS = (
    Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.AltModifier
    | (
        Qt.KeyboardModifier.ControlModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.MetaModifier
    )
)

# Control codes that aren't Ctrl+letter.
_EXTRA_CONTROL_KEYS = {
    Qt.Key.Key_BracketLeft: 0x1B,   # ^[  ESC
    Qt.Key.Key_Backslash: 0x1C,     # ^\  quit
    Qt.Key.Key_BracketRight: 0x1D,  # ^]
    Qt.Key.Key_Space: 0x00,         # ^@  NUL
    Qt.Key.Key_At: 0x00,
}


def control_code_for(event) -> Optional[int]:
    """Control byte a key event should transmit, or None.

    Ctrl+A..Ctrl+Z map to 0x01..0x1A, Escape to 0x1B, plus the handful of
    bracket/space codes terminals use.
    """
    key = event.key()
    if key == Qt.Key.Key_Escape:
        return 0x1B
    mods = event.modifiers()
    if not (mods & _CTRL_MOD) or (mods & _DISQUALIFYING_MODS):
        return None
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return key - Qt.Key.Key_A + 1
    return _EXTRA_CONTROL_KEYS.get(key)


def control_mnemonic(code: int) -> str:
    """Caret notation for a control byte, e.g. 0x03 -> '^C'."""
    return "^" + chr(code + 0x40)


class _HistoryLineEdit(QLineEdit):
    """QLineEdit with shell-style up/down history recall and control-key
    passthrough, so the field behaves like a terminal for Ctrl+C and friends."""

    control_typed = Signal(int)  # control byte, e.g. 0x03

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[str] = []
        self._idx = 0  # == len(_history) means "editing a new line"
        self._pending = ""  # text in progress before history navigation began

    def event(self, event) -> bool:
        # QAction shortcuts are resolved before the key reaches keyPressEvent,
        # so a combination bound at window level (Ctrl+F on Linux/Windows)
        # would never arrive. Claiming the ShortcutOverride says "this widget
        # handles that key", and the event comes through as a normal keypress.
        if event.type() == QEvent.Type.ShortcutOverride:
            if control_code_for(event) is not None:
                event.accept()
                return True
        return super().event(event)

    def add_history(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            del self._history[:-_HISTORY_MAX]
        self._idx = len(self._history)
        self._pending = ""

    def keyPressEvent(self, event) -> None:
        code = control_code_for(event)
        if code is not None:
            # Sent immediately and on its own — an interrupt must not wait for
            # Enter, and must not pick up the line-ending selector.
            self.control_typed.emit(code)
            event.accept()
            return
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
    send_requested = Signal(str, str)     # (text, line-ending characters)
    control_requested = Signal(bytes, str)  # (raw control byte, e.g. "^C")

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
        self._input.control_typed.connect(self._on_control)
        self._input.setToolTip(
            "Enter to send, ↑/↓ for history.\n"
            "Control keys go straight out: Ctrl+C sends ^C, Escape sends ^[."
        )
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

    def _on_control(self, code: int) -> None:
        self.control_requested.emit(bytes([code]), control_mnemonic(code))

    def set_connected(self, connected: bool) -> None:
        self._input.setEnabled(connected)
        self._send_btn.setEnabled(connected)
        if connected:
            self._input.setFocus()
