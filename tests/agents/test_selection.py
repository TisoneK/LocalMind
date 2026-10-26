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
        assert name in {"browser", "coding", "research", "direct", "verifier", "reviewer", "debugger", "analyst"}, (
            f"intent {intent.value} mapped to unknown agent {name!r}"
        )


def test_list_intent_mappings_covers_all_intents():
    """list_intent_mappings() returns one entry per ROUTING Intent.

    ADR-8 Phase 3  + B-2026-08-02-6  +
    B-2026-08-02-7  + B-2026-08-02-8  +
    B-2026-08-02-12  + B-2026-08-02-11: the
    DELEGATE / DELEGATE_PARALLEL / PROPOSE_EDIT / PROPOSE_WRITE /
    APPLY_PROPOSED / ADD_SUBGOAL / UPDATE_SUBGOAL / CREATE_PLAN / SKILL /
    BEST_OF_N_EDIT intents are meta-tool intents (the agent calls the
    corresponding tools, which are then dispatched by the agent loop).
    They are NOT routing intents — the intent classifier never produces
    them; they're only invoked when the model calls the tools. So they're
    excluded from the routing map.
    """
    mappings = list_intent_mappings()
    mapped_intents = {intent for intent, _ in mappings}
    # All routing intents must be mapped
    meta_tool_intents = (
        Intent.DELEGATE,
        Intent.DELEGATE_PARALLEL,
        Intent.DELEGATE_INLINE,
        Intent.PROPOSE_EDIT,
        Intent.PROPOSE_WRITE,
        Intent.APPLY_PROPOSED,
        Intent.ADD_SUBGOAL,
        Intent.UPDATE_SUBGOAL,
        Intent.CREATE_PLAN,
        Intent.SKILL,
        Intent.BEST_OF_N_EDIT,
        Intent.DESCRIBE_TOOL,  # ADR-40 option C: the describe_tool meta-tool
        Intent.TODO_WRITE,  # ADR-43: the todo_write meta-tool (agent-called, not routed)
        Intent.WEB_RESEARCH,  # Session 340: adaptive web acquisition (agent-called, not routed)
        Intent.SEARCH_TOOL_RESULTS,  # P0 Step 4 slice 2: read back a stored result (agent-called, not routed)
        Intent.GET_GOAL,  # durable-goal meta-tool (agent-called, not routed)
        Intent.UPDATE_GOAL,  # durable-goal meta-tool (agent-called, not routed)
    )
    routing_intents = {i for i in Intent if i not in meta_tool_intents}
    for intent in routing_intents:
        assert intent in mapped_intents, f"routing intent {intent.value} not in mappings"
    # Meta-tool intents are intentionally NOT in the routing map
    assert Intent.DELEGATE not in mapped_intents, (
        "Intent.DELEGATE should not be in the routing map — it's a "
        "meta-tool intent, not a routing intent. The intent classifier "
        "never produces DELEGATE; it's only invoked when the model calls "
        "the delegate tool."
    )
    assert Intent.DELEGATE_PARALLEL not in mapped_intents, (
        "Intent.DELEGATE_PARALLEL should not be in the routing map — it's "
        "a meta-tool intent like DELEGATE, not a routing intent."
    )
    assert Intent.DELEGATE_INLINE not in mapped_intents, (
        "Intent.DELEGATE_INLINE should not be in the routing map — it's a "
        "meta-tool intent (the model calls the delegate_inline tool inside "
        "an agent loop); the intent classifier never produces it."
    )
    assert Intent.PROPOSE_EDIT not in mapped_intents, (
        "Intent.PROPOSE_EDIT should not be in the routing map — it's a "
        "meta-tool intent (the model calls the propose_str_replace tool)."
    )
    assert Intent.PROPOSE_WRITE not in mapped_intents, (
        "Intent.PROPOSE_WRITE should not be in the routing map — it's a "
        "meta-tool intent (the model calls the propose_write_file tool)."
    )
    assert Intent.APPLY_PROPOSED not in mapped_intents, (
        "Intent.APPLY_PROPOSED should not be in the routing map — it's a "
        "meta-tool intent (the model calls the apply_proposed_edit tool)."
    )
    assert Intent.ADD_SUBGOAL not in mapped_intents, (
        "Intent.ADD_SUBGOAL should not be in the routing map — it's a "
        "meta-tool intent (the model calls the add_subgoal tool)."
    )
    assert Intent.UPDATE_SUBGOAL not in mapped_intents, (
        "Intent.UPDATE_SUBGOAL should not be in the routing map — it's a "
        "meta-tool intent (the model calls the update_subgoal tool)."
    )
    assert Intent.CREATE_PLAN not in mapped_intents, (
        "Intent.CREATE_PLAN should not be in the routing map — it's a "
        "meta-tool intent (the model calls the create_plan tool)."
    )
    assert Intent.SKILL not in mapped_intents, (
        "Intent.SKILL should not be in the routing map — it's a "
        "meta-tool intent (the model calls the skill tool)."
    )
    assert Intent.BEST_OF_N_EDIT not in mapped_intents, (
        "Intent.BEST_OF_N_EDIT should not be in the routing map — it's a "
        "meta-tool intent (the model calls the best_of_n_edit tool)."
    )
    assert Intent.DESCRIBE_TOOL not in mapped_intents, (
        "Intent.DESCRIBE_TOOL should not be in the routing map — it's a "
        "meta-tool intent (the model calls the describe_tool tool inside an "
        "agent loop); the intent classifier never produces it."
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
