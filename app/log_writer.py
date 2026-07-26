# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Manages the file-backed log. Opens a new timestamped .log file under logs/
at the start of each connection session. Append-only. Flushes after every
write so the log survives a crash."""

import itertools
from datetime import datetime
from pathlib import Path
from typing import Optional


class LogWriter:
    def __init__(self, log_dir: str = "logs"):
        self._log_dir = Path(log_dir)
        self._file = None
        self._path: Optional[Path] = None

    def open_session(self):
        """Start a new session log, always in a file of its own.

        The name carries a one-second-resolution timestamp, so reconnecting
        inside the same second would otherwise land on a name that already
        exists. Opening exclusively ("xb") and stepping through _2, _3, …
        guarantees a fresh file: two sessions can never share one, and an
        existing log can never be appended to or overwritten.
        """
        self.close()
        self._log_dir.mkdir(parents=True, exist_ok=True)
        stem = datetime.now().strftime("session_%Y%m%d_%H%M%S")
        for attempt in itertools.count(1):
            suffix = "" if attempt == 1 else f"_{attempt}"
            path = self._log_dir / f"{stem}{suffix}.log"
            try:
                self._file = open(path, "xb")
            except FileExistsError:
                continue
            self._path = path
            return

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
