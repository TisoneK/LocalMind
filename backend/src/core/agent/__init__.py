"""
core.agent — Agent loop package.

Public API (imported by engine.py and anywhere else that needs agent primitives):

    from core.agent import AgentLoop, AgentTrace, AgentStep, AGENT_INTENTS
    from core.agent.orchestrator import AgentOrchestrator, OrchestrationResult

Internals are split across sub-modules:
    constants    — tunable config values in one place
    models       — dataclasses (AgentStep, AgentTrace)
    prompts      — system-prompt builder
    filters      — thought sanitization (wraps core.filters)
    search       — web-search result helpers (truncation, extractive summary)
    dispatch     — tool dispatch with exponential-backoff retry
    loop         — AgentLoop class (the actual think→act→observe→reflect cycle)
    delegation  — parent/child run context and delegation contracts
    orchestrator — AgentOrchestrator: the middle layer of the three-layer pipeline
                   (Chat Agent → Orchestrator → Execution Agent)
"""

from core.agent.constants import AGENT_INTENTS
from core.agent.loop import AgentLoop
from core.agent.models import AgentStep, AgentTrace
from core.agent.orchestrator import AgentOrchestrator, OrchestrationResult

__all__ = [
    "AgentLoop",
    "AgentTrace",
    "AgentStep",
    "AGENT_INTENTS",
    "AgentOrchestrator",
    "OrchestrationResult",
]
