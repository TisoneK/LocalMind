"""
tools/contracts — Contract layer for LocalMind tool execution.

Public API:
    ToolContract         — ABC every tool contract must subclass.
    ToolRegistry         — Central registry (single source of truth).
    ContractViolationError — Raised on schema validation failure.
    resolve_contract     — Look up a contract by tool name, raise on miss.
    TOOL_SCHEMAS         — Raw schema dicts (used by the planner prompt builder).

Contracts are registered at import time:
  - Stub contracts (T2) are registered here via register_all_stub_contracts().
  - ShellContract (T5) is registered when tools/shell.py is imported.

Import this package early in the application bootstrap (before the orchestrator
starts) to ensure all contracts are in the registry before any task dispatches.
"""

from tools.contracts.base import (
    ContractViolationError,
    ToolContract,
    ToolRegistry,
    resolve_contract,
)
from tools.contracts.schemas import TOOL_SCHEMAS, register_all_stub_contracts

# Auto-register stub contracts for the 6 tools pending full Phase 3 migration.
# ShellContract self-registers when tools.shell is imported (which happens via
# tools/__init__.py).  Calling register_all_stub_contracts() here ensures the
# stubs are present even if shell import fails.
register_all_stub_contracts()

__all__ = [
    "ContractViolationError",
    "ToolContract",
    "ToolRegistry",
    "resolve_contract",
    "TOOL_SCHEMAS",
]
