# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Stateless filter logic. A filter rule is a dict with keys:
  type: 'substring' | 'regex' | 'level' | 'module'
  value: str
  mode: 'include' | 'exclude'
match(line, rules) returns True if the line should be displayed."""

import re

from app.log_format import detect_level, module_of


def _matches_rule(line: str, rule: dict) -> bool:
    t = rule["type"]
    v = rule["value"]
    if t == "substring":
        return v in line
    if t == "regex":
        try:
            return bool(re.search(v, line))
        except re.error:
            return False
    if t == "level":
        # Shares detect_level() with the colorizer, so a line shown in the
        # <err> colour is matched by a level:err rule. Matching only an
        # explicit <tag> here meant syslog and unstructured lines were
        # coloured by severity but invisible to level filters.
        return detect_level(line) == v
    if t == "module":
        module = module_of(line)
        return module is not None and module.startswith(v)
    return False


def match(line: str, rules: list, mode: str = "OR") -> bool:
    """Return True if line should be shown given rules and AND/OR mode.

    Exclude rules always win. Include rules are combined with AND or OR.
    If there are no include rules the line passes (subject to excludes).
    """
    if not rules:
        return True

    includes = [r for r in rules if r.get("mode", "include") == "include"]
    excludes = [r for r in rules if r.get("mode", "include") == "exclude"]

    for rule in excludes:
        if _matches_rule(line, rule):
            return False

    if not includes:
        return True

    if mode == "AND":
        return all(_matches_rule(line, r) for r in includes)
    return any(_matches_rule(line, r) for r in includes)
