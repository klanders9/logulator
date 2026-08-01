# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Top-level QMainWindow for a live serial session.

Adds the serial panel, send bar, status bar and settings sidebar on top of the
shared pane/filter/minimap behaviour in `LogWindowMixin`."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.log_writer import LogWriter
from app.serial_worker import SerialWorker
from app.settings import AppSettings
from app.theme import active_colors
from app.ui.find_bar import FindBar
from app.ui.find_controller import FindController
from app.ui.log_pane import _fmt
from app.ui.log_window import LogWindowMixin
from app.ui.send_bar import SendBar
from app.ui.serial_panel import SerialPanel
from app.ui.settings_sidebar import SettingsSidebar


# Shown in the raw pane while it is empty *and* no session is running. Qt
# shows a placeholder whenever the document is empty, which during a live
# session means it sits there telling the user to press Connect until the
# first byte happens to arrive. _on_connect clears it and _on_disconnect puts
# it back, so it only ever appears when it is actually the next thing to do.
_RAW_PANE_HINT = "Select a port and press Connect — or drop a .log file here."


def _reveal_in_file_manager(path: Path) -> None:
    """Show the file selected in Finder / Explorer / the default file manager."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        # Explorer wants "/select," and the path as a single argument. Passing
        # them separately makes it ignore both and open Documents instead.
        # The path needs native separators too.
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        # No portable "select this file" equivalent, so open the folder.
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(LogWindowMixin, QMainWindow):
    _instances: list = []

    def __init__(self):
        super().__init__()
        self.setWindowTitle("logulator")
        self.resize(1200, 720)

        self._init_log_window(AppSettings())

        self._worker: Optional[SerialWorker] = None
        self._log_writer = LogWriter()
        self._line_count = 0
        self._connect_time: Optional[datetime] = None
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

        self._build_log_panes(
            font,
            cap=self._settings.buffer_cap(),
            raw_placeholder=_RAW_PANE_HINT,
            filtered_placeholder="No lines match the active filters.",
        )

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
        self._send_bar.control_requested.connect(self._on_control)
        self._sidebar.buffer_cap_changed.connect(self._on_buffer_cap_changed)
        self._sidebar.font_size_changed.connect(self._on_font_size_changed)
        self._find_bar.filter_to_matches.connect(self._on_filter_to_matches)

        # Restore geometry
        geometry = self._settings.load_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.load_splitter()
        if splitter_state:
            self._splitter.restoreState(splitter_state)
            self._splitter_initialized = True

        # Establish the initial (empty) filter state.
        self._on_filters_changed(self._filter_bar.get_rules(), self._filter_bar.get_mode())
        self._apply_minimap_settings()
        self._update_minimap_viewport()
        self._update_filtered_minimap_viewport()

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

        # Pick up any log-directory change made since the last session, and
        # refuse to connect if we cannot record the session: the log file is
        # the source of truth, so a silent unlogged session is worse than none.
        log_dir = self._settings.log_dir()
        self._log_writer.set_log_dir(log_dir)
        # Read off the panel rather than settings so each window keeps its own
        # prefix; settings only supplies the value the field starts out with.
        self._log_writer.set_prefix(self._serial_panel.log_prefix())
        try:
            self._log_writer.open_session()
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Cannot open log file",
                f"Could not start a session log in:\n{log_dir}\n\n{exc}\n\n"
                "Pick a different log directory under Settings → Logging.",
            )
            return

        self._line_count = 0
        self._connect_time = datetime.now()
        path = self._log_writer.current_path
        self._status_log.setText(f"Log: {path.name}" if path else "Log: unknown")
        # The session has started; "press Connect" is no longer the next step,
        # even though no bytes have arrived to fill the pane yet.
        self._raw_pane.setPlaceholderText("")

        self._worker = SerialWorker(port, baud, self._log_writer, self._reconnect_options)
        self._worker.new_line.connect(self._on_new_line)
        self._worker.partial_line.connect(self._on_partial_line)
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
        # Whatever tail was showing stays on screen — it is real received data
        # and it is in the log — but it is no longer provisional, so a later
        # session must not overwrite it.
        self._pending_partial = False
        self._connect_time = None
        self._serial_panel.set_connected(False)
        self._send_bar.set_connected(False)
        self._set_status_log_clickable(False)
        self._status_log.setText("Not connected")
        self._status_stats.setText("")
        self._raw_pane.setPlaceholderText(_RAW_PANE_HINT)

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
        self._worker.partial_line.connect(self._on_partial_line)
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
        # A provisional tail from before the drop is superseded by the event.
        self._drop_pending_partial()
        sep_fmt = _fmt(active_colors()["separator"])
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
        # A bare Enter still nudges the target, but by default it leaves no
        # trace: an empty '>> ' marker carries no information and the send
        # field holds focus, so stray Enters would litter the pane and log.
        if text or self._settings.tx_echo_empty():
            self._record_tx(text)

    def _on_control(self, data: bytes, mnemonic: str):
        """Send a raw control byte, e.g. ^C to interrupt the target.

        No line ending: an interrupt is the byte on its own.
        """
        if self._worker is None:
            return
        self._worker.send(data)
        # Logged and echoed in caret notation rather than as the raw byte,
        # which would be invisible in the pane and in the saved log.
        self._record_tx(mnemonic)

    def _record_tx(self, text: str) -> None:
        """Log and echo one transmitted line with the '>> ' marker, so the
        session file captures both directions of the conversation."""
        self._log_writer.write_tx_line(text)
        self._append_display_line(">> " + text)

    # ------------------------------------------------------------------
    # Incoming data
    # ------------------------------------------------------------------

    def _on_new_line(self, line: str):
        self._append_display_line(line)
        self._line_count += 1

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

    # ------------------------------------------------------------------
    # UI controls
    # ------------------------------------------------------------------

    def _on_buffer_cap_changed(self, cap: int) -> None:
        # Serial windows only — file viewers keep their own _FILE_PANE_CAP.
        for window in MainWindow._instances:
            window._apply_buffer_cap(cap)

    def _apply_buffer_cap(self, cap: int) -> None:
        self._raw_pane.set_cap(cap)
        self._filtered_pane.set_cap(cap)
        self._minimap.set_cap(cap)
        self._filtered_minimap.set_cap(cap)

    def _on_clear(self):
        self._pending_partial = False
        self._raw_pane.clear()
        self._minimap.clear()
        if self._filtered_pane.isVisible():
            self._filtered_pane.clear()
            self._filtered_minimap.clear()
        self._line_count = 0
        self._update_pane_headers()

    def _on_filter_to_matches(self, text: str) -> None:
        # Case-insensitive to mirror QTextDocument.find, so the filtered pane
        # holds exactly the lines the find counter just reported.
        self._filter_bar.add_rule(text, "substring", "include", ignore_case=True)

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

    def _on_sidebar_toggle(self, checked: bool):
        self._sidebar.setVisible(checked)
        self._settings.set_sidebar_open(checked)

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
        self._release_log_window()
        if self in MainWindow._instances:
            MainWindow._instances.remove(self)
        super().closeEvent(event)
