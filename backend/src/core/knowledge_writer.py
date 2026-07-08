"""
knowledge_writer.py — v1.0

Writes live runtime config values into localmind.md at server startup,
replacing {{PLACEHOLDER}} tokens with actual settings values.

This keeps the knowledge doc the model reads at runtime in sync with the
actual running configuration — no more stale hardcoded tables.

Usage (called once from api/app.py startup hook):

    from core.knowledge_writer import update_knowledge_doc
    update_knowledge_doc()

Idempotent: safe to call multiple times. Writes only when values change.
Fails silently — a missing or unwritable localmind.md is logged but does
not prevent the server from starting.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Locate localmind.md relative to this file (project root).
_KNOWLEDGE_DOC_PATH = Path(__file__).parent.parent / "localmind.md"

# Mapping: placeholder token → callable that returns the live value string.
# All callables are evaluated lazily at write time so settings are fully
# resolved before we read them.
_PLACEHOLDER_MAP: dict[str, str | None] = {}  # populated in update_knowledge_doc()


def _resolve_placeholders() -> dict[str, str]:
    """
    Build the placeholder → value map from live settings.
    Called at write time so settings.resolve_paths() has already run.
    """
    from core.config import settings

    # Get the current active model based on adapter
    active_adapter = settings.localmind_adapter
    active_model = ""
    if active_adapter == "ollama":
        active_model = settings.ollama_model or "none configured"
    elif active_adapter == "openai":
        active_model = settings.openai_model or "gpt-4o-mini"
    elif active_adapter == "anthropic":
        active_model = settings.anthropic_model or "claude-3-5-sonnet"
    elif active_adapter == "zen":
        active_model = settings.zen_model or "minimax-m2.5-free"
    elif active_adapter == "groq":
        active_model = settings.groq_model or "llama-3.1-70b-versatile"
    elif active_adapter == "openrouter":
        active_model = settings.openrouter_model or "openrouter/auto"
    else:
        active_model = f"{active_adapter} (check settings)"

    fast = settings.ollama_model_fast or settings.ollama_model
    code = settings.ollama_model_code or settings.ollama_model

    return {
        "{{ACTIVE_ADAPTER}}": active_adapter.upper(),
        "{{ACTIVE_MODEL}}": active_model,
        "{{OLLAMA_MODEL}}": settings.ollama_model,
        "{{OLLAMA_MODEL_FAST}}": fast,
        "{{OLLAMA_MODEL_CODE}}": code,
        "{{OLLAMA_EMBED_MODEL}}": settings.ollama_embed_model,
        "{{OLLAMA_BASE_URL}}": settings.ollama_base_url,
        "{{DB_PATH}}": settings.localmind_db_path or "./localmind.db",
        "{{LOCALMIND_HOME}}": settings.localmind_home,
        "{{UPLOADS_PATH}}": settings.localmind_uploads_path,
        "{{SHELL_ENABLED}}": str(settings.localmind_shell_enabled).lower(),
        "{{CODE_EXEC_ENABLED}}": str(settings.localmind_code_exec_enabled).lower(),
        "{{REQUIRE_WRITE_PERMISSION}}": str(settings.localmind_require_write_permission).lower(),
        "{{SEARCH_PROVIDER}}": settings.localmind_search_provider,
        "{{MAX_FILE_SIZE_MB}}": str(settings.localmind_max_file_size_mb),
        "{{CODE_EXEC_TIMEOUT}}": str(settings.localmind_code_exec_timeout),
        "{{RESPONSE_RESERVE_TOKENS}}": str(settings.localmind_response_reserve_tokens),
    }


def update_knowledge_doc() -> bool:
    """
    Replace {{PLACEHOLDER}} tokens in localmind.md with live config values.

    Returns True if the file was written (values changed or placeholders found),
    False if nothing changed or the file could not be found/written.
    """
    if not _KNOWLEDGE_DOC_PATH.exists():
        logger.warning(
            "[knowledge_writer] localmind.md not found at %s — skipping update",
            _KNOWLEDGE_DOC_PATH,
        )
        return False

    try:
        original = _KNOWLEDGE_DOC_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("[knowledge_writer] could not read localmind.md: %s", exc)
        return False

    placeholders = _resolve_placeholders()

    updated = original
    replaced: list[str] = []
    for token, value in placeholders.items():
        if token in updated:
            updated = updated.replace(token, value)
            replaced.append(f"{token} → {value}")

    if not replaced:
        logger.debug("[knowledge_writer] no placeholders found — localmind.md already up to date")
        return False

    if updated == original:
        logger.debug("[knowledge_writer] values unchanged — skipping write")
        return False

    try:
        _KNOWLEDGE_DOC_PATH.write_text(updated, encoding="utf-8")
        logger.info(
            "[knowledge_writer] localmind.md updated (%d values written): %s",
            len(replaced),
            ", ".join(replaced),
        )
        return True
    except OSError as exc:
        logger.warning("[knowledge_writer] could not write localmind.md: %s", exc)
        return False
