"""
Settings endpoints for adapter and provider configuration.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from adapters import clear_adapter_cache
from core.config import settings

router = APIRouter()


class SettingsResponse(BaseModel):
    adapter: str
    model: str
    embed_model: Optional[str] = None  # Ollama embedding model (always local)
    # Context window (num_ctx) the loop budgets / Ollama allocates.
    # 0 = auto-detect the model's real declared window; >0 = explicit override.
    num_ctx: int = 0
    # Whether the shell tool is enabled (was env-only, now UI-toggle).
    shell_enabled: bool = False
    providers: dict
    # AI connections (preset providers + user-defined endpoints). Each entry:
    # id, name, kind, base_url, model, protocol, capabilities, enabled,
    # fallback_to, preset, api_key_set. The active adapter is one of these
    # ids (or "ollama").
    connections: list = Field(default_factory=list)
    # Reasoning-model thinking policy (z.ai/GLM).
    # Mirrored to the Settings UI so users can tune thinking without env vars.
    thinking: str = "enabled"
    reasoning_timeout: float = 180.0
    reasoning_plan_timeout: float = 30.0
    reasoning_max_wall_clock: float = 360.0
    reasoning_effort: str = ""
    # UI appearance (theme/mode/custom palette/tone),
    # persisted in settings.json by POST /api/settings/appearance.
    theme: str = "graphite"
    mode: str = "dark"
    custom_theme: Optional[dict] = None
    tone: float = 1.0
    # Startup session behavior — "resume" or "new".
    startup_session: str = "new"
    # Chat mode — "auto" | "agent" | "direct".
    chat_mode: str = "auto"
    # Agent engine — "classic" | "state" (experimental, ADR-71).
    engine: str = "classic"
    # Configurable operation permissions.
    permissions: dict = {
        "file_read": True,
        "file_write": True,
        "file_edit": True,
        "shell": True,
        "code_exec": True,
        "web_search": True,
        "web_fetch": True,
        "memory_op": True,
    }


class AdapterConfig(BaseModel):
    adapter: str
    model: Optional[str] = None


class ThinkingSettingsRequest(BaseModel):
    """Body for POST /api/settings/thinking (reasoning policy).

    All fields optional so a partial update is safe: only provided fields
    are applied and persisted. reasoning_effort="" clears the effort.
    """

    thinking: Optional[str] = None  # "enabled" | "disabled"
    reasoning_timeout: Optional[float] = None  # per-call seconds when thinking
    reasoning_plan_timeout: Optional[float] = None  # plan/init/orchestrator s
    reasoning_max_wall_clock: Optional[float] = None  # total-turn cap when thinking
    reasoning_effort: Optional[str] = None  # GLM-5.2+ effort level


class ProviderKeyRequest(BaseModel):
    provider: str
    api_key: str
    model: Optional[str] = None


class StartupSessionRequest(BaseModel):
    """Body for POST /api/settings/startup-session."""
    startup_session: str  # "resume" | "new"


@router.post("/settings/startup-session")
async def set_startup_session(req: StartupSessionRequest):
    """Persist the startup session behavior.

    "resume" = auto-open the most recent session on launch.
    "new" = start with a blank chat every time.
    """
    val = req.startup_session.strip().lower()
    if val not in ("resume", "new"):
        raise HTTPException(status_code=400, detail="startup_session must be 'resume' or 'new'")
    settings.localmind_startup_session = val
    # Persist to settings.json (write explicitly so False/empty don't get lost).
    _path = settings._runtime_settings_path()
    _data = settings._load_json_file(_path)
    _data["startup_session"] = val
    settings._secure_write_json(_path, _data)
    return {"startup_session": val, "message": f"Startup behavior set to {val}"}


class ChatModeRequest(BaseModel):
    """Body for POST /api/settings/chat-mode."""
    chat_mode: str  # "auto" | "agent" | "direct"


@router.post("/settings/chat-mode")
async def set_chat_mode(req: ChatModeRequest):
    """Persist the chat mode.

    "auto" = classifier decides (default).
    "agent" = always full agent loop.
    "direct" = no tools, lightweight chat.
    """
    val = req.chat_mode.strip().lower()
    if val not in ("auto", "agent", "direct"):
        raise HTTPException(status_code=400, detail="chat_mode must be 'auto', 'agent', or 'direct'")
    settings.localmind_chat_mode = val
    # Persist to settings.json (write explicitly so the value survives restart).
    _path = settings._runtime_settings_path()
    _data = settings._load_json_file(_path)
    _data["chat_mode"] = val
    settings._secure_write_json(_path, _data)
    return {"chat_mode": val, "message": f"Chat mode set to {val}"}


class EngineRequest(BaseModel):
    """Body for POST /api/settings/engine."""
    engine: str  # "classic" | "state"


@router.post("/settings/engine")
async def set_engine(req: EngineRequest):
    """Persist the agent engine: "classic" (default) or "state" (experimental, read-only, ADR-71).

    Independent of the provider and model. Chat keeps working on either; the UI shows the
    State Explorer instead of the chat pane while "state" is selected.
    """
    val = req.engine.strip().lower()
    if val not in ("classic", "state"):
        raise HTTPException(status_code=400, detail="engine must be 'classic' or 'state'")
    settings.localmind_engine = val
    _path = settings._runtime_settings_path()
    _data = settings._load_json_file(_path)
    _data["engine"] = val
    settings._secure_write_json(_path, _data)
    return {"engine": val, "message": f"Engine set to {val}"}


class ShellRequest(BaseModel):
    """Body for POST /api/settings/shell."""
    shell: str  # "auto" or a shell id from GET /api/settings/shell


@router.get("/settings/shell")
async def get_shell():
    from core.shell_config import configured, detect_shells

    return {"shell": configured(), "options": [c.to_dict() for c in detect_shells()]}


@router.post("/settings/shell")
async def set_shell(req: ShellRequest):
    """Choose the shell commands run in (terminal panel and the agent's shell tool)."""
    from core.shell_config import detect_shells

    val = req.shell.strip().lower()
    known = {c.id: c for c in detect_shells()}
    if val != "auto" and val not in known:
        raise HTTPException(status_code=400, detail=f"Unknown shell: {val}")
    if val != "auto" and not known[val].available:
        raise HTTPException(status_code=400, detail=f"{known[val].label} is not installed on this machine")
    settings.localmind_shell = val
    _path = settings._runtime_settings_path()
    _data = settings._load_json_file(_path)
    _data["shell"] = val
    settings._secure_write_json(_path, _data)
    return {"shell": val, "message": f"Commands now run in: {val}"}


class PackageEnvRequest(BaseModel):
    """Body for POST /api/settings/package-env."""
    package_env: str  # "localmind" | "system"


@router.get("/settings/package-env")
async def get_package_env():
    from core.package_env import mode, packages_dir

    return {"package_env": mode(), "packages_dir": str(packages_dir())}


@router.post("/settings/package-env")
async def set_package_env(req: PackageEnvRequest):
    """Choose where installs go: LocalMind's own packages folder, or the system Python."""
    val = req.package_env.strip().lower()
    if val not in ("localmind", "system"):
        raise HTTPException(status_code=400, detail="package_env must be 'localmind' or 'system'")
    settings.localmind_package_env = val
    _path = settings._runtime_settings_path()
    _data = settings._load_json_file(_path)
    _data["package_env"] = val
    settings._secure_write_json(_path, _data)
    from core.package_env import packages_dir

    return {"package_env": val, "packages_dir": str(packages_dir()), "message": f"Installs go to: {val}"}


class PermissionsRequest(BaseModel):
    """Body for POST /api/settings/permissions.

    All fields optional so a partial update is safe. Only recognized keys
    are applied; unknown keys are silently ignored.
    """

    file_read: Optional[bool] = None
    file_write: Optional[bool] = None
    file_edit: Optional[bool] = None
    shell: Optional[bool] = None
    code_exec: Optional[bool] = None
    web_search: Optional[bool] = None
    web_fetch: Optional[bool] = None
    memory_op: Optional[bool] = None


@router.post("/settings/permissions")
async def set_permissions(req: PermissionsRequest):
    """Update operation permissions and persist to settings.json."""
    payload = {}
    for key in ("file_read", "file_write", "file_edit", "shell", "code_exec", "web_search", "web_fetch", "memory_op"):
        val = getattr(req, key, None)
        if val is not None:
            settings.localmind_permissions[key] = val
            payload[key] = val
    # Persist to settings.json (direct write so boolean False isn't lost).
    _path = settings._runtime_settings_path()
    _data = settings._load_json_file(_path)
    _data["permissions"] = dict(settings.localmind_permissions)
    settings._secure_write_json(_path, _data)
    return {**settings.localmind_permissions, "message": "Permissions updated"}


class AppearanceRequest(BaseModel):
    """Body for POST /api/settings/appearance.

    All fields optional so a partial update is safe. `theme` is one of the
    built-in palette ids plus "custom" (user-defined palette via the UI);
    `custom_theme` carries the custom definition {name, accent, background,
    surface, text}; `tone` is the UI brightness multiplier (1 = unchanged).
    """

    theme: Optional[str] = None  # graphite | iris | warm | custom
    mode: Optional[str] = None  # light | dark | system
    custom_theme: Optional[dict] = None
    tone: Optional[float] = None  # 0.5–1.5


@router.post("/settings/appearance")
async def set_appearance(req: AppearanceRequest):
    """Apply and persist the UI appearance.

    The user's chosen theme (built-in palette or a custom palette defined in
    the UI), mode, custom palette definition, and tone/brightness are saved
    to settings.json so they survive restarts. The frontend reads them back
    via GET /api/settings on startup and re-applies them, so appearance is
    durable across launches (mirrors the adapter/model persistence flow).
    """
    valid_themes = ("graphite", "iris", "warm", "custom")
    valid_modes = ("light", "dark", "system")

    path = settings._runtime_settings_path()
    data = settings._load_json_file(path)

    if req.theme is not None:
        theme = req.theme.strip().lower()
        if theme not in valid_themes:
            raise HTTPException(status_code=400, detail=f"theme must be one of {', '.join(valid_themes)}")
        data["theme"] = theme
    if req.mode is not None:
        mode = req.mode.strip().lower()
        if mode not in valid_modes:
            raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(valid_modes)}")
        data["mode"] = mode
    if req.custom_theme is not None:
        custom = req.custom_theme or {}
        required = {"name", "accent", "background", "surface", "text"}
        missing = required - set(custom.keys())
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"custom_theme missing keys: {', '.join(sorted(missing))}",
            )
        data["custom_theme"] = {
            "name": str(custom.get("name", "")).strip() or "Custom",
            "accent": str(custom.get("accent", "#34d399")),
            "background": str(custom.get("background", "#12161d")),
            "surface": str(custom.get("surface", "#1f2530")),
            "text": str(custom.get("text", "#e6edf3")),
        }
    if req.tone is not None:
        if not (0.5 <= req.tone <= 1.5):
            raise HTTPException(status_code=400, detail="tone must be between 0.5 and 1.5")
        data["tone"] = round(float(req.tone), 3)

    settings._secure_write_json(path, data)
    return {
        "theme": data.get("theme", "graphite"),
        "mode": data.get("mode", "dark"),
        "custom_theme": data.get("custom_theme"),
        "tone": data.get("tone", 1.0),
        "message": "Appearance saved",
    }




