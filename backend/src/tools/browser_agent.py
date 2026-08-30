"""
Browser Agent tool — real browser interaction via agent-browser CLI.

Registered as Intent.BROWSE in the tool registry.

Unlike web_fetch (which only fetches static HTML), this tool drives a real
headless browser that can:
  - Navigate to pages (open, back, forward, reload)
  - Take snapshots of interactive elements (buttons, inputs, links)
  - Inspect rendered DOM/HTML, network requests, and console messages
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
    {"action": "dom", "selector": "#main"}
    {"action": "network", "filter": "api"}
    {"action": "console"}
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


async def _run_browser_cmd(
    args: list[str], timeout: int = _BROWSER_TIMEOUT
) -> tuple[int, str, str]:
    """Run an agent-browser command and return (exit_code, stdout, stderr)."""
    if not BROWSER_AVAILABLE:
        return (
            1,
            "",
            "agent-browser is not installed. Run: npm install -g agent-browser && agent-browser install",
        )

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


async def _extract_page_text(max_chars: int = _MAX_OUTPUT) -> str:
    """Best-effort: return the CURRENT page's rendered text (document.body.innerText).

    B-2026-08-30 (agent-browser content capture): `open` and the read actions
    left page content in the browser window — it never came back as tool
    evidence, so the agent opened a URL, saw nothing useful, and thrashed. The
    browser session is persistent (see the tool registration), so we can pull
    the rendered text via a follow-up `eval` in the same session.

    Returns "" on ANY failure — callers treat that as "no text extracted" and
    fall back gracefully (never breaking the navigation itself). Args are passed
    argv-style (no shell), so the script needs no cross-platform quoting.
    """
    rc, out, err = await _run_browser_cmd(
        ["eval", "document.body ? document.body.innerText : ''"]
    )
    if rc != 0:
        return ""
    text = (out or "").strip()
    # agent-browser may print the eval result JSON-encoded (a quoted string).
    # Unwrap a single layer so the agent gets the raw text, not "\"{...}\"".
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            text = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            text = text[1:-1]
    return text[:max_chars]


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

    # "read <url>" / "fetch <url>" — navigate + return content (same as open,
    # matched BEFORE the bare-URL shortcut so the verb is honored). Match the URL
    # against the ORIGINAL message so its case (e.g. /Nairobi) is preserved.
    read_match = re.match(r"(?:read|fetch)\s+(https?://\S+)", message, re.IGNORECASE)
    if read_match:
        return {"action": "read", "url": read_match.group(1)}

    # "open <url>"
    open_match = re.match(r"open\s+(https?://\S+)", message, re.IGNORECASE)
    if open_match:
        return {"action": "open", "url": open_match.group(1)}

    # A bare URL → open (which now navigates AND returns the page text).
    url_match = re.search(r"https?://\S+", message)
    if url_match and not msg_lower.startswith(
        ("click", "fill", "scroll", "snapshot", "screenshot", "close", "back", "forward", "eval")
    ):
        return {"action": "open", "url": url_match.group(0)}

    # "snapshot" or "screenshot"
    if "snapshot" in msg_lower:
        return {"action": "snapshot"}
    if "screenshot" in msg_lower:
        return {"action": "screenshot"}
    if "console" in msg_lower:
        return {"action": "console"}
    if "network" in msg_lower:
        return {"action": "network"}
    if "dom" in msg_lower or "html" in msg_lower:
        return {"action": "dom"}

    # "click @e1"
    click_match = re.search(r"click\s+(@\w+)", msg_lower)
    if click_match:
        return {"action": "click", "ref": click_match.group(1)}

    # "fill @e1 with text"
    fill_match = re.search(
        r'fill\s+(@\w+)\s+(?:with\s+)?["\']?(.+?)["\']?\s*$', message, re.IGNORECASE
    )
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
                '  {"action": "open", "url": "https://example.com"}  (navigates AND returns page text)\n'
                '  {"action": "read"}  (re-read the current page\'s text)\n'
                '  {"action": "snapshot"}\n'
                '  {"action": "click", "ref": "@e1"}\n'
                '  {"action": "fill", "ref": "@e2", "value": "text"}\n'
                '  {"action": "scroll", "direction": "down", "amount": 500}\n'
                '  {"action": "screenshot"}\n'
                '  {"action": "text", "ref": "@e3"}\n'
                '  {"action": "dom", "selector": "#main"}\n'
                '  {"action": "network", "filter": "api"}\n'
                '  {"action": "console"}\n'
                '  {"action": "eval", "script": "document.title"}\n'
                '  {"action": "close"}\n\n'
                "Or use natural language: 'open https://example.com', 'click @e1', 'snapshot', 'inspect the DOM'"
            ),
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="parse_error",
            error_message="Could not parse browser action from message",
        )

    raw_action = action.get("action", "")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return ToolResult(
            content="Browser action must include a non-empty string 'action' field.",
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="invalid_action",
            error_message="The action field must be a non-empty string",
        )

    act = raw_action.strip().lower()
    args: list[str] = []
    risk = RiskLevel.LOW

    if act in ("open", "read", "content", "get_content", "read_content"):
        url = action.get("url", "")
        if not url and act == "open":
            return ToolResult(
                content="No URL provided for 'open' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_url",
            )
        # Navigate (if a URL is given) then pull the rendered page TEXT back as
        # evidence in the SAME call — the session is persistent, so a single
        # `open` returns the content instead of leaving it in the browser
        # window. `read`/`content` re-extract the current page without needing
        # a URL. Extraction is best-effort: navigation success is never lost.
        if url:
            nav_rc, nav_out, nav_err = await _run_browser_cmd(["open", url])
            if nav_rc != 0:
                err_txt = (nav_err or nav_out).strip()
                return ToolResult(
                    content=f"Failed to open {url}: {err_txt or 'unknown error'}",
                    risk=RiskLevel.MEDIUM,
                    source="browser_agent",
                    success=False,
                    error_type="open_failed",
                    error_message=err_txt or "navigation failed",
                    metadata={"action": act, "url": url},
                )
        page_text = await _extract_page_text()
        where = f" {url}" if url else " current page"
        if page_text:
            content = f"Opened{where} — page content:\n\n{page_text}"
        else:
            content = (
                f"Opened{where}, but no text content was extracted (the page may be "
                "JS-rendered, empty, or non-HTML). Try action 'snapshot' for "
                "interactive elements, 'dom' for raw HTML, or a screenshot."
            )
        if len(content) > _MAX_OUTPUT:
            content = content[: _MAX_OUTPUT - 24] + "\n\n[... content truncated]"
        return ToolResult(
            content=content,
            risk=RiskLevel.MEDIUM,  # page content may contain user/session data
            source="browser_agent",
            success=True,
            metadata={"action": act, "url": url, "content_chars": len(page_text)},
        )

    elif act == "snapshot":
        interactive = action.get("interactive", True)
        args = ["snapshot"]
        if interactive:
            args.append("-i")  # Interactive elements only

    elif act == "click":
        ref = action.get("ref", "")
        if not ref:
            return ToolResult(
                content="No ref provided for 'click' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_ref",
            )
        args = ["click", ref]
        risk = RiskLevel.MEDIUM

    elif act == "fill":
        ref = action.get("ref", "")
        value = action.get("value", "")
        if not ref:
            return ToolResult(
                content="No ref provided for 'fill' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_ref",
            )
        args = ["fill", ref, value]
        risk = RiskLevel.MEDIUM

    elif act == "type":
        ref = action.get("ref", "")
        value = action.get("value", "")
        if not ref:
            return ToolResult(
                content="No ref provided for 'type' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_ref",
            )
        args = ["type", ref, value]

    elif act == "press":
        key = action.get("key", action.get("value", ""))
        if not key:
            return ToolResult(
                content="No key provided for 'press' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_key",
            )
        args = ["press", key]

    elif act == "scroll":
        direction = action.get("direction", "down")
        amount = str(action.get("amount", 500))
        args = ["scroll", direction, amount]

    elif act == "scrollintoview":
        ref = action.get("ref", "")
        if not ref:
            return ToolResult(
                content="No ref provided.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_ref",
            )
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
            return ToolResult(
                content="No ref provided for 'text' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_ref",
            )
        args = ["get", "text", ref]

    elif act == "dom":
        selector = action.get("selector", action.get("ref", "html"))
        if not isinstance(selector, str) or not selector.strip():
            selector = "html"
        args = ["get", "html", selector.strip()]
        risk = RiskLevel.MEDIUM  # Rendered HTML may contain user or session data

    elif act == "network":
        args = ["network", "requests"]
        risk = RiskLevel.MEDIUM  # URLs/headers may expose tokens or personal data
        if action.get("clear", False):
            args.append("--clear")
        for option in ("filter", "type", "method", "status"):
            value = action.get(option)
            if value:
                args.extend([f"--{option}", str(value)])

    elif act == "console":
        args = ["console"]
        risk = RiskLevel.MEDIUM  # Console output may contain application secrets
        if action.get("clear", False):
            args.append("--clear")
        if action.get("json", False):
            args.append("--json")

    elif act == "url":
        args = ["get", "url"]

    elif act == "title":
        args = ["get", "title"]

    elif act == "eval":
        script = action.get("script", action.get("value", ""))
        if not script:
            return ToolResult(
                content="No script provided for 'eval' action.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_script",
            )
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
            return ToolResult(
                content="No wait target provided.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_target",
            )
        args = ["wait", target]

    else:
        supported = (
            "open, read, snapshot, click, fill, type, press, scroll, scrollintoview, "
            "screenshot, text, dom, network, console, url, title, eval, back, "
            "forward, reload, close, wait"
        )
        return ToolResult(
            content=f"Unknown browser action: '{act}'. Supported: {supported}",
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="unknown_action",
            error_message=f"Unknown action: {act}",
        )

    # Validate all CLI arguments before invoking subprocess. Model-produced
    # JSON can contain the wrong scalar type; never let that become a raw
    # TypeError from create_subprocess_exec.
    if not all(isinstance(arg, str) for arg in args):
        return ToolResult(
            content=f"Invalid argument for browser action '{act}': all arguments must be strings.",
            risk=RiskLevel.LOW,
            source="browser_agent",
            success=False,
            error_type="invalid_argument",
            error_message="Browser CLI arguments must be strings",
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
    content = f"Browser action: {act}\n\n{output}" if output else f"Browser action: {act} (no output)"
    if len(content) > _MAX_OUTPUT:
        marker = "\n\n[... browser output truncated]"
        content = content[: _MAX_OUTPUT - len(marker)] + marker

    return ToolResult(
        content=content,
        risk=risk,
        source="browser_agent",
        success=success,
        metadata={"action": act, "exit_code": exit_code},
    )


# Register the tool
register_tool(
    Intent.BROWSE,
    browser_agent,
    description=(
        "Real browser interaction — navigate, click, fill forms, scroll, screenshot, "
        "inspect DOM/network/console, and execute JS. To READ a page's content, use "
        "action 'open' (or 'read') with the url: it navigates AND returns the page "
        "text in one step — you do NOT open then separately read, and the content "
        "comes back to you here, not just in the browser window. Use 'snapshot'/'dom' "
        "only when you need interactive element refs or raw HTML. For a plain HTTP "
        "GET of text/JSON (e.g. an API/weather endpoint), prefer web_fetch — the "
        "browser is for JS-rendered or interactive pages. DOM/network/console may "
        "expose page data. Uses agent-browser CLI."
    ),
    cost=0.5,
    latency_ms=3000,
    parallelizable=False,  # Browser is stateful — never run concurrently
)
