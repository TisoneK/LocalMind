"""Tests for the context builder."""
from core.context_builder import _build_environment_context, _count_tokens, build
from core.models import (
    EngineContext,
    FileAttachment,
    Intent,
    Message,
    RiskLevel,
    Role,
    ToolResult,
)


def _make_ctx(**kwargs) -> EngineContext:
    defaults = {
        "session_id": "test-session",
        "message": "Hello",
        "intent": Intent.CHAT,
        "history": [],
    }
    defaults.update(kwargs)
    return EngineContext(**defaults)


def test_build_returns_list_of_dicts():
    ctx = _make_ctx()
    messages = build(ctx)
    assert isinstance(messages, list)
    assert all(isinstance(m, dict) for m in messages)


def test_system_message_always_first():
    ctx = _make_ctx()
    messages = build(ctx)
    assert messages[0]["role"] == "system"


def test_user_message_always_last():
    ctx = _make_ctx(message="Tell me something")
    messages = build(ctx)
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Tell me something"


def test_history_included():
    history = [
        Message(role=Role.USER, content="Hi"),
        Message(role=Role.ASSISTANT, content="Hello!"),
    ]
    ctx = _make_ctx(history=history, message="How are you?")
    messages = build(ctx)
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles


def test_tool_result_injected_as_tool_message():
    tool_result = ToolResult(content="Search result: Paris", risk=RiskLevel.LOW, source="web_search")
    ctx = _make_ctx(tool_result=tool_result)
    messages = build(ctx)
    # Tool results are now injected as "tool" role messages (not in system prompt)
    # This is the anti-fabrication fix — models attend more to tool-role content
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    all_content = " ".join(m.get("content", "") for m in tool_msgs)
    assert "Paris" in all_content


def test_file_attachment_chunks_injected():
    attachment = FileAttachment(
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=1000,
        chunks=["This is chunk one.", "This is chunk two."],
    )
    ctx = _make_ctx(file_attachment=attachment)
    messages = build(ctx)
    # File attachment is now a separate system message, not merged into the first
    all_content = " ".join(m.get("content", "") for m in messages)
    assert "chunk one" in all_content


def test_memory_facts_injected():
    ctx = _make_ctx(memory_facts=["User prefers Python", "User is based in Kenya"])
    messages = build(ctx)
    assert "Python" in messages[0]["content"]
    assert "Kenya" in messages[0]["content"]


def test_history_trimmed_on_budget():
    # Create a very small context window to force trimming
    long_history = [
        Message(role=Role.USER, content="A" * 500),
        Message(role=Role.ASSISTANT, content="B" * 500),
    ] * 10
    ctx = _make_ctx(history=long_history, message="New question")
    # 512 token window — most history should be trimmed
    messages = build(ctx, model_context_window=512)
    # Should still have system + at least the current user message
    assert messages[0]["role"] == "system"
    assert messages[-1]["content"] == "New question"


def test_knowledge_doc_loader_is_memoized(monkeypatch, tmp_path):
    """_load_knowledge_doc reads disk once, then serves from the memo cache."""
    from core import context_builder as cb

    calls = []
    real_read = cb.Path.read_text

    def counting_read(self, *a, **kw):
        calls.append(str(self))
        return real_read(self, *a, **kw)

    monkeypatch.setattr(cb.Path, "read_text", counting_read)
    cb._load_knowledge_doc.cache.clear()  # start cold

    cb._load_knowledge_doc()
    first_call_reads = len(calls)
    assert first_call_reads >= 1  # probed the candidate paths

    cb._load_knowledge_doc()
    cb._load_knowledge_doc()
    # Subsequent calls must be cache hits — no additional disk reads.
    assert len(calls) == first_call_reads


def test_count_tokens_basic():
    assert _count_tokens("hello world") > 0
    assert _count_tokens("") == 0


def test_compact_env_context_is_smaller_and_drops_tool_prose():
    """Session 289: the classify/init call uses a compact env — it must keep
    the essentials (date, OS, working dir) but drop the redundant tool prose
    and hardware lines so the init prompt stays lean on slow local models."""
    full = _build_environment_context()
    compact = _build_environment_context(compact=True)

    # Compact keeps the grounding essentials.
    assert "## Environment" in compact
    assert "Current date:" in compact
    assert "Working directory:" in compact

    # Compact drops the redundant tool catalog and hardware detail.
    assert "## Available Tools" not in compact
    assert "## Available Tools" in full
    assert "Python:" not in compact
    assert "CPU:" not in compact

    # And it is materially smaller.
    assert len(compact) < len(full) / 2


# ── Boot-path efficiency (bootup-telemetry session) ──────────────────────────


def test_full_env_context_skips_vectorstore_in_async_context():
    """In an async runtime the memory count is unusable, so the full env
    build must NOT construct VectorStore (which would open sqlite and fire
    a synchronous HTTP probe to Ollama on the event loop)."""
    from unittest.mock import patch

    import asyncio

    async def _run():
        with patch(
            "storage.vector.VectorStore",
            side_effect=AssertionError("VectorStore must not be constructed in async context"),
        ):
            from core.context_builder import _build_environment_context

            text = _build_environment_context()
        return text

    text = asyncio.run(_run())
    assert "## Environment" in text
    assert "Available Tools" in text


def test_full_env_context_still_counts_in_sync_context():
    """The sync (non-event-loop) path still constructs VectorStore and
    reports the memory count — the run_until_complete branch is intact."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from core.context_builder import _build_environment_context

    fake_store = MagicMock()
    fake_store._ready = True
    fake_store.count = AsyncMock(return_value=123)

    with patch("storage.vector.VectorStore", return_value=fake_store):
        text = _build_environment_context()

    assert "123 facts in memory" in text
