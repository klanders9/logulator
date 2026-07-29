# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the file viewer's tail/follow mode."""

import pytest

from app.settings import AppSettings
from app.ui.file_viewer import FileViewer
from app.ui.log_window import iter_block_texts

LINES = [
    "[00:00:01] <inf> app: first",
    "[00:00:02] <inf> app: second",
]


@pytest.fixture(autouse=True)
def _clean_settings(clear_settings):
    clear_settings()


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


class TestLifecycle:
    def test_geometry_is_persisted_across_viewers(self, qtbot, log_file):
        settings = AppSettings()
        first = FileViewer(settings, log_file)
        qtbot.addWidget(first)
        first.show()
        with qtbot.waitSignal(first._worker.load_complete, timeout=5000):
            pass
        # Kept inside the offscreen platform's 800x600 virtual screen,
        # which otherwise clamps the restored width.
        first.resize(640, 420)
        first.close()

        second = FileViewer(settings, log_file)
        qtbot.addWidget(second)
        second.show()
        with qtbot.waitSignal(second._worker.load_complete, timeout=5000):
            pass
        try:
            assert second.size().width() == 640
            assert second.size().height() == 420
        finally:
            second.close()

    def test_viewer_geometry_is_separate_from_the_serial_window(self, qtbot, log_file):
        """The two windows have different layouts and get sized differently."""
        settings = AppSettings()
        v = FileViewer(settings, log_file)
        qtbot.addWidget(v)
        v.show()
        with qtbot.waitSignal(v._worker.load_complete, timeout=5000):
            pass
        v.resize(700, 400)
        v.close()
        assert settings.load_geometry() is None
        assert settings.load_viewer_geometry() is not None

    def test_close_stops_the_loader(self, qtbot, log_file):
        v = FileViewer(AppSettings(), log_file)
        qtbot.addWidget(v)
        v.show()
        with qtbot.waitSignal(v._worker.load_complete, timeout=5000):
            pass
        worker = v._worker
        v.close()
        assert worker.isFinished()

    def test_closing_mid_load_does_not_leave_a_running_thread(self, qtbot, tmp_path):
        big = tmp_path / "big.log"
        big.write_text("".join(f"line {i}\n" for i in range(60_000)))
        v = FileViewer(AppSettings(), big)
        qtbot.addWidget(v)
        v.show()
        worker = v._worker
        v.close()
        assert worker.wait(5000), "loader must stop promptly after cancel"


class TestReplacedLoaderGoesQuiet:
    """A cancelled loader must not deliver into the document that replaced it.

    cancel() only sets a flag checked between lines, so emits already queued
    for the GUI thread still arrive — and the slots have no idea which worker
    sent them. Two truncations in quick succession is the reachable case.
    """

    def test_the_old_loader_is_disconnected_on_reload(self, viewer):
        old = viewer._worker
        viewer._restart_follow_after_truncation()
        assert viewer._worker is not old
        # A queued chunk from the cancelled loader must land nowhere.
        before = raw_texts(viewer)
        old.chunk_ready.emit(["stale line from the previous pass"])
        assert raw_texts(viewer) == before

    def test_a_late_load_complete_does_not_move_follow_pos(self, viewer):
        """It would otherwise seek past what the new loader is still emitting,
        silently skipping content in follow mode."""
        old = viewer._worker
        viewer._restart_follow_after_truncation()
        viewer._follow_pos = 0
        old.load_complete.emit(9999)
        assert viewer._follow_pos == 0
        assert viewer._total_lines != 9999

    def test_a_late_error_shows_no_dialog(self, viewer, monkeypatch):
        from app.ui import file_viewer as mod

        shown = []
        monkeypatch.setattr(
            mod.QMessageBox, "critical", lambda *a, **k: shown.append(a)
        )
        old = viewer._worker
        viewer._restart_follow_after_truncation()
        old.error_occurred.emit("stale failure")
        assert shown == []

    def test_the_new_loader_is_still_wired(self, viewer):
        viewer._restart_follow_after_truncation()
        viewer._worker.chunk_ready.emit(["fresh line"])
        assert "fresh line" in raw_texts(viewer)
