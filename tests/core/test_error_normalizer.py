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
    is_permanent_quota_429,
    is_terminal_pre_generation_error,
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


class TestADR32TerminalProviderErrors:
    @pytest.mark.parametrize(
        "raw",
        [
            'zen returned 401: {"error":{"type":"invalid_api_key","message":"bad key"}}',
            'zen returned 402: {"error":{"type":"billing_error","message":"top up"}}',
            'zen returned 403: {"error":{"type":"forbidden","message":"denied"}}',
        ],
    )
    def test_auth_payment_permission_errors_are_terminal(self, raw):
        assert is_terminal_pre_generation_error(raw) is True

    def test_exhausted_quota_429_is_terminal(self):
        assert is_permanent_quota_429(ZEN_429) is True
        assert is_terminal_pre_generation_error(ZEN_429) is True

    def test_per_minute_429_remains_retryable(self):
        raw = 'zen returned 429: {"error":{"type":"requests","message":"per minute"}}'
        assert is_permanent_quota_429(raw) is False
        assert is_terminal_pre_generation_error(raw) is False


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

    @pytest.mark.parametrize(
        "raw",
        [
            ZEN_429,
            "zen returned 401: nope",
            "openai returned 402: nope",
            "Ollama returned 404 for model 'x'",
            "maximum context length exceeded",
            "zen returned 504: nope",
            "zen returned 503: nope",
            "connection refused",
        ],
    )
    def test_every_code_round_trips_through_canonical(self, raw):
        # Review fix (Session 168): re-normalizing ANY canonical object must
        # pass through untouched — friendly messages don't contain their own
        # keywords, so re-classification would flip the code to generic.
        canonical = normalize_error(raw)
        assert canonical["code"] != GENERIC_ERROR
        again = normalize_error(canonical)
        assert again == canonical

    def test_exception_raw_is_json_serializable(self):
        # Review fix (Session 168): `raw` must survive json.dumps if the
        # canonical object ever crosses the SSE wire directly.
        import json

        err = normalize_error(TimeoutError("zen request timed out"))
        dumped = json.dumps(err)
        assert isinstance(dumped, str)
        assert "timed out" in dumped

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


