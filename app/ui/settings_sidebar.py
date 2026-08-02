# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Collapsible right-side settings sidebar."""

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.settings import AppSettings
from app.theme import SYSTEM, active_colors

_APPLY_LABELS = ["All panes", "Raw log only", "Filtered log only", "None"]
_APPLY_VALUES = ["all", "raw", "filtered", "none"]

_THEME_LABELS = [
    "System", "Dracula", "VS Code Dark", "VS Code Light", "Solarized Light",
]
_THEME_VALUES = [
    SYSTEM, "dracula", "vscode", "vscode-light", "solarized-light",
]

# The pair "System" chooses between. Split so each list only offers themes of
# the right polarity — picking a dark theme as the light partner is never what
# anyone means.
_DARK_LABELS = ["Dracula", "VS Code Dark"]
_DARK_VALUES = ["dracula", "vscode"]
_LIGHT_LABELS = ["VS Code Light", "Solarized Light"]
_LIGHT_VALUES = ["vscode-light", "solarized-light"]

_MINIMAP_APPLY_LABELS = ["Both panes", "Raw only", "Filtered only"]
_MINIMAP_APPLY_VALUES = ["all", "raw", "filtered"]

_ANSI_LABELS = ["Strip", "Render colors", "Show raw"]
_ANSI_VALUES = ["strip", "render", "off"]


_FONT_SIZES = ["8", "9", "10", "11", "12", "13", "14", "16", "18", "20", "24"]


def _paint_swatch(swatch: QLabel, hex_color: str) -> None:
    swatch.setStyleSheet(
        f"background-color: {hex_color}; "
        f"border: 1px solid {active_colors()['border']};"
    )


