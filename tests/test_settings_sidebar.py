# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the settings sidebar controls."""

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from app import theme
from app.ui.settings_sidebar import SettingsSidebar


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    """Theme state is process-global; put it back after each test."""
    before = theme.active_theme()
    yield
    theme.apply_palette(qapp, before)


@pytest.fixture
def sidebar(qtbot, settings):
    w = SettingsSidebar(settings)
    qtbot.addWidget(w)
    return w


class TestBufferCapSpin:
    def test_typing_emits_only_the_final_value(self, sidebar, qtbot):
        """Intermediate keystrokes must not reach the panes.

        LogPane.set_cap trims immediately and irreversibly, so an intermediate
        2,500 while typing 250000 would throw away most of the buffer that the
        user was trying to enlarge.
        """
        fired = []
        sidebar.buffer_cap_changed.connect(fired.append)
        sidebar._cap_spin.clear()
        QTest.keyClicks(sidebar._cap_spin, "250000")
        assert fired == []

        sidebar._cap_spin.editingFinished.emit()
        sidebar._cap_spin.interpretText()
        assert fired == [250_000]

    def test_keyboard_tracking_is_off(self, sidebar):
        assert sidebar._cap_spin.keyboardTracking() is False

    def test_programmatic_change_still_emits(self, sidebar):
        fired = []
        sidebar.buffer_cap_changed.connect(fired.append)
        sidebar._cap_spin.setValue(42_000)
        assert fired == [42_000]

    def test_value_is_persisted(self, sidebar, settings):
        sidebar._cap_spin.setValue(7_000)
        assert settings.buffer_cap() == 7_000

    def test_range_matches_the_settings_clamp(self, sidebar):
        assert sidebar._cap_spin.minimum() == 1_000
        assert sidebar._cap_spin.maximum() == 500_000

    def test_initial_value_comes_from_settings(self, qtbot, settings):
        settings.set_buffer_cap(33_000)
        w = SettingsSidebar(settings)
        qtbot.addWidget(w)
        assert w._cap_spin.value() == 33_000


class TestLogDir:
    def test_label_shows_the_current_directory(self, sidebar, settings):
        assert sidebar._log_dir_label.text() == settings.log_dir()

    def test_label_updates_after_a_pick(self, sidebar, settings, tmp_path, monkeypatch):
        from app.ui import settings_sidebar as mod

        monkeypatch.setattr(
            mod.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
        )
        sidebar._on_pick_log_dir()
        assert settings.log_dir() == str(tmp_path)
        assert sidebar._log_dir_label.text() == str(tmp_path)

    def test_cancelling_the_picker_changes_nothing(self, sidebar, settings, monkeypatch):
        from app.ui import settings_sidebar as mod

        before = settings.log_dir()
        monkeypatch.setattr(
            mod.QFileDialog, "getExistingDirectory", lambda *a, **k: ""
        )
        sidebar._on_pick_log_dir()
        assert settings.log_dir() == before


class TestOtherControls:
    def test_theme_change_persists_and_emits(self, sidebar, settings, qtbot):
        with qtbot.waitSignal(sidebar.theme_changed) as blocker:
            sidebar._theme_combo.setCurrentText("VS Code Dark")
        assert blocker.args == ["vscode"]
        assert settings.theme() == "vscode"

    def test_font_size_change_persists_and_emits(self, sidebar, settings, qtbot):
        with qtbot.waitSignal(sidebar.font_size_changed) as blocker:
            sidebar._font_combo.setCurrentText("18")
        assert blocker.args == [18]
        assert settings.font_size() == 18

    def test_colorization_toggle_emits_settings_changed(self, sidebar, settings, qtbot):
        with qtbot.waitSignal(sidebar.settings_changed):
            sidebar._enable_cb.setChecked(not settings.color_enabled())

    def test_minimap_toggle_persists(self, sidebar, settings, qtbot):
        with qtbot.waitSignal(sidebar.settings_changed):
            sidebar._minimap_cb.setChecked(True)
        assert settings.minimap_enabled() is True


class TestEchoBlankSends:
    def test_unchecked_by_default(self, sidebar, settings):
        assert sidebar._echo_empty_cb.isChecked() is False
        assert settings.tx_echo_empty() is False

    def test_toggle_persists(self, sidebar, settings):
        sidebar._echo_empty_cb.setChecked(True)
        assert settings.tx_echo_empty() is True

    def test_reflects_the_stored_value(self, qtbot, settings):
        settings.set_tx_echo_empty(True)
        w = SettingsSidebar(settings)
        qtbot.addWidget(w)
        assert w._echo_empty_cb.isChecked() is True

    def test_does_not_trigger_a_pane_rebuild(self, sidebar, qtbot):
        """MainWindow reads the flag per send, so no rebuild is needed."""
        fired = []
        sidebar.settings_changed.connect(lambda: fired.append(1))
        sidebar._echo_empty_cb.setChecked(True)
        assert fired == []


