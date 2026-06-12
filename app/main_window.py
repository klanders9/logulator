"""Top-level QMainWindow. Composes SerialPanel, FilterBar, and the display
QPlainTextEdit. Wires SerialWorker signals through FilterEngine before
appending lines to the display. Enforces the 10,000-line display cap."""

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.log_writer import LogWriter
from app.serial_worker import SerialWorker
from app.ui.filter_bar import FilterBar
from app.ui.serial_panel import SerialPanel

_MAX_DISPLAY_LINES = 10_000
_DEFAULT_FONT_SIZE = 12
_PANE_STYLE = (
    "QPlainTextEdit {"
    "  background-color: #000000;"
    "  color: #cccccc;"
    "  selection-background-color: #444444;"
    "}"
)


def _make_pane(font: QFont) -> QPlainTextEdit:
    pane = QPlainTextEdit()
    pane.setReadOnly(True)
    pane.setMaximumBlockCount(_MAX_DISPLAY_LINES)
    pane.setStyleSheet(_PANE_STYLE)
    pane.setFont(font)
    return pane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("logulator")
        self.resize(1200, 720)

        self._worker: Optional[SerialWorker] = None
        self._log_writer = LogWriter()
        self._rules: list[dict] = []
        self._filter_mode = "OR"
        self._line_count = 0
        self._connect_time: Optional[datetime] = None
        self._splitter_initialized = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(4)

        self._serial_panel = SerialPanel()
        self._filter_bar = FilterBar()

        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(_DEFAULT_FONT_SIZE)

        self._raw_pane = _make_pane(font)
        self._filtered_pane = _make_pane(font)
        self._filtered_pane.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._raw_pane)
        self._splitter.addWidget(self._filtered_pane)

        layout.addWidget(self._serial_panel)
        layout.addWidget(self._filter_bar)
        layout.addWidget(self._splitter, stretch=1)

        # Status bar: log filename left, runtime/count/size right
        self._status_log = QLabel("Not connected")
        self._status_stats = QLabel("")
        self.statusBar().addWidget(self._status_log)
        self.statusBar().addPermanentWidget(self._status_stats)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_status_bar)

        self._serial_panel.connect_requested.connect(self._on_connect)
        self._serial_panel.disconnect_requested.connect(self._on_disconnect)
        self._serial_panel.font_size_changed.connect(self._on_font_size_changed)
        self._filter_bar.filters_changed.connect(self._on_filters_changed)

    # ------------------------------------------------------------------
    # Serial lifecycle
    # ------------------------------------------------------------------

    def _on_connect(self, port: str, baud: int):
        self._log_writer.open_session()
        self._line_count = 0
        self._connect_time = datetime.now()
        path = self._log_writer.current_path
        self._status_log.setText(f"Log: {path.name}" if path else "Log: unknown")

        self._worker = SerialWorker(port, baud, self._log_writer)
        self._worker.new_line.connect(self._on_new_line)
        self._worker.error_occurred.connect(self._on_serial_error)
        self._worker.start()
        self._serial_panel.set_connected(True)
        self._timer.start()

    def _on_disconnect(self):
        self._timer.stop()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._log_writer.close()
        self._connect_time = None
        self._serial_panel.set_connected(False)
        self._status_log.setText("Not connected")
        self._status_stats.setText("")

    def _on_serial_error(self, message: str):
        self._on_disconnect()
        QMessageBox.critical(self, "Serial error", message)

    # ------------------------------------------------------------------
    # Incoming data
    # ------------------------------------------------------------------

    def _on_new_line(self, line: str):
        self._raw_pane.appendPlainText(line)
        self._line_count += 1
        if self._rules and filter_engine.match(line, self._rules, self._filter_mode):
            self._filtered_pane.appendPlainText(line)

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _on_filters_changed(self, rules: list, mode: str):
        self._rules = rules
        self._filter_mode = mode
        if rules:
            if not self._splitter_initialized:
                self._splitter_initialized = True
                h = self._splitter.height()
                if h > 0:
                    self._splitter.setSizes([int(h * 0.6), int(h * 0.4)])
            self._filtered_pane.show()
            self._rebuild_filtered_pane()
        else:
            self._filtered_pane.hide()
            self._filtered_pane.clear()

    def _rebuild_filtered_pane(self):
        doc = self._raw_pane.document()
        block = doc.begin()
        matched = []
        while block != doc.end():
            text = block.text()
            if filter_engine.match(text, self._rules, self._filter_mode):
                matched.append(text)
            block = block.next()
        self._filtered_pane.setPlainText("\n".join(matched))
        sb = self._filtered_pane.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # UI controls
    # ------------------------------------------------------------------

    def _on_font_size_changed(self, size: int):
        for pane in (self._raw_pane, self._filtered_pane):
            f = pane.font()
            f.setPointSize(size)
            pane.setFont(f)

    def _update_status_bar(self):
        if self._connect_time is None:
            return
        elapsed = int((datetime.now() - self._connect_time).total_seconds())
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        runtime = f"{h:02d}:{m:02d}:{s:02d}"

        size_str = ""
        path = self._log_writer.current_path
        if path and path.exists():
            sz = path.stat().st_size
            if sz < 1024:
                size_str = f"{sz} B"
            elif sz < 1_048_576:
                size_str = f"{sz / 1024:.1f} KB"
            else:
                size_str = f"{sz / 1_048_576:.1f} MB"

        self._status_stats.setText(
            f"Runtime: {runtime}  |  Lines: {self._line_count:,}  |  Size: {size_str}"
        )

    def closeEvent(self, event):
        self._on_disconnect()
        super().closeEvent(event)
