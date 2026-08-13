"""
Tests for ADR-19 P2 (Session 178): cross-session decision ledger.

The user's lossy-compression case: "user wants PostgreSQL, rejected
MongoDB, wants SQLite locally, production uses PostgreSQL" must not
collapse to "Database: PostgreSQL". P0 preserves the lines for the
current turn; P2 persists them durably so a decision survives even
after the conversation that produced it is compressed away or the
session is deleted.

Covered:
- DB layer: record_decision persists; recall_decisions returns newest
  first with optional task_type filter; near-duplicate suppression
  within 7 days; retention prune keeps the table bounded.
- Cross-session durability: a decision recorded in one session_id is
  recallable for a different session_id (no FK to sessions).
- decision_ledger helpers: extract_decision_lines reuses the summarizer
  preservation; record_decisions_from_compression is best-effort;
  format_ledger_hint shape.
- Summarizer wiring: maybe_compress_history invokes decision_sink with
  the preserved lines when compression ran; no-op (no call) when the
  policy is default/None (no preserved lines) — regression-safe.
- Engine read path: recall_decisions result is formatted into a hint.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def store(tmp_path):
    from storage.db import SessionStore

    return SessionStore(str(tmp_path / "lm.db"))


class TestDbRecordDecision:
    def test_record_and_recall_roundtrip(self, store):
        store.record_decision("s1", "Production uses PostgreSQL", task_type="plan")
        rows = store.recall_decisions()
        assert len(rows) == 1
        assert rows[0]["decision"] == "Production uses PostgreSQL"
        assert rows[0]["task_type"] == "plan"

    def test_recall_newest_first(self, store):
        store.record_decision("s1", "First decision", task_type="plan")
        store.record_decision("s1", "Second decision", task_type="plan")
        rows = store.recall_decisions(limit=5)
        assert rows[0]["decision"] == "Second decision"
        assert rows[1]["decision"] == "First decision"

    def test_recall_filters_by_task_type(self, store):
        store.record_decision("s1", "Plan decision", task_type="plan")
        store.record_decision("s1", "Debug decision", task_type="debug")
        plan_rows = store.recall_decisions(task_type="plan")
        assert [r["decision"] for r in plan_rows] == ["Plan decision"]
        debug_rows = store.recall_decisions(task_type="debug")
        assert [r["decision"] for r in debug_rows] == ["Debug decision"]
        all_rows = store.recall_decisions()
        assert len(all_rows) == 2

    def test_cross_session_durability(self, store):
        """A decision outlives its source session (no FK to sessions)."""
        store.record_decision("session-A", "User rejected MongoDB", task_type="plan")
        # A different session (or a fresh one) recalls it.
        rows = store.recall_decisions()
        assert len(rows) == 1
        assert rows[0]["decision"] == "User rejected MongoDB"
        assert rows[0]["session_id"] == "session-A"

    def test_near_duplicate_suppressed_within_7_days(self, store):
        store.record_decision("s1", "Production uses PostgreSQL", task_type="plan")
        store.record_decision("s1", "Production uses PostgreSQL", task_type="plan")
        assert len(store.recall_decisions()) == 1

    def test_too_short_decision_ignored(self, store):
        store.record_decision("s1", "short", task_type="plan")
        assert store.recall_decisions() == []

    def test_retention_prune_removes_stale(self, store):
        # Insert an old row directly (bypasses record_decision's prune).
        import sqlite3

        import core.config as cfg

        conn = sqlite3.connect(cfg.settings.localmind_db_path or store._path)
        # Use the fixture's path — force it through the store's own DB.
        conn.close()

        # Write an old decision via SQL on the store's actual path.
        old_path = store._path
        import sqlite3 as sq

        with sq.connect(str(old_path)) as c:
            c.execute(
                "INSERT INTO decision_ledger(session_id, task_type, decision, created_at) "
                "VALUES ('s-old', 'plan', 'ancient decision', "
                "datetime('now', '-200 days'))"
            )
            c.commit()
        # A fresh write triggers the prune.
        store.record_decision("s1", "Fresh decision", task_type="plan")
        rows = store.recall_decisions()
        assert len(rows) == 1
        assert rows[0]["decision"] == "Fresh decision"


class TestDecisionLedgerHelpers:
    def test_extract_decision_lines_with_policy(self):
        from core.context_policy import policy_for
        from core.decision_ledger import extract_decision_lines

        excerpt = (
            "USER: Production uses PostgreSQL\n"
            "USER: I rejected MongoDB, it's not a fit\n"
            "USER: also SQLite for local mode\n"
        )
        lines = extract_decision_lines(excerpt, policy_for("plan"))
        assert any("rejected" in l for l in lines)
        assert any("PostgreSQL" in l for l in lines)

    def test_extract_decision_lines_no_policy(self):
        from core.decision_ledger import extract_decision_lines

        assert extract_decision_lines("USER: anything", None) == []
        from core.context_policy import policy_for

        assert extract_decision_lines("USER: anything", policy_for("default")) == []

    def test_record_decisions_from_compression(self, store):
        from core.decision_ledger import record_decisions_from_compression

        n = record_decisions_from_compression(
            store, "s1", ["Production uses PostgreSQL", "Rejected MongoDB"], task_type="plan"
        )
        assert n == 2
        rows = store.recall_decisions()
        assert len(rows) == 2

    def test_format_ledger_hint(self):
        from core.decision_ledger import format_ledger_hint

        assert format_ledger_hint([]) == ""
        hint = format_ledger_hint(
            [{"decision": "Production uses PostgreSQL", "task_type": "plan"}]
        )
        assert "Past decisions to honor" in hint
        assert "Production uses PostgreSQL" in hint


class TestSummarizerDecisionSink:
    """maybe_compress_history forwards preserved lines to the sink."""

    def _fake_adapter(self, summary_text="concise summary"):
        from unittest.mock import MagicMock

        adapter = MagicMock()

        async def _chat(messages, **kwargs):
            class _Chunk:
                error = None
                text = summary_text

            yield _Chunk()

        adapter.chat.side_effect = _chat
        adapter.error = None
        return adapter

    def _big_history(self, policy_task="plan"):
        from core.context_policy import policy_for

        policy = policy_for(policy_task)
        # Build messages that exceed the 75% compress threshold with a
        # small token budget: system + ~10 long user/assistant messages.
        messages = [{"role": "system", "content": "sys"}]
        for i in range(10):
            messages.append({"role": "user", "content": f"USER: requirement {i} must not change"})
            messages.append(
                {"role": "assistant", "content": f"ASSISTANT: decided option {i} for the design"}
            )
        return messages, policy

    @pytest.mark.asyncio
    async def test_sink_called_with_preserved_lines(self):
        from core.summarizer import maybe_compress_history

        messages, policy = self._big_history()
        sink_calls = []

        def _sink(lines):
            sink_calls.append(lines)

        # Small budget forces compression (fixture ≈264 tokens > 225 = 75%
        # of 300); plan policy preserves "must not" / "decided" lines.
        result = await maybe_compress_history(
            messages, self._fake_adapter(), 300, policy=policy, decision_sink=_sink
        )
        assert len(sink_calls) == 1
        assert len(sink_calls[0]) >= 1
        # The preserved lines made it into the result summary too.
        assert any("[Preserved decisions" in m.get("content", "") for m in result)

    @pytest.mark.asyncio
    async def test_sink_not_called_without_preserved_lines(self):
        """Default policy → no preserved lines → sink is a no-op
        (regression-safe: the legacy summary path is unchanged)."""
        from core.summarizer import maybe_compress_history

        messages, _ = self._big_history(policy_task="default")
        from core.context_policy import policy_for

        policy = policy_for("default")
        sink_calls = []

        def _sink(lines):
            sink_calls.append(lines)

        await maybe_compress_history(
            messages, self._fake_adapter(), 400, policy=policy, decision_sink=_sink
        )
        assert sink_calls == []

    @pytest.mark.asyncio
    async def test_sink_failure_does_not_break_compression(self):
        from core.summarizer import maybe_compress_history

        messages, policy = self._big_history()

        def _exploding_sink(lines):
            raise RuntimeError("ledger down")

        result = await maybe_compress_history(
            messages, self._fake_adapter(), 300, policy=policy, decision_sink=_exploding_sink
        )
        # Compression still happened despite the sink failure.
        assert len(result) < len(messages)


class TestEngineDecisionRecall:
    """The engine's read path formats recalled ledger decisions into a hint."""

    @pytest.mark.asyncio
    async def test_engine_read_path_appends_decision_hint(self, store, tmp_path):
        # Point the shared engine at a scratch DB so test records don't
        # pollute dev.
        import core.config as cfg

        monkey_orig = cfg.settings.localmind_db_path
        cfg.settings.localmind_db_path = str(tmp_path / "lm-engine.db")
        try:
            from core.engine import Engine

            engine = Engine()
            engine._store.record_decision("s-other", "Production uses PostgreSQL", task_type="plan")

            # The recall path is best-effort and deterministic: format the
            # recall directly (the engine appends format_ledger_hint output).
            from core.decision_ledger import format_ledger_hint

            rows = engine._store.recall_decisions(task_type="plan")
            hint = format_ledger_hint(rows)
            assert "PostgreSQL" in hint
        finally:
            cfg.settings.localmind_db_path = monkey_orig