# Provider info is derived from the single source of truth in
# PROVIDER_CONFIGS (adapters/openai_compat.py). Adding a new provider
# there automatically makes it available everywhere — no need to update
# this file.
from adapters.openai_compat import PROVIDER_CONFIGS

PROVIDER_INFO: dict[str, dict] = {
    key: {
        "name": cfg.display_name,
        "model_env": cfg.model_env,
        "key_env": cfg.key_env,
        "default_model": cfg.default_model,
    }
    for key, cfg in PROVIDER_CONFIGS.items()
}

# Valid adapter names for validation (ollama + all cloud providers)
VALID_ADAPTERS: list[str] = ["ollama"] + list(PROVIDER_CONFIGS.keys())

# Map: adapter key → settings field name (derived, not hardcoded)
ADAPTER_MODEL_FIELDS: dict[str, str] = {
    "ollama": "ollama_model",
    **{key: cfg.settings_field for key, cfg in PROVIDER_CONFIGS.items()},
}


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """
    Get current adapter and model configuration.
    """
    adapter = settings.localmind_adapter
    # Persisted appearance (theme/mode/custom palette/tone).
    appearance = _read_appearance()

    # Derive the model-setting map from ADAPTER_MODEL_FIELDS (single source
    # of truth in PROVIDER_CONFIGS). No hardcoded provider list.
    model_setting_map = {
        key: getattr(settings, field, "")
        for key, field in ADAPTER_MODEL_FIELDS.items()
    }
    current_model = model_setting_map.get(adapter) or settings.ollama_model
    embed_model = settings.ollama_embed_model

    # Build provider info (whether API key is set)
    # Check both runtime-stored keys (settings.json) and env vars.
    # The settings field name comes from ADAPTER_MODEL_FIELDS (derived from
    # PROVIDER_CONFIGS) — don't reconstruct it from model_env, which couples
    # this code to the env-var-naming convention and breaks if they ever diverge.
    providers = {}
    for prov, info in PROVIDER_INFO.items():
        runtime_key = settings.get_api_key(prov)
        env_key = os.getenv(info["key_env"], "")
        key_set = bool(runtime_key or env_key)
        settings_field = ADAPTER_MODEL_FIELDS.get(prov, "")
        model_value = (getattr(settings, settings_field, "") if settings_field else "") or info["default_model"]
        providers[prov] = {
            "name": info["name"],
            "api_key_set": key_set,
            "model": model_value,
            "default_model": info["default_model"],
        }

    # AI connections — the merged preset + user-defined list. The active
    # connection sorts first so the UI can default to it; the rest follow
    # registry order (presets, then custom) with disabled ones last.
    from core.connections import get_connection_registry

    registry = get_connection_registry()
    all_connections = registry.all()
    order: dict[str, int] = {}
    for conn in all_connections:
        rank = 0
        if conn.id != adapter:
            rank += 10
        if not conn.enabled:
            rank += 100
        order[conn.id] = rank
    ordered = sorted(all_connections, key=lambda c: (order.get(c.id, 0), registry.ids().index(c.id)))

    connections = []
    for conn in ordered:
        connections.append({
            "id": conn.id,
            "name": conn.name,
            "kind": conn.kind,
            "base_url": conn.base_url,
            "model": conn.model,
            "protocol": conn.protocol,
            "capabilities": conn.capabilities.to_dict(),
            "enabled": conn.enabled,
            "fallback_to": conn.fallback_to,
            "extra_models": list(conn.extra_models),
            "hidden_models": list(conn.hidden_models),
            "preset": conn.preset,
            "api_key_set": bool(settings.get_api_key(conn.id)),
        })

    return SettingsResponse(
        adapter=adapter,
        model=current_model,
        embed_model=embed_model,
        num_ctx=int(getattr(settings, "ollama_num_ctx", 0) or 0),
        shell_enabled=bool(getattr(settings, "localmind_shell_enabled", False)),
        providers=providers,
        connections=connections,
        thinking=settings.localmind_thinking,
        reasoning_timeout=settings.localmind_reasoning_timeout_secs,
        reasoning_plan_timeout=settings.localmind_reasoning_plan_timeout_secs,
        reasoning_max_wall_clock=settings.localmind_reasoning_max_wall_clock_secs,
        reasoning_effort=settings.localmind_reasoning_effort,
        # Appearance from settings.json (theme/mode/custom
        # palette/tone) so the UI restores the persisted choice on launch.
        theme=appearance.get("theme", "graphite"),
        mode=appearance.get("mode", "dark"),
        custom_theme=appearance.get("custom_theme"),
        tone=float(appearance.get("tone", 1.0) or 1.0),
        # Startup session behavior
        startup_session=getattr(settings, "localmind_startup_session", "new"),
        # Chat mode
        chat_mode=getattr(settings, "localmind_chat_mode", "auto"),
        engine=getattr(settings, "localmind_engine", "classic"),
        # Operation permissions
        permissions=dict(getattr(settings, "localmind_permissions", {})),
    )


