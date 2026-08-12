"""ADR-18 P0 acceptance-gate wiring tests (Session 156).

Covers the four wiring points of the locked P0 design:
  1. The dispatcher parses typed success_criteria from execution_plan.
  2. The model's create_plan tool stores success_criteria on the scratchpad.
  3. is_coding_done() evaluates criteria against trace evidence (real gate).
  4. AgentLoop.run() calls is_done_fn at the iteration head and terminates
     CLEANLY (not via the hit-limit path) when the gate passes.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from core.agent.loop import AgentLoop
from core.agent.models import AgentStep, AgentTrace
from core.models import Intent, StreamChunk
from core.obs import ObsCollector

# ── 1. Dispatcher parses success_criteria ───────────────────────────────────

_CRITERIA_JSON = (
    '{"capabilities":["shell"],"flags":{"requires_grounding":false,'
    '"requires_tools":true,"requires_planning":true,"requires_memory":false,'
    '"requires_reasoning":false,"requires_execution":true,'
    '"requires_file_access":true,"realtime_sensitive":false},'
    '"execution_mode":"agent_loop","safety_level":"low","confidence":0.9,'
    '"primary_domain":"shell","reformulated_query":"create a hello world repo",'
    '"acknowledgement":"Setting that up...",'
    '"execution_plan":{"steps":[{"id":"s1","capability":"shell","tool":"shell",'
    '"args":{},"depends_on":[],"label":"Create hello.py"},'
    '{"id":"s2","capability":"shell","tool":"shell","args":{},"depends_on":["s1"],'
    '"label":"Run pytest"}],'
    '"success_criteria":["pytest passes","hello.py exists with content"]}}'
)


class CriteriaJSONAdapter:
    """Adapter yielding the capability JSON with success_criteria."""

    async def chat(self, messages, temperature=0.7, **kwargs):
        yield StreamChunk(text=_CRITERIA_JSON)


async def _dispatch(dispatcher, message="create a hello world repo"):
    from core.obs import ObsCollector

    plan = None
    async for item in dispatcher.dispatch(
        message=message,
        history=[],
        memory_facts=[],
        has_attachment=False,
        obs=ObsCollector(),
        session_id="test-session",
    ):
        plan = item
    return plan


@pytest.mark.asyncio
async def test_dispatcher_parses_success_criteria():
    from core import thinking_dispatcher as td

    dispatcher = td.ThinkingDispatcher(base_adapter=CriteriaJSONAdapter())
    plan = await _dispatch(dispatcher)
    assert plan is not None
    assert plan.success_criteria == ["pytest passes", "hello.py exists with content"]


@pytest.mark.asyncio
async def test_dispatcher_caps_and_filters_criteria():
    from core import thinking_dispatcher as td

    noisy = _CRITERIA_JSON.replace(
        '"success_criteria":["pytest passes","hello.py exists with content"]',
        '"success_criteria":["a","pytest passes","  ","hello.py exists with content",'
        '"tsc clean","git diff contains hello.py","build ok","one too many"]',
    )

    class NoisyAdapter:
        async def chat(self, messages, temperature=0.7, **kwargs):
            yield StreamChunk(text=noisy)

    dispatcher = td.ThinkingDispatcher(base_adapter=NoisyAdapter())
    plan = await _dispatch(dispatcher)
    assert plan is not None
    # Blanks dropped, single-char dropped, capped at 6.
    assert "pytest passes" in plan.success_criteria
    assert all(len(c) >= 2 for c in plan.success_criteria)
    assert len(plan.success_criteria) <= 6


# ── 2. create_plan tool stores success_criteria ─────────────────────────────


@pytest.mark.asyncio
async def test_create_plan_tool_stores_criteria():
    from core.subgoal import reset_subgoals
    from tools.subgoal import create_plan

    reset_subgoals()
    result = await create_plan(
        json.dumps(
            {
                "steps": ["create dir", "write hello.py"],
                "success_criteria": ["pytest passes", "hello.py exists with content"],
            }
        )
    )
    assert result.success is True
    from core.subgoal import get_registry

    registry = get_registry()
    assert registry.success_criteria == ["pytest passes", "hello.py exists with content"]
    assert "Success criteria" in result.content
    assert result.metadata["success_criteria"] == ["pytest passes", "hello.py exists with content"]
    reset_subgoals()


@pytest.mark.asyncio
async def test_create_plan_tool_parses_markdown_criteria():
    from core.subgoal import reset_subgoals
    from tools.subgoal import create_plan

    reset_subgoals()
    result = await create_plan(
        json.dumps({"steps": ["a"], "success_criteria": "1. pytest passes\n2. hello.py exists"})
    )
    from core.subgoal import get_registry

    assert get_registry().success_criteria == ["pytest passes", "hello.py exists"]
    assert result.success is True
    reset_subgoals()


def test_create_plan_tool_schema_exposes_criteria():
    from core.agent.loop import TOOL_DEFINITIONS

    plan_def = next(
        (
            tool
            for tool in TOOL_DEFINITIONS
            if tool.get("function", {}).get("name") == "create_plan"
        ),
        None,
    )
    assert plan_def is not None, "create_plan tool def missing from loop"
    props = plan_def["function"]["parameters"]["properties"]
    assert "success_criteria" in props, "create_plan schema must accept success_criteria"


# ── 3. is_coding_done — the real gate ───────────────────────────────────────


def _trace_with_steps(steps: list[AgentStep], criteria: list[str]) -> AgentTrace:
    trace = AgentTrace(success_criteria=criteria)
    trace.steps.extend(steps)
    return trace


def _shell_step(input_: str, observation: str, failed: bool = False) -> AgentStep:
    return AgentStep(
        iteration=1,
        thought="",
        tool_name="shell",
        tool_input=input_,
        observation=observation,
        tool_failed=failed,
    )


def test_is_coding_done_no_criteria_returns_false():
    from agents.coding.is_done import is_coding_done

    trace = AgentTrace()
    done, reason = is_coding_done(3, 10.0, None, trace)
    assert done is False
    assert reason == ""


def test_is_coding_done_all_criteria_met():
    from agents.coding.is_done import is_coding_done

    trace = _trace_with_steps(
        [
            _shell_step("pytest tests -q", "3 passed in 0.5s"),
            _shell_step("cat hello.py", "print('hello')"),
        ],
        criteria=["pytest passes", "hello.py exists with content"],
    )
    # hello.py referenced in evidence (cat observation quotes it).
    with patch("core.agent.verify.os.path.isfile", return_value=True):
        done, reason = is_coding_done(3, 10.0, None, trace)
    assert done is True
    assert "criteria met" in reason
    assert trace.gate_passed is True
    assert trace.gate_summary.startswith("✓ 2/2 criteria met")


def test_is_coding_done_unmet_criteria_continues():
    from agents.coding.is_done import is_coding_done

    trace = _trace_with_steps(
        [_shell_step("pytest tests -q", "1 failed, 2 passed")],
        criteria=["pytest passes"],
    )
    done, reason = is_coding_done(3, 10.0, None, trace)
    assert done is False
    assert "criteria not yet met" in reason
    assert trace.gate_passed is False


def test_is_coding_done_never_passes_before_any_tool_run():
    """Run-scoped evidence guard: a criterion satisfied by PRE-EXISTING
    workspace state (a file that already exists) must NOT pass the gate
    before this run executed any tool — the agent would never work."""
    from agents.coding.is_done import is_coding_done

    trace = _trace_with_steps([], criteria=["hello.py exists with content"])
    with patch("core.agent.verify.os.path.isfile", return_value=True):
        done, reason = is_coding_done(1, 1.0, None, trace)
    assert done is False
    assert reason == ""


# ── 4. AgentLoop gate wiring ────────────────────────────────────────────────


class _GateLoopAdapter:
    """Adapter that would stream an answer — the gate must preempt it."""

    def __init__(self):
        self.chat_with_tools_calls = 0

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None):
        self.chat_with_tools_calls += 1

        async def _stream():
            yield StreamChunk(text="", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def chat(self, messages, temperature=0.4, intent=None):
        return
        yield  # pragma: no cover


@pytest.mark.asyncio
async def test_loop_gate_passes_cleanly_and_preempts_model_call():
    loop = AgentLoop(adapter=MagicMock())
    obs = ObsCollector()
    adapter = _GateLoopAdapter()

    def always_done(iterations, wall_clock_secs, last_tool_result, trace):
        trace.gate_passed = True
        trace.gate_summary = "✓ 1/1 criteria met (pytest passes)"
        return True, trace.gate_summary

    chunks = []
    async for chunk in loop.run(
        messages=[{"role": "user", "content": "create hello repo"}],
        intent=Intent.SHELL,
        initial_tool_result=None,
        available_tools=[],
        adapter=adapter,
        success_criteria=["pytest passes"],
        is_done_fn=always_done,
        obs=obs,
    ):
        chunks.append(chunk)

    text = "".join(c.text for c in chunks)
    assert "criteria met" in text
    assert any(c.done for c in chunks)
    # The gate preempted the model call entirely — clean, not hit-limit.
    assert adapter.chat_with_tools_calls == 0
    events = [e.type for e in obs.history()]
    assert "agent_loop_gate_passed" in events
    assert "agent_loop_done" in events


@pytest.mark.asyncio
async def test_loop_seeds_trace_criteria_from_param():
    loop = AgentLoop(adapter=MagicMock())

    captured = {}

    def first_call_done(iterations, wall_clock_secs, last_tool_result, trace):
        captured["criteria"] = list(trace.success_criteria)
        captured["criteria_results"] = list(getattr(trace, "criteria_results", []))
        return True, "done"

    adapter = _GateLoopAdapter()
    async for _chunk in loop.run(
        messages=[{"role": "user", "content": "x"}],
        intent=Intent.CODE_EXEC,
        initial_tool_result=None,
        available_tools=[],
        adapter=adapter,
        success_criteria=["pytest passes", "tsc clean"],
        is_done_fn=first_call_done,
    ):
        pass
    assert captured["criteria"] == ["pytest passes", "tsc clean"]


# ── 5. Final-answer gate + explicit replan (Session 157) ─────────────────────


def _trace_with_tool_runs(tool_runs, criteria=None):
    """Build a trace whose steps match the passed tool_runs list.

    tool_runs: list of (tool_name, tool_input, observation)
    """
    trace = AgentTrace(success_criteria=criteria or [])
    for i, (name, inp, obs) in enumerate(tool_runs):
        trace.steps.append(
            AgentStep(
                iteration=i + 1,
                thought=f"step {i}",
                tool_name=name,
                tool_input=inp,
                observation=obs,
            )
        )
    return trace


class _ReplanAdapter:
    """Adapter capturing the replan LLM call and returning a revised plan."""

    def __init__(self, plan_text="1. re-run tests\n2. verify output"):
        self.plan_text = plan_text
        self.replan_calls = []

    async def chat(self, messages, temperature=0.1, intent=None):
        self.replan_calls.append(messages)
        yield StreamChunk(text=self.plan_text, done=False)
        yield StreamChunk(text="", done=True)

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None):
        raise AssertionError("gate replan must use chat(), not chat_with_tools()")
        yield  # pragma: no cover


async def _run_gate(loop, trace, *, iteration=0, max_iter=8, messages=None):
    """Invoke the final-answer gate directly with minimal wiring."""
    loop_messages = messages or [{"role": "user", "content": "create hello repo"}]
    return await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=iteration,
        effective_max_iter=max_iter,
        loop_messages=loop_messages,
        observation_log="$ pytest\n1 passed",
        active_adapter=_ReplanAdapter(),
        intent=Intent.SHELL,
        obs=None,
    )


@pytest.mark.asyncio
async def test_gate_all_criteria_met_appends_summary():
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace_with_tool_runs(
        [("shell", "pytest", "$ pytest\n1 passed")],
        criteria=["pytest passes"],
    )
    suffix, is_final = await _run_gate(loop, trace)
    assert is_final is True
    assert "✓" in suffix and "1/1" in suffix
    assert trace.gate_passed is True
    assert trace.gate_summary == suffix.strip()


@pytest.mark.asyncio
async def test_gate_unmet_with_iterations_replans_and_continues():
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace_with_tool_runs(
        [("shell", "pytest", "$ pytest\n1 passed")],
        criteria=["pytest passes", "tsc clean"],
    )
    adapter = _ReplanAdapter()
    loop_messages = [{"role": "user", "content": "build the app"}]
    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="$ pytest\n1 passed",
        active_adapter=adapter,
        intent=Intent.SHELL,
        obs=None,
    )
    assert is_final is False
    assert suffix == ""
    # The replan call happened (explicit LLM replan, locked decision 3).
    assert len(adapter.replan_calls) == 1
    replan_user = adapter.replan_calls[0][-1]["content"]
    assert "tsc clean" in replan_user
    # The revised plan is injected as a user block and the loop continues.
    injected = loop_messages[-1]
    assert injected["role"] == "user"
    assert "ACCEPTANCE GATE" in injected["content"]
    assert "Do NOT report done" in injected["content"]


@pytest.mark.asyncio
async def test_gate_unmet_at_cap_is_honest_final():
    """Strict + honest: at the iteration cap the answer MUST state what's
    unmet instead of letting the model's "done" claim stand."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace_with_tool_runs(
        [("shell", "pytest", "$ pytest\n1 passed")],
        criteria=["pytest passes", "tsc clean"],
    )
    adapter = _ReplanAdapter()
    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=7,  # last allowed iteration
        effective_max_iter=8,
        loop_messages=[],
        observation_log="$ pytest\n1 passed",
        active_adapter=adapter,
        intent=Intent.SHELL,
        obs=None,
    )
    assert is_final is True
    # Honest report: the unmet criterion is stated, no replan fired at cap.
    assert "tsc clean" in suffix
    assert adapter.replan_calls == []


