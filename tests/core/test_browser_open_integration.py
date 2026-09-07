"""Tool-level integration for the browse open path, using a FAKE agent-browser
binary (real Chromium isn't available in CI / on every dev box).

Verifies the browser_agent 'open' action end-to-end through the slowness fix
(B-2026-09-01): navigate (open) + rendered-text extraction (eval) + ToolResult
assembly still work with start_new_session=True, and page text comes back as
evidence (not left in the browser window). Pairs with
test_browser_cmd_timeout.py, which covers the hang-bounded timeout path.
"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

import tools.browser_agent as ba


_FAKE_BODY = """import sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "open":
    print("navigated")
elif cmd == "eval":
    # agent-browser prints the eval result JSON-quoted; the tool unwraps one layer.
    print('"Example Domain\\nThis domain is for use in examples."')
else:
    print("")
sys.exit(0)
"""


@pytest.fixture()
def fake_agent_browser(tmp_path, monkeypatch):
    # Platform-executable fake: CreateProcess cannot exec a POSIX shebang
    # script (WinError 193), so on Windows the fake is a .cmd shim the OS
    # resolves natively — mirroring how the real npm-installed agent-browser
    # ships as a .cmd there.
    if sys.platform == "win32":
        # A .cmd shim can't carry a multi-line -c body through cmd.exe
        # quoting — write the fake logic as its own file and let the shim
        # hand every argument to it.
        logic = tmp_path / "agent-browser-fake.py"
        logic.write_text(_FAKE_BODY, encoding="utf-8")
        script = tmp_path / "agent-browser.cmd"
        script.write_text(f'@echo off\r\n"{sys.executable}" "{logic}" %*\r\n', encoding="utf-8")
    else:
        script = tmp_path / "agent-browser"
        script.write_text(f"#!{sys.executable}\n{_FAKE_BODY}", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setattr(ba, "_AGENT_BROWSER_BIN", str(script))
    monkeypatch.setattr(ba, "BROWSER_AVAILABLE", True)
    return script


@pytest.mark.asyncio
async def test_open_returns_page_text_as_evidence(fake_agent_browser):
    result = await ba.browser_agent(json.dumps({"action": "open", "url": "https://example.com"}))
    assert result.success is True
    assert "Example Domain" in result.content
    # extraction populated the evidence, not "no text content was extracted"
    assert "no text content was extracted" not in result.content
    assert result.metadata.get("content_chars", 0) > 0


@pytest.mark.asyncio
async def test_open_requires_url(fake_agent_browser):
    result = await ba.browser_agent(json.dumps({"action": "open"}))
    assert result.success is False
    assert result.error_type == "missing_url"
