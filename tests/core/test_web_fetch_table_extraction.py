"""web_fetch must not concatenate table-cell values into an unreadable run.

Regression (B-2026-09-01 EPL-table trace): _extract_readable_content converted
<tr> to a newline but stripped <td>/<th> to nothing, so a standings row
'<td>6</td><td>2</td>...' collapsed to '62...' ('22006246'). The model then
burned iterations guess-parsing ambiguous digit runs and hit iteration_limit.
Cells now get a ' | ' separator; rows stay on their own lines.
"""

from __future__ import annotations

from tools.web_fetch import _extract_readable_content


_TABLE_HTML = """
<html><body>
<table>
<tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>F</th><th>A</th><th>GD</th><th>Pts</th></tr>
<tr><td>Manchester City</td><td>2</td><td>2</td><td>0</td><td>0</td><td>6</td><td>2</td><td>4</td><td>6</td></tr>
<tr><td>Arsenal</td><td>2</td><td>2</td><td>0</td><td>0</td><td>4</td><td>0</td><td>4</td><td>6</td></tr>
</table>
</body></html>
"""


def test_table_cells_are_separated_not_concatenated():
    out = _extract_readable_content(_TABLE_HTML)
    # The pre-fix bug produced a concatenated run like "22006246".
    assert "22006246" not in out
    # Each cell value survives as its own token, separated.
    assert "Manchester City" in out
    # The row's numeric cells are individually recoverable (order preserved).
    row = next(ln for ln in out.splitlines() if "Manchester City" in ln)
    nums = [t for t in row.replace("|", " ").split() if t.isdigit()]
    assert nums == ["2", "2", "0", "0", "6", "2", "4", "6"], nums


def test_rows_stay_on_separate_lines():
    out = _extract_readable_content(_TABLE_HTML)
    city = next(ln for ln in out.splitlines() if "Manchester City" in ln)
    ars = next(ln for ln in out.splitlines() if "Arsenal" in ln)
    assert city != ars  # two teams never share a line


def test_non_table_text_unaffected():
    out = _extract_readable_content("<html><body><p>Hello world</p></body></html>")
    assert "Hello world" in out
    assert "|" not in out
