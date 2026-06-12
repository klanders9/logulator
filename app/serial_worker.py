"""QThread subclass that reads bytes from the serial port, emits new_line(str)
for each complete line, and appends raw bytes to LogWriter. Never applies
filters."""

import serial
from PySide6.QtCore import QThread, Signal

from app.log_writer import LogWriter


class SerialWorker(QThread):
    new_line = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, port: str, baud: int, log_writer: LogWriter):
        super().__init__()
        self._port = port
        self._baud = baud
        self._log_writer = log_writer
        self._running = False

    def run(self):
        self._running = True
        buf = b""
        try:
            with serial.Serial(self._port, self._baud, timeout=0.1) as ser:
                while self._running:
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
