"""ADR-19 selective compactor v2 tests (Session 161).

`simplify_tool_results(..., policy=...)` keeps the positional legacy path
byte-identical when policy is None/default, and adds TASK-AWARE selection
when a real policy is passed:
  - Old tool results matching the policy's keep_markers survive verbatim
    regardless of age (bounded by policy.max_keep).
  - CAN-DISCARD is a capability that is OFF for every policy_for() result
    (locked Session 159); only explicit test policies enable it.
  - tool_call_id protocol validity, idempotency, and non-tool messages are
    preserved in every path.
"""

from __future__ import annotations

from core.context_compactor import (
    _DISCARD_NOTICE,
    _STUB_MARKER,
    simplify_tool_results,
)
from core.context_policy import ContextPolicy, policy_for


def _tool_msg(content: str, call_id: str = "call_1") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _user_msg(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant_tool_calls(call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "shell", "arguments": "{}"},
            }
        ],
    }


# ── 1. Legacy no-op: policy=None / default behaves exactly as before ─────────


class TestLegacyNoop:
    def test_none_policy_is_legacy(self):
        big = "x" * 5_000
        messages = [
            _user_msg("do the work"),
            _tool_msg(big, "call_1"),
            _tool_msg(big, "call_2"),
            _tool_msg(big, "call_3"),
            _tool_msg(big, "call_4"),
            _tool_msg(big, "call_5"),
            _tool_msg(big, "call_6"),
        ]
        # Pass keep_last=4 explicitly — Session 410 tightened the module
        # default to 1 (P0 Context Engineering), but this test's intent is
        # "policy=None is a no-op for the same keep_last", not "the default
        # is 4". Pinning keep_last=4 keeps the legacy-window assertions
        # below deterministic regardless of the module default.
        with_policy = simplify_tool_results(messages, keep_last=4, policy=None)
        without = simplify_tool_results(messages, keep_last=4)
        assert with_policy == without
        # Newest 4 verbatim, oldest 2 stubbed.
        assert _STUB_MARKER in with_policy[1]["content"]
        assert _STUB_MARKER in with_policy[2]["content"]
        assert with_policy[3]["content"] == big  # keep_last=4 → newest 4 verbatim

    def test_default_policy_is_legacy(self):
        big = "x" * 5_000
        messages = [
            _tool_msg(big, "c1"),
            _tool_msg(big, "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
        ]
        default = simplify_tool_results(messages, policy=policy_for(None))
        assert default == simplify_tool_results(messages)


# ── 2. Policy-aware keep: marker-matched OLD results survive ─────────────────


class TestPolicyKeep:
    def test_marker_protects_old_result_beyond_keep_last(self):
        """A failing test two results back survives stubbing for debug tasks."""
        big = "x" * 5_000
        debug = policy_for("debug")
        messages = [
            _user_msg("run tests"),
            _tool_msg("pytest output ... Test failed: test_login", "call_1"),
            _tool_msg(big, "call_2"),
            _tool_msg(big, "call_3"),
            _tool_msg(big, "call_4"),
            _tool_msg(big, "call_5"),
            _tool_msg(big, "call_6"),
            _tool_msg(big, "call_7"),
            _tool_msg(big, "call_8"),
        ]
        # Pass keep_last=4 explicitly — Session 410 tightened the module
        # default to 1, but this test's intent is "marker protection works
        # independently of the keep_last window". Pinning keep_last=4 keeps
        # the window assertions below deterministic.
        result = simplify_tool_results(messages, keep_last=4, policy=debug)
        # call_1 (old, marker 'test failed') is kept verbatim despite being
        # older than the keep_last=4 window (which covers call_5..call_8).
        assert result[1]["content"] == messages[1]["content"]
        # The unmarked big results OUTSIDE the newest-4 window get stubbed
        # (call_2, call_3, call_4).
        assert _STUB_MARKER in result[2]["content"]
        assert _STUB_MARKER in result[3]["content"]
        assert _STUB_MARKER in result[4]["content"]
        # Newest window stays verbatim.
        assert result[7]["content"] == big
        assert result[8]["content"] == big

    def test_marker_match_is_case_insensitive(self):
        big = "x" * 5_000
        debug = policy_for("debug")
        messages = [
            _tool_msg("ERROR: boom", "c1"),
            _tool_msg("Traceback (most recent call last)", "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
            _tool_msg(big, "c6"),
        ]
        result = simplify_tool_results(messages, policy=debug)
        # 'ERROR:' and 'traceback' both match case-insensitively (markers are
        # lowercase; content has uppercase).
        assert result[0]["content"] == messages[0]["content"]
        assert result[1]["content"] == messages[1]["content"]

    def test_max_keep_budget_not_wasted_on_small_matches(self):
        """Small marker lines (never stubbed anyway) must not consume the
        max_keep budget — a LARGE old marker-bearing result stays protected."""
        big = "x" * 5_000
        debug = ContextPolicy(
            task_type="debug",
            keep_markers=("traceback",),
            max_keep=1,
        )
        messages = [
            _tool_msg("Traceback (small)", "c1"),  # small match — shouldn't count
            _tool_msg("Traceback" + "z" * 700, "c2"),  # large match — should be protected
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
            _tool_msg(big, "c6"),
            _tool_msg(big, "c7"),
            _tool_msg(big, "c8"),
        ]
        result = simplify_tool_results(messages, policy=debug, keep_last=2)
        # c2 (the large marker-bearing old result) is protected despite c1
        # (a small match) appearing first — small matches don't eat the cap.
        assert result[1]["content"] == messages[1]["content"]
        # c1 is small so it's left verbatim anyway; the unmarked big old
        # results beyond keep_last get stubbed.
        assert _STUB_MARKER in result[2]["content"]

    def test_max_keep_bounds_protected_results(self):
        """max_keep caps how many marker-protected old results survive."""
        big = "x" * 5_000
        debug = ContextPolicy(
            task_type="debug",
            keep_markers=("traceback",),
            max_keep=2,
        )
        messages = [
            _tool_msg("Traceback #1" + "x" * 700, "c1"),
            _tool_msg("Traceback #2" + "y" * 700, "c2"),
            _tool_msg("Traceback #3" + "z" * 700, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
            _tool_msg(big, "c6"),
            _tool_msg(big, "c7"),
            _tool_msg(big, "c8"),
        ]
        result = simplify_tool_results(messages, policy=debug, keep_last=2)
        # keep_last=2 protects the newest 2 (c7, c8) verbatim.
        # max_keep=2 protects the FIRST 2 matching old results (c1, c2).
        # c3 matches the marker but is NOT protected (bounded) → stubbed.
        assert result[0]["content"] == messages[0]["content"]
        assert result[1]["content"] == messages[1]["content"]
        assert _STUB_MARKER in result[2]["content"]
        assert result[6]["content"] == big
        assert result[7]["content"] == big


# ── 3. Discard capability (OFF in P0) ────────────────────────────────────────


class TestDiscardOffByDefault:
    def test_policy_for_never_enables_drop(self):
        for t in ("debug", "plan", "code", "research", "chat", "verify", "default"):
            assert policy_for(t).allow_drop is False

    def test_drop_does_not_fire_without_allow_drop(self):
        """Even with drop_markers set, allow_drop=False means stub, not drop."""
        big = "x" * 5_000
        no_drop = ContextPolicy(
            task_type="code",
            keep_markers=(),
            drop_markers=("already resolved",),
            allow_drop=False,
        )
        messages = [
            _tool_msg("this topic is already resolved", "c1"),
            _tool_msg(big, "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
        ]
        result = simplify_tool_results(messages, policy=no_drop)
        assert _DISCARD_NOTICE not in result[0]["content"]
        assert result[0]["content"] == messages[0]["content"]  # kept verbatim (newest)

    def test_drop_capability_works_when_explicitly_enabled(self):
        """The capability is implemented; only explicit test policies enable it."""
        big = "x" * 5_000
        drop_on = ContextPolicy(
            task_type="code",
            keep_markers=(),
            drop_markers=("already resolved",),
            allow_drop=True,
        )
        messages = [
            _tool_msg("this is already resolved content", "c1"),
            _tool_msg(big, "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
            _tool_msg(big, "c6"),
        ]
        result = simplify_tool_results(messages, policy=drop_on)
        # c1 matches drop marker and is old → replaced with the notice.
        assert result[0]["content"] == _DISCARD_NOTICE
        # Newest window stays verbatim.
        assert result[5]["content"] == big


# ── 4. Protocol invariants + idempotency across paths ────────────────────────


class TestInvariants:
    def test_tool_call_ids_preserved_with_policy(self):
        big = "x" * 5_000
        debug = policy_for("debug")
        messages = [
            _user_msg("go"),
            _assistant_tool_calls("call_a"),
            _tool_msg("Traceback ...", "call_a"),
            _assistant_tool_calls("call_b"),
            _tool_msg(big, "call_b"),
            _assistant_tool_calls("call_c"),
            _tool_msg(big, "call_c"),
            _assistant_tool_calls("call_d"),
            _tool_msg(big, "call_d"),
            _assistant_tool_calls("call_e"),
            _tool_msg(big, "call_e"),
        ]
        result = simplify_tool_results(messages, policy=debug)
        # Every tool result keeps its own tool_call_id.
        tool_ids = [m["tool_call_id"] for m in result if m.get("role") == "tool"]
        assert tool_ids == ["call_a", "call_b", "call_c", "call_d", "call_e"]
        # The assistant tool_calls ids still match their tool responses.
        for m in result:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                tid = m["tool_calls"][0]["id"]
                assert any(
                    t.get("tool_call_id") == tid for t in result if t.get("role") == "tool"
                )

    def test_policy_path_is_idempotent(self):
        big = "x" * 5_000
        debug = policy_for("debug")
        messages = [
            _tool_msg("Traceback boom", "c1"),
            _tool_msg(big, "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
            _tool_msg(big, "c6"),
        ]
        once = simplify_tool_results(messages, policy=debug)
        twice = simplify_tool_results(once, policy=debug)
        assert twice == once

    def test_non_tool_messages_untouched(self):
        big = "x" * 5_000
        debug = policy_for("debug")
        messages = [
            _user_msg("original user message"),
            _tool_msg("Traceback x", "c1"),
            _tool_msg(big, "c2"),
            _tool_msg(big, "c3"),
            _tool_msg(big, "c4"),
            _tool_msg(big, "c5"),
        ]
        result = simplify_tool_results(messages, policy=debug)
        assert result[0] == messages[0]
