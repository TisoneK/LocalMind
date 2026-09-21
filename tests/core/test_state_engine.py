"""The state-driven engine (experimental, beside the parent): search behavior with scripted stubs."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.state_engine import AgentState, EngineBudget, Evaluation, Goal, Move, Observation, StateEngine
from core.state_engine.catalog import DEFAULT_CATALOG, ToolSpec
from core.state_engine.executor import RegistryExecutor
from core.state_engine.llm import LLMEvaluator, LLMMoveProposer, parse_json

GOAL = Goal("find the project name")


def mv(tool="dir_explorer", **args):
    return Move(tool, args or {"path": "/x"}, "why")


class ScriptedProposer:
    """Returns the next scripted list of moves, minus anything in `avoid` (as the real one does)."""

    def __init__(self, *rounds):
        self.rounds, self.seen_avoid = list(rounds), []

    async def propose(self, state, n, avoid):
        self.seen_avoid.append(set(avoid))
        moves = self.rounds.pop(0) if self.rounds else []
        return [m for m in moves if m.fingerprint() not in avoid][:n]


class FakeExecutor:
    def __init__(self, results):  # {fingerprint-or-label: (ok, text)}
        self.results, self.ran = results, []

    async def run(self, move):
        self.ran.append(move.label())
        ok, text = self.results.get(move.label(), (True, "ok"))
        return Observation(move, ok, text)


class ScriptedEvaluator:
    def __init__(self, table):  # {label: Evaluation}
        self.table = table

    async def evaluate(self, state, outcomes):
        return [self.table.get(o.move.label(), Evaluation()) if o.ok else Evaluation() for o in outcomes]


async def collect(engine, goal=GOAL):
    return [e async for e in engine.run(goal)]


def engine(proposer, executor, evaluator, catalog=None, **budget):
    return StateEngine(
        None, catalog=catalog or DEFAULT_CATALOG, executor=executor, proposer=proposer,
        evaluator=evaluator, budget=EngineBudget(**budget) if budget else None,
    )


@pytest.mark.asyncio
async def test_one_step_done_returns_a_grounded_answer():
    a = mv(path="/a")
    ev = await collect(engine(ScriptedProposer([a]), FakeExecutor({}),
                              ScriptedEvaluator({a.label(): Evaluation(1.0, True, "LocalMind", "found")})))
    assert [e.kind for e in ev][-1] == "done" and ev[-1].data["answer"] == "LocalMind"


@pytest.mark.asyncio
async def test_no_progress_backtracks_and_never_repeats_a_failed_move():
    a, b, c = mv(path="/a"), mv(path="/b"), mv(path="/c")
    prop = ScriptedProposer([a], [b], [a, c])  # depth0: a (progress) ; depth1: b (stalls) ; back at depth0: a is now failed
    evalr = ScriptedEvaluator({
        a.label(): Evaluation(0.4), b.label(): Evaluation(0.1), c.label(): Evaluation(1.0, True, "ans"),
    })
    ev = await collect(engine(prop, FakeExecutor({}), evalr))
    kinds = [e.kind for e in ev]
    assert "backtrack" in kinds and kinds[-1] == "done"
    assert a.fingerprint() in prop.seen_avoid[-1]  # the move that led nowhere is remembered


@pytest.mark.asyncio
async def test_failed_probes_are_not_progress_and_the_stop_is_honest():
    a = mv(path="/nope")
    ev = await collect(engine(ScriptedProposer([a]), FakeExecutor({a.label(): (False, "not found")}),
                              ScriptedEvaluator({}), max_backtracks=0))
    assert ev[-1].kind == "stopped" and ev[-1].data["settled"] is False and ev[-1].data["reason"] == "no_progress"


@pytest.mark.asyncio
async def test_a_move_that_is_not_read_only_is_never_executed():
    cat = dict(DEFAULT_CATALOG)
    cat["file_write"] = ToolSpec("file_write", "write a file", "{}", read_only=False)
    w = Move("file_write", {"path": "/x", "content": "y"}, "create it")
    ex = FakeExecutor({})
    ev = await collect(engine(ScriptedProposer([w]), ex, ScriptedEvaluator({}), catalog=cat))
    assert ex.ran == []
    assert any(e.kind == "needs_confirmation" for e in ev)


@pytest.mark.asyncio
async def test_unknown_tools_are_dropped_and_remembered():
    ghost = Move("teleport", {}, "?")
    prop = ScriptedProposer([ghost])
    ev = await collect(engine(prop, FakeExecutor({}), ScriptedEvaluator({})))
    assert ev[-1].kind == "stopped" and ev[-1].data["reason"] == "no_moves"


@pytest.mark.asyncio
async def test_depth_budget_stops_honestly_with_what_is_known():
    rounds = [[mv(path=f"/{i}")] for i in range(10)]
    evalr = ScriptedEvaluator({m[0].label(): Evaluation(0.1 * (i + 1)) for i, m in enumerate(rounds)})
    ev = await collect(engine(ScriptedProposer(*rounds), FakeExecutor({}), evalr, max_depth=3))
    last = ev[-1]
    assert last.kind == "stopped" and last.data["reason"] == "budget" and len(last.data["facts"]) == 3


@pytest.mark.asyncio
async def test_unselected_probes_still_teach_facts():
    a, b = mv(path="/a"), mv(path="/b")
    ev = await collect(engine(ScriptedProposer([a, b]), FakeExecutor({b.label(): (True, "the name is Foo")}),
                              ScriptedEvaluator({a.label(): Evaluation(1.0, True, "x"), b.label(): Evaluation(0.5)})))
    assert ev[-1].kind == "done"
    st = next(e for e in reversed(ev) if e.kind == "state")
    assert st.data["facts"] == 2  # the winner's fact + the runner-up's real observation


def test_state_is_immutable_and_render_is_bounded():
    s0 = AgentState(GOAL)
    s1 = s0.apply(Observation(mv(), True, "x" * 5000), Evaluation(0.5))
    assert s0.depth == 0 and s1.depth == 1 and s0.facts == ()
    assert len(s1.render()) < 900 and s1.progress == 0.5
    assert mv(path="/a").fingerprint() == mv(path="/a").fingerprint() != mv(path="/b").fingerprint()


def test_parse_json_survives_fences_and_prose():
    assert parse_json('sure!\n```json\n{"moves": []}\n```') == {"moves": []}
    assert parse_json("no json here") is None


class _Adapter:
    def __init__(self, text):
        self.text = text

    async def chat(self, messages, temperature=0.2, intent="chat"):
        yield SimpleNamespace(text=self.text, error=None)


@pytest.mark.asyncio
async def test_llm_proposer_parses_dedupes_and_respects_avoid():
    a = mv(path="/a")
    text = ('{"moves": [{"tool": "dir_explorer", "args": {"path": "/a"}, "why": "1"},'
            ' {"tool": "dir_explorer", "args": {"path": "/a"}, "why": "dup"},'
            ' {"tool": "file_task", "args": {"path": "/b"}, "why": "2"}, "junk"]}')
    got = await LLMMoveProposer(_Adapter(text), DEFAULT_CATALOG).propose(AgentState(GOAL), 3, set())
    assert [m.tool for m in got] == ["dir_explorer", "file_task"]
    got = await LLMMoveProposer(_Adapter(text), DEFAULT_CATALOG).propose(AgentState(GOAL), 3, {a.fingerprint()})
    assert [m.tool for m in got] == ["file_task"]


@pytest.mark.asyncio
async def test_llm_evaluator_guards_failed_probes_and_answerless_done():
    ok, bad, noans = (Observation(mv(path=p), k, "t") for p, k in (("/a", True), ("/b", False), ("/c", True)))
    text = ('{"evals": [{"i": 0, "progress": 0.7, "done": true, "answer": "yes"},'
            ' {"i": 1, "progress": 0.9, "done": true, "answer": "lie"},'
            ' {"i": 2, "progress": 0.8, "done": true, "answer": ""}]}')
    e = await LLMEvaluator(_Adapter(text)).evaluate(AgentState(GOAL), [ok, bad, noans])
    assert (e[0].done, e[0].answer) == (True, "yes")
    assert (e[1].progress, e[1].done) == (0.0, False)  # a failed probe never counts, whatever the model says
    assert e[2].done is False  # "done" needs a grounded answer


@pytest.mark.asyncio
async def test_registry_executor_reports_unknown_tool_as_a_failed_observation():
    o = await RegistryExecutor().run(Move("teleport", {}, ""))
    assert o.ok is False and "unknown tool" in o.text


# ── The event contract a UI consumes (docs/prototypes/state-explorer) ───────


@pytest.mark.asyncio
async def test_events_carry_tree_ids_sequence_clock_and_excerpts():
    a, b = mv(path="/a"), mv(path="/b")
    prop = ScriptedProposer([a], [b])
    evalr = ScriptedEvaluator({a.label(): Evaluation(0.3), b.label(): Evaluation(1.0, True, "ok", "settled")})
    ev = await collect(engine(prop, FakeExecutor({a.label(): (True, "alpha  text")}), evalr))
    assert [e.seq for e in ev] == list(range(1, len(ev) + 1))
    assert all(ev[i].t_ms <= ev[i + 1].t_ms for i in range(len(ev) - 1))
    states = [e for e in ev if e.kind == "state"]
    assert [s.data["node"] for s in states] == ["n0", "n1", "n2"]
    assert [s.data["parent"] for s in states] == [None, "n0", "n1"]
    assert states[0].data["goal"] == GOAL.text
    probe = next(e for e in ev if e.kind == "probe")
    assert probe.data["excerpt"] == "alpha text" and probe.data["fp"] == a.fingerprint() and probe.data["at"] == "n0"
    cand = next(e for e in ev if e.kind == "candidates")
    assert cand.data["moves"][0]["fp"] == a.fingerprint() and "why" in cand.data["moves"][0]
    assert ev[0].to_dict()["kind"] == "state" and ev[-1].to_dict()["answer"] == "ok"


@pytest.mark.asyncio
async def test_backtrack_event_names_the_node_it_returns_to():
    a, b, c = mv(path="/a"), mv(path="/b"), mv(path="/c")
    prop = ScriptedProposer([a], [b], [c])
    evalr = ScriptedEvaluator({a.label(): Evaluation(0.4), b.label(): Evaluation(0.1), c.label(): Evaluation(1.0, True, "x")})
    ev = await collect(engine(prop, FakeExecutor({}), evalr))
    bt = next(e for e in ev if e.kind == "backtrack")
    assert bt.data["node"] == "n0"
    later = [e for e in ev if e.seq > bt.seq and e.kind == "candidates"]
    assert later and later[0].data["at"] == "n0"  # the next fan hangs off the node we returned to
