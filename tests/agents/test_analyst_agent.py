"""
Tests for the AnalystAgent — the requirements-analysis specialist agent.

Verifies:
  - AgentConfig structure (name, max_iterations, max_wall_clock_secs, tools)
  - Description concreteness (ADR-6 point 6)
  - Context builder (workflow injection, memory facts, orchestrator context)
  - is_done() Phase 1 contract
  - Scoped toolset (ANALYST_TOOLS) — the tightest toolset (3 tools)
  - Registry integration
  - Selection mapping (Intent.ANALYZE → analyst)
  - Analyst vs other agent toolset comparison
"""

from __future__ import annotations

from agents import AnalystAgent, get_agent, list_agents, select_agent
from agents.analyst.context_builder import build_analyst_context
from agents.analyst.is_done import is_analyst_done
from agents.analyst.tools import ANALYST_TOOLS
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent

# ── AgentConfig tests ─────────────────────────────────────────────────


def test_analyst_config_name():
    agent = AnalystAgent(adapter=None)
    assert agent.config().name == "analyst"


def test_analyst_config_max_iterations():
    agent = AnalystAgent(adapter=None)
    assert agent.config().max_iterations == 8


def test_analyst_config_max_wall_clock():
    agent = AnalystAgent(adapter=None)
    assert agent.config().max_wall_clock_secs == 180


def test_analyst_config_tools_enabled():
    agent = AnalystAgent(adapter=None)
    assert agent.config().tools_enabled is True


# ── Description tests (ADR-6 point 6) ─────────────────────────────────


def test_analyst_description_is_concrete():
    agent = AnalystAgent(adapter=None)
    desc = agent.description()
    assert "Analyst Agent" in desc
    assert "requirement" in desc.lower()
    assert "spec" in desc.lower() or "specif" in desc.lower()
    assert "build" in desc.lower()
    assert "file_task" in desc.lower() or "file" in desc.lower()


def test_analyst_description_distinct_from_reviewer():
    from agents import ReviewerAgent
    a_desc = AnalystAgent(adapter=None).description()
    r_desc = ReviewerAgent(adapter=None).description()
    assert a_desc != r_desc


# ── Context builder tests ─────────────────────────────────────────────


def test_build_analyst_context_returns_string():
    ctx = build_analyst_context(messages=[], intent=Intent.ANALYZE)
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_build_analyst_context_includes_workflow():
    ctx = build_analyst_context(messages=[], intent=Intent.ANALYZE)
    assert "analyst" in ctx.lower() or "Analyst" in ctx


def test_build_analyst_context_includes_memory_facts():
    ctx = build_analyst_context(
        messages=[], intent=Intent.ANALYZE,
        memory_facts=["Project uses React + FastAPI"],
    )
    assert "React + FastAPI" in ctx
    assert "Relevant Memory" in ctx


def test_build_analyst_context_caps_memory_facts():
    facts = [f"Fact {i}" for i in range(15)]
    ctx = build_analyst_context(messages=[], intent=Intent.ANALYZE, memory_facts=facts)
    assert "Fact 0" in ctx
    assert "Fact 9" in ctx
    assert "Fact 10" not in ctx


def test_build_analyst_context_includes_orchestrator_plan():
    ctx = build_analyst_context(
        messages=[], intent=Intent.ANALYZE,
        orchestrator_context="Step 1: Read PRD. Step 2: Check project.",
    )
    assert "Orchestrator Plan" in ctx
    assert "Read PRD" in ctx


# ── is_done() tests ───────────────────────────────────────────────────


def test_is_analyst_done_phase1_always_false():
    done, reason = is_analyst_done(1, 5.0, None, None)
    assert done is False
    assert reason == ""


# ── Scoped toolset tests ──────────────────────────────────────────────


def test_analyst_tools_is_frozenset():
    assert isinstance(ANALYST_TOOLS, frozenset)


def test_analyst_tools_are_subset_of_allowed():
    assert ANALYST_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_analyst_tools_include_file_task():
    assert "file_task" in ANALYST_TOOLS


def test_analyst_tools_include_git():
    assert "git" in ANALYST_TOOLS


def test_analyst_tools_include_delegate():
    assert "delegate" in ANALYST_TOOLS


def test_analyst_tools_exclude_shell():
    assert "shell" not in ANALYST_TOOLS


def test_analyst_tools_exclude_code_exec():
    assert "code_exec" not in ANALYST_TOOLS


def test_analyst_tools_exclude_process():
    assert "process" not in ANALYST_TOOLS


def test_analyst_tools_has_exactly_4():
    # 3 + skill (B-2026-08-02-12, universal)
    assert len(ANALYST_TOOLS) == 4


def test_analyst_has_tightest_toolset():
    """Analyst has the fewest tools of any agent — just read and delegate."""
    from agents.coding.tools import CODING_TOOLS
    from agents.debugger.tools import DEBUGGER_TOOLS
    from agents.reviewer.tools import REVIEWER_TOOLS
    from agents.verifier.tools import VERIFIER_TOOLS
    assert len(ANALYST_TOOLS) < len(REVIEWER_TOOLS)  # 3 < 4
    assert len(ANALYST_TOOLS) < len(DEBUGGER_TOOLS)  # 3 < 5
    assert len(ANALYST_TOOLS) < len(VERIFIER_TOOLS)  # 3 < 6
    assert len(ANALYST_TOOLS) < len(CODING_TOOLS)     # 3 < 8


# ── Registry integration tests ───────────────────────────────────────


def test_analyst_is_in_registry():
    agent_cls = get_agent("analyst")
    assert agent_cls is not None
    assert agent_cls is AnalystAgent


def test_analyst_appears_in_list_agents():
    agents = {name: cls for name, cls in list_agents()}
    assert "analyst" in agents
    assert agents["analyst"] is AnalystAgent


def test_analyst_agent_instantiable():
    agent = AnalystAgent(adapter=None)
    assert agent.config().name == "analyst"


# ── Selection mapping tests ──────────────────────────────────────────


def test_intent_analyze_maps_to_analyst():
    from agents.selection import intent_to_agent_name
    assert intent_to_agent_name(Intent.ANALYZE) == "analyst"


def test_select_agent_with_analyze_intent():
    agent_cls = select_agent(Intent.ANALYZE)
    assert agent_cls is AnalystAgent


# ── DOMAIN_TO_AGENT mapping ───────────────────────────────────────────


def test_domain_analyze_maps_to_analyst():
    from agents.selection import primary_domain_to_agent_name
    assert primary_domain_to_agent_name("analyze") == "analyst"


def test_select_by_task_profile_analyze():
    from agents.selection import select_agent_by_task_profile
    agent_cls = select_agent_by_task_profile("analyze", Intent.CHAT)
    assert agent_cls is AnalystAgent
