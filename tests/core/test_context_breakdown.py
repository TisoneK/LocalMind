"""Unit tests for the per-category context-usage breakdown estimator."""

import json

from core.agent.context_breakdown import (
    CURRENT_MESSAGE,
    HISTORY,
    SYSTEM_PROMPT,
    TOOL_RESULTS,
    TOOL_SCHEMAS,
    TURN_ADDITIONS,
    TURN_CONTEXT,
    compute_breakdown,
    scale_breakdown,
)


def _msg(role, content, **extra):
    m = {"role": role, "content": content}
    m.update(extra)
    return m


class TestComputeBreakdown:
    def test_classifies_turn_shape(self):
        # A realistic parent-turn payload: stable system prompt, dynamic
        # turn-context, two history turns, the current user message, then
        # per-iteration additions (assistant tool call + tool result).
        messages = [
            _msg("system", "You are LocalMind. " * 20),
            _msg("system", "Environment: Windows. Memory facts..."),
            _msg("user", "earlier question"),
            _msg("assistant", "earlier answer"),
            _msg("user", "the current request"),
            # boundary here (turn start captured after the system inserts)
            _msg("assistant", "", tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"q": "x"}'},
            }]),
            _msg("tool", "search result body", tool_call_id="call_1"),
            _msg("user", "Iteration 2/8. observations..."),
        ]
        boundary = 5
        out = compute_breakdown(messages, [], boundary)
        assert out[SYSTEM_PROMPT] > 0
        assert out[TURN_CONTEXT] > 0
        assert out[HISTORY] > 0
        assert out[CURRENT_MESSAGE] > 0
        assert out[TOOL_RESULTS] > 0
        assert out[TURN_ADDITIONS] > 0
        assert out[TOOL_SCHEMAS] == 0

    def test_tool_schemas_counted_from_json(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a command",
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            },
        }]
        out = compute_breakdown([_msg("system", "s")], tools, 1)
        assert out[TOOL_SCHEMAS] > 0
        # Roughly the JSON size in tokens (tiktoken or chars//4 fallback).
        assert abs(out[TOOL_SCHEMAS] - len(json.dumps(tools)) // 4) < out[TOOL_SCHEMAS]

    def test_current_message_is_last_pre_boundary(self):
        messages = [
            _msg("system", "prompt"),
            _msg("user", "old"),
            _msg("assistant", "old reply"),
            _msg("user", "NEW REQUEST"),
        ]
        out = compute_breakdown(messages, [], 4)
        # The current message carries the request text, history carries the rest.
        assert out[CURRENT_MESSAGE] >= 2
        assert out[HISTORY] > 0

    def test_mid_history_system_message_is_turn_context(self):
        # Attachment system messages sit between history and the current
        # message; they are per-turn injections, not the stable prompt.
        messages = [
            _msg("system", "stable prompt"),
            _msg("system", "attachment content"),
            _msg("user", "question about the file"),
        ]
        out = compute_breakdown(messages, [], 3)
        assert out[TURN_CONTEXT] > 0

    def test_non_dict_messages_skipped(self):
        # Only index 0 counts as the stable prompt; a system message at any
        # other index is per-turn context.
        out = compute_breakdown(["junk", _msg("system", "ok")], [], 2)
        assert out[TURN_CONTEXT] > 0
        assert out[SYSTEM_PROMPT] == 0

    def test_none_content_is_safe(self):
        out = compute_breakdown([_msg("assistant", None)], [], 1)
        assert sum(out.values()) > 0  # just the framing overhead


class TestScaleBreakdown:
    def test_scales_to_provider_total(self):
        est = {"system_prompt": 100, "history": 300}
        out = scale_breakdown(est, 2000)
        assert sum(out.values()) == 2000
        assert out["history"] == 1500
        assert out["system_prompt"] == 500

    def test_zero_total_returns_raw_estimates(self):
        est = {"system_prompt": 100, "history": 300, "tool_schemas": 0}
        out = scale_breakdown(est, 0)
        assert out == {"system_prompt": 100, "history": 300}  # zero cats dropped

    def test_empty_breakdown(self):
        assert scale_breakdown({}, 500) == {}

    def test_rounding_drift_parked_on_largest(self):
        est = {"a": 1, "b": 1, "c": 1}
        out = scale_breakdown(est, 10)
        assert sum(out.values()) == 10
