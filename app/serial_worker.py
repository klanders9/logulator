# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""QThread subclass that reads bytes from the serial port, emits new_line(str)
for each complete line, and appends raw bytes to LogWriter. Never applies
filters. Outbound bytes are queued via send() and written from the worker
thread so all serial access stays on one thread."""

import queue
from typing import Optional

import serial
from PySide6.QtCore import QThread, Signal

from app.log_writer import LogWriter

_PARITY_MAP = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}
_STOPBITS_MAP = {
    "1": serial.STOPBITS_ONE,
    "1.5": serial.STOPBITS_ONE_POINT_FIVE,
    "2": serial.STOPBITS_TWO,
}

# The read timeout is 0.1 s, so a healthy loop exits well inside this. The
# margin covers a port open that is still in progress.
_STOP_TIMEOUT_MS = 3000

# Workers that outlived their stop() deadline. Holding a reference keeps Python
# from destroying a QThread that is still running, which would crash.
_orphans = set()


class SerialWorker(QThread):
    new_line = Signal(str)
    error_occurred = Signal(str)
    connected = Signal()

    def __init__(
        self,
        port: str,
        baud: int,
        log_writer: LogWriter,
        options: Optional[dict] = None,
    ):
        """options keys (all optional): databits (int 5-8), parity
        ('N'/'E'/'O'/'M'/'S'), stopbits ('1'/'1.5'/'2'), flow
        ('none'/'rtscts'/'xonxoff'), dtr (bool), rts (bool)."""
        super().__init__()
        self._port = port
        self._baud = baud
        self._log_writer = log_writer
        self._options = options or {}
        self._tx_queue: "queue.Queue" = queue.Queue()
        self._running = False

    def send(self, data: bytes) -> None:
        """Queue bytes for transmission. Thread-safe; the run() loop writes
        them so all port access stays on the worker thread."""
        self._tx_queue.put(data)

    def _make_serial(self) -> serial.Serial:
        opts = self._options
        flow = opts.get("flow", "none")
        ser = serial.Serial(
            baudrate=self._baud,
            bytesize=opts.get("databits", 8),
            parity=_PARITY_MAP.get(opts.get("parity", "N"), serial.PARITY_NONE),
            stopbits=_STOPBITS_MAP.get(opts.get("stopbits", "1"), serial.STOPBITS_ONE),
            rtscts=(flow == "rtscts"),
            xonxoff=(flow == "xonxoff"),
            timeout=0.1,
        )
        # Set DTR/RTS before open so the initial line state applies at
        # assertion time (matters for boards that reset on a DTR/RTS edge).
        # RTS is driver-managed under hardware flow control, so leave it alone.
        ser.dtr = opts.get("dtr", True)
        if flow != "rtscts":
            ser.rts = opts.get("rts", True)
        ser.port = self._port
        ser.open()
        return ser

    def _drain_tx(self, ser: serial.Serial) -> None:
        while True:
            try:
                data = self._tx_queue.get_nowait()
            except queue.Empty:
                return
            ser.write(data)

    def run(self):
        self._running = True
        buf = b""
        try:
            with self._make_serial() as ser:
                self.connected.emit()
                while self._running:
                    self._drain_tx(ser)
                    chunk = ser.read(ser.in_waiting or 1)
                    if chunk:
                        self._log_writer.write(chunk)
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            # Strip \r so Windows-style \r\n endings don't cause
                            # blank lines in the display.
                            self.new_line.emit(
                                line.rstrip(b"\r").decode("utf-8", errors="replace")
                            )
        except serial.SerialException as exc:
            self.error_occurred.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — must not die silently
            # Anything else (a full disk or unmounted volume from LogWriter,
            # for instance) would otherwise end the thread with no signal,
            # leaving the UI showing a healthy connection that is dead.
            self.error_occurred.emit(f"{type(exc).__name__}: {exc}")

    def stop(self, timeout_ms: int = _STOP_TIMEOUT_MS) -> bool:
        """Ask the run loop to finish and wait for it.

        Bounded because this is called from the GUI thread: `_make_serial()`
        can block in `open()` on a wedged USB device, and an unbounded wait
        would freeze the window with no way out.

        A thread that misses the deadline is abandoned rather than terminated
        — `QThread.terminate()` on a thread executing Python can leave the GIL
        held and wedge the whole process. It is harmless to leave running:
        `_running` is already False, so once the blocking open() returns it
        closes the port and exits without touching the log or emitting lines.

        Returns True if the thread finished within the deadline.
        """
        self._running = False
        if self.wait(timeout_ms):
            return True
        # Destroying a running QThread crashes, so hold a reference until the
        # thread actually finishes.
        _orphans.add(self)
        self.finished.connect(lambda: _orphans.discard(self))
        return False
