"""Tests for the read-only capability catalog endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes import capabilities
from core.capabilities import CAPABILITY_CATALOG, CapabilityFamily


@pytest.mark.asyncio
async def test_capabilities_returns_all_cataloged_families_and_items():
    response = await capabilities.get_capabilities()

    assert [family.id for family in response.families] == [family.value for family in CapabilityFamily]
    returned_ids = {
        item.id
        for family in response.families
        for item in family.capabilities
    }
    assert returned_ids == {capability.value for capability in CAPABILITY_CATALOG}

    execution = next(
        family for family in response.families if family.id == CapabilityFamily.EXECUTION.value
    )
    shell = next(item for item in execution.capabilities if item.id == "shell")
    assert shell.description
    assert shell.tool_names == ("shell",)
    assert shell.cognitive is False


@pytest.mark.asyncio
async def test_capabilities_preserves_cognitive_metadata_without_tools():
    response = await capabilities.get_capabilities()

    reasoning = next(
        item
        for family in response.families
        for item in family.capabilities
        if item.id == "reasoning"
    )
    assert reasoning.cognitive is True
    assert reasoning.tool_names == ()


def test_capabilities_route_has_typed_response_model():
    route = next(
        route
        for route in capabilities.router.routes
        if getattr(route, "path", "") == "/capabilities"
    )

    assert route.response_model is capabilities.CapabilitiesResponse


def test_registered_capabilities_route_serializes_through_app():
    client = TestClient(create_app(), raise_server_exceptions=True)

    response = client.get("/api/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["families"]
    assert any(item["id"] == "shell" for family in payload["families"] for item in family["capabilities"])
