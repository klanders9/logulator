# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Shared pytest fixtures.

Two things matter here:

1. Qt must run headless. QT_QPA_PLATFORM is set before PySide6 is imported.
2. Tests must never touch the developer's real logulator preferences.
   AppSettings goes through QSettings("logulator", "logulator"), so the whole
   session is redirected to a temporary INI tree.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

from app.settings import AppSettings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolate_qsettings(tmp_path_factory):
    """Redirect QSettings to a throwaway directory for the whole session."""
    path = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(path)
    )


@pytest.fixture
def settings(_isolate_qsettings):
    """A clean AppSettings backed by the isolated store."""
    QSettings("logulator", "logulator").clear()
    return AppSettings()
