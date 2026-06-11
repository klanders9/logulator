"""Manages the file-backed log. Opens a new timestamped .log file under logs/
at the start of each connection session. Append-only. Flushes after every
write so the log survives a crash."""

from datetime import datetime
from pathlib import Path


class LogWriter:
    def __init__(self, log_dir: str = "logs"):
        self._log_dir = Path(log_dir)
        self._file = None

    def open_session(self):
        self._log_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._log_dir / f"session_{ts}.log"
        self._file = open(path, "ab")

    def write(self, data: bytes):
        if self._file:
            self._file.write(data)
            self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None
