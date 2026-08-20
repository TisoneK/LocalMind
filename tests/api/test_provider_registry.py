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


def test_bai_is_registered():
    """B.AI (ADR-55) is a first-class OpenAI-compatible provider."""
    cfg = PROVIDER_CONFIGS["bai"]
    assert cfg.name == "bai"
    assert cfg.base_url == "https://api.b.ai/v1"
    assert cfg.key_env == "BAI_API_KEY"
    assert cfg.model_env == "BAI_MODEL"
    assert cfg.settings_field == "bai_model"
    # Model IDs are LOWERCASE on B.AI (the capitalized forms are display
    # names only) — Session 320 fixed a case mismatch that made the default
    # model unresolvable ("DeepSeek-V4-Flash" → 400 model-not-found).
    assert cfg.default_model == "deepseek-v4-flash"


def test_bai_model_context_windows():
    """B.AI context windows match docs.b.ai (Session 320 correction)."""
    assert MODEL_CONTEXT_WINDOWS["deepseek-v4-flash"] == 1000000
    assert MODEL_CONTEXT_WINDOWS["hy3"] == 256000


def test_bai_resolves_in_derived_maps():
    assert models_mod._model_setting_attr("bai") == "bai_model"
    assert "bai" in models_mod._build_model_setting_map()
