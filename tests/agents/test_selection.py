"""
Tests for agent selection — the intent → agent name → agent class mapping.

Locks in:
    - Every Intent enum value has a mapping (no KeyErrors)
    - Each intent maps to the agent whose scoped toolset includes that intent
    - select_agent() returns the right BaseAgent subclass
    - The mapping is deterministic (same intent → same agent, always)
"""

from __future__ import annotations

from agents import (
    BrowserAgent,
    CodingAgent,
    DirectAgent,
    ResearchAgent,
    intent_to_agent_name,
    list_intent_mappings,
    select_agent,
)
from agents.browser import BROWSER_TOOLS
from agents.coding import CODING_TOOLS
from agents.research import RESEARCH_TOOLS
from core.models import Intent

# ── Every intent is mapped ───────────────────────────────────────────────────


def test_every_intent_is_mapped():
    """Every Intent enum value has a mapping — no KeyErrors."""
    for intent in Intent:
        name = intent_to_agent_name(intent)
        assert name in {"browser", "coding", "research", "direct"}, (
            f"intent {intent.value} mapped to unknown agent {name!r}"
        )


def test_list_intent_mappings_covers_all_intents():
    """list_intent_mappings() returns one entry per ROUTING Intent.

    ADR-8 Phase 3 (Session 34): Intent.DELEGATE is a meta-tool intent
    (the agent calls the `delegate` tool, which is then dispatched by
    the agent loop). It is NOT a routing intent — the intent classifier
    never produces DELEGATE; it's only invoked when the model calls the
    delegate tool. So it's excluded from the routing map.
    """
    mappings = list_intent_mappings()
    mapped_intents = {intent for intent, _ in mappings}
    # All routing intents must be mapped
    routing_intents = {i for i in Intent if i != Intent.DELEGATE}
    for intent in routing_intents:
        assert intent in mapped_intents, f"routing intent {intent.value} not in mappings"
    # DELEGATE is intentionally NOT in the routing map
    assert Intent.DELEGATE not in mapped_intents, (
        "Intent.DELEGATE should not be in the routing map — it's a "
        "meta-tool intent, not a routing intent. The intent classifier "
        "never produces DELEGATE; it's only invoked when the model calls "
        "the delegate tool."
    )


# ── Intent → agent name correctness ──────────────────────────────────────────


def test_coding_intents_map_to_coding():
    """SHELL, FILE_TASK, FILE_WRITE, FILE_EDIT, CODE_EXEC → coding."""
    assert intent_to_agent_name(Intent.SHELL) == "coding"
    assert intent_to_agent_name(Intent.FILE_TASK) == "coding"
    assert intent_to_agent_name(Intent.FILE_WRITE) == "coding"
    assert intent_to_agent_name(Intent.FILE_EDIT) == "coding"
    assert intent_to_agent_name(Intent.CODE_EXEC) == "coding"


def test_research_intents_map_to_research():
    """WEB_SEARCH, WEB_FETCH → research."""
    assert intent_to_agent_name(Intent.WEB_SEARCH) == "research"
    assert intent_to_agent_name(Intent.WEB_FETCH) == "research"


def test_browser_intent_maps_to_browser():
    """BROWSE → browser."""
    assert intent_to_agent_name(Intent.BROWSE) == "browser"


def test_chat_intent_maps_to_direct():
    """CHAT → direct (no tools, single model call)."""
    assert intent_to_agent_name(Intent.CHAT) == "direct"


def test_secondary_intents_map_to_coding():
    """SYSINFO, MEMORY_OP → coding (broadest toolset, secondary during any task)."""
    assert intent_to_agent_name(Intent.SYSINFO) == "coding"
    assert intent_to_agent_name(Intent.MEMORY_OP) == "coding"


# ── select_agent() returns the right class ───────────────────────────────────


def test_select_agent_returns_coding_class():
    assert select_agent(Intent.SHELL) is CodingAgent
    assert select_agent(Intent.CODE_EXEC) is CodingAgent


def test_select_agent_returns_research_class():
    assert select_agent(Intent.WEB_SEARCH) is ResearchAgent


def test_select_agent_returns_browser_class():
    assert select_agent(Intent.BROWSE) is BrowserAgent


def test_select_agent_returns_direct_class():
    assert select_agent(Intent.CHAT) is DirectAgent


# ── Determinism ──────────────────────────────────────────────────────────────


def test_mapping_is_deterministic():
    """Same intent → same agent, always."""
    for intent in Intent:
        name1 = intent_to_agent_name(intent)
        name2 = intent_to_agent_name(intent)
        assert name1 == name2


# ── Consistency: mapped agent's toolset includes the intent's tool ───────────


def test_coding_intents_are_in_coding_toolset():
    """Every intent mapped to 'coding' should be in CODING_TOOLS (or a
    secondary intent like SYSINFO/MEMORY_OP that's coded as coding by
    convention)."""
    # The 5 coding-tool intents must map to tools in CODING_TOOLS
    coding_tool_intents = {
        Intent.SHELL: "shell",
        Intent.FILE_TASK: "file_task",
        Intent.FILE_WRITE: "file_write",
        Intent.FILE_EDIT: "edit_file",  # NOTE: intent value is "file_edit" but tool name is "edit_file"
        Intent.CODE_EXEC: "code_exec",
    }
    for intent, tool_name in coding_tool_intents.items():
        assert intent_to_agent_name(intent) == "coding"
        assert tool_name in CODING_TOOLS, (
            f"tool {tool_name!r} for intent {intent.value} not in CODING_TOOLS"
        )


def test_research_intents_are_in_research_toolset():
    """Every intent mapped to 'research' should be in RESEARCH_TOOLS."""
    assert "web_search" in RESEARCH_TOOLS
    assert "web_fetch" in RESEARCH_TOOLS


def test_browser_intent_is_in_browser_toolset():
    """The BROWSE intent's tool should be in BROWSER_TOOLS."""
    assert "browse" in BROWSER_TOOLS


def test_direct_intent_has_no_tools():
    """The CHAT intent maps to direct agent which has no tools."""
    assert select_agent(Intent.CHAT).__name__ == "DirectAgent"
    direct = DirectAgent(adapter=None)
    assert direct.config().allowed_tools == frozenset()
    assert direct.config().tools_enabled is False
