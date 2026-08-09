"""
Session 82: B-2026-08-02-7 (B2) — propose-stage tools tests.

propose_str_replace / propose_write_file stage edits WITHOUT touching
disk; apply_proposed_edit writes the staged winner. The per-run proposal
registry (contextvars) must isolate runs: a run that ends without
applying discards its staged edits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.config import settings
from core.models import Intent
from tools.proposals import get_proposal, get_proposals, reset_proposals

# ── Registration / wiring ───────────────────────────────────────────────


def test_propose_intents_exist():
    assert Intent.PROPOSE_EDIT.value == "propose_str_replace"
    assert Intent.PROPOSE_WRITE.value == "propose_write_file"
    assert Intent.APPLY_PROPOSED.value == "apply_proposed_edit"


def test_propose_tools_are_registered():
    """All three registered in the tool registry."""
    from tools import _REGISTRY

    for intent, name, parallelizable in [
        (Intent.PROPOSE_EDIT, "propose_str_replace", True),
        (Intent.PROPOSE_WRITE, "propose_write_file", True),
        (Intent.APPLY_PROPOSED, "apply_proposed_edit", False),
    ]:
        assert intent in _REGISTRY, f"{name} not registered — must be imported in tools/__init__.py"
        entry = _REGISTRY[intent]
        assert entry["description"], f"{name} has no description"
        assert entry["cost"] > 0
        assert entry["parallelizable"] is parallelizable, (
            f"{name} parallelizable flag wrong: propose tools are pure registry "
            f"writes (True); apply touches disk (False)"
        )


def test_propose_tools_in_agent_allowed_and_coding_tools():
    from agents.coding.tools import CODING_TOOLS
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    for tool in ("propose_str_replace", "propose_write_file", "apply_proposed_edit"):
        assert tool in AGENT_ALLOWED_TOOLS
        assert tool in CODING_TOOLS


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def allowed_fs(monkeypatch, tmp_path):
    """Make tmp_path an allowed folder (tmp is normally outside ~)."""
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path), str(Path.home())],
    )
    reset_proposals()
    return tmp_path


def _propose_edit_payload(path: Path, search: str, replace: str) -> str:
    return json.dumps(
        {"path": str(path), "action": "replace", "search": search, "replace": replace}
    )


# ── propose_str_replace ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_str_replace_stages_without_writing(allowed_fs):
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("def old():\n    return 1\n", encoding="utf-8")

    result = await propose_str_replace(_propose_edit_payload(target, "old", "new"))

    assert result.success
    assert result.metadata["staged"] is True
    assert result.metadata["applied"] is False
    assert result.metadata["path"] == str(target.resolve())
    # No disk write — the file on disk is untouched
    assert target.read_text(encoding="utf-8") == "def old():\n    return 1\n"
    # But the staged content reflects the edit
    assert get_proposal(str(target.resolve())) == "def new():\n    return 1\n"
    # Diff preview metadata present (frontend DiffBlock)
    assert result.metadata["diff_hunks"]
    assert result.metadata["diff_language"] == "python"


@pytest.mark.asyncio
async def test_propose_str_replace_requires_path_and_action(allowed_fs):
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("hello", encoding="utf-8")

    result = await propose_str_replace(json.dumps({"action": "replace", "search": "x", "replace": "y"}))
    assert not result.success
    assert result.error_type == "validation_error"

    result = await propose_str_replace(_propose_edit_payload(target, "", "y"))
    assert not result.success
    assert result.error_type == "edit_error"  # empty search → apply fails


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_propose_str_replace_defaults_action_to_replace(allowed_fs):
    """The TOOL_DEFINITION documents action as optional (default: replace)."""
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("def old():", encoding="utf-8")

    # No "action" key — must default to replace, not validation_error
    payload = json.dumps({"path": str(target), "search": "old", "replace": "new"})
    result = await propose_str_replace(payload)

    assert result.success
    assert get_proposal(str(target.resolve())) == "def new():"


@pytest.mark.asyncio
async def test_propose_str_replace_invalid_payload_is_parse_error():
    from tools.propose_edit import propose_str_replace

    result = await propose_str_replace("not json at all")
    assert not result.success
    assert result.error_type == "parse_error"


@pytest.mark.asyncio
async def test_propose_str_replace_permission_gate(tmp_path):
    """A path outside the allowed folders is refused at propose time."""
    from tools.propose_edit import propose_str_replace

    # tmp_path is NOT in the allowed set here (no allowed_fs fixture)
    outside = tmp_path / "secret.py"
    outside.write_text("x = 1", encoding="utf-8")

    result = await propose_str_replace(_propose_edit_payload(outside, "x", "y"))
    assert not result.success
    assert result.error_type == "permission_denied"
    assert get_proposal(str(outside.resolve())) is None


# ── propose_write_file ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_write_file_stages_without_writing(allowed_fs):
    from tools.propose_write import propose_write_file

    target = allowed_fs / "new_app.py"
    message = f"{target}:\n\nprint('hi')\n"

    result = await propose_write_file(message)

    assert result.success
    assert result.metadata["staged"] is True
    assert result.metadata["path"] == str(target.resolve())
    assert not target.exists(), "propose_write_file must not touch disk"
    assert get_proposal(str(target.resolve())) == "print('hi')\n"


@pytest.mark.asyncio
async def test_propose_write_file_json_payload(allowed_fs):
    from tools.propose_write import propose_write_file

    target = allowed_fs / "data.json"
    payload = json.dumps({"path": str(target), "content": '{"a": 1}'})

    result = await propose_write_file(payload)

    assert result.success
    assert get_proposal(str(target.resolve())) == '{"a": 1}'
    assert not target.exists()


@pytest.mark.asyncio
async def test_propose_write_file_requires_path():
    from tools.propose_write import propose_write_file

    result = await propose_write_file(":\n\ncontent")
    assert not result.success
    assert result.error_type in ("parse_error", "validation_error")


# ── apply_proposed_edit ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_writes_staged_edit_and_discards(allowed_fs):
    from tools.apply_proposed import apply_proposed_edit
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("def old():\n    return 1\n", encoding="utf-8")

    staged = await propose_str_replace(_propose_edit_payload(target, "old", "new"))
    assert staged.success

    result = await apply_proposed_edit(str(target))

    assert result.success
    assert result.metadata["applied"] is True
    assert target.read_text(encoding="utf-8") == "def new():\n    return 1\n"
    # Applied proposals are removed from the registry
    assert get_proposal(str(target.resolve())) is None


@pytest.mark.asyncio
async def test_apply_writes_staged_full_file(allowed_fs):
    from tools.apply_proposed import apply_proposed_edit
    from tools.propose_write import propose_write_file

    target = allowed_fs / "fresh.py"
    await propose_write_file(f"{target}:\n\nprint('fresh')\n")

    result = await apply_proposed_edit(json.dumps({"path": str(target)}))

    assert result.success
    assert target.read_text(encoding="utf-8") == "print('fresh')\n"
    assert get_proposal(str(target.resolve())) is None


@pytest.mark.asyncio
async def test_apply_without_proposal_errors(allowed_fs):
    from tools.apply_proposed import apply_proposed_edit

    result = await apply_proposed_edit(str(allowed_fs / "nope.py"))

    assert not result.success
    assert result.error_type == "no_proposal"


@pytest.mark.asyncio
async def test_apply_requires_confirmation_when_gate_on(allowed_fs, monkeypatch):
    from tools.apply_proposed import apply_proposed_edit
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("def old():\n    return 1\n", encoding="utf-8")
    await propose_str_replace(_propose_edit_payload(target, "old", "new"))

    monkeypatch.setattr(settings, "localmind_require_write_permission", True)
    result = await apply_proposed_edit(str(target))

    assert result.requires_confirmation is True
    assert result.metadata["requires_permission"] is True
    assert result.metadata["pending_content"] == "def new():\n    return 1\n"
    assert target.read_text(encoding="utf-8") == "def old():\n    return 1\n", (
        "gate on → must not write without confirmation"
    )
    # Proposal stays staged for the confirmed retry
    assert get_proposal(str(target.resolve())) is not None


# ── Best-of-N + per-run isolation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_best_of_n_last_staged_wins(allowed_fs):
    from tools.apply_proposed import apply_proposed_edit
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("def old():\n    return 1\n", encoding="utf-8")

    # Candidate A
    await propose_str_replace(_propose_edit_payload(target, "return 1", "return 1 + 1"))
    # Candidate B (overwrites the staged entry for the same path)
    await propose_str_replace(_propose_edit_payload(target, "return 1", "return 42"))

    assert get_proposal(str(target.resolve())) == "def old():\n    return 42\n"

    result = await apply_proposed_edit(str(target))
    assert result.success
    assert target.read_text(encoding="utf-8") == "def old():\n    return 42\n"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_apply_ambiguous_basename_refuses(allowed_fs):
    """Two staged files sharing a basename must never be guessed between."""
    from tools.apply_proposed import apply_proposed_edit
    from tools.propose_write import propose_write_file

    dir_a = allowed_fs / "a"
    dir_b = allowed_fs / "b"
    await propose_write_file(f"{dir_a / 'app.py'}:\n\ncontent a\n")
    await propose_write_file(f"{dir_b / 'app.py'}:\n\ncontent b\n")

    # Apply with a bare basename — resolves to neither staged key exactly,
    # and both staged keys share the basename → must refuse, not guess.
    result = await apply_proposed_edit("app.py")

    assert not result.success
    assert result.error_type == "ambiguous_proposal"
    assert not (dir_a / "app.py").exists()
    assert not (dir_b / "app.py").exists()


@pytest.mark.asyncio
async def test_staged_edits_do_not_leak_across_runs(allowed_fs):
    """A run that ends without applying discards its staged edits."""
    from tools.apply_proposed import apply_proposed_edit
    from tools.propose_edit import propose_str_replace

    target = allowed_fs / "app.py"
    target.write_text("def old():\n    return 1\n", encoding="utf-8")

    # Run 1: stage a proposal, then the run ends (loop reset) without applying
    await propose_str_replace(_propose_edit_payload(target, "old", "new"))
    assert get_proposals()  # staged during run 1
    reset_proposals()  # AgentLoop.run() does this at the start of the next run

    # Run 2: the stale proposal is gone — apply must refuse
    assert get_proposals() == {}
    result = await apply_proposed_edit(str(target))
    assert not result.success
    assert result.error_type == "no_proposal"
    assert target.read_text(encoding="utf-8") == "def old():\n    return 1\n"
