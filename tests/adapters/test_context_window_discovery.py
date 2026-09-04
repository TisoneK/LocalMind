"""Context-window discovery tests (S416 follow-up — the "100% meter" fix).

Pins:
- extract_context_window_from_model_entry: the field names providers
  actually use (OpenRouter context_length + top_provider nesting, vLLM
  max_model_len, generic context_window/max_input_tokens), junk rejection.
- OpenAICompatAdapter.window_source / probe_context_window: table hit,
  fetched-upgrade on provider metadata, honest "default" when the
  provider exposes nothing (never present a guess as fact).
"""

import asyncio

import pytest

from adapters.openai_compat import (
    MODEL_CONTEXT_WINDOWS,
    OpenAICompatAdapter,
    extract_context_window_from_model_entry,
)
import adapters.openai_compat as oc


class TestExtractContextWindow:
    def test_openrouter_style_context_length(self):
        assert extract_context_window_from_model_entry({"id": "x", "context_length": 128000}) == 128000

    def test_openrouter_nested_top_provider(self):
        entry = {"id": "x", "top_provider": {"context_length": 64000}}
        assert extract_context_window_from_model_entry(entry) == 64000

    def test_vllm_max_model_len(self):
        assert extract_context_window_from_model_entry({"id": "x", "max_model_len": 32768}) == 32768

    def test_generic_context_window(self):
        assert extract_context_window_from_model_entry({"id": "x", "context_window": 1000000}) == 1000000

    def test_max_input_tokens(self):
        assert extract_context_window_from_model_entry({"id": "x", "max_input_tokens": 200000}) == 200000

    def test_no_metadata_returns_none(self):
        # bankofai shape, live-verified 2026-09-04: id/owned_by only.
        assert extract_context_window_from_model_entry({"id": "qwen3.8-flash", "owned_by": "ali"}) is None

    def test_junk_values_rejected(self):
        assert extract_context_window_from_model_entry({"id": "x", "context_length": -5}) is None
        assert extract_context_window_from_model_entry({"id": "x", "context_length": 99_999_999}) is None
        assert extract_context_window_from_model_entry({"id": "x", "context_length": "1M"}) is None
        assert extract_context_window_from_model_entry("not a dict") is None
        assert extract_context_window_from_model_entry({}) is None


class TestWindowSource:
    def _adapter(self, model: str) -> OpenAICompatAdapter:
        return OpenAICompatAdapter(provider="bankofai", model_override=model)

    def test_table_hit_reports_table_source(self):
        adapter = self._adapter("qwen3.8-flash")
        assert adapter.context_window == 1_000_000
        assert adapter.window_source == "table"

    def test_unknown_model_reports_default_source(self):
        adapter = self._adapter("totally-unknown-model")
        assert adapter.window_source == "default"
        # The conservative default is a guess, not the model's capacity.
        assert adapter.context_window == MODEL_CONTEXT_WINDOWS["default"]

    def test_probe_returns_none_when_provider_has_no_metadata(self, monkeypatch):
        adapter = self._adapter("totally-unknown-model")
        oc._MODELS_RAW_CACHE.set("bankofai", [{"id": "totally-unknown-model", "owned_by": "ali"}])
        assert asyncio.run(adapter.probe_context_window()) is None
        assert adapter.window_source == "default"  # honest — no upgrade

    def test_probe_upgrades_source_on_fetched_metadata(self, monkeypatch):
        adapter = self._adapter("totally-unknown-model")
        oc._MODELS_RAW_CACHE.set(
            "bankofai",
            [{"id": "totally-unknown-model", "context_length": 262144}],
        )
        assert asyncio.run(adapter.probe_context_window()) == 262144
        assert adapter.window_source == "fetched"
        assert adapter.context_window == 262144  # fetched beats the default

    def test_table_value_not_overridden_by_probe_absence(self):
        adapter = self._adapter("qwen3.8-flash")
        oc._MODELS_RAW_CACHE.set("bankofai", [{"id": "qwen3.8-flash", "owned_by": "ali"}])
        assert asyncio.run(adapter.probe_context_window()) is None
        assert adapter.context_window == 1_000_000
        assert adapter.window_source == "table"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
