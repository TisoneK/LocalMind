"""B-2026-08-25-1: system_search parses a leading operation keyword.

Weak models (and the shell→system_search redirect) hand the tool plain text
like "largest /Users/x" rather than JSON. Without keyword parsing that ran a
files search for a file NAMED "largest" — garbage. `_parse_plain_query` maps a
leading operation word to the right op, a path-like token to `root`, and the
rest to `query`; a non-keyword string stays a name search.
"""

from __future__ import annotations

from tools.system_search import _parse_plain_query


def test_leading_keyword_selects_operation() -> None:
    assert _parse_plain_query("largest /Users/bao *") == {"operation": "largest", "root": "/Users/bao"}
    assert _parse_plain_query("largest")["operation"] == "largest"
    assert _parse_plain_query("recent")["operation"] == "recent"
    assert _parse_plain_query("biggest ~/Downloads")["operation"] == "largest"
    assert _parse_plain_query("duplicates photos")["operation"] == "duplicates"
    assert _parse_plain_query("installed python")["operation"] == "apps"


def test_path_token_becomes_root_rest_becomes_query() -> None:
    got = _parse_plain_query("files report ~/Documents")
    assert got["operation"] == "files"
    assert got["root"] == "~/Documents"
    assert got["query"] == "report"


def test_glob_all_star_is_dropped() -> None:
    assert "query" not in _parse_plain_query("largest /Users/bao *")


def test_non_keyword_stays_a_name_search() -> None:
    assert _parse_plain_query("README") == {"operation": "files", "query": "README"}
    assert _parse_plain_query("find loop.py") == {"operation": "files", "query": "loop.py"}
