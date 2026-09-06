"""Regression tests for the provider-registry derivation (Session 319).

Adding B.AI (ADR-55) surfaced that ``models.py`` still held two hardcoded
provider→settings-field maps that had drifted from ``PROVIDER_CONFIGS`` —
the ADR-9 ZenMux entry was silently missing from both, so
``_model_setting_attr("zenmux")`` returned ``None`` and
``_build_model_setting_map()`` omitted it entirely (only ``health.py`` had
it). Both now derive from ``PROVIDER_CONFIGS``. These tests lock that
invariant so a future provider addition cannot drift out of the derived maps.
"""

from adapters.openai_compat import MODEL_CONTEXT_WINDOWS, PROVIDER_CONFIGS
from api.routes import models as models_mod


def test_model_setting_attr_covers_every_provider():
    """Every registered provider resolves to its exact settings field."""
    for key, cfg in PROVIDER_CONFIGS.items():
        assert models_mod._model_setting_attr(key) == cfg.settings_field, key


def test_build_model_setting_map_covers_every_provider():
    """No provider is silently omitted from the model-setting map."""
    model_map = models_mod._build_model_setting_map()
    for key in PROVIDER_CONFIGS:
        assert key in model_map, key


def test_bankofai_is_registered():
    """BankOfAI (ADR-55) is a first-class OpenAI-compatible provider."""
    cfg = PROVIDER_CONFIGS["bankofai"]
    assert cfg.name == "bankofai"
    # Session 321: canonical domain is api.bankofai.io (b.ai → bankofai.io).
    assert cfg.base_url == "https://api.bankofai.io/v1"
    assert cfg.key_env == "BANKOFAI_API_KEY"
    assert cfg.model_env == "BANKOFAI_MODEL"
    assert cfg.settings_field == "bankofai_model"
    # Model IDs are LOWERCASE on BankOfAI (the capitalized forms are display
    # names only) — Session 320 fixed a case mismatch that made the default
    # model unresolvable ("DeepSeek-V4-Flash" → 404 model_not_found, live).
    assert cfg.default_model == "deepseek-v4-flash"


def test_bankofai_needs_no_custom_user_agent():
    """BankOfAI's Cloudflare protection does not require a custom UA.

    Session 321 correction: an earlier (uncommitted) browser-UA header was
    added on a misdiagnosis — the 403 "error code: 1010" was triggered by the
    stdlib urllib "Python-urllib/*" UA used in the test scripts, NOT by httpx
    (the backend's HTTP client). httpx's default "python-httpx/*" UA passes
    Cloudflare (live-confirmed), so the provider config must carry no custom
    User-Agent header.
    """
    cfg = PROVIDER_CONFIGS["bankofai"]
    assert cfg.headers is None


def test_bankofai_model_context_windows():
    """BankOfAI context windows (Session 320 + live /models list)."""
    assert MODEL_CONTEXT_WINDOWS["deepseek-v4-flash"] == 1000000
    assert MODEL_CONTEXT_WINDOWS["hy3"] == 256000


def test_bankofai_resolves_in_derived_maps():
    assert models_mod._model_setting_attr("bankofai") == "bankofai_model"
    assert "bankofai" in models_mod._build_model_setting_map()


def test_omniroute_is_registered():
    """OmniRoute (Session 405) — a self-hosted OpenAI-compatible gateway.

    base_url points at the local gateway and is env-overridable via
    OMNIROUTE_BASE_URL (the port/host can differ per install); the key is the
    OmniRoute dashboard key, sent as the default Bearer header.
    """
    cfg = PROVIDER_CONFIGS["omniroute"]
    assert cfg.name == "omniroute"
    # Default is the local gateway; env-overridable via OMNIROUTE_BASE_URL
    # (same os.getenv pattern as litellm/vercel/cloudflare).
    assert cfg.base_url == "http://localhost:20128/v1"
    assert cfg.key_env == "OMNIROUTE_API_KEY"
    assert cfg.model_env == "OMNIROUTE_MODEL"
    assert cfg.settings_field == "omniroute_model"
    # No custom headers — plain Authorization: Bearer <dashboard key>.
    assert cfg.headers is None


def test_omniroute_resolves_in_derived_maps():
    assert models_mod._model_setting_attr("omniroute") == "omniroute_model"
    assert "omniroute" in models_mod._build_model_setting_map()
