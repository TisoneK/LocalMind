"""Boot-owned state for LocalMind's parent agent.

The kernel contains only server-lifetime state: the active adapter, the
parent's static contract, and the tool metadata catalog. User messages,
conversation history, workspace evidence, and plans remain per-session/turn
state and must never be stored here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from time import monotonic
from typing import Any

from agents.parent.context_builder import build_parent_context
from core.config import settings
from core.models import Intent


def active_parent_model() -> str:
    """Return the model selected for the parent agent right now."""
    from core.model_router import best_model_for

    return best_model_for(Intent.ANALYZE, fallback=settings.ollama_model)


def _provider_key_fingerprint() -> str:
    """Track key rotation without retaining the secret in the signature."""
    try:
        key = settings.get_api_key(settings.localmind_adapter) or ""
    except Exception:
        key = ""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def parent_kernel_signature() -> tuple[Any, ...]:
    """Return settings that require rebuilding the boot-owned kernel."""
    return (
        settings.localmind_adapter,
        active_parent_model(),
        _provider_key_fingerprint(),
        settings.localmind_thinking,
        settings.localmind_reasoning_effort,
        settings.localmind_shell_enabled,
        getattr(settings, "ollama_num_ctx", 0),
    )


@dataclass(frozen=True)
class ParentKernel:
    """Immutable server-lifetime parent context and provider handle."""

    signature: tuple[Any, ...]
    adapter: Any
    parent_context: str
    available_tools: tuple[dict, ...]
    created_at: float
    degraded_reason: str = ""

    @classmethod
    def build(cls, adapter: Any, tool_catalog: list[dict], degraded_reason: str = "") -> "ParentKernel":
        """Build static parent state without sending a fake model request."""
        return cls(
            signature=parent_kernel_signature(),
            adapter=adapter,
            parent_context=build_parent_context([], Intent.ANALYZE),
            available_tools=tuple(tool_catalog),
            created_at=monotonic(),
            degraded_reason=degraded_reason,
        )

    def matches_current_settings(self) -> bool:
        return self.signature == parent_kernel_signature()

    @property
    def ready(self) -> bool:
        return not self.degraded_reason
