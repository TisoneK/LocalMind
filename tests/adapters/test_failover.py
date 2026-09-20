"""Provider limits are absorbed by the agent: the turn moves to another provider, unseen."""

import pytest
from adapters.failover import FailoverAdapter, ProviderHealth
from core.models import StreamChunk

RATE = "zen returned 429: rate limit exceeded, try again later"
PAID = 'bankofai returned 402: {"error":{"message":"insufficient balance"}}'
CTX = "zai returned 400: maximum context length exceeded, too many tokens"


class Fake:
    def __init__(self, name, *, error=None, raises=None, text="hello from "):
        self.name, self.error, self.raises, self.text = name, error, raises, text
        self.calls = 0
        self.context_window = 1234

    async def chat(self, messages, temperature=0.7, **kw):
        self.calls += 1
        if self.raises:
            raise self.raises
        if self.error:
            yield StreamChunk(text="", error=self.error, done=True)
            return
        yield StreamChunk(text=self.text + self.name)
        yield StreamChunk(text="", done=True)

    async def chat_with_tools(self, messages, tools, temperature=0.7, intent="chat", tool_choice=None):
        return self.chat(messages)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def build(primary, others, health=None):
    adapters = {o.name: o for o in others}
    return FailoverAdapter(
        primary,
        primary.name,
        candidates=lambda _p: [(o.name, "") for o in others],
        make_adapter=lambda n, m: adapters[n],
        health=health or ProviderHealth(),
        retry_delays=(),
    )


async def drain(stream):
    return [c async for c in stream]


async def text_of(stream):
    return "".join(c.text for c in await drain(stream))


@pytest.mark.asyncio
async def test_rate_limited_primary_is_replaced_without_an_error():
    a, b = Fake("zen", error=RATE), Fake("groq")
    out = await drain(await build(a, [b]).chat_with_tools([], []))
    assert [c.error for c in out if c.error] == []
    assert "".join(c.text for c in out) == "hello from groq"


@pytest.mark.asyncio
async def test_payment_and_raised_errors_also_fail_over():
    a, b = Fake("bankofai", error=PAID), Fake("zai", raises=ConnectionError("boom")),
    c = Fake("groq")
    out = await text_of(await build(a, [b, c]).chat_with_tools([], []))
    assert out == "hello from groq"


@pytest.mark.asyncio
async def test_every_candidate_failing_surfaces_the_original_error():
    a, b = Fake("zen", error=RATE), Fake("groq", error=PAID)
    out = await drain(await build(a, [b]).chat_with_tools([], []))
    assert len(out) == 1 and out[0].error == PAID


@pytest.mark.asyncio
async def test_context_overflow_is_not_a_provider_problem():
    a, b = Fake("zai", error=CTX), Fake("groq")
    out = await drain(await build(a, [b]).chat_with_tools([], []))
    assert out[0].error == CTX and b.calls == 0


@pytest.mark.asyncio
async def test_failed_provider_is_skipped_until_its_cooldown_ends():
    clock, health = Clock(), None
    health = ProviderHealth(clock)
    a, b = Fake("zen", error=RATE), Fake("groq")
    fo = build(a, [b], health)
    await drain(await fo.chat_with_tools([], []))
    await drain(await fo.chat_with_tools([], []))
    assert a.calls == 1  # second call went straight to groq
    clock.t = 61.0
    a.error = None
    assert await text_of(await fo.chat_with_tools([], [])) == "hello from zen"


@pytest.mark.asyncio
async def test_healthy_primary_is_used_and_attributes_pass_through():
    a, b = Fake("zen"), Fake("groq")
    fo = build(a, [b])
    assert await text_of(fo.chat([])) == "hello from zen"
    assert b.calls == 0 and fo.context_window == 1234


@pytest.mark.asyncio
async def test_single_provider_retries_before_giving_up():
    a = Fake("zen", error=RATE)
    fo = FailoverAdapter(a, "zen", candidates=lambda _p: [], health=ProviderHealth(), retry_delays=(0, 0))
    out = await drain(await fo.chat_with_tools([], []))
    assert a.calls == 3 and out[0].error == RATE


@pytest.mark.asyncio
async def test_tool_call_results_pass_through_untouched():
    class Tooly(Fake):
        async def chat_with_tools(self, *a, **k):
            return {"tool": "x"}

    assert await build(Tooly("zen"), []).chat_with_tools([], []) == {"tool": "x"}


def test_local_model_never_falls_back_to_cloud_uninvited(monkeypatch):
    from adapters.failover import fallback_candidates
    from core.config import settings

    monkeypatch.setattr(type(settings), "get_api_key", lambda self, p: "k")
    assert fallback_candidates("ollama") == []
    assert len(fallback_candidates("zen")) > 0


def drain_status(fo):
    out = []
    while not fo.status_queue.empty():
        out.append(fo.status_queue.get_nowait())
    return out


@pytest.mark.asyncio
async def test_user_is_told_what_is_happening_while_it_switches():
    a, b = Fake("zen", error=RATE), Fake("groq")
    fo = build(a, [b])
    await drain(await fo.chat_with_tools([], []))
    said = drain_status(fo)
    assert len(said) == 2
    assert "busy" in said[0] and "switching to" in said[0]
    assert said[1].startswith("Continuing with")


@pytest.mark.asyncio
async def test_lone_provider_waits_the_window_it_named_and_counts_down(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("adapters.failover.asyncio.sleep", fake_sleep)
    a = Fake("zen", error="zen returned 429: rate limit, please retry in 3s")
    fo = FailoverAdapter(a, "zen", candidates=lambda _p: [], health=ProviderHealth())
    await drain(await fo.chat_with_tools([], []))
    said = drain_status(fo)
    assert a.calls == 3
    assert sum(slept) >= 3
    assert any("retrying in 3s" in m for m in said) and any("retrying in 2s" in m for m in said)


@pytest.mark.asyncio
async def test_a_long_window_is_not_waited_and_sets_the_cooldown():
    clock = Clock()
    health = ProviderHealth(clock)
    a = Fake("zen", error="zen returned 429: rate limit, please retry in 300s")
    fo = FailoverAdapter(a, "zen", candidates=lambda _p: [], health=health)
    out = await drain(await fo.chat_with_tools([], []))
    assert a.calls == 1 and out[0].error
    clock.t = 200.0
    assert health.is_down("zen")  # cooled for the 300s it asked for, not the 60s default
    clock.t = 302.0
    assert not health.is_down("zen")


@pytest.mark.asyncio
async def test_streaming_chat_yields_the_progress_lines_before_the_reply():
    a, b = Fake("zen", error=RATE), Fake("groq")
    out = await drain(build(a, [b]).chat([]))
    statuses = [c.status for c in out if c.status]
    assert any("switching to" in s for s in statuses)
    assert "".join(c.text for c in out) == "hello from groq"
