"""
Session 376: edit_file accepts common free-tier model aliases.

The Session 375 live trace showed deepseek-v4-flash failing edit_file twice:
first with a content-only payload (no action — it meant \"rewrite the whole
file\"), then with Claude-style `old_pattern`/`new_string` instead of the
schema's `pattern`/`replace`. Both bounced validation errors and cost the
turn extra iterations (and the free model gave up before a successful edit).

This normalizes those payloads so the first attempt succeeds:
- content-only (no action) → full-file `rewrite` of `content`
- regex_replace: old_pattern/regex/regex_pattern → pattern; new_string/replacement/new_text → replace
- replace: old_text/search_text/find → search
- insert/append/prepend: text → insert_text
- rewrite/overwrite canonicalized to rewrite

Covers the shared prepare_edit gate AND the typed EditFileContract's own
pre-validation (which ran before prepare_edit and rejected content-only).
"""
from unittest.mock import patch

import pytest

import core.config as config_module
from tools.contracts.schemas import EditFileContract
from tools.edit_file import _edit_from_payload, _normalize_edit_payload


def _allow(tmp_path):
    patcher = patch.object(config_module, "_allowed_user_folders", return_value=[str(tmp_path)])
    patcher.start()
    return patcher


def _write(tmp_path, name, content):
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")
    return target


# ── normalization unit tests ────────────────────────────────────────────────


def test_content_only_becomes_rewrite():
    p = _normalize_edit_payload({"path": "/tmp/a.txt", "content": "hello"})
    assert p["action"] == "rewrite"
    assert p["content"] == "hello"


def test_regex_aliases_map_to_pattern_and_replace():
    p = _normalize_edit_payload({"action": "regex_replace", "old_pattern": "x+", "new_string": "y"})
    assert p["pattern"] == "x+"
    assert p["replace"] == "y"
    p2 = _normalize_edit_payload({"action": "regex_replace", "regex": "x+", "replacement": "y"})
    assert p2["pattern"] == "x+" and p2["replace"] == "y"


def test_claude_old_string_new_string_without_action_defaults_to_replace():
    p = _normalize_edit_payload({"path": "/tmp/a.txt", "old_string": "a", "new_string": "b"})
    assert p["action"] == "replace"
    assert p["search"] == "a" and p["replace"] == "b"


def test_search_without_action_defaults_to_replace():
    p = _normalize_edit_payload({"path": "/tmp/a.txt", "search": "a", "replace": "b"})
    assert p["action"] == "replace"


def test_pattern_without_action_defaults_to_regex_replace():
    p = _normalize_edit_payload({"path": "/tmp/a.txt", "pattern": "x+", "replace": "y"})
    assert p["action"] == "regex_replace"


def test_replace_aliases_map_to_search_and_replace():
    p = _normalize_edit_payload({"action": "replace", "old_text": "a", "new_text": "b"})
    assert p["search"] == "a" and p["replace"] == "b"
    p2 = _normalize_edit_payload({"action": "replace", "find": "a", "replacement": "b"})
    assert p2["search"] == "a" and p2["replace"] == "b"


def test_text_aliases_to_insert_text():
    p = _normalize_edit_payload({"action": "append", "text": "tail"})
    assert p["insert_text"] == "tail"


def test_canonical_field_wins_over_alias():
    p = _normalize_edit_payload({"action": "replace", "search": "keep", "old_text": "drop"})
    assert p["search"] == "keep"


def test_overwrite_canonicalized_to_rewrite():
    p = _normalize_edit_payload({"action": "overwrite", "content": "x"})
    assert p["action"] == "rewrite"


# ── end-to-end edits through the shared gate ─────────────────────────────────


@pytest.mark.asyncio
async def test_content_only_payload_rewrites_file(tmp_path):
    target = _write(tmp_path, "notes.txt", "original content\n")
    patcher = _allow(tmp_path)
    try:
        result = await _edit_from_payload({"path": str(target), "content": "brand new content"})
    finally:
        patcher.stop()
    assert result.success, result.content
    assert target.read_text(encoding="utf-8") == "brand new content"


@pytest.mark.asyncio
async def test_regex_aliases_replace_in_file(tmp_path):
    target = _write(tmp_path, "code.py", "count = 1\n")
    patcher = _allow(tmp_path)
    try:
        result = await _edit_from_payload(
            {"action": "regex_replace", "path": str(target), "old_pattern": r"count = \d+", "new_string": "count = 42"}
        )
    finally:
        patcher.stop()
    assert result.success, result.content
    assert "count = 42" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_replace_aliases_edit_in_file(tmp_path):
    target = _write(tmp_path, "hello.txt", "hello world\n")
    patcher = _allow(tmp_path)
    try:
        result = await _edit_from_payload(
            {"action": "replace", "path": str(target), "old_text": "hello", "new_text": "goodbye", "all": True}
        )
    finally:
        patcher.stop()
    assert result.success, result.content
    assert "goodbye world" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_claude_old_string_new_string_edits_file(tmp_path):
    target = _write(tmp_path, "notes.txt", "original line one\n")
    patcher = _allow(tmp_path)
    try:
        result = await _edit_from_payload(
            {"path": str(target), "old_string": "original line one", "new_string": "edited line one"}
        )
    finally:
        patcher.stop()
    assert result.success, result.content
    assert "edited line one" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_append_text_alias(tmp_path):
    target = _write(tmp_path, "log.txt", "line1\n")
    patcher = _allow(tmp_path)
    try:
        result = await _edit_from_payload({"action": "append", "path": str(target), "text": "line2"})
    finally:
        patcher.stop()
    assert result.success, result.content
    assert target.read_text(encoding="utf-8") == "line1\nline2"


# ── typed contract pre-validation path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_accepts_content_only(tmp_path):
    """The contract's action validation ran BEFORE prepare_edit — content-only
    payloads were rejected there. Now normalized first, they succeed."""
    target = _write(tmp_path, "notes.txt", "old\n")
    patcher = _allow(tmp_path)
    try:
        result = await EditFileContract().execute({"path": str(target), "content": "new"})
    finally:
        patcher.stop()
    assert result.success, result.content
    assert target.read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_unknown_action_still_rejected(tmp_path):
    target = _write(tmp_path, "x.txt", "a\n")
    patcher = _allow(tmp_path)
    try:
        result = await EditFileContract().execute({"action": "nonsense", "path": str(target)})
    finally:
        patcher.stop()
    assert not result.success
    assert "Invalid action" in result.content
