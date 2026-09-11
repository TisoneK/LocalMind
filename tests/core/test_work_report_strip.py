"""Tests for the internal evidence-recap strip (worker-report leak guard).

The deterministic "Worker report — tool execution evidence:" block is a
USER-facing fallback rendered from the trace. It must never flow back into a
model prompt (a model that reads the format starts mimicking it into its own
answers), and a model-authored mimic of the block must be dropped at the
emission boundary so the deterministic renderer stays the only author.

Covers:
- strip_worker_reports against the exact renderer output (round-trip)
- drift tolerance for mimicked blocks (indent/numbering variants)
- prose and bare-header non-matches
- strip_worker_reports_from_history (assistant turns only)
- the parent-session feed (recent_tail + rolling summary stay clean)
- the memory-resolver feed (transcript stays clean)
- the episode-memory distill feed (excerpt stays clean)
"""

from __future__ import annotations

from types import SimpleNamespace

from core.agent.models import (
    WORK_REPORT_HEADER,
    WorkReport,
    WorkReportEntry,
    strip_worker_reports,
    strip_worker_reports_from_history,
)
from core.episode_memory import EpisodeMemory
from core.memory_resolver import build_resolution_messages
from core.parent_session import ParentSession


def _report(hit_limit: bool = False, *entries: WorkReportEntry) -> str:
    return WorkReport(
        entries=entries or (WorkReportEntry("shell", "count files", "4801", True),),
        hit_limit=hit_limit,
    ).render()


class TestStripWorkerReports:
    def test_strips_exact_renderer_output(self):
        answer = "4801\n\n" + _report()
        assert strip_worker_reports(answer) == "4801\n\n"

    def test_strips_trace_shaped_mimicry(self):
        # The shape observed in the field trace: header verbatim, entries
        # copied with drifted indentation (single-space Output indent).
        mimic = (
            "Worker report — tool execution evidence:\n"
            "1. shell(...) — succeeded\n"
            " Output: 4801"
        )
        assert strip_worker_reports("4801\n\n" + mimic) == "4801\n\n"

    def test_strips_hit_limit_variant(self):
        answer = "Working on it.\n\n" + _report(
            True,
            WorkReportEntry("shell", "ls", "a.txt", True),
            WorkReportEntry("file_read", "a.py", "c", False),
        )
        assert strip_worker_reports(answer) == "Working on it.\n\n"

    def test_strips_between_answer_and_trailing_prose(self):
        answer = "done\n\n" + _report() + "\n\nHope that helps!"
        assert strip_worker_reports(answer) == "done\n\nHope that helps!"

    def test_tolerates_paren_numbering_and_extra_indent(self):
        mimic = (
            WORK_REPORT_HEADER
            + "\n1) shell(dir) — succeeded\n"
            + "  Output: 12"
        )
        assert strip_worker_reports("Answer: 12\n\n" + mimic) == "Answer: 12\n\n"

    def test_prose_mention_untouched(self):
        text = "The worker report showed the count; the report header says done."
        assert strip_worker_reports(text) == text

    def test_bare_header_without_entries_untouched(self):
        text = "text\n\n" + WORK_REPORT_HEADER + "\nand more"
        assert strip_worker_reports(text) == text

    def test_empty_and_clean_text_unchanged(self):
        assert strip_worker_reports("") == ""
        assert strip_worker_reports("plain answer") == "plain answer"


class TestHistoryFeedHelper:
    def test_strips_assistant_turns_only(self):
        report = _report()
        history = [
            {"role": "user", "content": "How many files? Just the number."},
            {"role": "assistant", "content": "4801\n\n" + report},
            {"role": "user", "content": WORK_REPORT_HEADER + " is what I saw"},
        ]
        cleaned = strip_worker_reports_from_history(history)
        assert cleaned[1]["content"] == "4801\n\n"
        assert WORK_REPORT_HEADER not in cleaned[1]["content"]
        # user turns pass through verbatim
        assert cleaned[0]["content"] == history[0]["content"]
        assert cleaned[2]["content"] == history[2]["content"]

    def test_non_dict_items_pass_through(self):
        history = ["raw string", {"role": "assistant", "content": "a\n\n" + _report()}]
        cleaned = strip_worker_reports_from_history(history)
        assert cleaned[0] == "raw string"
        assert WORK_REPORT_HEADER not in cleaned[1]["content"]


class TestParentSessionFeed:
    def test_appended_report_never_enters_session_state(self):
        ps = ParentSession(session_id="s1")
        ps.update_with_turn("Count the files.", "4801\n\n" + _report())
        assert WORK_REPORT_HEADER not in ps.recent_tail[0]["assistant"]
        assert ps.recent_tail[0]["assistant"] == "4801"
        # The compacted summary (which future prompts inject) stays clean too.
        for _ in range(RECENT_TAIL_OVERFLOW):
            ps.update_with_turn(f"q{_}", f"a{_}")
        assert WORK_REPORT_HEADER not in (ps.rolling_summary or "")

    def test_model_mimicry_is_cleaned_the_same_way(self):
        ps = ParentSession(session_id="s1")
        ps.update_with_turn("Count.", "4801\n" + WORK_REPORT_HEADER + "\n1. shell(x) — succeeded\n Output: 4801")
        assert WORK_REPORT_HEADER not in ps.recent_tail[0]["assistant"]


RECENT_TAIL_OVERFLOW = 24  # RECENT_TAIL_MAX + a few, to force compaction


class TestMemoryResolverFeed:
    def test_transcript_excludes_report_block(self):
        history = [
            {"role": "user", "content": "What did you run?"},
            {"role": "assistant", "content": "shell\n\n" + _report()},
        ]
        messages = build_resolution_messages(history, "remember the source")
        transcript = messages[1]["content"]
        assert WORK_REPORT_HEADER not in transcript
        assert "shell" in transcript


class TestEpisodeMemoryFeed:
    def test_excerpt_excludes_report_block(self):
        history = [
            SimpleNamespace(role="user", content="Count the files."),
            SimpleNamespace(role="assistant", content="4801\n\n" + _report()),
            SimpleNamespace(role="assistant", content=WORK_REPORT_HEADER + "\n1. shell(x) — succeeded"),
        ]
        excerpt = EpisodeMemory._build_excerpt(history)
        assert WORK_REPORT_HEADER not in excerpt
        assert "4801" in excerpt
