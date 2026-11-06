"""Ответ шлюза: один JSON-объект или поток SSE превращаются в одно и то же."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

SSE_CONTENT_TYPE = "text/event-stream"


@dataclass(frozen=True)
class Reply:
    """Разобранный ответ шлюза: текст, кто ответил и сколько это стоило."""

    text: str
    served_model: str = ""
    provider: str | None = None
    cost_usd: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None


def reply(response: httpx.Response) -> Reply:
    """Ответ шлюза по content-type: непоточный запрос тоже приходит как text/event-stream."""
    content_type = response.headers.get("content-type", "")
    if SSE_CONTENT_TYPE in content_type:
        from . import sse

        return reply_of(sse.completion(response.text))
    try:
        return reply_of(response.json())
    except ValueError as exc:
        raise ValueError(f"ответ шлюза не разобрался как JSON: {exc}") from exc


def reply_of(body: Any) -> Reply:
    """Форма chat.completion (или её SSE-сборка) → `Reply`. Нет provider или cost 0 — это норма."""
    if not isinstance(body, dict):
        raise ValueError("ответ шлюза — не JSON-объект")
    choice = (body.get("choices") or [{}])[0] or {}
    message = choice.get("message") or {}
    usage = body.get("usage") or {}
    content = message.get("content")
    return Reply(
        text=content if isinstance(content, str) else "",
        served_model=str(body.get("model") or ""),
        provider=body.get("provider"),
        cost_usd=_cost(usage.get("cost")),
        prompt_tokens=_count(usage.get("prompt_tokens")),
        completion_tokens=_count(usage.get("completion_tokens")),
        finish_reason=choice.get("finish_reason"),
    )


def _count(value: Any) -> int:
    """Токены из ответа: не число — считаем нулём, ответ из-за этого не теряется."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cost(value: Any) -> float | None:
    """`usage.cost` шлюза: нет поля — цены нет (не ошибка), 0 — ответил подписочный провайдер."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def chunks(text: str) -> list[dict]:
    """Строки SSE (`data: {...}`) без `data: [DONE]` и без мусора."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            found.append(json.loads(payload))
        except ValueError:
            continue
    return found
