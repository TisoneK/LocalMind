"""
B-2026-08-02-11 (C2) — best-of-N editor pattern.

Covers tools/best_of_n_edit.py:
- pure parser helpers (_extract_json_objects / _extract_proposal /
  _extract_choice) incl. braces-inside-strings tolerance,
- the full tool flow with mocked sub-agents (N=2 happy path, selector
  fallbacks, no-candidates, restage failure, recursion/adapter guards),
- the wiring (Intent in CODING_TOOLS, tool registered, editor_selector
  agent registered).

The sub-agent spawns (_run_child) and the propose/apply tools are mocked —
no real agents or disk writes. The default-path isolation contract
(no adapter set → adapter_unavailable) is also exercised.
"""

import json

import pytest
from core.agent.delegation import DelegationResult
from core.models import Intent, RiskLevel, ToolResult
from tools.best_of_n_edit import (
    _build_editor_task,
    _build_selector_task,
    _extract_choice,
    _extract_json_objects,
    _extract_proposal,
    _truncate,
    best_of_n_edit,
)

# ── Parser helpers ───────────────────────────────────────────────────────────


def test_extract_json_objects_handles_braces_in_strings():
    """Code containing {} inside search/replace must not confuse the parser
    (the model emits valid JSON — braces in strings are escaped-free but
    nested braces must still parse)."""
    text = (
        'prose {"path": "a.py", "search": "def f() {\\n  return 1\\n}", '
        '"replace": "def f() {\\n  return 2\\n}"} tail'
    )
    objs = _extract_json_objects(text)
    assert len(objs) == 1
    assert objs[0]["path"] == "a.py"
    assert "return 1" in objs[0]["search"]


def test_extract_proposal_fenced_and_embedded():
    fenced = 'Here you go:\n```json\n{"path": "/abs/x.py", "action": "replace", "search": "old", "replace": "new", "rationale": "r"}\n```'
    prop = _extract_proposal(fenced)
    assert prop is not None
    assert prop["path"] == "/abs/x.py"
    assert prop["replace"] == "new"

    embedded = "I staged the edit. {" '"path": "y.py", "action": "replace", "search": "a", "replace": "b"' "} Regards."
    prop2 = _extract_proposal(embedded)
    assert prop2 is not None
    assert prop2["path"] == "y.py"


def test_extract_proposal_missing_fields_is_none():
    assert _extract_proposal("no json here") is None
    assert _extract_proposal('{"path": "x.py", "rationale": "only path"}') is None
    assert _extract_proposal("") is None


def test_extract_choice():
    assert _extract_choice('{"choice": 1, "reason": "r"}') == 1
    assert _extract_choice('prose {"choice": "2"} prose') == 2
    assert _extract_choice("no choice") is None


def test_build_editor_task_mentions_strategy_and_contract():
    task = _build_editor_task("/abs/f.py", "make it strict", "refactor", 2, 3)
    assert "STRATEGY: refactor" in task
    assert "make it strict" in task
    assert "propose_str_replace" in task
    assert "TARGET FILE: /abs/f.py" in task


def test_build_selector_task_includes_candidates():
    task = _build_selector_task("/abs/f.py", "fix bug", [{"strategy": "conservative", "rationale": "r", "search": "a" * 2000, "replace": "b"}])
    assert "fix bug" in task
    assert "conservative" in task
    # The 2000-char search is truncated in the selector's context view.
    assert "…[truncated]" in task
    assert _truncate("x" * 2000, 600).endswith("…[truncated]")


# ── Full tool flow (mocked sub-agents) ───────────────────────────────────────


def _completed(output: str) -> DelegationResult:
    return DelegationResult(status="completed", run_id="r", agent_name="coding", output=output)


def _failed(error_type: str) -> DelegationResult:
    return DelegationResult(status="failed", run_id="r", agent_name="coding", error_type=error_type)


def _proposal_payload(path: str, search: str, replace: str, rationale: str = "r") -> str:
    return json.dumps({"path": path, "action": "replace", "search": search, "replace": replace, "rationale": rationale})


def _set_adapter(adapter=None):
    from tools.delegate import set_current_adapter

    if adapter is None:
        adapter = object()
    set_current_adapter(adapter)
    return adapter


@pytest.fixture(autouse=True)
def _fresh_depth():
    from tools.delegate import _current_depth

    _current_depth.set(0)
    yield
    _current_depth.set(0)


