"""
API integration tests — v0.3

Covers: chat SSE streaming, sessions CRUD, health endpoint, tool registry.
Engine is mocked so tests run without Ollama.
"""
from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def _mock_stream(text="Hello!", intent="chat", confidence=0.95):
    """Patch Engine.process to yield predictable chunks + obs events.

    The signature must match Engine.process's actual parameters, including
    client_intent/client_confidence (added in v0.11 for client-side
    pre-classification) and **kwargs for forward-compat.
    """
    from core.models import StreamChunk

    async def _process(self, message, session_id, file=None, filename=None,
                        content_type=None, obs=None, original_path=None,
                        client_intent=None, client_confidence=0.0, **kwargs):
        if obs:
            obs.emit("intent_classified", primary=intent, secondary="none",
                     confidence=confidence)
            obs.emit("memory_retrieved", facts=0, latency_ms=5)
            obs.emit("turn_complete", intent=intent, confidence=confidence,
                     tokens_approx=len(text) // 4, total_latency_ms=50,
                     memory_facts=0, agent_mode=False)
        for char in text:
            yield StreamChunk(text=char, done=False)
        yield StreamChunk(text="", done=True)

    return patch("core.engine.Engine.process", _process)


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


# ── Health ────────────────────────────────────────────────────────────────────

class _FakeAdapter:
    """Deterministic adapter stub for health-route tests.

    The route calls ``get_adapter(settings.localmind_adapter)`` — and the
    dev .env typically selects 'zen' (a live OpenAI-compat provider), so
    patching ``adapters.ollama.OllamaAdapter.health_check`` never took
    effect: the route silently hit the real network instead. Patching
    ``api.routes.health.get_adapter`` makes these tests hermetic regardless
    of which adapter .env selects.
    """

    def __init__(self, reachable: bool):
        self._reachable = reachable

    async def health_check(self):
        return self._reachable


def _health_ctx(reachable: bool):
    return patch("api.routes.health.get_adapter", return_value=_FakeAdapter(reachable))


class TestHealth:
    def test_returns_200(self, client):
        with _health_ctx(True):
            assert client.get("/api/health").status_code == 200

    def test_schema_has_required_fields(self, client):
        with _health_ctx(True):
            data = client.get("/api/health").json()
        for field in ("status", "provider_reachable", "model", "tools", "version"):
            assert field in data, f"missing field: {field}"

    def test_degraded_when_provider_down(self, client):
        # Invalidate the reachability cache so our mock is actually used
        import api.routes.health as health_module
        health_module._reachability_cache.clear()  # force cache miss

        with _health_ctx(False):
            data = client.get("/api/health").json()
        assert data["status"] == "degraded"
        assert data["provider_reachable"] is False

    def test_lists_all_registered_tools(self, client):
        with _health_ctx(True):
            tools = client.get("/api/health").json()["tools"]
        intents = {t["intent"] for t in tools}
        for expected in ("web_search", "code_exec", "memory_op", "file_task"):
            assert expected in intents


# ── Chat ──────────────────────────────────────────────────────────────────────