def _read_appearance():
    """Read persisted appearance from settings.json (best-effort)."""
    try:
        data = settings._load_json_file(settings._runtime_settings_path())
        return {
            "theme": data.get("theme", "graphite"),
            "mode": data.get("mode", "dark"),
            "custom_theme": data.get("custom_theme"),
            "tone": float(data.get("tone", 1.0) or 1.0),
        }
    except Exception:
        return {"theme": "graphite", "mode": "dark", "custom_theme": None, "tone": 1.0}


@router.post("/settings/thinking")
async def set_thinking_settings(req: ThinkingSettingsRequest):
    """
    Update the reasoning-model thinking policy and persist it to
    settings.json so it survives restarts.

    Applies only the fields the client actually sends. The adapter reads
    these from the Settings singleton on every call, and load_runtime_settings
    applies settings.json after pydantic folds the env in — so a UI setting
    wins over LOCALMIND_THINKING / LOCALMIND_REASONING_* env vars.
    """
    if req.thinking is not None:
        if req.thinking not in ("enabled", "disabled"):
            raise HTTPException(status_code=400, detail="thinking must be 'enabled' or 'disabled'")
        settings.localmind_thinking = req.thinking
    if req.reasoning_timeout is not None:
        if req.reasoning_timeout < 45:
            raise HTTPException(status_code=400, detail="reasoning_timeout must be >= 45 seconds")
        settings.localmind_reasoning_timeout_secs = float(req.reasoning_timeout)
    if req.reasoning_plan_timeout is not None:
        if req.reasoning_plan_timeout < 8:
            raise HTTPException(status_code=400, detail="reasoning_plan_timeout must be >= 8 seconds")
        settings.localmind_reasoning_plan_timeout_secs = float(req.reasoning_plan_timeout)
    if req.reasoning_max_wall_clock is not None:
        if req.reasoning_max_wall_clock < 180:
            raise HTTPException(status_code=400, detail="reasoning_max_wall_clock must be >= 180 seconds")
        settings.localmind_reasoning_max_wall_clock_secs = float(req.reasoning_max_wall_clock)
    if req.reasoning_effort is not None:
        settings.localmind_reasoning_effort = req.reasoning_effort.strip().lower()

    settings.save_runtime_settings(
        thinking=settings.localmind_thinking,
        reasoning_timeout=settings.localmind_reasoning_timeout_secs,
        reasoning_plan_timeout=settings.localmind_reasoning_plan_timeout_secs,
        reasoning_max_wall_clock=settings.localmind_reasoning_max_wall_clock_secs,
        reasoning_effort=settings.localmind_reasoning_effort,
    )
    # save_runtime_settings PRESERVES empty values (so a partial update can't
    # clobber a saved model), which means an explicitly-cleared effort would
    # linger in settings.json and reappear on restart. Remove the key directly
    # when the user clears it. Guarded on an explicit empty request so partial
    # updates (effort untouched) never touch the file.
    if req.reasoning_effort is not None and not settings.localmind_reasoning_effort:
        try:
            _path = settings._runtime_settings_path()
            _data = settings._load_json_file(_path)
            if "reasoning_effort" in _data:
                _data.pop("reasoning_effort")
                settings._secure_write_json(_path, _data)
        except Exception:
            pass  # best-effort cleanup; the live value is already correct
    # The adapter caches provider params; rebuild so the new policy applies
    # to the next call without a restart.
    clear_adapter_cache()

    return {
        "thinking": settings.localmind_thinking,
        "reasoning_timeout": settings.localmind_reasoning_timeout_secs,
        "reasoning_plan_timeout": settings.localmind_reasoning_plan_timeout_secs,
        "reasoning_max_wall_clock": settings.localmind_reasoning_max_wall_clock_secs,
        "reasoning_effort": settings.localmind_reasoning_effort,
        "message": f"Reasoning thinking {'enabled' if settings.localmind_thinking != 'disabled' else 'disabled'}",
    }


