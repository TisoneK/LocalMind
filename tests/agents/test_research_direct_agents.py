"""
Tests for ResearchAgent and DirectAgent — completes the 4-agent registry.

Locks in:
    - ResearchAgent: scoped to web_search + web_fetch, 10 iters / 300s
    - DirectAgent: tools_enabled=False, empty toolset, 1 iter / 60s
    - All 4 agents registered (browser, coding, research, direct)
    - All 4 toolsets are pairwise disjoint (ADR-6 scoped-toolset value)
"""

from __future__ import annotations

from agents import (
    BrowserAgent,
    CodingAgent,
    DirectAgent,
    ResearchAgent,
    get_agent,
    is_registered,
    list_agents,
)
from agents.browser import BROWSER_TOOLS
from agents.coding import CODING_TOOLS
from agents.direct import DIRECT_TOOLS, build_direct_context, is_direct_done
from agents.research import RESEARCH_TOOLS, build_research_context, is_research_done
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent

# ── ResearchAgent ────────────────────────────────────────────────────────────


def test_research_agent_config():
    agent = ResearchAgent(adapter=None)
    cfg = agent.config()
    assert cfg.name == "research"
    assert cfg.tools_enabled is True
    assert cfg.allowed_tools == RESEARCH_TOOLS
    assert cfg.allowed_tools == frozenset({"web_search", "web_fetch", "delegate", "skill"})
    assert cfg.allowed_tools.issubset(AGENT_ALLOWED_TOOLS)


def test_research_agent_description_concrete():
    agent = ResearchAgent(adapter=None)
    desc = agent.description()
    assert len(desc) > 50
    assert "research" in desc.lower() or "web" in desc.lower()
    assert "cannot" in desc.lower() or "scoped" in desc.lower()


def test_research_agent_build_context():
    """ADR-8 Phase 2 (Session 34): build_context() loads the research
    playbook from agents/research/playbook.md. The "## Research Playbook"
    section header appears, plus the constraints (raw search results are
    NOT the answer, chunk before generating, verify synthesis, etc.).
    """
    agent = ResearchAgent(adapter=None)
    ctx = agent.build_context(
        messages=[], intent=Intent.WEB_SEARCH, memory_facts=["test fact"]
    )
    # Phase 2: the playbook file is loaded
    assert "Research Playbook" in ctx
    assert "Raw search results are NOT the answer" in ctx
    assert "test fact" in ctx


def test_research_agent_is_done_phase1():
    agent = ResearchAgent(adapter=None)
    done, reason = agent.is_done(0, 0.0, None, None)
    assert done is False
    assert reason == ""


def test_research_agent_scoped_tools():
    agent = ResearchAgent(adapter=None)
    all_tools = [
        {"intent": "web_search"}, {"intent": "web_fetch"},
        {"intent": "shell"}, {"intent": "browse"}, {"intent": "code_exec"},
    ]
    scoped = agent.scoped_tools(all_tools)
    assert {t["intent"] for t in scoped} == {"web_search", "web_fetch"}


def test_research_tools_subset():
    assert RESEARCH_TOOLS.issubset(AGENT_ALLOWED_TOOLS)


def test_build_research_context_memory_capped():
    facts = [f"fact {i}" for i in range(20)]
    ctx = build_research_context(messages=[], intent=Intent.WEB_SEARCH, memory_facts=facts)
    assert "fact 0" in ctx
    assert "fact 9" in ctx
    assert "fact 10" not in ctx


def test_is_research_done_phase1():
    assert is_research_done(0, 0.0, None, None) == (False, "")


# ── DirectAgent ──────────────────────────────────────────────────────────────


def test_direct_agent_config():
    agent = DirectAgent(adapter=None)
    cfg = agent.config()
    assert cfg.name == "direct"
    assert cfg.tools_enabled is False  # the key flag
    assert cfg.allowed_tools == DIRECT_TOOLS
    assert cfg.allowed_tools == frozenset()  # empty
    assert cfg.max_iterations == 1  # single call, no loop


def test_direct_agent_description_concrete():
    agent = DirectAgent(adapter=None)
    desc = agent.description()
    assert len(desc) > 50
    assert "direct" in desc.lower() or "chat" in desc.lower()
    assert "no tools" in desc.lower() or "cannot" in desc.lower()


