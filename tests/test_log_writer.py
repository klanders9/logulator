# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for LogWriter session handling."""

import re
from datetime import datetime

import pytest

from app.log_writer import LogWriter, sanitize_prefix


@pytest.fixture
def writer(tmp_path):
    w = LogWriter(str(tmp_path / "logs"))
    yield w
    w.close()


class TestSessionFiles:
    def test_creates_the_log_directory(self, writer, tmp_path):
        writer.open_session()
        assert (tmp_path / "logs").is_dir()

    def test_path_is_exposed_while_open(self, writer):
        writer.open_session()
        assert writer.current_path is not None
        assert writer.current_path.name.startswith("session_")
        assert writer.current_path.suffix == ".log"

    def test_path_is_cleared_on_close(self, writer):
        writer.open_session()
        writer.close()
        assert writer.current_path is None

    def test_back_to_back_sessions_never_share_a_file(self, writer):
        """Reconnecting inside the same second must not reuse the log.

        The name only has one-second resolution, so two sessions a few
        milliseconds apart would otherwise collide — and the old code opened
        in append mode, silently continuing the previous session's file.
        """
        writer.open_session()
        first = writer.current_path
        writer.write(b"session one\n")
        writer.close()

        writer.open_session()
        second = writer.current_path
        writer.write(b"session two\n")
        writer.close()

        assert first != second
        assert first.read_bytes() == b"session one\n"
        assert second.read_bytes() == b"session two\n"

    def test_many_sessions_in_the_same_second_all_get_their_own_file(self, writer):
        paths = []
        for i in range(5):
            writer.open_session()
            writer.write(f"session {i}\n".encode())
            paths.append(writer.current_path)
            writer.close()
        assert len(set(paths)) == 5
        for i, p in enumerate(paths):
            assert p.read_bytes() == f"session {i}\n".encode()

    def test_never_appends_to_a_pre_existing_file(self, writer, tmp_path):
        writer.open_session()
        taken = writer.current_path
        writer.close()
        taken.write_bytes(b"earlier content\n")

        writer.open_session()
        assert writer.current_path != taken
        writer.close()
        assert taken.read_bytes() == b"earlier content\n"

    def test_reopening_without_closing_does_not_leak_the_handle(self, writer):
        writer.open_session()
        first_file = writer._file
        writer.open_session()
        assert first_file.closed
        assert writer._file is not first_file


class TestWriting:
    def test_write_appends_in_order(self, writer):
        writer.open_session()
        writer.write(b"one\n")
        writer.write(b"two\n")
        assert writer.current_path.read_bytes() == b"one\ntwo\n"

    def test_write_flushes_immediately(self, writer):
        """The log must survive a crash, so nothing may sit in the buffer."""
        writer.open_session()
        writer.write(b"crash-me\n")
        assert writer.current_path.read_bytes() == b"crash-me\n"

    def test_write_before_open_is_a_no_op(self, writer):
        writer.write(b"nowhere\n")
        assert writer.current_path is None

    def test_write_after_close_is_a_no_op(self, writer):
        writer.open_session()
        path = writer.current_path
        writer.write(b"kept\n")
        writer.close()
        writer.write(b"dropped\n")
        assert path.read_bytes() == b"kept\n"

    def test_close_is_idempotent(self, writer):
        writer.open_session()
        writer.close()
        writer.close()
        assert writer.current_path is None

    def test_raw_bytes_are_stored_unmodified(self, writer):
        """Core design principle: the writer never transforms what it is given."""
        writer.open_session()
        payload = b"\x00\xff partial line without newline \r\n\x1b[31mANSI\x1b[0m"
        writer.write(payload)
        assert writer.current_path.read_bytes() == payload