class LocalSettingsRequest(BaseModel):
    """Body for POST /api/settings/local — Ollama-local knobs.

    Both fields optional so a partial update is safe. embed_model changes the
    local embedding model used for memory/RAG; num_ctx overrides the context
    window budget (0 = auto-detect the model's real declared window).
    """

    embed_model: Optional[str] = None
    num_ctx: Optional[int] = None
    shell_enabled: Optional[bool] = None


@router.post("/settings/local")
async def set_local_settings(req: LocalSettingsRequest):
    """Update Ollama-local settings (embedding model, context window) and
    persist them to settings.json so they survive restarts.

    num_ctx is validated as >= 0 (0 = auto). The adapter reads both from the
    Settings singleton, so clearing the adapter cache makes the change apply to
    the next request without a restart.
    """
    updated: dict = {}
    if req.embed_model is not None:
        embed = req.embed_model.strip()
        if not embed:
            raise HTTPException(status_code=400, detail="embed_model cannot be empty")
        settings.ollama_embed_model = embed
        settings.save_runtime_settings(embed_model=embed)
        updated["embed_model"] = embed
    if req.num_ctx is not None:
        if req.num_ctx < 0:
            raise HTTPException(status_code=400, detail="num_ctx must be >= 0 (0 = auto)")
        settings.ollama_num_ctx = int(req.num_ctx)
        # num_ctx=0 is meaningful (auto) but save_runtime_settings preserves
        # empty/zero via the "key absent" path — write it explicitly so a reset
        # to auto persists instead of leaving a stale override in the file.
        _path = settings._runtime_settings_path()
        _data = settings._load_json_file(_path)
        _data["num_ctx"] = int(req.num_ctx)
        settings._secure_write_json(_path, _data)
        updated["num_ctx"] = int(req.num_ctx)
    if req.shell_enabled is not None:
        settings.localmind_shell_enabled = bool(req.shell_enabled)
        # Boolean False is meaningful (disable) — write explicitly rather than
        # via save_runtime_settings' non-empty-only path.
        _path = settings._runtime_settings_path()
        _data = settings._load_json_file(_path)
        _data["shell_enabled"] = bool(req.shell_enabled)
        settings._secure_write_json(_path, _data)
        updated["shell_enabled"] = bool(req.shell_enabled)

    # Rebuild adapters so the new local settings apply on the next call.
    clear_adapter_cache()

    return {
        "embed_model": settings.ollama_embed_model,
        "num_ctx": int(getattr(settings, "ollama_num_ctx", 0) or 0),
        "updated": list(updated.keys()),
        "message": "Local settings updated" if updated else "No changes",
    }