@pytest.mark.asyncio
async def test_gate_no_criteria_legacy_path():
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace_with_tool_runs([("shell", "pytest", "$ pytest\n1 passed")])
    suffix, is_final = await _run_gate(loop, trace)
    assert is_final is True
    assert suffix == ""


@pytest.mark.asyncio
async def test_gate_skipped_before_any_tool_run():
    """Run-scoped evidence guard mirrors is_coding_done: a final answer
    with NO tool evidence cannot be gated (and cannot false-pass)."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace_with_tool_runs([], criteria=["hello.py exists with content"])
    suffix, is_final = await _run_gate(loop, trace)
    assert is_final is True
    assert suffix == ""
    assert trace.gate_passed is None


@pytest.mark.asyncio
async def test_replan_failure_falls_back_to_directive():
    """The replan call must NEVER break the loop: on failure the injected
    block carries a re-attempt directive and the gate continues (False)."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace_with_tool_runs(
        [("shell", "pytest", "$ pytest\n1 passed")],
        criteria=["pytest passes", "tsc clean"],
    )

    class _BrokenAdapter:
        async def chat(self, messages, temperature=0.1, intent=None):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    loop_messages = [{"role": "user", "content": "x"}]
    _suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="$ pytest\n1 passed",
        active_adapter=_BrokenAdapter(),
        intent=Intent.SHELL,
        obs=None,
    )
    assert is_final is False
    assert "Re-attempt the failed steps" in loop_messages[-1]["content"]


@pytest.mark.asyncio
async def test_loop_without_gate_fn_unchanged():
    """No is_done_fn → the legacy path (model streams the answer)."""
    loop = AgentLoop(adapter=MagicMock())

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None):
        async def _stream():
            yield StreamChunk(text="All good.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def plain_chat(messages, temperature=0.4, intent=None):
        return
        yield  # pragma: no cover

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = plain_chat

    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "hi"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
        ):
            chunks.append(chunk)

    text = "".join(c.text for c in chunks)
    assert "All good." in text
    assert any(c.done for c in chunks)
