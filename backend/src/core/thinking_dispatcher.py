"""
ThinkingDispatcher — sole capability-based orchestration dispatcher for LocalMind.

v4.0 — Consolidated single-source dispatcher
═══════════════════════════════════════════════════════════════════════

This module is the CANONICAL Layer 2 of the 6-layer pipeline.
It replaces both the previous ThinkingDispatcher (v3) and the
CapabilityOrchestrator (which was a parallel/alternate implementation
that was never wired into engine.py).

Capabilities:
  1. Signal detection — structural fast-paths without LLM call
  2. Follow-up detection — short contextual messages inherit prior intent
  3. LLM-based capability inference — single LLM call produces TaskProfile
  4. Real-time thinking token streaming to the frontend
  5. ExecutionGraph construction from LLM output
  6. Fallback to minimal TaskProfile on timeout/error
  7. System leak filtering on LLM output

Removed in v4.0:
  - CapabilityOrchestrator (consolidated into this module)
  - Lazy imports of execution_graph (now top-level)
  - capability.py re-export layer (deleted)

Architecture:
  Input → Signal Detection → Follow-up Detection → LLM Inference → OrchestrationPlan
                                                                          ├── TaskProfile
                                                                          └── ExecutionGraph
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator, Optional, Union

from core.models import (
    Intent, StreamChunk,
    TaskProfile, ExecutionMode, SafetyLevel, Capability,
    OrchestrationPlan, UnderstandingResult, ValidationResult,
    CAPABILITY_TO_INTENT, TOOL_CAPABILITIES, COGNITIVE_CAPABILITIES,
)
from core.execution_graph import ExecutionGraph, build_graph_from_plan_steps
from core.filters import _filter_system_leaks
from core.obs import ObsCollector

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

DISPATCHER_TIMEOUT_SECS: float = 10.0
DISPATCHER_TEMPERATURE: float = 0.2
MAX_HISTORY_FOR_PROMPT: int = 6

# Signal detection: only intercept truly unambiguous one-way signals.
# These produce TaskProfile objects without an LLM call, saving 2-5s.
# IMPORTANT: Fast-paths do NOT route to CHAT.
_SHELL_PREFIXES = (
    "ls ", "ls\t", "dir ", "dir\t", "pwd", "cat ", "cat\t",
    "echo ", "cd ", "mkdir ", "rm ", "cp ", "mv ",
    "grep ", "find ", "chmod ", "chown ",
    "pip install ", "npm install ", "git ",
    "python ", "node ",
)

_EXACT_SYSINFO_PHRASES = {
    "what time is it", "what's the time", "whats the time",
    "what time is it now", "current time", "what's the date",
    "whats the date", "what is the date", "what day is it",
    "what's today's date", "whats todays date",
}

_URL_PATTERN = re.compile(r'https?://\S+', re.IGNORECASE)

# Follow-up detection — short messages that inherit context
_FOLLOW_UP_PATTERNS = re.compile(
    r"^(yes|yeah|yep|sure|ok|okay|go ahead|do it|read it|read it now|"
    r"please|proceed|confirm|continue|show me|open it|check it|"
    r"try again|retry|again|run it|"
    r"did you\?|have you\?|were you\?|is it\?|can you\?)\s*[.!?]*$",
    re.IGNORECASE,
)

# Intent → display label mapping for structured dispatch steps.
_INTENT_STEP_LABELS: dict[str, str] = {
    "chat": "Chat",
    "web_search": "Web Search",
    "web_fetch": "Fetch URL",
    "code_exec": "Execute Code",
    "shell": "Run Command",
    "file_task": "Read File",
    "file_write": "Write File",
    "file_edit": "Edit File",
    "sysinfo": "System Info",
    "memory_op": "Memory",
}


# ── Helper: Build dispatch steps ─────────────────────────────────────────────

def _build_dispatch_steps(
    intent: Intent,
    message: str,
    reformulated: str,
    profile: Optional[TaskProfile] = None,
) -> list[dict]:
    """Build deterministic, user-facing dispatch steps from the routing decision."""
    steps = []
    intent_val = intent.value

    label = _INTENT_STEP_LABELS.get(intent_val, intent_val.replace("_", " ").title())
    steps.append({"intent": intent_val, "label": label, "detail": reformulated[:120]})

    if profile is not None:
        if profile.realtime_sensitive:
            steps.append({
                "intent": "capability",
                "label": "Live Data",
                "detail": "Requires current data — will not use cached/training data",
            })
        tools = profile.required_tools()
        if tools:
            tool_names = ", ".join(t.replace("_", " ").title() for t in tools)
            steps.append({"intent": "tools", "label": "Tools", "detail": tool_names})
        if profile.execution_mode not in (ExecutionMode.DIRECT, ExecutionMode.SINGLE_TOOL):
            mode_label = profile.execution_mode.value.replace("_", " ").title()
            steps.append({"intent": "execution", "label": "Execution", "detail": f"{mode_label} workflow"})

    msg_lower = message.lower().strip()
    if msg_lower in ("yes", "yeah", "yep", "sure", "ok", "okay", "go ahead", "proceed", "continue"):
        steps.append({
            "intent": "followup",
            "label": "Follow-up",
            "detail": f"Continuing previous request: {reformulated[:80]}",
        })

    return steps


# ── Capability inference system prompt ────────────────────────────────────────

_CAPABILITY_INFERENCE_SYSTEM = """\
You are LocalMind's capability inference engine. Your job is to analyze a user message and determine WHAT CAPABILITIES are needed to fulfill it — not just classify it into a single bucket.

