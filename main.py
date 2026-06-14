# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Entry point for logulator. Creates QApplication and launches MainWindow."""

# ✝ Soli Deo Gloria

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("logulator")
    app.setDesktopFileName("logulator")

    from app.theme import apply_dark_palette
    apply_dark_palette(app)

    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
