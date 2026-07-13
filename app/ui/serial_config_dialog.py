# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Modal dialog for advanced serial connection options: data bits, parity,
stop bits, flow control, and initial DTR/RTS line state. Reads and writes
AppSettings on accept."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from app.settings import AppSettings

_DATABITS = ["5", "6", "7", "8"]

_PARITY_LABELS = ["None", "Even", "Odd", "Mark", "Space"]
_PARITY_VALUES = ["N", "E", "O", "M", "S"]

_STOPBITS = ["1", "1.5", "2"]

_FLOW_LABELS = ["None", "RTS/CTS (hardware)", "XON/XOFF (software)"]
_FLOW_VALUES = ["none", "rtscts", "xonxoff"]


def config_summary(settings: AppSettings) -> str:
    """Short '8-N-1' style summary of the current serial options."""
    return (
        f"{settings.serial_databits()}"
        f"-{settings.serial_parity()}"
        f"-{settings.serial_stopbits()}"
    )


def config_tooltip(settings: AppSettings) -> str:
    """Full multi-line description of the current serial options."""
    parity = _PARITY_LABELS[_PARITY_VALUES.index(settings.serial_parity())]
    flow = _FLOW_LABELS[_FLOW_VALUES.index(settings.serial_flow())]
    return (
        "Advanced serial settings\n"
        f"Data bits: {settings.serial_databits()}\n"
        f"Parity: {parity}\n"
        f"Stop bits: {settings.serial_stopbits()}\n"
        f"Flow control: {flow}\n"
        f"DTR on connect: {'asserted' if settings.serial_dtr() else 'not asserted'}\n"
        f"RTS on connect: {'asserted' if settings.serial_rts() else 'not asserted'}"
    )


class SerialConfigDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._s = settings
        self.setWindowTitle("Serial Configuration")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(12)

        self._databits_combo = QComboBox()
        self._databits_combo.addItems(_DATABITS)
        self._databits_combo.setCurrentText(str(settings.serial_databits()))
        form.addRow("Data bits:", self._databits_combo)

        self._parity_combo = QComboBox()
        self._parity_combo.addItems(_PARITY_LABELS)
        self._parity_combo.setCurrentIndex(
            _PARITY_VALUES.index(settings.serial_parity())
        )
        form.addRow("Parity:", self._parity_combo)

        self._stopbits_combo = QComboBox()
        self._stopbits_combo.addItems(_STOPBITS)
        self._stopbits_combo.setCurrentText(settings.serial_stopbits())
        form.addRow("Stop bits:", self._stopbits_combo)

        self._flow_combo = QComboBox()
        self._flow_combo.addItems(_FLOW_LABELS)
        self._flow_combo.setCurrentIndex(_FLOW_VALUES.index(settings.serial_flow()))
        self._flow_combo.currentIndexChanged.connect(self._on_flow_changed)
        form.addRow("Flow control:", self._flow_combo)

        layout.addLayout(form)

        self._dtr_cb = QCheckBox("Assert DTR on connect")
        self._dtr_cb.setChecked(settings.serial_dtr())
        self._dtr_cb.setToolTip(
            "Some boards (e.g. Arduino-style bootloaders) reset when DTR toggles.\n"
            "Uncheck to leave DTR de-asserted when the port opens."
        )
        layout.addWidget(self._dtr_cb)

        self._rts_cb = QCheckBox("Assert RTS on connect")
        self._rts_cb.setChecked(settings.serial_rts())
        self._rts_cb.setToolTip(
            "Initial RTS line state when the port opens.\n"
            "Ignored under RTS/CTS flow control (driver-managed)."
        )
        layout.addWidget(self._rts_cb)

        hint = QLabel("Applied on the next connect.")
        hint.setStyleSheet("color: #888888;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_flow_changed(self._flow_combo.currentIndex())

    def _on_flow_changed(self, index: int) -> None:
        # RTS is driver-managed under hardware flow control.
        self._rts_cb.setEnabled(_FLOW_VALUES[index] != "rtscts")

    def accept(self) -> None:
        self._s.set_serial_databits(int(self._databits_combo.currentText()))
        self._s.set_serial_parity(_PARITY_VALUES[self._parity_combo.currentIndex()])
        self._s.set_serial_stopbits(self._stopbits_combo.currentText())
        self._s.set_serial_flow(_FLOW_VALUES[self._flow_combo.currentIndex()])
        self._s.set_serial_dtr(self._dtr_cb.isChecked())
        self._s.set_serial_rts(self._rts_cb.isChecked())
        super().accept()
