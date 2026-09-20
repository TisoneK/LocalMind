"""A site that failed is not fetched again for a while: the agent is told to use another source."""

import pytest
from core.models import RiskLevel, ToolResult
from tools import web_fetch as wf


def failing(error_type, status=None, msg="boom"):
    return ToolResult(
        content=msg, risk=RiskLevel.LOW, source="web_fetch", success=False,
        error_type=error_type, error_message=msg, metadata={"status_code": status} if status else {},
    )


@pytest.fixture(autouse=True)
def _clean():
    wf.forget_failed_sources()
    yield
    wf.forget_failed_sources()


@pytest.mark.asyncio
async def test_a_host_that_refused_is_not_retried_and_the_agent_is_told_to_switch(monkeypatch):
    calls = []

    async def fake(url):
        calls.append(url)
        return failing("http_error", 403, "HTTP 403")

    monkeypatch.setattr(wf, "_fetch_page", fake)
    first = await wf.web_fetch("https://www.livescore.com/en/")
    again = await wf.web_fetch("https://livescore.com/en/football/")
    assert not first.success and not again.success
    assert calls == ["https://www.livescore.com/en/"]  # the second call never went out
    assert again.error_type == "source_failed_earlier"
    assert "different source" in again.content


@pytest.mark.asyncio
async def test_a_404_only_blocks_that_page_not_the_site(monkeypatch):
    async def fake(url):
        return failing("http_error", 404, "HTTP 404") if url.endswith("/gone") else ToolResult(
            content="ok", risk=RiskLevel.LOW, source="web_fetch", success=True
        )

    monkeypatch.setattr(wf, "_fetch_page", fake)
    await wf.web_fetch("https://site.example/gone")
    assert (await wf.web_fetch("https://site.example/gone")).error_type == "source_failed_earlier"
    assert (await wf.web_fetch("https://site.example/other")).success


@pytest.mark.asyncio
async def test_other_hosts_and_successes_are_unaffected(monkeypatch):
    async def fake(url):
        return failing("timeout") if "slow" in url else ToolResult(content="ok", risk=RiskLevel.LOW, source="web_fetch", success=True)

    monkeypatch.setattr(wf, "_fetch_page", fake)
    await wf.web_fetch("https://slow.example/a")
    assert (await wf.web_fetch("https://fast.example/a")).success
    assert (await wf.web_fetch("https://slow.example/b")).error_type == "source_failed_earlier"


@pytest.mark.asyncio
async def test_a_failure_is_forgotten_after_the_window(monkeypatch):
    async def fake(url):
        return failing("connection_failed")

    monkeypatch.setattr(wf, "_fetch_page", fake)
    await wf.web_fetch("https://down.example/")
    for key in list(wf._failed_sources):
        when, why = wf._failed_sources[key]
        wf._failed_sources[key] = (when - wf._SOURCE_FAILURE_TTL_S - 1, why)
    assert (await wf.web_fetch("https://down.example/")).error_type == "connection_failed"
