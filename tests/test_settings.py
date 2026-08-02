# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for AppSettings validation and defaults."""

import pytest

from app import theme
from app.settings import AppSettings


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
            ("color_mode", "set_color_mode", "syntax", "sideways", "level"),
            ("color_apply_to", "set_color_apply_to", "raw", "elsewhere", "all"),
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


class TestLogPrefix:
    def test_defaults_to_session(self, settings):
        assert settings.log_prefix() == "session_"

    def test_roundtrip(self, settings):
        settings.set_log_prefix("featureA_")
        assert settings.log_prefix() == "featureA_"

    def test_empty_is_kept_rather_than_defaulted(self, settings):
        """Unlike log_dir, a bare timestamp is a valid choice, not an unset."""
        settings.set_log_prefix("")
        assert settings.log_prefix() == ""


class TestTxEchoEmpty:
    def test_off_by_default(self, settings):
        assert settings.tx_echo_empty() is False

    def test_roundtrip(self, settings):
        settings.set_tx_echo_empty(True)
        assert settings.tx_echo_empty() is True
        settings.set_tx_echo_empty(False)
        assert settings.tx_echo_empty() is False


class TestAnsiMode:
    def test_defaults_to_strip(self, settings):
        assert settings.ansi_mode() == "strip"

    @pytest.mark.parametrize("value", ["strip", "render", "off"])
    def test_round_trips_valid_values(self, settings, value):
        settings.set_ansi_mode(value)
        assert settings.ansi_mode() == value

    def test_rejects_unknown_values(self, settings):
        settings.set_ansi_mode("render")
        settings.set_ansi_mode("technicolor")
        assert settings.ansi_mode() == "render"

    def test_falls_back_when_the_store_holds_junk(self, settings):
        settings._qs.setValue("display/ansi_mode", "technicolor")
        assert settings.ansi_mode() == "strip"


class TestPerThemeLogColors:
    """Log colors are stored per theme — a dark choice must not follow you."""

    def test_defaults_come_from_the_active_theme(self, settings):
        settings.set_theme("dracula")
        assert settings.level_color("err") == "#ff5555"
        settings.set_theme("vscode-light")
        assert settings.level_color("err") == theme.log_default(
            "vscode-light", "level_err"
        )

    def test_an_override_is_scoped_to_its_theme(self, settings):
        settings.set_theme("dracula")
        settings.set_level_color("err", "#123456")
        settings.set_theme("solarized-light")
        assert settings.level_color("err") != "#123456"
        settings.set_theme("dracula")
        assert settings.level_color("err") == "#123456"

    @pytest.mark.parametrize(
        "getter, setter",
        [
            ("tx_color", "set_tx_color"),
            ("mark_color", "set_mark_color"),
        ],
    )
    def test_tx_and_mark_are_per_theme_too(self, settings, getter, setter):
        settings.set_theme("dracula")
        getattr(settings, setter)("#abcdef")
        settings.set_theme("vscode-light")
        assert getattr(settings, getter)() != "#abcdef"

    def test_syntax_colors_are_per_theme(self, settings):
        settings.set_theme("dracula")
        settings.set_syntax_color("message", "#111111")
        settings.set_theme("vscode-light")
        assert settings.syntax_color("message") == theme.log_default(
            "vscode-light", "syntax_message"
        )

    def test_system_theme_uses_the_resolved_palette(self, settings, monkeypatch):
        """Following the OS into light mode must bring the light colors."""
        settings.set_theme(theme.SYSTEM)
        settings.set_system_dark_theme("dracula")
        settings.set_system_light_theme("vscode-light")

        monkeypatch.setattr(theme, "system_is_dark", lambda: True)
        assert settings.level_color("err") == theme.log_default(
            "dracula", "level_err"
        )
        monkeypatch.setattr(theme, "system_is_dark", lambda: False)
        assert settings.level_color("err") == theme.log_default(
            "vscode-light", "level_err"
        )


class TestSystemThemePair:
    def test_defaults(self, settings):
        assert settings.system_dark_theme() == "dracula"
        assert settings.system_light_theme() == "vscode-light"

    def test_roundtrip(self, settings):
        settings.set_system_dark_theme("vscode")
        settings.set_system_light_theme("solarized-light")
        assert settings.system_dark_theme() == "vscode"
        assert settings.system_light_theme() == "solarized-light"

    def test_a_light_theme_is_rejected_as_the_dark_partner(self, settings):
        settings.set_system_dark_theme("vscode-light")
        assert settings.system_dark_theme() == "dracula"

    def test_a_dark_theme_is_rejected_as_the_light_partner(self, settings):
        settings.set_system_light_theme("dracula")
        assert settings.system_light_theme() == "vscode-light"

    def test_system_is_a_valid_theme_choice(self, settings):
        settings.set_theme(theme.SYSTEM)
        assert settings.theme() == theme.SYSTEM

    def test_every_concrete_theme_is_accepted(self, settings):
        for name in theme.theme_names():
            settings.set_theme(name)
            assert settings.theme() == name


class TestLogColorMigration:
    """Colors customized before the per-theme split must not be lost."""

    def test_old_keys_move_into_the_active_theme(self, settings_store, clear_settings):
        clear_settings()
        settings_store.setValue("app/theme", "vscode")
        settings_store.setValue("color/level_err", "#abcdef")
        settings_store.setValue("color/tx", "#fedcba")
        settings_store.sync()

        s = AppSettings()
        assert s.level_color("err") == "#abcdef"
        assert s.tx_color() == "#fedcba"

    def test_migrated_keys_are_removed(self, settings_store, clear_settings):
        clear_settings()
        settings_store.setValue("color/level_err", "#abcdef")
        settings_store.sync()
        AppSettings()
        settings_store.sync()
        assert not settings_store.value("color/level_err", "")

    def test_other_themes_keep_their_own_defaults(
        self, settings_store, clear_settings
    ):
        """The old value was chosen against one background, not all of them."""
        clear_settings()
        settings_store.setValue("app/theme", "dracula")
        settings_store.setValue("color/level_err", "#abcdef")
        settings_store.sync()

        s = AppSettings()
        s.set_theme("vscode-light")
        assert s.level_color("err") == theme.log_default("vscode-light", "level_err")

    def test_migration_runs_once(self, settings_store, clear_settings):
        """A later customization must not be clobbered by a re-run."""
        clear_settings()
        settings_store.setValue("color/level_err", "#abcdef")
        settings_store.sync()
        AppSettings()

        s = AppSettings()
        s.set_level_color("err", "#999999")
        AppSettings()  # a third window opening must not undo that
        assert AppSettings().level_color("err") == "#999999"

    def test_untouched_settings_migrate_cleanly(self, settings, clear_settings):
        clear_settings()
        s = AppSettings()
        assert s.level_color("err") == theme.log_default("dracula", "level_err")
