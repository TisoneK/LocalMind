"""Tests for the bounded CSV tool (B-2026-07-31-10, Session 131)."""

import asyncio

import core.config as cfg
import pytest
from core.models import Intent
from tools import dispatch
from tools.csv_tool import _csv_read


@pytest.fixture
def allow_tmp(tmp_path):
    """Allow pytest's tmp_path in the read-path allowlist (find_path/observe pattern)."""
    original = cfg._allowed_user_folders
    cfg._allowed_user_folders = lambda: [
        str(tmp_path),
        str(tmp_path.resolve()),
        str(__import__("pathlib").Path.home()),
    ]
    yield tmp_path
    cfg._allowed_user_folders = original


def test_reads_bounded_table(allow_tmp):
    p = allow_tmp / "t.csv"
    p.write_text("name,age,city\nAlice,30,NYC\nBob,25,SF\n")
    out = _csv_read(str(p))
    assert "3 rows × 3 cols" in out
    assert "Alice | 30  | NYC" in out
    assert "Bob" in out


def test_truncates_rows(allow_tmp):
    p = allow_tmp / "big.csv"
    p.write_text("h1,h2\n" + "a,b\n" * 100)
    out = _csv_read(str(p), max_rows=5)
    assert "101 rows × 2 cols" in out
    assert "… 96 more rows (capped at 5)" in out
    assert "a" in out and "h1" in out


def test_truncates_columns(allow_tmp):
    p = allow_tmp / "wide.csv"
    p.write_text("c1,c2,c3,c4,c5\n1,2,3,4,5\n")
    out = _csv_read(str(p), max_cols=2)
    assert "2 rows × 5 cols" in out
    assert "… 3 more columns (capped at 2)" in out


def test_rejects_disallowed_path(tmp_path):
    # tmp_path is NOT in the allowlist here (no allow_tmp fixture)
    out = _csv_read(str(tmp_path / "secret.csv"))
    assert "path not allowed" in out


def test_missing_file(allow_tmp):
    out = _csv_read(str(allow_tmp / "nope.csv"))
    assert "cannot read" in out


def test_empty_file(allow_tmp):
    p = allow_tmp / "empty.csv"
    p.write_text("")
    out = _csv_read(str(p))
    assert "empty" in out


def test_never_raises_on_garbage(allow_tmp):
    p = allow_tmp / "garbage.csv"
    p.write_bytes(b"\x00\x01\x02 not csv at all" * 10)
    out = _csv_read(str(p))
    assert isinstance(out, str) and out  # degrades, never raises


def test_clamps_bounds(allow_tmp):
    p = allow_tmp / "t.csv"
    p.write_text("a\nb\nc\n")
    out = _csv_read(str(p), max_rows=0, max_cols=0)  # invalid bounds → clamped
    assert "3 rows × 1 cols" in out


def test_bom_and_latin1_tolerated(allow_tmp):
    p = allow_tmp / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbfh1,h2\r\n1,2\r\n")  # UTF-8 BOM + CRLF
    out = _csv_read(str(p))
    assert "2 rows × 2 cols" in out
    assert "h1" in out


def test_dispatch_csv_registered(allow_tmp):
    p = allow_tmp / "t.csv"
    p.write_text("x,y\n1,2\n")
    args = f'{{"path": "{p}", "max_rows": 1}}'
    result = asyncio.run(dispatch(Intent.CSV, args))
    assert result is not None
    assert "2 rows × 2 cols" in result.content
    assert result.source == "csv"
