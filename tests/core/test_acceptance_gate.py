"""ADR-18 P0 acceptance-gate wiring tests (Session 156).

Covers the four wiring points of the locked P0 design:
  1. The dispatcher parses typed success_criteria from execution_plan.
  2. The model's create_plan tool stores success_criteria on the scratchpad.
  3. is_coding_done() evaluates criteria against trace evidence (real gate).
  4. AgentLoop.run() calls is_done_fn at the iteration head and terminates
     CLEANLY (not via the hit-limit path) when the gate passes.

Session 173: 5. The ENGINE's direct AgentLoop path (agent selection
   disabled/failed — the common free-tier fallback) now passes
   is_done_fn=_default_acceptance_gate, so the Verify stage runs there
   too, not only via BaseAgent.run() on the ADR-8 selection path.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from core.agent.loop import AgentLoop
from core.agent.models import AgentStep, AgentTrace
from core.models import (
    ExecutionMode,
    Intent,
    OrchestrationPlan,
    StreamChunk,
    TaskProfile,
)
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


def test_shared_criteria_gate_speaks_the_agents_dialect():
    """Session 174: the shared criteria_gate drives both agents' is_done;
    the unmet_label keeps each agent's dialect without duplicating the
    gate logic."""
    from agents.coding.is_done import is_coding_done
    from agents.verifier.is_done import is_verifier_done

    # Same evidence, same criteria → both verify identically.
    trace_c = _trace_with_steps(
        [_shell_step("pytest tests -q", "3 passed in 0.5s")],
        criteria=["pytest passes"],
    )
    trace_v = _trace_with_steps(
        [_shell_step("pytest tests -q", "3 passed in 0.5s")],
        criteria=["pytest passes"],
    )
    done_c, _ = is_coding_done(3, 10.0, None, trace_c)
    done_v, _ = is_verifier_done(3, 10.0, None, trace_v)
    assert done_c is True
    assert done_v is True

    # Unmet → each reports in its own dialect.
    bad_c = _trace_with_steps(
        [_shell_step("pytest tests -q", "1 failed")],
        criteria=["pytest passes"],
    )
    bad_v = _trace_with_steps(
        [_shell_step("pytest tests -q", "1 failed")],
        criteria=["pytest passes"],
    )
    _, reason_c = is_coding_done(3, 10.0, None, bad_c)
    _, reason_v = is_verifier_done(3, 10.0, None, bad_v)
    assert "criteria not yet met" in reason_c
    assert "verification criteria not yet met" in reason_v
    assert reason_c != reason_v


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


# ── 6. Engine wiring (Session 173) ──────────────────────────────────────────
# The Verify stage was dead code on the engine's DIRECT loop path: both
# `self._agent_loop.run()` call sites passed success_criteria but never
# is_done_fn, so the acceptance gate only ran when agent selection (ADR-8
# Phase 4) succeeded. On free-tier models the dispatcher LLM frequently
# fails → fallback CHAT plan → select_agent_by_task_profile returns None →
# the direct loop path runs WITHOUT any verification: Act→Act→Act until
# the model asserts done or the iteration cap hits.


def test_default_acceptance_gate_delegates_to_is_coding_done():
    """The wired gate is is_coding_done (safe no-op without criteria,
    criteria-verified stop with evidence)."""
    from core.engine._pipeline import _default_acceptance_gate

    # No criteria → (False, "") — legacy loop termination unchanged.
    done, reason = _default_acceptance_gate(1, 1.0, None, AgentTrace())
    assert done is False
    assert reason == ""

    # Criteria + evidence → verified stop.
    trace = _trace_with_steps(
        [_shell_step("pytest tests -q", "3 passed in 0.5s")],
        criteria=["pytest passes"],
    )
    done, reason = _default_acceptance_gate(3, 10.0, None, trace)
    assert done is True
    assert "criteria met" in reason
    assert trace.gate_passed is True

    # Criteria, no tool evidence yet → keep going (run-scoped guard).
    trace2 = _trace_with_steps([], criteria=["hello.py exists with content"])
    with patch("core.agent.verify.os.path.isfile", return_value=True):
        done2, _ = _default_acceptance_gate(1, 1.0, None, trace2)
    assert done2 is False


class _CriteriaPlanDispatcher:
    """Dispatcher stub yielding an AGENT_LOOP plan with success_criteria
    (mirrors the real dispatcher's execution_plan contract)."""

    def __init__(self, adapter):
        self._adapter = adapter

    async def dispatch(self, **kwargs):
        yield OrchestrationPlan(
            profile=TaskProfile(
                capabilities=["shell"],
                execution_mode=ExecutionMode.AGENT_LOOP,
                confidence=0.9,
                reformulated="create hello world repo",
                acknowledgement="Setting that up...",
            ),
            success_criteria=["hello.py exists with content", "pytest passes"],
            fast_path=False,
            dispatch_steps=[{"intent": "shell", "detail": "Create hello.py"}],
        )


class _DirectPlanDispatcher:
    """Dispatcher stub returning a DIRECT (no-tools) plan immediately.
    Local copy — keeps the escalation test self-contained instead of
    importing from test_direct_escalation (cross-test-module coupling)."""

    def __init__(self, adapter):
        self._adapter = adapter

    async def dispatch(self, **kwargs):
        yield OrchestrationPlan(
            profile=TaskProfile(
                capabilities=[],
                execution_mode=ExecutionMode.DIRECT,
                confidence=0.5,
                reformulated=kwargs.get("message", ""),
            )
        )


_DSML = (
    "<｜DSML｜tool_calls>\n"
    '<｜DSML｜invoke name="shell">\n'
    '<｜DSML｜parameter name="command" string="true">ls -la</｜DSML｜parameter>\n'
    "</｜DSML｜invoke>\n"
    "</｜DSML｜tool_calls>"
)


def _make_dsml_adapter():
    """Adapter whose chat() emits DSML (then ends) — local copy."""
    mock_adapter = MagicMock()

    async def chat(messages, intent="chat", **kwargs):
        yield MagicMock(text=_DSML, done=False, error=None, usage={})
        yield MagicMock(text="", done=True, error=None, usage={})

    mock_adapter.chat = chat
    mock_adapter.effective_context_window = 8192
    return mock_adapter


def _engine_loop_recorder():
    """A fake `_agent_loop.run` that records kwargs and streams a reply."""
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        yield StreamChunk(text="Created hello.py", done=False, usage={})
        yield StreamChunk(text="", done=True, usage={})

    return captured, fake_run


@pytest.mark.asyncio
async def test_engine_direct_loop_wires_acceptance_gate():
    """The direct `self._agent_loop.run()` call (agent selection OFF) must
    pass is_done_fn — before Session 173 the Verify stage was dead there."""
    from core.engine import Engine
    from core.engine._pipeline import _default_acceptance_gate

    engine = Engine()
    obs = ObsCollector()
    mock_adapter = MagicMock()
    mock_adapter.effective_context_window = 8192

    captured, fake_run = _engine_loop_recorder()

    with patch("core.engine._pipeline.ThinkingDispatcher", _CriteriaPlanDispatcher), patch(
        "core.engine.get_adapter", return_value=mock_adapter
    ), patch("core.engine._pipeline.AGENT_SELECTION_ENABLED", False), patch.object(
        engine._agent_loop, "run", fake_run
    ):
        chunks = [
            c
            async for c in engine.process(
                "create hello world repo", "sess-engine-gate", obs=obs
            )
        ]

    # The direct loop got BOTH the contract AND the Verify stage.
    assert captured.get("success_criteria") == [
        "hello.py exists with content",
        "pytest passes",
    ]
    assert captured.get("is_done_fn") is _default_acceptance_gate

    # User-visible reply still streams normally.
    full_text = "".join(getattr(c, "text", "") or "" for c in chunks)
    assert "Created hello.py" in full_text
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_engine_escalate_path_wires_acceptance_gate():
    """The DSML-escalate loop call also passes the gate (consistency)."""
    from core.engine import Engine

    engine = Engine()
    obs = ObsCollector()
    mock_adapter = MagicMock()
    mock_adapter.effective_context_window = 8192

    captured, fake_run = _engine_loop_recorder()
    # The escalate path is reached when a DIRECT stream emits DSML. Use the
    # local DSML adapter + real detection (no patching of the detector).
    dsml_adapter = _make_dsml_adapter()

    with patch("core.engine._pipeline.ThinkingDispatcher", _DirectPlanDispatcher), patch(
        "core.engine.get_adapter", return_value=dsml_adapter
    ), patch.object(engine._agent_loop, "run", fake_run):
        chunks = [
            c
            async for c in engine.process(
                "create hello world repo", "sess-engine-esc-gate", obs=obs
            )
        ]

    from core.engine._pipeline import _default_acceptance_gate

    assert captured.get("is_done_fn") is _default_acceptance_gate
    assert any(getattr(c, "done", False) for c in chunks)


# ── 7. ADR-18 P1 — Verifier as a stage (Session 174) ───────────────────────
# P1 promotes VerifierAgent from an intent-routing destination to the
# acceptance stage for high-stakes intents (file write/edit, code exec):
#  (a) real is_verifier_done (criteria-verified, same verify.py checkers)
#  (b) intent-aware gate selection in the engine (_acceptance_gate_for)
#  (c) the SINGLE_TOOL fast path records its initial tool result as a
#      trace.step, so criteria on fast-path plans (dir listing, git,
#      URL fetch) can finally verify (Session 173 follow-up).


def test_is_verifier_done_real_implementation():
    """The verifier stub is gone: criteria + evidence → verified stop;
    no criteria / no evidence → keep going (legacy)."""
    from agents.verifier.is_done import is_verifier_done

    # No criteria → (False, "") — legacy termination unchanged.
    done, reason = is_verifier_done(3, 10.0, None, AgentTrace())
    assert done is False
    assert reason == ""

    # Criteria + evidence → verified stop, honest summary on the trace.
    trace = _trace_with_steps(
        [_shell_step("pytest tests -q", "3 passed in 0.5s")],
        criteria=["pytest passes"],
    )
    done, reason = is_verifier_done(3, 10.0, None, trace)
    assert done is True
    assert "criteria met" in reason
    assert trace.gate_passed is True
    assert trace.gate_summary.startswith("✓ 1/1 criteria met")

    # Criteria but unmet → continue with a verifier-flavored reason.
    trace2 = _trace_with_steps(
        [_shell_step("pytest tests -q", "1 failed, 2 passed")],
        criteria=["pytest passes"],
    )
    done2, reason2 = is_verifier_done(3, 10.0, None, trace2)
    assert done2 is False
    assert "verification criteria not yet met" in reason2
    assert trace2.gate_passed is False

    # Run-scoped evidence guard: no tool run this turn → never passes.
    trace3 = _trace_with_steps([], criteria=["hello.py exists with content"])
    with patch("core.agent.verify.os.path.isfile", return_value=True):
        done3, _ = is_verifier_done(1, 1.0, None, trace3)
    assert done3 is False


def test_acceptance_gate_for_selects_verifier_for_high_stakes():
    """FILE_WRITE/FILE_EDIT/CODE_EXEC gate on the verifier; others on the
    coding gate. Both are safe no-ops without criteria."""
    from core.engine._pipeline import (
        _acceptance_gate_for,
        _default_acceptance_gate,
    )

    verifier_gate = _acceptance_gate_for(Intent.FILE_WRITE)
    assert verifier_gate is not _default_acceptance_gate
    # It behaves like the verifier (delegates to is_verifier_done).
    trace = _trace_with_steps(
        [_shell_step("pytest tests -q", "3 passed in 0.5s")],
        criteria=["pytest passes"],
    )
    done, _ = verifier_gate(3, 10.0, None, trace)
    assert done is True

    assert _acceptance_gate_for(Intent.FILE_EDIT) is not _default_acceptance_gate
    assert _acceptance_gate_for(Intent.CODE_EXEC) is not _default_acceptance_gate
    # Non-high-stakes intents keep the coding gate.
    assert _acceptance_gate_for(Intent.SHELL) is _default_acceptance_gate
    assert _acceptance_gate_for(Intent.WEB_SEARCH) is _default_acceptance_gate
    assert _acceptance_gate_for(Intent.CHAT) is _default_acceptance_gate


@pytest.mark.asyncio
async def test_engine_wires_verifier_gate_for_high_stakes_intent():
    """A FILE_WRITE plan (agent selection OFF) must pass the VERIFIER gate
    on the direct loop — high-stakes work gets the acceptance stage."""
    from core.engine import Engine

    engine = Engine()
    obs = ObsCollector()
    mock_adapter = MagicMock()
    mock_adapter.effective_context_window = 8192
    captured, fake_run = _engine_loop_recorder()

    class _FileWriteDispatcher:
        def __init__(self, adapter):
            self._adapter = adapter

        async def dispatch(self, **kwargs):
            yield OrchestrationPlan(
                profile=TaskProfile(
                    capabilities=["file_write"],
                    execution_mode=ExecutionMode.AGENT_LOOP,
                    confidence=0.9,
                    reformulated="write hello.py",
                    acknowledgement="Writing that for you...",
                ),
                success_criteria=["hello.py exists with content"],
                fast_path=False,
                dispatch_steps=[{"intent": "file_write", "detail": "Write hello.py"}],
            )

    with patch("core.engine._pipeline.ThinkingDispatcher", _FileWriteDispatcher), patch(
        "core.engine.get_adapter", return_value=mock_adapter
    ), patch("core.engine._pipeline.AGENT_SELECTION_ENABLED", False), patch.object(
        engine._agent_loop, "run", fake_run
    ):
        chunks = [
            c
            async for c in engine.process("write hello.py", "sess-engine-verifier-gate", obs=obs)
        ]

    from core.engine._pipeline import _acceptance_gate_for, _default_acceptance_gate

    assert captured.get("success_criteria") == ["hello.py exists with content"]
    assert captured.get("is_done_fn") is not _default_acceptance_gate
    assert captured.get("is_done_fn") is _acceptance_gate_for(Intent.FILE_WRITE)
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_initial_tool_result_becomes_trace_evidence():
    """SINGLE_TOOL fast path: the engine pre-dispatched tool result must
    land as a trace.step so criteria can verify (Session 173 follow-up —
    this is the piece that makes 'list projects in dev' verify)."""
    from core.agent.loop import AgentLoop
    from core.models import ToolResult

    loop = AgentLoop(adapter=MagicMock())
    captured = {}
    adapter = _GateLoopAdapter()

    def first_call_done(iterations, wall_clock_secs, last_tool_result, trace):
        captured["tool_names"] = [s.tool_name for s in trace.steps]
        captured["observations"] = [s.observation for s in trace.steps]
        return False, ""

    initial = ToolResult(
        content="Listing contents of dev:\n  frontend\n  backend\n  docs",
        source="shell",
        success=True,
    )
    async for _chunk in loop.run(
        messages=[{"role": "user", "content": "list projects in dev"}],
        intent=Intent.SHELL,
        initial_tool_result=initial,
        available_tools=[],
        adapter=adapter,
        success_criteria=["the listing for dev was shown"],
        is_done_fn=first_call_done,
    ):
        pass

    # The initial dispatch is recorded as run-scoped evidence.
    assert captured["tool_names"] == ["shell"]
    assert "Listing contents of dev" in captured["observations"][0]


@pytest.mark.asyncio
async def test_fast_path_criteria_verify_via_initial_tool_step():
    """With the initial tool result recorded as a step, the acceptance
    gate can verify a fast-path criterion end-to-end: 'dev folder
    contents listed' passes once the shell listing is evidence."""
    from core.agent.loop import AgentLoop
    from core.models import ToolResult

    loop = AgentLoop(adapter=MagicMock())

    # Use the real gate as is_done_fn — it must see the initial-tool step
    # as evidence and terminate cleanly on the first iteration head.
    from core.engine._pipeline import _default_acceptance_gate

    initial = ToolResult(
        content="Listing contents of dev:\n  frontend\n  backend\n  docs",
        source="shell",
        success=True,
    )
    chunks = []
    async for chunk in loop.run(
        messages=[{"role": "user", "content": "list projects in dev"}],
        intent=Intent.SHELL,
        initial_tool_result=initial,
        available_tools=[],
        adapter=_GateLoopAdapter(),
        success_criteria=["the listing for dev was shown"],
        is_done_fn=_default_acceptance_gate,
    ):
        chunks.append(chunk)

    text = "".join(c.text for c in chunks)
    assert "criteria met" in text
    assert any(c.done for c in chunks)
