"""Эндпоинт решений OpenRouter (`/api/alpha/decisions`): вероятности вместо текста.

Формат не chat/completions, поэтому мимо LiteLLM — прямой POST на httpx.
Ошибки — классы из `_common`: их по имени классифицирует chain.py.
"""

from __future__ import annotations

from typing import Any

from ._common import SubscriptionEmpty, SubscriptionServerError, SubscriptionTimeout, error_from_status

URL = "https://openrouter.ai/api/alpha/decisions"


async def adecide(
    *,
    model: str,
    state: str,
    questions: dict[str, Any],
    timeout: float,
    api_key: str | None = None,
    url: str = URL,
) -> dict[str, Any]:
    """Один запрос решений; ответ — JSON как есть (`model`, `answers`, `usage`, `id`)."""
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body = {"model": model, "state": state, "questions": questions}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise SubscriptionTimeout(f"решения: нет ответа за {timeout} с") from exc
    except httpx.TransportError as exc:
        raise SubscriptionServerError(f"решения: {type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise error_from_status(response.status_code, response.text, dict(response.headers))
    try:
        data = response.json()
    except ValueError as exc:
        raise SubscriptionEmpty("решения: ответ не JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise SubscriptionEmpty("решения: в ответе нет answers")
    return data