class TestProviderEnvelopes:
    """ADR-21 — ANY provider's error JSON envelope normalizes the same way.

    The classifier is provider-agnostic: the provider's structured
    error-type/code token (from the JSON envelope) is consulted before the
    HTTP status and prose keywords, so OpenAI / Anthropic / Zen / Ollama /
    Azure / gateway shapes all land on the canonical codes.
    """

    def test_openai_insufficient_quota(self):
        err = normalize_error(
            'openai returned 429: {"error":{"type":"insufficient_quota",'
            '"message":"You exceeded your current quota, please check your '
            'plan and billing details."}}'
        )
        assert err["code"] == RATE_LIMIT
        assert err["retryable"] is True
        assert err["provider"] == "openai"

    def test_openai_invalid_api_key_type(self):
        err = normalize_error(
            'openai returned 401: {"error":{"type":"invalid_api_key",'
            '"message":"Incorrect API key provided: sk-***"}}'
        )
        assert err["code"] == AUTH_ERROR
        assert err["retryable"] is False

    def test_openai_context_length_exceeded_type(self):
        err = normalize_error(
            'openai returned 400: {"error":{"type":"context_length_exceeded",'
            '"message":"This model\'s maximum context length is 128000 tokens. '
            'However, you requested 130000 tokens."}}'
        )
        assert err["code"] == CONTEXT_OVERFLOW

    def test_anthropic_rate_limit_error(self):
        err = normalize_error(
            'anthropic returned 429: {"type":"error","error":{'
            '"type":"rate_limit_error","message":"Your organization has '
            'reached its rate limit."}}'
        )
        assert err["code"] == RATE_LIMIT
        assert err["retryable"] is True
        assert err["provider"] == "anthropic"

    def test_anthropic_overloaded_error(self):
        err = normalize_error(
            'anthropic returned 529: {"type":"error","error":{'
            '"type":"overloaded_error","message":"Overloaded"}}'
        )
        assert err["code"] == SERVER_ERROR
        assert err["retryable"] is True

    def test_anthropic_not_found_error(self):
        err = normalize_error(
            'anthropic returned 404: {"type":"error","error":{'
            '"type":"not_found_error","message":"model: '
            'claude-3-5-sonnet-20241022"}}'
        )
        assert err["code"] == MODEL_NOT_FOUND

    def test_anthropic_request_too_large(self):
        err = normalize_error(
            'anthropic returned 400: {"type":"error","error":{'
            '"type":"request_too_large","message":"Your request is too '
            'large for the model."}}'
        )
        assert err["code"] == CONTEXT_OVERFLOW

    def test_ollama_error_string_envelope(self):
        err = normalize_error(
            'ollama returned 404: {"error":"model \'llama3\' not found"}'
        )
        assert err["code"] == MODEL_NOT_FOUND
        assert err["provider"] == "ollama"

    def test_ollama_connection_refused_envelope(self):
        # Connection failures normally surface as adapter exceptions (no HTTP
        # status), so a body with an unmapped status must fall through to
        # the network keywords.
        err = normalize_error('ollama returned 400: {"error":"connection refused"}')
        assert err["code"] == NETWORK_ERROR

    def test_azure_numeric_code_envelope(self):
        err = normalize_error(
            'azure returned 429: {"error":{"code":"429","message":"Rate '
            'limit is exceeded. Try again in N seconds."}}'
        )
        assert err["code"] == RATE_LIMIT
        assert err["retryable"] is True
        assert err["provider"] == "azure"

    def test_azure_dict_numeric_code(self):
        err = normalize_error(
            {
                "provider": "azure",
                "error": {"code": "429", "message": "Rate limit is exceeded."},
            }
        )
        assert err["code"] == RATE_LIMIT
        assert err["retryable"] is True

    def test_double_nested_error_envelope(self):
        err = normalize_error(
            'gateway returned 429: {"error":{"error":{"type":'
            '"rate_limit_error","message":"nested"}}}'
        )
        assert err["code"] == RATE_LIMIT

    def test_errors_plural_list_envelope(self):
        err = normalize_error(
            'proxy returned 401: {"errors":[{"type":"authentication_error",'
            '"message":"bad key"}]}'
        )
        assert err["code"] == AUTH_ERROR

    def test_unknown_type_token_falls_back_to_status(self):
        err = normalize_error(
            'openai returned 429: {"error":{"type":"brand_new_type",'
            '"message":"something"}}'
        )
        assert err["code"] == RATE_LIMIT

    def test_unknown_type_token_falls_back_to_keywords(self):
        err = normalize_error(
            'openai returned 400: {"error":{"type":"brand_new_type",'
            '"message":"This model\'s maximum context length is 128K '
            'tokens"}}'
        )
        assert err["code"] == CONTEXT_OVERFLOW

    def test_unknown_type_generic_stays_provider_shaped(self):
        # ADR-21: an error from a provider envelope keeps source=model_provider
        # even when nothing classifies — the UI says "the model provider".
        err = normalize_error(
            'openai returned 400: {"error":{"type":"weird_error",'
            '"message":"something odd happened"}}'
        )
        assert err["code"] == GENERIC_ERROR
        assert err["source"] == SOURCE_PROVIDER
        assert err["provider"] == "openai"
        assert "weird_error" in err["message"]

    def test_plain_dict_without_provider_stays_internal(self):
        err = normalize_error({"message": "iteration limit reached"})
        assert err["code"] == GENERIC_ERROR
        assert err["source"] == SOURCE_INTERNAL

    def test_type_token_beats_conflicting_status(self):
        # The provider's named error type is explicit semantics — it wins
        # even over a contradictory HTTP status.
        err = normalize_error(
            'anthropic returned 500: {"type":"error","error":{'
            '"type":"authentication_error","message":"bad key"}}'
        )
        assert err["code"] == AUTH_ERROR

    def test_long_json_body_survives_adapter_truncation(self):
        # Adapters now truncate at 1000 chars (was 200) so a long JSON
        # envelope still parses instead of being cut mid-JSON.
        body = (
            '{"error":{"type":"context_length_exceeded","message":"'
            + "x" * 300
            + '"}}'
        )
        err = normalize_error(f"openai returned 400: {body}")
        assert err["code"] == CONTEXT_OVERFLOW

    def test_openai_specific_code_in_generic_type_bucket(self):
        # OpenAI puts the specific subtype in error.code while error.type is
        # a generic bucket ("invalid_request_error") — the code must win
        # when the type misses the catalog.
        err = normalize_error(
            'openai returned 400: {"error":{"type":"invalid_request_error",'
            '"code":"context_length_exceeded","message":"We couldn\'t '
            'process this request"}}'
        )
        assert err["code"] == CONTEXT_OVERFLOW

    def test_plain_body_529_overload(self):
        # Anthropic's 529 overload status classifies even without a JSON
        # envelope (review fix, Session 169).
        err = normalize_error("anthropic returned 529: overloaded upstream")
        assert err["code"] == SERVER_ERROR
        assert err["retryable"] is True
        assert err["provider"] == "anthropic"

    def test_raw_capped_for_long_strings(self):
        err = normalize_error("plain provider error " + "z" * 3000)
        assert len(err["raw"]) <= 2000
        assert err["message"] != ""
