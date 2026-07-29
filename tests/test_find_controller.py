# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for FindController search, navigation and staleness handling."""

import time

import pytest
from PySide6.QtGui import QFont

from app.ui.find_bar import FindBar
from app.ui.find_controller import FindController
from app.ui.log_pane import _fmt, make_pane

LINES = [
    "[00:00:01] <inf> net_if: interface up",
    "[00:00:02] <err> net_if: send failed",
    "[00:00:03] <dbg> shell: prompt ready",
    "[00:00:04] <err> modem: send failed",
]


@pytest.fixture
def pane(qtbot):
    p = make_pane(QFont("Menlo"))
    qtbot.addWidget(p)
    plain = _fmt("#cccccc")
    for line in LINES:
        p.append_line([(line, plain)], scroll=False)
    return p


@pytest.fixture
def bar(qtbot):
    b = FindBar()
    qtbot.addWidget(b)
    b.show()
    return b


@pytest.fixture
def find(bar, pane):
    return FindController(bar, pane)


def search(find, bar, text):
    bar._input.setText(text)
    find._do_search()


class TestSearch:
    def test_finds_every_occurrence(self, find, bar):
        search(find, bar, "send failed")
        assert len(find._matches) == 2

    def test_reports_the_match_count(self, find, bar):
        search(find, bar, "send failed")
        assert bar._count_label.text() == "1 of 2"

    def test_no_matches_is_reported(self, find, bar):
        search(find, bar, "nothing here")
        assert bar._count_label.text() == "No matches"
        assert find._matches == []

    def test_matches_are_positions_not_cursors(self, find, bar):
        """Live QTextCursors are repositioned by Qt on every document edit, so
        holding one per match made appends scale with the match count."""
        search(find, bar, "send failed")
        assert all(
            isinstance(m, tuple) and all(isinstance(v, int) for v in m)
            for m in find._matches
        )

    def test_selects_the_first_match(self, find, bar, pane):
        search(find, bar, "send failed")
        assert pane.textCursor().selectedText() == "send failed"

    def test_empty_query_clears_state(self, find, bar):
        search(find, bar, "send failed")
        find._on_text_changed("")
        assert bar._count_label.text() == ""


class TestNavigation:
    def test_next_advances(self, find, bar):
        search(find, bar, "send failed")
        find._on_next()
        assert bar._count_label.text() == "2 of 2"

    def test_next_wraps_around(self, find, bar):
        search(find, bar, "send failed")
        find._on_next()
        find._on_next()
        assert bar._count_label.text() == "1 of 2"

    def test_prev_wraps_backwards(self, find, bar):
        search(find, bar, "send failed")
        find._on_prev()
        assert bar._count_label.text() == "2 of 2"

    def test_navigation_without_matches_is_a_no_op(self, find, bar):
        search(find, bar, "nothing here")
        find._on_next()
        find._on_prev()
        assert find._current_match_idx == -1

    def test_current_match_is_selected(self, find, bar, pane):
        search(find, bar, "net_if")
        find._on_next()
        assert pane.textCursor().selectedText() == "net_if"


class TestStaleness:
    def test_navigation_refreshes_after_the_document_grows(self, find, bar, pane):
        """Integer positions do not self-adjust the way cursors did, so
        navigation re-runs the search when the document has changed."""
        search(find, bar, "send failed")
        assert len(find._matches) == 2

        pane.append_line([("[00:00:05] <err> gps: send failed", _fmt("#cccccc"))],
                         scroll=False)
        find._on_next()
        assert len(find._matches) == 3

    def test_navigation_refreshes_after_a_trim(self, find, bar, pane):
        search(find, bar, "send failed")
        pane.set_cap(1)
        find._on_next()
        assert len(find._matches) <= 1

    def test_stale_positions_never_build_an_out_of_range_cursor(self, find, bar, pane):
        search(find, bar, "send failed")
        pane.clear()
        # Positions now point past the end of an empty document.
        assert find._cursor_for(0) is None

    def test_research_picks_up_new_content(self, find, bar, pane):
        search(find, bar, "send failed")
        pane.append_line([("another send failed", _fmt("#cccccc"))], scroll=False)
        find.research()
        assert len(find._matches) == 3

    def test_closing_clears_everything(self, find, bar):
        search(find, bar, "send failed")
        find._on_closed()
        assert find._matches == []
        assert find._current_match_idx == -1


class TestHighlightPerformance:
    def test_appends_stay_cheap_with_many_matches(self, qtbot):
        """The regression this replaces: one live QTextCursor per match made
        every append O(matches). 60k matches slowed appends ~7.5x, enough to
        stall the live serial buffer."""
        pane = make_pane(QFont("Menlo"))
        qtbot.addWidget(pane)
        plain = _fmt("#cccccc")
        for i in range(20_000):
            pane.append_line([(f"line {i} needle", plain)], scroll=False)

        bar = FindBar()
        qtbot.addWidget(bar)
        bar.show()
        find = FindController(bar, pane)
        search(find, bar, "needle")
        assert len(find._matches) == 20_000

        start = time.monotonic()
        for i in range(200):
            pane.append_line([(f"extra {i}", plain)], scroll=False)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"200 appends took {elapsed:.2f}s with matches held"