def _stub_ok_tool(path: str, content: str = "staged"):
    """A successful propose/apply stub — records the call and returns success."""

    async def _fn(message: str):
        _fn.calls.append(json.loads(message))
        from core.models import ToolResult

        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="stub",
            success=True,
            metadata={"path": path},
        )

    _fn.calls = []
    return _fn


def _stub_fail_tool():
    async def _fn(message: str):
        return ToolResult(
            content="stub failure",
            risk=RiskLevel.MEDIUM,
            source="stub",
            success=False,
            error_type="restage_stub_failure",
        )

    return _fn


@pytest.mark.asyncio
async def test_validation_missing_fields():
    result = await best_of_n_edit(json.dumps({"file_path": ""}))
    assert not result.success
    assert result.error_type == "validation_error"

    result2 = await best_of_n_edit(json.dumps({"instruction": "no file"}))
    assert not result2.success
    assert result2.error_type == "validation_error"


@pytest.mark.asyncio
async def test_validation_nonexistent_file(tmp_path):
    _set_adapter()
    result = await best_of_n_edit(
        json.dumps({"file_path": str(tmp_path / "missing.py"), "instruction": "edit it"})
    )
    assert not result.success
    assert result.error_type == "not_found"


@pytest.mark.asyncio
async def test_no_adapter_returns_adapter_unavailable():
    # No _current_adapter set in this task context → framework error.
    result = await best_of_n_edit(
        json.dumps({"file_path": "README.md", "instruction": "edit it"})
    )
    assert not result.success
    assert result.error_type == "adapter_unavailable"


@pytest.mark.asyncio
async def test_depth_limit_returns_recursion_limit(tmp_path):
    from tools.delegate import MAX_DELEGATION_DEPTH, _current_depth

    target = tmp_path / "f.py"
    target.write_text("old\n")

    _current_depth.set(MAX_DELEGATION_DEPTH)  # simulate a deeply-nested run
    _set_adapter()
    result = await best_of_n_edit(
        json.dumps({"file_path": str(target), "instruction": "edit"})
    )
    assert not result.success
    assert result.error_type == "recursion_limit"


@pytest.mark.asyncio
async def test_happy_path_n2_selector_picks_winner(monkeypatch, tmp_path):
    import tools.apply_proposed as apply_mod
    import tools.best_of_n_edit as module
    import tools.propose_edit as propose_mod

    target = tmp_path / "f.py"
    target.write_text("line1\nline2\n")
    _set_adapter()
    monkeypatch.setattr(module, "_path_allowed", lambda p: True)

    restage = _stub_ok_tool(str(target))
    apply_stub = _stub_ok_tool(str(target))

    async def fake_run_child(packet, adapter_, depth):
        if packet.target_agent == "coding":
            strategy = "refactor" if "STRATEGY: refactor" in packet.objective else "conservative"
            search = "line1" if strategy == "conservative" else "line2"
            replace = "line1 v1" if strategy == "conservative" else "line2 v2"
            return _completed(_proposal_payload(str(target), search, replace))
        # editor_selector → picks index 1
        return _completed(json.dumps({"choice": 1, "reason": "refactor is better", "suggested_improvements": "none"}))

    monkeypatch.setattr(module, "_run_child", fake_run_child)
    monkeypatch.setattr(propose_mod, "propose_str_replace", restage)
    monkeypatch.setattr(apply_mod, "apply_proposed_edit", apply_stub)

    result = await best_of_n_edit(
        json.dumps({"file_path": str(target), "instruction": "change both lines", "n": 2})
    )

    assert result.success
    assert result.metadata["winner_index"] == 1
    assert result.metadata["winner_strategy"] == "refactor"
    assert result.metadata["candidate_count"] == 2
    assert result.metadata["selector"]["reason"] == "refactor is better"
    # Re-staged with the WINNER's payload, applied to the winner's path.
    assert restage.calls and restage.calls[0]["search"] == "line2"
    assert restage.calls[0]["replace"] == "line2 v2"
    assert restage.calls[0]["path"] == str(target)
    assert apply_stub.calls and apply_stub.calls[0]["path"] == str(target)