@router.post("/settings/adapter")
async def set_adapter(req: AdapterConfig):
    """
    Switch to a different adapter (ollama, a preset provider, or a custom
    AI connection).
    """
    from core.connections import get_connection_registry, invalidate_connection_registry

    registry = get_connection_registry()
    connection = registry.get(req.adapter)
    if connection is None:
        raise HTTPException(status_code=400, detail=f"Invalid adapter. Valid: {sorted(registry.ids())}")
    if not connection.enabled:
        raise HTTPException(
            status_code=400,
            detail=f"Connection '{connection.name}' is disabled — enable it in the AI Connections settings first.",
        )

    # For preset cloud providers, check if an API key is available (runtime
    # storage or env var). Custom connections may legitimately run without a
    # key (local gateways), so they skip the check.
    if req.adapter != "ollama":
        info = PROVIDER_INFO.get(req.adapter)
        if info:
            runtime_key = settings.get_api_key(req.adapter)
            env_key = os.getenv(info["key_env"], "")
            if not (runtime_key or env_key):
                raise HTTPException(
                    status_code=400,
                    detail=f"API key not set for {info['name']}. Set it via the Settings UI or {info['key_env']} in .env.",  # noqa: E501
                )

    settings.localmind_adapter = req.adapter
    # Clear adapter cache so new adapter is used for next request
    clear_adapter_cache()

    # Resolve the model: the explicitly requested model, then the
    # connection's declared model, then the preset's saved model, then the
    # preset default. For presets the resolved model persists through the
    # historical Settings field; for custom connections it persists on the
    # connection record itself.
    model_field = ADAPTER_MODEL_FIELDS.get(req.adapter)
    if model_field:
        resolved_model = (
            req.model
            or connection.model
            or getattr(settings, model_field, "")
            or PROVIDER_INFO.get(req.adapter, {}).get("default_model", "")
        )
        if resolved_model:
            setattr(settings, model_field, resolved_model)
    else:
        resolved_model = req.model or connection.model or ""

    # Persist runtime settings to JSON file for restart survival.
    if req.adapter == "ollama":
        settings.save_runtime_settings(adapter=req.adapter, ollama_model=resolved_model)
    elif model_field:
        settings.save_runtime_settings(adapter=req.adapter, model=resolved_model)
    else:
        # Custom connection — the model lives on the connection record.
        record = connection.to_dict()
        record["model"] = resolved_model
        settings.save_connection_record(record)
        settings.save_runtime_settings(adapter=req.adapter)
        invalidate_connection_registry()
        clear_adapter_cache()

    return {
        "adapter": settings.localmind_adapter,
        "model": resolved_model or "default",
        "message": f"Switched to {req.adapter}",
    }


@router.post("/settings/provider-key")
async def set_provider_key(req: ProviderKeyRequest):
    """
    Validate and store a provider API key at runtime.
    The key is saved to settings.json so it persists across restarts.

    After saving, a lightweight health check is run against the provider
    so the user gets immediate feedback if the key is invalid (typo,
    wrong account, expired). The key is saved regardless of the health
    check result — the user may be offline, or the provider may be
    temporarily unreachable. The `validated` field reflects the health
    check outcome.
    """
    if req.provider == "ollama":
        raise HTTPException(status_code=400, detail="Ollama needs no API key.")
    from core.connections import get_connection_registry

    connection = get_connection_registry().get(req.provider)
    if connection is None:
        valid = sorted(get_connection_registry().ids())
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {valid}")

    info = PROVIDER_INFO.get(req.provider, {"name": connection.name, "key_env": None})

    # Save the API key to runtime storage first — we want it persisted
    # even if the health check fails (user may be offline).
    settings.save_api_key(req.provider, req.api_key)

    # If a model was provided, persist it too so the adapter uses it
    # on the next request. For presets that is the historical Settings
    # field; for custom connections the model lives on the record.
    if req.model:
        model_field = ADAPTER_MODEL_FIELDS.get(req.provider, "")
        if model_field and hasattr(settings, model_field):
            setattr(settings, model_field, req.model)
            settings.save_runtime_settings(adapter=req.provider, model=req.model)
        else:
            from core.connections import invalidate_connection_registry

            record = connection.to_dict()
            record["model"] = req.model
            settings.save_connection_record(record)
            invalidate_connection_registry()

    # Run a health check against the provider to validate the key.
    # This is best-effort: a False result doesn't unsave the key.
    validated = False
    validation_error: str | None = None
    try:
        from adapters import clear_adapter_cache, get_adapter

        # Clear the cache so the new key is picked up (the cached adapter
        # may have been constructed with the old key or none at all).
        clear_adapter_cache(req.provider)
        adapter = get_adapter(req.provider)
        validated = await adapter.health_check()
        if not validated:
            validation_error = "Key saved, but the provider did not respond to a health check. The key may be invalid, the provider may be down, or your network may be blocking the request."  # noqa: E501
        # Close the adapter's HTTP client to avoid leaking connections.
        if hasattr(adapter, "close"):
            await adapter.close()
    except Exception as exc:
        # Adapter construction can raise ValueError if the key is empty
        # or the provider is misconfigured. Surface that as a validation
        # failure rather than a 500.
        validation_error = f"Key saved, but validation failed: {exc}"

    # Clear the cache again so the next chat request builds a fresh
    # adapter with the validated key.
    clear_adapter_cache(req.provider)

    return {
        "provider": req.provider,
        "name": info["name"],
        "validated": validated,
        "validation_error": validation_error,
        "message": (
            f"API key saved for {info['name']}."
            if validated
            else f"API key saved for {info['name']}, but validation failed."
        ),
    }


