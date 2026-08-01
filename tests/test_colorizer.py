# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for level detection and line colorization."""

from datetime import datetime, timedelta, timezone

import pytest

from app.colorizer import Colorizer
from app.log_format import (
    MARK_PREFIX,
    TX_PREFIX,
    detect_level,
    format_mark,
    is_generated,
)

ZEPHYR = "[00:00:01.234,567] <inf> my_module: Some message here"
ZEPHYR_NOSPACE = "[2026-07-06 11:21:45.726]<inf> telit_modem: state=0"
SYSLOG_TRAD = "Jun 14 10:23:45 hostname systemd[1]: Started network.target."
SYSLOG_ISO = "2024-06-14T10:23:45.123456+00:00 hostname kernel: message here"


@pytest.fixture
def colorizer(settings, qapp):
    return Colorizer(settings)


def texts(segments):
    return [text for text, _fmt in segments]


def colors(segments):
    return [fmt.foreground().color().name() for _text, fmt in segments]


class TestDetectLevel:
    @pytest.mark.parametrize("tag", ["dbg", "inf", "wrn", "err"])
    def test_explicit_tag(self, tag):
        assert detect_level(f"[00:00:00.000] <{tag}> mod: msg") == tag

    @pytest.mark.parametrize(
        "line,expected",
        [
            ("something failed with an error", "err"),
            ("FATAL condition reached", "err"),
            ("critical failure", "err"),
            ("this is a warning", "wrn"),
            ("WARN: low battery", "wrn"),
            ("info: connected", "inf"),
            ("notice me", "inf"),
            ("debug output here", "dbg"),
            ("trace enabled", "dbg"),
        ],
    )
    def test_keyword_fallback(self, line, expected):
        assert detect_level(line) == expected

    def test_no_level(self):
        assert detect_level("just some plain text") is None

    def test_explicit_tag_wins_over_keyword(self):
        assert detect_level("[0] <dbg> mod: an error occurred") == "dbg"

    def test_err_outranks_wrn_when_both_present(self):
        assert detect_level("error and warning together") == "err"

    def test_keywords_are_word_anchored(self):
        """'errors' must not trip the \\berr\\b / \\berror\\b patterns."""
        assert detect_level("0 errors reported") is None


class TestTxLines:
    def test_tx_color_in_level_mode(self, colorizer, settings):
        settings.set_color_mode("level")
        segs = colorizer.colorize(">> reboot")
        assert texts(segs) == [">> reboot"]
        assert colors(segs) == [settings.tx_color()]

    def test_tx_color_in_syntax_mode(self, colorizer, settings):
        settings.set_color_mode("syntax")
        segs = colorizer.colorize(">> reboot")
        assert colors(segs) == [settings.tx_color()]

    def test_tx_marker_checked_before_zephyr_parsing(self, colorizer, settings):
        """A TX echo of a Zephyr-looking line stays one TX-colored segment."""
        settings.set_color_mode("syntax")
        segs = colorizer.colorize(">> " + ZEPHYR)
        assert len(segs) == 1


class TestMarkFormat:
    WHEN = datetime(2026, 8, 1, 14, 23, 45, tzinfo=timezone.utc)

    def test_shape(self):
        assert format_mark("disconnecting external power", self.WHEN) == (
            ">>>MARK - 2026-08-01T14:23:45Z: disconnecting external power"
        )

    def test_empty_note_leaves_marker_and_time(self):
        assert format_mark("", self.WHEN) == ">>>MARK - 2026-08-01T14:23:45Z"

    def test_whitespace_note_counts_as_empty(self):
        assert format_mark("   ", self.WHEN) == ">>>MARK - 2026-08-01T14:23:45Z"

    def test_note_is_trimmed(self):
        assert format_mark("  power off  ", self.WHEN).endswith(": power off")

    def test_local_time_is_converted_to_utc(self):
        """The point of the timestamp is comparability with other machines."""
        local = datetime(
            2026, 8, 1, 9, 23, 45, tzinfo=timezone(timedelta(hours=-5))
        )
        assert format_mark("x", local).startswith(">>>MARK - 2026-08-01T14:23:45Z")

    def test_default_time_is_now_in_utc(self):
        produced = format_mark("x")
        assert produced.startswith(">>>MARK - ")
        stamp = produced[len(">>>MARK - "):].split(":", 1)[0]
        assert stamp[:4] == datetime.now(timezone.utc).strftime("%Y")

    def test_does_not_collide_with_the_tx_marker(self):
        """Both start with '>>', so the distinction is the third character."""
        line = format_mark("x", self.WHEN)
        assert line.startswith(MARK_PREFIX)
        assert not line.startswith(TX_PREFIX)
        assert is_generated(line) and is_generated(">> reboot")


