"""
Tests for the ReviewerAgent — the code review specialist agent.

Verifies:
  - AgentConfig structure (name, max_iterations, max_wall_clock_secs, tools)
  - Description concreteness (ADR-6 point 6)
  - Context builder (workflow injection, memory facts, orchestrator context)
  - is_done() Phase 1 contract
  - Scoped toolset (REVIEWER_TOOLS)
  - Registry integration
  - Selection mapping (Intent.REVIEW → reviewer)
  - Reviewer vs other agent toolset comparison
"""

from __future__ import annotations

import pytest
from agents import ReviewerAgent, get_agent, list_agents, select_agent
from agents.reviewer.context_builder import build_reviewer_context
from agents.reviewer.is_done import is_reviewer_done
from agents.reviewer.tools import REVIEWER_TOOLS
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent

# ── AgentConfig tests ─────────────────────────────────────────────────


def test_reviewer_config_name():
    agent = ReviewerAgent(adapter=None)
    assert agent.config().name == "reviewer"


def test_reviewer_config_max_iterations():
    agent = ReviewerAgent(adapter=None)
    assert agent.config().max_iterations == 10


def test_reviewer_config_max_wall_clock():
    agent = ReviewerAgent(adapter=None)
    assert agent.config().max_wall_clock_secs == 300


def test_reviewer_config_tools_enabled():
    agent = ReviewerAgent(adapter=None)
    assert agent.config().tools_enabled is True


# ── Description tests (ADR-6 point 6) ─────────────────────────────────


def test_reviewer_description_is_concrete():
    agent = ReviewerAgent(adapter=None)
    desc = agent.description()
    assert "Reviewer Agent" in desc
    assert "review" in desc.lower()
    assert "assess" in desc.lower() or "quality" in desc.lower()
    assert "spec" in desc.lower() or "requirement" in desc.lower()
    # Should mention its scoped tools
    assert "file" in desc.lower()
    assert "git" in desc.lower()
    # Should NOT mention building/creating/testing
    assert "cannot" in desc.lower() or "scoped" in desc.lower()


def test_reviewer_description_distinct_from_verifier():
    from agents import VerifierAgent
    r_desc = ReviewerAgent(adapter=None).description()
    v_desc = VerifierAgent(adapter=None).description()
    assert r_desc != v_desc


# ── Context builder tests ─────────────────────────────────────────────


def test_build_reviewer_context_returns_string():
    ctx = build_reviewer_context(messages=[], intent=Intent.REVIEW)
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_build_reviewer_context_includes_workflow():
    ctx = build_reviewer_context(messages=[], intent=Intent.REVIEW)
    assert "reviewer" in ctx.lower() or "Reviewer" in ctx


def test_build_reviewer_context_includes_memory_facts():
    ctx = build_reviewer_context(
        messages=[], intent=Intent.REVIEW,
        memory_facts=["Convention: snake_case"],
    )
    assert "Convention: snake_case" in ctx
    assert "Relevant Memory" in ctx


def test_build_reviewer_context_caps_memory_facts():
    facts = [f"Fact {i}" for i in range(15)]
    ctx = build_reviewer_context(messages=[], intent=Intent.REVIEW, memory_facts=facts)
    assert "Fact 0" in ctx
    assert "Fact 9" in ctx
    assert "Fact 10" not in ctx


def test_build_reviewer_context_includes_orchestrator_plan():
    ctx = build_reviewer_context(
        messages=[], intent=Intent.REVIEW,
        orchestrator_context="Step 1: Read diff. Step 2: Check style.",
    )
    assert "Orchestrator Plan" in ctx
    assert "Read diff" in ctx


def test_build_reviewer_context_mentions_workspace_state():
    ctx = build_reviewer_context(messages=[], intent=Intent.REVIEW)
    assert "workspace state" in ctx.lower() or "git" in ctx.lower()


# ── is_done() tests ───────────────────────────────────────────────────


def test_is_reviewer_done_phase1_always_false():
    done, reason = is_reviewer_done(1, 5.0, None, None)
    assert done is False
    assert reason == ""


# ── Scoped toolset tests ──────────────────────────────────────────────


def test_reviewer_tools_is_frozenset():
    assert isinstance(REVIEWER_TOOLS, frozenset)


def test_reviewer_tools_are_subset_of_allowed():
    assert REVIEWER_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_reviewer_tools_include_file_task():
    assert "file_task" in REVIEWER_TOOLS


def test_reviewer_tools_include_git():
    assert "git" in REVIEWER_TOOLS


def test_reviewer_tools_include_shell():
    assert "shell" in REVIEWER_TOOLS


def test_reviewer_tools_include_delegate():
    assert "delegate" in REVIEWER_TOOLS


def test_reviewer_tools_exclude_code_exec():
    assert "code_exec" not in REVIEWER_TOOLS


def test_reviewer_tools_exclude_file_write():
    assert "file_write" not in REVIEWER_TOOLS


def test_reviewer_tools_exclude_edit_file():
    assert "edit_file" not in REVIEWER_TOOLS


def test_reviewer_tools_exclude_process():
    assert "process" not in REVIEWER_TOOLS


def test_reviewer_tools_has_exactly_5():
    # 4 + skill (B-2026-08-02-12, universal)
    assert len(REVIEWER_TOOLS) == 5


# ── Registry integration tests ───────────────────────────────────────


def test_reviewer_is_in_registry():
    agent_cls = get_agent("reviewer")
    assert agent_cls is not None
    assert agent_cls is ReviewerAgent


