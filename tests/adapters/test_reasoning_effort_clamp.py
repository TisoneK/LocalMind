"""Regression tests: reasoning_effort must be valid for the target model, and
the reject-retry backstop must be language-agnostic.

Root cause (live-diagnosed against bankofai/glm-5.3-flash): LocalMind forwarded
``reasoning_effort: "none"`` to GLM-5.3, which ALWAYS thinks and rejects any
"off" level with HTTP 400 (code 400001, body in Chinese: "该模型始终思考，不支持
关闭思考；请使用 low、high 或 max"). Two bugs:

  A. `_add_provider_params` passed the configured effort unvalidated, even
     though 5.3 only accepts {max, high, low}. Fix: clamp to the model's set —
     none/minimal/medium → low (the least thinking 5.3 allows), xhigh → high.
  B. The 400-retry that drops reasoning_effort gated on the English substrings
     "reasoning"/"reasoning_effort" being in the body — bankofai's reject body
     is Chinese, so the retry never fired and the turn hard-failed as
     "Not retryable". Fix: drop the param on any otherwise-unhandled 400/422
     when it is present (it is an optional, additive bounding hint).

Both fixes are model/provider-agnostic (keyed on the parsed GLM version, and on
the param's presence — never on a provider name or a localized message).
"""

from __future__ import annotations

import asyncio

import core.config as config_mod
from adapters.openai_compat import OpenAICompatAdapter

# ── A. Clamp: pure static-method behavior ───────────────────────────────────


class TestClampReasoningEffort:
    def test_glm53_maps_off_levels_to_low(self):
        for e in ("none", "minimal", "medium"):
            assert OpenAICompatAdapter._clamp_reasoning_effort(e, "glm-5.3-flash") == "low", e

    def test_glm53_maps_xhigh_to_high(self):
        assert OpenAICompatAdapter._clamp_reasoning_effort("xhigh", "glm-5.3-flash") == "high"

    def test_glm53_keeps_valid_levels(self):
        for e in ("low", "high", "max"):
            assert OpenAICompatAdapter._clamp_reasoning_effort(e, "glm-5.3-flash") == e, e

    def test_glm52_keeps_full_set(self):
        # 5.2 supports the whole ladder incl. none/minimal/medium/xhigh.
        for e in ("none", "minimal", "medium", "xhigh", "low", "high", "max"):
            assert OpenAICompatAdapter._clamp_reasoning_effort(e, "glm-5.2") == e, e

    def test_non_glm_passthrough(self):
        # Unknown/non-GLM ids pass through unchanged (retry backstop covers them).
        assert OpenAICompatAdapter._clamp_reasoning_effort("none", "deepseek-v4") == "none"

    def test_empty_is_omitted(self):
        assert OpenAICompatAdapter._clamp_reasoning_effort("", "glm-5.3-flash") is None


# ── A. Clamp: applied in _add_provider_params (the exact user scenario) ──────


class TestAddProviderParamsClamps:
    def test_bankofai_glm53_none_becomes_low(self, monkeypatch):
        """The reported bug: bankofai + glm-5.3-flash + effort=none must NOT send
        the invalid 'none' — it is clamped to 'low' so the request is valid."""
        monkeypatch.setenv("BANKOFAI_API_KEY", "sk-test")
        monkeypatch.setattr(config_mod.settings, "localmind_reasoning_effort", "none")
        adapter = OpenAICompatAdapter(provider="bankofai", model_override="glm-5.3-flash")
        payload = adapter._add_provider_params({})
        assert payload.get("reasoning_effort") == "low", (
            f"none must clamp to low for GLM-5.3, got {payload.get('reasoning_effort')!r}"
        )

    def test_glm52_none_preserved(self, monkeypatch):
        monkeypatch.setenv("BANKOFAI_API_KEY", "sk-test")
        monkeypatch.setattr(config_mod.settings, "localmind_reasoning_effort", "none")
        adapter = OpenAICompatAdapter(provider="bankofai", model_override="glm-5.2")
        payload = adapter._add_provider_params({})
        assert payload.get("reasoning_effort") == "none"


# ── B. Retry backstop: language-agnostic drop of reasoning_effort ────────────


class _FakeResponse:
    def __init__(self, status_code: int, body: bytes = b""):
        self.status_code = status_code
        self._body = body
        self.headers = {}
        self.closed = False

    async def aread(self) -> bytes:
        return self._body

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    """Records each request payload, returns queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.sent_payloads = []

    def build_request(self, method, url, json=None, headers=None, timeout=None):
        self.sent_payloads.append(json)
        return {"json": json}

    async def send(self, request, stream=True):
        return self._responses.pop(0)


def test_retry_drops_reasoning_effort_on_chinese_400(monkeypatch):
    """A 400 whose body is Chinese (no English 'reasoning' token) must still
    trigger the drop-and-retry, because reasoning_effort is present in the
    payload. Before the fix this returned as a non-retryable 400."""
    monkeypatch.setenv("BANKOFAI_API_KEY", "sk-test")
    adapter = OpenAICompatAdapter(provider="bankofai", model_override="glm-5.3-flash")

    chinese_400 = (
        '{"error":{"message":"The request is invalid: '
        "该模型始终思考，不支持关闭思考；请使用 low、high 或 max。"
        '","type":"invalid_request_error","code":"400001"}}'
    ).encode("utf-8")
    fake = _FakeClient([_FakeResponse(400, chinese_400), _FakeResponse(200, b"")])
    adapter._client = fake

    resp = asyncio.run(
        adapter._send_streaming_with_retry(
            "https://api.bankofai.io/v1/chat/completions",
            {"model": "glm-5.3-flash", "reasoning_effort": "none", "messages": []},
        )
    )
    assert resp.status_code == 200, "the retry (without reasoning_effort) must succeed"
    # First attempt carried reasoning_effort; the retried attempt dropped it.
    assert "reasoning_effort" in fake.sent_payloads[0]
    assert "reasoning_effort" not in fake.sent_payloads[1], (
        "reasoning_effort must be dropped on the retry"
    )
