# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the stateless filter engine."""

import pytest

from app import filter_engine
from app.log_format import detect_level


def sub(value, mode="include"):
    return {"type": "substring", "value": value, "mode": mode}


def rgx(value, mode="include"):
    return {"type": "regex", "value": value, "mode": mode}


def lvl(value, mode="include"):
    return {"type": "level", "value": value, "mode": mode}


def mod(value, mode="include"):
    return {"type": "module", "value": value, "mode": mode}


ZEPHYR = "[00:00:01.234,567] <inf> my_module: Some message here"
ZEPHYR_ERR = "[00:00:01.234,567] <err> net_if: Something failed: -5"
# Full-date variant with no space before the level tag, seen on some boards.
ZEPHYR_NOSPACE = "[2026-07-06 11:21:45.726]<inf> telit_modem: state=0"


class TestNoRules:
    def test_empty_rule_list_passes_everything(self):
        assert filter_engine.match("anything at all", [], "OR") is True

    def test_excludes_only_still_pass_non_matching(self):
        assert filter_engine.match("hello", [sub("world", "exclude")], "OR") is True


class TestSubstring:
    def test_match(self):
        assert filter_engine.match("hello world", [sub("world")], "OR") is True

    def test_no_match(self):
        assert filter_engine.match("hello", [sub("world")], "OR") is False

    def test_is_case_sensitive(self):
        assert filter_engine.match("ERROR here", [sub("error")], "OR") is False


class TestCombination:
    def test_or_needs_only_one(self):
        rules = [sub("alpha"), sub("beta")]
        assert filter_engine.match("alpha only", rules, "OR") is True

    def test_and_needs_all(self):
        rules = [sub("alpha"), sub("beta")]
        assert filter_engine.match("alpha only", rules, "AND") is False
        assert filter_engine.match("alpha and beta", rules, "AND") is True

    def test_exclude_beats_include_in_or_mode(self):
        rules = [sub("alpha"), sub("secret", "exclude")]
        assert filter_engine.match("alpha secret", rules, "OR") is False

    def test_exclude_beats_include_in_and_mode(self):
        rules = [sub("alpha"), sub("secret", "exclude")]
        assert filter_engine.match("alpha secret", rules, "AND") is False

    def test_no_includes_means_pass_subject_to_excludes(self):
        rules = [sub("secret", "exclude")]
        assert filter_engine.match("public line", rules, "AND") is True
        assert filter_engine.match("secret line", rules, "AND") is False


class TestRegex:
    def test_search_semantics_not_fullmatch(self):
        assert filter_engine.match("abc123", [rgx(r"\d+")], "OR") is True

    def test_invalid_pattern_never_matches(self):
        """An unparseable pattern must not raise out of the engine."""
        assert filter_engine.match("anything", [rgx("(unclosed")], "OR") is False

    def test_invalid_exclude_pattern_fails_open(self):
        """Documented consequence of the above: a broken exclude excludes nothing.

        FilterBar validates patterns at entry so this should not be reachable
        from the UI, but the engine itself must stay total.
        """
        assert filter_engine.match("anything", [rgx("(unclosed", "exclude")], "OR") is True


