"""
AgentOrchestrator — the middle layer of the three-layer agent pipeline.

Sits between the Chat Agent (Layer 1) and the Execution Agent (Layer 3).

Pipeline flow:
  User → Chat Agent (acknowledge/reformulate)
       → **Orchestrator** (plan, assess confidence, escalate if needed)
       → Execution Agent (AgentLoop with tools)
       → back up to user

The Orchestrator:
  - Receives the reformulated instruction from the Chat Agent
  - Makes a PLANNING LLM call (no tools) to break the task into execution steps
  - Assesses confidence: High → proceed, Medium → ask clarifying question,
    Low → escalate fully (stop and ask user)
  - Decides which tools each step needs
  - Passes structured context to the Execution Agent via the engine
  - Can request more info from Chat Agent when confidence is low

Bidirectional communication:
  - Orchestrator can request more info from Chat Agent (which asks user)
  - Chat Agent always mediates between User and Orchestrator
  - Execution Agents never talk to user directly

The orchestrator is OPTIONAL — controlled by ORCHESTRATOR_ENABLED in constants.py.
When disabled, the engine falls back to the current Chat Agent → AgentLoop path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from core.agent.constants import (
    AGENT_ALLOWED_TOOLS,
    ORCHESTRATOR_CONFIDENCE_HIGH,
    ORCHESTRATOR_CONFIDENCE_MEDIUM,
    ORCHESTRATOR_ENABLED,
    ORCHESTRATOR_TIMEOUT_SECS,
)
from core.agent.prompts import build_orchestrator_prompt
from core.models import Intent

logger = logging.getLogger(__name__)


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class OrchestrationStep:
    """A single step in the orchestration plan."""

    tool: str
    args: dict
    reason: str


@dataclass
class OrchestrationResult:
    """Structured result from the orchestrator's planning phase."""

    steps: list[OrchestrationStep] = field(default_factory=list)
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_question: str = ""
    orchestrator_context: str = ""
    raw_plan: str = ""

    # Derived helpers
    @property
    def confidence_level(self) -> str:
        if self.confidence >= ORCHESTRATOR_CONFIDENCE_HIGH:
            return "HIGH"
        elif self.confidence >= ORCHESTRATOR_CONFIDENCE_MEDIUM:
            return "MEDIUM"
        else:
            return "LOW"

    @property
    def should_proceed(self) -> bool:
        """True when confidence is HIGH enough to proceed with execution."""
        return self.confidence >= ORCHESTRATOR_CONFIDENCE_HIGH

    @property
    def should_ask_clarification(self) -> bool:
        """True when confidence is MEDIUM — ask one clarifying question."""
        return (
            ORCHESTRATOR_CONFIDENCE_MEDIUM <= self.confidence < ORCHESTRATOR_CONFIDENCE_HIGH
            and self.needs_clarification
        )

    @property
    def should_escalate(self) -> bool:
        """True when confidence is LOW — fully escalate to user."""
        return self.confidence < ORCHESTRATOR_CONFIDENCE_MEDIUM


# ── JSON parsing helpers ──────────────────────────────────────────────────────


