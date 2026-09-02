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
import os
import re
import shutil
import signal

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.web_fetch import smart_truncate


def _terminate_proc_group(proc) -> None:
    """Best-effort kill of a subprocess AND its children (the browser it spawned).

    A plain proc.kill() reaps only the CLI wrapper; grandchild processes
    (Chromium) survive and keep inherited pipes open, which can hang a
    follow-up communicate(). When the process was started with
    start_new_session=True, its pid is its own process-group leader, so a
    single killpg tears down the whole tree. Falls back to proc.kill() on any
    platform/edge case where the group signal is unavailable.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass

logger = logging.getLogger(__name__)

# Check if agent-browser is available
_AGENT_BROWSER_BIN = shutil.which("agent-browser")
BROWSER_AVAILABLE = _AGENT_BROWSER_BIN is not None

# Default timeout for browser commands (seconds)
_BROWSER_TIMEOUT = 30

# Navigation (`open`) has a bounded duration profile: a cold Chromium launch is
# ~14s and warm opens are ~1-2s, so a page still not ready at 25s is almost
# always JS-heavy or blocking automation (e.g. anti-bot walls). Fail navigation
# a bit sooner than generic commands so the agent falls through to a static
# source faster instead of burning the full 30s (B-2026-09-01 flashscore trace).
_BROWSER_OPEN_TIMEOUT = 25

# Max output length to prevent context bloat. Table-aware truncation
# (smart_truncate) keeps data tables whole within this budget.
_MAX_OUTPUT = 10000

# Max actions in a single `batch` call. Batching many steps into ONE tool call
# is the browser's key efficiency lever — a login-then-read flow costs one agent
# iteration instead of N — but a runaway batch must still terminate.
_MAX_BATCH_STEPS = 16

# Ordering so a batch reports the HIGHEST risk any of its steps carried.
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


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
        # start_new_session=True puts the CLI (and any Chromium it spawns for
        # THIS invocation) in its own process group so a timeout can reap the
        # whole tree, not just the CLI wrapper. The persistent agent-browser
        # daemon is a pre-existing, separately-grouped process, so this does
        # not tear down the session reused across calls.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return proc.returncode or 0, stdout, stderr
    except asyncio.TimeoutError:
        # The internal timeout MUST return promptly. proc.kill() reaps only the
        # CLI wrapper; Chromium children can keep the stdout/stderr pipes open,
        # so a bare `await proc.communicate()` here blocks until the OUTER
        # dispatch timeout (180s) fires — that is exactly the 3m browse hang.
        # Kill the whole process group, then bound the drain so this returns at
        # ~`timeout`, not 180s (B-2026-09-01 browser slowness).
        _terminate_proc_group(proc)
        try:
            await asyncio.wait_for(proc.communicate(), timeout=2)
        except (asyncio.TimeoutError, ProcessLookupError, Exception):
            pass
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

    # ── batch: run a sequence of actions in ONE tool call (efficiency) ────────
    # A multi-step flow (open → wait → click → read) costs a single agent
    # iteration instead of one per step, which is what stops the browse-then-
    # thrash-to-the-iteration-cap failure. Steps run in order against the same
    # persistent session; by default it stops at the first failed step.
    if act in ("batch", "sequence", "steps"):
        steps = action.get("steps") or action.get("actions") or []
        if not isinstance(steps, list) or not steps:
            return ToolResult(
                content=(
                    "batch requires a non-empty 'steps' list, e.g. "
                    '{"action":"batch","steps":[{"action":"open","url":"https://x"},'
                    '{"action":"click","ref":"@e2"},{"action":"read"}]}'
                ),
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="invalid_batch",
            )
        if len(steps) > _MAX_BATCH_STEPS:
            return ToolResult(
                content=f"batch has {len(steps)} steps; the max is {_MAX_BATCH_STEPS}.",
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="batch_too_large",
            )
        stop_on_error = bool(action.get("stop_on_error", True))
        parts: list[str] = []
        highest_risk = RiskLevel.LOW
        ran = 0
        all_ok = True
        for i, step in enumerate(steps, start=1):
            if not isinstance(step, dict) or not str(step.get("action", "")).strip():
                parts.append(f"[step {i}] SKIPPED — each step must be an object with an 'action'.")
                all_ok = False
                if stop_on_error:
                    break
                continue
            if str(step.get("action", "")).strip().lower() in ("batch", "sequence", "steps"):
                parts.append(f"[step {i}] SKIPPED — nested batch is not allowed.")
                all_ok = False
                if stop_on_error:
                    break
                continue
            sub = await browser_agent(json.dumps(step))  # reuse full validation/dispatch
            ran += 1
            if _RISK_ORDER.get(sub.risk, 0) > _RISK_ORDER.get(highest_risk, 0):
                highest_risk = sub.risk
            label = str(step.get("action", "?"))
            parts.append(f"[step {i}: {label}] {'OK' if sub.success else 'FAILED'}\n{sub.content}")
            if not sub.success:
                all_ok = False
                if stop_on_error:
                    break
        combined = "\n\n".join(parts)
        combined = smart_truncate(combined, _MAX_OUTPUT, "\n\n[... batch output truncated]")
        return ToolResult(
            content=combined or "batch produced no output",
            risk=highest_risk,
            source="browser_agent",
            success=all_ok,
            metadata={"action": "batch", "steps": len(steps), "ran": ran},
        )

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
            nav_rc, nav_out, nav_err = await _run_browser_cmd(
                ["open", url], timeout=_BROWSER_OPEN_TIMEOUT
            )
            if nav_rc != 0:
                err_txt = (nav_err or nav_out).strip()
                timed_out = "timed out" in err_txt.lower()
                hint = (
                    " This page is likely JavaScript-heavy or blocking automation. "
                    "Do NOT retry the browser on this URL — use web_fetch or web_research "
                    "on a different source instead."
                    if timed_out else ""
                )
                return ToolResult(
                    content=f"Failed to open {url}: {err_txt or 'unknown error'}.{hint}",
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
        content = smart_truncate(content, _MAX_OUTPUT)
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

    elif act in ("extract", "query"):
        # Structured extraction: return a JSON array of the chosen attribute for
        # every element matching a CSS selector — one call gets ALL the matches
        # (prices, rows, links) instead of a ref-by-ref crawl. Built on `eval`
        # with the selector/attr embedded as JSON string literals (no injection).
        selector = action.get("selector", action.get("ref", ""))
        if not isinstance(selector, str) or not selector.strip():
            return ToolResult(
                content=(
                    "extract requires a CSS 'selector', e.g. "
                    '{"action":"extract","selector":"h2.title","attr":"text"}'
                ),
                risk=RiskLevel.LOW,
                source="browser_agent",
                success=False,
                error_type="missing_selector",
            )
        attr = str(action.get("attr", "text")).strip().lower()
        limit = action.get("limit", 200)
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 200
        attr_expr = {
            "text": "e.innerText",
            "html": "e.innerHTML",
            "href": "e.href",
            "src": "e.src",
            "value": "e.value",
        }.get(attr, f"e.getAttribute({json.dumps(attr)})")
        sel_json = json.dumps(selector.strip())
        script = (
            f"JSON.stringify(Array.from(document.querySelectorAll({sel_json}))"
            f".slice(0,{limit}).map(function(e){{return {attr_expr};}}))"
        )
        args = ["eval", script]
        risk = RiskLevel.MEDIUM  # extracted content may include user/session data

    elif act == "links":
        # Convenience: every link on the page as {text, href} — common enough to
        # not make the model hand-write the selector each time.
        limit = action.get("limit", 200)
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 200
        script = (
            "JSON.stringify(Array.from(document.querySelectorAll('a[href]'))"
            f".slice(0,{limit}).map(function(a){{return {{text:(a.innerText||'').trim(), href:a.href}};}}))"
        )
        args = ["eval", script]
        risk = RiskLevel.MEDIUM

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
            "batch, open, read, extract, links, snapshot, click, fill, type, press, "
            "scroll, scrollintoview, screenshot, text, dom, network, console, url, "
            "title, eval, back, forward, reload, close, wait"
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
    output = smart_truncate(output, _MAX_OUTPUT, f"\n\n[... output truncated, {len(stdout)} total chars]")

    success = exit_code == 0
    if not success and stderr:
        output = f"Error: {stderr.strip()}\n\n{output}"
    content = f"Browser action: {act}\n\n{output}" if output else f"Browser action: {act} (no output)"
    content = smart_truncate(content, _MAX_OUTPUT, "\n\n[... browser output truncated]")

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
        "Real browser for JS-rendered / interactive pages. To READ content use "
        "'open' (or 'read') with a url — it navigates AND returns the page text in "
        "one step (comes back here, not just the window); no separate read needed. "
        "EFFICIENCY: use 'batch' to run a whole flow in ONE call "
        "(steps=[open, click, read]) instead of one tool call per step. "
        "'extract' returns a JSON array for a CSS selector "
        "(selector + attr=text|href|src|value|<attr>); "
        "'links' returns all page links. 'snapshot' gives interactive element refs "
        "(@e1) for click/fill; 'dom' gives raw HTML. For a plain HTTP GET of "
        "text/JSON (e.g. a weather/API endpoint) prefer web_fetch. DOM/network/"
        "console/extract may expose page data. Uses agent-browser CLI."
    ),
    cost=0.5,
    latency_ms=3000,
    parallelizable=False,  # Browser is stateful — never run concurrently
)
