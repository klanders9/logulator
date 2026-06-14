# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Dark application palette (Dracula-aligned) for Linux/GNOME."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_BG      = QColor("#282a36")   # Dracula background — window / panel fill
_BG_ALT  = QColor("#21222c")   # slightly darker — input / base background
_SURFACE = QColor("#44475a")   # Dracula selection — buttons, raised surfaces
_FG      = QColor("#f8f8f2")   # Dracula foreground — primary text
_FG_DIM  = QColor("#6272a4")   # Dracula comment — disabled / placeholder text
_SEL_BG  = QColor("#1a5fa8")   # selection highlight (matches log pane stylesheet)
_SEL_FG  = QColor("#f8f8f2")
_LINK    = QColor("#8be9fd")   # Dracula cyan — hyperlinks (About dialog)
_WHITE   = QColor("#ffffff")


def apply_dark_palette(app: QApplication) -> None:
    """Apply Fusion style + Dracula-aligned QPalette to the QApplication."""
    app.setStyle("Fusion")

    p = QPalette()

    # ---- Active / normal ----
    p.setColor(QPalette.ColorRole.Window,          _BG)
    p.setColor(QPalette.ColorRole.WindowText,      _FG)
    p.setColor(QPalette.ColorRole.Base,            _BG_ALT)
    p.setColor(QPalette.ColorRole.AlternateBase,   _BG)
    p.setColor(QPalette.ColorRole.Text,            _FG)
    p.setColor(QPalette.ColorRole.BrightText,      _WHITE)
    p.setColor(QPalette.ColorRole.Button,          _SURFACE)
    p.setColor(QPalette.ColorRole.ButtonText,      _FG)
    p.setColor(QPalette.ColorRole.Highlight,       _SEL_BG)
    p.setColor(QPalette.ColorRole.HighlightedText, _SEL_FG)
    p.setColor(QPalette.ColorRole.Link,            _LINK)
    p.setColor(QPalette.ColorRole.ToolTipBase,     _SURFACE)
    p.setColor(QPalette.ColorRole.ToolTipText,     _FG)
    p.setColor(QPalette.ColorRole.PlaceholderText, _FG_DIM)

    # ---- 3-D shading (Fusion uses these for button bevels) ----
    p.setColor(QPalette.ColorRole.Light,    QColor("#50536a"))
    p.setColor(QPalette.ColorRole.Midlight, QColor("#44475a"))
    p.setColor(QPalette.ColorRole.Mid,      QColor("#383b4d"))
    p.setColor(QPalette.ColorRole.Dark,     QColor("#21222c"))
    p.setColor(QPalette.ColorRole.Shadow,   QColor("#191a21"))

    # ---- Disabled state ----
    dis = QPalette.ColorGroup.Disabled
    p.setColor(dis, QPalette.ColorRole.WindowText,      _FG_DIM)
    p.setColor(dis, QPalette.ColorRole.Text,            _FG_DIM)
    p.setColor(dis, QPalette.ColorRole.ButtonText,      _FG_DIM)
    p.setColor(dis, QPalette.ColorRole.Highlight,       QColor("#3d4051"))
    p.setColor(dis, QPalette.ColorRole.HighlightedText, _FG_DIM)

    app.setPalette(p)
