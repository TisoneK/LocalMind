"""Tests for the additive capability-family catalog."""

from __future__ import annotations

import pytest

from core.capabilities import (
    CAPABILITY_CATALOG,
    CapabilityFamily,
    all_capability_families,
    capabilities_for_family,
    capability_metadata,
)
from core.models import Capability


def test_catalog_covers_every_capability():
    """Adding a capability requires adding its product-facing metadata."""
    assert set(CAPABILITY_CATALOG) == set(Capability)


def test_catalog_metadata_is_typed_and_descriptive():
    metadata = capability_metadata(Capability.FILE_READ)

    assert metadata.capability is Capability.FILE_READ
    assert metadata.family is CapabilityFamily.LOCAL_INFORMATION
    assert metadata.description
    assert metadata.tool_names == ("file_task",)
    assert metadata.cognitive is False


def test_cognitive_capabilities_have_no_tool_side_effect():
    for capability in capabilities_for_family(CapabilityFamily.KNOWLEDGE_REASONING):
        assert capability_metadata(capability).cognitive is True
        assert capability_metadata(capability).tool_names == ()


def test_capabilities_for_family_returns_only_that_family():
    internet = capabilities_for_family(CapabilityFamily.INTERNET)

    assert internet == (Capability.WEB_SEARCH, Capability.WEB_FETCH)
    assert all(capability_metadata(capability).family is CapabilityFamily.INTERNET for capability in internet)


def test_all_capability_families_matches_enum():
    assert all_capability_families() == tuple(CapabilityFamily)


def test_catalog_is_read_only():
    with pytest.raises(TypeError):
        CAPABILITY_CATALOG[Capability.FILE_READ] = capability_metadata(Capability.FILE_READ)  # type: ignore[index]
