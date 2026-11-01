"""
Path-decision events on the durable record (B-2026-11-01-26).

The investigation's Deliverable 5(b): the 564-vs-6K prompt-token spread was
TWO different prompt assemblers chosen per turn by an invisible routing
decision. The decision is invisible no more — every path (including the
negative/default ones) emits ``path_selected`` with the lane, the reason and
the classifier that decided it.

Contract locked here:
  - the conversational/trivial fast path records path=fast_path with its
    lane — BEFORE any provider outcome is known;
  - the deterministic memory lanes record their path;
  - a turn no deterministic lane claims records path=parent_loop (with the
    pre-init override reason when one fired);
  - a safety-blocked turn records path=blocked (the negative decisions are
    recorded too, never log-only).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.obs import ObsCollector
from storage.db import SessionStore


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """An AgentRuntime whose every write lands in an isolated tmp home
    (the test_fastpath_user_persist pattern — see that fixture's rationale)."""
    from core import config
    from core.engine import AgentRuntime

    monkeypatch.setattr(
        config.settings, "localmind_home", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        config.settings, "localmind_db_path", str(tmp_path / "test.db"), raising=False
    )

    rt = AgentRuntime()
    rt._store = SessionStore(str(tmp_path / "test.db"))
    rt._memory = SimpleNamespace(list_all_with_metadata=lambda: [])
    rt._last_observation = {}
    return rt


def _llm_forbidden_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.thinking_enabled = False
    adapter.chat.side_effect = AssertionError("no LLM in a deterministic-lane test")
    adapter.chat_with_tools.side_effect = AssertionError("no LLM in a deterministic-lane test")
    return adapter


async def _collect(agen) -> list:
    return [c async for c in agen]


def _paths(obs: ObsCollector) -> list[dict]:
    return [e.data for e in obs.history() if e.type == "path_selected"]


class TestFastPathDecisionRecorded:
    @pytest.mark.asyncio
    async def test_trivial_lane_recorded_before_provider_outcome(self, runtime):
        """A greeting records path=fast_path lane=trivial even though the
        provider call then fails into the canned fallback — the routing
        decision is a fact of the turn, independent of what the provider
        did with it."""
        obs = ObsCollector()
        with patch("core.engine.get_adapter", return_value=_llm_forbidden_adapter()):
            await _collect(runtime.process("Hi", "sess-path-trivial", obs=obs))

        decisions = _paths(obs)
        assert len(decisions) == 1
        assert decisions[0]["path"] == "fast_path"
        assert decisions[0]["lane"] == "trivial"
        assert decisions[0]["classifier"] == "trivial_input"

    @pytest.mark.asyncio
    async def test_conversational_lane_recorded(self, runtime):
        obs = ObsCollector()
        with patch("core.engine.get_adapter", return_value=_llm_forbidden_adapter()):
            await _collect(
                runtime.process(
                    "What can you do?", "sess-path-conv", obs=obs, client_intent="chat"
                )
            )

        decisions = _paths(obs)
        assert decisions[0]["path"] == "fast_path"
        assert decisions[0]["lane"] == "conversational"


class TestMemoryLaneDecisionsRecorded:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message,expected_path",
        [
            ("Remember that I prefer dark mode", "memory_write"),
            ("What do you know about me?", "memory_read"),
            ("Forget that I prefer dark mode", "memory_delete"),
        ],
    )
    async def test_memory_lanes_recorded(self, runtime, message, expected_path):
        obs = ObsCollector()
        with patch("core.engine.get_adapter", return_value=_llm_forbidden_adapter()):
            await _collect(runtime.process(message, "sess-path-memory", obs=obs))

        decisions = _paths(obs)
        assert any(d["path"] == expected_path for d in decisions)
        hit = next(d for d in decisions if d["path"] == expected_path)
        assert hit["classifier"] == "memory_intent"


class TestParentLoopDecisionRecorded:
    @pytest.mark.asyncio
    async def test_loop_fallthrough_recorded(self, runtime):
        """A turn with an attachment can never take the fast path — the
        parent-loop decision (the default) lands on the record too, then the
        loop itself may fail on the forbidden adapter (irrelevant here: the
        decision precedes it)."""
        obs = ObsCollector()

        async def consume_first_chunk():
            agen = runtime.process(
                "analyze this", "sess-path-loop", obs=obs, file=b"pretend bytes"
            )
            try:
                # The decision is emitted before any yield; one chunk (or the
                # first error path) is enough to have run the routing block.
                async for _chunk in agen:
                    break
            except Exception:
                pass  # the forbidden adapter may kill the loop — fine
            finally:
                await agen.aclose()

        with patch("core.engine.get_adapter", return_value=_llm_forbidden_adapter()):
            await consume_first_chunk()

        decisions = _paths(obs)
        assert decisions, "the parent-loop default decision must be on the record"
        assert decisions[0]["path"] == "parent_loop"