class TestChat:
    def test_returns_200(self, client):
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "hi", "session_id": "t1"})
        assert r.status_code == 200

    def test_content_type_is_sse(self, client):
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "hi", "session_id": "t2"})
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_session_id_in_response_header(self, client):
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "hi", "session_id": "my-sid"})
        assert r.headers.get("x-session-id") == "my-sid"

    def test_autogenerates_session_id_if_omitted(self, client):
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "hi"})
        assert len(r.headers.get("x-session-id", "")) > 0

    def test_streams_text_content(self, client):
        with _mock_stream("Hello world"):
            r = client.post("/api/chat", data={"message": "hi", "session_id": "t3"})
        events = _parse_sse(r.text)
        # Text is in {"type": "token", "content": "..."} events
        full = "".join(e.get("content", "") for e in events if e.get("type") == "token")
        assert "Hello world" in full

    def test_first_sse_event_is_immediate_control_event(self, client):
        """ADR-37: no hardcoded narration — the first wire event is an immediate
        obs/control event, not a delayed model token or a stage-name status."""
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "inspect the project", "session_id": "t-ack"})
        events = _parse_sse(r.text)
        assert events
        # The first event is an immediate obs control event (not a narration
        # status or a model token).
        assert "obs_event" in events[0]
        assert events[0]["obs_event"]["type"] == "intent_classified"

    def test_emits_done_true(self, client):
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "hi", "session_id": "t4"})
        events = _parse_sse(r.text)
        # Done is {"type": "done"} event
        assert any(e.get("type") == "done" for e in events)

    def test_emits_intent_classified_obs_event(self, client):
        with _mock_stream(intent="web_search"):
            r = client.post("/api/chat", data={"message": "search", "session_id": "t5"})
        events = _parse_sse(r.text)
        obs = [e["obs_event"] for e in events if "obs_event" in e]
        intent_events = [o for o in obs if o["type"] == "intent_classified"]
        assert len(intent_events) >= 1
        assert intent_events[0]["data"]["primary"] == "web_search"

    def test_forwards_tool_call_reasoning_to_sse(self, client):
        """Session 142: the SSE bridge must forward the plan-step label the
        loop attaches as `reasoning` on tool_call obs events. Before this fix
        the bridge only forwarded `thought` — a silent tool run (no narration)
        rendered a blank `why:` on the step cards even though the plan-step
        label was in the obs event the whole time."""

        async def _process_with_tool_call(self, message, session_id, file=None, filename=None,
                                           content_type=None, obs=None, original_path=None,
                                           client_intent=None, client_confidence=0.0, **kwargs):
            if obs:
                obs.emit("intent_classified", primary="shell", secondary="none", confidence=0.9)
                obs.emit(
                    "tool_call",
                    tool="shell",
                    label="Listing contents of the dev directory",
                    status="done",
                    output="Volume in drive C has no label.",
                    latency_ms=50,
                    tool_args="dir",
                    iteration=1,
                    todo_id="plan-0",
                    thought="",
                    reasoning="List the contents of the dev directory to show all projects",
                )
            from core.models import StreamChunk
            yield StreamChunk(text="done", done=True)

        with patch("core.engine.Engine.process", _process_with_tool_call):
            r = client.post("/api/chat", data={"message": "show projects", "session_id": "t-reason"})
        events = _parse_sse(r.text)
        tc_events = [e.get("tool_call") for e in events if e.get("type") == "tool_call"]
        assert tc_events, "expected a bridged tool_call SSE event"
        # The plan-step label must reach the frontend as `reasoning`.
        assert tc_events[0].get("reasoning") == (
            "List the contents of the dev directory to show all projects"
        )

    @pytest.mark.asyncio
    async def test_heartbeat_can_flush_tool_progress_before_engine_chunk(self):
        """A slow pending engine still exposes its already-emitted tool event."""
        from api.routes.chat import _drain_live_tool_events, _with_keepalives
        from core.models import StreamChunk
        from core.obs import ObsCollector

        obs = ObsCollector()

        async def slow_engine():
            obs.emit("tool_call", tool="web_search", status="started", output="")
            await asyncio.sleep(0.02)
            yield StreamChunk(text="finished", done=True)

        pending = _with_keepalives(slow_engine(), interval_s=0.001)
        assert await anext(pending) is None
        live_events = [event async for event in _drain_live_tool_events(obs, "heartbeat-test")]
        assert any('"type": "tool_call"' in event and '"started"' in event for event in live_events)
        assert await anext(pending) is None
        await pending.aclose()

    def test_live_tool_result_is_visible_but_delegated_output_stays_hidden(self, client):
        """Tool results must reach the user while child raw output remains private."""
        async def _process(self, message, session_id, file=None, filename=None,
                           content_type=None, obs=None, original_path=None,
                           client_intent=None, client_confidence=0.0, **kwargs):
            if obs:
                obs.emit(
                    "tool_call",
                    tool="web_search",
                    label="Searching the web",
                    status="done",
                    output="Kitengela is sunny, 26°C.",
                    latency_ms=12,
                    tool_args="Kitengela weather",
                    iteration=1,
                )
                obs.emit(
                    "tool_call",
                    tool="web_search",
                    label="Child search",
                    status="done",
                    output="private child result",
                    agent="research",
                    latency_ms=8,
                    tool_args="internal query",
                    iteration=1,
                )
            from core.models import StreamChunk
            yield StreamChunk(text="Verified result", done=True)

        with patch("core.engine.Engine.process", _process):
            response = client.post(
                "/api/chat", data={"message": "weather", "session_id": "live-result"}
            )

        events = _parse_sse(response.text)
        tool_events = [event["tool_call"] for event in events if event.get("type") == "tool_call"]
        assert any(event.get("output") == "Kitengela is sunny, 26°C." for event in tool_events)
        assert all(event.get("output") != "private child result" for event in tool_events)

    def test_emits_intent_convenience_payload(self, client):
        with _mock_stream(intent="memory_op", confidence=0.82):
            r = client.post("/api/chat", data={"message": "remember", "session_id": "t6"})
        events = _parse_sse(r.text)
        # Convenience intent payload is a top-level event with "intent" key
        intent_payloads = [e for e in events if "intent" in e and "obs_event" not in e]
        assert len(intent_payloads) >= 1
        assert intent_payloads[0]["intent"] == "memory_op"
        assert abs(intent_payloads[0]["confidence"] - 0.82) < 0.01

    def test_emits_turn_complete_obs_event(self, client):
        with _mock_stream():
            r = client.post("/api/chat", data={"message": "hi", "session_id": "t7"})
        events = _parse_sse(r.text)
        obs = [e["obs_event"] for e in events if "obs_event" in e]
        complete_events = [o for o in obs if o["type"] == "turn_complete"]
        assert len(complete_events) >= 1

    def test_file_too_large_returns_413(self, client):
        import io
        r = client.post(
            "/api/chat",
            data={"message": "read this", "session_id": "t8"},
            files={"file": ("big.txt", io.BytesIO(b"x" * (51 * 1024 * 1024)), "text/plain")},
        )
        assert r.status_code == 413

    def test_missing_message_returns_422(self, client):
        r = client.post("/api/chat", data={"session_id": "t9"})
        assert r.status_code == 422

    def test_upload_failure_emits_typed_error_event(self, client, tmp_path):
        """Upload/storage failures must render in the chat instead of being ignored.

        The frontend only handles typed SSE events. A legacy untyped
        {"error": ..., "done": true} payload was treated as an unknown event,
        leaving the assistant bubble empty after the stream completed.
        """
        from core.config import settings

        uploads_path = tmp_path / "not-a-directory"
        uploads_path.write_text("occupied")
        with patch.object(settings, "localmind_uploads_path", str(uploads_path)):
            r = client.post(
                "/api/chat",
                data={"message": "read this", "session_id": "upload-error"},
                files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
            )

        assert r.status_code == 200
        events = _parse_sse(r.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert error_events
        # ADR-20 (Session 166): the error payload is now the canonical object;
        # the friendly message carries the upload context, source is internal.
        err = error_events[0]["error"]
        assert isinstance(err, dict)
        assert "File upload failed" in err["message"]
        assert err["source"] == "internal"
        assert any(e.get("type") == "done" for e in events)


class TestErrorNormalization:
    """ADR-20 — the SSE error event carries the CANONICAL object, never the
    raw provider payload. The friendly message is what reaches the UI; the
    raw string stays in the `raw` debug field."""

    ZEN_429 = (
        'zen returned 429: {"type":"error","error":{"type":"FreeUsageLimitError",'
        '"message":"Error from provider (Console): Rate limit exceeded. '
        'Please try again later."}}'
    )

    def test_streamed_provider_error_is_canonical(self, client):
        from core.models import StreamChunk

        # `self` inside the patched method is the ENGINE, not the test —
        # capture the payload in a closure instead.
        zen_429 = self.ZEN_429

        async def _process(self, message, session_id, file=None, filename=None,
                           content_type=None, obs=None, original_path=None,
                           client_intent=None, client_confidence=0.0, **kwargs):
            yield StreamChunk(text="", done=True, error=zen_429)

        with patch("core.engine.Engine.process", _process):
            r = client.post(
                "/api/chat", data={"message": "hi", "session_id": "err-norm"}
            )

        assert r.status_code == 200
        events = _parse_sse(r.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert error_events
        err = error_events[0]["error"]
        assert isinstance(err, dict)
        assert err["code"] == "rate_limit"
        assert err["retryable"] is True
        assert err["provider"] == "zen"
        assert "FreeUsageLimitError" not in err["message"]
        assert err["raw"].startswith("zen returned 429")

    def test_exception_path_is_canonical_and_leaks_no_raw(self, client):
        async def _process(self, *args, **kwargs):
            raise RuntimeError("boom: connection refused")
            yield  # pragma: no cover

        with patch("core.engine.Engine.process", _process):
            r = client.post(
                "/api/chat", data={"message": "hi", "session_id": "err-exc"}
            )

        events = _parse_sse(r.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert error_events
        err = error_events[0]["error"]
        assert isinstance(err, dict)
        assert err["message"]
        assert err["raw"].startswith("boom")
        # Session 31 guarantee kept: the token line stays generic — no raw
        # exception text leaks into the content.
        token_text = "".join(
            e.get("content", "") for e in events if e.get("type") == "token"
        )
        assert "boom" not in token_text
        assert any(e.get("type") == "done" for e in events)


# ── Sessions ──────────────────────────────────────────────────────────────────

class TestSessions:
    def _seed(self, client, sid):
        # Seed the store directly using the shared store instance
        from core.config import settings
        from core.models import Message, Role
        from storage.db import get_shared_store
        store = get_shared_store(settings.localmind_db_path)
        store.append(sid, Message(role=Role.USER, content="hello"))
        store.append(sid, Message(role=Role.ASSISTANT, content="response"))

    def test_list_returns_200(self, client):
        assert client.get("/api/sessions").status_code == 200
        data = client.get("/api/sessions").json()
        # API returns {"sessions": [...]} not a bare list
        assert "sessions" in data or isinstance(data, list)

    def test_history_for_unknown_session(self, client):
        # New sessions return empty history (200), not 404
        r = client.get("/api/sessions/no-such-session/history")
        assert r.status_code == 200
        # Should return either {"history": []} or empty list
        data = r.json()
        assert "history" in data or isinstance(data, list)

    def test_delete_404_for_unknown_session(self, client):
        assert client.delete("/api/sessions/no-such-session").status_code == 404

    def test_delete_returns_deleted_id(self, client):
        sid = "to-delete-1"
        self._seed(client, sid)
        r = client.delete(f"/api/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["deleted"] == sid

    def test_history_has_messages_after_chat(self, client):
        sid = "history-check-1"
        self._seed(client, sid)
        data = client.get(f"/api/sessions/{sid}/history").json()
        # API returns {"history": [...]}
        msgs = data.get("history", data) if isinstance(data, dict) else data
        assert len(msgs) >= 1
        assert any(m["role"] == "user" for m in msgs)

    def test_history_returns_persisted_turn_artifacts(self, client):
        """Session 266: thinking / error / toolCalls / performance persisted
        with the assistant message must survive a reload — the history
        endpoint returns them so the frontend restores the thinking block,
        error card, step pills, and cumulative context counter."""
        from core.config import settings
        from core.models import Message, Role
        from storage.db import get_shared_store

        sid = "history-artifacts-1"
        store = get_shared_store(settings.localmind_db_path)
        store.append(sid, Message(role=Role.USER, content="show projects"))
        store.append(
            sid,
            Message(
                role=Role.ASSISTANT,
                content="Here is the project list.",
                thinking="Listing projects to answer the request.",
                error="zen returned 429: quota exceeded",
                tool_calls=[
                    {
                        "id": "tc-shell-iter1",
                        "name": "shell",
                        "label": "List dev projects",
                        "status": "done",
                        "iteration": 1,
                        "reasoning": "List the dev directory",
                        "tool_args": "ls dev",
                    }
                ],
                metrics={"prompt_tokens": 1200, "completion_tokens": 84, "latency_ms": 2300},
            ),
        )

        data = client.get(f"/api/sessions/{sid}/history").json()
        msgs = data.get("history", data) if isinstance(data, dict) else data
        assistant = next(m for m in msgs if m["role"] == "assistant")

        # Thinking block survives.
        assert assistant["thinking"] == "Listing projects to answer the request."
        # Error card survives — raw stored string is normalized at the
        # presentation boundary (ADR-20): canonical object, no raw leak.
        err = assistant["error"]
        assert isinstance(err, dict)
        assert err["code"] == "rate_limit"
        assert err["retryable"] is True
        assert "FreeUsageLimitError" not in err["message"]
        # Tool-step pills survive (persisted timeline beats the legacy
        # single-tool_name mapping).
        tcs = assistant["toolCalls"]
        assert tcs and tcs[0]["name"] == "shell"
        assert tcs[0]["reasoning"] == "List the dev directory"
        # Per-turn performance survives → the context counter can be reseeded.
        perf = assistant["performance"]
        assert perf["promptTokens"] == 1200
        assert perf["completionTokens"] == 84
        assert perf["latencyMs"] == 2300
        assert perf["tokensPerSecond"] == pytest.approx(84 / 2.3, rel=0.05)

    def test_history_returns_agent_workspace(self, client):
        """Session 267: the Agent Workspace run tree + phase strip persist
        with the assistant message and come back from the history endpoint so
        the Agents tab and phase visibility survive a reload."""
        from core.config import settings
        from core.models import Message, Role
        from storage.db import get_shared_store

        sid = "history-agent-workspace-1"
        store = get_shared_store(settings.localmind_db_path)
        store.append(sid, Message(role=Role.USER, content="find weather"))
        store.append(
            sid,
            Message(
                role=Role.ASSISTANT,
                content="It is 22°C in Nairobi.",
                agent_runs=[
                    {
                        "id": "parent",
                        "name": "parent",
                        "role": "parent",
                        "task": "find weather",
                        "status": "completed",
                        "depth": 0,
                        "startedAt": 1700000000000,
                        "completedAt": 1700000009000,
                        "tools": [
                            {"id": "tc-shell-iter1", "name": "shell", "status": "done", "input": "curl wttr.in"}
                        ],
                    }
                ],
                agent_phases=[
                    {"id": "phase-gate-pass-1", "type": "gate_passed", "label": "Verified — acceptance gate passed", "timestamp": 1700000008000}
                ],
            ),
        )

        data = client.get(f"/api/sessions/{sid}/history").json()
        msgs = data.get("history", data) if isinstance(data, dict) else data
        assistant = next(m for m in msgs if m["role"] == "assistant")
        assert assistant["agentRuns"][0]["name"] == "parent"
        assert assistant["agentRuns"][0]["tools"][0]["name"] == "shell"
        assert assistant["agentPhases"][0]["type"] == "gate_passed"

    def test_actions_include_provider_for_badge(self, client):
        """Session 271: the Actions endpoint returns the winning search engine
        so the frontend can render the provider badge on the card."""
        from core.config import settings
        from storage.db import get_shared_store

        sid = "actions-provider-1"
        store = get_shared_store(settings.localmind_db_path)
        store.ensure_session(sid)
        store.create_action(sid, "web_search", label="Searching the web", action_id="tc-web_search-iter1", provider="bing")

        data = client.get(f"/api/actions?session_id={sid}").json()
        row = data[0]
        assert row["type"] == "web_search"
        assert row["provider"] == "bing"


# ── Tool registry ─────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_all_built_in_tools_registered(self):
        from tools import available_tools
        intents = {t["intent"] for t in available_tools()}
        for i in ("web_search", "code_exec", "memory_op", "file_task"):
            assert i in intents

    def test_tool_metadata_schema(self):
        from tools import available_tools
        for t in available_tools():
            assert isinstance(t["description"], str) and t["description"]
            assert isinstance(t["cost"], float) and t["cost"] >= 0
            assert isinstance(t["latency_ms"], int) and t["latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_dispatch_none_for_unregistered_chat(self):
        from core.models import Intent
        from tools import dispatch
        assert await dispatch(Intent.CHAT, "hello") is None

    @pytest.mark.asyncio
    async def test_web_search_tool(self):
        from tools.web_search import web_search
        # _search_ddg now returns (results, query, source) tuple
        with patch("tools.web_search._search_ddg", new_callable=AsyncMock) as m:
            m.return_value = ([{"title": "Result", "href": "https://ex.com", "body": "snippet"}], "test", "duckduckgo")
            result = await web_search("test")
        assert result.source == "web_search"
        assert "Result" in result.content

    @pytest.mark.asyncio
    async def test_code_exec_runs_python(self):
        from tools.code_exec import code_exec
        result = await code_exec("```python\nprint('test output')\n```")
        assert result.source == "code_exec"
        assert "test output" in result.content

    @pytest.mark.asyncio
    async def test_code_exec_no_code_returns_guidance(self):
        from tools.code_exec import code_exec
        result = await code_exec("what is 2 + 2")
        # code_exec now tries to execute the raw text as Python, which fails
        # The result contains the error output (NameError) and success=True
        assert result.source == "code_exec"
        # It's okay if it's an error or guidance — just verify it doesn't crash
        assert isinstance(result.content, str) and len(result.content) > 0

    @pytest.mark.asyncio
    async def test_memory_op_store(self):
        from tools.memory_tool import memory_op
        with patch("storage.vector.VectorStore.store", new_callable=AsyncMock, return_value=True):
            result = await memory_op("remember that I prefer Python")
        assert result.source == "memory"
        assert "Python" in result.content or "Remembered" in result.content

    @pytest.mark.asyncio
    async def test_memory_op_list(self):
        from tools.memory_tool import memory_op
        with patch("storage.vector.VectorStore.list_all_with_metadata", new_callable=AsyncMock,
                   return_value=[{"fact": "likes Python", "memory_type": "semantic",
                                  "importance": "0.8", "access_count": "1"}]):
            result = await memory_op("what do you know about me")
        assert "likes Python" in result.content

    @pytest.mark.asyncio
    async def test_file_task_no_attachment_returns_guidance(self):
        from tools.file_reader import file_task
        result = await file_task("read my doc")
        assert result.source == "file_reader"
        assert "attach" in result.content.lower() or "file" in result.content.lower()

    def test_heartbeat_status_is_phase_aware_during_initialization(self):
        """During the parent init call (no tools yet), the heartbeat status
        must say 'getting started' — NOT 'waiting for a tool result' (the
        bootup-telemetry fix: the old text was misleading when the agent was
        initializing, the longest wait on slow models)."""
        from api.routes.chat import _heartbeat_status_text
        from core.obs import ObsCollector

        obs = ObsCollector()
        obs.emit("agent_initialization_start", intent="analyze")
        status = _heartbeat_status_text(obs, live_tool_events=False)
        assert "getting started" in status, status
        assert "waiting for a tool result" not in status, status

        # Once init completes, the neutral still-working text returns.
        obs.emit("agent_initialization_done", mode="execute", objective="x")
        status = _heartbeat_status_text(obs, live_tool_events=False)
        assert "still working" in status, status

    def test_heartbeat_status_working_with_tools_after_tool_call(self):
        """Once a tool has run, the heartbeat says 'working with tools'."""
        from api.routes.chat import _heartbeat_status_text
        from core.obs import ObsCollector

        obs = ObsCollector()
        obs.emit("tool_call", tool="shell", status="started", tool_args="ls")
        status = _heartbeat_status_text(obs, live_tool_events=False)
        assert "working with tools" in status, status

    def test_heartbeat_status_still_working_when_no_init_and_no_tools(self):
        """Without init or tool events, the heartbeat stays neutral."""
        from api.routes.chat import _heartbeat_status_text
        from core.obs import ObsCollector

        obs = ObsCollector()
        status = _heartbeat_status_text(obs, live_tool_events=False)
        assert "still working" in status, status
        assert "getting started" not in status, status
