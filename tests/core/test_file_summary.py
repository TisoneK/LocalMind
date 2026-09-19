"""The final answer's deterministic file-task summary.

Derived from the actual tool timeline (file_write → created with bytes,
edit_file/propose_write_file → modified) so the user SEES the file facts next
to the final output even when the model forgets to mention its own writes.
"""
from __future__ import annotations

from core.agent.file_summary import build_file_task_summary


class TestBuildFileTaskSummary:
    def test_empty_when_no_file_tools(self):
        assert build_file_task_summary([]) == ""
        assert (
            build_file_task_summary(
                [{"name": "shell", "tool_args": "ls -la"}, {"name": "web_search", "tool_args": "q"}]
            )
            == ""
        )

    def test_file_write_reports_created_with_bytes(self):
        calls = [
            {"name": "file_write", "tool_args": "demo-todo/a.txt:\n\nfirst line\nsecond line"},
        ]
        summary = build_file_task_summary(calls)
        assert summary.startswith("\n\n📁 Files:\n")
        assert "- `demo-todo/a.txt` (created, 22 B)" in summary

    def test_edit_file_reports_modified(self):
        calls = [
            {"name": "edit_file", "tool_args": '{"path": "src/foo.py", "old": "a", "new": "b"}'},
        ]
        summary = build_file_task_summary(calls)
        assert "- `src/foo.py` (modified)" in summary
        assert "created" not in summary

    def test_mixed_writes_and_edits_order_preserved(self):
        calls = [
            {"name": "file_write", "tool_args": "a.txt:\n\nx"},
            {"name": "file_write", "tool_args": "b.txt:\n\ny"},
            {"name": "edit_file", "tool_args": '{"path": "a.txt", "old": "x"}'},
        ]
        summary = build_file_task_summary(calls)
        # a.txt's FIRST occurrence (write) wins → created; b.txt created; dedup.
        assert summary.count("a.txt") == 1
        assert "- `a.txt` (created, 1 B)" in summary
        assert "- `b.txt` (created, 1 B)" in summary
        assert summary.index("a.txt") < summary.index("b.txt")

    def test_accepts_collect_tool_calls_shape(self):
        # Same shape _collect_tool_calls(collector) returns (name/tool_args).
        calls = [
            {"id": "tc-file_write-iter1-x", "name": "file_write", "status": "done",
             "tool_args": "README.md:\n\n# Hi"},
        ]
        summary = build_file_task_summary(calls)
        assert "- `README.md` (created, 4 B)" in summary

    def test_malformed_rows_ignored(self):
        calls = [
            {"name": "file_write", "tool_args": ""},
            {"name": "edit_file", "tool_args": "not json"},
            "garbage",
            None,
        ]
        assert build_file_task_summary(calls) == ""

    def test_windows_path_in_edit_json(self):
        calls = [
            {"name": "edit_file", "tool_args": '{"path": "C:\\\\Users\\\\tison\\\\file.md", "old": "a"}'},
        ]
        summary = build_file_task_summary(calls)
        # JSON decodes \\\\ → \\; the summary shows the real single-backslash path.
        assert "- `C:\\Users\\tison\\file.md` (modified)" in summary


class TestOnlySuccessfulWritesAreCreated:
    """The block is evidence: it must never say "created" for a file that was not."""

    def test_a_failed_write_is_reported_as_not_written(self):
        calls = [{"name": "file_write", "status": "failed", "tool_args": "a.txt:\n\neta"}]
        summary = build_file_task_summary(calls)
        assert "- `a.txt` (NOT written — the write failed)" in summary
        assert "created" not in summary

    def test_a_write_that_never_finished_is_reported_as_not_written(self):
        calls = [{"name": "file_write", "status": "started", "tool_args": "a.txt:\n\neta"}]
        summary = build_file_task_summary(calls)
        assert "- `a.txt` (NOT written — the write did not finish)" in summary

    def test_a_retry_that_succeeds_wins_over_the_failed_first_attempt(self):
        calls = [
            {"name": "file_write", "status": "failed", "tool_args": "a.txt:\n\ne"},
            {"name": "file_write", "status": "done", "tool_args": "a.txt:\n\neta"},
        ]
        summary = build_file_task_summary(calls)
        assert summary.count("a.txt") == 1
        assert "- `a.txt` (created, 3 B)" in summary
        assert "NOT written" not in summary

    def test_rows_without_a_status_are_still_trusted(self):
        # Rows restored from older saved turns carry no status.
        summary = build_file_task_summary([{"name": "file_write", "tool_args": "a.txt:\n\nhello"}])
        assert "- `a.txt` (created, 5 B)" in summary

