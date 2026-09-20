"""Tests for the parent-agent initialization decision contract."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from adapters.ollama import ToolCallResult
from agents.parent import ParentAgent
from core.agent.initialization import (
    InitializationDecision,
    build_initialization_prompt,
    parse_initialization,
)
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector


def test_parse_execute_decision_parses_plan_ignores_other_legacy_fields():
    """ADR-49 (revises ADR-38 for the todo checklist): the init now parses an
    ordered `plan` for execute mode → the live Todos panel. The OTHER legacy
    fields (tool_names/success_criteria, and the old `plan_steps` KEY) are still
    ignored — only `plan` is the sanctioned planning output."""
    decision = parse_initialization(
        '{"mode":"execute","acknowledgement":"I understand.",'
        '"objective":"Find the current weather",'
        '"tool_names":["web_search","web_fetch"],'
        '"plan":["Search Kitengela weather today","Fetch a reliable result"],'
        '"plan_steps":["legacy key must be ignored"],'
        '"success_criteria":["current source found"],"confidence":0.92}'
    )

    assert isinstance(decision, InitializationDecision)
    assert decision.mode == "execute"
    assert decision.objective == "Find the current weather"
    # `plan` IS parsed now  — the legacy `plan_steps` KEY is not.
    assert decision.plan_steps == ["Search Kitengela weather today", "Fetch a reliable result"]
    assert "legacy key must be ignored" not in decision.plan_steps
    assert not hasattr(decision, "tool_names")
    assert not hasattr(decision, "success_criteria")
    assert decision.objective_line() == "UNDERSTANDING: Find the current weather"


def test_parse_extracts_and_sanitizes_the_turn_title():
    """The classify call names the turn (a 2-4 word action phrase) → the Agent
    Workspace heading. It rides the existing init call (no extra model call).
    The parser trims quotes/trailing punctuation and bounds the length."""
    decision = parse_initialization(
        '{"mode":"execute","objective":"Find the current weather",'
        '"title":"  \\"Fetch Weather!\\"  ","confidence":0.9}'
    )
    assert decision.title == "Fetch Weather"

    # A model that omits the title yields "" → the UI falls back to "Turn N".
    assert parse_initialization('{"mode":"direct","response":"Hi."}').title == ""

    # An over-long title is bounded to a few words / 40 chars.
    long = parse_initialization(
        '{"mode":"execute","title":"Do a great many different things all at once now"}'
    ).title
    assert len(long) <= 40
    assert long.split(" ")[0] == "Do"


def test_parse_direct_decision_returns_complete_answer():
    decision = parse_initialization(
        '```json\n{"mode":"direct","acknowledgement":"Hi!",'
        '"response":"Hello from LocalMind.","confidence":0.99}\n```'
    )

    assert decision.is_direct
    assert decision.response == "Hello from LocalMind."


def test_parse_clarify_decision_requires_one_question():
    decision = parse_initialization(
        '{"mode":"clarify","acknowledgement":"I can do that.",'
        '"clarifying_question":"Which project should I use?"}'
    )

    assert decision.is_clarification
    assert decision.clarifying_question == "Which project should I use?"


def test_unparseable_output_resolves_to_direct_not_execute():
    # Execute is OPT-IN. An unparseable classify output must NOT
    # drag any model into the tool loop — a model that ignored the JSON
    # contract and just replied in prose has its prose shown as the answer.
    decision = parse_initialization("Hello! How can I help you today?")

    assert decision.mode == "direct"
    assert decision.response == "Hello! How can I help you today?"
    assert decision.raw == "Hello! How can I help you today?"


def test_unparseable_empty_output_gets_a_bounded_fallback_answer():
    # Truly empty/garbled output still resolves to a bounded direct answer,
    # never execute — the safe floor for any model on an unclear turn.
    decision = parse_initialization("")
    assert decision.mode == "direct"
    assert decision.response  # non-empty fallback, so the turn can complete

    garbled = parse_initialization('{"mode":"dir')  # malformed, no fields
    assert garbled.mode == "direct"
    assert garbled.response


def test_partial_json_response_is_salvaged_into_a_direct_answer():
    # A truncated JSON stream that still carries the response field: recover
    # the answer instead of discarding it into execute.
    decision = parse_initialization('{"mode":"direct","response":"Hi there, I\'m LocalMind.')
    assert decision.mode == "direct"
    assert decision.response == "Hi there, I'm LocalMind."


def test_missing_direct_response_stays_direct_with_fallback():
    # A `direct` with an empty response must still resolve to a bounded direct
    # answer (was: escalated to execute) — execute is opt-in.
    decision = parse_initialization('{"mode":"direct","response":""}')
    assert decision.mode == "direct"
    assert decision.response  # non-empty fallback


def test_unknown_mode_resolves_to_direct():
    decision = parse_initialization('{"mode":"banana","response":"Sure thing."}')
    assert decision.mode == "direct"
    assert decision.response == "Sure thing."


def test_clarify_without_question_resolves_to_direct():
    decision = parse_initialization('{"mode":"clarify","response":"","clarifying_question":""}')
    assert decision.mode == "direct"


def test_explicit_execute_is_still_honored():
    # The ONLY path to the tool loop: an explicit, parseable execute decision.
    decision = parse_initialization('{"mode":"execute","objective":"Find the largest file."}')
    assert decision.mode == "execute"
    assert decision.objective == "Find the largest file."


@pytest.mark.asyncio
async def test_parent_uses_initialization_for_direct_response_without_execution_call():
    class Adapter:
        def __init__(self):
            self.execution_calls = 0

        async def chat(self, messages, temperature=0.1, intent="chat"):
            yield StreamChunk(
                text=(
                    '{"mode":"direct","acknowledgement":"Hi!",'
                    '"response":"Hello from the parent agent."}'
                )
            )

        async def chat_with_tools(self, *args, **kwargs):
            self.execution_calls += 1
            raise AssertionError("direct initialization must not execute tools")

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    obs = ObsCollector()
    chunks = [
        chunk
        async for chunk in AgentLoop(adapter=adapter).run(
            messages=[{"role": "user", "content": "Hi"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            agent_config=config,
            allowed_tool_names=frozenset(),
            obs=obs,
        )
    ]

    assert "Hello from the parent agent." in "".join(chunk.text for chunk in chunks)
    assert adapter.execution_calls == 0
    assert sum(chunk.done for chunk in chunks) == 1
    timings = [event for event in obs.history() if event.type == "stage_timing"]
    assert any(event.data["stage"] == "agent_initialize" for event in timings)


@pytest.mark.asyncio
async def test_parent_initialization_precedes_tool_execution():
    class Adapter:
        def __init__(self):
            self.initialization_calls = 0
            self.execution_calls = 0

        async def chat(self, messages, temperature=0.1, intent="chat"):
            # The init call is the only plain-chat call at temperature=0.1;
            # the post-loop final-answer synthesis call (Session 147 rescue)
            # uses temperature=0.4 and must yield a real answer, not the
            # init JSON.
            if temperature == 0.1:
                self.initialization_calls += 1
                yield StreamChunk(
                    text=(
                        '{"mode":"execute","acknowledgement":"I will inspect it.",'
                        '"objective":"Run the requested command"}'
                    )
                )
                return
            yield StreamChunk(
                text="The command completed. The working directory is /workspace."
            )
            yield StreamChunk(text="", done=True)

        async def chat_with_tools(self, *args, **kwargs):
            self.execution_calls += 1
            if self.execution_calls == 1:
                return ToolCallResult(tool_name="shell", tool_args={"command": "pwd"})

            async def _answer():
                yield StreamChunk(text="The command completed.")
                yield StreamChunk(text="", done=True)

            return _answer()

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    with patch(
        "core.agent.loop.dispatch_with_retry",
        return_value=(ToolResult(content="/workspace", source="shell"), False, 0),
    ):
        chunks = [
            chunk
            async for chunk in AgentLoop(adapter=adapter).run(
                messages=[{"role": "user", "content": "run pwd"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[{"intent": "shell", "description": "Run a command"}],
                adapter=adapter,
                agent_config=config,
                allowed_tool_names=frozenset({"shell"}),
                obs=ObsCollector(),
            )
        ]

    assert adapter.initialization_calls == 1
    assert adapter.execution_calls >= 2
    assert "The command completed." in "".join(chunk.text for chunk in chunks)


@pytest.mark.asyncio
async def test_understanding_narrates_workspace_not_chat_thinking():
    """The classify "understanding" is INTERNAL: it narrates the Agent
    Workspace lifecycle (agent_initialization_understanding obs) and must NOT
    leak into the chat ThinkingBlock as a `thinking` StreamChunk."""

    class Adapter:
        async def chat(self, messages, temperature=0.1, intent="chat"):
            if temperature == 0.1:
                yield StreamChunk(
                    text=(
                        '{"mode":"execute","acknowledgement":"On it.",'
                        '"objective":"Read the config file","title":"Read Config"}'
                    )
                )
                return
            yield StreamChunk(text="Done reading the config.")
            yield StreamChunk(text="", done=True)

        async def chat_with_tools(self, *args, **kwargs):
            async def _answer():
                yield StreamChunk(text="Done.")
                yield StreamChunk(text="", done=True)

            return _answer()

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    obs = ObsCollector()
    with patch(
        "core.agent.loop.dispatch_with_retry",
        return_value=(ToolResult(content="ok", source="shell"), False, 0),
    ):
        chunks = [
            chunk
            async for chunk in AgentLoop(adapter=adapter).run(
                messages=[{"role": "user", "content": "read the config"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[{"intent": "shell", "description": "Run a command"}],
                adapter=adapter,
                agent_config=config,
                allowed_tool_names=frozenset({"shell"}),
                obs=obs,
            )
        ]

    # The workspace narration IS present (internal lifecycle phase).
    understanding_events = [
        e for e in obs.history() if e.type == "agent_initialization_understanding"
    ]
    assert understanding_events, "understanding should narrate the workspace"
    understanding_text = str(understanding_events[0].data.get("understanding", ""))
    assert understanding_text  # non-empty

    # It must NOT be streamed into the chat ThinkingBlock.
    thinking_blobs = [c.thinking for c in chunks if getattr(c, "thinking", None)]
    assert understanding_text not in thinking_blobs
    assert not any(understanding_text in (t or "") for t in thinking_blobs)


def test_initialization_prompt_is_classify_only():
    """Step 1: the init prompt classifies the tier only — tool
    names, plans, and upfront assessment fields are gone (they emerge
    mid-loop on gathered evidence)."""
    prompt = build_initialization_prompt(
        "What is the weather?",
        env_context="Current date: 2026-08-14",
    )

    assert "web_search" not in prompt
    assert "shell" not in prompt
    assert "plan_steps" not in prompt
    assert "facts" not in prompt
    assert "ambiguities" not in prompt
    assert 'mode": "direct|clarify|execute"' in prompt
    assert "intent classifier determined" not in prompt.lower()
    assert "Current date: 2026-08-14" in prompt


# ── B-2026-08-15-12 (c): only tier 3 (execute) may boot the workspace/loop ──
#
# direct and clarify (tiers 1-2) return immediately after the classify call
# (see loop.py's is_direct/is_clarification branches) — this pins that
# boundary as an obs-event regression so a future change can't silently let
# tiers 1-2 start paying for tool-loop work. `_LIFECYCLE_EVENT_TYPES` is the
# narration every turn emits regardless of tier; anything else means the
# tool loop actually ran.
_LIFECYCLE_EVENT_TYPES = frozenset({
    "agent_loop_start",
    "agent_initialization_start",
    "agent_initialization_ack",
    "agent_initialization_understanding",
    "agent_initialization_done",
    "stage_timing",
    "agent_loop_done",
})


def _workspace_or_loop_event_types(obs: ObsCollector) -> list[str]:
    return [e.type for e in obs.history() if e.type not in _LIFECYCLE_EVENT_TYPES]


@pytest.mark.asyncio
async def test_direct_mode_never_boots_the_workspace_or_loop():
    """Tier 1 (direct) must emit zero workspace/loop events — only the
    classify lifecycle narration."""

    class Adapter:
        async def chat(self, messages, temperature=0.1, intent="chat"):
            yield StreamChunk(text='{"mode":"direct","response":"Hi there!"}')

        async def chat_with_tools(self, *args, **kwargs):
            raise AssertionError("direct mode must never reach the tool loop")

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    obs = ObsCollector()
    chunks = [
        chunk
        async for chunk in AgentLoop(adapter=adapter).run(
            messages=[{"role": "user", "content": "hi"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            agent_config=config,
            allowed_tool_names=frozenset(),
            obs=obs,
        )
    ]

    assert "Hi there!" in "".join(chunk.text for chunk in chunks)
    assert _workspace_or_loop_event_types(obs) == []


@pytest.mark.asyncio
async def test_clarify_mode_never_boots_the_workspace_or_loop():
    """Tier 2 (clarify) must emit zero workspace/loop events — only the
    classify lifecycle narration."""

    class Adapter:
        async def chat(self, messages, temperature=0.1, intent="chat"):
            yield StreamChunk(
                text=(
                    '{"mode":"clarify","clarifying_question":'
                    '"Which file do you mean?"}'
                )
            )

        async def chat_with_tools(self, *args, **kwargs):
            raise AssertionError("clarify mode must never reach the tool loop")

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    obs = ObsCollector()
    chunks = [
        chunk
        async for chunk in AgentLoop(adapter=adapter).run(
            # A non-bare-verb message, so this exercises the classify LLM
            # call (via the mock adapter above) rather than the separate
            # deterministic pre-init pronoun/bare-verb clarify shortcut
            # (classify_pre_init) that a message like "fix it" would hit.
            messages=[{"role": "user", "content": "Should I use approach A or approach B here?"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            agent_config=config,
            allowed_tool_names=frozenset(),
            obs=obs,
        )
    ]

    assert "Which file do you mean?" in "".join(chunk.text for chunk in chunks)
    assert _workspace_or_loop_event_types(obs) == []


@pytest.mark.asyncio
async def test_execute_mode_does_boot_the_workspace_or_loop():
    """Positive control for the two tests above: tier 3 (execute) is the
    only tier allowed to emit workspace/loop events — proves the zero-event
    assertion above actually distinguishes tiers rather than being
    vacuously true (e.g. because ObsCollector never records anything)."""

    class Adapter:
        def __init__(self):
            self.execution_calls = 0

        async def chat(self, messages, temperature=0.1, intent="chat"):
            if temperature == 0.1:
                yield StreamChunk(
                    text='{"mode":"execute","objective":"Run the requested command"}'
                )
                return
            yield StreamChunk(text="The command completed.")
            yield StreamChunk(text="", done=True)

        async def chat_with_tools(self, *args, **kwargs):
            self.execution_calls += 1
            if self.execution_calls == 1:
                return ToolCallResult(tool_name="shell", tool_args={"command": "pwd"})

            async def _answer():
                yield StreamChunk(text="The command completed.")
                yield StreamChunk(text="", done=True)

            return _answer()

    adapter = Adapter()
    config = ParentAgent(adapter=None).config()
    obs = ObsCollector()
    with patch(
        "core.agent.loop.dispatch_with_retry",
        return_value=(ToolResult(content="/workspace", source="shell"), False, 0),
    ):
        [
            chunk
            async for chunk in AgentLoop(adapter=adapter).run(
                messages=[{"role": "user", "content": "run pwd"}],
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=[{"intent": "shell", "description": "Run a command"}],
                adapter=adapter,
                agent_config=config,
                allowed_tool_names=frozenset({"shell"}),
                obs=obs,
            )
        ]

    workspace_events = _workspace_or_loop_event_types(obs)
    assert workspace_events, "execute mode should boot the workspace/loop"
    assert "tool_call" in workspace_events


# ── the plan is whole before the first action runs ─────────────────────────


def test_prompt_asks_for_every_action_up_front_without_naming_tools():
    prompt = " ".join(build_initialization_prompt("What is the weather?", env_context="").split())
    assert "EVERY action" in prompt
    assert "Check the sources" in prompt
    assert "web_search" not in prompt and "shell" not in prompt


class TestEnsureUpfrontPlan:
    def test_a_real_plan_is_trusted(self):
        from core.agent.initialization import ensure_upfront_plan
        from core.models import Intent

        assert ensure_upfront_plan(["Find it", "Read it"], Intent.WEB_SEARCH) == ["Find it", "Read it"]

    def test_an_empty_plan_for_a_web_lookup_gets_the_lookup_steps(self):
        from core.agent.initialization import ensure_upfront_plan
        from core.agent.lookup_plan import LOOKUP_STEPS
        from core.models import Intent

        assert ensure_upfront_plan([], Intent.WEB_SEARCH) == list(LOOKUP_STEPS)

    def test_a_lone_step_is_kept_as_the_first_of_the_lookup(self):
        from core.agent.initialization import ensure_upfront_plan
        from core.agent.lookup_plan import LOOKUP_STEPS
        from core.models import Intent

        assert ensure_upfront_plan(["Fetch weather"], Intent.WEB_FETCH) == ["Fetch weather", *LOOKUP_STEPS[1:]]

    def test_other_work_is_left_alone(self):
        from core.agent.initialization import ensure_upfront_plan
        from core.models import Intent

        assert ensure_upfront_plan([], Intent.FILE_WRITE) == []
        assert ensure_upfront_plan(["Read the file"], Intent.FILE_TASK) == ["Read the file"]

    def test_blank_steps_are_dropped_and_the_plan_is_capped(self):
        from core.agent.initialization import ensure_upfront_plan

        many = [f"step {i}" for i in range(9)]
        assert ensure_upfront_plan(["", "  ", *many], "chat") == many[:6]
