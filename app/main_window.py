"""Top-level QMainWindow. Composes SerialPanel, FilterBar, and the display
panes. Enforces the 10,000-line display cap via LogPane.append_line()."""

from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.colorizer import Colorizer
from app.log_writer import LogWriter
from app.serial_worker import SerialWorker
from app.settings import AppSettings
from app.ui.filter_bar import FilterBar
from app.ui.serial_panel import SerialPanel
from app.ui.settings_sidebar import SettingsSidebar

_MAX_DISPLAY_LINES = 10_000
_DEFAULT_FONT_SIZE = 12
_PANE_STYLE = (
    "QTextEdit {"
    "  background-color: #000000;"
    "  color: #cccccc;"
    "  selection-background-color: #1a5fa8;"
    "}"
)
_PLAIN_COLOR = "#cccccc"


class LogPane(QTextEdit):
    """QTextEdit subclass that: (a) copies as plain text only, and
    (b) enforces a hard line cap via append_line()."""

    def createMimeData(self, selection) -> QMimeData:
        mime = QMimeData()
        mime.setText(selection.toPlainText())
        return mime

    def append_line(self, segments: List[Tuple[str, QTextCharFormat]], scroll: bool = True) -> None:
        doc = self.document()
        is_empty = doc.blockCount() == 1 and doc.lastBlock().text() == ""

        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not is_empty:
            cursor.insertBlock()
        for text, fmt in segments:
            cursor.insertText(text, fmt)

        # Trim oldest line when over cap
        while doc.blockCount() > _MAX_DISPLAY_LINES:
            trim = QTextCursor(doc)
            trim.movePosition(QTextCursor.MoveOperation.Start)
            trim.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
            trim.removeSelectedText()

        if scroll:
            sb = self.verticalScrollBar()
            sb.setValue(sb.maximum())


