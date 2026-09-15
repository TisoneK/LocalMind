"""Scrapamoja stealth-render acquisition strategy (LocalMind side).

Covers capability detection and the subprocess sentinel-parsing without any
network or a real scrapamoja install (the live end-to-end is exercised
separately). scrapamoja is an EXTERNAL project called via subprocess in its own
venv, so LocalMind only needs to: find it, invoke it, and parse the
@@RENDER_JSON@@ sentinel line out of log-noisy stdout.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import core.web_acquisition as wa


def test_available_false_when_path_missing(monkeypatch, tmp_path):
    from core.config import settings
    monkeypatch.setattr(settings, "localmind_scrapamoja_path", str(tmp_path / "nope"), raising=False)
    assert wa._scrapamoja_paths() is None
    assert wa.scrapamoja_available() is False


def test_available_true_with_venv(monkeypatch, tmp_path):
    proj = tmp_path / "scrapamoja"
    (proj / ".venv" / "bin").mkdir(parents=True)
    (proj / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    from core.config import settings
    monkeypatch.setattr(settings, "localmind_scrapamoja_path", str(proj), raising=False)
    paths = wa._scrapamoja_paths()
    assert paths is not None
    assert paths[1] == str(proj)
    assert wa.scrapamoja_available() is True


class _FakeProc:
    def __init__(self, stdout: bytes):
        self._stdout = stdout
        self.returncode = 0

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        pass


@pytest.mark.asyncio
async def test_render_parses_sentinel_amid_log_noise(monkeypatch, tmp_path):
    proj = tmp_path / "scrapamoja"
    (proj / ".venv" / "bin").mkdir(parents=True)
    (proj / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    from core.config import settings
    monkeypatch.setattr(settings, "localmind_scrapamoja_path", str(proj), raising=False)

    payload = {"url": "u", "title": "Quotes", "text": "Einstein said things",
               "status": "ok", "method": "scrapamoja_stealth"}
    stdout = (
        "2026-01-01 [debug] Retry config registered\n"
        "2026-01-01 [info] Module registered\n"
        "@@RENDER_JSON@@ " + json.dumps(payload) + "\n"
    ).encode()

    async def _fake_exec(*a, **k):
        return _FakeProc(stdout)

    monkeypatch.setattr(wa.asyncio, "create_subprocess_exec", _fake_exec)
    r = await wa._scrapamoja_render("u")
    assert r.status is wa.AcquisitionStatus.SUCCESS
    assert r.acquisition_method is wa.AcquisitionMethod.SCRAPAMOJA_RENDER
    assert "Einstein" in r.content
    assert r.content.startswith("**Quotes**")


@pytest.mark.asyncio
async def test_render_empty_text_is_failure(monkeypatch, tmp_path):
    proj = tmp_path / "scrapamoja"
    (proj / ".venv" / "bin").mkdir(parents=True)
    (proj / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    from core.config import settings
    monkeypatch.setattr(settings, "localmind_scrapamoja_path", str(proj), raising=False)

    payload = {"url": "u", "title": "", "text": "", "status": "empty", "method": "x"}
    stdout = ("@@RENDER_JSON@@ " + json.dumps(payload) + "\n").encode()

    async def _fake_exec(*a, **k):
        return _FakeProc(stdout)

    monkeypatch.setattr(wa.asyncio, "create_subprocess_exec", _fake_exec)
    r = await wa._scrapamoja_render("u")
    assert r.status is wa.AcquisitionStatus.FAILED


@pytest.mark.asyncio
async def test_render_unavailable_returns_failure(monkeypatch, tmp_path):
    from core.config import settings
    monkeypatch.setattr(settings, "localmind_scrapamoja_path", str(tmp_path / "absent"), raising=False)
    r = await wa._scrapamoja_render("u")
    assert r.status is wa.AcquisitionStatus.FAILED
    assert "not available" in (r.error or "")


@pytest.mark.asyncio
async def test_web_research_runs_scrapamoja_at_most_once(monkeypatch):
    """Regression: the heavy stealth render must NOT run per
    source in web_research's multi-source loop (it stacked ~65s per thin source
    and blew whole turns past the provider rate limit). It runs at most ONCE, as
    a final fallback, after the cheap static+browser strategies fail on every
    source.
    """
    from unittest.mock import AsyncMock

    # search returns 3 sources
    search = MagicMock()
    search.success = True
    search.content = "\n".join(
        f"{i}. **S{i}**\n   https://s{i}.example.com/x\n   snippet" for i in range(1, 4)
    )
    # every static fetch returns a thin skeleton → escalates
    thin = MagicMock()
    thin.success = True
    thin.content = "Loading…"

    calls = {"scrapamoja": 0}

    async def _fake_render(url, timeout=None):
        calls["scrapamoja"] += 1
        return wa.WebResult(
            status=wa.AcquisitionStatus.FAILED, source=url,
            acquisition_method=wa.AcquisitionMethod.SCRAPAMOJA_RENDER, content="",
            error="blocked",
        )

    monkeypatch.setattr("tools.web_search.web_search", AsyncMock(return_value=search))
    monkeypatch.setattr("tools.web_fetch.web_fetch", AsyncMock(return_value=thin))
    monkeypatch.setattr("tools.browser_agent._run_browser_cmd",
                        AsyncMock(return_value=(1, "", "browser failed")))
    monkeypatch.setattr(wa, "scrapamoja_available", lambda: True)
    monkeypatch.setattr(wa, "_scrapamoja_render", _fake_render)

    await wa.web_research("some query", max_sources=3)
    assert calls["scrapamoja"] <= 1, f"scrapamoja ran {calls['scrapamoja']}x — must be at most once"
