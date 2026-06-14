# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Widget for managing active filter rules. Provides a text input for new
rules, rule-type selector, include/exclude toggle, a list of active rules
with per-rule remove buttons, and an AND/OR mode toggle."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class FilterBar(QWidget):
    filters_changed = Signal(list, str)  # (rules, mode)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: list[dict] = []
        self._mode = "OR"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # --- input row ---
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Filter value…")
        self._input.returnPressed.connect(self._add_rule)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["substring", "regex", "level", "module"])

        self._inc_exc_combo = QComboBox()
        self._inc_exc_combo.addItems(["include", "exclude"])

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_rule)

        self._mode_btn = QPushButton("Mode: OR")
        self._mode_btn.setCheckable(True)
        self._mode_btn.toggled.connect(self._toggle_mode)

        input_row.addWidget(self._input, stretch=1)
        input_row.addWidget(self._type_combo)
        input_row.addWidget(self._inc_exc_combo)
        input_row.addWidget(add_btn)
        input_row.addWidget(self._mode_btn)

        # --- active rules list ---
        self._rules_container = QWidget()
        self._rules_layout = QVBoxLayout(self._rules_container)
        self._rules_layout.setContentsMargins(2, 2, 2, 2)
        self._rules_layout.setSpacing(2)
        self._rules_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rules_container)
        scroll.setMaximumHeight(100)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)

        outer.addLayout(input_row)
        outer.addWidget(scroll)

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
        self._rebuild_widgets()
        self.filters_changed.emit(list(self._rules), self._mode)

    def _remove_rule(self, index: int):
        del self._rules[index]
        self._rebuild_widgets()
        self.filters_changed.emit(list(self._rules), self._mode)

    def _rebuild_widgets(self):
        # Remove all items except the trailing stretch
        while self._rules_layout.count() > 1:
            item = self._rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, rule in enumerate(self._rules):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            tag = f"[{rule['mode']}] {rule['type']}: {rule['value']}"
            rl.addWidget(QLabel(tag), stretch=1)
            rm = QPushButton("✕")
            rm.setFixedWidth(28)
            rm.clicked.connect(lambda _checked, idx=i: self._remove_rule(idx))
            rl.addWidget(rm)
            self._rules_layout.insertWidget(i, row)

    def _toggle_mode(self, checked: bool):
        self._mode = "AND" if checked else "OR"
        self._mode_btn.setText(f"Mode: {self._mode}")
        self.filters_changed.emit(list(self._rules), self._mode)

    def get_rules(self) -> list:
        return list(self._rules)

    def get_mode(self) -> str:
        return self._mode
