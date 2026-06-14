# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""QSettings-backed persistent settings for logulator."""

import json
from typing import Optional

from PySide6.QtCore import QByteArray, QSettings


class AppSettings:
    _ORG = "logulator"
    _APP = "logulator"

    _LEVEL_DEFAULTS = {
        "err": "#ff5555",
        "wrn": "#ffb86c",
        "inf": "#50fa7b",
        "dbg": "#888888",
    }
    _SYNTAX_DEFAULTS = {
        "timestamp": "#666666",
        "module": "#bd93f9",
        "message": "#f8f8f2",
    }

    _BUFFER_DEFAULT = 100_000
    _BUFFER_MIN = 1_000
    _BUFFER_MAX = 500_000

    def __init__(self):
        self._qs = QSettings(self._ORG, self._APP)

    # --- Window geometry ---

    def save_geometry(self, data: QByteArray) -> None:
        self._qs.setValue("window/geometry", data)

    def load_geometry(self) -> Optional[QByteArray]:
        v = self._qs.value("window/geometry")
        return v if isinstance(v, QByteArray) else None

    def save_splitter(self, data: QByteArray) -> None:
        self._qs.setValue("window/splitter", data)

    def load_splitter(self) -> Optional[QByteArray]:
        v = self._qs.value("window/splitter")
        return v if isinstance(v, QByteArray) else None

    # --- Sidebar ---

    def sidebar_open(self) -> bool:
        return self._qs.value("sidebar/open", False, type=bool)

    def set_sidebar_open(self, val: bool) -> None:
        self._qs.setValue("sidebar/open", val)

    # --- Colorization ---

    def color_enabled(self) -> bool:
        return self._qs.value("color/enabled", True, type=bool)

    def set_color_enabled(self, val: bool) -> None:
        self._qs.setValue("color/enabled", val)

    def color_mode(self) -> str:
        v = self._qs.value("color/mode", "level")
        return v if v in ("level", "syntax") else "level"

    def set_color_mode(self, val: str) -> None:
        self._qs.setValue("color/mode", val)

    def color_apply_to(self) -> str:
        v = self._qs.value("color/apply_to", "all")
        return v if v in ("all", "raw", "filtered", "none") else "all"

    def set_color_apply_to(self, val: str) -> None:
        self._qs.setValue("color/apply_to", val)

    def level_color(self, level: str) -> str:
        return self._qs.value(
            f"color/level_{level}", self._LEVEL_DEFAULTS.get(level, "#cccccc")
        )

    def set_level_color(self, level: str, color: str) -> None:
        self._qs.setValue(f"color/level_{level}", color)

    def syntax_color(self, field: str) -> str:
        return self._qs.value(
            f"color/syntax_{field}", self._SYNTAX_DEFAULTS.get(field, "#cccccc")
        )

    def set_syntax_color(self, field: str, color: str) -> None:
        self._qs.setValue(f"color/syntax_{field}", color)

    # --- Buffer ---

    def buffer_cap(self) -> int:
        v = self._qs.value("buffer/cap", self._BUFFER_DEFAULT, type=int)
        return max(self._BUFFER_MIN, min(self._BUFFER_MAX, v))

    def set_buffer_cap(self, val: int) -> None:
        val = max(self._BUFFER_MIN, min(self._BUFFER_MAX, val))
        self._qs.setValue("buffer/cap", val)

    # --- Filter ---

    def filter_rules(self) -> list:
        v = self._qs.value("filter/rules", "[]")
        if not isinstance(v, str):
            return []
        try:
            result = json.loads(v)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, ValueError):
            return []

    def set_filter_rules(self, rules: list) -> None:
        self._qs.setValue("filter/rules", json.dumps(rules))

    def filter_mode(self) -> str:
        v = self._qs.value("filter/mode", "OR")
        return v if v in ("AND", "OR") else "OR"

    def set_filter_mode(self, mode: str) -> None:
        self._qs.setValue("filter/mode", mode)

    def filter_bar_open(self) -> bool:
        return self._qs.value("filter/bar_open", False, type=bool)

    def set_filter_bar_open(self, val: bool) -> None:
        self._qs.setValue("filter/bar_open", val)
