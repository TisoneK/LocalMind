"""History restore: thinkMs / diffData / candidates survive a reload.

The live stream shows the "Thought for Xs" label, the structured edit diff,
and the best-of-N candidate comparison; all three are now persisted with the
assistant message. The history endpoint must map them back to the exact
frontend field names (camelCase) the live SSE used.
"""
from __future__ import annotations

import asyncio

from core.models import Message, Role


def _run_history(messages):
    from unittest.mock import patch

    from api.routes import sessions as sessions_mod
    from api.routes.sessions import get_history

    with patch.object(sessions_mod, "_store") as mock_store, patch.object(
        sessions_mod, "get_shared_store", return_value=mock_store
    ):
        mock_store.get_history.return_value = messages
        mock_store.get_session_title.return_value = "t"
        return asyncio.run(get_history("s1"))["history"]


class TestHistoryRestoresReloadFields:
    def test_think_ms_maps_to_think_ms_camel(self):
        history = _run_history(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="done",
                    thinking="a reasoning trace",
                    metrics={
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "latency_ms": 100,
                        "think_ms": 4200,
                    },
                )
            ]
        )
        assert history[0]["thinkMs"] == 4200
        # performance still carries the token/latency fields as before
        assert history[0]["performance"]["latencyMs"] == 100

    def test_zero_or_absent_think_ms_omits_the_field(self):
        history = _run_history(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="done",
                    metrics={"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100, "think_ms": 0},
                ),
                Message(
                    role=Role.ASSISTANT,
                    content="done",
                    metrics={"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100},
                ),
            ]
        )
        assert "thinkMs" not in history[0]
        assert "thinkMs" not in history[1]

    def test_diff_data_maps_to_diff_data_camel(self):
        diff = {
            "hunks": [{"filePath": "src/foo.py", "lines": [{"type": "added", "content": "x = 2", "newLine": 10}]}],
            "language": "python",
            "filePath": "src/foo.py",
            "additions": 1,
            "deletions": 0,
        }
        history = _run_history(
            [Message(role=Role.ASSISTANT, content="edited", diff_data=diff)]
        )
        assert history[0]["diffData"] == diff

    def test_candidates_pass_through_in_frontend_shape(self):
        candidates = [
            {"index": 0, "strategy": "conservative", "rationale": "smallest change", "isWinner": False},
            {"index": 1, "strategy": "refactor", "rationale": "clearer structure", "isWinner": True},
        ]
        history = _run_history(
            [Message(role=Role.ASSISTANT, content="edited", candidates=candidates)]
        )
        assert history[0]["candidates"] == candidates

    def test_plain_message_carries_none_of_the_new_fields(self):
        history = _run_history([Message(role=Role.USER, content="hello")])
        msg = history[0]
        assert "thinkMs" not in msg
        assert "diffData" not in msg
        assert "candidates" not in msg
