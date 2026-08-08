# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the semantic color layer and live theme switching."""

import pytest

from app import theme
from app.main_window import MainWindow

_KEYS = {
    "plain_text", "muted_text", "header_text", "border", "separator",
    "neutral_band", "error_field", "match_highlight",
    "chip_include", "chip_exclude",
}


@pytest.fixture(autouse=True)
def _clean_settings(clear_settings):
    clear_settings()


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    """Theme state is process-global; put it back after each test."""
    before = theme.active_theme()
    yield
    theme.apply_palette(qapp, before)


_LOG_KEYS = {
    "level_err", "level_wrn", "level_inf", "level_dbg",
    "syntax_timestamp", "syntax_module", "syntax_message", "tx", "mark",
}


class TestColorTable:
    @pytest.mark.parametrize("name", theme.theme_names())
    def test_every_theme_defines_every_key(self, name):
        assert set(theme.colors(name)) == _KEYS

    @pytest.mark.parametrize("name", theme.theme_names())
    def test_every_theme_defines_every_log_color(self, name):
        assert set(theme.log_defaults(name)) == _LOG_KEYS

    def test_unknown_theme_falls_back_to_dracula(self):
        assert theme.colors("no-such-theme") == theme.colors("dracula")
        assert theme.log_defaults("no-such-theme") == theme.log_defaults("dracula")

    def test_themes_actually_differ(self):
        assert theme.colors("dracula") != theme.colors("vscode")

    def test_light_themes_do_not_reuse_the_dark_log_colors(self):
        """The whole reason log colors became per-theme."""
        dark = theme.log_defaults("dracula")
        for name in ("vscode-light", "solarized-light"):
            assert theme.log_defaults(name) != dark

    @pytest.mark.parametrize("name", theme.theme_names())
    def test_values_are_hex_colors(self, name):
        for key, value in theme.colors(name).items():
            assert value.startswith("#") and len(value) == 7, f"{name}.{key}"
        for key, value in theme.log_defaults(name).items():
            assert value.startswith("#") and len(value) == 7, f"{name}.{key}"

    def test_dark_themes_kept_the_original_log_palette(self):
        """Adding light themes must not restyle what existing users see."""
        assert theme.log_default("dracula", "level_err") == "#ff5555"
        assert theme.log_default("dracula", "syntax_message") == "#f8f8f2"
        assert theme.log_defaults("vscode") == theme.log_defaults("dracula")

    def test_apply_palette_updates_active_colors(self, qapp):
        theme.apply_palette(qapp, "vscode")
        assert theme.active_theme() == "vscode"
        assert theme.active_colors() == theme.colors("vscode")

    def test_unknown_theme_does_not_become_active(self, qapp):
        theme.apply_palette(qapp, "nonsense")
        assert theme.active_theme() == "dracula"


