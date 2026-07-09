"""
tools/contracts/base.py — Contract layer for LocalMind tools.

Every tool that passes through the orchestrator MUST have a ToolContract.
Contracts enforce the single architectural guarantee:
  tools accept typed dicts only — no natural-language interpretation inside tools.

Design rules (do not violate):
  - Validation is structural only: presence + type. No regex, no heuristics.
  - Validation happens before any I/O — if it fails, nothing runs.
  - ToolRegistry is the single source of truth. No implicit loading.
  - No external dependencies. This file has zero imports outside stdlib.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Type

# ── Exception ─────────────────────────────────────────────────────────────────


class ContractViolationError(Exception):
    """
    Raised when a tool payload fails schema validation.

    The orchestrator catches this and hard-rejects the task — no fallback,
    no retry, no interpretation. The planner must produce a valid payload.

    Attributes:
        tool_name:  The tool whose contract was violated.
        field:      The specific field that caused the failure (may be empty).
        reason:     Human-readable description of the violation.
    """

    def __init__(self, tool_name: str, reason: str, field: str = "") -> None:
        self.tool_name = tool_name
        self.field = field
        self.reason = reason
        field_part = f" (field: '{field}')" if field else ""
        super().__init__(f"[{tool_name}] contract violation{field_part}: {reason}")


# ── ToolContract ──────────────────────────────────────────────────────────────


class ToolContract(ABC):
    """
    Base contract for all LocalMind tools.

    Subclass rules:
      1. Set `name` to the tool's registry key (matches _TOOL_NAME_TO_INTENT).
      2. Set `schema` to a dict of {field_name: expected_type} for all
         REQUIRED fields. Optional fields are validated inside execute().
      3. Implement execute() to accept only the validated typed dict.
         No string parsing, no NL interpretation — ever.

    Validation guarantee:
      validate() returns (True, "") iff the payload matches schema exactly.
      On any mismatch it returns (False, human_reason).
      ContractViolationError is NOT raised here — the caller (orchestrator)
      decides whether to raise or log.

    Example:
        class WebSearchContract(ToolContract):
            name = "web_search"
            schema = {"query": str}

            async def execute(self, payload):
                return await _do_search(payload["query"])
    """

    name: str  # must be set on every concrete subclass
    schema: Dict[str, type] = {}  # required-field → expected type mapping

    @classmethod
    def validate(cls, payload: Dict[str, Any]) -> tuple[bool, str]:
        """
        Structural validator — presence + type only.

        Returns:
            (True,  "")            — payload is valid, execute() may proceed.
            (False, reason_str)    — payload is invalid; reason_str explains why.

        Never raises. Caller is responsible for acting on the result.
        """
        if not isinstance(payload, dict):
            return False, f"payload must be a dict, got {type(payload).__name__}"

        for field, expected_type in cls.schema.items():
            if field not in payload:
                return False, f"missing required field '{field}'"
            value = payload[field]
            if not isinstance(value, expected_type):
                return (
                    False,
                    f"field '{field}' expected {expected_type.__name__}, "
                    f"got {type(value).__name__}",
                )

        return True, ""

    @classmethod
    def validate_or_raise(cls, payload: Dict[str, Any]) -> None:
        """
        Convenience wrapper: validates and raises ContractViolationError on failure.

        Use this in the orchestrator's hot path — it produces a structured
        exception the dispatch loop can catch and turn into a clean rejection.
        """
        valid, reason = cls.validate(payload)
        if not valid:
            # Extract field name from reason for structured reporting
            field = ""
            if "field '" in reason:
                field = reason.split("'")[1]
            raise ContractViolationError(tool_name=cls.name, reason=reason, field=field)

    @abstractmethod
    async def execute(self, payload: Dict[str, Any]):
        """
        Execute the tool with a validated, typed dict payload.

        Precondition: validate(payload) returned (True, "").
        Postcondition: returns a ToolResult — never raises, never returns None.

        Tools MUST NOT:
          - accept or parse natural-language strings as intent
          - guess missing fields
          - fall back to a different execution path on bad input

        If a required field is missing despite the precondition, raise
        immediately — it means the schema did not declare it as required.
        """
        ...


# ── ToolRegistry ──────────────────────────────────────────────────────────────


class ToolRegistry:
    """
    Central registry for tool contracts.

    Single source of truth for orchestration. All contracts must be registered
    here before the orchestrator starts dispatching tasks. No dynamic discovery,
    no implicit loading — everything is explicit.

    Usage:
        ToolRegistry.register(WebSearchContract)
        contract_cls = ToolRegistry.get("web_search")
        valid, err = contract_cls.validate(payload)
    """

    _tools: Dict[str, Type[ToolContract]] = {}

    @classmethod
    def register(cls, tool_cls: Type[ToolContract]) -> None:
        """
        Register a ToolContract subclass.

        Raises:
            TypeError:  if tool_cls is not a ToolContract subclass.
            ValueError: if tool_cls.name is missing or empty.
        """
        if not (isinstance(tool_cls, type) and issubclass(tool_cls, ToolContract)):
            raise TypeError(f"register() expects a ToolContract subclass, got {tool_cls!r}")
        if not getattr(tool_cls, "name", ""):
            raise ValueError(
                f"ToolContract subclass {tool_cls.__name__} must define a non-empty 'name'"
            )
        cls._tools[tool_cls.name] = tool_cls

    @classmethod
    def get(cls, name: str) -> Type[ToolContract]:
        """
        Retrieve a registered contract by tool name.

        Raises:
            KeyError: if no contract is registered for name.
        """
        if name not in cls._tools:
            raise KeyError(
                f"No contract registered for tool '{name}'. Registered: {sorted(cls._tools)}"
            )
        return cls._tools[name]

    @classmethod
    def exists(cls, name: str) -> bool:
        """Return True if a contract is registered for name."""
        return name in cls._tools

    @classmethod
    def all_names(cls) -> list[str]:
        """Return sorted list of all registered tool names."""
        return sorted(cls._tools)


# ── resolve_contract (convenience) ───────────────────────────────────────────


def resolve_contract(tool_name: str) -> Type[ToolContract]:
    """
    Resolve a tool name to its registered ToolContract class.

    Raises:
        ValueError: if the tool has no registered contract.

    Use this at the start of any dispatch path that needs to validate before
    executing. If the tool is not yet migrated to Phase 3, it won't be in
    the registry — use ToolRegistry.exists() to guard before calling.
    """
    if not ToolRegistry.exists(tool_name):
        raise ValueError(
            f"No contract for tool '{tool_name}'. "
            f"Either register one or check ToolRegistry.exists() before calling."
        )
    return ToolRegistry.get(tool_name)
