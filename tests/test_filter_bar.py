# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the FilterBar widget: rule management and the chip strip."""

import pytest

from app.ui.filter_bar import FilterBar, _RuleChip, _chip_label_text


@pytest.fixture
def bar(qtbot):
    # Registered with qtbot so the widget's lifetime is deterministic.
    # _rebuild_chips retires chips with deleteLater(), and those deferred
    # deletions must not outlive the FilterBar that parents them — if Python
    # collects the bar first, the queued deletion fires against a freed parent
    # in whatever nested event loop runs next.
    bar = FilterBar()
    qtbot.addWidget(bar)
    return bar


def chips(bar):
    """Chips currently held by the strip's layout (the trailing stretch aside)."""
    layout = bar._chip_layout
    items = [layout.itemAt(i).widget() for i in range(layout.count())]
    return [w for w in items if isinstance(w, _RuleChip)]


def chip_children(bar):
    """Every chip still parented to the container, laid out or not."""
    return bar._chip_container.findChildren(_RuleChip)


class TestRuleManagement:
    def test_starts_empty(self, bar):
        assert bar.get_rules() == []
        assert bar.get_mode() == "OR"

    def test_add_rule_emits_and_stores(self, bar, qtbot):
        with qtbot.waitSignal(bar.filters_changed) as blocker:
            bar.add_rule("boom", "substring", "include")
        rules, mode = blocker.args
        assert rules == [
            {"type": "substring", "value": "boom", "mode": "include",
             "ignore_case": False}
        ]
        assert mode == "OR"
        assert bar.get_rules() == rules

    def test_add_rule_defaults(self, bar):
        bar.add_rule("boom")
        assert bar.get_rules()[0]["type"] == "substring"
        assert bar.get_rules()[0]["mode"] == "include"

    def test_get_rules_returns_a_copy(self, bar):
        bar.add_rule("boom")
        bar.get_rules().append("garbage")
        assert len(bar.get_rules()) == 1

    def test_input_row_add_uses_current_selectors(self, bar, qtbot):
        bar._input.setText("net_if")
        bar._type_combo.setCurrentText("module")
        bar._inc_exc_combo.setCurrentText("exclude")
        bar._add_rule()
        assert bar.get_rules() == [
            {"type": "module", "value": "net_if", "mode": "exclude",
             "ignore_case": False}
        ]

    def test_input_is_cleared_after_add(self, bar):
        bar._input.setText("boom")
        bar._add_rule()
        assert bar._input.text() == ""

    def test_blank_input_is_ignored(self, bar):
        bar._input.setText("   ")
        bar._add_rule()
        assert bar.get_rules() == []

    def test_value_is_stripped(self, bar):
        bar._input.setText("  spaced  ")
        bar._add_rule()
        assert bar.get_rules()[0]["value"] == "spaced"


class TestChips:
    def test_one_chip_per_rule(self, bar):
        bar.add_rule("a")
        bar.add_rule("b")
        assert len(chips(bar)) == 2

    def test_strip_hidden_when_no_rules(self, bar):
        assert not bar._chip_scroll.isVisible()

    @pytest.mark.xfail(
        strict=True,
        reason="_rebuild_chips only calls deleteLater(), so removed chips stay "
               "parented and keep painting until the event loop runs",
    )
    def test_removed_chips_are_detached_immediately(self, bar):
        bar.add_rule("a")
        bar.add_rule("b")
        bar._remove_rule(0)
        assert len(chip_children(bar)) == 1

    def test_removing_the_right_rule_when_several_exist(self, bar):
        """Chip callbacks close over an index, so removal must not go stale."""
        bar.add_rule("first")
        bar.add_rule("second")
        bar.add_rule("third")
        bar._remove_rule(1)
        assert [r["value"] for r in bar.get_rules()] == ["first", "third"]

    def test_removing_repeatedly_stays_consistent(self, bar):
        for v in ("a", "b", "c", "d"):
            bar.add_rule(v)
        bar._remove_rule(0)
        bar._remove_rule(0)
        assert [r["value"] for r in bar.get_rules()] == ["c", "d"]

    def test_remove_emits_filters_changed(self, bar, qtbot):
        bar.add_rule("a")
        with qtbot.waitSignal(bar.filters_changed) as blocker:
            bar._remove_rule(0)
        assert blocker.args[0] == []


