"""Мелкие помощники вызова шлюза: сообщения задачи и JSON."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .errors import LlmKitError

if TYPE_CHECKING:  # pragma: no cover
    from .models import Task


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(f"ответ не разобрался как JSON: {exc}") from exc


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
