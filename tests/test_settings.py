# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for AppSettings validation and defaults."""

import pytest


class TestBufferCap:
    def test_default(self, settings):
        assert settings.buffer_cap() == 100_000

    @pytest.mark.parametrize(
        "written,expected",
        [(50, 1_000), (999, 1_000), (1_000, 1_000), (250_000, 250_000),
         (500_000, 500_000), (10_000_000, 500_000)],
    )
    def test_clamped_on_write_and_read(self, settings, written, expected):
        settings.set_buffer_cap(written)
        assert settings.buffer_cap() == expected


class TestValidatedEnums:
    @pytest.mark.parametrize(
        "getter,setter,good,bad,default",
        [
            ("minimap_apply_to", "set_minimap_apply_to", "filtered", "nope", "raw"),
            ("theme", "set_theme", "vscode", "solarized", "dracula"),
            ("serial_parity", "set_serial_parity", "E", "Z", "N"),
            ("serial_stopbits", "set_serial_stopbits", "2", "7", "1"),
            ("serial_flow", "set_serial_flow", "rtscts", "magic", "none"),
            ("tx_line_ending", "set_tx_line_ending", "lf", "wat", "crlf"),
        ],
    )
    def test_accepts_good_rejects_bad(self, settings, getter, setter, good, bad, default):
        assert getattr(settings, getter)() == default
        getattr(settings, setter)(good)
        assert getattr(settings, getter)() == good
        getattr(settings, setter)(bad)
        assert getattr(settings, getter)() == good, "invalid value must not be stored"

    @pytest.mark.xfail(
        strict=True,
        reason="set_color_mode/set_color_apply_to write unvalidated, unlike every "
               "other enum setter; the getter then falls back to the default and "
               "the previous valid value is lost",
    )
    @pytest.mark.parametrize(
        "getter,setter,good,bad",
        [
            ("color_mode", "set_color_mode", "syntax", "sideways"),
            ("color_apply_to", "set_color_apply_to", "raw", "elsewhere"),
        ],
    )
    def test_color_setters_reject_bad_values(self, settings, getter, setter, good, bad):
        getattr(settings, setter)(good)
        getattr(settings, setter)(bad)
        assert getattr(settings, getter)() == good

    def test_databits(self, settings):
        assert settings.serial_databits() == 8
        settings.set_serial_databits(7)
        assert settings.serial_databits() == 7
        settings.set_serial_databits(99)
        assert settings.serial_databits() == 7

    def test_font_size(self, settings):
        assert settings.font_size() == 12
        settings.set_font_size(18)
        assert settings.font_size() == 18
        settings.set_font_size(13579)
        assert settings.font_size() == 18


class TestRecentFiles:
    def test_starts_empty(self, settings):
        assert settings.recent_files() == []

    def test_most_recent_first(self, settings):
        settings.add_recent_file("/a.log")
        settings.add_recent_file("/b.log")
        assert settings.recent_files() == ["/b.log", "/a.log"]

    def test_deduplicates_and_promotes(self, settings):
        settings.add_recent_file("/a.log")
        settings.add_recent_file("/b.log")
        settings.add_recent_file("/a.log")
        assert settings.recent_files() == ["/a.log", "/b.log"]

    def test_capped_at_ten(self, settings):
        for i in range(15):
            settings.add_recent_file(f"/log{i}.log")
        recent = settings.recent_files()
        assert len(recent) == 10
        assert recent[0] == "/log14.log"

    def test_accepts_path_objects(self, settings, tmp_path):
        settings.add_recent_file(tmp_path / "x.log")
        assert settings.recent_files() == [str(tmp_path / "x.log")]

    def test_corrupt_json_reads_as_empty(self, settings):
        settings._qs.setValue("files/recent", "{not json")
        assert settings.recent_files() == []


class TestBooleans:
    @pytest.mark.parametrize(
        "getter,setter,default",
        [
            ("sidebar_open", "set_sidebar_open", False),
            ("color_enabled", "set_color_enabled", True),
            ("minimap_enabled", "set_minimap_enabled", False),
            ("auto_reconnect", "set_auto_reconnect", False),
            ("serial_dtr", "set_serial_dtr", True),
            ("serial_rts", "set_serial_rts", True),
        ],
    )
    def test_roundtrip(self, settings, getter, setter, default):
        assert getattr(settings, getter)() is default
        getattr(settings, setter)(not default)
        assert getattr(settings, getter)() is (not default)


class TestColors:
    def test_level_defaults(self, settings):
        assert settings.level_color("err") == "#ff5555"
        assert settings.level_color("dbg") == "#888888"

    def test_unknown_level_falls_back(self, settings):
        assert settings.level_color("bogus") == "#cccccc"

    def test_syntax_defaults(self, settings):
        assert settings.syntax_color("module") == "#bd93f9"

    def test_tx_default_and_roundtrip(self, settings):
        assert settings.tx_color() == "#8be9fd"
        settings.set_tx_color("#010203")
        assert settings.tx_color() == "#010203"


class TestLogDir:
    def test_defaults_to_home_logs(self, settings):
        from pathlib import Path

        assert settings.log_dir() == str(Path.home() / "logs")

    def test_roundtrip(self, settings, tmp_path):
        settings.set_log_dir(str(tmp_path / "elsewhere"))
        assert settings.log_dir() == str(tmp_path / "elsewhere")

    def test_empty_value_restores_the_default(self, settings, tmp_path):
        from pathlib import Path

        settings.set_log_dir(str(tmp_path))
        settings.set_log_dir("")
        assert settings.log_dir() == str(Path.home() / "logs")

    def test_whitespace_is_treated_as_unset(self, settings):
        from pathlib import Path

        settings.set_log_dir("   ")
        assert settings.log_dir() == str(Path.home() / "logs")
