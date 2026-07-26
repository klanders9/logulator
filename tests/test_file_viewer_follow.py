# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the file viewer's tail/follow mode."""

import pytest
from PySide6.QtCore import QSettings

from app.settings import AppSettings
from app.ui.file_viewer import FileViewer
from app.ui.log_window import iter_block_texts

LINES = [
    "[00:00:01] <inf> app: first",
    "[00:00:02] <inf> app: second",
]


@pytest.fixture(autouse=True)
def _clean_settings(_isolate_qsettings):
    QSettings("logulator", "logulator").clear()


@pytest.fixture
def log_file(tmp_path):
    p = tmp_path / "follow.log"
    p.write_text("\n".join(LINES) + "\n")
    return p


@pytest.fixture
def viewer(qtbot, log_file):
    v = FileViewer(AppSettings(), log_file)
    qtbot.addWidget(v)
    v.show()
    with qtbot.waitSignal(v._worker.load_complete, timeout=5000):
        pass
    yield v
    v.close()


def raw_texts(v):
    return [t for t in iter_block_texts(v._raw_pane.document()) if t]


class TestFollowBasics:
    def test_follow_is_enabled_after_load(self, viewer):
        assert viewer._follow_action.isChecked()
        assert viewer._follow is True

    def test_follow_position_starts_at_end_of_file(self, viewer, log_file):
        assert viewer._follow_pos == log_file.stat().st_size

    def test_appended_lines_are_picked_up(self, viewer, log_file):
        with log_file.open("a") as f:
            f.write("[00:00:03] <wrn> app: third\n")
        viewer._on_file_changed(str(log_file))
        assert raw_texts(viewer)[-1] == "[00:00:03] <wrn> app: third"

    def test_partial_line_is_buffered_until_complete(self, viewer, log_file):
        with log_file.open("a") as f:
            f.write("[00:00:03] <wrn> app: par")
        viewer._on_file_changed(str(log_file))
        assert len(raw_texts(viewer)) == 2

        with log_file.open("a") as f:
            f.write("tial done\n")
        viewer._on_file_changed(str(log_file))
        assert raw_texts(viewer)[-1] == "[00:00:03] <wrn> app: partial done"

    def test_crlf_endings_are_stripped(self, viewer, log_file):
        with log_file.open("ab") as f:
            f.write(b"[00:00:03] <inf> app: crlf\r\n")
        viewer._on_file_changed(str(log_file))
        assert raw_texts(viewer)[-1] == "[00:00:03] <inf> app: crlf"

    def test_disabling_follow_stops_watching(self, viewer, log_file):
        viewer._follow_action.setChecked(False)
        assert viewer._watcher.files() == []
        with log_file.open("a") as f:
            f.write("[00:00:03] <inf> app: ignored\n")
        viewer._on_file_changed(str(log_file))
        assert len(raw_texts(viewer)) == 2


class TestTruncation:
    def test_truncated_file_is_reloaded(self, viewer, log_file, qtbot):
        """_follow_pos only ever grew, so after a truncation the seek landed
        past EOF and follow was silently dead for the life of the window."""
        log_file.write_text("[00:00:09] <inf> app: rotated\n")
        viewer._on_file_changed(str(log_file))
        with qtbot.waitSignal(viewer._worker.load_complete, timeout=5000):
            pass
        assert raw_texts(viewer) == ["[00:00:09] <inf> app: rotated"]

    def test_follow_still_works_after_truncation(self, viewer, log_file, qtbot):
        log_file.write_text("[00:00:09] <inf> app: rotated\n")
        viewer._on_file_changed(str(log_file))
        with qtbot.waitSignal(viewer._worker.load_complete, timeout=5000):
            pass

        with log_file.open("a") as f:
            f.write("[00:00:10] <inf> app: after rotation\n")
        viewer._on_file_changed(str(log_file))
        assert raw_texts(viewer)[-1] == "[00:00:10] <inf> app: after rotation"

    def test_line_count_is_reset_not_accumulated(self, viewer, log_file, qtbot):
        log_file.write_text("only one line\n")
        viewer._on_file_changed(str(log_file))
        with qtbot.waitSignal(viewer._worker.load_complete, timeout=5000):
            pass
        assert viewer._total_lines == 1

    def test_emptying_the_file_clears_the_pane(self, viewer, log_file, qtbot):
        log_file.write_text("")
        viewer._on_file_changed(str(log_file))
        with qtbot.waitSignal(viewer._worker.load_complete, timeout=5000):
            pass
        assert raw_texts(viewer) == []

    def test_same_size_rewrite_is_not_treated_as_truncation(self, viewer, log_file):
        """Only a shrink triggers a reload; equal size means nothing new."""
        before = viewer._follow_pos
        viewer._on_file_changed(str(log_file))
        assert viewer._follow_pos == before
        assert raw_texts(viewer) == LINES


class TestPause:
    def test_scrolling_up_pauses_following(self, viewer, log_file):
        sb = viewer._raw_pane.verticalScrollBar()
        sb.setMaximum(1000)
        viewer._on_scroll_changed(0)
        assert viewer._follow_paused is True
        assert viewer._resume_action.isVisible()

    def test_resume_clears_the_pause(self, viewer):
        viewer._follow_paused = True
        viewer._resume_action.setVisible(True)
        viewer._on_resume()
        assert viewer._follow_paused is False
        assert not viewer._resume_action.isVisible()

    def test_programmatic_scroll_does_not_pause(self, viewer):
        viewer._programmatic_scroll = True
        viewer._on_scroll_changed(0)
        assert viewer._follow_paused is False

    def test_paused_follow_still_appends(self, viewer, log_file):
        """Pausing stops the auto-scroll, not the tailing."""
        viewer._follow_paused = True
        with log_file.open("a") as f:
            f.write("[00:00:03] <inf> app: while paused\n")
        viewer._on_file_changed(str(log_file))
        assert raw_texts(viewer)[-1] == "[00:00:03] <inf> app: while paused"
