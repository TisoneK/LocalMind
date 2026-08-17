"""
LocalMind configuration — loaded from environment / .env file.
All settings validated by Pydantic at startup.
"""

import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_home() -> str:
    """Return platform-appropriate LocalMind home directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        base = Path.home()
    return str(base / "LocalMind")


def _default_uploads() -> str:
    return str(Path(_default_home()) / "uploads")


def _allowed_user_folders() -> list[str]:
    """
    Folders the model is allowed to READ from (never OS/system folders).

    Defaults to the user's home directory plus a set of common development
    folders. The list can be overridden via the LOCALMIND_ALLOWED_FOLDERS
    env var (comma-separated absolute or ~-relative paths) so users on
    non-default layouts don't have to edit source code to expose their
    project directories to the file explorer.

    The home directory itself is always included so the file explorer can
    list its top-level contents (not just specific subdirectories).
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        base = Path.home()

    # Always include the home directory itself so the file explorer can
    # list its contents. Without this, GET /api/files?path=~ returns 403.
    folders = [str(base)]

    # If the user has explicitly configured an allowlist via env, use it
    # as the authoritative set (beyond the home dir). This lets users on
    # non-standard layouts (e.g. /srv/projects, D:\\Code) expose their
    # actual work folders without editing source code.
    env_folders = os.getenv("LOCALMIND_ALLOWED_FOLDERS", "")
    if env_folders.strip():
        for entry in env_folders.split(","):
            entry = entry.strip()
            if not entry:
                continue
            # Expand ~ and env vars, then normalize to absolute
            expanded = Path(entry).expanduser()
            folders.append(str(expanded if expanded.is_absolute() else (base / expanded)))
        return folders

    # Default: common standard + development folders. These are generic
    # names that exist on most developer machines — not specific to one
    # user's setup (the prior version hardcoded names like "factory",
    # "repos", "builds" observed on one developer's machine).
    standard = [
        "Downloads",
        "Documents",
        "Pictures",
        "Videos",
        "Music",
        "Desktop",
        "Contacts",
        "Favorites",
    ]
    development = [
        "LocalMind",
        "Dev",
        "Scripts",
        "docs",
        "shared",
        "workflows",
        "examples",
        "config",
        "data",
        "Code",
        "Projects",
        "src",
        "repos",
        "workspace",
    ]
    folders.extend(str(base / folder) for folder in standard + development)
    return folders


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=False,  # allow hot-swap of ollama_model at runtime
    )

    # Runtime API keys (loaded from settings.json, not env)
    _runtime_api_keys: dict = {}

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""  # Empty = auto-detect first available model on startup

    # Set to True when the user has explicitly confirmed a working Ollama endpoint
    # (via POST /api/ollama/url) or via .env overrides at startup.
    # While False, all startup warmup calls are skipped.
    ollama_ready: bool = False
    ollama_embed_model: str = "nomic-embed-text"  # pin via OLLAMA_EMBED_MODEL in .env
    ollama_timeout: int = 120
    ollama_keep_alive: str = "-1"  # -1 = keep model loaded forever; e.g. "5m", "1h"

    # Adapter
    localmind_adapter: str = "ollama"

    # Cloud provider models (optional overrides)
    openai_model: str = ""
    anthropic_model: str = ""
    openrouter_model: str = ""
    deepseek_model: str = ""
    litellm_model: str = ""
    zen_model: str = ""
    groq_model: str = ""
    together_model: str = ""
    fireworks_model: str = ""
    deepinfra_model: str = ""
    mistral_model: str = ""
    cohere_model: str = ""
    vercel_model: str = ""
    cloudflare_model: str = ""
    cerebras_model: str = ""
    sambanova_model: str = ""
    gemini_model: str = ""
    chutes_model: str = ""
    zai_model: str = ""
    # ADR-9: ZenMux — IMPLEMENTED BUT UNTESTED (smoke test blocked).
    zenmux_model: str = ""

    # Server
    localmind_host: str = "127.0.0.1"
    localmind_port: int = 8000
    localmind_log_level: str = "INFO"

    # Storage — default to ~/LocalMind/
    localmind_home: str = Field(default="")
    localmind_db_path: str = ""  # resolved at startup if empty
    localmind_uploads_path: str = Field(default_factory=_default_uploads)

    # Cache — ~/LocalMind/ scratch space
    # Files/dirs older than this are deleted lazily on each write.
    localmind_cache_max_age_days: int = 7

    # File reader
    localmind_max_file_size_mb: int = 50
    localmind_chunk_size_tokens: int = 1500
    localmind_chunk_overlap_tokens: int = 200

    # Web search
    localmind_search_provider: str = "tiered"  # tiered, duckduckgo, searxng, brave
    brave_search_api_key: str = ""
    searxng_url: str = "https://searx.be"

    # Code executor
    localmind_code_exec_timeout: int = 30
    localmind_code_exec_enabled: bool = True

    # Shell tool — Session 31: enabled by default. LocalMind is a local-first
    # app where the user explicitly wants to run commands. Disabling shell by
    # default made every shell request silently fail with a misleading error.
    localmind_shell_enabled: bool = True

    # Context window management
    localmind_response_reserve_tokens: int = 2048
    localmind_history_max_tokens: int = 4096

    # ADR-19 P3 (Session 179): LLM-guided value scoring of history messages
    # — when enabled, one LLM call scores each message 0-1 and the
    # summarizer compresses the LOWEST-value messages instead of the oldest
    # 50%. OFF by default (design.md §6: "too slow for free-tier; the
    # deterministic marker approach is the P0 trade"). The deterministic
    # marker path (policy keep_markers) remains the default.
    localmind_llm_value_scoring: bool = False

    # Model routing
    ollama_model_fast: str = ""
    ollama_model_code: str = ""

    # Intent-specific timeouts (seconds) — override per model/environment in .env
    # chat is 180 (was 90): local models generate at <1-2 tok/s on CPU/small
    # GPUs, so a legitimately short reply can exceed 90s — the loop's per-call
    # cap reads this same knob for slow providers (Session 288).
    ollama_timeout_chat: int = 180
    ollama_timeout_web_search: int = 180
    ollama_timeout_file_task: int = 180
    ollama_timeout_file_write: int = 180
    ollama_timeout_shell: int = 180
    ollama_timeout_code_exec: int = 240
    ollama_timeout_sysinfo: int = 60
    ollama_timeout_memory_op: int = 120
    ollama_timeout_default: int = 180

    # Agent loop
    # (Note: localmind_agent_max_iterations was REMOVED — it was dead code
    # never read by anything. The loop's iteration cap comes from
    # LOCALMIND_MAX_ITERATIONS (constants.py) or the selected agent's
    # AgentConfig.max_iterations per ADR-8 Phase 2.)
    localmind_agent_enabled: bool = True

    # ADR-41 (Session 254): reasoning-model thinking policy (z.ai/GLM).
    # "enabled" (default) lets GLM reason before answering — disabling it
    # made glm-4.5-flash emit ~28-token terse answers. "disabled" opts out
    # for latency-sensitive use. GLM-5.3+ ignores this (z.ai rejects
    # thinking.type=disabled there). Settable via LOCALMIND_THINKING env or
    # the Settings UI (settings.json wins — load_runtime_settings runs
    # after pydantic folds the env in).
    localmind_thinking: str = "enabled"
    # Thinking-aware per-call timeout (seconds) used when the adapter has
    # thinking enabled — reasoning streams many tokens before the answer, so
    # the plain 45s PER_CALL_TIMEOUT_SECS would truncate mid-thought on a
    # slow free tier. LOCALMIND_REASONING_TIMEOUT_SECS / Settings UI.
    localmind_reasoning_timeout_secs: float = 180.0
    # Thinking-aware plan/init/orchestrator stream timeout (seconds).
    # LOCALMIND_REASONING_PLAN_TIMEOUT_SECS / Settings UI.
    localmind_reasoning_plan_timeout_secs: float = 30.0
    # Thinking-aware total-turn wall-clock cap (seconds) used when the
    # adapter has thinking enabled — a slow free tier spends 30-170s per
    # call thinking, so the 180s default only fits ~1-2 calls. The per-call
    # timeout + iteration cap + bounded retries remain the spin protections.
    # LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS / Settings UI.
    localmind_reasoning_max_wall_clock_secs: float = 360.0
    # Optional reasoning-effort for GLM-5.2+ (max/high/medium/low/...); empty
    # = provider default. GLM-4.5-flash does NOT support this parameter.
    # LOCALMIND_REASONING_EFFORT / Settings UI.
    localmind_reasoning_effort: str = ""

    # Permission gates — require user confirmation before write/delete
    localmind_require_write_permission: bool = False

    def is_ollama_configured(self) -> bool:
        """Return True only when Ollama has been explicitly confirmed working
        AND the adapter is ollama. Cloud adapters should never trigger Ollama
        warmup code paths."""
        return self.ollama_ready and self.localmind_adapter == "ollama"

    def resolve_paths(self) -> None:
        """Resolve dynamic paths after init. Call once at startup."""
        # Use default home if not set or empty
        home_path = self.localmind_home or _default_home()
        home = Path(home_path).expanduser()
        self.localmind_home = str(home)
        home.mkdir(parents=True, exist_ok=True)
        Path(self.localmind_uploads_path).expanduser().mkdir(parents=True, exist_ok=True)
        if not self.localmind_db_path:
            self.localmind_db_path = str(home / "localmind.db")
        else:
            p = Path(self.localmind_db_path).expanduser()
            if not p.is_absolute():
                p = (home / p).resolve()
            self.localmind_db_path = str(p)

        # Auto-mark Ollama as configured ONLY if the adapter is ollama AND
        # a model is explicitly set. Previously this checked if ollama_base_url
        # or ollama_model differed from compiled defaults — but since
        # ollama_model defaults to "" (empty), it always differed from
        # "llama3.1:8b", causing is_ollama_configured() to return True even
        # when the user was on a cloud adapter like Zen.
        if self.localmind_adapter == "ollama" and self.ollama_model:
            self.ollama_ready = True

    def allowed_read_paths(self) -> list[Path]:
        return [Path(p) for p in _allowed_user_folders()]

    def is_path_allowed(self, path: Path) -> bool:
        """Return True if path is within an allowed user folder."""
        try:
            resolved = path.resolve()
        except Exception:
            return False
        for allowed in self.allowed_read_paths():
            try:
                resolved.relative_to(allowed.resolve())
                return True
            except ValueError:
                continue
        return False

    def _runtime_settings_path(self) -> Path:
        """Return path to runtime settings file."""
        home = Path(self.localmind_home).expanduser()
        return home / "settings.json"

    def load_runtime_settings(self) -> None:
        """Load runtime settings from JSON file (if exists)."""
        import logging

        logger = logging.getLogger(__name__)
        path = self._runtime_settings_path()
        if not path.exists():
            logger.info(f"[config] No runtime settings file at {path}")
            return
        # Always read as UTF-8 — we always write UTF-8. The previous
        # multi-encoding fallback (utf-16, cp1252, latin-1) masked real
        # corruption by silently decoding bad bytes as latin-1, which
        # corrupted API keys. Fail loudly on decode errors instead.
        try:
            import json

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                return
            data = json.loads(content)
            logger.info(f"[config] Loaded runtime settings: {data}")
            # Apply runtime-persisted settings
            if "adapter" in data:
                self.localmind_adapter = data["adapter"]
                logger.info(f"[config] Set adapter to {data['adapter']}")
            if "model" in data:
                adapter = data.get("adapter", "ollama")
                model_key = f"{adapter}_model" if adapter != "ollama" else "ollama_model"
                if hasattr(self, model_key):
                    setattr(self, model_key, data["model"])
                    logger.info(f"[config] Set {model_key} to {data['model']}")
            if "ollama_url" in data:
                self.ollama_base_url = data["ollama_url"]
                logger.info(f"[config] Set ollama_url to {data['ollama_url']}")
            # ADR-41 (Session 254): reasoning-model thinking policy
            # (settings.json keys written by POST /api/settings/thinking).
            if "thinking" in data:
                self.localmind_thinking = str(data["thinking"])
                logger.info(f"[config] Set localmind_thinking to {data['thinking']}")
            if "reasoning_timeout" in data:
                self.localmind_reasoning_timeout_secs = float(data["reasoning_timeout"])
            if "reasoning_plan_timeout" in data:
                self.localmind_reasoning_plan_timeout_secs = float(data["reasoning_plan_timeout"])
            if "reasoning_max_wall_clock" in data:
                self.localmind_reasoning_max_wall_clock_secs = float(data["reasoning_max_wall_clock"])
            if "reasoning_effort" in data:
                self.localmind_reasoning_effort = str(data["reasoning_effort"])
            # Load API keys from runtime settings
            if "api_keys" in data:
                self._runtime_api_keys = data["api_keys"]
                logger.info(f"[config] Loaded {len(data['api_keys'])} runtime API keys")
        except Exception as e:
            logger.warning(f"[config] Failed to load runtime settings: {e}")

    def _secure_write_json(self, path: Path, data: dict) -> None:
        """
        Write JSON to a file atomically with restricted permissions (0600).

        Uses a temp-file + rename pattern so the original file is NEVER
        partially written or truncated. If the write fails for any reason,
        the original file is left intact.

        The settings file contains cloud-provider API keys, so it must not
        be world-readable.
        """
        import json
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2)

        # Write to a temp file in the SAME directory (so rename is atomic)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".settings_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            # Set permissions on the temp file
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            # Atomic rename — replaces the original file in one operation
            # On Windows, os.replace() handles the case where the target exists
            os.replace(tmp_path, str(path))
        except Exception:
            # Clean up the temp file on failure — original is untouched
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_json_file(self, path: Path) -> dict:
        """Load JSON from a file, returning {} on any error."""
        import json

        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_runtime_settings(self, **kwargs) -> None:
        """Save runtime settings to JSON file for persistence across restarts.

        Preserves existing values: if a kwarg is empty/None, the existing
        value in the file is kept rather than overwritten with empty. This
        prevents set_adapter(adapter='zen', model='') from wiping a
        previously-saved model name.
        """
        existing = self._load_json_file(self._runtime_settings_path())
        for key, value in kwargs.items():
            # Only overwrite if the new value is non-empty; otherwise keep
            # the existing value so partial updates don't clobber the file.
            if value is not None and value != "":
                existing[key] = value
            elif key not in existing:
                # Key doesn't exist yet — write it even if empty so the
                # file shape is predictable. (e.g. first-time adapter save)
                existing[key] = value
        self._secure_write_json(self._runtime_settings_path(), existing)

    def save_api_key(self, provider: str, api_key: str) -> None:
        """Save an API key for a provider."""
        path = self._runtime_settings_path()
        existing = self._load_json_file(path)
        api_keys = existing.get("api_keys", {})
        api_keys[provider] = api_key
        existing["api_keys"] = api_keys
        self._secure_write_json(path, existing)
        # Update runtime cache
        self._runtime_api_keys[provider] = api_key

    def delete_api_key(self, provider: str) -> bool:
        """Delete a stored API key for a provider.

        Returns True if a key was removed, False if no key was stored.
        """
        path = self._runtime_settings_path()
        existing = self._load_json_file(path)
        api_keys = existing.get("api_keys", {})
        if provider not in api_keys:
            return False
        del api_keys[provider]
        existing["api_keys"] = api_keys
        self._secure_write_json(path, existing)
        # Update runtime cache
        self._runtime_api_keys.pop(provider, None)
        return True

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider. Checks runtime storage first, then env vars."""
        # Check runtime storage first
        if provider in self._runtime_api_keys:
            return self._runtime_api_keys[provider]
        # Fall back to env var
        env_key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "zen": "ZEN_API_KEY",
            "groq": "GROQ_API_KEY",
            "together": "TOGETHER_API_KEY",
            "fireworks": "FIREWORKS_API_KEY",
            "deepinfra": "DEEPINFRA_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "cohere": "COHERE_API_KEY",
            "vercel": "VERCEL_API_KEY",
            "cloudflare": "CLOUDFLARE_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "sambanova": "SAMBANOVA_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "chutes": "CHUTES_API_KEY",
            "zai": "ZAI_API_KEY",
            # ADR-9: ZenMux — IMPLEMENTED BUT UNTESTED (smoke test blocked,
            # free plan has no API access). See ADR-9 for details.
            "zenmux": "ZENMUX_API_KEY",
        }
        env_var = env_key_map.get(provider)
        if env_var:
            return os.getenv(env_var) or None
        return None


# Singleton
settings = Settings()
settings.resolve_paths()
settings.load_runtime_settings()