class TestAnsiMode:
    def test_defaults_to_strip(self, sidebar, settings):
        assert sidebar._ansi_combo.currentText() == "Strip"
        assert settings.ansi_mode() == "strip"

    def test_change_persists_and_emits(self, sidebar, settings, qtbot):
        with qtbot.waitSignal(sidebar.settings_changed):
            sidebar._ansi_combo.setCurrentIndex(1)
        assert settings.ansi_mode() == "render"

    def test_reflects_the_stored_value(self, qtbot, settings):
        settings.set_ansi_mode("off")
        w = SettingsSidebar(settings)
        qtbot.addWidget(w)
        assert w._ansi_combo.currentText() == "Show raw"


class TestMarkColorRow:
    def test_mark_color_row_is_present(self, sidebar):
        labels = [
            w.text()
            for w in sidebar.findChildren(QLabel)
            if w.text().startswith("Mark lines")
        ]
        assert labels, "the mark color must be configurable like the TX color"

    def test_default_is_distinct_from_tx(self, settings):
        assert settings.mark_color() != settings.tx_color()


class TestThemeChoices:
    def test_system_is_offered_first(self, sidebar):
        assert sidebar._theme_combo.itemText(0) == "System"
        assert sidebar._theme_combo.count() == 5

    # isVisibleTo, not isVisible: the fixture never shows the sidebar, so Qt's
    # composed visibility would report False either way.
    def test_system_pair_is_hidden_for_a_concrete_theme(self, sidebar):
        assert not sidebar._system_pair.isVisibleTo(sidebar)

    def test_system_pair_appears_when_system_is_chosen(self, sidebar, settings):
        sidebar._theme_combo.setCurrentText("System")
        assert settings.theme() == "system"
        assert sidebar._system_pair.isVisibleTo(sidebar)

    def test_system_pair_hides_again_for_a_concrete_theme(self, sidebar):
        sidebar._theme_combo.setCurrentText("System")
        sidebar._theme_combo.setCurrentText("Dracula")
        assert not sidebar._system_pair.isVisibleTo(sidebar)

    def test_choosing_system_emits_a_concrete_theme(self, sidebar, qtbot):
        """Windows apply a palette, so the SYSTEM sentinel must not escape."""
        from app import theme

        with qtbot.waitSignal(sidebar.theme_changed) as blocker:
            sidebar._theme_combo.setCurrentText("System")
        assert blocker.args[0] in theme.theme_names()

    def test_pair_choice_persists(self, sidebar, settings):
        sidebar._theme_combo.setCurrentText("System")
        sidebar._light_combo.setCurrentText("Solarized Light")
        assert settings.system_light_theme() == "solarized-light"

    def test_light_partner_list_offers_only_light_themes(self, sidebar):
        labels = [
            sidebar._light_combo.itemText(i)
            for i in range(sidebar._light_combo.count())
        ]
        assert labels == ["VS Code Light", "Solarized Light"]

    def test_reflects_a_stored_system_choice(self, qtbot, settings):
        settings.set_theme("system")
        w = SettingsSidebar(settings)
        qtbot.addWidget(w)
        assert w._theme_combo.currentText() == "System"
        assert w._system_pair.isVisibleTo(w)


class TestSwatchRefresh:
    def test_swatches_repaint_for_the_new_theme(self, sidebar, settings, qapp):
        """Log colors are per theme, so every swatch changes with the theme."""
        from app import theme

        before = sidebar._swatches[0][1]()
        settings.set_theme("solarized-light")
        theme.apply_palette(qapp, "solarized-light")
        sidebar.restyle()
        after = sidebar._swatches[0][1]()
        assert before != after
        assert after in sidebar._swatches[0][0].styleSheet()

    def test_every_color_row_is_tracked(self, sidebar):
        # 4 levels + 3 syntax fields + TX + mark
        assert len(sidebar._swatches) == 9


class TestHeadingRestyle:
    """Headings bake their colour into a stylesheet, so a switch must reach it."""

    def _heading(self, sidebar, text):
        for label, _section in sidebar._headings:
            if label.text() == text:
                return label
        raise AssertionError(f"no heading {text!r}")

    def test_sections_and_subsections_share_a_colour(self, sidebar):
        section = self._heading(sidebar, "Appearance").styleSheet()
        subsection = self._heading(sidebar, "Level colors").styleSheet()
        colour = theme.active_colors()["header_text"]
        assert f"color: {colour}" in section
        assert f"color: {colour}" in subsection

    def test_headings_follow_a_theme_switch(self, sidebar, qapp):
        """The reported glitch: subsections kept the start-up theme's grey."""
        theme.apply_palette(qapp, "solarized-light")
        sidebar.restyle()
        colour = theme.colors("solarized-light")["header_text"]
        for text in ("Appearance", "Display", "Level colors", "Marks"):
            assert f"color: {colour}" in self._heading(sidebar, text).styleSheet(), (
                f"{text} kept a stale colour"
            )

    def test_section_rule_follows_the_theme(self, sidebar, qapp):
        theme.apply_palette(qapp, "vscode-light")
        sidebar.restyle()
        border = theme.colors("vscode-light")["border"]
        assert f"1px solid {border}" in self._heading(sidebar, "Display").styleSheet()

    def test_both_heading_levels_are_tracked(self, sidebar):
        kinds = {section for _lbl, section in sidebar._headings}
        assert kinds == {True, False}
