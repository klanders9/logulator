# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Dark application palettes (Dracula and VS Code Dark) for all platforms."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ── Dracula ──────────────────────────────────────────────────────────────────
_D_BG      = QColor("#282a36")
_D_BG_ALT  = QColor("#21222c")
_D_SURFACE = QColor("#44475a")
_D_FG      = QColor("#f8f8f2")
_D_FG_DIM  = QColor("#6272a4")
_D_SEL_BG  = QColor("#1a5fa8")
_D_SEL_FG  = QColor("#f8f8f2")
_D_LINK    = QColor("#8be9fd")

# ── VS Code Dark+ ─────────────────────────────────────────────────────────────
_V_BG      = QColor("#252526")   # sidebar / panel bg
_V_BG_ALT  = QColor("#1e1e1e")   # editor bg (darker)
_V_SURFACE = QColor("#3a3d41")   # buttons / raised surfaces
_V_FG      = QColor("#d4d4d4")   # primary text
_V_FG_DIM  = QColor("#858585")   # disabled / placeholder
_V_SEL_BG  = QColor("#264f78")   # editor selection blue
_V_SEL_FG  = QColor("#ffffff")
_V_LINK    = QColor("#4fc1ff")   # VS Code info cyan

_WHITE = QColor("#ffffff")


def _build_dracula() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          _D_BG)
    p.setColor(QPalette.ColorRole.WindowText,      _D_FG)
    p.setColor(QPalette.ColorRole.Base,            _D_BG_ALT)
    p.setColor(QPalette.ColorRole.AlternateBase,   _D_BG)
    p.setColor(QPalette.ColorRole.Text,            _D_FG)
    p.setColor(QPalette.ColorRole.BrightText,      _WHITE)
    p.setColor(QPalette.ColorRole.Button,          _D_SURFACE)
    p.setColor(QPalette.ColorRole.ButtonText,      _D_FG)
    p.setColor(QPalette.ColorRole.Highlight,       _D_SEL_BG)
    p.setColor(QPalette.ColorRole.HighlightedText, _D_SEL_FG)
    p.setColor(QPalette.ColorRole.Link,            _D_LINK)
    p.setColor(QPalette.ColorRole.ToolTipBase,     _D_SURFACE)
    p.setColor(QPalette.ColorRole.ToolTipText,     _D_FG)
    p.setColor(QPalette.ColorRole.PlaceholderText, _D_FG_DIM)
    p.setColor(QPalette.ColorRole.Light,    QColor("#50536a"))
    p.setColor(QPalette.ColorRole.Midlight, QColor("#44475a"))
    p.setColor(QPalette.ColorRole.Mid,      QColor("#383b4d"))
    p.setColor(QPalette.ColorRole.Dark,     QColor("#21222c"))
    p.setColor(QPalette.ColorRole.Shadow,   QColor("#191a21"))
    dis = QPalette.ColorGroup.Disabled
    p.setColor(dis, QPalette.ColorRole.WindowText,      _D_FG_DIM)
    p.setColor(dis, QPalette.ColorRole.Text,            _D_FG_DIM)
    p.setColor(dis, QPalette.ColorRole.ButtonText,      _D_FG_DIM)
    p.setColor(dis, QPalette.ColorRole.Highlight,       QColor("#3d4051"))
    p.setColor(dis, QPalette.ColorRole.HighlightedText, _D_FG_DIM)
    return p


def _build_vscode() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          _V_BG)
    p.setColor(QPalette.ColorRole.WindowText,      _V_FG)
    p.setColor(QPalette.ColorRole.Base,            _V_BG_ALT)
    p.setColor(QPalette.ColorRole.AlternateBase,   _V_BG)
    p.setColor(QPalette.ColorRole.Text,            _V_FG)
    p.setColor(QPalette.ColorRole.BrightText,      _WHITE)
    p.setColor(QPalette.ColorRole.Button,          _V_SURFACE)
    p.setColor(QPalette.ColorRole.ButtonText,      _V_FG)
    p.setColor(QPalette.ColorRole.Highlight,       _V_SEL_BG)
    p.setColor(QPalette.ColorRole.HighlightedText, _V_SEL_FG)
    p.setColor(QPalette.ColorRole.Link,            _V_LINK)
    p.setColor(QPalette.ColorRole.ToolTipBase,     _V_SURFACE)
    p.setColor(QPalette.ColorRole.ToolTipText,     _V_FG)
    p.setColor(QPalette.ColorRole.PlaceholderText, _V_FG_DIM)
    p.setColor(QPalette.ColorRole.Light,    QColor("#4d5054"))
    p.setColor(QPalette.ColorRole.Midlight, QColor("#3a3d41"))
    p.setColor(QPalette.ColorRole.Mid,      QColor("#303336"))
    p.setColor(QPalette.ColorRole.Dark,     QColor("#252526"))
    p.setColor(QPalette.ColorRole.Shadow,   QColor("#1a1a1a"))
    dis = QPalette.ColorGroup.Disabled
    p.setColor(dis, QPalette.ColorRole.WindowText,      _V_FG_DIM)
    p.setColor(dis, QPalette.ColorRole.Text,            _V_FG_DIM)
    p.setColor(dis, QPalette.ColorRole.ButtonText,      _V_FG_DIM)
    p.setColor(dis, QPalette.ColorRole.Highlight,       QColor("#37373d"))
    p.setColor(dis, QPalette.ColorRole.HighlightedText, _V_FG_DIM)
    return p


_BUILDERS = {
    "dracula": _build_dracula,
    "vscode":  _build_vscode,
}


def apply_palette(app: QApplication, theme: str) -> None:
    """Apply Fusion style + the named palette. theme: 'dracula' or 'vscode'."""
    app.setStyle("Fusion")
    builder = _BUILDERS.get(theme, _build_dracula)
    app.setPalette(builder())
