# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Log-line format knowledge shared by the colorizer and the filter engine.

Stdlib only — no Qt, no settings, no state. Both consumers need to answer
"what severity is this line?" the same way, and before this module existed
they disagreed: the colorizer fell back to a keyword scan while filter rules
matched only an explicit `<tag>`, so a line shown in red was not matched by a
`level: err` rule.
"""

import re
from typing import List, Optional, Tuple

LEVELS = ("dbg", "inf", "wrn", "err")

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