def _make_pane(font: QFont) -> LogPane:
    pane = LogPane()
    pane.setReadOnly(True)
    pane.setStyleSheet(_PANE_STYLE)
    pane.setFont(font)
    return pane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("logulator")
        self.resize(1200, 720)

        self._settings = AppSettings()
        self._colorizer = Colorizer(self._settings)
        self._plain_fmt = _fmt(_PLAIN_COLOR)

        self._worker: Optional[SerialWorker] = None
        self._log_writer = LogWriter()
        self._rules: list = []
        self._filter_mode = "OR"
        self._line_count = 0
        self._connect_time: Optional[datetime] = None
        self._splitter_initialized = False

        # --- Build UI ---
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(_DEFAULT_FONT_SIZE)

        self._raw_pane = _make_pane(font)
        self._filtered_pane = _make_pane(font)
        self._filtered_pane.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._raw_pane)
        self._splitter.addWidget(self._filtered_pane)

        self._serial_panel = SerialPanel()
        self._filter_bar = FilterBar()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self._serial_panel)
        left_layout.addWidget(self._filter_bar)
        left_layout.addWidget(self._splitter, stretch=1)

        self._sidebar = SettingsSidebar(self._settings)
        self._sidebar.setVisible(self._settings.sidebar_open())
        self._sidebar.settings_changed.connect(self._on_settings_changed)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        main_layout.addWidget(left, stretch=1)
        main_layout.addWidget(self._sidebar)

        # Gear button in toolbar
        toolbar = self.addToolBar("Settings")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self._settings_action = toolbar.addAction("⚙  Settings")
        self._settings_action.setCheckable(True)
        self._settings_action.setChecked(self._settings.sidebar_open())
        self._settings_action.toggled.connect(self._on_sidebar_toggle)

        # Status bar
        self._status_log = QLabel("Not connected")
        self._status_stats = QLabel("")
        self.statusBar().addWidget(self._status_log)
        self.statusBar().addPermanentWidget(self._status_stats)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_status_bar)

        # Signal wiring
        self._serial_panel.connect_requested.connect(self._on_connect)
        self._serial_panel.disconnect_requested.connect(self._on_disconnect)
        self._serial_panel.font_size_changed.connect(self._on_font_size_changed)
        self._serial_panel.clear_requested.connect(self._on_clear)
        self._filter_bar.filters_changed.connect(self._on_filters_changed)
        self._raw_pane.selectionChanged.connect(self._on_raw_pane_selection_changed)
        self._filtered_pane.selectionChanged.connect(self._on_filtered_pane_selection_changed)

        # Restore geometry
        geometry = self._settings.load_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.load_splitter()
        if splitter_state:
            self._splitter.restoreState(splitter_state)
            self._splitter_initialized = True

    # ------------------------------------------------------------------
    # Colorization helpers
    # ------------------------------------------------------------------

    def _get_segments(self, line: str, pane: str) -> List[Tuple[str, QTextCharFormat]]:
        """Return (text, format) segments. pane is 'raw' or 'filtered'."""
        if not self._settings.color_enabled():
            return [(line, self._plain_fmt)]
        apply_to = self._settings.color_apply_to()
        if apply_to == "none":
            return [(line, self._plain_fmt)]
        if apply_to == "raw" and pane != "raw":
            return [(line, self._plain_fmt)]
        if apply_to == "filtered" and pane != "filtered":
            return [(line, self._plain_fmt)]
        return self._colorizer.colorize(line)

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

    def _on_disconnect(self, prompt_clear: bool = True):
        self._timer.stop()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._log_writer.close()
        self._connect_time = None
        self._serial_panel.set_connected(False)
        self._status_log.setText("Not connected")
        self._status_stats.setText("")

        if prompt_clear:
            reply = QMessageBox.question(
                self,
                "Clear display?",
                "Clear the log display?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_clear()

    def _on_serial_error(self, message: str):
        self._on_disconnect(prompt_clear=False)
        QMessageBox.critical(self, "Serial error", message)

    # ------------------------------------------------------------------
    # Incoming data
    # ------------------------------------------------------------------

    def _on_new_line(self, line: str):
        self._raw_pane.append_line(self._get_segments(line, "raw"))
        self._line_count += 1
        if self._rules and filter_engine.match(line, self._rules, self._filter_mode):
            self._filtered_pane.append_line(self._get_segments(line, "filtered"))

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
        self._filtered_pane.setUpdatesEnabled(False)
        self._filtered_pane.clear()
        while block != doc.end():
            text = block.text()
            if filter_engine.match(text, self._rules, self._filter_mode):
                self._filtered_pane.append_line(self._get_segments(text, "filtered"), scroll=False)
            block = block.next()
        self._filtered_pane.setUpdatesEnabled(True)
        sb = self._filtered_pane.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _rebuild_raw_pane(self):
        doc = self._raw_pane.document()
        block = doc.begin()
        lines = []
        while block != doc.end():
            lines.append(block.text())
            block = block.next()
        self._raw_pane.setUpdatesEnabled(False)
        self._raw_pane.clear()
        for line in lines:
            self._raw_pane.append_line(self._get_segments(line, "raw"), scroll=False)
        self._raw_pane.setUpdatesEnabled(True)
        sb = self._raw_pane.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # UI controls
    # ------------------------------------------------------------------

    def _on_clear(self):
        self._raw_pane.clear()
        if self._filtered_pane.isVisible():
            self._filtered_pane.clear()
        self._line_count = 0

    def _on_settings_changed(self):
        self._rebuild_raw_pane()
        if self._filtered_pane.isVisible():
            self._rebuild_filtered_pane()

    def _on_sidebar_toggle(self, checked: bool):
        self._sidebar.setVisible(checked)
        self._settings.set_sidebar_open(checked)

    def _on_raw_pane_selection_changed(self):
        cursor = self._filtered_pane.textCursor()
        if cursor.hasSelection():
            self._filtered_pane.blockSignals(True)
            cursor.clearSelection()
            self._filtered_pane.setTextCursor(cursor)
            self._filtered_pane.blockSignals(False)

    def _on_filtered_pane_selection_changed(self):
        cursor = self._raw_pane.textCursor()
        if cursor.hasSelection():
            self._raw_pane.blockSignals(True)
            cursor.clearSelection()
            self._raw_pane.setTextCursor(cursor)
            self._raw_pane.blockSignals(False)

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
        self._settings.save_geometry(self.saveGeometry())
        self._settings.save_splitter(self._splitter.saveState())
        self._on_disconnect(prompt_clear=False)
        super().closeEvent(event)


def _fmt(hex_color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    return f
