"""
Settings endpoints for adapter and provider configuration.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
    # Whether the shell tool is enabled (Session 292: was env-only, now UI-toggle).
    shell_enabled: bool = False
    providers: dict
    # ADR-41 (Session 254): reasoning-model thinking policy (z.ai/GLM).
    # Mirrored to the Settings UI so users can tune thinking without env vars.
    thinking: str = "enabled"
    reasoning_timeout: float = 180.0
    reasoning_plan_timeout: float = 30.0
    reasoning_max_wall_clock: float = 360.0
    reasoning_effort: str = ""
    # B-2026-08-23-19: UI appearance (theme/mode/custom palette/tone),
    # persisted in settings.json by POST /api/settings/appearance.
    theme: str = "graphite"
    mode: str = "dark"
    custom_theme: Optional[dict] = None
    tone: float = 1.0
    # B-2026-08-23-27: startup session behavior — "resume" or "new".
    startup_session: str = "new"
    # B-2026-08-23-34: Chat mode — "auto" | "agent" | "direct".
    chat_mode: str = "auto"


class AdapterConfig(BaseModel):
    adapter: str
    model: Optional[str] = None


class ThinkingSettingsRequest(BaseModel):
    """Body for POST /api/settings/thinking (ADR-41 reasoning policy).

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
    """Body for POST /api/settings/startup-session (B-2026-08-23-27)."""
    startup_session: str  # "resume" | "new"


@router.post("/settings/startup-session")
async def set_startup_session(req: StartupSessionRequest):
    """Persist the startup session behavior (B-2026-08-23-27).

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
    """Body for POST /api/settings/chat-mode (B-2026-08-23-34)."""
    chat_mode: str  # "auto" | "agent" | "direct"


@router.post("/settings/chat-mode")
async def set_chat_mode(req: ChatModeRequest):
    """Persist the chat mode (B-2026-08-23-34).

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


class AppearanceRequest(BaseModel):
    """Body for POST /api/settings/appearance (B-2026-08-23-19).

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
    """Apply and persist the UI appearance (B-2026-08-23-19).

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
    # B-2026-08-23-19: persisted appearance (theme/mode/custom palette/tone).
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

    return SettingsResponse(
        adapter=adapter,
        model=current_model,
        embed_model=embed_model,
        num_ctx=int(getattr(settings, "ollama_num_ctx", 0) or 0),
        shell_enabled=bool(getattr(settings, "localmind_shell_enabled", False)),
        providers=providers,
        thinking=settings.localmind_thinking,
        reasoning_timeout=settings.localmind_reasoning_timeout_secs,
        reasoning_plan_timeout=settings.localmind_reasoning_plan_timeout_secs,
        reasoning_max_wall_clock=settings.localmind_reasoning_max_wall_clock_secs,
        reasoning_effort=settings.localmind_reasoning_effort,
        # B-2026-08-23-19: appearance from settings.json (theme/mode/custom
        # palette/tone) so the UI restores the persisted choice on launch.
        theme=appearance.get("theme", "graphite"),
        mode=appearance.get("mode", "dark"),
        custom_theme=appearance.get("custom_theme"),
        tone=float(appearance.get("tone", 1.0) or 1.0),
        # B-2026-08-23-27: startup session behavior
        startup_session=getattr(settings, "localmind_startup_session", "new"),
        # B-2026-08-23-34: chat mode
        chat_mode=getattr(settings, "localmind_chat_mode", "auto"),
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
    Update the reasoning-model thinking policy (ADR-41) and persist it to
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
    Switch to a different adapter (ollama, openai, anthropic, etc.).
    """
    valid_adapters = VALID_ADAPTERS
    if req.adapter not in valid_adapters:
        raise HTTPException(status_code=400, detail=f"Invalid adapter. Valid: {valid_adapters}")

    # For cloud providers, check if an API key is available.
    # Check both runtime-stored keys (settings.json) and env vars.
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

    # Resolve the model for this adapter: use the provided model, or fall
    # back to the adapter's current model setting, or the provider default.
    # Previously, calling set_adapter without a model saved model="" to
    # settings.json, wiping any previously-saved model on restart.
    # model_field is derived from ADAPTER_MODEL_FIELDS (single source of truth).
    model_field = ADAPTER_MODEL_FIELDS.get(req.adapter)
    if model_field:
        # Resolve the model in priority order: the explicitly requested model,
        # then THIS provider's own saved model, then THIS provider's DEFAULT.
        # The default fallback is load-bearing: switching provider without a
        # model used to leave resolved_model="" when the new provider had no
        # saved model, and save_runtime_settings PRESERVES an empty kwarg — so
        # the top-level model kept the PREVIOUS provider's value (e.g. a
        # Cerebras "gpt-oss-120b" stranded under the Gemini adapter, which then
        # hit Gemini's free-tier limit). Falling through to the provider
        # default makes an adapter switch always land on a valid model.
        resolved_model = (
            req.model
            or getattr(settings, model_field, "")
            or PROVIDER_INFO.get(req.adapter, {}).get("default_model", "")
        )
        if resolved_model:
            setattr(settings, model_field, resolved_model)
    else:
        resolved_model = req.model or ""

    # Persist runtime settings to JSON file for restart survival.
    # save_runtime_settings preserves existing values when a kwarg is empty,
    # so passing model="" won't wipe a previously-saved model.
    # Session 292: Ollama persists under its DEDICATED ollama_model key (the
    # generic `model` key is cloud-only on load), so an Ollama model survives a
    # restart and a stale cloud model never loads as the Ollama model.
    if req.adapter == "ollama":
        settings.save_runtime_settings(adapter=req.adapter, ollama_model=resolved_model)
    else:
        settings.save_runtime_settings(adapter=req.adapter, model=resolved_model)

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
    if req.provider not in PROVIDER_INFO:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {list(PROVIDER_INFO.keys())}")

    info = PROVIDER_INFO[req.provider]

    # Save the API key to runtime storage first — we want it persisted
    # even if the health check fails (user may be offline).
    settings.save_api_key(req.provider, req.api_key)

    # If a model was provided, persist it too so the adapter uses it
    # on the next request. The settings field name comes from the derived
    # ADAPTER_MODEL_FIELDS map (single source of truth in PROVIDER_CONFIGS),
    # not from reconstructing it via string manipulation.
    if req.model:
        model_field = ADAPTER_MODEL_FIELDS.get(req.provider, "")
        if model_field and hasattr(settings, model_field):
            setattr(settings, model_field, req.model)
            settings.save_runtime_settings(adapter=req.provider, model=req.model)

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
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {list(PROVIDER_INFO.keys())}")

    info = PROVIDER_INFO[req.provider]
    removed = settings.delete_api_key(req.provider)

    return {
        "provider": req.provider,
        "name": info["name"],
        "deleted": removed,
        "message": f"API key removed for {info['name']}" if removed else f"No API key was stored for {info['name']}",
    }


# ── B-2026-08-23-28: One-click embed-model download ─────────────────────

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
                                yield f"event: done\ndata: {json.dumps({'status': 'done', 'detail': f'{model} downloaded successfully'})}\n\n"
                                break
                            else:
                                yield f"event: progress\ndata: {json.dumps({'status': 'pulling', 'progress': pct, 'detail': status})}\n\n"
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'status': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
