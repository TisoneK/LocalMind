# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The TURN band — the trailing per-turn context message sections.

The system prompt is the byte-stable, cacheable prefix (identity, tool
list, universal rules). These sections vary by intent or turn (skill
fragment, expert persona, agent playbook, execution plan, routing
hint, the current-intent line), so embedding them in the system prompt
busted the provider prefix cache on every intent switch. The loop
merges them into the trailing turn-context message, which sits AFTER
the stable prefix: the cache survives intent switches, and within a
turn the tail is byte-identical across iterations so it caches too.

Turn-band doctrine order: the current-intent line (the objective layer
— what this turn is about) leads; the guidance sections follow it in
their documented slots (skill, persona, agent playbook, plan, routing
hint), after whatever context sections the loop registered.
Conditional sections are simply not registered when their input is
absent.
"""

from __future__ import annotations

from typing import Optional

from core.agent.prompt.names import (
    SECTION_AGENT_PLAYBOOK,
    SECTION_CURRENT_INTENT,
    SECTION_EXECUTION_PLAN,
    SECTION_EXPERT_PERSONA,
    SECTION_ROUTING_HINT,
    SECTION_SKILL_FRAGMENT,
)
from core.agent.prompt.sections.personas import persona_for_intent
from core.agent.prompt.structure import Band, Layer, SectionRegistry, make
from core.models import Intent


def add_intent_tail_sections(
    registry: SectionRegistry,
    intent: Intent,
    plan_context: Optional[str] = None,
    orchestrator_context: Optional[str] = None,
    agent_context: Optional[str] = None,
) -> None:
    """Register the per-intent / per-turn sections into a TURN registry.

    P0 Context Engineering Step 2 (addendum plan): the system prompt is the
    byte-stable, cacheable prefix (identity, tool list, universal rules).
    These sections vary by intent or turn (skill fragment, expert persona,
    agent playbook, execution plan, routing hint, the current-intent line),
    so embedding them in the system prompt busted the provider prefix cache
    on every intent switch. The AgentLoop merges them into the trailing
    turn-context message, which sits AFTER the stable prefix: the cache
    survives intent switches, and within a turn the tail is byte-identical
    across iterations so it caches too.

    Turn-band doctrine order: the current-intent line (the objective layer —
    what this turn is about) leads; the guidance sections follow it in their
    documented slots (skill, persona, agent playbook, plan, routing hint),
    after whatever context sections the loop registered. Conditional
    sections are simply not registered when their input is absent.
    """
    # The objective layer: what this turn is about, first thing the tail says.
    registry.add(
        make(
            SECTION_CURRENT_INTENT,
            Band.TURN,
            Layer.OBJECTIVE,
            1010,
            f"Current intent: {intent.value}",
        )
    )

    # Inject plan context if available from the planning phase
    if plan_context:
        # The plan was made WITHOUT tool evidence, so "follow exactly /
        # do NOT re-think" forced the model to obey steps that reality had
        # already contradicted (the prompt→tool→answer feel). The plan is a
        # prior: start from it, adapt as evidence lands.
        registry.add(
            make(
                SECTION_EXECUTION_PLAN,
                Band.TURN,
                Layer.GUIDANCE,
                1190,
                f"EXECUTION PLAN — your plan from before any tool ran:\n"
                f"{plan_context}\n"
                "\n"
                "Start from this plan and execute it with the tools. It was written without\n"
                "tool evidence: when a tool result contradicts a step (missing file, failed\n"
                "command, unexpected state), adapt the remaining steps to what you actually\n"
                "found — the goal is the outcome, not the literal steps. You don't need\n"
                "permission to deviate; just keep moving toward the user's goal.",
            )
        )

    # Inject intent-specific skill expertise from .md files
    # This gives the agent domain-specific knowledge (coding practices,
    # research methodology, shell safety, etc.) without bloating base.md.
    from core.context_builder import _intent_fragment_name, _load_fragment

    skill_fragment = _load_fragment(_intent_fragment_name(intent))
    if skill_fragment:
        # Cap the injected skill fragment at ~2,000
        # chars. The head (philosophy + how-to-approach) carries the
        # distinctive per-intent expertise; the tails (language-specific
        # practices, "what NOT to do", debugging heuristics) overlap with
        # the universal CRITICAL RULES / VERIFY / TOOL ARGUMENT sections
        # below and were costing 1.2-1.5K tokens per call on editing intents.
        _SKILL_CAP = 2000
        _truncated_skill = skill_fragment
        if len(skill_fragment) > _SKILL_CAP:
            _truncated_skill = skill_fragment[:_SKILL_CAP] + "\n[... remaining expertise omitted — follow the universal rules below]"
        registry.add(
            make(
                SECTION_SKILL_FRAGMENT,
                Band.TURN,
                Layer.GUIDANCE,
                1160,
                f"## Intent-specific expertise\n{_truncated_skill}",
            )
        )

    # ── Expert persona framing ──────────────────────────────────────────
    # P9: Deepened personas with cognitive strategies, failure modes,
    # and self-correction triggers. Each persona now includes:
    # - Identity: who you are and how you think
    # - Strategy: your approach to the task
    # - Failure modes: what goes wrong and how to catch it
    # - Self-check: a quick verification before responding
    # This produces more focused, expert-quality behavior per intent.
    persona_section = persona_for_intent(intent)
    if persona_section:
        registry.add(
            make(
                SECTION_EXPERT_PERSONA,
                Band.TURN,
                Layer.GUIDANCE,
                1170,
                persona_section.strip(),
            )
        )

    # Inject the selected BaseAgent's context (playbook +
    # persona + agent-specific guidance). This is the load-bearing piece
    # — when the CodingAgent is selected for SHELL/FILE_*/CODE_EXEC
    # intents, its playbook (read-before-write, verify-after-write,
    # follow-conventions, small-verifiable-changes) reaches the model
    # here. Without this section, the CodingAgent is just a scoped
    # toolset (Phase 1 behavior); with it, the CodingAgent's playbook
    # actually governs tool use (Phase 2 behavior).
    if agent_context:
        registry.add(
            make(
                SECTION_AGENT_PLAYBOOK,
                Band.TURN,
                Layer.GUIDANCE,
                1180,
                f"AGENT CONTEXT — your agent type's playbook + guidance:\n"
                f"{agent_context}\n"
                "\n"
                "The above is your agent's playbook. Follow it for every tool call in this\n"
                "turn — it governs HOW you use your scoped tools (read-before-write,\n"
                "verify-after-write, follow-conventions, small-verifiable-changes for\n"
                "the Coding Agent; enough-sources + cite-dates for the Research Agent;\n"
                "etc.). Your scoped toolset is the WHAT; this playbook is the HOW.",
            )
        )

    # Inject caller context as a hint; the parent remains responsible for
    # evaluating the suggestion and choosing the next action.
    if orchestrator_context:
        registry.add(
            make(
                SECTION_ROUTING_HINT,
                Band.TURN,
                Layer.GUIDANCE,
                1200,
                f"ROUTING HINT — evaluate this suggestion before acting:\n"
                f"{orchestrator_context}\n"
                "\n"
                "This hint may be incomplete or wrong. Verify it against the user's goal and\n"
                "current evidence, then choose the appropriate tool, delegate, clarification,\n"
                "or next reasoning step yourself. Do not treat it as an instruction to call a\n"
                "specific tool or follow a fixed order.",
            )
        )

def build_agent_intent_tail(
    intent: Intent,
    plan_context: Optional[str] = None,
    orchestrator_context: Optional[str] = None,
    agent_context: Optional[str] = None,
) -> str:
    """The per-intent / per-turn sections rendered as one tail string.

    Convenience wrapper over add_intent_tail_sections: a fresh TURN
    registry, the sections added, the TURN band rendered. The loop uses
    the add_* form directly so the tail sections share one registry (and
    one deterministic order) with the turn-context sections.
    """
    registry = SectionRegistry()
    add_intent_tail_sections(
        registry,
        intent=intent,
        plan_context=plan_context,
        orchestrator_context=orchestrator_context,
        agent_context=agent_context,
    )
    return registry.render(Band.TURN)

def memory_facts_section_text(memory_facts: list[str]) -> str:
    """The TURN-band retrieved-memory section text, knowledge-framed.

    Memory facts are things the agent KNOWS about the user — never
    "retrieved from a store" prose (the model repeats the framing it
    reads). Registered by the loop as the ``memory_facts`` TURN section;
    never woven into the byte-stable prefix.
    """
    return "What you know about this user:\n" + "\n".join(f"- {f}" for f in memory_facts)