class TestChipLabels:
    @pytest.mark.parametrize(
        "rule,expected",
        [
            ({"type": "substring", "value": "boom", "mode": "include"}, "+ sub: boom"),
            ({"type": "level", "value": "err", "mode": "exclude"}, "− lvl: err"),
            ({"type": "regex", "value": r"\d+", "mode": "include"}, r"+ rgx: \d+"),
            ({"type": "module", "value": "net", "mode": "include"}, "+ mod: net"),
        ],
    )
    def test_label_text(self, rule, expected):
        assert _chip_label_text(rule) == expected

    def test_long_values_are_elided(self):
        rule = {"type": "substring", "value": "x" * 40, "mode": "include"}
        label = _chip_label_text(rule)
        assert label.endswith("…")
        assert len(label) < 30


class TestModeToggle:
    def test_toggle_switches_to_and(self, bar, qtbot):
        with qtbot.waitSignal(bar.filters_changed) as blocker:
            bar._mode_btn.setChecked(True)
        assert blocker.args[1] == "AND"
        assert bar.get_mode() == "AND"

    def test_toggle_back_to_or(self, bar):
        bar._mode_btn.setChecked(True)
        bar._mode_btn.setChecked(False)
        assert bar.get_mode() == "OR"

    def test_button_label_tracks_mode(self, bar):
        bar._mode_btn.setChecked(True)
        assert bar._mode_btn.text() == "Mode: AND"


class TestInputBar:
    def test_closed_by_default(self, bar):
        assert bar.is_input_bar_open() is False

    def test_toggle_opens_and_closes(self, bar):
        bar.toggle_input_bar()
        assert bar.is_input_bar_open() is True
        bar.toggle_input_bar()
        assert bar.is_input_bar_open() is False

    def test_close_emits_input_bar_closed(self, bar, qtbot):
        bar.toggle_input_bar()
        with qtbot.waitSignal(bar.input_bar_closed):
            bar.toggle_input_bar()

    def test_open_state_survives_a_hidden_ancestor(self, qtbot):
        """is_input_bar_open() tracks an explicit flag, not composed visibility.

        The bar lives inside the filtered pane container, which is itself
        hidden until a rule exists, so Qt would report the row as not visible
        while it is logically open.

        Builds its own bar rather than taking the fixture: the host owns the
        bar once it is added to the layout, so registering both with qtbot
        would double-free at teardown.
        """
        from PySide6.QtWidgets import QWidget, QVBoxLayout

        host = QWidget()
        qtbot.addWidget(host)
        bar = FilterBar()
        QVBoxLayout(host).addWidget(bar)
        host.hide()
        bar.toggle_input_bar()
        assert bar._input_row.isVisible() is False
        assert bar.is_input_bar_open() is True


class TestCaseSensitivity:
    def test_match_case_is_on_by_default(self, bar):
        assert bar._case_btn.isChecked() is True

    def test_rule_added_with_match_case_on_is_case_sensitive(self, bar):
        bar._input.setText("Error")
        bar._add_rule()
        assert bar.get_rules()[0]["ignore_case"] is False

    def test_unchecking_match_case_produces_an_insensitive_rule(self, bar):
        bar._case_btn.setChecked(False)
        bar._input.setText("Error")
        bar._add_rule()
        assert bar.get_rules()[0]["ignore_case"] is True

    def test_programmatic_add_defaults_to_case_sensitive(self, bar):
        bar.add_rule("Error")
        assert bar.get_rules()[0]["ignore_case"] is False

    def test_programmatic_add_can_request_insensitive(self, bar):
        bar.add_rule("Error", ignore_case=True)
        assert bar.get_rules()[0]["ignore_case"] is True

    def test_chip_marks_case_insensitive_rules(self):
        rule = {"type": "substring", "value": "boom", "mode": "include",
                "ignore_case": True}
        assert _chip_label_text(rule) == "+ sub/i: boom"

    def test_chip_unmarked_when_case_sensitive(self):
        rule = {"type": "substring", "value": "boom", "mode": "include",
                "ignore_case": False}
        assert _chip_label_text(rule) == "+ sub: boom"
