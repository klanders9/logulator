"""Top-level QMainWindow. Composes SerialPanel, FilterBar, and the display
QPlainTextEdit. Wires SerialWorker signals through FilterEngine before
appending lines to the display. Enforces the 10,000-line display cap."""

from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.log_writer import LogWriter
from app.serial_worker import SerialWorker
from app.ui.filter_bar import FilterBar
from app.ui.serial_panel import SerialPanel

_MAX_DISPLAY_LINES = 10_000


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("logulator")
        self.resize(1200, 720)

        self._worker: Optional[SerialWorker] = None
        self._log_writer = LogWriter()
        self._rules: list[dict] = []
        self._filter_mode = "OR"

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(4)

        self._serial_panel = SerialPanel()
        self._filter_bar = FilterBar()

        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        self._display.setMaximumBlockCount(_MAX_DISPLAY_LINES)
        font = self._display.font()
        font.setFamily("Menlo")
        font.setPointSize(12)
        self._display.setFont(font)

        layout.addWidget(self._serial_panel)
        layout.addWidget(self._filter_bar)
        layout.addWidget(self._display, stretch=1)

        self._serial_panel.connect_requested.connect(self._on_connect)
        self._serial_panel.disconnect_requested.connect(self._on_disconnect)
        self._filter_bar.filters_changed.connect(self._on_filters_changed)

    def _on_connect(self, port: str, baud: int):
        self._log_writer.open_session()
        self._worker = SerialWorker(port, baud, self._log_writer)
        self._worker.new_line.connect(self._on_new_line)
        self._worker.error_occurred.connect(self._on_serial_error)
        self._worker.start()
        self._serial_panel.set_connected(True)

    def _on_disconnect(self):
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._log_writer.close()
        self._serial_panel.set_connected(False)

    def _on_new_line(self, line: str):
        if filter_engine.match(line, self._rules, self._filter_mode):
            self._display.appendPlainText(line)

    def _on_filters_changed(self, rules: list, mode: str):
        self._rules = rules
        self._filter_mode = mode

    def _on_serial_error(self, message: str):
        self._on_disconnect()
        QMessageBox.critical(self, "Serial error", message)

    def closeEvent(self, event):
        self._on_disconnect()
        super().closeEvent(event)
