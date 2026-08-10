"""Tests for the bounded JSON tool (B-2026-07-31-10, Session 131)."""

import asyncio

import core.config as cfg
import pytest
from core.models import Intent
from tools import dispatch
from tools.json_tool import _json_query


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


def test_parses_inline_object():
    out = _json_query('{"a": 1, "b": "x"}')
    assert '"a": 1' in out
    assert "object with 2 keys" in out


def test_parses_inline_array():
    out = _json_query("[1, 2, 3]")
    assert "array of 3 items" in out


def test_dot_path_query():
    out = _json_query('{"a": {"b": [10, 20, 30]}, "x": "y"}', query="a.b[1]")
    assert out == "20"


def test_dot_path_missing_key():
    out = _json_query('{"a": 1}', query="a.b")
    # the current value is an int, not an object → clear message
    assert "needs an object" in out


def test_dot_path_bad_index():
    out = _json_query('{"a": [1, 2]}', query="a[5]")
    assert "out of range" in out


def test_invalid_json():
    out = _json_query("not json at all")
    assert "not valid JSON" in out


def test_reads_allowed_file(allow_tmp):
    p = allow_tmp / "t.json"
    p.write_text('{"users": [{"name": "u1"}, {"name": "u2"}], "meta": {"n": 2}}')
    out = _json_query(str(p))
    assert "source:" in out  # file sources are labelled
    assert '"name": "u1"' in out


def test_file_dot_path(allow_tmp):
    p = allow_tmp / "t.json"
    p.write_text('{"users": [{"name": "u1"}, {"name": "u2"}], "meta": {"n": 2}}')
    out = _json_query(str(p), query="users[1].name")
    assert out.endswith("u2")  # file sources carry a "source:" prefix line


def test_rejects_disallowed_path(tmp_path):
    p = tmp_path / "secret.json"
    p.write_text('{"secret": true}')  # file exists but tmp_path is NOT allowed here
    out = _json_query(str(p))
    assert "path not allowed" in out


def test_missing_file_is_clear_error():
    # A non-JSON, non-existent path → json.loads gives a clear error
    out = _json_query("/nonexistent/definitely/not/here.json")
    assert "Error:" in out


def test_large_collection_summarized_not_dumped():
    import json

    big_list = [{"id": i, "data": "x" * 10} for i in range(500)]
    out = _json_query(json.dumps(big_list))
    assert "(array of 500 items)" in out
    assert "… 480 more items" in out
    assert len(out) < 2000  # bounded output

    big_dict = {f"k{i}": i for i in range(500)}
    out = _json_query(json.dumps(big_dict))
    assert "… 480 more keys" in out
    assert len(out) < 2000  # bounded output


def test_never_raises_on_garbage(allow_tmp):
    p = allow_tmp / "garbage.json"
    p.write_bytes(b"\x00\xff\xfe broken")
    out = _json_query(str(p))
    assert isinstance(out, str) and out


def test_dispatch_json_registered():
    result = asyncio.run(dispatch(Intent.JSON, '{"source": "{\\"a\\": 1}", "query": "a"}'))
    assert result is not None
    assert result.content == "1"
    assert result.source == "json"
