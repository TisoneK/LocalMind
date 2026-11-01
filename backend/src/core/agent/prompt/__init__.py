"""LocalMind's prompt package — every prompt the agent assembles, in one place.

A prompt is never a string that grew; it is NAMED SECTIONS with allocated
order slots, assembled by a strict registry. This package owns that whole
surface:

Layout (each file has one reason to change):

    structure.py         the registry engine — bands (STATIC = byte-stable
                         cacheable prefix, TURN = per-turn tail), the
                         4-layer doctrine (User Objective Primacy), order-
                         slot ranges, strict assembly (duplicate names,
                         unknown references, empty sections: fail loud
                         before any model call)
    names.py             the section-name catalog — the assembly contract
                         between builders, staged cuts, and telemetry;
                         also the TURN-only guard list
    staging.py           later-call input selection: what a mid-turn call
                         still needs, cut by section name
    rules.py             shared canonical rules — one statement per rule,
                         consumed by several surfaces
    sections/            the section TEXT, one module per prompt surface:
                         parent.py (native bootstrap), chat.py,
                         agent.py (scoped execution agent),
                         personas.py (per-intent expert framing),
                         turn.py (the TURN band)
    system.py            the surface dispatcher (build_agent_system_prompt)
    planner.py           the planning-phase prompt
    pipeline.py          the Chat Agent + Orchestrator handoff surfaces

How to expand:

- New section text: edit the surface's file in sections/ — a wording fix
  lands in exactly one place.
- New section: pick a free order slot inside its layer's range (see
  structure.LAYER_ORDER_RANGES), name it in names.py, register it in the
  surface's builder. Per-turn content registers TURN band only.
- New prompt surface: one new module in sections/ (or a builder here),
  registered in the dispatcher — the engine and the contract do not move.

Consumers import from this package, never from the modules inside it:
`from core.agent.prompt import Band, build_agent_system_prompt`.
"""

from __future__ import annotations

from core.agent.prompt.budget import (
    SOCIAL_DROP_SECTIONS,
    RelevanceHorizon,
    dropped_sections_for,
    horizon_for_intent,
    horizon_from_string,
    render_static_budgeted,
)
from core.agent.prompt.names import (
    SECTION_ACT_NOT_ANNOUNCE,
    SECTION_AGENT_PLAYBOOK,
    SECTION_ANTI_FABRICATION,
    SECTION_CARRIED_OBJECTIVE,
    SECTION_COMPLETION_ENFORCEMENT,
    SECTION_CONVERSATION_CONTRACT,
    SECTION_CONVERSATION_OR_ACTION,
    SECTION_CRITICAL_RULES,
    SECTION_CURRENT_INTENT,
    SECTION_ENVIRONMENT,
    SECTION_EXECUTION_PLAN,
    SECTION_EXPERT_PERSONA,
    SECTION_GENERAL_RULES,
    SECTION_GOAL_ROUTE,
    SECTION_IDENTITY,
    SECTION_INTENT_HISTORY,
    SECTION_ITERATION_BUDGET,
    SECTION_MEMORY_FACTS,
    SECTION_MEMORY_WEAVE,
    SECTION_MULTI_PART_COMPLETION,
    SECTION_ON_DEMAND_LOADING,
    SECTION_OPEN_QUESTION,
    SECTION_RESPONSE_FORMATTING,
    SECTION_ROUTING_HINT,
    SECTION_SAFETY_CHECK_STATE,
    SECTION_SAFETY_GROUNDING,
    SECTION_SELECTION_HINTS,
    SECTION_SKILL_FRAGMENT,
    SECTION_STYLE_EXAMPLES,
    SECTION_SYSTEM_FACTS,
    SECTION_TASK_STATE,
    SECTION_THINKING_AND_RESPONDING,
    SECTION_THINKING_DEPTH,
    SECTION_TIME_SENSITIVE_DATA,
    SECTION_TODO_STATE,
    SECTION_TOOL_ARGUMENT_RULES,
    SECTION_TOOL_INDEX,
    SECTION_TOOL_LIST,
    SECTION_TRANSCRIPT_FOCUS,
    SECTION_USER_CONTEXT_DEDUCED,
    SECTION_USER_IDENTITY_STATED,
    SECTION_VERIFY_RESULTS,
    SECTION_WORKSPACE_STATE,
    TURN_ONLY_SECTION_NAMES,
)
from core.agent.prompt.pipeline import (
    build_chat_agent_prompt,
    build_orchestrator_prompt,
)
from core.agent.prompt.planner import build_planning_prompt
from core.agent.prompt.rules import (
    CAPABILITY_HONESTY_SPINE,
    NO_MODES_RULE,
    QUESTION_VS_DIRECTIVE_RULE,
)
from core.agent.prompt.sections.agent import (
    agent_tool_list_text,
    build_agent_static_registry,
)
from core.agent.prompt.sections.chat import build_chat_static_registry
from core.agent.prompt.sections.parent import (
    _CORE_HEAD,
    _SAFETY_HEAD,
    _STYLE_HEAD,
    _TOOLS_HEAD,
    _system_env_line,
    build_parent_static_registry,
)
from core.agent.prompt.sections.personas import persona_for_intent
from core.agent.prompt.sections.turn import (
    add_intent_tail_sections,
    build_agent_intent_tail,
    memory_facts_section_text,
)
from core.agent.prompt.staging import (
    STAGED_ANSWER_ONLY_EXCLUDES,
    STAGED_TOOL_RESULT_EXCLUDES,
    staged_static_content,
    staged_system_prompt,
)
from core.agent.prompt.structure import (
    LAYER_ORDER_RANGES,
    Band,
    Layer,
    PromptStructureError,
    RenderedSection,
    Section,
    SectionRegistry,
    make,
)
from core.agent.prompt.system import build_agent_system_prompt

