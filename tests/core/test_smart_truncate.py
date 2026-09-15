"""smart_truncate: table-aware, line-boundary truncation.

Regression: a blunt text[:cap] severed data tables mid-row
(EPL standings lost rows 5-16), so the model chased more sources. smart_truncate
cuts on a line boundary and keeps a table that straddles the cut whole.
"""

from __future__ import annotations

from tools.web_fetch import smart_truncate


def _table(n: int) -> str:
    return "\n".join(f"Team{i} | 2 | 2 | 0 | 0 | {i} | 1 | 6" for i in range(1, n + 1))


def test_short_text_unchanged():
    assert smart_truncate("hello", 100) == "hello"


def test_cuts_on_line_boundary_not_midword():
    text = "\n".join(f"line number {i} with words" for i in range(400))
    out = smart_truncate(text, 500)
    body = out.replace("[... content truncated]", "").rstrip()
    # last kept line is a complete line (ends with the full trailing word)
    assert body.endswith("words")


def test_straddling_table_is_kept_whole():
    # Prose then a 20-row table so the cap lands INSIDE the table (the real
    # case: after nav removal the data table sits near the top and straddles
    # the cut). Every row of the straddled table must survive.
    prefix = "padding line\n" * 380  # ~4.9KB
    body = prefix + _table(20) + "\nAFTER"
    cut = len(prefix) + len(_table(8))  # cap falls around row ~8 of the table
    out = smart_truncate(body, cut)
    assert all(f"Team{i} |" in out for i in range(1, 21)), "table rows dropped"


def test_hard_ceiling_bounds_pathological_table():
    # A table far larger than the ceiling can't blow output past ~1.75*cap.
    body = "prefix\n" + _table(5000)
    out = smart_truncate(body, 4000)
    assert len(out) <= int(4000 * 1.75) + 64


def test_marker_appended_when_truncated():
    out = smart_truncate("x" * 5000, 1000)
    assert out.endswith("[... content truncated]")
