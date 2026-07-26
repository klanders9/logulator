# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Guards that the test suite never touches real user preferences.

This regressed once already: conftest used QSettings.setDefaultFormat(IniFormat),
which does not redirect QSettings(organization, application) on macOS or
Windows. The suite silently read and cleared the developer's real logulator
settings on every run.
"""

from pathlib import Path

from PySide6.QtCore import QSettings

from app.settings import AppSettings


def test_appsettings_writes_to_an_isolated_file(settings):
    settings.set_buffer_cap(4_000)
    backing = Path(settings._qs.fileName())
    assert backing.name != "com.logulator.logulator.plist"
    assert "logulator-pytest" in str(backing)


def test_backing_store_is_not_in_the_real_preferences_directory(settings):
    backing = Path(settings._qs.fileName()).resolve()
    real_prefs = (Path.home() / "Library" / "Preferences").resolve()
    assert real_prefs not in backing.parents, backing


def test_backing_store_is_ini_not_native(settings):
    assert settings._qs.format() == QSettings.Format.IniFormat


def test_every_appsettings_instance_shares_the_isolated_store(settings):
    settings.set_buffer_cap(7_000)
    assert AppSettings().buffer_cap() == 7_000


def test_clear_settings_only_clears_the_isolated_store(settings, clear_settings):
    settings.set_buffer_cap(9_000)
    clear_settings()
    assert AppSettings().buffer_cap() == 100_000  # back to the default
