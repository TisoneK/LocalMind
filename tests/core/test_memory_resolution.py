"""
Tests for S427 — evidence-grounded memory writes.

The live failure (user transcript, 2026-09-06): "Remember the source for
EPL table" stored the literal phrase "source for EPL table" (confirmed
"Remembered: source for EPL table") while the URL the user meant sat in the
turn-1 context. The DB row proved it: content='source for EPL table'.

The contract locked here (user directive): memory must have EVIDENCE first,
understand what the user wants remembered, and distill it into a
self-contained fact — never store the user's raw words when those words
only name a referent.

Layers:
  1. `memory_intent.needs_resolution` — bare-referent classification
     (deterministic, free; self-contained writes keep the zero-LLM path).
  2. `memory_resolver.resolve_memory_fact` — the ONE bounded resolution
     call over the conversation evidence; None means "do not write".
  3. The runtime's memory-write branch — resolved content is what gets
     stored AND echoed in the confirmation; resolution failure asks the
     user instead of writing or fake-confirming.
  4. The conversational fast path injects recent memories so "What's it?"
     can resolve against what was actually remembered.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.memory_intent import MemoryType, classify_memory_intent

# Module-level: loads the core.engine ↔ agent_runtime import chain BEFORE any
# test imports core.agent_runtime directly (partial-init cycle, S426 lesson).
from core.trivial_input import (  # noqa: F401
    _render_conversational_memories,
    conversational_response,
)


class TestReferentialClassification:
    @pytest.mark.parametrize(
        "message,want",
        [
            # The live EPL failure — bare determiner + source referent.
            ("Remember the source for EPL table", True),
            # Longer tail of the same shape must not slip through.
            ("Remember the source for the Kenyan youth employment program", True),
            ("Remember the score", True),
            ("Remember it", True),
            ("Remember the login flow", True),
            # Self-contained: complete statements (S342's original cases).
            ("Remember that I prefer concise answers", False),
            ("Remember the sites that give a lot of information", False),
            ("Remember my birthday is May 5", False),
            ("Remember that the server is on port 5432", False),
            # Self-contained: concrete payloads.
            ("Remember this: https://wttr.in/{place}?format=j1", False),
            ("Save this: server 192.168.1.10 port 5432 admin", False),
        ],
    )
    def test_needs_resolution(self, message, want):
        intent = classify_memory_intent(message)
        assert intent.is_write
        assert intent.needs_resolution is want, (
            f"{message!r}: needs_resolution={intent.needs_resolution}, want {want} "
            f"(extracted content: {intent.content!r})"
        )

    def test_epl_write_still_tagged_source_knowledge(self):
        intent = classify_memory_intent("Remember the source for EPL table")
        assert intent.is_source_knowledge
        assert intent.memory_type == MemoryType.SOURCE_KNOWLEDGE


class TestResolveMemoryFact:
    def _adapter_returning(self, text: str) -> MagicMock:
        adapter = MagicMock()

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text=text, done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        adapter.chat = chat
        return adapter

    def _history(self) -> list[dict]:
        return [
            {"role": "user", "content": "Show me epl table"},
            {
                "role": "assistant",
                "content": "Here's the table. Source: "
                "https://www.skysports.com/premier-league-table",
            },
            {"role": "user", "content": "Remember the source for EPL table"},
        ]

    @pytest.mark.asyncio
    async def test_resolves_referent_from_evidence(self):
        from core.memory_resolver import resolve_memory_fact

        captured: dict = {}

        async def chat(messages, intent="chat", **kwargs):
            captured["messages"] = messages
            yield MagicMock(
                text="The user's preferred EPL standings source is "
                "https://www.skysports.com/premier-league-table",
                done=False,
                error=None,
            )
            yield MagicMock(text="", done=True, error=None)

        adapter = MagicMock()
        adapter.chat = chat
        fact = await resolve_memory_fact(adapter, self._history(), "source for EPL table")
        assert fact is not None
        assert "skysports.com" in fact
        # The evidence transcript must be in the prompt.
        transcript = captured["messages"][1]["content"]
        assert "skysports.com" in transcript
        assert "Remember the source for EPL table" in transcript

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        from core.memory_resolver import resolve_memory_fact

        adapter = self._adapter_returning("NOT_FOUND")
        fact = await resolve_memory_fact(adapter, self._history(), "the score")
        assert fact is None

    @pytest.mark.asyncio
    async def test_provider_error_returns_none(self):
        from core.memory_resolver import resolve_memory_fact

        adapter = MagicMock()

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="", done=False, error="bankofai returned 500")
            yield MagicMock(text="", done=True, error="bankofai returned 500")

        adapter.chat = chat
        fact = await resolve_memory_fact(adapter, self._history(), "the score")
        assert fact is None

    @pytest.mark.asyncio
    async def test_empty_output_returns_none(self):
        from core.memory_resolver import resolve_memory_fact

        adapter = self._adapter_returning("   ")
        assert await resolve_memory_fact(adapter, [], "the score") is None

    def test_parse_strips_wrapping_quotes(self):
        from core.memory_resolver import parse_resolved_fact

        assert parse_resolved_fact('"the sky sports table"') == "the sky sports table"

    def test_parse_truncates_long_facts(self):
        from core.memory_resolver import parse_resolved_fact

        fact = parse_resolved_fact("word " * 200)
        assert len(fact) <= 402  # 400 cap + ellipsis


class TestRuntimeMemoryWriteResolution:
    """The runtime branch: referential write resolves BEFORE storing, the
    confirmation echoes the RESOLVED fact, and resolution failure asks."""

    def _runtime(self, history_rows: list) -> MagicMock:
        """A runtime whose store returns the given history rows."""
        from core.agent_runtime import AgentRuntime

        rt = AgentRuntime()
        rt._last_observation = {}
        store = MagicMock()
        store.get_history.return_value = history_rows
        rt._store = store
        return rt

    def _history_rows(self) -> list:
        rows = []
        for role, content in [
            ("user", "Show me epl table"),
            ("assistant", "Source: https://www.skysports.com/premier-league-table"),
        ]:
            row = MagicMock()
            row.role.value = role
            row.content = content
            rows.append(row)
        return rows

    @pytest.mark.asyncio
    async def test_referential_write_stores_resolved_fact_and_echoes_it(self):
        from core.obs import ObsCollector

        adapter = MagicMock()

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(
                text="The user's EPL standings source is "
                "https://www.skysports.com/premier-league-table",
                done=False,
                error=None,
            )
            yield MagicMock(text="", done=True, error=None)

        adapter.chat = chat

        stored = {}

        def fake_memory_op(message, content=None, memory_type=None, operation=None):
            stored["content"] = content
            stored["type"] = memory_type
            result = MagicMock()
            result.success = True
            result.content = f"Remembered: *{content}*"
            return result

        rt = self._runtime(self._history_rows())
        with patch("core.engine.get_adapter", return_value=adapter), patch(
            "tools.memory_tool.memory_op", side_effect=fake_memory_op
        ):
            chunks = [
                c
                async for c in rt.process(
                    "Remember the source for EPL table",
                    "sess-s427-resolve",
                    obs=ObsCollector(),
                )
            ]

        # The RESOLVED fact was stored, not the echoed phrase.
        assert stored["content"] is not None
        assert "skysports.com" in stored["content"]
        assert stored["content"] != "source for EPL table"
        # The confirmation echoes the resolved content.
        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert "skysports.com" in text
        assert "Remembered" in text

    @pytest.mark.asyncio
    async def test_resolution_failure_asks_and_does_not_write(self):
        from core.obs import ObsCollector

        adapter = MagicMock()

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(text="NOT_FOUND", done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        adapter.chat = chat

        memory_op_calls = []

        def fake_memory_op(message, content=None, memory_type=None, operation=None):
            memory_op_calls.append(content)
            result = MagicMock()
            result.success = True
            result.content = "Remembered"
            return result

        rt = self._runtime(self._history_rows())
        with patch("core.engine.get_adapter", return_value=adapter), patch(
            "tools.memory_tool.memory_op", side_effect=fake_memory_op
        ):
            chunks = [
                c
                async for c in rt.process(
                    "Remember the score",
                    "sess-s427-notfound",
                    obs=ObsCollector(),
                )
            ]

        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        # No write, no fake confirmation — a clarifying question instead.
        assert memory_op_calls == []
        assert "Remembered" not in text
        assert "remember this correctly" in text.lower() or "concrete" in text.lower()


class TestConversationalMemoryInjection:
    @pytest.mark.asyncio
    async def test_memory_facts_rendered_into_conversational_prompt(self):

        captured = {}

        async def chat(messages, intent="chat", **kwargs):
            captured["system"] = messages[0]["content"]
            yield MagicMock(text="The Sky Sports table.", done=False, error=None)
            yield MagicMock(text="", done=True, error=None)

        adapter = MagicMock()
        adapter.chat = chat

        chunks = [
            c
            async for c in conversational_response(
                "What's it?",
                adapter,
                history=[{"role": "user", "content": "Remember the source for EPL table"}],
                memory_facts=[
                    "The user's EPL standings source is "
                    "https://www.skysports.com/premier-league-table"
                ],
            )
        ]
        assert "skysports.com" in captured["system"]
        assert "Things you remember" in captured["system"]
        text = "".join(getattr(c, "text", "") or "" for c in chunks)
        assert text

    def test_render_memories_empty_is_empty(self):

        assert _render_conversational_memories(None) == ""
        assert _render_conversational_memories([]) == ""