@pytest.mark.asyncio
async def test_selector_invalid_choice_falls_back_to_zero(monkeypatch, tmp_path):
    import tools.apply_proposed as apply_mod
    import tools.best_of_n_edit as module
    import tools.propose_edit as propose_mod

    target = tmp_path / "f.py"
    target.write_text("a\n")
    _set_adapter()
    monkeypatch.setattr(module, "_path_allowed", lambda p: True)

    async def fake_run_child(packet, adapter_, depth):
        if packet.target_agent == "coding":
            return _completed(_proposal_payload(str(target), "a", "b"))
        return _completed(json.dumps({"choice": 99, "reason": "out of range"}))

    monkeypatch.setattr(module, "_run_child", fake_run_child)
    monkeypatch.setattr(propose_mod, "propose_str_replace", _stub_ok_tool(str(target)))
    monkeypatch.setattr(apply_mod, "apply_proposed_edit", _stub_ok_tool(str(target)))

    result = await best_of_n_edit(json.dumps({"file_path": str(target), "instruction": "edit", "n": 2}))
    assert result.success
    assert result.metadata["winner_index"] == 0
    assert "defaulted to candidate 0" in result.metadata["selector"]["reason"]


@pytest.mark.asyncio
async def test_selector_failure_falls_back_to_zero(monkeypatch, tmp_path):
    import tools.apply_proposed as apply_mod
    import tools.best_of_n_edit as module
    import tools.propose_edit as propose_mod

    target = tmp_path / "f.py"
    target.write_text("a\n")
    _set_adapter()
    monkeypatch.setattr(module, "_path_allowed", lambda p: True)

    async def fake_run_child(packet, adapter_, depth):
        if packet.target_agent == "coding":
            return _completed(_proposal_payload(str(target), "a", "b"))
        return _failed("child_exception")

    monkeypatch.setattr(module, "_run_child", fake_run_child)
    monkeypatch.setattr(propose_mod, "propose_str_replace", _stub_ok_tool(str(target)))
    monkeypatch.setattr(apply_mod, "apply_proposed_edit", _stub_ok_tool(str(target)))

    result = await best_of_n_edit(json.dumps({"file_path": str(target), "instruction": "edit", "n": 2}))
    assert result.success
    assert result.metadata["winner_index"] == 0


@pytest.mark.asyncio
async def test_no_candidates_returns_no_candidates(monkeypatch, tmp_path):
    import tools.best_of_n_edit as module

    target = tmp_path / "f.py"
    target.write_text("a\n")
    _set_adapter()
    monkeypatch.setattr(module, "_path_allowed", lambda p: True)

    async def fake_run_child(packet, adapter_, depth):
        if packet.target_agent == "coding":
            return _failed("empty_response")
        return _completed(json.dumps({"choice": 0}))

    monkeypatch.setattr(module, "_run_child", fake_run_child)

    result = await best_of_n_edit(json.dumps({"file_path": str(target), "instruction": "edit", "n": 2}))
    assert not result.success
    assert result.error_type == "no_candidates"


@pytest.mark.asyncio
async def test_restage_failure_returns_restage_failed(monkeypatch, tmp_path):
    import tools.apply_proposed as apply_mod
    import tools.best_of_n_edit as module
    import tools.propose_edit as propose_mod

    target = tmp_path / "f.py"
    target.write_text("a\n")
    _set_adapter()
    monkeypatch.setattr(module, "_path_allowed", lambda p: True)

    async def fake_run_child(packet, adapter_, depth):
        if packet.target_agent == "coding":
            return _completed(_proposal_payload(str(target), "does-not-exist", "b"))
        return _completed(json.dumps({"choice": 0, "reason": "r"}))

    monkeypatch.setattr(module, "_run_child", fake_run_child)
    monkeypatch.setattr(propose_mod, "propose_str_replace", _stub_fail_tool())
    monkeypatch.setattr(apply_mod, "apply_proposed_edit", _stub_ok_tool(str(target)))

    result = await best_of_n_edit(json.dumps({"file_path": str(target), "instruction": "edit", "n": 2}))
    assert not result.success
    assert result.error_type == "restage_failed"


# ── Wiring ───────────────────────────────────────────────────────────────────


def test_intent_wired_into_coding_tools():
    from agents.coding.tools import CODING_TOOLS
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    assert "best_of_n_edit" in AGENT_ALLOWED_TOOLS
    assert "best_of_n_edit" in CODING_TOOLS
    assert Intent.BEST_OF_N_EDIT.value == "best_of_n_edit"


def test_tool_registered():
    import tools

    meta = {t["intent"]: t for t in tools.available_tools()}
    assert "best_of_n_edit" in meta
    assert meta["best_of_n_edit"]["parallelizable"] is False


def test_editor_selector_agent_registered():
    from agents.registry import get_agent

    cls = get_agent("editor_selector")
    assert cls is not None
    cfg = cls(adapter=None).config()
    assert cfg.name == "editor_selector"
    assert cfg.tools_enabled is False
    assert cfg.allowed_tools == frozenset()
