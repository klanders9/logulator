# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Integration tests for LogWindowMixin, driven through both real windows.

MainWindow and FileViewer share their pane, filter, colorization and minimap
behaviour. These tests exercise that shared surface from each side so a change
to the mixin cannot silently break one window while the other still works.
"""

import pytest
from PySide6.QtCore import QSettings

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
def _clean_settings(_isolate_qsettings):
    QSettings("logulator", "logulator").clear()


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

    def test_main_window_honours_the_persisted_buffer_cap(self, qtbot):
        settings = QSettings("logulator", "logulator")
        settings.setValue("buffer/cap", 5_000)
        settings.sync()
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
