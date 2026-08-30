"""Tests for the Browser Agent tool.

The tests mock the agent-browser subprocess so they run without Chromium or the
optional agent-browser CLI installed. They lock the action-to-command contract
used by the BrowserAgent and the model-facing tool definition.
"""

from __future__ import annotations

import importlib
import json

import pytest

from core.models import Intent, RiskLevel

browser_module = importlib.import_module("tools.browser_agent")


@pytest.fixture
def mock_browser(monkeypatch):
    """Make the optional browser executable appear available and capture args."""
    calls: list[list[str]] = []

    async def _run(args: list[str], timeout: int = 30):
        calls.append(args)
        return 0, "mock browser output", ""

    monkeypatch.setattr(browser_module, "BROWSER_AVAILABLE", True)
    monkeypatch.setattr(browser_module, "_run_browser_cmd", _run)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_args", "expected_risk"),
    [
        ({"action": "dom", "selector": "#main"}, ["get", "html", "#main"], RiskLevel.MEDIUM),
        ({"action": "dom"}, ["get", "html", "html"], RiskLevel.MEDIUM),
        (
            {"action": "network", "filter": "api", "type": "xhr", "method": "GET", "status": "2xx"},
            ["network", "requests", "--filter", "api", "--type", "xhr", "--method", "GET", "--status", "2xx"],
            RiskLevel.MEDIUM,
        ),
        ({"action": "network", "clear": True}, ["network", "requests", "--clear"], RiskLevel.MEDIUM),
        ({"action": "console", "json": True, "clear": True}, ["console", "--clear", "--json"], RiskLevel.MEDIUM),
    ],
)
async def test_inspection_actions_map_to_agent_browser_commands(
    mock_browser, payload, expected_args, expected_risk
):
    """DOM, network, and console actions use the documented CLI commands."""
    result = await browser_module.browser_agent(json.dumps(payload))

    assert result.success is True
    assert result.risk == expected_risk
    assert mock_browser == [expected_args]
    assert result.metadata["action"] == payload["action"]


@pytest.mark.asyncio
async def test_browser_output_is_bounded(mock_browser, monkeypatch):
    """Large inspection output is capped before it reaches model context."""
    async def _large_output(args: list[str], timeout: int = 30):
        return 0, "x" * 10_000, ""

    monkeypatch.setattr(browser_module, "_run_browser_cmd", _large_output)
    result = await browser_module.browser_agent(json.dumps({"action": "dom"}))

    assert result.success is True
    assert len(result.content) < 10_000
    assert "output truncated" in result.content


@pytest.mark.asyncio
async def test_failed_browser_output_is_bounded(mock_browser, monkeypatch):
    """stderr cannot bypass the browser output cap on command failure."""
    async def _failed_output(args: list[str], timeout: int = 30):
        return 1, "stdout", "e" * 10_000

    monkeypatch.setattr(browser_module, "_run_browser_cmd", _failed_output)
    result = await browser_module.browser_agent(json.dumps({"action": "console"}))

    assert result.success is False
    assert len(result.content) <= browser_module._MAX_OUTPUT
    assert "browser output truncated" in result.content


@pytest.mark.asyncio
async def test_invalid_action_field_returns_structured_error(mock_browser):
    """Malformed model payloads fail cleanly instead of raising AttributeError."""
    result = await browser_module.browser_agent(json.dumps({"action": ["dom"]}))

    assert result.success is False
    assert result.error_type == "invalid_action"
    assert "non-empty string" in result.content
    assert mock_browser == []


def test_natural_language_inspection_actions_parse():
    """Common inspection requests are recognized without requiring JSON."""
    assert browser_module._parse_action("inspect the DOM") == {"action": "dom"}
    assert browser_module._parse_action("show network requests") == {"action": "network"}
    assert browser_module._parse_action("read console logs") == {"action": "console"}


