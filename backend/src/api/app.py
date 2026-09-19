"""
FastAPI application factory — v0.3

Serves the single-file UI from ui/index.html directly (no build step needed).

v0.4: migrated from the deprecated ``@app.on_event("startup"/"shutdown")``
handlers to a single ``lifespan`` async context manager (the FastAPI
on_event deprecation fix). ``on_event`` was deprecated by
FastAPI in favor of ``lifespan``; the migration is behavior-preserving and
clears the ~81 pytest deprecation warnings caused by the old handlers.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env file into os.environ so all routes can access env vars via os.getenv()
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.routes import (
    actions,
    capabilities,
    chat,
    config,
    filesystem,
    health,
    memory,
    metrics,
    models,
    objectives,
    observability,
    ollama,
    sessions,
    terminal,
    todos,
)
from core.config import settings

logger = logging.getLogger(__name__)

UI_HTML = Path(__file__).parent.parent / "ui" / "index.html"


async def _shutdown(app: FastAPI) -> None:
    """Stop autonomous work before closing pooled adapter clients."""
    objective_runtime = getattr(app.state, "objective_runtime", None)
    if objective_runtime is not None:
        await objective_runtime.stop()

    from adapters import close_all_adapters

    await close_all_adapters()
    logger.info("[shutdown] all adapter connections closed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — replaces the deprecated ``on_event`` handlers.

    Startup:
        - Boots the autonomous ObjectiveRuntime (shares the chat Engine).
        - Logs the ACTIVE model (adapter-aware, not always ollama_model).
        - Writes live config into localmind.md (self-knowledge for the model).
        - For the ollama adapter: warms the engine, LLM models, and
          VectorStore in the background. Cloud adapters skip warmup.
    Shutdown:
        - Stops autonomous work before pooled adapter clients close.
    """
    # ── Startup ────────────────────────────────────────────────────────
    # User-started autonomous objectives share the same Engine and safety
    # pipeline as chat requests, but continue after the chat HTTP response.
    from api.routes.chat import _engine as _chat_engine
    from core.objective_runtime import ObjectiveRuntime

    objective_runtime = ObjectiveRuntime(_chat_engine, settings.localmind_db_path)
    app.state.objective_runtime = objective_runtime
    # Log the actual active model based on the adapter, not always ollama_model.
    # Previously this always showed settings.ollama_model, which is empty when
    # using a cloud adapter — making it look like no model is configured.
    _adapter = settings.localmind_adapter
    _model_map = {
        "ollama": settings.ollama_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
        "openrouter": settings.openrouter_model,
        "deepseek": settings.deepseek_model,
        "lite-llm": settings.litellm_model,
        "zen": settings.zen_model,
        "groq": settings.groq_model,
        "together": settings.together_model,
        "fireworks": settings.fireworks_model,
        "deepinfra": settings.deepinfra_model,
        "mistral": settings.mistral_model,
        "cohere": settings.cohere_model,
        "vercel": settings.vercel_model,
        "cloudflare": settings.cloudflare_model,
        "cerebras": settings.cerebras_model,
        "sambanova": settings.sambanova_model,
        "gemini": settings.gemini_model,
        "chutes": settings.chutes_model,
        "zai": settings.zai_model,
    }
    _active_model = _model_map.get(_adapter, "") or "(default)"
    logger.info(f"LocalMind — adapter: {_adapter} | model: {_active_model} | ui: {UI_HTML.exists()}")

    # Write live config values into localmind.md so the model always reads
    # accurate self-knowledge. Runs before any LLM call so the first request
    # already sees the updated doc. Fails silently if the file is missing.
    from core.knowledge_writer import update_knowledge_doc

    update_knowledge_doc()

    from api.routes.health import set_engine_ready

    # Build the boot-owned ParentKernel before accepting requests. This is
    # static parent state only — no fake user prompt is sent during startup.
    # Provider warmup is best-effort; the kernel can report degraded and retry
    # lazily on the first real turn.
    await _chat_engine.startup()
    set_engine_ready()

    # Refresh the boot-time system-info cache so the
    # agent has system knowledge without calling the sysinfo tool. Static fields
    # are written once and skipped on later boots; mutating fields (disk/RAM/
    # uptime) are updated each boot. Best-effort — never blocks startup.
    try:
        from core.system_snapshot import set_cached_summary
        from storage.system_info_store import SystemInfoStore

        _sysinfo_store = SystemInfoStore(settings.localmind_db_path)
        _sysinfo_store.refresh_at_boot()
        # Phase 3: cache the compact summary for prompt injection every turn.
        set_cached_summary(_sysinfo_store.get_summary())
    except Exception as _sysinfo_exc:  # pragma: no cover - defensive
        logger.warning("[startup] system-info cache refresh skipped: %s", _sysinfo_exc)

    # Fuse the user-context signals (OS country setting, time zone, locale)
    # ONCE at boot so every turn starts with the deduction already made — the
    # agent never has to guess the user's region from scratch. Stable facts
    # only; nothing volatile is collected, and the recompute-each-boot model
    # means the conclusion can never go stale. Best-effort — never blocks boot.
    try:
        from core.user_context import (
            collect_user_signals,
            fuse_user_signals,
            set_cached_fused,
        )

        _fused = fuse_user_signals(collect_user_signals())
        set_cached_fused(_fused)
        if _fused.get("country"):
            logger.info(
                "[startup] user context deduced: %s (%s; %s confidence)",
                _fused["country"],
                ", ".join(_fused.get("sources", [])) or "no corroboration",
                _fused.get("confidence"),
            )
            # Persist the stable conclusion as ONE keyed fact so it survives
            # across sessions and rides passive memory retrieval: canonical
            # key `subject:location` makes re-deductions replace the row
            # instead of accumulating copies, and the durability tags mark it
            # a boot-derived refreshable cache (never a claim of permanence).
            # Re-deduced every boot, so the row self-heals if the user moves.
            async def _persist_user_location():
                try:
                    from core.memory import MemoryComposer

                    await MemoryComposer().store(
                        # "My country: …" wording on purpose: the write-path
                        # classifier already tags that shape as a refreshable
                        # stable fact (freshness=boot) and keys it to the
                        # single-valued location subject, so re-deductions
                        # replace the row instead of accumulating copies.
                        fact=f"My country: {_fused['country']} (deduced from machine settings at boot)",
                        session_id="boot",
                        memory_type="semantic",
                        source="system",
                        importance=0.6,
                        level="long_term",
                        extra_metadata={
                            "memory_kind": "STABLE_FACT",
                            "memory_freshness": "boot",
                            "memory_confidence": {"high": "0.9", "medium": "0.7", "low": "0.5"}.get(
                                _fused.get("confidence"), "0.6"
                            ),
                        },
                    )
                    logger.info("[startup] user location persisted to memory (keyed)")
                except Exception as persist_exc:
                    logger.warning("[startup] user-location memory write skipped: %s", persist_exc)

            asyncio.create_task(_persist_user_location())
        else:
            logger.info(
                "[startup] user context: no converging region signals — omitted from prompts"
            )
    except Exception as _uc_exc:  # pragma: no cover - defensive
        logger.warning("[startup] user-context cache skipped: %s", _uc_exc)

    if settings.localmind_adapter != "ollama":
        logger.info(
            "[startup] Cloud adapter '%s' active — skipping Ollama warmup entirely.",
            settings.localmind_adapter,
        )
        await objective_runtime.start()
        try:
            yield
        finally:
            await _shutdown(app)
        return

    # Single authoritative startup: warms LLM router, embed model,
    # RiskAwareRouter, and FlywheelLogger on the exact engine instance
    # that handles requests.
    await objective_runtime.start()
    logger.info("[startup] engine ready — accepting requests")

    # Background task to pre-warm VectorStore
    async def warm_vector_store():
        try:
            from storage.vector import VectorStore

            logger.info("[startup] pre-warming VectorStore...")
            vector_store = VectorStore()
            if vector_store._ready:
                count = await vector_store.count()
                logger.info(f"[startup] VectorStore ready — {count} facts stored")
                # Warm up the embedding model. This is Ollama-based even
                # when using a cloud LLM adapter, because embeddings are
                # always local (nomic-embed-text). Skip silently when
                # Ollama isn't running — memory search will fall back to
                # keyword matching until Ollama is started.
                if settings.localmind_adapter == "ollama":
                    await vector_store.warmup()
                else:
                    logger.info("[startup] skipping embedding warmup — cloud adapter active")
            else:
                logger.info("[startup] VectorStore not ready")
        except Exception as e:
            logger.warning(f"[startup] VectorStore warm-up failed: {e}")

    async def warm_llm_models():
        """
        Pre-load every configured LLM into Ollama VRAM before the first request.

        Ollama lazy-loads models on first use — that initial load costs 30–90 s of
        dead wait on the first user message.  Sending an empty /api/generate prompt
        forces the load at server startup instead, so every subsequent request starts
        generating within 1–2 s.

        Models are warmed concurrently (asyncio.gather) so total startup cost is
        bounded by the slowest model, not the sum of all models.

        SKIPPED entirely when the active adapter is not Ollama — cloud providers
        don't need VRAM pre-loading, and running this would overwrite the cloud
        model list (fetched by engine.startup) with an empty Ollama list.
        """
        if settings.localmind_adapter != "ollama":
            logger.info(
                "[startup] skipping Ollama LLM warmup — active adapter is '%s'",
                settings.localmind_adapter,
            )
            return

        from adapters.ollama import OllamaAdapter
        from core.model_router import update_pulled_models

        # Collect every distinct model name from config
        model_names: list[str] = [settings.ollama_model]
        for extra in (settings.ollama_model_fast, settings.ollama_model_code):
            if extra and extra not in model_names:
                model_names.append(extra)

        # Refresh router first (cheap /api/tags call)
        try:
            base_adapter = OllamaAdapter()
            pulled = await base_adapter.list_models()
            update_pulled_models(pulled)
            logger.info(f"[startup] model router ready — {len(pulled)} models available")
        except Exception as e:
            logger.warning(f"[startup] model router refresh failed: {e}")
            pulled = []

        # Warm every model that is actually pulled locally
        async def _warm_one(model_name: str):
            if pulled and model_name not in pulled:
                logger.info(f"[startup] skipping warmup for '{model_name}' — not pulled locally")
                return
            adapter = OllamaAdapter(model_override=model_name)
            await adapter.warmup()

        await asyncio.gather(*[_warm_one(m) for m in model_names], return_exceptions=True)

    background_tasks = set()

    if settings.localmind_adapter == "ollama":
        for coro in (warm_vector_store(), warm_llm_models()):
            task = asyncio.create_task(coro)
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    try:
        yield
    finally:
        await _shutdown(app)


