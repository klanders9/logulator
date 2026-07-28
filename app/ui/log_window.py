# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Shared behaviour for the two windows that display log panes.

`MainWindow` (live serial) and `FileViewer` (static file) present the same
raw/filtered split view, the same filter bar, the same optional minimaps and
the same colorization pipeline. Everything identical between them lives here;
only what genuinely differs stays in the two window classes:

  - `__init__` — different panels, toolbars and menus
  - `_on_filters_changed` — the file viewer defers rebuilds while loading
  - `_on_filter_to_matches` — the file viewer also opens the input row
  - `open_file` — the main window tracks viewers and the recent-files menu
  - `closeEvent` — different resources to tear down

Subclasses must be a `QWidget` (in practice `QMainWindow`), must call
`_init_log_window()` then `_build_log_panes()` from their own `__init__`, and
must provide `_on_filters_changed(rules, mode)` and `open_file(path)`.
"""

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QSplitter

from app import ansi, filter_engine
from app.colorizer import Colorizer
from app.log_format import detect_level
from app.settings import AppSettings
from app.theme import active_colors, apply_palette
from app.ui.filter_bar import FilterBar
from app.ui.log_pane import (
    _fmt,
    _plain_color,
    ansi_fmt,
    ansi_segments,
    block_ansi_styles,
    doc_line_count,
    make_pane,
    pane_with_header,
    restyle_pane,
    restyle_pane_header,
)
from app.ui.minimap import Minimap

# Initial raw/filtered split the first time the filtered pane is revealed.
_RAW_SPLIT_FRACTION = 0.6

# Every live log window (MainWindow and FileViewer alike). Display settings are
# shared through one AppSettings, so a change has to reach all of them —
# rebuilding only the window whose sidebar emitted it left the others showing
# the old colours, fonts and minimaps until something else forced a rebuild.
_open_windows: List["LogWindowMixin"] = []


def open_log_windows() -> List["LogWindowMixin"]:
    """Live log windows, in creation order."""
    return list(_open_windows)


def iter_blocks(doc):
    """Yield every block of a QTextDocument, in order."""
    block = doc.begin()
    while block != doc.end():
        yield block
        block = block.next()


def iter_block_texts(doc):
    """Yield the text of every block in a QTextDocument, in order."""
    for block in iter_blocks(doc):
        yield block.text()


def _is_empty_document(doc) -> bool:
    """True for a document with no content.

    Qt reports blockCount() == 1 with an empty first block for an empty
    document, so a naive walk would yield one phantom line.
    """
    return doc.blockCount() == 1 and doc.firstBlock().text() == ""


class LogWindowMixin:
    """Pane, filter, colorization and minimap behaviour shared by both windows."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _init_log_window(self, settings: AppSettings) -> None:
        """Set up the state the rest of the mixin depends on."""
        self._settings = settings
        self._colorizer = Colorizer(settings)
        self._plain_fmt = _fmt(_plain_color())
        self._rules: list = []
        self._filter_mode = "OR"
        self._splitter_initialized = False
        _open_windows.append(self)

    def _release_log_window(self) -> None:
        """Drop this window from the broadcast list. Call from closeEvent."""
        if self in _open_windows:
            _open_windows.remove(self)

    def _build_log_panes(
        self,
        font: QFont,
        cap: int,
        raw_placeholder: Optional[str] = None,
        filtered_placeholder: Optional[str] = None,
    ) -> None:
        """Build the raw/filtered panes, minimaps, filter bar and splitter.

        Sets `_raw_pane`, `_filtered_pane`, `_minimap`, `_filtered_minimap`,
        `_raw_header`, `_filtered_box`, `_filtered_header`, `_filter_bar` and
        `_splitter`, and wires every signal that behaves the same in both
        windows. The caller places `_splitter` in its own layout.
        """
        self._raw_pane = make_pane(font, cap=cap)
        self._filtered_pane = make_pane(font, cap=cap)
        if raw_placeholder:
            self._raw_pane.setPlaceholderText(raw_placeholder)
        if filtered_placeholder:
            self._filtered_pane.setPlaceholderText(filtered_placeholder)

        # Minimaps: colored-band overview beside each pane. Optional and off by
        # default; visibility is driven by _apply_minimap_settings().
        self._minimap = Minimap()
        self._minimap.set_cap(cap)
        self._minimap.position_clicked.connect(self._on_minimap_clicked)
        self._filtered_minimap = Minimap()
        self._filtered_minimap.set_cap(cap)
        self._filtered_minimap.position_clicked.connect(
            self._on_filtered_minimap_clicked
        )

        raw_box, self._raw_header = pane_with_header(
            self._raw_pane, "Raw", self._minimap
        )
        self._filtered_box, self._filtered_header = pane_with_header(
            self._filtered_pane, "Filtered", self._filtered_minimap
        )

        # The filter bar sits inside the filtered container between the header
        # label and the pane, so the controls stay next to what they filter.
        # Rules are in-memory only in both windows — nothing is persisted.
        self._filter_bar = FilterBar()
        self._filtered_box.layout().insertWidget(1, self._filter_bar)
        self._filtered_box.hide()

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(raw_box)
        self._splitter.addWidget(self._filtered_box)

        self._filter_bar.filters_changed.connect(self._on_filters_changed)
        self._filter_bar.input_bar_closed.connect(self._on_filter_bar_closed)
        self._raw_pane.selectionChanged.connect(self._on_raw_selection_changed)
        self._filtered_pane.selectionChanged.connect(
            self._on_filtered_selection_changed
        )
        self._filtered_pane.line_double_clicked.connect(self._jump_to_raw_line)
        self._raw_pane.file_dropped.connect(self.open_file)
        self._filtered_pane.file_dropped.connect(self.open_file)

        for signal in (
            self._raw_pane.verticalScrollBar().valueChanged,
            self._raw_pane.verticalScrollBar().rangeChanged,
        ):
            signal.connect(self._update_minimap_viewport)
        for signal in (
            self._filtered_pane.verticalScrollBar().valueChanged,
            self._filtered_pane.verticalScrollBar().rangeChanged,
        ):
            signal.connect(self._update_filtered_minimap_viewport)

    # ------------------------------------------------------------------
    # Colorization
    # ------------------------------------------------------------------

    def _split_ansi(self, line: str) -> Tuple[str, list]:
        """Split an incoming line into display text and wire colour spans.

        Every consumer downstream — the panes, the filter engine, the minimap,
        the find bar — works off the returned text, so escapes are removed
        exactly once and nothing has to know they were ever there. Spans come
        back empty unless the user asked for them to be painted.
        """
        mode = self._settings.ansi_mode()
        if mode == "off":
            return line, []
        text, spans = ansi.parse(line)
        return text, spans if mode == "render" else []

    def _colorization_active(self, pane: str) -> bool:
        """Whether this pane is currently colorized at all.

        The one gate, shared by the colorizer and the escape-sequence painter.
        Wire colours used to bypass it, which made "Enable colorization" off
        and "Apply to: raw only" both leak colour onto lines that carried
        escapes.
        """
        if not self._settings.color_enabled():
            return False
        apply_to = self._settings.color_apply_to()
        if apply_to == "none":
            return False
        if apply_to in ("raw", "filtered"):
            return pane == apply_to
        return True

    def _segments_for(
        self, text: str, spans: list, pane: str
    ) -> List[Tuple[str, QTextCharFormat]]:
        """Segments for a line already split by _split_ansi().

        Colours off the wire win over the colorizer for the lines that carry
        them; a line with no escapes is unaffected, so a build that colours
        only its warnings still gets level colouring everywhere else. Both
        paths answer to _colorization_active().
        """
        if spans:
            return ansi_segments(text, spans, self._colorization_active(pane))
        return self._get_segments(text, pane)

    def _get_segments(
        self, line: str, pane: str
    ) -> List[Tuple[str, QTextCharFormat]]:
        """Return (text, format) segments. pane is 'raw' or 'filtered'."""
        if not self._colorization_active(pane):
            return [(line, self._plain_fmt)]
        return self._colorizer.colorize(line)

    def _segments_for_block(
        self, block, pane: str
    ) -> List[Tuple[str, QTextCharFormat]]:
        """Segments for an existing block during a rebuild.

        Wire styles are recovered from the stored formats rather than
        recomputed, since the escapes that produced them are no longer in the
        block text — but they are re-applied through the current settings, so
        toggling colorization or apply-to is reversible for these lines too.
        Switching the mode away from 'render' releases them to the colorizer.

        Block text is re-split as well, so turning stripping *on* cleans up
        lines already on screen. The reverse cannot be undone: once an escape
        has been dropped from the document it is only in the session log.
        """
        if self._settings.ansi_mode() == "render":
            stored = block_ansi_styles(block)
            if stored is not None:
                active = self._colorization_active(pane)
                return [(text, ansi_fmt(style, active)) for text, style in stored]
        text, spans = self._split_ansi(block.text())
        return self._segments_for(text, spans, pane)

    # ------------------------------------------------------------------
    # Incoming lines
    # ------------------------------------------------------------------

    def _append_display_line(self, line: str, scroll: bool = True) -> None:
        """Append one incoming line to the raw pane, the filtered pane if it
        matches, and whichever minimaps are showing.

        The single entry point for display text in both windows, so the
        escape handling above cannot be applied inconsistently between them.
        """
        text, spans = self._split_ansi(line)
        self._raw_pane.append_line(self._segments_for(text, spans, "raw"), scroll=scroll)
        if self._minimap.isVisible():
            self._minimap.append_color(self._minimap_color_for(text))
        if self._rules and filter_engine.match(text, self._rules, self._filter_mode):
            self._filtered_pane.append_line(
                self._segments_for(text, spans, "filtered"), scroll=scroll
            )
            if self._filtered_minimap.isVisible():
                self._filtered_minimap.append_color(self._minimap_color_for(text))

    # ------------------------------------------------------------------
    # Pane rebuilds
    # ------------------------------------------------------------------

    def _rebuild_raw_pane(self) -> None:
        # The generator reads the pane's current document while replace_lines
        # fills a new one, so nothing has to be buffered in between.
        self._raw_pane.setUpdatesEnabled(False)
        self._raw_pane.replace_lines(
            self._segments_for_block(block, "raw")
            for block in iter_blocks(self._raw_pane.document())
        )
        self._raw_pane.setUpdatesEnabled(True)
        sb = self._raw_pane.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._minimap.isVisible():
            self._rebuild_raw_minimap()

    def _rebuild_filtered_pane(self) -> None:
        self._filtered_pane.setUpdatesEnabled(False)
        self._filtered_pane.replace_lines(
            self._segments_for_block(block, "filtered")
            for block in iter_blocks(self._raw_pane.document())
            if filter_engine.match(block.text(), self._rules, self._filter_mode)
        )
        self._filtered_pane.setUpdatesEnabled(True)
        sb = self._filtered_pane.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._update_pane_headers()
        if self._filtered_minimap.isVisible():
            self._rebuild_filtered_minimap()

    def _update_pane_headers(self) -> None:
        if self._filtered_box.isVisible():
            n = doc_line_count(self._filtered_pane)
            m = doc_line_count(self._raw_pane)
            self._filtered_header.setText(f"Filtered — {n:,} of {m:,} lines")

    # ------------------------------------------------------------------
    # Filtered pane visibility
    # ------------------------------------------------------------------

    def _ensure_filtered_box_visible(self) -> None:
        if not self._splitter_initialized:
            self._splitter_initialized = True
            h = self._splitter.height()
            if h > 0:
                self._splitter.setSizes(
                    [int(h * _RAW_SPLIT_FRACTION), int(h * (1 - _RAW_SPLIT_FRACTION))]
                )
        self._filtered_box.show()

    def _update_filtered_visibility(self) -> None:
        # The filter bar's input row lives above the filtered pane, so the
        # container must stay visible while it's open even before any rule
        # exists — otherwise there's no way to reach it to add the first rule.
        show = bool(self._rules) or self._filter_bar.is_input_bar_open()
        if show:
            self._ensure_filtered_box_visible()
        else:
            self._filtered_box.hide()
            self._filtered_pane.clear()

    def _on_filter_action_toggled(self, checked: bool) -> None:
        if checked:
            # Show the container before opening the row so it can take focus:
            # a hidden ancestor would swallow the setFocus() call.
            self._ensure_filtered_box_visible()
        if checked != self._filter_bar.is_input_bar_open():
            self._filter_bar.toggle_input_bar()
        if not checked:
            self._update_filtered_visibility()

    def _on_filter_bar_closed(self) -> None:
        self._filter_action.blockSignals(True)
        self._filter_action.setChecked(False)
        self._filter_action.blockSignals(False)
        self._update_filtered_visibility()

    # ------------------------------------------------------------------
    # Selection: starting one in either pane clears the other
    # ------------------------------------------------------------------

    def _clear_selection(self, pane) -> None:
        cursor = pane.textCursor()
        if cursor.hasSelection():
            pane.blockSignals(True)
            cursor.clearSelection()
            pane.setTextCursor(cursor)
            pane.blockSignals(False)

    def _on_raw_selection_changed(self) -> None:
        self._clear_selection(self._filtered_pane)

    def _on_filtered_selection_changed(self) -> None:
        self._clear_selection(self._raw_pane)

    def _jump_to_raw_line(self, line: str) -> None:
        """Select and center the first raw-pane block matching `line`."""
        doc = self._raw_pane.document()
        block = doc.begin()
        while block != doc.end():
            if block.text() == line:
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                self._raw_pane.setTextCursor(cursor)
                self._raw_pane.setFocus()
                self._raw_pane.ensureCursorVisible()
                rect = self._raw_pane.cursorRect()
                sb = self._raw_pane.verticalScrollBar()
                sb.setValue(
                    sb.value()
                    + rect.center().y()
                    - self._raw_pane.viewport().height() // 2
                )
                return
            block = block.next()

    # ------------------------------------------------------------------
    # Minimap
    # ------------------------------------------------------------------

    def _minimap_color_for(self, line: str) -> QColor:
        """Severity color for one line, independent of the colorization mode.

        The minimap shows severity even when colorization is off or set to
        syntax mode, so this goes through detect_level() rather than the
        Colorizer.
        """
        if line.startswith(">> "):
            return QColor(self._settings.tx_color())
        if line.startswith("---"):
            return QColor(active_colors()["separator"])
        level = detect_level(line)
        if level:
            return QColor(self._settings.level_color(level))
        return QColor(active_colors()["neutral_band"])

    def _rebuild_minimap(self, pane, minimap) -> None:
        doc = pane.document()
        if _is_empty_document(doc):
            minimap.set_colors([])
            return
        minimap.set_colors(
            [self._minimap_color_for(text) for text in iter_block_texts(doc)]
        )

    def _rebuild_raw_minimap(self) -> None:
        self._rebuild_minimap(self._raw_pane, self._minimap)

    def _rebuild_filtered_minimap(self) -> None:
        self._rebuild_minimap(self._filtered_pane, self._filtered_minimap)

    def _apply_minimap_settings(self) -> None:
        enabled = self._settings.minimap_enabled()
        apply_to = self._settings.minimap_apply_to()
        show_raw = enabled and apply_to in ("all", "raw")
        show_filtered = enabled and apply_to in ("all", "filtered")
        self._minimap.setVisible(show_raw)
        self._filtered_minimap.setVisible(show_filtered)
        if show_raw:
            self._rebuild_raw_minimap()
        else:
            self._minimap.clear()
        if show_filtered:
            self._rebuild_filtered_minimap()
        else:
            self._filtered_minimap.clear()

    @staticmethod
    def _viewport_fractions(sb) -> Optional[Tuple[float, float]]:
        total = sb.maximum() + sb.pageStep()
        if total <= 0:
            return None
        return sb.value() / total, (sb.value() + sb.pageStep()) / total

    def _update_minimap_viewport(self, *_args) -> None:
        fractions = self._viewport_fractions(self._raw_pane.verticalScrollBar())
        self._minimap.set_viewport(*(fractions or (0.0, 1.0)))

    def _update_filtered_minimap_viewport(self, *_args) -> None:
        fractions = self._viewport_fractions(self._filtered_pane.verticalScrollBar())
        self._filtered_minimap.set_viewport(*(fractions or (0.0, 1.0)))

    @staticmethod
    def _scroll_to_fraction(sb, frac: float) -> None:
        """Center the viewport on `frac` of the total scrollable content."""
        total = sb.maximum() + sb.pageStep()
        target = int(frac * total - sb.pageStep() / 2)
        sb.setValue(max(0, min(sb.maximum(), target)))

    def _on_minimap_clicked(self, frac: float) -> None:
        self._scroll_to_fraction(self._raw_pane.verticalScrollBar(), frac)

    def _on_filtered_minimap_clicked(self, frac: float) -> None:
        self._scroll_to_fraction(self._filtered_pane.verticalScrollBar(), frac)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _on_settings_changed(self) -> None:
        """Colorization/minimap settings changed — refresh every window.

        They all read the same AppSettings, so refreshing only the window
        whose sidebar emitted the change left the rest rendering with the old
        settings.
        """
        for window in open_log_windows():
            window._apply_display_settings()

    def _apply_display_settings(self) -> None:
        self._rebuild_raw_pane()
        if self._filtered_pane.isVisible():
            self._rebuild_filtered_pane()
        self._apply_minimap_settings()

    def _on_theme_changed(self, theme: str) -> None:
        # The palette is application-wide, but the log-pane chrome, minimap
        # bands and plain-line colour come from theme.active_colors() and are
        # baked into stylesheets and text formats, so every window has to be
        # restyled and rebuilt for the switch to take.
        apply_palette(QApplication.instance(), theme)
        for window in open_log_windows():
            window._apply_theme()

    def _apply_theme(self) -> None:
        self._plain_fmt = _fmt(_plain_color())
        restyle_pane_header(self._raw_header)
        restyle_pane_header(self._filtered_header)
        for pane in (self._raw_pane, self._filtered_pane):
            restyle_pane(pane)
        for minimap in (self._minimap, self._filtered_minimap):
            minimap.restyle()
        self._filter_bar.restyle()
        find_bar = getattr(self, "_find_bar", None)
        if find_bar is not None:
            find_bar.restyle()
        self._apply_display_settings()

    def _on_font_size_changed(self, size: int) -> None:
        for window in open_log_windows():
            window._apply_font_size(size)

    def _apply_font_size(self, size: int) -> None:
        for pane in (self._raw_pane, self._filtered_pane):
            f = pane.font()
            f.setPointSize(size)
            pane.setFont(f)
