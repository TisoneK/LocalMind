"""Static capability-family metadata for LocalMind.

This module is intentionally separate from ``core.models.Capability`` and
runtime observation state.  ``Capability`` remains the compatibility-facing
enum used by routing and execution; this catalog adds product vocabulary for
future capability discovery, UI presentation, and agent planning.

The catalog is descriptive only.  It does not register tools, change agent
selection, or execute anything.
"""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from core.models import Capability


class CapabilityFamily(str, Enum):
    """Broad product domain a capability belongs to."""

    KNOWLEDGE_REASONING = "knowledge_reasoning"
    LOCAL_INFORMATION = "local_information"
    INTERNET = "internet"
    COMPUTER = "computer"
    EXECUTION = "execution"
    MEMORY = "memory"


class CapabilityMetadata(BaseModel):
    """Static metadata describing one composable capability."""

    model_config = ConfigDict(frozen=True)

    capability: Capability
    family: CapabilityFamily
    description: str
    tool_names: tuple[str, ...] = Field(default_factory=tuple)
    cognitive: bool = False


# Keep this registry separate from the runtime tool registry.  A capability
# describes what the assistant may need; a tool describes how the runtime does
# it.  This separation lets future connectors expose capabilities without
# changing the existing Intent-based dispatch contract.
_CAPABILITY_CATALOG: dict[Capability, CapabilityMetadata] = {
    Capability.WEB_SEARCH: CapabilityMetadata(
        capability=Capability.WEB_SEARCH,
        family=CapabilityFamily.INTERNET,
        description="Search the live web for relevant sources.",
        tool_names=("web_search",),
    ),
    Capability.WEB_FETCH: CapabilityMetadata(
        capability=Capability.WEB_FETCH,
        family=CapabilityFamily.INTERNET,
        description="Fetch and read a specific web page or document.",
        tool_names=("web_fetch",),
    ),
    Capability.BROWSE: CapabilityMetadata(
        capability=Capability.BROWSE,
        family=CapabilityFamily.COMPUTER,
        description="Inspect and interact with a browser session.",
        tool_names=("browse",),
    ),
    Capability.CODE_EXEC: CapabilityMetadata(
        capability=Capability.CODE_EXEC,
        family=CapabilityFamily.EXECUTION,
        description="Execute a bounded Python computation.",
        tool_names=("code_exec",),
    ),
    Capability.SHELL: CapabilityMetadata(
        capability=Capability.SHELL,
        family=CapabilityFamily.EXECUTION,
        description="Run a system command in the user's workspace.",
        tool_names=("shell",),
    ),
    Capability.FILE_READ: CapabilityMetadata(
        capability=Capability.FILE_READ,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Read and analyze a local file or document.",
        tool_names=("file_task",),
    ),
    Capability.FILE_WRITE: CapabilityMetadata(
        capability=Capability.FILE_WRITE,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Create and save content in the local workspace.",
        tool_names=("file_write",),
    ),
    Capability.FILE_EDIT: CapabilityMetadata(
        capability=Capability.FILE_EDIT,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Apply a targeted edit to an existing local file.",
        tool_names=("edit_file",),
    ),
    Capability.MEMORY_STORE: CapabilityMetadata(
        capability=Capability.MEMORY_STORE,
        family=CapabilityFamily.MEMORY,
        description="Persist a user-approved fact or learning for later recall.",
        tool_names=("memory_op",),
    ),
    Capability.MEMORY_RETRIEVE: CapabilityMetadata(
        capability=Capability.MEMORY_RETRIEVE,
        family=CapabilityFamily.MEMORY,
        description="Retrieve relevant facts from LocalMind's persistent memory.",
        tool_names=("memory_op",),
    ),
    Capability.SYSINFO: CapabilityMetadata(
        capability=Capability.SYSINFO,
        family=CapabilityFamily.COMPUTER,
        description=(
            "Inspect system state: hardware, OS, network, GPU, processes, "
            "environment, uptime, users, services, installed programs, and time."
        ),
        tool_names=("sysinfo",),
    ),
    Capability.OBSERVE: CapabilityMetadata(
        capability=Capability.OBSERVE,
        family=CapabilityFamily.COMPUTER,
        description="Observe the desktop right now: active window, clipboard, running apps, "
        "system state, recently modified files (offline, bounded).",
        tool_names=("observe",),
    ),
    Capability.CALCULATE: CapabilityMetadata(
        capability=Capability.CALCULATE,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Evaluate a safe arithmetic expression exactly (offline, deterministic).",
        tool_names=("calculator",),
    ),
    Capability.CSV: CapabilityMetadata(
        capability=Capability.CSV,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Parse a local CSV file into a bounded aligned table.",
        tool_names=("csv",),
    ),
    Capability.JSON: CapabilityMetadata(
        capability=Capability.JSON,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Parse local JSON (file or inline) with optional dot-path queries, bounded.",
        tool_names=("json",),
    ),
    Capability.SQL: CapabilityMetadata(
        capability=Capability.SQL,
        family=CapabilityFamily.LOCAL_INFORMATION,
        description="Run read-only SQLite queries against a local database, bounded.",
        tool_names=("sql",),
    ),
    Capability.REASONING: CapabilityMetadata(
        capability=Capability.REASONING,
        family=CapabilityFamily.KNOWLEDGE_REASONING,
        description="Reason over the available context without a side effect.",
        cognitive=True,
    ),
    Capability.COMPARISON: CapabilityMetadata(
        capability=Capability.COMPARISON,
        family=CapabilityFamily.KNOWLEDGE_REASONING,
        description="Compare inputs and identify meaningful differences.",
        cognitive=True,
    ),
    Capability.SYNTHESIS: CapabilityMetadata(
        capability=Capability.SYNTHESIS,
        family=CapabilityFamily.KNOWLEDGE_REASONING,
        description="Combine evidence into a coherent answer or artifact.",
        cognitive=True,
    ),
    Capability.PLANNING: CapabilityMetadata(
        capability=Capability.PLANNING,
        family=CapabilityFamily.KNOWLEDGE_REASONING,
        description="Break a goal into bounded, verifiable work.",
        cognitive=True,
    ),
    Capability.PREDICTION: CapabilityMetadata(
        capability=Capability.PREDICTION,
        family=CapabilityFamily.KNOWLEDGE_REASONING,
        description="Project likely outcomes from the available evidence.",
        cognitive=True,
    ),
}

CAPABILITY_CATALOG: Mapping[Capability, CapabilityMetadata] = MappingProxyType(_CAPABILITY_CATALOG)


def capability_metadata(capability: Capability) -> CapabilityMetadata:
    """Return metadata for one capability.

    Raises:
        KeyError: if a new ``Capability`` enum member has not been cataloged.
    """

    return CAPABILITY_CATALOG[capability]


def capabilities_for_family(family: CapabilityFamily) -> tuple[Capability, ...]:
    """Return cataloged capabilities in declaration order for a family."""

    return tuple(
        capability
        for capability, metadata in CAPABILITY_CATALOG.items()
        if metadata.family == family
    )


def all_capability_families() -> tuple[CapabilityFamily, ...]:
    """Return families represented by the current catalog."""

    return tuple(CapabilityFamily)
