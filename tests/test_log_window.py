# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Integration tests for LogWindowMixin, driven through both real windows.

MainWindow and FileViewer share their pane, filter, colorization and minimap
behaviour. These tests exercise that shared surface from each side so a change
to the mixin cannot silently break one window while the other still works.
"""

import pytest

from app.main_window import MainWindow
from app.ui.file_viewer import FileViewer
from app.ui.log_pane import doc_line_count
from app.ui.log_window import iter_block_texts

ZEPHYR_LINES = [
    "[00:00:01.000,000] <inf> net_if: interface up",
    "[00:00:02.000,000] <err> net_if: send failed: -5",
    "[00:00:03.000,000] <dbg> shell: prompt ready",
    "[00:00:04.000,000] <err> modem: no carrier",
]


@pytest.fixture(autouse=True)
def _clean_settings(clear_settings):
    clear_settings()


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    # Shown (offscreen) because several behaviours are gated on isVisible(),
    # which stays False while any ancestor window is hidden.
    w.show()
    yield w
    w.close()


@pytest.fixture
def log_file(tmp_path):
    p = tmp_path / "session.log"
    p.write_text("\n".join(ZEPHYR_LINES) + "\n")
    return p


@pytest.fixture
def viewer(qtbot, log_file, win):
    v = FileViewer(win._settings, log_file)
    qtbot.addWidget(v)
    v.show()
    with qtbot.waitSignal(v._worker.load_complete, timeout=5000):
        pass
    yield v
    v.close()


def raw_texts(window):
    return list(iter_block_texts(window._raw_pane.document()))


def filtered_texts(window):
    return list(iter_block_texts(window._filtered_pane.document()))


def feed(win, *lines):
    for line in lines:
        win._on_new_line(line)


class TestSharedSetup:
    def test_main_window_builds_the_shared_widgets(self, win):
        for attr in ("_raw_pane", "_filtered_pane", "_minimap", "_filtered_minimap",
                     "_filtered_box", "_filtered_header", "_filter_bar", "_splitter"):
            assert getattr(win, attr) is not None, attr

    def test_file_viewer_builds_the_same_widgets(self, viewer):
        for attr in ("_raw_pane", "_filtered_pane", "_minimap", "_filtered_minimap",
                     "_filtered_box", "_filtered_header", "_filter_bar", "_splitter"):
            assert getattr(viewer, attr) is not None, attr

    def test_filtered_box_starts_hidden(self, win):
        assert not win._filtered_box.isVisible()

    def test_main_window_honours_the_persisted_buffer_cap(self, qtbot, settings_store):
        settings_store.setValue("buffer/cap", 5_000)
        settings_store.sync()
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._raw_pane._cap == 5_000
        assert w._minimap._cap == 5_000
        w.close()

    def test_file_viewer_uses_its_own_large_cap(self, viewer):
        from app.ui.file_viewer import _FILE_PANE_CAP

        assert viewer._raw_pane._cap == _FILE_PANE_CAP


class TestFiltering:
    def test_rule_reveals_filtered_pane_and_selects_lines(self, win):
        feed(win, *ZEPHYR_LINES)
        win._filter_bar.add_rule("err", "level", "include")
        assert win._filtered_box.isVisible()
        assert filtered_texts(win) == [ZEPHYR_LINES[1], ZEPHYR_LINES[3]]

    def test_removing_the_last_rule_clears_and_hides(self, win):
        feed(win, *ZEPHYR_LINES)
        win._filter_bar.add_rule("err", "level", "include")
        win._filter_bar._remove_rule(0)
        assert not win._filtered_box.isVisible()
        assert doc_line_count(win._filtered_pane) == 0

    def test_new_lines_append_to_both_panes(self, win):
        win._filter_bar.add_rule("net_if", "module", "include")
        feed(win, *ZEPHYR_LINES)
        assert len(raw_texts(win)) == 4
        assert filtered_texts(win) == ZEPHYR_LINES[:2]

    def test_exclude_rule(self, win):
        feed(win, *ZEPHYR_LINES)
        win._filter_bar.add_rule("net_if", "module", "exclude")
        assert filtered_texts(win) == [ZEPHYR_LINES[2], ZEPHYR_LINES[3]]

    def test_header_reports_counts(self, win):
        feed(win, *ZEPHYR_LINES)
        win._filter_bar.add_rule("err", "level", "include")
        assert win._filtered_header.text() == "Filtered — 2 of 4 lines"

    def test_file_viewer_filters_the_loaded_file(self, viewer):
        viewer._filter_bar.add_rule("err", "level", "include")
        assert filtered_texts(viewer) == [ZEPHYR_LINES[1], ZEPHYR_LINES[3]]


class TestRebuilds:
    def test_raw_rebuild_preserves_text(self, win):
        feed(win, *ZEPHYR_LINES)
        win._rebuild_raw_pane()
        assert raw_texts(win) == ZEPHYR_LINES

    def test_settings_change_rebuilds_without_losing_lines(self, win):
        feed(win, *ZEPHYR_LINES)
        win._filter_bar.add_rule("err", "level", "include")
        win._settings.set_color_mode("syntax")
        win._on_settings_changed()
        assert raw_texts(win) == ZEPHYR_LINES
        assert filtered_texts(win) == [ZEPHYR_LINES[1], ZEPHYR_LINES[3]]

    def test_rebuild_on_an_empty_pane_stays_empty(self, win):
        win._rebuild_raw_pane()
        assert doc_line_count(win._raw_pane) == 0


class TestColorizationRouting:
    def test_disabled_colorization_is_plain(self, win):
        win._settings.set_color_enabled(False)
        segs = win._get_segments(ZEPHYR_LINES[1], "raw")
        assert len(segs) == 1
        assert segs[0][1] is win._plain_fmt

    def test_apply_to_raw_leaves_filtered_plain(self, win):
        win._settings.set_color_enabled(True)
        win._settings.set_color_apply_to("raw")
        assert win._get_segments(ZEPHYR_LINES[1], "filtered")[0][1] is win._plain_fmt
        assert win._get_segments(ZEPHYR_LINES[1], "raw")[0][1] is not win._plain_fmt

    def test_apply_to_none_is_plain_everywhere(self, win):
        win._settings.set_color_apply_to("none")
        for pane in ("raw", "filtered"):
            assert win._get_segments(ZEPHYR_LINES[1], pane)[0][1] is win._plain_fmt


class TestMinimap:
    def test_hidden_by_default(self, win):
        assert not win._minimap.isVisible()

    def test_enabling_backfills_from_the_existing_document(self, win):
        feed(win, *ZEPHYR_LINES)
        win._settings.set_minimap_enabled(True)
        win._settings.set_minimap_apply_to("all")
        win._apply_minimap_settings()
        assert len(win._minimap._colors) == 4

    def test_empty_pane_backfills_to_no_bands(self, win):
        """An empty QTextDocument reports blockCount() == 1; that must not
        become one phantom band."""
        win._settings.set_minimap_enabled(True)
        win._apply_minimap_settings()
        assert win._minimap._colors == []

    def test_disabling_clears_the_bands(self, win):
        feed(win, *ZEPHYR_LINES)
        win._settings.set_minimap_enabled(True)
        win._apply_minimap_settings()
        win._settings.set_minimap_enabled(False)
        win._apply_minimap_settings()
        assert win._minimap._colors == []

    def test_apply_to_raw_only(self, win):
        win._settings.set_minimap_enabled(True)
        win._settings.set_minimap_apply_to("raw")
        win._apply_minimap_settings()
        assert win._minimap.isVisible()
        assert not win._filtered_minimap.isVisible()

    def test_band_color_follows_severity(self, win):
        assert win._minimap_color_for(ZEPHYR_LINES[1]).name() == \
            win._settings.level_color("err")

    def test_tx_and_separator_bands(self, win):
        assert win._minimap_color_for(">> reboot").name() == win._settings.tx_color()
        assert win._minimap_color_for("--- reconnected ---").name() == "#555555"

    def test_unleveled_line_gets_the_neutral_band(self, win):
        assert win._minimap_color_for("nothing notable").name() == "#444444"


class TestSelectionAndJump:
    def test_jump_selects_the_matching_raw_line(self, win):
        feed(win, *ZEPHYR_LINES)
        win._jump_to_raw_line(ZEPHYR_LINES[2])
        assert win._raw_pane.textCursor().selectedText() == ZEPHYR_LINES[2]

    def test_jump_to_absent_line_is_a_no_op(self, win):
        feed(win, *ZEPHYR_LINES)
        win._jump_to_raw_line("never logged")
        assert not win._raw_pane.textCursor().hasSelection()

    def test_selecting_in_one_pane_clears_the_other(self, win):
        feed(win, *ZEPHYR_LINES)
        win._filter_bar.add_rule("err", "level", "include")

        cursor = win._filtered_pane.textCursor()
        cursor.select(cursor.SelectionType.Document)
        win._filtered_pane.setTextCursor(cursor)
        assert win._filtered_pane.textCursor().hasSelection()

        cursor = win._raw_pane.textCursor()
        cursor.select(cursor.SelectionType.Document)
        win._raw_pane.setTextCursor(cursor)

        assert win._raw_pane.textCursor().hasSelection()
        assert not win._filtered_pane.textCursor().hasSelection()


class TestFileViewerLoading:
    def test_loads_every_line(self, viewer):
        assert raw_texts(viewer) == ZEPHYR_LINES
        assert viewer._total_lines == 4

    def test_status_bar_reports_the_file(self, viewer, log_file):
        assert log_file.name in viewer._status_label.text()
        assert "4 lines" in viewer._status_label.text()


class TestConnectRefusesWithoutALog:
    """The log file is the source of truth, so an unloggable session is refused."""

    def test_unwritable_log_dir_aborts_the_connection(self, win, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        blocked = tmp_path / "blocked"
        blocked.mkdir()
        blocked.chmod(0o500)
        win._settings.set_log_dir(str(blocked / "logs"))

        shown = []
        monkeypatch.setattr(
            QMessageBox, "critical", lambda *a, **k: shown.append(a[2])
        )
        try:
            win._on_connect("/dev/nonexistent", 115200)
        finally:
            blocked.chmod(0o700)

        assert shown, "user must be told the session log could not be opened"
        assert win._worker is None, "no serial worker may start without a log"
        assert win._connect_time is None

    def test_log_dir_setting_is_picked_up_at_connect(self, win, tmp_path, monkeypatch):
        """A directory chosen mid-session applies to the next connect."""
        from app import main_window as mw

        target = tmp_path / "chosen"
        win._settings.set_log_dir(str(target))
        monkeypatch.setattr(mw, "SerialWorker", lambda *a, **k: _StubWorker())

        win._on_connect("/dev/nonexistent", 115200)
        try:
            assert win._log_writer.current_path.parent == target
        finally:
            win._on_disconnect(prompt_clear=False)


class _StubWorker:
    """Stands in for SerialWorker so no real port is touched."""

    class _Sig:
        def connect(self, *_a, **_k):
            pass

    new_line = _Sig()
    partial_line = _Sig()
    error_occurred = _Sig()
    connected = _Sig()

    def __init__(self):
        self.sent = []
        self.stopped = False

    def send(self, data):
        self.sent.append(data)

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class TestSettingsReachEveryWindow:
    """All windows share one AppSettings, so a change must refresh them all."""

    def test_colorization_change_rebuilds_other_windows(self, win, qtbot):
        other = MainWindow()
        qtbot.addWidget(other)
        other.show()
        try:
            for w in (win, other):
                feed(w, *ZEPHYR_LINES)
            win._settings.set_color_enabled(False)
            win._on_settings_changed()

            # A plain rebuild leaves one segment per line; verify via the text
            # surviving intact in both.
            assert raw_texts(win) == ZEPHYR_LINES
            assert raw_texts(other) == ZEPHYR_LINES
            assert other._get_segments(ZEPHYR_LINES[0], "raw")[0][1] is other._plain_fmt
        finally:
            other.close()

    def test_minimap_toggle_reaches_other_windows(self, win, qtbot):
        other = MainWindow()
        qtbot.addWidget(other)
        other.show()
        try:
            feed(other, *ZEPHYR_LINES)
            assert not other._minimap.isVisible()
            win._settings.set_minimap_enabled(True)
            win._settings.set_minimap_apply_to("raw")
            win._on_settings_changed()
            assert other._minimap.isVisible()
            assert len(other._minimap._colors) == 4
        finally:
            other.close()

    def test_font_size_reaches_other_windows(self, win, qtbot):
        other = MainWindow()
        qtbot.addWidget(other)
        other.show()
        try:
            win._on_font_size_changed(20)
            assert other._raw_pane.font().pointSize() == 20
            assert other._filtered_pane.font().pointSize() == 20
        finally:
            other.close()

    def test_buffer_cap_reaches_other_serial_windows(self, win, qtbot):
        other = MainWindow()
        qtbot.addWidget(other)
        other.show()
        try:
            win._on_buffer_cap_changed(2_500)
            assert other._raw_pane._cap == 2_500
            assert other._minimap._cap == 2_500
        finally:
            other.close()

    def test_buffer_cap_leaves_file_viewers_alone(self, win, viewer):
        """File viewers use _FILE_PANE_CAP; the serial cap must not shrink them."""
        from app.ui.file_viewer import _FILE_PANE_CAP

        win._on_buffer_cap_changed(2_500)
        assert viewer._raw_pane._cap == _FILE_PANE_CAP

    def test_settings_change_reaches_file_viewers(self, win, viewer):
        win._settings.set_minimap_enabled(True)
        win._settings.set_minimap_apply_to("raw")
        win._on_settings_changed()
        assert viewer._minimap.isVisible()

    def test_closed_windows_stop_receiving_updates(self, win, qtbot):
        from app.ui.log_window import open_log_windows

        other = MainWindow()
        qtbot.addWidget(other)
        other.show()
        assert other in open_log_windows()
        other.close()
        assert other not in open_log_windows()
        # Must not raise against the closed window.
        win._on_settings_changed()


class TestControlCharacterTx:
    """Ctrl+C must reach the port as a bare 0x03, and stay readable in the log."""

    def test_control_byte_reaches_the_worker(self, win, monkeypatch, tmp_path):
        from app import main_window as mw

        sent = []

        class Worker(_StubWorker):
            def send(self, data):
                sent.append(data)

        win._settings.set_log_dir(str(tmp_path / "logs"))
        monkeypatch.setattr(mw, "SerialWorker", lambda *a, **k: Worker())
        win._on_connect("/dev/nonexistent", 115200)
        try:
            win._on_control(b"\x03", "^C")
            assert sent == [b"\x03"], "no line ending may be appended"
        finally:
            win._on_disconnect(prompt_clear=False)

    def test_control_byte_is_echoed_in_caret_notation(self, win, monkeypatch, tmp_path):
        from app import main_window as mw

        win._settings.set_log_dir(str(tmp_path / "logs"))
        monkeypatch.setattr(mw, "SerialWorker", lambda *a, **k: _StubWorker())
        win._on_connect("/dev/nonexistent", 115200)
        try:
            log_path = win._log_writer.current_path
            win._on_control(b"\x03", "^C")
            assert raw_texts(win)[-1] == ">> ^C"
        finally:
            win._on_disconnect(prompt_clear=False)
        # The saved log shows the mnemonic, not an invisible raw byte.
        assert log_path.read_bytes() == b">> ^C\n"

    def test_control_byte_is_ignored_while_disconnected(self, win):
        """Worker is briefly None during an auto-reconnect gap."""
        assert win._worker is None
        win._on_control(b"\x03", "^C")  # must not raise
        assert doc_line_count(win._raw_pane) == 0


class TestEmptySendEcho:
    """A bare Enter must always transmit; only the echo is configurable."""

    def _connect(self, win, monkeypatch, tmp_path):
        from app import main_window as mw

        worker = _StubWorker()
        win._settings.set_log_dir(str(tmp_path / "logs"))
        monkeypatch.setattr(mw, "SerialWorker", lambda *a, **k: worker)
        win._on_connect("/dev/nonexistent", 115200)
        return worker

    def test_line_ending_is_sent_even_when_not_echoed(self, win, monkeypatch, tmp_path):
        worker = self._connect(win, monkeypatch, tmp_path)
        try:
            win._on_send("", "\r\n")
            assert worker.sent == [b"\r\n"], "the nudge must still reach the target"
        finally:
            win._on_disconnect(prompt_clear=False)

    def test_blank_send_is_not_echoed_by_default(self, win, monkeypatch, tmp_path):
        self._connect(win, monkeypatch, tmp_path)
        try:
            log_path = win._log_writer.current_path
            win._on_send("", "\r\n")
            assert doc_line_count(win._raw_pane) == 0
        finally:
            win._on_disconnect(prompt_clear=False)
        assert log_path.read_bytes() == b""

    def test_blank_send_is_echoed_when_enabled(self, win, monkeypatch, tmp_path):
        self._connect(win, monkeypatch, tmp_path)
        win._settings.set_tx_echo_empty(True)
        try:
            log_path = win._log_writer.current_path
            win._on_send("", "\r\n")
            assert raw_texts(win) == [">> "]
        finally:
            win._on_disconnect(prompt_clear=False)
        assert log_path.read_bytes() == b">> \n"

    def test_real_commands_are_always_echoed(self, win, monkeypatch, tmp_path):
        self._connect(win, monkeypatch, tmp_path)
        try:
            win._on_send("help", "\r\n")
            assert raw_texts(win) == [">> help"]
        finally:
            win._on_disconnect(prompt_clear=False)

    def test_whitespace_only_send_still_counts_as_content(self, win, monkeypatch, tmp_path):
        """A space is a deliberate keystroke, not a reflexive Enter."""
        self._connect(win, monkeypatch, tmp_path)
        try:
            win._on_send(" ", "\r\n")
            assert raw_texts(win) == [">>  "]
        finally:
            win._on_disconnect(prompt_clear=False)

    def test_control_bytes_are_echoed_regardless(self, win, monkeypatch, tmp_path):
        """^C is never blank, so the setting must not suppress it."""
        self._connect(win, monkeypatch, tmp_path)
        try:
            win._on_control(b"\x03", "^C")
            assert raw_texts(win) == [">> ^C"]
        finally:
            win._on_disconnect(prompt_clear=False)


ANSI_ERR = "\x1b[1;31m[00:00:05.000,000] <err> modem: init failed: -5\x1b[0m"
ANSI_TAG = "[00:00:06.000,000] \x1b[1;33m<wrn>\x1b[0m modem: retrying"
ANSI_SHELL = "\x1b[2J\x1b[Huart:~$ \x1b[Kkernel version"
PLAIN_WRN = "[00:00:09.000,000] <wrn> app: plain warning"


def block_runs(pane, index):
    """(text, colour, is_ansi_tagged) for each format run of one block."""
    from app.ui.log_pane import ANSI_PROPERTY

    block = pane.document().findBlockByNumber(index)
    runs = []
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid():
            fmt = fragment.charFormat()
            runs.append(
                (
                    fragment.text(),
                    fmt.foreground().color().name(),
                    bool(fmt.property(ANSI_PROPERTY)),
                )
            )
        it += 1
    return runs


class TestAnsiEscapeHandling:
    """Escape sequences are a display concern; the log keeps the bytes."""

    def test_stripped_by_default(self, win):
        assert win._settings.ansi_mode() == "strip"
        feed(win, ANSI_ERR, ANSI_TAG, ANSI_SHELL)
        assert raw_texts(win) == [
            "[00:00:05.000,000] <err> modem: init failed: -5",
            "[00:00:06.000,000] <wrn> modem: retrying",
            "uart:~$ kernel version",
        ]

    def test_stripping_restores_colorization(self, win):
        """A leading colour code otherwise disables the anchored Zephyr regex."""
        win._settings.set_color_mode("syntax")
        feed(win, ANSI_ERR)
        # Timestamp / level / module / message rather than one plain run.
        assert len(block_runs(win._raw_pane, 0)) == 4

    def test_stripping_restores_module_filtering(self, win):
        win._rules = [{"type": "module", "value": "modem", "mode": "include"}]
        win._filter_mode = "OR"
        win._filtered_box.show()
        feed(win, ANSI_TAG, "[00:00:07.000,000] <inf> net_if: unrelated")
        assert filtered_texts(win) == ["[00:00:06.000,000] <wrn> modem: retrying"]

    def test_render_mode_uses_the_wire_colour(self, win):
        win._settings.set_ansi_mode("render")
        feed(win, ANSI_TAG)
        runs = block_runs(win._raw_pane, 0)
        assert [text for text, _, _ in runs] == [
            "[00:00:06.000,000] ",
            "<wrn>",
            " modem: retrying",
        ]
        # The firmware's yellow, not AppSettings.level_color('wrn').
        assert runs[1][1] == "#f1fa8c"
        assert runs[1][1] != win._settings.level_color("wrn")

    def test_render_mode_leaves_uncoloured_lines_to_the_colorizer(self, win):
        """Mixed output is normal — a bootloader prints plain, the app colours."""
        win._settings.set_ansi_mode("render")
        feed(win, "[00:00:08.000,000] <err> app: plain error")
        text, color, is_ansi = block_runs(win._raw_pane, 0)[0]
        assert is_ansi is False
        assert color == win._settings.level_color("err")

    def test_render_mode_survives_a_rebuild(self, win):
        """The escapes are gone from the document, so a rebuild would otherwise
        silently repaint these lines with the colorizer's palette."""
        win._settings.set_ansi_mode("render")
        feed(win, ANSI_TAG)
        before = block_runs(win._raw_pane, 0)
        win._apply_display_settings()
        assert block_runs(win._raw_pane, 0) == before

    def test_leaving_render_mode_releases_lines_to_the_colorizer(self, win):
        win._settings.set_ansi_mode("render")
        feed(win, ANSI_TAG)
        win._settings.set_ansi_mode("strip")
        win._apply_display_settings()
        runs = block_runs(win._raw_pane, 0)
        assert len(runs) == 1
        assert runs[0][2] is False
        assert runs[0][1] == win._settings.level_color("wrn")

    def test_off_mode_shows_the_escapes(self, win):
        win._settings.set_ansi_mode("off")
        feed(win, ANSI_TAG)
        assert raw_texts(win) == [ANSI_TAG]

    def test_turning_stripping_on_cleans_existing_lines(self, win):
        win._settings.set_ansi_mode("off")
        feed(win, ANSI_TAG)
        win._settings.set_ansi_mode("strip")
        win._apply_display_settings()
        assert raw_texts(win) == ["[00:00:06.000,000] <wrn> modem: retrying"]

    def test_minimap_tracks_the_cleaned_line(self, win):
        """Severity has to be read off the same text the pane shows."""
        win._settings.set_minimap_enabled(True)
        win._settings.set_minimap_apply_to("raw")
        win._apply_minimap_settings()
        feed(win, ANSI_ERR)
        assert win._minimap._colors[-1].name() == win._settings.level_color("err")

    def test_the_session_log_keeps_the_escapes(self, win, monkeypatch, tmp_path):
        """Non-negotiable: the file records what arrived, not what was shown."""
        from app import main_window as mw

        win._settings.set_log_dir(str(tmp_path / "logs"))
        monkeypatch.setattr(mw, "SerialWorker", lambda *a, **k: _StubWorker())
        win._on_connect("/dev/nonexistent", 115200)
        log_path = win._log_writer.current_path
        try:
            win._log_writer.write(ANSI_ERR.encode() + b"\n")
            win._on_new_line(ANSI_ERR)
        finally:
            win._on_disconnect(prompt_clear=False)
        assert log_path.read_bytes() == ANSI_ERR.encode() + b"\n"
        assert "\x1b" not in raw_texts(win)[0]


