"""Мелкие помощники вызова модели: разбор ответа и JSON, цена провайдера, ленивые LiteLLM и Instructor, маскирование ключа."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import chain as chain_mod
from .errors import ConfigError, LlmKitError

if TYPE_CHECKING:  # pragma: no cover
    from .models import Task


def warn_unknown(warnings: list[str], ref: str) -> None:
    message = f"price unknown for {ref}"
    if message not in warnings:
        warnings.append(message)


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise chain_mod.JsonParseFailed(f"ответ не разобрался как JSON: {exc}") from exc


# Сюда LiteLLM кладёт `usage.cost` из ответа OpenRouter (llms/openrouter/chat/transformation.py).
_LITELLM_COST_HEADER = "llm_provider-x-litellm-response-cost"


def provider_cost(response: Any) -> float | None:
    """Сколько списал провайдер по его ответу: `usage.cost` (OpenRouter отдаёт всегда) или он же у LiteLLM."""
    value = getattr(getattr(response, "usage", None), "cost", None)
    if value is None:
        hidden = getattr(response, "_hidden_params", None)
        headers = hidden.get("additional_headers") if isinstance(hidden, dict) else None
        value = headers.get(_LITELLM_COST_HEADER) if isinstance(headers, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_litellm():
    """Ленивый импорт LiteLLM с заглушённым шумом (раздел 9)."""
    import litellm

    litellm.suppress_debug_info = True
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    return litellm


def load_instructor():
    """Ленивый импорт Instructor; его логгер тоже приглушаем."""
    import instructor

    logging.getLogger("instructor").setLevel(logging.WARNING)
    return instructor


def default_instructor_factory(completion: Callable[..., Any], mode: str) -> Any:
    """Клиент Instructor поверх функции вызова модели."""
    instructor = load_instructor()
    try:
        enum_mode = instructor.Mode[mode]
    except KeyError:
        raise ConfigError(f"неизвестный режим Instructor {mode!r}") from None
    return instructor.from_litellm(completion, mode=enum_mode)


def mask(text: str, secret: str | None) -> str:
    """Убрать ключ провайдера из текста ошибки перед записью куда бы то ни было."""
    return text.replace(secret, "***") if secret else text


def text_of(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise chain_mod.EmptyResponse("провайдер вернул ответ без choices")
    choice = choices[0]
    if getattr(choice, "finish_reason", None) == "content_filter":
        raise chain_mod.ContentFiltered("ответ отклонён контент-фильтром провайдера")
    text = getattr(getattr(choice, "message", None), "content", None) or ""
    if not text.strip():
        raise chain_mod.EmptyResponse("модель вернула пустой ответ")
    return text


def messages_of(task: Task) -> list[dict]:
    if task.messages:
        return [dict(message) for message in task.messages]
    if not task.user:
        raise LlmKitError("задаче нужен user или messages")
    messages = []
    if task.system:
        messages.append({"role": "system", "content": task.system})
    messages.append({"role": "user", "content": task.user})
    return messages
