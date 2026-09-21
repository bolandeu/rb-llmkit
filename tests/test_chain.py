"""Классификация ошибок и политика ретраев (раздел 6 спеки)."""

from __future__ import annotations

import conftest as fakes
import pytest

from llmkit import chain
from llmkit.config import RetryConfig
from llmkit.errors import KeyMissing

CASES = [
    (fakes.Timeout("x"), "timeout"),
    (fakes.RateLimitError("x"), "rate_limit"),
    (fakes.ServiceUnavailableError("x"), "server"),
    (fakes.InternalServerError("x"), "server"),
    (fakes.APIConnectionError("x"), "server"),
    (fakes.InstructorRetryException("x"), "invalid_output"),
    (chain.EmptyResponse("x"), "invalid_output"),
    (chain.JsonParseFailed("x"), "invalid_output"),
    (fakes.ContentPolicyViolationError("x"), "refusal"),
    (chain.ContentFiltered("x"), "refusal"),
    (fakes.ContextWindowExceededError("x"), "context_length"),
    (fakes.AuthenticationError("x"), "auth"),
    (KeyMissing("a", "TEST_A_KEY"), "auth"),
    (fakes.BadRequestError("x"), "bad_request"),
    (ValueError("что-то своё"), "bad_request"),
]


@pytest.mark.parametrize(("exc", "expected"), CASES)
def test_classify(exc, expected):
    assert chain.classify(exc) == expected


def test_litellm_exception_names_are_covered():
    """Имена реальных классов LiteLLM совпадают с картой классификации."""
    import litellm

    expected = {
        "Timeout": "timeout",
        "RateLimitError": "rate_limit",
        "ServiceUnavailableError": "server",
        "InternalServerError": "server",
        "APIConnectionError": "server",
        "ContentPolicyViolationError": "refusal",
        "ContextWindowExceededError": "context_length",
        "AuthenticationError": "auth",
        "BadRequestError": "bad_request",
    }
    for name, error_type in expected.items():
        klass = getattr(litellm, name)
        assert chain.classify(klass.__new__(klass)) == error_type


def test_retries_only_where_policy_allows():
    retry = RetryConfig(timeout=1, rate_limit=2, server=3, invalid_output=2)
    assert chain.retries_for("timeout", retry) == 1
    assert chain.retries_for("rate_limit", retry) == 2
    assert chain.retries_for("server", retry) == 3
    assert chain.retries_for("refusal", retry) == 0
    # Instructor повторяет сам, пустой ответ — сразу следующая модель…
    assert chain.retries_for("invalid_output", retry) == 0
    # …а разбор готовой JSON Schema повторяем на той же модели.
    assert chain.retries_for("invalid_output", retry, chain.JsonParseFailed("x")) == 2


def test_backoff_growth_and_cap():
    assert chain.backoff_seconds("timeout", 0) == 0.0
    assert chain.backoff_seconds("rate_limit", 0) == 2.0
    assert chain.backoff_seconds("rate_limit", 1) == 4.0
    assert chain.backoff_seconds("server", 10) == chain.MAX_BACKOFF


def test_backoff_uses_retry_after_header():
    exc = fakes.RateLimitError("x")
    exc.response = type("R", (), {"headers": {"retry-after": "7"}})()
    assert chain.backoff_seconds("rate_limit", 0, exc) == 7.0
