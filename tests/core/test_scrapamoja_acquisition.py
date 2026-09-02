"""Scrapamoja stealth-render acquisition strategy (LocalMind side).

Covers capability detection and the subprocess sentinel-parsing without any
network or a real scrapamoja install (the live end-to-end is exercised
separately). scrapamoja is an EXTERNAL project called via subprocess in its own
venv, so LocalMind only needs to: find it, invoke it, and parse the
@@RENDER_JSON@@ sentinel line out of log-noisy stdout.
"""

from __future__ import annotations

import json

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
