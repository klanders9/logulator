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

`parse()` is a one-line terminal: it renders the sequence of writes, cursor
moves and erases into the text a terminal would end up showing. Merely
deleting the escapes is not enough, because the Zephyr shell wipes its prompt
before printing each log message — `uart:~$ ESC[2K CR [00:00:00.200] <inf> …`
— so dropping the erase and the carriage return without acting on them
cements the prompt onto the front of every log line during boot.

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

# CSI split into parameters and final byte, for the cursor/erase sequences.
_CSI_RE = re.compile(r"\x1b\[([0-?]*)[ -/]*([@-~])\Z")

# Only these need the line actually rendered rather than filtered.
_NEEDS_RENDER = re.compile(r"[\x1b\r\x08]")

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
    """Return the text a terminal would show for this line, without styling.

    Defined as `parse(line)[0]` so the text used for filtering, searching and
    the minimap can never disagree with the text on screen.
    """
    return parse(line)[0]


def _first_param(params: str, default: int) -> int:
    head = params.split(";")[0].lstrip("?")
    return int(head) if head.isdigit() else default


def _apply_csi(cells: list, col: int, params: str, final: str) -> int:
    """Act on one cursor/erase CSI. Returns the new column.

    Only the sequences a log stream actually uses are implemented; anything
    else is consumed and ignored, which is what a terminal does with a
    capability it lacks.
    """
    if final == "K":  # erase in line
        mode = _first_param(params, 0)
        if mode == 0:
            del cells[col:]
        elif mode == 1:
            for i in range(min(col + 1, len(cells))):
                cells[i] = (" ", DEFAULT_STYLE)
        else:
            del cells[:]
    elif final == "J":  # erase in display — one line is all we have
        if _first_param(params, 0) == 2:
            del cells[:]
    elif final == "C":
        col += _first_param(params, 1)
    elif final == "D":
        col = max(0, col - _first_param(params, 1))
    elif final == "G":
        col = max(0, _first_param(params, 1) - 1)
    elif final in ("H", "f"):
        col = 0  # row is meaningless in a line-oriented view
    return col


def _render(line: str) -> Tuple[str, List[Span]]:
    """Replay the line's writes, moves and erases into final cell contents."""
    cells: List[Tuple[str, Style]] = []
    col = 0
    style = DEFAULT_STYLE
    pos, end = 0, len(line)

    while pos < end:
        match = _ESCAPE_RE.match(line, pos)
        if match:
            pos = match.end()
            seq = match.group(0)
            sgr = _SGR_RE.match(seq)
            if sgr is not None:
                style = _apply_sgr(style, sgr.group(1))
                continue
            csi = _CSI_RE.match(seq)
            if csi is not None:
                col = _apply_csi(cells, col, csi.group(1), csi.group(2))
            continue

        char = line[pos]
        pos += 1
        if char == "\r":
            col = 0
            continue
        if char == "\x08":
            col = max(0, col - 1)
            continue
        if _CONTROL_RE.match(char):
            continue
        if col < len(cells):
            cells[col] = (char, style)
        else:
            cells.extend([(" ", DEFAULT_STYLE)] * (col - len(cells)))
            cells.append((char, style))
        col += 1

    text = "".join(char for char, _ in cells)
    spans: List[Span] = []
    run_start = 0
    run_style = cells[0][1] if cells else DEFAULT_STYLE
    for index, (_char, cell_style) in enumerate(cells):
        if cell_style != run_style:
            if run_style != DEFAULT_STYLE:
                spans.append((run_start, index - run_start, run_style))
            run_start, run_style = index, cell_style
    if run_style != DEFAULT_STYLE and len(cells) > run_start:
        spans.append((run_start, len(cells) - run_start, run_style))
    return text, spans


def parse(line: str) -> Tuple[str, List[Span]]:
    """Render a line into display text and the colour spans SGR asked for.

    Returns `(text, spans)`. `text` is what a terminal would end up showing:
    no escapes, no control bytes, and with carriage returns, backspaces and
    erase-line sequences applied rather than discarded. `spans` covers only
    the runs carrying a non-default style, and is empty for a line with no
    colouring — so a caller can treat "no spans" as "colour this the usual
    way".

    Overwrites are resolved the way a terminal resolves them, by column: a
    write lands on the cell the cursor is over. Guessing was the alternative,
    and guessing wrong showed up as the shell prompt cemented onto the front
    of every log line.
    """
    # The overwhelming majority of log lines have nothing to render — no
    # escape, no carriage return, no backspace — so they skip the cell buffer
    # entirely and only pay one regex scan for stray control bytes.
    if not _NEEDS_RENDER.search(line):
        return _CONTROL_RE.sub("", line), []
    return _render(line)