class TestAnsiInFileViewer:
    """The file viewer loads saved logs, which is where the escapes end up."""

    def test_chunk_load_strips(self, qtbot, win, tmp_path):
        path = tmp_path / "coloured.log"
        path.write_text(ANSI_ERR + "\n" + ANSI_SHELL + "\n")
        v = FileViewer(win._settings, path)
        qtbot.addWidget(v)
        v.show()
        with qtbot.waitSignal(v._worker.load_complete, timeout=5000):
            pass
        try:
            assert raw_texts(v) == [
                "[00:00:05.000,000] <err> modem: init failed: -5",
                "uart:~$ kernel version",
            ]
        finally:
            v.close()

    def test_render_mode_applies_on_load(self, qtbot, win, tmp_path):
        win._settings.set_ansi_mode("render")
        path = tmp_path / "coloured.log"
        path.write_text(ANSI_TAG + "\n")
        v = FileViewer(win._settings, path)
        qtbot.addWidget(v)
        v.show()
        with qtbot.waitSignal(v._worker.load_complete, timeout=5000):
            pass
        try:
            assert block_runs(v._raw_pane, 0)[1][1] == "#f1fa8c"
        finally:
            v.close()


class TestAnsiRespectsColorizationSettings:
    """Wire colours answer to the same gate the colorizer does.

    Bypassing it meant 'Enable colorization' off still showed firmware colours,
    and 'Apply to: raw only' leaked them into the filtered pane.
    """

    def _colors(self, pane, index=0):
        return [color for _, color, _ in block_runs(pane, index)]

    def test_disabled_colorization_still_renders_wire_colours(self, win):
        """'Enable colorization' governs logulator's own colouring.

        Turning it off while choosing 'Render colors' is how you say "use the
        target's colours, not yours" — it must not render plain.
        """
        win._settings.set_ansi_mode("render")
        win._settings.set_color_enabled(False)
        feed(win, ANSI_TAG)
        assert "#f1fa8c" in self._colors(win._raw_pane)

    def test_disabled_colorization_still_plainifies_ordinary_lines(self, win):
        """The other half of the same setting: the colorizer really is off."""
        win._settings.set_ansi_mode("render")
        win._settings.set_color_enabled(False)
        feed(win, PLAIN_WRN)
        assert set(self._colors(win._raw_pane)) == {"#cccccc"}

    def test_apply_to_round_trips(self, win):
        """The style is recorded on the format, not just painted, so routing
        colour away from a pane and back does not lose it — even though the
        escapes are long gone from the document."""
        win._settings.set_ansi_mode("render")
        feed(win, ANSI_TAG)
        coloured = self._colors(win._raw_pane)
        assert "#f1fa8c" in coloured

        win._settings.set_color_apply_to("filtered")
        win._apply_display_settings()
        assert set(self._colors(win._raw_pane)) == {"#cccccc"}

        win._settings.set_color_apply_to("all")
        win._apply_display_settings()
        assert self._colors(win._raw_pane) == coloured

    def test_apply_to_raw_keeps_the_filtered_pane_plain(self, win):
        win._settings.set_ansi_mode("render")
        win._settings.set_color_apply_to("raw")
        win._rules = [{"type": "substring", "value": "modem", "mode": "include"}]
        win._filter_mode = "OR"
        win._filtered_box.show()
        feed(win, ANSI_TAG)
        assert "#f1fa8c" in self._colors(win._raw_pane)
        assert set(self._colors(win._filtered_pane)) == {"#cccccc"}

    def test_apply_to_filtered_keeps_the_raw_pane_plain(self, win):
        win._settings.set_ansi_mode("render")
        win._settings.set_color_apply_to("filtered")
        win._rules = [{"type": "substring", "value": "modem", "mode": "include"}]
        win._filter_mode = "OR"
        win._filtered_box.show()
        feed(win, ANSI_TAG)
        assert set(self._colors(win._raw_pane)) == {"#cccccc"}
        assert "#f1fa8c" in self._colors(win._filtered_pane)

    def test_stripping_still_happens_with_colorization_off(self, win):
        """Escapes are noise regardless of colour — the gate is downstream."""
        win._settings.set_color_enabled(False)
        feed(win, ANSI_TAG, ANSI_SHELL)
        assert raw_texts(win) == [
            "[00:00:06.000,000] <wrn> modem: retrying",
            "uart:~$ kernel version",
        ]

    def test_font_flags_are_dropped_when_inactive(self, win):
        from PySide6.QtGui import QFont

        win._settings.set_ansi_mode("render")
        win._settings.set_color_apply_to("none")
        feed(win, ANSI_TAG)
        block = win._raw_pane.document().findBlockByNumber(0)
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                weight = fragment.charFormat().fontWeight()
                assert weight != QFont.Weight.Bold
            it += 1


