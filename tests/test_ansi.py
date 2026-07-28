# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the ANSI/VT100 escape sequence parser."""

import pytest

from app import ansi
from app.colorizer import _ZEPHYR_RE
from app.filter_engine import match
from app.log_format import detect_level, module_of

# Zephyr with CONFIG_LOG_BACKEND_SHOW_COLOR: the whole line is wrapped.
ZEPHYR_WRAPPED = "\x1b[1;31m[00:00:01.234,567] <err> modem: init failed: -5\x1b[0m"
# The other shape seen in the wild: only the level tag is coloured.
ZEPHYR_TAG_ONLY = "[00:00:01.234,567] \x1b[1;33m<wrn>\x1b[0m modem: retrying"


class TestStrip:
    def test_removes_sgr_colour(self):
        assert ansi.strip(ZEPHYR_WRAPPED) == (
            "[00:00:01.234,567] <err> modem: init failed: -5"
        )

    def test_removes_cursor_control(self):
        assert ansi.strip("\x1b[2J\x1b[Huart:~$ \x1b[Kversion") == "uart:~$ version"

    def test_removes_osc_title(self):
        assert ansi.strip("\x1b]0;my board\x07ready") == "ready"

    def test_removes_charset_selection(self):
        assert ansi.strip("\x1b(Bplain") == "plain"

    def test_removes_stray_control_bytes(self):
        assert ansi.strip("a\x08b\x07c\x7f") == "abc"

    def test_keeps_tabs(self):
        """A tab is content in a log line, not terminal chatter."""
        assert ansi.strip("col1\tcol2") == "col1\tcol2"

    def test_leaves_ordinary_lines_alone(self):
        line = "[00:00:02.000,000] <inf> app: hello"
        assert ansi.strip(line) == line

    def test_handles_a_trailing_lone_escape(self):
        """A sequence split across two reads leaves a bare ESC at the end."""
        assert ansi.strip("text\x1b") == "text"


class TestHasEscapes:
    @pytest.mark.parametrize(
        "line", [ZEPHYR_WRAPPED, "\x1b[2J", "\x1b]0;t\x07", "a\x08b"]
    )
    def test_true(self, line):
        assert ansi.has_escapes(line) is True

    @pytest.mark.parametrize("line", ["", "plain text", "col1\tcol2"])
    def test_false(self, line):
        assert ansi.has_escapes(line) is False


class TestParseSpans:
    def test_whole_line_colour(self):
        text, spans = ansi.parse(ZEPHYR_WRAPPED)
        assert text == "[00:00:01.234,567] <err> modem: init failed: -5"
        assert len(spans) == 1
        start, length, style = spans[0]
        assert (start, length) == (0, len(text))
        assert style.color == "#ff5555"
        assert style.bold is True

    def test_span_covers_only_the_coloured_run(self):
        text, spans = ansi.parse(ZEPHYR_TAG_ONLY)
        assert text == "[00:00:01.234,567] <wrn> modem: retrying"
        assert len(spans) == 1
        start, length, _ = spans[0]
        assert text[start:start + length] == "<wrn>"

    def test_no_spans_without_colour(self):
        """Cursor control alone must not make the line look coloured."""
        text, spans = ansi.parse("\x1b[2J\x1b[Huart:~$ ")
        assert text == "uart:~$ "
        assert spans == []

    def test_reset_ends_a_span(self):
        text, spans = ansi.parse("\x1b[31mred\x1b[0mplain")
        assert text == "redplain"
        assert [(s, ln) for s, ln, _ in spans] == [(0, 3)]

    def test_bare_reset_sequence_ends_a_span(self):
        """ESC[m is SGR 0 with the parameter omitted."""
        _, spans = ansi.parse("\x1b[31mred\x1b[mplain")
        assert [(s, ln) for s, ln, _ in spans] == [(0, 3)]

    def test_unterminated_colour_runs_to_end_of_line(self):
        text, spans = ansi.parse("\x1b[32mgreen to the end")
        assert spans[0][:2] == (0, len(text))

    def test_bright_foreground(self):
        _, spans = ansi.parse("\x1b[92mbright")
        assert spans[0][2].color == "#69ff94"

    def test_indexed_256_colour(self):
        _, spans = ansi.parse("\x1b[38;5;208morange")
        assert spans[0][2].color == "#ff8700"

    def test_truecolour(self):
        _, spans = ansi.parse("\x1b[38;2;10;200;30mgreenish")
        assert spans[0][2].color == "#0ac81e"

    def test_background_is_consumed_but_not_rendered(self):
        """48;5;n must not be mistaken for a foreground request."""
        text, spans = ansi.parse("\x1b[48;5;208mon orange")
        assert text == "on orange"
        assert spans == []

    def test_italic_and_underline(self):
        _, spans = ansi.parse("\x1b[3;4mfancy")
        style = spans[0][2]
        assert (style.italic, style.underline) == (True, True)

    def test_underline_off_splits_the_run(self):
        text, spans = ansi.parse("\x1b[4;92mlink\x1b[24m tail")
        assert text == "link tail"
        assert [(s, ln, st.underline) for s, ln, st in spans] == [
            (0, 4, True),
            (4, 5, False),
        ]

    def test_style_carries_across_a_second_sgr(self):
        """SGR is cumulative: setting bold later keeps the colour."""
        _, spans = ansi.parse("\x1b[31mred\x1b[1mbold red")
        assert [st.color for _, _, st in spans] == ["#ff5555", "#ff5555"]
        assert [st.bold for _, _, st in spans] == [False, True]

    def test_spans_index_into_the_cleaned_text(self):
        """The whole point: offsets must survive removal of earlier escapes."""
        text, spans = ansi.parse("\x1b[2Jabc\x1b[31mred")
        start, length, _ = spans[0]
        assert text[start:start + length] == "red"

    def test_empty_line(self):
        assert ansi.parse("") == ("", [])

    def test_text_matches_strip(self):
        for line in (ZEPHYR_WRAPPED, ZEPHYR_TAG_ONLY, "\x1b[2Ja\x08b", "plain"):
            assert ansi.parse(line)[0] == ansi.strip(line)


class TestDownstreamParsersRecover:
    """Escapes break the line-structure parsers; stripping is what fixes them.

    These are the regressions that motivated the module, not just the
    cosmetics — they fail on the raw line and pass on the cleaned one.
    """

    @pytest.mark.parametrize("line", [ZEPHYR_WRAPPED, ZEPHYR_TAG_ONLY])
    def test_zephyr_syntax_regex(self, line):
        assert _ZEPHYR_RE.match(line) is None
        assert _ZEPHYR_RE.match(ansi.strip(line)) is not None

    def test_module_detection(self):
        assert module_of(ZEPHYR_TAG_ONLY) is None
        assert module_of(ansi.strip(ZEPHYR_TAG_ONLY)) == "modem"

    def test_module_filter_rule(self):
        rule = [{"type": "module", "value": "modem", "mode": "include"}]
        assert match(ZEPHYR_TAG_ONLY, rule, "OR") is False
        assert match(ansi.strip(ZEPHYR_TAG_ONLY), rule, "OR") is True

    def test_level_detection_already_worked(self):
        """detect_level searches rather than anchors, so it was never broken."""
        assert detect_level(ZEPHYR_WRAPPED) == "err"
