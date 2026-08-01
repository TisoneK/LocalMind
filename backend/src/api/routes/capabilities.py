"""Read-only capability catalog endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.capabilities import (
    CapabilityFamily,
    all_capability_families,
    capabilities_for_family,
    capability_metadata,
)

router = APIRouter()


class CapabilityItem(BaseModel):
    id: str
    description: str
    tool_names: tuple[str, ...] = ()
    cognitive: bool = False


class CapabilityFamilyResponse(BaseModel):
    id: str
    label: str
    capabilities: list[CapabilityItem] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    families: list[CapabilityFamilyResponse] = Field(default_factory=list)


def _family_label(family: CapabilityFamily) -> str:
    """Turn the stable enum identifier into a compact UI label."""

    return family.value.replace("_", " ").title()


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities() -> CapabilitiesResponse:
    """Return the descriptive capability catalog grouped by family.

    This endpoint is intentionally read-only. The catalog describes product
    vocabulary for discovery and UI presentation; it does not expose mutable
    registry state or alter routing/tool availability.
    """

    families: list[CapabilityFamilyResponse] = []
    for family in all_capability_families():
        capabilities = [
            CapabilityItem(
                id=capability.value,
                description=metadata.description,
                tool_names=metadata.tool_names,
                cognitive=metadata.cognitive,
            )
            for capability in capabilities_for_family(family)
            for metadata in (capability_metadata(capability),)
        ]
        families.append(
            CapabilityFamilyResponse(
                id=family.value,
                label=_family_label(family),
                capabilities=capabilities,
            )
        )

    return CapabilitiesResponse(families=families)