class TestLogDirectory:
    def test_expands_a_tilde_path(self, tmp_path):
        from pathlib import Path

        w = LogWriter("~/some-logs")
        assert w._log_dir == Path.home() / "some-logs"

    def test_set_log_dir_applies_to_the_next_session(self, writer, tmp_path):
        writer.open_session()
        assert writer.current_path.parent == tmp_path / "logs"
        writer.close()

        writer.set_log_dir(str(tmp_path / "other"))
        writer.open_session()
        assert writer.current_path.parent == tmp_path / "other"

    def test_creates_nested_directories(self, tmp_path):
        w = LogWriter(str(tmp_path / "a" / "b" / "c"))
        w.open_session()
        assert (tmp_path / "a" / "b" / "c").is_dir()
        w.close()

    def test_unwritable_directory_raises_oserror(self, tmp_path):
        """MainWindow relies on this to refuse the connection with a dialog."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        blocked.chmod(0o500)
        w = LogWriter(str(blocked / "logs"))
        try:
            with pytest.raises(OSError):
                w.open_session()
        finally:
            blocked.chmod(0o700)


class TestFilenamePrefix:
    _STAMP = re.compile(r"\d{8}_\d{6}")

    def test_default_matches_the_historical_name(self, writer):
        writer.open_session()
        assert writer.current_path.name.startswith("session_")

    def test_custom_prefix_is_used(self, tmp_path):
        w = LogWriter(str(tmp_path / "logs"), prefix="featureA_")
        w.open_session()
        try:
            assert w.current_path.name.startswith("featureA_")
            assert self._STAMP.search(w.current_path.name)
        finally:
            w.close()

    def test_set_prefix_applies_to_the_next_session(self, writer):
        writer.open_session()
        writer.close()
        writer.set_prefix("ulcplus_")
        writer.open_session()
        assert writer.current_path.name.startswith("ulcplus_")

    def test_empty_prefix_leaves_a_bare_timestamp(self, tmp_path):
        """A nameless file is impossible — the timestamp is always appended."""
        w = LogWriter(str(tmp_path / "logs"), prefix="")
        w.open_session()
        try:
            assert self._STAMP.fullmatch(w.current_path.stem)
        finally:
            w.close()

    def test_collision_suffix_still_applies(self, tmp_path, monkeypatch):
        """Two sessions in one second must not share a file, prefix or not."""
        import app.log_writer as lw

        fixed = datetime(2026, 8, 1, 14, 30, 12)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(lw, "datetime", _Frozen)
        w = LogWriter(str(tmp_path / "logs"), prefix="run-")
        try:
            w.open_session()
            first = w.current_path
            w.open_session()
            assert first.name == "run-20260801_143012.log"
            assert w.current_path.name == "run-20260801_143012_2.log"
        finally:
            w.close()


class TestPrefixSanitizing:
    """The settings file is hand-editable, so the prefix cannot be trusted."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("featureA_", "featureA_"),
            ("../../escape_", "....escape_"),
            ("a/b\\c_", "abc_"),
            ('bad<>:"|?*chars_', "badchars_"),
            ("  padded  ", "padded"),
            ("nul\x00byte_", "nulbyte_"),
        ],
    )
    def test_sanitize(self, raw, expected):
        assert sanitize_prefix(raw) == expected

    def test_length_is_capped(self):
        assert len(sanitize_prefix("x" * 500)) == 64

    def test_a_separator_prefix_cannot_redirect_the_write(self, tmp_path):
        """Whatever is typed, the log lands in the configured directory."""
        target = tmp_path / "logs"
        w = LogWriter(str(target), prefix="../../../etc/passwd_")
        w.open_session()
        try:
            assert w.current_path.parent == target
        finally:
            w.close()


class TestTransmitRecords:
    def test_tx_line_gets_the_marker(self, writer):
        writer.open_session()
        writer.write_tx_line("kernel reboot")
        assert writer.current_path.read_bytes() == b">> kernel reboot\n"

    def test_tx_after_a_complete_rx_line_adds_no_blank_line(self, writer):
        writer.open_session()
        writer.write(b"[00:00:01] <inf> app: ready\n")
        writer.write_tx_line("help")
        assert writer.current_path.read_bytes() == (
            b"[00:00:01] <inf> app: ready\n>> help\n"
        )

    def test_tx_mid_line_starts_a_new_line_first(self, writer):
        """RX chunks routinely end mid-line; the marker must not be spliced in."""
        writer.open_session()
        writer.write(b"[00:00:01] <inf> app: partial")
        writer.write_tx_line("help")
        assert writer.current_path.read_bytes() == (
            b"[00:00:01] <inf> app: partial\n>> help\n"
        )

    def test_rx_continues_on_its_own_line_after_a_tx_record(self, writer):
        writer.open_session()
        writer.write(b"partial")
        writer.write_tx_line("help")
        writer.write(b" continues\n")
        lines = writer.current_path.read_bytes().split(b"\n")
        assert lines[0] == b"partial"
        assert lines[1] == b">> help"

    def test_first_tx_of_a_session_adds_no_leading_newline(self, writer):
        writer.open_session()
        writer.write_tx_line("first")
        assert not writer.current_path.read_bytes().startswith(b"\n")

    def test_empty_tx_line_is_recorded(self, writer):
        """Sending a bare line ending is a normal way to nudge a shell prompt."""
        writer.open_session()
        writer.write_tx_line("")
        assert writer.current_path.read_bytes() == b">> \n"

    def test_tx_before_open_is_a_no_op(self, writer):
        writer.write_tx_line("nowhere")
        assert writer.current_path is None

    def test_line_state_resets_between_sessions(self, writer):
        writer.open_session()
        writer.write(b"mid-line")
        writer.close()
        writer.open_session()
        writer.write_tx_line("fresh")
        assert writer.current_path.read_bytes() == b">> fresh\n"


class TestThreadSafety:
    def test_concurrent_rx_and_tx_never_interleave_within_a_record(self, writer):
        """Every line must be either a whole RX line or a whole TX record."""
        import threading

        writer.open_session()
        rx_line = b"x" * 200 + b"\n"
        errors = []

        def rx():
            try:
                for _ in range(200):
                    writer.write(rx_line)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        def tx():
            try:
                for i in range(200):
                    writer.write_tx_line(f"cmd{i}")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=rx), threading.Thread(target=tx)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        content = writer.current_path.read_bytes()
        for line in content.split(b"\n"):
            if not line:
                continue
            assert line == b"x" * 200 or line.startswith(b">> cmd"), line

    def test_close_during_concurrent_writes_does_not_raise(self, writer):
        """write() must not race the open/closed check against close()."""
        import threading

        writer.open_session()
        errors = []
        stop = threading.Event()

        def rx():
            try:
                while not stop.is_set():
                    writer.write(b"data\n")
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=rx)
        t.start()
        try:
            for _ in range(50):
                writer.close()
                writer.open_session()
        finally:
            stop.set()
            t.join()
        assert not errors
