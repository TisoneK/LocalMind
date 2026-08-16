"""The Thinker — the agent's reasoning backbone (ADR-42).

A silent, read-only mid-loop analyst that reasons on GATHERED EVIDENCE (never
the raw request) and returns a structured analysis the agent acts on. This is
the ground-up replacement for the old "understanding" one-liner, which merely
echoed the request from the upfront init call (ADR-38 diagnosis).
"""

from .contract import Ambiguity, Evidence, ThinkerAnalysis
from .parse import parse_thinker_analysis
from .prompt import build_thinker_messages
from .thinker import Thinker

__all__ = [
    "Thinker",
    "Evidence",
    "ThinkerAnalysis",
    "Ambiguity",
    "parse_thinker_analysis",
    "build_thinker_messages",
]
