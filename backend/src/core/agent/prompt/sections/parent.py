# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The parent (native-bootstrap) execution prompt — STATIC sections.

The 4-layer doctrine (User Objective Primacy) with allocated order
slots: identity (10), constraints (110-140), relevant context
(210-290), execution guidance (400-430). The user objective is
deliberately ABSENT: it is per-turn content and leads the TURN band
(sections/turn.py), never the byte-stable prefix.
"""

from __future__ import annotations

from typing import Optional

from core.agent.prompt.names import (
    SECTION_ACT_NOT_ANNOUNCE,
    SECTION_AGENT_PLAYBOOK,
    SECTION_CONVERSATION_OR_ACTION,
    SECTION_IDENTITY,
    SECTION_MULTI_PART_COMPLETION,
    SECTION_ON_DEMAND_LOADING,
    SECTION_SAFETY_GROUNDING,
    SECTION_SELECTION_HINTS,
    SECTION_STYLE_EXAMPLES,
    SECTION_SYSTEM_FACTS,
    SECTION_TOOL_INDEX,
    SECTION_USER_CONTEXT_DEDUCED,
    SECTION_USER_IDENTITY_STATED,
)
from core.agent.prompt.structure import Band, Layer, SectionRegistry, make
from core.agent.tool_schemas import compact_tool_summary
from core.system_snapshot import get_cached_summary
from core.user_context import get_cached_fused
from core.user_profile import format_identity_context

# Section heads of the native parent prompt that `staged_system_prompt` cuts at.
# The builder below interpolates these same constants, so the boundaries cannot
# drift from the text they describe.
_STYLE_HEAD = "Style — terseness and the converse-or-act call (arrows show the final reply):"
_TOOLS_HEAD = "Available tools — pick the RIGHT one for the request (name: what it does):"
_CORE_HEAD = "Core tools ("
_SAFETY_HEAD = "Safety: check current state before writes, edits, or deletes."

def _system_env_line() -> str:
    """The boot-cached system summary as a prompt line, with guidance to answer
    from it instead of calling sysinfo. Empty when the cache is unset."""
    from core.shell_config import note as _shell_note

    summary = get_cached_summary()
    if not summary:
        # The shell choice is a setting, not a boot fact: without the cached
        # summary the model still must know which syntax its commands run in
        # (PowerShell cmdlets were sent to a git-bash shell).
        return _shell_note()
    summary = f"{summary}\n{_shell_note()}".rstrip()
    return (
        f"{summary}\n(You already know the machine above — answer OS/CPU/RAM/disk/"
        "hostname questions directly from it — free disk/RAM are as of startup, so "
        "say so; only call sysinfo for details not listed, e.g. processes, network, "
        "or a live re-read.)"
    )

def build_parent_static_registry(
    tool_defs: Optional[list[dict]] = None,
    agent_context: Optional[str] = None,
) -> SectionRegistry:
    """The parent (native-bootstrap) STATIC prompt as a named-section registry.

    The 4-layer doctrine (User Objective Primacy) with allocated order slots:

    - identity (10): who LocalMind is.
    - constraints (110-140): the conversation-or-action decision, act-not-
      announce, multi-part completion, and the safety/grounding rule — the
      hard rules first, before any context or guidance.
    - relevant context (210-290): the agent playbook, the boot-cached system
      facts, deduced user context, stated identity facts, retrieved memory —
      everything the constraints above reason about.
    - execution guidance (400-430): reply-style examples, the tool index,
      selection hints, on-demand loading.

    The user objective is deliberately ABSENT here: it is per-turn content
    and leads the TURN band (the trailing turn-context message), never the
    byte-stable prefix. The registry is returned (not just its render) so
    the loop can stage later calls by section name (staged_static_content)
    instead of cutting rendered text by section-head string matches.
    """
    registry = SectionRegistry()

    registry.add(
        make(
            SECTION_IDENTITY,
            Band.STATIC,
            Layer.IDENTITY,
            10,
            "You are LocalMind, a general-purpose agent running locally on the "
            "user's machine. You handle whatever the user needs — questions, "
            "files, web research, system tasks, code, calculations, or plain "
            "conversation.",
        )
    )

    # ── Layer 1: constraints ────────────────────────────────────────────
    # The conversation-or-action decision. "System facts above" became
    # "System facts below": the facts moved into the context layer, after
    # the constraints, and the reference must point where the text now is.
    registry.add(
        make(
            SECTION_CONVERSATION_OR_ACTION,
            Band.STATIC,
            Layer.CONSTRAINTS,
            110,
            "You own the user's objective end to end. First decide whether this "
            "turn needs conversation or action:\n"
            "- If the answer is knowledge you already have (including the System "
            "facts below), a question about what YOU can do (read the tool list "
            "below — don't call a tool to discover your own abilities), or the "
            "user is just chatting, reply directly in plain text. Don't call a "
            "tool to confirm what you already know.\n"
            "- If it needs something outside you — files, current information, "
            "running a command, system state, code — use the native tool API. "
            "Never fabricate a tool result or claim you did something you didn't.",
        )
    )
    registry.add(
        make(
            SECTION_ACT_NOT_ANNOUNCE,
            Band.STATIC,
            Layer.CONSTRAINTS,
            120,
            "Be concise and direct. Answer what was asked, then stop — no "
            'preamble ("Sure, let me…"), no postamble ("Let me know if…"), no '
            "narrating your plan. Act instead of announcing the act, and once "
            "the objective is met, end the turn.",
        )
    )
    registry.add(
        make(
            SECTION_MULTI_PART_COMPLETION,
            Band.STATIC,
            Layer.CONSTRAINTS,
            130,
            "Multi-part requests are not done until EVERY part is answered. "
            '"X and Y" means both X and Y: if a tool can get a part you don\'t '
            'have yet, call it — never concede a requested part ("I couldn\'t '
            'get X in this pass"), never defer it to a "next pass", and never '
            "tell the user to check it themselves. A partial answer plus a punt "
            "is an incomplete turn, not an answer.",
        )
    )
    registry.add(
        make(
            SECTION_SAFETY_GROUNDING,
            Band.STATIC,
            Layer.CONSTRAINTS,
            140,
            f"{_SAFETY_HEAD} Ground every answer in what tools actually "
            "returned. Do not emit XML tool calls or expose internal reasoning.",
        )
    )

    # ── Layer 3: relevant context ───────────────────────────────────────
    # The parent agent's contract/playbook rides here on native parent
    # turns (self-contained prompt); conditional sections are simply not
    # registered when empty.
    if agent_context:
        registry.add(
            make(
                SECTION_AGENT_PLAYBOOK,
                Band.STATIC,
                Layer.CONTEXT,
                210,
                agent_context,
            )
        )
    # The boot-cached system summary + fused user context. The agent
    # already KNOWS the machine and the user's regional setting, so it
    # answers those questions directly instead of calling sysinfo or
    # assuming/hedging a region on location-sensitive requests.
    _sys = _system_env_line()
    if _sys:
        registry.add(
            make(
                SECTION_SYSTEM_FACTS,
                Band.STATIC,
                Layer.CONTEXT,
                220,
                _sys,
            )
        )
    _user = get_cached_fused()
    if _user:
        registry.add(
            make(
                SECTION_USER_CONTEXT_DEDUCED,
                Band.STATIC,
                Layer.CONTEXT,
                230,
                _user,
            )
        )
    # The user-STATED identity facts ride the same surface — labeled,
    # guaranteed, and unconditional: unstated facts are declared absent
    # with the clarify-don't-guess contract, so "where am I" is
    # answerable from context or asked about, never inferred from tool
    # results. Boot-cached, so the surface stays byte-stable per process.
    _identity = format_identity_context()
    if _identity:
        registry.add(
            make(
                SECTION_USER_IDENTITY_STATED,
                Band.STATIC,
                Layer.CONTEXT,
                240,
                _identity,
            )
        )
    # Retrieved memory is deliberately ABSENT here: it is per-turn content
    # (memory_weave is a TURN-only section name) — it rides the trailing
    # turn-context message, never the byte-stable prefix.

    # ── Layer 4: execution guidance ─────────────────────────────────────
    registry.add(
        make(
            SECTION_STYLE_EXAMPLES,
            Band.STATIC,
            Layer.GUIDANCE,
            400,
            f"{_STYLE_HEAD}\n"
            '- "how much RAM do I have?" → "16 GB." (from System facts; no tool)\n'
            '- "weather in Nairobi?" → run web_search, then: "24°C, partly cloudy."\n'
            '- "delete the two .bin files in ~/tmp" → run shell to delete, then: '
            '"Deleted junk_a.bin and junk_b.bin."\n'
            '- "can you search the web for this?" → "Yes — I can search the web. '
            'What would you like me to look up?" (a "can you…?" question: state '
            "the capability from your tools; don't fire a blank tool call for an "
            "unspecified target)\n"
            '- "thanks, that helps" → "Anytime." (conversation, no task)',
        )
    )
    # The first native call must stay light. It only needs a capability
    # index so it can name a tool for describe_tool; sending every
    # registry description here recreates the old kitchen-sink prompt.
    # A NAME-only list once made the first tool choice
    # blind to purpose (sysinfo picked for a weather query). Give a compact
    # per-tool purpose summary so selection is informed from turn 1, while
    # staying well below the full-schema kitchen sink.
    compact_tool_list = compact_tool_summary(
        # Scope the capability index to the SAME defs the native
        # tools param is built from (single source of truth) so a scoped
        # agent's bootstrap prompt never advertises tools outside its
        # allowlist. describe_tool is always reachable (tool_defs_for_call
        # adds it even when the raw scoped defs don't carry it).
        allowed_names=(
            {td.get("function", {}).get("name") for td in tool_defs}
            | {"describe_tool"}
            if tool_defs is not None
            else None
        )
    )
    registry.add(
        make(
            SECTION_TOOL_INDEX,
            Band.STATIC,
            Layer.GUIDANCE,
            410,
            f"{_TOOLS_HEAD}\n{compact_tool_list}",
        )
    )
    registry.add(
        make(
            SECTION_SELECTION_HINTS,
            Band.STATIC,
            Layer.GUIDANCE,
            420,
            "Selection hints: current info (weather/news/prices) → web_search "
            "or web_fetch;\nfind files on this computer → system_search; read "
            "a file → file_task; run a\ncommand → shell; system facts "
            "(CPU/RAM/disk) → answer from System above, else sysinfo.",
        )
    )
    # Derive the core/long-tail tool-name lists dynamically
    # from the tier-split constants so this prompt NEVER goes stale when
    # tools move between tiers (an earlier tier move shifted 6 tools
    # core→long-tail but
    # this list was hardcoded and stale until now). Import is local
    # because this is the only path that needs the tier constants.
    from core.agent.tool_schemas import (  # noqa: PLC0415
        CORE_TOOL_NAMES,
        LONG_TAIL_TOOL_NAMES,
    )

    # Intersect the tier lists with the same allowed-name set the
    # compact index and native param use, so the parked multi-agent tools
    # never appear in the on-demand instructions either.
    _allowed_tier_names = (
        {td.get("function", {}).get("name") for td in tool_defs} | {"describe_tool"}
        if tool_defs is not None
        else None
    )
    _core_scope = (
        CORE_TOOL_NAMES
        if _allowed_tier_names is None
        else CORE_TOOL_NAMES & _allowed_tier_names
    )
    _long_tail_scope = (
        LONG_TAIL_TOOL_NAMES
        if _allowed_tier_names is None
        else LONG_TAIL_TOOL_NAMES & _allowed_tier_names
    )
    _core_names_inline = ", ".join(sorted(_core_scope))
    _long_tail_names_inline = ", ".join(sorted(_long_tail_scope))
    registry.add(
        make(
            SECTION_ON_DEMAND_LOADING,
            Band.STATIC,
            Layer.GUIDANCE,
            430,
            f"Core tools ({_core_names_inline}) are loaded with full schemas —\n"
            "call them directly. ONLY for an on-demand tool "
            f"({_long_tail_names_inline})\ncall `describe_tool(\"<name>\")` "
            'FIRST (e.g. `describe_tool("sql")`).',
        )
    )
    return registry
