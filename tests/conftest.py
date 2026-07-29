# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Shared pytest fixtures.

Two things matter here:

1. Qt must run headless. QT_QPA_PLATFORM is set before PySide6 is imported.
2. Tests must never touch the developer's real logulator preferences.

The second is easy to get wrong. `QSettings.setDefaultFormat(IniFormat)` does
**not** redirect `QSettings(organization, application)`: on macOS and Windows
that constructor always uses NativeFormat, so it still resolves to
~/Library/Preferences/com.logulator.logulator.plist no matter what the default
format says. Verified:

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings("logulator", "logulator").format()   -> Format.NativeFormat

So instead of setting a default, the QSettings name that app.settings binds is
replaced outright with one that builds an INI-backed store under a temporary
directory. Tests must go through `settings_store()` rather than constructing
`QSettings("logulator", "logulator")` themselves, or they will read and write
the real preferences again.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

from app import settings as settings_module  # noqa: E402
from app.settings import AppSettings  # noqa: E402

# Deliberately not "logulator": if the redirect ever regresses, tests land in
# an obviously-named scratch domain instead of the real one.
_TEST_ORG = "logulator-pytest"
_TEST_APP = "logulator-pytest"


def _test_qsettings(*_args, **_kwargs) -> QSettings:
    return QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, _TEST_ORG, _TEST_APP
    )


@pytest.fixture(scope="session", autouse=True)
def _isolate_qsettings(tmp_path_factory):
    """Point every AppSettings at a throwaway INI store for the whole session."""
    path = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(path)
    )
    real = settings_module.QSettings
    settings_module.QSettings = _test_qsettings
    try:
        yield
    finally:
        settings_module.QSettings = real


@pytest.fixture
def settings_store(_isolate_qsettings) -> QSettings:
    """The raw QSettings behind AppSettings, for tests that need to seed keys."""
    return _test_qsettings()


@pytest.fixture
def clear_settings(settings_store):
    """Wipe the isolated store. Never touches real preferences."""
    def _clear():
        settings_store.clear()
        settings_store.sync()
    return _clear


@pytest.fixture
def settings(clear_settings):
    """A clean AppSettings backed by the isolated store."""
    clear_settings()
    return AppSettings()
