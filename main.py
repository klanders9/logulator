# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Entry point for logulator. Creates QApplication and launches MainWindow."""

# ✝ Soli Deo Gloria

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.theme import apply_palette


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("logulator")
    app.setDesktopFileName("logulator")

    _qs = QSettings("logulator", "logulator")
    _theme = _qs.value("app/theme", "dracula")
    if _theme not in ("dracula", "vscode"):
        _theme = "dracula"
    apply_palette(app, _theme)

    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