def _parse_orchestrator_json(text: str) -> OrchestrationResult:
    """
    Parse the orchestrator LLM's JSON output into an OrchestrationResult.

    The expected format is:
    {
        "steps": [{"tool": "...", "args": {...}, "reason": "..."}],
        "confidence": 0.0-1.0,
        "needs_clarification": bool,
        "clarification_question": "..."
    }

    Falls back gracefully if JSON parsing fails — extracts what it can
    from the raw text.
    """
    # Try to extract JSON from the response (model may wrap it in markdown)
    json_text = text.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        json_text = fence_match.group(1).strip()

    # Try direct JSON parse
    try:
        data = json.loads(json_text)
        return _build_result_from_dict(data, text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            data = json.loads(brace_match.group(0))
            return _build_result_from_dict(data, text)
        except json.JSONDecodeError:
            pass

    # Fallback: couldn't parse JSON — construct a basic result from the raw text
    logger.warning("[orchestrator] failed to parse JSON from planning output — using fallback")
    return OrchestrationResult(
        steps=[],
        confidence=0.5,  # Medium confidence — proceed but flag for review
        needs_clarification=False,
        clarification_question="",
        orchestrator_context=f"[Orchestrator planning output (unparsed)]\n{text[:500]}",
        raw_plan=text,
    )


def _build_result_from_dict(data: dict, raw_text: str) -> OrchestrationResult:
    """Build an OrchestrationResult from a parsed JSON dict."""
    steps = []
    for step_data in data.get("steps", []):
        if isinstance(step_data, dict):
            tool_name = step_data.get("tool", "")
            # Only include steps with tools in the allowed list
            if tool_name and tool_name in AGENT_ALLOWED_TOOLS:
                steps.append(
                    OrchestrationStep(
                        tool=tool_name,
                        args=step_data.get("args", {}),
                        reason=step_data.get("reason", ""),
                    )
                )

    confidence = float(data.get("confidence", 0.5))
    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, confidence))

    needs_clarification = bool(data.get("needs_clarification", False))
    clarification_question = str(data.get("clarification_question", ""))

    # Build the orchestrator context string to inject into the execution agent
    context_parts = []
    if steps:
        context_parts.append("ORCHESTRATOR PLAN:")
        for i, step in enumerate(steps, 1):
            args_str = ", ".join(f"{k}={v!r}" for k, v in step.args.items()) if step.args else ""
            context_parts.append(f"  {i}. {step.tool}({args_str}) — {step.reason}")
        context_parts.append(
            f"Confidence: {confidence:.0%} ({'HIGH' if confidence >= ORCHESTRATOR_CONFIDENCE_HIGH else 'MEDIUM' if confidence >= ORCHESTRATOR_CONFIDENCE_MEDIUM else 'LOW'})"
        )
    else:
        context_parts.append(
            "[Orchestrator: no structured steps produced — execution agent should plan independently]"
        )

    orchestrator_context = "\n".join(context_parts)

    return OrchestrationResult(
        steps=steps,
        confidence=confidence,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        orchestrator_context=orchestrator_context,
        raw_plan=raw_text,
    )


# ── AgentOrchestrator ────────────────────────────────────────────────────────


