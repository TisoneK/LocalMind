"""
Tests for B-2026-08-02-4 (A4) — deterministic tool-result simplification.

`simplify_tool_results()` stubs OLD tool-role results (head + omission
marker + tail) while preserving the newest few verbatim, so the agent
loop's conversation window stays in budget without an LLM call. Unlike
`maybe_compress_history` (LLM turn summarization past 75% budget), this
is a synchronous, idempotent, structure-preserving pass.

Locks in:
    - The newest `keep_last` tool results are preserved verbatim
    - Older oversized tool results are stubbed (head + marker + tail)
    - Every `tool_call_id` is preserved (OpenAI tool-calling protocol
      validity — every tool_calls id keeps its matching tool response)
    - Small old results are left alone (no needless stubbing)
    - Idempotent — a second pass does not re-stub or mutate further
    - Non-tool messages are never touched
"""

from __future__ import annotations

from core.context_compactor import simplify_tool_results


def _tool_msg(content: str, call_id: str = "call_1") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _user_msg(content: str) -> dict:
    return {"role": "user", "content": content}


class TestSimplifyToolResults:
    def test_preserves_newest_results_verbatim(self):
        big = "x" * 5_000
        messages = [
            _user_msg("do the work"),
            _tool_msg(big, "call_1"),
            _tool_msg(big, "call_2"),
            _tool_msg(big, "call_3"),
            _tool_msg(big, "call_4"),
            _tool_msg("final result", "call_5"),
        ]
        out = simplify_tool_results(messages, keep_last=2)

        # The last two tool results are untouched.
        assert out[-2]["content"] == big
        assert out[-1]["content"] == "final result"
        # The first three got stubbed.
        for i in (1, 2, 3):
            assert "truncated for length" in out[i]["content"]
            assert out[i]["tool_call_id"] == f"call_{i}"

    def test_preserves_tool_call_id_on_stub(self):
        messages = [
            _user_msg("go"),
            _tool_msg("y" * 3_000, "call_alpha"),
            _tool_msg("z" * 3_000, "call_beta"),
            _tool_msg("w" * 3_000, "call_gamma"),
            _tool_msg("w" * 3_000, "call_delta"),
            _tool_msg("done", "call_omega"),
        ]
        out = simplify_tool_results(messages, keep_last=1)
        stubbed_ids = [m["tool_call_id"] for m in out if "truncated for length" in m["content"]]
        assert stubbed_ids == ["call_alpha", "call_beta", "call_gamma", "call_delta"]
        assert out[-1]["tool_call_id"] == "call_omega"
        assert out[-1]["content"] == "done"

    def test_head_and_tail_survive_the_stub(self):
        content = "START_MARKER" + "m" * 4_000 + "END_MARKER"
        messages = [
            _tool_msg(content, "call_1"),
            _tool_msg(content, "call_2"),
            _tool_msg(content, "call_3"),
            _tool_msg(content, "call_4"),
            _tool_msg(content, "call_5"),
        ]
        out = simplify_tool_results(messages, keep_last=1, max_chars=100)
        stub = out[0]["content"]
        assert stub.startswith("START_MARKER")
        assert stub.endswith("END_MARKER")
        assert "truncated for length" in stub

    def test_small_old_results_left_alone(self):
        messages = [
            _tool_msg("tiny", "call_1"),
            _tool_msg("small result", "call_2"),
            _tool_msg("ok", "call_3"),
        ]
        out = simplify_tool_results(messages, keep_last=1)
        assert out == messages  # nothing exceeded max_chars → untouched

    def test_idempotent(self):
        big = "q" * 3_000
        messages = [_tool_msg(big, "call_1"), _tool_msg(big, "call_2"), _tool_msg("final", "call_3")]
        once = simplify_tool_results(messages, keep_last=1)
        twice = simplify_tool_results(once, keep_last=1)
        assert twice == once

    def test_non_tool_messages_untouched(self):
        messages = [
            {"role": "system", "content": "sys prompt"},
            _user_msg("hello"),
            {"role": "assistant", "content": "let me check", "tool_calls": [{"id": "call_1"}]},
            _tool_msg("z" * 2_000, "call_1"),
            _tool_msg("z" * 2_000, "call_2"),
            _user_msg("what did you find?"),
        ]
        out = simplify_tool_results(messages, keep_last=1)
        assert out[0] == messages[0]
        assert out[1] == messages[1]
        assert out[2] == messages[2]
        assert out[-1] == messages[-1]

    def test_fewer_tool_results_than_keep_last_returns_unchanged(self):
        messages = [
            _tool_msg("a" * 2_000, "call_1"),
            _tool_msg("b" * 2_000, "call_2"),
            _tool_msg("c" * 2_000, "call_3"),
        ]
        out = simplify_tool_results(messages, keep_last=5)
        assert out is messages  # no copy, no stubbing

    def test_empty_input(self):
        assert simplify_tool_results([]) == []

    def test_keep_last_zero_stubs_every_oversized_result(self):
        messages = [_tool_msg("a" * 2_000, "call_1"), _tool_msg("b" * 2_000, "call_2")]
        out = simplify_tool_results(messages, keep_last=0)
        for m in out:
            assert "truncated for length" in m["content"]

    def test_stubbing_preserves_other_message_keys(self):
        big = "k" * 2_000
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_x",
                "content": big,
                "extra": {"tool": "file_task", "path": "/tmp/x.py"},
            },
            _tool_msg(big, "call_y"),
            _tool_msg("final", "call_z"),
        ]
        out = simplify_tool_results(messages, keep_last=1)
        stubbed = out[0]
        assert "truncated for length" in stubbed["content"]
        # Non-content keys survive the stub ({**messages[i], "content": stub}).
        assert stubbed["tool_call_id"] == "call_x"
        assert stubbed["extra"] == {"tool": "file_task", "path": "/tmp/x.py"}


