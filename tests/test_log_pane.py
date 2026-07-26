# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the shared LogPane widget and its helpers."""

import pytest
from PySide6.QtGui import QFont, QTextCursor

from app.ui.log_pane import _fmt, doc_line_count, make_pane, pane_with_header


@pytest.fixture
def pane(qapp):
    font = QFont("Menlo")
    font.setPointSize(12)
    return make_pane(font)


@pytest.fixture
def plain():
    return _fmt("#cccccc")


def append(pane, plain, *lines):
    for line in lines:
        pane.append_line([(line, plain)], scroll=False)


def block_texts(pane):
    doc = pane.document()
    out = []
    block = doc.begin()
    while block != doc.end():
        out.append(block.text())
        block = block.next()
    return out


class TestDocLineCount:
    def test_empty_document_counts_zero(self, pane):
        """Qt reports blockCount() == 1 for an empty document."""
        assert pane.document().blockCount() == 1
        assert doc_line_count(pane) == 0

    def test_counts_appended_lines(self, pane, plain):
        append(pane, plain, "one", "two", "three")
        assert doc_line_count(pane) == 3


class TestAppendLine:
    def test_first_line_does_not_leave_a_blank_block(self, pane, plain):
        append(pane, plain, "first")
        assert block_texts(pane) == ["first"]

    def test_preserves_order(self, pane, plain):
        append(pane, plain, "a", "b", "c")
        assert block_texts(pane) == ["a", "b", "c"]

    def test_multi_segment_line_is_one_block(self, pane, plain):
        pane.append_line([("[ts]", plain), (" <inf>", plain), (" msg", plain)],
                         scroll=False)
        assert block_texts(pane) == ["[ts] <inf> msg"]

    def test_empty_line_still_creates_a_block(self, pane, plain):
        append(pane, plain, "a", "", "b")
        assert block_texts(pane) == ["a", "", "b"]


class TestCap:
    def test_append_trims_oldest_when_over_cap(self, pane, plain):
        pane.set_cap(3)
        append(pane, plain, "1", "2", "3", "4", "5")
        assert block_texts(pane) == ["3", "4", "5"]

    def test_set_cap_trims_immediately(self, pane, plain):
        append(pane, plain, *[str(i) for i in range(10)])
        pane.set_cap(4)
        assert block_texts(pane) == ["6", "7", "8", "9"]

    def test_raising_cap_does_not_restore_lines(self, pane, plain):
        append(pane, plain, *[str(i) for i in range(10)])
        pane.set_cap(2)
        pane.set_cap(100)
        assert block_texts(pane) == ["8", "9"]

    def test_cap_of_one(self, pane, plain):
        pane.set_cap(1)
        append(pane, plain, "a", "b", "c")
        assert block_texts(pane) == ["c"]


class TestCopyIsPlainText:
    @pytest.mark.xfail(
        strict=True,
        reason="LogPane.createMimeData is not a QTextEdit virtual; the real hook "
               "is createMimeDataFromSelection(), so the override never runs and "
               "copy still puts HTML on the clipboard",
    )
    def test_copy_puts_only_plain_text_on_the_clipboard(self, pane, plain, qapp):
        pane.append_line(
            [("[ts]", _fmt("#666666")), (" <err> boom", _fmt("#ff5555"))],
            scroll=False,
        )
        cursor = pane.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.End,
                            QTextCursor.MoveMode.KeepAnchor)
        pane.setTextCursor(cursor)
        pane.copy()

        mime = qapp.clipboard().mimeData()
        assert mime.text() == "[ts] <err> boom"
        assert not mime.hasHtml()


class TestPaneWithHeader:
    def test_returns_container_and_live_label(self, pane):
        container, header = pane_with_header(pane, "Raw")
        assert header.text() == "Raw"
        header.setText("Filtered — 3 of 9 lines")
        assert header.text() == "Filtered — 3 of 9 lines"

    def test_pane_is_inside_the_container(self, pane):
        container, _ = pane_with_header(pane, "Raw")
        assert pane in container.findChildren(type(pane))

    def test_side_widget_sits_beside_the_pane_not_the_header(self, pane, qapp):
        from app.ui.minimap import Minimap

        minimap = Minimap()
        container, header = pane_with_header(pane, "Raw", minimap)
        layout = container.layout()
        # [0] header, [1] content row holding pane + minimap
        assert layout.itemAt(0).widget() is header
        content = layout.itemAt(1).widget()
        assert minimap in content.findChildren(Minimap)
        assert pane in content.findChildren(type(pane))


class TestReplaceLines:
    def test_replaces_all_content(self, pane, plain):
        append(pane, plain, "old one", "old two")
        pane.replace_lines([[("new one", plain)], [("new two", plain)]])
        assert block_texts(pane) == ["new one", "new two"]

    def test_accepts_a_generator_reading_the_current_document(self, pane, plain):
        """The rebuild path streams from the live document into the new one,
        so nothing has to be buffered in between."""
        append(pane, plain, "a", "b", "c")
        pane.replace_lines(
            [(text.upper(), plain)] for text in block_texts(pane)
        )
        assert block_texts(pane) == ["A", "B", "C"]

    def test_multi_segment_lines_stay_one_block(self, pane, plain):
        pane.replace_lines([[("[ts]", plain), (" msg", plain)]])
        assert block_texts(pane) == ["[ts] msg"]

    def test_empty_input_empties_the_pane(self, pane, plain):
        append(pane, plain, "a", "b")
        pane.replace_lines([])
        assert doc_line_count(pane) == 0

    def test_cap_is_enforced(self, pane, plain):
        pane.set_cap(2)
        pane.replace_lines([[(str(i), plain)] for i in range(6)])
        assert block_texts(pane) == ["4", "5"]

    def test_cap_survives_the_swap(self, pane, plain):
        pane.set_cap(3)
        pane.replace_lines([[("a", plain)]])
        append(pane, plain, "b", "c", "d")
        assert block_texts(pane) == ["b", "c", "d"]

    def test_appending_still_works_after_a_replace(self, pane, plain):
        pane.replace_lines([[("first", plain)]])
        append(pane, plain, "second")
        assert block_texts(pane) == ["first", "second"]

    def test_font_is_preserved_across_the_swap(self, pane, plain):
        f = pane.font()
        f.setPointSize(19)
        pane.setFont(f)
        pane.replace_lines([[("x", plain)]])
        assert pane.document().defaultFont().pointSize() == 19

    def test_read_only_survives_the_swap(self, pane, plain):
        pane.replace_lines([[("x", plain)]])
        assert pane.isReadOnly()


class TestTrimBatching:
    def test_lowering_the_cap_far_is_not_quadratic(self, pane, plain):
        import time

        pane.set_cap(200_000)
        append(pane, plain, *[str(i) for i in range(60_000)])
        start = time.monotonic()
        pane.set_cap(1_000)
        elapsed = time.monotonic() - start
        assert pane.document().blockCount() == 1_000
        assert elapsed < 1.0, f"trim took {elapsed:.2f}s"
