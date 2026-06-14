# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Colorizes log lines into (text, QTextCharFormat) segment lists."""

import re
from typing import List, Optional, Tuple

from PySide6.QtGui import QColor, QTextCharFormat

from app.settings import AppSettings

# Zephyr: [HH:MM:SS.mmm,uuu] <level> module: message
_ZEPHYR_RE = re.compile(
    r'^(\[[\d:.,]+\])'
    r'( <(?:dbg|inf|wrn|err)>)'
    r'( \S+?:)'
    r'( .*)$'
)
_LEVEL_RE = re.compile(r'<(dbg|inf|wrn|err)>')

# Syslog traditional: "Jun 14 10:23:45 hostname process[pid]: message"
_SYSLOG_TRAD_RE = re.compile(
    r'^([A-Z][a-z]{2} [ \d]\d [\d:]+)'  # timestamp
    r'( \S+)'                             # hostname
    r'( \S+?:)'                           # process[pid]:
    r'( .*)$'                             # message
)

# Syslog ISO 8601: "2024-06-14T10:23:45.123456+00:00 hostname process[pid]: message"
_SYSLOG_ISO_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}T[\d:.]+[+\-]\d{2}:\d{2})'  # ISO timestamp
    r'( \S+)'                                            # hostname
    r'( \S+?:)'                                         # process[pid]:
    r'( .*)$'                                            # message
)

# Keyword level detection for formats that don't use <tag> syntax.
# Matched case-insensitively; order determines priority (err before wrn).
_KEYWORD_LEVELS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\b(?:error|err|fatal|critical)\b', re.IGNORECASE), 'err'),
    (re.compile(r'\b(?:warning|warn)\b', re.IGNORECASE), 'wrn'),
    (re.compile(r'\b(?:info|notice)\b', re.IGNORECASE), 'inf'),
    (re.compile(r'\b(?:debug|dbg|trace)\b', re.IGNORECASE), 'dbg'),
]


def _fmt(hex_color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    return f


def _keyword_level(line: str) -> Optional[str]:
    """Return a Zephyr level key ('err'/'wrn'/'inf'/'dbg') by keyword search, or None."""
    for pattern, level in _KEYWORD_LEVELS:
        if pattern.search(line):
            return level
    return None


class Colorizer:
    def __init__(self, settings: AppSettings):
        self._s = settings

    def colorize(self, line: str) -> List[Tuple[str, QTextCharFormat]]:
        if self._s.color_mode() == "syntax":
            return self._syntax(line)
        return self._level(line)

    def _level(self, line: str) -> List[Tuple[str, QTextCharFormat]]:
        # Prefer explicit <tag> (Zephyr), fall back to keyword scan.
        m = _LEVEL_RE.search(line)
        if m:
            return [(line, _fmt(self._s.level_color(m.group(1))))]
        level = _keyword_level(line)
        if level:
            return [(line, _fmt(self._s.level_color(level)))]
        return [(line, _fmt("#cccccc"))]

    def _syntax(self, line: str) -> List[Tuple[str, QTextCharFormat]]:
        # --- Zephyr ---
        m = _ZEPHYR_RE.match(line)
        if m:
            ts, tag, mod, msg = m.group(1), m.group(2), m.group(3), m.group(4)
            lm = _LEVEL_RE.search(tag)
            level_color = self._s.level_color(lm.group(1)) if lm else "#cccccc"
            return [
                (ts,  _fmt(self._s.syntax_color("timestamp"))),
                (tag, _fmt(level_color)),
                (mod, _fmt(self._s.syntax_color("module"))),
                (msg, _fmt(self._s.syntax_color("message"))),
            ]

        # --- Syslog (ISO or traditional) ---
        m = _SYSLOG_ISO_RE.match(line) or _SYSLOG_TRAD_RE.match(line)
        if m:
            ts, host, proc, msg = m.group(1), m.group(2), m.group(3), m.group(4)
            level = _keyword_level(msg)
            msg_color = self._s.level_color(level) if level else self._s.syntax_color("message")
            return [
                (ts,   _fmt(self._s.syntax_color("timestamp"))),
                (host, _fmt("#cccccc")),
                (proc, _fmt(self._s.syntax_color("module"))),
                (msg,  _fmt(msg_color)),
            ]

        # --- Fallback ---
        return [(line, _fmt("#cccccc"))]
