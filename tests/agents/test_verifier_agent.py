"""
Tests for the VerifierAgent — the verification specialist agent.

Verifies:
  - AgentConfig structure (name, max_iterations, max_wall_clock_secs, tools)
  - Description concreteness (ADR-6 point 6)
  - Context builder (workflow injection, memory facts, orchestrator context)
  - is_done() Phase 1 contract
  - Scoped toolset (VERIFIER_TOOLS)
  - Registry integration
  - Selection mapping (Intent.VERIFY → verifier)
  - Verifier vs Coding agent toolset comparison
"""

from __future__ import annotations

import pytest

from agents import VerifierAgent, get_agent, list_agents, select_agent
from agents.verifier.context_builder import build_verifier_context
from agents.verifier.is_done import is_verifier_done
from agents.verifier.tools import VERIFIER_TOOLS
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent


# ── AgentConfig tests ─────────────────────────────────────────────────


def test_verifier_config_name():
    agent = VerifierAgent(adapter=None)
    assert agent.config().name == "verifier"


def test_verifier_config_max_iterations():
    agent = VerifierAgent(adapter=None)
    assert agent.config().max_iterations == 15


def test_verifier_config_max_wall_clock():
    agent = VerifierAgent(adapter=None)
    assert agent.config().max_wall_clock_secs == 480


def test_verifier_config_tools_enabled():
    agent = VerifierAgent(adapter=None)
    assert agent.config().tools_enabled is True


# ── Description tests (ADR-6 point 6) ─────────────────────────────────


def test_verifier_description_is_concrete():
    agent = VerifierAgent(adapter=None)
    desc = agent.description()
    assert "Verifier Agent" in desc
    assert "run" in desc.lower()
    assert "test" in desc.lower()
    assert "bug" in desc.lower()
    assert "verif" in desc.lower()
    # Should mention its scoped tools
    assert "shell" in desc.lower() or "command" in desc.lower()
    assert "git" in desc.lower()
    # Should NOT mention building/creating (that's the coding agent)
    assert "write new code" in desc.lower() or "cannot write" in desc.lower()


def test_verifier_description_distinct_from_coding():
    from agents import CodingAgent
    v_desc = VerifierAgent(adapter=None).description()
    c_desc = CodingAgent(adapter=None).description()
    # The verifier description should be different from the coding description
    assert v_desc != c_desc
    # Verifier should emphasize testing, not building
    assert "build" not in v_desc.lower() or "verify" in v_desc.lower()


# ── Context builder tests ─────────────────────────────────────────────


def test_build_verifier_context_returns_string():
    ctx = build_verifier_context(messages=[], intent=Intent.VERIFY)
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_build_verifier_context_includes_workflow():
    ctx = build_verifier_context(messages=[], intent=Intent.VERIFY)
    # Should include the verifier workflow (or fallback header)
    assert "verifier" in ctx.lower() or "Verifier" in ctx
    assert "test" in ctx.lower() or "verify" in ctx.lower()


def test_build_verifier_context_includes_memory_facts():
    ctx = build_verifier_context(
        messages=[],
        intent=Intent.VERIFY,
        memory_facts=["Fact 1", "Fact 2"],
    )
    assert "Fact 1" in ctx
    assert "Fact 2" in ctx
    assert "Relevant Memory" in ctx


def test_build_verifier_context_caps_memory_facts():
    facts = [f"Fact {i}" for i in range(15)]
    ctx = build_verifier_context(
        messages=[],
        intent=Intent.VERIFY,
        memory_facts=facts,
    )
    # Only first 10 should appear
    assert "Fact 0" in ctx
    assert "Fact 9" in ctx
    assert "Fact 10" not in ctx


def test_build_verifier_context_includes_orchestrator_plan():
    ctx = build_verifier_context(
        messages=[],
        intent=Intent.VERIFY,
        orchestrator_context="Step 1: Run tests. Step 2: Check output.",
    )
    assert "Orchestrator Plan" in ctx
    assert "Run tests" in ctx


def test_build_verifier_context_mentions_workspace_state():
    ctx = build_verifier_context(messages=[], intent=Intent.VERIFY)
    assert "workspace state" in ctx.lower()


# ── is_done() tests ───────────────────────────────────────────────────


def test_is_verifier_done_phase1_always_false():
    done, reason = is_verifier_done(iterations=1, wall_clock_secs=5.0, last_tool_result=None, trace=None)
    assert done is False
    assert reason == ""


def test_is_verifier_done_phase1_after_many_iterations():
    # Even after many iterations, Phase 1 returns False — the AgentLoop handles limits
    done, reason = is_verifier_done(iterations=50, wall_clock_secs=500.0, last_tool_result=None, trace=None)
    assert done is False