class TestMarkLines:
    MARK = ">>>MARK - 2026-08-01T14:23:45Z: power cycled"

    @pytest.mark.parametrize("mode", ["level", "syntax"])
    def test_mark_color_in_both_modes(self, colorizer, settings, mode):
        settings.set_color_mode(mode)
        segs = colorizer.colorize(self.MARK)
        assert texts(segs) == [self.MARK]
        assert colors(segs) == [settings.mark_color()]

    def test_mark_is_distinct_from_tx(self, colorizer, settings):
        assert settings.mark_color() != settings.tx_color()
        assert colors(colorizer.colorize(self.MARK)) != colors(
            colorizer.colorize(">> reboot")
        )

    def test_a_note_that_looks_like_a_log_line_stays_one_segment(
        self, colorizer, settings
    ):
        """Checked before any parsing, so an embedded format cannot split it."""
        settings.set_color_mode("syntax")
        segs = colorizer.colorize(">>>MARK - 2026-08-01T14:23:45Z: " + ZEPHYR)
        assert len(segs) == 1

    def test_a_note_mentioning_an_error_keeps_the_mark_color(
        self, colorizer, settings
    ):
        """Keyword level detection must not repaint a mark red."""
        settings.set_color_mode("level")
        segs = colorizer.colorize(">>>MARK - 2026-08-01T14:23:45Z: error injected")
        assert colors(segs) == [settings.mark_color()]


class TestLevelMode:
    def test_whole_line_gets_level_color(self, colorizer, settings):
        settings.set_color_mode("level")
        segs = colorizer.colorize("[0] <err> mod: boom")
        assert len(segs) == 1
        assert colors(segs) == [settings.level_color("err")]

    def test_unleveled_line_is_plain(self, colorizer, settings):
        settings.set_color_mode("level")
        segs = colorizer.colorize("plain text")
        assert colors(segs) == ["#cccccc"]


class TestSyntaxMode:
    @pytest.fixture(autouse=True)
    def _syntax(self, settings):
        settings.set_color_mode("syntax")

    def test_zephyr_splits_into_four_fields(self, colorizer):
        segs = colorizer.colorize(ZEPHYR)
        assert texts(segs) == [
            "[00:00:01.234,567]",
            " <inf>",
            " my_module:",
            " Some message here",
        ]

    def test_zephyr_field_colors(self, colorizer, settings):
        segs = colorizer.colorize(ZEPHYR)
        assert colors(segs) == [
            settings.syntax_color("timestamp"),
            settings.level_color("inf"),
            settings.syntax_color("module"),
            settings.syntax_color("message"),
        ]

    def test_zephyr_full_date_without_space_before_tag(self, colorizer):
        segs = colorizer.colorize(ZEPHYR_NOSPACE)
        assert texts(segs) == [
            "[2026-07-06 11:21:45.726]",
            "<inf>",
            " telit_modem:",
            " state=0",
        ]

    def test_syslog_traditional(self, colorizer):
        segs = colorizer.colorize(SYSLOG_TRAD)
        assert texts(segs)[0] == "Jun 14 10:23:45"
        assert len(segs) == 4

    def test_syslog_iso(self, colorizer):
        segs = colorizer.colorize(SYSLOG_ISO)
        assert texts(segs)[0] == "2024-06-14T10:23:45.123456+00:00"
        assert len(segs) == 4

    def test_syslog_message_takes_level_color_on_keyword(self, colorizer, settings):
        line = "Jun 14 10:23:45 host app[1]: fatal condition"
        segs = colorizer.colorize(line)
        assert colors(segs)[3] == settings.level_color("err")

    def test_unrecognized_line_is_plain(self, colorizer):
        segs = colorizer.colorize("not a log line")
        assert colors(segs) == ["#cccccc"]


def test_colorizer_reads_settings_live(colorizer, settings):
    """Color changes must apply on the next call without rebuilding Colorizer."""
    settings.set_color_mode("level")
    settings.set_level_color("err", "#123456")
    segs = colorizer.colorize("[0] <err> mod: boom")
    assert colors(segs) == ["#123456"]
