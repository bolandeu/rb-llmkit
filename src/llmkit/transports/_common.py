"""Общее для своих транспортов (подписки, решения): ошибки и сборка ответа."""

from __future__ import annotations

import re
from typing import Any

# Ошибки классифицируются в chain.py по имени класса — имена менять вместе с таблицей там.


class SubscriptionError(Exception):
    """Сбой провайдера по подписке; `headers` — для Retry-After."""

    def __init__(self, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.headers = headers or {}


class SubscriptionAuthError(SubscriptionError):
    """Вход устарел или отозван: нужен повторный `llm auth login`."""


class SubscriptionRateLimit(SubscriptionError):
    """429 или исчерпан лимит подписки."""


class SubscriptionServerError(SubscriptionError):
    """5xx, обрыв соединения или потока."""


class SubscriptionTimeout(SubscriptionError):
    """Ответа не было дольше таймаута."""


class SubscriptionBadRequest(SubscriptionError):
    """Запрос отвергнут: модель, параметры, схема."""


class SubscriptionContextLength(SubscriptionError):
    """Запрос не влезает в окно модели."""


class SubscriptionEmpty(SubscriptionError):
    """Провайдер ответил, но без текста."""


_PATTERNS: list[tuple[type[SubscriptionError], re.Pattern[str]]] = [
    (SubscriptionRateLimit, re.compile(r"\b429\b|rate.?limit|usage.?limit|limit reached|quota", re.I)),
    (SubscriptionContextLength, re.compile(r"context.?(length|window)|prompt is too long|too many tokens", re.I)),
    (
        SubscriptionAuthError,
        re.compile(r"\b40[13]\b|unauthori|authenticat|not logged in|/login|invalid.?(api.?key|token)|expired", re.I),
    ),
    (SubscriptionServerError, re.compile(r"\b5\d\d\b|overloaded|internal server|unavailable|connection", re.I)),
]


def error_from_text(text: str, headers: dict[str, str] | None = None) -> SubscriptionError:
    """Тип ошибки по тексту, когда статуса нет (итог CLI, событие потока)."""
    for klass, pattern in _PATTERNS:
        if pattern.search(text):
            return klass(text, headers)
    return SubscriptionBadRequest(text, headers)


def error_from_status(status: int, text: str, headers: dict[str, str] | None = None) -> SubscriptionError:
    """Тип ошибки по HTTP-статусу."""
    message = f"HTTP {status}: {text[:500]}"
    if status in (401, 403):
        return SubscriptionAuthError(message, headers)
    if status == 429:
        return SubscriptionRateLimit(message, headers)
    if status >= 500:
        return SubscriptionServerError(message, headers)
    if re.search(r"context.?(length|window)|too long", text, re.I):
        return SubscriptionContextLength(message, headers)
    return SubscriptionBadRequest(message, headers)


def text_of(content: Any) -> str:
    """Текст сообщения в формате OpenAI: строка или список частей."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(str(part.get("text", "")))
        elif isinstance(part, str):
            parts.append(part)
    return "\n".join(parts)


def strip_fences(text: str) -> str:
    """Снять обёртку ```json … ```, если модель её добавила."""
    match = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", text, re.S)
    return match.group(1) if match else text


def model_response(model: str, text: str, prompt_tokens: int, completion_tokens: int, finish_reason: str) -> Any:
    """Ответ в форме LiteLLM: его понимают ядро, Instructor и учёт."""
    import litellm

    return litellm.ModelResponse(
        model=model,
        choices=[{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
        usage=litellm.Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )
