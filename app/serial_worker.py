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

    def stop(self):
        self._running = False
        self.wait()