class TestLiveSwitch:
    @pytest.fixture
    def win(self, qtbot):
        w = MainWindow()
        qtbot.addWidget(w)
        w.show()
        yield w
        w.close()

    def test_pane_border_follows_the_theme(self, win):
        win._on_theme_changed("vscode")
        assert theme.colors("vscode")["border"] in win._raw_pane.styleSheet()
        win._on_theme_changed("dracula")
        assert theme.colors("dracula")["border"] in win._raw_pane.styleSheet()

    def test_pane_header_follows_the_theme(self, win):
        win._on_theme_changed("vscode")
        assert theme.colors("vscode")["header_text"] in win._raw_header.styleSheet()

    def test_minimap_border_follows_the_theme(self, win):
        win._on_theme_changed("vscode")
        assert theme.colors("vscode")["border"] in win._minimap.styleSheet()

    def test_plain_line_format_follows_the_theme(self, win):
        win._on_theme_changed("vscode")
        colour = win._plain_fmt.foreground().color().name()
        assert colour == theme.colors("vscode")["plain_text"]

    def test_existing_lines_are_recoloured(self, win):
        win._settings.set_color_enabled(False)
        win._on_new_line("a line with no structure")
        win._on_theme_changed("vscode")

        from PySide6.QtGui import QTextCursor

        cursor = QTextCursor(win._raw_pane.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
        colour = cursor.charFormat().foreground().color().name()
        assert colour == theme.colors("vscode")["plain_text"]

    def test_minimap_neutral_band_follows_the_theme(self, win):
        win._on_theme_changed("vscode")
        band = win._minimap_color_for("nothing notable")
        assert band.name() == theme.colors("vscode")["neutral_band"]

    def test_separator_band_follows_the_theme(self, win):
        win._on_theme_changed("vscode")
        band = win._minimap_color_for("--- reconnected ---")
        assert band.name() == theme.colors("vscode")["separator"]

    def test_switch_reaches_every_open_window(self, win, qtbot):
        other = MainWindow()
        qtbot.addWidget(other)
        other.show()
        try:
            win._on_theme_changed("vscode")
            assert theme.colors("vscode")["border"] in other._raw_pane.styleSheet()
        finally:
            other.close()

    def test_lines_survive_a_theme_switch(self, win):
        lines = ["[00:00:01] <inf> app: one", "[00:00:02] <err> app: two"]
        for line in lines:
            win._on_new_line(line)
        win._on_theme_changed("vscode")
        from app.ui.log_window import iter_block_texts

        assert list(iter_block_texts(win._raw_pane.document())) == lines

    def test_find_no_match_field_follows_the_theme(self, win):
        win._find_bar.show_and_focus()
        win._find_bar._input.setText("nothing matches this")
        win._find._do_search()
        win._on_theme_changed("vscode")
        assert theme.colors("vscode")["error_field"] in win._find_bar._input.styleSheet()

    def test_filter_input_error_follows_the_theme(self, win):
        win._filter_bar._type_combo.setCurrentText("regex")
        win._filter_bar._input.setText("(unclosed")
        win._filter_bar._add_rule()
        win._on_theme_changed("vscode")
        assert theme.colors("vscode")["error_field"] in win._filter_bar._input.styleSheet()

    def test_chips_follow_the_theme(self, win):
        from app.ui.filter_bar import _RuleChip

        win._filter_bar.add_rule("boom", "substring", "include")
        win._on_theme_changed("vscode")
        chip = win._filter_bar._chip_container.findChildren(_RuleChip)[0]
        assert theme.colors("vscode")["chip_include"] in chip.styleSheet()

    def test_a_healthy_find_field_stays_unstyled(self, win):
        win._on_new_line("findable line")
        win._find_bar.show_and_focus()
        win._find_bar._input.setText("findable")
        win._find._do_search()
        win._on_theme_changed("vscode")
        assert win._find_bar._input.styleSheet() == ""


class TestSystemTheme:
    """'System' is a mode, not a palette: it resolves through the OS."""

    def test_resolves_to_the_dark_partner(self, monkeypatch):
        monkeypatch.setattr(theme, "system_is_dark", lambda: True)
        assert theme.resolve_theme(theme.SYSTEM, "vscode", "solarized-light") == (
            "vscode"
        )

    def test_resolves_to_the_light_partner(self, monkeypatch):
        monkeypatch.setattr(theme, "system_is_dark", lambda: False)
        assert theme.resolve_theme(theme.SYSTEM, "vscode", "solarized-light") == (
            "solarized-light"
        )

    def test_a_concrete_choice_ignores_the_os(self, monkeypatch):
        monkeypatch.setattr(theme, "system_is_dark", lambda: False)
        assert theme.resolve_theme("dracula", "vscode", "vscode-light") == "dracula"

    def test_nonsense_resolves_to_the_default(self):
        assert theme.resolve_theme("bogus", "vscode", "vscode-light") == "dracula"

    def test_a_bogus_partner_resolves_to_the_default(self, monkeypatch):
        monkeypatch.setattr(theme, "system_is_dark", lambda: False)
        assert theme.resolve_theme(theme.SYSTEM, "vscode", "bogus") == "dracula"

    def test_unknown_os_scheme_is_treated_as_dark(self, qapp):
        """Qt reports Unknown where the OS has no such notion."""
        from PySide6.QtCore import Qt

        assert qapp.styleHints().colorScheme() in (
            Qt.ColorScheme.Unknown, Qt.ColorScheme.Dark, Qt.ColorScheme.Light
        )
        # Offscreen reports Unknown, which must not be read as "light".
        if qapp.styleHints().colorScheme() == Qt.ColorScheme.Unknown:
            assert theme.system_is_dark() is True

    def test_is_dark_classifies_every_theme(self):
        assert {n for n in theme.theme_names() if theme.is_dark(n)} == {
            "dracula", "vscode"
        }


class TestPaletteApplied:
    def test_reports_applied_after_a_switch(self, qapp):
        theme.apply_palette(qapp, "vscode-light")
        assert theme.palette_applied() is True
        assert theme.active_theme() == "vscode-light"

    def test_light_palettes_are_actually_light(self, qapp):
        """A light theme whose Base stayed dark would be a wiring mistake."""
        for name in ("vscode-light", "solarized-light"):
            theme.apply_palette(qapp, name)
            base = qapp.palette().base().color()
            assert base.lightness() > 200, f"{name} base is {base.name()}"

    def test_dark_palettes_are_actually_dark(self, qapp):
        for name in ("dracula", "vscode"):
            theme.apply_palette(qapp, name)
            assert qapp.palette().base().color().lightness() < 60


class TestDarkToLightSwitch:
    """The case per-theme log colors exist for: a dark pane becoming light."""

    @pytest.fixture
    def win(self, qtbot):
        w = MainWindow()
        qtbot.addWidget(w)
        w.show()
        yield w
        w.close()

    def _level_color_at(self, win, block_index=0):
        from PySide6.QtGui import QTextCursor

        doc = win._raw_pane.document()
        cursor = QTextCursor(doc.findBlockByNumber(block_index))
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
        return cursor.charFormat().foreground().color().name()

    def test_existing_error_lines_take_the_light_palette(self, win):
        win._settings.set_color_mode("level")
        win._on_new_line("[00:00:01.000,000] <err> app: boom")
        assert self._level_color_at(win) == theme.log_default("dracula", "level_err")

        win._settings.set_theme("vscode-light")
        win._on_theme_changed("vscode-light")
        assert self._level_color_at(win) == theme.log_default(
            "vscode-light", "level_err"
        )

    def test_tx_and_mark_lines_follow_too(self, win):
        win._settings.set_theme("solarized-light")
        win._on_theme_changed("solarized-light")
        assert win._settings.tx_color() == theme.log_default(
            "solarized-light", "tx"
        )
        assert win._minimap_color_for(">>>MARK - 2026-08-01T00:00:00Z: x").name() == (
            theme.log_default("solarized-light", "mark")
        )

    def test_a_customization_survives_a_round_trip(self, win):
        win._settings.set_theme("dracula")
        win._on_theme_changed("dracula")
        win._settings.set_level_color("err", "#010203")

        win._settings.set_theme("vscode-light")
        win._on_theme_changed("vscode-light")
        assert win._settings.level_color("err") == "#cd3131"

        win._settings.set_theme("dracula")
        win._on_theme_changed("dracula")
        assert win._settings.level_color("err") == "#010203"

    def test_redundant_switch_is_a_no_op(self, win, qapp, monkeypatch):
        """The OS signal fires even when the resolved theme has not changed."""
        from app.ui import log_window as lw

        theme.apply_palette(qapp, "vscode-light")
        applied = []
        # Patched where log_window bound it, not on theme: the module imported
        # the name, so patching theme.apply_palette would go unnoticed.
        monkeypatch.setattr(lw, "apply_palette", lambda *a: applied.append(a[1]))

        lw.retheme_all_windows("vscode-light")
        assert applied == [], "no work for an unchanged theme"

        lw.retheme_all_windows("dracula")
        assert applied == ["dracula"], "a real change must still be applied"
