# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Top-level QMainWindow. Composes SerialPanel, FilterBar, and the display panes."""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.colorizer import Colorizer
from app.log_writer import LogWriter
from app.serial_worker import SerialWorker
from app.settings import AppSettings
from app.ui.filter_bar import FilterBar
from app.ui.log_pane import LogPane, _fmt, _PANE_STYLE, _PLAIN_COLOR, _DEFAULT_CAP, make_pane
from app.ui.serial_panel import SerialPanel
from app.ui.settings_sidebar import SettingsSidebar

_DEFAULT_FONT_SIZE = 12


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
        self._file_viewers: list = []

        # --- Build UI ---
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(_DEFAULT_FONT_SIZE)

        self._raw_pane = make_pane(font)
        self._filtered_pane = make_pane(font)
        self._filtered_pane.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._raw_pane)
        self._splitter.addWidget(self._filtered_pane)

        self._serial_panel = SerialPanel()
        self._filter_bar = FilterBar(self._settings)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self._filter_bar)
        left_layout.addWidget(self._serial_panel)
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

        # File menu
        file_menu = self.menuBar().addMenu("File")
        open_action = file_menu.addAction("Open Log File…")
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._on_open_file)

        # Toolbar
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self._filter_action = toolbar.addAction("▽ Filter")
        self._filter_action.setCheckable(True)
        self._filter_action.setChecked(self._settings.filter_bar_open())
        self._filter_action.toggled.connect(self._on_filter_action_toggled)
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
        self._filter_bar.input_bar_closed.connect(self._on_filter_bar_closed)
        self._raw_pane.file_dropped.connect(self.open_file)
        self._filtered_pane.file_dropped.connect(self.open_file)
        self._raw_pane.selectionChanged.connect(self._on_raw_pane_selection_changed)
        self._filtered_pane.selectionChanged.connect(self._on_filtered_pane_selection_changed)
        self._filtered_pane.line_double_clicked.connect(self._jump_to_raw_line)
        self._sidebar.buffer_cap_changed.connect(self._on_buffer_cap_changed)

        # Apply persisted buffer cap (overrides _DEFAULT_CAP set in LogPane.__init__)
        initial_cap = self._settings.buffer_cap()
        self._raw_pane.set_cap(initial_cap)
        self._filtered_pane.set_cap(initial_cap)

        # Restore geometry
        geometry = self._settings.load_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.load_splitter()
        if splitter_state:
            self._splitter.restoreState(splitter_state)
            self._splitter_initialized = True

        # Sync filter state from persisted settings (filter bar loads rules in __init__)
        self._on_filters_changed(self._filter_bar.get_rules(), self._filter_bar.get_mode())

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

    def _jump_to_raw_line(self, line: str) -> None:
        doc = self._raw_pane.document()
        block = doc.begin()
        while block != doc.end():
            if block.text() == line:
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                self._raw_pane.setTextCursor(cursor)
                self._raw_pane.setFocus()
                self._raw_pane.ensureCursorVisible()
                rect = self._raw_pane.cursorRect()
                sb = self._raw_pane.verticalScrollBar()
                sb.setValue(sb.value() + rect.center().y() - self._raw_pane.viewport().height() // 2)
                return
            block = block.next()

    def _on_buffer_cap_changed(self, cap: int) -> None:
        self._raw_pane.set_cap(cap)
        self._filtered_pane.set_cap(cap)

    def _on_clear(self):
        self._raw_pane.clear()
        if self._filtered_pane.isVisible():
            self._filtered_pane.clear()
        self._line_count = 0

    def _on_settings_changed(self):
        self._rebuild_raw_pane()
        if self._filtered_pane.isVisible():
            self._rebuild_filtered_pane()

    def _on_filter_action_toggled(self, checked: bool):
        if checked != self._filter_bar.is_input_bar_open():
            self._filter_bar.toggle_input_bar()

    def _on_filter_bar_closed(self):
        self._filter_action.blockSignals(True)
        self._filter_action.setChecked(False)
        self._filter_action.blockSignals(False)

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

    # ------------------------------------------------------------------
    # File viewer
    # ------------------------------------------------------------------

    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Log File", "", "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        from app.ui.file_viewer import FileViewer
        viewer = FileViewer(self._settings, path)
        self._file_viewers.append(viewer)
        viewer.about_to_close.connect(lambda v=viewer: self._on_viewer_closed(v))
        viewer.open_file_requested.connect(self.open_file)
        viewer.show()

    def _on_viewer_closed(self, viewer) -> None:
        if viewer in self._file_viewers:
            self._file_viewers.remove(viewer)

    def closeEvent(self, event):
        self._settings.save_geometry(self.saveGeometry())
        self._settings.save_splitter(self._splitter.saveState())
        self._on_disconnect(prompt_clear=False)
        super().closeEvent(event)


