"""
AI Connections — user-configurable model endpoints.

Every endpoint LocalMind can talk to is a Connection: a name, a base URL,
a key, a model, and the capabilities the endpoint is assumed or known to
have. Preset connections are seeded from the adapter registry
(PROVIDER_CONFIGS) so every existing provider keeps working untouched;
records stored in settings.json override preset fields or add entirely
new endpoints — a self-hosted gateway, a local proxy, any
OpenAI-compatible service — without a product-code change.

API keys are deliberately NOT stored on a connection record: they stay in
the existing ``api_keys`` map in settings.json (or env vars) and are
resolved through ``Settings.get_api_key(connection_id)``, so a custom
connection adds no new secret surface.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_valid_connection_id(value: str) -> bool:
    """Connection ids are slugs: lowercase letters, digits, single dashes."""
    return bool(_ID_PATTERN.match(value or ""))


@dataclass
class ConnectionCapabilities:
    """What an endpoint is assumed or known to support.

    Defaults are the historical assumptions: an OpenAI-compatible endpoint
    streams and calls tools. A connection test tightens these from
    evidence, and a user can override them by hand.
    """

    streaming: bool = True
    context_window: int = 0  # tokens; 0 = unknown (probe, then registry table)
    vision: bool = False
    tool_calling: bool = True
    structured_output: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ConnectionCapabilities":
        if not isinstance(data, dict):
            return cls()
        values: dict = {}
        for key in ("streaming", "vision", "tool_calling", "structured_output"):
            if key in data and isinstance(data[key], bool):
                values[key] = data[key]
        if "context_window" in data:
            try:
                values["context_window"] = max(0, int(data["context_window"]))
            except (TypeError, ValueError):
                pass
        return cls(**values)


@dataclass
class Connection:
    """One model endpoint, preset-seeded or user-defined."""

    id: str
    name: str
    kind: str = "openai-compat"  # "openai-compat" | "ollama"
    base_url: str = ""
    model: str = ""  # empty = the preset's default / legacy Settings field
    protocol: str = "openai"  # "openai" chat completions; room for future protocols
    capabilities: ConnectionCapabilities = field(default_factory=ConnectionCapabilities)
    enabled: bool = True
    fallback_to: str = ""  # connection id tried when this one fails; "" = none
    preset: bool = True  # seeded from the registry; the UI offers Reset, not Delete

    def to_dict(self) -> dict:
        """The fields a settings.json record stores (never the preset flag)."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "protocol": self.protocol,
            "capabilities": self.capabilities.to_dict(),
            "enabled": self.enabled,
            "fallback_to": self.fallback_to,
        }


def _seed_presets() -> dict[str, Connection]:
    """Preset connections: one per registry provider, plus Ollama."""
    # Lazy import — core.connections sits below adapters in the import graph
    # and must not pull the adapter package at module load time.
    from adapters.openai_compat import PROVIDER_CONFIGS

    presets: dict[str, Connection] = {
        "ollama": Connection(id="ollama", name="Ollama (local)", kind="ollama", preset=True),
    }
    for key, cfg in PROVIDER_CONFIGS.items():
        presets[key] = Connection(
            id=key,
            name=cfg.display_name or key,
            kind="openai-compat",
            base_url=(cfg.base_url or "").rstrip("/"),
            model="",
            preset=True,
        )
    return presets


def _merge_record(base: Connection | None, record: dict) -> dict:
    """Merge a stored record over a seed connection's effective fields."""
    merged: dict = base.to_dict() if base else {}
    for key in ("name", "kind", "base_url", "model", "protocol", "enabled", "fallback_to"):
        if key in record and record[key] is not None:
            merged[key] = record[key]
    if isinstance(record.get("capabilities"), dict):
        cap = merged.get("capabilities") or {}
        for key in ("streaming", "vision", "tool_calling", "structured_output", "context_window"):
            if key in record["capabilities"]:
                cap[key] = record["capabilities"][key]
        merged["capabilities"] = cap
    return merged


def _connection_from_record(base: Connection | None, record: dict, *, preset: bool) -> Connection:
    merged = _merge_record(base, record)
    return Connection(
        id=str(record["id"]),
        name=str(merged.get("name") or record["id"]),
        kind=str(merged.get("kind") or "openai-compat"),
        base_url=str(merged.get("base_url") or ""),
        model=str(merged.get("model") or ""),
        protocol=str(merged.get("protocol") or "openai"),
        capabilities=ConnectionCapabilities.from_dict(merged.get("capabilities")),
        enabled=bool(merged.get("enabled", True)),
        fallback_to=str(merged.get("fallback_to") or ""),
        preset=preset,
    )


class ConnectionRegistry:
    """Merged view of preset seeds and user records from settings.json."""

    def __init__(self, stored: list[dict] | None = None):
        self._presets = _seed_presets()
        self._stored: dict[str, dict] = {}
        for record in stored or []:
            if isinstance(record, dict) and isinstance(record.get("id"), str) and record["id"]:
                self._stored[record["id"]] = record

    def ids(self) -> list[str]:
        """Preset ids first, then custom ones — stable ordering for the UI."""
        return list(self._presets) + [cid for cid in self._stored if cid not in self._presets]

    def get(self, connection_id: str | None) -> Connection | None:
        connection_id = (connection_id or "").strip()
        if not connection_id:
            return None
        preset = self._presets.get(connection_id)
        record = self._stored.get(connection_id)
        if preset is None and record is None:
            return None
        if preset is None:
            return _connection_from_record(None, record, preset=False)
        if record is None:
            return preset
        return _connection_from_record(preset, record, preset=True)

    def all(self) -> list[Connection]:
        connections = [self.get(cid) for cid in self.ids()]
        return [c for c in connections if c is not None]


# ── Process-wide registry (rebuilt after settings changes) ──────────────────

_registry: ConnectionRegistry | None = None


def get_connection_registry() -> ConnectionRegistry:
    """Return the process registry, building it once from current settings."""
    global _registry
    if _registry is None:
        from core.config import settings  # lazy — avoids an import cycle

        _registry = ConnectionRegistry(list(getattr(settings, "_runtime_connections", []) or []))
    return _registry


def invalidate_connection_registry() -> None:
    """Drop the cached registry so the next lookup rebuilds from settings."""
    global _registry
    _registry = None