class DeleteProviderKeyRequest(BaseModel):
    provider: str


@router.delete("/settings/provider-key")
async def delete_provider_key(req: DeleteProviderKeyRequest):
    """
    Delete a stored provider API key.

    Previously, once a key was saved via POST /settings/provider-key, there
    was no way to revoke it without manually editing settings.json. This
    endpoint allows the frontend to remove a key cleanly.
    """
    if req.provider not in PROVIDER_INFO:
        from core.connections import get_connection_registry

        connection = get_connection_registry().get(req.provider)
        if connection is None:
            valid = sorted(get_connection_registry().ids())
            raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {valid}")
        info = {"name": connection.name}
    else:
        info = PROVIDER_INFO[req.provider]

    removed = settings.delete_api_key(req.provider)

    return {
        "provider": req.provider,
        "name": info["name"],
        "deleted": removed,
        "message": f"API key removed for {info['name']}" if removed else f"No API key was stored for {info['name']}",
    }


# ── AI Connections — user-configurable endpoints ────────────────────────────
# Preset providers + user-defined connections live in settings.json under
# `connections` and overlay the seeded registry (core/connections.py). A new
# endpoint — a gateway, a proxy, any OpenAI-compatible service — needs no
# product-code change: add a connection here and switch to it.

class ConnectionSaveRequest(BaseModel):
    """Body for POST /api/settings/connections (create or update).

    All fields optional for an update; a NEW connection (id not yet known)
    requires id, name, base_url, and model.
    """

    id: Optional[str] = None
    name: Optional[str] = None
    kind: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[str] = None
    capabilities: Optional[dict] = None
    enabled: Optional[bool] = None
    fallback_to: Optional[str] = None
    extra_models: Optional[list] = None
    hidden_models: Optional[list] = None


_CAPABILITY_KEYS = ("streaming", "vision", "tool_calling", "structured_output", "context_window")


def _clean_model_ids(values: list) -> list[str]:
    """Trimmed, de-duplicated model ids (bounded, so a bad client cannot bloat settings.json)."""
    seen: list[str] = []
    for v in values or []:
        item = str(v).strip()
        if item and item not in seen:
            seen.append(item)
    return seen[:200]


def _validated_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="base_url must start with http:// or https://")
    return value


@router.post("/settings/connections")
async def save_connection(req: ConnectionSaveRequest):
    """Create or update an AI connection.

    Updating a preset stores an override record (the seed stays untouched;
    deleting the record resets the preset). Creating a new connection adds
    a user-defined endpoint with a fresh id.
    """
    from core.connections import (
        get_connection_registry,
        invalidate_connection_registry,
        is_valid_connection_id,
    )

    registry = get_connection_registry()
    existing = registry.get(req.id) if req.id else None

    if existing is None:
        # ── New custom connection ──
        if not req.id or not is_valid_connection_id(req.id):
            raise HTTPException(
                status_code=400,
                detail="New connections need an id: lowercase letters, digits and single dashes (e.g. 'atria-proxy').",
            )
        if req.id in registry.ids():
            raise HTTPException(status_code=400, detail=f"A connection named '{req.id}' already exists.")
        if not req.name or not req.name.strip():
            raise HTTPException(status_code=400, detail="New connections need a name.")
        if not req.base_url:
            raise HTTPException(status_code=400, detail="New connections need a base URL.")
        if not req.model or not req.model.strip():
            raise HTTPException(status_code=400, detail="New connections need a model id.")
        base_url = _validated_base_url(req.base_url)
        record = {
            "id": req.id,
            "name": req.name.strip(),
            "kind": "openai-compat",
            "base_url": base_url,
            "model": req.model.strip(),
            "protocol": (req.protocol or "openai").strip(),
            "capabilities": _validated_capabilities(req.capabilities),
            "enabled": req.enabled if req.enabled is not None else True,
            "fallback_to": (req.fallback_to or "").strip(),
        }
        message = f"Created connection '{req.name.strip()}'."
    else:
        # ── Update (preset override or custom edit) ──
        record = existing.to_dict()
        if req.name is not None:
            if not req.name.strip():
                raise HTTPException(status_code=400, detail="name cannot be empty.")
            record["name"] = req.name.strip()
        if req.base_url is not None:
            record["base_url"] = _validated_base_url(req.base_url)
        if req.model is not None:
            record["model"] = req.model.strip()
        if req.protocol is not None:
            record["protocol"] = req.protocol.strip() or "openai"
        if req.capabilities is not None:
            caps = record.get("capabilities") or {}
            caps.update(_validated_capabilities(req.capabilities))
            record["capabilities"] = caps
        if req.enabled is not None:
            record["enabled"] = bool(req.enabled)
        if req.fallback_to is not None:
            record["fallback_to"] = (req.fallback_to or "").strip()
        if req.extra_models is not None:
            record["extra_models"] = _clean_model_ids(req.extra_models)
        if req.hidden_models is not None:
            record["hidden_models"] = _clean_model_ids(req.hidden_models)
        if req.kind is not None:
            # Kind is structural (routes to the adapter family) — only the
            # ollama preset uses "ollama"; refuse silent rewrites.
            if req.kind not in ("openai-compat", "ollama"):
                raise HTTPException(status_code=400, detail="kind must be 'openai-compat' or 'ollama'")
            if req.kind != record.get("kind") and existing.preset:
                raise HTTPException(status_code=400, detail="A preset connection's kind cannot be changed.")
            record["kind"] = req.kind
        message = f"Saved connection '{record['name']}'."

    # A custom connection must end up with a model (presets may rely on
    # their default).
    if not existing and not record.get("model"):
        raise HTTPException(status_code=400, detail="A connection needs a model id.")

    settings.save_connection_record(record)
    invalidate_connection_registry()
    clear_adapter_cache(record["id"])
    if record["id"] == settings.localmind_adapter:
        clear_adapter_cache()

    return {"connection": record, "message": message}