class SettingsSidebar(QWidget):
    settings_changed = Signal()
    buffer_cap_changed = Signal(int)
    theme_changed = Signal(str)
    font_size_changed = Signal(int)

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._s = settings
        self._swatches = []
        self.setFixedWidth(280)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(self._section_label("Appearance"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(_THEME_LABELS)
        cur_theme = settings.theme()
        self._theme_combo.setCurrentIndex(
            _THEME_VALUES.index(cur_theme) if cur_theme in _THEME_VALUES else 0
        )
        self._theme_combo.currentIndexChanged.connect(
            lambda i: self._on_theme_changed(_THEME_VALUES[i])
        )
        theme_row.addWidget(self._theme_combo, stretch=1)
        layout.addLayout(theme_row)

        # Only meaningful under "System", so shown only then.
        self._system_pair = QWidget()
        pair_layout = QVBoxLayout(self._system_pair)
        pair_layout.setContentsMargins(12, 0, 0, 0)
        pair_layout.setSpacing(2)
        self._dark_combo = self._pair_combo(
            pair_layout, "When dark:", _DARK_LABELS, _DARK_VALUES,
            settings.system_dark_theme(), self._s.set_system_dark_theme,
        )
        self._light_combo = self._pair_combo(
            pair_layout, "When light:", _LIGHT_LABELS, _LIGHT_VALUES,
            settings.system_light_theme(), self._s.set_system_light_theme,
        )
        layout.addWidget(self._system_pair)
        self._system_pair.setVisible(cur_theme == SYSTEM)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font size:"), stretch=1)
        self._font_combo = QComboBox()
        self._font_combo.addItems(_FONT_SIZES)
        self._font_combo.setCurrentText(str(settings.font_size()))
        self._font_combo.setFixedWidth(60)
        self._font_combo.currentTextChanged.connect(self._on_font_size_changed)
        font_row.addWidget(self._font_combo)
        font_row.addWidget(QLabel("pt"))
        layout.addLayout(font_row)

        layout.addWidget(self._section_label("Display"))

        # Ahead of colorization, because it decides what the colorizer sees.
        layout.addWidget(self._subsection_label("Escape sequences"))
        ansi_row = QHBoxLayout()
        ansi_row.addWidget(QLabel("ANSI codes:"))
        self._ansi_combo = QComboBox()
        self._ansi_combo.addItems(_ANSI_LABELS)
        cur_ansi = settings.ansi_mode()
        self._ansi_combo.setCurrentIndex(
            _ANSI_VALUES.index(cur_ansi) if cur_ansi in _ANSI_VALUES else 0
        )
        self._ansi_combo.setToolTip(
            "How to display ANSI/VT100 escape codes from the target.\n\n"
            "Strip — remove them and colorize normally (recommended)\n"
            "Render colors — paint the colors the target asked for\n"
            "Show raw — leave the escape characters in the text\n\n"
            "The session log always records the bytes verbatim."
        )
        self._ansi_combo.currentIndexChanged.connect(
            lambda i: self._on_ansi_mode_changed(_ANSI_VALUES[i])
        )
        ansi_row.addWidget(self._ansi_combo, stretch=1)
        layout.addLayout(ansi_row)

        layout.addWidget(self._subsection_label("Colorization"))

        self._enable_cb = QCheckBox("Enable colorization")
        self._enable_cb.setChecked(settings.color_enabled())
        self._enable_cb.toggled.connect(self._on_enable_toggled)
        layout.addWidget(self._enable_cb)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Level", "Syntax"])
        self._mode_combo.setCurrentText("Level" if settings.color_mode() == "level" else "Syntax")
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo, stretch=1)
        layout.addLayout(mode_row)

        apply_row = QHBoxLayout()
        apply_row.addWidget(QLabel("Apply to:"))
        self._apply_combo = QComboBox()
        self._apply_combo.addItems(_APPLY_LABELS)
        cur = settings.color_apply_to()
        self._apply_combo.setCurrentIndex(_APPLY_VALUES.index(cur) if cur in _APPLY_VALUES else 0)
        self._apply_combo.currentIndexChanged.connect(
            lambda i: self._on_apply_changed(_APPLY_VALUES[i])
        )
        apply_row.addWidget(self._apply_combo, stretch=1)
        layout.addLayout(apply_row)

        layout.addWidget(self._subsection_label("Level colors"))
        for lvl, lbl in [("err", "<err>"), ("wrn", "<wrn>"), ("inf", "<inf>"), ("dbg", "<dbg>")]:
            layout.addLayout(self._color_row(
                lbl,
                lambda l=lvl: self._s.level_color(l),
                lambda c, l=lvl: self._set_level_color(l, c),
            ))

        layout.addWidget(self._subsection_label("Syntax field colors"))
        for field, lbl in [("timestamp", "Timestamp"), ("module", "Module"), ("message", "Message")]:
            layout.addLayout(self._color_row(
                lbl,
                lambda f=field: self._s.syntax_color(f),
                lambda c, f=field: self._set_syntax_color(f, c),
            ))

        layout.addWidget(self._subsection_label("Sent data"))
        layout.addLayout(self._color_row(
            "TX lines (>> )",
            lambda: self._s.tx_color(),
            lambda c: self._s.set_tx_color(c),
        ))

        self._echo_empty_cb = QCheckBox("Echo blank sends")
        self._echo_empty_cb.setChecked(settings.tx_echo_empty())
        self._echo_empty_cb.setToolTip(
            "Show a '>> ' line when you press Enter on an empty send field.\n"
            "The line ending is transmitted either way."
        )
        self._echo_empty_cb.toggled.connect(self._s.set_tx_echo_empty)
        layout.addWidget(self._echo_empty_cb)

        layout.addWidget(self._subsection_label("Marks"))
        layout.addLayout(self._color_row(
            "Mark lines (>>>MARK)",
            lambda: self._s.mark_color(),
            lambda c: self._s.set_mark_color(c),
        ))

        layout.addWidget(self._subsection_label("Minimap"))
        self._minimap_cb = QCheckBox("Show minimap")
        self._minimap_cb.setChecked(settings.minimap_enabled())
        self._minimap_cb.toggled.connect(self._on_minimap_enabled_toggled)
        layout.addWidget(self._minimap_cb)

        minimap_apply_row = QHBoxLayout()
        minimap_apply_row.addWidget(QLabel("Apply to:"))
        self._minimap_apply_combo = QComboBox()
        self._minimap_apply_combo.addItems(_MINIMAP_APPLY_LABELS)
        cur_minimap_apply = settings.minimap_apply_to()
        self._minimap_apply_combo.setCurrentIndex(
            _MINIMAP_APPLY_VALUES.index(cur_minimap_apply)
            if cur_minimap_apply in _MINIMAP_APPLY_VALUES else 1
        )
        self._minimap_apply_combo.currentIndexChanged.connect(
            lambda i: self._on_minimap_apply_changed(_MINIMAP_APPLY_VALUES[i])
        )
        minimap_apply_row.addWidget(self._minimap_apply_combo, stretch=1)
        layout.addLayout(minimap_apply_row)

        layout.addWidget(self._section_label("Logging"))
        log_row = QHBoxLayout()
        log_row.setSpacing(4)
        self._log_dir_label = QLabel()
        self._log_dir_label.setWordWrap(True)
        self._log_dir_label.setStyleSheet(
            "color: %s; font-size: 11px;" % active_colors()["header_text"]
        )
        self._refresh_log_dir_label()
        log_row.addWidget(self._log_dir_label, stretch=1)
        log_dir_btn = QPushButton("…")
        log_dir_btn.setFixedWidth(28)
        log_dir_btn.setToolTip("Choose the session log directory")
        log_dir_btn.clicked.connect(self._on_pick_log_dir)
        log_row.addWidget(log_dir_btn)
        layout.addLayout(log_row)
        log_hint = QLabel("Session logs are written here. Applies on the next connect.")
        log_hint.setWordWrap(True)
        log_hint.setStyleSheet(
            "color: %s; font-size: 10px;" % active_colors()["muted_text"]
        )
        layout.addWidget(log_hint)

        layout.addWidget(self._section_label("Buffer"))
        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Line cap:"), stretch=1)
        self._cap_spin = QSpinBox()
        self._cap_spin.setRange(1_000, 500_000)
        self._cap_spin.setSingleStep(1_000)
        self._cap_spin.setValue(settings.buffer_cap())
        self._cap_spin.setFixedWidth(90)
        # Without this, valueChanged fires on every keystroke: typing "250000"
        # emits 2, 25, 250, ... clamped to the 1,000 minimum along the way, and
        # each intermediate value trims the panes irreversibly. Raising the cap
        # would destroy most of the buffer before reaching the intended number.
        self._cap_spin.setKeyboardTracking(False)
        self._cap_spin.valueChanged.connect(self._on_buffer_cap_changed)
        cap_row.addWidget(self._cap_spin)
        layout.addLayout(cap_row)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-weight: bold; font-size: 13px;"
            "padding-bottom: 2px; border-bottom: 1px solid %s;"
            % active_colors()["border"]
        )
        return lbl

    def _subsection_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-weight: bold; color: %s; margin-top: 6px;"
            % active_colors()["header_text"]
        )
        return lbl

    def _color_row(
        self,
        label: str,
        getter: Callable[[], str],
        setter: Callable[[str], None],
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel(label), stretch=1)

        swatch = QLabel()
        swatch.setFixedSize(20, 20)
        _paint_swatch(swatch, getter())
        # Tracked so a theme switch can repaint them: log colors are stored
        # per theme, so every swatch here shows a different value afterwards.
        self._swatches.append((swatch, getter))
        row.addWidget(swatch)

        pick_btn = QPushButton("…")
        pick_btn.setFixedWidth(28)

        def pick(checked=False, _getter=getter, _setter=setter, _swatch=swatch, _label=label):
            color = QColorDialog.getColor(QColor(_getter()), self, f"Color: {_label}")
            if color.isValid():
                _setter(color.name())
                _paint_swatch(_swatch, color.name())
                self.settings_changed.emit()

        pick_btn.clicked.connect(pick)
        row.addWidget(pick_btn)
        return row

    def refresh_colors(self) -> None:
        """Repaint the colour swatches after a theme switch.

        Log colours are stored per theme, so every getter here returns a
        different value once the theme changes; without this the pickers would
        keep advertising the previous theme's palette.
        """
        for swatch, getter in self._swatches:
            _paint_swatch(swatch, getter())

    def _pair_combo(self, layout, label, labels, values, current, setter):
        """One row of the System dark/light partner selector."""
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        combo = QComboBox()
        combo.addItems(labels)
        combo.setCurrentIndex(values.index(current) if current in values else 0)

        def changed(i, _setter=setter, _values=values):
            _setter(_values[i])
            # Only half the pair is in use at a time; re-resolving picks up a
            # change to the half that is.
            self.theme_changed.emit(self._s.resolved_theme())

        combo.currentIndexChanged.connect(changed)
        row.addWidget(combo, stretch=1)
        layout.addLayout(row)
        return combo

    def _on_theme_changed(self, theme: str) -> None:
        self._s.set_theme(theme)
        self._system_pair.setVisible(theme == SYSTEM)
        # Windows need a palette name, not the SYSTEM sentinel.
        self.theme_changed.emit(self._s.resolved_theme())

    def _on_enable_toggled(self, checked: bool) -> None:
        self._s.set_color_enabled(checked)
        self.settings_changed.emit()

    def _on_ansi_mode_changed(self, value: str) -> None:
        self._s.set_ansi_mode(value)
        self.settings_changed.emit()

    def _on_mode_changed(self, text: str) -> None:
        self._s.set_color_mode("level" if text == "Level" else "syntax")
        self.settings_changed.emit()

    def _on_apply_changed(self, value: str) -> None:
        self._s.set_color_apply_to(value)
        self.settings_changed.emit()

    def _set_level_color(self, level: str, color: str) -> None:
        self._s.set_level_color(level, color)

    def _set_syntax_color(self, field: str, color: str) -> None:
        self._s.set_syntax_color(field, color)

    def _on_minimap_enabled_toggled(self, checked: bool) -> None:
        self._s.set_minimap_enabled(checked)
        self.settings_changed.emit()

    def _on_minimap_apply_changed(self, value: str) -> None:
        self._s.set_minimap_apply_to(value)
        self.settings_changed.emit()

    def _refresh_log_dir_label(self) -> None:
        path = self._s.log_dir()
        self._log_dir_label.setText(path)
        self._log_dir_label.setToolTip(path)

    def _on_pick_log_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Session log directory", self._s.log_dir()
        )
        if chosen:
            self._s.set_log_dir(chosen)
            self._refresh_log_dir_label()

    def _on_buffer_cap_changed(self, value: int) -> None:
        self._s.set_buffer_cap(value)
        self.buffer_cap_changed.emit(value)

    def _on_font_size_changed(self, text: str) -> None:
        size = int(text)
        self._s.set_font_size(size)
        self.font_size_changed.emit(size)
