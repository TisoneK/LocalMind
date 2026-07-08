"""
LocalMind configuration — loaded from environment / .env file.
All settings validated by Pydantic at startup.
"""
import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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

    Covers standard Windows shell folders plus the observed user top-level
    folders from C:\\Users\\tison.  Keeping both platforms in sync ensures
    is_path_allowed() works correctly regardless of where LocalMind runs.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        base = Path.home()

    # Standard shell folders present on both Windows and *nix home dirs
    standard = [
        "Downloads", "Documents", "Pictures", "Videos",
        "Music", "Desktop", "Contacts", "Favorites",
    ]
    # User-created top-level folders observed in C:\\Users\\tison
    user_created = [
        "LocalMind", "Dev", "Scripts", "docs", "shared",
        "workflows", "examples", "factory", "config", "data", "OneDrive",
        "Code", "Projects", "src", "repos", "builds", "workspace",
    ]
    return [str(base / folder) for folder in standard + user_created]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=False,   # allow hot-swap of ollama_model at runtime
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
    ollama_keep_alive: str = "-1"   # -1 = keep model loaded forever; e.g. "5m", "1h"

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

    # Server
    localmind_host: str = "127.0.0.1"
    localmind_port: int = 8000
    localmind_log_level: str = "INFO"

    # Storage — default to ~/LocalMind/
    localmind_home: str = Field(default="")
    localmind_db_path: str = ""          # resolved at startup if empty
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

    # Shell tool
    localmind_shell_enabled: bool = False

    # Context window management
    localmind_response_reserve_tokens: int = 2048
    localmind_history_max_tokens: int = 4096

    # Model routing
    ollama_model_fast: str = ""
    ollama_model_code: str = ""

    # Intent-specific timeouts (seconds) — override per model/environment in .env
    ollama_timeout_chat: int = 90
    ollama_timeout_web_search: int = 180
    ollama_timeout_file_task: int = 180
    ollama_timeout_file_write: int = 180
    ollama_timeout_shell: int = 180
    ollama_timeout_code_exec: int = 240
    ollama_timeout_sysinfo: int = 60
    ollama_timeout_memory_op: int = 120
    ollama_timeout_default: int = 180

    # Agent loop
    localmind_agent_enabled: bool = True
    localmind_agent_max_iterations: int = 6

    # Permission gates — require user confirmation before write/delete
    localmind_require_write_permission: bool = False

    def is_ollama_configured(self) -> bool:
        """Return True only when Ollama has been explicitly confirmed working."""
        return self.ollama_ready

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

        # Auto-mark as configured if .env/env vars differ from compiled-in defaults
        _DEFAULT_URL   = "http://localhost:11434"
        _DEFAULT_MODEL = "llama3.1:8b"
        if self.ollama_base_url != _DEFAULT_URL or self.ollama_model != _DEFAULT_MODEL:
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
        try:
            import json
            # Try multiple encodings to handle files saved with different encodings
            content = ""
            for enc in ["utf-8-sig", "utf-16", "utf-16-le", "cp1252", "latin-1"]:
                try:
                    with open(path, "r", encoding=enc) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
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
            # Load API keys from runtime settings
            if "api_keys" in data:
                self._runtime_api_keys = data["api_keys"]
                logger.info(f"[config] Loaded {len(data['api_keys'])} runtime API keys")
        except Exception as e:
            logger.warning(f"[config] Failed to load runtime settings: {e}")

    def save_runtime_settings(self, **kwargs) -> None:
        """Save runtime settings to JSON file for persistence across restarts."""
        path = self._runtime_settings_path()
        import json
        # Load existing to merge
        existing = {}
        if path.exists():
            try:
                with open(path, "r") as f:
                    existing = json.load(f)
            except Exception:
                pass
        # Merge and save
        existing.update(kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)

    def save_api_key(self, provider: str, api_key: str) -> None:
        """Save an API key for a provider."""
        import json
        path = self._runtime_settings_path()
        # Load existing
        existing = {}
        if path.exists():
            try:
                with open(path, "r") as f:
                    existing = json.load(f)
            except Exception:
                pass
        # Update API keys
        api_keys = existing.get("api_keys", {})
        api_keys[provider] = api_key
        existing["api_keys"] = api_keys
        # Save
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)
        # Update runtime cache
        self._runtime_api_keys[provider] = api_key

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
        }
        env_var = env_key_map.get(provider)
        if env_var:
            return os.getenv(env_var) or None
        return None


# Singleton
settings = Settings()
settings.resolve_paths()
settings.load_runtime_settings()
