"""ADR-19 task-aware context policy tests (Session 160).

Covers:
  1. policy_for() per-task tables + legacy no-op default.
  2. resolve_task_type() priority (explicit > domain hint > intent > phase).
  3. parse_task_type_from_plan fallbacks.
  4. The default policy reproduces legacy positional behavior (no keep,
     no drop) — wiring safety.
"""

from __future__ import annotations

import pytest
from core.context_policy import parse_task_type_from_plan, policy_for, resolve_task_type

# ── 1. policy_for ────────────────────────────────────────────────────────────


def test_default_policy_is_legacy_noop():
    """The default policy must NOT change current behavior: no keep markers,
    no drop markers, allow_drop False."""
    p = policy_for(None)
    assert p.task_type == "default"
    assert p.keep_markers == ()
    assert p.drop_markers == ()
    assert p.allow_drop is False


def test_policy_for_unknown_falls_back_to_default():
    assert policy_for("nonexistent-task").task_type == "default"
    assert policy_for("").task_type == "default"
    assert policy_for("  ").task_type == "default"


def test_policy_for_explicit_types():
    for t in ("debug", "plan", "code", "research", "chat", "verify"):
        assert policy_for(t).task_type == t


def test_debug_policy_keeps_error_markers():
    p = policy_for("debug")
    assert "traceback" in p.keep_markers
    assert "error:" in p.keep_markers
    assert "exit code" in p.keep_markers
    # Debug must never drop anything in P0.
    assert p.allow_drop is False


def test_plan_policy_keeps_decision_markers():
    p = policy_for("plan")
    assert "rejected" in p.keep_markers
    assert "must not" in p.keep_markers
    assert "decided" in p.keep_markers
    # Greedy bare tokens were dropped in review (match nearly everything).
    assert "must" not in p.keep_markers


def test_policy_allow_drop_off_for_all_p0_types():
    for t in TASK_TYPES_ALL:
        assert policy_for(t).allow_drop is False


TASK_TYPES_ALL = ("debug", "plan", "code", "research", "chat", "verify", "default")


def test_per_task_tables_are_distinct():
    """Locked decision: per-task KEEP tables — policies differ by task."""
    markers = {t: policy_for(t).keep_markers for t in TASK_TYPES_ALL}
    assert markers["debug"] != markers["plan"]
    assert markers["debug"] != markers["research"]
    assert markers["plan"] != markers["code"]


def test_policy_is_frozen_dataclass():
    p = policy_for("debug")
    with pytest.raises(FrozenInstanceError):
        p.keep_markers = ("x",)  # type: ignore[misc]


from dataclasses import FrozenInstanceError

# ── 2. resolve_task_type priority ────────────────────────────────────────────


def test_explicit_task_type_wins():
    assert resolve_task_type("debug", primary_domain="shell", phase="execute") == "debug"
    assert resolve_task_type("research", primary_domain="web_search") == "research"


def test_domain_hint_when_no_explicit():
    assert resolve_task_type("", primary_domain="shell") == "code"
    assert resolve_task_type("", primary_domain="web_search") == "research"
    assert resolve_task_type("", primary_domain="debug") == "debug"
    assert resolve_task_type("", primary_domain="diagnostics") == "debug"


def test_intent_fallback():
    assert resolve_task_type("", intent="WEB_SEARCH") == "research"
    assert resolve_task_type("", intent="SHELL") == "code"
    assert resolve_task_type("", intent="CODE_EXEC") == "code"


def test_chat_hint_corrected_on_non_chat_routing():
    # ADR-19 x ADR-22 re-key (Session 186): 'chat' is the no-tool fallback,
    # so a canonical 'chat' hint on a non-CHAT routing is a misclassification.
    # Corrected to the intent fallback when the caller KNOWS the routing.
    assert resolve_task_type("chat", intent="SHELL") == "code"
    assert resolve_task_type("chat", intent="WEB_SEARCH") == "research"
    # The dispatcher (no intent) keeps its emitted chat hint verbatim.
    assert resolve_task_type("chat") == "chat"
    # An actual CHAT routing keeps the chat hint.
    assert resolve_task_type("chat", intent="CHAT") == "chat"


def test_phase_fallback():
    assert resolve_task_type("", phase="verify") == "verify"
    assert resolve_task_type("", phase="plan") == "plan"
    assert resolve_task_type("", phase="execute") == ""
    assert resolve_task_type("", phase="final") == ""


def test_resolve_defaults_to_empty_for_legacy():
    assert resolve_task_type("") == ""
    assert resolve_task_type(None) == ""
    assert resolve_task_type("", intent="CHAT") == ""


def test_resolve_normalizes_case():
    assert resolve_task_type("DEBUG") == "debug"
    assert resolve_task_type("  Plan  ") == "plan"


# ── 3. parse_task_type_from_plan ─────────────────────────────────────────────


def test_parse_valid():
    assert parse_task_type_from_plan("debug") == "debug"
    assert parse_task_type_from_plan("code") == "code"


def test_parse_invalid_falls_back_to_domain():
    assert parse_task_type_from_plan("banana", primary_domain="shell") == "code"
    assert parse_task_type_from_plan("", primary_domain="web_search") == "research"


def test_parse_none_is_legacy():
    assert parse_task_type_from_plan(None) == ""
    assert parse_task_type_from_plan(42) == ""


# ── 4. Legacy dispatcher task_type parse tests removed ─────────────────────
# The ThinkingDispatcher was deleted (Session 239). task_type parsing is
# covered above by parse_task_type_from_plan; the agent loop settles
# task_type itself (see core.agent.loop task_type_settled event).
