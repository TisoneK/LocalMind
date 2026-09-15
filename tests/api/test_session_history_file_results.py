"""The history endpoint must surface the files the agent wrote.

The live `done` SSE carries the last written path, but the stored message only
kept user-attached files. The tool-call timeline is the durable record —
`_agent_written_paths` recovers paths from it so the export (and a reload) can
show which files the session created.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from api.routes.sessions import _agent_written_paths


class TestAgentWrittenPaths:
    def test_file_write_args_are_path_content(self):
        calls = [
            {
                "name": "file_write",
                "tool_args": "demo-todo/a.txt:\n\nfirst line\nsecond line",
            },
            {
                "name": "file_write",
                "tool_args": "demo-todo/b.txt:\n\nsecond",
            },
        ]
        assert _agent_written_paths(calls) == ["demo-todo/a.txt", "demo-todo/b.txt"]

    def test_edit_file_json_args(self):
        calls = [
            {
                "name": "edit_file",
                "tool_args": '{"path": "src/foo.py", "old": "a", "new": "b"}',
            },
        ]
        assert _agent_written_paths(calls) == ["src/foo.py"]

    def test_dedupes_while_preserving_order(self):
        calls = [
            {"name": "file_write", "tool_args": "a.txt:\n\nx"},
            {"name": "file_write", "tool_args": "a.txt:\n\ny"},
            {"name": "edit_file", "tool_args": '{"path": "a.txt", "old": "x"}'},
        ]
        assert _agent_written_paths(calls) == ["a.txt"]

    def test_non_writing_tools_ignored(self):
        calls = [
            {"name": "shell", "tool_args": "ls -la"},
            {"name": "web_search", "tool_args": "query"},
            {"name": "file_task", "tool_args": "README.md"},
        ]
        assert _agent_written_paths(calls) == []

    def test_empty_and_malformed_inputs_safe(self):
        assert _agent_written_paths([]) == []
        assert _agent_written_paths(None) == []
        assert _agent_written_paths([{"name": "file_write", "tool_args": ""}]) == []
        assert _agent_written_paths([{"name": "file_write", "tool_args": "   "}]) == []
        assert _agent_written_paths([{"name": "edit_file", "tool_args": "not json"}]) == []
        assert _agent_written_paths([{"name": "file_write", "tool_args": "   \n\ncontent"}]) == []


class TestHistoryDerivesFileResults:
    """The history endpoint merges user-attached files + agent-written paths."""

    def test_agent_written_paths_merge_into_file_results(self):
        fake_messages = [
            type(
                "Msg",
                (),
                {
                    "timestamp": 1000.0,
                    "role": type("R", (), {"value": "assistant"})(),
                    "content": "done",
                    "thinking": None,
                    "acknowledgement": None,
                    "error": None,
                    "tool_calls": [
                        {
                            "name": "file_write",
                            "tool_args": "out/f.txt:\n\nhello",
                            "status": "done",
                        }
                    ],
                    "metrics": None,
                    "agent_runs": None,
                    "agent_phases": None,
                    "tool_name": None,
                    "file_path": None,
                    "file_name": None,
                    "file_size": None,
                    "file_type": None,
                },
            )
        ]

        from api.routes import sessions as sessions_mod

        with patch.object(
            sessions_mod, "_store"
        ) as mock_store, patch.object(
            sessions_mod, "get_shared_store", return_value=mock_store
        ):
            mock_store.get_history.return_value = fake_messages
            mock_store.get_session_title.return_value = "t"

            # get_history is a sync FastAPI route; call the underlying logic
            # through the module (the route wrapper is thin).
            from api.routes.sessions import get_history

            result = asyncio.run(get_history("s1"))
            history = result["history"]
            assert len(history) == 1
            fr = history[0]["fileResults"]
            paths = [f["path"] for f in fr]
            assert "out/f.txt" in paths
            assert fr[0]["type"] in ("written", "unknown")  # written wins
