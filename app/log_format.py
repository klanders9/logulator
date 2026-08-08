# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Log-line format knowledge shared by the colorizer and the filter engine.

Stdlib only — no Qt, no settings, no state. Both consumers need to answer
"what severity is this line?" the same way, and before this module existed
they disagreed: the colorizer fell back to a keyword scan while filter rules
matched only an explicit `<tag>`, so a line shown in red was not matched by a
`level: err` rule.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

LEVELS = ("dbg", "inf", "wrn", "err")

# Markers on the two kinds of line logulator generates itself, as opposed to
# receiving. Both are recorded in the session log and echoed to the display,
# so the colorizer and the minimap have to recognise them on the way back in —
# from a live pane rebuild or from a saved log reopened in the file viewer.
# ">>>MARK" does not collide with ">> ": the third character differs.
TX_PREFIX = ">> "
MARK_PREFIX = ">>>MARK"

# Zephyr severity tag, e.g. "<inf>".
LEVEL_TAG_RE = re.compile(r"<(dbg|inf|wrn|err)>")

# Module field following the level tag, e.g. "<inf> net_if:" -> "net_if".
MODULE_RE = re.compile(r"<(?:dbg|inf|wrn|err)>\s+(\S+?):")

# Keyword level detection for formats that don't use <tag> syntax.
# Matched case-insensitively; order determines priority (err before wrn).
_KEYWORD_LEVELS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\b(?:error|err|fatal|critical)\b', re.IGNORECASE), 'err'),
    (re.compile(r'\b(?:warning|warn)\b', re.IGNORECASE), 'wrn'),
    (re.compile(r'\b(?:info|notice)\b', re.IGNORECASE), 'inf'),
    (re.compile(r'\b(?:debug|dbg|trace)\b', re.IGNORECASE), 'dbg'),
]


def keyword_level(line: str) -> Optional[str]:
    """Return a level key by keyword search alone, or None."""
    for pattern, level in _KEYWORD_LEVELS:
        if pattern.search(line):
            return level
    return None


def detect_level(line: str) -> Optional[str]:
    """Detect a line's severity ('dbg'/'inf'/'wrn'/'err'), or None.

    An explicit `<tag>` wins; otherwise fall back to a keyword scan. This is
    the single definition of a line's severity — level-mode colorization,
    `level` filter rules and the minimap all go through it, so what you see
    coloured red is what a `level: err` rule selects.
    """
    m = LEVEL_TAG_RE.search(line)
    if m:
        return m.group(1)
    return keyword_level(line)


def module_of(line: str) -> Optional[str]:
    """Return the module field of a Zephyr-style line, or None."""
    m = MODULE_RE.search(line)
    return m.group(1) if m else None


def format_mark(note: str, when: Optional[datetime] = None) -> str:
    """Render a user mark: '>>>MARK - 2026-08-01T14:23:45Z: note'.

    The timestamp is UTC because a mark exists to be lined up with something
    outside the log — a bench instrument, a ticket, another machine's log —
    and those rarely share the operator's timezone. An empty note leaves just
    the marker and the time, which is still a usable landmark.
    """
    when = when if when is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = note.strip()
    return f"{MARK_PREFIX} - {stamp}: {note}" if note else f"{MARK_PREFIX} - {stamp}"


def is_generated(line: str) -> bool:
    """Whether a line was written by logulator rather than received."""
    return line.startswith(TX_PREFIX) or line.startswith(MARK_PREFIX)
