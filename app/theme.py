# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Application palettes — two dark, two light — plus follow-the-OS resolution.

Alongside each QPalette this module owns two colour tables the palette cannot
express: `_THEME_COLORS`, the fixed chrome colours widgets look up, and
`_LOG_DEFAULTS`, the *starting* log colours for a theme. Log colours are
per-theme because a palette tuned for a dark pane and one tuned for a light
pane cannot share them — #f8f8f2 message text is invisible on white.

Settings-free by design: `AppSettings` reads defaults from here, never the
other way round, so `active_colors()` works in any widget without one.
"""

from PySide6.QtCore import Qt
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

# ── VS Code Light+ ────────────────────────────────────────────────────────────
_L_BG      = QColor("#f3f3f3")   # sidebar / panel bg
_L_BG_ALT  = QColor("#ffffff")   # editor bg
_L_SURFACE = QColor("#e4e4e4")   # buttons / raised surfaces
_L_FG      = QColor("#333333")
_L_FG_DIM  = QColor("#a0a0a0")
_L_SEL_BG  = QColor("#add6ff")   # VS Code's own light selection blue
_L_SEL_FG  = QColor("#000000")
_L_LINK    = QColor("#0066bf")

# ── Solarized Light ───────────────────────────────────────────────────────────
# Ethan Schoonover's base tones: base3 #fdf6e3 … base01 #586e75.
_S_BG      = QColor("#eee8d5")   # base2 — panel bg
_S_BG_ALT  = QColor("#fdf6e3")   # base3 — editor bg
_S_SURFACE = QColor("#e0dac4")   # buttons, a shade below base2
_S_FG      = QColor("#586e75")   # base01 — emphasized body text
_S_FG_DIM  = QColor("#93a1a1")   # base1 — de-emphasized
# Solarized itself selects with base2 on base3, which is nearly invisible in a
# log pane, so this departs from the spec for a legible highlight.
_S_SEL_BG  = QColor("#c9dce8")
_S_SEL_FG  = QColor("#073642")   # base02
_S_LINK    = QColor("#268bd2")   # solarized blue

_WHITE = QColor("#ffffff")


def _build(
    bg, bg_alt, surface, fg, fg_dim, sel_bg, sel_fg, link,
    light, midlight, mid, dark, shadow, dis_sel_bg,
) -> QPalette:
    """Assemble a QPalette from one theme's tones.

    The Fusion style draws button bevels from Light/Midlight/Mid/Dark/Shadow,
    so those are set explicitly rather than left to Qt's derivation, which
    guesses badly from a saturated surface colour.
    """
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          bg)
    p.setColor(QPalette.ColorRole.WindowText,      fg)
    p.setColor(QPalette.ColorRole.Base,            bg_alt)
    p.setColor(QPalette.ColorRole.AlternateBase,   bg)
    p.setColor(QPalette.ColorRole.Text,            fg)
    p.setColor(QPalette.ColorRole.BrightText,      _WHITE)
    p.setColor(QPalette.ColorRole.Button,          surface)
    p.setColor(QPalette.ColorRole.ButtonText,      fg)
    p.setColor(QPalette.ColorRole.Highlight,       sel_bg)
    p.setColor(QPalette.ColorRole.HighlightedText, sel_fg)
    p.setColor(QPalette.ColorRole.Link,            link)
    p.setColor(QPalette.ColorRole.ToolTipBase,     surface)
    p.setColor(QPalette.ColorRole.ToolTipText,     fg)
    p.setColor(QPalette.ColorRole.PlaceholderText, fg_dim)
    p.setColor(QPalette.ColorRole.Light,    light)
    p.setColor(QPalette.ColorRole.Midlight, midlight)
    p.setColor(QPalette.ColorRole.Mid,      mid)
    p.setColor(QPalette.ColorRole.Dark,     dark)
    p.setColor(QPalette.ColorRole.Shadow,   shadow)
    dis = QPalette.ColorGroup.Disabled
    p.setColor(dis, QPalette.ColorRole.WindowText,      fg_dim)
    p.setColor(dis, QPalette.ColorRole.Text,            fg_dim)
    p.setColor(dis, QPalette.ColorRole.ButtonText,      fg_dim)
    p.setColor(dis, QPalette.ColorRole.Highlight,       dis_sel_bg)
    p.setColor(dis, QPalette.ColorRole.HighlightedText, fg_dim)
    return p


def _build_dracula() -> QPalette:
    return _build(
        _D_BG, _D_BG_ALT, _D_SURFACE, _D_FG, _D_FG_DIM, _D_SEL_BG, _D_SEL_FG,
        _D_LINK,
        QColor("#50536a"), QColor("#44475a"), QColor("#383b4d"),
        QColor("#21222c"), QColor("#191a21"), QColor("#3d4051"),
    )


def _build_vscode() -> QPalette:
    return _build(
        _V_BG, _V_BG_ALT, _V_SURFACE, _V_FG, _V_FG_DIM, _V_SEL_BG, _V_SEL_FG,
        _V_LINK,
        QColor("#4d5054"), QColor("#3a3d41"), QColor("#303336"),
        QColor("#252526"), QColor("#1a1a1a"), QColor("#37373d"),
    )


def _build_vscode_light() -> QPalette:
    return _build(
        _L_BG, _L_BG_ALT, _L_SURFACE, _L_FG, _L_FG_DIM, _L_SEL_BG, _L_SEL_FG,
        _L_LINK,
        QColor("#ffffff"), QColor("#f0f0f0"), QColor("#d0d0d0"),
        QColor("#bdbdbd"), QColor("#9e9e9e"), QColor("#dcdcdc"),
    )


def _build_solarized_light() -> QPalette:
    return _build(
        _S_BG, _S_BG_ALT, _S_SURFACE, _S_FG, _S_FG_DIM, _S_SEL_BG, _S_SEL_FG,
        _S_LINK,
        QColor("#fdf6e3"), QColor("#f2ecd9"), QColor("#d5cfba"),
        QColor("#c3bda8"), QColor("#a9a390"), QColor("#e0dac4"),
    )


_BUILDERS = {
    "dracula":         _build_dracula,
    "vscode":          _build_vscode,
    "vscode-light":    _build_vscode_light,
    "solarized-light": _build_solarized_light,
}

# Which themes are dark. Used to pick a sensible partner when the app is
# following the OS, and to keep the two "System" sub-choices honest.
_DARK_THEMES = frozenset({"dracula", "vscode"})

SYSTEM = "system"

# Semantic colors for the bits QPalette does not cover: log-pane chrome, the
# minimap's non-severity bands, inline error fields and the filter chips.
# Widgets look these up through active_colors() instead of hardcoding hex, so
# a theme switch changes them too. Keys must exist in every theme.
_THEME_COLORS = {
    "dracula": {
        "plain_text":      "#cccccc",  # log line with no recognised structure
        "muted_text":      "#888888",  # hints, secondary labels
        "header_text":     "#999999",  # pane header labels
        "border":          "#555555",  # pane and minimap edges
        "separator":       "#555555",  # "--- reconnected ---" marker lines
        "neutral_band":    "#444444",  # minimap band, no detectable level
        "error_field":     "#3a0000",  # invalid input background
        "match_highlight": "#443900",  # non-current find match
        "chip_include":    "#3a6a3a",
        "chip_exclude":    "#6a3a3a",
    },
    "vscode": {
        "plain_text":      "#d4d4d4",
        "muted_text":      "#858585",
        "header_text":     "#9d9d9d",
        "border":          "#3c3c3c",
        "separator":       "#4a4a4a",
        "neutral_band":    "#3a3a3a",
        "error_field":     "#5a1d1d",
        "match_highlight": "#515c6a",  # VS Code's own find-match blue-grey
        "chip_include":    "#3c6e3c",
        "chip_exclude":    "#6e3c3c",
    },
    "vscode-light": {
        "plain_text":      "#333333",
        "muted_text":      "#6a6a6a",
        "header_text":     "#616161",
        "border":          "#c8c8c8",
        "separator":       "#b4b4b4",
        "neutral_band":    "#d0d0d0",
        "error_field":     "#f8d7d7",
        "match_highlight": "#fff2b0",  # VS Code's own light find-match yellow
        "chip_include":    "#c7e6c7",
        "chip_exclude":    "#f0cccc",
    },
    "solarized-light": {
        "plain_text":      "#657b83",  # base00 — Solarized's body text
        "muted_text":      "#93a1a1",  # base1
        "header_text":     "#839496",  # base0
        "border":          "#d3cbb7",
        "separator":       "#c5bda8",
        "neutral_band":    "#ddd6c1",
        "error_field":     "#f7dcd8",
        "match_highlight": "#f2e6a8",
        "chip_include":    "#d7dfc0",
        "chip_exclude":    "#f0d8cf",
    },
}

# Starting log colours per theme. These are defaults, not fixed values: the
# sidebar's colour pickers override them per theme, so a customisation made
# against a dark pane does not follow the user onto a light one.
#
# The two dark themes deliberately share the original palette — changing what
# existing users already see is not part of adding light themes.
_DARK_LOG_DEFAULTS = {
    "level_err":        "#ff5555",
    "level_wrn":        "#ffb86c",
    "level_inf":        "#50fa7b",
    "level_dbg":        "#888888",
    "syntax_timestamp": "#666666",
    "syntax_module":    "#bd93f9",
    "syntax_message":   "#f8f8f2",
    "tx":               "#8be9fd",
    "mark":             "#ff79c6",
}

_LOG_DEFAULTS = {
    "dracula": _DARK_LOG_DEFAULTS,
    "vscode":  _DARK_LOG_DEFAULTS,
    # Tuned against a white pane: the dark set's near-white message colour and
    # pale green info colour are unreadable there.
    "vscode-light": {
        "level_err":        "#cd3131",
        "level_wrn":        "#a86a00",
        "level_inf":        "#157f3b",
        # Muted, but still ~5:1 on white — the dark themes' greys drop under
        # 3.5:1 there, which is where debug lines stop being readable at all.
        "level_dbg":        "#6a6a6a",
        "syntax_timestamp": "#767676",
        "syntax_module":    "#6f42c1",
        "syntax_message":   "#24292f",
        "tx":               "#0550ae",
        "mark":             "#a21caf",
    },
    # Solarized's accent colours are specified to work on base3, so they are
    # used as published rather than re-derived. Solarized Light is a low
    # contrast scheme by design — body text sits near 4:1 — and that is left
    # alone: anyone choosing it wants Solarized, and every value here is a
    # default the colour pickers can override. Debug is the one exception,
    # nudged from base1 to base0 because base1 on base3 is only 2.5:1.
    "solarized-light": {
        "level_err":        "#dc322f",  # red
        "level_wrn":        "#cb4b16",  # orange
        "level_inf":        "#859900",  # green
        "level_dbg":        "#839496",  # base0
        "syntax_timestamp": "#93a1a1",
        "syntax_module":    "#6c71c4",  # violet
        "syntax_message":   "#657b83",  # base00
        "tx":               "#268bd2",  # blue
        "mark":             "#d33682",  # magenta
    },
}

_DEFAULT_THEME = "dracula"

# Set by apply_palette so widgets can style themselves without each needing an
# AppSettings instance. _applied distinguishes "Dracula is active" from "no
# palette has been applied yet", which happen to share a name — without it a
# caller that skips redundant applies would skip the very first one.
_active_theme = _DEFAULT_THEME
_applied = False


def colors(theme: str) -> dict:
    """Semantic colors for a named theme (falls back to Dracula)."""
    return _THEME_COLORS.get(theme, _THEME_COLORS[_DEFAULT_THEME])


def theme_names() -> tuple:
    """Every concrete theme, dark first. 'system' is not one of these."""
    return tuple(_BUILDERS)


def is_dark(theme: str) -> bool:
    return theme in _DARK_THEMES


def log_defaults(theme: str) -> dict:
    """Starting log colors for a named theme (falls back to Dracula)."""
    return _LOG_DEFAULTS.get(theme, _LOG_DEFAULTS[_DEFAULT_THEME])


def log_default(theme: str, key: str) -> str:
    """One starting log color, e.g. log_default('vscode-light', 'level_err')."""
    return log_defaults(theme).get(key, colors(theme)["plain_text"])


def system_is_dark() -> bool:
    """Whether the OS is currently asking for a dark UI.

    Qt reports Unknown on platforms with no such notion; that is treated as
    dark, which is what logulator has always been and what a log tool is
    usually run as.
    """
    app = QApplication.instance()
    if app is None:
        return True
    return app.styleHints().colorScheme() != Qt.ColorScheme.Light


def resolve_theme(key: str, dark: str, light: str) -> str:
    """Map a stored theme choice to the palette to actually apply.

    'system' resolves to `dark` or `light` depending on the OS. The pair is
    passed in rather than read here, so this module keeps knowing nothing
    about AppSettings.
    """
    if key == SYSTEM:
        chosen = dark if system_is_dark() else light
        return chosen if chosen in _BUILDERS else _DEFAULT_THEME
    return key if key in _BUILDERS else _DEFAULT_THEME


def active_colors() -> dict:
    """Semantic colors for the theme currently applied."""
    return colors(_active_theme)


def active_theme() -> str:
    return _active_theme


def palette_applied() -> bool:
    """Whether apply_palette has run. See `_applied`."""
    return _applied


def apply_palette(app: QApplication, theme: str) -> None:
    """Apply Fusion style + the named palette.

    `theme` must be a concrete name from theme_names(); callers holding a
    possibly-'system' preference resolve it first (AppSettings.resolved_theme).
    """
    global _active_theme, _applied
    _active_theme = theme if theme in _BUILDERS else _DEFAULT_THEME
    _applied = True
    app.setStyle("Fusion")
    app.setPalette(_BUILDERS[_active_theme]())