class TestPendingPartialLine:
    """A shell prompt arrives without a newline and must still be visible.

    It is provisional: shown in place in the raw pane, replaced as it grows,
    and dropped the moment anything real supersedes it.
    """

    def test_shown_in_the_raw_pane(self, win):
        win._on_partial_line("uart:~$ ")
        assert raw_texts(win) == ["uart:~$ "]
        assert win._pending_partial is True

    def test_growth_replaces_rather_than_stacks(self, win):
        win._on_partial_line("uart:~$ ")
        win._on_partial_line("uart:~$ ver")
        assert raw_texts(win) == ["uart:~$ ver"]

    def test_completed_line_supersedes_it(self, win):
        win._on_partial_line("uart:~$ ")
        win._on_new_line("uart:~$ version")
        assert raw_texts(win) == ["uart:~$ version"]
        assert win._pending_partial is False

    def test_it_does_not_swallow_the_line_before_it(self, win):
        feed(win, "boot done")
        win._on_partial_line("uart:~$ ")
        win._on_new_line("uart:~$ version")
        assert raw_texts(win) == ["boot done", "uart:~$ version"]

    def test_a_tx_echo_supersedes_it_too(self, win):
        """Dropping only in _on_new_line would leave the echo as the last
        block, so the next completed line would delete the echo instead."""
        win._on_partial_line("uart:~$ ")
        win._record_tx("help")
        assert raw_texts(win) == [">> help"]
        win._on_new_line("uart:~$ help")
        assert raw_texts(win) == [">> help", "uart:~$ help"]

    def test_a_separator_supersedes_it(self, win):
        win._on_partial_line("uart:~$ ")
        win._append_separator("--- reconnected ---")
        assert raw_texts(win) == ["--- reconnected ---"]

    def test_not_counted_as_a_received_line(self, win):
        """Provisional: the status bar must not tick up for it."""
        before = win._line_count
        win._on_partial_line("uart:~$ ")
        assert win._line_count == before
        win._on_new_line("uart:~$ version")
        assert win._line_count == before + 1

    def test_not_committed_to_the_filtered_pane(self, win):
        """Retracting it there too, if the completed line stopped matching,
        is complexity the prompt does not justify."""
        win._rules = [{"type": "substring", "value": "uart", "mode": "include"}]
        win._filter_mode = "OR"
        win._filtered_box.show()
        win._on_partial_line("uart:~$ ")
        assert doc_line_count(win._filtered_pane) == 0
        win._on_new_line("uart:~$ version")
        assert filtered_texts(win) == ["uart:~$ version"]

    def test_escapes_are_stripped_from_it(self, win):
        win._on_partial_line("\x1b[1;32muart:~$ \x1b[m")
        assert raw_texts(win) == ["uart:~$ "]

    def test_wire_colour_applies_to_it(self, win):
        win._settings.set_ansi_mode("render")
        win._settings.set_color_enabled(False)
        win._on_partial_line("\x1b[1;32muart:~$ \x1b[m")
        assert [c for _, c, _ in block_runs(win._raw_pane, 0)] == ["#50fa7b"]

    def test_clear_resets_the_flag(self, win):
        win._on_partial_line("uart:~$ ")
        win._on_clear()
        assert win._pending_partial is False
        win._on_new_line("first line after clear")
        assert raw_texts(win) == ["first line after clear"]

    def test_a_lone_pending_line_can_be_dropped(self, win):
        """drop_last_line on a single-block document must not corrupt it."""
        win._on_partial_line("uart:~$ ")
        win._drop_pending_partial()
        assert doc_line_count(win._raw_pane) == 0


