# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Compact filter bar: collapsible input row + horizontal rule chip strip."""

from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from typing import Optional as _Optional

from app.settings import AppSettings

_CHIP_INCLUDE_STYLE = (
    "QWidget#chip { border: 1px solid #3a6a3a; border-radius: 3px; }"
)
_CHIP_EXCLUDE_STYLE = (
    "QWidget#chip { border: 1px solid #6a3a3a; border-radius: 3px; }"
)
_CHIP_LABEL_STYLE = "QLabel { background: transparent; border: none; padding: 0px; }"
_CHIP_BTN_STYLE = (
    "QPushButton { color: #888888; background: transparent; border: none;"
    " padding: 0px; font-size: 11px; min-width: 16px; max-width: 16px;"
    " min-height: 16px; max-height: 16px; }"
    "QPushButton:hover { color: #cccccc; }"
)

_TYPE_ABBREV = {"substring": "sub", "regex": "rgx", "level": "lvl", "module": "mod"}


def _chip_label_text(rule: dict) -> str:
    prefix = "+" if rule.get("mode", "include") == "include" else "−"
    t = _TYPE_ABBREV.get(rule["type"], rule["type"][:3])
    v = rule["value"]
    if len(v) > 20:
        v = v[:17] + "…"
    return f"{prefix} {t}: {v}"


class _RuleChip(QWidget):
    remove_clicked = Signal()

    def __init__(self, rule: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("chip")
        style = (
            _CHIP_INCLUDE_STYLE
            if rule.get("mode", "include") == "include"
            else _CHIP_EXCLUDE_STYLE
        )
        self.setStyleSheet(style)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 1, 2, 1)
        layout.setSpacing(3)

        label = QLabel(_chip_label_text(rule))
        label.setStyleSheet(_CHIP_LABEL_STYLE)
        layout.addWidget(label)

        btn = QPushButton("×")
        btn.setStyleSheet(_CHIP_BTN_STYLE)
        btn.clicked.connect(lambda _: self.remove_clicked.emit())
        layout.addWidget(btn)

        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class FilterBar(QWidget):
    filters_changed = Signal(list, str)  # (rules, mode)
    input_bar_closed = Signal()  # emitted when Escape dismisses the input bar

    def __init__(
        self,
        settings: _Optional[AppSettings] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._settings = settings
        if settings is not None:
            self._rules: list = settings.filter_rules()
            self._mode: str = settings.filter_mode()
            _input_bar_open = settings.filter_bar_open()
        else:
            self._rules = []
            self._mode = "OR"
            _input_bar_open = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Collapsible input row ----
        self._input_row = QWidget()
        ir = QHBoxLayout(self._input_row)
        ir.setContentsMargins(4, 2, 4, 2)
        ir.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Filter value…")
        self._input.returnPressed.connect(self._add_rule)
        self._input.installEventFilter(self)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["substring", "regex", "level", "module"])

        self._inc_exc_combo = QComboBox()
        self._inc_exc_combo.addItems(["include", "exclude"])

        self._mode_btn = QPushButton(f"Mode: {self._mode}")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setChecked(self._mode == "AND")
        self._mode_btn.setFixedWidth(80)
        self._mode_btn.toggled.connect(self._on_mode_toggled)

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_rule)

        ir.addWidget(self._input, stretch=1)
        ir.addWidget(self._type_combo)
        ir.addWidget(self._inc_exc_combo)
        ir.addWidget(self._mode_btn)
        ir.addWidget(add_btn)

        self._input_row.setVisible(_input_bar_open)

        # ---- Horizontal chip strip ----
        self._chip_container = QWidget()
        self._chip_container.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed
        )
        self._chip_layout = QHBoxLayout(self._chip_container)
        self._chip_layout.setContentsMargins(4, 2, 4, 2)
        self._chip_layout.setSpacing(4)
        self._chip_layout.addStretch()

        self._chip_scroll = QScrollArea()
        self._chip_scroll.setWidget(self._chip_container)
        self._chip_scroll.setWidgetResizable(True)
        self._chip_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._chip_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._chip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chip_scroll.setFixedHeight(32)

        outer.addWidget(self._input_row)
        outer.addWidget(self._chip_scroll)

        self._rebuild_chips()
        self._chip_scroll.setVisible(bool(self._rules))

    # ---- Event filter for Escape in the text input ----

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._close_input_bar()
                return True
        return super().eventFilter(obj, event)

    def _close_input_bar(self):
        self._input_row.setVisible(False)
        if self._settings is not None:
            self._settings.set_filter_bar_open(False)
        self.input_bar_closed.emit()

    # ---- Public API ----

    def toggle_input_bar(self):
        if self._input_row.isVisible():
            self._close_input_bar()
        else:
            self._input_row.setVisible(True)
            if self._settings is not None:
                self._settings.set_filter_bar_open(True)
            self._input.setFocus()
            self._input.selectAll()

    def is_input_bar_open(self) -> bool:
        return self._input_row.isVisible()

    def get_rules(self) -> list:
        return list(self._rules)

    def get_mode(self) -> str:
        return self._mode

    # ---- Internal rule management ----

    def _add_rule(self):
        value = self._input.text().strip()
        if not value:
            return
        rule = {
            "type": self._type_combo.currentText(),
            "value": value,
            "mode": self._inc_exc_combo.currentText(),
        }
        self._rules.append(rule)
        self._input.clear()
        self._commit()

    def _remove_rule(self, index: int):
        del self._rules[index]
        self._commit()

    def _on_mode_toggled(self, checked: bool):
        self._mode = "AND" if checked else "OR"
        self._mode_btn.setText(f"Mode: {self._mode}")
        if self._settings is not None:
            self._settings.set_filter_mode(self._mode)
        self.filters_changed.emit(list(self._rules), self._mode)

    def _commit(self):
        if self._settings is not None:
            self._settings.set_filter_rules(self._rules)
        self._rebuild_chips()
        self._chip_scroll.setVisible(bool(self._rules))
        self.filters_changed.emit(list(self._rules), self._mode)

    def add_rule(self, value: str, rule_type: str = "substring", mode: str = "include") -> None:
        """Programmatically add a rule (e.g. from the find bar's 'Filter to matches')."""
        rule = {"type": rule_type, "value": value, "mode": mode}
        self._rules.append(rule)
        self._commit()

    def _rebuild_chips(self):
        # Remove all chips, preserving the trailing stretch (last item)
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, rule in enumerate(self._rules):
            chip = _RuleChip(rule)
            chip.remove_clicked.connect(lambda idx=i: self._remove_rule(idx))
            self._chip_layout.insertWidget(i, chip)
