"""CORS origins follow the configured ports — the browser preflight contract.

The dev stack can move off the default ports (scripts/dev-full.js picks a free
port when another app holds one, and propagates it via env). The API's CORS
list must follow: a frontend that moved to 3001 served from the browser hits
the API cross-origin, and a stale allow-origin list turns every request into a
failed preflight with nothing on the backend naming why.
"""

from __future__ import annotations

import pytest

from api.app import _cors_allow_origins


def test_defaults_cover_the_documented_dev_servers(monkeypatch):
    for var in ("LOCALMIND_FRONTEND_PORT", "LOCALMIND_CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)
    origins = _cors_allow_origins()
    for expected in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ):
        assert expected in origins


def test_frontend_port_env_adds_its_origins(monkeypatch):
    monkeypatch.setenv("LOCALMIND_FRONTEND_PORT", "4321")
    origins = _cors_allow_origins()
    assert "http://localhost:4321" in origins
    assert "http://127.0.0.1:4321" in origins


def test_invalid_frontend_port_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("LOCALMIND_FRONTEND_PORT", "not-a-number")
    origins = _cors_allow_origins()
    assert "http://localhost:3000" in origins
    assert "http://localhost:4321" not in origins


def test_explicit_override_replaces_the_whole_list(monkeypatch):
    monkeypatch.setenv("LOCALMIND_CORS_ORIGINS", "https://ui.example, http://localhost:9999")
    assert _cors_allow_origins() == ["https://ui.example", "http://localhost:9999"]


def test_blank_override_entries_are_dropped(monkeypatch):
    monkeypatch.setenv("LOCALMIND_CORS_ORIGINS", "https://ui.example,, ")
    assert _cors_allow_origins() == ["https://ui.example"]


@pytest.mark.parametrize("var", ["LOCALMIND_CORS_ORIGINS"])
def test_origins_are_unique(var, monkeypatch):
    monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALMIND_FRONTEND_PORT", "3000")
    origins = _cors_allow_origins()
    assert len(origins) == len(set(origins))
