"""
web_research tool.

High-level web research operation that the parent agent calls instead of
web_search + web_fetch directly. Implements the user's invariant:

  Parent agent specifies WHAT information is needed.
  Web subsystem determines HOW to acquire it.

The tool wraps the WebAcquisitionRouter:
  1. Search for sources (web_search)
  2. Try static fetch on the top candidate
  3. If that fails, escalate to browser_read (JS rendering)
  4. If that fails, try the next source
  5. Validate the result
  6. Return the best content

The parent agent never sees web_search/web_fetch/browser mechanics.
"""
from __future__ import annotations

import logging
from typing import Any

from core.models import Intent, RiskLevel, ToolResult
from core.web_acquisition import web_research

logger = logging.getLogger(__name__)

TOOL_NAME = "web_research"
TOOL_DESCRIPTION = (
    "Research a topic on the web and return the most relevant, current content. "
    "Automatically searches for sources, fetches the best one (with JavaScript "
    "rendering if needed), and validates the result. Use this for any request "
    "that needs current information from the web — news, weather, sports scores, "
    "standings, prices, documentation, etc."
)
TOOL_INTENT = "web_research"  # new intent for adaptive web acquisition
TOOL_RISK = RiskLevel.LOW


async def web_research_tool(query: str, **kwargs: Any) -> ToolResult:
    """Research a topic on the web.

    Args:
        query: The search query — what information the user needs.

    Returns:
        ToolResult with the acquired content, or an error message.
    """
    query = (query or "").strip()
    if not query or len(query) < 3:
        return ToolResult(
            content="Query too short — please provide a search query of at least 3 characters.",
            risk=TOOL_RISK,
            source=TOOL_NAME,
            success=False,
            error_type="invalid_input",
            error_message="Empty or too-short query",
        )

    logger.info("[web_research] starting research for query=%r", query[:80])

    try:
        result = await web_research(
            query=query,
            max_sources=3,
            freshness_required=False,
        )

        content = result.to_tool_result_content()
        success = result.is_success() or result.status.value == "partial"

        return ToolResult(
            content=content,
            risk=TOOL_RISK,
            source=TOOL_NAME,
            success=success,
            error_type=None if success else "acquisition_failed",
            error_message=result.error if not success else None,
            metadata={
                "acquisition_status": result.status.value,
                "acquisition_method": result.acquisition_method.value,
                "source_url": result.source,
                "confidence": result.confidence,
                "freshness": result.freshness,
                "attempted_strategies": result.attempted_strategies,
            },
        )
    except Exception as e:
        logger.exception("[web_research] failed for query=%r", query[:80])
        return ToolResult(
            content=f"Web research failed: {e}",
            risk=TOOL_RISK,
            source=TOOL_NAME,
            success=False,
            error_type="exception",
            error_message=str(e)[:200],
        )


# Tool registration
from tools import register_tool  # noqa: E402

register_tool(
    Intent.WEB_RESEARCH,
    web_research_tool,
    description=TOOL_DESCRIPTION,
    cost=0.5,
    latency_ms=5000,
    parallelizable=False,  # web_research does sequential search→fetch→browser
)

TOOL_DEF = {
    "intent": "web_research",
    "name": TOOL_NAME,
    "description": TOOL_DESCRIPTION,
    "handler": web_research_tool,
    "risk": TOOL_RISK,
}
