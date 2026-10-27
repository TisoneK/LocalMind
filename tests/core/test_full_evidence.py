"""Full-text tool evidence tests (the layers that think must see what the tools returned).

The Kitengela trace's three-in-one failure — a one-sentence thought, a raw
evidence dump as the final answer, "truncation on output" — shared one root:
the Thinker and the synthesis rescues reasoned over head+tail observation
stubs while the full tool output sat in the index behind a stub pointer.
These tests pin the full-text view those layers now read.
"""

from __future__ import annotations

import pytest
from core.agent.full_evidence import (
    EvidenceBlock,
    full_tool_evidence_blocks,
    render_evidence_blocks,
)
from core.agent.models import AgentStep, AgentTrace, WorkReport, strip_worker_reports

STUB_ID = "web_fetch-71e8154ac9a1796d"
CHROME_HEAD = "Weather Kitengela - meteoblue\nGet the app"
CHROME_MIDDLE = "FORECAST-ROW Kitengela 26/17 wind 24 km/h sunshine 4h"
CHROME_TAIL = "Back to top\n© 2026 meteoblue"
STUB_OBSERVATION = (
    f"{CHROME_HEAD}\n…[truncated for context — full web_fetch output "
    f"(9,964 chars) stored — id={STUB_ID}; call search_tool_results]…\n{CHROME_TAIL}"
)


@pytest.fixture()
def _index_with_chunks(monkeypatch, tmp_path):
    """A tool-result index double: chunks_for_result returns the full text."""
    import storage.tool_result_index as tri

    class _FakeIndex:
        def chunks_for_result(self, result_id):
            if result_id == STUB_ID:
                return [CHROME_HEAD, CHROME_MIDDLE, CHROME_TAIL]
            return []

    monkeypatch.setattr(tri, "get_tool_result_index", lambda: _FakeIndex())
    yield


def test_stubbed_step_reads_full_stored_chunks(_index_with_chunks):
    trace = AgentTrace(
        steps=[
            AgentStep(
                iteration=1, thought="", tool_name="web_fetch",
                tool_input="https://www.meteoblue.com/…",
                observation=STUB_OBSERVATION,
            )
        ]
    )
    blocks = full_tool_evidence_blocks(trace)
    assert len(blocks) == 1
    # The middle — invisible in the head+tail stub — is IN.
    assert "FORECAST-ROW" in blocks[0].text
    assert "26/17" in blocks[0].text


def test_unstubbed_step_keeps_observation(_index_with_chunks):
    trace = AgentTrace(
        steps=[
            AgentStep(
                iteration=1, thought="", tool_name="shell",
                tool_input="git status",
                observation="On branch main\nnothing to commit, working tree clean",
            )
        ]
    )
    blocks = full_tool_evidence_blocks(trace)
    assert blocks[0].text.startswith("On branch main")


def test_tool_messages_carry_full_small_results(_index_with_chunks):
    trace = AgentTrace(
        steps=[
            AgentStep(iteration=1, thought="", tool_name="shell", tool_input="ls", observation="a.txt\nb.txt")
        ]
    )
    messages = [
        {"role": "user", "content": "list"},
        {"role": "tool", "tool_call_id": "x", "content": "a.txt\nb.txt\nc.txt\nd.txt"},
    ]
    blocks = full_tool_evidence_blocks(trace, messages)
    joined = "\n".join(b.text for b in blocks)
    assert "d.txt" in joined  # the full copy, not the truncated step record


def test_stubshaped_tool_message_is_skipped(_index_with_chunks):
    trace = AgentTrace()
    messages = [
        {"role": "tool", "tool_call_id": "x", "content": STUB_OBSERVATION},
    ]
    blocks = full_tool_evidence_blocks(trace, messages)
    assert blocks == []  # the chunks path owns stubbed content


def test_total_budget_keeps_newest_evidence(_index_with_chunks):
    steps = [
        AgentStep(
            iteration=i + 1, thought="", tool_name="shell",
            tool_input=f"cmd-{i}", observation="x" * 5000,
        )
        for i in range(8)
    ]
    blocks = full_tool_evidence_blocks(trace=AgentTrace(steps=steps), total_cap=12000)
    assert sum(len(b.text) for b in blocks) <= 12000 + 7  # caps + separators slack
    assert blocks[-1].tool_input == "cmd-7"  # the newest survives


def test_non_tool_steps_contribute_nothing():
    trace = AgentTrace(
        steps=[AgentStep(iteration=2, thought=CHROME_TAIL, tool_name=None, tool_input=None, observation=None)]
    )
    assert full_tool_evidence_blocks(trace) == []


def test_render_matches_thinker_shape():
    text = render_evidence_blocks([EvidenceBlock(tool_name="shell", tool_input="git status", text="clean")])
    assert text.startswith("[shell] git status\n")


# ── The user-facing fallback framing ────────────────────────────────────────


def _report():
    from core.agent.models import WorkReportEntry

    return WorkReport(
        entries=(WorkReportEntry(tool_name="web_search", tool_input="q", observation="8 results", succeeded=True),)
    )


def test_fallback_framing_says_what_it_is():
    out = _report().render_user_fallback()
    assert out.startswith("I could not produce a clean final answer from these steps.")
    assert "Worker report — tool execution evidence:" in out


def test_strip_removes_framed_block_from_history():
    framed = _report().render_user_fallback()
    cleaned = strip_worker_reports(framed)
    assert "Worker report" not in cleaned
    assert "I could not produce a clean final answer" not in cleaned


def test_bare_block_still_strips():
    cleaned = strip_worker_reports(_report().render())
    assert "Worker report" not in cleaned
