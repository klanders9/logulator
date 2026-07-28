# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""ANSI/VT100 escape sequence parsing for the display panes.

Some firmware builds emit coloured output (Zephyr's
`CONFIG_LOG_BACKEND_SHOW_COLOR`, for instance) and any build with a shell
emits VT100 cursor control. Rendered literally those bytes are noise, and
they also break every parser downstream: `colorizer._ZEPHYR_RE` is anchored
at `^`, so a leading colour code disables syntax colouring outright, and
`log_format.MODULE_RE` needs whitespace directly after the level tag, so
`<wrn>\\x1b[0m module:` yields no module and `module:` filter rules stop
matching. Escapes therefore have to come out of the text before anything
else looks at it.

Stdlib only, and pure — no Qt, no settings, no state. `parse()` returns
plain data so the caller decides how (or whether) to paint it.

The session log is untouched by any of this: `LogWriter` records the bytes
off the wire verbatim, escapes included. This module only affects display.
"""

import re
from collections import namedtuple
from typing import List, Optional, Tuple

# A run of text sharing one style. `color` is a "#rrggbb" string or None for
# "whatever the pane would use anyway".
Style = namedtuple("Style", "color bold italic underline")

DEFAULT_STYLE = Style(None, False, False, False)

# (start, length, Style) over the *cleaned* text.
Span = Tuple[int, int, Style]

# Escape sequences, longest-matching form first.
#
#   CSI   ESC [ params intermediates final      — colours, cursor motion, erase
#   OSC   ESC ] ... BEL | ST                    — window title and friends
#   DCS   ESC P|X|^|_ ... ST                    — device control strings
#   nF    ESC intermediate final                — charset selection, e.g. ESC ( B
#   Fe    ESC final                             — single-character escapes
_ESCAPE_RE = re.compile(
    r"""
      \x1b\[ [0-?]* [ -/]* [@-~]
    | \x1b\] .*? (?: \x07 | \x1b\\ )
    | \x1b [PX^_] .*? (?: \x1b\\ | \x07 )
    | \x1b [ -/]+ [0-~]
    | \x1b [0-~]
    | \x1b                                  # trailing lone ESC at end of line
    """,
    re.VERBOSE | re.DOTALL,
)

# Control characters that survive line splitting and would draw as boxes.
# Tab is kept: it is real content in a log line.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")

_SGR_RE = re.compile(r"\x1b\[([0-?]*)m\Z")

# Dracula's ANSI palette. Both app themes are dark, so one set reads well on
# either; the point is only to honour the 8/16 colour indices the firmware
# asked for, not to reproduce a specific terminal emulator.
_PALETTE = (
    "#21222c", "#ff5555", "#50fa7b", "#f1fa8c",  # black red green yellow
    "#bd93f9", "#ff79c6", "#8be9fd", "#f8f8f2",  # blue magenta cyan white
    "#6272a4", "#ff6e6e", "#69ff94", "#ffffa5",  # bright …
    "#d6acff", "#ff92df", "#a4ffff", "#ffffff",
)

_CUBE_STEPS = (0, 95, 135, 175, 215, 255)


def _hex(r: int, g: int, b: int) -> str:
    return "#%02x%02x%02x" % (r, g, b)


def _xterm256(n: int) -> Optional[str]:
    """Map an xterm-256 index to a hex colour."""
    if 0 <= n < 16:
        return _PALETTE[n]
    if 16 <= n < 232:
        n -= 16
        return _hex(
            _CUBE_STEPS[n // 36], _CUBE_STEPS[(n // 6) % 6], _CUBE_STEPS[n % 6]
        )
    if 232 <= n < 256:
        v = 8 + (n - 232) * 10
        return _hex(v, v, v)
    return None


def _apply_sgr(style: Style, params: str) -> Style:
    """Fold one SGR sequence's parameters into the running style.

    Background colours are parsed (so their parameters are consumed rather
    than misread as foreground) but deliberately not rendered: a log pane
    with per-line background blocks is harder to read than one without, and
    the firmware's background choice rarely survives a theme it never saw.
    """
    # An empty parameter list means SGR 0.
    codes = [int(p) if p.isdigit() else 0 for p in params.split(";")] if params else [0]
    color, bold, italic, underline = style
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            color, bold, italic, underline = DEFAULT_STYLE
        elif c == 1:
            bold = True
        elif c in (21, 22):
            bold = False
        elif c == 3:
            italic = True
        elif c == 23:
            italic = False
        elif c == 4:
            underline = True
        elif c == 24:
            underline = False
        elif 30 <= c <= 37:
            color = _PALETTE[c - 30]
        elif 90 <= c <= 97:
            color = _PALETTE[c - 90 + 8]
        elif c == 39:
            color = None
        elif c in (38, 48):
            # 38;5;n (indexed) or 38;2;r;g;b (truecolour); 48 is the
            # background equivalent, consumed the same way and discarded.
            if i + 1 < len(codes) and codes[i + 1] == 5:
                picked = _xterm256(codes[i + 2]) if i + 2 < len(codes) else None
                i += 2
            elif i + 1 < len(codes) and codes[i + 1] == 2:
                if i + 4 < len(codes):
                    picked = _hex(
                        min(codes[i + 2], 255),
                        min(codes[i + 3], 255),
                        min(codes[i + 4], 255),
                    )
                else:
                    picked = None
                i += 4
            else:
                picked = None
            if c == 38:
                color = picked
        # Everything else (background codes, reverse video, blink, …) is
        # recognised as SGR and dropped.
        i += 1
    return Style(color, bold, italic, underline)


def has_escapes(line: str) -> bool:
    """True if the line contains an escape sequence or a stray control byte."""
    return bool(_ESCAPE_RE.search(line) or _CONTROL_RE.search(line))


def strip(line: str) -> str:
    """Return the line with all escape sequences and control bytes removed."""
    return _CONTROL_RE.sub("", _ESCAPE_RE.sub("", line))


def parse(line: str) -> Tuple[str, List[Span]]:
    """Split a line into display text and the colour spans SGR asked for.

    Returns `(text, spans)`. `text` never contains escapes or control bytes.
    `spans` covers only the runs that carry a non-default style, and is empty
    for a line with no colouring — so a caller can treat "no spans" as
    "colour this the usual way".

    Cursor motion, erase-line and the rest of VT100 are removed rather than
    emulated. A shell redrawing its prompt in place therefore shows each
    revision as written instead of only the final state; the alternative is
    guessing which characters an overwrite was meant to replace, and the
    session log already holds the exact bytes for anyone who needs them.
    """
    if "\x1b" not in line:
        cleaned = _CONTROL_RE.sub("", line)
        return cleaned, []

    out: List[str] = []
    spans: List[Span] = []
    style = DEFAULT_STYLE
    pos = 0          # index into the cleaned text
    run_start = 0
    run_style = DEFAULT_STYLE

    def close_run(end: int) -> None:
        # A run only starts when the style actually changes, so consecutive
        # spans always differ and never need merging.
        if end > run_start and run_style != DEFAULT_STYLE:
            spans.append((run_start, end - run_start, run_style))

    last = 0
    for m in _ESCAPE_RE.finditer(line):
        chunk = _CONTROL_RE.sub("", line[last:m.start()])
        if chunk:
            out.append(chunk)
            pos += len(chunk)
        last = m.end()

        sgr = _SGR_RE.match(m.group(0))
        if sgr is None:
            continue
        new_style = _apply_sgr(style, sgr.group(1))
        if new_style != style:
            close_run(pos)
            run_start, run_style = pos, new_style
            style = new_style

    chunk = _CONTROL_RE.sub("", line[last:])
    if chunk:
        out.append(chunk)
        pos += len(chunk)
    close_run(pos)

    return "".join(out), spans