AVAILABLE CAPABILITIES:
- web_search: Search the web for current/live information (sports, news, weather, prices, events)
- web_fetch: Fetch and read a specific URL
- code_exec: Execute Python code
- shell: Run system commands, browse directories
- file_read: Read file contents
- file_write: Create/overwrite a file
- file_edit: Edit an existing file in-place
- memory_store: Store a persistent fact for later recall
- memory_retrieve: Recall stored facts from memory
- sysinfo: Get system info (current time, date, hardware specs, installed programs)
- reasoning: Deep analysis, logical deduction, evaluation
- synthesis: Combine information from multiple sources into coherent output
- planning: Multi-step task decomposition and sequencing
- comparison: Compare options, data, or alternatives
- prediction: Forecast, predict, or estimate future outcomes

CAPABILITY FLAGS:
- requires_grounding: Needs real external data (web search, file read, system info)
- requires_tools: Needs tool execution (shell, code_exec, file_write, etc.)
- requires_planning: Needs multi-step planning before execution
- requires_memory: Needs memory retrieval or storage
- requires_reasoning: Needs analytical reasoning
- requires_execution: Needs code/shell execution
- requires_file_access: Needs file read/write
- realtime_sensitive: Data MUST be current — weather, sports, prices, news

EXECUTION MODES:
- direct: Pure conversation, no tools needed
- single_tool: One tool call, no orchestration
- multi_tool: Multiple tools, may be parallelizable
- agent_loop: Plan→Execute→Verify workflow for complex tasks
- multi_phase: Very complex — needs multi-phase planning with dependencies

CRITICAL RULES:
1. Follow-ups ("yes", "go ahead", "try again") refer to the previous message — use history.
2. Live/current info (weather, sports, prices, news) → ALWAYS web_search + realtime_sensitive=true
   - "Today's", "latest", "current", "recent" are signals for live data
   - INDIRECT requests count too: "Should I carry an umbrella?" → needs weather data → web_search
   - "Is it a good day for a picnic?" → needs weather data → web_search
   - "Will my flight be on time?" → needs flight data → web_search
   - Interpret WHAT THE USER NEEDS, not just what they literally said
3. Time/date queries → sysinfo only (NOT web_search)
   - "What time is it", "what's the date", "what day is it"
4. System specification queries → sysinfo only
   - "How much RAM", "CPU specs", "disk space", "installed programs"
5. Browse/list directories → shell (NOT code_exec)
6. A query can need MULTIPLE capabilities:
   - "Search for X and save to file" → web_search + file_write
   - "Compare my specs with requirements" → sysinfo + web_search + comparison
   - "Summarize this PDF and fact-check it" → file_read + web_search + synthesis
7. When unsure about a capability, INCLUDE it — the execution layer will skip it if unneeded.
8. NEVER set execution_mode=direct when live/external data is needed.
9. The reformulated_query should be the ACTUAL query to search/execute — NOT the user's
   raw message. "Should I carry an umbrella in Kitengela?" → reformulated_query should be
   "Kitengela weather today rain forecast" — the optimal query for getting the data the
   user needs, not a literal copy of their question.

