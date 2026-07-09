"""
Ollama lifecycle routes — F1

NOTE: These routes only work when LOCALMIND_ADAPTER=ollama.
For cloud providers (OpenAI, Anthropic, etc.), these return 501.

POST   /api/ollama/start   — start `ollama serve` as a subprocess (ollama only)
GET    /api/ollama/status  — is Ollama reachable + loaded models (ollama only)
POST   /api/ollama/pull    — stream `ollama pull <model>` progress as SSE (ollama only)

Remote URL configuration:
GET    /api/ollama/url     — current base URL and whether it is remote
POST   /api/ollama/url     — set a new base URL (validated by reachability check)
DELETE /api/ollama/url     — reset to the default local URL

NOTE: GET /api/models and POST /api/models/select live in api/routes/models.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


def _require_ollama():
    """Raise 501 if not using Ollama adapter."""
    if settings.localmind_adapter != "ollama":
        raise HTTPException(
            status_code=501,
            detail=f"Ollama routes are not available when using {settings.localmind_adapter} adapter"
        )


def _ollama_base() -> str:
    """Return the current Ollama base URL from live settings (no trailing slash)."""
    return settings.ollama_base_url.rstrip("/")


# ── helpers ───────────────────────────────────────────────────────────────

async def _ollama_get(path: str, base_url: str | None = None) -> Optional[dict]:
    url = (base_url or _ollama_base()) + path
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


# ── /api/ollama/url ───────────────────────────────────────────────────────

class UrlResponse(BaseModel):
    url: str
    is_remote: bool


class SetUrlRequest(BaseModel):
    url: str


class SetUrlResponse(BaseModel):
    url: str
    reachable: bool
    message: str


@router.get("/ollama/url", response_model=UrlResponse)
async def get_ollama_url():
    """Return the current Ollama base URL."""
    _require_ollama()
    url = _ollama_base()
    is_remote = not (
        url.startswith("http://localhost")
        or url.startswith("http://127.0.0.1")
        or url.startswith("http://0.0.0.0")
    )
    return UrlResponse(url=url, is_remote=is_remote)


@router.post("/ollama/url", response_model=SetUrlResponse)
async def set_ollama_url(req: SetUrlRequest):
    """
    Set a new Ollama base URL.

    The URL is validated by issuing a GET /api/tags against it before
    committing the change. Accepts any URL that serves the Ollama API —
    local addresses, LAN IPs, or tunnel URLs (ngrok, Cloudflare, etc.).

    Example body:
        { "url": "https://xyz.trycloudflare.com" }
    """
    _require_ollama()
    raw = req.url.strip().rstrip("/")
    if not raw:
        raise HTTPException(status_code=400, detail="url cannot be empty")

    if not raw.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="url must start with http:// or https://",
        )

    data = await _ollama_get("/api/tags", base_url=raw)
    reachable = data is not None

    if reachable:
        was_configured = settings.ollama_ready
        settings.ollama_base_url = raw
        settings.ollama_ready = True
        settings.save_runtime_settings(ollama_url=raw)
        logger.info("[ollama/url] base URL updated to %s", raw)

        # First-time configuration — trigger engine startup now that Ollama is reachable
        if not was_configured:
            # asyncio imported at module level — no inner re-import
            async def _late_startup():
                try:
                    from api.routes.chat import _engine as _chat_engine
                    await _chat_engine.startup()
                    logger.info("[ollama/url] late engine startup complete")
                except Exception as exc:
                    logger.warning("[ollama/url] late engine startup failed: %s", exc)
            asyncio.create_task(_late_startup())

        return SetUrlResponse(
            url=raw,
            reachable=True,
            message=f"Ollama URL set to {raw}",
        )
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot reach Ollama at {raw}. "
                "Verify the server is running and the URL is correct."
            ),
        )


@router.delete("/ollama/url", response_model=SetUrlResponse)
async def reset_ollama_url():
    """Reset the Ollama base URL to the default local address."""
    _require_ollama()
    settings.ollama_base_url = _DEFAULT_OLLAMA_URL
    settings.ollama_ready = False
    logger.info("[ollama/url] base URL reset to %s", _DEFAULT_OLLAMA_URL)
    return SetUrlResponse(
        url=_DEFAULT_OLLAMA_URL,
        reachable=True,
        message=f"Ollama URL reset to default ({_DEFAULT_OLLAMA_URL})",
    )


# ── /api/ollama/start ─────────────────────────────────────────────────────

class StartResponse(BaseModel):
    started: bool
    already_running: bool
    message: str


@router.post("/ollama/start", response_model=StartResponse)
async def ollama_start():
    """Start `ollama serve` as a background subprocess."""
    _require_ollama()
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        raise HTTPException(
            status_code=503,
            detail="Ollama binary not found. Install from https://ollama.ai",
        )

    status = await _ollama_get("/api/tags")
    if status is not None:
        return StartResponse(started=False, already_running=True, message="Ollama is already running.")

    subprocess.Popen(
        [ollama_bin, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(8):
        await asyncio.sleep(1)
        if await _ollama_get("/api/tags") is not None:
            return StartResponse(started=True, already_running=False, message="Ollama started successfully.")

    return StartResponse(
        started=False, already_running=False,
        message="Ollama is starting but taking longer than expected. Retry in a moment.",
    )


# ── /api/ollama/status ────────────────────────────────────────────────────

class OllamaStatusResponse(BaseModel):
    reachable: bool
    active_model: Optional[str]
    loaded_models: list[str]


@router.get("/ollama/status", response_model=OllamaStatusResponse)
async def ollama_status():
    _require_ollama()
    tags = await _ollama_get("/api/tags")
    if tags is None:
        return OllamaStatusResponse(reachable=False, active_model=None, loaded_models=[])

    loaded = [m["name"] for m in tags.get("models", [])]
    return OllamaStatusResponse(
        reachable=True,
        active_model=settings.ollama_model,
        loaded_models=loaded,
    )


# ── /api/ollama/pull ──────────────────────────────────────────────────────

class PullRequest(BaseModel):
    model: str


@router.post("/ollama/pull")
async def ollama_pull(req: PullRequest):
    """Stream `ollama pull <model>` progress as SSE."""
    _require_ollama()
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        raise HTTPException(status_code=503, detail="Ollama binary not found.")

    async def _stream():
        proc = await asyncio.create_subprocess_exec(
            ollama_bin, "pull", req.model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    yield f"data: {json.dumps({'text': text})}\n\n"
            await proc.wait()
            rc = proc.returncode
            if rc == 0:
                yield f"data: {json.dumps({'done': True, 'success': True})}\n\n"
            else:
                yield f"data: {json.dumps({'done': True, 'success': False, 'error': f'pull exited {rc}'})}\n\n"
        except asyncio.CancelledError:
            proc.kill()
            raise

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