def _validated_capabilities(capabilities: Optional[dict]) -> dict:
    """Keep only the known capability keys, typed; reject nothing (unknown
    keys are future-proofing noise from older/newer clients)."""
    out: dict = {}
    if not isinstance(capabilities, dict):
        return out
    for key in ("streaming", "vision", "tool_calling", "structured_output"):
        if key in capabilities and isinstance(capabilities[key], bool):
            out[key] = capabilities[key]
    if "context_window" in capabilities:
        try:
            out["context_window"] = max(0, int(capabilities["context_window"]))
        except (TypeError, ValueError):
            pass
    return out


@router.delete("/settings/connections/{connection_id}")
async def delete_connection(connection_id: str):
    """Remove a custom connection, or reset a preset to its defaults."""
    from core.connections import get_connection_registry, invalidate_connection_registry

    registry = get_connection_registry()
    connection = registry.get(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail=f"No connection named '{connection_id}'.")
    if connection.id == "ollama":
        raise HTTPException(status_code=400, detail="The local Ollama connection cannot be deleted.")

    removed = settings.delete_connection_record(connection_id)
    invalidate_connection_registry()
    clear_adapter_cache(connection_id)

    switched_to = ""
    if connection.preset:
        message = f"Reset '{connection.name}' to its defaults."
    else:
        message = f"Deleted connection '{connection.name}'."
        # A deleted endpoint takes its secrets and references with it:
        # its saved API key, and any other connection that named it as a fallback.
        settings.delete_api_key(connection_id)
        for other in get_connection_registry().all():
            if other.fallback_to == connection_id:
                settings.save_connection_record({**other.to_dict(), "fallback_to": ""})
        invalidate_connection_registry()
        # Never leave the active adapter pointing at a deleted endpoint. Prefer another
        # provider that is ready to use (enabled, key saved) over silently dropping to a local
        # model the user may not have; Ollama is the last resort.
        if settings.localmind_adapter == connection_id:
            replacement = "ollama"
            for other in get_connection_registry().all():
                if other.id not in (connection_id, "ollama") and other.enabled and settings.get_api_key(other.id):
                    replacement = other.id
                    break
            settings.localmind_adapter = replacement
            settings.save_runtime_settings(adapter=replacement)
            clear_adapter_cache()
            switched_to = replacement
            message += f" It was the active provider, so LocalMind switched to '{replacement}'."

    return {
        "connection": connection_id,
        "deleted": removed,
        "adapter": settings.localmind_adapter,
        "switched_to": switched_to,
        "message": message,
    }


def _probe_model_for(connection) -> str:
    """Resolve the model the probe should exercise (connection → preset)."""
    from adapters.openai_compat import PROVIDER_CONFIGS

    cfg = PROVIDER_CONFIGS.get(connection.id)
    model = connection.model or (getattr(settings, cfg.settings_field, "") if cfg else "")
    if model:
        return model
    if cfg is not None:
        return cfg.default_model
    return ""


