# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Manages the file-backed log. Opens a new timestamped .log file under logs/
at the start of each connection session. Append-only. Flushes after every
write so the log survives a crash."""

import itertools
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


class LogWriter:
    """Append-only session log.

    Written from two threads: the serial worker appends received bytes, and
    the GUI thread records transmitted lines. A reentrant lock keeps those
    from interleaving and makes the open/closed check atomic against close().
    """

    def __init__(self, log_dir: str = "logs"):
        self._log_dir = Path(log_dir).expanduser()
        self._file = None
        self._path: Optional[Path] = None
        self._lock = threading.RLock()
        # Whether the last byte written was a newline. TX records use this to
        # avoid landing inside a partially received RX line.
        self._at_line_start = True

    def set_log_dir(self, log_dir: str) -> None:
        """Change the destination directory. Takes effect on the next session."""
        self._log_dir = Path(log_dir).expanduser()

    def open_session(self):
        """Start a new session log, always in a file of its own.

        The name carries a one-second-resolution timestamp, so reconnecting
        inside the same second would otherwise land on a name that already
        exists. Opening exclusively ("xb") and stepping through _2, _3, …
        guarantees a fresh file: two sessions can never share one, and an
        existing log can never be appended to or overwritten.
        """
        with self._lock:
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
                self._at_line_start = True
                return

    def write(self, data: bytes):
        """Append received bytes verbatim."""
        with self._lock:
            self._write(data)

    def write_tx_line(self, text: str) -> None:
        """Record a transmitted line, marked with '>> '.

        Starts a new line first when the file is mid-line. Received chunks
        routinely end partway through a line, so without this a sent command
        would be spliced into the middle of an incoming one, leaving both
        unreadable. The inserted newline is part of the TX extension; received
        bytes themselves are still written unmodified and in order.
        """
        with self._lock:
            if not self._at_line_start:
                self._write(b"\n")
            self._write(b">> " + text.encode("utf-8") + b"\n")

    def _write(self, data: bytes) -> None:
        """Caller must hold the lock."""
        if not self._file or not data:
            return
        self._file.write(data)
        self._file.flush()
        self._at_line_start = data.endswith(b"\n")

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None
            self._path = None
            self._at_line_start = True

    @property
    def current_path(self) -> Optional[Path]:
        return self._path
