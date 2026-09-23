"""Модели подписки ChatGPT: Responses API бэкенда Codex.

Порт `codexFetch` из iva-agent (`agent/provider.ts`): свежий Bearer и
ChatGPT-Account-Id перед каждым запросом, `store: false` (бэкенд ничего не
хранит — история едет целиком), поток SSE, один повтор после принудительного
обновления токена при 401. Температуру и лимит токенов бэкенд подписки
отвергает — они не отправляются.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import chatgpt_auth
from ._common import (
    SubscriptionAuthError,
    SubscriptionEmpty,
    SubscriptionError,
    SubscriptionServerError,
    SubscriptionTimeout,
    error_from_status,
    error_from_text,
    model_response,
    text_of,
)

BASE_URL = "https://chatgpt.com/backend-api/codex"
# Поле instructions обязательно; без системного сообщения шлём нейтральное.
DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


def _client_factory(timeout: float | None) -> Any:
    """Точка подмены в тестах: httpx.AsyncClient с MockTransport."""
    import httpx

    return httpx.AsyncClient(timeout=httpx.Timeout(timeout or 120.0, connect=15.0))


def _content(role: str, content: Any) -> list[dict[str, Any]]:
    """Части сообщения OpenAI → части Responses API."""
    text_type = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, str) or content is None:
        return [{"type": text_type, "text": content or ""}]
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append({"type": text_type, "text": part})
        elif part.get("type") == "text":
            parts.append({"type": text_type, "text": str(part.get("text", ""))})
        elif part.get("type") == "image_url" and role != "assistant":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            parts.append({"type": "input_image", "image_url": url})
    return parts


def build_body(model: str, messages: list[dict[str, Any]], response_format: dict[str, Any] | None) -> dict[str, Any]:
    """Тело запроса /responses из сообщений в формате chat completions."""
    instructions = []
    items = []
    for message in messages:
        role = message.get("role")
        if role in ("system", "developer"):
            instructions.append(text_of(message.get("content")))
            continue
        if role not in ("user", "assistant"):
            # Ответы инструментов и прочее — как текст пользователя: инструментов у нас нет.
            role, content = "user", text_of(message.get("content"))
        else:
            content = message.get("content")
        items.append({"type": "message", "role": role, "content": _content(role, content)})
    body: dict[str, Any] = {
        "model": model,
        "instructions": "\n\n".join(part for part in instructions if part) or DEFAULT_INSTRUCTIONS,
        "input": items,
        "store": False,
        "stream": True,
    }
    if response_format:
        kind = response_format.get("type")
        if kind == "json_schema":
            spec = response_format.get("json_schema") or {}
            # strict выключен всегда: строгий режим делает все поля обязательными,
            # и модель забивает необязательные мусором (урок iva-agent).
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": spec.get("name") or "answer",
                    "schema": spec.get("schema") or {},
                    "strict": False,
                }
            }
        elif kind == "json_object":
            body["text"] = {"format": {"type": "json_object"}}
    return body


def _stream_error(event: dict[str, Any]) -> SubscriptionError:
    error = event.get("error") or (event.get("response") or {}).get("error") or event
    if isinstance(error, dict):
        text = " ".join(str(error.get(key) or "") for key in ("code", "type", "message")).strip()
    else:
        text = str(error)
    return error_from_text(text or json.dumps(event)[:500])


def parse_events(lines: list[str]) -> tuple[str, int, int, str]:
    """SSE → (текст, токены запроса, токены ответа, finish_reason)."""
    deltas: list[str] = []
    final: dict[str, Any] | None = None
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "response.output_text.delta":
            deltas.append(str(event.get("delta") or ""))
        elif kind in ("response.completed", "response.incomplete"):
            final = event.get("response") or {}
        elif kind in ("response.failed", "error"):
            raise _stream_error(event)
    if final is None:
        raise SubscriptionServerError("поток ответа оборвался до response.completed")
    text = "".join(deltas)
    if not text:
        # Дельт не было — текст может лежать только в итоговом output.
        for item in final.get("output") or []:
            if item.get("type") == "message":
                text += "".join(
                    part.get("text", "") for part in item.get("content") or [] if part.get("type") == "output_text"
                )
    usage = final.get("usage") or {}
    finish = "stop"
    if final.get("status") == "incomplete":
        reason = (final.get("incomplete_details") or {}).get("reason")
        finish = "content_filter" if reason == "content_filter" else "length"
    return text, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), finish


def _headers(auth: chatgpt_auth.Auth) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {auth.access_token}",
        "originator": chatgpt_auth.ORIGINATOR,
        "User-Agent": f"{chatgpt_auth.ORIGINATOR}/{chatgpt_auth.CLIENT_VERSION}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    if auth.account_id:
        headers["ChatGPT-Account-Id"] = auth.account_id
    return headers


def _is_token_rejected(status: int, text: str) -> bool:
    return status == 401 and (not text.strip() or "token_expired" in text or "invalid_token" in text)


async def _post(client: Any, url: str, body: dict[str, Any], auth: chatgpt_auth.Auth) -> tuple[int, str, list[str], dict]:
    async with client.stream("POST", url, json=body, headers=_headers(auth)) as response:
        if response.status_code != 200:
            text = (await response.aread()).decode("utf-8", "replace")
            return response.status_code, text, [], dict(response.headers)
        lines = [line async for line in response.aiter_lines()]
        return 200, "", lines, dict(response.headers)


async def acompletion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float | None = None,
    response_format: dict[str, Any] | None = None,
    auth_file: str | None = None,
    provider: str = "chatgpt",
    api_base: str | None = None,
    **_ignored: Any,
) -> Any:
    """Вызов модели подписки; сигнатура как у `litellm.acompletion`."""
    import httpx

    store = chatgpt_auth.store_for(Path(auth_file) if auth_file else chatgpt_auth.default_path(), provider)
    body = build_body(model, messages, response_format)
    url = f"{(api_base or BASE_URL).rstrip('/')}/responses"
    try:
        async with _client_factory(timeout) as client:
            auth = await store.access(client)
            status, text, lines, headers = await _post(client, url, body, auth)
            if _is_token_rejected(status, text):
                auth = await store.force_refresh(client, auth.access_token)
                status, text, lines, headers = await _post(client, url, body, auth)
                if status == 401:
                    raise SubscriptionAuthError(
                        f"токен подписки отвергнут; {chatgpt_auth.login_hint(provider)}", headers
                    )
    except httpx.TimeoutException as exc:
        raise SubscriptionTimeout(f"нет ответа за {timeout} с") from exc
    except httpx.TransportError as exc:
        raise SubscriptionServerError(f"сеть: {exc}") from exc
    if status != 200:
        raise error_from_status(status, text, headers)
    content, prompt_tokens, completion_tokens, finish = parse_events(lines)
    if not content.strip() and finish == "stop":
        raise SubscriptionEmpty("модель вернула пустой ответ")
    return model_response(model, content, prompt_tokens, completion_tokens, finish)
