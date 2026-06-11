"""Widget providing serial port enumeration (QComboBox), baud rate selector,
and a Connect/Disconnect button. Emits connect_requested(port, baud) and
disconnect_requested() signals."""

import serial.tools.list_ports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600", "1000000"]


class SerialPanel(QWidget):
    connect_requested = Signal(str, int)
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(180)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)

        self._baud_combo = QComboBox()
        self._baud_combo.addItems(_BAUD_RATES)
        self._baud_combo.setCurrentText("115200")

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect_toggle)

        layout.addWidget(QLabel("Port:"))
        layout.addWidget(self._port_combo)
        layout.addWidget(refresh_btn)
        layout.addWidget(QLabel("Baud:"))
        layout.addWidget(self._baud_combo)
        layout.addWidget(self._connect_btn)
        layout.addStretch()

        self._connected = False
        self._refresh_ports()

    def _refresh_ports(self):
        self._port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_combo.addItems(ports)

    def _on_connect_toggle(self):
        if self._connected:
            self.disconnect_requested.emit()
        else:
            port = self._port_combo.currentText()
            if port:
                self.connect_requested.emit(port, int(self._baud_combo.currentText()))

    def set_connected(self, connected: bool):
        self._connected = connected
        self._connect_btn.setText("Disconnect" if connected else "Connect")
        self._port_combo.setEnabled(not connected)
        self._baud_combo.setEnabled(not connected)