def create_app() -> FastAPI:
    app = FastAPI(
        title="LocalMind",
        description="Local AI runtime — file reading, web search, memory, tool use",
        version="0.4.0-dev",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8000",
            f"http://{settings.localmind_host}:{settings.localmind_port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(ollama.router, prefix="/api", tags=["ollama"])
    app.include_router(memory.router, prefix="/api", tags=["memory"])
    app.include_router(models.router, prefix="/api", tags=["models"])
    app.include_router(sessions.router, prefix="/api", tags=["sessions"])
    app.include_router(filesystem.router, prefix="/api", tags=["filesystem"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(actions.router, prefix="/api", tags=["actions"])
    app.include_router(capabilities.router, prefix="/api", tags=["capabilities"])
    app.include_router(todos.router, prefix="/api", tags=["todos"])
    app.include_router(metrics.router, prefix="/api", tags=["metrics"])
    app.include_router(observability.router, prefix="/api", tags=["observability"])
    app.include_router(objectives.router, prefix="/api", tags=["objectives"])
    app.include_router(terminal.router, prefix="/api", tags=["terminal"])
    app.include_router(config.router, prefix="/api", tags=["settings"])

    @app.get("/api/routing", tags=["models"])
    async def model_routing():
        """Show which model handles each intent — useful for debugging and UI display."""
        from core.model_router import routing_report

        return {
            "main_model": settings.ollama_model,
            "routing": routing_report(settings.ollama_model),
            "note": "First pulled model from preference list wins per intent.",
        }

    # Serve single-file UI — no build step required
    if UI_HTML.exists():

        @app.get("/", include_in_schema=False)
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_ui(full_path: str = ""):
            if full_path.startswith("api/"):
                return {"error": "not found"}
            return FileResponse(str(UI_HTML))
    else:

        @app.get("/", include_in_schema=False)
        async def no_ui():
            return {"status": "LocalMind API running", "docs": "/api/docs"}

    return app
