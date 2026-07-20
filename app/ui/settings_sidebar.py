# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Collapsible right-side settings sidebar."""

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
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

_APPLY_LABELS = ["All panes", "Raw log only", "Filtered log only", "None"]
_APPLY_VALUES = ["all", "raw", "filtered", "none"]

_THEME_LABELS = ["Dracula", "VS Code Dark"]
_THEME_VALUES = ["dracula", "vscode"]

_MINIMAP_APPLY_LABELS = ["Both panes", "Raw only", "Filtered only"]
_MINIMAP_APPLY_VALUES = ["all", "raw", "filtered"]


_FONT_SIZES = ["8", "9", "10", "11", "12", "13", "14", "16", "18", "20", "24"]


class SettingsSidebar(QWidget):
    settings_changed = Signal()
    buffer_cap_changed = Signal(int)
    theme_changed = Signal(str)
    font_size_changed = Signal(int)

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._s = settings
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

        layout.addWidget(self._section_label("Buffer"))
        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Line cap:"), stretch=1)
        self._cap_spin = QSpinBox()
        self._cap_spin.setRange(1_000, 500_000)
        self._cap_spin.setSingleStep(1_000)
        self._cap_spin.setValue(settings.buffer_cap())
        self._cap_spin.setFixedWidth(90)
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
            "padding-bottom: 2px; border-bottom: 1px solid #555;"
        )
        return lbl

    def _subsection_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; color: #aaaaaa; margin-top: 6px;")
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
        swatch.setStyleSheet(f"background-color: {getter()}; border: 1px solid #666;")
        row.addWidget(swatch)

        pick_btn = QPushButton("…")
        pick_btn.setFixedWidth(28)

        def pick(checked=False, _getter=getter, _setter=setter, _swatch=swatch, _label=label):
            color = QColorDialog.getColor(QColor(_getter()), self, f"Color: {_label}")
            if color.isValid():
                hex_color = color.name()
                _setter(hex_color)
                _swatch.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #666;")
                self.settings_changed.emit()

        pick_btn.clicked.connect(pick)
        row.addWidget(pick_btn)
        return row

    def _on_theme_changed(self, theme: str) -> None:
        self._s.set_theme(theme)
        self.theme_changed.emit(theme)

    def _on_enable_toggled(self, checked: bool) -> None:
        self._s.set_color_enabled(checked)
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

    def _on_buffer_cap_changed(self, value: int) -> None:
        self._s.set_buffer_cap(value)
        self.buffer_cap_changed.emit(value)

    def _on_font_size_changed(self, text: str) -> None:
        size = int(text)
        self._s.set_font_size(size)
        self.font_size_changed.emit(size)
