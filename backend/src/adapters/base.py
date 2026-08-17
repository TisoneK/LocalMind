"""
Base adapter interface. All runtime adapters must implement this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.models import StreamChunk


class BaseAdapter(ABC):
    """
    Abstract base class for model runtime adapters.

    To add a new runtime (LM Studio, llama.cpp, etc.):
    1. Create adapters/my_runtime.py
    2. Subclass BaseAdapter and implement chat()
    3. Register in adapters/__init__.py
    4. Set LOCALMIND_ADAPTER=my_runtime in .env
    """

    @property
    def context_window(self) -> int:
        """Model context window in tokens. Override per adapter/model."""
        return 8192

    @property
    def slow_provider(self) -> bool:
        """True when this adapter's generations are slow enough that the
        generic 45s per-call cap would truncate a legitimately slow reply
        (local models on CPU / small GPUs often generate <1-2 tok/s).

        The agent loop reads this to apply a more generous per-call / plan /
        wall-clock budget — WITHOUT enabling the Thinker, which stays gated
        on ``thinking_enabled`` (a semantic "the model reasons" signal, not
        a speed one: a slow non-thinking local model must not get an extra
        sequential consult call it can't afford).
        """
        return False

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """
        Send messages to the model and stream the response.

        Args:
            messages: List of message dicts in OpenAI chat format.
            temperature: Sampling temperature.

        Yields:
            StreamChunk objects. The final chunk has done=True.
        """
        ...

    async def health_check(self) -> bool:
        """Return True if the runtime is reachable. Override if needed."""
        return True
