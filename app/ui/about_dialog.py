# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""About dialog for logulator."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from app.version import __version__

_REPO_URL = "https://github.com/klanders9/logulator"
_ICON_PATH = Path(__file__).parent.parent.parent / "icon.png"


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Logulator")
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        if _ICON_PATH.exists():
            icon_label = QLabel()
            pixmap = QPixmap(str(_ICON_PATH)).scaled(
                64, 64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_label.setPixmap(pixmap)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        name_label = QLabel("Logulator")
        name_font = QFont(name_label.font())
        name_font.setBold(True)
        name_font.setPointSize(name_font.pointSize() + 4)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        version_label = QLabel(f"Version {__version__}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        desc_label = QLabel("A cross-platform serial log viewer and analyzer.")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        copyright_label = QLabel("Copyright © 2026 Kevin Landers")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_label.setStyleSheet("color: #888888;")
        layout.addWidget(copyright_label)

        license_label = QLabel("License: MIT")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(license_label)

        link_label = QLabel(f'<a href="{_REPO_URL}">GitHub Repository</a>')
        link_label.setOpenExternalLinks(True)
        link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(link_label)

        sdg_label = QLabel("† Soli Deo Gloria")
        sdg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sdg_label.setStyleSheet("color: #888888; font-style: italic;")
        layout.addWidget(sdg_label)

        layout.addSpacing(4)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
