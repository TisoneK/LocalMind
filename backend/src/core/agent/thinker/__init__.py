"""The Thinker — a read-only mid-loop analyst.

Reasons on GATHERED EVIDENCE (never the raw request) and returns a structured
analysis the agent acts on. What the user watches from a consult is the
model's native reasoning, streamed verbatim from the thinking channel — the
consult never asks the model to author thinking-shaped prose and never shows
the answer channel. This is the ground-up replacement for the old
"understanding" one-liner, which merely echoed the request from the upfront
init call (a diagnosed failure).
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
