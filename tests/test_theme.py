# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the semantic color layer and live theme switching."""

import pytest
from PySide6.QtCore import QSettings

from app import theme
from app.main_window import MainWindow

_KEYS = {
    "plain_text", "muted_text", "header_text", "border", "separator",
    "neutral_band", "error_field", "match_highlight",
    "chip_include", "chip_exclude",
}


@pytest.fixture(autouse=True)
def _clean_settings(_isolate_qsettings):
    QSettings("logulator", "logulator").clear()


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    """Theme state is process-global; put it back after each test."""
    before = theme.active_theme()
    yield
    theme.apply_palette(qapp, before)


class TestColorTable:
    @pytest.mark.parametrize("name", ["dracula", "vscode"])
    def test_every_theme_defines_every_key(self, name):
        assert set(theme.colors(name)) == _KEYS

    def test_unknown_theme_falls_back_to_dracula(self):
        assert theme.colors("solarized") == theme.colors("dracula")

    def test_themes_actually_differ(self):
        assert theme.colors("dracula") != theme.colors("vscode")

    @pytest.mark.parametrize("name", ["dracula", "vscode"])
    def test_values_are_hex_colors(self, name):
        for key, value in theme.colors(name).items():
            assert value.startswith("#") and len(value) == 7, f"{name}.{key}"

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