def test_browse_tool_definition_exposes_inspection_actions():
    """The model-facing browse schema includes the upgraded capabilities."""
    from core.agent.loop import TOOL_DEFINITIONS, _extract_tool_input

    definitions = [td for td in TOOL_DEFINITIONS if td["function"]["name"] == "browse"]
    assert len(definitions) == 1
    params = definitions[0]["function"]["parameters"]
    assert "action" in params["required"]
    assert {"dom", "network", "console"}.issubset(set(params["properties"]["action"]["enum"]))
    assert json.loads(_extract_tool_input("browse", {"action": "console", "json": True})) == {
        "action": "console",
        "json": True,
    }


def test_browse_tool_is_registered():
    """BROWSE remains registered after the capability expansion."""
    from tools import _REGISTRY

    assert Intent.BROWSE in _REGISTRY
    assert "inspect DOM" in _REGISTRY[Intent.BROWSE]["description"]


# ── B-2026-08-30: open/read return page CONTENT as evidence ──────────────────


@pytest.mark.asyncio
async def test_open_navigates_and_returns_page_content(mock_browser):
    """`open` must navigate AND pull the page text back (persistent session), so
    the content reaches the agent as evidence instead of only the browser window."""
    result = await browser_module.browser_agent(
        json.dumps({"action": "open", "url": "https://wttr.in/Nairobi?format=j1"})
    )
    assert result.success is True
    assert "page content" in result.content.lower()
    assert "mock browser output" in result.content  # the extracted text
    assert result.metadata["content_chars"] > 0
    # two agent-browser commands: navigate, then extract text in the same session
    assert mock_browser[0] == ["open", "https://wttr.in/Nairobi?format=j1"]
    assert mock_browser[1][0] == "eval"


@pytest.mark.asyncio
async def test_read_reextracts_current_page_without_url(mock_browser):
    """`read` with no url just re-extracts the current page (one eval, no open)."""
    result = await browser_module.browser_agent(json.dumps({"action": "read"}))
    assert result.success is True
    assert "mock browser output" in result.content
    assert mock_browser == [["eval", "document.body ? document.body.innerText : ''"]]


@pytest.mark.asyncio
async def test_open_navigation_failure_is_reported(monkeypatch):
    """A failed navigation surfaces open_failed, not a false success."""
    async def _run(args, timeout: int = 30):
        return (1, "", "net::ERR_NAME_NOT_RESOLVED") if args[0] == "open" else (0, "x", "")

    monkeypatch.setattr(browser_module, "BROWSER_AVAILABLE", True)
    monkeypatch.setattr(browser_module, "_run_browser_cmd", _run)
    result = await browser_module.browser_agent(
        json.dumps({"action": "open", "url": "https://nope.invalid"})
    )
    assert result.success is False
    assert result.error_type == "open_failed"


@pytest.mark.asyncio
async def test_open_without_content_guides_fallback(monkeypatch):
    """When extraction yields nothing, open still succeeds and suggests snapshot/dom."""
    async def _run(args, timeout: int = 30):
        return (0, "", "") if args[0] == "eval" else (0, "navigated", "")

    monkeypatch.setattr(browser_module, "BROWSER_AVAILABLE", True)
    monkeypatch.setattr(browser_module, "_run_browser_cmd", _run)
    result = await browser_module.browser_agent(
        json.dumps({"action": "open", "url": "https://example.com"})
    )
    assert result.success is True
    assert result.metadata["content_chars"] == 0
    assert "snapshot" in result.content and "dom" in result.content


@pytest.mark.asyncio
async def test_extract_unwraps_json_quoted_eval_result(monkeypatch):
    """agent-browser may print eval output JSON-encoded; the raw text is returned."""
    async def _run(args, timeout: int = 30):
        return (0, '"{\\"temp_C\\": \\"18\\"}"', "") if args[0] == "eval" else (0, "ok", "")

    monkeypatch.setattr(browser_module, "BROWSER_AVAILABLE", True)
    monkeypatch.setattr(browser_module, "_run_browser_cmd", _run)
    text = await browser_module._extract_page_text()
    assert text == '{"temp_C": "18"}'


def test_read_action_parses_from_natural_language():
    assert browser_module._parse_action("read https://wttr.in/Nairobi?format=j1") == {
        "action": "read",
        "url": "https://wttr.in/Nairobi?format=j1",
    }
