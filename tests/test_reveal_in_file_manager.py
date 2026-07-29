# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the status-bar "reveal the log file" action, per platform."""

from pathlib import Path

import pytest

from app import main_window


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(main_window.subprocess, "Popen", lambda argv: calls.append(argv))
    return calls


class TestWindows:
    def test_select_switch_and_path_are_one_argument(self, monkeypatch, spawned):
        """Explorer ignores "/select," and the path when passed separately,
        opening Documents instead of selecting the file."""
        monkeypatch.setattr(main_window.sys, "platform", "win32")
        main_window._reveal_in_file_manager(Path("/logs/session.log"))
        assert len(spawned) == 1
        argv = spawned[0]
        assert argv[0] == "explorer"
        assert len(argv) == 2
        assert argv[1].startswith("/select,")
        assert argv[1].endswith("session.log")


class TestMacOS:
    def test_uses_open_dash_r(self, monkeypatch, spawned):
        monkeypatch.setattr(main_window.sys, "platform", "darwin")
        main_window._reveal_in_file_manager(Path("/logs/session.log"))
        assert spawned == [["open", "-R", "/logs/session.log"]]


class TestLinux:
    def test_opens_the_containing_folder(self, monkeypatch, spawned, qapp):
        opened = []
        monkeypatch.setattr(main_window.sys, "platform", "linux")
        monkeypatch.setattr(
            main_window.QDesktopServices, "openUrl", lambda url: opened.append(url)
        )
        main_window._reveal_in_file_manager(Path("/logs/session.log"))
        assert spawned == []
        assert len(opened) == 1
        assert opened[0].toLocalFile() == "/logs"
