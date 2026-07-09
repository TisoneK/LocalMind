"""
Browser Agent tool — real browser interaction via agent-browser CLI.

Registered as Intent.BROWSE in the tool registry.

Unlike web_fetch (which only fetches static HTML), this tool drives a real
headless browser that can:
  - Navigate to pages (open, back, forward, reload)
  - Take snapshots of interactive elements (buttons, inputs, links)
  - Click, fill forms, scroll, take screenshots
  - Execute JavaScript
  - Handle authentication and cookies

This closes the gap between "I can search the web" and "I can interact
with the web" — the agent can now log into sites, fill forms, click
buttons, and read dynamic content that requires JavaScript execution.

Usage from the agent loop:
  The LLM emits a JSON action describing what to do:
    {"action": "open", "url": "https://example.com"}
    {"action": "snapshot"}
    {"action": "click", "ref": "@e1"}
    {"action": "fill", "ref": "@e2", "value": "hello"}
    {"action": "scroll", "direction": "down", "amount": 500}
    {"action": "screenshot", "path": "/tmp/page.png"}
    {"action": "text", "ref": "@e3"}
    {"action": "eval", "script": "document.title"}
    {"action": "close"}

The tool parses the action, runs the corresponding agent-browser command,
and returns the output as a ToolResult.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# Check if agent-browser is available
_AGENT_BROWSER_BIN = shutil.which("agent-browser")
BROWSER_AVAILABLE = _AGENT_BROWSER_BIN is not None

# Default timeout for browser commands (seconds)
_BROWSER_TIMEOUT = 30

# Max output length to prevent context bloat
_MAX_OUTPUT = 8000


async def _run_browser_cmd(args: list[str], timeout: int = _BROWSER_TIMEOUT) -> tuple[int, str, str]:
    """Run an agent-browser command and return (exit_code, stdout, stderr)."""
    if not BROWSER_AVAILABLE:
        return 1, "", "agent-browser is not installed. Run: npm install -g agent-browser && agent-browser install"

    cmd = [_AGENT_BROWSER_BIN] + args
    logger.info("[browser_agent] running: %s", " ".join(cmd[:5]))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return proc.returncode or 0, stdout, stderr
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 1, "", f"Browser command timed out after {timeout}s"
    except Exception as e:
        return 1, "", f"Browser command failed: {e}"


def _parse_action(message: str) -> dict | None:
    """Parse the browser action from the message.

    The message may be:
    - A JSON object: {"action": "open", "url": "..."}
    - A natural language instruction: "open https://example.com"
    - A URL by itself: "https://example.com"
    """
    message = message.strip()

    # Try JSON parse first
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "action" in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to extract JSON from the message
    json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', message, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if "action" in data:
                return data
        except json.JSONDecodeError:
            pass

    # Natural language patterns
    msg_lower = message.lower()

    # URL by itself → open
    url_match = re.search(r'https?://\S+', message)
    if url_match and not msg_lower.startswith(("click", "fill", "scroll", "snapshot", "screenshot", "close", "back", "forward", "eval")):
        return {"action": "open", "url": url_match.group(0)}

    # "open <url>"
    open_match = re.match(r'open\s+(https?://\S+)', msg_lower)
    if open_match:
        return {"action": "open", "url": open_match.group(1)}

    # "snapshot" or "screenshot"
    if "snapshot" in msg_lower:
        return {"action": "snapshot"}
    if "screenshot" in msg_lower:
        return {"action": "screenshot"}

    # "click @e1"
    click_match = re.search(r'click\s+(@\w+)', msg_lower)
    if click_match:
        return {"action": "click", "ref": click_match.group(1)}

    # "fill @e1 with text"
    fill_match = re.search(r'fill\s+(@\w+)\s+(?:with\s+)?["\']?(.+?)["\']?\s*$', message, re.IGNORECASE)
    if fill_match:
        return {"action": "fill", "ref": fill_match.group(1), "value": fill_match.group(2)}

    # "close"
    if "close" in msg_lower and "browser" in msg_lower:
        return {"action": "close"}
    if msg_lower.strip() == "close":
        return {"action": "close"}

    # "back" / "forward"
    if msg_lower.strip() == "back":
        return {"action": "back"}
    if msg_lower.strip() == "forward":
        return {"action": "forward"}

    return None


async def browser_agent(message: str) -> ToolResult:
    """
    Execute a browser interaction via agent-browser.

    Parses the action from the message and runs the corresponding
    agent-browser CLI command.
    """
    if not BROWSER_AVAILABLE:
        return ToolResult(
            content=(
                "Browser agent is not available. Install it with:\n"
                "  npm install -g agent-browser\n"
                "  agent-browser install\n\n"
                "Then restart LocalMind."
            ),
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="not_installed",
            error_message="agent-browser CLI not found",
        )

    action = _parse_action(message)
    if not action:
        return ToolResult(
            content=(
                "Could not parse browser action. Use one of:\n"
                '  {"action": "open", "url": "https://example.com"}\n'
                '  {"action": "snapshot"}\n'
                '  {"action": "click", "ref": "@e1"}\n'
                '  {"action": "fill", "ref": "@e2", "value": "text"}\n'
                '  {"action": "scroll", "direction": "down", "amount": 500}\n'
                '  {"action": "screenshot"}\n'
                '  {"action": "text", "ref": "@e3"}\n'
                '  {"action": "eval", "script": "document.title"}\n'
                '  {"action": "close"}\n\n'
                "Or use natural language: 'open https://example.com', 'click @e1', 'snapshot'"
            ),
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="parse_error",
            error_message="Could not parse browser action from message",
        )

    act = action.get("action", "").lower()
    args: list[str] = []
    risk = RiskLevel.LOW

    if act == "open":
        url = action.get("url", "")
        if not url:
            return ToolResult(content="No URL provided for 'open' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_url")
        args = ["open", url]
        risk = RiskLevel.MEDIUM  # Navigating to a URL is medium risk

    elif act == "snapshot":
        interactive = action.get("interactive", True)
        args = ["snapshot"]
        if interactive:
            args.append("-i")  # Interactive elements only

    elif act == "click":
        ref = action.get("ref", "")
        if not ref:
            return ToolResult(content="No ref provided for 'click' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_ref")
        args = ["click", ref]
        risk = RiskLevel.MEDIUM

    elif act == "fill":
        ref = action.get("ref", "")
        value = action.get("value", "")
        if not ref:
            return ToolResult(content="No ref provided for 'fill' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_ref")
        args = ["fill", ref, value]
        risk = RiskLevel.MEDIUM

    elif act == "type":
        ref = action.get("ref", "")
        value = action.get("value", "")
        if not ref:
            return ToolResult(content="No ref provided for 'type' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_ref")
        args = ["type", ref, value]

    elif act == "press":
        key = action.get("key", action.get("value", ""))
        if not key:
            return ToolResult(content="No key provided for 'press' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_key")
        args = ["press", key]

    elif act == "scroll":
        direction = action.get("direction", "down")
        amount = str(action.get("amount", 500))
        args = ["scroll", direction, amount]

    elif act == "scrollintoview":
        ref = action.get("ref", "")
        if not ref:
            return ToolResult(content="No ref provided.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_ref")
        args = ["scrollintoview", ref]

    elif act == "screenshot":
        path = action.get("path", "")
        full = action.get("full", False)
        args = ["screenshot"]
        if path:
            args.append(path)
        if full:
            args.append("--full")

    elif act == "text":
        ref = action.get("ref", "")
        if not ref:
            return ToolResult(content="No ref provided for 'text' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_ref")
        args = ["get", "text", ref]

    elif act == "url":
        args = ["get", "url"]

    elif act == "title":
        args = ["get", "title"]

    elif act == "eval":
        script = action.get("script", action.get("value", ""))
        if not script:
            return ToolResult(content="No script provided for 'eval' action.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_script")
        args = ["eval", script]
        risk = RiskLevel.HIGH  # JavaScript execution is high risk

    elif act == "back":
        args = ["back"]

    elif act == "forward":
        args = ["forward"]

    elif act == "reload":
        args = ["reload"]

    elif act == "close":
        args = ["close"]

    elif act == "wait":
        target = action.get("target", action.get("value", ""))
        if not target:
            return ToolResult(content="No wait target provided.", risk=RiskLevel.LOW,
                            source="browser_agent", success=False, error_type="missing_target")
        args = ["wait", target]

    else:
        return ToolResult(
            content=f"Unknown browser action: '{act}'. Supported: open, snapshot, click, fill, type, press, scroll, scrollintoview, screenshot, text, url, title, eval, back, forward, reload, close, wait",
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="unknown_action",
            error_message=f"Unknown action: {act}",
        )

    # Run the command
    exit_code, stdout, stderr = await _run_browser_cmd(args)

    # Build result
    output = stdout.strip()
    if not output and stderr.strip():
        output = stderr.strip()
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + f"\n\n[... output truncated, {len(stdout)} total chars]"

    success = exit_code == 0
    if not success and stderr:
        output = f"Error: {stderr.strip()}\n\n{output}"

    return ToolResult(
        content=f"Browser action: {act}\n\n{output}" if output else f"Browser action: {act} (no output)",
        risk=risk,
        source="browser_agent",
        success=success,
        metadata={"action": act, "exit_code": exit_code},
    )


# Register the tool
register_tool(
    Intent.BROWSE,
    browser_agent,
    description="Real browser interaction — navigate, click, fill forms, scroll, screenshot, execute JS. Uses agent-browser CLI.",
    cost=0.5,
    latency_ms=3000,
    parallelizable=False,  # Browser is stateful — never run concurrently
)
