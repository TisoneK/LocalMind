"""
Tests for ADR-8 Phase 4: task-type-based agent selection.

Per ADR-8 Principle 1: "Classification by task type, not tool. 'Create
hello world repo' is a *coding* task → CodingAgent — not a SHELL
intent → CodingAgent."

The task-type `primary_domain` field (populated by
ThinkingDispatcher) is the task-type signal. Phase 4 wires it into
agent selection: when primary_domain is set, it routes to the
appropriate agent directly, bypassing the intent→agent map.

Tests:
    - primary_domain_to_agent_name() maps known domains correctly
    - primary_domain_to_agent_name() returns None for empty/unknown
    - select_agent_by_task_profile() uses primary_domain when set
    - select_agent_by_task_profile() falls back to intent when empty
    - select_agent_by_task_profile() falls back to intent when unknown
    - the engine's agent-selection call uses select_agent_by_task_profile
      (verified via import inspection, not a full engine run)
"""

from __future__ import annotations

import pytest

from agents import (
    BrowserAgent,
    CodingAgent,
    DirectAgent,
    ResearchAgent,
    primary_domain_to_agent_name,
    select_agent,
    select_agent_by_task_profile,
)
from core.models import Intent


# ── primary_domain_to_agent_name ──────────────────────────────────────────


@pytest.mark.parametrize(
    "domain,expected_agent_name",
    [
        ("shell_command", "coding"),
        ("web_fetch", "research"),
        ("web_search", "research"),
        ("browse", "browser"),
        ("file_analysis", "coding"),
        ("file_edit", "coding"),
        ("file_write", "coding"),
        ("system_info", "coding"),
        ("code_exec", "coding"),
        ("memory_op", "coding"),
        ("chat", "direct"),
        ("direct", "direct"),
    ],
)
def test_primary_domain_to_agent_name_known_domains(domain, expected_agent_name):
    """Each known primary_domain maps to the expected agent name."""
    assert primary_domain_to_agent_name(domain) == expected_agent_name


def test_primary_domain_to_agent_name_empty_returns_none():
    """Empty primary_domain returns None (caller falls back to intent)."""
    assert primary_domain_to_agent_name("") is None


def test_primary_domain_to_agent_name_unknown_returns_none():
    """Unknown primary_domain returns None (caller falls back to intent)."""
    assert primary_domain_to_agent_name("unknown_xyz") is None
    assert primary_domain_to_agent_name("not_in_map") is None


# ── select_agent_by_task_profile ──────────────────────────────────────────


@pytest.mark.parametrize(
    "primary_domain,expected_class",
    [
        ("shell_command", CodingAgent),
        ("web_fetch", ResearchAgent),
        ("web_search", ResearchAgent),
        ("browse", BrowserAgent),
        ("file_analysis", CodingAgent),
        ("file_edit", CodingAgent),
        ("file_write", CodingAgent),
        ("system_info", CodingAgent),
        ("code_exec", CodingAgent),
        ("memory_op", CodingAgent),
        ("chat", DirectAgent),
        ("direct", DirectAgent),
    ],
)
def test_select_agent_by_task_profile_uses_primary_domain(primary_domain, expected_class):
    """When primary_domain is set, select_agent_by_task_profile uses it."""
    # Use a mismatched fallback intent to prove primary_domain wins
    fallback_intent = Intent.CHAT  # would route to DirectAgent if used
    cls = select_agent_by_task_profile(primary_domain, fallback_intent)
    assert cls is expected_class, (
        f"primary_domain={primary_domain!r} should select {expected_class.__name__}; "
        f"got {cls.__name__ if cls else None}"
    )


def test_select_agent_by_task_profile_falls_back_when_empty():
    """When primary_domain is empty, falls back to intent-based selection."""
    cls = select_agent_by_task_profile("", Intent.SHELL)
    assert cls is CodingAgent  # SHELL intent → coding

    cls = select_agent_by_task_profile("", Intent.WEB_SEARCH)
    assert cls is ResearchAgent  # WEB_SEARCH intent → research

    cls = select_agent_by_task_profile("", Intent.BROWSE)
    assert cls is BrowserAgent  # BROWSE intent → browser

    cls = select_agent_by_task_profile("", Intent.CHAT)
    assert cls is DirectAgent  # CHAT intent → direct


def test_select_agent_by_task_profile_falls_back_when_unknown():
    """When primary_domain is unknown, falls back to intent-based selection."""
    cls = select_agent_by_task_profile("unknown_xyz", Intent.SHELL)
    assert cls is CodingAgent  # SHELL intent → coding (fallback)

    cls = select_agent_by_task_profile("not_in_map", Intent.WEB_FETCH)
    assert cls is ResearchAgent  # WEB_FETCH intent → research (fallback)


def test_select_agent_by_task_profile_primary_domain_wins_over_intent():
    """When primary_domain and intent disagree, primary_domain wins.

    Per ADR-8 Principle 1: "Classification by task type, not tool." The
    task type (primary_domain) is the routing key, not the intent.

    Example: a 'web_fetch' task type with a SHELL fallback intent should
    route to the ResearchAgent (because the task type says web_fetch),
    NOT the CodingAgent (which the SHELL intent would suggest).
    """
    cls = select_agent_by_task_profile("web_fetch", Intent.SHELL)
    assert cls is ResearchAgent, (
        "primary_domain='web_fetch' should select ResearchAgent even when "
        f"fallback intent is SHELL; got {cls.__name__ if cls else None}"
    )

    cls = select_agent_by_task_profile("shell_command", Intent.WEB_SEARCH)
    assert cls is CodingAgent, (
        "primary_domain='shell_command' should select CodingAgent even when "
        f"fallback intent is WEB_SEARCH; got {cls.__name__ if cls else None}"
    )


# ── Backward compat: select_agent (intent-based) still works ──────────────


def test_select_agent_intent_based_still_works():
    """The Phase 1-3 select_agent(intent) function still works (backward compat)."""
    assert select_agent(Intent.SHELL) is CodingAgent
    assert select_agent(Intent.WEB_SEARCH) is ResearchAgent
    assert select_agent(Intent.BROWSE) is BrowserAgent
    assert select_agent(Intent.CHAT) is DirectAgent


# ── Engine uses select_agent_by_task_profile (import inspection) ──────────


def test_parent_agent_replaces_engine_agent_selection():
    """The request runtime starts one LocalMind parent; specialized agent
    selection is now an internal delegation decision, not an engine branch."""
    from agents.parent import ParentAgent
    from core.engine import AgentRuntime, Engine

    assert Engine is AgentRuntime
    assert ParentAgent(adapter=None).config().name == "parent"


# ── _DOMAIN_TO_AGENT map covers all primary_domain values ─────────────────


def test_domain_to_agent_map_covers_known_task_types():
    """The _DOMAIN_TO_AGENT map covers the known task-type values so
    task-type selection (ADR-8 Phase 4) doesn't silently fall back to
    intent-based selection for them."""
    from agents.selection import _DOMAIN_TO_AGENT

    # Known task-type primary_domain values (fast-path task types + LLM
    # task types the runtime can settle on).
    known_domains = {
        "browse",
        "web_fetch",
        "file_analysis",
        "system_info",
        "shell_command",
    }
    for domain in known_domains:
        assert domain in _DOMAIN_TO_AGENT, (
            f"task-type domain {domain!r} not in "
            f"_DOMAIN_TO_AGENT map — agent selection will fall back to "
            f"intent-based (Phase 1-3 behavior) for this domain"
        )