class TestLevel:
    def test_matches_explicit_tag(self):
        assert filter_engine.match(ZEPHYR_ERR, [lvl("err")], "OR") is True

    def test_rejects_other_tag(self):
        assert filter_engine.match(ZEPHYR, [lvl("err")], "OR") is False

    def test_agrees_with_the_colorizer_on_keyword_severity(self):
        """A line the colorizer paints <err> must match a level:err rule.

        Level rules used to require an explicit <tag>, so syslog and
        unstructured lines were coloured by severity yet invisible to level
        filters — the same line looked red and did not match "err".
        """
        line = "Jun 14 10:23:45 host app[1]: fatal error occurred"
        assert detect_level(line) == "err"
        assert filter_engine.match(line, [lvl("err")], "OR") is True

    @pytest.mark.parametrize(
        "line,level",
        [
            ("connection warning raised", "wrn"),
            ("info: link established", "inf"),
            ("trace point reached", "dbg"),
        ],
    )
    def test_keyword_levels_are_filterable(self, line, level):
        assert filter_engine.match(line, [lvl(level)], "OR") is True

    def test_explicit_tag_still_wins_over_a_keyword_in_the_message(self):
        line = "[00:00:01.000,000] <dbg> mod: an error occurred"
        assert filter_engine.match(line, [lvl("dbg")], "OR") is True
        assert filter_engine.match(line, [lvl("err")], "OR") is False

    def test_unleveled_line_matches_nothing(self):
        line = "just some plain text"
        for level in ("dbg", "inf", "wrn", "err"):
            assert filter_engine.match(line, [lvl(level)], "OR") is False

    def test_exclude_by_level_drops_keyword_matches_too(self):
        line = "Jun 14 10:23:45 host app[1]: fatal error occurred"
        assert filter_engine.match(line, [lvl("err", "exclude")], "OR") is False


class TestModule:
    def test_exact(self):
        assert filter_engine.match(ZEPHYR, [mod("my_module")], "OR") is True

    def test_prefix(self):
        assert filter_engine.match(ZEPHYR, [mod("my_")], "OR") is True

    def test_non_matching_module(self):
        assert filter_engine.match(ZEPHYR, [mod("other")], "OR") is False

    def test_zephyr_variant_without_space_before_tag(self):
        assert filter_engine.match(ZEPHYR_NOSPACE, [mod("telit")], "OR") is True


class TestMalformedRules:
    def test_unknown_rule_type_never_matches(self):
        rule = {"type": "bogus", "value": "x", "mode": "include"}
        assert filter_engine.match("x", [rule], "OR") is False

    def test_missing_mode_key_defaults_to_include(self):
        rule = {"type": "substring", "value": "hit"}
        assert filter_engine.match("hit", [rule], "OR") is True
        assert filter_engine.match("miss", [rule], "OR") is False


@pytest.mark.parametrize("mode", ["AND", "OR", "nonsense"])
def test_unknown_mode_falls_back_to_or(mode):
    """Anything that is not 'AND' is treated as OR."""
    rules = [sub("alpha"), sub("beta")]
    expected = mode != "AND"
    assert filter_engine.match("alpha only", rules, mode) is expected


class TestCaseInsensitiveRules:
    def test_substring_ignore_case(self):
        rule = {"type": "substring", "value": "error", "mode": "include",
                "ignore_case": True}
        assert filter_engine.match("ERROR here", [rule], "OR") is True

    def test_substring_case_sensitive_by_default(self):
        assert filter_engine.match("ERROR here", [sub("error")], "OR") is False

    def test_explicit_false_is_case_sensitive(self):
        rule = {"type": "substring", "value": "error", "mode": "include",
                "ignore_case": False}
        assert filter_engine.match("ERROR here", [rule], "OR") is False

    def test_regex_ignore_case(self):
        rule = {"type": "regex", "value": r"err\w+", "mode": "include",
                "ignore_case": True}
        assert filter_engine.match("ERRORS everywhere", [rule], "OR") is True

    def test_regex_case_sensitive_by_default(self):
        assert filter_engine.match("ERRORS everywhere", [rgx(r"err\w+")], "OR") is False

    def test_ignore_case_applies_to_excludes_too(self):
        rule = {"type": "substring", "value": "secret", "mode": "exclude",
                "ignore_case": True}
        assert filter_engine.match("SECRET payload", [rule], "OR") is False

    def test_ignore_case_is_ignored_for_level_rules(self):
        """Level keys are already normalised, so the flag is a no-op there."""
        rule = {"type": "level", "value": "err", "mode": "include",
                "ignore_case": True}
        assert filter_engine.match(ZEPHYR_ERR, [rule], "OR") is True
