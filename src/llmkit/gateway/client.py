"""HTTP-клиент шлюза 9router: один POST на вызов, разбор JSON и SSE ответа."""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import GatewayUnavailable
from . import parse
from .parse import Reply

CHAT_PATH = "/chat/completions"
MODELS_PATH = "/models"
PROBE_TIMEOUT = 5.0


def _bearer(api_key: str | None) -> dict[bytes, bytes]:
    """Заголовок авторизации в байтах UTF-8: ключ в тестах — кириллица, а HTTP-заголовок а�SCII не требует."""
    return {b"authorization": f"Bearer {api_key}".encode()} if api_key else {}


class GatewayClient:
    """Вызовы шлюза по адресу и ключу из routing.

    `transport` — подмена сети в тестах (`httpx.MockTransport`). Ключ не попадает
    ни в сообщения об ошибках, ни в журнал.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key
        self._transport = transport

    @property
    def headers(self) -> dict[bytes, bytes]:
        return _bearer(self._api_key)

    async def chat(self, body: dict[str, Any]) -> Reply:
        """Отправить запрос и разобрать ответ; сбой шлюза — `GatewayUnavailable`."""
        url = self.base_url + CHAT_PATH
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self.timeout) as http:
                response = await http.post(url, json=body, headers=self.headers)
        except httpx.TimeoutException as exc:
            raise GatewayUnavailable(self.base_url, "timeout", type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise GatewayUnavailable(self.base_url, "server", f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise GatewayUnavailable(self.base_url, "server", f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            return parse.reply(response)
        except ValueError as exc:
            raise GatewayUnavailable(self.base_url, "server", str(exc)) from exc


def probe(
    base_url: str,
    *,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> str | None:
    """Проверка доступности шлюза для `llm doctor`: None — отвечает, иначе текст ошибки."""
    url = base_url.rstrip("/") + MODELS_PATH
    headers = _bearer(api_key)
    try:
        with httpx.Client(transport=transport, timeout=timeout) as http:
            http.get(url, headers=headers).raise_for_status()
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None