# ── Scoped toolset tests ──────────────────────────────────────────────


def test_verifier_tools_is_frozenset():
    assert isinstance(VERIFIER_TOOLS, frozenset)


def test_verifier_tools_are_subset_of_allowed():
    assert VERIFIER_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_verifier_tools_include_shell():
    assert "shell" in VERIFIER_TOOLS


def test_verifier_tools_include_process():
    assert "process" in VERIFIER_TOOLS


def test_verifier_tools_include_git():
    assert "git" in VERIFIER_TOOLS


def test_verifier_tools_include_file_task():
    assert "file_task" in VERIFIER_TOOLS


def test_verifier_tools_include_edit_file():
    assert "edit_file" in VERIFIER_TOOLS


def test_verifier_tools_include_delegate():
    assert "delegate" in VERIFIER_TOOLS


def test_verifier_tools_exclude_file_write():
    # Verifier uses edit_file for targeted fixes, not file_write for creating
    assert "file_write" not in VERIFIER_TOOLS


def test_verifier_tools_exclude_code_exec():
    assert "code_exec" not in VERIFIER_TOOLS


def test_verifier_tools_exclude_web_search():
    assert "web_search" not in VERIFIER_TOOLS


def test_verifier_tools_exclude_web_fetch():
    assert "web_fetch" not in VERIFIER_TOOLS


def test_verifier_tools_exclude_browse():
    assert "browse" not in VERIFIER_TOOLS


def test_verifier_tools_exclude_memory_op():
    assert "memory_op" not in VERIFIER_TOOLS


def test_verifier_tools_exclude_sysinfo():
    assert "sysinfo" not in VERIFIER_TOOLS


def test_verifier_tools_has_exactly_6():
    assert len(VERIFIER_TOOLS) == 6


# ── Registry integration tests ───────────────────────────────────────


def test_verifier_is_in_registry():
    agent_cls = get_agent("verifier")
    assert agent_cls is not None
    assert agent_cls is VerifierAgent


def test_verifier_appears_in_list_agents():
    agents = {name: cls for name, cls in list_agents()}
    assert "verifier" in agents
    assert agents["verifier"] is VerifierAgent


def test_verifier_agent_instantiable():
    agent = VerifierAgent(adapter=None)
    assert agent.config().name == "verifier"


# ── Selection mapping tests ──────────────────────────────────────────


def test_intent_verify_maps_to_verifier():
    from agents.selection import intent_to_agent_name
    assert intent_to_agent_name(Intent.VERIFY) == "verifier"


def test_select_agent_with_verify_intent():
    agent_cls = select_agent(Intent.VERIFY)
    assert agent_cls is VerifierAgent


# ── Verifier vs Coding agent comparison ───────────────────────────────


def test_verifier_and_coding_have_overlapping_toolsets():
    from agents.coding.tools import CODING_TOOLS
    shared = VERIFIER_TOOLS & CODING_TOOLS
    # They share shell, process, git, file_task, edit_file, delegate
    assert "shell" in shared
    assert "git" in shared
    assert "file_task" in shared
    assert "edit_file" in shared


def test_verifier_has_process_coding_also_has():
    from agents.coding.tools import CODING_TOOLS
    assert "process" in CODING_TOOLS
    assert "process" in VERIFIER_TOOLS


def test_coding_has_code_exec_verifier_does_not():
    from agents.coding.tools import CODING_TOOLS
    assert "code_exec" in CODING_TOOLS
    assert "code_exec" not in VERIFIER_TOOLS


def test_coding_has_file_write_verifier_does_not():
    from agents.coding.tools import CODING_TOOLS
    assert "file_write" in CODING_TOOLS
    assert "file_write" not in VERIFIER_TOOLS


def test_verifier_has_fewer_tools_than_coding():
    from agents.coding.tools import CODING_TOOLS
    assert len(VERIFIER_TOOLS) < len(CODING_TOOLS)


def test_verifier_more_iterations_than_research():
    from agents.research.tools import RESEARCH_TOOLS
    from agents.research.agent import ResearchAgent
    v_agent = VerifierAgent(adapter=None)
    r_agent = ResearchAgent(adapter=None)
    # Verifier may need more iterations than research (bug reproduction takes steps)
    # but they're similar
    assert v_agent.config().max_iterations >= r_agent.config().max_iterations


# ── DOMAIN_TO_AGENT mapping ───────────────────────────────────────────


def test_domain_verify_maps_to_verifier():
    from agents.selection import primary_domain_to_agent_name
    assert primary_domain_to_agent_name("verify") == "verifier"


def test_select_by_task_profile_verify():
    from agents.selection import select_agent_by_task_profile
    agent_cls = select_agent_by_task_profile("verify", Intent.CHAT)
    assert agent_cls is VerifierAgent
