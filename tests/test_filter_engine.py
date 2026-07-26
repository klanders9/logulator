# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Tests for the stateless filter engine."""

import pytest

from app import filter_engine


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
