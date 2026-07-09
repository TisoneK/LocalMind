"""
LocalMind Core Engine — v4.0

6-Layer Pipeline:
  [0] Safety Gate → blocks unsafe messages
  [1] Load History + Persist User Message
  [2] Capability Inference via ThinkingDispatcher → OrchestrationPlan
  [3] Derive routing from TaskProfile.execution_mode
  [4] Execute: DIRECT (chat) | SINGLE_TOOL | MULTI_TOOL | AGENT_LOOP | MULTI_PHASE
  [5] Post-Processing: Memory persistence, history, observability, metrics

This package was split from a single 2,611-line engine.py into focused
submodules for maintainability. The public API (Engine, get_adapter) is
re-exported here so existing `from core.engine import Engine` imports
continue to work unchanged.

Module layout:
  _pipeline.py        — Engine class with the main process() method
  _helpers.py         — module-level utilities (_safe_task, _LRUCache,
                        _parse_chat_agent_output, _resolve_intent, etc.)
  _memory_mixin.py    — fact extraction, validation, and storage
  _persistence_mixin.py — user/assistant message persistence helpers
  _reflection_mixin.py — post-response self-critique quality gate
  _chat_agent_mixin.py — two-stage Chat Agent acknowledgement phase

The mixin classes are composed into the final Engine class in _pipeline.py.
"""

from __future__ import annotations

# Re-export the public API so `from core.engine import Engine` still works.
# Also re-export get_adapter because tests patch `core.engine.get_adapter`.
from adapters import get_adapter

from ._pipeline import Engine

__all__ = ["Engine", "get_adapter"]
