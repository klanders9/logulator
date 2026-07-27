# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the settings sidebar controls."""

import pytest
from PySide6.QtTest import QTest

from app.ui.settings_sidebar import SettingsSidebar


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
            sidebar._theme_combo.setCurrentIndex(1)
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
