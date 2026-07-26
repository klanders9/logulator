# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for LogWriter session handling."""

import pytest

from app.log_writer import LogWriter


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
