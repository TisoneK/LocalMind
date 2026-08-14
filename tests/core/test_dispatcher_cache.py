'''Session 135 regression tests — dispatcher plan cache.

Repeated/near-duplicate requests (same normalized message + same recent
intent-history context) reuse the previous routing plan and SKIP the
capability-inference LLM call entirely. The cache is module-level (the
engine constructs a fresh ThinkingDispatcher per request) and only stores
REAL LLM-produced plans (fallback plans return before the store point).

These tests assert the contract: a second identical dispatch must not call
the adapter, the key is context-sensitive (intent history), TTL expires,
entries are bounded, attachments never cache, and a cache hit yields a
usable plan + the same obs events as the normal path.
'''

from __future__ import annotations

import asyncio

import pytest
from core import thinking_dispatcher as td
from core.models import StreamChunk
from core.obs import ObsCollector

_CAPABILITY_JSON = (
    '{"capabilities":["web_search"],"flags":{"requires_grounding":true,'
    '"requires_tools":true,"requires_planning":false,"requires_memory":false,'
    '"requires_reasoning":false,"requires_execution":false,'
    '"requires_file_access":false,"realtime_sensitive":true},'
    '"execution_mode":"single_tool","safety_level":"low","confidence":0.9,'
    '"primary_domain":"web_search",'
    '"reformulated_query":"kitengela weather today",'
    '"acknowledgement":"Searching the web for that...",'
    '"execution_plan":{"steps":[]}}'
)

_LOW_CONF_JSON = _CAPABILITY_JSON.replace('"confidence":0.9', '"confidence":0.2')


class CountingJSONAdapter:
    """Adapter that counts chat() calls and yields a valid capability JSON."""

    def __init__(self):
        self.chat_calls = 0
        self.payload = _CAPABILITY_JSON

    async def chat(self, messages, temperature=0.7, **kwargs):
        self.chat_calls += 1
        yield StreamChunk(text=self.payload)


async def _collect(dispatcher, message, intent_history=None, has_attachment=False):
    items = []
    async for item in dispatcher.dispatch(
        message=message,
        history=[],
        memory_facts=[],
        has_attachment=has_attachment,
        obs=ObsCollector(),
        session_id="test-session",
        intent_history=intent_history,
    ):
        items.append(item)
    return items


def _plans(items):
    return [i for i in items if not isinstance(i, StreamChunk)]


@pytest.fixture(autouse=True)
def _clear_cache():
    td._PLAN_CACHE.clear()
    yield
    td._PLAN_CACHE.clear()


@pytest.mark.asyncio
async def test_repeat_request_skips_llm_call():
    # NB: weather phrasing is now a zero-LLM signal (Session 195) — it would
    # never reach the LLM, so this cache contract is exercised with a
    # non-signal research question (same precedent as the Session 149 git
    # signal note below).
    adapter = CountingJSONAdapter()
    d = td.ThinkingDispatcher(adapter)
    await _collect(d, "explain how quantum computing differs from classical computing")
    assert adapter.chat_calls == 1

    # Identical message again — the LLM call is skipped entirely.
    await _collect(d, "explain how quantum computing differs from classical computing")
    assert adapter.chat_calls == 1, "repeat request must not re-call the LLM"


@pytest.mark.asyncio
async def test_near_duplicate_phrasing_hits_cache():
    # NB: this fixture used to be "Check git status!!" but the Session 149
    # git-phrasing signal now routes ANY git-anchored message through the
    # zero-LLM signal fast path (which correctly bypasses the cache). Use a
    # non-signal message so this test exercises the cache normalization.
    adapter = CountingJSONAdapter()
    d = td.ThinkingDispatcher(adapter)
    await _collect(d, "What is the latest news on quantum computing?")
    assert adapter.chat_calls == 1

    # Near-duplicate (case/whitespace/punctuation) must reuse the plan.
    items = await _collect(d, "what  is the latest news on  quantum computing")
    assert adapter.chat_calls == 1
    plans = _plans(items)
    assert plans, "cache hit must still yield an OrchestrationPlan"
    assert plans[0].profile.primary_intent().value == "web_search"


