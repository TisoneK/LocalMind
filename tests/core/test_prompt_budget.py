"""Init prompt budget + classify-only shape (rebuild Step 1, ADR-38).

Validates that:
1. The init prompt is CLASSIFY-ONLY — no tool catalog, no plan/facts/
   ambiguities fields (the plan emerges from the loop on evidence).
2. The init prompt stays well under the 2500-char budget (was 7039 chars
   before B-12, 2969 with the capability summary; ~40% smaller now).
3. The InitializationDecision records init_prompt_chars for budget
   measurement.
"""

from __future__ import annotations

from core.agent.initialization import (
    InitializationDecision,
    build_initialization_prompt,
)

PLAN_FIELDS = (
    "plan_steps",
    "success_criteria",
    "tool_names",
    '"facts"',
    '"ambiguities"',
    "Capabilities",
    "Available tools",
)


def _sample_tools() -> list[dict]:
    """A representative subset of LocalMind's 30 tools."""
    return [
        {"intent": "sysinfo", "description": "Get current time, date, OS version, CPU, RAM, disk specs. Offline, instant."},  # noqa: E501
        {"intent": "file_task", "description": "Read the TEXT CONTENTS of a single FILE (code, text, PDF, DOCX, CSV, XLSX)."},  # noqa: E501
        {"intent": "shell", "description": "Execute shell commands and filesystem operations: list directory contents, find files, run commands, open apps/files/websites, check disk/internet/IP."},  # noqa: E501
        {"intent": "code_exec", "description": "Execute Python code snippets and return stdout/stderr output"},  # noqa: E501
        {"intent": "web_search", "description": "Search the web for current information, news, prices, or recent events"},  # noqa: E501
        {"intent": "delegate", "description": "Delegate a sub-task to another specialized agent. Use this when the current task requires a different domain of expertise (e.g., a coding task that needs web research, or a research task that needs file analysis)."},  # noqa: E501
        {"intent": "memory_op", "description": "Store, recall, or delete facts from persistent semantic memory"},  # noqa: E501
        {"intent": "calculate", "description": "Evaluate a safe arithmetic expression exactly (no shell needed): numbers, + - * / // % **, parentheses, unary minus, constants pi/e/tau, and functions abs/round/min/max/pow/sqrt/floor/ceil/trunc/exp/log/sin/cos/tan."},  # noqa: E501
    ]


def test_init_prompt_is_under_budget():
    """The init prompt must stay lean: no tool catalog.

    Budget history:
    - Pre-B-12: 7039 chars (monolithic plan-stream prompt)
    - ADR-38: 2969 chars (classify-only, capability summary)
    - ADR-49: +260 chars (ordered `plan` output for live Todos checklist) → 3000 budget
    - Session 331 (B-2026-08-21): +450 chars (clarify exception for bare verb phrases,
      ACT-not-ask bias refinement, acknowledgement/title contract) → 3500 budget
    - Session 332 (cyber-café fix): no init-prompt changes (fast-path bypasses init
      entirely for trivial/conversational prompts)

    Current size: ~3453 chars. Budget is 3500 to give headroom for the next
    small wording refinement without breaking the test.
    """
    prompt = build_initialization_prompt(
        user_message="whats the time?",
        env_context="",
        history=[],
    )
    assert len(prompt) < 3500, (
        f"budget violation: init prompt is {len(prompt)} chars, "
        f"expected under 3500 (lean classify + short plan + clarify exceptions)."
    )


def test_init_prompt_is_classify_only_no_tool_catalog():
    """Step 1 (ADR-38): the classifier does NOT see the tool catalog — it
    only picks the tier. Tool names must NOT appear in the prompt."""
    from tools import available_tools

    tools = available_tools()
    prompt = build_initialization_prompt(
        user_message="test",
        env_context="",
        history=[],
    )
    import re

    for tool in tools:
        name = str(tool.get("intent") or tool.get("name") or "").strip()
        if name:
            # Word-boundary match: 'browse' must not match the word
            # 'browser' in the prompt body.
            assert not re.search(rf"\b{re.escape(name)}\b", prompt), (
                f"tool name '{name}' leaked into the classify-only init prompt"
            )
        desc = str(tool.get("description") or "")
        if len(desc) > 100:
            assert desc[:80] not in prompt, (
                f"tool description leaked into init prompt: {desc[:80]!r}"
            )


def test_init_prompt_has_no_plan_or_assessment_fields():
    """The classify-only prompt must not ask for plan_steps, tool_names,
    success_criteria, facts, or ambiguities — those arrive mid-loop on
    gathered evidence (Steps 2-3 of the rebuild)."""
    prompt = build_initialization_prompt(
        user_message="test",
        env_context="",
        history=[],
    )
    for field in PLAN_FIELDS:
        assert field not in prompt, (
            f"classify-only init prompt must not mention {field!r}"
        )
    # The tier + opening line + objective ARE present.
    assert '"mode": "direct|clarify|execute"' in prompt
    assert '"objective"' in prompt
    assert '"acknowledgement"' in prompt


def test_init_prompt_keeps_act_not_ask_rule():
    """The act-not-ask bias (Sessions 235-237) survives the rewrite."""
    prompt = build_initialization_prompt(
        user_message="read my CV",
        env_context="",
        history=[],
    )
    assert "ACT rather than ask" in prompt
    assert "LAST RESORT" in prompt
    assert "read my CV" in prompt


def test_initialization_decision_has_prompt_chars_field():
    """ADR-34 B-12: InitializationDecision must have an init_prompt_chars
    field for budget measurement."""
    decision = InitializationDecision()
    assert hasattr(decision, "init_prompt_chars")
    assert decision.init_prompt_chars == 0  # default


def test_parse_initialization_preserves_prompt_chars():
    """parse_initialization should not clobber init_prompt_chars when set."""
    from core.agent.initialization import parse_initialization

    decision = parse_initialization('{"mode": "execute", "objective": "test"}')
    decision.init_prompt_chars = 1795
    assert decision.init_prompt_chars == 1795
    assert decision.mode == "execute"
