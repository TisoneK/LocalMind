# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The execution-prompt surface dispatcher.

v0.9 changes:
- Restructured for Plan→Execute→Verify workflow
- Planning phase: dedicated prompt asks the model to plan before acting
- Execution phase: plan context injected so model follows the plan
- Verification phase: prompt encourages self-checking after tool execution
- Removed duplicate JSON action format (native tool calling handles this)
- Added intent-specific workflow templates for common tasks

v0.8 changes:
- Added OS/shell awareness: injects the environment context so the
  model knows whether it's on Windows (CMD/PowerShell) or Unix (bash/zsh).
- Added planning guidance: instructs the model to think before calling
  tools, especially for file_write where both 'path' and 'content' must
  be present in a single call.
- Added tool arg validation hints: reminds the model that file_write
  requires both 'path' AND 'content', shell commands must match the
  current OS, etc.

The dispatcher picks ONE of three registry-built surfaces and returns
its STATIC render:

- native_bootstrap → sections.parent (the parent's warm-kernel prompt)
- Intent.CHAT      → sections.chat (the conversational surface)
- otherwise        → sections.agent (the scoped execution-agent prompt)
"""

from __future__ import annotations

from typing import Optional

from core.agent.prompt.sections.agent import (
    agent_tool_list_text,
    build_agent_static_registry,
)
from core.agent.prompt.sections.chat import build_chat_static_registry
from core.agent.prompt.sections.parent import build_parent_static_registry
from core.agent.prompt.structure import Band
from core.models import Intent


def build_agent_system_prompt(
    intent: Intent,
    available_tools: list[dict],
    intent_history: Optional[list[str]] = None,
    plan_context: Optional[str] = None,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
    agent_context: Optional[str] = None,
    tool_defs: Optional[list[dict]] = None,
    native_bootstrap: bool = False,
) -> str:
    """
    Return the agent execution-phase system prompt string.

    Args:
        intent:               The resolved effective intent for this turn.
        available_tools:      Metadata dicts from tools.available_tools().
        intent_history:       Optional list of recent intent values (most recent last)
                              used to improve follow-up message accuracy.
        plan_context:         Optional planning-phase output to inject so the model
                              follows the plan instead of free-styling.
        memory_facts:         Optional list of memory facts retrieved for this turn.
                              Injected into the prompt so the agent has context about
                              the user across all intents, not just CHAT.
        orchestrator_context: Optional caller-provided routing hint or context.
                              The parent agent evaluates it before acting; it is
                              not a directive that replaces parent planning.
        agent_context:        Optional agent-specific context from the selected
                              BaseAgent subclass's build_context() method. When the CodingAgent is selected, this
                              includes the coding playbook (read-before-write,
                              verify-after-write, follow-conventions, small-
                              verifiable-changes) loaded from
                              agents/coding/playbook.md. Same for research /
                              browser / direct agents. When None (Direct Mode
                              or no agent selected), the section is omitted.
    """
    # Agent-loop token efficiency: the environment
    # context — which bakes in the CURRENT TIME (changes every minute) plus
    # OS/cwd — is NO LONGER embedded here. It was the worst prompt-cache
    # buster: a per-minute string in the middle of the otherwise-static system
    # prompt meant even providers that auto-cache identical prefixes missed on
    # every call. The loop now appends the environment as a SEPARATE trailing
    # message (see AgentLoop, build the turn context), keeping this system
    # prompt byte-stable so the system+tools prefix caches.

    # Intent history is per-turn/dynamic and rides the trailing
    # turn-context (loop.py), not the byte-stable prefix — no longer embedded in
    # any branch of this builder.

    agent_tool_list = agent_tool_list_text(available_tools, tool_defs)

    # Warm-kernel bootstrap: the first native parent call gets only the
    # describe_tool schema plus this compact capability index. Full tool
    # schemas are loaded on demand after the model selects a tool. This keeps
    # ordinary direct conversation from paying the entire tool catalog while
    # preserving one model-owned parent boundary for every turn.
    if native_bootstrap:
        # The parent prompt is assembled from the named-section registry
        # (4-layer doctrine: identity -> constraints -> context -> guidance).
        # build_parent_static_registry carries the full section comments.
        return build_parent_static_registry(
            tool_defs=tool_defs,
            agent_context=agent_context,
        ).render(Band.STATIC)

    # Chat mode: natural conversational response — rich, thoughtful, alive
    if intent == Intent.CHAT:
        # Byte-stable chat prefix, assembled from the named-section registry
        # (same 4-layer doctrine as the parent prompt; see sections.chat).
        return build_chat_static_registry().render(Band.STATIC)

    return build_agent_static_registry(agent_tool_list).render(Band.STATIC)