@pytest.mark.asyncio
async def test_intent_history_disambiguates_key():
    adapter = CountingJSONAdapter()
    d = td.ThinkingDispatcher(adapter)
    await _collect(d, "show me the results", intent_history=["shell"])
    assert adapter.chat_calls == 1

    # Same words but a different routing context — must MISS the cache.
    await _collect(d, "show me the results", intent_history=["chat"])
    assert adapter.chat_calls == 2

    # Same context again — hits.
    await _collect(d, "show me the results", intent_history=["chat"])
    assert adapter.chat_calls == 2


@pytest.mark.asyncio
async def test_attachment_handled_by_signal_path_not_cache():
    # Attachments are routed by signal detection (FILE_READ fast path)
    # BEFORE the cache / LLM — so the adapter is never called even the
    # first time. The cache simply has no role for attachments.
    adapter = CountingJSONAdapter()
    d = td.ThinkingDispatcher(adapter)
    items = await _collect(d, "analyze this file", has_attachment=True)
    assert adapter.chat_calls == 0
    assert _plans(items), "signal-detected attachment plan still yielded"
    assert len(td._PLAN_CACHE) == 0, "attachments must never populate the cache"


@pytest.mark.asyncio
async def test_cache_hit_emits_same_obs_events(monkeypatch):
    adapter = CountingJSONAdapter()
    d = td.ThinkingDispatcher(adapter)
    obs = ObsCollector()
    items = []
    async for item in d.dispatch(
        message="what time is it in nairobi",
        history=[],
        memory_facts=[],
        has_attachment=False,
        obs=obs,
        session_id="s1",
    ):
        items.append(item)

    obs2 = ObsCollector()
    items2 = []
    async for item in d.dispatch(
        message="what time is it in nairobi",
        history=[],
        memory_facts=[],
        has_attachment=False,
        obs=obs2,
        session_id="s1",
    ):
        items2.append(item)

    hit_events = {e.type for e in obs2.history()}
    assert "dispatcher_cache_hit" in hit_events
    assert "intent_classified" in hit_events
    assert "dispatcher_complete" in hit_events
    # The cached plan is a fresh deep copy, not the stored object.
    assert _plans(items2)[0] is not _plans(items)[0]


@pytest.mark.asyncio
async def test_ttl_expiry_forces_reclassification():
    td._PLAN_CACHE.ttl_seconds = 0.05
    try:
        adapter = CountingJSONAdapter()
        d = td.ThinkingDispatcher(adapter)
        await _collect(d, "top stories today")
        assert adapter.chat_calls == 1

        await asyncio.sleep(0.12)  # let the entry expire
        await _collect(d, "top stories today")
        assert adapter.chat_calls == 2, "expired entry must be recomputed"
    finally:
        td._PLAN_CACHE.ttl_seconds = 300.0


@pytest.mark.asyncio
async def test_low_confidence_plan_never_cached():
    """Parsed-but-garbage low-confidence plans must NOT populate the cache."""
    adapter = CountingJSONAdapter()
    adapter.payload = _LOW_CONF_JSON
    d = td.ThinkingDispatcher(adapter)
    await _collect(d, "explain how quantum computing differs from classical computing")
    assert adapter.chat_calls == 1
    assert len(td._PLAN_CACHE) == 0, "low-confidence plan must not be cached"

    # Same message again — must re-run the LLM (nothing was cached).
    await _collect(d, "explain how quantum computing differs from classical computing")
    assert adapter.chat_calls == 2


@pytest.mark.asyncio
async def test_cache_is_bounded():
    td._PLAN_CACHE.max_entries = 4
    try:
        adapter = CountingJSONAdapter()
        d = td.ThinkingDispatcher(adapter)
        for i in range(10):
            await _collect(d, f"distinct message number {i}")
        assert len(td._PLAN_CACHE) <= 4
    finally:
        td._PLAN_CACHE.max_entries = 64
