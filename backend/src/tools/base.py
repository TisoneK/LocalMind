"""
Tool base types. All tools return ToolResult.
Import from core.models — this file re-exports for tool author convenience.
"""
from core.models import RiskLevel as ToolRisk
from core.models import ToolResult

__all__ = ["ToolResult", "ToolRisk"]