@router.post("/settings/connections/{connection_id}/test")
async def test_connection(connection_id: str):
    """Probe a connection and report what the endpoint really supports.

    Runs four bounded checks: /models reachability + auth, a non-streaming
    chat completion, a streaming completion, and a tools-parameter probe.
    Discovered facts (context window, streaming, tool-calling) are stored
    back onto the connection so LocalMind learns instead of assuming.
    """
    from adapters.openai_compat import extract_context_window_from_model_entry
    from core.connections import get_connection_registry, invalidate_connection_registry

    registry = get_connection_registry()
    connection = registry.get(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail=f"No connection named '{connection_id}'.")
    if connection.kind == "ollama":
        raise HTTPException(
            status_code=400,
            detail="Ollama has its own health checks; test is for OpenAI-compatible connections.",
        )

    model = _probe_model_for(connection)
    if not model:
        raise HTTPException(status_code=400, detail="Set a model on this connection before testing it.")

    api_key = settings.get_api_key(connection.id) or ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = connection.base_url.rstrip("/")

    result: dict = {
        "connection": connection_id,
        "model": model,
        "ok": False,
        "reachable": False,
        "auth_ok": False,
        "chat_ok": False,
        "streaming_ok": None,
        "tools": None,
        "models_count": None,
        "context_window": None,
        "latency_ms": None,
        "error": None,
    }

    def _redact(text: str) -> str:
        text = (text or "")[:300]
        if api_key and api_key in text:
            text = text.replace(api_key, "[redacted]")
        return text

    client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
    try:
        # 1. /models — reachability, auth, and raw entries for the window.
        models_raw: list[dict] = []
        try:
            resp = await client.get(f"{base}/models", headers=headers)
            if resp.status_code == 200:
                result["reachable"] = True
                result["auth_ok"] = True
                entries = [m for m in resp.json().get("data", []) if isinstance(m, dict)]
                models_raw = entries
                result["models_count"] = len(entries)
            else:
                result["reachable"] = True
                result["auth_ok"] = resp.status_code not in (401, 403)
                result["error"] = f"GET /models returned {resp.status_code}: {_redact(resp.text)}"
        except httpx.ConnectError:
            result["error"] = "Could not connect to the endpoint — check the base URL and that the service is running."
        except Exception as exc:  # noqa: BLE001 — probe must never raise to the client
            result["error"] = f"GET /models failed: {_redact(str(exc))}"

        # 2. Context window from the /models metadata (no extra request).
        if models_raw:
            for entry in models_raw:
                if str(entry.get("id", "")).lower() == model.lower():
                    window = extract_context_window_from_model_entry(entry)
                    if window:
                        result["context_window"] = window
                    break

        if result["reachable"]:
            chat_payload = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            }
            # 3. Non-streaming chat completion — the definitive "this works".
            started = time.monotonic()
            try:
                resp = await client.post(f"{base}/chat/completions", json=chat_payload, headers=headers)
                result["latency_ms"] = int((time.monotonic() - started) * 1000)
                if resp.status_code == 200:
                    result["chat_ok"] = True
                    result["ok"] = True
                    result["auth_ok"] = True
                elif resp.status_code in (401, 403):
                    result["error"] = (
                        f"Chat request rejected ({resp.status_code}) — the API key was refused: "
                        f"{_redact(resp.text)}"
                    )
                else:
                    result["error"] = f"Chat request returned {resp.status_code}: {_redact(resp.text)}"
            except Exception as exc:  # noqa: BLE001
                result["latency_ms"] = int((time.monotonic() - started) * 1000)
                result["error"] = f"Chat request failed: {_redact(str(exc))}"

            # 4. Streaming probe — read a few SSE frames; success = a 200
            # stream that emits at least one data frame.
            stream_payload = dict(chat_payload, stream=True)
            try:
                async with client.stream(
                    "POST", f"{base}/chat/completions", json=stream_payload, headers=headers
                ) as stream_resp:
                    if stream_resp.status_code == 200:
                        frames = 0
                        async for line in stream_resp.aiter_lines():
                            if line and line.startswith("data:") and frames < 5:
                                frames += 1
                            if frames >= 2:
                                break
                        result["streaming_ok"] = frames >= 1
                    else:
                        result["streaming_ok"] = False
            except Exception:  # noqa: BLE001
                result["streaming_ok"] = False

            # 5. Tools probe — the `tools` parameter is accepted (tentative),
            # rejected, or unknown. tool_choice="none" keeps the model from
            # actually calling anything.
            tools_payload = {
                **chat_payload,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "description": "Reply with the given text.",
                            "parameters": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        },
                    }
                ],
                "tool_choice": "none",
            }
            try:
                tools_resp = await client.post(
                    f"{base}/chat/completions", json=tools_payload, headers=headers
                )
                if tools_resp.status_code == 200:
                    result["tools"] = "accepted"
                else:
                    body = tools_resp.text.lower()
                    result["tools"] = "rejected" if "tool" in body else "unknown"
            except Exception:  # noqa: BLE001
                result["tools"] = "unknown"
    finally:
        await client.aclose()

    # Learn instead of assuming: store what the probe measured onto the
    # connection record. Only definitive results persist — a flaky network
    # must not overwrite good declared values with absence.
    stored = None
    if result.get("chat_ok"):
        record = connection.to_dict()
        caps = record.get("capabilities") or {}
        changed = False
        if result.get("context_window") and not caps.get("context_window"):
            caps["context_window"] = result["context_window"]
            changed = True
        if result.get("streaming_ok") is False and caps.get("streaming", True):
            caps["streaming"] = False
            changed = True
        if result.get("tools") in ("accepted", "rejected"):
            tool_value = result["tools"] == "accepted"
            if caps.get("tool_calling", True) != tool_value:
                caps["tool_calling"] = tool_value
                changed = True
        if changed:
            record["capabilities"] = caps
            settings.save_connection_record(record)
            invalidate_connection_registry()
            clear_adapter_cache(connection_id)
            stored = caps

    result["stored"] = stored
    return result


# ── One-click embed-model download ─────────────────────

OLLAMA_PULL_URL_TEMPLATE = "{base}/api/pull"


@router.get("/ollama/embed-status")
async def get_ollama_embed_status():
    """Check whether Ollama is reachable and the configured embed model is installed."""
    base = getattr(settings, "ollama_base_url", "http://localhost:11434")
    model = getattr(settings, "ollama_embed_model", "nomic-embed-text")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()
            tags = resp.json()
            models = [m.get("name", "") for m in tags.get("models", [])]
            # Check both exact name and name:latest (Ollama appends :latest)
            installed = model in models or f"{model}:latest" in models
            return {"ollama_available": True, "model_installed": installed, "model_name": model}
    except Exception:
        return {"ollama_available": False, "model_installed": False, "model_name": model}


@router.post("/ollama/pull-embed")
async def pull_embed_model():
    """Stream ollama pull progress for the configured embed model via SSE.

    Events:
      event: progress  — {status, progress, detail}
      event: done      — {status: 'done', detail}
      event: error     — {status: 'error', detail}
    """
    base = getattr(settings, "ollama_base_url", "http://localhost:11434")
    model = getattr(settings, "ollama_embed_model", "nomic-embed-text")

    async def event_stream():
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream(
                    "POST",
                    OLLAMA_PULL_URL_TEMPLATE.format(base=base),
                    json={"name": model, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            pct = None
                            if data.get("total") and data.get("completed") is not None:
                                pct = round(data["completed"] / data["total"] * 100, 1)
                            if status == "success":
                                done = {"status": "done", "detail": f"{model} downloaded successfully"}
                                yield f"event: done\ndata: {json.dumps(done)}\n\n"
                                break
                            else:
                                pulling = {
                                    "status": "pulling",
                                    "progress": pct,
                                    "detail": status,
                                }
                                yield f"event: progress\ndata: {json.dumps(pulling)}\n\n"
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'status': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