def test_reviewer_appears_in_list_agents():
    agents = {name: cls for name, cls in list_agents()}
    assert "reviewer" in agents
    assert agents["reviewer"] is ReviewerAgent


def test_reviewer_agent_instantiable():
    agent = ReviewerAgent(adapter=None)
    assert agent.config().name == "reviewer"


# ── Selection mapping tests ──────────────────────────────────────────


def test_intent_review_maps_to_reviewer():
    from agents.selection import intent_to_agent_name
    assert intent_to_agent_name(Intent.REVIEW) == "reviewer"


def test_select_agent_with_review_intent():
    agent_cls = select_agent(Intent.REVIEW)
    assert agent_cls is ReviewerAgent


# ── Reviewer vs other agents comparison ───────────────────────────────


def test_reviewer_has_minimal_toolset():
    from agents.coding.tools import CODING_TOOLS
    from agents.verifier.tools import VERIFIER_TOOLS
    assert len(REVIEWER_TOOLS) < len(CODING_TOOLS)
    assert len(REVIEWER_TOOLS) < len(VERIFIER_TOOLS)


def test_reviewer_does_not_have_edit_file():
    from agents.verifier.tools import VERIFIER_TOOLS
    assert "edit_file" in VERIFIER_TOOLS  # Verifier can fix bugs
    assert "edit_file" not in REVIEWER_TOOLS  # Reviewer just reports


def test_reviewer_tools_are_in_coding():
    from agents.coding.tools import CODING_TOOLS
    assert REVIEWER_TOOLS.issubset(CODING_TOOLS)


# ── DOMAIN_TO_AGENT mapping ───────────────────────────────────────────


def test_domain_review_maps_to_reviewer():
    from agents.selection import primary_domain_to_agent_name
    assert primary_domain_to_agent_name("review") == "reviewer"


def test_select_by_task_profile_review():
    from agents.selection import select_agent_by_task_profile
    agent_cls = select_agent_by_task_profile("review", Intent.CHAT)
    assert agent_cls is ReviewerAgent


# ── B-2026-08-09-15 / ADR-15 §1: fixed output schema ───────────────────────


def test_reviewer_config_has_fixed_output_schema():
    """The reviewer is a SPECIFIC sub-agent: its config declares a FIXED
    output schema (issues + verdict) so the parent can parse the result."""
    schema = ReviewerAgent(adapter=None).config().output_schema
    assert schema is not None
    assert "issues" in schema
    issue = schema["issues"][0]
    for key in ("severity", "file", "line", "description"):
        assert key in issue, f"issues[0] must have {key!r}"
    assert "verdict" in schema
    assert "summary" in schema


def test_render_output_contract_renders_schema_as_json():
    """The contract must be literal JSON the model can mirror exactly."""
    from agents.base_agent import render_output_contract

    schema = ReviewerAgent(adapter=None).config().output_schema
    rendered = render_output_contract(schema)
    assert "OUTPUT CONTRACT" in rendered
    assert '"issues"' in rendered
    assert '"severity"' in rendered
    assert '"verdict"' in rendered
    # The embedded shape parses as valid JSON (mirror-able, not prose).
    import json as _json

    _json.loads(_json.dumps(schema))
    assert rendered.count("{") >= 2


def test_render_output_contract_empty_for_general_agents():
    """General agents (no schema) get no contract section."""
    from agents.base_agent import render_output_contract

    assert render_output_contract(None) == ""
    assert render_output_contract({}) == ""


def test_reviewer_context_contains_output_contract():
    """BaseAgent.run() appends the contract to the agent context so it
    reaches the model's system prompt (ADR-8 Phase 2 wiring)."""
    from agents import ReviewerAgent
    from agents.base_agent import render_output_contract

    agent = ReviewerAgent(adapter=None)
    ctx = agent.build_context(messages=[], intent=Intent.CHAT)
    ctx += render_output_contract(agent.config().output_schema)
    assert "OUTPUT CONTRACT" in ctx
    assert '"verdict"' in ctx


@pytest.mark.asyncio
async def test_output_contract_reaches_loop_only_for_delegated_run(monkeypatch):
    """The schema must reach the model ONLY on delegated child runs (where
    the parent needs to parse the result) — a top-level user query routed
    to the reviewer must keep a readable prose answer, not a JSON blob."""
    from agents import ReviewerAgent
    from core.agent.delegation import (
        reset_current_run_id,
        set_current_run_id,
    )

    captured = {}

    class _FakeLoop:
        def __init__(self, adapter=None):
            pass

        async def run(self, **kwargs):
            captured["agent_context"] = kwargs.get("agent_context", "")
            if False:
                yield None

    monkeypatch.setattr("core.agent.loop.AgentLoop", _FakeLoop)
    agent = ReviewerAgent(adapter=None)

    # 1) Top-level run (no current run id) → NO output contract.
    captured.clear()
    async for _ in agent.run(
        messages=[],
        intent=Intent.CHAT,
        initial_tool_result=None,
        available_tools=[],
    ):
        pass
    assert "OUTPUT CONTRACT" not in captured.get("agent_context", "")

    # 2) Delegated child run (current run id set by the delegate tools) →
    #    the contract IS appended.
    token = set_current_run_id("run_test_child")
    try:
        captured.clear()
        async for _ in agent.run(
            messages=[],
            intent=Intent.CHAT,
            initial_tool_result=None,
            available_tools=[],
        ):
            pass
    finally:
        reset_current_run_id(token)
    assert "OUTPUT CONTRACT" in captured.get("agent_context", "")
    assert '"verdict"' in captured.get("agent_context", "")
