"""Older tool results are stubbed only when they would crowd the window.

Live capture (glm-4.5-flash and DeepSeek, fixed fixture): after a second tool ran,
the first tool's 5-entry folder listing (~475 chars) was cut to head + tail
mid-list ("delta ... [omitted] ... on/ gamma"), so one model invented a folder and
the other reported four. A multi-part request needs every result at answer time."""
from __future__ import annotations

from core.context_compactor import (
    _STUB_MARKER,
    STUB_MAX_CHARS,
    TOOL_RESULT_BUDGET_CHARS,
    simplify_tool_results,
)

LISTING = (
    "[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
    "Contents of /Users/bao/s024-fixture/projects — 5 entries:\n"
    + "".join(f"  📁 {n}/ · 2026-09-20 01:32\n" for n in ("alpha", "beta", "delta", "epsilon", "gamma"))
    + "Listed 5 of 5 seen · scan complete · names only — no file contents are ever returned\n"
    "[END TOOL OUTPUT — do NOT invent or add items not shown above]"
)


def _tool(i, text):
    return [{"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": text}]


def _conv(*texts):
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "do A, then B, then C"}]
    for i, t in enumerate(texts):
        msgs += _tool(i, t)
    return msgs


def _tools(msgs):
    return [m["content"] for m in msgs if m["role"] == "tool"]


def test_the_listing_is_bigger_than_the_stub_threshold():
    # the live case: over the per-result threshold, well under the total budget
    assert STUB_MAX_CHARS < len(LISTING) < TOOL_RESULT_BUDGET_CHARS


def test_a_multi_part_run_keeps_every_result_when_it_fits_the_budget():
    msgs = _conv(LISTING, "fix: handle empty config gracefully (#42)", "12")
    out = simplify_tool_results(msgs, budget_chars=TOOL_RESULT_BUDGET_CHARS)
    assert _tools(out) == _tools(msgs)
    assert all(_STUB_MARKER not in t for t in _tools(out))
    assert "epsilon" in _tools(out)[0]


def test_without_a_budget_the_old_unconditional_behaviour_is_unchanged():
    out = simplify_tool_results(_conv(LISTING, "b", "c"))
    assert _STUB_MARKER in _tools(out)[0] and "epsilon" not in _tools(out)[0]


def test_over_budget_the_oldest_oversized_result_shrinks_first_and_only_as_needed():
    big = "W" * 6000
    msgs = _conv(big, "X" * 3000, "Y" * 2000)  # 11k total > 8k budget
    out = simplify_tool_results(msgs, budget_chars=8000)
    t = _tools(out)
    assert _STUB_MARKER in t[0] and len(t[0]) < 1000       # oldest cut
    assert t[1] == "X" * 3000 and t[2] == "Y" * 2000       # stopped once it fit
    assert sum(len(x) for x in t) <= 8000


def test_the_newest_result_is_never_stubbed_even_over_budget():
    msgs = _conv("A" * 500, "N" * 20000)
    out = simplify_tool_results(msgs, budget_chars=8000)
    assert _tools(out)[1] == "N" * 20000


def test_small_results_are_never_stubbed_and_stubbing_is_idempotent():
    msgs = _conv("tiny", "Z" * 9000, "last")
    once = simplify_tool_results(msgs, budget_chars=1000)
    assert _tools(once)[0] == "tiny"
    assert simplify_tool_results(once, budget_chars=1000) == once


def test_the_stub_does_not_point_at_output_that_no_longer_exists():
    assert "see earlier" not in _STUB_MARKER.lower()
    assert "omitted" in _STUB_MARKER


def test_message_structure_and_tool_call_ids_survive():
    msgs = _conv("A" * 9000, "B" * 9000, "C" * 100)
    out = simplify_tool_results(msgs, budget_chars=8000)
    assert [m.get("tool_call_id") for m in out] == [m.get("tool_call_id") for m in msgs]
    assert len(out) == len(msgs)
