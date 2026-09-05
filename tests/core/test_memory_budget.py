"""P0 Step 3 — Memory Retrieval Gate: the token-budget cap.

The Memory Composer already retrieves per-request, semantic top-K, and
relevance-thresholded; the missing piece was a TOKEN budget on the assembled
block (a fact COUNT cap alone lets a few long facts balloon the prompt). These
pin cap_facts_to_budget.
"""

from __future__ import annotations

from core.memory import _MEMORY_TOKEN_BUDGET, cap_facts_to_budget


def _tok(s: str) -> int:
    # Mirror the helper's chars/4 (+1 list-item framing) cost estimate.
    return max(1, len(s) // 4) + 1


def test_under_budget_keeps_all_facts():
    facts = ["short fact one", "short fact two", "short fact three"]
    assert cap_facts_to_budget(facts) == facts


def test_over_budget_trims_the_tail_keeping_priority_front():
    # Each fact ~40 tokens; a small budget keeps only the leading ones.
    facts = [f"fact number {i} " + "x" * 150 for i in range(10)]
    kept = cap_facts_to_budget(facts, budget_tokens=100)
    assert kept == facts[: len(kept)]  # a prefix — front-priority preserved
    assert len(kept) < len(facts)  # tail dropped
    total = sum(_tok(f) for f in kept)
    # Never exceeds budget except for the always-kept first fact.
    assert total <= 100 or len(kept) == 1


def test_single_over_budget_fact_is_never_dropped_to_empty():
    huge = "y" * 4000  # ~1000 tokens, well over the 500 budget
    assert cap_facts_to_budget([huge]) == [huge]


def test_empty_list():
    assert cap_facts_to_budget([]) == []


def test_default_budget_is_500():
    assert _MEMORY_TOKEN_BUDGET == 500
    # A realistic set of short facts sits comfortably under the default.
    facts = [f"the user prefers option {i}" for i in range(6)]
    assert cap_facts_to_budget(facts) == facts
