# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Background worker that streams a file's lines in chunks to keep the UI responsive."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

_CHUNK_SIZE = 2000

# How long closeEvent waits for a cancelled load to notice.
_STOP_TIMEOUT_MS = 2000

# Loaders that outlived their stop() deadline. Holding a reference keeps Python
# from destroying a QThread that is still running, which would crash.
_orphans = set()


class FileLoaderWorker(QThread):
    chunk_ready = Signal(list)   # list[str] of decoded lines
    load_complete = Signal(int)  # total line count
    error_occurred = Signal(str)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def stop(self, timeout_ms: int = _STOP_TIMEOUT_MS) -> bool:
        """Cancel the load and wait for the thread to notice.

        The cancellation flag is checked per line, so a healthy load stops
        almost immediately; the timeout covers a read stalled on slow storage.
        A loader that misses the deadline is kept referenced rather than left
        to be garbage collected mid-run, which would destroy a running
        QThread and crash. Returns True if the thread finished in time.
        """
        self._cancelled = True
        if self.wait(timeout_ms):
            return True
        _orphans.add(self)
        self.finished.connect(lambda: _orphans.discard(self))
        return False

    def run(self) -> None:
        total = 0
        try:
            with open(self._path, "r", encoding="utf-8", errors="replace") as f:
                chunk: list = []
                for raw_line in f:
                    if self._cancelled:
                        return
                    chunk.append(raw_line.rstrip("\r\n"))
                    if len(chunk) >= _CHUNK_SIZE:
                        self.chunk_ready.emit(chunk)
                        total += len(chunk)
                        chunk = []
                if chunk:
                    self.chunk_ready.emit(chunk)
                    total += len(chunk)
        except OSError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.load_complete.emit(total)