class AgentOrchestrator:
    """
    Middle layer of the three-layer agent pipeline.

    Receives reformulated instructions from the Chat Agent, breaks them
    into execution steps, assesses confidence, and either:
      - Passes structured context to the Execution Agent (high confidence)
      - Asks the Chat Agent one clarifying question (medium confidence)
      - Escalates fully to the user (low confidence)
    """

    def __init__(self, adapter=None):
        self._adapter = adapter

    async def orchestrate(
        self,
        reformulated_message: str,
        intent: Intent,
        adapter=None,
        memory_facts: Optional[list[str]] = None,
        intent_history: Optional[list[str]] = None,
        obs=None,
    ) -> OrchestrationResult:
        """
        Run the orchestration phase: plan + confidence assessment.

        Args:
            reformulated_message: The structured instruction from the Chat Agent.
            intent: The resolved effective intent for this turn.
            adapter: LLM adapter to use (overrides self._adapter if provided).
            memory_facts: Optional memory facts for context.
            intent_history: Optional list of recent intent values.
            obs: Optional observability collector.

        Returns:
            OrchestrationResult with steps, confidence, and context for the
            execution agent.
        """
        if not ORCHESTRATOR_ENABLED:
            # Orchestrator disabled — return a pass-through result
            return OrchestrationResult(
                steps=[],
                confidence=1.0,  # High confidence: proceed normally
                needs_clarification=False,
                clarification_question="",
                orchestrator_context="",
                raw_plan="",
            )

        active_adapter = adapter or self._adapter
        if not active_adapter:
            logger.warning("[orchestrator] no adapter available — skipping orchestration")
            return OrchestrationResult(
                steps=[],
                confidence=1.0,
                orchestrator_context="",
            )

        if obs:
            obs.emit("orchestrator_start", intent=intent.value)

        # Build the orchestrator prompt
        from core.context_builder import _build_environment_context

        env_context = _build_environment_context()

        orchestrator_prompt = build_orchestrator_prompt(
            reformulated_message=reformulated_message,
            intent=intent,
            env_context=env_context,
            memory_facts=memory_facts,
            intent_history=intent_history,
        )

        messages = [
            {"role": "system", "content": orchestrator_prompt},
            {"role": "user", "content": reformulated_message},
        ]

        try:
            # Collect the full planning response with timeout
            full_response: list[str] = []

            async def _collect():
                async for chunk in active_adapter.chat(
                    messages,
                    temperature=0.2,  # Low temperature for structured planning
                    intent="chat",  # No tools — pure planning call
                ):
                    if chunk.text:
                        full_response.append(chunk.text)

            await asyncio.wait_for(_collect(), timeout=ORCHESTRATOR_TIMEOUT_SECS)

            raw_plan = "".join(full_response).strip()

            if not raw_plan:
                logger.warning("[orchestrator] empty planning response — falling through")
                return OrchestrationResult(
                    steps=[],
                    confidence=0.5,
                    orchestrator_context="[Orchestrator: planning produced no output]",
                    raw_plan="",
                )

            # Parse the structured JSON output
            result = _parse_orchestrator_json(raw_plan)

            if obs:
                obs.emit(
                    "orchestrator_done",
                    intent=intent.value,
                    confidence=round(result.confidence, 2),
                    confidence_level=result.confidence_level,
                    steps=len(result.steps),
                    needs_clarification=result.needs_clarification,
                )

            logger.info(
                "[orchestrator] plan complete: confidence=%.2f (%s), steps=%d, needs_clarification=%s",
                result.confidence,
                result.confidence_level,
                len(result.steps),
                result.needs_clarification,
            )

            return result

        except asyncio.TimeoutError:
            logger.warning(
                "[orchestrator] planning timed out — falling through with medium confidence"
            )
            if obs:
                obs.emit("orchestrator_timeout", timeout=ORCHESTRATOR_TIMEOUT_SECS)
            return OrchestrationResult(
                steps=[],
                confidence=0.5,
                orchestrator_context="[Orchestrator: planning timed out — execution agent should proceed with caution]",
                raw_plan="",
            )
        except Exception as e:
            logger.warning(f"[orchestrator] planning failed (non-fatal): {e}")
            if obs:
                obs.emit("orchestrator_failed", error=str(e)[:80])
            return OrchestrationResult(
                steps=[],
                confidence=0.5,
                orchestrator_context=f"[Orchestrator: planning error — {str(e)[:100]}]",
                raw_plan="",
            )

    async def replan(
        self,
        reformulated_message: str,
        intent: Intent,
        failed_step: OrchestrationStep,
        failure_reason: str,
        adapter=None,
        memory_facts: Optional[list[str]] = None,
        intent_history: Optional[list[str]] = None,
        obs=None,
    ) -> OrchestrationResult:
        """
        Replan after an execution failure. The Orchestrator receives information
        about which step failed and why, then produces an updated plan.

        This is the bidirectional communication path:
        Execution Agent → Orchestrator → (replan) → Execution Agent
        """
        if not ORCHESTRATOR_ENABLED:
            return OrchestrationResult(
                steps=[],
                confidence=1.0,
                needs_clarification=False,
                clarification_question="",
                orchestrator_context="",
                raw_plan="",
            )

        active_adapter = adapter or self._adapter
        if not active_adapter:
            logger.warning(
                "[orchestrator] replan: no adapter available — returning low-confidence result"
            )
            return OrchestrationResult(
                steps=[],
                confidence=0.3,
                needs_clarification=True,
                clarification_question=f"A tool execution failed ({failure_reason[:100]}). How would you like to proceed?",
                orchestrator_context=f"[Orchestrator replan: execution failure — {failure_reason[:150]}]",
                raw_plan="",
            )

        if obs:
            obs.emit(
                "orchestrator_replan_start",
                failed_tool=failed_step.tool,
                failure_reason=failure_reason[:100],
            )

        # Build the replanning prompt — includes failure context so the
        # Orchestrator can adjust the plan to work around the failure.
        from core.context_builder import _build_environment_context

        env_context = _build_environment_context()

        replan_prompt = build_orchestrator_prompt(
            reformulated_message=reformulated_message,
            intent=intent,
            env_context=env_context,
            memory_facts=memory_facts,
            intent_history=intent_history,
        )

        # Prepend failure context to the user message so the Orchestrator
        # knows what went wrong and can plan around it.
        failure_context = (
            f"[REPLAN REQUEST — previous execution failed]\n"
            f"Failed step: {failed_step.tool}({', '.join(f'{k}={v!r}' for k, v in failed_step.args.items()) if failed_step.args else ''})\n"
            f"Reason: {failed_step.reason}\n"
            f"Failure reason: {failure_reason}\n\n"
            f"Please create an UPDATED plan that avoids the failure above. "
            f"Consider alternative tools, different arguments, or a different approach.\n\n"
            f"Original reformulated instruction: {reformulated_message}"
        )

        messages = [
            {"role": "system", "content": replan_prompt},
            {"role": "user", "content": failure_context},
        ]

        try:
            full_response: list[str] = []

            async def _collect():
                async for chunk in active_adapter.chat(
                    messages,
                    temperature=0.2,
                    intent="chat",
                ):
                    if chunk.text:
                        full_response.append(chunk.text)

            await asyncio.wait_for(_collect(), timeout=ORCHESTRATOR_TIMEOUT_SECS)

            raw_plan = "".join(full_response).strip()

            if not raw_plan:
                logger.warning(
                    "[orchestrator] replan produced no output — returning low-confidence fallback"
                )
                return OrchestrationResult(
                    steps=[],
                    confidence=0.3,
                    needs_clarification=True,
                    clarification_question=f"A tool execution failed ({failure_reason[:80]}). Would you like to try a different approach?",
                    orchestrator_context=f"[Orchestrator replan: no output — original failure: {failure_reason[:100]}]",
                    raw_plan="",
                )

            result = _parse_orchestrator_json(raw_plan)

            if obs:
                obs.emit(
                    "orchestrator_replan_done",
                    confidence=round(result.confidence, 2),
                    steps=len(result.steps),
                )

            logger.info(
                "[orchestrator] replan complete: confidence=%.2f (%s), steps=%d, failed_tool=%s",
                result.confidence,
                result.confidence_level,
                len(result.steps),
                failed_step.tool,
            )

            return result

        except asyncio.TimeoutError:
            logger.warning("[orchestrator] replan timed out")
            if obs:
                obs.emit("orchestrator_replan_timeout", timeout=ORCHESTRATOR_TIMEOUT_SECS)
            return OrchestrationResult(
                steps=[],
                confidence=0.3,
                needs_clarification=True,
                clarification_question=f"A tool execution failed and replanning timed out ({failure_reason[:80]}). How would you like to proceed?",
                orchestrator_context=f"[Orchestrator replan: timed out — original failure: {failure_reason[:100]}]",
                raw_plan="",
            )
        except Exception as e:
            logger.warning(f"[orchestrator] replan failed (non-fatal): {e}")
            if obs:
                obs.emit("orchestrator_replan_failed", error=str(e)[:80])
            return OrchestrationResult(
                steps=[],
                confidence=0.3,
                needs_clarification=True,
                clarification_question=f"A tool execution failed ({failure_reason[:80]}). Would you like to try a different approach?",
                orchestrator_context=f"[Orchestrator replan error — {str(e)[:100]}]",
                raw_plan="",
            )

    def request_info_from_chat_agent(
        self,
        question: str,
        conversation_context: str,
    ) -> str:
        """
        Build a structured query for the Chat Agent layer.

        The Orchestrator calls this when it needs information that might
        be available from the conversation history or user context.

        Returns a formatted string that the engine can pass to the Chat Agent
        for resolution before continuing with execution.
        """
        return (
            f"[ORCHESTRATOR → CHAT AGENT REQUEST]\n"
            f"Question: {question}\n"
            f"Context: {conversation_context}\n"
            f"Please resolve this using conversation history or ask the user."
        )
