# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Background worker that streams a file's lines in chunks to keep the UI responsive."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

_CHUNK_SIZE = 2000


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
