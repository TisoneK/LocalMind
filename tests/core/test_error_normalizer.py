"""ADR-20 — error normalizer tests.

The normalizer is pure and deterministic, so the full classification table
is unit-testable without any live provider. These tests lock the canonical
shape, the code/retryable classification, provider parsing, the friendly
messages, and the internal-source override.
"""

import pytest
from core.error_normalizer import (
    AUTH_ERROR,
    CONTEXT_OVERFLOW,
    GENERIC_ERROR,
    MODEL_NOT_FOUND,
    NETWORK_ERROR,
    PAYMENT_REQUIRED,
    RATE_LIMIT,
    SERVER_ERROR,
    SOURCE_INTERNAL,
    SOURCE_PROVIDER,
    TIMEOUT,
    is_canonical_error,
    normalize_error,
)

# The exact payload the user saw in chat during the ADR-19 live smoke.
ZEN_429 = (
    'zen returned 429: {"type":"error","error":{"type":"FreeUsageLimitError",'
    '"message":"Error from provider (Console): Rate limit exceeded. '
    'Please try again later."}}'
)


class TestCanonicalShape:
    def test_zen_429_becomes_canonical(self):
        err = normalize_error(ZEN_429)
        assert err["status"] == "error"
        assert err["source"] == SOURCE_PROVIDER
        assert err["provider"] == "zen"
        assert err["code"] == RATE_LIMIT
        assert err["retryable"] is True
        # Friendly message, not the provider payload.
        assert "usage limit" in err["message"].lower()
        assert "FreeUsageLimitError" not in err["message"]
        # Raw retained for debug.
        assert err["raw"] == ZEN_429

    def test_is_canonical_error(self):
        err = normalize_error(ZEN_429)
        assert is_canonical_error(err) is True
        assert is_canonical_error({"error": "nope"}) is False

    def test_friendly_messages_never_leak_provider_json(self):
        for raw in (
            ZEN_429,
            "ollama returned 500: {\"error\": \"boom\"}",
            "claude returned 400: {\"type\":\"error\",\"error\":{\"message\":\"nope\"}}",
        ):
            err = normalize_error(raw)
            assert "{" not in err["message"]


class TestClassification:
    @pytest.mark.parametrize(
        "raw, expected_code, expected_retryable",
        [
            (ZEN_429, RATE_LIMIT, True),
            ("zen returned 429: too many requests", RATE_LIMIT, True),
            ("rate limit exceeded for this model", RATE_LIMIT, True),
            (
                'openai returned 429: {"error":{"type":"requests","message":"Rate limit reached"}}',
                RATE_LIMIT,
                True,
            ),
            ("zen returned 401: Invalid API key", AUTH_ERROR, False),
            ("zen returned 403: forbidden", AUTH_ERROR, False),
            ("authentication failed: invalid_api_key", AUTH_ERROR, False),
            ("openai returned 402: insufficient balance", PAYMENT_REQUIRED, False),
            ("Ollama returned 404 for model 'llama3'. The model appears to exist but Ollama could not load it. Try restarting Ollama or pulling the model again.", MODEL_NOT_FOUND, False),
            ("model not found: qwen3-235b", MODEL_NOT_FOUND, False),
            ("cerebras returned 400: {\"error\":{\"message\":\"This model's maximum context length is 128K tokens. However, your messages resulted in 130K tokens.\"}}", CONTEXT_OVERFLOW, False),
            ("prompt is too long for the model's context window", CONTEXT_OVERFLOW, False),
            ("zen returned 504: upstream timeout", TIMEOUT, True),
            ("request timed out after 60s", TIMEOUT, True),
            ("zen returned 503: service unavailable", SERVER_ERROR, True),
            ("model is overloaded, try again later", SERVER_ERROR, True),
            ("connection refused by api.zen.ai", NETWORK_ERROR, True),
            ("econnrefused: could not connect", NETWORK_ERROR, True),
        ],
    )
    def test_classification_table(self, raw, expected_code, expected_retryable):
        err = normalize_error(raw)
        assert err["code"] == expected_code
        assert err["retryable"] is expected_retryable
        assert err["source"] == SOURCE_PROVIDER


class TestGenericAndInternal:
    def test_plain_string_defaults_to_internal(self):
        err = normalize_error("iteration limit reached")
        assert err["code"] == GENERIC_ERROR
        assert err["source"] == SOURCE_INTERNAL
        assert err["retryable"] is False
        assert err["provider"] is None
        assert err["message"] == "iteration limit reached"

    def test_exception_input(self):
        err = normalize_error(TimeoutError("zen request timed out"))
        assert err["code"] == TIMEOUT
        assert err["retryable"] is True

    def test_source_hint_internal_skips_provider_classification(self):
        # A network-y keyword inside an upload error must NOT be labeled a
        # provider outage.
        err = normalize_error("File upload failed: connection reset",
                              source_hint=SOURCE_INTERNAL)
        assert err["source"] == SOURCE_INTERNAL
        assert err["code"] == GENERIC_ERROR
        assert err["retryable"] is False
        assert "File upload failed" in err["message"]

    def test_dict_already_canonical_passthrough(self):
        canonical = normalize_error(ZEN_429)
        again = normalize_error(canonical)
        assert again == canonical

    def test_provider_dict_input(self):
        err = normalize_error(
            {
                "provider": "zen",
                "status_code": 429,
                "error": {"type": "FreeUsageLimitError", "message": "Rate limit"},
            }
        )
        assert err["code"] == RATE_LIMIT
        assert err["provider"] == "zen"
        assert err["retryable"] is True

    def test_message_truncated(self):
        err = normalize_error("oops " + "x" * 500)
        assert len(err["message"]) <= 230
        assert err["source"] == SOURCE_INTERNAL


class TestMessages:
    def test_every_classified_code_has_a_friendly_message(self):
        from core.error_normalizer import _MESSAGES

        for raw, code in [
            (ZEN_429, RATE_LIMIT),
            ("zen returned 401: nope", AUTH_ERROR),
            ("openai returned 402: nope", PAYMENT_REQUIRED),
            ("Ollama returned 404 for model 'x'", MODEL_NOT_FOUND),
            ("maximum context length exceeded", CONTEXT_OVERFLOW),
            ("zen returned 504: nope", TIMEOUT),
            ("zen returned 503: nope", SERVER_ERROR),
            ("connection refused", NETWORK_ERROR),
        ]:
            assert code in _MESSAGES, f"missing friendly message for {code}"
            err = normalize_error(raw)
            assert err["message"] == _MESSAGES[code]
