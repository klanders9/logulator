# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for SerialWorker line splitting, error reporting and shutdown.

The serial port itself is stubbed — these cover the worker's own logic, not
pyserial.
"""

import threading
import time

import pytest
import serial

from app import serial_worker as serial_worker_module
from app.serial_worker import SerialWorker


class FakeSerial:
    """Minimal stand-in for serial.Serial, usable as a context manager."""

    def __init__(self, chunks=None, read_error=None):
        self._chunks = list(chunks or [])
        self._read_error = read_error
        self.written = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True
        return False

    @property
    def in_waiting(self):
        return len(self._chunks[0]) if self._chunks else 0

    def read(self, _n):
        if self._read_error is not None:
            error, self._read_error = self._read_error, None
            raise error
        if self._chunks:
            return self._chunks.pop(0)
        time.sleep(0.01)
        return b""

    def write(self, data):
        self.written.append(data)


class RecordingLogWriter:
    def __init__(self, error=None):
        self.data = b""
        self._error = error

    def write(self, chunk):
        if self._error is not None:
            raise self._error
        self.data += chunk


def run_worker(monkeypatch, qapp, fake, log_writer=None, stop_after=1.0):
    """Run a worker against `fake` and collect what it emits.

    The worker emits from its own thread, so the connections are queued and
    only deliver while the main thread pumps events.
    """
    log_writer = log_writer or RecordingLogWriter()
    worker = SerialWorker("/dev/fake", 115200, log_writer)
    monkeypatch.setattr(worker, "_make_serial", lambda: fake)

    lines, errors = [], []
    worker.new_line.connect(lines.append)
    worker.error_occurred.connect(errors.append)

    worker.start()
    deadline = time.monotonic() + stop_after
    while time.monotonic() < deadline and not errors and fake._chunks:
        qapp.processEvents()
        time.sleep(0.005)
    worker.stop()
    qapp.processEvents()
    return worker, lines, errors, log_writer


class TestLineSplitting:
    def test_splits_on_newline(self, qapp, monkeypatch):
        fake = FakeSerial([b"one\ntwo\nthree\n"])
        _w, lines, _e, _lw = run_worker(monkeypatch, qapp, fake)
        assert lines == ["one", "two", "three"]

    def test_strips_carriage_returns(self, qapp, monkeypatch):
        """Zephyr UART emits \\r\\n; the bare \\r would show as blank lines."""
        fake = FakeSerial([b"one\r\ntwo\r\n"])
        _w, lines, _e, _lw = run_worker(monkeypatch, qapp, fake)
        assert lines == ["one", "two"]

    def test_reassembles_lines_split_across_chunks(self, qapp, monkeypatch):
        fake = FakeSerial([b"par", b"tial li", b"ne\n"])
        _w, lines, _e, _lw = run_worker(monkeypatch, qapp, fake)
        assert lines == ["partial line"]

    def test_holds_back_an_incomplete_trailing_line(self, qapp, monkeypatch):
        fake = FakeSerial([b"complete\nincomplete"])
        _w, lines, _e, _lw = run_worker(monkeypatch, qapp, fake)
        assert lines == ["complete"]

    def test_undecodable_bytes_are_replaced_not_fatal(self, qapp, monkeypatch):
        fake = FakeSerial([b"good\n\xff\xfe bad\n"])
        _w, lines, _e, _lw = run_worker(monkeypatch, qapp, fake)
        assert lines[0] == "good"
        assert len(lines) == 2


class TestLogging:
    def test_every_byte_reaches_the_log_unmodified(self, qapp, monkeypatch):
        """Core design principle: the log gets raw bytes, filters never apply."""
        payload = b"one\r\ntwo\r\npartial"
        fake = FakeSerial([payload])
        _w, _l, _e, log_writer = run_worker(monkeypatch, qapp, fake)
        assert log_writer.data == payload


class TestErrorReporting:
    def test_serial_exception_is_reported(self, qapp, monkeypatch):
        fake = FakeSerial(read_error=serial.SerialException("device disconnected"))
        _w, _l, errors, _lw = run_worker(monkeypatch, qapp, fake)
        assert errors == ["device disconnected"]

    def test_log_writer_failure_is_reported(self, qapp, monkeypatch):
        """A full disk used to kill the thread silently, leaving the UI
        showing a connection that was no longer reading anything."""
        fake = FakeSerial([b"data\n"])
        log_writer = RecordingLogWriter(error=OSError(28, "No space left on device"))
        _w, _l, errors, _lw = run_worker(monkeypatch, qapp, fake, log_writer)
        assert len(errors) == 1
        assert "OSError" in errors[0]
        assert "No space left" in errors[0]

    def test_port_open_failure_is_reported(self, qapp, monkeypatch):
        worker = SerialWorker("/dev/nope", 115200, RecordingLogWriter())

        def boom():
            raise serial.SerialException("could not open port")

        monkeypatch.setattr(worker, "_make_serial", boom)
        errors = []
        worker.error_occurred.connect(errors.append)
        worker.start()
        assert worker.wait(2000)
        qapp.processEvents()
        assert errors == ["could not open port"]


class TestTransmit:
    def test_queued_bytes_are_written_from_the_worker_thread(self, qapp, monkeypatch):
        fake = FakeSerial([b"hello\n"])
        worker = SerialWorker("/dev/fake", 115200, RecordingLogWriter())
        monkeypatch.setattr(worker, "_make_serial", lambda: fake)
        worker.send(b"cmd\r\n")
        worker.start()
        time.sleep(0.2)
        worker.stop()
        assert b"cmd\r\n" in fake.written

    def test_send_is_safe_before_the_thread_starts(self, qapp):
        worker = SerialWorker("/dev/fake", 115200, RecordingLogWriter())
        worker.send(b"queued\r\n")  # must not raise
        assert worker._tx_queue.qsize() == 1


class TestShutdown:
    def test_stop_returns_true_for_a_responsive_loop(self, qapp, monkeypatch):
        fake = FakeSerial([b"line\n"])
        worker = SerialWorker("/dev/fake", 115200, RecordingLogWriter())
        monkeypatch.setattr(worker, "_make_serial", lambda: fake)
        worker.start()
        time.sleep(0.1)
        assert worker.stop() is True
        assert worker.isFinished()

    def test_stop_is_bounded_when_the_port_open_hangs(self, qapp, monkeypatch):
        """stop() runs on the GUI thread; an unbounded wait() froze the window
        whenever a wedged USB device stalled inside open()."""
        release = threading.Event()

        def hanging_open():
            release.wait(30)
            return FakeSerial()

        worker = SerialWorker("/dev/wedged", 115200, RecordingLogWriter())
        monkeypatch.setattr(worker, "_make_serial", hanging_open)
        worker.start()
        time.sleep(0.05)

        started = time.monotonic()
        finished_cleanly = worker.stop(timeout_ms=300)
        elapsed = time.monotonic() - started

        assert finished_cleanly is False
        assert elapsed < 5, "stop() must not block the GUI thread indefinitely"

        # Abandoned, not terminated: the object stays referenced so Python
        # cannot destroy a QThread that is still running.
        assert worker in serial_worker_module._orphans

        release.set()
        assert worker.wait(5000), "the abandoned thread must still finish on its own"

    def test_an_abandoned_worker_reads_nothing_after_stop(self, qapp, monkeypatch):
        """Once stop() has set _running False, a late port open must not
        deliver lines or write to a log the window has already closed."""
        release = threading.Event()
        log_writer = RecordingLogWriter()
        fake = FakeSerial([b"late data\n"])

        def hanging_open():
            release.wait(30)
            return fake

        worker = SerialWorker("/dev/wedged", 115200, log_writer)
        monkeypatch.setattr(worker, "_make_serial", hanging_open)
        lines = []
        worker.new_line.connect(lines.append)
        worker.start()
        time.sleep(0.05)
        worker.stop(timeout_ms=200)

        release.set()
        assert worker.wait(5000)
        assert lines == []
        assert log_writer.data == b""
        assert fake.closed, "the port must still be closed cleanly"

    def test_stop_is_idempotent(self, qapp, monkeypatch):
        fake = FakeSerial([b"line\n"])
        worker = SerialWorker("/dev/fake", 115200, RecordingLogWriter())
        monkeypatch.setattr(worker, "_make_serial", lambda: fake)
        worker.start()
        time.sleep(0.1)
        worker.stop()
        worker.stop()
        assert worker.isFinished()


class TestPortConfiguration:
    @pytest.mark.parametrize(
        "opts,attr,expected",
        [
            ({"databits": 7}, "bytesize", 7),
            ({"parity": "E"}, "parity", serial.PARITY_EVEN),
            ({"stopbits": "2"}, "stopbits", serial.STOPBITS_TWO),
            ({"flow": "rtscts"}, "rtscts", True),
            ({"flow": "xonxoff"}, "xonxoff", True),
        ],
    )
    def test_options_reach_the_port(self, qapp, monkeypatch, opts, attr, expected):
        captured = {}

        class Probe:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.dtr = self.rts = None
                self.port = None

            def open(self):
                pass

        monkeypatch.setattr(serial, "Serial", Probe)
        SerialWorker("/dev/fake", 9600, RecordingLogWriter(), opts)._make_serial()
        assert captured[attr] == expected

    def test_unknown_values_fall_back_to_defaults(self, qapp, monkeypatch):
        captured = {}

        class Probe:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.dtr = self.rts = None
                self.port = None

            def open(self):
                pass

        monkeypatch.setattr(serial, "Serial", Probe)
        opts = {"parity": "bogus", "stopbits": "bogus"}
        SerialWorker("/dev/fake", 9600, RecordingLogWriter(), opts)._make_serial()
        assert captured["parity"] == serial.PARITY_NONE
        assert captured["stopbits"] == serial.STOPBITS_ONE

    def test_rts_is_left_alone_under_hardware_flow_control(self, qapp, monkeypatch):
        """RTS is driver-managed with rtscts, so the worker must not drive it."""
        probe = {}

        class Probe:
            def __init__(self, **kwargs):
                self.dtr = None
                self.rts = "untouched"
                self.port = None

            def open(self):
                probe["rts"] = self.rts

        monkeypatch.setattr(serial, "Serial", Probe)
        opts = {"flow": "rtscts", "rts": True}
        SerialWorker("/dev/fake", 9600, RecordingLogWriter(), opts)._make_serial()
        assert probe["rts"] == "untouched"

    def test_dtr_is_set_before_open(self, qapp, monkeypatch):
        """Boards that reset on a DTR edge need the level set pre-open."""
        seen = {}

        class Probe:
            def __init__(self, **kwargs):
                self.dtr = None
                self.rts = None
                self.port = None

            def open(self):
                seen["dtr"] = self.dtr

        monkeypatch.setattr(serial, "Serial", Probe)
        SerialWorker("/dev/fake", 9600, RecordingLogWriter(), {"dtr": False})._make_serial()
        assert seen["dtr"] is False
