# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the send bar: line sending, history recall and control keys."""

import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.ui.send_bar import SendBar, control_mnemonic

# The physical Control key. Qt maps ControlModifier to Command on macOS, so the
# modifier that produces a control character differs by platform.
CTRL = (
    Qt.KeyboardModifier.MetaModifier
    if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)
# Whatever the platform uses for app shortcuts (Cmd on macOS, Ctrl elsewhere).
APP_SHORTCUT = (
    Qt.KeyboardModifier.ControlModifier
    if sys.platform == "darwin"
    else Qt.KeyboardModifier.MetaModifier
)


@pytest.fixture
def bar(qtbot, settings):
    b = SendBar(settings)
    qtbot.addWidget(b)
    b.show()
    b.set_connected(True)
    return b


@pytest.fixture
def controls(bar):
    seen = []
    bar.control_requested.connect(lambda data, label: seen.append((data, label)))
    return seen


@pytest.fixture
def lines(bar):
    seen = []
    bar.send_requested.connect(lambda text, ending: seen.append((text, ending)))
    return seen


class TestControlCharacters:
    def test_ctrl_c_sends_the_interrupt_byte(self, bar, controls):
        QTest.keyClick(bar._input, Qt.Key.Key_C, CTRL)
        assert controls == [(b"\x03", "^C")]

    @pytest.mark.parametrize(
        "key,code,label",
        [
            (Qt.Key.Key_A, b"\x01", "^A"),
            (Qt.Key.Key_C, b"\x03", "^C"),
            (Qt.Key.Key_D, b"\x04", "^D"),
            (Qt.Key.Key_U, b"\x15", "^U"),
            (Qt.Key.Key_Z, b"\x1a", "^Z"),
        ],
    )
    def test_ctrl_letter_mapping(self, bar, controls, key, code, label):
        QTest.keyClick(bar._input, key, CTRL)
        assert controls == [(code, label)]

    def test_escape_sends_esc(self, bar, controls):
        QTest.keyClick(bar._input, Qt.Key.Key_Escape)
        assert controls == [(b"\x1b", "^[")]

    def test_control_byte_carries_no_line_ending(self, bar, controls, lines):
        """An interrupt is the byte on its own — CRLF would be wrong."""
        QTest.keyClick(bar._input, Qt.Key.Key_C, CTRL)
        assert controls[0][0] == b"\x03"
        assert lines == [], "control keys must not go through the line path"

    def test_control_key_does_not_wait_for_enter(self, bar, controls):
        bar._input.setText("half-typed command")
        QTest.keyClick(bar._input, Qt.Key.Key_C, CTRL)
        assert controls == [(b"\x03", "^C")]

    def test_control_key_inserts_no_text(self, bar):
        QTest.keyClick(bar._input, Qt.Key.Key_C, CTRL)
        assert bar._input.text() == ""

    def test_plain_letters_still_type(self, bar, controls):
        QTest.keyClicks(bar._input, "reboot")
        assert bar._input.text() == "reboot"
        assert controls == []

    def test_shift_modifier_is_not_a_control_char(self, bar, controls):
        QTest.keyClick(bar._input, Qt.Key.Key_F, CTRL | Qt.KeyboardModifier.ShiftModifier)
        assert controls == []

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS modifier mapping")
    def test_command_key_is_left_for_app_shortcuts(self, bar, controls):
        """Cmd+C must keep copying; only the physical Control key transmits."""
        QTest.keyClick(bar._input, Qt.Key.Key_C, APP_SHORTCUT)
        assert controls == []


class TestMnemonics:
    @pytest.mark.parametrize(
        "code,expected",
        [(0x00, "^@"), (0x01, "^A"), (0x03, "^C"), (0x1A, "^Z"), (0x1B, "^[")],
    )
    def test_caret_notation(self, code, expected):
        assert control_mnemonic(code) == expected


class TestLineSending:
    def test_enter_sends_with_the_line_ending(self, bar, lines):
        QTest.keyClicks(bar._input, "help")
        QTest.keyClick(bar._input, Qt.Key.Key_Return)
        assert lines == [("help", "\r\n")]

    def test_input_clears_after_sending(self, bar, lines):
        QTest.keyClicks(bar._input, "help")
        QTest.keyClick(bar._input, Qt.Key.Key_Return)
        assert bar._input.text() == ""

    def test_empty_send_is_allowed(self, bar, lines):
        """A bare line ending is a normal way to nudge a shell prompt."""
        QTest.keyClick(bar._input, Qt.Key.Key_Return)
        assert lines == [("", "\r\n")]

    def test_line_ending_selector_is_honoured(self, bar, lines):
        bar._ending_combo.setCurrentIndex(3)  # None
        QTest.keyClicks(bar._input, "x")
        QTest.keyClick(bar._input, Qt.Key.Key_Return)
        assert lines == [("x", "")]


class TestHistory:
    def test_up_recalls_the_previous_line(self, bar):
        for cmd in ("first", "second"):
            bar._input.setText(cmd)
            bar._on_send()
        QTest.keyClick(bar._input, Qt.Key.Key_Up)
        assert bar._input.text() == "second"
        QTest.keyClick(bar._input, Qt.Key.Key_Up)
        assert bar._input.text() == "first"

    def test_down_returns_to_the_pending_line(self, bar):
        bar._input.setText("sent")
        bar._on_send()
        QTest.keyClicks(bar._input, "typing")
        QTest.keyClick(bar._input, Qt.Key.Key_Up)
        assert bar._input.text() == "sent"
        QTest.keyClick(bar._input, Qt.Key.Key_Down)
        assert bar._input.text() == "typing"

    def test_consecutive_duplicates_are_not_stored_twice(self, bar):
        for _ in range(2):
            bar._input.setText("same")
            bar._on_send()
        assert bar._input._history == ["same"]


class TestConnectedState:
    def test_disabled_while_disconnected(self, bar):
        bar.set_connected(False)
        assert not bar._input.isEnabled()
        assert not bar._send_btn.isEnabled()

    def test_enabled_and_focused_on_connect(self, bar):
        bar.set_connected(False)
        bar.set_connected(True)
        assert bar._input.isEnabled()
