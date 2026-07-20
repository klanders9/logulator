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

    _TX_DEFAULT = "#8be9fd"

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

    # --- Minimap ---

    def minimap_enabled(self) -> bool:
        return self._qs.value("display/minimap_enabled", False, type=bool)

    def set_minimap_enabled(self, val: bool) -> None:
        self._qs.setValue("display/minimap_enabled", val)

    def minimap_apply_to(self) -> str:
        v = self._qs.value("display/minimap_apply_to", "raw")
        return v if v in ("all", "raw", "filtered") else "raw"

    def set_minimap_apply_to(self, val: str) -> None:
        if val in ("all", "raw", "filtered"):
            self._qs.setValue("display/minimap_apply_to", val)

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

    # --- Recent files ---

    _RECENT_MAX = 10

    def recent_files(self) -> list:
        v = self._qs.value("files/recent", "[]")
        if not isinstance(v, str):
            return []
        try:
            result = json.loads(v)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, ValueError):
            return []

    def add_recent_file(self, path) -> None:
        s = str(path)
        paths = self.recent_files()
        if s in paths:
            paths.remove(s)
        paths.insert(0, s)
        self._qs.setValue("files/recent", json.dumps(paths[: self._RECENT_MAX]))

    # --- Auto-reconnect ---

    def auto_reconnect(self) -> bool:
        return self._qs.value("serial/auto_reconnect", False, type=bool)

    def set_auto_reconnect(self, val: bool) -> None:
        self._qs.setValue("serial/auto_reconnect", val)

    # --- Last-used connection ---

    def last_port(self) -> str:
        v = self._qs.value("serial/last_port", "")
        return v if isinstance(v, str) else ""

    def set_last_port(self, val: str) -> None:
        self._qs.setValue("serial/last_port", val)

    def last_baud(self) -> int:
        return self._qs.value("serial/last_baud", 115200, type=int)

    def set_last_baud(self, val: int) -> None:
        self._qs.setValue("serial/last_baud", val)

    # --- Serial connection options ---

    def serial_databits(self) -> int:
        v = self._qs.value("serial/databits", 8, type=int)
        return v if v in (5, 6, 7, 8) else 8

    def set_serial_databits(self, val: int) -> None:
        if val in (5, 6, 7, 8):
            self._qs.setValue("serial/databits", val)

    def serial_parity(self) -> str:
        v = self._qs.value("serial/parity", "N")
        return v if v in ("N", "E", "O", "M", "S") else "N"

    def set_serial_parity(self, val: str) -> None:
        if val in ("N", "E", "O", "M", "S"):
            self._qs.setValue("serial/parity", val)

    def serial_stopbits(self) -> str:
        v = self._qs.value("serial/stopbits", "1")
        return v if v in ("1", "1.5", "2") else "1"

    def set_serial_stopbits(self, val: str) -> None:
        if val in ("1", "1.5", "2"):
            self._qs.setValue("serial/stopbits", val)

    def serial_flow(self) -> str:
        v = self._qs.value("serial/flow", "none")
        return v if v in ("none", "rtscts", "xonxoff") else "none"

    def set_serial_flow(self, val: str) -> None:
        if val in ("none", "rtscts", "xonxoff"):
            self._qs.setValue("serial/flow", val)

    def serial_dtr(self) -> bool:
        return self._qs.value("serial/dtr", True, type=bool)

    def set_serial_dtr(self, val: bool) -> None:
        self._qs.setValue("serial/dtr", val)

    def serial_rts(self) -> bool:
        return self._qs.value("serial/rts", True, type=bool)

    def set_serial_rts(self, val: bool) -> None:
        self._qs.setValue("serial/rts", val)

    # --- TX (send) ---

    def tx_line_ending(self) -> str:
        v = self._qs.value("tx/line_ending", "crlf")
        return v if v in ("none", "lf", "cr", "crlf") else "crlf"

    def set_tx_line_ending(self, val: str) -> None:
        if val in ("none", "lf", "cr", "crlf"):
            self._qs.setValue("tx/line_ending", val)

    def tx_color(self) -> str:
        return self._qs.value("color/tx", self._TX_DEFAULT)

    def set_tx_color(self, color: str) -> None:
        self._qs.setValue("color/tx", color)

    # --- Font ---

    _FONT_SIZES = (8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24)

    def font_size(self) -> int:
        v = self._qs.value("app/font_size", 12, type=int)
        return v if v in self._FONT_SIZES else 12

    def set_font_size(self, val: int) -> None:
        if val in self._FONT_SIZES:
            self._qs.setValue("app/font_size", val)

    # --- Theme ---

    def theme(self) -> str:
        v = self._qs.value("app/theme", "dracula")
        return v if v in ("dracula", "vscode") else "dracula"

    def set_theme(self, val: str) -> None:
        if val in ("dracula", "vscode"):
            self._qs.setValue("app/theme", val)
