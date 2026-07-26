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

    def test_rebuilding_leaves_no_orphan_chips(self, bar):
        for v in ("a", "b", "c"):
            bar.add_rule(v)
        bar._remove_rule(1)
        assert len(chip_children(bar)) == len(chips(bar)) == 2

    def test_clearing_all_rules_removes_every_chip(self, bar):
        bar.add_rule("a")
        bar.add_rule("b")
        bar._remove_rule(0)
        bar._remove_rule(0)
        assert chip_children(bar) == []



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


class TestRegexValidation:
    def test_invalid_pattern_is_rejected(self, bar):
        bar._type_combo.setCurrentText("regex")
        bar._input.setText("(unclosed")
        bar._add_rule()
        assert bar.get_rules() == []

    def test_invalid_pattern_keeps_the_text_for_editing(self, bar):
        bar._type_combo.setCurrentText("regex")
        bar._input.setText("(unclosed")
        bar._add_rule()
        assert bar._input.text() == "(unclosed"

    def test_invalid_pattern_explains_itself(self, bar):
        bar._type_combo.setCurrentText("regex")
        bar._input.setText("(unclosed")
        bar._add_rule()
        assert "Invalid regular expression" in bar._input.toolTip()
        assert bar._input.styleSheet() != ""

    def test_invalid_pattern_emits_nothing(self, bar):
        emitted = []
        bar.filters_changed.connect(lambda *a: emitted.append(a))
        bar._type_combo.setCurrentText("regex")
        bar._input.setText("(unclosed")
        bar._add_rule()
        assert emitted == []

    def test_editing_clears_the_error_state(self, bar):
        bar._type_combo.setCurrentText("regex")
        bar._input.setText("(unclosed")
        bar._add_rule()
        bar._input.textEdited.emit("(unclosed)")
        assert bar._input.styleSheet() == ""
        assert bar._input.toolTip() == ""

    def test_valid_pattern_is_accepted(self, bar):
        bar._type_combo.setCurrentText("regex")
        bar._input.setText(r"err\w+")
        bar._add_rule()
        assert bar.get_rules()[0]["value"] == r"err\w+"

    def test_fixing_the_pattern_then_adding_works(self, bar):
        bar._type_combo.setCurrentText("regex")
        bar._input.setText("(unclosed")
        bar._add_rule()
        bar._input.setText("(closed)")
        bar._add_rule()
        assert [r["value"] for r in bar.get_rules()] == ["(closed)"]
        assert bar._input.styleSheet() == ""

    def test_other_rule_types_are_not_regex_validated(self, bar):
        """"(unclosed" is a perfectly good substring."""
        bar._type_combo.setCurrentText("substring")
        bar._input.setText("(unclosed")
        bar._add_rule()
        assert bar.get_rules()[0]["value"] == "(unclosed"

    def test_invalid_exclude_pattern_is_also_rejected(self, bar):
        """The dangerous case: a broken exclude used to silently exclude nothing."""
        bar._type_combo.setCurrentText("regex")
        bar._inc_exc_combo.setCurrentText("exclude")
        bar._input.setText("[")
        bar._add_rule()
        assert bar.get_rules() == []


class TestLevelRuleEditor:
    """Level rules take fixed keys, so the value must be picked, not typed.

    Typing "warning", "<wrn>", "warn" or "WRN" all silently matched nothing;
    only the internal key "wrn" worked, and nothing in the UI said so.
    """

    def test_level_type_swaps_in_the_dropdown(self, bar):
        bar._type_combo.setCurrentText("level")
        assert bar._level_combo.isVisible() or not bar._input.isVisible()
        assert bar._input.isVisible() is False

    def test_other_types_use_the_text_box(self, bar):
        bar._type_combo.setCurrentText("level")
        bar._type_combo.setCurrentText("substring")
        assert bar._level_combo.isVisible() is False

    def test_dropdown_offers_exactly_the_four_levels(self, bar):
        keys = [bar._level_combo.itemData(i) for i in range(bar._level_combo.count())]
        assert keys == ["err", "wrn", "inf", "dbg"]

    def test_labels_name_the_keywords_they_match(self, bar):
        """The label is the only place the keyword fallback is documented."""
        labels = [bar._level_combo.itemText(i) for i in range(bar._level_combo.count())]
        joined = " ".join(labels)
        for word in ("<err>", "fatal", "warning", "notice", "trace"):
            assert word in joined

    def test_adding_a_level_rule_uses_the_key_not_the_label(self, bar):
        bar._type_combo.setCurrentText("level")
        bar._level_combo.setCurrentIndex(1)  # wrn
        bar._add_rule()
        assert bar.get_rules() == [
            {"type": "level", "value": "wrn", "mode": "include", "ignore_case": False}
        ]

    def test_level_rule_needs_no_text_in_the_box(self, bar):
        bar._type_combo.setCurrentText("level")
        bar._input.clear()
        bar._add_rule()
        assert len(bar.get_rules()) == 1

    def test_level_rule_honours_include_exclude(self, bar):
        bar._type_combo.setCurrentText("level")
        bar._inc_exc_combo.setCurrentText("exclude")
        bar._add_rule()
        assert bar.get_rules()[0]["mode"] == "exclude"

    def test_stale_text_in_the_box_is_ignored(self, bar):
        bar._input.setText("warning")
        bar._type_combo.setCurrentText("level")
        bar._add_rule()
        assert bar.get_rules()[0]["value"] == "err"


class TestValueHints:
    def test_each_text_type_explains_what_it_wants(self, bar):
        for rule_type, expected in [
            ("substring", "Text to match…"),
            ("regex", "Regular expression…"),
            ("module", "Module name or prefix…"),
        ]:
            bar._type_combo.setCurrentText(rule_type)
            assert bar._input.placeholderText() == expected

    def test_match_case_is_disabled_where_it_does_nothing(self, bar):
        for rule_type in ("level", "module"):
            bar._type_combo.setCurrentText(rule_type)
            assert bar._case_btn.isEnabled() is False
        for rule_type in ("substring", "regex"):
            bar._type_combo.setCurrentText(rule_type)
            assert bar._case_btn.isEnabled() is True
