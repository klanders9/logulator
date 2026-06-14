# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Colorizes log lines into (text, QTextCharFormat) segment lists."""

import re
from typing import List, Tuple

from PySide6.QtGui import QColor, QTextCharFormat

from app.settings import AppSettings

_ZEPHYR_RE = re.compile(
    r'^(\[[\d:.,]+\])'        # timestamp  [HH:MM:SS.mmm,uuu]
    r'( <(?:dbg|inf|wrn|err)>)'  # level tag with leading space
    r'( \S+?:)'               # module name with leading space and colon
    r'( .*)$'                 # message body with leading space
)
_LEVEL_RE = re.compile(r'<(dbg|inf|wrn|err)>')


def _fmt(hex_color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    return f


class Colorizer:
    def __init__(self, settings: AppSettings):
        self._s = settings

    def colorize(self, line: str) -> List[Tuple[str, QTextCharFormat]]:
        if self._s.color_mode() == "syntax":
            return self._syntax(line)
        return self._level(line)

    def _level(self, line: str) -> List[Tuple[str, QTextCharFormat]]:
        m = _LEVEL_RE.search(line)
        color = self._s.level_color(m.group(1)) if m else "#cccccc"
        return [(line, _fmt(color))]

    def _syntax(self, line: str) -> List[Tuple[str, QTextCharFormat]]:
        m = _ZEPHYR_RE.match(line)
        if not m:
            return [(line, _fmt("#cccccc"))]
        ts, tag, mod, msg = m.group(1), m.group(2), m.group(3), m.group(4)
        lm = _LEVEL_RE.search(tag)
        level_color = self._s.level_color(lm.group(1)) if lm else "#cccccc"
        return [
            (ts, _fmt(self._s.syntax_color("timestamp"))),
            (tag, _fmt(level_color)),
            (mod, _fmt(self._s.syntax_color("module"))),
            (msg, _fmt(self._s.syntax_color("message"))),
        ]