Reply with ONLY valid JSON:
{"capabilities":["cap1","cap2"],"flags":{"requires_grounding":false,"requires_tools":false,"requires_planning":false,"requires_memory":false,"requires_reasoning":false,"requires_execution":false,"requires_file_access":false,"realtime_sensitive":false},"execution_mode":"direct","safety_level":"low","confidence":0.85,"primary_domain":"","reformulated_query":"the optimal query for getting the data the user needs — NOT their raw message","acknowledgement":"brief 1-sentence acknowledgement","execution_plan":{"steps":[{"id":"step_id","capability":"cap_name","tool":"tool_name","args":{},"depends_on":[],"label":"Human-readable step description"}]}}
"""


# ── ThinkingDispatcher ────────────────────────────────────────────────────────

class ThinkingDispatcher:
    """
    Capability-based orchestrating dispatcher — the sole Layer 2 implementation.

    Yields OrchestrationPlan objects (TaskProfile + ExecutionGraph).
    The engine.py consumes these plans directly in the 6-layer pipeline.

    The dispatcher is the PRIMARY routing mechanism. It does NOT fall
    back to any regex classifier. On failure, it falls back to a minimal
    TaskProfile with low confidence.

    Usage in engine.py:
        async for output in dispatcher.dispatch(...):
            if isinstance(output, StreamChunk):
                yield output
            elif isinstance(output, OrchestrationPlan):
                plan = output
                # Use plan.profile, plan.graph, etc.
    """

    def __init__(self, base_adapter):
        self._base_adapter = base_adapter
        self._adapter = None
        try:
            from core.config import settings
            from adapters import get_adapter
            fast_model = getattr(settings, "ollama_model_fast", "") or ""
            if fast_model and fast_model != settings.ollama_model:
                self._adapter = get_adapter(settings.localmind_adapter, model_override=fast_model)
            else:
                self._adapter = base_adapter
        except Exception:
            self._adapter = base_adapter

    async def dispatch(
        self,
        message: str,
        history: list,
        memory_facts: list[str],
        has_attachment: bool,
        obs: ObsCollector,
        session_id: str = "",
        attachment_filename: Optional[str] = None,
    ) -> AsyncIterator[Union[StreamChunk, OrchestrationPlan]]:
        """
        Infer capabilities and return an OrchestrationPlan.

        Steps:
          1. Check signal detection for truly unambiguous signals.
          2. Check follow-up detection for short contextual messages.
          3. Build context from history + memory.
          4. Call the LLM with capability inference prompt.
          5. Stream thinking tokens to the frontend IN REAL-TIME.
          6. Parse the structured JSON output into OrchestrationPlan.
          7. Build ExecutionGraph from plan steps.

        Yields:
            StreamChunk — thinking tokens streamed in real-time
            OrchestrationPlan — the final plan with profile + graph
        """
        t0 = time.monotonic()

        # ── 1. Signal detection for truly unambiguous signals ────────────
        signal_plan = self._try_signal_detection(message, has_attachment, attachment_filename)
        if signal_plan:
            obs.emit("dispatcher_signal_detected",
                     intent=signal_plan.profile.primary_intent().value,
                     execution_mode=signal_plan.profile.execution_mode.value,
                     message_preview=message[:60])
            logger.info("[dispatcher] signal: %s/%s for %r",
                        signal_plan.profile.primary_intent().value,
                        signal_plan.profile.execution_mode.value,
                        message[:40])
            if signal_plan.profile.acknowledgement:
                yield StreamChunk(text="", status=signal_plan.profile.acknowledgement,
                                  dispatch_steps=signal_plan.dispatch_steps)
            yield signal_plan
            return

        # ── 1b. Follow-up detection for short contextual messages ────────
        if _FOLLOW_UP_PATTERNS.match(message.strip()) and history:
            followup_plan = self._try_followup_plan(message, history, obs)
            if followup_plan:
                obs.emit("dispatcher_followup",
                         intent=followup_plan.profile.primary_intent().value,
                         message_preview=message[:60],
                         inherited_from="previous_turn")
                logger.info("[dispatcher] follow-up: %s for %r",
                            followup_plan.profile.primary_intent().value, message[:40])
                yield StreamChunk(text="", thinking="start")
                yield StreamChunk(text="", thinking=followup_plan.profile.acknowledgement or "Following up on your previous request.")
                yield StreamChunk(text="", thinking="end")
                yield followup_plan
                return

        # ── 2. Build context from history ────────────────────────────────
        history_text = self._format_history(history)
        memory_text = self._format_memory(memory_facts)

        user_content = (
            f"CONVERSATION HISTORY (most recent last):\n{history_text}\n\n"
            f"MEMORY FACTS:\n{memory_text}\n\n"
            f"has_attachment={str(has_attachment).lower()}\n"
            f"CURRENT USER MESSAGE: {message}"
        )

        messages = [
            {"role": "system", "content": _CAPABILITY_INFERENCE_SYSTEM},
            {"role": "user",   "content": user_content},
        ]

        # ── 3. Stream from LLM — emit thinking in real-time ─────────────
        obs.emit("thinking_start", intent="dispatch")
        yield StreamChunk(text="", thinking="start")

        raw_chunks: list[str] = []
        _in_json = False
        _brace_depth = 0
        _thinking_buffer: list[str] = []
        _json_buffer: list[str] = []

        try:
            # Use a queue to stream thinking tokens in real-time while
            # collecting the JSON output. This avoids the async generator
            # + asyncio.wait_for incompatibility.
            _thinking_queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL = object()

            async def _stream_and_collect():
                nonlocal _in_json, _brace_depth
                try:
                    async for chunk in self._adapter.chat(
                        messages,
                        temperature=DISPATCHER_TEMPERATURE,
                        intent="chat",
                    ):
                        text = _filter_system_leaks(chunk.text)
                        if not text:
                            continue
                        raw_chunks.append(text)
                        if not _in_json:
                            brace_idx = text.find('{')
                            if brace_idx >= 0:
                                pre_brace = text[:brace_idx]
                                if pre_brace.strip():
                                    _thinking_buffer.append(pre_brace)
                                    await _thinking_queue.put(pre_brace)
                                _in_json = True
                                _brace_depth = 1
                                json_part = text[brace_idx + 1:]
                                if json_part:
                                    _json_buffer.append(json_part)
                                for ch in json_part:
                                    if ch == '{': _brace_depth += 1
                                    elif ch == '}': _brace_depth -= 1
                            else:
                                _thinking_buffer.append(text)
                                await _thinking_queue.put(text)
                        else:
                            _json_buffer.append(text)
                            for ch in text:
                                if ch == '{': _brace_depth += 1
                                elif ch == '}': _brace_depth -= 1
                finally:
                    await _thinking_queue.put(_SENTINEL)

            # Start the collection task
            _collect_task = asyncio.create_task(_stream_and_collect())

            # Stream thinking tokens in real-time with timeout
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(
                            _thinking_queue.get(),
                            timeout=DISPATCHER_TIMEOUT_SECS,
                        )
                    except asyncio.TimeoutError:
                        _collect_task.cancel()
                        logger.warning("[dispatcher] timed out — falling back")
                        break
                    if item is _SENTINEL:
                        break
                    yield StreamChunk(text="", thinking=item)
                # Ensure the task completes — but don't hang if it already
                # finished or errored. Use a short timeout.
                try:
                    await asyncio.wait_for(_collect_task, timeout=5)
                except (asyncio.TimeoutError, Exception):
                    _collect_task.cancel()
            except Exception:
                _collect_task.cancel()
                raise

        except asyncio.TimeoutError:
            logger.warning("[dispatcher] timed out — falling back to minimal profile")
            obs.emit("dispatcher_timeout", timeout=DISPATCHER_TIMEOUT_SECS)
            yield StreamChunk(text="", thinking="end")
            yield self._fallback_plan(message, has_attachment, history)
            return
        except Exception as e:
            logger.warning("[dispatcher] error (%s) — falling back to minimal profile", e)
            obs.emit("dispatcher_error", error=str(e)[:80])
            yield StreamChunk(text="", thinking="end")
            yield self._fallback_plan(message, has_attachment, history)
            return

        raw = "".join(raw_chunks).strip()
        raw_json = "".join(_json_buffer)
        if not raw_json.strip() or _brace_depth > 0:
            raw_json = raw

        # ── 4. Parse JSON output ────────────────────────────────────────
        data = None
        try:
            clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            clean = re.sub(r"\s*```$", "", clean)
            data = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]+\}', raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    logger.warning("[dispatcher] JSON parse failed — using minimal profile")
                    yield StreamChunk(text="", thinking="end")
                    yield self._fallback_plan(message, has_attachment, history)
                    return
            else:
                logger.warning("[dispatcher] no JSON found in response — using minimal profile")
                yield StreamChunk(text="", thinking="end")
                yield self._fallback_plan(message, has_attachment, history)
                return

        # ── 5. Build OrchestrationPlan from parsed data ─────────────────
        plan = self._parse_llm_output(data, message, has_attachment, history)

        # Stream the dispatch steps as thinking tokens
        yield StreamChunk(text="", thinking="end")
        yield StreamChunk(text="", thinking="start", dispatch_steps=[])
        for step in plan.dispatch_steps:
            yield StreamChunk(text="", thinking=f"[{step.get('label', step.get('intent', ''))}] {step.get('detail', '')}", dispatch_steps=[])
        yield StreamChunk(text="", thinking="end", dispatch_steps=[])
        obs.emit("thinking_done", intent="dispatch")

        latency_ms = round((time.monotonic() - t0) * 1000)
        # Emit intent_classified so the SSE bridge sends an 'intent' event
        # to the frontend — this populates the Observe tab's intent display
        # and confidence bar in real-time, BEFORE the response is generated.
        obs.emit("intent_classified",
                 primary=plan.profile.primary_intent().value,
                 confidence=round(plan.profile.confidence, 2))
        obs.emit("dispatcher_complete",
                 intent=plan.profile.primary_intent().value,
                 execution_mode=plan.profile.execution_mode.value,
                 confidence=round(plan.profile.confidence, 2),
                 latency_ms=latency_ms,
                 capabilities=[c.value for c in plan.profile.capabilities],
                 session_id=session_id[:8] if session_id else "")

        logger.info(
            "[dispatcher] intent=%s mode=%s conf=%.2f latency=%dms "
            "capabilities=%s reformulated=%r",
            plan.profile.primary_intent().value,
            plan.profile.execution_mode.value,
            plan.profile.confidence, latency_ms,
            [c.value for c in plan.profile.capabilities],
            plan.profile.reformulated[:60],
        )

        yield plan

    # ── Signal Detection (structural only, no semantic regex) ────────────

    def _try_signal_detection(
        self, message: str, has_attachment: bool, attachment_filename: Optional[str] = None,
    ) -> Optional[OrchestrationPlan]:
        """Detect unambiguous structural signals.

        Only signals with exactly ONE valid interpretation are detected.
        All semantic classification goes through the LLM.

        Detected signals:
          - URL present → WEB_FETCH
          - File attachment → FILE_READ
          - Exact time/date query → SYSINFO
          - Shell command prefix → SHELL
        """
        msg = message.strip()
        msg_lower = msg.lower()

        # URL detection → WEB_FETCH (or BROWSE if interactive keywords present)
        url_match = _URL_PATTERN.search(msg)
        if url_match:
            url = url_match.group(0)
            # Check if the user wants to interact with the page (not just read it)
            _interactive_keywords = any(kw in msg_lower for kw in [
                "click", "fill", "type", "login", "sign in", "submit",
                "form", "button", "scroll", "screenshot", "interact",
            ])
            if _interactive_keywords:
                # Interactive browsing → use the browser agent
                profile = TaskProfile(
                    capabilities=[Capability.BROWSE, Capability.SYNTHESIS],
                    requires_grounding=True,
                    requires_tools=True,
                    execution_mode=ExecutionMode.AGENT_LOOP,
                    safety_level=SafetyLevel.MEDIUM,
                    confidence=0.85,
                    primary_domain="browse",
                    reformulated=f"Open {url} in the browser and interact with it",
                    acknowledgement=f"Opening {url} in the browser...",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps([{
                        "id": "browse_url", "capability": "browse",
                        "tool": "browse", "args": {"action": "open", "url": url},
                        "depends_on": [], "label": f"Opening: {url[:60]}",
                    }]),
                    dispatch_steps=[{"intent": "browse", "detail": f"Browse: {url[:50]}"}],
                    fast_path=True,
                )
            # Static fetch → web_fetch
            profile = TaskProfile(
                capabilities=[Capability.WEB_FETCH, Capability.SYNTHESIS],
                requires_grounding=True,
                requires_tools=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.95,
                primary_domain="web_fetch",
                reformulated=f"Fetch and read the content from {url}",
                acknowledgement=f"Fetching content from {url}...",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps([{
                    "id": "fetch_url", "capability": "web_fetch",
                    "tool": "web_fetch", "args": {"url": url},
                    "depends_on": [], "label": f"Fetching: {url[:60]}",
                }]),
                dispatch_steps=[{"intent": "web_fetch", "detail": f"Fetch: {url[:50]}"}],
                fast_path=True,
            )

        # File attachment → FILE_READ
        if has_attachment:
            filename = attachment_filename or "uploaded file"
            profile = TaskProfile(
                capabilities=[Capability.FILE_READ, Capability.SYNTHESIS],
                requires_tools=True,
                requires_file_access=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.95,
                primary_domain="file_analysis",
                reformulated=f"Analyze the uploaded file: {filename}",
                acknowledgement=f"Reading {filename}...",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps([{
                    "id": "read_file", "capability": "file_read",
                    "tool": "file_reader", "args": {"path": filename},
                    "depends_on": [], "label": f"Reading: {filename}",
                }]),
                dispatch_steps=[{"intent": "file_task", "detail": f"Read: {filename}"}],
                fast_path=True,
            )

        # Exact time/date query → SYSINFO
        if msg_lower in _EXACT_SYSINFO_PHRASES:
            profile = TaskProfile(
                capabilities=[Capability.SYSINFO],
                requires_tools=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.98,
                primary_domain="system_info",
                reformulated=msg,
                acknowledgement="Let me check that for you.",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps([{
                    "id": "sysinfo", "capability": "sysinfo",
                    "tool": "sysinfo", "args": {"goal": msg},
                    "depends_on": [], "label": "Getting system info",
                }]),
                dispatch_steps=[{"intent": "sysinfo", "detail": "System info query"}],
                fast_path=True,
            )

        # Shell command prefix → SHELL
        if any(msg.startswith(prefix) for prefix in _SHELL_PREFIXES):
            profile = TaskProfile(
                capabilities=[Capability.SHELL],
                requires_tools=True,
                requires_execution=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.HIGH,
                confidence=0.92,
                primary_domain="shell_command",
                reformulated=msg,
                acknowledgement=f"Running: {msg[:50]}...",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps([{
                    "id": "shell_cmd", "capability": "shell",
                    "tool": "shell", "args": {"action": msg},
                    "depends_on": [], "label": f"Shell: {msg[:50]}",
                }]),
                dispatch_steps=[{"intent": "shell", "detail": f"Shell: {msg[:50]}"}],
                fast_path=True,
            )

        return None

    # ── Follow-up Detection ─────────────────────────────────────────────

    def _try_followup_plan(
        self, message: str, history: list, obs: ObsCollector
    ) -> Optional[OrchestrationPlan]:
        """Follow-up detection that returns OrchestrationPlan."""
        from core.agent.constants import FOLLOWUP_HISTORY_DEPTH

        if not history or len(history) < 2:
            return None

        msg_lower = message.strip().lower().rstrip("!?.,")
        depth = FOLLOWUP_HISTORY_DEPTH
        recent_messages = history[-depth:] if len(history) > depth else history

        user_msgs = []
        assistant_msgs = []
        for msg in reversed(recent_messages):
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "") or ""
            role_str = role.value if hasattr(role, "value") else str(role)
            if role_str == "user":
                user_msgs.append(content[:300])
            elif role_str == "assistant":
                assistant_msgs.append(content[:500])

        last_user = user_msgs[0] if user_msgs else ""
        last_asst = assistant_msgs[0] if assistant_msgs else ""
        prior_user = user_msgs[1] if len(user_msgs) > 1 else ""
        prior_asst = assistant_msgs[1] if len(assistant_msgs) > 1 else ""

        # Detect prior SHELL context
        _SHELL_KEYWORDS = re.compile(
            r'\b(run|execute|install|start|launch|open|command|terminal|shell|cmd|'
            r'browse|directory|folder|list files|find|locate|search for|look for|'
            r'documents|downloads|desktop|projects?)\b',
            re.IGNORECASE,
        )

        all_text = " ".join([last_user, last_asst, prior_user, prior_asst]).lower()
        shell_keyword_hits = len(_SHELL_KEYWORDS.findall(all_text))
        has_prior_shell_context = shell_keyword_hits >= 1

        if has_prior_shell_context:
            _CONFIRM_WORDS = {
                "yes", "yeah", "yep", "ok", "okay", "go ahead",
                "do it", "please", "proceed", "confirm", "continue",
                "sure", "try again", "retry", "again", "run it",
            }
            if msg_lower in _CONFIRM_WORDS:
                reformulated = (
                    f"Previous request: '{prior_user or last_user}'. "
                    f"User confirmed with '{message}' — rerun the prior shell/command task."
                )
                profile = TaskProfile(
                    capabilities=[Capability.SHELL],
                    requires_tools=True,
                    requires_execution=True,
                    execution_mode=ExecutionMode.SINGLE_TOOL,
                    safety_level=SafetyLevel.HIGH,
                    confidence=0.80,
                    reformulated=reformulated,
                    acknowledgement="Running that for you.",
                    reasoning="Follow-up: prior shell context detected, user confirmed.",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps([{
                        "id": "shell_followup", "capability": "shell",
                        "tool": "shell", "args": {"action": reformulated},
                        "depends_on": [], "label": "Rerunning previous command",
                    }]),
                    dispatch_steps=_build_dispatch_steps(Intent.SHELL, message, reformulated),
                    fast_path=False,
                )

        # Detect file-related follow-ups
        _FILE_SIGNALS_PATTERNS = [
            re.compile(r'\b(read|open|view|show|check|fetch)\b.*\b(file|cv|resume|document|pdf|doc)\b', re.IGNORECASE),
            re.compile(r'\.(pdf|docx?|txt|csv|xlsx?|md)\b', re.IGNORECASE),
        ]
        _file_signal_count = sum(
            1 for p in _FILE_SIGNALS_PATTERNS
            for text in [last_asst, last_user, prior_user, prior_asst]
            if p.search(text)
        )

        if _file_signal_count >= 1:
            reformulated = (
                f"User originally asked: '{prior_user or last_user}'. "
                f"User confirmed: '{message}' — proceed with file operation."
            )
            profile = TaskProfile(
                capabilities=[Capability.FILE_READ],
                requires_grounding=True,
                requires_tools=True,
                requires_file_access=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.80,
                reformulated=reformulated,
                acknowledgement="Reading that file for you now.",
                reasoning="Follow-up: file operation context detected from history.",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps([{
                    "id": "file_followup", "capability": "file_read",
                    "tool": "file_task", "args": {},
                    "depends_on": [], "label": "Reading file",
                }]),
                dispatch_steps=_build_dispatch_steps(Intent.FILE_TASK, message, reformulated),
                fast_path=False,
            )

        # Generic confirmation
        _GENERIC_CONFIRM = {
            "yes", "yeah", "yep", "ok", "okay", "go ahead",
            "do it", "please", "proceed", "confirm", "continue", "sure",
        }
        if msg_lower in _GENERIC_CONFIRM:
            reformulated = (
                f"User originally asked: '{prior_user or last_user}'. "
                f"User said '{message}' — confirming action from prior turn."
            )
            profile = TaskProfile(
                capabilities=[Capability.FILE_READ],
                requires_grounding=True,
                requires_tools=True,
                requires_file_access=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.70,
                reformulated=reformulated,
                acknowledgement="Proceeding with the previous request.",
                reasoning="Follow-up: generic confirmation from history.",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps([{
                    "id": "followup", "capability": "file_read",
                    "tool": "file_task", "args": {},
                    "depends_on": [], "label": "Following up",
                }]),
                dispatch_steps=_build_dispatch_steps(Intent.FILE_TASK, message, reformulated),
                fast_path=False,
            )

        return None

    # ── LLM Output Parsing ──────────────────────────────────────────────

    def _parse_llm_output(
        self, data: dict, message: str, has_attachment: bool, history: list
    ) -> OrchestrationPlan:
        """Parse the LLM's JSON output into an OrchestrationPlan."""
        # Parse capabilities
        capabilities = []
        for cap_str in data.get("capabilities", []):
            try:
                capabilities.append(Capability(cap_str))
            except ValueError:
                logger.debug(f"[dispatcher] unknown capability: {cap_str}")

        # Parse flags
        flags = data.get("flags", {})

        # Parse execution mode
        execution_mode = ExecutionMode.DIRECT
        mode_str = data.get("execution_mode", "direct")
        try:
            execution_mode = ExecutionMode(mode_str)
        except ValueError:
            pass

        # Parse safety level
        safety_level = SafetyLevel.LOW
        safety_str = data.get("safety_level", "low")
        try:
            safety_level = SafetyLevel(safety_str)
        except ValueError:
            pass

        # Build TaskProfile
        profile = TaskProfile(
            requires_grounding=flags.get("requires_grounding", False),
            requires_tools=flags.get("requires_tools", bool(capabilities)),
            requires_planning=flags.get("requires_planning", False),
            requires_memory=flags.get("requires_memory", False),
            requires_reasoning=flags.get("requires_reasoning", False),
            requires_execution=flags.get("requires_execution", False),
            requires_file_access=flags.get("requires_file_access", False),
            realtime_sensitive=flags.get("realtime_sensitive", False),
            capabilities=capabilities,
            safety_level=safety_level,
            confidence=min(1.0, max(0.0, float(data.get("confidence", 0.7)))),
            execution_mode=execution_mode,
            primary_domain=data.get("primary_domain", ""),
            reformulated=data.get("reformulated_query", message),
            acknowledgement=data.get("acknowledgement", ""),
        )

        # Auto-correct inconsistencies
        profile.auto_correct()

        # Capability correction: if realtime_sensitive but no WEB_SEARCH, add it
        if profile.realtime_sensitive and Capability.WEB_SEARCH not in capabilities:
            capabilities.insert(0, Capability.WEB_SEARCH)
            profile.capabilities = capabilities
            profile.auto_correct()
            logger.info("[dispatcher] adding WEB_SEARCH: realtime_sensitive=True but no web_search capability")

        # Derive execution mode if not already set correctly
        if profile.is_chat_only() and profile.execution_mode != ExecutionMode.DIRECT:
            profile.execution_mode = ExecutionMode.DIRECT
        elif not profile.is_chat_only() and profile.execution_mode == ExecutionMode.DIRECT:
            if len(profile.tool_capabilities()) >= 2:
                profile.execution_mode = ExecutionMode.MULTI_TOOL
            else:
                profile.execution_mode = ExecutionMode.SINGLE_TOOL
            logger.info(
                "[dispatcher] correcting execution_mode: %s → %s for capabilities=%s",
                ExecutionMode.DIRECT.value,
                profile.execution_mode.value,
                [c.value for c in capabilities],
            )

        # Build execution graph from plan steps
        steps = data.get("execution_plan", {}).get("steps", [])
        graph = build_graph_from_plan_steps(steps) if steps else ExecutionGraph()

        # Build dispatch steps for UI
        dispatch_steps = []
        for step in steps:
            cap_name = step.get("capability", "")
            label = step.get("label", cap_name)
            dispatch_steps.append({"intent": cap_name, "detail": label})

        if not dispatch_steps:
            dispatch_steps = _build_dispatch_steps(
                profile.primary_intent(), message, profile.reformulated, profile
            )

        return OrchestrationPlan(
            profile=profile,
            graph=graph,
            reasoning=data.get("reasoning", ""),
            dispatch_steps=dispatch_steps,
            fast_path=False,
        )

    # ── Fallback ────────────────────────────────────────────────────────

    def _fallback_plan(
        self, message: str, has_attachment: bool, history: list
    ) -> OrchestrationPlan:
        """Fallback on timeout/error. Returns a minimal CHAT TaskProfile."""
        return OrchestrationPlan(
            profile=TaskProfile(
                capabilities=[],
                execution_mode=ExecutionMode.DIRECT,
                safety_level=SafetyLevel.LOW,
                confidence=0.3,
                reformulated=message,
                acknowledgement="",
                reasoning="Fallback: LLM dispatch call failed or timed out",
            ),
            graph=ExecutionGraph(),
            reasoning="Fallback: LLM dispatch call failed or timed out",
            dispatch_steps=[{"intent": "chat", "detail": "Direct conversation"}],
            fast_path=False,
        )

    # ── Private helpers ─────────────────────────────────────────────────

    def _format_history(self, history: list) -> str:
        if not history:
            return "(No prior exchange exists.)"
        lines = []
        for msg in history[-MAX_HISTORY_FOR_PROMPT:]:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "") or ""
            role_str = role.value if hasattr(role, "value") else str(role)
            lines.append(f"  {role_str}: {content[:200]}")
        return "\n".join(lines)

    def _format_memory(self, facts: list[str]) -> str:
        if not facts:
            return "(No memory facts.)"
        return "\n".join(f"  - {f[:200]}" for f in facts[:10])
