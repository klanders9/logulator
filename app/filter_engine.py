"""Stateless filter logic. A filter rule is a dict with keys:
  type: 'substring' | 'regex' | 'level' | 'module'
  value: str
  mode: 'include' | 'exclude'
match(line, rules) returns True if the line should be displayed."""
