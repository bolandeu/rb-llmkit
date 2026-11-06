"""SSE шлюза: склеить порции потока в один ответ формы chat.completion."""

from __future__ import annotations

from typing import Any

from .parse import chunks


def completion(text: str) -> dict[str, Any]:
    """Порции `delta.content` складываются в текст; `model`, `provider` и `usage` — из последней порции.

    Шлюз отвечает так и на непоточный запрос: одна JSON-строка и `data: [DONE]`.
    """
    body: dict[str, Any] = {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": None}]}
    message: dict[str, Any] = body["choices"][0]["message"]
    choice: dict[str, Any] = body["choices"][0]
    parts: list[str] = []
    for chunk in chunks(text):
        for key in ("model", "provider", "usage"):
            if chunk.get(key) is not None:
                body[key] = chunk[key]
        for item in chunk.get("choices") or []:
            # Непоточный ответ приходит одной порцией в форме message, а не delta.
            content = (item.get("delta") or {}).get("content") or (item.get("message") or {}).get("content")
            if isinstance(content, str):
                parts.append(content)
            if item.get("finish_reason"):
                choice["finish_reason"] = item["finish_reason"]
    message["content"] = "".join(parts)
    return body
