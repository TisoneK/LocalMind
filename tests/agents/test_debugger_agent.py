"""
Tests for the DebuggerAgent — the failure-diagnosis specialist agent.

Verifies:
  - AgentConfig structure (name, max_iterations, max_wall_clock_secs, tools)
  - Description concreteness (ADR-6 point 6)
  - Context builder (workflow injection, memory facts, orchestrator context)
  - is_done() Phase 1 contract
  - Scoped toolset (DEBUGGER_TOOLS)
  - Registry integration
  - Selection mapping (Intent.DEBUG → debugger)
  - Debugger vs other agent toolset comparison
"""

from __future__ import annotations

import pytest

from agents import DebuggerAgent, get_agent, list_agents, select_agent
from agents.debugger.context_builder import build_debugger_context
from agents.debugger.is_done import is_debugger_done
from agents.debugger.tools import DEBUGGER_TOOLS
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent


# ── AgentConfig tests ─────────────────────────────────────────────────


def test_debugger_config_name():
    agent = DebuggerAgent(adapter=None)
    assert agent.config().name == "debugger"


def test_debugger_config_max_iterations():
    agent = DebuggerAgent(adapter=None)
    assert agent.config().max_iterations == 12


def test_debugger_config_max_wall_clock():
    agent = DebuggerAgent(adapter=None)
    assert agent.config().max_wall_clock_secs == 360


def test_debugger_config_tools_enabled():
    agent = DebuggerAgent(adapter=None)
    assert agent.config().tools_enabled is True


# ── Description tests (ADR-6 point 6) ─────────────────────────────────


def test_debugger_description_is_concrete():
    agent = DebuggerAgent(adapter=None)
    desc = agent.description()
    assert "Debugger Agent" in desc
    assert "root cause" in desc.lower()
    assert "bug" in desc.lower()
    assert "isolat" in desc.lower()
    assert "file_task" in desc.lower() or "file" in desc.lower()
    assert "git" in desc.lower()
    assert "process" in desc.lower()


def test_debugger_description_distinct_from_verifier():
    from agents import VerifierAgent
    d_desc = DebuggerAgent(adapter=None).description()
    v_desc = VerifierAgent(adapter=None).description()
    assert d_desc != v_desc


# ── Context builder tests ─────────────────────────────────────────────


def test_build_debugger_context_returns_string():
    ctx = build_debugger_context(messages=[], intent=Intent.DEBUG)
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_build_debugger_context_includes_workflow():
    ctx = build_debugger_context(messages=[], intent=Intent.DEBUG)
    assert "debugger" in ctx.lower() or "Debugger" in ctx


def test_build_debugger_context_includes_memory_facts():
    ctx = build_debugger_context(
        messages=[], intent=Intent.DEBUG,
        memory_facts=["Known: auth module is fragile"],
    )
    assert "auth module is fragile" in ctx
    assert "Relevant Memory" in ctx


def test_build_debugger_context_caps_memory_facts():
    facts = [f"Fact {i}" for i in range(15)]
    ctx = build_debugger_context(messages=[], intent=Intent.DEBUG, memory_facts=facts)
    assert "Fact 0" in ctx
    assert "Fact 9" in ctx
    assert "Fact 10" not in ctx


def test_build_debugger_context_includes_orchestrator_plan():
    ctx = build_debugger_context(
        messages=[], intent=Intent.DEBUG,
        orchestrator_context="Step 1: Read error log. Step 2: Check git diff.",
    )
    assert "Orchestrator Plan" in ctx
    assert "Read error log" in ctx


def test_build_debugger_context_mentions_workspace_state():
    ctx = build_debugger_context(messages=[], intent=Intent.DEBUG)
    assert "workspace state" in ctx.lower() or "git" in ctx.lower()


# ── is_done() tests ───────────────────────────────────────────────────


def test_is_debugger_done_phase1_always_false():
    done, reason = is_debugger_done(1, 5.0, None, None)
    assert done is False
    assert reason == ""


# ── Scoped toolset tests ──────────────────────────────────────────────


def test_debugger_tools_is_frozenset():
    assert isinstance(DEBUGGER_TOOLS, frozenset)


def test_debugger_tools_are_subset_of_allowed():
    assert DEBUGGER_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_debugger_tools_include_file_task():
    assert "file_task" in DEBUGGER_TOOLS


def test_debugger_tools_include_git():
    assert "git" in DEBUGGER_TOOLS


def test_debugger_tools_include_shell():
    assert "shell" in DEBUGGER_TOOLS


def test_debugger_tools_include_process():
    assert "process" in DEBUGGER_TOOLS


def test_debugger_tools_include_delegate():
    assert "delegate" in DEBUGGER_TOOLS


def test_debugger_tools_exclude_code_exec():
    assert "code_exec" not in DEBUGGER_TOOLS


def test_debugger_tools_exclude_file_write():
    assert "file_write" not in DEBUGGER_TOOLS


def test_debugger_tools_exclude_edit_file():
    assert "edit_file" not in DEBUGGER_TOOLS


def test_debugger_tools_has_exactly_6():
    assert len(DEBUGGER_TOOLS) == 6


# ── Registry integration tests ───────────────────────────────────────


def test_debugger_is_in_registry():
    agent_cls = get_agent("debugger")
    assert agent_cls is not None
    assert agent_cls is DebuggerAgent


def test_debugger_appears_in_list_agents():
    agents = {name: cls for name, cls in list_agents()}
    assert "debugger" in agents
    assert agents["debugger"] is DebuggerAgent


def test_debugger_agent_instantiable():
    agent = DebuggerAgent(adapter=None)
    assert agent.config().name == "debugger"


# ── Selection mapping tests ──────────────────────────────────────────


def test_intent_debug_maps_to_debugger():
    from agents.selection import intent_to_agent_name
    assert intent_to_agent_name(Intent.DEBUG) == "debugger"


def test_select_agent_with_debug_intent():
    agent_cls = select_agent(Intent.DEBUG)
    assert agent_cls is DebuggerAgent


# ── Debugger vs other agents comparison ───────────────────────────────


def test_debugger_has_process_verifier_also_has():
    from agents.verifier.tools import VERIFIER_TOOLS
    assert "process" in DEBUGGER_TOOLS
    assert "process" in VERIFIER_TOOLS


def test_debugger_does_not_have_edit_file():
    from agents.verifier.tools import VERIFIER_TOOLS
    assert "edit_file" in VERIFIER_TOOLS
    assert "edit_file" not in DEBUGGER_TOOLS


def test_debugger_tools_are_subset_of_coding():
    from agents.coding.tools import CODING_TOOLS
    assert DEBUGGER_TOOLS.issubset(CODING_TOOLS)


# ── DOMAIN_TO_AGENT mapping ───────────────────────────────────────────


def test_domain_debug_maps_to_debugger():
    from agents.selection import primary_domain_to_agent_name
    assert primary_domain_to_agent_name("debug") == "debugger"


def test_select_by_task_profile_debug():
    from agents.selection import select_agent_by_task_profile
    agent_cls = select_agent_by_task_profile("debug", Intent.CHAT)
    assert agent_cls is DebuggerAgent
