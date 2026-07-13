# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Widget providing serial port enumeration (QComboBox), baud rate selector,
an advanced-config button (data bits/parity/stop bits/flow/DTR/RTS via
SerialConfigDialog), and a Connect/Disconnect button. Emits
connect_requested(port, baud) and disconnect_requested() signals.
Last-used port and baud are persisted and restored on launch."""

from typing import Optional

import serial.tools.list_ports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from app.settings import AppSettings
from app.ui.serial_config_dialog import SerialConfigDialog, config_summary, config_tooltip

_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600", "1000000"]

_DOT_COLORS = {
    "idle": "#777777",
    "connected": "#50fa7b",
    "reconnecting": "#ffb86c",
}
_DOT_TOOLTIPS = {
    "idle": "Not connected",
    "connected": "Connected",
    "reconnecting": "Reconnecting…",
}


class SerialPanel(QWidget):
    connect_requested = Signal(str, int)
    disconnect_requested = Signal()
    clear_requested = Signal()
    auto_reconnect_changed = Signal(bool)

    def __init__(self, settings: Optional[AppSettings] = None, parent=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else AppSettings()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status_dot = QLabel("●")
        self.set_status("idle")

        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(180)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)

        self._baud_combo = QComboBox()
        self._baud_combo.addItems(_BAUD_RATES)
        saved_baud = str(self._settings.last_baud())
        self._baud_combo.setCurrentText(
            saved_baud if saved_baud in _BAUD_RATES else "115200"
        )

        self._config_btn = QPushButton()
        self._config_btn.clicked.connect(self._on_config_clicked)
        self._update_config_button()

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setDefault(True)
        self._connect_btn.clicked.connect(self._on_connect_toggle)

        self._auto_reconnect_cb = QCheckBox("Auto-reconnect")
        self._auto_reconnect_cb.toggled.connect(self.auto_reconnect_changed)

        layout.addWidget(self._status_dot)
        layout.addWidget(QLabel("Port:"))
        layout.addWidget(self._port_combo)
        layout.addWidget(refresh_btn)
        layout.addWidget(QLabel("Baud:"))
        layout.addWidget(self._baud_combo)
        layout.addWidget(self._config_btn)
        layout.addWidget(self._connect_btn)
        layout.addWidget(self._auto_reconnect_cb)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_requested)

        layout.addStretch()
        layout.addWidget(clear_btn)

        self._connected = False
        self._refresh_ports()
        self._restore_last_port()

    def _refresh_ports(self):
        # Preserve the current selection across a refresh when possible.
        current = self._port_combo.currentData()
        self._port_combo.clear()
        for p in serial.tools.list_ports.comports():
            desc = p.description if p.description and p.description != "n/a" else ""
            label = f"{p.device} — {desc}" if desc else p.device
            self._port_combo.addItem(label, p.device)
        if current:
            idx = self._port_combo.findData(current)
            if idx >= 0:
                self._port_combo.setCurrentIndex(idx)

    def _restore_last_port(self):
        saved = self._settings.last_port()
        if saved:
            idx = self._port_combo.findData(saved)
            if idx >= 0:
                self._port_combo.setCurrentIndex(idx)

    def _on_config_clicked(self):
        dlg = SerialConfigDialog(self._settings, self)
        if dlg.exec():
            self._update_config_button()

    def _update_config_button(self):
        self._config_btn.setText(config_summary(self._settings))
        self._config_btn.setToolTip(config_tooltip(self._settings))

    def _on_connect_toggle(self):
        if self._connected:
            self.disconnect_requested.emit()
        else:
            port = self._port_combo.currentData()
            if port:
                baud = int(self._baud_combo.currentText())
                self._settings.set_last_port(port)
                self._settings.set_last_baud(baud)
                self.connect_requested.emit(port, baud)

    def set_connected(self, connected: bool):
        self._connected = connected
        self._connect_btn.setText("Disconnect" if connected else "Connect")
        self._port_combo.setEnabled(not connected)
        self._baud_combo.setEnabled(not connected)
        self._config_btn.setEnabled(not connected)
        self.set_status("connected" if connected else "idle")

    def set_status(self, state: str) -> None:
        """state: 'idle' | 'connected' | 'reconnecting' — drives the dot."""
        color = _DOT_COLORS.get(state, _DOT_COLORS["idle"])
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        self._status_dot.setToolTip(_DOT_TOOLTIPS.get(state, ""))

    def auto_reconnect(self) -> bool:
        return self._auto_reconnect_cb.isChecked()

    def set_auto_reconnect(self, val: bool) -> None:
        self._auto_reconnect_cb.setChecked(val)