__all__ = [
    # engine
    "Band",
    "Layer",
    "PromptStructureError",
    "LAYER_ORDER_RANGES",
    "Section",
    "RenderedSection",
    "SectionRegistry",
    "TURN_ONLY_SECTION_NAMES",
    "make",
    # section-name contract
    "SECTION_ACT_NOT_ANNOUNCE",
    "SECTION_AGENT_PLAYBOOK",
    "SECTION_ANTI_FABRICATION",
    "SECTION_COMPLETION_ENFORCEMENT",
    "SECTION_CONVERSATION_CONTRACT",
    "SECTION_CONVERSATION_OR_ACTION",
    "SECTION_CRITICAL_RULES",
    "SECTION_CURRENT_INTENT",
    "SECTION_CARRIED_OBJECTIVE",
    "SECTION_ENVIRONMENT",
    "SECTION_EXECUTION_PLAN",
    "SECTION_EXPERT_PERSONA",
    "SECTION_GENERAL_RULES",
    "SECTION_GOAL_ROUTE",
    "SECTION_IDENTITY",
    "SECTION_INTENT_HISTORY",
    "SECTION_ITERATION_BUDGET",
    "SECTION_MEMORY_FACTS",
    "SECTION_MEMORY_WEAVE",
    "SECTION_MULTI_PART_COMPLETION",
    "SECTION_ON_DEMAND_LOADING",
    "SECTION_OPEN_QUESTION",
    "SECTION_RESPONSE_FORMATTING",
    "SECTION_ROUTING_HINT",
    "SECTION_SAFETY_CHECK_STATE",
    "SECTION_SAFETY_GROUNDING",
    "SECTION_SELECTION_HINTS",
    "SECTION_SKILL_FRAGMENT",
    "SECTION_STYLE_EXAMPLES",
    "SECTION_SYSTEM_FACTS",
    "SECTION_TASK_STATE",
    "SECTION_THINKING_AND_RESPONDING",
    "SECTION_THINKING_DEPTH",
    "SECTION_TIME_SENSITIVE_DATA",
    "SECTION_TODO_STATE",
    "SECTION_TOOL_ARGUMENT_RULES",
    "SECTION_TOOL_INDEX",
    "SECTION_TOOL_LIST",
    "SECTION_TRANSCRIPT_FOCUS",
    "SECTION_USER_CONTEXT_DEDUCED",
    "SECTION_USER_IDENTITY_STATED",
    "SECTION_VERIFY_RESULTS",
    "SECTION_WORKSPACE_STATE",
    # staging
    "STAGED_ANSWER_ONLY_EXCLUDES",
    "STAGED_TOOL_RESULT_EXCLUDES",
    "staged_static_content",
    "staged_system_prompt",
    # per-turn relevance budget
    "SOCIAL_DROP_SECTIONS",
    "RelevanceHorizon",
    "dropped_sections_for",
    "horizon_for_intent",
    "horizon_from_string",
    "render_static_budgeted",
    # shared rules
    "CAPABILITY_HONESTY_SPINE",
    "NO_MODES_RULE",
    "QUESTION_VS_DIRECTIVE_RULE",
    # builders
    "add_intent_tail_sections",
    "agent_tool_list_text",
    "build_agent_intent_tail",
    "build_agent_static_registry",
    "build_agent_system_prompt",
    "build_chat_agent_prompt",
    "build_chat_static_registry",
    "build_orchestrator_prompt",
    "build_parent_static_registry",
    "build_planning_prompt",
    "memory_facts_section_text",
    "persona_for_intent",
    # legacy boundary constants + helpers (kept importable; tests pin them)
    "_CORE_HEAD",
    "_SAFETY_HEAD",
    "_STYLE_HEAD",
    "_TOOLS_HEAD",
    "_system_env_line",
]
