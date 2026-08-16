"""Session 245 Lever 2: prompt-caching payload markers (OpenAI-compat path).

The stable system prefix (Lever 1) must be marked cacheable for Anthropic-
family models, left as a plain string for others (which cache automatically),
and degrade cleanly to plain text when a provider rejects the block format.
"""

from adapters.openai_compat import OpenAICompatAdapter, _flatten_message_content


def _adapter(model: str) -> OpenAICompatAdapter:
    # Build without network: only _model + _mark_system_cacheable are exercised.
    a = OpenAICompatAdapter.__new__(OpenAICompatAdapter)
    a._model = model
    return a


class TestSystemCacheMarker:
    def test_anthropic_model_gets_cache_control_block(self):
        a = _adapter("claude-sonnet-4-5")
        msgs = [{"role": "system", "content": "STABLE PREFIX"}, {"role": "user", "content": "hi"}]
        out = a._mark_system_cacheable(msgs)
        assert isinstance(out[0]["content"], list)
        block = out[0]["content"][0]
        assert block["type"] == "text"
        assert block["text"] == "STABLE PREFIX"
        assert block["cache_control"] == {"type": "ephemeral"}
        # user message untouched
        assert out[1] == {"role": "user", "content": "hi"}

    def test_only_first_system_marked(self):
        a = _adapter("claude-opus-4-8")
        msgs = [
            {"role": "system", "content": "STABLE"},
            {"role": "system", "content": "TURN CONTEXT"},
            {"role": "user", "content": "hi"},
        ]
        out = a._mark_system_cacheable(msgs)
        assert isinstance(out[0]["content"], list)      # stable prefix cached
        assert out[1]["content"] == "TURN CONTEXT"        # dynamic, not cached

    def test_non_anthropic_model_left_as_plain_string(self):
        # gemini / deepseek / gpt cache the stable prefix automatically — no marker.
        for model in ("gemini-2.5-flash", "deepseek-v4-flash-free", "gpt-5"):
            a = _adapter(model)
            msgs = [{"role": "system", "content": "STABLE"}, {"role": "user", "content": "hi"}]
            out = a._mark_system_cacheable(msgs)
            assert out[0]["content"] == "STABLE", f"{model} should keep a plain string"

    def test_empty_messages_safe(self):
        a = _adapter("claude-sonnet-4-5")
        assert a._mark_system_cacheable([]) == []


class TestFlattenDegrade:
    def test_flattens_block_content_back_to_string(self):
        msgs = [
            {"role": "system", "content": [{"type": "text", "text": "abc", "cache_control": {"type": "ephemeral"}}]},
            {"role": "user", "content": "hi"},
        ]
        out = _flatten_message_content(msgs)
        assert out[0]["content"] == "abc"
        assert "cache_control" not in out[0]
        assert out[1] == {"role": "user", "content": "hi"}

    def test_returns_none_when_nothing_to_flatten(self):
        msgs = [{"role": "system", "content": "plain"}, {"role": "user", "content": "hi"}]
        assert _flatten_message_content(msgs) is None

    def test_non_list_is_safe(self):
        assert _flatten_message_content(None) is None
