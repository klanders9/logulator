# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Top-level QMainWindow. Composes SerialPanel, FilterBar, and the display panes."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import filter_engine
from app.theme import apply_palette
from app.colorizer import Colorizer, detect_level
from app.log_writer import LogWriter
from app.serial_worker import SerialWorker
from app.settings import AppSettings
from app.ui.filter_bar import FilterBar
from app.ui.find_bar import FindBar
from app.ui.find_controller import FindController
from app.ui.log_pane import (
    LogPane,
    _fmt,
    _PANE_STYLE,
    _PLAIN_COLOR,
    _DEFAULT_CAP,
    doc_line_count,
    make_pane,
    pane_with_header,
)
from app.ui.minimap import Minimap
from app.ui.send_bar import SendBar
from app.ui.serial_panel import SerialPanel
from app.ui.settings_sidebar import SettingsSidebar


def _reveal_in_file_manager(path: Path) -> None:
    """Show the file selected in Finder / Explorer / the default file manager."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    _instances: list = []

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
        self._auto_reconnect: bool = self._settings.auto_reconnect()
        self._reconnecting: bool = False
        self._reconnect_port: str = ""
        self._reconnect_baud: int = 115200
        self._reconnect_options: dict = {}
        MainWindow._instances.append(self)

        # --- Build UI ---
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(self._settings.font_size())

        self._raw_pane = make_pane(font)
        self._filtered_pane = make_pane(font)
        self._raw_pane.setPlaceholderText(
            "Select a port and press Connect — or drop a .log file here."
        )
        self._filtered_pane.setPlaceholderText("No lines match the active filters.")

        # Minimaps: colored-band overview beside each pane, optional (Settings
        # sidebar), off by default.
        self._minimap = Minimap()
        self._minimap.position_clicked.connect(self._on_minimap_clicked)
        self._filtered_minimap = Minimap()
        self._filtered_minimap.position_clicked.connect(self._on_filtered_minimap_clicked)

        raw_box, self._raw_header = pane_with_header(self._raw_pane, "Raw", self._minimap)
        self._filtered_box, self._filtered_header = pane_with_header(
            self._filtered_pane, "Filtered", self._filtered_minimap
        )
        self._filter_bar = FilterBar()
        self._filtered_box.layout().insertWidget(1, self._filter_bar)
        self._filtered_box.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(raw_box)
        self._splitter.addWidget(self._filtered_box)

        self._serial_panel = SerialPanel(self._settings)
        self._send_bar = SendBar(self._settings)
        self._find_bar = FindBar()
        self._find = FindController(self._find_bar, self._raw_pane, self)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self._serial_panel)
        left_layout.addWidget(self._splitter, stretch=1)
        left_layout.addWidget(self._find_bar)
        left_layout.addWidget(self._send_bar)

        self._sidebar = SettingsSidebar(self._settings)
        self._sidebar.setVisible(self._settings.sidebar_open())
        self._sidebar.settings_changed.connect(self._on_settings_changed)
        self._sidebar.theme_changed.connect(self._on_theme_changed)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        main_layout.addWidget(left, stretch=1)
        main_layout.addWidget(self._sidebar)

        # File menu
        file_menu = self.menuBar().addMenu("File")
        new_win_menu_action = file_menu.addAction("New Window")
        new_win_menu_action.setShortcut(QKeySequence("Ctrl+N"))
        new_win_menu_action.triggered.connect(MainWindow.open_new)
        file_menu.addSeparator()
        open_action = file_menu.addAction("Open Log File…")
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._on_open_file)
        file_menu.addSeparator()
        self._recent_menu = file_menu.addMenu("Recent Files")
        self._rebuild_recent_menu()
        file_menu.aboutToShow.connect(self._rebuild_recent_menu)

        # Help menu
        help_menu = self.menuBar().addMenu("Help")
        about_action = help_menu.addAction("About Logulator")
        about_action.triggered.connect(self._on_about)

        # Toolbar
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        new_win_action = toolbar.addAction("New Window")
        new_win_action.triggered.connect(MainWindow.open_new)
        self._filter_action = toolbar.addAction("▽ Filter")
        self._filter_action.setCheckable(True)
        self._filter_action.setChecked(False)
        self._filter_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self._filter_action.toggled.connect(self._on_filter_action_toggled)
        self._settings_action = toolbar.addAction("⚙  Settings")
        self._settings_action.setCheckable(True)
        self._settings_action.setChecked(self._settings.sidebar_open())
        self._settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self._settings_action.toggled.connect(self._on_sidebar_toggle)

        # Ctrl+F — find in the live raw buffer
        find_action = QAction(self)
        find_action.setShortcut(QKeySequence("Ctrl+F"))
        find_action.triggered.connect(self._find_bar.show_and_focus)
        self.addAction(find_action)

        # Status bar
        self._status_log = _ClickableLabel("Not connected")
        self._status_log.clicked.connect(self._on_status_log_clicked)
        self._status_stats = QLabel("")
        self.statusBar().addWidget(self._status_log)
        self.statusBar().addPermanentWidget(self._status_stats)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_status_bar)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(1000)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

        # Signal wiring
        self._serial_panel.connect_requested.connect(self._on_connect)
        self._serial_panel.disconnect_requested.connect(self._on_disconnect)
        self._serial_panel.clear_requested.connect(self._on_clear)
        self._serial_panel.auto_reconnect_changed.connect(self._on_auto_reconnect_changed)
        self._serial_panel.set_auto_reconnect(self._auto_reconnect)
        self._send_bar.send_requested.connect(self._on_send)
        self._filter_bar.filters_changed.connect(self._on_filters_changed)
        self._filter_bar.input_bar_closed.connect(self._on_filter_bar_closed)
        self._raw_pane.file_dropped.connect(self.open_file)
        self._filtered_pane.file_dropped.connect(self.open_file)
        self._raw_pane.selectionChanged.connect(self._on_raw_pane_selection_changed)
        self._filtered_pane.selectionChanged.connect(self._on_filtered_pane_selection_changed)
        self._filtered_pane.line_double_clicked.connect(self._jump_to_raw_line)
        self._sidebar.buffer_cap_changed.connect(self._on_buffer_cap_changed)
        self._sidebar.font_size_changed.connect(self._on_font_size_changed)
        self._find_bar.filter_to_matches.connect(self._on_filter_to_matches)
        self._raw_pane.verticalScrollBar().valueChanged.connect(self._update_minimap_viewport)
        self._raw_pane.verticalScrollBar().rangeChanged.connect(self._update_minimap_viewport)
        self._filtered_pane.verticalScrollBar().valueChanged.connect(self._update_filtered_minimap_viewport)
        self._filtered_pane.verticalScrollBar().rangeChanged.connect(self._update_filtered_minimap_viewport)

        # Apply persisted buffer cap (overrides _DEFAULT_CAP set in LogPane.__init__)
        initial_cap = self._settings.buffer_cap()
        self._raw_pane.set_cap(initial_cap)
        self._filtered_pane.set_cap(initial_cap)
        self._minimap.set_cap(initial_cap)
        self._filtered_minimap.set_cap(initial_cap)

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
        self._apply_minimap_settings()
        self._update_minimap_viewport()
        self._update_filtered_minimap_viewport()

    # ------------------------------------------------------------------
    # Colorization helpers
    # ------------------------------------------------------------------

    def _minimap_color_for(self, line: str) -> QColor:
        if line.startswith(">> "):
            return QColor(self._settings.tx_color())
        if line.startswith("---"):
            return QColor("#555555")
        level = detect_level(line)
        if level:
            return QColor(self._settings.level_color(level))
        return QColor("#444444")

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

    def _serial_options(self) -> dict:
        s = self._settings
        return {
            "databits": s.serial_databits(),
            "parity": s.serial_parity(),
            "stopbits": s.serial_stopbits(),
            "flow": s.serial_flow(),
            "dtr": s.serial_dtr(),
            "rts": s.serial_rts(),
        }

    def _on_connect(self, port: str, baud: int):
        self._reconnect_port = port
        self._reconnect_baud = baud
        self._reconnect_options = self._serial_options()
        self._log_writer.open_session()
        self._line_count = 0
        self._connect_time = datetime.now()
        path = self._log_writer.current_path
        self._status_log.setText(f"Log: {path.name}" if path else "Log: unknown")

        self._worker = SerialWorker(port, baud, self._log_writer, self._reconnect_options)
        self._worker.new_line.connect(self._on_new_line)
        self._worker.error_occurred.connect(self._on_serial_error)
        self._worker.connected.connect(self._on_reconnected)
        self._worker.start()
        self._serial_panel.set_connected(True)
        self._send_bar.set_connected(True)
        self._set_status_log_clickable(True)
        self._timer.start()

    def _on_disconnect(self, prompt_clear: bool = True):
        self._reconnect_timer.stop()
        self._reconnecting = False
        self._timer.stop()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._log_writer.close()
        self._connect_time = None
        self._serial_panel.set_connected(False)
        self._send_bar.set_connected(False)
        self._set_status_log_clickable(False)
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
        if self._auto_reconnect:
            if self._worker is not None:
                self._worker.stop()
                self._worker = None
            if not self._reconnecting:
                self._reconnecting = True
                self._append_separator("--- disconnected, reconnecting… ---")
            self._serial_panel.set_status("reconnecting")
            self._status_log.setText(f"Reconnecting to {self._reconnect_port}…")
            self._reconnect_timer.start()
        else:
            self._on_disconnect(prompt_clear=False)
            QMessageBox.critical(self, "Serial error", message)

    def _try_reconnect(self):
        self._worker = SerialWorker(
            self._reconnect_port, self._reconnect_baud, self._log_writer,
            self._reconnect_options,
        )
        self._worker.new_line.connect(self._on_new_line)
        self._worker.error_occurred.connect(self._on_serial_error)
        self._worker.connected.connect(self._on_reconnected)
        self._worker.start()

    def _on_reconnected(self):
        if not self._reconnecting:
            return
        self._reconnecting = False
        self._serial_panel.set_status("connected")
        path = self._log_writer.current_path
        self._status_log.setText(f"Log: {path.name}" if path else "Log: unknown")
        self._append_separator("--- reconnected ---")

    def _on_auto_reconnect_changed(self, val: bool):
        self._auto_reconnect = val
        self._settings.set_auto_reconnect(val)
        if not val and self._reconnecting:
            self._on_disconnect(prompt_clear=False)

    def _append_separator(self, text: str):
        sep_fmt = _fmt("#555555")
        self._raw_pane.append_line([(text, sep_fmt)])
        if self._minimap.isVisible():
            self._minimap.append_color(self._minimap_color_for(text))
        if self._filtered_pane.isVisible():
            self._filtered_pane.append_line([(text, sep_fmt)])
            if self._filtered_minimap.isVisible():
                self._filtered_minimap.append_color(self._minimap_color_for(text))

    # ------------------------------------------------------------------
    # Outgoing data
    # ------------------------------------------------------------------

    def _on_send(self, text: str, ending: str):
        # Worker is briefly None between an auto-reconnect drop and the retry.
        if self._worker is None:
            return
        self._worker.send((text + ending).encode("utf-8"))
        # Record TX in the session log with a '>> ' marker so the file
        # captures both directions of the conversation.
        self._log_writer.write(b">> " + text.encode("utf-8") + b"\n")
        echo = ">> " + text
        self._raw_pane.append_line(self._get_segments(echo, "raw"))
        if self._minimap.isVisible():
            self._minimap.append_color(self._minimap_color_for(echo))
        if self._rules and filter_engine.match(echo, self._rules, self._filter_mode):
            self._filtered_pane.append_line(self._get_segments(echo, "filtered"))
            if self._filtered_minimap.isVisible():
                self._filtered_minimap.append_color(self._minimap_color_for(echo))

    # ------------------------------------------------------------------
    # Incoming data
    # ------------------------------------------------------------------

    def _on_new_line(self, line: str):
        self._raw_pane.append_line(self._get_segments(line, "raw"))
        if self._minimap.isVisible():
            self._minimap.append_color(self._minimap_color_for(line))
        self._line_count += 1
        if self._rules and filter_engine.match(line, self._rules, self._filter_mode):
            self._filtered_pane.append_line(self._get_segments(line, "filtered"))
            if self._filtered_minimap.isVisible():
                self._filtered_minimap.append_color(self._minimap_color_for(line))

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _on_filters_changed(self, rules: list, mode: str):
        self._rules = rules
        self._filter_mode = mode
        self._update_filtered_visibility()
        if rules:
            self._rebuild_filtered_pane()
        else:
            self._filtered_pane.clear()
            self._filtered_minimap.clear()
            self._update_pane_headers()

    def _ensure_filtered_box_visible(self):
        if not self._splitter_initialized:
            self._splitter_initialized = True
            h = self._splitter.height()
            if h > 0:
                self._splitter.setSizes([int(h * 0.6), int(h * 0.4)])
        self._filtered_box.show()

    def _update_filtered_visibility(self):
        # The filter bar's input row now lives above the filtered pane, so the
        # container must stay visible while it's open even before any rule
        # exists — otherwise there's no way to reach it to add the first rule.
        show = bool(self._rules) or self._filter_bar.is_input_bar_open()
        if show:
            self._ensure_filtered_box_visible()
        else:
            self._filtered_box.hide()
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
        self._update_pane_headers()
        if self._filtered_minimap.isVisible():
            self._rebuild_filtered_minimap()

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
        if self._minimap.isVisible():
            self._rebuild_raw_minimap()

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
        self._minimap.set_cap(cap)
        self._filtered_minimap.set_cap(cap)

    def _on_clear(self):
        self._raw_pane.clear()
        self._minimap.clear()
        if self._filtered_pane.isVisible():
            self._filtered_pane.clear()
            self._filtered_minimap.clear()
        self._line_count = 0
        self._update_pane_headers()

    def _update_minimap_viewport(self, *_args) -> None:
        sb = self._raw_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        if total <= 0:
            self._minimap.set_viewport(0.0, 1.0)
            return
        self._minimap.set_viewport(sb.value() / total, (sb.value() + sb.pageStep()) / total)

    def _on_minimap_clicked(self, frac: float) -> None:
        sb = self._raw_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        target = int(frac * total - sb.pageStep() / 2)
        sb.setValue(max(0, min(sb.maximum(), target)))

    def _update_filtered_minimap_viewport(self, *_args) -> None:
        sb = self._filtered_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        if total <= 0:
            self._filtered_minimap.set_viewport(0.0, 1.0)
            return
        self._filtered_minimap.set_viewport(sb.value() / total, (sb.value() + sb.pageStep()) / total)

    def _on_filtered_minimap_clicked(self, frac: float) -> None:
        sb = self._filtered_pane.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        target = int(frac * total - sb.pageStep() / 2)
        sb.setValue(max(0, min(sb.maximum(), target)))

    def _rebuild_raw_minimap(self) -> None:
        doc = self._raw_pane.document()
        colors = []
        if not (doc.blockCount() == 1 and doc.firstBlock().text() == ""):
            block = doc.begin()
            while block != doc.end():
                colors.append(self._minimap_color_for(block.text()))
                block = block.next()
        self._minimap.set_colors(colors)

    def _rebuild_filtered_minimap(self) -> None:
        doc = self._filtered_pane.document()
        colors = []
        if not (doc.blockCount() == 1 and doc.firstBlock().text() == ""):
            block = doc.begin()
            while block != doc.end():
                colors.append(self._minimap_color_for(block.text()))
                block = block.next()
        self._filtered_minimap.set_colors(colors)

    def _apply_minimap_settings(self) -> None:
        enabled = self._settings.minimap_enabled()
        apply_to = self._settings.minimap_apply_to()
        show_raw = enabled and apply_to in ("all", "raw")
        show_filtered = enabled and apply_to in ("all", "filtered")
        self._minimap.setVisible(show_raw)
        self._filtered_minimap.setVisible(show_filtered)
        if show_raw:
            self._rebuild_raw_minimap()
        else:
            self._minimap.clear()
        if show_filtered:
            self._rebuild_filtered_minimap()
        else:
            self._filtered_minimap.clear()

    def _update_pane_headers(self):
        if self._filtered_box.isVisible():
            n = doc_line_count(self._filtered_pane)
            m = doc_line_count(self._raw_pane)
            self._filtered_header.setText(f"Filtered — {n:,} of {m:,} lines")

    def _on_filter_to_matches(self, text: str) -> None:
        self._filter_bar.add_rule(text, "substring", "include")

    def _set_status_log_clickable(self, clickable: bool) -> None:
        if clickable:
            self._status_log.setCursor(Qt.CursorShape.PointingHandCursor)
            self._status_log.setToolTip("Click to reveal the log file")
        else:
            self._status_log.unsetCursor()
            self._status_log.setToolTip("")

    def _on_status_log_clicked(self) -> None:
        path = self._log_writer.current_path
        if path and path.exists():
            _reveal_in_file_manager(path)

    def _on_settings_changed(self):
        self._rebuild_raw_pane()
        if self._filtered_pane.isVisible():
            self._rebuild_filtered_pane()
        self._apply_minimap_settings()

    def _on_theme_changed(self, theme: str):
        apply_palette(QApplication.instance(), theme)

    def _on_filter_action_toggled(self, checked: bool):
        if checked:
            # Show the container before opening the row so it can take focus.
            self._ensure_filtered_box_visible()
        if checked != self._filter_bar.is_input_bar_open():
            self._filter_bar.toggle_input_bar()
        if not checked:
            self._update_filtered_visibility()

    def _on_filter_bar_closed(self):
        self._filter_action.blockSignals(True)
        self._filter_action.setChecked(False)
        self._filter_action.blockSignals(False)
        self._update_filtered_visibility()

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
        self._update_pane_headers()
        self._update_minimap_viewport()
        self._update_filtered_minimap_viewport()

    # ------------------------------------------------------------------
    # File viewer
    # ------------------------------------------------------------------

    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Log File", "", "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.open_file(Path(path))

    def _on_about(self) -> None:
        from app.ui.about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        paths = self._settings.recent_files()
        if not paths:
            no_action = self._recent_menu.addAction("(none)")
            no_action.setEnabled(False)
            return
        for p in paths:
            path = Path(p)
            action = QAction(str(path), self)
            if not path.exists():
                action.setEnabled(False)
            else:
                action.triggered.connect(lambda checked=False, fp=path: self.open_file(fp))
            self._recent_menu.addAction(action)

    def open_file(self, path: Path) -> None:
        from app.ui.file_viewer import FileViewer
        self._settings.add_recent_file(path)
        self._rebuild_recent_menu()
        viewer = FileViewer(self._settings, path)
        self._file_viewers.append(viewer)
        viewer.about_to_close.connect(lambda v=viewer: self._on_viewer_closed(v))
        viewer.show()

    @classmethod
    def open_new(cls) -> None:
        w = cls()
        w.show()

    def _on_viewer_closed(self, viewer) -> None:
        if viewer in self._file_viewers:
            self._file_viewers.remove(viewer)

    def closeEvent(self, event):
        self._settings.save_geometry(self.saveGeometry())
        self._settings.save_splitter(self._splitter.saveState())
        self._on_disconnect(prompt_clear=False)
        if self in MainWindow._instances:
            MainWindow._instances.remove(self)
        super().closeEvent(event)


