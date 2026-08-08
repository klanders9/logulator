# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Entry point for logulator. Creates QApplication and launches MainWindow."""

# ✝ Soli Deo Gloria

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.settings import AppSettings
from app.theme import apply_palette
from app.ui.log_window import retheme_all_windows


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("logulator")
    app.setDesktopFileName("logulator")

    # Applied before any widget exists, so nothing is built with the wrong
    # palette and then repainted.
    settings = AppSettings()
    apply_palette(app, settings.resolved_theme())

    # Under the "System" theme the OS can flip out from under us — at sunset,
    # or on a manual toggle — so follow it rather than waiting for a restart.
    app.styleHints().colorSchemeChanged.connect(
        lambda _scheme: retheme_all_windows(settings.resolved_theme())
    )

    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
