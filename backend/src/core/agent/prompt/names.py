"""The section-name catalog — the assembly contract between producers.

Every section name LocalMind registers lives here, grouped by prompt
surface, with its allocated order slot in a comment. The names are the
contract between the section builders (sections/), the loop's staged
input selection (staging.py), and the per-section telemetry — renaming
one means renaming it here and at every use; the registry fails loud on
any drift.

New sections take a free slot inside their layer's range (see
structure.LAYER_ORDER_RANGES), never a number outside it, and are
defined in their surface's section file — never inline in a builder.

Names listed in TURN_ONLY_SECTION_NAMES are per-turn content (retrieved
memory, plans, routing, state). They can never be registered into the
STATIC band — a per-turn value inside the cacheable prefix is the
cache-buster bug class, and the registry refuses it at construction
instead of at review time.
"""

from __future__ import annotations

# Sections whose content is inherently PER-TURN. These names can never be
# registered into the STATIC band — a per-turn value inside the cacheable
# prefix is the cache-buster bug class, and the registry refuses it at
# construction instead of at review time.
TURN_ONLY_SECTION_NAMES: frozenset[str] = frozenset(
    {
        "current_intent",
        "environment",
        "memory_facts",
        "memory_weave",
        "intent_history",
        "workspace_state",
        "todo_state",
        "goal_route",
        "task_state",
        "transcript_focus",
        "skill_fragment",
        "expert_persona",
        "execution_plan",
        "routing_hint",
    }
)

# ── Section names LocalMind uses today ──────────────────────────────────────
# The names are the assembly contract between the builders, the loop's
# staged input selection, and the per-section telemetry. Renaming one means
# renaming it here and at every use — the registry fails loud on any drift.

# STATIC band — the parent (native bootstrap) execution prompt
SECTION_IDENTITY = "identity"  # 10
SECTION_CONVERSATION_OR_ACTION = "conversation_or_action"  # 110
SECTION_ACT_NOT_ANNOUNCE = "act_not_announce"  # 120
SECTION_MULTI_PART_COMPLETION = "multi_part_completion"  # 130
SECTION_SAFETY_GROUNDING = "safety_grounding"  # 140
SECTION_AGENT_PLAYBOOK = "agent_playbook"  # 210
SECTION_SYSTEM_FACTS = "system_facts"  # 220
SECTION_USER_CONTEXT_DEDUCED = "user_context_deduced"  # 230
SECTION_USER_IDENTITY_STATED = "user_identity_stated"  # 240
SECTION_MEMORY_WEAVE = "memory_weave"  # 290
SECTION_STYLE_EXAMPLES = "style_examples"  # 400
SECTION_TOOL_INDEX = "tool_index"  # 410
SECTION_SELECTION_HINTS = "selection_hints"  # 420
SECTION_ON_DEMAND_LOADING = "on_demand_loading"  # 430

# STATIC band — the scoped execution-agent prompt
SECTION_CRITICAL_RULES = "critical_rules"  # 110
SECTION_SAFETY_CHECK_STATE = "safety_check_state"  # 120
SECTION_TOOL_LIST = "tool_list"  # 310
SECTION_VERIFY_RESULTS = "verify_results"  # 400
SECTION_COMPLETION_ENFORCEMENT = "completion_enforcement"  # 410
SECTION_TOOL_ARGUMENT_RULES = "tool_argument_rules"  # 420
SECTION_THINKING_AND_RESPONDING = "thinking_and_responding"  # 430
SECTION_RESPONSE_FORMATTING = "response_formatting"  # 440
SECTION_ITERATION_BUDGET = "iteration_budget"  # 449

# STATIC band — the chat-surface prompt
SECTION_CONVERSATION_CONTRACT = "conversation_contract"  # 110
SECTION_ANTI_FABRICATION = "anti_fabrication"  # 120
SECTION_TIME_SENSITIVE_DATA = "time_sensitive_data"  # 130
SECTION_GENERAL_RULES = "general_rules"  # 140
SECTION_THINKING_DEPTH = "thinking_depth"  # 400

# TURN band — the trailing per-turn context message
SECTION_CURRENT_INTENT = "current_intent"  # 1010
SECTION_ENVIRONMENT = "environment"  # 1050
SECTION_MEMORY_FACTS = "memory_facts"  # 1060
SECTION_INTENT_HISTORY = "intent_history"  # 1065
SECTION_WORKSPACE_STATE = "workspace_state"  # 1070
SECTION_TODO_STATE = "todo_state"  # 1080
SECTION_GOAL_ROUTE = "goal_route"  # 1090
SECTION_TASK_STATE = "task_state"  # 1100
SECTION_TRANSCRIPT_FOCUS = "transcript_focus"  # 1110
SECTION_SKILL_FRAGMENT = "skill_fragment"  # 1160
SECTION_EXPERT_PERSONA = "expert_persona"  # 1170
SECTION_EXECUTION_PLAN = "execution_plan"  # 1190
SECTION_ROUTING_HINT = "routing_hint"  # 1200