class TestAbandonedWorkerCannotKillTheLiveSession:
    """User-visible consequence of a worker abandoned by stop().

    Window slots resolve self._worker when the signal arrives. An abandoned
    worker whose wedged open() finally raises would otherwise tear down
    whatever session had been started since.
    """

    def _abandoned(self, win):
        from app.serial_worker import SerialWorker

        stale = SerialWorker("/dev/wedged", 115200, win._log_writer)
        # Wire it exactly as _on_connect does.
        stale.new_line.connect(win._on_new_line)
        stale.partial_line.connect(win._on_partial_line)
        stale.error_occurred.connect(win._on_serial_error)
        stale.connected.connect(win._on_reconnected)
        stale.wait = lambda *_a, **_k: False
        assert stale.stop() is False
        return stale

    def test_a_late_error_leaves_the_new_session_running(self, win, monkeypatch):
        from app import main_window as mw

        stale = self._abandoned(win)
        live = _StubWorker()
        win._worker = live
        monkeypatch.setattr(
            mw.QMessageBox, "critical", lambda *a, **k: pytest.fail("dialog shown")
        )

        stale.error_occurred.emit("could not open /dev/wedged")

        assert win._worker is live, "the live session was torn down"
        assert live.stopped is False

    def test_a_late_connected_adds_no_reconnect_marker(self, win):
        stale = self._abandoned(win)
        win._reconnecting = True
        stale.connected.emit()
        assert "--- reconnected ---" not in raw_texts(win)

    def test_late_lines_do_not_reach_the_pane(self, win):
        stale = self._abandoned(win)
        stale.new_line.emit("stale line")
        stale.partial_line.emit("stale tail")
        assert doc_line_count(win._raw_pane) == 0