class TestSession410Defaults:
    """Session 410 (P0 Context Engineering) tightened the module defaults:
    KEEP_LAST_TOOL_RESULTS 4 → 1 and STUB_MAX_CHARS 600 → 400, after the
    prompt-assembly audit showed tool-result history growing 91 → 4228
    tokens across one research turn. These tests pin the new defaults so a
    future agent can't quietly regress them.
    """

    def test_default_keep_last_is_one(self):
        """With default args, only the NEWEST tool result stays verbatim."""
        big = "x" * 5_000
        messages = [
            _tool_msg(big, "call_1"),
            _tool_msg(big, "call_2"),
            _tool_msg(big, "call_3"),
            _tool_msg(big, "call_4"),  # newest — must stay verbatim
        ]
        out = simplify_tool_results(messages)  # default args
        # The newest (call_4) is verbatim.
        assert out[-1]["content"] == big
        assert out[-1]["tool_call_id"] == "call_4"
        # The three older ones are stubbed (would have been verbatim under
        # the legacy keep_last=4 default).
        for i in (0, 1, 2):
            assert "truncated for length" in out[i]["content"]
            assert out[i]["tool_call_id"] == f"call_{i+1}"

    def test_default_stub_max_chars_is_400(self):
        """With default args, a stubbed result's content is ~400 chars
        (200 head + marker + 200 tail), not the legacy 600."""
        # Build content where head and tail are distinguishable.
        content = "H" * 200 + "M" * 5_000 + "T" * 200
        messages = [
            _tool_msg(content, "old"),
            _tool_msg(content, "older"),
            _tool_msg("final", "new"),  # newest — verbatim
        ]
        out = simplify_tool_results(messages)  # default args
        stub = out[0]["content"]
        # Head and tail survive.
        assert stub.startswith("H" * 200)
        assert stub.endswith("T" * 200)
        # The stub is well under the legacy 600-char head+tail (which would
        # have been 300+300=600). With max_chars=400, head+tail = 200+200=400.
        # The marker adds ~90 chars, so total stub length is ~490.
        assert len(stub) < 600, (
            f"stub length {len(stub)} suggests max_chars is still 600 — "
            "Session 410 tightened STUB_MAX_CHARS to 400"
        )

    def test_default_aggressive_compaction_in_research_scenario(self):
        """Simulates the audit's research-turn shape: 5 tool results, each
        ~5000 chars (≈1300 tokens, like a web_fetch result). Under the new
        defaults, the oldest 4 collapse to ~490-char stubs and only the
        newest stays verbatim — ~5.5K chars of history instead of ~25K."""
        big = "x" * 5_000
        messages = [
            _user_msg("research prompt"),
            _tool_msg(big, "c1"),
            _tool_msg(big, "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),  # newest — verbatim
        ]
        out = simplify_tool_results(messages)
        total_chars = sum(len(m.get("content", "")) for m in out if m["role"] == "tool")
        # 4 stubs × ~490 + 1 verbatim × 5000 = ~6960 chars
        # Under legacy keep_last=4, this would be 4 × 5000 + 1 stub × ~690 = ~20690
        assert total_chars < 8_000, (
            f"total tool content {total_chars} chars — expected <8K under "
            "Session 410 defaults (keep_last=1, stub=400)"
        )