def test_direct_agent_build_context():
    agent = DirectAgent(adapter=None)
    ctx = agent.build_context(messages=[], intent=Intent.CHAT, memory_facts=["fact"])
    assert "Direct Agent" in ctx
    assert "fact" in ctx


def test_direct_agent_is_done_always_true():
    """Direct agent is always done — single model call, no loop."""
    agent = DirectAgent(adapter=None)
    done, reason = agent.is_done(0, 0.0, None, None)
    assert done is True
    assert "direct" in reason.lower() or "single" in reason.lower()


def test_direct_agent_scoped_tools_empty():
    agent = DirectAgent(adapter=None)
    all_tools = [{"intent": "shell"}, {"intent": "web_search"}]
    assert agent.scoped_tools(all_tools) == []


def test_direct_tools_empty():
    assert DIRECT_TOOLS == frozenset()


def test_build_direct_context_minimal():
    ctx = build_direct_context(messages=[], intent=Intent.CHAT)
    assert "Direct Agent" in ctx


def test_is_direct_done_always_true():
    done, reason = is_direct_done(0, 0.0, None, None)
    assert done is True


# ── Registry: all 4 agents ──────────────────────────────────────────────────


def test_registry_has_all_four_agents():
    names = [name for name, _ in list_agents()]
    assert "browser" in names
    assert "coding" in names
    assert "research" in names
    assert "direct" in names
    assert len(names) >= 4


def test_registry_research_registered():
    assert is_registered("research")
    assert get_agent("research") is ResearchAgent


def test_registry_direct_registered():
    assert is_registered("direct")
    assert get_agent("direct") is DirectAgent


# ── All 4 toolsets are pairwise disjoint (ADR-6) ─────────────────────────────


def test_all_four_toolsets_disjoint():
    """ADR-6: each agent has a scoped, non-overlapping PRIMARY toolset.

    ADR-8 Phase 3 (Session 34): the `delegate` tool is intentionally
    shared across multiple agents (it's the universal delegation
    primitive — any agent with `delegate` in its toolset can delegate
    to any other agent). B-2026-08-02-12 (Session 84): `skill` is the
    other intentionally-shared universal tool (any agent may pull a
    skill into context). The PRIMARY tools (excluding both shared
    tools) remain pairwise disjoint: browser has browse, coding has
    shell + file tools, research has web_search + web_fetch, direct
    has none.
    """
    toolsets = [BROWSER_TOOLS, CODING_TOOLS, RESEARCH_TOOLS, DIRECT_TOOLS]
    for i, ts1 in enumerate(toolsets):
        for j, ts2 in enumerate(toolsets):
            if i < j:
                # Strip the shared universal tools before checking disjoint
                _shared = {"delegate", "skill"}
                ts1_primary = ts1 - _shared
                ts2_primary = ts2 - _shared
                assert ts1_primary.isdisjoint(ts2_primary), (
                    f"toolsets {i} and {j} primary tools overlap: "
                    f"{ts1_primary & ts2_primary}"
                )
    # Sanity: delegate IS shared (at least 2 agents have it)
    delegate_count = sum(1 for ts in toolsets if "delegate" in ts)
    assert delegate_count >= 2, (
        f"at least 2 agents should have 'delegate' (Phase 3 delegation); "
        f"only {delegate_count} do"
    )


def test_coding_more_iterations_than_research():
    """Coding tasks need more iterations than research tasks."""
    coding = CodingAgent(adapter=None)
    research = ResearchAgent(adapter=None)
    assert coding.config().max_iterations > research.config().max_iterations


def test_direct_least_iterations():
    """Direct agent has the fewest iterations — single model call."""
    direct = DirectAgent(adapter=None)
    browser = BrowserAgent(adapter=None)
    coding = CodingAgent(adapter=None)
    research = ResearchAgent(adapter=None)
    assert direct.config().max_iterations < browser.config().max_iterations
    assert direct.config().max_iterations < research.config().max_iterations
    assert direct.config().max_iterations < coding.config().max_iterations


def test_direct_only_agent_with_tools_disabled():
    """DirectAgent is the only agent with tools_enabled=False."""
    agents = [BrowserAgent, CodingAgent, ResearchAgent, DirectAgent]
    for cls in agents:
        cfg = cls(adapter=None).config()
        if cls is DirectAgent:
            assert cfg.tools_enabled is False
        else:
            assert cfg.tools_enabled is True
