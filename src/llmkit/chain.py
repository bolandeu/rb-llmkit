"""Цепочки моделей, классификация ошибок и политика ретраев (раздел 6)."""

from __future__ import annotations

from typing import Any

from .config import RetryConfig

# Классификация по имени класса исключения, а не по самому классу: так модуль
# не тянет litellm на импорте. MRO обходится от частного к общему, поэтому
# ContextWindowExceededError не схлопывается в bad_request.
ERROR_TYPE_BY_EXCEPTION = {
    "Timeout": "timeout",
    "APITimeoutError": "timeout",
    "RateLimitError": "rate_limit",
    "ServiceUnavailableError": "server",
    "InternalServerError": "server",
    "APIConnectionError": "server",
    "InstructorRetryException": "invalid_output",
    "EmptyResponse": "invalid_output",
    "JsonParseFailed": "invalid_output",
    "ContentFiltered": "refusal",
    "ContentPolicyViolationError": "refusal",
    "ContextWindowExceededError": "context_length",
    "AuthenticationError": "auth",
    "PermissionDeniedError": "auth",
    "KeyMissing": "auth",
    "BadRequestError": "bad_request",
    "NotFoundError": "bad_request",
    "APIStatusError": "bad_request",
    "APIError": "bad_request",
    # Провайдеры по подписке (transports/_common.py).
    "SubscriptionAuthError": "auth",
    "SubscriptionRateLimit": "rate_limit",
    "SubscriptionServerError": "server",
    "SubscriptionTimeout": "timeout",
    "SubscriptionContextLength": "context_length",
    "SubscriptionEmpty": "invalid_output",
    "SubscriptionBadRequest": "bad_request",
}

# Ошибки, после которых повтор идёт на той же модели.
RETRY_SAME_MODEL = ("timeout", "rate_limit", "server")
# Ошибки с паузой перед повтором.
BACKOFF_TYPES = ("rate_limit", "server")
MAX_BACKOFF = 30.0


class AnswerRejected(Exception):
    """Ответ провайдера пришёл, но не годится; `billed` — его токены и цена (ядро заполняет)."""

    billed: Any = None


class EmptyResponse(AnswerRejected):
    """Модель вернула пустой ответ — считаем невалидным выводом."""


class JsonParseFailed(AnswerRejected):
    """Ответ по готовой JSON Schema не разобрался — повторяем на той же модели."""


class ContentFiltered(AnswerRejected):
    """Провайдер отказал по контент-фильтру (finish_reason=content_filter)."""


def classify(exc: BaseException) -> str | None:
    """Тип ошибки по таблице раздела 6 или None, если исключение чужое.

    None означает «это не сбой провайдера»: ядро такую ошибку не глушит
    фолбэком, а пробрасывает — иначе наш собственный баг (TypeError и
    подобные) выглядел бы как bad_request у модели.
    """
    found = None
    for klass in type(exc).__mro__:
        found = ERROR_TYPE_BY_EXCEPTION.get(klass.__name__)
        if found:
            break
    if found == "invalid_output" and type(exc).__name__ == "InstructorRetryException":
        # Instructor заворачивает ошибку провайдера в свою (`raise … from`),
        # поэтому смотрим на причину: 429 сквозь Instructor остаётся 429.
        cause = exc.__cause__
        for _ in range(5):
            if cause is None:
                break
            deeper = classify(cause)
            if deeper is not None and deeper != "invalid_output":
                return deeper
            cause = cause.__cause__
    return found


def retries_for(error_type: str, retry: RetryConfig, exc: BaseException | None = None) -> int:
    """Сколько повторов на той же модели допускает политика."""
    if error_type in RETRY_SAME_MODEL:
        return int(getattr(retry, error_type))
    # invalid_output повторяем только на разборе готовой JSON Schema:
    # у Instructor свои max_retries внутри вызова, пустой ответ — сразу дальше.
    if error_type == "invalid_output" and isinstance(exc, JsonParseFailed):
        return retry.invalid_output
    return 0


def retry_after(exc: BaseException) -> float | None:
    """Значение заголовка Retry-After, если провайдер его прислал."""
    for holder in (getattr(exc, "response", None), exc):
        headers = getattr(holder, "headers", None) or getattr(holder, "litellm_response_headers", None)
        if not headers:
            continue
        value = None
        for name in ("retry-after", "Retry-After"):
            try:
                value = headers.get(name)
            except AttributeError:
                value = None
            if value:
                break
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def backoff_seconds(error_type: str, attempt: int, exc: BaseException | None = None) -> float:
    """Пауза перед повтором: Retry-After, иначе 2·2ⁿ секунд, максимум 30."""
    if error_type not in BACKOFF_TYPES:
        return 0.0
    if exc is not None:
        header = retry_after(exc)
        if header is not None:
            return min(max(header, 0.0), MAX_BACKOFF)
    return min(2.0 * (2**attempt), MAX_BACKOFF)
