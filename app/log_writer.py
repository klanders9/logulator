# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Manages the file-backed log. Opens a new timestamped .log file under logs/
at the start of each connection session. Append-only. Flushes after every
write so the log survives a crash."""

from datetime import datetime
from pathlib import Path
from typing import Optional


class LogWriter:
    def __init__(self, log_dir: str = "logs"):
        self._log_dir = Path(log_dir)
        self._file = None
        self._path: Optional[Path] = None

    def open_session(self):
        self._log_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = self._log_dir / f"session_{ts}.log"
        self._file = open(self._path, "ab")

    def write(self, data: bytes):
        if self._file:
            self._file.write(data)
            self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None
        self._path = None

    @property
    def current_path(self) -> Optional[Path]:
        return self._path
